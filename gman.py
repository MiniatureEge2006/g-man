import asyncio
import contextlib
import io
import textwrap
import bot_info
import json
import database as db
import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import CheckFailure
import media_cache
import os
import re
import sys
import traceback
from urllib.parse import urlparse


class Blacklisted(CheckFailure):
    pass


# If any videos were not deleted while the bot was last up, remove them
vid_files = [f for f in os.listdir('vids') if os.path.isfile(os.path.join('vids', f))]
for f in vid_files:
    os.remove(f'vids/{f}')


extensions = ['cogs.bitrate', 'cogs.filter', 'cogs.fun', 'cogs.corruption', 'cogs.bookmarks', 'cogs.utility']
bot = commands.Bot(command_prefix=commands.when_mentioned_or('!'), help_command=None, intents=discord.Intents.all())

bot.blacklisted_users = []

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


@bot.check
async def blacklist_detector(ctx):
    if ctx.message.author.id in bot.blacklisted_users:
        raise Blacklisted("User has been blacklisted from using the bot")
    else:
        return True
    
    
    
    
# Set up stuff
@bot.event
async def on_ready():
    print('Logged in as')
    print(bot.user.name)
    print(bot.user.id)
    print('------')
    data = read_json("blacklistedusers")
    bot.blacklisted_users = data["blacklistedUsers"]
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
    elif(re.match(media_cache.yt_regex, message.content) or re.match(media_cache.twitter_regex, message.content) or re.match(media_cache.tumblr_regex, message.content) or re.match(media_cache.medaltv_regex, message.content) or re.match(media_cache.archive_regex, message.content)):
        media_cache.add_to_cache(message, message.content)
        print("Added yt/twitter/tumblr url! " + message.content)
    elif(re.match(media_cache.soundcloud_regex, message.content) or re.match(media_cache.bandcamp_regex, message.content)):
        media_cache.add_to_cache(message, message.content)
        print("Added soundcloud/bandcamp url! " + message.content)

    await bot.process_commands(message)

@bot.event
async def on_command(ctx):
    if isinstance(ctx.message.channel, discord.DMChannel):
        print(f'User {ctx.message.author} ({ctx.message.author.id}) used command {ctx.command} in {bot.user.name}\'s ({bot.user.id}) DMs')
    else:
        print(f'User {ctx.message.author} ({ctx.message.author.id}) used command {ctx.command} in guild {ctx.guild} ({ctx.guild.id}) at #{ctx.channel} ({ctx.channel.id})')

# Forgetting videos that get deleted
@bot.event
async def on_message_delete(message):
    db.vids.delete_one({'message_id':str(message.id)})

# Command error
@bot.event
async def on_command_error(ctx, error):
    if(isinstance(error, commands.CommandInvokeError)):
        print(error)
        return
    if(isinstance(error, commands.CommandNotFound)):
        return
    if(ctx.message.author.id in bot.blacklisted_users):
        await ctx.send("You are blocked from using G-Man.")
        return
    if(str(ctx.message.author.id) not in bot_info.data['owners']):
        await ctx.send("You do not have permission to run this command.")
        return
    else:
        if(not isinstance(error, commands.CommandNotFound)):
            await ctx.send('Oops, something is wrong!\n```\n' + repr(error) + '\n```')
        #print(error)
        traceback.print_exception(type(error), error, error.__traceback__, file=sys.stderr)

@bot.command()
@bot_info.is_owner()
async def sync(ctx):
    await ctx.send("ok")
    await bot.tree.sync()
    print("Commands synced!")


@bot.command()
@bot_info.is_owner()
async def block(ctx, user: discord.User, *, reason):
     if ctx.message.author.id == user.id:
        await ctx.send("Don't block yourself dummy")
        return
     bot.blacklisted_users.append(user.id)
     data = read_json("blacklistedusers")
     data["blacklistedUsers"].append(user.id)
     write_json(data, "blacklistedusers")
     await ctx.send(f"Blocked {user.name}. Reason: `{reason}`")

@bot.command()
@bot_info.is_owner()
async def unblock(ctx, user: discord.User):
     bot.blacklisted_users.remove(user.id)
     data = read_json("blacklistedusers")
     data["blacklistedUsers"].remove(user.id)
     write_json(data, "blacklistedusers")
     await ctx.send(f"Unblocked {user.name}.")

# Reloading extensions
@bot.command(description='Reloads extensions. Usage: /reload [extension_list]', pass_context=True)
@bot_info.is_owner()
async def reload(ctx, *, exs : str = None):
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

@bot.hybrid_command(name="eval", description="Evaluate code.", aliases=["exec", "code"])
@app_commands.user_install()
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot_info.is_owner()
async def eval(ctx, *, code):
    code = cleanup_code(code)
    result = None

    env = {
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
    env.update(globals())
    stdout = io.StringIO()
    
    to_compile = f'async def func():\n{textwrap.indent(code, "  ")}'
    
    try:
        exec(to_compile, env)
    except Exception as e:
            result = result[:2000]
            await ctx.send(embed=discord.Embed(title="Eval Error", description=f'```py\n{result}{traceback.format_exc()}\n```', color=discord.Color.red()))
            return
    func = env['func']
    try:
        with contextlib.redirect_stdout(stdout):
            ret = await func()
    except Exception as e:
        result = stdout.getvalue()
        result = result[:2000]
        await ctx.send(embed=discord.Embed(title="Eval Error", description=f'```py\n{result}{traceback.format_exc()}\n```', color=discord.Color.red()))
    else:
        result = stdout.getvalue()
        result = result[:2000]
        await ctx.send(embed=discord.Embed(title="Eval", description=f'```py\n{result}\n-- {ret}```', color=discord.Color.og_blurple()))

def cleanup_code(content: str) -> str:
    if content.startswith('```') and content.endswith('```'):
        return '\n'.join(content.split('\n')[1:-1])
    return content.strip(' \n')

def read_json(filename):
    with open(f"{filename}.json", "r") as file:
        data = json.load(file)
        return data

def write_json(data, filename):
    with open(f"{filename}.json", "w") as file:
        json.dump(data, file)


# Start the bot
bot.run(bot_info.data['login'])
