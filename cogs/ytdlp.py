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
            'outtmpl': 'vids/%(extractor)s-%(id)s.%(ext)s',
            'playlist_items': '1'
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

        start_time = time.time()
        info = None

        try:
            info = await task

            if ydl_opts.get('listformats', False):
                await self.handle_listformats(ctx, info)
            elif ydl_opts.get('json', False):
                await self.handle_json_output(ctx, info)
            else:
                boost_count = ctx.guild.premium_subscription_count if ctx.guild else 0
                await self.handle_video_download(ctx, info, boost_count, start_time)
        
        except Exception as e:
            await self.send_error_embed(ctx, e)
        finally:
            if info:
                await self.cleanup_downloaded_file(info)

    async def extract_info(self, ydl_opts, url, download=True):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._extract_info, ydl_opts, url, download)
    
    async def handle_listformats(self, ctx: commands.Context, info):
        formats = info.get('formats', [])
        if not formats:
            return await ctx.send("No formats available for this URL.")
        
        lines = [
            f"ID: {f.get('format_id')} | Ext: {f.get('ext')} | Res: {f.get('resolution', 'N/A')} | FPS: {f.get('fps', 'N/A')} | "
            f"Video Codec: {f.get('vcodec', 'N/A')} | Audio Codec: {f.get('acodec', 'N/A')} | "
            f"Bitrate: {f.get('tbr', 'N/A')}k | Size: {self.get_format_size(f, info)} | "
            f"Protocol: {f.get('protocol', 'N/A')} | Notes: {f.get('format_note', 'N/A')} | Container: {f.get('container', 'N/A')}"
            for f in formats
        ]

        message = "\n".join(lines)
        if len(message) > 2000:
            path = f"vids/formats-{info.get('id', 'Unknown')}.txt"
            with open(path, 'w') as f:
                f.write(message)
            await ctx.send(f"Available formats for {info.get('title', 'Unknown')}:", file=discord.File(path))
            os.remove(path)
        else:
            await ctx.send(f"Available formats for {info.get('title', 'Unknown')}:\n```{message}```")
    
    async def handle_json_output(self, ctx: commands.Context, info):
        path = f"vids/{info.get('id', 'Unknown')}.info.json"
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(info, f, indent=4)
            await ctx.send(f"Info dict JSON extracted for {info.get('title', 'Unknown Title')}:", file=discord.File(path))
        except Exception as e:
            await ctx.send(f"Error extracting the info dict JSON: {e}")
        finally:
            if os.path.exists(path):
                os.remove(path)
    
    async def handle_video_download(self, ctx: commands.Context, info, boost_count, start_time):
        file_path = info.get('final_file')
        if not file_path or not os.path.exists(file_path):
            raise FileNotFoundError(f"The file `{file_path}` does not exist.")
        
        size = os.path.getsize(file_path)
        max_size = self.get_max_file_size(boost_count)

        if size > max_size:
            raise commands.CommandError(
                f"File too large. ({size} bytes > {max_size} bytes ({self.human_readable_size(size)} > {self.human_readable_size(max_size)}))"
            )
        elapsed = time.time() - start_time
        meta = self.build_metadata_message(info, file_path, size, elapsed)

        with open(file_path, 'rb') as f:
            await ctx.send(meta, file=discord.File(f, filename=os.path.basename(file_path)))
    
    def build_metadata_message(self, info: dict, file_path: str, file_size: int, elapsed: float) -> str:
        fields = []

        title = info.get('title')
        video_id = info.get('id')
        url = info.get('webpage_url')
        if title and url and video_id:
            fields.append(f"[{title} ({video_id})](<{url}> '{os.path.basename(file_path)}')")
        elif title and video_id:
            fields.append(f"{title} ({video_id})")
        
        uploader = info.get('uploader')
        uploader_url = info.get('uploader_url')
        uploader_id = info.get('uploader_id')
        if uploader:
            if uploader_url and uploader_id:
                fields.append(f"by [{uploader}](<{uploader_url}> '{uploader_id}')")
            else:
                fields.append(f"by {uploader}")
        
        width, height = info.get('width'), info.get('height')
        if width and height:
            fields.append(f"Resolution: {width}x{height}")
        
        duration_str = info.get('duration_string')
        duration = info.get('duration')
        if duration_str and duration:
            fields.append(f"Duration: {duration_str} ({duration} seconds)")
        
        format_id = info.get('format_id')
        format_name = info.get('format')
        if format_id and format_name:
            fields.append(f"Formats: `{format_id} ({format_name})`")
        
        fields.append(f"Size: {self.human_readable_size(file_size)} ({file_size} bytes)")
        fields.append(f"Took: {elapsed:.2f} seconds")

        return "-# " + ", ".join(fields)
    
    async def send_error_embed(self, ctx: commands.Context, error):
        error_text = f"```ansi\n{error}```"
        advice = None
        color = discord.Color.red()

        lower_msg = str(error).lower()
        if "unsupported url" in lower_msg:
            advice = "This media type is not supported. Usually this means yt-dlp does not support the website. Try a different link."
            color = discord.Color.orange()
        elif "unable to extract" in lower_msg:
            advice = "yt-dlp failed to extract the content inside this webpage. It might be private, region-locked, or malformed."
            color = discord.Color.dark_orange()
        elif "drm" in lower_msg or "protected" in lower_msg:
            advice = "This media is DRM (Digital Rights Management) protected, meaning you are legally not allowed to download this content.\n**Help will __not__ be provided regarding DRM protected content.**"
            color = 0xFF0000
        elif "file too large" in lower_msg:
            advice = "The file exceeds Discord's upload limit for this server's boost level. Try checking the available formats for this content to download a smaller one. If used as an external user application, you'll need to contact your server staff/support for help as it's not possible to detect and upload large files if the bot is not in the server."
            color = discord.Color.blurple()
        
        embed = discord.Embed(
            title=":warning: yt-dlp Error",
            description=error_text,
            color=color,
            timestamp=discord.utils.utcnow()
        )
        
        if advice:
            embed.add_field(name="Additional info regarding this error", value=advice, inline=False)
        
        embed.set_author(name=f"{ctx.author}#{ctx.author.discriminator}", icon_url=ctx.author.display_avatar, url=f"https://discord.com/users/{ctx.author.id}")
        await ctx.send(embed=embed)
    
    async def cleanup_downloaded_file(self, info):
        path = info.get('final_file')
        if path and os.path.exists(path):
            os.remove(path)

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
    
    def get_format_size(self, fmt: dict, info: dict) -> str:
        filesize = fmt.get('filesize') or fmt.get('filesize_approx')
        if filesize and filesize > 0:
            return self.human_readable_size(filesize)
        
        try:
            duration = float(info.get('duration', 0)) if info.get('duration') else 0
            tbr = float(fmt.get('tbr', 0)) * 1000 if fmt.get('tbr') else 0

            if duration > 0 and tbr > 0:
                approx_size = (tbr * duration) / 8
                return f"~{self.human_readable_size(approx_size)} (estimation)"
        except (TypeError, ValueError):
            pass
        
        return "Variable/Unknown"

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
        for unit in ["B", "KiB", "MiB", "GiB", "TiB"]:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024

async def setup(bot):
    await bot.add_cog(Ytdlp(bot))
