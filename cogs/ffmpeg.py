import discord
from discord.ext import commands
from discord import app_commands
import time
import os
import aiohttp
import shlex
from urllib.parse import urlparse
from pathlib import Path
import asyncio


class FFmpeg(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    

    @commands.hybrid_command(name="ffmpeg", description="Use FFmpeg as if its a CLI!")
    @app_commands.describe(args="FFmpeg arguments.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def ffmpeg_command(self, ctx: commands.Context, *, args: str):
        
        await ctx.typing()

        try:
            start_time = time.time()

            processing_dir = 'vids'
            
            input_files = []

            
            
            split_args = shlex.split(args)
            for idx, arg in enumerate(split_args):
                if arg == "-i" and idx + 1 < len(split_args):
                    input_url = split_args[idx + 1]
                    if self.is_valid_url(input_url):
                        filename = self.get_filename(input_url)
                        file_path = os.path.join(processing_dir, filename)
                        file_downloaded = await self.download_file(input_url, file_path)
                        if file_downloaded:
                            input_files.append(file_path)
                            split_args[idx + 1] = file_path
                        else:
                            await ctx.send(f"Failed to download the media from `{input_url}`")
                            return
            filter_options = ["-filter_complex", "-vf", "-af"]
            for option in filter_options:
                if option in split_args:
                    idx = split_args.index(option)
                    if idx + 1 < len(split_args):
                        filter_value = split_args[idx + 1]
                        if filter_value.startswith('"') and filter_value.endswith('"'):
                            split_args[idx + 1] = filter_value[1:-1]
            
            cmd = ["ffmpeg"] + split_args

            

            process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            
            output_task = asyncio.create_task(self.read_output(process.stdout))
            error_task = asyncio.create_task(self.read_stderr(process.stderr))


            await asyncio.gather(output_task, error_task)
            await process.wait()

            output = await output_task
            error_output = await error_task

            if process.returncode != 0:
                error_message = error_output
                if len(error_message) > 2000:
                    error_file_path = os.path.join(processing_dir, "ffmpeg_error.txt")
                    with open(error_file_path, 'w') as f:
                        f.write(error_message)
                    await ctx.send("FFmpeg encountered an error.", file=discord.File(error_file_path))
                    os.remove(error_file_path)
                else:
                    await ctx.send(f"FFmpeg encountered an error: ```{error_message}```")
                return


            output_file = [arg for arg in split_args if not arg.startswith("-")][-1]
            file_size = os.path.getsize(output_file)
            boost_count = ctx.guild.premium_subscription_count if ctx.guild else 0
            max_size = self.get_max_file_size(boost_count)
            if file_size > max_size:
                raise commands.CommandError(f"File is too large to send. (Size: {file_size} bytes/{self.human_readable_size(file_size)}, Max Size: {max_size} bytes/{self.human_readable_size(max_size)})")
            if os.path.exists(output_file):
                elapsed_time = time.time() - start_time
                await ctx.send(f"-# {file_size} bytes ({self.human_readable_size(file_size)}), FFmpeg processing completed in {elapsed_time:.2f} seconds.", file=discord.File(output_file))
            else:
                await ctx.send("FFmpeg processing completed, but the output file could not be found.")
            

        except Exception as e:
            raise commands.CommandError(f"Error: `{e}`")
        finally:
            for file in input_files:
                if os.path.exists(file):
                    os.remove(file)
            output_file = [arg for arg in split_args if not arg.startswith("-")][-1]
            if os.path.exists(output_file):
                os.remove(output_file)


    async def read_output(self, stream):
            output = []
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    break
                decoded_chunk = chunk.decode('utf-8', errors='ignore').strip()
                print(decoded_chunk)
                output.append(decoded_chunk)
            return '\n'.join(output)
    
    async def read_stderr(self, stream):
            error_output = []
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    break
                decoded_chunk = chunk.decode('utf-8', errors='ignore').strip()
                print(decoded_chunk)
                error_output.append(decoded_chunk)
            return '\n'.join(error_output)

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
    await bot.add_cog(FFmpeg(bot))