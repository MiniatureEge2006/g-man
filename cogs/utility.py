import asyncio
from genericpath import isfile
import discord
from discord.ext import commands
from discord import app_commands
import database as db
import ffmpeg
import filter_helper
import media_cache
import os
import re
import requests
import subprocess
import video_creator

class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    
    async def _download(self, ctx, vstream, astream, kwargs):
        return vstream, astream, {}
    @commands.command()
    async def download(self, ctx):
        await video_creator.apply_filters_and_send(ctx, self._download, {})
    @commands.command()
    async def fix(self, ctx):
        await self.download(ctx)
    @commands.command()
    async def dl(self, ctx):
        await self.download(ctx)

    async def _gif(self, ctx, vstream, astream, kwargs):
        fps = kwargs['fps']
        vstream = vstream.filter('fps', fps=fps).split()
        palette = vstream[1].filter('palettegen')
        vstream = ffmpeg.filter([vstream[0], palette], 'paletteuse')
        return vstream, astream, {}
    @commands.command()
    async def gif(self, ctx, fps : int = 24):
        fps = max(1, min(fps, 24))
        await video_creator.apply_filters_and_send(ctx, self._gif, {'is_gif':True, 'fps':fps})

    @commands.command()
    async def vid2img(self, ctx):
        await video_creator.set_progress_bar(ctx.message, 0)
        input_filepath = media_cache.get_from_cache(str(ctx.message.channel.id))[-1]
        output_filename = 'vids/discord-' + str(ctx.message.id) + '.png'
        await video_creator.set_progress_bar(ctx.message, 1)

        await video_creator.set_progress_bar(ctx.message, 2)
        subprocess.run([
            'ffmpeg',
            '-i', f'{input_filepath}',
            '-frames:v', '1',
            output_filename
        ])
        await video_creator.set_progress_bar(ctx.message, 3)
        if(os.path.isfile(output_filename)):
            await ctx.send(file=discord.File(output_filename))
            os.remove(output_filename)
        else:
            await ctx.send(f'There was an error converting the video (`{input_filepath}`) to an image.')
        await ctx.message.clear_reactions()

    @commands.command()
    async def help(self, ctx, command_name : str = ''):
        if(command_name == ''):
            await ctx.send(embed=discord.Embed(title='Command list', color=0x0000FF)
                           .add_field(name='Bitrate', value='`b` `vb` `ab`')
                           .add_field(name='Filters', value='`amplify` `audioblend/audiomerge` `audioswap` `backwards/reverse` `bassboost` `bitcrush` `blur` `brightness` `concat/merge` `contrast` `edges` `equalize/equalizer` `extract` `fade` `fps` `gamma` `greenscreen` `overlay` `hue` `interpolate` `invert/inverse/negate/negative` `lagfun` `loop` `nervous` `pitch` `retro` `rotate` `rotatedeg` `saturate/saturation` `scale/size` `scroll` `semitone` `shader` `speed` `volume` `wobble` `zoom`')
                           .add_field(name='Corruption', value='`corrupt` `faketime` `mosh` `rearrange` `smear` `stutter`')
                           .add_field(name='Fun effects', value='`americ` `cartoony/cartoon` `deepfry` `demonize` `harmonize` `harmonizedeep` `histogram` `hypercam` `ifunny` `mahna/mahnamahna` `pingpong` `rainbow` `sequencer` `tetris` `text` `trippy` `tutorial` `vintage`')
                           .add_field(name='Bookmarks', value='`save/store` `load/use` `delete/remove` `bookmarks`')
                           .add_field(name='Utility', value='`download/fix/dl` `img2vid` `gif` `vid2img` `mp3` `swap` `time/timestamp` `undo` `ping`')
                           .add_field(name='Advanced (power users only!)', value='`filter` `yt-dlp/youtube-dl/youtubedl/ytdl/ytdlp`')
                           .add_field(name='Owner only (NO ACCESS)', value='`reload` `eval/exec/code` `block` `unblock` `sync`'))
            return
        if(command_name == 'filter'):
            await ctx.send(embed=discord.Embed(title='Filter command', description='The filter command is used to apply almost any filter that is in FFMPEG. If you know how FFMPEG syntax works then this command is the perfect command for you. However, if you don\'t know how this works then I suggest reading the FFMPEG documentation [here.](https://ffmpeg.org/ffmpeg-filters.html)', color=0xFF0000)
                           .add_field(name='Format', value='`!filter <filter_name> <filter_args>`\n`<filter_args>` are formatted in this way: `arg1_name=arg1_value arg2_name=arg2_value ...`')
                           .add_field(name='Examples', value='`!filter aecho` or `!filter edgedetect low=0.1 mode=wires` or `!filter drawtext text="g_man was here" x="(main_w-tw)/2" y="(main_h-th)/2 + 100*sin(t*6)" fontsize=50`')
                           .add_field(name='Multiple filters', value='`!filter reverse !filter areverse` or `!filter eq contrast=1.2 !filter hue h=60 enable=gte(t,3) !filter negate`')
                           .add_field(name="Info", value='At the moment you **cannot** apply filters requiring multiple inputs.'))
            return
        if(command_name == 'yt-dlp' or command_name == 'youtube-dl' or command_name == 'youtubedl' or command_name == 'ytdl' or command_name == 'ytdlp'):
            await ctx.send(embed=discord.Embed(title='The yt-dlp command', description='The yt-dlp command (also known as youtube-dl, youtubedl, ytdl and ytdlp) is an advanced command that is similar to `!download` but even more advanced and allows you to specify custom yt-dlp options. The formatting is similar to `!filter` so you might get used to this command as well.', color=0xFF0000)
                           .add_field(name='Format', value='`!yt-dlp <url> [options]`')
                           .add_field(name='Examples', value='`!yt-dlp url format=bestvideo+bestaudio --simulate`'))
            return
        if(command_name == 'help'):
            await ctx.send('`!help` to get a list of all the commands.\n`!help <command_name>` to get help on a specific command.')
            return

        commands_file = open('COMMANDS.md', 'r')
        all_commands = commands_file.read().split('\n')
        commands_file.close()

        embed = None
        for command in all_commands:
            if(command == '' or command[0] != '|' or command.startswith('| Command') or command.startswith('| ---')):
                continue
            command = re.split(r'^\| | \| |\| | \|$', command)
            if(command[0] == ''):
                command = command[1:]
            if(command[-1] == ''):
                command = command[:-1]
            command = {
                'names' : command[0].split('<br>'),
                'syntax' : command[1].replace('<br><br>','\n'),
                'limits' : command[2].replace('<br>', '\n'),
                'description' : command[3].replace('<br>', '\n').replace('\\|', '|'),
                'examples' : command[4].replace('<br><br>', '\n').replace('\\|', '|')
            }

            if(command_name not in command['names']):
                continue
            embed = discord.Embed(title=command_name, description=command['description'], color=0x00FF00)
            embed.add_field(name='Syntax', value=command['syntax'], inline=False)
            if(command['limits'] != ''):
                embed.add_field(name='Min/Max Values', value=command['limits'], inline=False)
            if(command['syntax'] != command['examples']):
                embed.add_field(name='Examples', value=command['examples'], inline=False)
            if(len(command['names']) > 1):
                aliases = list(filter(lambda x : x != command_name, command['names']))
                aliases = ', '.join(aliases)
                footer_text = 'Alternative command name'
                if(len(command['names']) > 2):
                    footer_text += 's:\n'
                else:
                    footer_text += ': '
                footer_text += aliases
                embed.set_footer(text=footer_text)

            await ctx.send(embed=embed)
            break

        if(embed is None):
            await ctx.send("Command not found. Please type `!help` to see a list of commands.")

    @app_commands.command(name="help", description="Get a list of my commands.")
    @app_commands.user_install()
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def _help(self, ctx: discord.Interaction, command_name: str = ''):
        if(command_name == ''):
            await ctx.response.send_message(embed=discord.Embed(title="Command list", color=0x0000FF)
                                            .add_field(name="Bitrate", value="`b` `vb` `ab`")
                                            .add_field(name="Filters", value="`amplify` `audioblend/audiomerge` `audioswap` `backwards/reverse` `bassboost` `bitcrush` `blur` `brightness` `concat/merge` `contrast` `edges` `equalize/equalizer` `extract` `fade` `fps` `gamma` `greenscreen` `overlay` `hue` `interpolate` `invert/inverse/negate/negative` `lagfun` `loop` `nervous` `pitch` `retro` `rotate` `rotatedeg` `saturate/saturation` `scale/size` `scroll` `semitone` `shader` `speed` `volume` `wobble` `zoom`")
                                            .add_field(name="Corruption", value="`corrupt` `faketime` `mosh` `rearrange` `smear` `stutter`")
                                            .add_field(name="Fun effects", value="`americ` `cartoony/cartoon` `deepfry` `demonize` `harmonize` `harmonizedeep` `histogram` `hypercam` `ifunny` `mahna/mahnamahna` `pingpong` `rainbow` `sequencer` `tetris` `text` `trippy` `tutorial` `vintage`")
                                            .add_field(name="Bookmarks", value="`save/store` `load/use` `delete/remove` `bookmarks`")
                                            .add_field(name="Utility", value="`download/fix/dl` `img2vid` `gif` `vid2img` `mp3` `swap` `time/timestamp` `undo` `ping`")
                                            .add_field(name="Advanced (power users only!)", value="`filter` `yt-dlp/youtube-dl/youtubedl/ytdl/ytdlp`")
                                            .add_field(name="Owner only (NO ACCESS)", value="`reload` `eval/exec/code` `block` `unblock` `sync`"))
            return
        if(command_name == 'filter'):
            await ctx.response.send_message(embed=discord.Embed(title='Filter command', description='The filter command is used to apply almost any filter that is in FFMPEG. If you know how FFMPEG syntax works then this command is the perfect command for you. However, if you don\'t know how this works then I suggest reading the FFMPEG documentation [here.](https://ffmpeg.org/ffmpeg-filters.html)', color=0xFF0000)
                           .add_field(name='Format', value='`!filter <filter_name> <filter_args>`\n`<filter_args>` are formatted in this way: `arg1_name=arg1_value arg2_name=arg2_value ...`')
                           .add_field(name='Examples', value='`!filter aecho` or `!filter edgedetect low=0.1 mode=wires` or `!filter drawtext text="g_man was here" x="(main_w-tw)/2" y="(main_h-th)/2 + 100*sin(t*6)" fontsize=50`')
                           .add_field(name='Multiple filters', value='`!filter reverse !filter areverse` or `!filter eq contrast=1.2 !filter hue h=60 enable=gte(t,3) !filter negate`')
                           .add_field(name="Info", value='At the moment you **cannot** apply filters requiring multiple inputs.'))
            return
        if(command_name == 'yt-dlp' or command_name == 'youtube-dl' or command_name == 'youtubedl' or command_name == 'ytdl' or command_name == 'ytdlp'):
            await ctx.response.send_message(embed=discord.Embed(title='The yt-dlp command', description='The yt-dlp command (also known as youtube-dl, youtubedl, ytdl and ytdlp) is an advanced command that is similar to `!download` but even more advanced and allows you to specify custom yt-dlp options. The formatting is similar to `!filter` so you might get used to this command as well.', color=0xFF0000)
                           .add_field(name='Format', value='`!yt-dlp <url> [options]`')
                           .add_field(name='Examples', value='`!yt-dlp url format=bestvideo+bestaudio --simulate`'))
            return
        if(command_name == 'help'):
            await ctx.response.send_message("`/help` to get a list of commands.\n`/help <command_name>` to get help on a specific command.")
            return
        
        commands_file = open('COMMANDS.md', 'r')
        all_commands = commands_file.read().split('\n')
        commands_file.close()

        embed = None
        for command in all_commands:
            if(command == '' or command[0] != '|' or command.startswith('| Command') or command.startswith('| ---')):
                continue
            command = re.split(r'^\| | \| |\| | \|$', command)
            if(command[0] == ''):
                command = command[1:]
            if(command[-1] == ''):
                command = command[:-1]
            command = {
                'names' : command[0].split('<br>'),
                'syntax' : command[1].replace('<br><br>','\n'),
                'limits' : command[2].replace('<br>', '\n'),
                'description' : command[3].replace('<br>', '\n').replace('\\|', '|'),
                'examples' : command[4].replace('<br><br>', '\n').replace('\\|', '|')
            }

            if(command_name not in command['names']):
                continue
            embed = discord.Embed(title=command_name, description=command['description'], color=0x00FF00)
            embed.add_field(name='Syntax', value=command['syntax'], inline=False)
            if(command['limits'] != ''):
                embed.add_field(name='Min/Max Values', value=command['limits'], inline=False)
            if(command['syntax'] != command['examples']):
                embed.add_field(name='Examples', value=command['examples'], inline=False)
            if(len(command['names']) > 1):
                aliases = list(filter(lambda x : x != command_name, command['names']))
                aliases = ', '.join(aliases)
                footer_text = 'Alternative command name'
                if(len(command['names']) > 2):
                    footer_text += 's:\n'
                else:
                    footer_text += ': '
                footer_text += aliases
                embed.set_footer(text=footer_text)
            
            await ctx.response.send_message(embed=embed)
            break

        if(embed is None):
            await ctx.response.send_message("Command not found. Please use /help to see a list of commands.")
    # TODO: make this automatic in video_creator.py
    @commands.command()
    async def img2vid(self, ctx):
        await video_creator.set_progress_bar(ctx.message, 0)
        input_filepath = media_cache.get_from_cache(str(ctx.message.channel.id))[-1]
        output_filename = 'vids/discord-' + str(ctx.message.id) + '.mp4'
        await video_creator.set_progress_bar(ctx.message, 1)

        await video_creator.set_progress_bar(ctx.message, 2)
        subprocess.run([
            'ffmpeg',
            '-loop', '1',
            '-i', f'{input_filepath}',
            '-t', '1',
            output_filename
        ])
        await video_creator.set_progress_bar(ctx.message, 3)
        if(os.path.isfile(output_filename)):
            await ctx.send(file=discord.File(output_filename))
            os.remove(output_filename)
        else:
            await ctx.send(f'There was an error converting the image (`{input_filepath}`) to a video.')
        await ctx.message.clear_reactions()


    @commands.command()
    async def link(self, ctx):
        vid_link = media_cache.get_from_cache(str(ctx.message.channel.id))[0]
        await ctx.send(f'`{vid_link}`')


    
    async def _mp3(self, ctx, vstream, astream, kwargs):
        return (vstream, astream, {})
    @commands.command()
    async def mp3(self, ctx):
        await video_creator.apply_filters_and_send(ctx, self._mp3, {'is_mp3':True})
    

    @commands.command()
    async def swap(self, ctx):
        channel_id = str(ctx.channel.id)
        vids = list(db.vids.find({'channel':channel_id}).sort('_id', -1).limit(2))
        if(len(vids) < 2):
            await ctx.send("I don't see two videos to swap.")
            return
        new_vid, old_vid = vids

        await ctx.send(old_vid['url'])
        old_vid_msg = await ctx.fetch_message(int(old_vid['message_id']))
        
    
    async def _timestamp(self, ctx, vstream, astream, kwargs):
        speed_change = kwargs['speed_change']
        vstream = (
            vstream
            .filter('fps', fps=100)
            .filter('scale', w=480, h=-2)
            .drawtext(
                text="%{pts}",
                #x="main_w/2 - tw/2", y="main_h/2 - th/2",
                x="15", y="main_h - th*2 - 35",
                fontsize=40, fontcolor="white", fontfile="fonts/arial.ttf", borderw=2, bordercolor="black",
                escape_text=False
            )
        )
        if(speed_change != 1.0):
            vstream, astream = filter_helper.apply_speed(vstream, astream, speed_change)
        return vstream, astream, {}
    @commands.command()
    async def timestamp(self, ctx, speed_change : float = 1.0):
        await video_creator.apply_filters_and_send(ctx, self._timestamp, {'is_ignored_mp4':True, 'speed_change':speed_change})
    @commands.command()
    async def time(self, ctx, speed_change : float = 1.0):
        await self.timestamp(ctx, speed_change)

    
    @commands.command()
    async def undo(self, ctx):
        # Limiting to 2 so that you don't undo/delete the last video gman can use
        vid_msg_id = list(db.vids.find({'channel':str(ctx.channel.id)}).sort('_id', -1).limit(2))
        #await ctx.send(vid_msg_id)
        if(len(vid_msg_id) <= 1):
            await ctx.send("Out of undos!")
            return
        vid_msg_id = vid_msg_id[0]['message_id']
        
        vid_to_undo = await ctx.fetch_message(int(vid_msg_id))
        await vid_to_undo.delete()
        await ctx.message.delete()
        db.vids.delete_one({'message_id': vid_msg_id})
    
    @commands.command()
    async def ping(self, ctx):
        if round(self.bot.latency * 1000) <= 50:
            embed = discord.Embed(title="Bot latency", description=f"Pong! Latency is {round(self.bot.latency * 1000)} ms", color=0x00FF00)
        elif round(self.bot.latency * 1000) <= 100:
            embed = discord.Embed(title="Bot latency", description=f"Pong! Latency is {round(self.bot.latency * 1000)} ms", color=0xFFFF00)
        elif round(self.bot.latency * 1000) <= 200:
            embed = discord.Embed(title="Bot latency", description=f"Pong! Latency is {round(self.bot.latency * 1000)} ms", color=0xFF8000)
        else:
            embed = discord.Embed(title="Bot latency", description=f"Pong! Latency is {round(self.bot.latency * 1000)} ms", color=0xFF0000)
        await ctx.send(embed=embed)
    @app_commands.command(name="ping", description="Get G-Man's latency.")
    @app_commands.user_install()
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def _ping(self, ctx: discord.Interaction):
        if round(self.bot.latency * 1000) <= 50:
            embed = discord.Embed(title="Bot latency", description=f"Pong! Latency is {round(self.bot.latency * 1000)} ms", color=0x00FF00)
        elif round(self.bot.latency * 1000) <= 100:
            embed = discord.Embed(title="Bot latency", description=f"Pong! Latency is {round(self.bot.latency * 1000)} ms", color=0xFFFF00)
        elif round(self.bot.latency * 1000) <= 200:
            embed = discord.Embed(title="Bot latency", description=f"Pong! Latency is {round(self.bot.latency * 1000)} ms", color=0xFF8000)
        else:
            embed = discord.Embed(title="Bot latency", description=f"Pong! Latency is {round(self.bot.latency * 1000)} ms", color=0xFF0000)
        await ctx.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Utility(bot))
