import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import os
import asyncio
from collections import deque

YDL_OPTIONS = {'format': 'bestaudio/best', 'noplaylist': True, 'outtmpl': 'vids/%(extractor)s-%(id)s-%(title)s.%(ext)s', 'restrictfilenames': True}

class Audio(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues = {}
    
    def get_queue(self, guild_id):
        if guild_id not in self.queues:
            self.queues[guild_id] = deque()
        return self.queues[guild_id]

    async def connect_to_channel(self, ctx: commands.Context):
        if ctx.author.voice:
            channel = ctx.author.voice.channel
            await channel.connect()
            await ctx.send(f"Connected to {channel.name}.")
        else:
            await ctx.send("You are not connected to a voice channel.")
            return
    
    async def play_next(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)
        if queue:
            url, filters = queue.popleft()
            await self.play_audio(ctx, url, filters)

    async def play_audio(self, ctx: commands.Context, url: str, filters=None):
        async with ctx.typing():
            with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                info = ydl.extract_info(url, download=True)
                file_path = ydl.prepare_filename(info)
        
            if ctx.voice_client is None:
                await self.connect_to_channel(ctx)
        
            voice_client = ctx.voice_client

            if voice_client:
                ffmpeg_options = {
                    'options': '-vn'
                }
                if filters:
                    ffmpeg_options['options'] += f" -af {','.join(filters)}"
            
                source = discord.FFmpegPCMAudio(file_path, **ffmpeg_options)
                voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self.cleanup_file_and_play_next(ctx, file_path), self.bot.loop))
                await ctx.send(f"Playing: [{info['title']} ({info['id']})](<{info['webpage_url'] if 'webpage_url' in info else 'Unknown URL'}>) by [{info['uploader'] if 'uploader' in info else 'Unknown Uploader'}](<{info['uploader_url'] if 'uploader_url' in info else 'Unknown URL'}> '{info['uploader_id'] if 'uploader_id' in info else 'Unknown ID'}') from {info['extractor']} with a duration of {info['duration_string'] if 'duration_string' in info else 'Unknown Duration'} ({info['duration'] if 'duration' in info else 'Unknown Duration'} seconds).")
    
    async def cleanup_file_and_play_next(self, ctx, file_path):
        if os.path.exists(file_path):
            await asyncio.sleep(1)
            os.remove(file_path)
        await self.play_next(ctx)
    
    @commands.hybrid_command(name="join", description="Join a voice channel.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def join(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        
        await self.connect_to_channel(ctx)
    
    @commands.hybrid_command(name="leave", description="Leave the current voice channel.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def leave(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        if ctx.author.voice is None:
            await ctx.send("You are not connected to a voice channel.")
            return
        if ctx.voice_client:
            queue = self.get_queue(ctx.guild.id)
            queue.clear()
            await ctx.send(f"Disconnected from {ctx.voice_client.channel}.")
            await ctx.voice_client.disconnect()
        else:
            await ctx.send("I am not connected to a voice channel.")
    
    @commands.hybrid_command(name="play", description="Play an audio/song from a given URL. Any URL that yt-dlp supports also works.", aliases=["p"])
    @app_commands.describe(url="The URL of the audio/song to play.")
    @app_commands.describe(filters="A comma-separated list of filters to apply to the audio.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def play(self, ctx: commands.Context, url: str, *, filters: str = None):
        if ctx.interaction:
            await ctx.defer()
        
        filters_list = filters.split(',') if filters else []
        queue = self.get_queue(ctx.guild.id)
        if ctx.voice_client and ctx.voice_client.is_playing():
            queue.append((url, filters_list))
            await ctx.send(f"Added {url} to the queue.")
        else:
            await self.play_audio(ctx, url, filters=filters_list)
    
    @commands.hybrid_command(name="queue", description="Display the current queue.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def queue(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        queue = self.get_queue(ctx.guild.id)
        if queue:
            queue_list = [f"{index + 1}. {url} ({', '.join(filters)})" for index, (url, filters) in enumerate(queue)]
            await ctx.send(f"Queue:\n{''.join(queue_list)}")
        else:
            await ctx.send("The queue is empty.")
    
    @commands.hybrid_command(name="skip", description="Skip the currently playing audio/song.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def skip(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("Skipped playback.")
        else:
            await ctx.send("Nothing is currently playing.")
    
    @commands.hybrid_command(name="stop", description="Stop the currently playing audio.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def stop(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        
        if ctx.voice_client and ctx.voice_client.is_playing():
            queue = self.get_queue(ctx.guild.id)
            queue.clear()
            ctx.voice_client.stop()
            await ctx.send("Stopped playback.")
        else:
            await ctx.send("I am not connected to a voice channel.")
    
    @commands.hybrid_command(name="clear", description="Clear the queue.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def clear(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        queue = self.get_queue(ctx.guild.id)
        queue.clear()
        await ctx.send("Cleared the queue.")
    
    @commands.hybrid_command(name="pause", description="Pause the currently playing audio.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def pause(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("Paused playback.")
        else:
            await ctx.send("Nothing is currently playing.")
    
    @commands.hybrid_command(name="resume", description="Resume the currently paused audio.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def resume(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("Resumed playback.")
        else:
            await ctx.send("Nothing is currently paused.")
    
async def setup(bot):
    await bot.add_cog(Audio(bot))