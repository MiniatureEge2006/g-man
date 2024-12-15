import discord
from discord.ext import commands
from discord import app_commands
import subprocess
import os
import aiohttp
import shlex
from urllib.parse import urlparse
from pathlib import Path


class FFmpeg(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    

    @commands.hybrid_command(name="ffmpeg", description="Use FFmpeg as if its a CLI!")
    @app_commands.describe(args="FFmpeg arguments.")
    @app_commands.user_install()
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def ffmpeg_command(self, ctx: commands.Context, *, args: str):
        
        if ctx.interaction:
            await ctx.defer()
        else:
            await ctx.typing()

        try:
            processing_dir = 'vids'
            
            input_files = []

            
            
            split_args = shlex.split(args)
            for idx, arg in enumerate(split_args):
                if arg == "-i" and idx + 1 < len(split_args):
                    input_url = split_args[idx + 1]
                    if is_valid_url(input_url):
                        filename = get_filename(input_url)
                        file_path = os.path.join(processing_dir, filename)
                        async with aiohttp.ClientSession() as session:
                            async with session.get(input_url) as resp:
                                if resp.status == 200:
                                    with open(file_path, 'wb') as f:
                                        f.write(await resp.read())
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

            

            print("Executing FFmpeg command:", " ".join(cmd))

            result = subprocess.run(cmd, capture_output=True, text=True)
            
            print("FFmpeg Output:", result.stdout)
            print("FFmpeg Error:", result.stderr)

            if result.returncode != 0:
                error_message = result.stderr
                if len(error_message) > 2000:
                    error_file_path = os.path.join(processing_dir, "ffmpeg_error.txt")
                    with open(error_file_path, 'w') as f:
                        f.write(error_message)
                    await ctx.send("FFmpeg encountered an error. See the attached log file.", file=discord.File(error_file_path))
                    os.remove(error_file_path)
                else:
                    await ctx.send(f"FFmpeg encountered an error: ```{error_message}```")
                return


            output_file = [arg for arg in split_args if not arg.startswith("-")][-1]
            if os.path.exists(output_file):
                await ctx.send(file=discord.File(output_file))
                os.remove(output_file)
            else:
                await ctx.send("FFmpeg processing completed, but the output file could not be found.")
            
            for file in input_files:
                os.remove(file)

        except Exception as e:
            await ctx.send(f"An error occurred: `{e}`")


def is_valid_url(url: str) -> bool:
    parsed = urlparse(url)
    return bool(parsed.scheme and parsed.netloc)

def get_filename(url: str) -> str:
    parsed_url = urlparse(url)
    filename = Path(parsed_url.path).name
    return filename

async def setup(bot):
    await bot.add_cog(FFmpeg(bot))