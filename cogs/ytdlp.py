import os
import discord
from discord import app_commands
from discord.ext import commands
from yt_dlp.utils import download_range_func
import yt_dlp
import shlex
import json

class Ytdlp(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.hybrid_command(name="yt-dlp", aliases=["youtube-dl", "ytdl", "youtubedl", "ytdlp"], description="Use yt-dlp! (for a list of formats use --listformats or listformats=true)")
    @app_commands.describe(url="Input URL. (e.g., YouTube, SoundCloud. DRM protected websites are NOT supported.)", options="yt-dlp Options. (e.g., download_ranges=10-15 --force_keyframes_at_cuts)")
    @app_commands.user_install()
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def ytdlp(self, ctx: commands.Context, url: str, *, options: str = ''):
        if ctx.interaction:
            await ctx.defer()
        else:
            await ctx.typing()
        ydl_opts = {
            'noplaylist': True,
            'outtmpl': 'vids/%(extractor)s-%(id)s.%(ext)s'
        }

        if options.strip():
            try:
                custom_opts = self.parse_options(options)
                ydl_opts.update(custom_opts)
            except Exception as e:
                await ctx.send(f"Error parsing options: `{e}`")
                return
        
        try:
            if ydl_opts.get("listformats", False):
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    formats = info.get('formats', [])
                    if not formats:
                        await ctx.send("No formats available for this URL.")
                        return
                    
                    format_list = [
                    (
                    f"ID: {fmt.get('format_id')} | Ext: {fmt.get('ext')} | "
                    f"Res: {fmt.get('resolution', 'N/A')} | FPS: {fmt.get('fps', 'N/A')} | "
                    f"Video Codec: {fmt.get('vcodec', 'N/A')} | Audio Codec: {fmt.get('acodec', 'N/A')} | "
                    f"Bitrate: {fmt.get('tbr', 'N/A')}k | Size: {self.human_readable_size(fmt.get('filesize', 0)) if fmt.get('filesize') else 'N/A'} | "
                    f"Protocol: {fmt.get('protocol', 'N/A')}"
                    )
                    for fmt in formats
                ]

                    format_message = "\n".join(format_list)
                    if len(format_message) > 2000:
                        file_path = f"vids/formats.txt"
                        with open(file_path, 'w') as f:
                            f.write(format_message)
                        await ctx.send("The available formats are too many to display. See the attached file:", file=discord.File(file_path))
                        os.remove(file_path)
                    else:
                        await ctx.send(f"Available formats:\n```{format_message}```")
                return
            else:
                await ctx.send(f"Downloading from `{url}` with options `{ydl_opts}`...")
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    final_file = (
                    info.get('requested_downloads', [{}])[0].get('filepath')
                    or ydl.prepare_filename(info)
                    )

                    if not os.path.exists(final_file):
                        raise FileNotFoundError(f"The file '{final_file}' does not exist.")
                    file_size = os.path.getsize(final_file)
                    boost_count = ctx.guild.premium_subscription_count if ctx.guild else 0
                    max_size = self.get_max_file_size(boost_count)

                    if file_size > max_size:
                        await ctx.send(f"File is too large to send via Discord. ({file_size} bytes/{self.human_readable_size(int(file_size))})")
                    else:
                        await ctx.send(file=discord.File(final_file))

                os.remove(final_file)
        except FileNotFoundError as e:
            await ctx.send(f"File handling error: `{e}`")
        except Exception as e:
            await ctx.send(f"Download failed: ```ansi\n{e}```")

    def parse_time_to_seconds(self, time_str):
        time_parts = time_str.split(":")
        if len(time_parts) == 1: # Seconds only
            return float(time_parts[0])
        elif len(time_parts) == 2: # MM:SS
            minutes = int(time_parts[0])
            seconds = float(time_parts[1])
            return minutes * 60 + seconds
        elif len(time_parts) == 3: # HH:MM:SS
            hours = int(time_parts[0])
            minutes = int(time_parts[1])
            seconds = float(time_parts[2])
            return hours * 3600 + minutes * 60 + seconds
        else:
            raise ValueError(f"Invalid time format: `{time_str}`")

    def parse_options(self, options: str) -> dict:
        parsed_opts = {}
        for opt in shlex.split(options):
            if "=" in opt:
                key, value = opt.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"')

                if value.lower() == 'true':
                    parsed_opts[key] = True
                elif value.lower() == 'false':
                    parsed_opts[key] = False
                
                if key == "postprocessors":
                    try:
                        parsed_value = json.loads(value)
                        if not isinstance(parsed_value, list) or not all(isinstance(item, dict) for item in parsed_value):
                            raise ValueError("Postprocessors must be a JSON-formatted list of dictionaries.")
                        parsed_opts[key] = parsed_value
                    except json.JSONDecodeError as e:
                        raise ValueError(f"Error parsing postprocessors: {e}")
                    continue
                if key == "postprocessor_args":
                    try:
                        parsed_value = json.loads(value)
                        if not isinstance(parsed_value, list) or not all(isinstance(item, str) for item in parsed_value):
                            raise ValueError("postprocessor_args must be a JSON-formatted list of strings.")
                        parsed_opts[key] = parsed_value
                    except json.JSONDecodeError as e:
                        raise ValueError(f"Error parsing postprocessor_args: {e}")
                    continue
                # For download_ranges
                if key == "download_ranges":
                    try:
                        ranges = []
                        for rng in value.split(","):
                            if "-" in rng:
                                start, end = rng.split("-", 1)
                                start = self.parse_time_to_seconds(start.strip())
                                end = self.parse_time_to_seconds(end.strip()) if end.strip() else None
                                ranges.append((start, end))
                            else:
                                start = self.parse_time_to_seconds(rng.strip())
                                ranges.append((start, None))
                        parsed_opts['download_ranges'] = download_range_func(None, ranges)
                    except ValueError as e:
                        raise ValueError(f"Invalid range format for download_ranges: `{e}`")
                else:
                    parsed_opts[key] = value
            elif opt.startswith("--"):
                key = opt[2:].strip()
                parsed_opts[key] = True
            else:
                raise ValueError(f"Invalid option format: `{opt}`")
        return parsed_opts
    

    def get_max_file_size(self, boost_count: int) -> int:
        if boost_count >= 14:
            return 100 * 1024 * 1024 # 100 MB
        elif boost_count >= 7:
            return 50 * 1024 * 1024 # 50 MB
        else:
            return 25 * 1024 * 1024 # 25 MB
    
    def human_readable_size(self, size: int) -> str:
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024

async def setup(bot):
    await bot.add_cog(Ytdlp(bot))
