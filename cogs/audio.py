import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import spotipy
import bot_info
import os
import asyncio
from collections import deque
from datetime import datetime

YDL_OPTIONS = {'format': 'bestaudio/best', 'noplaylist': True, 'outtmpl': 'vids/%(extractor)s-%(id)s-%(title)s.%(ext)s', 'restrictfilenames': True}
spotify = spotipy.Spotify(auth_manager=spotipy.SpotifyClientCredentials(client_id=bot_info.data['spotify_client_id'], client_secret=bot_info.data['spotify_client_secret']))

class Audio(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues = {}
        self.currently_playing = {}
        self.loop_mode = {}
    
    def get_queue(self, guild_id):
        if guild_id not in self.queues:
            self.queues[guild_id] = deque()
        return self.queues[guild_id]

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
    
    async def play_next(self, ctx: commands.Context):
        guild_id = ctx.guild.id
        queue = self.get_queue(guild_id)
        if self.loop_mode.get(guild_id) == "single":
            current = self.currently_playing.get(guild_id)
            if current:
                await self.play_audio(ctx, current['url'], current['filters'])
            return
        if queue:
            url, filters = queue.popleft()
            await self.play_audio(ctx, url, filters)
        elif self.loop_mode.get(guild_id) == "queue":
            for item in self.currently_playing.get(guild_id, {}).get("queue_snapshot", []):
                queue.append(item)
            if queue:
                url, filters = queue.popleft()
                await self.play_audio(ctx, url, filters)

    async def play_audio(self, ctx: commands.Context, url: str, filters=None):
        if 'spotify.com' in url:
            track = spotify.track(url)
            query = f"{track['name']} {track['artists'][0]['name']}"
            with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                results = ydl.extract_info(f"ytsearch:{query}", download=False)['entries']
                if results:
                    url = results[0]['webpage_url']
            
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, self.extract_info, url)

        file_path = yt_dlp.YoutubeDL(YDL_OPTIONS).prepare_filename(info)
        
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
            ffmpeg_options = {
                'options': '-vn'
            }
            if filters:
                ffmpeg_options['options'] += f" -af {','.join(filters)}"
            
            source = discord.FFmpegPCMAudio(file_path, **ffmpeg_options)
            voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self.cleanup_file_and_play_next(ctx, file_path), self.bot.loop))
            self.currently_playing[ctx.guild.id] = {
                'info': info,
                'url': url,
                'filters': filters,
                'queue_snapshot': list(self.get_queue(ctx.guild.id))
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
    
    def extract_info(self, url):
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            return ydl.extract_info(url, download=True)

    async def cleanup_file_and_play_next(self, ctx, file_path):
        if os.path.exists(file_path):
            await asyncio.sleep(1)
            os.remove(file_path)
        await self.play_next(ctx)
    
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
    
    @commands.hybrid_command(name="play", description="Play an audio/song from a given URL. Any URL that yt-dlp supports also works.", aliases=["p"])
    @app_commands.describe(url="The URL of the audio/song to play.", filters="A comma-separated list of filters to apply to the audio.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def play(self, ctx: commands.Context, url: str, *, filters: str = None):
        await ctx.typing()
        
        filters_list = filters.split(',') if filters else []
        queue = self.get_queue(ctx.guild.id)
        if ctx.voice_client and ctx.voice_client.is_playing() and ctx.author.voice and ctx.author.voice.channel == ctx.voice_client.channel:
            queue.append((url, filters_list))
            await ctx.send(f"Added {url} to the queue.")
        elif ctx.voice_client and ctx.voice_client.is_playing() and (ctx.author.voice is None or ctx.author.voice.channel != ctx.voice_client.channel):
            await ctx.send("You must be in the same voice channel as me to play audio.")
            return
        elif ctx.voice_client is None or (ctx.author.voice and ctx.author.voice.channel != ctx.voice_client.channel):
            connected = await self.connect_to_channel(ctx)
            if not connected:
                return
            await self.play_audio(ctx, url, filters=filters_list)
        else:
            await self.play_audio(ctx, url, filters=filters_list)
    
    @commands.hybrid_command(name="repeat", description="Repeat the currently playing audio/song or the queue.")
    @app_commands.describe(mode="The mode to repeat. Can be 'single', 'queue', or 'none'.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def repeat(self, ctx: commands.Context, mode: str):
        await ctx.typing()
        if mode.lower() not in ["single", "queue", "none"]:
            await ctx.send("Invalid mode. Valid modes are 'single', 'queue', or 'none'.")
            return
        if ctx.author.voice is None or ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You are not in the same voice channel as me.")
            return
        self.loop_mode[ctx.guild.id] = mode.lower()
        await ctx.send(f"Loop mode set to {mode.lower()}.")
    

    @commands.hybrid_command(name="queue", description="Display the current queue.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def queue(self, ctx: commands.Context):
        await ctx.typing()
        queue = self.get_queue(ctx.guild.id)
        if queue:
            embed = discord.Embed(
                title="Queue",
                description="\n".join(f"{i+1}. {url} ({', '.join(filters)})" for i, (url, filters) in enumerate(queue)),
                color=discord.Color.og_blurple(),
                timestamp=discord.utils.utcnow()
            )
            await ctx.send(embed=embed)
        elif ctx.author.voice is None or ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You are not in the same voice channel as me.")
            return
        else:
            await ctx.send("The queue is empty.")
    
    @commands.hybrid_command(name="skip", description="Skip the currently playing audio/song.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def skip(self, ctx: commands.Context):
        await ctx.typing()
        if ctx.voice_client and ctx.voice_client.is_playing() and ctx.author.voice and ctx.author.voice.channel == ctx.voice_client.channel:
            ctx.voice_client.stop()
            await ctx.send("Skipped playback.")
        elif ctx.voice_client and ctx.voice_client.is_playing() and ctx.author.voice and ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You must be in the same voice channel as me to skip the audio.")
            return
        else:
            await ctx.send("Nothing is currently playing.")
    
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
            return
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
            return
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
            return
        else:
            await ctx.send("Nothing is currently paused.")
    
    @commands.hybrid_command(name="nowplaying", description="Display information about the currently playing audio/song.", aliases=["np"])
    @app_commands.allowed_installs(guilds=True, users=False)
    async def nowplaying(self, ctx: commands.Context):
        await ctx.typing()
        if ctx.voice_client and ctx.voice_client.is_playing():
            current = self.currently_playing.get(ctx.guild.id)
            if current:
                info = current['info']
                filters = current['filters']
                embed = discord.Embed(
                    title=f"Currently Playing - {info['title'] if info['title'] else 'Unknown'}",
                    description=f"URL: {info['webpage_url'] if info['webpage_url'] else 'Unknown'}",
                    color=discord.Color.og_blurple(),
                    timestamp=discord.utils.utcnow()
                )
                raw_date = info.get('upload_date')
                upload_date = datetime.strptime(raw_date, '%Y%m%d').strftime('%B %d, %Y') if raw_date else "Unknown"
                embed.add_field(name="Length", value=info.get('duration_string', 'Unknown'), inline=True)
                embed.add_field(name="Author", value=info.get('uploader', 'Unknown'), inline=True)
                embed.add_field(name="Channel", value=info.get('uploader_url', 'Unknown'), inline=True)
                if info.get('view_count'):
                    embed.add_field(name="Views", value=f"{info['view_count']:,}")
                if info.get('like_count'):
                    embed.add_field(name="Likes", value=f"{info['like_count']:,}")
                embed.add_field(name="Filters", value=", ".join(filters) if filters else "None", inline=True)
                embed.add_field(name="Published At", value=upload_date, inline=True)
                embed.set_image(url=info.get('thumbnail', None))
                embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
                await ctx.send(embed=embed)
        elif ctx.author.voice is None or ctx.author.voice.channel != ctx.voice_client.channel:
            await ctx.send("You are not in the same voice channel as me.")
            return
        else:
            await ctx.send("Nothing is currently playing.")
    
async def setup(bot):
    await bot.add_cog(Audio(bot))