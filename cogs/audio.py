import asyncio
import audioop
import os
import random
import tempfile
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import asyncpg
import discord
import gtts
import yt_dlp
from discord import app_commands
from discord.ext import commands
from gtts import gTTS

import bot_info


class MixerAudioSource(discord.AudioSource):
    def __init__(self, main_source: Optional[discord.AudioSource] = None):
        self.main_source = main_source
        self.tts_source: Optional[discord.AudioSource] = None
        self.after_main = None
        self.after_tts = None
        self.FRAME_SIZE = 3840
        self.bot = None

    def read(self) -> bytes:
        main_data = b""
        if self.main_source:
            try:
                main_data = self.main_source.read()
            except Exception:
                main_data = b""

            if not main_data:
                self.main_source = None
                if self.after_main:
                    callback = self.after_main
                    self.after_main = None
                    if self.bot:
                        self.bot.loop.call_soon_threadsafe(callback)
                    else:
                        callback()

        tts_data = b""
        if self.tts_source:
            try:
                tts_data = self.tts_source.read()
            except Exception:
                tts_data = b""

            if not tts_data:
                self.tts_source = None
                if self.after_tts:
                    self.after_tts(None)
                    self.after_tts = None

        if not main_data and not tts_data:
            return b""

        if len(main_data) < self.FRAME_SIZE:
            main_data += b"\x00" * (self.FRAME_SIZE - len(main_data))
        elif len(main_data) > self.FRAME_SIZE:
            main_data = main_data[: self.FRAME_SIZE]

        if len(tts_data) < self.FRAME_SIZE:
            tts_data += b"\x00" * (self.FRAME_SIZE - len(tts_data))
        elif len(tts_data) > self.FRAME_SIZE:
            tts_data = tts_data[: self.FRAME_SIZE]

        try:
            return audioop.add(main_data, tts_data, 2)
        except Exception:
            return main_data

    @property
    def volume(self):
        if self.main_source and hasattr(self.main_source, "volume"):
            return self.main_source.volume
        return 1.0

    @volume.setter
    def volume(self, value):
        if self.main_source and hasattr(self.main_source, "volume"):
            self.main_source.volume = value

    def is_opus(self) -> bool:
        return False

    def cleanup(self):
        if self.main_source:
            self.main_source.cleanup()
        if self.tts_source:
            self.tts_source.cleanup()


class VoicePaginator(discord.ui.View):
    def __init__(self, pages: list[discord.Embed], timeout: float = 60.0):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.current_page = 0

        self.update_buttons()

    def update_buttons(self):
        self.prev_page.disabled = self.current_page == 0
        self.next_page.disabled = self.current_page == len(self.pages) - 1

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.blurple)
    async def prev_page(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            await interaction.response.edit_message(
                embed=self.pages[self.current_page], view=self
            )

    @discord.ui.button(label="Next", style=discord.ButtonStyle.blurple)
    async def next_page(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
            self.update_buttons()
            await interaction.response.edit_message(
                embed=self.pages[self.current_page], view=self
            )

    async def on_timeout(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        try:
            if hasattr(self, "message"):
                await self.message.edit(view=self)
        except Exception:
            pass


class GuildMusicState:
    def __init__(self):
        self.queue: deque = deque()
        self.currently_playing: Optional[Dict[str, Any]] = None
        self.loop_mode: str = "off"
        self.volume: float = 0.25
        self.paused_at: Optional[datetime] = None
        self.original_queue: List[Any] = []
        self.voice_channel_id: Optional[int] = None
        self.is_seeking: bool = False
        self.is_tts_playing: bool = False
        self.tts_queue: deque = deque()


class Audio(commands.Cog):
    def __init__(self, bot: commands.AutoShardedBot):
        self.bot = bot
        self.db_pool: Optional[asyncpg.Pool] = None
        self.guild_states: Dict[int, GuildMusicState] = {}
        self.paused_times: Dict[int, datetime] = {}
        self.executor = ThreadPoolExecutor(max_workers=5)
        self.ydl_options = {
            "format": "bestaudio/best",
            "outtmpl": f"{os.path.join(tempfile.gettempdir())}/%(extractor)s-%(id)s-%(title)s.%(ext)s",
            "restrictfilenames": True,
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
        }
        self.default_volume = 0.25

    async def cog_load(self):
        db_url = bot_info.data["database"]
        try:
            self.db_pool = await asyncpg.create_pool(db_url)
        except Exception:
            self.db_pool = None

    async def cog_unload(self):
        if self.db_pool:
            await self.db_pool.close()
        for guild_id, state in self.guild_states.items():
            if guild := self.bot.get_guild(guild_id):
                if vc := guild.voice_client:
                    await vc.disconnect()
        self.executor.shutdown(wait=False)

    def get_state(self, guild_id: int) -> GuildMusicState:
        if guild_id not in self.guild_states:
            self.guild_states[guild_id] = GuildMusicState()
        return self.guild_states[guild_id]

    async def run_in_executor(self, func, *args):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, func, *args)

    async def load_guild_settings(self, guild_id: int):
        if not self.db_pool:
            return
        state = self.get_state(guild_id)
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT volume, loop_mode FROM guild_music_settings WHERE guild_id = $1",
                guild_id,
            )
            if row:
                state.volume = row["volume"] or self.default_volume
                state.loop_mode = row["loop_mode"] or "off"

    async def save_guild_settings(
        self,
        guild_id: int,
        volume: Optional[float] = None,
        loop_mode: Optional[str] = None,
    ):
        if not self.db_pool:
            return
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO guild_music_settings (guild_id, volume, loop_mode)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (guild_id)
                   DO UPDATE SET volume = COALESCE($2, guild_music_settings.volume),
                                 loop_mode = COALESCE($3, guild_music_settings.loop_mode),
                                 updated_at = NOW()""",
                guild_id,
                volume,
                loop_mode,
            )

    async def log_play(
        self,
        guild_id: int,
        channel_id: int,
        user_id: int,
        url: str,
        title: str,
        duration: int,
    ):
        if not self.db_pool:
            return
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO music_play_logs (guild_id, channel_id, user_id, track_url, track_title, duration_sec)
                    VALUES ($1, $2, $3, $4, $5, $6)""",
                guild_id,
                channel_id,
                user_id,
                url,
                title,
                duration,
            )

    async def fetch_yt_info(self, url: str, download: bool = False) -> Dict:
        def sync_extract():
            with yt_dlp.YoutubeDL(self.ydl_options) as ydl:
                return ydl.extract_info(url, download=download)

        return await self.run_in_executor(sync_extract)

    async def connect_to_channel(self, ctx: commands.Context) -> bool:
        if not ctx.author.voice:
            await ctx.send("You are not connected to a voice channel.")
            return False

        channel = ctx.author.voice.channel
        voice_client = ctx.voice_client

        if voice_client:
            if voice_client.channel != channel:
                if (
                    len([m for m in voice_client.channel.members if not m.bot]) > 0
                    and voice_client.is_playing()
                ):
                    await ctx.send("I'm already being used in another voice channel.")
                    return False
                await voice_client.move_to(channel)
                await ctx.send(f"Moved to {channel.name}.")
            return True
        else:
            await channel.connect()
            await ctx.send(f"Connected to {channel.name}.")
            return True

    async def _resolve_tts_config(
        self,
        author_id: int,
        voice_channel_id: int,
        guild_id: int,
        text_channel_id: Optional[int] = None,
    ) -> dict:
        config = {"language": None, "filters": []}
        if not self.db_pool:
            return config

        async with self.db_pool.acquire() as conn:
            binding_language = None
            binding_filters = None

            if text_channel_id:
                row = await conn.fetchrow(
                    "SELECT language, filters FROM tts_bindings WHERE text_channel_id = $1",
                    text_channel_id,
                )
                if row:
                    binding_language = row["language"]
                    binding_filters = (
                        row["filters"].split(",") if row["filters"] else None
                    )

            if binding_language and binding_filters is not None:
                return {"language": binding_language, "filters": binding_filters}

            rows = await conn.fetch(
                """
                SELECT entity_type, language, filters FROM tts_configs
                   WHERE (entity_id = $1 AND guild_id = $4)
                      OR (entity_id = $2 AND guild_id = $4)
                      OR (entity_id = $3 AND guild_id = $4)
                """,
                author_id,
                voice_channel_id,
                guild_id,
                guild_id,
            )

            mapping = {r["entity_type"]: r for r in rows}
            hierarchy_language = None
            hierarchy_filters = None
            for entity_type in ["user", "channel", "guild"]:
                if entity_type in mapping:
                    r = mapping[entity_type]
                    if hierarchy_language is None and r["language"]:
                        hierarchy_language = r["language"]
                    if hierarchy_filters is None and r["filters"]:
                        hierarchy_filters = r["filters"].split(",")
                    if hierarchy_language is not None and hierarchy_filters is not None:
                        break

            return {
                "language": binding_language or hierarchy_language,
                "filters": (
                    binding_filters
                    if binding_filters is not None
                    else (hierarchy_filters or [])
                ),
            }

    def _generate_tts_file(self, text: str, language: Optional[str]) -> str:
        fp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        filename = fp.name
        fp.close()
        lang = language if language else "en"
        try:
            tts = gTTS(text=text, lang=lang, slow=False)
            tts.save(filename)
        except Exception:
            tts = gTTS(text=text, lang="en", slow=False)
            tts.save(filename)
        return filename

    async def _play_tts_file(
        self,
        vc: discord.VoiceClient,
        filename: str,
        filters: List[str],
        state: GuildMusicState,
    ):
        ffmpeg_opts = {"options": "-vn"}
        if filters:
            ffmpeg_opts["options"] += f' -af "{",".join(filters)}"'

        source = discord.FFmpegPCMAudio(filename, **ffmpeg_opts)
        source = discord.PCMVolumeTransformer(source, volume=1.0)

        state.is_tts_playing = True

        if vc.source and isinstance(vc.source, MixerAudioSource):
            mixer = vc.source
            mixer.bot = self.bot

            if mixer.main_source and hasattr(mixer.main_source, "volume"):
                mixer.main_source.volume = state.volume * 0.20

            def finish_mixed_tts(e):
                if vc.source and isinstance(vc.source, MixerAudioSource):
                    if vc.source.main_source and hasattr(
                        vc.source.main_source, "volume"
                    ):
                        vc.source.main_source.volume = state.volume
                state.is_tts_playing = False
                try:
                    os.remove(filename)
                except Exception:
                    pass
                asyncio.run_coroutine_threadsafe(
                    self._check_tts_queue(vc, state), self.bot.loop
                )

            mixer.after_tts = finish_mixed_tts
            mixer.tts_source = source

            if not vc.is_playing() and not vc.is_paused():
                vc.play(mixer, after=lambda e: mixer.cleanup())

        else:

            def finish_standalone_tts(e):
                state.is_tts_playing = False
                try:
                    os.remove(filename)
                except Exception:
                    pass
                asyncio.run_coroutine_threadsafe(
                    self._check_tts_queue(vc, state), self.bot.loop
                )

            vc.play(source, after=finish_standalone_tts)

    async def _check_tts_queue(self, vc: discord.VoiceClient, state: GuildMusicState):
        if not vc or not vc.is_connected():
            state.tts_queue.clear()
            state.is_tts_playing = False
            return

        if not vc.is_playing() and not vc.is_paused():
            state.is_tts_playing = False

        if state.is_tts_playing or not state.tts_queue:
            return

        filename, filters = state.tts_queue.popleft()
        await self._play_tts_file(vc, filename, filters, state)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not self.db_pool:
            return

        async with self.db_pool.acquire() as conn:
            bound = await conn.fetchrow(
                "SELECT text_channel_id FROM tts_bindings WHERE text_channel_id = $1",
                message.channel.id,
            )

        if bound:
            vc = message.guild.voice_client
            if (
                vc
                and vc.is_connected()
                and message.author.voice
                and message.author.voice.channel == vc.channel
            ):
                state = self.get_state(message.guild.id)
                config = await self._resolve_tts_config(
                    author_id=message.author.id,
                    voice_channel_id=vc.channel.id,
                    guild_id=message.guild.id,
                    text_channel_id=message.channel.id,
                )
                try:
                    filename = await self.run_in_executor(
                        self._generate_tts_file,
                        message.content,
                        config["language"],
                    )
                    state.tts_queue.append((filename, config["filters"]))
                    await self._check_tts_queue(vc, state)
                except Exception:
                    pass

    async def _internal_say(
        self,
        ctx: commands.Context,
        text: str,
        language: Optional[str] = None,
        filters: Optional[List[str]] = None,
    ):
        state = self.get_state(ctx.guild.id)
        vc = ctx.voice_client
        if not vc or not vc.is_connected():
            return await ctx.send("I must be connected to a voice channel first.")

        config = await self._resolve_tts_config(
            author_id=ctx.author.id,
            voice_channel_id=vc.channel.id,
            guild_id=ctx.guild.id,
        )

        resolved_language = language or config["language"]
        resolved_filters = filters if filters is not None else config["filters"]

        try:
            filename = await self.run_in_executor(
                self._generate_tts_file,
                text,
                resolved_language,
            )
            state.tts_queue.append((filename, resolved_filters))
            await self._check_tts_queue(vc, state)
        except Exception as e:
            await ctx.send(f"gTTS error: {e}", delete_after=5)

    async def play_next(self, ctx: Optional[commands.Context], guild_id: int):
        if not ctx:
            guild = self.bot.get_guild(guild_id)
            if not guild or not guild.voice_client:
                return
            voice_client = guild.voice_client
        else:
            voice_client = ctx.voice_client

        state = self.get_state(guild_id)

        if not voice_client:
            return

        if state.loop_mode == "track" and state.currently_playing:
            track = state.currently_playing
            state.is_seeking = False
            await self._play_source(
                ctx,
                track["url"],
                track["filters"],
                0,
                track["is_stream"],
                track["info"],
                track["file_path"],
            )
            return

        if not state.queue:
            if state.loop_mode == "queue" and state.original_queue:
                state.queue = deque(state.original_queue)
                if ctx:
                    await ctx.send("Restarting queue loop.")
                await self.play_next(ctx, guild_id)
            else:
                state.currently_playing = None
            return

        url, filters, is_stream, title, requester = state.queue.popleft()

        if state.loop_mode == "queue" and not state.original_queue:
            state.original_queue = list(state.queue) + [
                (url, filters, is_stream, title, requester)
            ]

        try:
            info = await self.fetch_yt_info(url, download=not is_stream)
            await self._play_source(
                ctx, url, filters, 0, is_stream, info, requester=requester
            )
        except Exception as e:
            if ctx:
                await ctx.send(f"Error playing track: {e}")
            await self.play_next(ctx, guild_id)

    async def _play_source(
        self,
        ctx: Optional[commands.Context],
        url: str,
        filters: List[str],
        position: float,
        is_stream: bool,
        info: Dict,
        file_path: Optional[str] = None,
        requester=None,
    ):
        if not ctx:
            return

        guild_id = ctx.guild.id
        state = self.get_state(guild_id)
        voice_client = ctx.voice_client

        if not voice_client:
            return

        actual_file_path = None

        if is_stream:
            formats = info.get("formats", [])
            stream_url = None
            for f in sorted(
                formats, key=lambda x: x.get("filesize") or 0, reverse=True
            ):
                if f.get("acodec") != "none" and f.get("vcodec") == "none":
                    if f.get("url", "").startswith("http"):
                        stream_url = f["url"]
                        break
            if not stream_url:
                stream_url = info.get("url", "")
            ffmpeg_opts = {
                "before_options": f"-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -ss {position}",
                "options": "-vn -f s16le",
            }
            source = discord.FFmpegPCMAudio(
                stream_url,
                **ffmpeg_opts,
            )
        else:
            if file_path and os.path.exists(file_path):
                actual_file_path = file_path
            else:
                ydl = yt_dlp.YoutubeDL(self.ydl_options)
                actual_file_path = ydl.prepare_filename(info)
                if not os.path.exists(actual_file_path):
                    info = await self.fetch_yt_info(url, download=True)
                    actual_file_path = ydl.prepare_filename(info)
            ffmpeg_opts = {
                "before_options": f"-ss {position}",
                "options": "-vn -f s16le",
            }
            if filters:
                ffmpeg_opts["options"] += f" -af {','.join(filters)}"
            source = discord.FFmpegPCMAudio(
                actual_file_path,
                **ffmpeg_opts,
            )
        source = discord.PCMVolumeTransformer(source, volume=state.volume)

        def after_callback(e):
            asyncio.run_coroutine_threadsafe(
                self._after_play(ctx, actual_file_path, guild_id), self.bot.loop
            )

        if voice_client.source and isinstance(voice_client.source, MixerAudioSource):
            mixer = voice_client.source
            mixer.bot = self.bot
            mixer.main_source = source
            mixer.after_main = lambda: after_callback(None)

            if not voice_client.is_playing() and not voice_client.is_paused():
                voice_client.play(mixer, after=lambda e: mixer.cleanup())
        else:
            mixer = MixerAudioSource(source)
            mixer.bot = self.bot

            def trigger_after_main():
                after_callback(None)

            mixer.after_main = trigger_after_main
            voice_client.play(mixer, after=lambda e: mixer.cleanup())
        duration = info.get("duration", 0)
        state.currently_playing = {
            "url": url,
            "filters": filters,
            "position": position,
            "is_stream": is_stream,
            "info": info,
            "start_time": datetime.now(),
            "file_path": actual_file_path,
            "requester": requester or ctx.author,
        }

        actual_requester = requester or (ctx.author if ctx else None)

        if actual_requester:
            await self.log_play(
                guild_id,
                ctx.channel.id,
                actual_requester.id,
                url,
                info.get("title", "Unknown"),
                int(duration),
            )

            if position == 0:
                embed = discord.Embed(
                    title=f"{'Streaming' if is_stream else 'Playing'} - {info.get('title', 'Unknown')}",
                    description=f"URL: {info.get('webpage_url', 'Unknown')}",
                    color=discord.Color.og_blurple()
                    if not is_stream
                    else discord.Color.blurple(),
                    timestamp=discord.utils.utcnow(),
                )
                if info.get("thumbnail"):
                    embed.set_image(url=info["thumbnail"])
                embed.add_field(
                    name="Duration", value=self.format_time(duration), inline=True
                )
                embed.add_field(
                    name="Uploader", value=info.get("uploader", "Unknown"), inline=True
                )
                if info.get("view_count"):
                    embed.add_field(
                        name="Views", value=f"{info['view_count']:,}", inline=True
                    )
                if info.get("like_count"):
                    embed.add_field(
                        name="Likes", value=f"{info['like_count']:,}", inline=True
                    )
                raw_date = info.get("upload_date")
                upload_date = (
                    datetime.strptime(raw_date, "%Y%m%d").strftime("%B %d, %Y")
                    if raw_date
                    else "Unknown"
                )
                embed.add_field(name="Published At", value=upload_date, inline=True)
                if filters:
                    embed.add_field(
                        name="Filters", value=", ".join(filters), inline=True
                    )
                if actual_requester:
                    embed.set_footer(
                        text=f"Requested by {actual_requester.name}",
                        icon_url=actual_requester.display_avatar.url,
                    )
                try:
                    await ctx.send(embed=embed)
                except discord.errors.Forbidden:
                    pass

    async def _after_play(
        self, ctx: commands.Context, file_path: Optional[str], guild_id: int
    ):
        state = self.get_state(guild_id)

        if state.is_seeking:
            state.is_seeking = False
            return

        if file_path and os.path.exists(file_path) and state.loop_mode != "track":
            try:
                await asyncio.to_thread(os.remove, file_path)
            except Exception:
                pass

        await self.play_next(ctx, guild_id)

    def format_time(self, seconds: float) -> str:
        if not seconds:
            return "0:00"
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def parse_time(self, t: str) -> float:
        t = t.strip()
        if ":" in t:
            parts = list(map(float, t.split(":")))
            if len(parts) == 2:
                return parts[0] * 60 + parts[1]
            elif len(parts) == 3:
                return parts[0] * 3600 + parts[1] * 60 + parts[2]
        elif "." in t or t.replace(".", "", 1).isdigit():
            return float(t)
        elif t.isdigit():
            return float(t)
        raise ValueError(f"Unrecognized time format: {t}")

    def parse_seek_position(
        self, pos_str: str, total_duration: float, current_pos: float
    ) -> float:
        pos_str = pos_str.strip()
        if not pos_str:
            raise ValueError("Empty position string provided.")
        if pos_str.startswith(("-", "+")) and pos_str.endswith("%"):
            rel_percent = float(pos_str[1:-1])
            delta = (rel_percent / 100) * total_duration
            return current_pos + (delta if pos_str[0] == "+" else -delta)
        elif pos_str.endswith("%"):
            percent = float(pos_str[:-1]) / 100
            return total_duration * percent
        elif pos_str.startswith(("+", "-")):
            rel_seconds = self.parse_time(pos_str[1:])
            return current_pos + (rel_seconds if pos_str[0] == "+" else -rel_seconds)
        else:
            return self.parse_time(pos_str)

    def get_valid_stream_url(self, info):
        formats = info.get("formats", [])
        formats.sort(key=lambda f: f.get("filesize") or 0, reverse=True)
        for f in formats:
            if f.get("acodec") != "none" and f.get("vcodec") == "none":
                if f.get("protocol", " ").startswith(("http", "https")):
                    return f["url"]
        return info.get("url")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member == self.bot.user:
            if not after.channel:
                guild_id = member.guild.id
                state = self.get_state(guild_id)
                state.queue.clear()
                state.currently_playing = None
        else:
            if before.channel and before.channel.guild.voice_client:
                vc = before.channel.guild.voice_client
                if (
                    vc.channel == before.channel
                    and len(before.channel.members) == 1
                    and self.bot.user in before.channel.members
                ):
                    await asyncio.sleep(5)
                    if (
                        len(before.channel.members) == 1
                        and self.bot.user in before.channel.members
                    ):
                        await vc.disconnect()

    @commands.hybrid_command(name="join", description="Join a voice channel.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def join(self, ctx: commands.Context):
        await ctx.typing()
        await self.connect_to_channel(ctx)

    @commands.hybrid_command(
        name="leave", description="Leave the current voice channel."
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    async def leave(self, ctx: commands.Context):
        await ctx.typing()
        if ctx.author.voice is None:
            await ctx.send("You are not in a voice channel.")
            return
        elif ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You are not in the same voice channel as me.")
            return
        if ctx.voice_client:
            queue = self.get_queue(ctx.guild.id)
            queue.clear()
            await ctx.send(f"Disconnected from {ctx.voice_client.channel}.")
            await ctx.voice_client.disconnect()

    def get_queue(self, guild_id):
        if guild_id not in self.guild_states:
            self.guild_states[guild_id] = GuildMusicState()
        return self.guild_states[guild_id].queue

    async def process_playlist(
        self, ctx: commands.Context, url: str, filters=None, is_stream: bool = False
    ):
        try:
            if not await self.connect_to_channel(ctx):
                return

            def sync_playlist_process():
                with yt_dlp.YoutubeDL(self.ydl_options) as ydl:
                    return ydl.extract_info(url, download=False)

            info = await self.run_in_executor(sync_playlist_process)
            if "entries" not in info:
                if is_stream:
                    return await self.play_stream(ctx, url, filters)
                else:
                    return await self.play_audio(ctx, url, filters)

            entries = [e for e in info["entries"] if e]
            filters_list = filters.split(",") if filters else []
            queue = self.get_queue(ctx.guild.id)
            for entry in entries:
                title = entry.get("title", "Unknown Title")
                queue.append((entry["url"], filters_list, is_stream, title, ctx.author))

            state = self.get_state(ctx.guild.id)
            if state.loop_mode == "queue":
                state.original_queue = list(queue)

            await ctx.send(
                f"Added {len(entries)} tracks from {info.get('title', 'Unknown Playlist')}."
            )
            if not ctx.voice_client or not ctx.voice_client.is_playing():
                if is_stream:
                    await self.play_next_stream(ctx)
                else:
                    await self.play_next(ctx, ctx.guild.id)
        except Exception as e:
            await ctx.send(f"Error processing playlist: {e}")

    async def play_audio(self, ctx: commands.Context, url: str, filters=None):
        await self._generic_play(ctx, url, filters, download=True)

    async def play_stream(self, ctx: commands.Context, url: str, filters=None):
        await self._generic_play(ctx, url, filters, download=False)

    async def _generic_play(
        self, ctx: commands.Context, url: str, filters=None, download=True
    ):
        if not await self.connect_to_channel(ctx):
            return

        state = self.get_state(ctx.guild.id)
        filters_list = filters.split(",") if filters else []

        if ctx.voice_client and ctx.voice_client.is_playing():
            try:
                info = await self.fetch_yt_info(url, download=False)
                title = info.get("title", "Unknown")
            except Exception:
                title = url
            state.queue.append((url, filters_list, not download, title, ctx.author))
            await ctx.send(f"Added {title} to the queue.")
            if state.loop_mode == "queue":
                state.original_queue = list(state.queue)
        else:
            try:
                info = await self.fetch_yt_info(url, download=download)
                await self._play_source(ctx, url, filters_list, 0, not download, info)
            except Exception as e:
                raise Exception(str(e))

    async def play_next_stream(self, ctx: commands.Context):
        await self.play_next(ctx, ctx.guild.id)

    @commands.hybrid_command(
        name="play",
        description="Play a track or playlist from a given URL. Any URL that yt-dlp supports also works.",
        aliases=["p"],
    )
    @app_commands.describe(
        url="The URL of the track or playlist to play.",
        attachment="The attachment media file to use for playing.",
        filters="A comma-separated list of filters to apply to the track.",
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    async def play(
        self,
        ctx: commands.Context,
        url: str = None,
        attachment: Optional[discord.Attachment] = None,
        filters: str = None,
    ):
        await ctx.typing()
        source_url = url
        if ctx.message.attachments or attachment:
            source_url = (
                attachment.url if attachment else ctx.message.attachments[0].url
            )

        if not source_url:
            await ctx.send("Please provide an URL or an attachment file.")
            return

        is_playlist = any(p in source_url.lower() for p in ["playlist", "list="])
        if is_playlist:
            await self.process_playlist(ctx, source_url, filters, is_stream=False)
            return

        await self.play_audio(ctx, source_url, filters)

    @commands.hybrid_command(
        name="stream",
        description="Stream a track or playlist from a given URL without downloading to disk.",
        aliases=["s"],
    )
    @app_commands.describe(
        url="The URL of the track or playlist to stream.",
        attachment="The attachment media file to use for streaming.",
        filters="A comma-separated list of filters to apply to the track.",
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    async def stream(
        self,
        ctx: commands.Context,
        url: str = None,
        attachment: Optional[discord.Attachment] = None,
        filters: str = None,
    ):
        await ctx.typing()
        source_url = url
        if ctx.message.attachments or attachment:
            source_url = (
                attachment.url if attachment else ctx.message.attachments[0].url
            )

        if not source_url:
            await ctx.send("Please provide an URL or an attachment file.")
            return

        is_playlist = any(p in source_url.lower() for p in ["playlist", "list="])
        if is_playlist:
            await self.process_playlist(ctx, source_url, filters, is_stream=True)
            return

        await self.play_stream(ctx, source_url, filters)

    @commands.hybrid_command(
        name="seek",
        description="Seek to a specific position in the currently playing track.",
    )
    @app_commands.describe(
        position="Position to seek to. Can be absolute (e.g. 2:30), relative (+/- 30), or percentage. (50%)"
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    async def seek(self, ctx: commands.Context, position: str):
        await ctx.typing()
        if ctx.author.voice is None:
            await ctx.send("You are not in a voice channel.")
            return
        elif ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You are not in the same voice channel as me.")
            return
        elif ctx.voice_client and not ctx.voice_client.is_playing():
            await ctx.send("Nothing is currently playing.")
            return

        state = self.get_state(ctx.guild.id)
        current_data = state.currently_playing
        if not current_data or "info" not in current_data:
            await ctx.send("No valid data available.")
            return

        duration = current_data["info"].get("duration")
        if not duration:
            await ctx.send("Cannot seek; duration unknown.")
            return

        start_time = current_data.get("start_time", datetime.now())
        elapsed = (datetime.now() - start_time).total_seconds()
        if state.paused_at:
            if ctx.guild.id in self.paused_times:
                pause_start = self.paused_times[ctx.guild.id]
                pause_duration = (datetime.now() - pause_start).total_seconds()
                elapsed -= pause_duration

        current_pos = int(elapsed + current_data.get("position", 0))

        try:
            new_pos = self.parse_seek_position(position.strip(), duration, current_pos)
        except ValueError as e:
            await ctx.send(str(e))
            return

        new_pos = max(0, min(new_pos, duration))
        state.is_seeking = True
        ctx.voice_client.stop()
        current_data["position"] = new_pos
        current_data["start_time"] = datetime.now()

        await self._play_source(
            ctx,
            current_data["url"],
            current_data["filters"],
            new_pos,
            current_data.get("is_stream", False),
            current_data["info"],
            current_data.get("file_path"),
        )

        await ctx.send(f"Seeked to {self.format_time(new_pos)}.")

    @commands.hybrid_command(
        name="goto", description="Skip to a specific track in the queue by index."
    )
    @app_commands.describe(
        index="The index of the track in the queue to skip to. (starting at 1)"
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    async def goto(self, ctx: commands.Context, index: int):
        await ctx.typing()
        if ctx.author.voice is None:
            await ctx.send("You are not in a voice channel.")
            return
        elif ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You are not in the same voice channel as me.")
            return
        queue = self.get_queue(ctx.guild.id)
        if not queue or index < 1 or index > len(queue):
            await ctx.send("Invalid index.")
            return

        for _ in range(index - 1):
            queue.popleft()

        if ctx.voice_client.is_playing():
            ctx.voice_client.stop()
        else:
            await self.play_next(ctx, ctx.guild.id)
        await ctx.send(f"Skipped to position {index}.")

    @commands.hybrid_command(
        name="move", description="Move a track to another position in the queue."
    )
    @app_commands.describe(
        old_index="Current position of the track. (starting at 1)",
        new_index="New position for the track. (starting at 1)",
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    async def move(self, ctx: commands.Context, old_index: int, new_index: int):
        await ctx.typing()
        if ctx.author.voice is None:
            await ctx.send("You are not in a voice channel.")
            return
        elif ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You are not in the same voice channel as me.")
            return
        queue = list(self.get_queue(ctx.guild.id))
        length = len(queue)
        if not (1 <= old_index <= length) or not (1 <= new_index <= length):
            await ctx.send("Invalid indexes.")
            return

        moved_item = queue.pop(old_index - 1)
        queue.insert(new_index - 1, moved_item)

        state = self.get_state(ctx.guild.id)
        state.queue = deque(queue)
        if state.loop_mode == "queue":
            state.original_queue = queue

        await ctx.send(f"Moved track from position {old_index} to {new_index}.")

    @commands.hybrid_command(
        name="remove", description="Remove a track from the queue by index."
    )
    @app_commands.describe(index="Index of the track to remove. (starting at 1)")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def remove(self, ctx: commands.Context, index: int):
        await ctx.typing()
        if ctx.author.voice is None:
            await ctx.send("You are not in a voice channel.")
            return
        elif ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You are not in the same voice channel as me.")
            return
        queue = list(self.get_queue(ctx.guild.id))
        if not queue or not (1 <= index <= len(queue)):
            await ctx.send("Invalid index.")
            return

        removed = queue.pop(index - 1)
        state = self.get_state(ctx.guild.id)
        state.queue = deque(queue)
        if state.loop_mode == "queue":
            state.original_queue = queue

        await ctx.send(f"Removed {removed[3]} from the queue.")

    @commands.hybrid_command(
        name="volume",
        description="Adjust the playback volume (0-100%).",
        aliases=["vol"],
    )
    @app_commands.describe(level="Volume level. (0-100)")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def volume(self, ctx: commands.Context, level: int):
        await ctx.typing()
        if ctx.author.voice is None:
            await ctx.send("You are not in a voice channel.")
            return
        elif ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You are not in the same voice channel as me.")
            return
        level = max(0, min(100, level))
        volume_level = level / 100.0

        state = self.get_state(ctx.guild.id)
        state.volume = volume_level
        await self.save_guild_settings(ctx.guild.id, volume=volume_level)

        if ctx.voice_client.source:
            ctx.voice_client.source.volume = volume_level
        await ctx.send(f"Volume has been set to {level}%")

    @commands.hybrid_command(
        name="nowplaying",
        description="Display information about the currently playing track.",
        aliases=["np"],
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    async def nowplaying(self, ctx: commands.Context):
        await ctx.typing()
        if (
            ctx.voice_client
            and ctx.author.voice
            and ctx.author.voice.channel == ctx.voice_client.channel
            and ctx.voice_client.is_playing()
            or ctx.voice_client.is_paused()
        ):
            state = self.get_state(ctx.guild.id)
            current = state.currently_playing
            if current:
                info = current["info"]
                filters = current["filters"]
                is_stream = current["is_stream"]
                start_time = current.get("start_time", datetime.now())
                requester = current.get("requester", ctx.author)
                elapsed = (datetime.now() - start_time).total_seconds()
                if ctx.guild.id in self.paused_times:
                    pause_start = self.paused_times[ctx.guild.id]
                    pause_duration = (datetime.now() - pause_start).total_seconds()
                    elapsed -= pause_duration
                current_pos = elapsed + current.get("position", 0)
                duration = info.get("duration", 0)
                formatted_position = (
                    f"{self.format_time(current_pos)} / {self.format_time(duration)}"
                )
                if ctx.voice_client.is_paused():
                    status = "Paused"
                    color = discord.Color.dark_grey()
                else:
                    status = "Playing" if not is_stream else "Streaming"
                    color = (
                        discord.Color.og_blurple()
                        if not is_stream
                        else discord.Color.blurple()
                    )
                embed = discord.Embed(
                    title=f"Currently {status} - {info['title'] if info['title'] else 'Unknown'}",
                    description=f"URL: {info['webpage_url'] if info['webpage_url'] else 'Unknown'}",
                    color=color,
                    timestamp=discord.utils.utcnow(),
                )
                raw_date = info.get("upload_date")
                upload_date = (
                    datetime.strptime(raw_date, "%Y%m%d").strftime("%B %d, %Y")
                    if raw_date
                    else "Unknown"
                )
                embed.add_field(name="Length", value=formatted_position, inline=True)
                embed.add_field(
                    name="Uploader", value=info.get("uploader", "Unknown"), inline=True
                )
                embed.add_field(
                    name="Channel",
                    value=info.get("uploader_url", "Unknown"),
                    inline=True,
                )
                if info.get("view_count"):
                    embed.add_field(
                        name="Views", value=f"{info['view_count']:,}", inline=True
                    )
                if info.get("like_count"):
                    embed.add_field(
                        name="Likes", value=f"{info['like_count']:,}", inline=True
                    )
                if filters:
                    embed.add_field(
                        name="Filters",
                        value=", ".join(filters) if filters else "None",
                        inline=True,
                    )
                embed.add_field(name="Published At", value=upload_date, inline=True)
                embed.set_image(url=info.get("thumbnail", None))
                embed.set_footer(
                    text=f"Requested by {requester.name}",
                    icon_url=requester.display_avatar.url,
                )
                await ctx.send(embed=embed)
        elif ctx.author.voice is None:
            await ctx.send("You are not in a voice channel.")
        elif ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You are not in the same voice channel as me.")
        else:
            await ctx.send("Nothing is currently playing.")

    @commands.hybrid_command(
        name="shuffle", description="Shuffle the current queue/playlist."
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    async def shuffle(self, ctx: commands.Context):
        if (
            ctx.voice_client
            and ctx.author.voice
            and ctx.author.voice.channel == ctx.voice_client.channel
        ):
            await ctx.typing()
            queue = self.get_queue(ctx.guild.id)
            if len(queue) < 2:
                await ctx.send("Queue must have more than 2 tracks to shuffle.")
                return

            queue_list = list(queue)
            random.shuffle(queue_list)
            state = self.get_state(ctx.guild.id)
            state.queue = deque(queue_list)
            if state.loop_mode == "queue":
                state.original_queue = queue_list

            await ctx.send("Queue has been shuffled.")
        elif ctx.author.voice is None:
            await ctx.send("You are not in a voice channel.")
        elif ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You are not in the same voice channel as me.")

    @commands.hybrid_command(
        name="repeat",
        description="Repeat the currently playing track or playlist.",
        aliases=["loop"],
    )
    @app_commands.describe(mode="Loop mode. (off/track/queue)")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def repeat(self, ctx: commands.Context, mode: str = None):
        if (
            ctx.voice_client
            and ctx.voice_client.is_playing()
            and ctx.author.voice
            and ctx.author.voice.channel == ctx.voice_client.channel
        ):
            await ctx.typing()
            modes = {
                "off": "Loop disabled.",
                "track": "Track loop enabled.",
                "queue": "Queue loop enabled.",
            }
            state = self.get_state(ctx.guild.id)

            if mode is None:
                new_mode = (
                    "track"
                    if state.loop_mode == "off"
                    else "queue"
                    if state.loop_mode == "track"
                    else "off"
                )
            else:
                mode = mode.lower()
                if mode not in modes:
                    await ctx.send(
                        "Not a valid mode. Must be one of: `off`, `track`, and `queue`"
                    )
                    return
                new_mode = mode

            state.loop_mode = new_mode
            if new_mode == "queue":
                state.original_queue = list(state.queue)

            await self.save_guild_settings(ctx.guild.id, loop_mode=new_mode)
            await ctx.send(modes[new_mode])
        elif ctx.author.voice is None:
            await ctx.send("You are not in a voice channel.")
        elif ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You are not in the same voice channel as me.")

    @commands.hybrid_command(name="queue", description="Display the current queue.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def queue(self, ctx: commands.Context):
        if ctx.author.voice is None:
            await ctx.send("You are not in a voice channel.")
            return
        elif ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You are not in the same voice channel as me.")
            return
        elif (
            ctx.voice_client
            and ctx.author.voice
            and ctx.author.voice.channel == ctx.voice_client.channel
        ):
            await ctx.typing()
            queue = self.get_queue(ctx.guild.id)
            if not queue:
                await ctx.send("The queue is empty.")
                return
            ITEMS_PER_PAGE = 10
            total_pages = (len(queue) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE

            class QueuePaginator(discord.ui.View):
                def __init__(self, queue, total_pages, original_author):
                    super().__init__(timeout=180)
                    self.queue = queue
                    self.current_page = 0
                    self.total_pages = total_pages
                    self.original_author = original_author
                    self.message = None
                    self.disabled = False

                async def interaction_check(self, interaction: discord.Interaction):
                    if interaction.user != self.original_author:
                        await interaction.response.send_message(
                            "You can't control this pagination.", ephemeral=True
                        )
                        return False
                    return True

                async def on_timeout(self):
                    await self.message.edit(view=None)

                def create_embed(self):
                    start_idx = self.current_page * ITEMS_PER_PAGE
                    end_idx = min(
                        (self.current_page + 1) * ITEMS_PER_PAGE, len(self.queue)
                    )
                    embed = discord.Embed(
                        title=f"Queue (Page {self.current_page + 1}/{self.total_pages})",
                        color=discord.Color.og_blurple(),
                        timestamp=discord.utils.utcnow(),
                    )
                    for i, (url, filters, is_stream, title, requester) in enumerate(
                        self.queue[start_idx:end_idx], start=start_idx + 1
                    ):
                        filter_text = f" ({', '.join(filters)})" if filters else ""
                        stream_label = " (Stream)" if is_stream else ""
                        requester_label = f" - Requested by {requester.name}"
                        embed.add_field(
                            name=f"{i}.",
                            value=f"[{title}]({url}){filter_text}{stream_label}{requester_label}",
                            inline=False,
                        )
                    return embed

                @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary)
                async def first_page(
                    self, interaction: discord.Interaction, button: discord.ui.Button
                ):
                    if self.current_page == 0:
                        await interaction.response.defer()
                        return
                    self.current_page = 0
                    await interaction.response.edit_message(
                        embed=self.create_embed(), view=self
                    )

                @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.primary)
                async def prev_page(
                    self, interaction: discord.Interaction, button: discord.ui.Button
                ):
                    if self.current_page == 0:
                        await interaction.response.defer()
                        return
                    self.current_page -= 1
                    await interaction.response.edit_message(
                        embed=self.create_embed(), view=self
                    )

                @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.primary)
                async def next_page(
                    self, interaction: discord.Interaction, button: discord.ui.Button
                ):
                    if self.current_page == self.total_pages - 1:
                        await interaction.response.defer()
                        return
                    self.current_page += 1
                    await interaction.response.edit_message(
                        embed=self.create_embed(), view=self
                    )

                @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary)
                async def last_page(
                    self, interaction: discord.Interaction, button: discord.ui.Button
                ):
                    if self.current_page == self.total_pages - 1:
                        await interaction.response.defer()
                        return
                    self.current_page = self.total_pages - 1
                    await interaction.response.edit_message(
                        embed=self.create_embed(), view=self
                    )

                @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.success)
                async def random_page(
                    self, interaction: discord.Interaction, button: discord.ui.Button
                ):
                    new_page = random.randint(0, self.total_pages - 1)
                    if new_page == self.current_page:
                        await interaction.response.defer()
                        return
                    self.current_page = new_page
                    await interaction.response.edit_message(
                        embed=self.create_embed(), view=self
                    )

                @discord.ui.button(emoji="🔢", style=discord.ButtonStyle.secondary)
                async def jump_to_page(
                    self, interaction: discord.Interaction, button: discord.ui.Button
                ):
                    if self.disabled:
                        await interaction.response.defer()
                        return

                    class PageJumpModal(discord.ui.Modal, title="Jump to Page"):
                        page_num = discord.ui.TextInput(
                            label=f"Page Number (1-{self.total_pages})",
                            placeholder=f"Enter a number between 1 and {self.total_pages}",
                            min_length=1,
                            max_length=len(str(self.total_pages)),
                        )

                        async def on_submit(self, interaction: discord.Interaction):
                            try:
                                page = int(self.page_num.value)
                                if 1 <= page <= self.view.total_pages:
                                    self.view.current_page = page - 1
                                    await interaction.response.edit_message(
                                        embed=self.view.create_embed(), view=self.view
                                    )
                                else:
                                    await interaction.response.send_message(
                                        f"Please enter a number between 1 and {self.view.total_pages}.",
                                        ephemeral=True,
                                    )
                            except ValueError:
                                await interaction.response.send_message(
                                    "Please enter a valid number.", ephemeral=True
                                )

                    modal = PageJumpModal()
                    modal.view = self
                    await interaction.response.send_modal(modal)

                @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger)
                async def disable_components(
                    self, interaction: discord.Interaction, button: discord.ui.Button
                ):
                    await interaction.response.edit_message(view=None)

                @discord.ui.button(emoji="🗑️", style=discord.ButtonStyle.danger)
                async def delete_message(
                    self, interaction: discord.Interaction, button: discord.ui.Button
                ):
                    await interaction.message.delete()
                    self.stop()

            paginator = QueuePaginator(list(queue), total_pages, ctx.author)
            embed = paginator.create_embed()
            paginator.message = await ctx.send(embed=embed, view=paginator)

    @commands.hybrid_command(
        name="skip", description="Skip the currently playing track."
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    async def skip(self, ctx: commands.Context):
        await ctx.typing()
        if (
            ctx.voice_client
            and ctx.voice_client.is_playing()
            and ctx.author.voice
            and ctx.author.voice.channel == ctx.voice_client.channel
        ):
            state = self.get_state(ctx.guild.id)
            if state.loop_mode == "track":
                state.loop_mode = "off"
                await self.save_guild_settings(ctx.guild.id, loop_mode="off")
            ctx.voice_client.stop()
            await ctx.send("Skipped track.")
        elif ctx.author.voice is None:
            await ctx.send("You are not in a voice channel.")
        elif ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You are not in the same voice channel as me.")
        elif not ctx.voice_client.is_playing():
            await ctx.send("Nothing is currently playing.")

    @commands.hybrid_command(
        name="stop", description="Stop the currently playing track and clear the queue."
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    async def stop(self, ctx: commands.Context):
        await ctx.typing()
        if (
            ctx.voice_client
            and ctx.voice_client.is_playing()
            and ctx.author.voice
            and ctx.author.voice.channel == ctx.voice_client.channel
        ):
            state = self.get_state(ctx.guild.id)
            state.queue.clear()
            state.original_queue = []
            ctx.voice_client.stop()
            await ctx.send("Stopped track and cleared the queue.")
        elif ctx.author.voice is None:
            await ctx.send("You are not in a voice channel.")
        elif ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You are not in the same voice channel as me.")
        elif (
            not ctx.voice_client.is_playing()
            and self.get_state(ctx.guild.id).queue is None
        ):
            await ctx.send("Nothing is currently playing.")
        elif (
            not ctx.voice_client.is_playing()
            and self.get_state(ctx.guild.id).queue
            and ctx.author.voice
            and ctx.author.voice.channel == ctx.voice_client.channel
        ):
            self.get_state(ctx.guild.id).queue.clear()
            self.get_state(ctx.guild.id).original_queue = []
            await ctx.send("Cleared the queue.")

    @commands.hybrid_command(name="clear", description="Clear the queue.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def clear(self, ctx: commands.Context):
        if (
            ctx.voice_client
            and ctx.author.voice
            and ctx.author.voice.channel == ctx.voice_client.channel
        ):
            await ctx.typing()
            state = self.get_state(ctx.guild.id)
            state.queue.clear()
            await ctx.send("Cleared the queue.")
        elif ctx.author.voice is None:
            await ctx.send("You are not in a voice channel.")
        elif ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You are not in the same voice channel as me.")

    @commands.hybrid_command(
        name="pause", description="Pause the currently playing track."
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    async def pause(self, ctx: commands.Context):
        await ctx.typing()
        if (
            ctx.voice_client
            and ctx.voice_client.is_playing()
            and ctx.author.voice
            and ctx.author.voice.channel == ctx.voice_client.channel
        ):
            state = self.get_state(ctx.guild.id)
            state.paused_at = datetime.now()
            self.paused_times[ctx.guild.id] = datetime.now()
            ctx.voice_client.pause()
            await ctx.send("Paused track.")
        elif (
            ctx.voice_client
            and ctx.voice_client.is_paused()
            and ctx.author.voice
            and ctx.author.voice.channel == ctx.voice_client.channel
        ):
            await ctx.send("Current track is already paused.")
        elif ctx.author.voice is None:
            await ctx.send("You are not in a voice channel.")
        elif ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You are not in the same voice channel as me.")

    @commands.hybrid_command(
        name="resume", description="Resume the currently paused track."
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    async def resume(self, ctx: commands.Context):
        await ctx.typing()
        if (
            ctx.voice_client
            and ctx.voice_client.is_paused()
            and ctx.author.voice
            and ctx.author.voice.channel == ctx.voice_client.channel
        ):
            state = self.get_state(ctx.guild.id)
            if state.paused_at and state.currently_playing:
                pause_dur = (datetime.now() - state.paused_at).total_seconds()
                state.currently_playing["start_time"] += timedelta(seconds=pause_dur)
            state.paused_at = None
            self.paused_times.pop(ctx.guild.id, None)
            ctx.voice_client.resume()
            await ctx.send("Resumed track.")
        elif (
            ctx.voice_client
            and ctx.voice_client.is_playing()
            and ctx.author.voice
            and ctx.author.voice.channel == ctx.voice_client.channel
        ):
            await ctx.send("Current track is already playing.")
        elif ctx.author.voice is None:
            await ctx.send("You are not in a voice channel.")
        elif ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You are not in the same voice channel as me.")

    @commands.hybrid_command(
        name="musicprofile",
        description="View your or someone else's music listening profile.",
        aliases=["profile", "mprofile", "mp", "musicp"],
    )
    @app_commands.describe(target_user="The user to view.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def musicprofile(
        self, ctx: commands.Context, target_user: Optional[discord.Member] = None
    ):
        await ctx.typing()
        if not self.db_pool:
            await ctx.send(
                "Statistics are currently not available, sorry. (is the database connected?)"
            )
            return

        user = target_user or ctx.author
        async with self.db_pool.acquire() as conn:
            total_tracks = await conn.fetchval(
                "SELECT COUNT(*) FROM music_play_logs WHERE user_id = $1", user.id
            )
            total_time = await conn.fetchval(
                "SELECT COALESCE(SUM(duration_sec), 0) FROM music_play_logs WHERE user_id = $1",
                user.id,
            )
            unique_tracks = await conn.fetchval(
                "SELECT COUNT(DISTINCT track_title) FROM music_play_logs WHERE user_id = $1",
                user.id,
            )
            first_listen = await conn.fetchval(
                "SELECT MIN(played_at) FROM music_play_logs WHERE user_id = $1", user.id
            )
            last_listen = await conn.fetchval(
                "SELECT MAX(played_at) FROM music_play_logs WHERE user_id = $1", user.id
            )
            top_tracks = await conn.fetch(
                "SELECT track_title, track_url, COUNT(*) as play_count FROM music_play_logs WHERE user_id = $1 GROUP BY track_title, track_url ORDER BY play_count DESC LIMIT 5",
                user.id,
            )
            top_guild = await conn.fetchrow(
                "SELECT guild_id, COUNT(*) as play_count FROM music_play_logs WHERE user_id = $1 GROUP BY guild_id ORDER BY play_count DESC LIMIT 1",
                user.id,
            )
            active_day_row = await conn.fetchrow(
                """SELECT EXTRACT(DOW FROM played_at) AS dow, COUNT(*) as play_count
                FROM music_play_logs WHERE user_id = $1
                GROUP BY dow ORDER BY play_count DESC LIMIT 1""",
                user.id,
            )
            recent_tracks = await conn.fetch(
                """SELECT track_title, track_url FROM music_play_logs WHERE user_id = $1 ORDER BY played_at DESC LIMIT 5""",
                user.id,
            )

        day_names = [
            "Sunday",
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
        ]

        embed = discord.Embed(
            title=f"Music Profile: {user.display_name}",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=user.display_avatar.url)

        embed.add_field(name="Total Plays", value=f"{total_tracks:,}", inline=True)
        embed.add_field(name="Unique Tracks", value=f"{unique_tracks:,}", inline=True)
        embed.add_field(
            name="Time Listened", value=self.format_time(total_time), inline=True
        )

        if first_listen and last_listen:
            first_str = (
                first_listen.strftime("%b %d, %Y")
                if hasattr(first_listen, "strftime")
                else str(first_listen)[:10]
            )
            last_str = (
                last_listen.strftime("%b %d, %Y")
                if hasattr(last_listen, "strftime")
                else str(last_listen)[:10]
            )
            embed.add_field(
                name="Listening Since", value=f"{first_str} -> {last_str}", inline=False
            )

        if top_tracks:
            lines = []
            for i, row in enumerate(top_tracks):
                title = (row["track_title"] or "Unknown")[:50]
                url = row["track_url"]
                label = f"[{title}]({url})" if url else title
                lines.append(f"{i + 1}. {label} - **{row['play_count']}**")
            embed.add_field(name="Top Tracks", value="\n".join(lines), inline=False)

        if top_guild:
            guild_obj = self.bot.get_guild(top_guild["guild_id"])
            g_name = guild_obj.name if guild_obj else "Unknown Server"
            embed.add_field(
                name="Most Active Server",
                value=f"{g_name} ({top_guild['play_count']:,} plays)",
                inline=True,
            )

        if active_day_row:
            dow_index = int(active_day_row["dow"])
            embed.add_field(
                name="Busiest Day",
                value=f"{day_names[dow_index]} ({active_day_row['play_count']:,} plays)",
                inline=True,
            )

        if recent_tracks:
            lines = []
            for row in recent_tracks:
                title = (row["track_title"] or "Unknown")[:50]
                url = row["track_url"]
                label = f"[{title}]({url})" if url else title
                lines.append(f"- {label}")
            embed.add_field(
                name="Recently Played", value="\n".join(lines), inline=False
            )

        embed.set_footer(
            text=f"Requested by {ctx.author.name}",
            icon_url=ctx.author.display_avatar.url,
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="say",
        description="Manually use Text-to-Speech.",
    )
    @app_commands.describe(
        text="The message string content to read aloud.",
        language="Optional: language to use for this message only (does not change your saved config).",
        filters="Optional: comma-separated FFmpeg filter graph blocks for this message only (e.g., vibrato=f=15,asetrate=44100*1.2).",
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    async def say(
        self,
        ctx: commands.Context,
        *,
        text: str,
        language: Optional[str] = None,
        filters: Optional[str] = None,
    ):
        await ctx.typing()
        if ctx.voice_client:
            if not ctx.author.voice:
                return await ctx.send("You are not in a voice channel.")
            elif ctx.author.voice.channel != ctx.voice_client.channel:
                return await ctx.send("You are not in the same voice channel as me.")
        elif not ctx.voice_client and ctx.author.voice:
            await ctx.author.voice.channel.connect()
        elif not ctx.voice_client and not ctx.author.voice:
            return await ctx.send("You are not in a voice channel.")

        if language:
            try:
                supported_langs = gtts.lang.tts_langs()
            except Exception:
                supported_langs = None
            if supported_langs is not None and language not in supported_langs:
                return await ctx.send(
                    f"`{language}` is not a supported gTTS language code. "
                    f"Use `{ctx.prefix}tts langs` to see the list of available languages."
                )

        filters_list = filters.split(",") if filters else None

        await self._internal_say(ctx, text, language=language, filters=filters_list)
        await ctx.send(f"Saying `{text}`")

    @commands.hybrid_group(
        name="tts",
        description="Manage gTTS configuration.",
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    async def tts(self, ctx: commands.Context):
        return

    @tts.command(
        name="config",
        description="Set custom gTTS configuration for users, voice channels, and guilds.",
    )
    @app_commands.describe(
        target_type="The target type. ('user', 'channel', or 'guild')",
        target_id="Optional: Explicit channel ID to configure. (channel type only)",
        language="Language.",
        filters="Comma-separated FFmpeg filter graph blocks. (e.g., vibrato=f=15,asetrate=44100*1.2)",
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    async def tts_config(
        self,
        ctx: commands.Context,
        target_type: str,
        target_id: Optional[str] = None,
        language: Optional[str] = None,
        filters: Optional[str] = None,
    ):
        if target_type not in ["user", "channel", "guild"]:
            return await ctx.send("Target can only be: 'user', 'channel', or 'guild'.")

        if not self.db_pool:
            return await ctx.send("Database connection pool is not available.")

        if target_id and target_type != "channel":
            return await ctx.send("You can only configure channels via ID.")

        if target_type == "user":
            entity_id = ctx.author.id

        elif target_type == "guild":
            if not ctx.author.guild_permissions.manage_guild:
                return await ctx.send(
                    "You need the `Manage Server` permission to modify server-wide gTTS configuration."
                )
            entity_id = ctx.guild.id

        elif target_type == "channel":
            if not ctx.author.guild_permissions.manage_channels:
                return await ctx.send(
                    "You need the `Manage Channels` permission to modify channel-wide gTTS configuration."
                )
            if target_id:
                try:
                    entity_id = int(target_id)
                except ValueError:
                    return await ctx.send("The provided channel ID must be valid.")
            else:
                entity_id = ctx.channel.id

        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO tts_configs (entity_id, guild_id, entity_type, language, filters)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (entity_id, guild_id) DO UPDATE 
                SET language = EXCLUDED.language, filters = EXCLUDED.filters;
            """,
                entity_id,
                ctx.guild.id,
                target_type,
                language,
                filters,
            )

        await ctx.send(
            f"Successfully saved gTTS configuration for `{target_type}` on this server."
        )

    @tts.command(
        name="bind",
        description="Bind the current text channel as a TTS channel.",
    )
    @app_commands.describe(
        language="Optional TTS language.",
        filters="Optional FFmpeg filters for this TTS channel.",
    )
    @commands.has_guild_permissions(manage_channels=True)
    async def tts_bind(
        self,
        ctx: commands.Context,
        language: Optional[str] = None,
        filters: Optional[str] = None,
    ):
        if not self.db_pool:
            return await ctx.send("Database connection pool is not available.")

        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO tts_bindings (guild_id, text_channel_id, filters, language)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (text_channel_id) DO UPDATE 
                SET filters = EXCLUDED.filters, language = EXCLUDED.language;
            """,
                ctx.guild.id,
                ctx.channel.id,
                filters,
                language,
            )

        await ctx.send(f"Successfully binded {ctx.channel.mention} as a TTS channel.")

    @tts.command(
        name="reset",
        description="Reset gTTS configurations or channel bindings back to defaults.",
    )
    @app_commands.describe(
        scope="What scope to reset. ('self', 'user', 'channel', 'guild', or 'binding')",
        target_id="The ID of the target user/channel to reset (Required for 'user', 'channel', and 'binding' if admin).",
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    async def tts_reset(
        self,
        ctx: commands.Context,
        scope: str,
        target_id: Optional[str] = None,
    ):
        scope = scope.lower()
        valid_scopes = ["self", "user", "channel", "guild", "binding"]
        if scope not in valid_scopes:
            return await ctx.send(
                f"Invalid scope. Choose from: {', '.join(f'`{s}`' for s in valid_scopes)}"
            )

        if not self.db_pool:
            return await ctx.send("Database connection pool is not available.")

        await ctx.typing()

        if scope == "self":
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM tts_configs WHERE entity_id = $1 AND guild_id = $2 AND entity_type = 'user'",
                    ctx.author.id,
                    ctx.guild.id,
                )
            return await ctx.send(
                "Your personal gTTS configuration on this server has been reset to defaults."
            )

        if scope == "guild" and not ctx.author.guild_permissions.manage_guild:
            return await ctx.send(
                "You need the `Manage Server` permission to reset guild-wide configs."
            )

        if (
            scope in ["user", "channel", "binding"]
            and not ctx.author.guild_permissions.manage_channels
        ):
            return await ctx.send(
                "You need the `Manage Channels` permission to administratively wipe these parameters."
            )

        entity_id = None
        if target_id:
            try:
                entity_id = int(target_id)
            except ValueError:
                return await ctx.send(
                    "The provided target ID must be a valid numerical ID."
                )
        else:
            if scope == "channel":
                entity_id = ctx.channel.id
            elif scope == "binding":
                entity_id = ctx.channel.id
            elif scope == "guild":
                entity_id = ctx.guild.id
            elif scope == "user":
                return await ctx.send("Please provide a specific user ID to reset.")

        if scope == "user":
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM tts_configs WHERE entity_id = $1 AND guild_id = $2 AND entity_type = 'user'",
                    entity_id,
                    ctx.guild.id,
                )
            return await ctx.send(
                f"gTTS configuration for user ID `{entity_id}` has been cleared on this server."
            )

        elif scope == "channel":
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM tts_configs WHERE entity_id = $1 AND guild_id = $2 AND entity_type = 'channel'",
                    entity_id,
                    ctx.guild.id,
                )
            return await ctx.send(
                f"gTTS configuration for channel ID `{entity_id}` has been cleared."
            )

        elif scope == "guild":
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM tts_configs WHERE entity_id = $1 AND guild_id = $2 AND entity_type = 'guild'",
                    entity_id,
                    ctx.guild.id,
                )
            return await ctx.send(
                "Server-wide default gTTS configuration has been cleared."
            )

        elif scope == "binding":
            async with self.db_pool.acquire() as conn:
                deleted = await conn.fetchval(
                    "DELETE FROM tts_bindings WHERE text_channel_id = $1 RETURNING text_channel_id",
                    entity_id,
                )
            if deleted:
                return await ctx.send(
                    f"Text channel binding for channel ID `{entity_id}` has been un-bound successfully."
                )
            else:
                return await ctx.send(
                    f"No active gTTS binding was found on channel ID `{entity_id}`."
                )

    @tts.command(
        name="status",
        description="View your active gTTS configuration overrides on this server.",
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    async def tts_status(self, ctx: commands.Context):
        if not self.db_pool:
            return await ctx.send("Database connection pool is not available.")

        await ctx.typing()

        voice_channel_id = (
            ctx.author.voice.channel.id
            if ctx.author.voice and ctx.author.voice.channel
            else 0
        )

        async with self.db_pool.acquire() as conn:
            binding = await conn.fetchrow(
                "SELECT language, filters FROM tts_bindings WHERE text_channel_id = $1",
                ctx.channel.id,
            )

            rows = await conn.fetch(
                """SELECT entity_type, language, filters FROM tts_configs
                   WHERE (entity_id = $1 AND guild_id = $4)
                      OR (entity_id = $2 AND guild_id = $4)
                      OR (entity_id = $3 AND guild_id = $4)""",
                ctx.author.id,
                voice_channel_id,
                ctx.guild.id,
                ctx.guild.id,
            )

        mapping = {r["entity_type"]: r for r in rows}

        embed = discord.Embed(
            title="gTTS Configuration Hierarchy Status",
            color=discord.Color.blue(),
            description="Settings resolve from top to bottom. The first active configuration found is used.",
        )

        if binding:
            embed.add_field(
                name="Text Channel Binding (Active here)",
                value=f"**Language:** `{binding['language']}`\n**Filters:** `{binding['filters'] or 'None'}`",
                inline=False,
            )
        else:
            embed.add_field(
                name="Text Channel Binding",
                value="*No explicit binding for this channel.*",
                inline=False,
            )

        user_cfg = mapping.get("user")
        if user_cfg:
            embed.add_field(
                name=f"Your Per-Server Overrides ({ctx.author.display_name})",
                value=f"**Language:** `{user_cfg['language']}`\n**Filters:** `{user_cfg['filters'] or 'None'}`",
                inline=False,
            )
        else:
            embed.add_field(
                name="Your Per-Server Overrides",
                value="*No personal overrides set on this server.*",
                inline=False,
            )

        vc_cfg = mapping.get("channel")
        if vc_cfg:
            embed.add_field(
                name="Current Voice Channel Overrides",
                value=f"**Language:** `{vc_cfg['language']}`\n**Filters:** `{vc_cfg['filters'] or 'None'}`",
                inline=False,
            )
        else:
            embed.add_field(
                name="Voice Channel Overrides",
                value="*No voice channel specific overrides encountered.*",
                inline=False,
            )

        guild_cfg = mapping.get("guild")
        if guild_cfg:
            embed.add_field(
                name=f"Server-Wide Defaults ({ctx.guild.name})",
                value=f"**Language:** `{guild_cfg['language']}`\n**Filters:** `{guild_cfg['filters'] or 'None'}`",
                inline=False,
            )
        else:
            embed.add_field(
                name="Server-Wide Defaults",
                value="*No custom server defaults set. Using gTTS defaults.*",
                inline=False,
            )

        await ctx.send(embed=embed)

    @tts.command(
        name="langs",
        description="List all available gTTS languages.",
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    async def tts_langs(self, ctx: commands.Context):
        await ctx.typing()
        try:
            all_langs = gtts.lang.tts_langs()
            voices = [f"`{code}`: {name}" for code, name in all_langs.items()]

            if not voices:
                return await ctx.send("No voices reported by gTTS.")

            voices_per_page = 25
            pages = []

            chunks = [
                voices[i : i + voices_per_page]
                for i in range(0, len(voices), voices_per_page)
            ]
            total_pages = len(chunks)

            for index, chunk in enumerate(chunks):
                embed = discord.Embed(
                    title="Available TTS Languages",
                    color=discord.Color.green(),
                    description="\n".join(chunk),
                )

                embed.set_footer(
                    text=f"Page {index + 1} of {total_pages} | Total Voices: {len(voices)}"
                )
                pages.append(embed)

            view = VoicePaginator(pages=pages, timeout=120.0)
            view.message = await ctx.send(embed=pages[0], view=view)

        except Exception as e:
            await ctx.send(f"Failed to retrieve gTTS languages: {e}")

    @commands.hybrid_group(
        name="playlist",
        description="Manage your playlists.",
        invoke_without_command=True,
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    async def playlist(self, ctx: commands.Context):
        await ctx.send(
            "Usage: `playlist create <name>`, `playlist add <name> <url>`, `playlist play <name>`",
        )

    @playlist.command(name="create", description="Create a music playlist.")
    @app_commands.describe(name="The name of the playlist to create.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def playlist_create(self, ctx: commands.Context, name: str):
        await ctx.typing()
        if not self.db_pool:
            await ctx.send(
                "Database is currently not available, sorry. (is the database connected?)."
            )
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO music_playlists (owner_id, name) VALUES ($1, $2)",
                    ctx.author.id,
                    name,
                )
            await ctx.send(f"Successfully created playlist with name `{name}`")
        except asyncpg.UniqueViolationError:
            await ctx.send("This playlist already exists.")

    @playlist.command(
        name="add",
        description="Add a track or an entire playlist to an existing playlist.",
    )
    @app_commands.describe(
        name="The name of the playlist to add to.",
        url="URL of the track or playlist to add.",
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    async def playlist_add(self, ctx: commands.Context, name: str, url: str):
        await ctx.typing()
        if not self.db_pool:
            await ctx.send(
                "Database is currently not available, sorry. (is the database connected?)"
            )
            return

        try:
            info = await self.fetch_yt_info(url, download=False)
        except Exception as e:
            await ctx.send(f"Failed to fetch info for URL: {e}")
            return

        if not info:
            await ctx.send("Could not retrieve information for the provided URL.")
            return

        is_playlist = "entries" in info and info["entries"] is not None

        async with self.db_pool.acquire() as conn:
            pid = await conn.fetchval(
                "SELECT id FROM music_playlists WHERE owner_id = $1 AND name = $2",
                ctx.author.id,
                name,
            )
            if not pid:
                await ctx.send(f"You don't have a playlist named `{name}`")
                return

            start_pos = await conn.fetchval(
                "SELECT COALESCE(MAX(position), 0) + 1 FROM music_playlist_entries WHERE playlist_id = $1",
                pid,
            )

            if is_playlist:
                valid_entries = [e for e in info["entries"] if e and "url" in e]
                if not valid_entries:
                    await ctx.send(
                        "The provided playlist URL contains no valid tracks."
                    )
                    return

                tracks_to_add = []
                for entry in valid_entries:
                    track_url = entry.get("webpage_url") or entry.get("url")
                    track_title = entry.get("title", "Unknown")
                    track_duration = entry.get("duration") or 0

                    tracks_to_add.append(
                        (
                            pid,
                            track_url,
                            track_title,
                            start_pos + len(tracks_to_add),
                            int(track_duration),
                        )
                    )

                if tracks_to_add:
                    await conn.executemany(
                        "INSERT INTO music_playlist_entries (playlist_id, url, title, position, duration) VALUES ($1, $2, $3, $4, $5)",
                        tracks_to_add,
                    )
                    await ctx.send(
                        f"Successfully added {len(tracks_to_add)} tracks from the playlist to `{name}`."
                    )
                else:
                    await ctx.send(
                        "No valid tracks found in the provided playlist URL."
                    )
            else:
                track_url = info.get("webpage_url") or url
                track_title = info.get("title", "Unknown")
                track_duration = info.get("duration") or 0

                await conn.execute(
                    "INSERT INTO music_playlist_entries (playlist_id, url, title, position, duration) VALUES ($1, $2, $3, $4, $5)",
                    pid,
                    track_url,
                    track_title,
                    start_pos,
                    int(track_duration),
                )
                await ctx.send(
                    f"Added `{track_title}` to playlist `{name}` successfully."
                )

    @playlist.command(name="play", description="Play a playlist.")
    @app_commands.describe(name="The name of the playlist to play.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def playlist_play(self, ctx: commands.Context, name: str):
        await ctx.typing()
        if ctx.author.voice is None:
            await ctx.send("You are not in a voice channel.")
            return
        elif ctx.voice_client and ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You are not in the same voice channel as me.")
            return
        if not self.db_pool:
            await ctx.send(
                "Database is currently not available, sorry. (is the database connected?)"
            )
            return
        async with self.db_pool.acquire() as conn:
            pid = await conn.fetchval(
                "SELECT id FROM music_playlists WHERE owner_id = $1 AND name = $2",
                ctx.author.id,
                name,
            )
            if not pid:
                await ctx.send(f"Playlist `{name}` does not exist.")
                return
            rows = await conn.fetch(
                "SELECT url, title FROM music_playlist_entries WHERE playlist_id = $1 ORDER BY position",
                pid,
            )

        if not await self.connect_to_channel(ctx):
            return

        if not rows:
            await ctx.send("This playlist does not have any tracks, yet.")
            return

        state = self.get_state(ctx.guild.id)
        for row in rows:
            state.queue.append((row["url"], [], False, row["title"], ctx.author))

        await ctx.send(f"Enqueued {len(rows)} tracks from playlist `{name}`")
        if not ctx.voice_client.is_playing() or not ctx.voice_client:
            await self.play_next(ctx, ctx.guild.id)

    @playlist.command(
        name="stream", description="Stream a playlist without downloading to disk."
    )
    @app_commands.describe(name="The name of the playlist to stream.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def playlist_stream(self, ctx: commands.Context, name: str):
        await ctx.typing()
        if ctx.author.voice is None:
            await ctx.send("You are not in a voice channel.")
            return
        elif ctx.voice_client and ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You are not in the same voice channel as me.")
            return
        if not self.db_pool:
            await ctx.send(
                "Database is currently not available, sorry. (is the database connected?)"
            )
            return
        async with self.db_pool.acquire() as conn:
            pid = await conn.fetchval(
                "SELECT id FROM music_playlists WHERE owner_id = $1 AND name = $2",
                ctx.author.id,
                name,
            )
            if not pid:
                await ctx.send(f"Playlist `{name}` does not exist.")
                return
            rows = await conn.fetch(
                "SELECT url, title FROM music_playlist_entries WHERE playlist_id = $1 ORDER BY position",
                pid,
            )
        if not await self.connect_to_channel(ctx):
            return
        if not rows:
            await ctx.send("This playlist does not have any tracks, yet.")
            return
        state = self.get_state(ctx.guild.id)
        for row in rows:
            state.queue.append((row["url"], [], True, row["title"], ctx.author))
        await ctx.send(f"Streaming {len(rows)} tracks from playlist `{name}`")
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            await self.play_next(ctx, ctx.guild.id)

    @playlist.command(name="list", description="List your current playlists.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def playlist_list(self, ctx: commands.Context):
        await ctx.typing()
        if not self.db_pool:
            await ctx.send(
                "Database is currently not available, sorry. (is the database connected?)"
            )
            return
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT p.name, COUNT(*) AS track_count, COALESCE(SUM(e.duration), 0) AS total_duration
                FROM music_playlists p
                LEFT JOIN music_playlist_entries e ON e.playlist_id = p.id
                WHERE p.owner_id = $1
                GROUP BY p.name
                ORDER BY p.name""",
                ctx.author.id,
            )
        if not rows:
            await ctx.send("You don't have any playlists, yet.")
            return
        embed = discord.Embed(
            title=f"{ctx.author.display_name}'s Playlists",
            color=discord.Color.og_blurple(),
        )
        lines = []
        for r in rows:
            duration_str = (
                self.format_time(r["total_duration"]) if r["total_duration"] else "0:00"
            )
            lines.append(
                f"**{r['name']}** - {r['track_count']} track(s), {duration_str}"
            )
        embed.description = "\n".join(lines)
        embed.set_footer(
            text=f"Requested by {ctx.author.name}",
            icon_url=ctx.author.display_avatar.url,
        )
        await ctx.send(embed=embed)

    @playlist.command(name="view", description="View the contents of a playlist.")
    @app_commands.describe(name="The name of the playlist to view.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def playlist_view(self, ctx: commands.Context, name: str):
        await ctx.typing()
        if not self.db_pool:
            await ctx.send(
                "Database is currently not available, sorry. (is the database connected?)"
            )
            return
        async with self.db_pool.acquire() as conn:
            pid = await conn.fetchval(
                "SELECT id FROM music_playlists WHERE owner_id = $1 AND name = $2",
                ctx.author.id,
                name,
            )
            if not pid:
                await ctx.send(f"You don't have a playlist named `{name}`")
                return
            rows = await conn.fetch(
                "SELECT position, title, url, duration FROM music_playlist_entries WHERE playlist_id = $1 ORDER BY position",
                pid,
            )
        if not rows:
            await ctx.send(f"Playlist `{name}` has no tracks yet.")
            return
        embed = discord.Embed(
            title=f"Playlist: {name}", color=discord.Color.og_blurple()
        )
        lines = []
        for row in rows:
            title = (row["title"] or "Unknown")[:50]
            label = f"[{title}]({row['url']})" if row["url"] else title
            duration_str = self.format_time(row["duration"]) if row["duration"] else "?"
            lines.append(f"`{row['position']}.` {label} - {duration_str}")
        embed.description = "\n".join(lines)
        embed.set_footer(
            text=f"{len(rows)} tracks(s) | Requested by {ctx.author.name}",
            icon_url=ctx.author.display_avatar.url,
        )
        await ctx.send(embed=embed)

    @playlist.command(
        name="remove", description="Remove a track from a playlist by its position."
    )
    @app_commands.describe(
        name="The name of the playlist.",
        position="The position of the track to remove.",
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    async def playlist_remove(self, ctx: commands.Context, name: str, position: int):
        await ctx.typing()
        if not self.db_pool:
            await ctx.send(
                "Database is currently not available, sorry. (is the database connected?"
            )
            return
        async with self.db_pool.acquire() as conn:
            pid = await conn.fetchval(
                "SELECT id FROM music_playlists WHERE owner_id = $1 AND name = $2",
                ctx.author.id,
                name,
            )
            if not pid:
                await ctx.send(f"You don't have a playlist named `{name}`")
                return
            deleted = await conn.fetchval(
                "DELETE FROM music_playlist_entries WHERE playlist_id = $1 AND position = $2 RETURNING title",
                pid,
                position,
            )
            if not deleted:
                await ctx.send(
                    f"No track at position `{position}` in playlist `{name}`"
                )
                return
            await conn.execute(
                "UPDATE music_playlist_entries SET position = position - 1 WHERE playlist_id = $1 AND position > $2",
                pid,
                position,
            )
        await ctx.send(
            f"Removed track `{deleted}` (position {position}) from playlist `{name}`"
        )

    @playlist.command(name="delete", description="Delete an existing playlist.")
    @app_commands.describe(name="The playlist to delete.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def playlist_delete(self, ctx: commands.Context, name: str):
        await ctx.typing()
        if not self.db_pool:
            await ctx.send(
                "Database is currently not available, sorry. (is the database connected?)"
            )
            return
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM music_playlists WHERE owner_id = $1 AND name = $2",
                ctx.author.id,
                name,
            )
        await ctx.send(f"Successfully deleted playlist `{name}`")


async def setup(bot):
    await bot.add_cog(Audio(bot))
