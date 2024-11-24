import os
import discord
from discord.ext import commands
import yt_dlp

class Ytdlp(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(name="yt-dlp", aliases=["youtube-dl", "ytdl", "youtubedl", "ytdlp"])
    async def ytdlp(self, ctx, url: str, *, options: str = ''):

        ydl_opts = {
            'no_playlist': True,
            'outtmpl': 'vids/%(extractor)s-%(id)s.%(ext)s'
        }

        if options.strip():
            try:
                custom_opts = self.parse_options(options)
                ydl_opts.update(custom_opts)
            except Exception as e:
                await ctx.send(f"Error parsing options: `{e}`")
                return
        
        try:
            await ctx.send(f"Downloading from `{url}` with options `{ydl_opts}`...")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                file_path = ydl.prepare_filename(info)
            
            file_size = os.path.getsize(file_path)
            max_size = self.get_max_file_size(ctx.guild.premium_subscription_count)

            if file_size > max_size:
                await ctx.send(f"File is too large to send via Discord. ({file_size} bytes)")
            else:
                await ctx.send(file=discord.File(file_path))

            os.remove(file_path)
        except Exception as e:
            await ctx.send(f"Download failed: `{e}`")
        
    def parse_options(self, options: str) -> dict:
        parsed_opts = {}
        for opt in options.split():
            if "=" in opt:
                key, value = opt.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"')

                if value.lower() == 'true':
                    parsed_opts[key] = True
                elif value.lower() == 'false':
                    parsed_opts[key] = False
                else:
                    parsed_opts[key] = value
            elif opt.startswith("--"):
                key = opt[2:].strip()
                parsed_opts[key] = True
            else:
                raise ValueError(f"Invalid option format: `{opt}`")
        return parsed_opts
    

    def get_max_file_size(self, boost_count: int) -> int:
        if boost_count >= 14:
            return 100 * 1024 * 1024 # 100 MB
        elif boost_count >= 7:
            return 50 * 1024 * 1024 # 50 MB
        else:
            return 25 * 1024 * 1024 # 25 MB

async def setup(bot):
    await bot.add_cog(Ytdlp(bot))
