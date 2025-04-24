import discord
from discord.ext import commands
from discord import app_commands
import asyncpg
import re
import bot_info
import operator
import asyncio
from typing import Callable, Dict, Set, Union
import aiohttp
import os
import uuid
import platform
from pathlib import Path
import subprocess
import shlex
import shutil
from datetime import datetime
import random


class MediaProcessor:
    def __init__(self):
        self.media_cache: Dict[str, str] = {}
        self.active_processes: Set[asyncio.subprocess.Process] = set()
        self.temp_dir = Path(os.getenv('TEMP', '/tmp')) / 'gscript'
        self.temp_dir.mkdir(exist_ok=True)
        self.temp_files = set()
        self._cleanup_task = None
        self._last_cleanup = None
        self.cleanup_interval = 3600
        self.file_max_age = 86400
        self.start_cleanup_task()
        self.command_specs = {
            'load': {
                'url': {'required': True, 'type': str},
                'media_key': {'required': True, 'type': str}
            },
            'reverse': {
                'input_key': {'required': True, 'type': str},
                'output_key': {'required': True, 'type': str}
            },
            'concat': {
                'output_key': {'required': True, 'type': str},
                # Input keys are handled as remaining positional args
            },
            'render': {
                'media_key': {'required': True, 'type': str},
                # Format and filename are handled as remaining positional args
            },
            'contrast': {
                'input_key': {'required': True, 'type': str},
                'contrast_level': {'required': True, 'type': float},
                'output_key': {'required': True, 'type': str}
            },
            'resize': {
                'input_key': {'required': True, 'type': str},
                'width': {'required': True, 'type': str},  # Can be "iw/2" etc.
                'height': {'required': True, 'type': str},
                'output_key': {'required': True, 'type': str}
            },
            'crop': {
                'input_key': {'required': True, 'type': str},
                'x': {'required': True, 'type': str},
                'y': {'required': True, 'type': str},
                'width': {'required': True, 'type': str},
                'height': {'required': True, 'type': str},
                'output_key': {'required': True, 'type': str}
            },
            'rotate': {
                'input_key': {'required': True, 'type': str},
                'angle': {'required': True, 'type': float},
                'output_key': {'required': True, 'type': str}
            },
            'filter': {
                'input_key': {'required': True, 'type': str},
                'filter_type': {'required': True, 'type': str},
                'output_key': {'required': True, 'type': str}
            },
            'trim': {
                'input_key': {'required': True, 'type': str},
                'start_time': {'required': True, 'type': str},  # "00:00:10"
                'end_time': {'required': True, 'type': str},
                'output_key': {'required': True, 'type': str}
            },
            'speed': {
                'input_key': {'required': True, 'type': str},
                'speed': {'required': True, 'type': float},
                'output_key': {'required': True, 'type': str}
            },
            'volume': {
                'input_key': {'required': True, 'type': str},
                'volume_level': {'required': True, 'type': float},
                'output_key': {'required': True, 'type': str}
            },
            'overlay': {
                'base_key': {'required': True, 'type': str},
                'overlay_key': {'required': True, 'type': str},
                'x': {'required': True, 'type': str},
                'y': {'required': True, 'type': str},
                'output_key': {'required': True, 'type': str}
            },
            'text': {
                'input_key': {'required': True, 'type': str},
                'text': {'required': True, 'type': str},
                'x': {'required': True, 'type': str},
                'y': {'required': True, 'type': str},
                'font_size': {'required': True, 'type': int},
                'font_color': {'required': True, 'type': str},
                'output_key': {'required': True, 'type': str}
            },
            'text2': {
                'input_key': {'required': True, 'type': str},
                'text': {'required': True, 'type': str},
                'x': {'required': True, 'type': str},
                'y': {'required': True, 'type': str},
                'font_size': {'required': True, 'type': int},
                'font_color': {'required': True, 'type': str},
                'outline_color': {'required': True, 'type': str},
                'outline_width': {'required': True, 'type': int},
                'box_color': {'required': True, 'type': str},
                'box_opacity': {'required': True, 'type': float},
                'output_key': {'required': True, 'type': str}
            },
            'audioputreplace': {
                'media_key': {'required': True, 'type': str},
                'audio_key': {'required': True, 'type': str},
                'output_key': {'required': True, 'type': str},
                'preserve_length': {'default': True, 'type': bool},
                'force_video': {'default': False, 'type': bool},
                'loop_media': {'default': False, 'type': bool}
            },
            'audioputmix': {
                'media_key': {'required': True, 'type': str},
                'audio_key': {'required': True, 'type': str},
                'output_key': {'required': True, 'type': str},
                'volume': {'default': 1.0, 'type': float},
                'preserve_length': {'default': True, 'type': bool},
                'loop_audio': {'default': False, 'type': bool},
                'loop_media': {'default': False, 'type': bool}
            }
        }
        self.gscript_commands = {
            'load': self._load_media,
            'reverse': self._reverse_media,
            'concat': self._concat_media,
            'render': self._render_media,
            'contrast': self._adjust_contrast,
            'resize': self._resize_media,
            'crop': self._crop_media,
            'rotate': self._rotate_media,
            'filter': self._apply_filter,
            'trim': self._trim_media,
            'speed': self._change_speed,
            'volume': self._adjust_volume,
            'overlay': self._overlay_media,
            'text': self._overlay_text,
            'text2': self._advanced_text,
            'audioputreplace': self._replace_audio,
            'audioputmix': self._mix_audio
        }
    
    def start_cleanup_task(self):
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
    
    async def _periodic_cleanup(self):
        while True:
            try:
                await self._cleanup_old_files()
                self._last_cleanup = datetime.now()
                await asyncio.sleep(self.cleanup_interval)
            except Exception as e:
                await asyncio.sleep(60)
    async def _cleanup_old_files(self):
        now = datetime.now().timestamp()
        cleaned_files = 0
        cleaned_dirs = 0


        for key, path in list(self.media_cache.items()):
            try:
                if not os.path.exists(path):
                    del self.media_cache[key]
                    continue
                
                file_age = now - os.path.getmtime(path)
                if file_age > self.file_max_age:
                    os.unlink(path)
                    del self.media_cache[key]
                    cleaned_files += 1
            except Exception as e:
                pass

        
        for path in list(self.temp_files):
            try:
                if not os.path.exists(path):
                    self.temp_files.discard(path)
                    continue
                
                file_age = now - os.path.getmtime(path)
                if file_age > self.file_max_age:
                    os.unlink(path)
                    self.temp_files.discard(path)
                    cleaned_files += 1
            except Exception as e:
                pass

        
        try:
            for item in self.temp_dir.glob('*'):
                try:
                    item_age = now - item.stat().st_mtime
                    if item_age > self.file_max_age:
                        if item.is_file():
                            item.unlink()
                            cleaned_files += 1
                        elif item.is_dir():
                            shutil.rmtree(item)
                            cleaned_dirs += 1
                except Exception as e:
                    pass
        except Exception as e:
            pass

    
    async def cleanup(self):
        for proc in self.active_processes:
            if proc.returncode is None:
                try:
                    proc.terminate()
                    await asyncio.sleep(1)
                    if proc.returncode is None:
                        proc.kill()
                except ProcessLookupError:
                    pass
        for file_path in self.media_cache.values():
            try:
                if file_path and os.path.exists(file_path):
                    os.unlink(file_path)
            except Exception as e:
                pass
        for file_path in self.temp_files:
            try:
                if os.path.exists(file_path):
                    os.unlink(file_path)
            except Exception as e:
                pass
        
        try:
            for item in self.temp_dir.glob('*'):
                try:
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)
                except Exception as e:
                    pass
        except Exception as e:
            pass
        
        self.media_cache.clear()
        self.active_processes.clear()
        self.temp_files.clear()
    
    
    def _get_temp_path(self, extension: str = '') -> Path:
        path = self.temp_dir / f"{uuid.uuid4()}{f'.{extension}' if extension else ''}"
        self.temp_files.add(str(path))
        path.touch(exist_ok=True)
        return path
    
    
    def _parse_command_args(self, cmd: str, args: list[str]) -> dict:
        try:
            spec = self.command_specs[cmd]
            parsed = {}
            remaining_args = args.copy()

            def str2bool(v: str) -> bool:
                return str(v).strip().lower() in ('true', '1', 'yes')

            def convert(val: str, typ):
                return str2bool(val) if typ is bool else typ(val)


            spec_items = list(spec.items())
            for i, (param, param_spec) in enumerate(spec_items):
                if not remaining_args:
                    if param_spec.get('required', False):
                        raise ValueError(param)
                    continue

                if '=' in remaining_args[0] and not remaining_args[0].startswith(('http://', 'https://')):
                    break

                value = remaining_args.pop(0)
                try:
                    parsed[param] = convert(value, param_spec['type'])
                except Exception as e:
                    raise ValueError(f"{param}={value} ({e})")


            if cmd == 'concat':
                parsed['input_keys'] = remaining_args
                remaining_args = []
            elif cmd == 'render':
                parsed['extra_args'] = remaining_args
                remaining_args = []


            for arg in remaining_args:
                if '=' in arg:
                    key, value = arg.split('=', 1)
                    key = key.lower()
                    if key in spec:
                        try:
                            parsed[key] = convert(value, spec[key]['type'])
                        except Exception as e:
                            raise ValueError(f"{key}={value} ({e})")
                    else:
                        raise ValueError(f"Unknown argument: {key}")


            for param, param_spec in spec.items():
                if param not in parsed and 'default' in param_spec:
                    parsed[param] = param_spec['default']

            return parsed

        except Exception as e:
            raise ValueError(f"Invalid arguments for {cmd}: {str(e)}")

    
    async def _run_ffmpeg(self, cmd: list) -> tuple:
        if platform.system() == 'Windows':
            cmd[0] = 'ffmpeg.exe'
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if platform.system() == 'Windows'
                else 0
            )
        )

        self.active_processes.add(proc)

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode != 0:
                error_msg = stderr.decode('utf-8', errors='replace').strip()
                if platform.system() == 'Windows':
                    error_msg = error_msg.replace('\r\n', '\n')
                return False, f"FFmpeg error: {error_msg}"
            return True, stdout.decode('utf-8', errors='replace').strip()
        except asyncio.TimeoutError:
            proc.kill()
            return False, "FFmpeg processing took longer than 60 seconds."
        except Exception as e:
            return False, f"Unexpected error: {str(e)}"
        finally:
            self.active_processes.discard(proc)
    
    async def execute_media_script(self, script: str) -> list[str]:
        output_files = []
        for line in script.splitlines():
            line = line.strip()
            if not line:
                continue

            parts = shlex.split(line)
            if not parts:
                continue

            cmd = parts[0].lower()
            args = parts[1:]

            if cmd not in self.gscript_commands:
                return [f"Unknown command: {cmd}"]

            try:
                parsed_args = self._parse_command_args(cmd, args)
                func = self.gscript_commands[cmd]
                result = await func(**parsed_args)

                if isinstance(result, str) and result.startswith("Error"):
                    return [result]
                if cmd == "render" and isinstance(result, str) and result.startswith("media://"):
                    output_files.append(result[8:])
            except Exception as e:
                return [str(e) if 'result' not in locals() else f"Error in {cmd}: {result} ({str(e)})"]
    
        return output_files if output_files else ["Processing complete"]
    
    async def _load_media(self, **kwargs) -> str:
        try:
            return await self._load_media_impl(**kwargs)
        except ValueError as e:
            return f"Load error: {str(e)}"

    
    async def _load_media_impl(self, **kwargs) -> str:
        url = kwargs['url']
        media_key = kwargs['media_key']
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return f"HTTP Error {resp.status}"
                
                    ext = Path(url.split('?')[0]).suffix[1:] or 'tmp'
                    temp_file = self._get_temp_path(ext)

                    with temp_file.open('wb') as f:
                        async for chunk in resp.content.iter_chunked(8192):
                            f.write(chunk)
                
                    self.media_cache[media_key] = str(temp_file)
                    return f"Loaded {media_key}"
        except Exception as e:
            return f"Download error: {str(e)}"
    
    async def _reverse_media(self, **kwargs) -> str:
        try:
            return await self._reverse_media_impl(**kwargs)
        except ValueError as e:
            return f"Reverse error: {str(e)}"
    
    async def _reverse_media_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        output_key = kwargs['output_key']
        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"
        input_path = Path(self.media_cache[input_key])
        output_file = self._get_temp_path(input_path.suffix[1:])
        suffix = input_path.suffix.lower()
        if suffix in ('.mp4', '.mov', '.webm', '.mkv', '.avi', '.wmv'):
            cmd = [
                'ffmpeg', '-hide_banner',
                '-i', input_path.as_posix(),
                '-vf', 'reverse',
                '-af', 'areverse',
                '-y', output_file.as_posix()
            ]
        elif suffix in '.gif':
            cmd = [
                'ffmpeg', '-hide_banner',
                '-i', input_path.as_posix(),
                '-vf', 'reverse',
                '-y', output_file.as_posix()
            ]
        else:
            cmd = [
                'ffmpeg', '-hide_banner',
                '-i', input_path.as_posix(),
                '-af', 'areverse',
                '-y', output_file.as_posix()
            ]
        
        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
    async def _concat_media(self, **kwargs) -> str:
        try:
            return await self._concat_media_impl(**kwargs)
        except ValueError as e:
            return f"Concat error: {str(e)}"
    
    async def _concat_media_impl(self, **kwargs) -> str:
        input_keys = kwargs['input_keys']
        output_key = kwargs['output_key']
        if len(input_keys) < 2:
            return "Error: Need at least 2 inputs"
        
        missing = [k for k in input_keys if k not in self.media_cache]
        if missing:
            return f"Error: Missing keys {', '.join(missing)}"
        
        list_file = self._get_temp_path('txt')
        with list_file.open('w', encoding='utf-8') as f:
            for key in input_keys:
                f.write(f"file '{Path(self.media_cache[key]).as_posix()}'\n")
        
        output_file = self._get_temp_path('mp4')
        cmd = [
            'ffmpeg', '-hide_banner',
            '-f', 'concat',
            '-safe', '0',
            '-i', list_file.as_posix(),
            '-c', 'copy',
            '-y', output_file.as_posix()
        ]
        
        success, error = await self._run_ffmpeg(cmd)
        list_file.unlink(missing_ok=True)
        
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
    async def _render_media(self, **kwargs) -> str:
        try:
            return await self._render_media_impl(**kwargs)
        except ValueError as e:
            return f"Render error: {str(e)}"
    
    async def _render_media_impl(self, **kwargs) -> str:
        media_key = kwargs['media_key']
        extra_args = kwargs['extra_args']
        path = Path(self.media_cache[media_key])
        if not path.exists():
            return f"Error: File for {media_key} missing"
        
        output_format = None
        output_filename = None

        for arg in extra_args:
            if arg.startswith(('video/', 'audio/', 'image/')) or arg in ('mp4', 'mov', 'webm', 'mkv', 'avi', 'wmv', 'gif', 'png', 'jpg', 'jpeg', 'webp', 'mp3', 'ogg', 'wav', 'opus', 'flac', 'm4a', 'wma', 'mka'):
                output_format = arg
            else:
                output_filename = arg
        
        if output_format:
            new_ext = {
                'video/mp4': 'mp4',
                'video/quicktime': 'mov',
                'video/webm': 'webm',
                'video/x-matroska': 'mkv',
                'video/x-msvideo': 'avi',
                'video/x-ms-wmv': 'wmv',
                'image/gif': 'gif',
                'image/png': 'png',
                'image/jpg': 'jpg',
                'image/jpeg': 'jpeg',
                'image/webp': 'webp',
                'audio/mpeg': 'mp3',
                'audio/ogg': 'ogg',
                'audio/wav': 'wav',
                'audio/opus': 'opus',
                'audio/flac': 'flac',
                'audio/mp4': 'm4a',
                'audio/x-ms-wma': 'wma',
                'audio/x-matroska': 'mka'
            }.get(output_format, output_format.split('/')[-1] if '/' in output_format else output_format)
        
            new_path = self._get_temp_path(new_ext)
            cmd = [
                'ffmpeg', '-hide_banner',
                '-i', path.as_posix(),
                '-y', new_path.as_posix()
            ]
            
            success, error = await self._run_ffmpeg(cmd)
            if not success:
                return error
            
            path = new_path
        
        if output_filename:
            final_path = self._get_temp_path(path.suffix[1:])
            final_path = final_path.with_name(output_filename)
            if not final_path.suffix:
                final_path = final_path.with_suffix(path.suffix)
            path.rename(final_path)
            path = final_path
        
        self.media_cache[media_key] = str(path)
        
        return f"media://{path.as_posix()}"
    
    async def _adjust_contrast(self, **kwargs) -> str:
        try:
            return await self._adjust_contrast_impl(**kwargs)
        except ValueError as e:
            return f"Contrast error: {str(e)}"
    
    async def _adjust_contrast_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        contrast_level = kwargs['contrast_level']
        output_key = kwargs['output_key']
        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"

        input_path = Path(self.media_cache[input_key])
        suffix = input_path.suffix.lower()
        allowed_suffixes = ('.mp4', '.mov', '.webm', '.mkv', '.avi', '.wmv', '.gif', '.png', '.jpg', '.jpeg', '.webp')
        if suffix not in allowed_suffixes:
            return f"Error: {input_key} is not a video or image file."
        output_file = self._get_temp_path(input_path.suffix[1:])

        cmd = [
            'ffmpeg', '-hide_banner',
            '-i', input_path.as_posix(),
            '-vf', f'eq=contrast={contrast_level}',
            '-y', output_file.as_posix()
        ]
        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
    async def _resize_media(self, **kwargs) -> str:
        try:
            return await self._resize_media_impl(**kwargs)
        except ValueError as e:
            return f"Resize error: {str(e)}"
    
    async def _resize_media_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        width = kwargs['width']
        height = kwargs['height']
        output_key = kwargs['output_key']
        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"

        input_path = Path(self.media_cache[input_key])
        suffix = input_path.suffix.lower()
        allowed_suffixes = ('.mp4', '.mov', '.webm', '.mkv', '.avi', '.wmv', '.gif', '.png', '.jpg', '.jpeg', '.webp')
        if suffix not in allowed_suffixes:
            return f"Error: {input_key} is not a video or image file."
        output_file = self._get_temp_path(input_path.suffix[1:])

        cmd = [
            'ffmpeg', '-hide_banner',
            '-i', input_path.as_posix(),
            '-vf', f'scale={width}:{height}',
            '-y', output_file.as_posix()
        ]
        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
    async def _crop_media(self, **kwargs) -> str:
        try:
            return await self._crop_media_impl(**kwargs)
        except ValueError as e:
            return f"Crop error: {str(e)}"
    
    async def _crop_media_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        x = kwargs['x']
        y = kwargs['y']
        width = kwargs['width']
        height = kwargs['height']
        output_key = kwargs['output_key']
        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"

        input_path = Path(self.media_cache[input_key])
        suffix = input_path.suffix.lower()
        allowed_suffixes = ('.mp4', '.mov', '.webm', '.mkv', '.avi', '.wmv', '.gif', '.png', '.jpg', '.jpeg', '.webp')
        if suffix not in allowed_suffixes:
            return f"Error: {input_key} is not a video or image file."
        output_file = self._get_temp_path(input_path.suffix[1:])

        cmd = [
            'ffmpeg', '-hide_banner',
            '-i', input_path.as_posix(),
            '-vf', f'crop={width}:{height}:{x}:{y}',
            '-y', output_file.as_posix()
        ]
        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    async def _rotate_media(self, **kwargs) -> str:
        try:
            return await self._rotate_media_impl(**kwargs)
        except ValueError as e:
            return f"Rotate error: {str(e)}"
    
    async def _rotate_media_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        angle = kwargs['angle']
        output_key = kwargs['output_key']
        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"

        input_path = Path(self.media_cache[input_key])
        suffix = input_path.suffix.lower()
        allowed_suffixes = ('.mp4', '.mov', '.webm', '.mkv', '.avi', '.wmv', '.gif', '.png', '.jpg', '.jpeg', '.webp')
        if suffix not in allowed_suffixes:
            return f"Error: {input_key} is not a video or image file."
        output_file = self._get_temp_path(input_path.suffix[1:])

        cmd = [
            'ffmpeg', '-hide_banner',
            '-i', input_path.as_posix(),
            '-vf', f'rotate={angle}*PI/180',
            '-y', output_file.as_posix()
        ]
        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
    async def _apply_filter(self, **kwargs) -> str:
        try:
            return await self._apply_filter_impl(**kwargs)
        except ValueError as e:
            return f"Filter error: {str(e)}"
    
    async def _apply_filter_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        filter_type = kwargs['filter_type']
        output_key = kwargs['output_key']
        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"

        input_path = Path(self.media_cache[input_key])
        suffix = input_path.suffix.lower()
        allowed_suffixes = ('.mp4', '.mov', '.webm', '.mkv', '.avi', '.wmv', '.gif', '.png', '.jpg', '.jpeg', '.webp')
        if suffix not in allowed_suffixes:
            return f"Error: {input_key} is not a video or image file."
        output_file = self._get_temp_path(input_path.suffix[1:])

        filter_map = {
            'grayscale': 'format=gray',
            'sepia': 'colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131'
        }

        if filter_type not in filter_map:
            return f"Error: Unknown filter type {filter_type}"

        cmd = [
            'ffmpeg', '-hide_banner',
            '-i', input_path.as_posix(),
            '-vf', filter_map[filter_type],
            '-y', output_file.as_posix()
        ]
        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
    async def _trim_media(self, **kwargs) -> str:
        try:
            return await self._trim_media_impl(**kwargs)
        except ValueError as e:
            return f"Trim error: {str(e)}"
    
    async def _trim_media_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        start_time = kwargs['start_time']
        end_time = kwargs['end_time']
        output_key = kwargs['output_key']
        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"

        input_path = Path(self.media_cache[input_key])
        output_file = self._get_temp_path(input_path.suffix[1:])

        cmd = [
            'ffmpeg', '-hide_banner',
            '-i', input_path.as_posix(),
            '-ss', start_time,
            '-to', end_time,
            '-y', output_file.as_posix()
        ]
        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
    async def _change_speed(self, **kwargs) -> str:
        try:
            return await self._change_speed_impl(**kwargs)
        except ValueError as e:
            return f"Speed error: {str(e)}"
    
    async def _change_speed_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        speed = kwargs['speed']
        output_key = kwargs['output_key']
        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"

        input_path = Path(self.media_cache[input_key])
        output_file = self._get_temp_path(input_path.suffix[1:])
        suffix = input_path.suffix.lower()
        try:
            speed = float(speed)
        except ValueError:
            return f"Error: invalid speed value `{speed}`. Must be a number."
        if suffix in ('.mp4', '.mov', '.webm', '.mkv', '.avi', '.wmv'):
            cmd = [
                'ffmpeg', '-hide_banner',
                '-i', input_path.as_posix(),
                '-filter_complex', f'[0:v]setpts={1/speed}*PTS[v];[0:a]atempo={speed}[a]',
                '-map', '[v]',
                '-map', '[a]',
                '-y', output_file.as_posix()
            ]
        elif suffix in '.gif':
            cmd = [
                'ffmpeg', '-hide_banner',
                '-i', input_path.as_posix(),
                '-vf', f'setpts={1/speed}*PTS',
                '-y', output_file.as_posix()
            ]
        else:
            cmd = [
                'ffmpeg', '-hide_banner',
                '-i', input_path.as_posix(),
                '-af', f'atempo={speed}',
                '-y', output_file.as_posix()
            ]
        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
    async def _adjust_volume(self, **kwargs) -> str:
        try:
            return await self._adjust_volume_impl(**kwargs)
        except ValueError as e:
            return f"Volume error: {str(e)}"
    
    async def _adjust_volume_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        volume_level = kwargs['volume_level']
        output_key = kwargs['output_key']
        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"

        input_path = Path(self.media_cache[input_key])
        suffix = input_path.suffix.lower()
        allowed_suffixes = ('.mp4', '.mov', '.webm', '.mkv', '.avi', '.wmv', '.mp3', '.ogg', '.wav', '.opus', '.flac', '.m4a', '.wma', '.mka')
        if suffix not in allowed_suffixes:
            return f"Error: {input_key} is not a video or audio file."
        output_file = self._get_temp_path(input_path.suffix[1:])

        cmd = [
            'ffmpeg', '-hide_banner',
            '-i', input_path.as_posix(),
            '-af', f'volume={volume_level}',
            '-y', output_file.as_posix()
        ]
        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
    async def _overlay_media(self, **kwargs) -> str:
        try:
            return await self._overlay_media_impl(**kwargs)
        except ValueError as e:
            return f"Overlay error: {str(e)}"
    
    async def _overlay_media_impl(self, **kwargs) -> str:
        base_key = kwargs['base_key']
        overlay_key = kwargs['overlay_key']
        x = kwargs['x']
        y = kwargs['y']
        output_key = kwargs['output_key']
        if base_key not in self.media_cache or overlay_key not in self.media_cache:
            return f"Error: One of the keys not found"

        base_path = Path(self.media_cache[base_key])
        overlay_path = Path(self.media_cache[overlay_key])
        allowed_suffixes = ('.mp4', '.mov', '.webm', '.mkv', '.avi', '.wmv', '.gif', '.png', '.jpg', '.jpeg', '.webp')
        base_suffix = base_path.suffix.lower()
        overlay_suffix = overlay_path.suffix.lower()
        if base_suffix not in allowed_suffixes or overlay_suffix not in allowed_suffixes:
            return f"Error: Overlay requires video or image files."
        output_file = self._get_temp_path(base_path.suffix[1:])

        cmd = [
            'ffmpeg', '-hide_banner',
            '-i', base_path.as_posix(),
            '-i', overlay_path.as_posix(),
            '-filter_complex', f'overlay={x}:{y}',
            '-y', output_file.as_posix()
        ]
        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
    async def _overlay_text(self, **kwargs) -> str:
        try:
            return await self._overlay_text_impl(**kwargs)
        except ValueError as e:
            return f"Text error: {str(e)}"
    
    async def _overlay_text_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        text = kwargs['text']
        x = kwargs['x']
        y = kwargs['y']
        font_size = kwargs['font_size']
        font_color = kwargs['font_color']
        output_key = kwargs['output_key']
        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"
        
        input_path = Path(self.media_cache[input_key])
        suffix = input_path.suffix.lower()
        allowed_suffixes = ('.mp4', '.mov', '.webm', '.mkv', '.avi', '.wmv', '.gif', '.png', '.jpg', '.jpeg', '.webp')
        if suffix not in allowed_suffixes:
            return f"Error: text requires video or image files."
        output_file = self._get_temp_path(input_path.suffix[1:])
        cmd = [
            'ffmpeg', '-hide_banner',
            '-i', input_path.as_posix(),
            '-vf', f'drawtext=text=\'{text}\':fontfile=fonts/arial.ttf:x={x}:y={y}:fontsize={font_size}:fontcolor={font_color}',
            '-y', output_file.as_posix()
        ]
        
        success, error = await self._run_ffmpeg(cmd)
        if not success:
            return f"Text overlay failed: {error}"
        self.media_cache[output_key] = str(output_file)
        return f"media://{output_file}"
    
    async def _advanced_text(self, **kwargs) -> str:
        try:
            return await self._advanced_text_impl(**kwargs)
        except ValueError as e:
            return f"Advanced Text error: {str(e)}"
    
    async def _advanced_text_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        text = kwargs['text']
        x = kwargs['x']
        y = kwargs['y']
        font_size = kwargs['font_size']
        font_color = kwargs['font_color']
        outline_color = kwargs['outline_color']
        outline_width = kwargs['outline_width']
        box_color = kwargs['box_color']
        box_opacity = kwargs['box_opacity']
        output_key = kwargs['output_key']
        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"
    
        input_path = Path(self.media_cache[input_key])
        output_file = self._get_temp_path(input_path.suffix[1:])
        text = text.replace("'", "'\\''")
        drawtext_filter = (
            f"drawtext=text='{text}':"
            f"fontfile=fonts/arial.ttf:"
            f"x={x}:y={y}:"
            f"fontsize={font_size}:"
            f"fontcolor={font_color}:"
            f"bordercolor={outline_color}:"
            f"borderw={outline_width}:"
            f"box=1:boxcolor={box_color}@{box_opacity}"
        )

        cmd = [
            'ffmpeg', '-hide_banner',
            '-i', input_path.as_posix(),
            '-vf', drawtext_filter,
            '-y', output_file.as_posix()
        ]
        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
    async def _replace_audio(self, **kwargs) -> str:
        try:
            return await self._replace_audio_impl(**kwargs)
        except ValueError as e:
            return f"Audio Put Replace error: {str(e)}"
    
    async def _replace_audio_impl(self, **kwargs) -> str:
        media_key = kwargs['media_key']
        audio_key = kwargs['audio_key']
        output_key = kwargs['output_key']
        preserve_length = kwargs['preserve_length']
        force_video = kwargs['force_video']
        loop_media = kwargs['loop_media']
        if media_key not in self.media_cache or audio_key not in self.media_cache:
            return "Error: Missing input media"
    
        media_path = Path(self.media_cache[media_key])
        audio_path = Path(self.media_cache[audio_key])
        is_image = media_path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp')
    
        if is_image or force_video:
            output_ext = 'mp4'
        else:
            output_ext = media_path.suffix[1:]
    
        output_file = self._get_temp_path(output_ext)
    
        cmd = ['ffmpeg', '-hide_banner']
        if is_image or loop_media:
            cmd.extend(['-stream_loop', '-1'])
        
        cmd.extend([
            '-i', media_path.as_posix(),
            '-i', audio_path.as_posix()
        ])
        if preserve_length or loop_media:
            cmd.append('-shortest')

        if is_image or force_video:
            cmd.extend(['-c:v', 'libx264'])
        else:
            cmd.append('-c:v')
            cmd.append('copy')
        
        if loop_media:
            cmd.extend(['-filter_complex', '[1]aloop=loop=-1:size=1e+09[audio_loop]'])
            cmd.append('-map')
            cmd.append('0:v')
            cmd.append('-map')
            cmd.append('[audio_loop]')
        else:
            cmd.extend(['-map', '0:v', '-map', '1:a'])
        
        
        cmd.append('-y')
        cmd.append(output_file.as_posix())
    
        success, error = await self._run_ffmpeg([x for x in cmd if x is not None])
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
    async def _mix_audio(self, **kwargs) -> str:
        try:
            return await self._mix_audio_impl(**kwargs)
        except ValueError as e:
            return f"Audio Put Mix error: {str(e)}"
    
    async def _mix_audio_impl(self, **kwargs) -> str:
        media_key = kwargs['media_key']
        audio_key = kwargs['audio_key']
        output_key = kwargs['output_key']
        volume = kwargs['volume']
        loop_audio = kwargs['loop_audio']
        preserve_length = kwargs['preserve_length']
        loop_media = kwargs['loop_media']
        if media_key not in self.media_cache or audio_key not in self.media_cache:
            return "Error: Missing input media"
    
        media_path = Path(self.media_cache[media_key])
        audio_path = Path(self.media_cache[audio_key])
        is_image = media_path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp')
        is_audio = media_path.suffix.lower() in ('.mp3', '.wav', '.ogg', '.opus', '.flac', '.m4a', '.mka', '.wma')
    
        output_ext = 'mp4' if (is_image or not is_audio) else media_path.suffix[1:]
        output_file = self._get_temp_path(output_ext)
    
        cmd = [
            'ffmpeg', '-hide_banner',
            *(['-stream_loop', '-1', '-r', '25'] if is_image or loop_media else []),
            '-i', media_path.as_posix(),
            '-i', audio_path.as_posix()
        ]

        audio_filter = []
        if loop_audio and not is_image:
            audio_filter.append(
                f'[1:a]aloop=loop=-1:size=2e+9,asetpts=N/SR/TB[looped]'
            )
            audio_input = '[looped]'
        else:
            audio_input = '[1:a]'

        audio_filter.extend([
            f'[0:a]aformat=sample_fmts=fltp,volume={volume}[a0]',
            f'{audio_input}aformat=sample_fmts=fltp,volume={volume}[a1]',
            f'[a0][a1]amix=inputs=2:duration=longest[a]'
        ])

        filter_complex_str = ';'.join(audio_filter)


        should_apply_shortest = not loop_audio and not preserve_length

        cmd.extend([
            '-filter_complex', filter_complex_str,
            *(['-c:v', 'libx264', '-pix_fmt', 'yuv420p'] if is_image else 
            ['-c:v', 'copy'] if not is_audio else []),
            '-map', '0:v:0' if not is_audio else None,
            '-map', '[a]',
            *(['-shortest'] if should_apply_shortest else []),
            '-y', output_file.as_posix()
        ])
    
        success, error = await self._run_ffmpeg([x for x in cmd if x is not None])
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error




class TagFormatter:
    def __init__(self):
        self.functions: Dict[str, Callable] = {}
    
    def register(self, name: str):
        def decorator(func: Callable):
            self.functions[name] = func
            return func
        return decorator
    
    async def format(self, content: str, ctx: commands.Context, **kwargs) -> str:
        async def process_chunk(chunk: str) -> str:
            if not chunk.startswith('{') or not chunk.endswith('}'):
                return chunk
            
            inner = chunk[1:-1]
            parts = inner.split(':', 1)
            name = parts[0].strip()
        
            if name in self.functions:
                try:
                    args = parts[1] if len(parts) > 1 else ''
                    processed_args = await self.format(args, ctx, **kwargs)
                    func = self.functions[name]
                    result = func(ctx, processed_args, **kwargs)
                    if asyncio.iscoroutine(result):
                        result = await result
                    return str(result)
                except Exception:
                    return chunk
            return chunk


        chunks = []
        pos = 0
        depth = 0
        start = 0
    
        for i, c in enumerate(content):
            if c == '{':
                if depth == 0:
                    if pos < i:
                        chunks.append(content[pos:i])
                    start = i
                depth += 1
            elif c == '}' and depth > 0:
                depth -= 1
                if depth == 0:
                    chunks.append(content[start:i+1])
                    pos = i + 1
    

        if pos < len(content):
            chunks.append(content[pos:])
    

        processed_chunks = []
        for chunk in chunks:
            if chunk.startswith('{') and chunk.endswith('}'):
                processed_chunks.append(await process_chunk(chunk))
            else:
                processed_chunks.append(chunk)
        
        return ''.join(processed_chunks)
    
    async def resolve_user(self, ctx, input_str: str) -> Union[discord.User, discord.Member]:
        input_str = input_str.strip()

        if not input_str:
            return ctx.author
        
        try:
            user_id = int(input_str.strip('<@!>'))
            user = await ctx.bot.fetch_user(user_id)
            return user
        except (ValueError, discord.NotFound):
            pass

        if ctx.guild:
            member = discord.utils.find(
                lambda m: m.name.lower() == input_str.lower() or m.display_name.lower() == input_str.lower(),
                ctx.guild.members
            )
            if member:
                return member
        
        return ctx.author

class Tags(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pool = bot.pool
        self._variables = {}
        self.formatter = TagFormatter()
        self.processor = MediaProcessor()
        self.setup_formatters()
        self.media_cache = {}
        self.setup_media_formatters()
        self.active_processes = set()
        self._cleanup_task = None
        self.start_cleanup_task()
    
    def start_cleanup_task(self):
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        
        asyncio.create_task(self.cleanup_resources())
    
    async def _periodic_cleanup(self):
        while True:
            try:
                await self.processor._cleanup_old_files()
                now = datetime.now()
                for msg_id, vars_data in list(self._variables.items()):
                    if (now - vars_data.get('_timestamp', now)).total_seconds() > 86400:
                        del self._variables[msg_id]
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                return
            except Exception as e:
                await asyncio.sleep(300)
    
    async def cleanup_resources(self):
        try:
            await self.processor.cleanup()
            self._variables.clear()
        except Exception as e:
            pass
    
    
    
    def setup_media_formatters(self):
        @self.formatter.register('gscript')
        async def _gscript(ctx, script, **kwargs):
            """
            G-Man Script. (GScript for short.)

            """
            try:
                results = await self.processor.execute_media_script(script)
                file_paths = [Path(p) for p in results if not p.startswith("Error") and p != "Processing complete"]
                file_paths = [f for f in file_paths if f.exists() and f.is_file()]

                if not file_paths:
                    return "\n".join(results)

                files = []
                for path in file_paths:
                    if path.stat().st_size <= ctx.guild.filesize_limit if ctx.guild else 10 * 1024 * 1024:
                        files.append(discord.File(path))

                if not files:
                    return "All output files were too large to upload."

                try:
                    await ctx.send(files=files[:10])
                except Exception as e:
                    return f"Upload error: {str(e)}"
                finally:
                    for fp in file_paths:
                        try:
                            if fp.exists():
                                fp.unlink(missing_ok=True)
                                self.processor.temp_files.discard(str(fp))
                        except Exception as e:
                            pass

                return ""
            except Exception as e:
                await self.processor.cleanup()
                return f"Script processing error: {str(e)}"

    
    def setup_formatters(self):
        @self.formatter.register('eval')
        async def _eval(ctx, val, **kwargs):
            """
            ### {eval:content}
                * Processes nested tag functions in the content.
                * Example: `{eval:Hello {user}!}`
            """
            return await self.process_tags(ctx, val, kwargs.get('args', ''))
            
        @self.formatter.register('args')
        def args(ctx, _, **kwargs):
            """
            ### {args}
                * Returns all arguments passed to the tag.
                * Example: `{args}`
            """
            return kwargs.get('args', '')
            
        @self.formatter.register('arg')
        async def arg(ctx, i, **kwargs):
            """
            ### {arg:index}
                * Returns the argument at the specified index. (0-based)
                * Example: `{arg:1}` returns the second argument.
            """
            args_string = kwargs.get('args', '')
            args_list = args_string.split()

            processed_input = await ctx.cog.formatter.format(i, ctx, **kwargs)

            try:
                index = int(processed_input.strip())
            except ValueError:
                return f"[arg error: invalid index `{processed_input.strip()}`]"
            
            if 0 <= index < len(args_list):
                return args_list[index]
            return ''
            
        @self.formatter.register('rest')
        def rest(ctx, i, **kwargs):
            """
            ### {rest:index}
                * Returns all arguments from the specified index onward.
                * Example: `{rest:2}` returns arguments starting from the 3rd one.
            """
            split_args = kwargs.get('args', '').split()
            return ' '.join(split_args[int(i):]) if i.isdigit() else ''
            
        @self.formatter.register('default')
        def default(ctx, val, fb, **kwargs):
            """
            ### {default:value|fallback}
                * Returns `value` if it exists, otherwise returns `fallback`.
                * Example: `{default:{arg:0}|No argument provided}`
            """
            return val if val else fb
        
        @self.formatter.register('newline')
        def _newline(ctx, _, **kwargs):
            """
            ### {newline}
                * Inserts a newline character.
                * Example: `Line1{newline}Line2`
                * Can be useful inside slash commands.
            """
            return '\n'
        
        @self.formatter.register('substring')
        async def _substring(ctx, args_str, **kwargs):
            """
            ### {substring:text|start|end|step}
                * Extracts a substring.
                * Example: `{substring:Hello World|6|11}` -> "World"
            """
            try:
                processed_input = await ctx.cog.formatter.format(args_str, ctx, **kwargs)

                if '|' in processed_input:
                    parts = [p.strip() for p in processed_input.split('|') if p.strip()]
                else:
                    parts = [p.strip() for p in processed_input.split(':', 2) if p.strip()]
                
                if len(parts) < 2:
                    return "[error: substring requires atleast text and start position]"
                
                text = parts[0]
                length = len(text)
                
                try:
                    start = int(parts[1])
                    if start < 0:
                        start = max(length + start, 0)
                    start = min(start, length)
                except ValueError:
                    return f"[error: invalid start position `{parts[1]}`]"
                
                end = length
                step = 1

                if len(parts) >= 3 and parts[2]:
                    try:
                        end = int(parts[2])
                        if end < 0:
                            end = length + end
                        end = min(max(end, 0), length)
                    except ValueError:
                        return f"[error: invalid end position `{parts[2]}`]"
                
                if len(parts) >= 4 and [parts[3]]:
                    try:
                        step = int(parts[3])
                        if step == 0:
                            return "[error: step cannot be zero]"
                    except ValueError:
                        return f"[error: invalid step position `{parts[3]}]"
                
                start = min(max(start, 0), length)
                end = min(max(end, 0), length)

                return text[start:end:step]
            except Exception as e:
                return f"[substring error: {str(e)}]"
        
        @self.formatter.register('replace')
        async def _replace(ctx, args_str, **kwargs):
            """
            ### {replace:text|find|replace|flags}
                * Replaces text with various options.
                * Flags: i (case insensitive), r (regex), w (whole words), g (global), c (count)
                * Example: `{replace:Hello|e|a}` -> "Hallo
            """
            try:
                processed_input = await ctx.cog.formatter.format(args_str, ctx, **kwargs)
                
                if '|' in processed_input:
                    parts = [p.strip() for p in processed_input.split('|')]
                else:
                    parts = [p.strip() for p in processed_input.split(':')]
                
                if len(parts) < 3:
                    return processed_input
                
                text = parts[0]
                find = parts[1]
                replace = parts[2]
                flags = parts[3].lower() if len(parts) > 3 else ''
                
                if not find:
                    return text
                
                if 'c' in flags:
                    if 'r' in flags:
                        re_flags = re.IGNORECASE if 'i' in flags else 0
                        if 'w' in flags:
                            find = r'\b' + find + r'\b'
                        try:
                            return str(len(re.findall(find, text, flags=re_flags)))
                        except re.error:
                            return text
                    else:
                        if 'i' in flags:
                            return str(text.lower().count(find.lower()))
                        if 'w' in flags:
                            words = text.split()
                            find_lower = find.lower() if 'i' in flags else find
                            count = sum(1 for word in words
                                        if (word.lower() == find_lower.lower() if 'i' in flags 
                                        else word == find))
                            return str(count)
                        return str(text.count(find))
                
                if 'r' in flags:
                    re_flags = re.IGNORECASE if 'i' in flags else 0
                    if 'w' in flags:
                        find = r'\b' + find + r'\b'
                    try:
                        pattern = re.compile(find, flags=re_flags)
                        return pattern.sub(replace, text)
                    except re.error:
                        return text
                else:
                    if 'w' in flags:
                        words = text.split()
                        find_lower = find.lower()
                        replaced = []
                        for word in words:
                            if ('i' in flags and word.lower() == find_lower) or word == find:
                                replaced.append(replace)
                            else:
                                replaced.append(word)
                        return ' '.join(replaced)
                    elif 'i' in flags:
                        return re.sub(re.escape(find), replace, text, flags=re.IGNORECASE)
                    else:
                        return text.replace(find, replace)
    
            except Exception:
                return args_str
        
        @self.formatter.register('reverse')
        async def _reverse(ctx, text, **kwargs):
            """
            ### {reverse:text}
                * Reverses the given text.
                * Example: `{reverse:hello}` -> "olleh"
            """
            try:
                processed_text = await ctx.cog.formatter.format(text, ctx, **kwargs)
                return processed_text[::-1]
            except Exception:
                return text
            
        @self.formatter.register('if')
        async def _if(ctx, args_str, **kwargs):
            """
            ### {if:left|operator|right|then|value|else|value}
                * Conditional statement with comparison operators.
                * Operators: ==, !=, >=, <=, >, <, *= (contains), ^= (starts with), $= (ends with), ~= (regex match)
                * Prefix the 4 special operators with `!` to reverse them. (!*=)
                * Example: `{if:{arg:0}|==|hello|then|World|else|Goodbye}`
            """
            raw = self.parse_args(args_str)
            if len(raw) < 5:
                return "[error: insufficient arguments for if]"

            left_raw, op_raw, right_raw, *rest = raw


            then_raw = else_raw = ""
            for key, val in zip(rest[::2], rest[1::2]):
                if key.lower() == "then":
                    then_raw = val
                elif key.lower() == "else":
                    else_raw = val


            left  = await self.formatter.format(left_raw,  ctx, **kwargs)
            right = await self.formatter.format(right_raw, ctx, **kwargs)


            ops: dict[str, Callable[[str,str], bool]] = {
                "==": operator.eq,
                "!=": operator.ne,
                ">=": operator.ge,
                "<=": operator.le,
                ">":  operator.gt,
                "<":  operator.lt,
                "*=": lambda a, b: b in a,
                "^=": lambda a, b: a.startswith(b),
                "$=": lambda a, b: a.endswith(b),
                "~=": lambda a, b: re.search(b, a) is not None,
            }

            negate = False
            if op_raw.startswith("!") and op_raw not in ops:
                negate = True
                op_raw = op_raw[1:]

            func = ops.get(op_raw)
            if func is None:
                return f"[error: unknown operator '{op_raw}']"

            result = func(left, right)
            if negate:
                result = not result

            chosen_raw = then_raw if result else else_raw
            return await self.formatter.format(chosen_raw, ctx, **kwargs)
        
        @self.formatter.register('random')
        async def _random(ctx, args_str, **kwargs):
            """
            ### {random:min|max}
                * Generates a random integer between min and max (inclusive)
                * Example: `{random:1|6}` -> "5"
            """
            try:
                processed = await ctx.cog.formatter.format(args_str, ctx, **kwargs)
                if '|' in processed:
                    min_val, max_val = processed.split('|', 1)
                else:
                    min_val, max_val = '1', processed
                
                min_val = int(min_val.strip())
                max_val = int(max_val.strip())

                if min_val > max_val:
                    min_val, max_val = max_val, min_val
                
                return str(random.randint(min_val, max_val))
            except Exception:
                return "[random error: invalid input]"
        
        @self.formatter.register('dice')
        async def _dice(ctx, notation, **kwargs):
            """
            ### {dice:notation}
                * Rolls the dice. (uses dice notation)
                * Example: `{dice:2d6+1}` -> Rolls 2 six-sided dice and adds 1
            """
            try:
                processed = await ctx.cog.formatter.format(notation, ctx, **kwargs)
                parts = re.split(r'[d+-]', processed)
                modifiers = re.findall(r'[+-]', processed)
        
                count = int(parts[0]) if parts[0] else 1
                sides = int(parts[1])
        
                if count < 1 or sides < 1:
                    return "[dice error: values must be positive]"
        
                rolls = [random.randint(1, sides) for _ in range(count)]
                total = sum(rolls)
        
                if len(modifiers) > 0 and len(parts) > 2:
                    modifier = int(modifiers[0] + parts[2])
                    total += modifier
        
                result = f"{total} ("
                if count > 1:
                    result += f"{'+'.join(map(str, rolls))}"
                    if len(modifiers) > 0 and len(parts) > 2:
                        result += f"{modifiers[0]}{parts[2]}"
                    result += " = "
                result += f"{total})"
        
                return result
            except Exception:
                return "[dice error: invalid notation]"
        
        @self.formatter.register('choose')
        async def _choose(ctx, options_str, **kwargs):
            """
            ### {choose:option1|option2|option3|...}
                * Randomly picks **one** option from the list.
                * Default separator: `|`
                * You can add `@weight` to make options appear more/less frequently.
                    * `{choose:Common@5|Rare@1|Legendary@0.1}`
                    * (Common is 5x more likely than Rare, Legendary is 10x rarer than Rare)
                * You can also use `%` to set exact odds. (weights auto-adjust)
                    * `{choose:Yes%30|No%60|Maybe%10}`
                    * (30% Yes, 60% No, 10% Maybe)
                * You can change the separator with `sep=`:
                    * `{choose:Apple,Banana,Cherry sep=,}`
                    * (Uses commas instead of `|`)
                    * **Escape chars:** Use `\\,` or `\\|` for literal separators.
                * You can combine option groups with `group=true`:
                    * `{choose:{A|B|C} vs {X|Y|Z} group=true}`
                    * **Possible outputs:**
                        * "A vs X"
                        * "B vs Z"
                        * "C vs Y"
                * Use `\\n` for newlines in options:
                    * `{choose:Line1\\nLine2|SingleLine}`
                * Works with other tags:
                    * `{choose:{user} rolled {dice:1d20}!|Try again!}`
            """
            try:
                processed = await ctx.cog.formatter.format(options_str, ctx, **kwargs)
                settings = {}
                if 'sep=' in processed.lower():
                    parts = processed.rsplit('sep=', 1)
                    processed = parts[0]
                    settings["sep"] = parts[1].strip().split()[0].strip("'\"")
                
                if 'group=' in processed.lower():
                    parts = processed.rsplit('group=', 1)
                    processed = parts[0]
                    settings["group"] = parts[1].strip().split()[0].strip().lower() in ('true', 'yes', '1')
        
                sep = settings.get("sep", "|")
                group_mode = settings.get("group", False)

                def process_group(match):
                    options = [opt.strip() for opt in match.group(1).split('|') if opt.strip()]
                    return random.choice(options) if options else ''
                
                if group_mode:
                    processed = re.sub(r'\{([^{}]+)\}', process_group, processed)
        
                raw_parts = re.split(rf'(?<!\\)\{sep}', processed)
                options = []
                weights = []
                total_percent = 0
                percent_entries = []
        
                for part in raw_parts:
                    part = part.replace(f'\\{sep}', sep).strip()
                    if not part:
                        continue
            
                    weight = 1
                    percent = None
            
                    if '%' in part:
                        opt_part, percent_part = part.rsplit('%', 1)
                        opt_part = opt_part.strip()
                        try:
                            percent = float(percent_part.strip())
                            percent_entries.append((len(options), percent))
                            total_percent += percent
                            part = opt_part
                        except ValueError:
                            pass
                    
                    if '%' not in part and '@' in part:
                        opt_part, weight_part = part.rsplit('@', 1)
                        part = opt_part.strip()
                        try:
                            weight = max(1, int(weight_part.strip()))
                        except ValueError:
                            pass
                
            
                    options.append(part)
                    weights.append(weight)
        
                if percent_entries:
                    if total_percent > 100:
                        weights = [1] * len(options)
                    else:
                        for idx, percent in percent_entries:
                            weights[idx] = max(1, int(percent))
        
                if not options:
                    return "[choose error: no valid options]"
        
                choice = random.choices(options, weights=weights or None, k=1)[0]
                return await ctx.cog.formatter.format(choice, ctx, **kwargs)
    
            except Exception as e:
                return f"[choose error: {str(e)}]"
            
        @self.formatter.register('len')
        def _len(ctx, val, **kwargs):
            """
            ### {len:text}
                * Returns the length of the text.
                * Example: `{len:hello}` -> "5"
            """
            return str(len(val))
            
        @self.formatter.register('upper')
        def upper(ctx, val, **kwargs):
            """
            ### {upper:text}
                * Converts text to uppercase.
                * Example: `{upper:hello}` -> "HELLO"
            """
            return val.upper()
            
        @self.formatter.register('lower')
        def lower(ctx, val, **kwargs):
            """
            ### {lower:text}
                * Converts text to lowercase.
                * Example: `{lower:HELLO}` -> "hello"
            """
            return val.lower()
            
        @self.formatter.register('capitalize')
        def capitalize(ctx, val, **kwargs):
            """
            ### {capitalize:text}
                * Capitalizes the first letter.
                * Example: `{capitalize:hello}` -> "Hello"
            """
            return val.capitalize()
            
        @self.formatter.register('set')
        async def _set(ctx, args_str, **kwargs):
            """
            ### {set:name|value}
                * Sets a variable for the tag.
                * Example: `{set:name|John}`
            """
            if not args_str:
                return "[error: missing name|value]"
            
            processed_input = await ctx.cog.formatter.format(args_str, ctx, **kwargs)

            parts = processed_input.split('|', 1)
            if len(parts) < 2:
                return "[error: format should be {set:name|value}]"
            
            name = parts[0].strip()
            value = parts[1].strip()

            ctx.cog._variables.setdefault(ctx.message.id, {})[name] = value
            return ""
            
        @self.formatter.register('get')
        async def _get(ctx, name, **kwargs):
            """
            ### {get:name}
                * Retrieves a previously set variable in the tag.
                * Example: `Hello {get:name}!`
            """
            name = name.strip()
            processed_name = await ctx.cog.formatter.format(name, ctx, **kwargs)
            variables = ctx.cog._variables.get(ctx.message.id, {})
            value = variables.get(processed_name, "")
            return await ctx.cog.formatter.format(value, ctx, **kwargs)
            
        @self.formatter.register('math')
        def math(ctx, expr, **kwargs):
            """
            ### {math:expression}
                * Evaluates a mathematical expression.
                * Example: `{math:5+3*2}` -> "11"
            """
            if not expr:
                return '0'
            try:
                return str(eval(expr, {"__builtins__": None}, {}))
            except Exception as e:
                return f'[error in math: {e}]'
        
        @self.formatter.register('user')
        async def _user(ctx, i, **kwargs):
            """
            ### {user:mention/name/displayname/id}
                * Returns username of mentioned user or self.
                * Example: `{user:@MiniatureEge2006}` -> "miniatureege2006"
            """
            user = await self.formatter.resolve_user(ctx, await self.formatter.format(i, ctx, **kwargs))
            if isinstance(user, discord.Member):
                return user.name
            return user.name
        
        @self.formatter.register('nick')
        async def _nick(ctx, i, **kwargs):
            """
            ### {nick:mention/name/displayname/id}
                * Returns server nickname of mentioned user or self. (returns display name instead if not available)
                * Example: `{nick:@MiniatureEge2006}` -> "Mini"
            """
            user = await self.formatter.resolve_user(ctx, await self.formatter.format(i, ctx, **kwargs))
            if isinstance(user, discord.Member):
                return user.nick
            return user.display_name
        
        @self.formatter.register('userdisplay')
        async def _userdisplay(ctx, i, **kwargs):
            """
            ### {userdisplay:mention/name/displayname/id}
                * Returns display name of mentioned user or self.
                * Example: `{userdisplay:@MiniatureEge2006}` -> "MiniatureEge2006"
            """
            user = await self.formatter.resolve_user(ctx, await self.formatter.format(i, ctx, **kwargs))
            return user.display_name
        
        @self.formatter.register('mention')
        async def _mention(ctx, i, **kwargs):
            """
            ### {mention:mention/name/displayname/id}
                * Mentions the user or self.
                * Example: `{mention:@MiniatureEge2006}` -> "@MiniatureEge2006"
            """
            user = await self.formatter.resolve_user(ctx, await ctx.cog.formatter.format(i, ctx, **kwargs))
            return user.mention
        
        @self.formatter.register('avatar')
        async def _avatar(ctx, i, **kwargs):
            """
            ### {avatar:mention/name/displayname/id}
                * Returns avatar URL. (display avatar, defaults to normal if not available)
                * Example: `{avatar:@MiniatureEge2006}` -> URL
            """
            user = await self.formatter.resolve_user(ctx, await ctx.cog.formatter.format(i, ctx, **kwargs))
            return str(user.display_avatar.url)
        
        @self.formatter.register('useravatar')
        async def _useravatar(ctx, i, **kwargs):
            """
            ### {useravatar:mention/name/displayname/id}
                * Returns avatar URL. (user avatar)
                * Example: `{useravatar:@MiniatureEge2006}` -> URL
            """
            user = await self.formatter.resolve_user(ctx, await ctx.cog.formatter.format(i, ctx, **kwargs))
            return str(user.avatar.url)
        
        @self.formatter.register('banner')
        async def _banner(ctx, i, **kwargs):
            """
            ### {banner:mention/name/displayname/id}
                * Returns banner URL. (display banner)
                * Example: `{banner:@MiniatureEge2006}` -> URL
            """
            user = await self.formatter.resolve_user(ctx, await ctx.cog.formatter.format(i, ctx, **kwargs))
            if isinstance(user, discord.Member):
                user = await ctx.bot.fetch_user(user.id)
                return str(user.banner.url) or f"{user.name} does not have a banner."
            if not user.display_banner:
                return f"{user.name} does not have a banner."
            return str(user.display_banner.url)
        
        @self.formatter.register('userbanner')
        async def _userbanner(ctx, i, **kwargs):
            """
            ### {userbanner:mention/name/displayname/id}
                * Returns banner URL. (user banner)
                * Example: `{userbanner:@MiniatureEge2006}` -> URL
            """
            user = await self.formatter.resolve_user(ctx, await ctx.cog.formatter.format(i, ctx, **kwargs))
            if isinstance(user, discord.Member):
                user = await ctx.bot.fetch_user(user.id)
            if not user.banner:
                return f"{user.name} does not have a banner."
            return str(user.banner.url)
        
        @self.formatter.register('userjoindate')
        async def _userjoindate(ctx, i, **kwargs):
            """
            ### {userjoindate:mention/name/displayname/id}
                * Returns join date in server.
                * Example: `{userjoindate:@MiniatureEge2006}` -> "2025-24-24 12:00:00 (April 24, 2025 at 12:00:00 PM)"
            """
            user = await self.formatter.resolve_user(ctx, await ctx.cog.formatter.format(i, ctx, **kwargs))
            if isinstance(user, discord.Member):
                return user.joined_at.strftime('%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)') if user.joined_at else "Join date not available."
            return "User is not in a server."
        
        @self.formatter.register('userstatus')
        async def _userstatus(ctx, i, **kwargs):
            """
            ### {userstatus:mention/name/displayname/id}
                * Returns user status.
                * Example: `{userstatus:@MiniatureEge2006}` -> "Online"
            """
            user = await self.formatter.resolve_user(ctx, await ctx.cog.formatter.format(i, ctx, **kwargs))
            if isinstance(user, discord.Member):
                return str(user.status.value).capitalize()
            return "User is not in a server."
        
        @self.formatter.register('usercustomstatus')
        async def _usercustomstatus(ctx, i, **kwargs):
            """
            ### {usercustomstatus:mention/name/displayname/id}
                * Returns custom status if set.
                * Example: `{usercustomstatus:@MiniatureEge2006}` -> "Playing Roblox"
            """
            user = await self.formatter.resolve_user(ctx, await ctx.cog.formatter.format(i, ctx, **kwargs))
            if isinstance(user, discord.Member):
                custom_status = user.activity
                if custom_status:
                    activity_type = custom_status.type
                    activity_type_str = {
                        discord.ActivityType.playing: "Playing",
                        discord.ActivityType.streaming: "Streaming",
                        discord.ActivityType.listening: "Listening to",
                        discord.ActivityType.watching: "Watching",
                        discord.ActivityType.competing: "Competing in"
                    }.get(activity_type, "Activity")

                    emoji = custom_status.emoji
                    status = custom_status.state

                    if emoji:
                        return f"{emoji} {activity_type_str} {status}"
                    return f"{activity_type_str} {status}"
            return "User has no status or is not in a server."
        
        @self.formatter.register('userbadges')
        async def _userbadges(ctx, i, **kwargs):
            """
            ### {userbadges:mention/name/displayname/id}
                * Returns user badges.
                * Example: `{userbadges:@MiniatureEge2006}` -> "Active Developer, Early Verified Bot Developer"
            """
            user = await self.formatter.resolve_user(ctx, await ctx.cog.formatter.format(i, ctx, **kwargs))
            if isinstance(user, discord.Member):
                badges = user.public_flags
            elif isinstance(user, discord.User):
                badges = user.public_flags
            else:
                return "User not found."
            badge_names = []

            if badges.staff:
                badge_names.append("Discord Staff")
            if badges.partner:
                badge_names.append("Discord Partner")
            if badges.hypesquad:
                badge_names.append("HypeSquad Events Member")
            if badges.hypesquad_balance:
                badge_names.append("HypeSquad Balance Member")
            if badges.hypesquad_bravery:
                badge_names.append("HypeSquad Bravery Member")
            if badges.hypesquad_brilliance:
                badge_names.append("HypeSquad Brilliance Member")
            if badges.bug_hunter:
                badge_names.append("Discord Bug Hunter")
            if badges.bug_hunter_level_2:
                badge_names.append("Discord Golden Bug Hunter")
            if badges.early_supporter:
                badge_names.append("Early Supporter")
            if badges.team_user:
                badge_names.append("Team User")
            if badges.verified_bot_developer:
                badge_names.append("Early Verified Bot Developer")
            if badges.system:
                badge_names.append("System")
            if badges.active_developer:
                badge_names.append("Active Developer")
            if badges.discord_certified_moderator:
                badge_names.append("Discord Certified Moderator")
            
            if badge_names:
                return ", ".join(badge_names)
            else:
                return "No badges found."
        
        @self.formatter.register('channel')
        async def _channel(ctx, i, **kwargs):
            """
            ### {channel}
                * Returns current channel name.
                * Example: `{channel}` -> "general"
            """
            return ctx.channel.name if ctx.channel else "DMs"
        
        @self.formatter.register('guild')
        async def _guild(ctx, i, **kwargs):
            """
            ### {guild}
                * Returns current server name.
                * Example: `{guild}` -> "G-Server"
            """
            return ctx.guild.name if ctx.guild else "DM"

    
    def parse_args(self, raw: str) -> list[str]:
        if not raw:
            return []
        parts = []
        current = []
        in_quotes = False
        escape = False

        for char in raw:
            if escape:
                current.append(char)
                escape = False
            elif char == '\\':
                escape = True
            elif char == '"':
                in_quotes = not in_quotes
            elif char == '|' and not in_quotes:
                parts.append(''.join(current).strip())
                current = []
            else:
                current.append(char)
        if current:
            parts.append(''.join(current).strip())
        return parts

    async def process_tags(self, ctx: commands.Context, content: str, args: str = "") -> str:
        return await self.formatter.format(content, ctx, args=args)
    
    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.id in self._variables:
            del self._variables[message.id]

    
    @commands.hybrid_group(name="tag", description="Tag management commands.", invoke_without_command=True, with_app_command=True, aliases=["t"])
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def tag(self, ctx: commands.Context, name: str, *, args: str = ""):
        await ctx.typing()
        async with self.pool.acquire() as conn:
            tag = await conn.fetchrow(
                """SELECT content, uses FROM tags
                WHERE name = $1 AND (guild_id = $2 OR user_id = $3)""",
                name, ctx.guild.id if ctx.guild else None, ctx.author.id
            )

            if not tag:
                return await ctx.send(f"Tag `{name}` not found.")
            
            await conn.execute(
                """UPDATE tags SET uses = uses + 1
                WHERE name = $1 AND (guild_id = $2 OR user_id = $3)""",
                name, ctx.guild.id if ctx.guild else None, ctx.author.id
            )
            content = await self.process_tags(ctx, tag['content'], args)
            if content.strip():
                await ctx.send(content)
    
    @tag.command(name="show", description="Show a tag.", with_app_command=True, aliases=["fetch"])
    @app_commands.describe(name="The tag name.", args="The tag arguments, if any.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def show(self, ctx: commands.Context, name: str, *, args: str = ""):
        await ctx.typing()
        async with self.pool.acquire() as conn:
            tag = await conn.fetchrow(
                """SELECT content, uses FROM tags
                WHERE name = $1 AND (guild_id = $2 OR user_id = $3)""",
                name, ctx.guild.id if ctx.guild else None, ctx.author.id
            )

            if not tag:
                return await ctx.send(f"Tag `{name}` not found.")
            
            await conn.execute(
                """UPDATE tags SET uses = uses + 1
                WHERE name = $1 AND (guild_id = $2 OR user_id = $3)""",
                name, ctx.guild.id if ctx.guild else None, ctx.author.id
            )
            content = await self.process_tags(ctx, tag['content'], args)
            if content.strip():
                await ctx.send(content)
    
    @tag.command(name="create", description="Create a tag.", with_app_command=True, aliases=["add"])
    @app_commands.describe(name="The tag name.", content="The tag content.", personal="Make this a personal tag.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def create(self, ctx: commands.Context, name: str, *, content: str, personal: bool = False):
        await ctx.typing()
        if content is None:
            return await ctx.send("Please provide both a name and content for the tag.")
        name = name.lower()
        if len(name) > 50:
            return await ctx.send("Tag names must be 50 characters or less.")
        if len(content) > 2000:
            return await ctx.send("Tag content must be 2000 characters or less.")
        
        try:
            async with self.pool.acquire() as conn:
                if personal or "--personal" in content:
                    if "--personal" in content:
                        content = content.replace("--personal", "").strip()
                        personal = True
                    await conn.execute(
                        """INSERT INTO tags (user_id, name, content, author_id)
                        VALUES ($1, $2, $3, $4)""",
                        ctx.author.id, name, content, ctx.author.id
                    )
                    await ctx.send(f"Created personal tag `{name}`.")
                else:
                    if not ctx.guild:
                        return await ctx.send("Server tags can only be created in servers.")
                    await conn.execute(
                        """INSERT INTO tags (guild_id, name, content, author_id)
                        VALUES ($1, $2, $3, $4)""",
                        ctx.guild.id, name, content, ctx.author.id
                    )
                    await ctx.send(f"Created server tag `{name}`.")
        except asyncpg.UniqueViolationError:
            await ctx.send(f"A tag named `{name}` already exists in this context.")
    
    @tag.command(name="edit", description="Edit an existing tag.", with_app_command=True, aliases=["update"])
    @app_commands.describe(name="The tag name.", new_content="The new content for the tag.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def edit(self, ctx: commands.Context, name: str, *, new_content: str):
        await ctx.typing()
        name = name.lower()
        if not new_content:
            return await ctx.send("Please provide the new content for the tag.")
        
        async with self.pool.acquire() as conn:
            updated = await conn.execute(
                """UPDATE tags SET content = $1 WHERE name = $2 AND user_id = $3""",
                new_content, name, ctx.author.id
            )

            if updated != "UPDATE 0":
                return await ctx.send(f"Updated personal tag `{name}`.")


            if ctx.guild:
                updated = await conn.execute(
                    """UPDATE tags SET content = $1 WHERE name = $2 AND guild_id = $3 AND author_id = $4""",
                    new_content, name, ctx.guild.id, ctx.author.id
                )

                if updated != "UPDATE 0":
                    return await ctx.send(f"Updated server tag `{name}`.")

                if ctx.author.guild_permissions.manage_messages:
                    updated = await conn.execute(
                        """UPDATE tags SET content = $1 WHERE name = $2 AND guild_id = $3""",
                        new_content, name, ctx.guild.id
                    )
                    if updated != "UPDATE 0":
                        return await ctx.send(f"Forcefully updated server tag `{name}`.")

        await ctx.send(f"No editable tag named `{name}` found.")
    
    @tag.command(name="delete", description="Delete a tag.", with_app_command=True, aliases=["remove", "rm", "del"])
    @app_commands.describe(name="The tag name.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def delete(self, ctx: commands.Context, *, name: str):
        await ctx.typing()
        name = name.lower()
        async with self.pool.acquire() as conn:
            if await conn.fetchval(
                "SELECT 1 FROM tags WHERE name = $1 AND user_id = $2",
                name, ctx.author.id
            ):
                await conn.execute(
                    "DELETE FROM tags WHERE name = $1 AND user_id = $2",
                    name, ctx.author.id
                )
                return await ctx.send(f"Deleted personal tag `{name}`.")
            
            if ctx.guild and await conn.fetchval(
                """SELECT 1 FROM tags
                WHERE name = $1 AND guild_id = $2 AND author_id = $3""",
                name, ctx.guild.id, ctx.author.id
            ):
                await conn.execute(
                    """DELETE FROM tags
                    WHERE name = $1 AND guild_id = $2 AND author_id = $3""",
                    name, ctx.guild.id, ctx.author.id
                )
                return await ctx.send(f"Deleted server tag `{name}`.")
            
            if ctx.guild and ctx.author.guild_permissions.manage_messages:
                if await conn.fetchval(
                    "SELECT 1 FROM tags WHERE name = $1 AND guild_id = $2",
                    name, ctx.guild.id
                ):
                    await conn.execute(
                        "DELETE FROM tags WHERE name = $1 AND guild_id = $2",
                        name, ctx.guild.id
                    )
                    return await ctx.send(f"Forcefully deleted server tag `{name}`.")
            
            await ctx.send(f"No deletable tag `{name}` found.")
    
    @tag.command(name="list", description="List available tags.", with_app_command=True, aliases=["ls"])
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def list(self, ctx: commands.Context, personal: bool = False):
        await ctx.typing()
        async with self.pool.acquire() as conn:
            if personal:
                tags = await conn.fetch(
                    "SELECT name FROM tags WHERE user_id = $1 ORDER BY name",
                    ctx.author.id
                )
                title = "Your personal tags"
            else:
                if not ctx.guild:
                    return await ctx.send("Server tags can only be listed in servers.")
                tags = await conn.fetch(
                    "SELECT name FROM tags WHERE guild_id = $1 ORDER BY name",
                    ctx.guild.id
                )
                title = f"Server tags in {ctx.guild.name}"

            if not tags:
                return await ctx.send(f"No {'personal' if personal else 'server'} tags found.")
            
            embed = discord.Embed(title=title, color=discord.Color.blue())
            embed.description = "\n".join(f"• {tag['name']}" for tag in tags)
            await ctx.send(embed=embed)
    
    @tag.command(name="info", description="Get information about a tag.", with_app_command=True)
    @app_commands.describe(name="The tag name.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def info(self, ctx: commands.Context, *, name: str):
        await ctx.typing()
        name = name.lower()
        async with self.pool.acquire() as conn:
            tag = await conn.fetchrow(
                """SELECT content, author_id, created_at, uses,
                guild_id IS NOT NULL as is_guild_tag
                FROM tags
                WHERE name = $1 AND (guild_id = $2 OR user_id = $3)""",
                name, ctx.guild.id if ctx.guild else None, ctx.author.id
            )

            if not tag:
                return await ctx.send(f"Tag `{name}` not found.")
            
            embed = discord.Embed(title=f"Tag: {name}", color=discord.Color.blue())
            embed.add_field(name="Type", value="Server" if tag['is_guild_tag'] else "Personal", inline=True)
            embed.add_field(name="Uses", value=tag['uses'], inline=True)
            embed.add_field(name="Created", value=tag['created_at'].strftime("%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)"), inline=True)
            author = self.bot.get_user(tag['author_id'])
            if author:
                embed.set_author(name=f"Created by {author}", icon_url=author.display_avatar.url, url=f"https://discord.com/users/{author.id}")
            
            await ctx.send(embed=embed)
    
    @tag.command(name="raw", description="Get the raw content of a tag.", with_app_command=True)
    @app_commands.describe(name="The tag name.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def raw(self, ctx: commands.Context, *, name: str):
        await ctx.typing()
        name = name.lower()
        async with self.pool.acquire() as conn:
            tag = await conn.fetchrow(
                "SELECT content FROM tags WHERE name = $1 AND (guild_id = $2 OR user_id = $3)",
                name, ctx.guild.id if ctx.guild else None, ctx.author.id
            )

            if not tag:
                return await ctx.send(f"Tag `{name}` not found.")
            
            await ctx.send(f"```\n{tag['content']}```")
    
    @tag.command(name="transfer", description="Transfer ownership of a personal tag.", with_app_command=True, aliases=["gift"])
    @app_commands.describe(name="The tag name.", new_owner="The user to transfer to.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def transfer(self, ctx: commands.Context, name: str, new_owner: discord.User):
        await ctx.typing()
        name = name.lower()
        async with self.pool.acquire() as conn:
            updated = await conn.execute(
                """UPDATE tags SET user_id = $1
                WHERE name = $2 AND user_id = $3""",
                new_owner.id, name, ctx.author.id
            )

            if updated == "UPDATED 0":
                await ctx.send(f"No personal tag `{name}` found that you own.")
            else:
                await ctx.send(f"Transferred tag `{name}` to {new_owner.name}")

async def setup(bot):
    if not hasattr(bot, 'pool'):
        bot.pool = await asyncpg.create_pool(bot_info.data['database'])
    await bot.add_cog(Tags(bot))