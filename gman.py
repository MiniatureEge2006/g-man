import asyncio
import contextlib
import io
import textwrap
import bot_info
import json
import datetime
import logging
import colorlog
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


extensions = ['cogs.audio', 'cogs.help', 'cogs.ping', 'cogs.bitrate', 'cogs.filter', 'cogs.fun', 'cogs.corruption', 'cogs.bookmarks', 'cogs.utility', 'cogs.caption', 'cogs.exif', 'cogs.ffmpeg', 'cogs.imagemagick', 'cogs.ytdlp', 'cogs.info']
bot = commands.Bot(command_prefix=commands.when_mentioned_or('!'), status=discord.Status.online, activity=discord.Game(name="!help"), help_command=None, intents=discord.Intents.all())

bot.blacklisted_users = []

def setup_logger():
    log_format = "%(log_color)s%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    logger = logging.getLogger()
    handler = logging.StreamHandler()
    formatter = colorlog.ColoredFormatter(log_format)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Loads extensions, returns string saying what reloaded
async def reload_extensions(exs):
    module_msg = ''
    for ex in exs:
        try:
            if ex in bot.extensions:
                await bot.unload_extension(ex)
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
    logger = logging.getLogger()
    global extensions
    try:
        logger.info(await reload_extensions(extensions))
    except Exception as e:
        logger.error(f"Error reloading extensions: {e}")
    logger.info(f"Bot {bot.user.name} has successfully logged in via Token {bot_info.data['login']}. ID: {bot.user.id}")
    logger.info(f"Bot {bot.user.name} is in {len(bot.guilds)} guilds.")
    logger.info(f"Bot {bot.user.name} has a total of {len(bot.commands)} commands with {len(bot.cogs)} cogs.")
    logger.info(f"Bot {bot.user.name} has cached a number of {len(bot.users)} users.")
    data = read_json("blacklistedusers")
    bot.blacklisted_users = data["blacklistedUsers"]

# Process commands
@bot.event
async def on_message(message):
    logger = logging.getLogger()
    # Adding URLs to the cache
    if(len(message.attachments) > 0):
        logger.info(message.attachments[0].url)
        msg_url = message.attachments[0].url
        parsed_url = urlparse(msg_url)
        url_path = parsed_url.path
        if(not url_path.endswith('_ignore.mp4') and url_path.split('.')[-1].lower() in media_cache.approved_filetypes):
            media_cache.add_to_cache(message, msg_url)
            logger.info("Added file!")
    elif(re.match(media_cache.discord_cdn_regex, message.content) or re.match(media_cache.hosted_file_regex, message.content)):
        media_cache.add_to_cache(message, message.content)
        logger.info("Added discord cdn/hosted file url!")
    elif(re.match(media_cache.yt_regex, message.content) or re.match(media_cache.twitter_regex, message.content) or re.match(media_cache.tumblr_regex, message.content) or re.match(media_cache.medaltv_regex, message.content) or re.match(media_cache.archive_regex, message.content)):
        media_cache.add_to_cache(message, message.content)
        logger.info("Added yt/twitter/tumblr url! " + message.content)
    elif(re.match(media_cache.soundcloud_regex, message.content) or re.match(media_cache.bandcamp_regex, message.content)):
        media_cache.add_to_cache(message, message.content)
        logger.info("Added soundcloud/bandcamp url! " + message.content)

    await bot.process_commands(message)

@bot.event
async def on_command(ctx):
    logger = logging.getLogger()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user = f"{ctx.author.name}#{ctx.author.discriminator} (ID: {ctx.author.id})"
    guild = f"{ctx.guild.name} (ID: {ctx.guild.id})" if ctx.guild else "DMs"
    channel = f"{ctx.channel.name} (ID: {ctx.channel.id})" if ctx.guild else f"DMs with {ctx.author.name}#{ctx.author.discriminator} (ID: {ctx.author.id})"
    command_name = ctx.command.qualified_name
    command_content = ctx.message.content
    log_message = (
        f"\n--- Command Log ---\n"
        f"Timestamp: {timestamp}\n"
        f"User: {user}\n"
        f"Guild: {guild}\n"
        f"Channel: {channel}\n"
        f"Command: {command_name}\n"
        f"Command Content: {command_content}\n"
        f"--- End Command Log ---"
    )
    logger.info(log_message)

# Forgetting videos that get deleted
@bot.event
async def on_message_delete(message):
    db.vids.delete_one({'message_id':str(message.id)})

# Command error
@bot.event
async def on_command_error(ctx, error):
    logger = logging.getLogger()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user = f"{ctx.author.name}#{ctx.author.discriminator} (ID: {ctx.author.id})"
    guild = f"{ctx.guild.name} (ID: {ctx.guild.id})" if ctx.guild else "DMs"
    channel = f"{ctx.channel.name} (ID: {ctx.channel.id})" if ctx.guild else f"DMs with {ctx.author.name}#{ctx.author.discriminator} (ID: {ctx.author.id})"
    command_name = ctx.command.qualified_name if ctx.command else "Unknown"
    command_content = ctx.message.content
    logger.error(f"\n--- Command Error Log ---\nTimestamp: {timestamp}\nUser: {user}\nGuild: {guild}\nChannel: {channel}\nCommand: {command_name}\nCommand Content: {command_content}\nError: {error}\n--- End Command Error Log ---")
    if isinstance(error, commands.CommandNotFound):
        logger.warning(f"Command not found: {ctx.message.content}")
        return
    if isinstance(error, commands.MissingRequiredArgument):
        logger.warning(f"Missing required argument for command {ctx.command.qualified_name}: {ctx.message.content} ({error.param.name} is required)")
        await ctx.send(f"Missing required argument for command {ctx.command.qualified_name}. ({error.param.name} is required)")
        return
    if isinstance(error, commands.BadArgument):
        logger.warning(f"Bad argument for command {ctx.command.qualified_name}: {ctx.message.content} ({error})")
        await ctx.send(f"Bad argument for command {ctx.command.qualified_name}. ({error})")
        return
    if ctx.author.id in bot.blacklisted_users:
        logger.warning(f"User has been blocked from using the bot: {ctx.message.content}")
        await ctx.send("You are blocked from using G-Man. Please contact the bot owner if you think this is a mistake.")
        return
    if str(ctx.author.id) not in bot_info.data['owners']:
        logger.warning(f"User is not a bot owner: {ctx.message.content}")
        await ctx.send("You are not a bot owner.")
        return
    else:
        logger.critical(f"An unexpected error occurred: {error}")
    
    await ctx.send(f"An error occurred while processing your command. ```\n{error}```")
    
@bot.event
async def on_command_completion(ctx):
    logger = logging.getLogger()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user = f"{ctx.author.name}#{ctx.author.discriminator} (ID: {ctx.author.id})"
    guild = f"{ctx.guild.name} (ID: {ctx.guild.id})" if ctx.guild else "DMs"
    channel = f"{ctx.channel.name} (ID: {ctx.channel.id})" if ctx.guild else f"DMs with {ctx.author.name}#{ctx.author.discriminator} (ID: {ctx.author.id})"
    command_name = ctx.command.qualified_name
    command_content = ctx.message.content
    logger.info(f"\n--- Command Success ---\nTimestamp: {timestamp}\nUser: {user}\nGuild: {guild}\nChannel: {channel}\nCommand: {command_name}\nCommand Content: {command_content}\n--- End Command Success ---")

@bot.event
async def on_guild_join(guild):
    logger = logging.getLogger()
    logger.info(f"Joined guild {guild.name} (ID: {guild.id})")

@bot.event
async def on_guild_remove(guild):
    logger = logging.getLogger()
    logger.info(f"Removed from guild {guild.name} (ID: {guild.id})")

@bot.event
async def on_guild_update(before, after):
    logger = logging.getLogger()
    logger.info(f"Guild updated: {before} -> {after}")

@bot.event
async def on_guild_unavailable(guild):
    logger = logging.getLogger()
    logger.info(f"Guild unavailable: {guild.name} (ID: {guild.id})")

@bot.event
async def on_guild_available(guild):
    logger = logging.getLogger()
    logger.info(f"Guild available: {guild.name} (ID: {guild.id})")


@bot.command()
@bot_info.is_owner()
async def sync(ctx: commands.Context):
    logger = logging.getLogger()
    message = await ctx.send("Syncing slash commands...")
    try:
        await bot.tree.sync()
    except Exception as e:
        logger.error(f"Error syncing slash commands: {e}")
        await message.edit(content=f"Error syncing slash commands: {e}")
    await message.edit(content="Slash commands synced.")
    logger.info("Slash commands synced.")


@bot.command()
@bot_info.is_owner()
async def block(ctx: commands.Context, user: discord.User, *, reason = "No reason provided."):
     if ctx.message.author.id == user.id:
        await ctx.send("Don't block yourself.")
        return
     bot.blacklisted_users.append(user.id)
     data = read_json("blacklistedusers")
     data["blacklistedUsers"].append(user.id)
     write_json(data, "blacklistedusers")
     await ctx.send(f"Blocked {user.name}. Reason: `{reason}`")

@bot.command()
@bot_info.is_owner()
async def unblock(ctx: commands.Context, user: discord.User):
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
@app_commands.describe(code="The code to evaluate.")
@app_commands.user_install()
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@bot_info.is_owner()
async def eval(ctx, *, code):
    logger = logging.getLogger()
    code = cleanup_code(code)
    result = None

    env = {
        "discord": discord,
        "commands": commands,
        "bot": bot,
        "client": bot,
        "ctx": ctx,
        "context": ctx,
        "send": ctx.send,
        "reply": ctx.reply,
        "channel": ctx.channel,
        "voice": ctx.voice_client,
        "vc": ctx.voice_client,
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
            logger.error(f"Error evaluating code: {e}")
            return
    func = env['func']
    try:
        with contextlib.redirect_stdout(stdout):
            ret = await func()
    except Exception as e:
        result = stdout.getvalue()
        result = result[:2000]
        await ctx.send(embed=discord.Embed(title="Eval Error", description=f'```py\n{result}{traceback.format_exc()}\n```', color=discord.Color.red()))
        logger.error(f"Error evaluating code: {e}")
    else:
        result = stdout.getvalue()
        result = result[:2000]
        await ctx.send(embed=discord.Embed(title="Eval", description=f'```py\n{result}\n-- {ret}```', color=discord.Color.og_blurple()))
        logger.info(f"Evaluated code: {code}")

def cleanup_code(content: str) -> str:
    if content.startswith('```') and content.endswith('```'):
        content = content[3:-3].strip()

        if ' ' in content or '\n' in content:
            first_space_or_newline = content.find(' ')
            first_newline = content.find('\n')
            if first_space_or_newline == -1 or (0 <= first_newline < first_space_or_newline):
                first_space_or_newline = first_newline
            if first_space_or_newline > -1:
                content = content[first_space_or_newline:].strip()
        else:
            content = content.lstrip("abcdefghijklmnopqrstuvwxyz")
    return content.strip()

def read_json(filename):
    with open(f"{filename}.json", "r") as file:
        data = json.load(file)
        return data

def write_json(data, filename):
    with open(f"{filename}.json", "w") as file:
        json.dump(data, file)

setup_logger()

# Start the bot
bot.run(bot_info.data['login'], log_handler=None)
