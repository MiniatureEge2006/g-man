import discord
from discord.ext import commands
from discord import app_commands
import os
import aiohttp
import subprocess
import json
import mimetypes
from urllib.parse import urlparse

class Exif(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.hybrid_command(name="exif", description="Use FFprobe to extract exif metadata from media.", aliases=["ffprobe"])
    @app_commands.describe(url="Input URL to extract metadata from.")
    @app_commands.user_install()
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def exif(self, ctx: commands.Context, url: str = None):
        if ctx.interaction:
            await ctx.defer()
        else:
            await ctx.typing()
        
        try:
            if not url and not ctx.message.attachments:
                await ctx.send("Please provide an URL or attach a media file.")
                return
            
            file_path = await self.download_media(ctx, url)

            metadata = self.get_metadata(file_path)

            if metadata:
                formatted_metadata = "\n".join([f"**{key}:** {value}" for key, value in metadata.items()])
                if len(formatted_metadata) > 2000:
                    metadata_file = f"{file_path}.txt"
                    with open(metadata_file, 'w') as f:
                        f.write(formatted_metadata)
                    await ctx.send("Metadata is too large to display, sent as a file:", file=discord.File(metadata_file))
                    os.remove(metadata_file)
                else:
                    await ctx.send(f"**Metadata:**\n{formatted_metadata}")
            else:
                await ctx.send("No metadata found in the file.")
            
            os.remove(file_path)
        
        except Exception as e:
            await ctx.send(f"An error occurred: `{e}`")
    

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
            
        elif ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            file_name = attachment.filename
            file_path = f"vids/{file_name}"
            await attachment.save(file_path)
        else:
            raise ValueError("Invalid input: Malformed URL")
        return file_path
    
    def is_valid_url(self, url: str) -> bool:
        parsed = urlparse(url)
        return bool(parsed.scheme and parsed.netloc)
    
    def get_metadata(self, file_path: str) -> dict:
        try:
            cmd = [
                "ffprobe",
                "-v", "error",
                "-show_entries",
                "format=duration,size,format_name,bit_rate:stream=codec_name,codec_type,width,height,duration,bit_rate",
                "-print_format", "json",
                file_path
            ]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            if result.returncode != 0:
                raise ValueError(f"FFprobe error: {result.stderr.strip()}")
            
            metadata = json.loads(result.stdout)

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
                    else:
                        flat_metadata[f"Format {key.capitalize()}"] = value
                        
            if "streams" in metadata:
                for idx, stream in enumerate(metadata["streams"]):
                    for key, value in stream.items():
                        if key == "duration":
                            duration_seconds = float(value)
                            flat_metadata[f"Stream {idx + 1} Duration"] = f"{duration_seconds} seconds ({self.format_duration(duration_seconds)})"
                        else:
                            flat_metadata[f"Stream {idx + 1} {key.capitalize()}"] = value
            return flat_metadata
        
        except Exception as e:
            return {"Error": str(e)}
        
    def human_readable_size(self, size: int) -> str:
        for unit in ["B", "KB", "MB", "GB", "TB"]:
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
