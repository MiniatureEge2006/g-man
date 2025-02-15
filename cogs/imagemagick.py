import discord
from discord import app_commands
from discord.ext import commands
import os
import time
import subprocess
import shlex
import aiohttp
from urllib.parse import urlparse
from pathlib import Path
import asyncio

class ImageMagick(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.hybrid_command(name="imagemagick", description="Use ImageMagick as if its a CLI!", aliases=["magick"])
    @app_commands.describe(args="ImageMagick arguments.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def imagemagick(self, ctx: commands.Context, *, args: str):
        await ctx.typing()
        

        try:
            start_time = time.time()

            processing_dir = 'vids'

            split_args = shlex.split(args)

            if len(split_args) < 2:
                await ctx.send("You must provide at least an input file and an output file.")
                return
            input_file = split_args[0]
            output_file = split_args[-1]

            if self.is_valid_url(input_file):
                filename = self.get_filename(input_file)
                local_input_file = os.path.join(processing_dir, filename)
                file_downloaded = await self.download_file(input_file, local_input_file)
                if not file_downloaded:
                    await ctx.send("Failed to download the input file.")
                    return
                split_args[0] = local_input_file
            
            cmd = ["magick"] + split_args

            result = await self.run_imagemagick(cmd)

            if result.returncode != 0:
                error_message = result.stderr
                await ctx.send(f"ImageMagick failed: ```{error_message}```")
                return
            file_size = os.path.getsize(output_file)
            boost_count = ctx.guild.premium_subscription_count if ctx.guild else 0
            max_size = self.get_max_file_size(boost_count)
            if file_size > max_size:
                raise commands.CommandError(f"File is too large to send. (Size: {file_size} bytes/{self.human_readable_size(file_size)}, Max Size: {max_size} bytes/{self.human_readable_size(max_size)})")
            if os.path.exists(output_file):
                elapsed_time = time.time() - start_time
                await ctx.send(f"-# {file_size} bytes ({self.human_readable_size(file_size)}), ImageMagick completed in {elapsed_time:.2f} seconds.", file=discord.File(output_file))
            else:
                await ctx.send("ImageMagick completed, but no output file was created.")
            
        
        except Exception as e:
            raise commands.CommandError(f"An error occurred: `{e}`")
        finally:
            if "local_input_file" in locals() and os.path.exists(local_input_file):
                os.remove(local_input_file)
            if os.path.exists(output_file):
                os.remove(output_file)


    async def run_imagemagick(self, args: list):
        process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()
        result = subprocess.CompletedProcess(args, process.returncode, stdout.decode('utf-8'), stderr.decode('utf-8'))
        return result

    async def download_file(self, url: str, file_path: str) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        with open(file_path, 'wb') as f:
                            f.write(await resp.read())
                        return True
                    else:
                        return False
        except Exception as e:
            print(f"Error downloading the media from {url}: {e}")
            return False

    def is_valid_url(self, url: str) -> bool:
        parsed = urlparse(url)
        return bool(parsed.scheme and parsed.netloc)

    def get_filename(self, url: str) -> str:
        parsed_url = urlparse(url)
        filename = Path(parsed_url.path).name
        return filename
    
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
    await bot.add_cog(ImageMagick(bot))