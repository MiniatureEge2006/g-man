import os
import time
import discord
from discord import app_commands
from discord.ext import commands
from discord.ext import tasks
from yt_dlp.utils import download_range_func
import yt_dlp
import shlex
import json
import asyncio
import tempfile
import shutil
import re
import uuid

class Ytdlp(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.download_semaphore = asyncio.Semaphore(3)
        self.temp_dir_prefix = f"yt_dlp_{os.getpid()}_"
        self.clean_temp_dir.start()
    
    @commands.Cog.listener()
    async def on_cog_unload(self):
        self.clean_temp_dir.cancel()
    
    @commands.hybrid_command(name="yt-dlp", aliases=["youtube-dl", "ytdl", "youtubedl", "ytdlp", "download", "dl"], description="Use yt-dlp! (for a list of formats use --listformats)")
    @app_commands.describe(url="Input URL(s). Multiple URLs would be seperated by a space.", options="yt-dlp options. (e.g., --download-ranges 10-15 --force-keyframes-at-cuts)")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def ytdlp(self, ctx: commands.Context, url: str, *, options: str = ''):
        await ctx.typing()
        async with self.download_semaphore:
            temp_dir = os.path.join(tempfile.gettempdir(), f"{self.temp_dir_prefix}{uuid.uuid4().hex}")
            os.makedirs(temp_dir, exist_ok=True)
            lock_file = os.path.join(temp_dir, "active.lock")
            try:
                with open(lock_file, 'w') as f:
                    f.write("active")
                if ' ' in url and not url.startswith(('http://', 'https://', 'ytsearch', 'ytsearch:')):
                    url = f"ytsearch1:{url}"
                ydl_opts = {
                    'noplaylist': True,
                    'playlist_items': '1',
                    'quiet': True,
                    'no_warnings': True,
                    'outtmpl': '%(extractor)s-%(id)s.%(ext)s',
                    'paths': {
                        'home': temp_dir,
                        'temp': temp_dir
                    }
                }

                if options.strip():
                    try:
                        custom_opts = self.parse_options(options)
                        ydl_opts.update(custom_opts)
                    except Exception as e:
                        await ctx.send(f"Error parsing options: {e}")
                        return
                urls = [url] if url.startswith(('ytsearch', 'ytsearch:')) else url.split()
                ytsearch_match = re.match(r'^ytsearch(\d+):', url)
                is_multiple_videos = len(urls) > 1 or (ytsearch_match and int(ytsearch_match.group(1)) > 1)
                max_size = self.get_max_file_size(ctx.guild.premium_subscription_count if ctx.guild else 0)
                start_time = time.time()
                results = {
                    'success': [],
                    'skipped': [],
                    'failed': []
                }
                for entry in urls:
                    try:
                        infos = await self.extract_info(ydl_opts, entry, download=not ydl_opts.get("json", False))
                        for info in infos:
                            if ydl_opts.get('listformats', False):
                                await self.handle_listformats(ctx, info)
                                continue
                            if ydl_opts.get('json', False):
                                await self.handle_json_output(ctx, info)
                                continue

                            file_path = info.get('final_file')
                            size = os.path.getsize(file_path)
                            if not file_path:
                                continue
                            title = info.get('title', 'Unknown')
                            if size > max_size:
                                results['skipped'].append({
                                    'title': title,
                                    'size': size,
                                    'entry': entry
                                })
                                continue
                            results['success'].append({
                                'info': info,
                                'file_path': file_path,
                                'title': title,
                                'size': size
                            })
                    except Exception as e:
                        size = self.extract_size_from_info(info) if 'info' in locals() else None
                        results['failed'].append({
                            'entry': entry,
                            'error': str(e),
                            'size': size,
                            'title': info.get('title', 'Unknown') if 'info' in locals() else 'Unknown'
                        })
                        continue
                await self.send_results(ctx, results, is_multiple_videos, max_size, start_time, ydl_opts)
            except Exception as e:
                await ctx.send(f"An error occurred during download: {str(e)}")
            finally:
                try:
                    os.remove(lock_file)
                except:
                    pass
                try:
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    pass
    
    async def send_results(self, ctx: commands.Context, results, is_multiple, max_size, start_time, ydl_opts):
        for failure in results['failed']:
            error_msg = f"Failed to download {failure.get('title', failure.get('entry', 'URL'))}"
            if failure.get('size'):
                error_msg += f" [Size: {failure['size']}]"
            error_msg += f": {failure.get('error', 'Unknown error')}"
            await ctx.send(error_msg[:2000])
        
        if results['skipped']:
            if is_multiple:
                skip_msg = ["Skipped due to size limits:"]
                for item in results['skipped']:
                    skip_msg.append(
                        f"- {item.get('title', 'Unknown')} "
                        f"({self.human_readable_size(item.get('size', 0))}) > "
                        f"{self.human_readable_size(max_size)})"
                    )
                await ctx.send("\n".join(skip_msg)[:2000])
            else:
                item = results['skipped'][0]
                await ctx.send(
                    f"{item.get('title', 'Unknown')} exceeds size limit. "
                    f"({self.human_readable_size(item.get('size', 0))} > "
                    f"{self.human_readable_size(max_size)})"
                )
        
        if results['success']:
            files = [discord.File(item['file_path']) for item in results['success']]
            messages = [
                self.build_metadata_message(
                    item['info'],
                    item['file_path'],
                    os.path.getsize(item['file_path']),
                    time.time() - start_time
                )
                for item in results['success']
            ]
            await ctx.send("\n\n".join(messages)[:2000], files=files[:10])
        
        elif not any([results['failed'], results['skipped']]) and not any([ydl_opts.get('listformats', False), ydl_opts.get('json', False)]):
            await ctx.send("No videos could be downloaded.")
                
    
    def extract_size_from_info(self, info: dict) -> str:
        if not info:
            return ""
        try:
            if info.get('filesize'):
                return self.human_readable_size(info['filesize'])
            
            if info.get('requested_downloads'):
                dl = info['requested_downloads'][0]
                return self.human_readable_size(dl.get('filesize') or dl.get('filesize_approx'))
            
            if info.get('formats'):
                selected_format = next(
                    (f for f in info.get('formats', [])
                    if f.get('format_id') == info.get('format_id')),
                    None
                )
                if selected_format:
                    return self.human_readable_size(selected_format.get('filesize') or selected_format.get('filesize_approx'))
        
        except Exception:
            pass

        return None

    def build_skipped_summary(self, skipped_files, max_size):
        message_lines = [f"Skipped {len(skipped_files)} file(s) due to size limit:"]
        total_size = 0
        for file in skipped_files[:10]:
            human_size = self.human_readable_size(file['size'])
            message_lines.append(f"- {file['title']} ({human_size})")
            total_size += file['size']
        message_lines.append(f"\nTotal skipped size: {self.human_readable_size(total_size)} | Max allowed: {self.human_readable_size(max_size)}")
        return "\n".join(message_lines)

    async def extract_info(self, ydl_opts, url, download=True):
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, self._extract_info, ydl_opts, url, download)
        except Exception as e:
            if hasattr(e, 'exc_info'):
                original_error = e.exc_info[1]
                raise original_error from e
            raise
    
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
    
    async def cleanup_temp_files(self):
        try:
            for filename in os.listdir(self.temp_dir):
                file_path = os.path.join(self.temp_dir, filename)
                try:
                    if os.path.isfile(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception as e:
                    print(f"Could not delete {file_path}: {e}")
        except Exception as e:
            print(f"Error cleaning temp files: {e}")
    
    async def safe_cleanup(self, path: str):
        try:
            if os.path.exists(path):
                if os.path.isfile(path):
                    os.unlink(path)
                else:
                    shutil.rmtree(path)
        except Exception as e:
            print(f"Error cleaning up {path}: {e}")
    
    @tasks.loop(minutes=30)
    async def clean_temp_dir(self):
        temp_parent = tempfile.gettempdir()
        try:
            for name in os.listdir(temp_parent):
                if name.startswith('yt_dlp_'):
                    path = os.path.join(temp_parent, name)
                    try:
                        if os.path.getmtime(path) < time.time() - 3600:
                            await self.safe_cleanup(path)
                    except Exception as e:
                        print(f"Could not delete {path}: {e}")
        except Exception as e:
            print(f"Error cleaning temp dir: {e}")


    def find_video_entries(self, info, limit = 10):
        entries = []

        def collect_entries(obj):
            nonlocal entries
            if not obj or len(entries) >= limit:
                return
            if obj.get('_type') == 'playlist' and 'entries' in obj:
                for entry in obj['entries']:
                    collect_entries(entry)
                    if len(entries) >= limit:
                        break
            elif obj.get('_type') != 'playlist':
                entries.append(obj)
        collect_entries(info)
        return entries


    def _extract_info(self, ydl_opts, url, download=True):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=download)
                entries = self.find_video_entries(info, limit=10)
                if not entries:
                    raise yt_dlp.utils.DownloadError("No video entries found - the playlist might be empty or inaccessible")
            
                for entry in entries:
                    if download:
                        if 'requested_downloads' in entry and entry['requested_downloads']:
                            entry['final_file'] = entry['requested_downloads'][0]['filepath']
                        else:
                            entry['final_file'] = ydl.prepare_filename(entry)
                return entries
        except Exception as e:
            if not isinstance(e, (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError)):
                raise yt_dlp.utils.DownloadError(str(e))
            raise

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
