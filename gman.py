import asyncio
import contextlib
import io
import textwrap
import bot_info
import database as db
import discord
from discord.ext import commands
from discord.ext.buttons import Paginator
import media_cache
import os
import re
import sys
import traceback
from urllib.parse import urlparse

class Pag(Paginator):
    async def teardown(self):
        try:
            await self.page.clear_reactions()
        except discord.HTTPException:
            pass

# If any videos were not deleted while the bot was last up, remove them
vid_files = [f for f in os.listdir('vids') if os.path.isfile(os.path.join('vids', f))]
for f in vid_files:
    os.remove(f'vids/{f}')


extensions = ['cogs.bitrate', 'cogs.filter', 'cogs.fun', 'cogs.corruption', 'cogs.bookmarks', 'cogs.utility']
bot = commands.Bot(command_prefix=commands.when_mentioned_or('!'), help_command=None, intents=discord.Intents.all())

# Loads extensions, returns string saying what reloaded
async def reload_extensions(exs):
    module_msg = ''
    for ex in exs:
        try:
           #await bot.unload_extension(ex)
           await bot.load_extension(ex)
           module_msg += 'module "{}" reloaded\n'.format(ex)
        except Exception as e:
            module_msg += 'reloading "{}" failed, error is:```{}```\n'.format(ex, e)
    return module_msg

    
    
    
    
# Set up stuff
@bot.event
async def on_ready():
    print('Logged in as')
    print(bot.user.name)
    print(bot.user.id)
    print('------')
    await bot.change_presence(activity=discord.Game(name="!help"))
    global extensions
    print(await reload_extensions(extensions))

# Process commands
@bot.event
async def on_message(message):
    # Adding URLs to the cache
    if(len(message.attachments) > 0):
        print(message.attachments[0].url)
        msg_url = message.attachments[0].url
        parsed_url = urlparse(msg_url)
        url_path = parsed_url.path
        if(not url_path.endswith('_ignore.mp4') and url_path.split('.')[-1].lower() in media_cache.approved_filetypes):
            media_cache.add_to_cache(message, msg_url)
            print("Added file!")
    elif(re.match(media_cache.discord_cdn_regex, message.content) or re.match(media_cache.hosted_file_regex, message.content)):
        media_cache.add_to_cache(message, message.content)
        print("Added discord cdn/hosted file url!")
    elif(re.match(media_cache.yt_regex, message.content) or re.match(media_cache.twitter_regex, message.content) or re.match(media_cache.tumblr_regex, message.content) or re.match(media_cache.medaltv_regex, message.content)):
        media_cache.add_to_cache(message, message.content)
        print("Added yt/twitter/tumblr url! " + message.content)
    elif(re.match(media_cache.soundcloud_regex, message.content) or re.match(media_cache.bandcamp_regex, message.content)):
        media_cache.add_to_cache(message, message.content)
        print("Added soundcloud/bandcamp url! " + message.content)

    await bot.process_commands(message)

# Forgetting videos that get deleted
@bot.event
async def on_message_delete(message):
    db.vids.delete_one({'message_id':str(message.id)})

# Command error
@bot.event
async def on_command_error(ctx, error):
    if(not isinstance(error, commands.CommandNotFound)):
        await ctx.send('Oops, something is wrong!\n```\n' + repr(error) + '\n```')
        #print(error)
        traceback.print_exception(type(error), error, error.__traceback__, file=sys.stderr)
    
# Reloading extensions
@bot.command(description='Reloads extensions. Usage: /reload [extension_list]', pass_context=True)
@bot_info.is_owner()
async def reload(ctx, *, exs : str = None):
    if(str(ctx.message.author.id) not in bot_info.data['owners']):
        await ctx.send("Error using command: You do not have permission to use this command. (Are you owner?)")
        return
    else:
    module_msg = 'd' # d
    if(exs is None):
        module_msg = await reload_extensions(extensions)
    else:
        module_msg = await reload_extensions(exs.split())
    await ctx.send(module_msg)
async def setup(bot):
 for ex in extensions:
    try:
        await bot.load_extension(ex)
    except Exception as e:
        print('Failed to load {} because: {}'.format(ex, e))

@bot.command(name="eval", aliases=["exec", "code"])
@bot_info.is_owner()
async def _eval(ctx, *, code):
    if(str(ctx.message.author.id) not in bot_info.data['owners']):
        await ctx.send("Error using command: You do not have permission to use this command. (Are you owner?)")
        return
    else:
    code = clean_code(code)

    local_variables = {
        "discord": discord,
        "commands": commands,
        "bot": bot,
        "client": bot,
        "ctx": ctx,
        "context": ctx,
        "channel": ctx.channel,
        "author": ctx.author,
        "guild": ctx.guild,
        "message": ctx.message

    }

    stdout = io.StringIO()
    
    try:
        with contextlib.redirect_stdout(stdout):
            exec(
                f"async def func():\n{textwrap.indent(code, '    ')}", local_variables,
            )

            obj = await local_variables["func"]()
            result = f'{stdout.getvalue()}\n-- {obj}\n'
    except Exception as e:
        result = "".join(traceback.format_exception(e, e, e.__traceback__))
    
    pager = Pag(
        timeout=100,
        entries=[result[i: i + 2000] for i in range(0, len(result), 2000)],
        length=1,
        prefix="```py\n",
        suffix="```",
        color=discord.colour
    )

    await pager.start(ctx)

def clean_code(content):
    if(content.startswith("```") and content.endswith("```")):
        return "\n".join(content.split("\n")[1:][:-3])
    else:
        return content


# Start the bot
bot.run(bot_info.data['login'])
