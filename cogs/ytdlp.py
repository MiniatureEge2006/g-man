import os
import time
import discord
from discord import app_commands
from discord.ext import commands
from yt_dlp.utils import download_range_func
import yt_dlp
import shlex
import json
import asyncio

class Ytdlp(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.hybrid_command(name="yt-dlp", aliases=["youtube-dl", "ytdl", "youtubedl", "ytdlp", "download", "dl"], description="Use yt-dlp! (for a list of formats use --listformats)")
    @app_commands.describe(url="Input URL. (e.g., YouTube, SoundCloud. DRM protected websites are NOT supported.)", options="yt-dlp options. (e.g., --download-ranges 10-15 --force-keyframes-at-cuts)")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def ytdlp(self, ctx: commands.Context, url: str, *, options: str = ''):
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
                await ctx.send(f"Error parsing options: {e}")
                return
        download = not ydl_opts.get("json", False)
        task = asyncio.create_task(self.extract_info(ydl_opts, url, download=download))
        try:
            start_time = time.time()

            if ydl_opts.get("listformats", False):
                info = await task
                formats = info.get('formats', [])
                if not formats:
                    await ctx.send("No formats available for this URL.")
                    return
                    
                format_list = [
                (
                f"ID: {fmt.get('format_id')} | Ext: {fmt.get('ext')} | "
                f"Res: {fmt.get('resolution', 'N/A')} | FPS: {fmt.get('fps', 'N/A')} | "
                f"Video Codec: {fmt.get('vcodec', 'N/A')} | Audio Codec: {fmt.get('acodec', 'N/A')} | "
                f"Bitrate: {fmt.get('tbr', 'N/A')}k | Size: {self.human_readable_size(fmt.get('filesize') or fmt.get('filesize_approx') or 0)} | "
                f"Protocol: {fmt.get('protocol', 'N/A')} | "
                f"Notes: {fmt.get('format_note', 'N/A')} | "
                f"Container: {fmt.get('container', 'N/A')}"
                )
                for fmt in formats
                ]

                format_message = "\n".join(format_list)
                if len(format_message) > 2000:
                    file_path = f"vids/formats-{info.get('id', 'Unknown ID')}.txt"
                    with open(file_path, 'w') as f:
                        f.write(format_message)
                    await ctx.send(f"Available formats for {info.get('title', 'Unknown Title')}:", file=discord.File(file_path))
                    os.remove(file_path)
                else:
                    await ctx.send(f"Available formats for {info.get('title', 'Unknown Title')}:\n```{format_message}```")
                return
            if ydl_opts.get("json", False):
                info = await task
                json_file_path = f"vids/info-{info.get('id', 'Unknown ID')}.json"
                try:
                    with open(json_file_path, 'w', encoding='utf-8') as json_file:
                        json.dump(info, json_file, indent=4)
                    await ctx.send(f"JSON info extracted for {info.get('title', 'Unknown Title')}:", file=discord.File(json_file_path))
                except Exception as e:
                    await ctx.send(f"Error extracting JSON info: {e}")
                os.remove(json_file_path)
            else:
                info = await task
                final_file = info.get('final_file')

                if not final_file or not os.path.exists(final_file):
                    raise FileNotFoundError(f"The file '{final_file}' does not exist.")
                file_size = os.path.getsize(final_file)
                boost_count = ctx.guild.premium_subscription_count if ctx.guild else 0
                max_size = self.get_max_file_size(boost_count)

                if file_size > max_size:
                    raise commands.CommandError(f"File is too large to send. (Size: {file_size} bytes/{self.human_readable_size(file_size)}, Max Size: {max_size} bytes/{self.human_readable_size(max_size)})")
                else:
                    elapsed_time = time.time() - start_time
                    video_url = info.get('webpage_url', 'Unknown URL')
                    title = info.get('title', 'Unknown Title')
                    id = info.get('id', 'Unknown Video ID')
                    width = info.get('width', 'Unknown Width')
                    height = info.get('height', 'Unknown Height')
                    resolution = f"{width}x{height}"
                    uploader = info.get('uploader', 'Unknown Uploader')
                    uploader_url = info.get('uploader_url', 'Unknown URL')
                    uploader_id = info.get('uploader_id', 'Unknown ID')
                    duration = info.get('duration_string', 'Unknown')
                    duration_seconds = info.get('duration', 'Unknown')
                    format_id = info.get('format_id', 'Unknown Format IDs')
                    format_details = info.get('format', 'Unknown Format Details')
                    await ctx.send(f"-# [{title} ({id})](<{video_url}> '{os.path.basename(final_file)}') by [{uploader}](<{uploader_url}> '{uploader_id}'), {resolution}, {duration} ({duration_seconds} seconds) Duration, Format IDs: `{format_id} ({format_details})`, {file_size} bytes ({self.human_readable_size(file_size)}), took {elapsed_time:.2f} seconds", file=discord.File(final_file))

        except FileNotFoundError as e:
            raise commands.CommandError(f"File handling error: `{e}`")
        except Exception as e:
            raise commands.CommandError(f"Download failed: ```ansi\n{e}```")
        finally:
            info = await task
            final_file = info.get('final_file')
            if final_file and os.path.exists(final_file):
                os.remove(final_file)

    async def extract_info(self, ydl_opts, url, download=True):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._extract_info, ydl_opts, url, download)

    def _extract_info(self, ydl_opts, url, download=True):
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=download)
            if download:
                final_file = info.get('requested_downloads', [{}])[0].get('filepath') or ydl.prepare_filename(info)
                info['final_file'] = final_file
            return info

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
        
        postprocessor_mapping = {
            "convert": {
                "key": "FFmpegVideoConvertor",
                "params": ["preferedformat"],
                "default": "mp4"
            },
            "remux": {
                "key": "FFmpegVideoRemuxer",
                "params": ["preferedformat"],
                "default": "mp4"
            },
            "audio": {
                "key": "FFmpegExtractAudio",
                "params": ["preferredcodec"],
                "default": "mp3"
            }
        }

        options_list = shlex.split(options)
        i = 0
        while i < len(options_list):
            opt = options_list[i]

            if not (opt.startswith("-") or opt.startswith("--")):
                raise ValueError(f"Options must start with '-' or '--'. Invalid option: `{opt}`")
            
            opt = opt[1:] if opt.startswith("-") and not opt.startswith("--") else opt[2:]

            opt = opt.replace("-", "_")
            
            key = opt
            if i + 1 < len(options_list) and not (options_list[i + 1].startswith("-") or options_list[i + 1].startswith("--")):
                value = options_list[i + 1]
                i += 1
            else:
                value = None
            
            if opt in postprocessor_mapping:
                pp_info = postprocessor_mapping[opt]
                pp_key = pp_info["key"]
                pp_params = pp_info["params"]
                pp_value = value if value is not None else pp_info["default"]

                postprocessor = {
                    "key": pp_key,
                    "when": "post_process"
                }
                postprocessor.update({pp_params[0]: pp_value})
                parsed_opts.setdefault("postprocessors", []).append(postprocessor)
            else:
                if opt == "format_sort":
                    if value is None:
                        raise ValueError("format_sort requires a value.")
                    try:
                        parsed_value = json.loads(value)
                        if not isinstance(parsed_value, list) or not all(isinstance(item, str) for item in parsed_value):
                            raise ValueError("format_sort must be a list of strings.")
                        parsed_opts[key] = parsed_value
                    except json.JSONDecodeError as e:
                        raise ValueError(f"Error parsing format_sort: `{e}`")
                elif opt == "download_ranges":
                    if value is None:
                        raise ValueError("download_ranges requires a value.")
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
                            parsed_opts[key] = download_range_func(None, ranges)
                    except ValueError as e:
                        raise ValueError(f"Invalid range format for download_ranges: `{e}`")
                else:
                    if value is None:
                        parsed_opts[key] = True
                    else:
                        if value.lower() == "true":
                            parsed_opts[key] = True
                        elif value.lower() == "false":
                            parsed_opts[key] = False
                        else:
                            parsed_opts[key] = value
            i += 1
        return parsed_opts
    

    def get_max_file_size(self, boost_count: int) -> int:
        if boost_count >= 14:
            return 100 * 1024 * 1024 # 100 MB
        elif boost_count >= 7:
            return 50 * 1024 * 1024 # 50 MB
        else:
            return 10 * 1024 * 1024 # 10 MB
    
    def human_readable_size(self, size: int) -> str:
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024

async def setup(bot):
    await bot.add_cog(Ytdlp(bot))
