import discord
from discord.ext import commands
from discord import app_commands
import os
import aiohttp
import json
import mimetypes
from urllib.parse import urlparse
from typing import Optional
import asyncio

class Exif(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.hybrid_command(name="exif", description="Use FFprobe to extract exif metadata from media.", aliases=["ffprobe"])
    @app_commands.describe(url="Input URL to extract metadata from.", attachment="Media attachment to extract metadata from.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def exif(self, ctx: commands.Context, url: str = None, attachment: Optional[discord.Attachment] = None):
        await ctx.typing()
        
        try:
            if not url and not (ctx.message.attachments or attachment):
                await ctx.send("Please provide an URL or attach a media file.")
                return
            
            file_path = await self.download_media(ctx, url)

            metadata = await self.get_metadata(file_path)

            if metadata:
                mime_type = metadata.get("MIME Type", "unknown").lower()
                color = discord.Color.light_gray()
                thumbnail_url = None
                thumbnail_file = None
                if "image" in mime_type:
                    color = discord.Color.green()
                    if url and self.is_valid_url(url):
                        thumbnail_url = url
                    elif ctx.message.attachments:
                        thumbnail_file = discord.File(file_path, filename=os.path.basename(file_path))
                        thumbnail_url = f"attachment://{os.path.basename(file_path)}"
                elif "video" in mime_type:
                    color = discord.Color.red()
                    thumbnail_file = discord.File("assets/video.png", filename="video.png")
                    thumbnail_url = f"attachment://video.png"
                elif "audio" in mime_type:
                    color = discord.Color.blue()
                    thumbnail_file = discord.File("assets/audio.png", filename="audio.png")
                    thumbnail_url = f"attachment://audio.png"
                base_embed = discord.Embed(
                    title="EXIF Metadata",
                    url=url if url else None,
                    description="Metadata extracted using FFprobe.",
                    color=color,
                    timestamp=discord.utils.utcnow()
                )
                base_embed.set_footer(text="Powered by FFprobe", icon_url="https://img.icons8.com/?size=100&id=32418&format=png&color=000000")
                if thumbnail_url:
                    base_embed.set_thumbnail(url=thumbnail_url)
                base_embed.add_field(
                    name="Summary",
                    value=(
                        f"**Filename:** {metadata.get('Filename', 'Unknown')}\n"
                        f"**MIME Type:** {mime_type}\n"
                        f"**File Size:** {metadata.get('File Size', 'Unknown')}\n"
                        f"**Duration:** {metadata.get('Total Duration', 'Unknown')}\n"
                    ),
                    inline=False
                )
                metadata_items = list(metadata.items())
                embeds = [base_embed]
                current_embed = base_embed
                for i, (key, value) in enumerate(metadata_items):
                    if key not in ["Filename", "MIME Type", "File Size", "Total Duration"]:
                        if len(current_embed.fields) >= 25:
                            current_embed = discord.Embed(
                                title="More EXIF Metadata",
                                color=color,
                                timestamp=discord.utils.utcnow()
                            )
                            embeds.append(current_embed)
                        current_embed.add_field(name=key, value=value, inline=False)
                for embed in embeds:
                    if thumbnail_file and embed == base_embed:
                        await ctx.send(embed=embed, file=thumbnail_file)
                    else:
                        await ctx.send(embed=embed)
            else:
                await ctx.send("No metadata found in the file.")
            
        
        except Exception as e:
            raise commands.CommandError(f"An error occurred: `{e}`")

        finally:
            if os.path.exists(file_path):
                os.remove(file_path)
    

    async def download_media(self, ctx: commands.Context, url: str) -> str:
        if self.is_valid_url(url):
            file_name = os.path.basename(urlparse(url).path)
            file_path = f"vids/{file_name}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        with open(file_path, 'wb') as f:
                            f.write(await resp.read())
                    else:
                        raise ValueError("Failed to download the file.")
            
        elif ctx.message.attachments or ctx.interaction.message.attachments:
            attachment = ctx.message.attachments[0] or ctx.interaction.message.attachments[0]
            file_name = attachment.filename
            file_path = f"vids/{file_name}"
            await attachment.save(file_path)
        else:
            raise ValueError("Invalid input: Malformed URL")
        return file_path
    
    def is_valid_url(self, url: str) -> bool:
        parsed = urlparse(url)
        return bool(parsed.scheme and parsed.netloc)
    
    async def get_metadata(self, file_path: str) -> dict:
        try:
            cmd = [
                "ffprobe",
                "-v", "error",
                "-show_entries",
                "format=duration,size,format_name,format_long_name,bit_rate,format_tags:stream=codec_name,codec_type,codec_tag_string,codec_tag,codec_long_name,width,height,duration,bit_rate:side_data_list:format_tags:stream_tags",
                "-print_format", "json",
                file_path
            ]
            result = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, stderr = await result.communicate()

            if result.returncode != 0:
                raise ValueError(f"FFprobe error: {stderr}")
            
            metadata = json.loads(stdout)

            flat_metadata = {}

            flat_metadata["Filename"] = os.path.basename(file_path)

            mime_type, _ = mimetypes.guess_type(file_path)

            flat_metadata["MIME Type"] = mime_type if mime_type else "Unknown"

            if "format" in metadata:
                for key, value in metadata["format"].items():
                    if key == "size":
                        flat_metadata["File Size"] = f"{int(value)} bytes ({self.human_readable_size(int(value))})"
                    elif key == "duration":
                        duration_seconds = float(value)
                        flat_metadata["Total Duration"] = f"{duration_seconds} seconds ({self.format_duration(duration_seconds)})"
                    elif key == "tags":
                        for tag_key, tag_value in value.items():
                            flat_metadata[f"Tag {tag_key.capitalize()}"] = tag_value
                    else:
                        flat_metadata[f"Format {key.capitalize()}"] = value
                        
            if "streams" in metadata:
                for idx, stream in enumerate(metadata["streams"]):
                    codec_name = stream.get("codec_name", "Unknown")
                    codec_long_name = stream.get("codec_long_name", "Unknown")
                    codec_tag_string = stream.get("codec_tag_string", "Unknown")
                    flat_metadata[f"Stream {idx + 1} Codec"] = f"{codec_name} ({codec_tag_string}, {codec_long_name})"
                    for key, value in stream.items():
                        if key == "duration":
                            duration_seconds = float(value)
                            flat_metadata[f"Stream {idx + 1} Duration"] = f"{duration_seconds} seconds ({self.format_duration(duration_seconds)})"
                        elif key == "tags":
                            for tag_key, tag_value in value.items():
                                flat_metadata[f"Stream {idx + 1} Tag {tag_key.capitalize()}"] = tag_value
                        elif key not in ["codec_name", "codec_long_name", "codec_tag_string"]:
                            flat_metadata[f"Stream {idx + 1} {key.capitalize()}"] = value
            return flat_metadata
        
        except Exception as e:
            return {"Error": str(e)}
        
    def human_readable_size(self, size: int) -> str:
        for unit in ["B", "KiB", "MiB", "GiB", "TiB"]:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
    
    def format_duration(self, seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = seconds % 60
        return f"{hours:02}:{minutes:02}:{seconds:06.3f}"

async def setup(bot):
    await bot.add_cog(Exif(bot))
