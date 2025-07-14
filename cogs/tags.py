import discord
from discord.ext import commands
from discord import app_commands
import asyncpg
import re
import bot_info
import asyncio
import ast
from typing import Callable, Dict, List, Set, Union
import aiohttp
import yt_dlp
import os
import uuid
import platform
from pathlib import Path
import subprocess
import shlex
import shutil
from datetime import datetime, timedelta
import random
from io import BytesIO
from urllib.parse import quote, unquote, urlparse
import base64
import json
from jsonschema import validate, ValidationError
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import math
import matplotlib.font_manager
import hashlib
from zoneinfo import ZoneInfo
import dateparser

IMAGE_TYPES = ('image/png', 'image/jpeg', 'image/jpg', 'image/webp', 'image/gif')
VIDEO_TYPES = ('video/mp4', 'video/webm', 'video/quicktime', 'video/x-matroska', 'video/x-msvideo', 'video/x-ms-wmv')
AUDIO_TYPES = ('audio/mpeg', 'audio/mp4', 'audio/wav', 'audio/ogg', 'audio/opus', 'audio/flac', 'audio/x-matroska', 'audio/x-ms-wma')


class TagPaginator(discord.ui.View):
    def __init__(self, pages: List[discord.Embed], interaction: discord.Interaction, original_author):
        super().__init__(timeout=60)
        self.pages = pages
        self.current_page = 0
        self.original_author = original_author
        self.message = None
        self.interaction = interaction
    
    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user != self.original_author:
            await interaction.response.send_message("You can't control this pagination.", ephemeral=True)
            return False
        return True
    
    async def on_timeout(self):
        await self.message.edit(view=None)

    async def update_message(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    @discord.ui.button(label="⏮️", style=discord.ButtonStyle.blurple)
    async def first_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = 0
        await self.update_message(interaction)

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.blurple)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_message(interaction)

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.blurple)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
            await self.update_message(interaction)

    @discord.ui.button(label="⏭️", style=discord.ButtonStyle.blurple)
    async def last_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = len(self.pages) - 1
        await self.update_message(interaction)

    @discord.ui.button(label="🔢", style=discord.ButtonStyle.green)
    async def jump_to_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = JumpToPageModal(paginator_view=self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🗑️", style=discord.ButtonStyle.red)
    async def delete_message(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()
        self.stop()

    @discord.ui.button(label="⏹️", style=discord.ButtonStyle.gray)
    async def hide_components(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.edit(view=None)
        self.stop()


class JumpToPageModal(discord.ui.Modal, title="Jump to Page"):
    def __init__(self, paginator_view: TagPaginator):
        super().__init__()
        self.paginator_view = paginator_view

    page = discord.ui.TextInput(
        label="Page Number",
        placeholder="Enter the page number...",
        required=True,
        min_length=1,
        max_length=5
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            page_number = int(self.page.value) - 1
            if 0 <= page_number < len(self.paginator_view.pages):
                self.paginator_view.current_page = page_number
                await self.paginator_view.update_message(interaction)
            else:
                await interaction.response.send_message("Invalid page number.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Please enter a valid number.", ephemeral=True)


class DiscordGenerator:
    @staticmethod
    def _build_embed(**kwargs) -> discord.Embed:
        color = kwargs.get('color')
        if isinstance(color, str):
            try:
                color = int(color.strip('#'), 16)
            except ValueError:
                color = None
        embed = discord.Embed(
            title=kwargs.get('title'),
            description=kwargs.get('description'),
            color=color
        )
        

        if 'fields' in kwargs:
            for field in kwargs['fields']:
                embed.add_field(
                    name=field.get('name', ''),
                    value=field.get('value', ''),
                    inline=field.get('inline', True)
                )
        if 'author' in kwargs:
            embed.set_author(
                name=kwargs['author'].get('name'),
                icon_url=kwargs['author'].get('icon_url'),
                url=kwargs['author'].get('url')
            )
        if 'footer' in kwargs:
            embed.set_footer(
                text=kwargs['footer'].get('text'),
                icon_url=kwargs['footer'].get('icon_url')
            )
        if 'timestamp' in kwargs:
            try:
                timestamp = kwargs['timestamp']
                if isinstance(timestamp, str):
                    timestamp = datetime.fromisoformat(timestamp)
                embed.timestamp = timestamp
            except Exception:
                pass
        if 'thumbnail' in kwargs:
            embed.set_thumbnail(url=kwargs['thumbnail'].get('url'))
        if 'image' in kwargs:
            embed.set_image(url=kwargs['image'].get('url'))
        return embed
    
    @staticmethod
    def create_select(source: Union[str, dict], **kwargs) -> discord.ui.Select:
        if isinstance(source, str):
            try:
                data = json.loads(source)
            except json.JSONDecodeError:
                raise ValueError("Invalid JSON for select")
        else:
            data = source.copy()
        data.update(kwargs)
        
        options = []
        for opt in data.get('options', []):
            options.append(discord.SelectOption(
                label=opt['label'],
                value=opt.get('value', opt['label']),
                description=opt.get('description'),
                emoji=opt.get('emoji'),
                default=opt.get('default', False)
            ))
        
        return discord.ui.Select(
            custom_id=data.get('custom_id'),
            placeholder=data.get('placeholder'),
            min_values=data.get('min', 1),
            max_values=data.get('max', 1),
            options=options,
            disabled=data.get('disabled', False)
        )


    @staticmethod
    def create_button(source: Union[str, dict], **kwargs) -> discord.ui.Button:
        if isinstance(source, str):
            try:
                data = json.loads(source)
            except json.JSONDecodeError:
                raise ValueError("Invalid JSON for button")
        else:
            data = source.copy()
        data.update(kwargs)
        
        return discord.ui.Button(
            label=data.get('label'),
            style=DiscordGenerator.parse_button_style(data.get('style', 'primary')),
            custom_id=data.get('custom_id'),
            url=data.get('url'),
            disabled=data.get('disabled', False),
            emoji=data.get('emoji')
        )
    
    
    @staticmethod
    def parse_button_style(style):
        styles = {
            'primary': discord.ButtonStyle.primary,
            'secondary': discord.ButtonStyle.secondary,
            'success': discord.ButtonStyle.success,
            'danger': discord.ButtonStyle.danger,
            'link': discord.ButtonStyle.link
        }
        return styles.get(style.lower(), discord.ButtonStyle.primary)


class MediaProcessor:
    def __init__(self):
        self.media_cache: Dict[str, str] = {}
        self.active_processes: Set[asyncio.subprocess.Process] = set()
        self.temp_dir = Path(os.getenv('TEMP', '/tmp')) / 'gscript'
        self.temp_dir.mkdir(exist_ok=True)
        self.temp_files = set()
        self.session = None
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
            'convert': {
                'input_key': {'required': True, 'type': str},
                'format': {'required': True, 'type': str},
                'output_key': {'required': True, 'type': str}
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
            'opacity': {
                'input_key': {'required': True, 'type': str},
                'opacity_level': {'required': True, 'type': float},
                'output_key': {'required': True, 'type': str}
            },
            'saturate': {
                'input_key': {'required': True, 'type': str},
                'saturation_level': {'required': True, 'type': float},
                'output_key': {'required': True, 'type': str}
            },
            'hue': {
                'input_key': {'required': True, 'type': str},
                'hue_shift': {'required': True, 'type': str},
                'output_key': {'required': True, 'type': str}
            },
            'brightness': {
                'input_key': {'required': True, 'type': str},
                'brightness_level': {'required': True, 'type': float},
                'output_key': {'required': True, 'type': str}
            },
            'gamma': {
                'input_key': {'required': True, 'type': str},
                'gamma_level': {'required': True, 'type': float},
                'output_key': {'required': True, 'type': str}
            },
            'clone': {
                'input_key': {'required': True, 'type': str},
                'output_key': {'required': True, 'type': str}
            },
            'fps': {
                'input_key': {'required': True, 'type': str},
                'fps_value': {'required': True, 'type': str},
                'output_key': {'required': True, 'type': str}
            },
            'grayscale': {
                'input_key': {'required': True, 'type': str},
                'output_key': {'required': True, 'type': str}
            },
            'sepia': {
                'input_key': {'required': True, 'type': str},
                'output_key': {'required': True, 'type': str}
            },
            'invert': {
                'input_key': {'required': True, 'type': str},
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
                'angle': {'required': True, 'type': str},
                'output_key': {'required': True, 'type': str}
            },
            'trim': {
                'input_key': {'required': True, 'type': str},
                'start_time': {'required': True, 'type': str},
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
                'x': {'default': '0', 'type': str},
                'y': {'default': '0', 'type': str},
                'color': {'default': 'black', 'type': str},
                'output_key': {'required': True, 'type': str},
                'font_size': {'default': 64, 'type': int},
                'font': {'default': 'arial', 'type': str},
                'outline_color': {'required': False, 'type': str},
                'outline_width': {'required': False, 'type': int},
                'shadow_color': {'required': False, 'type': str},
                'shadow_offset': {'required': False, 'type': int},
                'shadow_blur': {'required': False, 'type': int},
                'wrap_width': {'required': False, 'type': int},
                'line_spacing': {'required': False, 'type': int}
            },
            'caption': {
                'input_key': {'required': True, 'type': str},
                'text': {'required': True, 'type': str},
                'output_key': {'required': True, 'type': str},
                'font_size': {'default': 36, 'type': int},
                'font': {'default': 'Futura Condensed Extra Bold', 'type': str},
                'color': {'default': '#000000', 'type': str},
                'background_color': {'default': '#FFFFFF', 'type': str},
                'padding': {'default': 50, 'type': int},
                'outline_color': {'required': False, 'type': str},
                'outline_width': {'required': False, 'type': int},
                'shadow_color': {'required': False, 'type': str},
                'shadow_offset': {'default': 2, 'type': int},
                'shadow_blur': {'default': 0, 'type': int}
            },
            'audioputreplace': {
                'input_key': {'required': True, 'type': str},
                'audio_key': {'required': True, 'type': str},
                'output_key': {'required': True, 'type': str},
                'preserve_length': {'default': True, 'type': bool},
                'force_video': {'default': False, 'type': bool},
                'loop_media': {'default': False, 'type': bool}
            },
            'audioputmix': {
                'input_key': {'required': True, 'type': str},
                'audio_key': {'required': True, 'type': str},
                'output_key': {'required': True, 'type': str},
                'volume': {'default': 1.0, 'type': float},
                'preserve_length': {'default': True, 'type': bool},
                'loop_audio': {'default': False, 'type': bool},
                'loop_media': {'default': False, 'type': bool}
            },
            'tremolo': {
                'input_key': {'required': True, 'type': str},
                'frequency': {'default': 5.0, 'type': float},
                'depth': {'default': 0.5, 'type': float},
                'output_key': {'required': True, 'type': str}
            },
            'vibrato': {
                'input_key': {'required': True, 'type': str},
                'frequency': {'default': 5.0, 'type': float},
                'depth': {'default': 0.5, 'type': float},
                'output_key': {'required': True, 'type': str}
            },
            'create': {
                'media_key': {'required': True, 'type': str},
                'width': {'required': True, 'type': str},
                'height': {'required': True, 'type': str},
                'color': {'default': 'black', 'type': str}
            },
            'fadein': {
                'input_key': {'required': True, 'type': str},
                'duration': {'required': True, 'type': str},
                'color': {'default': '#000000', 'type': str},
                'audio': {'default': True, 'type': bool},
                'output_key': {'required': True, 'type': str}
            },
            'fadeout': {
                'input_key': {'required': True, 'type': str},
                'start_time': {'required': True, 'type': float},
                'duration': {'required': True, 'type': str},
                'color': {'default': '#000000', 'type': str},
                'audio': {'default': True, 'type': bool},
                'output_key': {'required': True, 'type': str}
            },
            'colorkey': {
                'input_key': {'required': True, 'type': str},
                'color': {'default': 'black', 'type': str},
                'similarity': {'default': 0.01, 'type': float},
                'blend': {'default': 0.0, 'type': float},
                'output_key': {'required': True, 'type': str}
            },
            'chromakey': {
                'input_key': {'required': True, 'type': str},
                'color': {'default': 'black', 'type': str},
                'similarity': {'default': 0.01, 'type': float},
                'blend': {'default': 0.0, 'type': float},
                'output_key': {'required': True, 'type': str}
            },
            'dobetween': {
                'input_key': {'required': True, 'type': str},
                'start_time': {'required': True, 'type': str},
                'end_time': {'required': True, 'type': str},
                'output_key': {'required': True, 'type': str},
                'segment_key': {'default': 'segment', 'type': str}
            }
        }
        self.gscript_commands = {
            'load': self._load_media,
            'reverse': self._reverse_media,
            'concat': self._concat_media,
            'render': self._render_media,
            'convert': self._convert_media,
            'contrast': self._adjust_contrast,
            'opacity': self._adjust_opacity,
            'saturate': self._adjust_saturation,
            'hue': self._adjust_hue,
            'brightness': self._adjust_brightness,
            'gamma': self._adjust_gamma,
            'clone': self._clone_media,
            'fps': self._change_fps,
            'grayscale': self._apply_grayscale,
            'sepia': self._apply_sepia,
            'invert': self._invert_media,
            'resize': self._resize_media,
            'crop': self._crop_media,
            'rotate': self._rotate_media,
            'trim': self._trim_media,
            'speed': self._change_speed,
            'volume': self._adjust_volume,
            'overlay': self._overlay_media,
            'text': self._text,
            'caption': self._apply_caption,
            'audioputreplace': self._replace_audio,
            'audioputmix': self._mix_audio,
            'tremolo': self._tremolo,
            'vibrato': self._vibrato,
            'create': self._create_image,
            'fadein': self._fadein_media,
            'fadeout': self._fadeout_media,
            'colorkey': self._colorkey,
            'chromakey': self._chromakey,
            'dobetween': self._dobetween_media
        }
    
    async def ensure_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()

    
    async def cleanup(self):
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None
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
            except Exception:
                pass
        for file_path in self.temp_files:
            try:
                if os.path.exists(file_path):
                    os.unlink(file_path)
            except Exception:
                pass
        
        try:
            for item in self.temp_dir.glob('*'):
                try:
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)
                except Exception:
                    pass
        except Exception:
            pass
        
        self.media_cache.clear()
        self.active_processes.clear()
        self.temp_files.clear()
    
    
    def _get_temp_path(self, extension: str = '') -> Path:
        path = self.temp_dir / f"{uuid.uuid4()}{f'.{extension}' if extension else ''}"
        self.temp_files.add(str(path))
        path.touch(exist_ok=True)
        return path
    
    
    async def _get_media_dimensions(self, media_key: str) -> tuple[int, int]:
        if media_key not in self.media_cache:
            return (0, 0)
        
        file_path = self.media_cache[media_key]
        

        cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'json',
            file_path
        ]
        
        success, output = await self._run_ffprobe(cmd)
        if success and output:
            try:
                data = json.loads(output)
                stream = data['streams'][0]
                return (int(stream['width']), int(stream['height']))
            except:
                return (0, 0)
        return (0, 0)

    async def _resolve_dimension(self, dim_str: str, context_key: str = None, overlay_key: str = None) -> int:
        try:
            try:
                return int(float(dim_str))
            except ValueError:
                pass


            ctx_w, ctx_h = (0, 0)
            if context_key and context_key in self.media_cache:
                dims = await self._get_media_dimensions(context_key) or (0, 0)
                ctx_w, ctx_h = dims


            var_map = {
                'iw': ctx_w, 'W': ctx_w, 'width': ctx_w, 'main_w': ctx_w,
                'ih': ctx_h, 'H': ctx_h, 'height': ctx_h, 'main_h': ctx_h,
                'ow': 0, 'oh': 0, 'w': 0, 'h': 0
            }


            if '_' in dim_str or any(c.isalpha() and c.islower() for c in dim_str if not c in ['w','h']):
                parts = dim_str.split('_') if '_' in dim_str else [dim_str[:-1], dim_str[-1]]
                if len(parts) >= 2 and parts[-1] in ['w', 'h']:
                    media_key = '_'.join(parts[:-1]) if '_' in dim_str else dim_str[:-1]
                    dimension = parts[-1]
                    
                    if media_key in self.media_cache:
                        media_w, media_h = await self._get_media_dimensions(media_key) or (0, 0)
                        if dimension == 'w':
                            dim_str = str(media_w)
                        elif dimension == 'h':
                            dim_str = str(media_h)


            if overlay_key and overlay_key in self.media_cache:
                overlay_dims = await self._get_media_dimensions(overlay_key) or (0, 0)
                var_map.update({
                    'ow': overlay_dims[0], 'w': overlay_dims[0],
                    'oh': overlay_dims[1], 'h': overlay_dims[1]
                })


            for var, val in var_map.items():
                dim_str = dim_str.replace(var, str(val))


            if '(' in dim_str:
                mode, args_str = dim_str.split('(')[0].lower(), dim_str.split(')')[0].split('(')[1]
                args = [await self._resolve_dimension(arg.strip(), context_key, overlay_key) for arg in args_str.split(',')]
                
                if mode == 'fill': return max(args)
                if mode == 'contain': return min(args)
                if mode == 'cover': 
                    scale = max(args[0]/ctx_w, args[1]/ctx_h) if ctx_w and ctx_h else 1
                    return int(scale * ctx_w)
                if mode == 'stretch': return args[0]
                if mode == 'center':
                    return (ctx_w - args[0]) // 2 if any(c in dim_str.lower() for c in ['w','width']) else (ctx_h - args[0]) // 2


            if '%' in dim_str:
                base = ctx_w if any(c in dim_str.lower() for c in ['w','width','x']) else ctx_h
                return int(base * float(dim_str.replace('%', ''))) / 100


            return int(float(eval(dim_str, {'__builtins__': None}, {}))) if any(op in dim_str for op in '+-*/') else int(float(dim_str))
        
        except Exception:
            return 0
    
    
    async def _resolve_timestamp(self, input_key: str, time_val: Union[str, float]) -> str:
        if not isinstance(time_val, str) or not time_val.endswith('%'):
            return str(time_val)

        if input_key not in self.media_cache:
            return "0"

        path = Path(self.media_cache[input_key])
        _, _, duration, _ = await self._probe_media_info(path)

        try:
            pct = float(time_val.strip('%'))
            return str(duration * (pct / 100.0))
        except Exception:
            return "0"


    
    def _parse_color(self, color_str: str, size: tuple = None) -> Union[tuple, Image.Image]:
        if color_str.lower() in ('random', 'rand'):
            if size is None:
                return self._generate_random_color()
            else:
                angle = random.randint(0, 359)
                color_str = f'linear-gradient({angle}deg, random, random)'
        
        if color_str.startswith('#'):
            return self._hex_to_rgb(color_str)
        
        if not color_str.startswith(('linear-gradient(', 'radial-gradient(')):
            return self._parse_single_color(color_str)

        color_str = self._replace_random_in_gradient(color_str)
        base_str = color_str

        body = base_str[base_str.index('(')+1 : base_str.rindex(')')]
        parts = [p.strip().strip('"').strip("'") for p in body.split(',')]

        angle = 90.0
        colors_and_stops = []
        for part in parts:
            if part.endswith('deg'):
                try:
                    angle = float(part[:-3]) % 360
                except ValueError:
                    angle = 90.0
                continue
            if '%' in part:
                tokens = part.split()
                if len(tokens) == 2:
                    col_str, pct_str = tokens
                else:
                    col_str, pct_str = part.rsplit('%', 1)
                    col_str = col_str.strip()
                    pct_str = pct_str.strip()
                try:
                    stop = float(pct_str.strip('%')) / 100.0
                except ValueError:
                    stop = None
                colors_and_stops.append((col_str.strip(), stop))
            else:
                colors_and_stops.append((part, None))

        n = len(colors_and_stops)
        for i, (c, p) in enumerate(colors_and_stops):
            if p is None:
                colors_and_stops[i] = (c, i/(n-1) if n>1 else 0.0)

        width, height = size
        img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        if base_str.startswith('linear-gradient('):
            rad = math.radians(angle)
            dx, dy = math.sin(rad), -math.cos(rad)
            max_dist = math.sqrt((dx*width)**2 + (dy*height)**2)

            for y_pos in range(height):
                for x_pos in range(width):
                    pos = (x_pos*dx + y_pos*dy) / max_dist
                    pos = max(0, min(1, pos))

                    for i in range(len(colors_and_stops)-1):
                        start_pos = colors_and_stops[i][1]
                        end_pos = colors_and_stops[i+1][1]
                        
                        if start_pos <= pos <= end_pos:
                            if end_pos == start_pos:
                                t = 0
                            else:
                                t = (pos - start_pos) / (end_pos - start_pos)
                            
                            c1 = self._parse_single_color(colors_and_stops[i][0])
                            c2 = self._parse_single_color(colors_and_stops[i+1][0])
                            
                            r = int(c1[0] + (c2[0] - c1[0]) * t)
                            g = int(c1[1] + (c2[1] - c1[1]) * t)
                            b = int(c1[2] + (c2[2] - c1[2]) * t)
                            a = int(c1[3] + (c2[3] - c1[3]) * t)
                            
                            draw.point((x_pos, y_pos), fill=(r, g, b, a))
                            break

        elif base_str.startswith('radial-gradient('):
            center_x, center_y = width // 2, height // 2
            max_radius = math.sqrt(center_x**2 + center_y**2)
            
            for y_pos in range(height):
                for x_pos in range(width):
                    dist = math.sqrt((x_pos-center_x)**2 + (y_pos-center_y)**2) / max_radius
                    dist = max(0, min(1, dist))
                    
                    for i in range(len(colors_and_stops)-1):
                        start_pos = colors_and_stops[i][1]
                        end_pos = colors_and_stops[i+1][1]
                        
                        if start_pos <= dist <= end_pos:
                            if end_pos == start_pos:
                                t = 0
                            else:
                                t = (dist - start_pos) / (end_pos - start_pos)
                            
                            c1 = self._parse_single_color(colors_and_stops[i][0])
                            c2 = self._parse_single_color(colors_and_stops[i+1][0])
                            
                            r = int(c1[0] + (c2[0] - c1[0]) * t)
                            g = int(c1[1] + (c2[1] - c1[1]) * t)
                            b = int(c1[2] + (c2[2] - c1[2]) * t)
                            a = int(c1[3] + (c2[3] - c1[3]) * t)
                            
                            draw.point((x_pos, y_pos), fill=(r, g, b, a))
                            break

        return img

    def _replace_random_in_gradient(self, gradient_str: str) -> str:
        parts = gradient_str.split('(')
        prefix = parts[0]
        body = '('.join(parts[1:])
        
        color_parts = []
        current_part = []
        in_quotes = False
        for char in body:
            if char in ('"', "'"):
                in_quotes = not in_quotes
            if char == ',' and not in_quotes:
                color_parts.append(''.join(current_part).strip())
                current_part = []
            else:
                current_part.append(char)
        if current_part:
            color_parts.append(''.join(current_part).strip().rstrip(')'))
        
        processed_parts = []
        for part in color_parts:
            if part.endswith('deg'):
                processed_parts.append(part)
                continue
            
            if '%' in part:
                color_part, percent_part = part.rsplit('%', 1)
                color_part = color_part.strip()
                if color_part.lower() in ('random', 'rand'):
                    color_part = self._rgb_to_hex(self._generate_random_color())
                processed_parts.append(f"{color_part}%{percent_part}")
            else:
                if part.lower() in ('random', 'rand'):
                    part = self._rgb_to_hex(self._generate_random_color())
                processed_parts.append(part)
        
        return f"{prefix}({', '.join(processed_parts)})"

    def _generate_random_color(self, alpha: int = None) -> tuple:
        return (
            random.randint(0, 255),
            random.randint(0, 255),
            random.randint(0, 255),
            alpha if alpha is not None else 255
        )

    def _rgb_to_hex(self, color: tuple) -> str:
        if len(color) == 4:
            return f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}{color[3]:02x}"
        return f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"

    def _hex_to_rgb(self, hex_str: str) -> tuple:
        hex_str = hex_str.lstrip('#')
        length = len(hex_str)
        if length == 3:  # RGB
            return tuple(int(c*2, 16) for c in hex_str) + (255,)
        elif length == 4:  # RGBA
            return tuple(int(c*2, 16) for c in hex_str[:3]) + (int(hex_str[3]*2, 16),)
        elif length == 6:  # RRGGBB
            return tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4)) + (255,)
        elif length == 8:  # RRGGBBAA
            return tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4, 6))
        return (0, 0, 0, 255)

    def _parse_single_color(self, color_str: str) -> tuple:
        color_str = color_str.strip().lower()
        
        if color_str in ('none', 'transparent'):
            return (0, 0, 0, 0)
        
        if color_str in ('random', 'rand'):
            return self._generate_random_color()
        
        if color_str.startswith('#'):
            return self._hex_to_rgb(color_str)
        
        if color_str.startswith(('rgb(', 'rgba(')):
            try:
                values_str = color_str.split('(')[1].split(')')[0]
                values = [v.strip() for v in values_str.split(',')]
                
                r = int(values[0])
                g = int(values[1])
                b = int(values[2])
                
                a = 255
                if len(values) > 3:
                    alpha = float(values[3])
                    if alpha <= 1.0:
                        a = int(alpha * 255)
                    else:
                        a = int(alpha)
                
                return (r, g, b, a)
            except (ValueError, IndexError):
                pass
        
        if ',' in color_str or ' ' in color_str:
            separators = ',' if ',' in color_str else ' '
            try:
                parts = [p.strip() for p in color_str.split(separators)]
                if len(parts) >= 3:
                    r = int(parts[0])
                    g = int(parts[1])
                    b = int(parts[2])
                    a = 255 if len(parts) < 4 else int(float(parts[3])) * 255 if float(parts[3]) <= 1.0 else int(parts[3])
                    return (r, g, b, a)
            except (ValueError, IndexError):
                pass
        
        return {
            'white': (255, 255, 255, 255),
            'black': (0, 0, 0, 255),
            'red': (255, 0, 0, 255),
            'green': (0, 255, 0, 255),
            'blue': (0, 0, 255, 255),
            'yellow': (255, 255, 0, 255),
            'cyan': (0, 255, 255, 255),
            'magenta': (255, 0, 255, 255),
            'orange': (255, 165, 0, 255),
            'purple': (128, 0, 128, 255),
            'pink': (255, 192, 203, 255),
            'brown': (165, 42, 42, 255),
            'gray': (128, 128, 128, 255),
            'grey': (128, 128, 128, 255),
            'silver': (192, 192, 192, 255),
            'gold': (255, 215, 0, 255),
        }.get(color_str, (0, 0, 0, 255))


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
                        raise ValueError(f"Missing required argument: `{param}`")
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
            raise ValueError(f"{cmd} command error: {e}")

    
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
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode != 0:
                error_msg = stderr.decode('utf-8', errors='replace').strip()
                if platform.system() == 'Windows':
                    error_msg = error_msg.replace('\r\n', '\n')
                return False, f"FFmpeg error: {error_msg}"
            return True, stdout.decode('utf-8', errors='replace').strip()
        except asyncio.TimeoutError:
            proc.kill()
            return False, "FFmpeg processing took longer than 120 seconds."
        except Exception as e:
            return False, f"Unexpected error: {str(e)}"
        finally:
            self.active_processes.discard(proc)
    
    async def _run_ffprobe(self, cmd: list) -> tuple:
        if platform.system() == 'Windows':
            cmd[0] = 'ffprobe.exe'
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == 'Windows' else 0
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20)
            if proc.returncode != 0:
                error_msg = stderr.decode('utf-8', errors='replace').strip()
                return False, f"FFprobe error: {error_msg}"
            return True, stdout.decode('utf-8', errors='replace').strip()
        except Exception as e:
            return False, f"FFprobe error: {str(e)}"
    
    async def _probe_media_info(self, path: Path) -> tuple:
        cmd = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'stream=codec_type,width,height,duration',
            '-show_entries', 'format=duration',
            '-of', 'json',
            str(path)
        ]
        
        success, output = await self._run_ffprobe(cmd)
        if not success:
            return (1, 1, 0.0, False)

        try:
            data = json.loads(output)
            streams = data.get('streams', [])
            format_info = data.get('format', {})
            

            width, height = 1, 1
            for stream in streams:
                if stream.get('codec_type') == 'video':
                    width = max(int(stream.get('width', 1)), 1)
                    height = max(int(stream.get('height', 1)), 1)
                    break
                    

            duration = max(float(format_info.get('duration', 0)), 0.0)
            

            has_audio = any(s.get('codec_type') == 'audio' for s in streams)
            
            return (width, height, duration, has_audio)
            
        except Exception as e:
            return (1, 1, 0.0, False)
    
    async def execute_media_script(self, script):
        lines = [line.strip() for line in script.splitlines() if line.strip()]
        output_files = []
        errors = []
        last_output_key = None
        i = 0
        try:
            while i < len(lines):
                line = lines[i]
                try:
                    if line.lower().startswith('dobetween'):
                        parts = line.split()
                        input_key = parts[1]
                        start = parts[2]
                        end = parts[3]
                        output_key = parts[4]
                        sub_script = []
                        i += 1
                        while i < len(lines) and not lines[i].lower() == 'end':
                            sub_script.append(lines[i])
                            i += 1
                        if i >= len(lines):
                            errors.append("Missing 'end' for dobetween")
                            break
                        result = await self._dobetween_media(input_key=input_key, start_time=start, end_time=end, output_key=output_key, sub_script='\n'.join(sub_script))
                        last_output_key = output_key
                        if result.startswith("Error"):
                            errors.append(result)
                        i += 1
                    else:
                        parts = shlex.split(line)
                        cmd = parts[0].lower()
                        args = parts[1:]

                        if cmd not in self.gscript_commands:
                            errors.append(f"[{line}]\n -> Unknown command: `{cmd}`")
                            i += 1
                            continue

                        try:
                            parsed = self._parse_command_args(cmd, args)
                        except Exception as e:
                            errors.append(f"[{line}]\n -> Argument error: {e}")
                            i += 1
                            continue
                        func = self.gscript_commands[cmd]
                        result = await func(**parsed)
                        if 'output_key' in parsed:
                            last_output_key = parsed['output_key']
                        if result.startswith("Error"):
                            errors.append(result)
                        elif cmd == "render" and result.startswith("media://"):
                            output_files.append(result[8:])
                        i += 1
                except Exception as e:
                    errors.append(f"Error processing `{line}`: {str(e)}")
                    i += 1

            if not errors and not output_files and last_output_key:
                try:
                    auto_result = await self._render_media(media_key=last_output_key)
                    if auto_result.startswith("media://"):
                        output_files.append(auto_result[8:])
                except Exception as e:
                    errors.append(f"Auto-render failed: {str(e)}")

            return errors if errors else output_files or ["Processing complete"]
        except Exception as e:
            await self.cleanup()
            return [f"Script execution error: {str(e)}"]
    
    async def _load_media(self, **kwargs) -> str:
        try:
            return await self._load_media_impl(**kwargs)
        except ValueError as e:
            return f"Load error: {str(e)}"

    
    async def _load_media_impl(self, **kwargs) -> str:
        url = kwargs['url']
        media_key = kwargs['media_key']
        try:
            temp_file = self._get_temp_path()
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'outtmpl': f'{temp_file}.%(ext)s',
                'noplaylist': True
            }

            def sync_ydl_download():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    return ydl.prepare_filename(info)

            downloaded_path = await asyncio.get_event_loop().run_in_executor(None, sync_ydl_download)
            downloaded_path = Path(downloaded_path)

            if not downloaded_path.exists():
                raise RuntimeError("Downloaded file not found")


            ext = downloaded_path.suffix[1:]
            final_temp_file = self._get_temp_path(ext)
            

            shutil.move(str(downloaded_path), final_temp_file)
            downloaded_path.unlink(missing_ok=True)

            self.media_cache[media_key] = str(final_temp_file)
            return f"Loaded {media_key} via yt-dlp"
        
        except Exception:
            try:
                await self.ensure_session()
                async with self.session.get(url) as resp:
                    if resp.status != 200:
                        return f"HTTP Error {resp.status}"


                    ext = Path(url.split('?')[0]).suffix[1:] or 'tmp'
                    temp_file = self._get_temp_path(ext)

                    with temp_file.open('wb') as f:
                        async for chunk in resp.content.iter_chunked(8192):
                            f.write(chunk)

                    self.media_cache[media_key] = str(temp_file)
                    return f"Loaded {media_key}"
            
            except Exception as http_error:
                return f"Download error: {str(http_error)}"
    
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
        input_keys = kwargs.get('input_keys')
        output_key = kwargs['output_key']

        if not input_keys or not isinstance(input_keys, list):
            return "Error: No input files specified"
        
        missing = [k for k in input_keys if k not in self.media_cache]
        if missing:
            return f"Missing input keys: {', '.join(missing)}"
        
        input_paths = [Path(self.media_cache[k]) for k in input_keys]

        is_video = lambda p: p.suffix.lower() in ('.mp4', '.mov', '.webm', '.mkv', '.avi', '.wmv')
        is_audio = lambda p: p.suffix.lower() in ('.mp3', '.wav', '.ogg', '.opus', '.flac', '.m4a', '.wma', '.mka')
        is_image = lambda p: p.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp', '.gif')

        media_info = []
        all_gifs = True

        for path in input_paths:
            suffix = path.suffix.lower()
            if is_video(path):
                w, h, dur, has_audio = await self._probe_media_info(path)
                media_info.append({
                    'type': 'video',
                    'path': path,
                    'width': w,
                    'height': h,
                    'duration': dur,
                    'has_audio': has_audio
                })
                all_gifs = False
            elif is_audio(path):
                info = await self._probe_media_info(path)
                duration = float(info[2]) if info[2] else 3.0
                media_info.append({
                    'type': 'audio',
                    'path': path,
                    'duration': duration
                })
                all_gifs = False
            elif is_image(path):
                if suffix == '.gif':
                    _, _, dur, _ = await self._probe_media_info(path)
                    duration = float(dur) if dur else 0.5
                else:
                    duration = 0.5
                media_info.append({
                    'type': 'image',
                    'path': path,
                    'duration': duration
                })
                if suffix != '.gif':
                    all_gifs = False
            else:
                return f"Error: Unsupported file type '{suffix}'"

        output_format = (
            '.gif' if all(i['type'] == 'image' and i['path'].suffix.lower() == '.gif' for i in media_info) else
            '.mp3' if all(i['type'] == 'audio' for i in media_info) else
            '.mp4'
        )
        output_file = self._get_temp_path(output_format[1:])

        ffmpeg_cmd = ['ffmpeg', '-hide_banner']
        filter_complex = []
        map_args = []

        v_streams = []
        a_streams = []
        current_time = 0.0

        target_width, target_height = 512, 512
        for info in media_info:
            if info['type'] in ('video', 'image'):
                if info['type'] == 'video':
                    target_width, target_height = info['width'], info['height']
                break

        scale_filter = f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2"

        for idx, info in enumerate(media_info):
            path = info['path']
            media_type = info['type']
            duration = info['duration']
            suffix = path.suffix.lower()

            if media_type == 'image':
                ffmpeg_cmd += ['-t', str(duration), '-i', str(path)]
                if suffix == '.gif' and all_gifs:
                    filter_complex.append(f"[{idx}:v]setpts=PTS-STARTPTS,fps=10[v{idx}]")
                else:
                    filter_complex.append(f"[{idx}:v]{scale_filter},format=rgb24,fps=15[v{idx}]")
                v_streams.append(f"[v{idx}]")
                current_time += duration

            elif media_type == 'video':
                ffmpeg_cmd += ['-i', str(path)]
                if all_gifs:
                    filter_complex.append(f"[{idx}:v]setpts=PTS-STARTPTS,fps=10[v{idx}]")
                else:
                    filter_complex.append(f"[{idx}:v]{scale_filter}[v{idx}]")
                v_streams.append(f"[v{idx}]")
                if info['has_audio']:
                    a_streams.append(f"[{idx}:a]")
                current_time += info['duration']

            elif media_type == 'audio':
                ffmpeg_cmd += ['-i', str(path)]
                filter_complex.append(f"[{idx}:a]asetpts=PTS+{current_time}/TB[a{idx}]")
                a_streams.append(f"[a{idx}]")
                current_time += duration

        if not v_streams and any(i['type'] in ('image', 'video') for i in media_info):
            ffmpeg_cmd += ['-f', 'lavfi', '-i', f'color=c=black:s={target_width}x{target_height}:d={current_time}']
            filter_complex.append(f"[{len(input_paths)}:v]format=rgb24,fps=15[v0]")
            v_streams.append('[v0]')

        if all_gifs and v_streams:
            total_duration = sum(info['duration'] for info in media_info)
            v_concat = ''.join(v_streams) + f'concat=n={len(v_streams)}:v=1:a=0[v]'
            filter_complex.append(v_concat)
            filter_complex.append(f"[v]trim=duration={total_duration},setpts=PTS-STARTPTS[vg]")
            map_args += ['-map', '[vg]', '-c:v', 'gif', '-final_delay', '500']

        elif v_streams:
            v_concat = ''.join(v_streams) + f'concat=n={len(v_streams)}:v=1:a=0[v]'
            filter_complex.append(v_concat)
            map_args += ['-map', '[v]', '-pix_fmt', 'yuv420p']

        if a_streams:
            a_concat = ''.join(a_streams) + f'concat=n={len(a_streams)}:v=0:a=1[a]'
            filter_complex.append(a_concat)
            map_args += ['-map', '[a]', '-b:a', '192k']
        elif v_streams:
            map_args += ['-shortest']

        if filter_complex:
            ffmpeg_cmd += ['-filter_complex', ';'.join(filter_complex)]

        map_args += ['-fps_mode', 'vfr', '-async', '1']
        ffmpeg_cmd += map_args + ['-y', output_file.as_posix()]

        success, error = await self._run_ffmpeg(ffmpeg_cmd)
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
        extra_args = kwargs.get('extra_args', [])
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
    
    async def _convert_media(self, **kwargs) -> str:
        try:
            return await self._convert_media_impl(**kwargs)
        except ValueError as e:
            return f"Convert error: {str(e)}"

    async def _convert_media_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        output_key = kwargs['output_key']
        output_format = kwargs['format'].lower()

        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"
        
        input_path = Path(self.media_cache[input_key])
        output_file = self._get_temp_path(output_format)
        
        cmd = ['ffmpeg', '-hide_banner', '-i', input_path.as_posix()]
        

        format_filters = {
            'gif': ['-vf', 'split[o],palettegen,[o]paletteuse'],
            'png': ['-vframes', '1'],
            'jpg': ['-vframes', '1'],
            'jpeg': ['-vframes', '1'],
            'webp': ['-vframes', '1']
        }
        
        if output_format in format_filters:
            cmd.extend(format_filters[output_format])
        

        cmd.extend(['-y', output_file.as_posix()])
        
        success, error = await self._run_ffmpeg(cmd)
        
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
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
    
    async def _adjust_opacity(self, **kwargs) -> str:
        try:
            return await self._adjust_opacity_impl(**kwargs)
        except ValueError as e:
            return f"Opacity error: {str(e)}"

    async def _adjust_opacity_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        opacity_level = max(0.0, min(1.0, float(kwargs['opacity_level'])))
        output_key = kwargs['output_key']
        
        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"

        input_path = Path(self.media_cache[input_key])
        output_file = self._get_temp_path(input_path.suffix[1:])

        cmd = [
            'ffmpeg', '-hide_banner',
            '-i', input_path.as_posix(),
            '-vf', f'format=rgba,colorchannelmixer=aa={opacity_level}',
            '-y', output_file.as_posix()
        ]
        

        if input_path.suffix.lower() in ('.jpg', '.jpeg'):
            output_file = output_file.with_suffix('.png')
            cmd[-1] = output_file.as_posix()

        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
    async def _adjust_saturation(self, **kwargs) -> str:
        try:
            return await self._adjust_saturation_impl(**kwargs)
        except ValueError as e:
            return f"Saturation error: {str(e)}"

    async def _adjust_saturation_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        saturation_level = kwargs['saturation_level']
        output_key = kwargs['output_key']
        
        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"

        input_path = Path(self.media_cache[input_key])
        output_file = self._get_temp_path(input_path.suffix[1:])

        cmd = [
            'ffmpeg', '-hide_banner',
            '-i', input_path.as_posix(),
            '-vf', f'eq=saturation={saturation_level}',
            '-y', output_file.as_posix()
        ]
        
        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
    async def _adjust_hue(self, **kwargs) -> str:
        try:
            return await self._adjust_hue_impl(**kwargs)
        except ValueError as e:
            return f"Hue error: {str(e)}"

    async def _adjust_hue_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        hue_shift = kwargs['hue_shift']
        output_key = kwargs['output_key']
        
        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"

        input_path = Path(self.media_cache[input_key])
        output_file = self._get_temp_path(input_path.suffix[1:])

        cmd = [
            'ffmpeg', '-hide_banner',
            '-i', input_path.as_posix(),
            '-vf', f'hue=h={hue_shift}',
            '-y', output_file.as_posix()
        ]
        
        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
    async def _adjust_brightness(self, **kwargs) -> str:
        try:
            return await self._adjust_brightness_impl(**kwargs)
        except ValueError as e:
            return f"Brightness error: {str(e)}"

    async def _adjust_brightness_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        brightness_level = kwargs['brightness_level']
        output_key = kwargs['output_key']
        
        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"

        input_path = Path(self.media_cache[input_key])
        output_file = self._get_temp_path(input_path.suffix[1:])

        cmd = [
            'ffmpeg', '-hide_banner',
            '-i', input_path.as_posix(),
            '-vf', f'eq=brightness={brightness_level}',
            '-y', output_file.as_posix()
        ]
        
        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
    async def _adjust_gamma(self, **kwargs) -> str:
        try:
            return await self._adjust_gamma_impl(**kwargs)
        except ValueError as e:
            return f"Gamma error: {str(e)}"

    async def _adjust_gamma_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        gamma_level = kwargs['gamma_level']
        output_key = kwargs['output_key']
        
        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"

        input_path = Path(self.media_cache[input_key])
        output_file = self._get_temp_path(input_path.suffix[1:])

        cmd = [
            'ffmpeg', '-hide_banner',
            '-i', input_path.as_posix(),
            '-vf', f'eq=gamma={gamma_level}',
            '-y', output_file.as_posix()
        ]
        
        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
    async def _clone_media(self, **kwargs) -> str:
        try:
            return await self._clone_media_impl(**kwargs)
        except ValueError as e:
            return f"Clone error: {str(e)}"

    async def _clone_media_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        output_key = kwargs['output_key']
        
        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"

        input_path = Path(self.media_cache[input_key])
        output_file = self._get_temp_path(input_path.suffix[1:])
        

        shutil.copy(input_path, output_file)
        
        self.media_cache[output_key] = str(output_file)
        return f"media://{output_file.as_posix()}"
    
    async def _change_fps(self, **kwargs) -> str:
        try:
            return await self._change_fps_impl(**kwargs)
        except ValueError as e:
            return f"FPS error: {str(e)}"

    async def _change_fps_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        fps_value = kwargs['fps_value']
        output_key = kwargs['output_key']
        
        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"

        input_path = Path(self.media_cache[input_key])
        output_file = self._get_temp_path(input_path.suffix[1:])

        cmd = [
            'ffmpeg', '-hide_banner',
            '-i', input_path.as_posix(),
            '-vf', f'fps={fps_value}',
            '-y', output_file.as_posix()
        ]
        
        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error

    async def _apply_grayscale(self, **kwargs) -> str:
        try:
            return await self._apply_grayscale_impl(**kwargs)
        except ValueError as e:
            return f"Grayscale error: {str(e)}"

    async def _apply_grayscale_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        output_key = kwargs['output_key']
        
        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"

        input_path = Path(self.media_cache[input_key])
        output_file = self._get_temp_path(input_path.suffix[1:])

        cmd = [
            'ffmpeg', '-hide_banner',
            '-i', input_path.as_posix(),
            '-vf', 'format=gray',
            '-y', output_file.as_posix()
        ]
        
        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error

    async def _apply_sepia(self, **kwargs) -> str:
        try:
            return await self._apply_sepia_impl(**kwargs)
        except ValueError as e:
            return f"Sepia error: {str(e)}"

    async def _apply_sepia_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        output_key = kwargs['output_key']
        
        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"

        input_path = Path(self.media_cache[input_key])
        output_file = self._get_temp_path(input_path.suffix[1:])

        cmd = [
            'ffmpeg', '-hide_banner',
            '-i', input_path.as_posix(),
            '-vf', 'colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131',
            '-y', output_file.as_posix()
        ]
        
        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
    async def _invert_media(self, **kwargs) -> str:
        try:
            return await self._invert_media_impl(**kwargs)
        except ValueError as e:
            return f"Invert error: {str(e)}"

    async def _invert_media_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        output_key = kwargs['output_key']
        
        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"

        input_path = Path(self.media_cache[input_key])
        output_file = self._get_temp_path(input_path.suffix[1:])

        cmd = [
            'ffmpeg', '-hide_banner',
            '-i', input_path.as_posix(),
            '-vf', 'negate',
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
        width_expr = kwargs.get('width', 0)
        height_expr = kwargs.get('height', 0)
        output_key = kwargs['output_key']
        if not all([input_key, width_expr, height_expr, output_key]):
            return "Error: Missing required parameters"
        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"

        input_path = Path(self.media_cache[input_key])
        suffix = input_path.suffix.lower()
        allowed_suffixes = ('.mp4', '.mov', '.webm', '.mkv', '.avi', '.wmv', '.gif', '.png', '.jpg', '.jpeg', '.webp')
        if suffix not in allowed_suffixes:
            return f"Error: {input_key} is not a video or image file."
        output_file = self._get_temp_path(input_path.suffix[1:])
        
        width = await self._resolve_dimension(width_expr, input_key)
        height = await self._resolve_dimension(height_expr, input_key)

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
        width = await self._resolve_dimension(kwargs['width'], context_key=input_key)
        height = await self._resolve_dimension(kwargs['height'], context_key=input_key)
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
            '-vf', f'rotate={angle}',
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
        start_time = await self._resolve_timestamp(kwargs['input_key'], kwargs['start_time'])
        end_time = await self._resolve_timestamp(kwargs['input_key'], kwargs['end_time'])
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
        base_key = kwargs.get('base_key') or kwargs['input_key']
        overlay_key = kwargs['overlay_key']
        x = kwargs['x']
        y = kwargs['y']
        output_key = kwargs['output_key']
        if base_key not in self.media_cache or overlay_key not in self.media_cache:
            return f"Error: One of the keys not found"

        base_path = Path(self.media_cache[base_key])
        overlay_path = Path(self.media_cache[overlay_key])
        is_base_image = base_path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp')
        is_overlay_image = overlay_path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp')
        output_file = self._get_temp_path(base_path.suffix[1:])

        x = await self._resolve_dimension(x, base_key, overlay_key)
        y = await self._resolve_dimension(y, base_key, overlay_key)

        cmd = [
            'ffmpeg', '-hide_banner',
            '-i', base_path.as_posix(),
            '-i', overlay_path.as_posix(),
            '-filter_complex', f'overlay={x}:{y}',
            '-y', output_file.as_posix()
        ]


        if is_base_image and is_overlay_image:
            cmd = [
                'ffmpeg', '-hide_banner',
                '-i', base_path.as_posix(),
                '-i', overlay_path.as_posix(),
                '-filter_complex', f'overlay={x}:{y}',
                '-frames:v', '1',
                '-y', output_file.as_posix()
            ]


        elif not is_base_image and is_overlay_image:
            cmd[4:4] = ['-stream_loop', '-1']
            cmd.insert(cmd.index('-y'), '-shortest')
        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
    async def _text(self, **kwargs) -> str:
        try:
            return await self._text_impl(**kwargs)
        except ValueError as e:
            return f"Text error: {str(e)}"
        
    async def _text_impl(self, **kwargs) -> str:
        def get_text_size(font, text):
            bbox = font.getbbox(text)
            width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]
            return width, height

        async def load_font(font_name: str, font_size: int) -> ImageFont.FreeTypeFont:
            try:
                font = await asyncio.to_thread(ImageFont.truetype, font=font_name, size=font_size)
                return font
            except Exception:
                pass

            try:
                matches = []
                for f in matplotlib.font_manager.fontManager.ttflist:
                    if f.name.lower() == font_name.lower():
                        matches.append(f.fname)
                        try:
                            font = await asyncio.to_thread(ImageFont.truetype, f.fname, font_size)
                            return font
                        except Exception:
                            continue
            except Exception:
                pass

            system_paths = [
                f"C:/Windows/Fonts/{font_name.replace(' ', '')}.ttf",
                f"C:/Windows/Fonts/{font_name.replace(' ', '')}.otf",
                f"/Library/Fonts/{font_name}.ttf",
                f"/Library/Fonts/{font_name}.otf",
                f"/usr/share/fonts/truetype/{font_name.replace(' ', '')}.ttf",
                f"/usr/local/share/fonts/{font_name.replace(' ', '')}.ttf",
            ]
            for path in system_paths:
                try:
                    font = await asyncio.to_thread(ImageFont.truetype, path, font_size)
                    return font
                except Exception:
                    pass

            return await asyncio.to_thread(ImageFont.load_default)

        try:
            input_key = kwargs['input_key']
            text = kwargs['text']
            x_raw = kwargs['x']
            y_raw = kwargs['y']
            font_size = kwargs['font_size']
            color = kwargs['color']
            output_key = kwargs['output_key']
            font_name = kwargs['font']

            outline_color = kwargs.get('outline_color', None)
            outline_width = kwargs.get('outline_width', None)

            shadow_color = kwargs.get('shadow_color', None)
            shadow_offset = kwargs.get('shadow_offset', 2)
            shadow_blur = kwargs.get('shadow_blur', 0)

            wrap_width = kwargs.get('wrap_width', None)
            line_spacing = kwargs.get('line_spacing', 5)

            if input_key not in self.media_cache:
                return f"Error: {input_key} not found"

            input_path = Path(self.media_cache[input_key])
            base_img = await asyncio.to_thread(Image.open, input_path)
            base_img = await asyncio.to_thread(base_img.convert, 'RGBA')

            font = await load_font(font_name, font_size)
            if not isinstance(font, ImageFont.FreeTypeFont):
                font = await asyncio.to_thread(ImageFont.load_default)

            draw = await asyncio.to_thread(ImageDraw.Draw, base_img)

            max_width = base_img.width
            if wrap_width:
                max_width = int(wrap_width)

            current_font_size = font_size
            while True:
                test_font = await load_font(font_name, current_font_size)
                text_width, _ = get_text_size(test_font, text)
                
                if text_width <= max_width or current_font_size <= 8:
                    font = test_font
                    break
                current_font_size = max(8, int(current_font_size * 0.9))

            def wrap_text(draw, text, font, max_width):
                words = text.split(' ')
                lines = []
                current_line = ""
                for word in words:
                    test_line = current_line + word + " "
                    width, _ = get_text_size(font, test_line)
                    if width <= max_width:
                        current_line = test_line
                    else:
                        lines.append(current_line.rstrip())
                        current_line = word + " "
                lines.append(current_line.rstrip())
                return lines

            if wrap_width:
                lines = await asyncio.to_thread(wrap_text, draw, text, font, wrap_width)
            else:
                lines = [text]

            text_width = max(get_text_size(font, line)[0] for line in lines)
            text_height_total = sum(get_text_size(font, line)[1] + line_spacing for line in lines) - line_spacing

            if str(x_raw).lower() == "center":
                x = (base_img.width - text_width) // 2
            else:
                x = int(x_raw)

            if str(y_raw).lower() == "center":
                y = (base_img.height - text_height_total) // 2
            else:
                y = int(y_raw)


            txt_layer = await asyncio.to_thread(Image.new, 'L', base_img.size, 0)
            txt_draw = await asyncio.to_thread(ImageDraw.Draw, txt_layer)

            cur_y = y
            for line in lines:
                line_width, line_height = get_text_size(font, line)
                cur_x = (base_img.width - line_width) // 2 if str(x_raw).lower() == "center" else x
                await asyncio.to_thread(txt_draw.text, (cur_x, cur_y), line, font=font, fill=255)
                cur_y += line_height + line_spacing


            if shadow_color:
                shadow_layer = await asyncio.to_thread(Image.new, 'L', base_img.size, 0)
                shadow_draw = await asyncio.to_thread(ImageDraw.Draw, shadow_layer)
                ox = int(shadow_offset)
                oy = int(shadow_offset)

                cur_y = y
                for line in lines:
                    line_width, line_height = get_text_size(font, line)
                    cur_x = (base_img.width - line_width) // 2 if str(x_raw).lower() == "center" else x
                    await asyncio.to_thread(shadow_draw.text, (cur_x+ox, cur_y+oy), line, font=font, fill=255)
                    cur_y += line_height + line_spacing

                if shadow_blur > 0:
                    shadow_layer = await asyncio.to_thread(shadow_layer.filter, ImageFilter.GaussianBlur(radius=shadow_blur))

                shadow_img = await asyncio.to_thread(Image.new, 'RGBA', base_img.size, (0,0,0,0))
                shadow_color_parsed = await asyncio.to_thread(self._parse_color, shadow_color, base_img.size)
                
                if isinstance(shadow_color_parsed, tuple):
                    await asyncio.to_thread(shadow_img.paste, shadow_color_parsed, (0, 0), mask=shadow_layer)
                else:
                    await asyncio.to_thread(shadow_img.paste, shadow_color_parsed, (0, 0), mask=shadow_layer)

                base_img = await asyncio.to_thread(Image.alpha_composite, base_img, shadow_img)


            if outline_color:
                if outline_width is None:
                    outline_width = max(1, font_size // 20)

                outline_layer = await asyncio.to_thread(Image.new, 'L', base_img.size, 0)
                outline_draw = await asyncio.to_thread(ImageDraw.Draw, outline_layer)

                for dx in range(-outline_width, outline_width+1):
                    for dy in range(-outline_width, outline_width+1):
                        if dx*dx + dy*dy <= outline_width*outline_width:
                            cur_y = y
                            for line in lines:
                                line_width, line_height = get_text_size(font, line)
                                cur_x = (base_img.width - line_width) // 2 if str(x_raw).lower() == "center" else x
                                await asyncio.to_thread(outline_draw.text, (cur_x+dx, cur_y+dy), line, font=font, fill=255)
                                cur_y += line_height + line_spacing

                outline_img = await asyncio.to_thread(Image.new, 'RGBA', base_img.size, (0,0,0,0))
                outline_color_parsed = await asyncio.to_thread(self._parse_color, outline_color, base_img.size)
                
                if isinstance(outline_color_parsed, tuple):
                    await asyncio.to_thread(outline_img.paste, outline_color_parsed, (0, 0), mask=outline_layer)
                else:
                    await asyncio.to_thread(outline_img.paste, outline_color_parsed, (0, 0), mask=outline_layer)

                base_img = await asyncio.to_thread(Image.alpha_composite, base_img, outline_img)


            bbox = txt_layer.getbbox()
            if not bbox:
                return "Error: Text bounding box could not be determined"


            gradient_img = await asyncio.to_thread(self._parse_color, color, (bbox[2]-bbox[0], bbox[3]-bbox[1]))
            result = await asyncio.to_thread(base_img.copy)
            
            if isinstance(gradient_img, Image.Image):
                gradient_layer = await asyncio.to_thread(Image.new, 'RGBA', base_img.size, (0,0,0,0))
                gradient_crop = await asyncio.to_thread(gradient_img.crop, (0, 0, bbox[2]-bbox[0], bbox[3]-bbox[1]))
                await asyncio.to_thread(gradient_layer.paste, gradient_crop, (bbox[0], bbox[1]))
                await asyncio.to_thread(result.paste, gradient_layer, (0, 0), mask=txt_layer)
            else:
                solid_color = await asyncio.to_thread(Image.new, 'RGBA', base_img.size, gradient_img)
                await asyncio.to_thread(result.paste, solid_color, (0, 0), mask=txt_layer)

            output_file = self._get_temp_path('png')
            await asyncio.to_thread(result.save, output_file)
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"

        except Exception as e:
            return f"Text error: {str(e)}"

    async def _apply_caption(self, **kwargs) -> str:
        try:
            return await self._apply_caption_impl(**kwargs)
        except ValueError as e:
            return f"Caption error: {str(e)}"
    
    async def _apply_caption_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        text = kwargs['text']
        output_key = kwargs['output_key']
        padding = kwargs.get('padding', 50)
        font_size = kwargs.get('font_size', 36)
        font = kwargs.get('font', 'Futura Condensed Extra Bold')
        color = kwargs.get('color', '#000000')
        background_color = kwargs.get('background_color', '#FFFFFF')
        outline_color = kwargs.get('outline_color')
        outline_width = kwargs.get('outline_width')
        shadow_color = kwargs.get('shadow_color')
        shadow_offset = kwargs.get('shadow_offset', 2)
        shadow_blur = kwargs.get('shadow_blur', 0)

        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"

        input_path = Path(self.media_cache[input_key])
        is_video = input_path.suffix.lower() in ('.mp4', '.mov', '.webm', '.mkv', '.avi', '.wmv')
        is_gif = input_path.suffix.lower() == '.gif'

        width, height, _, _ = await self._probe_media_info(input_path)
        if width == 0 or height == 0:
            return "Error: could not determine input media dimensions"


        bg_img = await asyncio.to_thread(self._parse_color, background_color, (width, padding))
        if isinstance(bg_img, tuple):
            bg_img = await asyncio.to_thread(Image.new, 'RGBA', (width, padding), bg_img)
        caption_file = self._get_temp_path('png')
        await asyncio.to_thread(bg_img.save, caption_file)


        text_key = f"{output_key}_text"
        await self._create_image(
            media_key=text_key,
            width=str(width),
            height=str(padding),
            color='transparent'
        )
        await self._text(
            input_key=text_key,
            text=text,
            x='center',
            y=str((padding - font_size) // 2),
            color=color,
            output_key=text_key,
            font_size=font_size,
            font=font,
            outline_color=outline_color,
            outline_width=outline_width,
            shadow_color=shadow_color,
            shadow_offset=shadow_offset,
            shadow_blur=shadow_blur,
            wrap_width=width - 40
        )

        output_file = self._get_temp_path(input_path.suffix[1:])
            
        cmd = [
            'ffmpeg', '-hide_banner',
            '-i', str(input_path),
            '-i', str(caption_file),
            '-i', self.media_cache[text_key],
            '-filter_complex',
            '[1:v][2:v]overlay=0:0[bgtext];'
            f'[0:v]pad=width={width}:height={height+padding}:y={padding}:color=black[padded];'
            '[padded][bgtext]overlay=0:0[v]',
            *(['-frames:v', '1'] if not is_video and not is_gif else []),
            '-map', '[v]',
            '-map', '0:a?',
            '-preset', 'fast',
            '-crf', '23',
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
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
        input_key = kwargs['input_key']
        audio_key = kwargs['audio_key']
        output_key = kwargs['output_key']
        preserve_length = kwargs['preserve_length']
        force_video = kwargs['force_video']
        loop_media = kwargs['loop_media']
        if input_key not in self.media_cache or audio_key not in self.media_cache:
            return "Error: Missing input media"
    
        media_path = Path(self.media_cache[input_key])
        audio_path = Path(self.media_cache[audio_key])
        is_image = media_path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp')


        output_ext = 'mp4' if (is_image or force_video) else media_path.suffix[1:]
        output_file = self._get_temp_path(output_ext)


        cmd = ['ffmpeg', '-hide_banner', '-y']


        if is_image:
            cmd.extend([
            '-loop', '1',
            '-i', media_path.as_posix(),
            '-i', audio_path.as_posix(),
            '-vf', 'pad=width=ceil(iw/2)*2:height=ceil(ih/2)*2',
            '-shortest',
            '-vsync', '0',
            '-copyts',
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', '23',
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
            '-c:a', 'aac',
            '-b:a', '192k',
            output_file.as_posix()
        ])
        else:
            if loop_media:
                cmd.extend(['-stream_loop', '-1'])
            cmd.extend(['-i', media_path.as_posix()])
            cmd.extend(['-i', audio_path.as_posix()])


            if force_video or loop_media:
                cmd.extend([
                    '-c:v', 'libx264',
                    '-preset', 'fast',
                    '-crf', '23',
                    '-pix_fmt', 'yuv420p',
                    '-movflags', '+faststart'
                ])
            else:
                cmd.extend(['-c:v', 'copy'])


            cmd.extend(['-c:a', 'aac', '-b:a', '192k'])


            if preserve_length:
                cmd.append('-shortest')


            cmd.append(output_file.as_posix())


        success, error = await self._run_ffmpeg(cmd)
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
        input_key = kwargs['input_key']
        audio_key = kwargs['audio_key']
        output_key = kwargs['output_key']
        volume = kwargs['volume']
        loop_audio = kwargs['loop_audio']
        preserve_length = kwargs['preserve_length']
        loop_media = kwargs['loop_media']
        
        if input_key not in self.media_cache or audio_key not in self.media_cache:
            return "Error: Missing input media"

        media_path = Path(self.media_cache[input_key])
        audio_path = Path(self.media_cache[audio_key])
        is_image = media_path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp')
        is_audio = media_path.suffix.lower() in ('.mp3', '.wav', '.ogg', '.opus', '.flac', '.m4a', '.mka', '.wma')

        output_ext = 'mp4' if (is_image or not is_audio) else media_path.suffix[1:]
        output_file = self._get_temp_path(output_ext)


        audio_duration = None
        if loop_media:
            _, _, duration, _ = await self._probe_media_info(audio_path)
            audio_duration = duration

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

        should_apply_shortest = not loop_audio and preserve_length

        cmd.extend([
            '-filter_complex', filter_complex_str,
            *(['-c:v', 'libx264', '-pix_fmt', 'yuv420p'] if is_image else 
            ['-c:v', 'copy'] if not is_audio else []),
            '-map', '0:v:0' if not is_audio else None,
            '-map', '[a]',
            *(['-shortest'] if should_apply_shortest else []),
            *(['-t', str(audio_duration)] if loop_media and audio_duration else []),
            '-y', output_file.as_posix()
        ])

        success, error = await self._run_ffmpeg([x for x in cmd if x is not None])
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
    async def _tremolo(self, **kwargs) -> str:
        try:
            return await self._tremolo_impl(**kwargs)
        except ValueError as e:
            return f"Tremolo error: {str(e)}"
    
    async def _tremolo_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        frequency = kwargs['frequency']
        depth = kwargs['depth']
        output_key = kwargs['output_key']
        if input_key not in self.media_cache:
            return "Error: Missing input media"

        input_path = Path(self.media_cache[input_key])
        output_file = self._get_temp_path(input_path.suffix[1:])

        cmd = [
            'ffmpeg', '-hide_banner',
            '-i', input_path.as_posix(),
            '-af', f'tremolo={frequency}:{depth}',
            '-y', output_file.as_posix()
        ]

        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
    async def _vibrato(self, **kwargs) -> str:
        try:
            return await self._vibrato_impl(**kwargs)
        except ValueError as e:
            return f"Vibrato error: {str(e)}"
    
    async def _vibrato_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        frequency = kwargs['frequency']
        depth = kwargs['depth']
        output_key = kwargs['output_key']
        if input_key not in self.media_cache:
            return "Error: Missing input media"

        input_path = Path(self.media_cache[input_key])
        output_file = self._get_temp_path(input_path.suffix[1:])

        cmd = [
            'ffmpeg', '-hide_banner',
            '-i', input_path.as_posix(),
            '-af', f'vibrato={frequency}:{depth}',
            '-y', output_file.as_posix()
        ]

        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
    async def _create_image(self, **kwargs) -> str:
        try:
            return await self._create_image_impl(**kwargs)
        except ValueError as e:
            return f"Create error: {str(e)}"
    
    async def _create_image_impl(self, **kwargs) -> str:
        try:
            width = await self._resolve_dimension(kwargs['width'])
            height = await self._resolve_dimension(kwargs['height'])
            size = (width, height)

            color = await asyncio.to_thread(self._parse_color, kwargs['color'], size)
            if isinstance(color, Image.Image):
                img = color
            else:
                img = await asyncio.to_thread(Image.new, 'RGBA', size, color)

            output_file = self._get_temp_path('png')
            await asyncio.to_thread(img.save, output_file)
            self.media_cache[kwargs['media_key']] = str(output_file)
            return f"media://{output_file.as_posix()}"
        except Exception as e:
           return f"Create error: {str(e)}"
    
    async def _fadein_media(self, **kwargs) -> str:
        try:
            return await self._fadein_media_impl(**kwargs)
        except ValueError as e:
            return f"Fade in error: {str(e)}"
    
    async def _fadein_media_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        duration = float(kwargs['duration'])
        color = kwargs.get('color', '#000000')
        audio_fade = kwargs.get('audio', True)
        output_key = kwargs['output_key']

        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"

        input_path = Path(self.media_cache[input_key])
        output_file = self._get_temp_path(input_path.suffix[1:].lstrip('.'))


        width, height, input_duration, has_audio = await self._probe_media_info(input_path)
        try:
            input_duration = float(input_duration) if input_duration else 0.0
        except (ValueError, TypeError):
            input_duration = 0.0
        is_image = input_duration <= 0


        if color.startswith(('linear-gradient', 'radial-gradient')):
            bg_img = await asyncio.to_thread(self._parse_color, color, (width, height))
            bg_file = self._get_temp_path('png')
            await asyncio.to_thread(bg_img.save, bg_file)
            bg_input = ['-stream_loop', '-1', '-i', bg_file.as_posix()]
        else:
            bg_input = ['-f', 'lavfi', '-i', f'color=c={color}:s={width}x{height}:d=9999']


        filter_parts = [
                f"[0:v]format=yuva420p,fade=t=in:st=0:d={duration}:alpha=1[fg];",
                f"[1:v][fg]overlay=format=auto,pad=width=ceil(iw/2)*2:height=ceil(ih/2)*2[v]"
            ]
            
        if has_audio:
            if audio_fade:
                filter_parts.append(f";[0:a]afade=t=in:st=0:d={duration}[a]")
            else:
                filter_parts.append(";[0:a]acopy[a]")

        cmd = [
            'ffmpeg', '-hide_banner',
            *(['-stream_loop', '-1'] if is_image else []),
            '-i', input_path.as_posix(),
            *bg_input,
            '-filter_complex', ''.join(filter_parts),
            '-map', '[v]',
            *(['-map', '[a]'] if has_audio else []),
        ]


        if is_image:
            output_file = self._get_temp_path('mp4')
            cmd.extend([
                '-t', str(duration),
                '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart'
            ])
        else:
            cmd.extend(['-shortest'])

        cmd.extend(['-y', output_file.as_posix()])

        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        else:
            return error
    
    async def _fadeout_media(self, **kwargs) -> str:
        try:
            return await self._fadeout_media_impl(**kwargs)
        except ValueError as e:
            return f"Fade out error: {str(e)}"
    
    async def _fadeout_media_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        duration = float(kwargs['duration'])
        start_time = float(kwargs['start_time'])
        color = kwargs.get('color', '#000000')
        audio_fade = kwargs.get('audio', True)
        output_key = kwargs['output_key']

        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"

        input_path = Path(self.media_cache[input_key])
        output_file = self._get_temp_path(input_path.suffix[1:].lstrip('.'))

        width, height, input_duration, has_audio = await self._probe_media_info(input_path)
        try:
            input_duration = float(input_duration) if input_duration else 0.0
        except (ValueError, TypeError):
            input_duration = 0.0
        is_image = input_duration <= 0

        if color.startswith(('linear-gradient', 'radial-gradient')):
            bg_img = await asyncio.to_thread(self._parse_color, color, (width, height))
            bg_file = self._get_temp_path('png')
            await asyncio.to_thread(bg_img.save, bg_file)
            bg_input = ['-stream_loop', '-1', '-i', bg_file.as_posix()]
        else:
            bg_input = ['-f', 'lavfi', '-i', f'color=c={color}:s={width}x{height}:d=9999']


        filter_complex_parts = [
            f"[0:v]format=yuva420p,fade=t=out:st={start_time}:d={duration}:alpha=1[fg];",
            f"[1:v][fg]overlay=format=auto,pad=width=ceil(iw/2)*2:height=ceil(ih/2)*2[v]"
        ]
        

        if has_audio:
            if audio_fade:
                filter_complex_parts.append(f";[0:a]afade=t=out:st={start_time}:d={duration}[a]")
            else:
                filter_complex_parts.append(";[0:a]acopy[a]")

        cmd = [
            'ffmpeg', '-hide_banner',
            *(['-stream_loop', '-1'] if is_image else []),
            '-i', input_path.as_posix(),
            *bg_input,
            '-filter_complex', ''.join(filter_complex_parts),
            '-map', '[v]',
            *(['-map', '[a]'] if has_audio else []),
        ]


        if is_image:
            output_file = self._get_temp_path('mp4')
            cmd.extend([
                '-t', str(start_time + duration),
                '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart'
            ])
        else:
            cmd.append('-shortest')

        cmd += ['-y', output_file.as_posix()]

        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
    async def _colorkey(self, **kwargs) -> str:
        try:
            return await self._colorkey_impl(**kwargs)
        except ValueError as e:
            return f"Colorkey error: {str(e)}"
    
    async def _colorkey_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        color = kwargs['color']
        similarity = kwargs['similarity']
        blend = kwargs['blend']
        output_key = kwargs['output_key']

        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"
        
        input_path = Path(self.media_cache[input_key])
        output_file = self._get_temp_path(input_path.suffix[1:])

        cmd = [
            'ffmpeg', '-hide_banner',
            '-i', input_path.as_posix(),
            '-vf', f'colorkey={color}:{similarity}:{blend}',
            '-y', output_file.as_posix()
        ]

        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
    async def _chromakey(self, **kwargs) -> str:
        try:
            return await self._chromakey_impl(**kwargs)
        except ValueError as e:
            return f"Chromakey error: {str(e)}"
    
    async def _chromakey_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        color = kwargs['color']
        similarity = kwargs['similarity']
        blend = kwargs['blend']
        output_key = kwargs['output_key']

        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"
        
        input_path = Path(self.media_cache[input_key])
        output_file = self._get_temp_path(input_path.suffix[1:])

        cmd = [
            'ffmpeg', '-hide_banner',
            '-i', input_path.as_posix(),
            '-vf', f'chromakey={color}:{similarity}:{blend}',
            '-y', output_file.as_posix()
        ]

        success, error = await self._run_ffmpeg(cmd)
        if success:
            self.media_cache[output_key] = str(output_file)
            return f"media://{output_file.as_posix()}"
        return error
    
    async def _dobetween_media(self, **kwargs) -> str:
        try:
            return await self._dobetween_media_impl(**kwargs)
        except ValueError as e:
            return f"Dobetween error: {str(e)}"
    
    async def _dobetween_media_impl(self, **kwargs) -> str:
        input_key = kwargs['input_key']
        start_time = kwargs['start_time']
        end_time = kwargs['end_time']
        output_key = kwargs['output_key']
        segment_key = kwargs.get('segment_key', 'segment')
        sub_script = kwargs.get('sub_script', '')
        
        if input_key not in self.media_cache:
            return f"Error: {input_key} not found"


        resolved_start = await self._resolve_timestamp(input_key, start_time)
        resolved_end = await self._resolve_timestamp(input_key, end_time)


        before_key = f"{segment_key}_before"
        segment_key = f"{segment_key}_main"
        after_key = f"{segment_key}_after"
        edited_key = f"{segment_key}_edited"


        trim_tasks = [
            self._trim_media(
                input_key=input_key,
                start_time='0',
                end_time=resolved_start,
                output_key=before_key
            ),
            self._trim_media(
                input_key=input_key,
                start_time=resolved_start,
                end_time=resolved_end,
                output_key=segment_key
            ),
            self._trim_media(
                input_key=input_key,
                start_time=resolved_end,
                end_time='9999999',
                output_key=after_key
            )
        ]
        
        results = await asyncio.gather(*trim_tasks)
        if any(r.startswith("Error") for r in results):
            return f"Trim error(s): {results}"


        if sub_script:
            patched_lines = []
            for line in sub_script.splitlines():
                line = line.strip()
                if not line:
                    continue

                parts = shlex.split(line)
                cmd = parts[0]
                pos_args = [p for p in parts[1:] if '=' not in p]
                kw_args = dict(p.split('=', 1) for p in parts[1:] if '=' in p)


                if 'input_key' not in kw_args:
                    kw_args['input_key'] = segment_key
                if 'output_key' not in kw_args:
                    kw_args['output_key'] = edited_key


                new_parts = [cmd] + pos_args + [f"{k}={v}" for k, v in kw_args.items()]
                patched_lines.append(shlex.join(new_parts))

            patched_script = "\n".join(patched_lines)
            script_result = await self.execute_media_script(patched_script)
            if any(r.startswith("Error") for r in script_result):
                return f"Sub-script error: {script_result}"

            segment_to_use = edited_key
        else:
            segment_to_use = segment_key

        concat_result = await self._concat_media(
            input_keys=[before_key, segment_to_use, after_key],
            output_key=output_key
        )
        
        return concat_result




class TagFormatter:
    def __init__(self):
        self.functions: Dict[str, Callable] = {}
        self._component_tags = {'embed', 'button', 'view', 'select'}
    
    def register(self, name: str):
        def decorator(func: Callable):
            if any(comp in func.__name__ for comp in self._component_tags):
                self._component_tags.add(name)
            self.functions[name] = func
            return func
        return decorator
    
    async def format(self, content: str, ctx: commands.Context, **kwargs) -> tuple[str, list[discord.Embed], discord.ui.View | None, list[discord.File]]:
        text_parts = []
        embeds = []
        view = None
        files = []
        
        for chunk in self._split_chunks(content):
            if chunk.startswith('{') and chunk.endswith('}'):
                result = await self._process_tag(chunk, ctx, **kwargs)
                text, new_embeds, new_view, new_files = self._normalize_result(result)
                
                text_parts.append(str(text))
                embeds.extend(new_embeds)
                if new_view:
                    view = view or discord.ui.View(timeout=None)
                    for item in new_view.children:
                        view.add_item(item)
                files.extend(new_files)
            else:
                text_parts.append(chunk)
        
        return ''.join(text_parts), embeds, view if view and view.children else None, files

    async def _process_tag(self, tag: str, ctx: commands.Context, **kwargs):
        inner = tag[1:-1].strip()
        parts = inner.split(':', 1)
        name = parts[0].strip()
            
        if name not in self.functions:
            return tag

        try:
            args = parts[1] if len(parts) > 1 else ''
            func = self.functions[name]

            if name in ('note', 'comment'):
                return await func(ctx, args, **kwargs)
            
            if name == 'ignore':
                return await func(ctx, args, **kwargs)
                

            if name in self._component_tags:
                result = func(ctx, args, **kwargs)
            else:
                arg_text, _, _, _ = await self.format(args, ctx, **kwargs)
                result = func(ctx, arg_text.strip(), **kwargs)
                
            return await result if asyncio.iscoroutine(result) else result
                
        except Exception as e:
            return f"[Tag Error: {str(e)}]"
    @staticmethod
    def _normalize_result(result) -> tuple[str, list[discord.Embed], discord.ui.View | None, list[discord.File]]:
        if result is None or result is discord.utils.MISSING:
            return ("", [], None, [])
        if isinstance(result, discord.Embed):
            return ("", [result], None, [])
        elif isinstance(result, discord.ui.Item):
            view = discord.ui.View(timeout=None)
            view.add_item(result)
            return ("", [], view, [])
        elif isinstance(result, discord.ui.View):
            return ("", [], result, [])
        elif isinstance(result, tuple):
            if len(result) == 3:
                return (*result, [])
            return result
        else:
            return (result, [], None, [])

    def _split_chunks(self, content: str) -> list[str]:
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
        return chunks
    
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
        self.setup_media_formatters()
        self.active_processes = set()
    
    async def execute_language(self, ctx, language: str, code: str, **kwargs):
        await self.processor.ensure_session()
        url = f"http://localhost:8000/{language}/execute"
        data = aiohttp.FormData()
        data.add_field("code", code)


        attachments = ctx.message.attachments
        if attachments:
            for attachment in attachments:
                try:
                    file_bytes = await attachment.read()
                    data.add_field(
                        "files",
                        BytesIO(file_bytes),
                        filename=attachment.filename,
                        content_type=attachment.content_type or "application/octet-stream"
                    )
                except Exception as e:
                    return f"[{language} error: Failed to process attachment {attachment.filename}: {str(e)}]"

        try:
            async with self.processor.session.post(url, data=data) as response:
                if response.status != 200:
                    return f"[{language} error: HTTP {response.status}]"
                result = await response.json()

            
                output = result.get("output", "").replace("\r\n", "\n").strip()
                if result.get("error") or "error" in output.lower():
                    return f"[{language} error: {output or 'Code execution failed with no output'}]"

            
                if result.get("files"):
                    file_objs = []
                    for filename in result["files"][:10]:
                        file_url = f"http://localhost:8000/files/{filename}"
                        try:
                            async with self.processor.session.get(file_url) as file_resp:
                                if file_resp.status == 200:
                                    file_data = await file_resp.read()
                                    file_objs.append(discord.File(BytesIO(file_data), filename=filename))
                        except Exception as e:
                            return f"[{language} error: Failed to fetch file {filename}: {str(e)}]"

                    if file_objs:
                        return ("", [], None, file_objs[:10])

                return output or "Code execution succeeded with no console output"
        except Exception as e:
            return f"[{language} exception: {str(e)}]"

        

    
    def setup_media_formatters(self):
        @self.formatter.register('gmanscript')
        @self.formatter.register('gscript')
        async def _gscript(ctx, script, **kwargs):
            """
            ### {gmanscript:...}
                * Uses G-Man Script to manipulate media.
                * Example: `{gscript:load url key{newline}convert key mov converted{newline}render converted}
                * Available GScript commands:
                    - load [url] [media_key]
                    - reverse [input_key] [output_key]
                    - concat [output_key] [input_keys...]
                    - convert [input_key] [format] [output_key]
                    - render [media_key] [format] [filename]
                    - contrast [input_key] [contrast_level] [output_key]
                    - opacity [input_key] [opacity_level] [output_key]
                    - saturate [input_key] [saturation_level] [output_key]
                    - hue [input_key] [hue_shift] [output_key]
                    - brightness [input_key] [brightness_level] [output_key]
                    - gamma [input_key] [gamma_level] [output_key]
                    - clone [input_key] [output_key]
                    - fps [input_key] [fps_value] [output_key]
                    - grayscale [input_key] [output_key]
                    - sepia [input_key] [output_key]
                    - invert [input_key] [output_key]
                    - resize [input_key] [width] [height] [output_key]
                    - crop [input_key] [x] [y] [width] [height] [output_key]
                    - rotate [input_key] [angle] [output_key]
                    - trim [input_key] [start_time] [end_time] [output_key]
                    - speed [input_key] [speed] [output_key]
                    - volume [input_key] [volume_level] [output_key]
                    - overlay [base_key] [overlay_key] [x] [y] [output_key]
                    - text [input_key] [text] [x] [y] [color] [output_key] [font_size] [font] [outline_color] [outline_width] [shadow_color] [shadow_offset] [shadow_blur] [wrap_width] [line_spacing]
                    - caption [input_key] [text] [output_key] [font_size] [font] [color] [background_color] [padding] [outline_color] [outline_width] [shadow_color] [shadow_offset] [shadow_blur]
                    - audioputreplace [media_key] [audio_key] [output_key] [preserve_length] [force_video] [loop_media]
                    - audioputmix [media_key] [audio_key] [output_key] [volume] [preserve_length] [loop_audio] [loop_media]
                    - tremolo [input_key] [frequency] [depth] [output_key]
                    - vibrato [input_key] [frequency] [depth] [output_key]
                    - create [media_key] [width] [height] [color]
                    - fadein [input_key] [duration] [color] [audio] [output_key]
                    - fadeout [input_key] [start_time] [duration] [color] [audio] [output_key]
                    - colorkey [input_key] [color] [similarity] [blend] [output_key]
                    - chromakey [input_key] [color] [similarity] [blend] [output_key]
                    - dobetween [input_key] [start_time] [end_time] [segment_key] [gmanscript]
            """
            try:
                results = await self.processor.execute_media_script(script)

                if isinstance(results, list):
                    if len(results) > 0 and results[0] == "Processing complete":
                        return ("Processing complete.", [], None, [])


                    errors = [r for r in results if isinstance(r, str) and not r.startswith("media://") and not os.path.isfile(r)]
                    if errors:
                        return ("\n".join(errors), [], None, [])


                    files = []
                    for path in results:
                        if os.path.isfile(path):
                            try:
                                with open(path, 'rb') as f:
                                    data = BytesIO(f.read())
                                filename = os.path.basename(path)
                                files.append(discord.File(data, filename=filename))
                                os.remove(path)
                            except Exception:
                                continue
                    if files:
                        return ("", [], None, files[:10])
                    else:
                        return ("No valid files could be loaded.", [], None, [])
                else:
                    return (str(results), [], None, [])

            except Exception as e:
                await self.processor.cleanup()
                return (f"[gmanscript error: {str(e)}]", [], None, [])
            finally:
                await self.processor.cleanup()

    
    def setup_formatters(self):
        @self.formatter.register('eval')
        async def _eval(ctx, val, **kwargs):
            """
            ### {eval:content}
                * Processes nested tag functions in the content.
                * Example: `{eval:Hello {user}!}`
            """
            return await self.process_tags(ctx, val, kwargs.get('args', ''))
        
        @self.formatter.register('ignore')
        async def _ignore(ctx, text, **kwargs):
            """
            ### {ignore:text}
                * Returns the text exactly as provided, without evaluating any nested tags.
                * Example: `{ignore:{user}}` -> "{user}"
            """
            return text.replace('{', '\\{').replace('}', '\\}')
        
        @self.formatter.register('note')
        @self.formatter.register('comment')
        async def _note(ctx, text, **kwargs):
            """
            ### {note:text}
                * Acts as a comment - removed from final output but visible in raw content.
                * Example: `Hello {note:This is a comment}world` -> "Hello world"
            """
            return ""
        
        @self.formatter.register('text')
        async def _fetch_text(ctx, url, **kwargs):
            """
            ### {text:url}
                * Fetches the text or HTML content from a URL.
                * Example: `{text:https://example.com}`
            """
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        if response.status != 200:
                            return f"[text error: HTTP Exception: {response.status}]"
                        content = await response.text()
                        return content
            except Exception as e:
                return f"[text error: {str(e)}]"
        
        @self.formatter.register('attachtext')
        async def _attach_text(ctx, text, **kwargs):
            """
            ### {attachtext:text}
                * Sends text content as a .txt attachment.
                * Example: `{attachtext:MiniatureEge2006}`
            """
            try:
                buffer = BytesIO(text.encode('utf-8'))
                
                file = discord.File(buffer, filename="attachment.txt")

                return ("", [], None, [file])
            
            except Exception as e:
                return f"[attachtext error: {str(e)}", [], None, []

            
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

            try:
                index = int(str(i).strip())
            except ValueError:
                return f"[arg error: invalid index `{i}`]"
            
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
            val_str = str(val) if val is not None else ""
            fb_str = str(fb) if fb is not None else ""
            return val_str if val_str else fb_str
        
        @self.formatter.register('newline')
        def _newline(ctx, _, **kwargs):
            """
            ### {newline}
                * Inserts a newline character.
                * Example: `Line1{newline}Line2`
                * Can be useful inside slash commands.
            """
            return '\n'
        
        @self.formatter.register('jsonify')
        def _jsonify(ctx, text, **kwargs):
            """
            ### {jsonify:text}
                * Converts text to JSON-compatible format. (escapes quotes, handles newlines)
                * Example: {jsonify:Hello "World"} -> "Hello \"World\""
                * Useful for embedding text in JSON or GScript commands
            """
            try:
                processed_text = str(text)
                return json.dumps(processed_text)
            except Exception as e:
                return f"[JSON Error: {str(e)}]"
        
        @self.formatter.register('traversejson')
        def _traversejson(ctx, val, **kwargs):
            """
            ### {traversejson:path|json}
                * Traverses a JSON object using dot notation path and returns the value.
                * Example: `{traversejson:user.name|{"user":{"name":"John"}}}` -> "John"
                * Example: `{traversejson:1.id|[{}, {"id":42}]}` -> "42"
                * Returns "[JSON traverse error]" if path is invalid or JSON is malformed
            """
            try:
                parts = str(val).split('|', 1)
                if len(parts) < 2:
                    return "[JSON traverse error: missing path or JSON]"
                
                path, json_str = parts[0].strip(), parts[1].strip()
                data = json.loads(json_str)
                
                keys = path.split('.')
                result = data
                for key in keys:
                    if isinstance(result, dict):
                        result = result.get(key)
                    elif isinstance(result, list):
                        try:
                            result = result[int(key)]
                        except (ValueError, IndexError):
                            return f"[JSON traverse error: invalid list index '{key}']"
                    else:
                        return f"[JSON traverse error: cannot traverse into '{key}' of non-container type]"
                
                return str(result) if result is not None else ""
            except json.JSONDecodeError:
                return "[JSON traverse error: malformed JSON]"
            except Exception as e:
                return f"[JSON traverse error: {str(e)}]"
        
        @self.formatter.register('repeat')
        def _repeat(ctx, val, **kwargs):
            """
            ### {repeat:count|text}
                * Repeats the text the specified number of times.
                * Example: `{repeat:3|hello}` -> "hellohellohello"
                * Example: `{repeat:5|* }` -> "* * * * * "
                * If count is not a valid number, returns the text once
            """
            try:
                parts = str(val).split('|', 1)
                if len(parts) < 2:
                    return str(val)
                
                count_str, text = parts[0].strip(), parts[1]
                repeat_count = int(count_str)
                
                if repeat_count < 0:
                    repeat_count = 0
                    
                return text * repeat_count
            except ValueError:
                return text
        
        @self.formatter.register('join')
        async def _join(ctx, val, **kwargs):
            """
            ### {join:delimiter|json_array}
                * Joins JSON array elements with delimiter.
                * Example: `{join:, |["a","b","c"]}` -> "a, b, c"
            """
            try:
                delim, arr = val.split('|', 1)
                return delim.join(json.loads(arr))
            except Exception as e:
                return f"[join error: {str(e)}]"
        
        @self.formatter.register('split')
        async def _split(ctx, val, **kwargs):
            """
            ### {split:delimiter|text}
                * Properly handles space delimiter and special cases.
                * Examples:
                - {split: |hello world} -> ["hello","world"]
                - {split:space|hello world} -> ["hello","world"]
                - {split:whitespace|hello   world} -> ["hello","world"]
            """
            try:
                if not val:
                    return json.dumps([])
                    

                parts = val.split('|', 1)
                if len(parts) < 2:
                    return "[split error: missing text to split]"
                    
                delim_spec, text = parts
                

                if delim_spec.lower() == "space":
                    delim = " "
                elif delim_spec.lower() == "whitespace":
                    return json.dumps(re.split(r'\s+', text.strip()))
                else:
                    delim = delim_spec.replace("\\n", "\n").replace("\\t", "\t")
                

                if delim == "" and " " in val:
                    delim = " "
                    
                return json.dumps([s.strip() for s in text.split(delim) if s.strip()])
            
            except Exception as e:
                return f"[split error: {str(e)}]"
        
        @self.formatter.register('trim')
        @self.formatter.register('strip')
        async def _trim(ctx, val, **kwargs):
            """
            ### {trim:text}
                * Removes leading/trailing whitespace.
                * Example: `{trim:  test  }` -> "test"
            """
            return val.strip()
        
        @self.formatter.register('substring')
        async def _substring(ctx, args_str, **kwargs):
            """
            ### {substring:text|start|end|step}
                * Extracts a substring.
                * Example: `{substring:Hello World|6|11}` -> "World"
            """
            try:
                processed_input = str(args_str)

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
                * Example: `{replace:Hello|e|a}` -> "Hallo"
            """
            try:
                processed_input = str(args_str)
                
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
            

        @self.formatter.register('timestamp')
        async def _timestamp(ctx, val, **kwargs):
            """
            ### {timestamp:format|timezone|offset}
                * Formats timestamp with timezone support.
                * Format options:
                    - discord: t/T/d/D/f/F/R (Discord-style timestamps)
                    - strftime: Any valid format string
                    - unix/iso: UNIX timestamp or ISO-8601
                * Timezone: IANA name (e.g. "Europe/Paris")
                * Offset: +- hours adjustment (e.g. "+1")
                * Example: `{timestamp:F|Europe/Paris|+1}`
            """
            try:
                parts = val.split('|', 2) if val else []
                format_code = parts[0].strip() if parts else "f"
                tz = parts[1].strip() if len(parts) > 1 else "UTC"
                offset = float(parts[2]) if len(parts) > 2 else 0


                try:
                    tz_info = ZoneInfo(tz)
                except Exception:
                    tz_info = ZoneInfo("UTC")

                now = datetime.now(tz_info) + timedelta(hours=offset)


                discord_formats = {
                    "t": "t",
                    "T": "T",
                    "d": "d",
                    "D": "D",
                    "f": "f",
                    "F": "F",
                    "R": "R"
                }

                if format_code == "R":
                    return f"<t:{int(now.timestamp())}:R>"
                elif format_code in discord_formats:
                    fmt = discord_formats[format_code]
                    return f"<t:{int(now.timestamp())}:{fmt}>"
                elif format_code.lower() == "unix":
                    return str(int(now.timestamp()))
                elif format_code.lower() == "iso":
                    return now.isoformat()
                else:
                    return now.strftime(format_code)

            except Exception as e:
                return f"[timestamp error: {str(e)}]"
        
        @self.formatter.register('duration')
        async def _duration(ctx, val, **kwargs):
            """
            ### {duration:start|end|format|precision}
                * Calculates duration between timestamps (supports relative expressions)
                * Formats:
                    - human: "3d 2h" (default)
                    - precise: "3 days, 2 hours, 15 minutes"
                    - colon: "74:15:30" (HH:MM:SS)
                    - iso: "P3DT2H15M30S" (ISO 8601)
                    - seconds: total seconds
                    - discord: <t:unix_timestamp:F>
                    - unix: Unix timestamp
                * Supports:
                    - Absolute: ISO dates, Unix timestamps
                    - Relative: now+2h, now-30m
                * Examples:
                    - {duration:now|now+3h|human} -> "3h"
                    - {duration:2023-01-01|now|precise}
                    - {duration:now-30m|now+1h|colon} -> "01:30:00"
            """
            try:
                parts = str(val).split('|', 3)
                start_str = parts[0].strip()
                end_str = parts[1].strip()
                fmt = parts[2].lower() if len(parts) > 2 else "human"
                precision = int(parts[3]) if len(parts) > 3 else 2

                def parse_relative(time_str):
                    now = datetime.now(ZoneInfo("UTC"))
                    match = re.match(r'now([+-])(\d+)([hmsd])', time_str.lower())
                    if not match:
                        return None
                    
                    sign, num, unit = match.groups()
                    delta = timedelta(**{
                        'h': {'hours': int(num)},
                        'm': {'minutes': int(num)},
                        's': {'seconds': int(num)},
                        'd': {'days': int(num)}
                    }[unit])
                    return now + delta if sign == '+' else now - delta

                def parse_time(time_str):
                    if time_str.lower().startswith('now'):
                        relative = parse_relative(time_str)
                        if relative:
                            return relative
                    

                    if time_str.lower() == "now":
                        return datetime.now(ZoneInfo("UTC"))
                    try:
                        return datetime.fromisoformat(time_str).astimezone(ZoneInfo("UTC"))
                    except ValueError:
                        try:
                            return datetime.fromtimestamp(int(time_str), ZoneInfo("UTC"))
                        except ValueError:
                            raise ValueError(f"Invalid time format: {time_str}")


                start = parse_time(start_str)
                end = parse_time(end_str)
                delta = end - start if end > start else start - end
                total_seconds = delta.total_seconds()


                def format_human(seconds, max_units):
                    intervals = [
                        ('year', 31536000),
                        ('month', 2592000),
                        ('week', 604800),
                        ('day', 86400),
                        ('hour', 3600),
                        ('minute', 60),
                        ('second', 1)
                    ]
                    parts = []
                    for name, count in intervals:
                        value = int(seconds // count)
                        if value > 0:
                            seconds -= value * count
                            parts.append(f"{value}{name[0]}")
                        if len(parts) >= max_units:
                            break
                    return " ".join(parts) if parts else "0s"

                def format_precise(seconds):
                    units = [
                        ('day', delta.days),
                        ('hour', delta.seconds // 3600),
                        ('minute', (delta.seconds // 60) % 60),
                        ('second', delta.seconds % 60)
                    ]
                    parts = []
                    for unit, value in units:
                        if value > 0:
                            parts.append(f"{value} {unit}{'s' if value != 1 else ''}")
                    return ", ".join(parts) if parts else "0 seconds"

                def format_iso(seconds):
                    days = delta.days
                    hours = delta.seconds // 3600
                    minutes = (delta.seconds // 60) % 60
                    seconds = delta.seconds % 60
                    iso = "P"
                    if days: iso += f"{days}D"
                    if any((hours, minutes, seconds)):
                        iso += "T"
                        if hours: iso += f"{hours}H"
                        if minutes: iso += f"{minutes}M"
                        if seconds: iso += f"{seconds}S"
                    return iso.replace("T0S", "").replace("P0D", "PT0S")


                if fmt == "human":
                    return format_human(total_seconds, precision)
                elif fmt == "precise":
                    return format_precise(total_seconds)
                elif fmt == "colon":
                    hours = int(total_seconds // 3600)
                    minutes = int((total_seconds % 3600) // 60)
                    seconds = int(total_seconds % 60)
                    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                elif fmt == "iso":
                    return format_iso(total_seconds)
                elif fmt == "seconds":
                    return str(int(total_seconds))
                elif fmt in ("discord", "unix"):
                    ts = int(end.timestamp() if fmt == "discord" else total_seconds)
                    return f"<t:{ts}:F>" if fmt == "discord" else str(ts)
                else:
                    return format_human(total_seconds, precision)

            except Exception as e:
                return f"[duration error: {str(e)}]"
        
        @self.formatter.register('businessdays')
        async def _businessdays(ctx, val, **kwargs):
            """
            ### {businessdays:start|end|[holidays]}
                * Calculates working days between dates. (excludes weekends + holidays)
                * Holidays format: JSON array as string: "[""2023-12-25""]"
                * Example: `{businessdays:2023-12-01|2023-12-31|["2023-12-25"]}`
            """
            try:
                parts = val.split('|', 2)
                if len(parts) < 2:
                    return "[businessdays error: need start and end dates]"
                    
                start_str, end_str = parts[0].strip(), parts[1].strip()
                holidays = json.loads(parts[2].replace('""', '"')) if len(parts) > 2 else []

                def parse_date(d):
                    if d.lower() == "now":
                        return datetime.now().date()
                    try:
                        return datetime.fromisoformat(d).date()
                    except ValueError:
                        try:
                            return datetime.fromtimestamp(int(d)).date()
                        except:
                            raise ValueError(f"Invalid date: {d}")

                start_date = parse_date(start_str)
                end_date = parse_date(end_str)
                
                if start_date > end_date:
                    start_date, end_date = end_date, start_date

                delta = end_date - start_date
                business_days = 0
                holidays = [datetime.fromisoformat(h).date() if isinstance(h, str) else h for h in holidays]

                for i in range(delta.days + 1):
                    current = start_date + timedelta(days=i)
                    if current.weekday() < 5 and current not in holidays:
                        business_days += 1

                return str(business_days)
                
            except json.JSONDecodeError:
                return "[businessdays error: invalid holidays format]"
            except Exception as e:
                return f"[businessdays error: {str(e)}]"
        
        @self.formatter.register('parsetime')
        async def _parsetime(ctx, val, **kwargs):
            """
            ### {parsetime:time string|timezone|format}
                * Parse natural language timestamps to ISO, unix, or discord's formats.
                * Example: `{parsetime:in 2 hours|UTC|ISO}`
            """
            try:
                parts = val.split('|', 2)
                time_str = parts[0].strip(' "\'')
                tz = parts[1].strip() if len(parts) > 1 else "UTC"
                fmt = parts[2].strip().lower() if len(parts) > 2 else "iso"


                now = datetime.now(ZoneInfo(tz))
                

                settings = {
                    'TIMEZONE': tz,
                    'RETURN_AS_TIMEZONE_AWARE': True,
                    'PREFER_DATES_FROM': 'future',
                    'RELATIVE_BASE': now,
                    'DATE_ORDER': 'MDY',
                }


                dt = dateparser.parse(
                    time_str,
                    settings=settings
                )

                if not dt:
                    return f"[parsetime error: could not understand '{time_str}']"


                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=ZoneInfo(tz))
                dt = dt.astimezone(ZoneInfo(tz))


                if fmt == "unix":
                    return str(int(dt.timestamp()))
                elif fmt == "discord":
                    return f"<t:{int(dt.timestamp())}:F>"
                return dt.isoformat()

            except Exception as e:
                return f"[parsetime error: {str(e)}]"
        
        
        @self.formatter.register('jsonpretty')
        async def _jsonpretty(ctx, val, **kwargs):
            """
                ### {jsonpretty:json}
                    * Formats JSON with indentation.
                    * Example: `{jsonpretty:{"a":1}}` -> 
                {
                    "a": 1
                }
            """
            try:
                data = json.loads(val)
                return json.dumps(data, indent=2)
            except Exception as e:
                return f"[jsonpretty error: {str(e)}]"
        
        @self.formatter.register('jsonschema')
        async def _jsonschema(ctx, val, **kwargs):
            """
            ### {jsonschema:json|schema}
                * Validates JSON against a schema.
                * Returns "valid" or error message.
                * Example: `{jsonschema:{"age":25}|{"type":"object","properties":{"age":{"type":"number"}}}`
            """
            try:
                parts = str(val).split("|", 1)
                if len(parts) < 2:
                    return "[jsonschema error: missing json or schema]"
                    
                json_str, schema_str = parts
                instance = json.loads(json_str)
                schema = json.loads(schema_str)
                
                validate(instance=instance, schema=schema)
                return "valid"
            except ValidationError as e:
                return f"validation error: {str(e)}"
            except Exception as e:
                return f"[jsonschema error: {str(e)}]"
        
        @self.formatter.register('type')
        async def _type(ctx, val, **kwargs):
            """
            ### {type:value}
                * Returns the type of the given value.
                * Example: `{type:{arg:0}}` -> "str"
                * Example: `{type:[1,2,3]}` -> "list"
            """
            try:
                evaluated_val = ast.literal_eval(val)
            except:
                evaluated_val = val
            return type(evaluated_val).__name__
        
        @self.formatter.register('hash')
        async def _hash(ctx, val, **kwargs):
            """
            ### {hash:algorithm|text}
                * Generates hash digest.
                * Supported algorithms: md5, sha1, sha256, sha512
                * Example: `{hash:sha256|hello}` -> "2cf24d...b2b4"
            """
            try:
                algo, text = val.split('|', 1)
                return hashlib.new(algo.strip(), text.encode()).hexdigest()
            except Exception as e:
                return f"[Hash error: {str(e)}]"
        
        @self.formatter.register('urlencode')
        async def _urlencode(ctx, text, **kwargs):
            """
            ### {urlencode:text}
                * URL-encodes the given text.
                * Example: `{urlencode:hello world}` -> "hello%20world"
            """
            try:
                processed = str(text)
                return quote(processed)
            except Exception:
                return text
        
        @self.formatter.register('urldecode')
        async def _urldecode(ctx, text, **kwargs):
            """
            ### {urldecode:text}
                * URL-decodes the given text.
                * Example: `{urldecode:hello%20world}` -> "hello world"
            """
            try:
                processed = str(text)
                return unquote(processed)
            except Exception:
                return text
        
        @self.formatter.register('base64encode')
        async def _base64encode(ctx, text, **kwargs):
            """
            ### {base64encode:text}
                * Base64 encodes the given text.
                * Example: `{base64encode:hello}` -> "aGVsbG8="
            """
            try:
                processed = str(text)
                return base64.b64encode(processed.encode()).decode()
            except Exception:
                return "[base64 error]"
        
        @self.formatter.register('base64decode')
        async def _base64decode(ctx, text, **kwargs):
            """
            ### {base64decode:text}
                * Base64 decodes the given text.
                * Example: `{base64decode:aGVsbG8=}` -> "hello"
            """
            try:
                processed = str(text)
                return base64.b64decode(processed.encode()).decode()
            except Exception:
                return "[base64 error]"
        
        @self.formatter.register('hex')
        async def _hex(ctx, args_str, **kwargs):
            """
            ### {hex:encode|text} or {hex:decode|text}
                * Hex encodes or decodes the given text.
                * Example: `{hex:encode|hello}` -> "68656c6c6f"
                * Example: `{hex:decode|68656c6c6f}` -> "hello"
            """
            try:
                processed = str(args_str)
                mode, text = processed.split("|", 1)
                mode = mode.strip().lower()
                
                if mode == "encode":
                    return text.encode().hex()
                elif mode == "decode":
                    return bytes.fromhex(text).decode()
                else:
                    return "[hex error: invalid mode]"
            except Exception:
                return "[hex error]"
        
        @self.formatter.register('countdown')
        async def _countdown(ctx, val, **kwargs):
            """
            ### {countdown:target_time|format|timezone|past_message}
                * Creates a countdown/count-up timer relative to current time.
                * Time formats: ISO-8601, UNIX timestamp, or natural language
                * Output formats:
                    - human: "3 days, 2 hours" (default)
                    - precise: "3 days, 2 hours, 15 minutes, 30 seconds"
                    - colon: "74:15:30" (total hours)
                    - iso: ISO 8601 duration format
                    - discord: Discord relative timestamp (<t:...:R>)
                * Timezone: IANA timezone name (default: UTC)
                * past_message: Custom message for past times (default: "The target time has already passed.")
                * Examples:
                    - `{countdown:2025-01-01 00:00:00}`
                    - `{countdown:1735689600|colon|America/New_York}`
                    - `{countdown:tomorrow at 3pm|discord|Europe/London}`
            """
            try:
                parts = str(val).split('|', 3)
                time_str = parts[0].strip('"')
                fmt = parts[1].lower() if len(parts) > 1 else "human"
                tz = parts[2] if len(parts) > 2 else "UTC"
                past_msg = parts[3] if len(parts) > 3 else "The target time has already passed."


                try:
                    if time_str.lower() == "now":
                        target = datetime.now(ZoneInfo(tz))
                    elif time_str.isdigit():
                        target = datetime.fromtimestamp(int(time_str), ZoneInfo(tz))
                    else:
                        target = dateparser.parse(
                            time_str,
                            settings={'TIMEZONE': tz, 'RETURN_AS_TIMEZONE_AWARE': True}
                        )
                        
                    if not target:
                        return "[countdown error: invalid time format]"
                except Exception as e:
                    return f"[countdown error: invalid time - {str(e)}]"


                now = datetime.now(ZoneInfo(tz))
                delta = target - now if target > now else now - target
                is_past = target < now


                if fmt == "discord":
                    return f"<t:{int(target.timestamp())}:R>" if not is_past else past_msg


                if is_past:
                    return past_msg


                def format_duration(seconds, precision=3):
                    intervals = [
                        ('day', 86400),
                        ('hour', 3600),
                        ('minute', 60),
                        ('second', 1)
                    ]
                    
                    parts = []
                    for name, count in intervals:
                        value = int(seconds // count)
                        if value:
                            seconds -= value * count
                            parts.append(f"{value} {name if value == 1 else name + 's'}")
                        if len(parts) >= precision:
                            break
                    return ", ".join(parts) if parts else "0 seconds"

                total_seconds = delta.total_seconds()
                
                if fmt == "human":
                    return format_duration(total_seconds)
                elif fmt == "precise":
                    return format_duration(total_seconds, precision=4)
                elif fmt == "colon":
                    hours, rem = divmod(total_seconds, 3600)
                    mins, secs = divmod(rem, 60)
                    return f"{int(hours):02d}:{int(mins):02d}:{int(secs):02d}"
                elif fmt == "iso":
                    return f"P{delta.days}DT{delta.seconds}S".replace("T0S", "")
                else:
                    return format_duration(total_seconds)

            except Exception as e:
                return f"[countdown error: {str(e)}]"
        
        @self.formatter.register('reverse')
        async def _reverse(ctx, text, **kwargs):
            """
            ### {reverse:text}
                * Reverses the given text.
                * Example: `{reverse:hello}` -> "olleh"
            """
            try:
                processed_text = str(text)
                return processed_text[::-1]
            except Exception:
                return text
            
        @self.formatter.register('if')
        async def _if(ctx, args_str, **kwargs):
            """
            ### {if:left|operator|right|then:value[|elif:left|operator|right|then:value|...]|else:value}
                * Flexible if conditions.
                * elif and else are optional, and will be None by default.
                * You can have any amount of elif statements.
                * Operators: ==, !=, >=, <=, >, <, *= (contains), ^= (starts with), $= (ends with), ~= (regex match)
                * Prefixing any operators with `!` reverses them. (!*=)
                * Example: `{if:some|==|thing|then:yes|else:no}`
            """
            resolved_str, _, _, _ = await self.formatter.format(args_str, ctx, **kwargs)
            tokens = []
            for part in resolved_str.split('|'):
                if ':' in part:
                    key = part.split(':')[0].lower()
                    if key in ('then', 'else', 'elif'):
                        key_val = part.split(':', 1)
                        tokens.append(key_val[0].strip())
                        tokens.append(key_val[1].strip())
                    else:
                        tokens.append(part.strip())
                else:
                    tokens.append(part.strip())

            if len(tokens) < 4:
                return "[error: missing required arguments]"

            i = 0
            conditions = []
            else_value = None


            left = tokens[i]
            op = tokens[i + 1]
            right = tokens[i + 2]
            i += 3

            if i >= len(tokens) or tokens[i].lower() != 'then':
                return f"[error: missing 'then' after condition at position {i}]"
            i += 1
            if i >= len(tokens):
                return "[error: missing value after 'then']"
            then_val = tokens[i]
            i += 1
            conditions.append((left, op, right, then_val))


            while i < len(tokens):
                if tokens[i].lower() == 'elif':
                    i += 1
                    if i + 3 >= len(tokens):
                        return "[error: incomplete elif block]"
                    elif_left = tokens[i]
                    elif_op = tokens[i+1]
                    elif_right = tokens[i+2]
                    i += 3
                    if i >= len(tokens) or tokens[i].lower() != 'then':
                        return "[error: missing 'then' after elif]"
                    i += 1
                    if i >= len(tokens):
                        return "[error: missing value after elif 'then']"
                    elif_then = tokens[i]
                    i += 1
                    conditions.append((elif_left, elif_op, elif_right, elif_then))
                elif tokens[i].lower() == 'else':
                    i += 1
                    else_value = '|'.join(tokens[i:])
                    break
                else:
                    break


            ops = {
                '==': lambda a, b: str(a) == str(b),
                '!=': lambda a, b: str(a) != str(b),
                '>': lambda a, b: float(a) > float(b),
                '<': lambda a, b: float(a) < float(b),
                '>=': lambda a, b: float(a) >= float(b),
                '<=': lambda a, b: float(a) <= float(b),
                '*=': lambda a, b: str(b) in str(a),
                '^=': lambda a, b: str(a).startswith(str(b)),
                '$=': lambda a, b: str(a).endswith(str(b)),
                '~=': lambda a, b: re.search(str(b), str(a)) is not None,
            }


            for cond in conditions:
                l, o, r, t = cond
                negate = False

                if o.startswith('!') and o[1:] in ops:
                    negate = True
                    o = o[1:]

                func = ops.get(o)
                if not func:
                    return f"[error: unknown operator '{o}']"

                try:
                    result = func(l, r)
                except Exception as e:
                    return f"[error: failed to evaluate condition - {str(e)}]"

                if negate:
                    result = not result

                if result:
                    text, _, _, _ = await self.formatter.format(t, ctx, **kwargs)
                    return text.strip()


            if else_value is not None:
                text, _, _, _ = await self.formatter.format(else_value, ctx, **kwargs)
                return text.strip()

            return None
        
        @self.formatter.register('and')
        async def _and(ctx, args_str, **kwargs):
            """
            ### {and:value1|value2|...}
                * Returns last value if ALL values are non-empty strings
                * Returns None if any value is empty
                * Example: `{and:Yes|{get:var}}` returns "Yes" only if {get:var} exists
            """
            args = self.parse_args(args_str)
            if not args:
                return None
            
            last_valid = ""
            for arg in args:
                if not arg.strip():
                    return None
                last_valid = arg
            return last_valid
        
        @self.formatter.register('or')
        async def _or(ctx, args_str, **kwargs):
            """
            ### {or:value1|value2|...}
                * Returns first non-empty value
                * Example: `{or:{get:var1}|{get:var2}|default}`
            """
            for arg in self.parse_args(args_str):
                if arg.strip():
                    return arg
            return None
        
        @self.formatter.register('equals')
        async def _equals(ctx, args_str, **kwargs):
            """
            ### {equals:val1|val2|...}
                * Returns True if ALL values match exactly. False Otherwise.
                * Example: `{equals:{get:var}|hello}`
            """
            args = self.parse_args(args_str)
            if len(args) < 2:
                return ""
            
            first = args[0]
            for val in args[1:]:
                if val != first:
                    return False
            return True
        
        @self.formatter.register('notequals')
        @self.formatter.register('unequals')
        async def _notequals(ctx, args_str, **kwargs):
            """
            ### {notequals:val1|val2|...}
                * Returns True if any value differs from others. False Otherwise.
                * Example: `{notequals:{get:var}|{get:var2}}`
            """
            args = self.parse_args(args_str)
            if len(args) < 2:
                return None
            
            first = args[0]
            for val in args[1:]:
                if val != first:
                    return True
            return False
        
        @self.formatter.register('range')
        async def _range(ctx, args_str, **kwargs):
            """
            ### {range:min|max}
                * Generates a random integer between min and max (inclusive)
                * Example: `{range:1|6}` -> "5"
            """
            try:
                processed = str(args_str)
                if '|' in processed:
                    min_val, max_val = processed.split('|', 1)
                else:
                    min_val, max_val = '1', processed
                
                min_val = int(min_val.strip())
                max_val = int(max_val.strip())

                if min_val > max_val:
                    min_val, max_val = max_val, min_val
                
                return random.randint(min_val, max_val)
            except Exception:
                return "[range error: invalid input]"
        
        @self.formatter.register('dice')
        async def _dice(ctx, notation, **kwargs):
            """
            ### {dice:notation}
                * Rolls the dice. (uses dice notation)
                * Example: `{dice:2d6+1}` -> Rolls 2 six-sided dice and adds 1
            """
            try:
                processed = str(notation)
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
                processed = str(options_str)
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
            return str(len(str(val)))
            
        @self.formatter.register('upper')
        def _upper(ctx, val, **kwargs):
            """
            ### {upper:text}
                * Converts text to uppercase.
                * Example: `{upper:hello}` -> "HELLO"
            """
            return str(val).upper()
            
        @self.formatter.register('lower')
        def _lower(ctx, val, **kwargs):
            """
            ### {lower:text}
                * Converts text to lowercase.
                * Example: `{lower:HELLO}` -> "hello"
            """
            return str(val).lower()
            
        @self.formatter.register('capitalize')
        def _capitalize(ctx, val, **kwargs):
            """
            ### {capitalize:text}
                * Capitalizes the first letter.
                * Example: `{capitalize:hello}` -> "Hello"
            """
            return str(val).capitalize()
            
        @self.formatter.register('set')
        async def _set(ctx, val, **kwargs):
            """
            ### {set:name|value}
                * Sets a variable for the tag.
                * Example: `{set:name|John}`
            """
            parts = val.split('|', 1)
            if len(parts) < 2:
                return "[error: format should be {set:name|value}]"
            name, value = parts[0].strip(), parts[1].strip()
            

            ctx.cog._variables.setdefault(ctx.message.id, {})[name] = value
            return ""
            
        @self.formatter.register('get')
        async def _get(ctx, name, **kwargs):
            """
            ### {get:name}
                * Retrieves a previously set variable in the tag.
                * Example: `Hello {get:name}!`
            """
            variables = ctx.cog._variables.get(ctx.message.id, {})
            return str(variables.get(name.strip(), ""))
            
        @self.formatter.register('math')
        def _math(ctx, expr, **kwargs):
            """
            ### {math:expression}
                * Evaluates a mathematical expression.
                * Example: `{math:5+3*2}` -> "11"
            """
            try:
                expr = str(expr)
                if not expr:
                    return '0'
                return str(eval(expr, {"__builtins__": None}, {}))
            except Exception as e:
                return f'[math error: {e}]'
        
        @self.formatter.register('python')
        @self.formatter.register('py')
        async def _python(ctx, code, **kwargs):
            """
            ### {python:code}
                * Execute Python code.
                * Example: `{py:print("hi")}` -> "hi"
            """
            return await self.execute_language(ctx, 'python', code, **kwargs)

        @self.formatter.register('bash')
        @self.formatter.register('sh')
        async def _bash(ctx, code, **kwargs):
            """
            ### {bash:code}
                * Execute Bash code.
                * Example: `{sh:echo hi}` -> "hi"
            """
            return await self.execute_language(ctx, 'bash', code, **kwargs)

        @self.formatter.register('javascript')
        @self.formatter.register('js')
        @self.formatter.register('node')
        async def _javascript(ctx, code, **kwargs):
            """
            ### {javascript:code}
                * Execute JavaScript code.
                * Example: `{js:console.log('hi');}` -> "hi"
            """
            return await self.execute_language(ctx, 'javascript', code, **kwargs)

        @self.formatter.register('typescript')
        @self.formatter.register('ts')
        async def _typescript(ctx, code, **kwargs):
            """
            ### {typescript:code}
                * Execute TypeScript code.
                * Example: `{ts:console.log('hi');}` -> "hi"
            """
            return await self.execute_language(ctx, 'typescript', code, **kwargs)
        
        @self.formatter.register('php')
        async def _php(ctx, code, **kwargs):
            """
            ### {php:code}
                * Execute PHP code.
            """
            return await self.execute_language(ctx, 'php', code, **kwargs)
        
        @self.formatter.register('ruby')
        @self.formatter.register('rb')
        async def _ruby(ctx, code, **kwargs):
            """
            ### {ruby:code}
                * Execute Ruby code.
                * Example: `{rb:puts "hi"}` -> "hi"
            """
            return await self.execute_language(ctx, 'ruby', code, **kwargs)
        
        @self.formatter.register('lua')
        async def _lua(ctx, code, **kwargs):
            """
            ### {lua:code}
                * Execute Lua code.
                * Example: `{lua:print("hi")}` -> "hi"
            """
            return await self.execute_language(ctx, 'lua', code, **kwargs)

        @self.formatter.register('go')
        async def _go(ctx, code, **kwargs):
            """
            ### {go:code}
                * Execute Go code.
            """
            return await self.execute_language(ctx, 'go', code, **kwargs)

        @self.formatter.register('rust')
        @self.formatter.register('rs')
        async def _rust(ctx, code, **kwargs):
            """
            ### {rust:code}
                * Execute Rust code.
            """
            return await self.execute_language(ctx, 'rust', code, **kwargs)

        @self.formatter.register('c')
        async def _c(ctx, code, **kwargs):
            """
            ### {c:code}
                * Execute C code.
            """
            return await self.execute_language(ctx, 'c', code, **kwargs)

        @self.formatter.register('cpp')
        @self.formatter.register('c++')
        async def _cpp(ctx, code, **kwargs):
            """
            ### {cpp:code}
                * Execute C++ code.
            """
            return await self.execute_language(ctx, 'cpp', code, **kwargs)

        @self.formatter.register('csharp')
        @self.formatter.register('cs')
        @self.formatter.register('c#')
        async def _csharp(ctx, code, **kwargs):
            """
            ### {csharp:code}
                * Execute C# code.
            """
            return await self.execute_language(ctx, 'csharp', code, **kwargs)

        @self.formatter.register('zig')
        async def _zig(ctx, code, **kwargs):
            """
            ### {zig:code}
                * Execute Zig code.
            """
            return await self.execute_language(ctx, 'zig', code, **kwargs)
        
        @self.formatter.register('java')
        async def _java(ctx, code, **kwargs):
            """
            ### {java:code}
                * Execute Java code.
            """
            return await self.execute_language(ctx, 'java', code, **kwargs)
        
        @self.formatter.register('kotlin')
        @self.formatter.register('kt')
        async def _kotlin(ctx, code, **kwargs):
            """
            ### {kt:code}
                * Execute Kotlin code.
            """
            return await self.execute_language(ctx, 'kotlin', code, **kwargs)
        
        @self.formatter.register('nim')
        async def _nim(ctx, code, **kwargs):
            """
            ### {nim:code}
                * Execute Nim code.
            """
            return await self.execute_language(ctx, 'nim', code, **kwargs)
        
        @self.formatter.register('user')
        async def _user(ctx, i, **kwargs):
            """
            ### {user:mention/name/displayname/id}
                * Returns username of mentioned user or self.
                * Example: `{user:@MiniatureEge2006}` -> "miniatureege2006"
            """
            user = await self.formatter.resolve_user(ctx, i)
            if isinstance(user, discord.Member):
                return user.name
            return user.name
        
        @self.formatter.register('userid')
        async def _userid(ctx, i, **kwargs):
            """
            ### {userid:mention/name/displayname/id}
                * Returns the user ID of an user or self.
                * Example: `{userid:@MiniatureEge2006}` -> "576819686877036584"
            """
            user = await self.formatter.resolve_user(ctx, i)
            return user.id
        
        @self.formatter.register('nick')
        async def _nick(ctx, i, **kwargs):
            """
            ### {nick:mention/name/displayname/id}
                * Returns server nickname of mentioned user or self. (returns display name instead if not available)
                * Example: `{nick:@MiniatureEge2006}` -> "Mini"
            """
            user = await self.formatter.resolve_user(ctx, i)
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
            user = await self.formatter.resolve_user(ctx, i)
            return user.display_name
        
        @self.formatter.register('mention')
        async def _mention(ctx, i, **kwargs):
            """
            ### {mention:mention/name/displayname/id}
                * Mentions the user or self.
                * Example: `{mention:@MiniatureEge2006}` -> "@MiniatureEge2006"
            """
            user = await self.formatter.resolve_user(ctx, i)
            return user.mention
        
        @self.formatter.register('avatar')
        async def _avatar(ctx, i, **kwargs):
            """
            ### {avatar:mention/name/displayname/id}
                * Returns guild avatar URL, otherwise global if not available.
                * Example: `{avatar:@MiniatureEge2006}` -> URL
            """
            user = await self.formatter.resolve_user(ctx, i)
            return str(user.display_avatar.url)
        
        @self.formatter.register('avatarkey')
        async def _avatarkey(ctx, i, **kwargs):
            """
            ### {avatarkey:mention/name/displayname/id}
                * Returns guild avatar hash, otherwise global if not available.
                * Example: `{avatarkey:@MiniatureEge2006}` -> hash
            """
            user = await self.formatter.resolve_user(ctx, i)
            return str(user.display_avatar.key)
        
        @self.formatter.register('useravatar')
        async def _useravatar(ctx, i, **kwargs):
            """
            ### {useravatar:mention/name/displayname/id}
                * Returns global avatar URL.
                * Example: `{useravatar:@MiniatureEge2006}` -> URL
            """
            user = await self.formatter.resolve_user(ctx, i)
            return str(user.avatar.url) if user.avatar else None
        
        @self.formatter.register('useravatarkey')
        async def _useravatarkey(ctx, i, **kwargs):
            """
            ### {useravatarkey:mention/name/displayname/id}
                * Returns global avatar hash.
                * Example: `{useravatarkey:@MiniatureEge2006}` -> hash
            """
            user = await self.formatter.resolve_user(ctx, i)
            return str(user.avatar.key) if user.avatar else None
        
        @self.formatter.register('banner')
        async def _banner(ctx, i, **kwargs):
            """
            ### {banner:mention/name/displayname/id}
                * Returns guild banner URL, otherwise global banner if unavailable.
                * Example: `{banner:@MiniatureEge2006}` -> URL
            """
            user = await self.formatter.resolve_user(ctx, i)
            if isinstance(user, discord.Member):
                return str(user.guild_banner.url) if user.guild_banner else await _userbanner(ctx, i)
        
        @self.formatter.register('bannerkey')
        async def _bannerkey(ctx, i, **kwargs):
            """
            ### {bannerkey:mention/name/displayname/id}
                * Returns guild banner hash, otherwise global banner if unavailable.
                * Example: `{bannerkey:@MiniatureEge2006}` -> hash
            """
            user = await self.formatter.resolve_user(ctx, i)
            if isinstance(user, discord.Member):
                return str(user.guild_banner.key) if user.guild_banner else await _userbannerkey(ctx, i)
        
        @self.formatter.register('userbanner')
        async def _userbanner(ctx, i, **kwargs):
            """
            ### {userbanner:mention/name/displayname/id}
                * Returns global banner URL.
                * Example: `{userbanner:@MiniatureEge2006}` -> URL
            """
            user = await self.formatter.resolve_user(ctx, i)
            if isinstance(user, discord.Member):
                user = await ctx.bot.fetch_user(user.id)
            if not user.banner:
                return None
            return str(user.banner.url)
        
        @self.formatter.register('userbannerkey')
        async def _userbannerkey(ctx, i, **kwargs):
            """
            ### {userbannerkey:mention/name/displayname/id}
                * Returns global banner hash.
                * Example: `{userbannerkey:@MiniatureEge2006}` -> hash
            """
            user = await self.formatter.resolve_user(ctx, i)
            if isinstance(user, discord.Member):
                user = await ctx.bot.fetch_user(user.id)
            if not user.banner:
                return None
            return str(user.banner.key)
        
        @self.formatter.register('usercreatedate')
        async def _usercreatedate(ctx, i, **kwargs):
            """
            ### {usercreatedate:mention/name/displayname/id}
                * Always returns account creation date (unlike userjoindate which returns server join date when available).
                * Example: `{usercreatedate:@MiniatureEge2006}` -> "2019-05-11 17:15:30 (May 11, 2019 at 05:15:30 PM)"
            """
            user = await self.formatter.resolve_user(ctx, i)
            return user.created_at.strftime('%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)') if user.created_at else None
        
        @self.formatter.register('userjoindate')
        async def _userjoindate(ctx, i, **kwargs):
            """
            ### {userjoindate:mention/name/displayname/id}
                * Returns join date in server if member, otherwise account creation date.
                * Example outputs:
                - For server members: "2025-04-24 12:00:00 (April 24, 2025 at 12:00:00 PM)"
                - For non-members: "2019-05-11 17:15:30 (May 11, 2019 at 05:15:30 PM)"
            """
            user = await self.formatter.resolve_user(ctx, i)
            date_to_use = None
            
            if isinstance(user, discord.Member):
                date_to_use = user.joined_at or user.created_at
            else:
                date_to_use = user.created_at
            
            return date_to_use.strftime('%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)') if date_to_use else None
        
        @self.formatter.register('userstatus')
        async def _userstatus(ctx, i, **kwargs):
            """
            ### {userstatus:mention/name/displayname/id}
                * Returns user status.
                * Example: `{userstatus:@MiniatureEge2006}` -> "Online"
            """
            user = await self.formatter.resolve_user(ctx, i)
            if isinstance(user, discord.Member):
                return str(user.status.value).capitalize()
            return None
        
        @self.formatter.register('usercustomstatus')
        async def _usercustomstatus(ctx, i, **kwargs):
            """
            ### {usercustomstatus:mention/name/displayname/id}
                * Returns custom status if set.
                * Example: `{usercustomstatus:@MiniatureEge2006}` -> "Playing Roblox"
            """
            user = await self.formatter.resolve_user(ctx, i)
            if not isinstance(user, discord.Member):
                return None
            
            activities = []
            for activity in user.activities:
                if isinstance(activity, discord.CustomActivity):
                    status = []
                    if activity.emoji:
                        status.append(str(activity.emoji))
                    if activity.name:
                        status.append(activity.name)
                    if status:
                        activities.append(" ".join(status))
                
                elif isinstance(activity, discord.Game):
                    activities.append(f"Playing {activity.name}")
                elif isinstance(activity, discord.Spotify):
                    artists = ", ".join(activity.artists)
                    activities.append(f"Listening to {artists} - {activity.title}")
                elif isinstance(activity, discord.Streaming):
                    activities.append(f"Streaming {activity.game} on {activity.platform}")
                elif activity.type == discord.ActivityType.listening and not isinstance(activity, discord.Spotify):
                    activities.append(f"Listening to {activity.name}")
                elif activity.type == discord.ActivityType.watching:
                    activities.append(f"Watching {activity.name}")
                elif activity.type == discord.ActivityType.competing:
                    activities.append(f"Competing in {activity.name}")
                elif activity.type == discord.ActivityType.playing and not isinstance(activity, discord.Game):
                    activities.append(f"Playing {activity.name}")
            
            if not activities:
                return None
            
            return " | ".join(activities)
        
        @self.formatter.register('userbadges')
        async def _userbadges(ctx, i, **kwargs):
            """
            ### {userbadges:mention/name/displayname/id}
                * Returns user badges.
                * Example: `{userbadges:@MiniatureEge2006}` -> "Active Developer, Early Verified Bot Developer"
            """
            user = await self.formatter.resolve_user(ctx, i)
            if isinstance(user, discord.Member):
                badges = user.public_flags
            elif isinstance(user, discord.User):
                badges = user.public_flags
            else:
                return None
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
                return None
        
        @self.formatter.register('randuser')
        async def _randuser(ctx, user, **kwargs):
            """
            ### {randuser}
                * Returns a random user from the server.
                * Example: `{randuser}`
            """
            if ctx.guild:
                random_user = random.choice(ctx.guild.members)
                return random_user.name
            return None
        
        @self.formatter.register('randonline')
        async def _randonline(ctx, user, **kwargs):
            """
            ### {randonline}
                * Returns a random online user from the server.
                * Example: `{randonline}`
            """
            if ctx.guild:
                online_users = [user for user in ctx.guild.members if user.status != discord.Status.offline]
                random_online_user = random.choice(online_users)
                return random_online_user.name
            return None
        
        @self.formatter.register('randonlineid')
        async def _randonlineid(ctx, user, **kwargs):
            """
            ### {randonlineid}
                * Returns a random online user ID from the server.
                * Example: `{randonlineid}`
            """
            if ctx.guild:
                online_users = [user for user in ctx.guild.members if user.status != discord.Status.offline]
                random_online_user = random.choice(online_users)
                return random_online_user.id
            return None
        
        @self.formatter.register('randuserid')
        async def _randuserid(ctx, user, **kwargs):
            """
            ### {randuserid}
                * Returns a random user ID from the server.
                * Example: `{randuserid}`
            """
            if ctx.guild:
                random_user = random.choice(ctx.guild.members)
                return random_user.id
            return None
        
        @self.formatter.register('channel')
        async def _channel(ctx, channel, **kwargs):
            """
            ### {channel:channel}
                * Returns a channel name. Defaults to current channel.
                * Example: `{channel}` -> "general"
            """
            if not channel:
                return ctx.channel.name
            try:
                channel = await commands.GuildChannelConverter().convert(ctx, channel)
                return channel.name
            except Exception:
                return ctx.channel.name
        
        @self.formatter.register('channelmention')
        async def _channelmention(ctx, channel, **kwargs):
            """
            ### {channelmention:channel}
                * Returns a channel mention. Defaults to current channel.
                * Example: `{channelmention}` -> "#general"
            """
            if not channel:
                return ctx.channel.mention
            try:
                channel = await commands.GuildChannelConverter().convert(ctx, channel)
                return channel.mention
            except Exception:
                return ctx.channel.mention
        
        @self.formatter.register('channelid')
        async def _channelid(ctx, channel, **kwargs):
            """
            ### {channelid:channel}
                * Returns a channel ID. Defaults to current channel.
                * Example: `{channelid}` -> "1337131589087400046"
            """
            if not channel:
                return ctx.channel.id
            try:
                channel = await commands.GuildChannelConverter().convert(ctx, channel)
                return channel.id
            except Exception:
                return ctx.channel.id
        
        @self.formatter.register('randchannel')
        async def _randchannel(ctx, channel, **kwargs):
            """
            ### {randchannel}
                * Returns a random channel name from the server.
                * Example: `{randchannel}`
            """
            if ctx.guild:
                random_channel = random.choice(ctx.guild.channels)
                return random_channel.name
            return None
        
        @self.formatter.register('randchannelmention')
        async def _randchannelmention(ctx, channel, **kwargs):
            """
            ### {randchannelmention}
                * Returns a random channel mention from the server.
                * Example: `{randchannelmention}`
            """
            if ctx.guild:
                random_channel = random.choice(ctx.guild.channels)
                return random_channel.mention
            return None
        
        @self.formatter.register('randchannelid')
        async def _randchannelid(ctx, channel, **kwargs):
            """
            ### {randchannelid}
                * Returns a random channel ID from the server.
                * Example: `{randchannelid}`
            """
            if ctx.guild:
                random_channel = random.choice(ctx.guild.channels)
                return random_channel.id
            return None
        
        @self.formatter.register('guild')
        @self.formatter.register('server')
        async def _guild(ctx, i, **kwargs):
            """
            ### {guild}
                * Returns current server name.
                * Example: `{guild}` -> "G-Server"
            """
            if ctx.guild:
                return ctx.guild.name
            elif isinstance(ctx.guild, discord.DMChannel):
                return "Direct Messages"
            else:
                return "Private Channel"
        
        @self.formatter.register('guildid')
        @self.formatter.register('serverid')
        async def _guildid(ctx, i, **kwargs):
            """
            ### {guildid}
                * Returns current server ID.
                * Example: `{guildid}` -> "1337128182964293632"
            """
            if ctx.guild:
                return ctx.guild.id
            elif isinstance(ctx.guild, discord.DMChannel):
                return None
            else:
                return None
        
        @self.formatter.register('guildicon')
        @self.formatter.register('servericon')
        async def _guildicon(ctx, i, **kwargs):
            """
            ### {guildicon}
                * Returns current server icon URL.
                * Example: `{guildicon}`
            """
            if ctx.guild and ctx.guild.icon:
                return ctx.guild.icon.url
            return None
        
        @self.formatter.register('guildbanner')
        @self.formatter.register('serverbanner')
        async def _guildbanner(ctx, i, **kwargs):
            """
            ### {guildbanner}
                * Returns current server banner URL.
                * Example: `{guildbanner}`
            """
            if ctx.guild and ctx.guild.banner:
                return ctx.guild.banner.url
            return None

        @self.formatter.register('embed')
        @self.formatter.register('embedjson')
        @self.formatter.register('json.embed')
        async def _embed(ctx, args_str, **kwargs):
            """
            ### {embed:JSON}
                * Builds an embed from JSON data.
                * Example: `{embed:{"title":"Hello"}}`
            """
            try:
                processed_content, _, _, _ = await self.formatter.format(args_str, ctx, **kwargs)
                embed_data = json.loads(processed_content)
                resolved_data = await resolve_json_tags(ctx, embed_data)
                embed = DiscordGenerator._build_embed(**resolved_data)
                return ("", [embed], None, [])
            except json.JSONDecodeError as e:
                return (f"[embed error: {str(e)}]", [], None, [])
        
        async def parse_component_input(ctx, input_str: str):
            try:
                data = json.loads(input_str.strip())
                return await resolve_json_tags(ctx, data)
            except json.JSONDecodeError:
                raise ValueError("Component input must be valid JSON")

        async def resolve_json_tags(ctx, data):
            if isinstance(data, dict):
                return {k: await resolve_json_tags(ctx, v) for k, v in data.items()}
            elif isinstance(data, list):
                return [await resolve_json_tags(ctx, item) for item in data]
            elif isinstance(data, str):
                processed, _, _, _ = await self.formatter.format(data, ctx)
                return processed
            return data
            
        @self.formatter.register('button')
        @self.formatter.register('buttonjson')
        @self.formatter.register('json.button')
        async def _button(ctx, args_str, **kwargs):
            """
            ### {button:JSON}
                * Builds a button component from JSON data.
                * Example: `{button:{"label":"Click","style":"primary"}}`
            """
            try:
                params = await parse_component_input(ctx, args_str)
                

                if 'command' in params:
                    cmd = params.pop('command').strip()
                    params['custom_id'] = f"cmd:{cmd}"
                elif 'tag' in params:
                    tag = params.pop('tag').strip()
                    params['custom_id'] = f"tag:{tag}"
                elif 'custom_id' not in params and 'url' not in params:
                    params['custom_id'] = f"btn_{uuid.uuid4().hex[:8]}"


                if 'style' not in params and 'url' not in params:
                    params['style'] = 'secondary'

                button = DiscordGenerator.create_button(params)
                return ("", [], discord.ui.View().add_item(button), [])
            
            except Exception as e:
                return (f"[button error: {str(e)}]", [], None, [])
        
        @self.formatter.register('select')
        @self.formatter.register('selectjson')
        @self.formatter.register('json.select')
        async def _select(ctx, args_str, **kwargs):
            """
            ### {select:JSON}
                * Builds a select menu component from JSON data.
                * Example: `{select:{"placeholder": "Choose","min": 1,"options": [{"label":"A","value":"a"},{"label":"B","value":"b"}]}}`
            """
            try:
                data = await parse_component_input(ctx, args_str)

                select = DiscordGenerator.create_select(data)

                view = discord.ui.View().add_item(select)
                return ("", [], view, [])
            
            except Exception as e:
                return (f"[select error: {str(e)}]", [], None, [])
        
        @self.formatter.register('json.user')
        @self.formatter.register('userjson')
        async def _json_user(ctx, user_ref='', **kwargs):
            """
            ### {json.user:user}
                * Returns an user's JSON object. Defaults to self.
            """
            try:
                if not user_ref.strip():
                    user = ctx.author
                else:
                    user = await self.formatter.resolve_user(ctx, user_ref)

                user_data = {
                    "id": str(user.id),
                    "name": user.name,
                    "display_name": getattr(user, "display_name", user.name),
                    "discriminator": user.discriminator,
                    "bot": user.bot,
                    "created_at": user.created_at.isoformat(),
                    "avatar": str(user.avatar.key) if user.avatar else str(user.display_avatar.key),
                    "avatar_url": str(user.avatar.url) if user.avatar else str(user.display_avatar.url),
                    "banner": (str((await ctx.bot.fetch_user(user.id)).banner.key) if (await ctx.bot.fetch_user(user.id)).banner else None),
                    "banner_url": (str((await ctx.bot.fetch_user(user.id)).banner.url) if (await ctx.bot.fetch_user(user.id)).banner else None),
                    "mention": user.mention
                }

                return json.dumps(user_data)
            except Exception as e:
                return f"[JSON User Error: {str(e)}]"
        
        @self.formatter.register('json.member')
        @self.formatter.register('memberjson')
        async def _json_member(ctx, user_ref='', **kwargs):
            """
            ### {json.member:user}
                * Returns a member's JSON object. Defaults to self.
            """
            try:
                if not ctx.guild:
                    return "[JSON Member Error: Not in a guild]"

                if not user_ref.strip():
                    member = ctx.author
                else:
                    member = await self.formatter.resolve_user(ctx, user_ref)

                if not isinstance(member, discord.Member):
                    return "[JSON Member Error: User is not a member of the guild]"

                member_data = {
                    "id": str(member.id),
                    "name": member.name,
                    "display_name": getattr(member, "display_name", member.name),
                    "nick": member.nick,
                    "joined_at": member.joined_at.isoformat() if member.joined_at else None,
                    "avatar": str(member.guild_avatar.key) if member.guild_avatar else None,
                    "avatar_url": str(member.guild_avatar.url) if member.guild_avatar else None,
                    "banner": str(member.guild_banner.key) if member.guild_banner else None,
                    "banner_url": str(member.guild_banner.url) if member.guild_banner else None,
                    "roles": [{"id": str(r.id), "name": r.name} for r in member.roles],
                    "top_role": {"id": str(member.top_role.id), "name": member.top_role.name},
                    "guild_permissions": list(member.guild_permissions),
                    "timed_out_until": member.timed_out_until.isoformat() if member.timed_out_until else None
                }

                return json.dumps(member_data)
            except Exception as e:
                return f"[JSON Member Error: {str(e)}]"
        
        @self.formatter.register('json.memberoruser')
        @self.formatter.register('memberoruserjson')
        async def _json_memberoruser(ctx, user_ref='', **kwargs):
            """
            ### {json.memberoruser:user}
                * Returns an user or a member's JSON object. Defaults to self.
            """
            try:
                if not user_ref.strip():
                    user = ctx.author
                else:
                    user = await self.formatter.resolve_user(ctx, user_ref)
                
                user_data = {
                    "id": str(user.id),
                    "name": user.name,
                    "display_name": getattr(user, "display_name", user.name),
                    "discriminator": user.discriminator,
                    "bot": user.bot,
                    "created_at": user.created_at.isoformat(),
                    "avatar": str(user.display_avatar.key),
                    "avatar_url": str(user.display_avatar.url),
                    "banner": str(user.guild_banner.key) if getattr(user, "guild_banner", None) else (str((await ctx.bot.fetch_user(user.id)).banner.key) if (await ctx.bot.fetch_user(user.id)).banner else None),
                    "banner_url": str(user.guild_banner.url) if getattr(user, "guild_banner", None) else (str((await ctx.bot.fetch_user(user.id)).banner.url) if (await ctx.bot.fetch_user(user.id)).banner else None),
                    "mention": user.mention
                }
                
                if isinstance(user, discord.Member):
                    user_data.update({
                        "nick": user.nick,
                        "joined_at": user.joined_at.isoformat() if user.joined_at else None,
                        "roles": [{"id": str(r.id), "name": r.name} for r in user.roles],
                        "top_role": {"id": str(user.top_role.id), "name": user.top_role.name},
                        "guild_permissions": list(user.guild_permissions),
                        "timed_out_until": user.timed_out_until.isoformat() if user.timed_out_until else None
                    })
                
                return json.dumps(user_data)
            except Exception as e:
                return f"[JSON MemberOrUser Error: {str(e)}]"
        
        @self.formatter.register('json.message')
        @self.formatter.register('messagejson')
        async def _json_message(ctx, message_ref='', **kwargs):
            """
            ### {json.message:message}
                * Returns a message's JSON object. Defaults to current message.
            """
            try:
                if not message_ref.strip():
                    if ctx.message.reference:
                        message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                    else:
                        message = ctx.message
                else:
                    message_id = int(message_ref.strip())
                    message = await ctx.channel.fetch_message(message_id)
                
                message_data = {
                    "id": str(message.id),
                    "content": message.content,
                    "clean_content": message.clean_content,
                    "created_at": message.created_at.isoformat(),
                    "edited_at": message.edited_at.isoformat() if message.edited_at else None,
                    "author": json.loads(await _json_user(ctx, str(message.author.id))),
                    "channel": {
                        "id": str(message.channel.id),
                        "name": getattr(message.channel, "name", "DM"),
                        "mention": message.channel.mention
                    },
                    "attachments": [{
                        "id": str(a.id),
                        "filename": a.filename,
                        "url": a.url,
                        "size": a.size,
                        "content_type": a.content_type
                    } for a in message.attachments],
                    "embeds": [e.to_dict() for e in message.embeds],
                    "components": [c.to_dict() for c in message.components],
                    "mention_everyone": message.mention_everyone,
                    "mentions": [json.loads(await _json_user(ctx, str(u.id))) for u in message.mentions],
                    "reference": {
                        "message_id": str(message.reference.message_id),
                        "channel_id": str(message.reference.channel_id),
                        "guild_id": str(message.reference.guild_id)
                    } if message.reference else None,
                    "pinned": message.pinned,
                    "type": str(message.type)
                }
                
                
                return json.dumps(message_data)
            except Exception as e:
                return f"[JSON Message Error: {str(e)}]"
        
        @self.formatter.register('json.guild')
        @self.formatter.register('guildjson')
        async def _json_guild(ctx, guild_ref='', **kwargs):
            """
            ### {json.guild}
                * Returns the current server's JSON object.
            """
            try:
                if not ctx.guild:
                    return "{}"
                    
                guild_data = {
                    "id": str(ctx.guild.id),
                    "name": ctx.guild.name,
                    "description": ctx.guild.description,
                    "icon_url": str(ctx.guild.icon.url) if ctx.guild.icon else None,
                    "banner_url": str(ctx.guild.banner.url) if ctx.guild.banner else None,
                    "owner_id": str(ctx.guild.owner_id),
                    "created_at": ctx.guild.created_at.isoformat(),
                    "member_count": ctx.guild.member_count,
                    "premium_tier": ctx.guild.premium_tier,
                    "premium_subscription_count": ctx.guild.premium_subscription_count,
                    "features": ctx.guild.features,
                    "verification_level": str(ctx.guild.verification_level),
                    "explicit_content_filter": str(ctx.guild.explicit_content_filter),
                    "default_notifications": str(ctx.guild.default_notifications),
                    "mfa_level": str(ctx.guild.mfa_level),
                    "system_channel": {
                        "id": str(ctx.guild.system_channel.id),
                        "name": ctx.guild.system_channel.name
                    } if ctx.guild.system_channel else None,
                    "rules_channel": {
                        "id": str(ctx.guild.rules_channel.id),
                        "name": ctx.guild.rules_channel.name
                    } if ctx.guild.rules_channel else None,
                    "afk_channel": {
                        "id": str(ctx.guild.afk_channel.id),
                        "name": ctx.guild.afk_channel.name
                    } if ctx.guild.afk_channel else None,
                    "afk_timeout": ctx.guild.afk_timeout,
                    "emojis": [{
                        "id": str(e.id),
                        "name": e.name,
                        "animated": e.animated,
                        "url": str(e.url)
                    } for e in ctx.guild.emojis],
                    "roles": [{
                        "id": str(r.id),
                        "name": r.name,
                        "color": r.color.value,
                        "position": r.position,
                        "permissions": r.permissions.value,
                        "mentionable": r.mentionable
                    } for r in ctx.guild.roles],
                    "channels": [json.loads(await _json_channel(ctx, str(c))) for c in ctx.guild.channels],
                    "members": [json.loads(await _json_member(ctx, str(u))) for u in ctx.guild.members]
                }
                
                return json.dumps(guild_data)
            except Exception as e:
                return f"[JSON Guild Error: {str(e)}]"
        
        @self.formatter.register('json.channel')
        @self.formatter.register('channeljson')
        async def _json_channel(ctx, channel_ref='', **kwargs):
            """
            ### {json.channel:channel}
                * Returns a server channel's JSON object. Defaults to current channel.
            """
            try:
                channel = None
                

                if not channel_ref.strip():
                    channel = ctx.channel
                elif hasattr(channel_ref, 'id') and hasattr(channel_ref, 'type'):
                    channel = channel_ref
                elif isinstance(channel_ref, str):
                    channel_id = channel_ref.strip('<>#')
                    if channel_id.isdigit():
                        channel = ctx.guild.get_channel(int(channel_id))
                    else:
                        channel = discord.utils.get(ctx.guild.channels, name=channel_id)


                channel_data = {
                    "id": str(channel.id),
                    "name": getattr(channel, 'name', 'DM'),
                    "type": str(channel.type),
                    "created_at": channel.created_at.isoformat() if hasattr(channel, 'created_at') else None,
                    "position": getattr(channel, 'position', None),
                    "topic": getattr(channel, 'topic', None),
                    "nsfw": getattr(channel, 'nsfw', None),
                    "bitrate": getattr(channel, 'bitrate', None),
                    "user_limit": getattr(channel, 'user_limit', None),
                    "slowmode_delay": getattr(channel, 'slowmode_delay', None),
                    "category": {
                        "id": str(channel.category.id),
                        "name": channel.category.name
                    } if getattr(channel, 'category', None) else None,
                    "mention": channel.mention
                }
                
                return json.dumps(channel_data)
            except Exception as e:
                return f"[JSON Channel Error: {str(e)}]"
        
        @self.formatter.register('json.role')
        @self.formatter.register('rolejson')
        async def _json_role(ctx, role_ref='', **kwargs):
            """
            ### {json.role:role}
                * Returns a server role's JSON object. Defaults to all roles.
            """
            try:
                if not ctx.guild:
                    return "[]"
                    
                if not role_ref:
                    roles_data = []
                    for role in ctx.guild.roles:
                        role_data = {
                            "id": str(role.id),
                            "name": role.name,
                            "color": role.color.value,
                            "position": role.position,
                            "permissions": role.permissions.value,
                            "mentionable": role.mentionable,
                            "managed": role.managed,
                            "hoist": role.hoist,
                            "created_at": role.created_at.isoformat(),
                            "mention": role.mention
                        }
                        roles_data.append(role_data)
                    return json.dumps(roles_data)
                
                try:
                    role_id = int(role_ref.strip('<@&>'))
                    role = ctx.guild.get_role(role_id)
                    if role:
                        role_data = {
                            "id": str(role.id),
                            "name": role.name,
                            "color": role.color.value,
                            "position": role.position,
                            "permissions": role.permissions.value,
                            "mentionable": role.mentionable,
                            "managed": role.managed,
                            "hoist": role.hoist,
                            "created_at": role.created_at.isoformat(),
                            "mention": role.mention
                        }
                        return json.dumps(role_data)
                except ValueError:
                    pass
                

                role = discord.utils.get(ctx.guild.roles, name=role_ref)
                if role:
                    role_data = {
                        "id": str(role.id),
                        "name": role.name,
                        "color": role.color.value,
                        "position": role.position,
                        "permissions": role.permissions.value,
                        "mentionable": role.mentionable,
                        "managed": role.managed,
                        "hoist": role.hoist,
                        "created_at": role.created_at.isoformat(),
                        "mention": role.mention
                    }
                    return json.dumps(role_data)
                
                return "[JSON Role Error: Role not found]"
            except Exception as e:
                return f"[JSON Role Error: {str(e)}]"
        
        @self.formatter.register('json.emoji')
        @self.formatter.register('emojijson')
        async def _json_emoji(ctx, emoji_ref, **kwargs):
            """
            ### {json.emoji:emoji}
                * Returns a server emoji's JSON object. Defaults to all emojis.
            """
            try:
                if not ctx.guild:
                    return "[]"
                    
                emoji_ref = emoji_ref.strip()
                
                if not emoji_ref:
                    emojis_data = [{
                        "id": str(e.id),
                        "name": e.name,
                        "animated": e.animated,
                        "url": str(e.url),
                        "created_at": e.created_at.isoformat(),
                        "mention": str(e)
                    } for e in ctx.guild.emojis]
                    return json.dumps(emojis_data)
                

                try:
                    emoji_id = int(emoji_ref)
                    emoji = ctx.guild.get_emoji(emoji_id)
                    if emoji:
                        emoji_data = {
                            "id": str(emoji.id),
                            "name": emoji.name,
                            "animated": emoji.animated,
                            "url": str(emoji.url),
                            "created_at": emoji.created_at.isoformat(),
                            "mention": str(emoji)
                        }
                        return json.dumps(emoji_data)
                except ValueError:
                    pass
                

                emoji = discord.utils.get(ctx.guild.emojis, name=emoji_ref)
                if emoji:
                    emoji_data = {
                        "id": str(emoji.id),
                        "name": emoji.name,
                        "animated": emoji.animated,
                        "url": str(emoji.url),
                        "created_at": emoji.created_at.isoformat(),
                        "mention": str(emoji)
                    }
                    return json.dumps(emoji_data)
                
                return "[JSON Emoji Error: Emoji not found]"
            except Exception as e:
                return f"[JSON Emoji Error: {str(e)}]"
        
        @self.formatter.register('json.attachment')
        @self.formatter.register('attachmentjson')
        async def _json_attachment(ctx, attachment_ref, **kwargs):
            """
            ### {json.attachment:index}
                * Returns the current message's specific attachment. Defaults to all attachments. 
            """
            try:
                attachments = ctx.message.attachments
                if not attachments:
                    return "[]"
                    
                attachment_ref = attachment_ref.strip().lower()
                
                if not attachment_ref.strip():
                    attachments_data = [{
                        "id": str(a.id),
                        "filename": a.filename,
                        "url": a.url,
                        "size": a.size,
                        "content_type": a.content_type,
                        "height": getattr(a, 'height', None),
                        "width": getattr(a, 'width', None)
                    } for a in attachments]
                    return json.dumps(attachments_data)
                

                try:
                    index = int(attachment_ref)
                    if 0 <= index < len(attachments):
                        a = attachments[index]
                        attachment_data = {
                            "id": str(a.id),
                            "filename": a.filename,
                            "url": a.url,
                            "size": a.size,
                            "content_type": a.content_type,
                            "height": getattr(a, 'height', None),
                            "width": getattr(a, 'width', None)
                        }
                        return json.dumps(attachment_data)
                    return "[JSON Attachment Error: Invalid index]"
                except ValueError:
                    pass
                

                for a in attachments:
                    if attachment_ref in (a.url, a.filename):
                        attachment_data = {
                            "id": str(a.id),
                            "filename": a.filename,
                            "url": a.url,
                            "size": a.size,
                            "content_type": a.content_type,
                            "height": getattr(a, 'height', None),
                            "width": getattr(a, 'width', None)
                        }
                        return json.dumps(attachment_data)
                
                return "[JSON Attachment Error: Attachment not found]"
            except Exception as e:
                return f"[JSON Attachment Error: {str(e)}]"
        
        @self.formatter.register('attach')
        async def _attach(ctx, args_str, **kwargs):
            """
            ### {attach:optional_url}
                * Attaches media to the message from URL or message attachment.
                * Works with any media type. (images, videos, audio, etc.)
                * Examples:
                    - `{attach:https://example.com/image.png}`
                    - `{attach}` (with file attached)
            """
            try:
                url = args_str.strip() if args_str else None
                attachments = ctx.message.attachments
                files = []


                if not url and attachments:
                    for attachment in attachments[:10]:
                        file = discord.File(
                            BytesIO(await attachment.read()),
                            filename=attachment.filename
                        )
                        files.append(file)
                    return ("", [], None, files)


                if url:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url) as resp:
                            if resp.status != 200:
                                return (f"[attach error: HTTP {resp.status}]", [], None, [])
                            
                            content_type = resp.headers.get('Content-Type', '')
                            filename = os.path.basename(urlparse(url).path)
                            

                            ext = self._get_extension(content_type, filename)
                            filename = f"{filename.split('.')[0]}.{ext}" if '.' not in filename else filename
                            

                            file_data = BytesIO(await resp.read())
                            file = discord.File(file_data, filename=filename)
                            return ("", [], None, [file])

                return ("[attach error: No URL or attachment found]", [], None, [])
            
            except Exception as e:
                return (f"[attach error: {str(e)}]", [], None, [])
            
        
        async def _get_media_url(ctx, url_arg: str, media_types: tuple):
            if url_arg:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url_arg) as resp:
                        if resp.status != 200:
                            return None
                        
                        content_type = resp.headers.get('Content-Type', '')
                        if content_type in media_types:
                            return url_arg
                

            if ctx.message.attachments:
                for attachment in ctx.message.attachments:
                    if media_types is None or attachment.content_type in media_types:
                        return attachment.url
                        
            return None

        @self.formatter.register('image')
        async def _image(ctx, url: str = None, **kwargs):
            """
            ### {image:url}
                * Returns the provided image URL or first image attachment URL.
                * Supported types: PNG, JPG, JPEG, WEBP, GIF
                * Returns None if no match.
                * Examples:
                    - `{image:https://example.com/img.png}` -> "https://example.com/img.png"
                    - `{image}` (with image attachment) -> attachment URL
                    - `{image}` (no attachment) -> None
            """
            return await _get_media_url(ctx, url, media_types=IMAGE_TYPES)

        @self.formatter.register('video')
        async def _video(ctx, url: str = None, **kwargs):
            """
            ### {video:url}
                * Returns the provided video URL or first video attachment URL.
                * Supported types: MP4, WEBM, MOV, MKV, AVI, WMV
                * Returns None if no match.
                * Examples:
                    - `{video:https://example.com/vid.mp4}` -> "https://example.com/vid.mp4"
                    - `{video}` (with video attachment) -> attachment URL
            """
            return await _get_media_url(ctx, url, media_types=VIDEO_TYPES)

        @self.formatter.register('iv')
        async def _iv(ctx, url: str = None, **kwargs):
            """
            ### {iv:url}
                * Returns the provided image/video URL or first matching attachment URL.
                * Returns None if no match.
                * Examples:
                    - `{iv:https://example.com/media.gif}` -> URL
                    - `{iv}` (with image/video attachment) -> attachment URL
            """
            return await _get_media_url(ctx, url, media_types=IMAGE_TYPES+VIDEO_TYPES)

        @self.formatter.register('audio')
        async def _audio(ctx, url: str = None, **kwargs):
            """
            ### {audio:url}
                * Returns the provided audio URL or first audio attachment URL.
                * Supported types: MP3, WAV, OGG, OPUS, FLAC, M4A, MKA, WMA
                * Returns None if no match.
                * Examples:
                    - `{audio:https://example.com/sound.mp3}` -> URL
                    - `{audio}` (with audio attachment) -> attachment URL
            """
            return await _get_media_url(ctx, url, media_types=AUDIO_TYPES)

        @self.formatter.register('av')
        async def _av(ctx, url: str = None, **kwargs):
            """
            ### {av:url}
                * Returns the provided audio/video URL or first matching attachment URL.
                * Returns None if no match.
                * Examples:
                    - `{av:https://example.com/media.mp4}` -> URL
                    - `{av}` (with audio/video attachment) -> attachment URL
            """
            return await _get_media_url(ctx, url, media_types=AUDIO_TYPES+VIDEO_TYPES)

        @self.formatter.register('media')
        async def _media(ctx, url: str = None, **kwargs):
            """
            ### {media:url}
                * Returns the provided URL or first attachment URL. (any type)
                * Returns None if no match.
                * Examples:
                    - `{media:https://example.com/video.mp4}` -> URL
                    - `{media}` (with any attachment) -> attachment URL
            """
            return await _get_media_url(ctx, url, media_types=AUDIO_TYPES+VIDEO_TYPES+IMAGE_TYPES)
        
    def _get_extension(self, content_type: str, filename: str = None) -> str:
        if content_type:
            type_to_ext = {
                'image/png': 'png',
                'image/jpeg': 'jpg',
                'image/jpg': 'jpg',
                'image/webp': 'webp',
                'image/gif': 'gif',
                'video/mp4': 'mp4',
                'video/webm': 'webm',
                'video/quicktime': 'mov',
                'video/x-matroska': 'mkv',
                'video/x-msvideo': 'avi',
                'video/x-ms-wmv': 'wmv',
                'audio/mpeg': 'mp3',
                'audio/mp4': 'm4a',
                'audio/wav': 'wav',
                'audio/ogg': 'ogg',
                'audio/opus': 'opus',
                'audio/flac': 'flac',
                'audio/x-matroska': 'mka',
                'audio/x-ms-wma': 'wma'
            }
            for mime, ext in type_to_ext.items():
                if mime in content_type.lower():
                    return ext
        

            if '.' in filename:
                return filename.split('.')[-1].lower()
        

            return '.tmp'

    
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

    async def process_tags(self, ctx: commands.Context, content: str, args: str = "") -> tuple[str, list, discord.ui.View]:
        return await self.formatter.format(content, ctx, args=args)
    
    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.id in self._variables:
            del self._variables[message.id]
    
    def cog_unload(self):
        asyncio.create_task(self.processor.cleanup())
    
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return

        try:

            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)

            custom_id = interaction.data.get("custom_id")
            component_type = interaction.data.get("component_type")

            if component_type == 2:
                await self.handle_button(interaction, custom_id)

            elif component_type == 3:
                values = interaction.data.get("values", [])
                if not values:
                    return await interaction.followup.send("No selection made.", ephemeral=True)
                await self.handle_select(interaction, values[0])

            else:
                await interaction.followup.send("Unknown component type.", ephemeral=True)
        
        except discord.HTTPException:
            pass

        except Exception as e:
            try:
                await interaction.followup.send(f"Interaction failed: {str(e)}", ephemeral=True)
            except:
                await interaction.channel.send(f"Interaction failed: {str(e)}")
    
    async def handle_button(self, interaction: discord.Interaction, custom_id: str):
        if not custom_id:
            return await interaction.followup.send("This button has no action configured.", ephemeral=True)


        if custom_id.startswith("cmd:"):
            await self.execute_command(interaction, custom_id[4:])
        elif custom_id.startswith("tag:"):
            await self.execute_tag(interaction, custom_id[4:])
        else:
            pass

    async def handle_select(self, interaction: discord.Interaction, selected: str):

        if selected.startswith("cmd:"):
            await self.execute_command(interaction, selected[4:])
        elif selected.startswith("tag:"):
            await self.execute_tag(interaction, selected[4:])
        else:
            pass

    async def execute_command(self, interaction: discord.Interaction, command_str: str):
        command_name, *args = command_str.split()
        command = self.bot.get_command(command_name)
        
        if not command:
            return await interaction.followup.send(
                f"Command not found: {command_name}",
                ephemeral=True
            )


        fake_message = interaction.message
        fake_message.author = interaction.user


        prefix = await self.bot.get_prefix(fake_message)
        if isinstance(prefix, list):
            prefix = prefix[0]

        fake_message.content = prefix + command_str

        ctx = await self.bot.get_context(fake_message)

        try:
            await self.bot.invoke(ctx)
        except Exception as e:
            await interaction.followup.send(
                f"Command failed: {str(e)}",
                ephemeral=True
            )


    async def execute_tag(self, interaction: discord.Interaction, tag_str: str):
        tag_name = tag_str.split(maxsplit=1)[0]

        async with self.pool.acquire() as conn:
            tag = await conn.fetchrow(
                """SELECT content FROM tags 
                WHERE name = $1 AND (guild_id = $2 OR user_id = $3)""",
                tag_name,
                interaction.guild.id if interaction.guild else None,
                interaction.user.id
            )

        if not tag:
            return await interaction.followup.send(
                f"Tag not found: {tag_name}",
                ephemeral=True
            )

        args = tag_str[len(tag_name):].strip()


        fake_message = interaction.message
        fake_message.author = interaction.user
        fake_message.content = ""

        ctx = await self.bot.get_context(fake_message)


        text, embeds, view, files = await self.formatter.format(tag['content'], ctx, args=args)

        try:
            send_kwargs = {
                "content": text[:2000] if text else None,
                "embeds": embeds[:10],
                "files": files[:10],
                "ephemeral": True
            }

            if view and getattr(view, "children", []):
                send_kwargs["view"] = view

            await interaction.followup.send(**send_kwargs)

        except Exception as e:
            await interaction.followup.send(
                f"Failed to send tag result: {str(e)}",
                ephemeral=True
            )
    
    def parse_personal_flag(self, content: str) -> tuple[str, bool]:
        personal = False
        if "--personal" in content.lower():
            personal = True
            content = content.replace("--personal", "").strip()
        return content, personal
    
    @app_commands.autocomplete()
    async def tag_name_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str
    ) -> List[app_commands.Choice[str]]:
        cog = interaction.client.get_cog("Tags")
        if not cog:
            return []
            
        async with cog.pool.acquire() as conn:
            if interaction.namespace.personal:
                query = """
                    SELECT name AS tag_name, NULL AS alias FROM tags
                    WHERE user_id = $1 AND name ILIKE $2
                    
                    UNION ALL
                    
                    SELECT alias, tag_name FROM tag_aliases
                    WHERE user_id = $1 AND alias ILIKE $2
                    """
                rows = await conn.fetch(query, interaction.user.id, f"%{current}%")
            else:
                if not interaction.guild:
                    return []
                query = """
                    SELECT name AS tag_name, NULL AS alias FROM tags 
                    WHERE guild_id = $1 AND name ILIKE $2

                    UNION ALL

                    SELECT alias, tag_name FROM tag_aliases
                    WHERE guild_id = $1 AND alias ILIKE $2
                    """
                rows = await conn.fetch(query, interaction.guild.id, f"%{current}%")
            
        choices = []
        for row in rows:
            tag_name = row["tag_name"]
            alias = row["alias"]
            if alias is None:
                display = tag_name
            else:
                display = f"{alias} ({tag_name})"
            choices.append(app_commands.Choice(name=display, value=alias or tag_name))
            
        return choices[:25]

    
    @commands.hybrid_group(name="tag", description="Tag management commands.", invoke_without_command=True, with_app_command=True, aliases=["t"])
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def tag(self, ctx: commands.Context, name: str, *, args: str = ""):
        await ctx.typing()
        name, forced_personal = self.parse_personal_flag(name)
        name = name.lower()
        
        async with self.pool.acquire() as conn:
            if not forced_personal:
                tag = await conn.fetchrow(
                    """SELECT content, uses FROM tags
                    WHERE name = $1 AND user_id = $2""",
                    name, ctx.author.id
                )
                

                if not tag and ctx.guild:
                    tag = await conn.fetchrow(
                        """SELECT content, uses FROM tags
                        WHERE name = $1 AND guild_id = $2""",
                        name, ctx.guild.id
                    )
            else:
                tag = await conn.fetchrow(
                    """SELECT content, uses FROM tags
                    WHERE name = $1 AND (($2 AND user_id = $3) OR (NOT $2 AND guild_id = $4))""",
                    name, forced_personal, ctx.author.id, ctx.guild.id if ctx.guild else None
                )


            if not tag:
                alias = await conn.fetchrow(
                    """SELECT tag_name FROM tag_aliases
                    WHERE alias = $1 AND (user_id = $2 OR guild_id = $3)""",
                    name, ctx.author.id, ctx.guild.id if ctx.guild else None
                )
                if alias:
                    tag = await conn.fetchrow(
                        """SELECT content, uses FROM tags
                        WHERE name = $1 AND (user_id = $2 OR guild_id = $3)""",
                        alias['tag_name'], ctx.author.id, ctx.guild.id if ctx.guild else None
                    )
                    if tag:
                        name = alias['tag_name']
            
            if not tag:
                return await ctx.send(f"Tag or alias `{name}` not found.")
            

            await conn.execute(
                """UPDATE tags SET uses = uses + 1
                WHERE name = $1 AND (user_id = $2 OR guild_id = $3)""",
                name, ctx.author.id, ctx.guild.id if ctx.guild else None
            )
            
            text, embeds, view, files = await self.formatter.format(tag['content'], ctx, args=args)
            if text.strip() or embeds or (view and view.children) or files:
                try:
                    await ctx.send(
                        content=text[:2000] if text else None,
                        embeds=embeds[:10],
                        view=view if view and view.children else None,
                        files=files[:10]
                    )
                except discord.HTTPException as e:
                    await ctx.send(f"Failed to send tag: {e}")
    
    @tag.command(name="show", description="Show a tag.", with_app_command=True, aliases=["fetch"])
    @app_commands.describe(name="The tag name.", args="The tag arguments, if any.", personal="Whether to show a personal tag.")
    async def show(self, ctx: commands.Context, name: str, *, args: str = "", personal: bool = False):
        await ctx.typing()
        name, content_personal = self.parse_personal_flag(name)
        personal = personal or content_personal
        name = name.lower()
        
        async with self.pool.acquire() as conn:
            if not personal:
                tag = await conn.fetchrow(
                    """SELECT content, uses FROM tags
                    WHERE name = $1 AND user_id = $2""",
                    name, ctx.author.id
                )
                if not tag and ctx.guild:
                    tag = await conn.fetchrow(
                        """SELECT content, uses FROM tags
                        WHERE name = $1 AND guild_id = $2""",
                        name, ctx.guild.id
                    )
            else:
                tag = await conn.fetchrow(
                    """SELECT content, uses FROM tags
                    WHERE name = $1 AND user_id = $2""",
                    name, ctx.author.id
                )


            if not tag and not personal:
                alias = await conn.fetchrow(
                    """SELECT tag_name FROM tag_aliases
                    WHERE alias = $1 AND (guild_id = $2 OR user_id = $3)""",
                    name, ctx.guild.id if ctx.guild else None, ctx.author.id
                )
                if alias:
                    tag = await conn.fetchrow(
                        """SELECT content, uses FROM tags
                        WHERE name = $1 AND (guild_id = $2 OR user_id = $3)""",
                        alias['tag_name'], ctx.guild.id if ctx.guild else None, ctx.author.id
                    )
                    if tag:
                        name = alias['tag_name']
            
            if not tag:
                return await ctx.send(f"Tag or alias `{name}` not found.")
            
            await conn.execute(
                """UPDATE tags SET uses = uses + 1
                WHERE name = $1 AND (($2 AND user_id = $3) OR (NOT $2 AND guild_id = $4))""",
                name, personal, ctx.author.id, ctx.guild.id if ctx.guild else None
            )
            

            text, embeds, view, files = await self.formatter.format(tag['content'], ctx, args=args)
            if text.strip() or embeds or (view and view.children) or files:
                try:
                    await ctx.send(
                        content=text[:2000] if text else None,
                        embeds=embeds[:10],
                        view=view if view and view.children else None,
                        files=files[:10]
                    )
                except discord.HTTPException as e:
                    await ctx.send(f"Failed to send tag: {e}")
    
    @show.autocomplete("name")
    async def autocomplete_tag_show_name(
        self,
        interaction: discord.Interaction,
        current: str
    ):
        return await self.tag_name_autocomplete(interaction, current)
    
    @tag.command(name="create", description="Create a tag.", with_app_command=True, aliases=["add"])
    @app_commands.describe(
        name="The tag name.", 
        content="The tag content.", 
        personal="Make this a personal tag."
    )
    async def create(self, ctx: commands.Context, name: str, *, content: str, personal: bool = False):
        await ctx.typing()
        if content is None:
            return await ctx.send("Please provide both a name and content for the tag.")
        
        content, content_personal = self.parse_personal_flag(content)
        personal = personal or content_personal
        
        name = name.lower()
        if len(name) > 50:
            return await ctx.send("Tag names must be 50 characters or less.")
        if len(content) > 2000:
            return await ctx.send("Tag content must be 2000 characters or less.")
        
        try:
            async with self.pool.acquire() as conn:
                if personal:
                    await conn.execute(
                        """INSERT INTO tags (user_id, name, content, author_id)
                        VALUES ($1, $2, $3, $4)""",
                        ctx.author.id, name, content, ctx.author.id
                    )
                    await ctx.send(f"Created personal tag `{name}`")
                else:
                    if not ctx.guild:
                        return await ctx.send("Server tags can only be created in servers.")
                    await conn.execute(
                        """INSERT INTO tags (guild_id, name, content, author_id)
                        VALUES ($1, $2, $3, $4)""",
                        ctx.guild.id, name, content, ctx.author.id
                    )
                    await ctx.send(f"Created server tag `{name}`")
        except asyncpg.UniqueViolationError:
            await ctx.send(f"A tag named `{name}` already exists in this context.")
    
    @tag.command(name="edit", description="Edit an existing tag.", with_app_command=True, aliases=["update"])
    @app_commands.describe(
        name="The tag name.",
        new_content="The new content for the tag.",
        personal="Whether this is a personal tag."
    )
    async def edit(self, ctx: commands.Context, name: str, *, new_content: str = None, personal: bool = False):
        await ctx.typing()
        name = name.lower()
        

        if new_content is not None:
            new_content, content_personal = self.parse_personal_flag(new_content)
            personal = personal or content_personal
        
        if not new_content:
            return await ctx.send("Please provide the new content for the tag.")
        
        async with self.pool.acquire() as conn:
            if personal:
                updated = await conn.execute(
                    """UPDATE tags SET content = $1 
                    WHERE name = $2 AND user_id = $3""",
                    new_content, name, ctx.author.id
                )
                if updated != "UPDATE 0":
                    return await ctx.send(f"Edited personal tag `{name}`")
            else:
                if not ctx.guild:
                    return await ctx.send("Server tags can only be edited in servers.")
                

                updated = await conn.execute(
                    """UPDATE tags SET content = $1 
                    WHERE name = $2 AND guild_id = $3 AND author_id = $4""",
                    new_content, name, ctx.guild.id, ctx.author.id
                )
                if updated != "UPDATE 0":
                    return await ctx.send(f"Edited server tag `{name}`")


                if ctx.author.guild_permissions.manage_messages:
                    updated = await conn.execute(
                        """UPDATE tags SET content = $1 
                        WHERE name = $2 AND guild_id = $3""",
                        new_content, name, ctx.guild.id
                    )
                    if updated != "UPDATE 0":
                        return await ctx.send(f"Forcefully edited server tag `{name}`")

            await ctx.send(f"No editable tag named `{name}` found.")
    
    @edit.autocomplete("name")
    async def autocomplete_tag_edit_name(
        self,
        interaction: discord.Interaction,
        current: str
    ):
        return await self.tag_name_autocomplete(interaction, current)
    
    @tag.command(name="rename", description="Rename a tag.", with_app_command=True)
    @app_commands.describe(
        old_name="The current tag name.",
        new_name="The new name for the tag.",
        personal="Whether this is a personal tag."
    )
    async def rename(self, ctx: commands.Context, old_name: str, new_name: str, personal: bool = False):
        await ctx.typing()
        old_name = old_name.lower()
        new_name = new_name.lower()
        
        if len(new_name) > 50:
            return await ctx.send("Tag names must be 50 characters or less.")
        
        if old_name == new_name:
            return await ctx.send("The new name must be different from the old name.")

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                exists = await conn.fetchrow(
                    """SELECT 1 FROM tags 
                    WHERE name = $1 AND (($2 AND user_id = $3) OR (NOT $2 AND guild_id = $4))""",
                    new_name, personal, ctx.author.id, ctx.guild.id if ctx.guild else None
                )
                if exists:
                    return await ctx.send(f"A tag named `{new_name}` already exists in this context.")


                tag = await conn.fetchrow(
                    """SELECT 1 FROM tags 
                    WHERE name = $1 AND (($2 AND user_id = $3) OR (NOT $2 AND guild_id = $4 AND author_id = $5))""",
                    old_name, personal, ctx.author.id, ctx.guild.id if ctx.guild else None, ctx.author.id
                )
                
                if not tag and ctx.author.guild_permissions.manage_messages and not personal:
                    tag = await conn.fetchrow(
                        """SELECT 1 FROM tags 
                        WHERE name = $1 AND guild_id = $2""",
                        old_name, ctx.guild.id
                    )

                if not tag:
                    scope = "personal" if personal else "server"
                    return await ctx.send(f"No {scope} tag named `{old_name}` found that you can rename.")


                if personal:
                    await conn.execute(
                        """UPDATE tags SET name = $1 
                        WHERE name = $2 AND user_id = $3""",
                        new_name, old_name, ctx.author.id
                    )
                else:
                    await conn.execute(
                        """UPDATE tags SET name = $1 
                        WHERE name = $2 AND guild_id = $3""",
                        new_name, old_name, ctx.guild.id
                    )


                await conn.execute(
                    """UPDATE tag_aliases SET tag_name = $1
                    WHERE tag_name = $2 AND (
                        ($3 AND user_id = $4) OR
                        (NOT $3 AND guild_id = $5)
                    )""",
                    new_name, old_name, personal, ctx.author.id, ctx.guild.id if ctx.guild else None
                )

        await ctx.send(f"Renamed tag from `{old_name}` to `{new_name}`")
    
    @rename.autocomplete("old_name")
    async def autocomplete_tag_rename_name(
        self,
        interaction: discord.Interaction,
        current: str
    ):
        return await self.tag_name_autocomplete(interaction, current)
    
    @tag.command(name="remove", description="Remove a tag.", with_app_command=True, aliases=["rm", "delete", "del"])
    @app_commands.describe(
        name="The tag name.",
        personal="Whether this is a personal tag."
    )
    async def remove(self, ctx: commands.Context, *, name: str, personal: bool = False):
        await ctx.typing()
        name, content_personal = self.parse_personal_flag(name)
        personal = personal or content_personal
        name = name.lower()
        
        async with self.pool.acquire() as conn:
            if personal:
                deleted = await conn.execute(
                    "DELETE FROM tags WHERE name = $1 AND user_id = $2",
                    name, ctx.author.id
                )
                if deleted != "DELETE 0":
                    return await ctx.send(f"Removed personal tag `{name}`")
            else:
                if not ctx.guild:
                    return await ctx.send("Server tags can only be removed in servers.")
                

                deleted = await conn.execute(
                    """DELETE FROM tags 
                    WHERE name = $1 AND guild_id = $2 AND author_id = $3""",
                    name, ctx.guild.id, ctx.author.id
                )
                if deleted != "DELETE 0":
                    return await ctx.send(f"Removed server tag `{name}`")


                if ctx.author.guild_permissions.manage_messages:
                    deleted = await conn.execute(
                        "DELETE FROM tags WHERE name = $1 AND guild_id = $2",
                        name, ctx.guild.id
                    )
                    if deleted != "DELETE 0":
                        return await ctx.send(f"Forcefully removed server tag `{name}`")

            await ctx.send(f"No removeable tag `{name}` found.")
    
    @remove.autocomplete("name")
    async def autocomplete_tag_remove_name(
        self,
        interaction: discord.Interaction,
        current: str
    ):
        return await self.tag_name_autocomplete(interaction, current)
    
    @tag.command(name="list", description="List available tags.", with_app_command=True, aliases=["ls"])
    @app_commands.describe(user="Filter tags by this user.", personal="Only show your personal tags.")
    async def list(self, ctx: commands.Context, user: discord.User = None, personal: bool = False):
        await ctx.typing()
        async with self.pool.acquire() as conn:
            target_user = user or ctx.author
            if personal:
                if target_user.id != ctx.author.id:
                    return await ctx.send("You can only view your own personal tags.")
                tags = await conn.fetch(
                    "SELECT name FROM tags WHERE user_id = $1 ORDER BY name",
                    target_user.id
                )
                title = "Your personal tags"
            else:
                if not ctx.guild:
                    return await ctx.send("Server tags can only be listed in servers.")
                if user is None:
                    tags = await conn.fetch(
                        "SELECT name FROM tags WHERE guild_id IS NOT DISTINCT FROM $1 ORDER BY name",
                        ctx.guild.id
                    )
                else:
                    tags = await conn.fetch(
                        "SELECT name FROM tags WHERE guild_id IS NOT DISTINCT FROM $1 AND author_id IS NOT DISTINCT FROM $2 ORDER BY name",
                        ctx.guild.id, target_user.id
                    )
                if user:
                    title = f"Tags created by {target_user} in {ctx.guild.name}"
                else:
                    title = f"Server tags in {ctx.guild.name}"

            if not tags:
                return await ctx.send(f"No {'personal' if personal else 'server'} tags found.")
            
            per_page = 10
            pages = []
            for i in range(0, len(tags), per_page):
                embed = discord.Embed(title=title, color=discord.Color.blue())
                for idx, tag in enumerate(tags[i:i+per_page], start=i + 1):
                    embed.add_field(name=f"{idx}.", value=tag['name'], inline=False)
                embed.set_footer(text=f"Page {i//per_page + 1} of {(len(tags)-1)//per_page + 1}")
                pages.append(embed)
            
            view = TagPaginator(pages, ctx.interaction, ctx.author)
            view.message = await ctx.send(embed=pages[0], view=view)
    
    @tag.command(name="info", description="Get information about a tag.", with_app_command=True)
    @app_commands.describe(
        name="The tag name.",
        personal="Whether to look for a personal tag."
    )
    async def info(self, ctx: commands.Context, *, name: str, personal: bool = False):
        await ctx.typing()
        name, content_personal = self.parse_personal_flag(name)
        personal = personal or content_personal
        name = name.lower()
        
        async with self.pool.acquire() as conn:
            tag = await conn.fetchrow(
                """SELECT content, author_id, created_at, uses,
                guild_id IS NOT NULL as is_guild_tag
                FROM tags
                WHERE name = $1 AND (($2 AND user_id = $3) OR (NOT $2 AND guild_id = $4))""",
                name, personal, ctx.author.id, ctx.guild.id if ctx.guild else None
            )

            if not tag:
                return await ctx.send(f"Tag `{name}` not found.")
            
            embed = discord.Embed(title=f"Tag: {name}", color=discord.Color.blue())
            embed.add_field(name="Type", value="Server" if tag['is_guild_tag'] else "Personal", inline=True)
            embed.add_field(name="Uses", value=tag['uses'], inline=True)
            embed.add_field(name="Created", value=tag['created_at'].strftime("%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)"), inline=True)
            author = self.bot.get_user(tag['author_id'])
            if author:
                embed.set_author(name=f"Owned by {author}", icon_url=author.display_avatar.url, url=f"https://discord.com/users/{author.id}")
            
            await ctx.send(embed=embed)
    
    @info.autocomplete("name")
    async def autocomplete_tag_info_name(
        self,
        interaction: discord.Interaction,
        current: str
    ):
        return await self.tag_name_autocomplete(interaction, current)
    
    @tag.command(name="raw", description="Get the raw content of a tag.", with_app_command=True)
    @app_commands.describe(
        name="The tag name.",
        personal="Whether to look for a personal tag."
    )
    async def raw(self, ctx: commands.Context, *, name: str, personal: bool = False):
        await ctx.typing()
        name, content_personal = self.parse_personal_flag(name)
        personal = personal or content_personal
        name = name.lower()
        
        async with self.pool.acquire() as conn:
            tag = await conn.fetchrow(
                """SELECT content FROM tags 
                WHERE name = $1 AND (($2 AND user_id = $3) OR (NOT $2 AND guild_id = $4))""",
                name, personal, ctx.author.id, ctx.guild.id if ctx.guild else None
            )

            if not tag:
                return await ctx.send(f"Tag `{name}` not found.")
            
            await ctx.send(f"```\n{tag['content']}```")
    
    @raw.autocomplete("name")
    async def autocomplete_tag_raw_name(
        self,
        interaction: discord.Interaction,
        current: str
    ):
        return await self.tag_name_autocomplete(interaction, current)
    
    @tag.command(name="transfer", description="Transfer ownership of a tag (server or personal).", with_app_command=True, aliases=["gift"])
    @app_commands.describe(name="The tag name.", new_owner="The user to transfer to.", personal="Whether this is a personal tag.")
    async def transfer(self, ctx: commands.Context, name: str, new_owner: discord.User, personal: bool = False):
        await ctx.typing()
        name = name.lower()
        name, flag_from_name = self.parse_personal_flag(name)
        personal = personal or flag_from_name

        async with self.pool.acquire() as conn:
            tag = await conn.fetchrow("""
                SELECT user_id, guild_id, author_id FROM tags
                WHERE name = $1 AND (($2 AND user_id = $3) OR (NOT $2 AND guild_id IS NOT DISTINCT FROM $4))
            """, name, personal, ctx.author.id, ctx.guild.id if ctx.guild else None)

            if not tag:
                return await ctx.send(f"No {'personal' if personal else 'server'} tag named `{name}` found that you own.")

            if not personal:
                if not ctx.guild:
                    return await ctx.send("Server tags can only be transferred in servers.")
                if ctx.author.id != tag['author_id']:
                    return await ctx.send("You don't have permission to transfer this server tag.")

            if personal:
                result = await conn.execute("""
                        UPDATE tags SET user_id = $1
                        WHERE name = $2 AND user_id = $3
                    """, new_owner.id, name, ctx.author.id)
            else:
                result = await conn.execute("""
                        UPDATE tags SET author_id = $1
                        WHERE name = $2 AND guild_id = $3
                    """, new_owner.id, name, ctx.guild.id)
            
            if result == "UPDATE 0":
                return await ctx.send("Failed to transfer tag; no matching tag found.")
            
            await conn.execute("UPDATE tag_aliases SET user_id = $1 WHERE tag_name = $2 AND guild_id = $3", new_owner.id, name, ctx.guild.id)

            await ctx.send(f"Transferred {'personal' if personal else 'server'} tag `{name}` to {new_owner.mention}")
    
    @tag.command(name="search", description="Search for tags by name or content.", with_app_command=True)
    @app_commands.describe(query="The search term.", personal="Whether to search only your personal tags.")
    async def search(self, ctx: commands.Context, *, query: str, personal: bool = False):
        await ctx.typing()
        query, flag_from_query = self.parse_personal_flag(query)
        personal = personal or flag_from_query
        async with self.pool.acquire() as conn:
            if personal:
                rows = await conn.fetch("""
                    SELECT name, content FROM tags 
                    WHERE user_id = $1 AND (name ILIKE '%' || $2 || '%' OR content ILIKE '%' || $2 || '%')""",
                    ctx.author.id, query)
            else:
                if not ctx.guild:
                    return await ctx.send("Server tags can only be searched in servers.")
                rows = await conn.fetch("""
                    SELECT name, content FROM tags 
                    WHERE guild_id = $1 AND (name ILIKE '%' || $2 || '%' OR content ILIKE '%' || $2 || '%')""",
                    ctx.guild.id, query)

            if not rows:
                return await ctx.send("No tags found matching your query.")

            per_page = 5
            pages = []
            for i in range(0, len(rows), per_page):
                embed = discord.Embed(title=f"Tag Search Results {'(Personal)' if personal else ''}", color=discord.Color.orange())
                for row in rows[i:i+per_page]:
                    embed.add_field(name=row['name'], value=row['content'][:100], inline=False)
                embed.set_footer(text=f"Page {i//per_page + 1} of {(len(rows)-1)//per_page + 1}")
                pages.append(embed)

            view = TagPaginator(pages, ctx.interaction, ctx.author)
            view.message = await ctx.send(embed=pages[0], view=view)
    
    @tag.command(name="random", description="Show a random tag.", with_app_command=True)
    @app_commands.describe(args="Arguments and flags. (e.g. --personal, --user @User, --hide-name)", personal="Whether to fetch from personal tags.")
    async def random(self, ctx: commands.Context, *, args: str = "", personal: bool = False):
        await ctx.typing()
        hide_name = False
        user_str = None
        user = None
        parts = args.split()
        rest = []

        i = 0
        while i < len(parts):
            part = parts[i].lower()
            if part == "--hide-name":
                hide_name = True
            elif part == "--user" and i + 1 < len(parts):
                i += 1
                user_str = parts[i]
            else:
                rest.append(parts[i])
            i += 1
        new_args = ' '.join(rest)
        if user_str:
            try:
                user = await commands.UserConverter().convert(ctx, user_str)
            except commands.BadArgument:
                pass
        target_user = user or ctx.author
        new_args, flag_from_args = self.parse_personal_flag(new_args)
        personal = personal or flag_from_args
        async with self.pool.acquire() as conn:
            if personal:
                if target_user.id != ctx.author.id:
                    return await ctx.send("You can only use your own personal tags for random selection.")
                rows = await conn.fetch("SELECT name FROM tags WHERE user_id = $1", target_user.id)
            else:
                if not ctx.guild:
                    return await ctx.send("Cannot fetch server tags outside a server.")
                if user is None:
                    rows = await conn.fetch("SELECT name FROM tags WHERE guild_id IS NOT DISTINCT FROM $1", ctx.guild.id)
                else:
                    rows = await conn.fetch("SELECT name from tags WHERE guild_id IS NOT DISTINCT FROM $1 AND author_id IS NOT DISTINCT FROM $2", ctx.guild.id, target_user.id)

            if not rows:
                return await ctx.send("No tags found.")

            tag_name = random.choice(rows)['name']
            tag = await conn.fetchrow("""
                SELECT content FROM tags
                WHERE name = $1 AND (($2 AND user_id = $3) OR (NOT $2 AND guild_id IS NOT DISTINCT FROM $4))
            """, tag_name, personal, target_user.id, ctx.guild.id if ctx.guild else None)

            if not tag:
                return await ctx.send("Failed to fetch tag content.")
            
            await conn.execute("""
                UPDATE tags SET uses = uses + 1
                WHERE name = $1 AND (($2 AND user_id = $3) OR (NOT $2 AND guild_id IS NOT DISTINCT FROM $4))
            """, tag_name, personal, target_user.id, ctx.guild.id if ctx.guild else None)

            text, embeds, view, files = await self.formatter.format(tag['content'], ctx, args=new_args)
            if not hide_name:
                header = f"Showing tag: `{tag_name}`\n\n"
                if text:
                    text = header + text
                else:
                    text = header

            try:
                await ctx.send(
                    content=text[:2000],
                    embeds=embeds[:10],
                    view=view,
                    files=files[:10]
                )
            except discord.HTTPException as e:
                await ctx.send(f"Failed to send tag: {e}")
    
    @tag.group(name="alias", description="Manage tag aliases.", with_app_command=True)
    async def alias(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.send("Available commands: `add`, `remove`, `list`")

    @alias.command(name="add", description="Add an alias to a tag.")
    @app_commands.describe(
        tag_name="The original tag name",
        alias="The new alias",
        personal="Whether this is for a personal tag"
    )
    async def alias_add(self, ctx: commands.Context, tag_name: str, alias: str, personal: bool = False):
        await ctx.typing()
        tag_name = tag_name.lower().strip()
        alias = alias.lower().strip()
        if len(alias) > 50:
            return await ctx.send("Aliases must be 50 characters or less.")

        async with self.pool.acquire() as conn:
            if personal:
                tag = await conn.fetchrow("""
                    SELECT user_id FROM tags WHERE name = $1 AND user_id = $2
                """, tag_name, ctx.author.id)
            else:
                if not ctx.guild:
                    return await ctx.send("Server tags can only be managed in servers.")
                tag = await conn.fetchrow("""
                    SELECT user_id FROM tags WHERE name = $1 AND guild_id = $2
                """, tag_name, ctx.guild.id)

            if not tag:
                return await ctx.send(f"No such {'personal' if personal else 'server'} tag exists.")

            tag_author_id = tag['user_id']

            if ctx.author.id != tag_author_id:
                return await ctx.send("You can only add aliases to tags you own.")

            try:
                if personal:
                    await conn.execute("""
                        INSERT INTO tag_aliases (alias, tag_name, user_id)
                        VALUES ($1, $2, $3)
                    """, alias, tag_name, ctx.author.id)
                else:
                    await conn.execute("""
                        INSERT INTO tag_aliases (alias, tag_name, guild_id)
                        VALUES ($1, $2, $3)
                    """, alias, tag_name, ctx.guild.id)
                await ctx.send(f"Added alias `{alias}` for tag `{tag_name}`")
            except asyncpg.UniqueViolationError:
                await ctx.send("This alias already exists for another tag.")

    @alias.command(name="remove", description="Remove a tag alias.", aliases=["delete", "rm", "del"])
    @app_commands.describe(
        alias="The alias to remove",
        personal="Whether this is a personal tag alias"
    )
    async def alias_remove(self, ctx: commands.Context, alias: str, personal: bool = False):
        await ctx.typing()
        alias = alias.lower().strip()

        async with self.pool.acquire() as conn:
            if personal:
                row = await conn.fetchrow("""
                    SELECT tag_name FROM tag_aliases WHERE alias = $1 AND user_id = $2
                """, alias, ctx.author.id)
                if not row:
                    return await ctx.send("No personal alias found with that name.")
                tag_name = row['tag_name']
                tag = await conn.fetchrow("""
                    SELECT user_id FROM tags WHERE name = $1 AND user_id = $2
                """, tag_name, ctx.author.id)
            else:
                if not ctx.guild:
                    return await ctx.send("Server tags can only be managed in servers.")
                row = await conn.fetchrow("""
                    SELECT tag_name FROM tag_aliases WHERE alias = $1 AND guild_id = $2
                """, alias, ctx.guild.id)
                if not row:
                    return await ctx.send("No server alias found with that name.")
                tag_name = row['tag_name']
                tag = await conn.fetchrow("""
                    SELECT user_id FROM tags WHERE name = $1 AND guild_id = $2
                """, tag_name, ctx.guild.id)

            if not tag:
                return await ctx.send("Tag no longer exists.")

            tag_author_id = tag['user_id']
            if ctx.author.id != tag_author_id:
                return await ctx.send("You can only remove aliases from tags you own.")

            if personal:
                await conn.execute("""
                    DELETE FROM tag_aliases WHERE alias = $1 AND user_id = $2
                """, alias, ctx.author.id)
            else:
                await conn.execute("""
                    DELETE FROM tag_aliases WHERE alias = $1 AND guild_id = $2
                """, alias, ctx.guild.id)

            await ctx.send(f"Removed alias `{alias}`")

    @alias.command(name="list", description="List tag aliases.", aliases=["ls"])
    @app_commands.describe(personal="Whether to list personal tag aliases")
    async def alias_list(self, ctx: commands.Context, personal: bool = False):
        await ctx.typing()
        
        if not ctx.guild and not personal:
            return await ctx.send("Server tags can only be listed in servers.")

        async with self.pool.acquire() as conn:
            try:
                if personal:
                    aliases = await conn.fetch(
                        """SELECT alias, tag_name FROM tag_aliases 
                        WHERE user_id = $1 ORDER BY alias""",
                        ctx.author.id
                    )
                    title = "Your personal tag aliases"
                else:
                    aliases = await conn.fetch(
                        """SELECT alias, tag_name FROM tag_aliases 
                        WHERE guild_id = $1 ORDER BY alias""",
                        ctx.guild.id
                    )
                    title = f"Tag aliases in {ctx.guild.name}"

                if not aliases:
                    scope_type = "personal" if personal else "server"
                    return await ctx.send(f"No {scope_type} tag aliases found.")
                
                per_page = 10
                pages = []
                for i in range(0, len(aliases), per_page):
                    embed = discord.Embed(title=f"{title}", color=discord.Color.blue())
                    current_aliases = aliases[i:i+per_page]
                    description = "\n".join(f"- `{a['alias']}` -> `{a['tag_name']}`" for a in current_aliases)
                    embed.description = description
                    embed.set_footer(text=f"Page {i//per_page + 1} of {(len(aliases)-1)//per_page + 1}")
                    pages.append(embed)

                view = TagPaginator(pages, ctx.interaction, ctx.author)
                view.message = await ctx.send(embed=pages[0], view=view)
                
            except Exception as e:
                await ctx.send(f"An error occurred: {str(e)}")

async def setup(bot):
    if not hasattr(bot, 'pool'):
        bot.pool = await asyncpg.create_pool(bot_info.data['database'])
    await bot.add_cog(Tags(bot))