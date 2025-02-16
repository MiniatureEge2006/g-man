import asyncio
import discord
from discord.ext import commands
from discord import app_commands
import os
import random
import textwrap
import aiohttp
import re
import urllib.parse

class Tutorial(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    async def download_file(self, url, prefix="temp_input"):
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    parsed = urllib.parse.urlparse(url)
                    filename = os.path.basename(parsed.path)
                    if "." not in filename:
                        content_disposition = resp.headers.get("Content-Disposition", "")
                        if "filename=" in content_disposition:
                            filename = re.findall("filename=(.+)", content_disposition)[0].strip('"')
                    _, ext = os.path.splitext(filename)
                    temp_filename = f"{prefix}{ext or ''}"
                    with open(temp_filename, "wb") as f:
                        f.write(await resp.read())
                    return temp_filename
                return None


    @commands.hybrid_command(name="tutorial", description="Make an oldschool video tutorial.")
    @app_commands.describe(msg="Message to use for the title. Use a '|' after the title to use a subtitle. If there are any URLS in the message, they will be used as video and music URLs in order.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def tutorial(self, ctx: commands.Context, *, msg: str = ''):
        await ctx.typing()

        if ctx.message.attachments:
            video_attachment = ctx.message.attachments[0]
            video_filename = f"vids/temp_video_{video_attachment.filename}"
            await video_attachment.save(video_filename)
        else:
            url_match = re.search(r'(https?://\S+)', msg)
            if not url_match:
                await ctx.send("Please provide a video URL or attach a video file.")
                return
            video_url = url_match.group(1)
            msg = msg.replace(video_url, '').strip()
            video_filename = await self.download_file(video_url, "temp_video_")
            if not video_filename:
                await ctx.send("Failed to download the video.")
                return
        
        music_filename = None
        if len(ctx.message.attachments) > 1:
            music_attachment = ctx.message.attachments[1]
            music_filename = f"vids/temp_music_{music_attachment.filename}"
            await music_attachment.save(music_filename)
        else:
            url_match = re.search(r'(https?://\S+)', msg)
            if url_match:
                music_url = url_match.group(1)
                msg = msg.replace(music_url, '').strip()
                music_filename = await self.download_file(music_url, "temp_music_")
        
        if not music_filename:
            await ctx.send("Please provide a music URL or attach a music file.")
            return
        
        title_top = ''
        title_bottom = 'by ' + str(ctx.author.display_name)
        msg = msg.split('|')
        for i in range(len(msg)):
            msg[i] = msg[i].strip()
        if len(msg) == 1:
            if msg[0] == '':
                title_top = random.choice([
                    'how to get free club penguin',
                    'My Movie',
                    'How To Download from Megaupload.com',
                    'How to Downalod off Megaupload.com',
                    'FREE robux tutorial WORKING 2009',
                    'Where to get Gta San Andreas Noob Mod V2',
                    'club penguin how to tip the iceberg the only way!!!!',
                    'club penguin proof of tipping iceberg!',
                    'Wizard 101 - How to get on 2 accounts!!!!',
                    'Emulator/Rom Tutorial',
                    'How to get on top of the night club in club penguin with out hacking',
                    'How to install cleo mods to GTA San Andreas',
                    'How to install weapon mods on GTA San Andreas (IMGTool)',
                    'Gta San Andreas goez crazy',
                    'Austin Powers watch online free (link in description)'
                ])
            else:
                title_top = msg[0]
        else:
            title_top = msg[0]
            title_bottom = msg[1]
        
        title_font_size = 60
        max_line_width = 30
        wrapped_title = textwrap.wrap(title_top, width=max_line_width)
        if len(wrapped_title) > 3:
            title_font_size = 50
            max_line_width = 40
            wrapped_title = textwrap.wrap(title_top, width=max_line_width)
        sub_font_size = title_font_size * 0.7
        output_filename = "vids/tutorial.mp4"
        ffmpeg_command = [
            'ffmpeg',
            '-i', 'tutorial/bg.mp4',
            '-i', video_filename,
            '-i', music_filename,
            '-filter_complex',
            f"""
            [0:v]drawtext=text='{title_top}':fontfile=fonts/arial.ttf:fontsize=180:x=(main_w-tw)/2-th+t*70:y=100:alpha='min(1,-abs(t-1.7)+1.7)*0.5':fontcolor=#f0f0f0[bg];
            [bg]drawtext=text='{title_top}':fontfile=fonts/arial.ttf:fontsize=385:x=(main_w-tw)/2+th-t*40:y=200:alpha='min(1,-abs(t-1.7)+1.7)*0.2':fontcolor=#f0f0f0[bg2];
            [bg2]drawtext=text='{wrapped_title[-1]}':fontfile=fonts/arial.ttf:fontsize={title_font_size}:x=(main_w-tw)/2:y=main_h/2-({title_font_size}*0)-{title_font_size/2}:alpha='-abs(t-1.7)+1.7':fontcolor=#f0f0f0:shadowcolor=black:shadowx=1:shadowy=1[bg3];
            [bg3]drawtext=text='{title_bottom[:19]}':fontfile=fonts/arial.ttf:fontsize={sub_font_size}:x=(main_w-tw)/2:y=main_h/2+({sub_font_size}):alpha='-abs(t-1.7-0.25)+1.7-0.25':fontcolor=#f0f0f0:shadowcolor=black:shadowx=1:shadowy=1[bg4];
            [1:v]scale=640:480,setsar=1:1[vid];
            [bg4][vid]concat=n=2:v=1:a=0[mainvid];
            [0:v]drawtext=text='Thx for watching':fontfile=fonts/arial.ttf:fontsize=60:x=(main_w-tw)/2:y=(main_h-th)/2:fontcolor=#f0f0f0:shadowcolor=black:shadowx=2:shadowy=2:enable='between(t,0,3)':alpha='if(lt(t,1),t,if(gt(t,2),3-t,1))'[thanks];
            [0:v]drawtext=text='Pls like and subscribe':fontfile=fonts/arial.ttf:fontsize=40:x=(main_w-tw)/2:y=(main_h-th)/2+70:fontcolor=#f0f0f0:shadowcolor=black:shadowx=2:shadowy=2:enable='between(t,0,3)':alpha='if(lt(t,1),t,if(gt(t,2),3-t,1))'[subscribe];
            [mainvid][thanks][subscribe]concat=n=3:v=1:a=0[outv]""",
            '-map', '[outv]',
            '-map', '2:a',
            '-vsync', '2',
            '-shortest',
            '-y', output_filename
        ]
        try:
            proc = await asyncio.create_subprocess_exec(*ffmpeg_command)
            await proc.wait()
            if proc.returncode == 0:
                await ctx.send(file=discord.File(output_filename))
            else:
                await ctx.send("Video processing failed.")
        finally:
            for f in [video_filename, music_filename, output_filename]:
                if f and os.path.exists(f):
                    os.remove(f)

async def setup(bot):
    await bot.add_cog(Tutorial(bot))