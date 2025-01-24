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
import asyncpg
import discord
from discord import app_commands
from discord.ext import commands
import media_cache
import os
import re
import sys
import traceback
from urllib.parse import urlparse




# If any videos were not deleted while the bot was last up, remove them
vid_files = [f for f in os.listdir('vids') if os.path.isfile(os.path.join('vids', f))]
for f in vid_files:
    os.remove(f'vids/{f}')


extensions = ['cogs.audio', 'cogs.help', 'cogs.ping', 'cogs.bitrate', 'cogs.filter', 'cogs.fun', 'cogs.corruption', 'cogs.bookmarks', 'cogs.utility', 'cogs.caption', 'cogs.exif', 'cogs.ffmpeg', 'cogs.imagemagick', 'cogs.ytdlp', 'cogs.info']
bot = commands.Bot(command_prefix=commands.when_mentioned_or('!'), status=discord.Status.online, activity=discord.Game(name="!help"), help_command=None, intents=discord.Intents.all())


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


@bot.before_invoke
async def check_access(ctx: commands.Context):
    try:
        is_admin = ctx.author.guild_permissions.administrator
        roles = [role.id for role in ctx.author.roles]
    except AttributeError:
        is_admin = False
        roles = []
    user_id = ctx.author.id
    channel_id = ctx.channel.id
    guild_id = ctx.guild.id if ctx.guild else None
    if is_admin or str(user_id) in bot_info.data['owners']:
        return
    async with bot.db.acquire() as conn:
        allowlist_active = await conn.fetchval("SELECT EXISTS (SELECT 1 FROM allowlist)")
        if allowlist_active:
            is_allowed = await conn.fetchval("SELECT 1 FROM allowlist WHERE (type = 'user' AND entity_id = $1) OR (type = 'channel' AND entity_id = $2) OR (type = 'role' AND entity_id = ANY($3))", user_id, channel_id, roles)
            if not is_allowed:
                await ctx.send("Command blocked. Either you, one of your roles, or this channel is not part of the allowlist.")
                raise commands.CheckFailure("User/Channel/Role is not allowed.")
        global_blocked = await conn.fetchval("SELECT reason FROM global_blocked_users WHERE discord_id = $1", user_id)
        if global_blocked:
            await ctx.send(f"You are globally blocked from using G-Man. Reason: `{global_blocked}`")
            raise commands.CheckFailure("User is globally blocked.")
        if guild_id:
            server_blocked = await conn.fetchval("SELECT reason FROM global_blocked_servers WHERE guild_id = $1", guild_id)
            if server_blocked:
                await ctx.send(f"This server is globally blocked from using G-Man. Reason: `{server_blocked}`")
                raise commands.CheckFailure("Server is globally blocked.")
        allowed = await conn.fetchval("SELECT 1 FROM allowlist WHERE (type = 'user' AND entity_id = $1) OR (type = 'channel' AND entity_id = $2) OR (type = 'role' AND entity_id = ANY($3))", user_id, channel_id, roles)
        if allowed:
            return
        blocked = await conn.fetchval("SELECT reason FROM blocklist WHERE (type = 'user' AND entity_id = $1) OR (type = 'channel' AND entity_id = $2) OR (type = 'role' AND entity_id = ANY($3))", user_id, channel_id, roles)
        if blocked:
            await ctx.send(f"Command blocked. Either you, one of your roles, or this channel is part of the blocklist. Reason: `{blocked}`")
            raise commands.CheckFailure("User/Channel/Role is blocked.")
    
    
    
    
# Set up stuff
@bot.event
async def on_ready():
    logger = logging.getLogger()
    global extensions
    try:
        logger.info(await reload_extensions(extensions))
    except Exception as e:
        logger.error(f"Error reloading extensions: {e}")
    try:
        bot.db = await asyncpg.create_pool(bot_info.data['database'])
        logger.info(f"Connected to PostgreSQL database via {bot_info.data['database']}")
    except Exception as e:
        logger.error(f"Error connecting to PostgreSQL database: {e}")
    logger.info(f"Bot {bot.user.name} has successfully logged in via Token {bot_info.data['login']}. ID: {bot.user.id}")
    logger.info(f"Bot {bot.user.name} is in {len(bot.guilds)} guilds, caching a total of {sum(1 for _ in bot.get_all_channels())} channels and {len(bot.users)} users.")
    logger.info(f"Bot {bot.user.name} has a total of {len(bot.commands)} commands with {len(bot.cogs)} cogs.")

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
    if isinstance(error, commands.MissingPermissions):
        logger.warning(f"Missing permissions for command {ctx.command.qualified_name}: {ctx.message.content} ({error})")
        await ctx.send(f"{ctx.command.qualified_name} requires the following permissions: {', '.join(error.missing_permissions)}")
        return
    if str(ctx.author.id) not in bot_info.data['owners']:
        logger.warning(f"{ctx.author.name} is not a bot owner: {ctx.message.content}")
        await ctx.send("You are not a bot owner.")
        return
    if isinstance(error, commands.CheckFailure):
        logger.warning(f"Check failed for command {ctx.command.qualified_name}: {ctx.message.content} ({error})")
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


@bot.command(name="block", description="Blocks a user, channel, or role from using the bot.")
@commands.check(lambda ctx: str(ctx.author.id) in bot_info.data['owners'] or ctx.author.guild_permissions.administrator)
async def block(ctx: commands.Context, type: str, type_id: int, *, reason="No reason provided"):
    valid_types = ["global", "user", "channel", "role", "server"]
    if type_id == ctx.author.id:
        await ctx.send("You can't block yourself.")
        return
    if type not in ["global", "user", "channel", "role", "server"]:
        await ctx.send(f"Invalid type. Valid types: {', '.join(valid_types)}")
        return
    if type in ["global", "server"] and str(ctx.author.id) not in bot_info.data['owners']:
        await ctx.send(f"{type.capitalize()} blocks can only be set by bot owners.")
        return
    async with bot.db.acquire() as conn:
        if type == "server":
            exists = await conn.fetchval("SELECT EXISTS (SELECT 1 FROM global_blocked_servers WHERE guild_id = $1)", type_id)
            if exists:
                await ctx.send("This server is already globally blocked.")
                return
            await conn.execute("INSERT INTO global_blocked_servers (guild_id, reason) VALUES ($1, $2) ON CONFLICT (guild_id) DO UPDATE SET reason = $2", type_id, reason)
            await ctx.send(f"Globally blocked server with ID {type_id}. Reason: `{reason}`")
        elif type == "global":
            exists = await conn.fetchval("SELECT EXISTS (SELECT 1 FROM global_blocked_users WHERE discord_id = $1)", type_id)
            if exists:
                await ctx.send("This user is already globally blocked.")
                return
            await conn.execute("INSERT INTO global_blocked_users (discord_id, reason) VALUES ($1, $2) ON CONFLICT (discord_id) DO UPDATE SET reason = $2", type_id, reason)
            await ctx.send(f"Globally blocked user with ID {type_id}. Reason: `{reason}`")
        else:
            exists = await conn.fetchval("SELECT EXISTS (SELECT 1 FROM blocklist WHERE type = $1 AND entity_id = $2)", type, type_id)
            if exists:
                await ctx.send(f"{type.capitalize()} with ID {type_id} is already blocked.")
                return
            await conn.execute("INSERT INTO blocklist (type, entity_id, reason) VALUES ($1, $2, $3) ON CONFLICT (type, entity_id) DO UPDATE SET reason = $3", type, type_id, reason)
            await ctx.send(f"Blocked {type} with ID {type_id}. Reason: `{reason}`")

@bot.command(name="unblock", description="Unblocks a user, channel, or role from using the bot.")
@commands.check(lambda ctx: str(ctx.author.id) in bot_info.data['owners'] or ctx.author.guild_permissions.administrator)
async def unblock(ctx: commands.Context, type: str, type_id: int):
    valid_types = ["global", "user", "channel", "role", "server"]
    if type not in valid_types:
        await ctx.send(f"Invalid type. Valid types: {', '.join(valid_types)}")
        return
    if type in ["global", "server"] and str(ctx.author.id) not in bot_info.data['owners']:
        await ctx.send(f"{type.capitalize()} blocks can only be removed by bot owners.")
        return
    async with bot.db.acquire() as conn:
        if type == "server":
            result = await conn.execute("DELETE FROM global_blocked_servers WHERE guild_id = $1", type_id)
            if result == "DELETE 0":
                await ctx.send("This server is not globally blocked.")
                return
            else:
                await ctx.send(f"Unblocked server with ID {type_id}.")
        elif type == "global":
            result = await conn.execute("DELETE FROM global_blocked_users WHERE discord_id = $1", type_id)
            if result == "DELETE 0":
                await ctx.send("This user is not globally blocked.")
                return
            else:
                await ctx.send(f"Unblocked user with ID {type_id}.")
        else:
            result = await conn.execute("DELETE FROM blocklist WHERE type = $1 AND entity_id = $2", type, type_id)
            if result == "DELETE 0":
                await ctx.send(f"{type.capitalize()} with ID {type_id} is not blocked.")
                return
            else:    
                await ctx.send(f"Unblocked {type} with ID {type_id}.")

@bot.command(name="allow", description="Allows a user, channel, or role to use the bot.")
@commands.check(lambda ctx: str(ctx.author.id) in bot_info.data['owners'] or ctx.author.guild_permissions.administrator)
async def allow(ctx: commands.Context, type: str, type_id: int, *, reason="No reason provided"):
    valid_types = ["user", "channel", "role"]
    if type not in valid_types:
        await ctx.send("Invalid type. Valid types: `user`, `channel`, or `role`.")
        return
    async with bot.db.acquire() as conn:
        exists = await conn.fetchval("SELECT EXISTS (SELECT 1 FROM allowlist WHERE type = $1 AND entity_id = $2)", type, type_id)
        if exists:
            await ctx.send(f"{type.capitalize()} with ID {type_id} is already allowed.")
            return
        await conn.execute("INSERT INTO allowlist (type, entity_id, reason) VALUES ($1, $2, $3) ON CONFLICT (type, entity_id) DO NOTHING", type, type_id, reason)
    await ctx.send(f"Allowed {type} with ID {type_id}. Reason: `{reason}`")

@bot.command(name="deny", description="Denies a user, channel, or role from using the bot. (Not to be confused with `block`.)")
@commands.check(lambda ctx: str(ctx.author.id) in bot_info.data['owners'] or ctx.author.guild_permissions.administrator)
async def deny(ctx: commands.Context, type: str, type_id: int):
    valid_types = ["user", "channel", "role"]
    if type not in valid_types:
        await ctx.send("Invalid type. Valid types: `user`, `channel`, or `role`.")
        return
    async with bot.db.acquire() as conn:
        exists = await conn.fetchval("SELECT EXISTS (SELECT 1 FROM allowlist WHERE type = $1 AND entity_id = $2)", type, type_id)
        if not exists:
            await ctx.send(f"{type.capitalize()} with ID {type_id} is not allowed.")
            return
        await conn.execute("DELETE FROM allowlist WHERE type = $1 AND entity_id = $2", type, type_id)
    await ctx.send(f"Denied {type} with ID {type_id}.")

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
@app_commands.allowed_installs(guilds=True, users=True)
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
