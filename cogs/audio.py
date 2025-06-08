import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import spotipy
import bot_info
import os
import asyncio
import random
from urllib.parse import urlparse, parse_qs
from collections import deque
from datetime import datetime
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'outtmpl': 'vids/%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'extract_flat': 'in_playlist',
    'quiet': True,
    'no_warnings': True
}

spotify = spotipy.Spotify(auth_manager=spotipy.SpotifyClientCredentials(
    client_id=bot_info.data['spotify_client_id'],
    client_secret=bot_info.data['spotify_client_secret']
))

class Audio(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues = {}
        self.currently_playing = {}
        self.loop_mode = {}
        self.original_queues = {}
        self.metadata_cache = {}
        self.executor = ThreadPoolExecutor(max_workers=4)

    def get_queue(self, guild_id):
        if guild_id not in self.queues:
            self.queues[guild_id] = deque()
        return self.queues[guild_id]

    async def run_in_executor(self, func, *args):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, func, *args)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        voice_client = member.guild.voice_client
        if voice_client is None:
            return
        await asyncio.sleep(5)
        if len(voice_client.channel.members) == 1 and voice_client.channel.members[0] == self.bot.user:
            guild_id = member.guild.id
            if guild_id in self.queues:
                self.queues[guild_id].clear()
            if guild_id in self.currently_playing:
                del self.currently_playing[guild_id]
            if guild_id in self.loop_mode:
                del self.loop_mode[guild_id]
            await voice_client.disconnect()

    async def connect_to_channel(self, ctx: commands.Context) -> bool:
        if ctx.voice_client:
            if ctx.voice_client.is_playing():
                if not (ctx.author.voice and ctx.author.voice.channel == ctx.voice_client.channel):
                    await ctx.send("You must be in the same voice channel as me to play audio.")
                    return False
            if ctx.author.voice and ctx.author.voice.channel != ctx.voice_client.channel:
                await ctx.voice_client.move_to(ctx.author.voice.channel)
                await ctx.send(f"Moved to {ctx.author.voice.channel.name}.")
            return True
        if ctx.author.voice:
            channel = ctx.author.voice.channel
            await channel.connect()
            await ctx.send(f"Connected to {channel.name}.")
            return True
        else:
            await ctx.send("You are not connected to a voice channel.")
            return False

    async def process_spotify_url(self, url: str) -> list:
        try:
            if 'track' in url:
                track = await self.run_in_executor(spotify.track, url)
                return [f"{track['name']} {track['artists'][0]['name']}"]
            elif 'playlist' in url:
                playlist = await self.run_in_executor(spotify.playlist, url)
                tracks = []
                for item in playlist['tracks']['items']:
                    track = item['track']
                    tracks.append(f"{track['name']} {track['artists'][0]['name']}")
                return tracks
            elif 'album' in url:
                album = await self.run_in_executor(spotify.album, url)
                tracks = []
                for track in album['tracks']['items']:
                    tracks.append(f"{track['name']} {track['artists'][0]['name']}")
                return tracks
            elif 'artist' in url:
                top_tracks = await self.run_in_executor(spotify.artist_top_tracks, url)
                tracks = []
                for track in top_tracks['tracks'][:10]:
                    tracks.append(f"{track['name']} {track['artists'][0]['name']}")
                return tracks
        except Exception:
            return None

    async def play_next_stream(self, ctx: commands.Context):
        guild_id = ctx.guild.id
        queue = self.get_queue(guild_id)

        if self.loop_mode.get(guild_id) == "track":
            if guild_id in self.currently_playing:
                current = self.currently_playing[guild_id]
                if current.get('is_stream', False):
                    return await self.play_stream(ctx, current['url'], current['filters'])
                else:
                    return await self.play_audio(ctx, current['url'], current['filters'])

        if not queue and self.loop_mode.get(guild_id) == "queue":
            if guild_id in self.original_queues and self.original_queues[guild_id]:
                self.queues[guild_id] = deque(self.original_queues[guild_id])
                queue = self.get_queue(guild_id)
                await ctx.send("Restarting queue loop.")
                return await self.play_next_stream(ctx)

        if queue:
            url, filters, is_stream, title = queue.popleft()
            if guild_id not in self.original_queues and self.loop_mode.get(guild_id) == "queue":
                self.original_queues[guild_id] = list(queue) + [(url, filters, is_stream, title)]

            if is_stream:
                await self.play_stream(ctx, url, filters)
            else:
                await self.play_audio(ctx, url, filters)

    async def play_next(self, ctx: commands.Context):
        guild_id = ctx.guild.id
        queue = self.get_queue(guild_id)
        if self.loop_mode.get(guild_id) == "track":
            if guild_id in self.currently_playing:
                current = self.currently_playing[guild_id]
                if current.get('is_stream', False):
                    return await self.play_stream(ctx, current['url'], current['filters'])
                else:
                    return await self.play_audio(ctx, current['url'], current['filters'])
        if not queue and self.loop_mode.get(guild_id) == "queue":
            if guild_id in self.original_queues and self.original_queues[guild_id]:
                self.queues[guild_id] = deque(self.original_queues[guild_id])
                queue = self.get_queue(guild_id)
                await ctx.send("Restarting queue loop.")
                return await self.play_next(ctx)
        if queue:
            url, filters, is_stream, title = queue.popleft()
            if self.loop_mode.get(guild_id) == "queue" and guild_id not in self.original_queues:
                self.original_queues[guild_id] = list(queue) + [(url, filters, is_stream, title)]
            if is_stream:
                await self.play_stream(ctx, url, filters)
            else:
                await self.play_audio(ctx, url, filters)

    async def process_playlist(self, ctx: commands.Context, url: str, filters=None, is_stream: bool = False):
        try:
            if 'spotify.com' in url:
                queries = await self.process_spotify_url(url)
                if not queries:
                    await ctx.send("Failed to process Spotify playlist.")
                    return
                queue = self.get_queue(ctx.guild.id)
                search_tasks = [self.search_youtube(query) for query in queries]
                youtube_results = await asyncio.gather(*search_tasks)
                youtube_urls = [url for url in youtube_results if url]
                if not youtube_urls:
                    await ctx.send("Could not find any YouTube videos which match the Spotify tracks.")
                    return
                valid_results = [r for r in youtube_results if r]
                for result in valid_results:
                    youtube_url = result['url']
                    title = result['title']
                    queue.append((youtube_url, filters, is_stream, title))
                await ctx.send(f"Added {len(youtube_urls)} tracks from the Spotify playlist to the queue.")
                if not ctx.voice_client or not ctx.voice_client.is_playing():
                    if is_stream:
                        await self.play_next_stream(ctx)
                    else:
                        await self.play_next(ctx)
                return
            def sync_playlist_process():
                with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                    return ydl.extract_info(url, download=False)
            info = await self.run_in_executor(sync_playlist_process)
            if 'entries' not in info:
                if is_stream:
                    return await self.play_stream(ctx, url, filters)
                else:
                    return await self.play_audio(ctx, url, filters)
            entries = [e for e in info['entries'] if e]
            queue = self.get_queue(ctx.guild.id)
            for entry in entries:
                title = entry.get('title', 'Unknown Title')
                queue.append((entry['url'], filters, is_stream, title))
            if self.loop_mode.get(ctx.guild.id) == "queue":
                self.original_queues[ctx.guild.id] = list(queue)
            await ctx.send(f"Added {len(entries)} tracks from {info.get('title', 'Unknown Playlist')}.")
            if not ctx.voice_client or not ctx.voice_client.is_playing():
                if is_stream:
                    await self.play_next_stream(ctx)
                else:
                    await self.play_next(ctx)
        except Exception as e:
            await ctx.send(f"Error processing playlist: {e}")

    async def search_youtube(self, query: str) -> Optional[str]:
        try:
            def sync_search():
                with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                    results = ydl.extract_info(f"ytsearch:{query}", download=False)
                    if results and 'entries' in results and results['entries']:
                        entry = results['entries'][0]
                        return {
                            'url': entry['url'],
                            'title': entry.get('title', 'Unknown Title')
                        }
                return None
            result = await self.run_in_executor(sync_search)
            return result
        except Exception:
            return None

    async def extract_info(self, url: str):
        def sync_extract():
            with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                return ydl.extract_info(url, download=True)
        return await self.run_in_executor(sync_extract)

    async def play_audio(self, ctx: commands.Context, url: str, filters=None):
        if 'spotify.com' in url and 'track' in url:
            query = await self.process_spotify_url(url)
            if query:
                youtube_url = await self.search_youtube(query[0])
                if youtube_url:
                    url = youtube_url['url']
                else:
                    await ctx.send("Could not find any YouTube video for this Spotify track.")
                    return
        cached_info = self.metadata_cache.get(url)
        loop_mode_active = self.loop_mode.get(ctx.guild.id) == "track"
        if cached_info and loop_mode_active:
            info = cached_info
            file_path = yt_dlp.YoutubeDL(YDL_OPTIONS).prepare_filename(info)
        else:
            info = await self.extract_info(url)
            file_path = yt_dlp.YoutubeDL(YDL_OPTIONS).prepare_filename(info)
            self.metadata_cache[url] = info
        if not os.path.exists(file_path):
            info = await self.extract_info(url)
            self.metadata_cache[url] = info
        if ctx.voice_client:
            if ctx.voice_client.is_playing() and ctx.author.voice.channel != ctx.voice_client.channel:
                await ctx.send("You must be in the same voice channel as me to play audio.")
                return
            if ctx.author.voice and ctx.author.voice.channel != ctx.voice_client.channel:
                moved = await self.connect_to_channel(ctx)
                if not moved:
                    return
        else:
            if ctx.author.voice and ctx.author.voice.channel:
                connected = await self.connect_to_channel(ctx)
                if not connected:
                    return
            else:
                await ctx.send("You are not connected to a voice channel.")
                return
        voice_client = ctx.voice_client
        if voice_client:
            ffmpeg_options = {'options': '-vn'}
            if filters:
                ffmpeg_options['options'] += f" -af {','.join(filters)}"
            source = discord.FFmpegPCMAudio(file_path, **ffmpeg_options)
            ctx.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self.cleanup_file_and_play_next(ctx, file_path), self.bot.loop))
            self.currently_playing[ctx.guild.id] = {
                'info': info,
                'url': url,
                'filters': filters,
                'start_time': datetime.now(),
                'position': 0,
                'is_stream': False
            }
            embed = discord.Embed(
                title=f"Playing - {info['title'] or 'Unknown'}",
                description=f"URL: {info['webpage_url'] or 'Unknown'}",
                color=discord.Color.og_blurple(),
                timestamp=discord.utils.utcnow()
            )
            raw_date = info.get('upload_date')
            upload_date = datetime.strptime(raw_date, '%Y%m%d').strftime('%B %d, %Y') if raw_date else "Unknown"
            embed.add_field(name="Length", value=info.get('duration_string', 'Unknown'), inline=True)
            embed.add_field(name="Author", value=info.get('uploader', 'Unknown'), inline=True)
            embed.add_field(name="Channel", value=info.get('uploader_url', 'Unknown'), inline=True)
            if info.get('view_count'):
                embed.add_field(name="Views", value=f"{info['view_count']:,}", inline=True)
            if info.get('like_count'):
                embed.add_field(name="Likes", value=f"{info['like_count']:,}", inline=True)
            embed.add_field(name="Filters", value=", ".join(filters) if filters else "None", inline=True)
            embed.add_field(name="Published At", value=upload_date, inline=True)
            embed.set_image(url=info.get('thumbnail'))
            embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
            await ctx.send(embed=embed)

    async def cleanup_file_and_play_next(self, ctx, file_path):
        if self.loop_mode.get(ctx.guild.id) != "track":
            if os.path.exists(file_path):
                await asyncio.sleep(1)
                os.remove(file_path)
        await self.play_next(ctx)

    def format_time(self, seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        else:
            return f"{m}:{s:02d}"

    def parse_time(self, t: str) -> float:
        t = t.strip()
        if ':' in t:
            parts = list(map(float, t.split(':')))
            if len(parts) == 2:
                return parts[0] * 60 + parts[1]
            elif len(parts) == 3:
                return parts[0] * 3600 + parts[1] * 60 + parts[2]
            else:
                raise ValueError("Invalid time format.")
        elif '.' in t or t.replace('.', '', 1).isdigit():
            return float(t)
        elif t.isdigit():
            return float(t)
        else:
            raise ValueError(f"Unrecognized time format: {t}")

    def parse_seek_position(self, pos_str: str, total_duration: float, current_pos: float) -> float:
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
        formats = info.get('formats', [])
        formats.sort(key=lambda f: f.get('filesize') or 0, reverse=True)
        for f in formats:
            if f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                if f.get('protocol', '').startswith(('http', 'https')):
                    return f['url']
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            result = ydl.extract_info(info['webpage_url'], download=False)
            return result['url']

    async def play_stream_from_position(self, ctx: commands.Context, url: str, filters, position: float):
        current_data = self.currently_playing.get(ctx.guild.id)
        if not current_data or 'info' not in current_data:
            def sync_extract_info():
                with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                    return ydl.extract_info(url, download=False)
            info = await self.run_in_executor(sync_extract_info)
        else:
            info = current_data['info']
        stream_url = self.get_valid_stream_url(info)
        before_options = f"-ss {position}"
        ffmpeg_options = {
            'before_options': before_options,
            'options': '-vn'
        }
        if filters:
            ffmpeg_options['options'] += f" -af {','.join(filters)}"
        source = discord.FFmpegPCMAudio(stream_url, **ffmpeg_options)
        ctx.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self.cleanup_file_and_play_next(ctx, ""), self.bot.loop))
        self.currently_playing[ctx.guild.id] = {
            'info': info,
            'url': url,
            'filters': filters,
            'start_time': datetime.now(),
            'position': position,
            'is_stream': True
        }

    async def play_audio_from_position(self, ctx: commands.Context, url: str, filters, position: float):
        current_data = self.currently_playing.get(ctx.guild.id)
        if not current_data or 'info' not in current_data:
            def sync_extract_info():
                with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                    return ydl.extract_info(url, download=True)
            info = await self.run_in_executor(sync_extract_info)
        else:
            info = current_data['info']
        file_path = yt_dlp.YoutubeDL(YDL_OPTIONS).prepare_filename(info)
        before_options = f"-ss {position}"
        ffmpeg_options = {
            'before_options': before_options,
            'options': '-vn'
        }
        if filters:
            ffmpeg_options['options'] += f" -af {','.join(filters)}"
        source = discord.FFmpegPCMAudio(file_path, **ffmpeg_options)
        ctx.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self.cleanup_file_and_play_next(ctx, file_path), self.bot.loop))
        self.currently_playing[ctx.guild.id] = {
            'info': info,
            'url': url,
            'filters': filters,
            'start_time': datetime.now(),
            'position': position,
            'is_stream': False
        }

    @commands.hybrid_command(name="join", description="Join a voice channel.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def join(self, ctx: commands.Context):
        await ctx.typing()
        await self.connect_to_channel(ctx)

    @commands.hybrid_command(name="leave", description="Leave the current voice channel.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def leave(self, ctx: commands.Context):
        await ctx.typing()
        if ctx.author.voice is None or ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You are not in the same voice channel as me.")
            return
        if ctx.voice_client:
            queue = self.get_queue(ctx.guild.id)
            queue.clear()
            await ctx.send(f"Disconnected from {ctx.voice_client.channel}.")
            await ctx.voice_client.disconnect()
        else:
            await ctx.send("I am not connected to a voice channel.")

    @commands.hybrid_command(name="play", description="Play an audio/song or playlist from a given URL. Any URL that yt-dlp supports also works.", aliases=["p"])
    @app_commands.describe(url="The URL of the audio/song or playlist to play.", attachment="The attachment media file to use for playing.", filters="A comma-separated list of filters to apply to the audio.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def play(self, ctx: commands.Context, url: str = None, attachment: Optional[discord.Attachment] = None, filters: str = None):
        await ctx.typing()
        if ctx.message.attachments or attachment:
            source_url = attachment.url if attachment else ctx.message.attachments[0].url
            if not filters:
                message_content = ctx.message.content[len(ctx.prefix + ctx.invoked_with):].strip()
                filters = message_content
        else:
            if not url:
                await ctx.send("Please provide an URL or an attachment file.")
                return
            source_url = url
        filters_list = filters.split(',') if filters else []
        is_playlist = False
        if source_url:
            playlist_patterns = [
                'youtube.com/playlist',
                'youtube.com/watch?list=',
                'youtube.com/playlist?list=',
                'youtu.be/playlist?list=',
                'spotify.com/playlist',
                'spotify.com/album',
                'spotify.com/artist'
            ]
            is_playlist = any(pattern in source_url.lower() for pattern in playlist_patterns)
            if 'youtube.com/watch' in source_url.lower() and 'list=' in source_url.lower():
                parsed = urlparse(source_url)
                query = parse_qs(parsed.query)
                if 'v' in query:
                    source_url = f"https://www.youtube.com/watch?v={query['v'][0]}"
                    is_playlist = False
        if is_playlist:
            await self.process_playlist(ctx, source_url, filters_list, is_stream=False)
            return
        queue = self.get_queue(ctx.guild.id)
        if ctx.voice_client and ctx.voice_client.is_playing() and ctx.author.voice and ctx.author.voice.channel == ctx.voice_client.channel:
            title = await self.get_title(source_url)
            queue.append((source_url, filters_list, False, title))
            await ctx.send(f"Added {url} to the queue.")
            if self.loop_mode.get(ctx.guild.id) == "queue":
                self.original_queues[ctx.guild.id] = list(queue)
        elif ctx.voice_client and ctx.voice_client.is_playing() and (ctx.author.voice is None or ctx.author.voice.channel != ctx.voice_client.channel):
            await ctx.send("You must be in the same voice channel as me to play audio.")
            return
        elif ctx.voice_client is None or (ctx.author.voice and ctx.author.voice.channel != ctx.voice_client.channel):
            connected = await self.connect_to_channel(ctx)
            if not connected:
                return
            await self.play_audio(ctx, source_url, filters=filters_list)
        else:
            await self.play_audio(ctx, source_url, filters=filters_list)

    @commands.hybrid_command(name="stream", description="Stream an audio/song or playlist from a given URL without downloading.", aliases=["strm", "s"])
    @app_commands.describe(url="The URL of the audio/song or playlist to stream.", attachment="The attachment media file to use for streaming.", filters="A comma-separated list of filters to apply to the audio.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def stream(self, ctx: commands.Context, url: str = None, attachment: Optional[discord.Attachment] = None, filters: str = None):
        await ctx.typing()
        if ctx.message.attachments or attachment:
            source_url = attachment.url if attachment else ctx.message.attachments[0].url
            if not filters:
                message_content = ctx.message.content[len(ctx.prefix + ctx.invoked_with):].strip()
                filters = message_content
        else:
            if not url:
                await ctx.send("Please provide an URL or an attachment file.")
                return
            source_url = url
        filters_list = filters.split(',') if filters else []
        is_playlist = False
        if source_url:
            playlist_patterns = [
                'youtube.com/playlist',
                'youtube.com/watch?list=',
                'youtube.com/playlist?list=',
                'youtu.be/playlist?list=',
                'spotify.com/playlist',
                'spotify.com/album',
                'spotify.com/artist'
            ]
            is_playlist = any(pattern in source_url.lower() for pattern in playlist_patterns)
            if 'youtube.com/watch' in source_url.lower() and 'list=' in source_url.lower():
                parsed = urlparse(source_url)
                query = parse_qs(parsed.query)
                if 'v' in query:
                    source_url = f"https://www.youtube.com/watch?v={query['v'][0]}"
                    is_playlist = False
        if is_playlist:
            await self.process_playlist(ctx, source_url, filters_list, is_stream=True)
            return
        queue = self.get_queue(ctx.guild.id)
        if ctx.voice_client and ctx.voice_client.is_playing() and ctx.author.voice and ctx.author.voice.channel == ctx.voice_client.channel:
            title = await self.get_title(source_url)
            queue.append((source_url, filters_list, True, title))
            await ctx.send(f"Added {url} to the queue.")
        elif ctx.voice_client and ctx.voice_client.is_playing() and (ctx.author.voice is None or ctx.author.voice.channel != ctx.voice_client.channel):
            await ctx.send("You must be in the same voice channel as me to play audio.")
            return
        elif ctx.voice_client is None or (ctx.author.voice and ctx.author.voice.channel != ctx.voice_client.channel):
            connected = await self.connect_to_channel(ctx)
            if not connected:
                return
            await self.play_stream(ctx, source_url, filters_list)
        else:
            await self.play_stream(ctx, source_url, filters_list)

    async def play_stream(self, ctx: commands.Context, url: str, filters=None):
        if 'spotify.com' in url and 'track' in url:
            query = await self.process_spotify_url(url)
            if query:
                youtube_url = await self.search_youtube(query[0])
                if youtube_url:
                    url = youtube_url['url']
                else:
                    await ctx.send("Could not find any YouTube video for this Spotify track.")
                    return
        def sync_extract_info():
            with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                return ydl.extract_info(url, download=False)
        info = await self.run_in_executor(sync_extract_info)
        stream_url = self.get_valid_stream_url(info)
        if ctx.voice_client:
            if ctx.voice_client.is_playing() and ctx.author.voice.channel != ctx.voice_client.channel:
                await ctx.send("You must be in the same voice channel as me to play audio.")
                return
            if ctx.author.voice and ctx.author.voice.channel != ctx.voice_client.channel:
                moved = await self.connect_to_channel(ctx)
                if not moved:
                    return
        else:
            if ctx.author.voice:
                connected = await self.connect_to_channel(ctx)
                if not connected:
                    return
            else:
                await ctx.send("You are not connected to a voice channel.")
                return
        ffmpeg_options = {
            'options': '-vn'
        }
        if filters:
            ffmpeg_options['options'] += f" -af {','.join(filters)}"
        source = discord.FFmpegPCMAudio(stream_url, **ffmpeg_options)
        ctx.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self.play_next_stream(ctx), self.bot.loop))
        self.currently_playing[ctx.guild.id] = {
            'info': info,
            'url': url,
            'filters': filters,
            'start_time': datetime.now(),
            'position': 0,
            'is_stream': True
        }
        embed = discord.Embed(
            title=f"Streaming - {info['title']}",
            description=f"URL: {info['webpage_url']}",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow()
        )
        raw_date = info.get('upload_date')
        upload_date = datetime.strptime(raw_date, '%Y%m%d').strftime('%B %d, %Y') if raw_date else "Unknown"
        embed.add_field(name="Length", value=info.get('duration_string', 'Unknown'), inline=True)
        embed.add_field(name="Author", value=info.get('uploader', 'Unknown'), inline=True)
        embed.add_field(name="Channel", value=info.get('uploader_url', 'Unknown'), inline=True)
        if info.get('view_count'):
            embed.add_field(name="Views", value=f"{info['view_count']:,}", inline=True)
        if info.get('like_count'):
            embed.add_field(name="Likes", value=f"{info['like_count']:,}", inline=True)
        embed.add_field(name="Filters", value=", ".join(filters) if filters else "None", inline=True)
        embed.add_field(name="Published At", value=upload_date, inline=True)
        embed.set_image(url=info.get('thumbnail'))
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="seek", description="Seek to a specific position in the currently playing audio.")
    @app_commands.describe(position="Position to seek to. Can be absolute (e.g. 2:30), relative (+/- 30), or percentage (50%).")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def seek(self, ctx: commands.Context, position: str):
        await ctx.typing()
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            await ctx.send("Nothing is currently playing.")
            return
        if ctx.author.voice is None or ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You must be in the same voice channel as me to seek.")
            return
        current_data = self.currently_playing.get(ctx.guild.id)
        if not current_data or 'info' not in current_data:
            await ctx.send("No valid data available for seeking.")
            return
        duration = current_data['info'].get('duration')
        if not duration:
            await ctx.send("Cannot seek; total duration unknown.")
            return
        start_time = current_data.get('start_time', datetime.now())
        elapsed = (datetime.now() - start_time).total_seconds()
        current_pos = int(elapsed + current_data.get('position', 0))
        try:
            new_pos = self.parse_seek_position(position.strip(), duration, current_pos)
        except ValueError as e:
            await ctx.send(str(e))
            return
        if new_pos < 0:
            new_pos = 0
        elif new_pos >= duration:
            new_pos = duration
        ctx.voice_client.stop()
        current_data['position'] = new_pos
        current_data['start_time'] = datetime.now()
        url = current_data['url']
        filters = current_data['filters']
        is_stream = current_data.get('is_stream', False)
        if is_stream:
            await self.play_stream_from_position(ctx, url, filters, new_pos)
        else:
            await self.play_audio_from_position(ctx, url, filters, new_pos)
        await ctx.send(f"Seeked to {self.format_time(new_pos)}.")
    
    @commands.hybrid_command(name="goto", description="Skip to a specific song in the queue by index.")
    @app_commands.describe(index="The index of the song in the queue to skip to (starting at 1).")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def goto(self, ctx: commands.Context, index: int):
        await ctx.typing()
        if ctx.author.voice is None or ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You must be in the same voice channel as me.")
            return

        queue = self.get_queue(ctx.guild.id)
        if not queue:
            await ctx.send("The queue is empty.")
            return

        if index < 1 or index > len(queue):
            await ctx.send(f"Please provide a valid index between 1 and {len(queue)}.")
            return


        for _ in range(index - 1):
            queue.popleft()

        if ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send(f"Skipped to position **{index}** in the queue.")
        else:
            await self.play_next(ctx)
    
    @commands.hybrid_command(name="move", description="Move a song to another position in the queue.")
    @app_commands.describe(old_index="Current position of the song (starting at 1)", new_index="New position for the song (starting at 1)")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def move(self, ctx: commands.Context, old_index: int, new_index: int):
        await ctx.typing()
        if ctx.author.voice is None or ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You must be in the same voice channel as me.")
            return

        queue = list(self.get_queue(ctx.guild.id))
        if not queue:
            await ctx.send("The queue is empty.")
            return

        length = len(queue)
        if not (1 <= old_index <= length) or not (1 <= new_index <= length):
            await ctx.send(f"Please provide valid indices between 1 and {length}.")
            return


        old_index -= 1
        new_index -= 1

        if old_index == new_index:
            await ctx.send("The song is already at that position.")
            return

        moved_item = queue.pop(old_index)
        queue.insert(new_index, moved_item)

        self.queues[ctx.guild.id] = deque(queue)
        if self.loop_mode.get(ctx.guild.id) == "queue":
            self.original_queues[ctx.guild.id] = queue

        await ctx.send(f"Moved item from position **{old_index + 1}** to **{new_index + 1}**.")
    
    @commands.hybrid_command(name="remove", description="Remove a song from the queue by index.")
    @app_commands.describe(index="Index of the song to remove (starting at 1)")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def remove(self, ctx: commands.Context, index: int):
        await ctx.typing()
        if ctx.author.voice is None or ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You must be in the same voice channel as me.")
            return

        queue = list(self.get_queue(ctx.guild.id))
        if not queue:
            await ctx.send("The queue is empty.")
            return

        length = len(queue)
        if not (1 <= index <= length):
            await ctx.send(f"Please provide a valid index between 1 and {length}.")
            return

        removed = queue.pop(index - 1)
        self.queues[ctx.guild.id] = deque(queue)
        if self.loop_mode.get(ctx.guild.id) == "queue":
            self.original_queues[ctx.guild.id] = queue

        title = removed[3]
        await ctx.send(f"Removed **{title}** from the queue.")

    @commands.hybrid_command(name="nowplaying", description="Display information about the currently playing audio/song.", aliases=["np"])
    @app_commands.allowed_installs(guilds=True, users=False)
    async def nowplaying(self, ctx: commands.Context):
        await ctx.typing()
        if ctx.voice_client and ctx.voice_client.is_playing():
            current = self.currently_playing.get(ctx.guild.id)
            if current:
                info = current['info']
                filters = current['filters']
                is_stream = current['is_stream']
                start_time = current.get('start_time', datetime.now())
                elapsed = (datetime.now() - start_time).total_seconds()
                current_pos = elapsed + current.get('position', 0)
                duration = info.get('duration', 0)
                formatted_position = f"{self.format_time(current_pos)} / {self.format_time(duration)}"
                embed = discord.Embed(
                    title=f"Currently {'Playing' if not is_stream else 'Streaming'} - {info['title'] if info['title'] else 'Unknown'}",
                    description=f"URL: {info['webpage_url'] if info['webpage_url'] else 'Unknown'}",
                    color=discord.Color.og_blurple() if not is_stream else discord.Color.blurple(),
                    timestamp=discord.utils.utcnow()
                )
                raw_date = info.get('upload_date')
                upload_date = datetime.strptime(raw_date, '%Y%m%d').strftime('%B %d, %Y') if raw_date else "Unknown"
                embed.add_field(name="Length", value=formatted_position, inline=True)
                embed.add_field(name="Author", value=info.get('uploader', 'Unknown'), inline=True)
                embed.add_field(name="Channel", value=info.get('uploader_url', 'Unknown'), inline=True)
                if info.get('view_count'):
                    embed.add_field(name="Views", value=f"{info['view_count']:,}", inline=True)
                if info.get('like_count'):
                    embed.add_field(name="Likes", value=f"{info['like_count']:,}", inline=True)
                embed.add_field(name="Filters", value=", ".join(filters) if filters else "None", inline=True)
                embed.add_field(name="Published At", value=upload_date, inline=True)
                embed.set_image(url=info.get('thumbnail', None))
                embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
                await ctx.send(embed=embed)
        elif ctx.author.voice is None or ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You are not in the same voice channel as me.")
        else:
            await ctx.send("Nothing is currently playing.")

    @commands.hybrid_command(name="shuffle", description="Shuffle the current queue/playlist.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def shuffle(self, ctx: commands.Context):
        await ctx.typing()
        if ctx.author.voice is None or ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You must be in the same voice channel as me to shuffle the queue.")
            return
        queue = self.get_queue(ctx.guild.id)
        if len(queue) < 2:
            await ctx.send("Queue needs at least 2 items to shuffle.")
            return
        queue_list = list(queue)
        random.shuffle(queue_list)
        self.queues[ctx.guild.id] = deque(queue_list)
        if self.loop_mode.get(ctx.guild.id) == "queue":
            self.original_queues[ctx.guild.id] = queue_list
        await ctx.send("Queue shuffled.")

    @commands.hybrid_command(name="repeat", description="Repeat the currently playing audio/song or playlist.", aliases=["loop"])
    @app_commands.describe(mode="Loop mode (off/track/queue)")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def repeat(self, ctx: commands.Context, mode: str = None):
        await ctx.typing()
        modes = {"off": "Loop disabled.", "track": "Set to single track loop.", "queue": "Set to full queue/playlist loop."}
        if mode is None:
            current = self.loop_mode.get(ctx.guild.id, "off")
            new_mode = "track" if current == "off" else "queue" if current == "track" else "off"
        else:
            mode = mode.lower()
            if mode not in modes:
                return await ctx.send("Invalid mode. Use one of: off, track, or queue")
            new_mode = mode
        self.loop_mode[ctx.guild.id] = new_mode
        if new_mode == "queue":
            queue = self.get_queue(ctx.guild.id)
            self.original_queues[ctx.guild.id] = list(queue)
        await ctx.send(modes[new_mode])
    
    async def get_title(self, url):
        if url in self.metadata_cache:
            return self.metadata_cache.get(url, {}).get('title', 'Unknown Title')
        
        try:
            def sync_extract():
                with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True, 'extract_flat': True}) as ydl:
                    return ydl.extract_info(url, download=False)
            
            info = await self.run_in_executor(sync_extract)
            title = info.get('title', 'Unknown Title')
            self.metadata_cache[url] = info
            return title
        except Exception:
            return url

    @commands.hybrid_command(name="queue", description="Display the current queue.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def queue(self, ctx: commands.Context):
        await ctx.typing()
        queue = self.get_queue(ctx.guild.id)
        if ctx.author.voice is None or ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You are not in the same voice channel as me.")
            return
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
                    await interaction.response.send_message("You can't control this pagination.", ephemeral=True)
                    return False
                return True
            async def on_timeout(self):
                await self.message.edit(view=None)
            def create_embed(self):
                start_idx = self.current_page * ITEMS_PER_PAGE
                end_idx = min((self.current_page + 1) * ITEMS_PER_PAGE, len(self.queue))
                embed = discord.Embed(title=f"Queue (Page {self.current_page + 1}/{self.total_pages})", color=discord.Color.og_blurple(), timestamp=discord.utils.utcnow())
                for i, (url, filters, is_stream, title) in enumerate(self.queue[start_idx:end_idx], start=start_idx + 1):
                    filter_text = f" ({', '.join(filters)})" if filters else ""
                    stream_label = " (Stream)" if is_stream else ""
                    embed.add_field(
                        name=f"{i}.",
                        value=f"[{title}]({url}){filter_text}{stream_label}",
                        inline=False
                    )
                return embed
            @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary)
            async def first_page(self, interaction: discord.Interaction, button: discord.ui.Button):
                if self.current_page == 0:
                    await interaction.response.defer()
                    return
                self.current_page = 0
                await interaction.response.edit_message(embed=self.create_embed(), view=self)
            @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.primary)
            async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
                if self.current_page == 0:
                    await interaction.response.defer()
                    return
                self.current_page -= 1
                await interaction.response.edit_message(embed=self.create_embed(), view=self)
            @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.primary)
            async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
                if self.current_page == self.total_pages - 1:
                    await interaction.response.defer()
                    return
                self.current_page += 1
                await interaction.response.edit_message(embed=self.create_embed(), view=self)
            @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary)
            async def last_page(self, interaction: discord.Interaction, button: discord.ui.Button):
                if self.current_page == self.total_pages - 1:
                    await interaction.response.defer()
                    return
                self.current_page = self.total_pages - 1
                await interaction.response.edit_message(embed=self.create_embed(), view=self)
            @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.success)
            async def random_page(self, interaction: discord.Interaction, button: discord.ui.Button):
                new_page = random.randint(0, self.total_pages - 1)
                if new_page == self.current_page:
                    await interaction.response.defer()
                    return
                self.current_page = new_page
                await interaction.response.edit_message(embed=self.create_embed(), view=self)
            @discord.ui.button(emoji="🔢", style=discord.ButtonStyle.secondary)
            async def jump_to_page(self, interaction: discord.Interaction, button: discord.ui.Button):
                if self.disabled:
                    await interaction.response.defer()
                    return
                class PageJumpModal(discord.ui.Modal, title="Jump to Page"):
                    page_num = discord.ui.TextInput(label=f"Page Number (1-{self.total_pages})", placeholder=f"Enter a number between 1 and {self.total_pages}", min_length=1, max_length=len(str(self.total_pages)))
                    async def on_submit(self, interaction: discord.Interaction):
                        try:
                            page = int(self.page_num.value)
                            if 1 <= page <= self.view.total_pages:
                                self.view.current_page = page - 1
                                await interaction.response.edit_message(embed=self.view.create_embed(), view=self.view)
                            else:
                                await interaction.response.send_message(f"Please enter a number between 1 and {self.view.total_pages}.", ephemeral=True)
                        except ValueError:
                            await interaction.response.send_message("Please enter a valid number.", ephemeral=True)
                modal = PageJumpModal()
                modal.view = self
                await interaction.response.send_modal(modal)
            @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger)
            async def disable_components(self, interaction: discord.Interaction, button: discord.ui.Button):
                await interaction.response.edit_message(view=None)
            @discord.ui.button(emoji="🗑️", style=discord.ButtonStyle.danger)
            async def delete_message(self, interaction: discord.Interaction, button: discord.ui.Button):
                await interaction.message.delete()
                self.stop()
        paginator = QueuePaginator(list(queue), total_pages, ctx.author)
        embed = paginator.create_embed()
        paginator.message = await ctx.send(embed=embed, view=paginator)

    @commands.hybrid_command(name="skip", description="Skip the currently playing audio/song.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def skip(self, ctx: commands.Context):
        await ctx.typing()
        if ctx.voice_client and ctx.voice_client.is_playing() and ctx.author.voice and ctx.author.voice.channel == ctx.voice_client.channel:
            ctx.voice_client.stop()
            await ctx.send("Skipped playback.")
        elif ctx.author.voice is None or ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You must be in the same voice channel as me to skip the audio.")
        else:
            await ctx.send("I am not playing anything.")

    @commands.hybrid_command(name="stop", description="Stop the currently playing audio.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def stop(self, ctx: commands.Context):
        await ctx.typing()
        if ctx.voice_client and ctx.voice_client.is_playing() and ctx.author.voice and ctx.author.voice.channel == ctx.voice_client.channel:
            queue = self.get_queue(ctx.guild.id)
            queue.clear()
            ctx.voice_client.stop()
            await ctx.send("Stopped playback and cleared the queue.")
        elif ctx.author.voice is None or ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You must be in the same voice channel as me to stop the audio.")
        else:
            await ctx.send("I am not connected to a voice channel.")

    @commands.hybrid_command(name="clear", description="Clear the queue.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def clear(self, ctx: commands.Context):
        await ctx.typing()
        if ctx.author.voice is None or ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You are not in the same voice channel as me.")
            return
        queue = self.get_queue(ctx.guild.id)
        queue.clear()
        await ctx.send("Cleared the queue.")

    @commands.hybrid_command(name="pause", description="Pause the currently playing audio.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def pause(self, ctx: commands.Context):
        await ctx.typing()
        if ctx.voice_client and ctx.voice_client.is_playing() and ctx.author.voice and ctx.author.voice.channel == ctx.voice_client.channel:
            ctx.voice_client.pause()
            await ctx.send("Paused playback.")
        elif ctx.author.voice is None or ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You must be in the same voice channel as me to pause the audio.")
        else:
            await ctx.send("Nothing is currently playing.")

    @commands.hybrid_command(name="resume", description="Resume the currently paused audio.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def resume(self, ctx: commands.Context):
        await ctx.typing()
        if ctx.voice_client and ctx.voice_client.is_paused() and ctx.author.voice and ctx.author.voice.channel == ctx.voice_client.channel:
            ctx.voice_client.resume()
            await ctx.send("Resumed playback.")
        elif ctx.author.voice is None or ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You must be in the same voice channel as me to resume the audio.")
        else:
            await ctx.send("Nothing is currently paused.")

async def setup(bot):
    await bot.add_cog(Audio(bot))