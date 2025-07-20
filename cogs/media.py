import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
import os
import mimetypes
from urllib.parse import urlparse
import re
from pathlib import Path

class Media(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.tags_cog = bot.get_cog('Tags')
    
    async def process_media_input(self, ctx: commands.Context, input_value: str = None, attachment: discord.Attachment = None):
        if not input_value and not attachment:
            return None, None, "No input provided."
        
        if attachment:
            input_key = f"media://{attachment.url}"
            filename = attachment.filename
            file_ext = os.path.splitext(filename)[1][1:]
            return input_key, file_ext, None
        
        if input_value.startswith(('http://', 'https://')):
            input_key = f"media://{input_value}"
            parsed_url = urlparse(input_value)
            path = parsed_url.path
            file_ext = os.path.splitext(path)[1][1:]

            if not file_ext:
                try:
                    response = await self.bot.session.head(input_value)
                    content_type = response.headers.get('Content-Type')
                    if content_type:
                        file_ext = mimetypes.guess_extension(content_type.split(';')[0])[1:]
                except:
                    pass
            
            return input_key, file_ext, None
        
        emoji_match = re.match(r'<a?:(\w+):(\d+)>', input_value)
        if emoji_match:
            emoji_id = emoji_match.group(2)
            ext = 'gif' if input_value.startswith('<a:') else 'png'
            url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}"
            input_key = f"media://{url}"
            return input_key, ext, None
        
        try:
            user = await commands.UserConverter().convert(ctx, input_value)
            avatar_url = str(user.display_avatar.url)
            parsed_url = urlparse(avatar_url)
            path = parsed_url.path
            file_ext = os.path.splitext(path)[1][1:]

            return f"media://{avatar_url}", file_ext, None
        except commands.UserNotFound:
            pass

        return None, None, "Invalid input format."
    
    async def run_gscript_command(self, ctx, command_name, input_key, output_key=None, **kwargs):
        output_key = output_key or f"{command_name}_{ctx.message.id}"

        try:
            func = self.tags_cog.processor.gscript_commands.get(command_name)
            if not func:
                raise commands.CommandError(f"Unknown command: {command_name}")

            if input_key not in self.tags_cog.processor.media_cache:
                raise commands.CommandError(f"{input_key} not found in media cache")

            result = await func(input_key=input_key, output_key=output_key, **kwargs)

            if not isinstance(result, str) or not result.startswith("media://"):
                raise commands.CommandError(f"{command_name} failed: {result}")


            render_result = await self.tags_cog.processor._render_media(
                media_key=output_key,
                extra_args=[Path(result[8:]).suffix[1:]]
            )
            if not isinstance(render_result, str) or not render_result.startswith("media://"):
                raise commands.CommandError(f"Rendering failed: {render_result}")

            output_path = Path(render_result[8:])
            if not output_path.exists():
                raise commands.CommandError(f"Output file not found at {output_path}")


            ext = output_path.suffix[1:]
            custom_name = kwargs.pop("name", None)
            final_name = f"{custom_name}.{ext}" if custom_name else f"{command_name}.{ext}"
            final_path = output_path.with_name(final_name)
            if final_path.exists():
                final_path.unlink()
            output_path.rename(final_path)

            with open(final_path, 'rb') as f:
                file = discord.File(f, filename=final_name)
                await ctx.send(file=file)

        finally:
            await self.tags_cog.processor.cleanup()
    
    @commands.hybrid_group(name="media", with_app_command=True, description="Media manipulation commands.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def media(self, ctx: commands.Context):
        return
    
    @media.group(name="image", with_app_command=True, description="Image manipulation commands.")
    async def image(self, ctx: commands.Context):
        return
    
    @media.group(name="video", with_app_command=True, description="Video manipulation commands.")
    async def video(self, ctx: commands.Context):
        return
    
    @media.group(name="audio", with_app_command=True, description="Audio manipulation commands.")
    async def audio(self, ctx: commands.Context):
        return
    
    @media.group(name="av", with_app_command=True, description="Audio/Video manipulation commands.")
    async def av(self, ctx: commands.Context):
        return
    
    @media.group(name="iv", with_app_command=True, description="Image/Video manipulation commands.")
    async def iv(self, ctx: commands.Context):
        return
    
    @media.command(name="convert", description="Convert media.")
    @app_commands.describe(url="URL/Emoji/User.", attachment="Media file.", format="The format to convert to.")
    async def convert(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None, format: str = ""):
        await ctx.typing()
        input_key = f"convert_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "convert", input_key, format=format)
    
    @media.command(name="audioputreplace", description="Replace a video/audio/image's audio with another audio.")
    @app_commands.describe(
        url="URL/Emoji/User.", 
        attachment="Media file.",
        audio_url="Audio URL.",
        audio_attachment="Audio file.",
        preserve_length="Keep original video length?",
        force_video="Force video output?",
        loop_media="Loop video if shorter than audio?"
    )
    async def audioputreplace(self, ctx: commands.Context, 
                             url: Optional[str] = None, 
                             attachment: Optional[discord.Attachment] = None,
                             audio_url: Optional[str] = None,
                             audio_attachment: Optional[discord.Attachment] = None,
                             preserve_length: bool = True,
                             force_video: bool = False,
                             loop_media: bool = False):
        await ctx.typing()
        input_key = f"media_{ctx.message.id}"
        input_parsed = await self.process_media_input(ctx, url, attachment)
        if input_parsed[2]:
            raise commands.CommandError(input_parsed[2])
        input_url = input_parsed[0][8:]
        

        audio_key = f"audio_{ctx.message.id}"
        audio_parsed = await self.process_media_input(ctx, audio_url, audio_attachment)
        if audio_parsed[2]:
            raise commands.CommandError(audio_parsed[2])
        audio_url = audio_parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.tags_cog.processor._load_media(url=audio_url, media_key=audio_key)
        
        await self.run_gscript_command(
            ctx, 
            "audioputreplace",
            input_key=input_key,
            media_key=input_key,
            audio_key=audio_key,
            preserve_length=preserve_length,
            force_video=force_video,
            loop_media=loop_media
        )
    
    @media.command(name="audioputmix", description="Mix a video/audio/image's audio with another audio.")
    @app_commands.describe(
        url="URL/Emoji/User.", 
        attachment="Media file.",
        audio_url="Audio URL.",
        audio_attachment="Audio file.",
        volume="Volume of mixed audio.",
        loop_audio="Loop audio if shorter than video?",
        preserve_length="Keep original video length?",
        loop_media="Loop video if shorter than audio?"
    )
    async def audioputmix(self, ctx: commands.Context, 
                          url: Optional[str] = None, 
                          attachment: Optional[discord.Attachment] = None,
                          audio_url: Optional[str] = None,
                          audio_attachment: Optional[discord.Attachment] = None,
                          volume: float = 1.0,
                          loop_audio: bool = False,
                          preserve_length: bool = True,
                          loop_media: bool = False):
        await ctx.typing()
        input_key = f"video_{ctx.message.id}"
        input_parsed = await self.process_media_input(ctx, url, attachment)
        if input_parsed[2]:
            raise commands.CommandError(input_parsed[2])
        input_url = input_parsed[0][8:]
        

        audio_key = f"audio_{ctx.message.id}"
        audio_parsed = await self.process_media_input(ctx, audio_url, audio_attachment)
        if audio_parsed[2]:
            raise commands.CommandError(audio_parsed[2])
        audio_url = audio_parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.tags_cog.processor._load_media(url=audio_url, media_key=audio_key)
        
        await self.run_gscript_command(
            ctx, 
            "audioputmix", 
            input_key=input_key,
            audio_key=audio_key,
            volume=volume,
            loop_audio=loop_audio,
            preserve_length=preserve_length,
            loop_media=loop_media
        )
    
    @media.command(name="trim", description="Trim a video/audio/image.")
    @app_commands.describe(
        url="URL/Emoji/User.", 
        attachment="Video/Audio/Image file.", 
        start="Start time. (seconds, timestamp, or percentage)", 
        end="End time. (seconds, timestamp, or percentage)"
    )
    async def trim(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None, start: str = "0", end: str = "10"):
        await ctx.typing()
        input_key = f"trim_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "trim", input_key, start_time=start, end_time=end)
    
    @media.command(name="speed", description="Change a video/audio/image's speed.")
    @app_commands.describe(
        url="URL/Emoji/User.", 
        attachment="Video/Audio/Image file.",
        speed="Speed multiplier. (0.5 = half speed, 2.0 = double speed)"
    )
    async def speed(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None, speed: float = 1.5):
        await ctx.typing()
        input_key = f"speed_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "speed", input_key, speed=speed)
    
    @media.command(name="reverse", description="Reverse a video/audio/image.")
    @app_commands.describe(url="URL/Emoji/User.", attachment="Video/Audio/Image file.")
    async def reverse(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None):
        await ctx.typing()
        input_key = f"reverse_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "reverse", input_key)
    
    @image.command(name="text", description="Add text to an image.")
    @app_commands.describe(url="URL/Emoji/User.", 
    attachment="Image file.", 
    text="Text to add.", 
    x="X position. (or 'center')", 
    y="Y position. (or 'center')", 
    color="Text color. (name, hex, or gradient)", 
    font_size="Font size.", 
    font="Font name.", 
    outline_color="Outline color. (name, hex, or gradient)", 
    outline_width="Outline width.", 
    shadow_color="Shadow color. (name, hex, or gradient)", 
    shadow_offset="Shadow offset.", 
    shadow_blur="Shadow blur.", 
    wrap_width="Text wrap width.", 
    line_spacing="Text line spacing amount.")
    async def text(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None, text: str = "Hello", x: str = "0", y: str = "0", color: str = "white", font_size: int = 64, font: str = "arial", outline_color: str = None, outline_width: int = None, shadow_color: str = None, shadow_offset: int = 2, shadow_blur: int = 0, wrap_width: int = None, line_spacing: int = 5):
        await ctx.typing()
        input_key = f"text_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "text", input_key, text=text, x=x, y=y, color=color, font_size=font_size, font=font, outline_color=outline_color, outline_width=outline_width, shadow_color=shadow_color, shadow_offset=shadow_offset, shadow_blur=shadow_blur, wrap_width=wrap_width, line_spacing=line_spacing)
    
    @iv.command(name="caption", description="Caption media.")
    @app_commands.describe(
        url="URL/Emoji/User.",
        attachment="Video/Image file.",
        text="Caption text.",
        font_size="Font size.",
        font="Caption font.",
        color="Caption font color. (name, hex, or gradient)",
        background_color="Caption padding color. (name, hex, or gradient)",
        padding="Padding amount.",
        outline_color="Caption font outline color. (name, hex, or gradient)",
        outline_width="Caption font outline width amount.",
        shadow_color="Caption font shadow color. (name, hex, or gradient)",
        shadow_offset="Caption font shadow offset amount.",
        shadow_blur="Caption font shadow blur amount.",
        wrap_width="Text wrap width amount.",
        line_spacing="Text line spacing amount."
    )
    async def caption(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None, text: str = None, font_size: int = 0, font: str = "Futura Condensed Extra Bold", color: str = "#000000", background_color: str = "#FFFFFF", padding: int = 0, outline_color: str = None, outline_width: int = None, shadow_color: str = None, shadow_offset: int = 2, shadow_blur: int = 0, wrap_width: int = None, line_spacing: int = 5):
        await ctx.typing()
        input_key = f"caption_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "caption", input_key, text=text, font_size=font_size, font=font, color=color, background_color=background_color, padding=padding, outline_color=outline_color, outline_width=outline_width, shadow_color=shadow_color, shadow_offset=shadow_offset, shadow_blur=shadow_blur, wrap_width=wrap_width, line_spacing=line_spacing)
    
    @iv.command(name="fps", description="Change a video or image's frame rate.")
    @app_commands.describe(
        url="URL/Emoji/User.", 
        attachment="Video/Image file.",
        fps="FPS to set."
    )
    async def fps(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None, fps: str = "30"):
        await ctx.typing()
        input_key = f"fps_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "fps", input_key, fps_value=fps)
    
    @iv.command(name="contrast", description="Adjust an image or video's contrast.")
    @app_commands.describe(url="URL/Emoji/User.", attachment="Image/Video file.", contrast_level="Contrast level.")
    async def contrast(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None, contrast_level: float = 1.0):
        await ctx.typing()
        input_key = f"contrast_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "contrast", input_key, contrast_level=contrast_level)
    
    @iv.command(name="opacity", description="Adjust an image or video's opacity.")
    @app_commands.describe(url="URL/Emoji/User.", attachment="Image/Video file.", opacity_level="Opacity level.")
    async def opacity(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None, opacity_level: float = 1.0):
        await ctx.typing()
        input_key = f"opacity_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "opacity", input_key, opacity_level=opacity_level)
    
    @iv.command(name="brightness", description="Adjust an image or video's brightness.")
    @app_commands.describe(url="URL/Emoji/User.", attachment="Image/Video file.", brightness_level="Brightness level.")
    async def brightness(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None, brightness_level: float = 0.0):
        await ctx.typing()
        input_key = f"brightness_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "brightness", input_key, brightness_level=brightness_level)
    
    @iv.command(name="gamma", description="Adjust an image or video's gamma.")
    @app_commands.describe(url="URL/Emoji/User.", attachment="Image/Video file.", gamma_level="Gamma level.")
    async def gamma(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None, gamma_level: float = 1.0):
        await ctx.typing()
        input_key = f"gamma_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "gamma", input_key, gamma_level=gamma_level)
    
    @iv.command(name="saturate", description="Adjust an image or video's saturation.")
    @app_commands.describe(url="URL/Emoji/User.", attachment="Image/Video file.", saturation_level="Saturation level.")
    async def saturate(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None, saturation_level: float = 1.0):
        await ctx.typing()
        input_key = f"saturate_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "saturate", input_key, saturation_level=saturation_level)
    
    @iv.command(name="hue", description="Adjust an image or video's hue shift.")
    @app_commands.describe(url="URL/Emoji/User.", attachment="Image/Video file.", hue_shift="Hue shift degrees. Also supports expressions from ffmpeg.")
    async def hue(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None, hue_shift: str = "90"):
        await ctx.typing()
        input_key = f"hue_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "hue", input_key, hue_shift=hue_shift)
    
    @iv.command(name="grayscale", description="Convert an image or video to grayscale.")
    @app_commands.describe(url="URL/Emoji/User.", attachment="Image/Video file.")
    async def grayscale(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None):
        await ctx.typing()
        input_key = f"grayscale_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "grayscale", input_key)
    
    @iv.command(name="sepia", description="Convert an image or video to sepia.")
    @app_commands.describe(url="URL/Emoji/User.", attachment="Image/Video file.")
    async def sepia(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None):
        await ctx.typing()
        input_key = f"sepia_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "sepia", input_key)
    
    @iv.command(name="resize", description="Resize an image or video.")
    @app_commands.describe(url="URL/Emoji/User.", attachment="Image/Video file.", width="Width in pixels or expression. (e.g., '50%', 'iw/2')", height="Height in pixels or expression. (e.g., '50%', 'ih/2')")
    async def resize(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None, width: str = "512", height: str = "512"):
        await ctx.typing()
        input_key = f"resize_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "resize", input_key, width=width, height=height)
    
    @iv.command(name="rotate", description="Rotate an image or video.")
    @app_commands.describe(url="URL/Emoji/User.", attachment="Image/Video file.", angle="Rotation angle in degrees. Supports expressions from ffmpeg.")
    async def rotate(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None, angle: str = "90"):
        await ctx.typing()
        input_key = f"rotate_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "rotate", input_key, angle=angle)
    
    @iv.command(name="crop", description="Crop an image or video.")
    @app_commands.describe(url="URL/Emoji/User.", attachment="Image/Video file.", x="X position to start crop.", y="Y position to start crop.", width="Width of crop area.", height="Height of crop area.")
    async def crop(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None, x: str = "0", y: str = "0", width: str = "512", height: str = "512"):
        await ctx.typing()
        input_key = f"crop_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "crop", input_key, x=x, y=y, width=width, height=height)
    
    @iv.command(name="invert", description="Invert the colors of a video or image.")
    @app_commands.describe(url="URL/Emoji/User.", attachment="Image/Video file.")
    async def invert(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None):
        await ctx.typing()
        input_key = f"invert_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "invert", input_key)
    
    @iv.command(name="fadein", description="Apply fade-in effect to a video or image.")
    @app_commands.describe(url="URL/Emoji/User.", attachment="Image/Video file.", duration="Duration of the fade-in, in seconds.", color="Background color or gradient.", audio="Whether to fade the audio track (if present).")
    async def fadein(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None, duration: float = 1.0, color: str = "#000000", audio: bool = True):
        await ctx.typing()
        input_key = f"fadein_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "fadein", input_key, duration=duration, color=color, audio=audio)
    
    @iv.command(name="fadeout", description="Apply fade-out effect to a video or image.")
    @app_commands.describe(
        url="URL/Emoji/User.", 
        attachment="Image/Video file.", 
        start_time="When to start fading out. (seconds)", 
        duration="Duration of the fade-out, in seconds.", 
        color="Background color or gradient.", 
        audio="Whether to fade the audio track (if present)."
    )
    async def fadeout(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None, start_time: float = 0.0, duration: float = 1.0, color: str = "#000000", audio: bool = True):
        await ctx.typing()
        input_key = f"fadeout_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "fadeout", input_key, start_time=start_time, duration=duration, color=color, audio=audio)
    
    @iv.command(name="overlay", description="Overlay one image/video on another.")
    @app_commands.describe(
        base_url="Base URL/Emoji/User.", 
        base_attachment="Base image/video file.",
        overlay_url="Overlay URL/Emoji/User.",
        overlay_attachment="Overlay image/video file.",
        x="X position. (pixels or expression)",
        y="Y position. (pixels or expression)"
    )
    async def overlay(self, ctx: commands.Context, 
                        base_url: Optional[str] = None, 
                        base_attachment: Optional[discord.Attachment] = None,
                        overlay_url: Optional[str] = None,
                        overlay_attachment: Optional[discord.Attachment] = None,
                        x: str = "0",
                        y: str = "0"):
        await ctx.typing()
        base_key = f"base_{ctx.message.id}"
        base_parsed = await self.process_media_input(ctx, base_url, base_attachment)
        if base_parsed[2]:
            raise commands.CommandError(base_parsed[2])
        base_url = base_parsed[0][8:]
        

        overlay_key = f"overlay_{ctx.message.id}"
        overlay_parsed = await self.process_media_input(ctx, overlay_url, overlay_attachment)
        if overlay_parsed[2]:
            raise commands.CommandError(overlay_parsed[2])
        overlay_url = overlay_parsed[0][8:]

        await self.tags_cog.processor._load_media(url=base_url, media_key=base_key)
        await self.tags_cog.processor._load_media(url=overlay_url, media_key=overlay_key)
        
        await self.run_gscript_command(
            ctx, 
            "overlay", 
            input_key=base_key,
            overlay_key=overlay_key,
            x=x,
            y=y
        )
    
    @iv.command(name="colorkey", description="RGB colorspace key an image or video.")
    @app_commands.describe(url="URL/Emoji/User.", attachment="Image/Video file.", color="FFmpeg color name or hex code.", similarity="How much the color should be similar in order to be transparent.", blend="Level of transparency. 0.0 results in full transparency, while higher values result in semi.")
    async def colorkey(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None, color: str = "black", similarity: float = 0.01, blend: float = 0.0):
        await ctx.typing()
        input_key = f"colorkey_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "colorkey", input_key, color=color, similarity=similarity, blend=blend)
    
    @iv.command(name="chromakey", description="YUV colorspace key an image or video.")
    @app_commands.describe(url="URL/Emoji/User.", attachment="Image/Video file.", color="FFmpeg color name or hex code.", similarity="How much the color should be similar in order to be transparent.", blend="Level of transparency. 0.0 results in full transparency, while higher values result in semi.")
    async def chromakey(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None, color: str = "black", similarity: float = 0.01, blend: float = 0.0):
        await ctx.typing()
        input_key = f"chromakey_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "chromakey", input_key, color=color, similarity=similarity, blend=blend)
    
    @av.command(name="volume", description="Adjust a video or audio's volume.")
    @app_commands.describe(
        url="URL/Emoji/User.", 
        attachment="Audio/Video file.",
        volume_level="Volume level. (0.5 = half volume, 2.0 = double volume)"
    )
    async def volume(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None, volume_level: float = 1.5):
        await ctx.typing()
        input_key = f"volume_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "volume", input_key, volume_level=volume_level)
    
    @av.command(name="tremolo", description="Apply tremolo effect to an audio or video.")
    @app_commands.describe(
        url="URL/Emoji/User.", 
        attachment="Audio/Video file.",
        frequency="Frequency in Hz.",
        depth="Depth. (0.0 to 1.0)"
    )
    async def tremolo(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None, frequency: float = 5.0, depth: float = 0.5):
        await ctx.typing()
        input_key = f"tremolo_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "tremolo", input_key, frequency=frequency, depth=depth)

    @av.command(name="vibrato", description="Apply vibrato effect to an audio or video.")
    @app_commands.describe(
        url="URL/Emoji/User.", 
        attachment="Audio/Video file.",
        frequency="Frequency in Hz.",
        depth="Depth. (0.0 to 1.0)"
    )
    async def vibrato(self, ctx: commands.Context, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None, frequency: float = 5.0, depth: float = 0.5):
        await ctx.typing()
        input_key = f"vibrato_{ctx.message.id}"
        parsed = await self.process_media_input(ctx, url, attachment)
        if parsed[2]:
            raise commands.CommandError(parsed[2])
        input_url = parsed[0][8:]

        await self.tags_cog.processor._load_media(url=input_url, media_key=input_key)
        await self.run_gscript_command(ctx, "vibrato", input_key, frequency=frequency, depth=depth)


async def setup(bot):
    await bot.add_cog(Media(bot))
