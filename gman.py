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
import random
from urllib.parse import urlparse




# If any videos were not deleted while the bot was last up, remove them
vid_files = [f for f in os.listdir('vids') if os.path.isfile(os.path.join('vids', f))]
for f in vid_files:
    os.remove(f'vids/{f}')

async def get_prefix(ctx: commands.Context):
    if ctx.guild is None:
        return bot_info.data['prefix']
    guild_id = ctx.guild.id
    async with bot.db.acquire() as conn:
        prefix = await conn.fetchrow("SELECT prefix FROM prefixes WHERE guild_id = $1", guild_id)
        if prefix:
            return prefix['prefix']
        return bot_info.data['prefix']

async def set_prefix(guild_id, prefix):
    async with bot.db.acquire() as conn:
        await conn.execute("INSERT INTO prefixes (guild_id, prefix) VALUES ($1, $2) ON CONFLICT (guild_id) DO UPDATE SET prefix = $2", guild_id, prefix)


extensions = ['cogs.audio', 'cogs.help', 'cogs.ping', 'cogs.bitrate', 'cogs.filter', 'cogs.fun', 'cogs.corruption', 'cogs.bookmarks', 'cogs.utility', 'cogs.caption', 'cogs.exif', 'cogs.ffmpeg', 'cogs.imagemagick', 'cogs.ytdlp', 'cogs.youtube', 'cogs.info', 'cogs.ai']
bot = commands.Bot(command_prefix=lambda bot, msg: get_prefix(msg), case_insensitive=True, strip_after_prefix=True, status=discord.Status.online, activity=discord.Game(name=f"{bot_info.data['prefix']}help"), help_command=None, intents=discord.Intents.all())


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
async def global_permissions_check(ctx: commands.Context):
    if str(ctx.author.id) in bot_info.data['owners'] or ctx.author.guild_permissions.administrator:
        return True
    return await command_permission_check(ctx)

async def command_permission_check(ctx: commands.Context) -> bool:
    async with bot.db.acquire() as conn:
        server_query = "SELECT status, reason FROM server_command_permissions WHERE guild_id = $1 AND command_name = $2"
        server_result = await conn.fetchrow(server_query, ctx.guild.id, ctx.command.name)
        if server_result:
            if not server_result["status"]:
                await ctx.send(f"Command blocked. This server disabled this command. Reason: `{server_result['reason']}`")
                return False
        block_query = "SELECT status, target_type, reason FROM command_permissions WHERE guild_id = $1 AND command_name = $2 AND ((target_type = 'user' AND target_id = $3) OR (target_type = 'channel' AND target_id = $4) OR (target_type = 'role' AND target_id = ANY($5::BIGINT[])))"
        role_ids = [role.id for role in ctx.author.roles]
        block_result = await conn.fetch(block_query, ctx.guild.id, ctx.command.name, ctx.author.id, ctx.channel.id, role_ids)
        for row in block_result:
            if not row["status"]:
                if row["target_type"] == "user":
                    await ctx.send(f"Command blocked. You are part of the command blocklist. Reason: `{row['reason']}`")
                elif row["target_type"] == "channel":
                    await ctx.send(f"Command blocked. This channel is part of the command blocklist. Reason: `{row['reason']}`")
                elif row["target_type"] == "role":
                    await ctx.send(f"Command blocked. One of your roles is part of the command blocklist. Reason: `{row['reason']}`")
                return False
        allow_query = "SELECT status, target_type, target_id, reason FROM command_permissions WHERE guild_id = $1 AND command_name = $2 AND status = TRUE"
        allow_result = await conn.fetch(allow_query, ctx.guild.id, ctx.command.name)
        if allow_result:
            allowed = False
            for row in allow_result:
                if row["target_type"] == "user" and ctx.author.id == row["target_id"]:
                    allowed = True
                elif row["target_type"] == "channel" and ctx.channel.id == row["target_id"]:
                    allowed = True
                elif row["target_type"] == "role" and row["target_id"] in role_ids:
                    allowed = True
            if not allowed:
                await ctx.send(f"Command blocked. Either you, this channel, or one of your roles are not part of the allowlist. Reason: `{row['reason']}`")
                return False
    return True

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
    async with bot.db.acquire() as conn:
        global_blocked = await conn.fetchval("SELECT reason FROM global_blocked_users WHERE discord_id = $1", user_id)
        if global_blocked:
            await ctx.send(f"You are globally blocked from using G-Man. Reason: `{global_blocked}`")
            raise commands.CheckFailure("User is globally blocked.")
        if guild_id:
            server_blocked = await conn.fetchval("SELECT reason FROM global_blocked_servers WHERE guild_id = $1", guild_id)
            if server_blocked:
                await ctx.send(f"This server is globally blocked from using G-Man. Reason: `{server_blocked}`")
                raise commands.CheckFailure("Server is globally blocked.")
        if str(user_id) in bot_info.data['owners']:
            return
        if is_admin:
            return
        allowlist_active = await conn.fetchval("SELECT EXISTS (SELECT 1 FROM allowlist)")
        if allowlist_active:
            is_allowed = await conn.fetchval("SELECT 1 FROM allowlist WHERE (type = 'user' AND entity_id = $1) OR (type = 'channel' AND entity_id = $2) OR (type = 'role' AND entity_id = ANY($3))", user_id, channel_id, roles)
            if not is_allowed:
                await ctx.send("You, this channel, or one of your roles are not part of the allowlist.")
                raise commands.CheckFailure("User/Channel/Role is not allowed.")
            if is_allowed:
                return
        blocked = await conn.fetchval("SELECT reason FROM blocklist WHERE (type = 'user' AND entity_id = $1) OR (type = 'channel' AND entity_id = $2) OR (type = 'role' AND entity_id = ANY($3))", user_id, channel_id, roles)
        if blocked:
            await ctx.send(f"You, this channel, or one of your roles are part of the blocklist. Reason: `{blocked}`")
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
    embed = discord.Embed(title="Command Error", color=discord.Color.red(), timestamp=discord.utils.utcnow())
    embed.set_author(name=f"{ctx.author.name}#{ctx.author.discriminator}", icon_url=ctx.author.display_avatar.url, url=f"https://discord.com/users/{ctx.author.id}")
    if isinstance(error, commands.CheckFailure):
        return
    if isinstance(error, commands.CommandNotFound):
        logger.warning(f"Command not found: {ctx.message.content}")
        return
    if isinstance(error, commands.MissingRequiredArgument):
        logger.warning(f"Missing required argument for command {ctx.command.qualified_name}: {ctx.message.content} ({error.param.name} is required)")
        embed.description = f"Missing required argument: `{error.param.name}`"
        await ctx.send(embed=embed)
        return
    if isinstance(error, commands.BadArgument):
        logger.warning(f"Bad argument for command {ctx.command.qualified_name}: {ctx.message.content} ({error})")
        embed.description = f"Bad argument: `{error}`"
        await ctx.send(embed=embed)
        return
    if isinstance(error, commands.MissingPermissions):
        logger.warning(f"Missing permissions for command {ctx.command.qualified_name}: {ctx.message.content} ({error})")
        embed.description = f"`{command_name}` requires the following permissions: `{', '.join(error.missing_permissions).capitalize()}`"
        await ctx.send(embed=embed)
        return
    else:
        logger.critical(f"An unexpected error occurred: {traceback.format_exception(type(error), error, error.__traceback__)}")
        embed.description = f"An unexpected error occurred: {error}"
    await ctx.send(embed=embed)
    
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


@bot.command(name="command", description="Enable or disable a command.", aliases=["cmd"])
@commands.check(lambda ctx: str(ctx.author.id) in bot_info.data['owners'] or ctx.author.guild_permissions.manage_guild)
async def command_permission(ctx: commands.Context, command: str, target_type: str, target: commands.MemberConverter | commands.TextChannelConverter | commands.RoleConverter | None = None, status: str = "allow", *, reason: str = "No reason provided"):
    if status.lower() == "allow":
        status = True
    elif status.lower() == "deny":
        status = False
    elif status.lower() == "reset":
        status = None
    else:
        await ctx.send("Invalid status. Valid statuses: `allow`, `deny`, or `reset`.")
        return
    if status is None:
        if target_type == "server":
            query = "DELETE FROM server_command_permissions WHERE guild_id = $1 AND command_name = $2;"
            try:
                async with bot.db.acquire() as conn:
                    await conn.execute(query, ctx.guild.id, command)
                await ctx.send(f"Server-wide command permissions for `{command}` have been reset.")
            except Exception as e:
                await ctx.send(f"Error: {e}")
                return
        elif target_type in ["user", "channel", "role"] and target:
            if not target:
                await ctx.send("You must provide a target for user, channel, or role.")
                return
            query = "DELETE FROM command_permissions WHERE guild_id = $1 AND command_name = $2 AND target_type = $3 AND target_id = $4;"
            try:
                async with bot.db.acquire() as conn:
                    await conn.execute(query, ctx.guild.id, command, target_type, target.id)
                await ctx.send(f"Command permissions for `{command}` have been reset for {target_type} with ID {target}.")
            except Exception as e:
                await ctx.send(f"Error: {e}")
                return
        else:
            await ctx.send("Invalid reset action. Please provide a target for server, user, channel, or role.")
            return
        return
    if target_type == "server":
        query = "INSERT INTO server_command_permissions (guild_id, command_name, status, reason) VALUES ($1, $2, $3, $4) ON CONFLICT (guild_id, command_name) DO UPDATE SET status = EXCLUDED.status, reason = EXCLUDED.reason;"
        try:
            async with bot.db.acquire() as conn:
                await conn.execute(query, ctx.guild.id, command, status, reason)
        except Exception as e:
            await ctx.send(f"Error: {e}")
            return
    elif target_type in ["user", "channel", "role"]:
        if not target:
            await ctx.send("You must provide a target for user, channel, or role.")
            return
        if target_type == "user" and not isinstance(target, discord.Member):
            await ctx.send("Invalid user provided. Please provide a valid user.")
            return
        elif target_type == "channel" and not isinstance(target, discord.TextChannel):
            await ctx.send("Invalid channel provided. Please provide a valid channel.")
            return
        elif target_type == "role" and not isinstance(target, discord.Role):
            await ctx.send("Invalid role provided. Please provide a valid role.")
            return
        target = target.id
        query = "INSERT INTO command_permissions (guild_id, command_name, target_type, target_id, status, reason) VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (guild_id, command_name, target_type, target_id) DO UPDATE SET status = EXCLUDED.status, reason = EXCLUDED.reason;"
        try:
            async with bot.db.acquire() as conn:
                await conn.execute(query, ctx.guild.id, command, target_type, target, status, reason)
        except Exception as e:
            await ctx.send(f"Error: {e}")
            return
    status_str = "allowed" if status else "denied"
    target_name = f"entire server" if target_type == "server" else f"{target_type} with ID {target}"
    await ctx.send(f"Command `{command}` has been {status_str} for {target_name}. Reason: `{reason}`")

@bot.command(name="commandclear", description="Clear all command permissions for a command.", aliases=["cmdclear"])
@commands.check(lambda ctx: str(ctx.author.id) in bot_info.data['owners'] or ctx.author.guild_permissions.manage_guild)
async def command_clear(ctx: commands.Context, command: str, target_type: str, target: commands.MemberConverter | commands.TextChannelConverter | commands.RoleConverter | None = None):
    if target_type == "server":
        query = "DELETE FROM server_command_permissions WHERE guild_id = $1 AND command_name = $2"
        try:
            async with bot.db.acquire() as conn:
                result = await conn.execute(query, ctx.guild.id, command)
                if result == "DELETE 0":
                    await ctx.send(f"No server-wide command permissions found for command `{command}`.")
                else:
                    await ctx.send(f"Server-wide command permissions for command `{command}` have been cleared.")
        except Exception as e:
            await ctx.send(f"Error clearing server-wide command permissions: {e}")
        return
    query = "DELETE FROM command_permissions WHERE guild_id = $1 AND command_name = $2"
    params = [ctx.guild.id, command]
    if target_type and target:
        if target_type == "user":
            query += " AND target_type = $3 AND target_id = $4"
            params.extend([target_type, target.id])
        elif target_type == "channel":
            query += " AND target_type = $3 AND target_id = $4"
            params.extend([target_type, target.id])
        elif target_type == "role":
            query += " AND target_type = $3 AND target_id = $4"
            params.extend([target_type, target.id])
        else:
            await ctx.send("Invalid target type. Valid types: `server`, `user`, `channel`, or `role`.")
            return
    else:
        query += ";"
    try:
        async with bot.db.acquire() as conn:
            result = await conn.execute(query, *params)
            if result == "DELETE 0":
                await ctx.send(f"No command permissions found for command `{command}` with the specified target.")
            else:
                await ctx.send(f"Command permissions for command `{command}` have been cleared.")
    except Exception as e:
        await ctx.send(f"Error clearing command permissions: {e}")

@bot.command(name="commandlist", description="List all command permissions for a command.", aliases=["cmdlist"])
@commands.check(lambda ctx: str(ctx.author.id) in bot_info.data['owners'] or ctx.author.guild_permissions.manage_guild)
async def command_list(ctx: commands.Context):
    query = "SELECT command_name, target_type, target_id, status, reason FROM command_permissions WHERE guild_id = $1"
    async with bot.db.acquire() as conn:
        result = await conn.fetch(query, ctx.guild.id)
    if not result:
        await ctx.send("There are no command allow/blocklist entries for this server.")
        return
    allow_entries = []
    block_entries = []
    for row in result:
        target_name = "Server-wide" if row["target_type"] == "server" else f"{row['target_type'].capitalize()} with ID {row['target_id']}"
        entry_str = f"`{row['command_name']}` - {target_name} | Reason: `{row['reason']}`"
        if row["status"]:
            allow_entries.append(entry_str)
        else:
            block_entries.append(entry_str)
    allow_text = "\n".join(allow_entries) if allow_entries else "None"
    block_text = "\n".join(block_entries) if block_entries else "None"
    embed = discord.Embed(title="Command Allow/Blocklist Entries", color=discord.Color.light_gray())
    embed.add_field(name="Allow Entries", value=allow_text, inline=False)
    embed.add_field(name="Block Entries", value=block_text, inline=False)
    embed.set_author(name=f"{ctx.guild.name} (ID: {ctx.guild.id})", icon_url=ctx.guild.icon.url if ctx.guild.icon else None, url=f"https://discord.com/channels/{ctx.guild.id}")
    embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url if ctx.author.avatar else None)
    await ctx.send(embed=embed)

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

@bot.command(name="setprefix", description="Sets the prefix for a guild.")
async def setprefix(ctx: commands.Context, prefix: str):
    if ctx.guild is None:
        await ctx.send("This command can only be used in a guild.")
        return
    if ctx.author.guild_permissions.manage_guild or str(ctx.author.id) in bot_info.data['owners']:
        await set_prefix(ctx.guild.id, prefix)
        await ctx.send(f"Prefix for {ctx.guild.name} set to `{prefix}`.")
    else:
        await ctx.send(f"{ctx.command.qualified_name} can only be used by users who have the `Manage Guild` permission.")
        return

@bot.command(name="getprefix", description="Gets the prefix for a guild.")
async def getprefix(ctx: commands.Context):
    if ctx.guild is None:
        await ctx.send("This command can only be used in a guild.")
        return
    prefix = await get_prefix(ctx)
    await ctx.send(f"Prefix for {ctx.guild.name} is `{prefix}`.")

@bot.command(name="resetprefix", description="Resets the prefix for a guild to the default.")
async def resetprefix(ctx: commands.Context):
    if ctx.guild is None:
        await ctx.send("This command can only be used in a guild.")
        return
    if ctx.author.guild_permissions.manage_guild or str(ctx.author.id) in bot_info.data['owners']:
        await set_prefix(ctx.guild.id, bot_info.data['prefix'])
        await ctx.send(f"Prefix for {ctx.guild.name} reset to `{bot_info.data['prefix']}`.")
    else:
        await ctx.send(f"{ctx.command.qualified_name} can only be used by users who have the `Manage Guild` permission.")
        return

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
        result = f"```py\n{e.__class__.__name__}: {e}\n```"
    func = env['func']
    try:
        with contextlib.redirect_stdout(stdout):
            ret = await func()
    except Exception as e:
        result = stdout.getvalue()
        embed = discord.Embed(title="Evaluation Error", description=f"```py\n{result}\n{traceback.format_exc()}```", color=discord.Color.red())
        await ctx.send(embed=embed)
        logger.error(f"Error evaluating code: {e}")
        return
    else:
        result = stdout.getvalue() or "No output."
        if ret is not None:
            result += f'\n--> {ret}'
        logger.info(f"Evaluated code: {code}")
    
    pages = [result[i:i+1980] for i in range(0, len(result), 1980)]
    
    if not pages:
        pages = ["```py\nNo output.\n```"]
    
    class EvalView(discord.ui.View):
        def __init__(self, total_pages: int):
            super().__init__()
            self.current_page = 0
            self.timeout = 60.0
            self.total_pages = total_pages
            self.update_button_states()
        
        def update_button_states(self):
            self.children[0].disabled = self.current_page == 0
            self.children[1].disabled = self.current_page == self.total_pages - 1

        @discord.ui.button(label="◀", style=discord.ButtonStyle.primary, disabled=True)
        async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.current_page > 0:
                self.current_page -= 1
                await self.update_page(interaction)

        @discord.ui.button(label="▶", style=discord.ButtonStyle.primary, disabled=False)
        async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.current_page < self.total_pages - 1:
                self.current_page += 1
                await self.update_page(interaction)

        @discord.ui.button(label="🔁", style=discord.ButtonStyle.primary)
        async def shuffle(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.current_page = random.randint(0, self.total_pages - 1)
            await self.update_page(interaction)
        
        @discord.ui.button(label="🔢", style=discord.ButtonStyle.primary)
        async def jump(self, interaction: discord.Interaction, button: discord.ui.Button):
            class JumpView(discord.ui.Modal):
                def __init__(self, paginator):
                    super().__init__(title="Jump to Page")
                    self.paginator = paginator
                    self.page_input = discord.ui.TextInput(
                        label="Page Number",
                        placeholder=f"Enter a number between 1 and {self.paginator.total_pages}",
                        required=True
                    )
                    self.add_item(self.page_input)
                
                async def on_submit(self, interaction: discord.Interaction):
                    try:
                        page = int(self.page_input.value)
                        if 1 <= page <= self.paginator.total_pages:
                            self.paginator.current_page = page - 1
                            await self.paginator.update_page(interaction)
                        else:
                            await interaction.response.send_message("Invalid page number.", ephemeral=True)
                    except ValueError:
                        await interaction.response.send_message("Please enter a valid number.", ephemeral=True)
            
            await interaction.response.send_modal(JumpView(self))

        @discord.ui.button(label="⏹️", style=discord.ButtonStyle.danger)
        async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.edit_message(view=None)
        
        @discord.ui.button(label="🗑️", style=discord.ButtonStyle.danger)
        async def clear(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.message.delete()
        
        async def update_page(self, interaction: discord.Interaction):
            embed = discord.Embed(title="Evaluation Result", description=f"```py\n{pages[self.current_page]}\n```", color=discord.Color.og_blurple())
            embed.set_footer(text=f"Page {self.current_page + 1}/{self.total_pages}")
            self.update_button_states()
            await interaction.response.edit_message(embed=embed, view=self)

    embed = discord.Embed(title="Evaluation Result", description=f"```py\n{pages[0]}\n```", color=discord.Color.og_blurple())
    embed.set_footer(text=f"Page 1/{len(pages)}")

    view = EvalView(total_pages=len(pages))

    await ctx.send(embed=embed, view=view)

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
