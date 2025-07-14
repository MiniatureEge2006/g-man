import contextlib
import copy
import io
import textwrap
import bot_info
import datetime
import time
import psutil
import logging
import colorlog
import asyncpg
import discord
from discord import app_commands
from discord.ext import commands
from typing import Literal, Optional, Union
import os
import traceback
import random


uptime_start = datetime.datetime.now(datetime.timezone.utc)

# If any videos were not deleted while the bot was last up, remove them
vid_files = [f for f in os.listdir('vids') if os.path.isfile(os.path.join('vids', f))]
for f in vid_files:
    os.remove(f'vids/{f}')

async def get_prefix(bot, message: discord.Message):
    if not message.guild:
        async with bot.db.acquire() as conn:
            personal_prefixes = await conn.fetchval("SELECT prefixes from user_prefixes WHERE user_id = $1", message.author.id)
        return commands.when_mentioned_or(*(personal_prefixes or [bot_info.data['prefix']]))(bot, message)
    
    async with bot.db.acquire() as conn:
        row = await conn.fetchrow(
            """
SELECT (SELECT prefixes FROM user_prefixes WHERE user_id = $1) AS personal_prefixes,
(SELECT prefixes FROM guild_prefixes WHERE guild_id = $2) AS guild_prefixes""",
message.author.id, message.guild.id
        )
    
    personal_prefixes = row["personal_prefixes"] or []
    guild_prefixes = row["guild_prefixes"] or []

    all_prefixes = personal_prefixes or guild_prefixes or [bot_info.data['prefix']]

    return commands.when_mentioned_or(*all_prefixes)(bot, message)

async def set_prefix(entity_id: int, prefix: str, is_guild: bool = True):
    table = "guild_prefixes" if is_guild else "user_prefixes"
    id_field = "guild_id" if is_guild else "user_id"

    async with bot.db.acquire() as conn:
        current_prefixes = await conn.fetchval(f"SELECT prefixes FROM {table} WHERE {id_field} = $1", entity_id)

        if current_prefixes is None:
            current_prefixes = []
        else:
            current_prefixes = list(current_prefixes)
        
        if prefix not in current_prefixes:
            current_prefixes.append(prefix)
            await conn.execute(f"INSERT INTO {table} ({id_field}, prefixes) VALUES ($1, $2) ON CONFLICT ({id_field}) DO UPDATE SET prefixes = $2", entity_id, current_prefixes)
            return f"Added prefix `{prefix}` successfully."
        else:
            return f"Prefix `{prefix}` is already set."


extensions = ['cogs.ai', 'cogs.audio', 'cogs.code', 'cogs.exif', 'cogs.help', 'cogs.info', 'cogs.tags', 'cogs.media', 'cogs.moderation', 'cogs.reminder', 'cogs.roblox', 'cogs.search', 'cogs.ytdlp']
bot = commands.AutoShardedBot(command_prefix=get_prefix, case_insensitive=True, strip_after_prefix=True, status=discord.Status.online, activity=discord.Game(name=f"{bot_info.data['prefix']}help"), help_command=None, intents=discord.Intents.all(), allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False, replied_user=True))


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
    if ctx.author.id in bot_info.data['owners']:
        return True
    return await command_permission_check(ctx)

async def command_permission_check(ctx: commands.Context) -> bool:
    try:
        is_admin = ctx.author.guild_permissions.administrator
        role_ids = [role.id for role in ctx.author.roles]
    except AttributeError:
        is_admin = False
        role_ids = []
    guild_id = ctx.guild.id if ctx.guild else None
    if guild_id:
        async with bot.db.acquire() as conn:
            server_query = "SELECT status, reason FROM server_command_permissions WHERE guild_id = $1 AND command_name = $2"
            server_result = await conn.fetchrow(server_query, ctx.guild.id, ctx.command.name)
            if server_result:
                if not server_result["status"] and not is_admin:
                    await ctx.send(f"Command blocked. This server disabled this command. Reason: `{server_result['reason']}`")
                    return False
            block_query = "SELECT status, target_type, reason FROM command_permissions WHERE guild_id = $1 AND command_name = $2 AND ((target_type = 'user' AND target_id = $3) OR (target_type = 'channel' AND target_id = $4) OR (target_type = 'role' AND target_id = ANY($5::BIGINT[])))"
            block_result = await conn.fetch(block_query, ctx.guild.id, ctx.command.name, ctx.author.id, ctx.channel.id, role_ids)
            for row in block_result:
                if not row["status"] and not is_admin:
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
                if not allowed and not is_admin:
                    await ctx.send(f"Command blocked. Either you, this channel, or one of your roles are not part of the allowlist. Reason: `{row['reason']}`")
                    return False
        return True
    else:
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


@bot.event
async def on_message(message):
    ctx = await bot.get_context(message)

    if ctx.command is None:
        return
    
    await bot.process_commands(message)


@bot.event
async def on_command(ctx: commands.Context):
    logger = logging.getLogger()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user = f"{ctx.author.name}#{ctx.author.discriminator} (ID: {ctx.author.id})"
    guild = f"{ctx.guild.name} (ID: {ctx.guild.id})" if ctx.guild else "DMs"
    channel = f"#{ctx.channel.name} (ID: {ctx.channel.id})" if ctx.guild else f"DMs with {ctx.author.name}#{ctx.author.discriminator} (ID: {ctx.author.id})"
    command_name = ctx.command.qualified_name
    command_content = ctx.message.content if not ctx.interaction else "".join(f"/{ctx.interaction.command.qualified_name} " + " ".join(f"{k}:{v}" for k, v in ctx.interaction.namespace.__dict__.items() if v is not None))
    log_message = (
        f"\n--- {'Slash ' if ctx.interaction else ''}Command Log ---\n"
        f"Timestamp: {timestamp}\n"
        f"User: {user}\n"
        f"Guild: {guild}\n"
        f"Channel: {channel}\n"
        f"Command: {command_name}\n"
        f"Command Content: {command_content}\n"
        f"--- End {'Slash ' if ctx.interaction else ''}Command Log ---"
    )
    logger.info(log_message)

# Command error
@bot.event
async def on_command_error(ctx: commands.Context, error):
    logger = logging.getLogger()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user = f"{ctx.author.name}#{ctx.author.discriminator} (ID: {ctx.author.id})"
    guild = f"{ctx.guild.name} (ID: {ctx.guild.id})" if ctx.guild else "DMs"
    channel = f"#{ctx.channel.name} (ID: {ctx.channel.id})" if ctx.guild else f"DMs with {ctx.author.name}#{ctx.author.discriminator} (ID: {ctx.author.id})"
    command_name = ctx.command.qualified_name if ctx.command else "Unknown"
    command_content = ctx.message.content if not ctx.interaction else "".join(f"/{ctx.interaction.command.qualified_name} " + " ".join(f"{k}:{v}" for k, v in ctx.interaction.namespace.__dict__.items() if v is not None))
    logger.error(
        f"\n--- {'Slash ' if ctx.interaction else ''}Command Error Log ---\n"
        f"Timestamp: {timestamp}\n"
        f"User: {user}\n"
        f"Guild: {guild}\n"
        f"Channel: {channel}\n"
        f"Command: {command_name}\n"
        f"Command Content: {command_content}\n"
        f"--- End {'Slash ' if ctx.interaction else ''}Command Error Log ---"
    )
    embed = discord.Embed(title=":warning: Command Error" if not ctx.interaction else ":warning: Slash Command Error", color=discord.Color.red(), timestamp=discord.utils.utcnow())
    embed.set_author(name=f"{ctx.author.name}#{ctx.author.discriminator}", icon_url=ctx.author.display_avatar.url, url=f"https://discord.com/users/{ctx.author.id}")
    if isinstance(error, commands.CheckFailure):
        return
    if isinstance(error, commands.MissingRequiredArgument):
        embed.description = f"Missing required argument: `{error.param.name}`"
        await ctx.send(embed=embed)
        return
    if isinstance(error, commands.BadArgument):
        embed.description = f"Bad argument: `{error}`"
        await ctx.send(embed=embed)
        return
    if isinstance(error, commands.MissingPermissions):
        embed.description = f"`{command_name}` requires the following permissions: `{', '.join(error.missing_permissions).capitalize()}`"
        await ctx.send(embed=embed)
        return
    else:
        logger.critical(traceback.format_exception(type(error), error, error.__traceback__))
        embed.description = str(error)
    await ctx.send(embed=embed)
    
@bot.event
async def on_command_completion(ctx: commands.Context):
    logger = logging.getLogger()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user = f"{ctx.author.name}#{ctx.author.discriminator} (ID: {ctx.author.id})"
    guild = f"{ctx.guild.name} (ID: {ctx.guild.id})" if ctx.guild else "DMs"
    channel = f"#{ctx.channel.name} (ID: {ctx.channel.id})" if ctx.guild else f"DMs with {ctx.author.name}#{ctx.author.discriminator} (ID: {ctx.author.id})"
    command_name = ctx.command.qualified_name
    command_content = ctx.message.content if not ctx.interaction else "".join(f"/{ctx.interaction.command.qualified_name} " + " ".join(f"{k}:{v}" for k, v in ctx.interaction.namespace.__dict__.items() if v is not None))
    logger.info(
        f"\n--- {'Slash ' if ctx.interaction else ''}Command Success Log ---\n"
        f"Timestamp: {timestamp}\n"
        f"User: {user}\n"
        f"Guild: {guild}\n"
        f"Channel: {channel}\n"
        f"Command: {command_name}\n"
        f"Command Content: {command_content}\n"
        f"--- End {'Slash ' if ctx.interaction else ''}Command Success Log ---"
    )

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


@bot.hybrid_command(name="ping", description="Check the bot's latency.")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def ping(ctx: commands.Context):
    ws_latency = round(bot.latency * 1000)
    start_time = time.perf_counter()
    message = await ctx.send("Pinging...")
    end_time = time.perf_counter()
    api_response_time = round((end_time - start_time) * 1000)
    current_time = datetime.datetime.now(datetime.timezone.utc)
    uptime = current_time - uptime_start
    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    cpu_usage = psutil.cpu_percent()
    memory_info = psutil.virtual_memory()
    memory_usage = round(memory_info.used / (1024 ** 2))
    memory_total = round(memory_info.total / (1024 ** 2))

    content = f"Pong!\nGateway: {ws_latency}ms\nAPI: {api_response_time}ms\nUptime: {days}d {hours}h {minutes}m {seconds}s\nCPU Usage: {cpu_usage}%\nMemory Usage: {memory_usage} MB / {memory_total} MB"

    await message.edit(content=content)


@bot.command(name="sudo", description="Execute a command as another user. Use sudo! to bypass checks and permissions.", aliases=["sudo!"])
@bot_info.is_owner()
async def sudo(ctx: commands.Context, user: discord.Member, command: str, *, arguments: str = None):
    async def get_effective_prefix(bot, message):
        return await get_prefix(bot, message)
    
    fake_message = copy.copy(ctx.message)
    fake_message.author = user
    effective_prefixes = await get_effective_prefix(bot, fake_message)
    used_prefix = effective_prefixes[0] if effective_prefixes else bot_info.data['prefix']
    fake_message.content = f"{used_prefix}{command}" + (f" {arguments}" if arguments else "")

    new_ctx = await bot.get_context(fake_message)

    if new_ctx.command is None:
        await ctx.send(f"Command `{command}` not found or cannot be executed.")
        return

    try:
        if ctx.invoked_with and ctx.invoked_with.endswith('!'):
            await new_ctx.command.reinvoke(new_ctx)
            return
        await new_ctx.command.invoke(new_ctx)
        return
    except Exception as e:
        await ctx.send(f"Error while running command as {user}: {e}")
        raise


@bot.command(name="sync", description="Sync slash commands.")
@bot_info.is_owner()
async def sync(ctx: commands.Context, guilds: commands.Greedy[discord.Object], spec: Optional[Literal["~", "*", "^"]] = None) -> None:
    logger = logging.getLogger()
    message = await ctx.send("Syncing...")
    if not guilds:
        if spec == "~":
            synced = await ctx.bot.tree.sync(guild=ctx.guild)
        elif spec == "*":
            ctx.bot.tree.copy_global_to(guild=ctx.guild)
            synced = await ctx.bot.tree.sync(guild=ctx.guild)
        elif spec == "^":
            ctx.bot.tree.clear_commands(guild=ctx.guild)
            await ctx.bot.tree.sync(guild=ctx.guild)
            synced = []
        else:
            synced = await ctx.bot.tree.sync()
        logger.info(f"Synced {len(synced)} commands {'globally' if spec is None else 'to the current guild'}.")
        await message.edit(content=f"Synced {len(synced)} commands {'globally' if spec is None else 'to the current guild'}.")
        return
    ret = 0
    for guild in guilds:
        try:
            await ctx.bot.tree.sync(guild=guild)
        except discord.HTTPException:
            logger.warning(f"Failed to sync commands to {guild.id}")
            pass
        else:
            ret += 1
    
    await ctx.send(f"Synced the tree to {ret}/{len(guilds)} guilds.")
    



@bot.command(name="command", description="Enable or disable a command.", aliases=["cmd"])
@commands.check(lambda ctx: str(ctx.author.id) in bot_info.data['owners'] or ctx.author.guild_permissions.manage_guild)
async def command_permission(
    ctx: commands.Context,
    command: str,
    target_type: Literal["server", "user", "channel", "role"],
    target: Optional[Union[commands.MemberConverter, commands.TextChannelConverter, commands.RoleConverter]] = None,
    status: Literal["allow", "deny", "reset"] = "allow",
    *, 
    reason: str = "No reason provided"
):
    status_value = {
        "allow": True,
        "deny": False,
        "reset": None
    }[status.lower()]


    if target_type == "server":
        if status_value is None:
            query = "DELETE FROM server_command_permissions WHERE guild_id = $1 AND command_name = $2"
            params = (ctx.guild.id, command)
            action = "reset"
        else:
            query = """
                INSERT INTO server_command_permissions (guild_id, command_name, status, reason, added_by, added_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (guild_id, command_name)
                DO UPDATE SET status = EXCLUDED.status, reason = EXCLUDED.reason
            """
            params = (ctx.guild.id, command, status_value, reason, ctx.author.id, datetime.datetime.now())
            action = "allowed" if status_value else "denied"
        
        async with bot.db.acquire() as conn:
            await conn.execute(query, *params)
        
        await ctx.send(f"Command `{command}` has been {action} server-wide. Reason: `{reason}`")
        return


    if target is None:
        raise commands.BadArgument(f"You must specify a target when using {target_type} permissions.")

    try:
        if target_type == "user":
            target_obj = await commands.MemberConverter().convert(ctx, str(target))
        elif target_type == "channel":
            target_obj = await commands.TextChannelConverter().convert(ctx, str(target))
        elif target_type == "role":
            target_obj = await commands.RoleConverter().convert(ctx, str(target))
    except commands.BadArgument as e:
        raise commands.BadArgument(f"Invalid {target_type}: {e}")

    if status_value is None:
        query = "DELETE FROM command_permissions WHERE guild_id = $1 AND command_name = $2 AND target_type = $3 AND target_id = $4"
        params = (ctx.guild.id, command, target_type, target_obj.id)
        action = "reset"
    else:
        query = """
            INSERT INTO command_permissions (guild_id, command_name, target_type, target_id, status, reason, added_by, added_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (guild_id, command_name, target_type, target_id)
            DO UPDATE SET status = EXCLUDED.status, reason = EXCLUDED.reason
        """
        params = (ctx.guild.id, command, target_type, target_obj.id, status_value, reason, ctx.author.id, datetime.datetime.now())
        action = "allowed" if status_value else "denied"

    async with bot.db.acquire() as conn:
        await conn.execute(query, *params)

    await ctx.send(f"Command `{command}` has been {action} for {target_type} {target_obj}. Reason: `{reason}`")

@bot.command(name="commandclear", description="Clear all command permissions for a command.", aliases=["cmdclear"])
@commands.check(lambda ctx: str(ctx.author.id) in bot_info.data['owners'] or ctx.author.guild_permissions.manage_guild)
async def command_clear(ctx: commands.Context, command: str, target_type: str):
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
    query = "DELETE FROM command_permissions WHERE guild_id = $1 AND command_name = $2 AND target_type = $3"
    try:
        async with bot.db.acquire() as conn:
            result = await conn.execute(query, ctx.guild.id, command, target_type)
            if result == "DELETE 0":
                await ctx.send(f"No command permissions found for command `{command}` for {target_type}.")
            else:
                await ctx.send(f"Command permissions for command `{command}` have been cleared for {target_type}.")
    except Exception as e:
        await ctx.send(f"Error clearing command permissions: {e}")
    return

@bot.command(name="commandlist", description="List all command permissions for a command.", aliases=["cmdlist"])
@commands.check(lambda ctx: str(ctx.author.id) in bot_info.data['owners'] or ctx.author.guild_permissions.manage_guild)
async def command_list(ctx: commands.Context):
    query = """
        SELECT command_name, target_type, target_id, status, reason, added_by, added_at 
        FROM command_permissions 
        WHERE guild_id = $1 
        UNION ALL 
        SELECT command_name, 'server' AS target_type, NULL AS target_id, status, reason, added_by, added_at 
        FROM server_command_permissions 
        WHERE guild_id = $1
        ORDER BY command_name, target_type
    """
    
    async with bot.db.acquire() as conn:
        records = await conn.fetch(query, ctx.guild.id)
    
    if not records:
        await ctx.send("No command permissions are configured for this server.")
        return
    

    processed = []
    for record in records:
        entry = {
            "command": record["command_name"],
            "type": record["target_type"],
            "status": record["status"],
            "reason": record["reason"],
            "added_by": record["added_by"],
            "added_at": f"<t:{int(record['added_at'].timestamp())}:R>"
        }
        

        if record["target_type"] == "server":
            entry["target"] = "Server-wide"
        else:
            try:
                if record["target_type"] == "user":
                    target = await commands.MemberConverter().convert(ctx, str(record["target_id"]))
                    entry["target"] = f"User: {target.mention}"
                elif record["target_type"] == "channel":
                    target = await commands.TextChannelConverter().convert(ctx, str(record["target_id"]))
                    entry["target"] = f"Channel: {target.mention}"
                elif record["target_type"] == "role":
                    target = await commands.RoleConverter().convert(ctx, str(record["target_id"]))
                    entry["target"] = f"Role: {target.mention}"
            except commands.BadArgument:
                entry["target"] = f"{record['target_type'].title()} ID: {record['target_id']}"
        

        try:
            adder = await commands.MemberConverter().convert(ctx, str(record["added_by"]))
            entry["added_by"] = adder.mention
        except commands.BadArgument:
            entry["added_by"] = f"User ID: {record['added_by']}"
        
        processed.append(entry)
    

    commands_dict = {}
    for entry in processed:
        if entry["command"] not in commands_dict:
            commands_dict[entry["command"]] = []
        commands_dict[entry["command"]].append(entry)
    

    pages = []
    current_page = []
    current_length = 0
    
    for cmd, entries in commands_dict.items():
        cmd_text = [f"**Command:** `{cmd}`"]
        
        for entry in entries:
            entry_text = (
                f"- **Target:** {entry['target']}\n"
                f"- **Status:** {'Allowed' if entry['status'] else 'Blocked'}\n"
                f"- **Reason:** `{entry['reason']}`\n"
                f"- **By:** {entry['added_by']} at {entry['added_at']}"
            )
            cmd_text.append(entry_text)
        
        full_cmd_text = "\n".join(cmd_text)
        
        if current_length + len(full_cmd_text) > 2000:
            pages.append("\n\n".join(current_page))
            current_page = []
            current_length = 0
        
        current_page.append(full_cmd_text)
        current_length += len(full_cmd_text) + 2
    
    if current_page:
        pages.append("\n\n".join(current_page))
    

    for i, page in enumerate(pages, 1):
        embed = discord.Embed(
            title=f"Command Permissions (Page {i}/{len(pages)})",
            description=page,
            color=discord.Color.blurple()
        )
        await ctx.send(embed=embed)

@bot.command(name="blocklist", description="List all blocked users, channels, and roles.")
@commands.check(lambda ctx: str(ctx.author.id) in bot_info.data['owners'] or ctx.author.guild_permissions.administrator)
async def blocklist(ctx: commands.Context):
    async with bot.db.acquire() as conn:
        records = await conn.fetch("SELECT type, entity_id, reason, added_by, added_at FROM blocklist")
        global_blocked_records = await conn.fetch("SELECT discord_id, reason FROM global_blocked_users")
        server_blocked_records = await conn.fetch("SELECT guild_id, reason FROM global_blocked_servers")
        if not (records or global_blocked_records or server_blocked_records):
            await ctx.send("The blocklist is empty.")
            return
        formatted_records = []
        for record in records:
            entity_id = record['entity_id']
            entity_type = record['type']
            reason = record['reason']
            added_by_user = ctx.guild.get_member(record['added_by'])
            added_by_name_unknown = await bot.fetch_user(record['added_by'])
            added_by_name = added_by_user.mention if added_by_user else added_by_name_unknown.mention
            added_at = f"<t:{int(record['added_at'].timestamp())}:R>"
            if entity_type == "user":
                user = ctx.guild.get_member(entity_id)
                entity_name = f"{user.name}#{user.discriminator} ({user.mention})" if user else entity_id
            elif entity_type == "channel":
                channel = ctx.guild.get_channel(entity_id)
                entity_name = f"{channel.name} ({channel.mention})" if channel else entity_id
            elif entity_type == "role":
                role = ctx.guild.get_role(entity_id)
                entity_name = f"{role.name} ({role.mention})" if role else entity_id
            else:
                entity_name = entity_id
            formatted_records.append(f"**Type:** {entity_type.capitalize()} | **Name:** {entity_name} | **Reason:** `{reason}` | **Added by:** {added_by_name} | **Added at:** {added_at}")
        formatted_text = "\n".join(formatted_records) if formatted_records else "None"
        embed = discord.Embed(title="Blocklist", color=discord.Color.red())
        embed.add_field(name="Blocked Entries", value=formatted_text, inline=False)
        if str(ctx.author.id) in bot_info.data['owners']:
            formatted_global_records = "\n".join(f"**User ID:** {record['discord_id']} | **Reason:** `{record['reason']}`" for record in global_blocked_records)
            formatted_server_records = "\n".join(f"**Server ID:** {record['guild_id']} | **Reason:** `{record['reason']}`" for record in server_blocked_records)
            embed.add_field(name="Global/Server Blocklist", value=f"**Global:**\n{formatted_global_records}\n\n**Server:**\n{formatted_server_records}", inline=False)
        embed.set_author(name=f"{ctx.author.name}#{ctx.author.discriminator}", icon_url=ctx.author.display_avatar.url, url=f"https://discord.com/users/{ctx.author.id}")
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url if ctx.author.avatar else None)
        await ctx.send(embed=embed)

@bot.command(name="allowlist", description="List all allowed users, channels, and roles.")
@commands.check(lambda ctx: str(ctx.author.id) in bot_info.data['owners'] or ctx.author.guild_permissions.administrator)
async def allowlist(ctx: commands.Context):
    async with bot.db.acquire() as conn:
        records = await conn.fetch("SELECT type, entity_id, reason, added_by, added_at FROM allowlist")
        if not records:
            await ctx.send("The allowlist is empty.")
            return
        formatted_records = []
        for record in records:
            entity_id = record['entity_id']
            entity_type = record['type']
            reason = record['reason']
            added_by_user = ctx.guild.get_member(record['added_by'])
            added_by_name_unknown = await bot.fetch_user(record['added_by'])
            added_by_name = added_by_user.mention if added_by_user else added_by_name_unknown.mention
            added_at = f"<t:{int(record['added_at'].timestamp())}:R>"
            if entity_type == "user":
                user = ctx.guild.get_member(entity_id)
                entity_name = f"{user.name}#{user.discriminator} ({user.mention})" if user else entity_id
            elif entity_type == "channel":
                channel = ctx.guild.get_channel(entity_id)
                entity_name = f"{channel.name} ({channel.mention})" if channel else entity_id
            elif entity_type == "role":
                role = ctx.guild.get_role(entity_id)
                entity_name = f"{role.name} ({role.mention})" if role else entity_id
            else:
                entity_name = entity_id
            formatted_records.append(f"**Type:** {entity_type.capitalize()} | **Name:** {entity_name} | **Reason:** `{reason}` | **Added by:** {added_by_name} | **Added at:** {added_at}")
        formatted_text = "\n".join(formatted_records) if formatted_records else "None"
        embed = discord.Embed(title="Allowlist", color=discord.Color.green())
        embed.add_field(name="Allowed Entries", value=formatted_text, inline=False)
        embed.set_author(name=f"{ctx.author.name}#{ctx.author.discriminator}", icon_url=ctx.author.display_avatar.url, url=f"https://discord.com/users/{ctx.author.id}")
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url if ctx.author.avatar else None)
        await ctx.send(embed=embed)

@bot.command(name="block", description="Blocks a user, channel, or role from using the bot.")
@commands.check(lambda ctx: str(ctx.author.id) in bot_info.data['owners'] or ctx.author.guild_permissions.administrator)
async def block(ctx: commands.Context, type: str, target: str, *, reason = "No reason provided"):
    valid_types = ["global", "user", "channel", "role", "server"]
    
    if type not in valid_types:
        await ctx.send(f"Invalid type. Valid types: {', '.join(valid_types)}")
        return
    
    if type in ["global", "server"] and str(ctx.author.id) not in bot_info.data['owners']:
        await ctx.send(f"{type.capitalize()} blocks can only be set by bot owners.")
        return

    converted = None
    converted_name = None
    entity_id = None

    try:
        if type == "user":
            conv = commands.MemberConverter()
            converted = await conv.convert(ctx, target)
            entity_id = converted.id
            converted_name = str(converted)
        elif type == "channel":
            conv = commands.TextChannelConverter()
            converted = await conv.convert(ctx, target)
            entity_id = converted.id
            converted_name = str(converted)
        elif type == "role":
            conv = commands.RoleConverter()
            converted = await conv.convert(ctx, target)
            entity_id = converted.id
            converted_name = str(converted)
        elif type == "global":
            conv = commands.UserConverter()
            converted = await conv.convert(ctx, target)
            entity_id = converted.id
            converted_name = str(converted)
        elif type == "server":
            conv = commands.GuildConverter()
            converted = await conv.convert(ctx, target)
            entity_id = converted.id
            converted_name = str(converted)
    except commands.BadArgument:
        try:
            entity_id = int(target)
            converted_name = str(entity_id)
        except ValueError:
            await ctx.send("Could not resolve target. Please provide a valid ID, mention, or name.")
            return

    if type in ["global", "user"] and entity_id == ctx.author.id:
        await ctx.send("You can't block yourself.")
        return

    async with bot.db.acquire() as conn:
        if type == "server":
            exists = await conn.fetchval("SELECT EXISTS (SELECT 1 FROM global_blocked_servers WHERE guild_id = $1)", entity_id)
            if exists:
                await ctx.send(f"Server `{converted_name}` is already globally blocked.")
                return
            await conn.execute("INSERT INTO global_blocked_servers (guild_id, reason) VALUES ($1, $2) ON CONFLICT (guild_id) DO UPDATE SET reason = $2", entity_id, reason)
            await ctx.send(f"Globally blocked server `{converted_name}`. Reason: `{reason}`")

        elif type == "global":
            exists = await conn.fetchval("SELECT EXISTS (SELECT 1 FROM global_blocked_users WHERE discord_id = $1)", entity_id)
            if exists:
                await ctx.send(f"User `{converted_name}` is already globally blocked.")
                return
            await conn.execute("INSERT INTO global_blocked_users (discord_id, reason) VALUES ($1, $2) ON CONFLICT (discord_id) DO UPDATE SET reason = $2", entity_id, reason)
            await ctx.send(f"Globally blocked user `{converted_name}`. Reason: `{reason}`")

        else:
            exists = await conn.fetchval("SELECT EXISTS (SELECT 1 FROM blocklist WHERE type = $1 AND entity_id = $2)", type, entity_id)
            if exists:
                await ctx.send(f"{type.capitalize()} `{converted_name}` is already blocked.")
                return
            await conn.execute(
                "INSERT INTO blocklist (type, entity_id, reason, added_by, added_at) "
                "VALUES ($1, $2, $3, $4, $5) ON CONFLICT (type, entity_id) DO UPDATE SET reason = $3",
                type, entity_id, reason, ctx.author.id, datetime.datetime.now()
            )
            await ctx.send(f"Blocked {type} `{converted_name}`. Reason: `{reason}`")

@bot.command(name="unblock", description="Unblocks a user, channel, or role from using the bot.")
@commands.check(lambda ctx: str(ctx.author.id) in bot_info.data['owners'] or ctx.author.guild_permissions.administrator)
async def unblock(ctx: commands.Context, type: str, target: str):
    valid_types = ["global", "user", "channel", "role", "server"]

    if type not in valid_types:
        await ctx.send(f"Invalid type. Valid types: {', '.join(valid_types)}")
        return

    if type in ["global", "server"] and str(ctx.author.id) not in bot_info.data['owners']:
        await ctx.send(f"{type.capitalize()} blocks can only be removed by bot owners.")
        return

    converted_name = None
    entity_id = None

    try:
        if type == "user":
            conv = commands.MemberConverter()
            converted = await conv.convert(ctx, target)
            entity_id = converted.id
            converted_name = str(converted)
        elif type == "channel":
            conv = commands.TextChannelConverter()
            converted = await conv.convert(ctx, target)
            entity_id = converted.id
            converted_name = str(converted)
        elif type == "role":
            conv = commands.RoleConverter()
            converted = await conv.convert(ctx, target)
            entity_id = converted.id
            converted_name = str(converted)
        elif type == "global":
            conv = commands.UserConverter()
            converted = await conv.convert(ctx, target)
            entity_id = converted.id
            converted_name = str(converted)
        elif type == "server":
            conv = commands.GuildConverter()
            converted = await conv.convert(ctx, target)
            entity_id = converted.id
            converted_name = str(converted)
    except commands.BadArgument:
        try:
            entity_id = int(target)
            converted_name = str(entity_id)
        except ValueError:
            await ctx.send("Could not resolve target. Please provide a valid ID, mention, or name.")
            return

    async with bot.db.acquire() as conn:
        if type == "server":
            result = await conn.execute("DELETE FROM global_blocked_servers WHERE guild_id = $1", entity_id)
            if result == "DELETE 0":
                await ctx.send(f"Server `{converted_name}` is not globally blocked.")
            else:
                await ctx.send(f"Unblocked server `{converted_name}`.")

        elif type == "global":
            result = await conn.execute("DELETE FROM global_blocked_users WHERE discord_id = $1", entity_id)
            if result == "DELETE 0":
                await ctx.send(f"User `{converted_name}` is not globally blocked.")
            else:
                await ctx.send(f"Unblocked user `{converted_name}`.")

        else:
            result = await conn.execute("DELETE FROM blocklist WHERE type = $1 AND entity_id = $2", type, entity_id)
            if result == "DELETE 0":
                await ctx.send(f"{type.capitalize()} `{converted_name}` is not blocked.")
            else:
                await ctx.send(f"Unblocked {type} `{converted_name}`.")

@bot.command(name="allow", description="Allows a user, channel, or role to use the bot.")
@commands.check(lambda ctx: str(ctx.author.id) in bot_info.data['owners'] or ctx.author.guild_permissions.administrator)
async def allow(ctx: commands.Context, type: str, target: commands.MemberConverter | commands.TextChannelConverter | commands.RoleConverter, *, reason = "No reason provided"):
    valid_types = ["user", "channel", "role"]
    if type not in valid_types:
        await ctx.send("Invalid type. Valid types: `user`, `channel`, or `role`.")
        return
    converter = commands.MemberConverter() if type == "user" else commands.TextChannelConverter() if type == "channel" else commands.RoleConverter()
    converted = await converter.convert(ctx, str(target))
    converted_name = converted.name if converted else target
    type_id = target.id if hasattr(target, "id") else target
    async with bot.db.acquire() as conn:
        exists = await conn.fetchval("SELECT EXISTS (SELECT 1 FROM allowlist WHERE type = $1 AND entity_id = $2)", type, type_id)
        if exists:
            await ctx.send(f"{type.capitalize()} {converted_name} is already allowed.")
            return
        await conn.execute("INSERT INTO allowlist (type, entity_id, reason, added_by, added_at) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (type, entity_id) DO NOTHING", type, type_id, reason, ctx.author.id, datetime.datetime.now())
    await ctx.send(f"Allowed {type} {converted_name}. Reason: `{reason}`")

@bot.command(name="deny", description="Denies a user, channel, or role from using the bot. (Not to be confused with `block`.)")
@commands.check(lambda ctx: str(ctx.author.id) in bot_info.data['owners'] or ctx.author.guild_permissions.administrator)
async def deny(ctx: commands.Context, type: str, target: commands.MemberConverter | commands.TextChannelConverter | commands.RoleConverter):
    valid_types = ["user", "channel", "role"]
    if type not in valid_types:
        await ctx.send("Invalid type. Valid types: `user`, `channel`, or `role`.")
        return
    converter = commands.MemberConverter() if type == "user" else commands.TextChannelConverter() if type == "channel" else commands.RoleConverter()
    converted = await converter.convert(ctx, str(target))
    converted_name = converted.name if converted else target
    type_id = target.id if hasattr(target, "id") else target
    async with bot.db.acquire() as conn:
        exists = await conn.fetchval("SELECT EXISTS (SELECT 1 FROM allowlist WHERE type = $1 AND entity_id = $2)", type, type_id)
        if not exists:
            await ctx.send(f"{type.capitalize()} {converted_name} is not allowed.")
            return
        await conn.execute("DELETE FROM allowlist WHERE type = $1 AND entity_id = $2", type, type_id)
    await ctx.send(f"Denied {type} {converted_name}.")

@bot.command(name="addpersonalprefix", description="Add a personal prefix for yourself.", aliases=["apersonalprefix", "apprefix", "app"])
async def addpersonalprefix(ctx: commands.Context, prefix: str):
    response = await set_prefix(ctx.author.id, prefix, is_guild=False)
    await ctx.send(response)

@bot.command(name="removepersonalprefix", description="Remove a personal prefix that you made.", aliases=["rmpersonalprefix", "rmpprefix", "rmpp"])
async def removepersonalprefix(ctx: commands.Context, prefix: str):
    async with bot.db.acquire() as conn:
        current_prefixes = await conn.fetchval("SELECT prefixes FROM user_prefixes WHERE user_id = $1", ctx.author.id)

        if current_prefixes is None:
            await ctx.send("You have no personal prefixes set.")
            return
        
        current_prefixes = list(current_prefixes)

        if prefix in current_prefixes:
            current_prefixes.remove(prefix)
            await conn.execute("UPDATE user_prefixes SET prefixes = $1 WHERE user_id = $2", current_prefixes, ctx.author.id)
            await ctx.send(f"Removed personal prefix `{prefix}`.")
        else:
            await ctx.send(f"Prefix `{prefix}` is not in your personal prefixes.")

@bot.command(name="listpersonalprefixes", description="List your personal prefixes.", aliases=["lspersonalprefixes", "lspprefixes", "lspp"])
async def listpersonalprefixes(ctx: commands.Context):
    async with bot.db.acquire() as conn:
        prefixes = await conn.fetchval("SELECT prefixes FROM user_prefixes WHERE user_id = $1", ctx.author.id)

        if prefixes is None or len(prefixes) == 0:
            await ctx.send("You have no personal prefixes set.")
        else:
            await ctx.send(f"Your personal prefixes: {', '.join([f'`{p}`' for p in prefixes])}")

@bot.command(name="addguildprefix", description="Add a guild prefix for the current guild.", aliases=["aguildprefix", "agprefix", "agp"])
@commands.has_permissions(manage_guild=True)
async def addguildprefix(ctx: commands.Context, prefix: str):
    if ctx.guild is None:
        await ctx.send("This command can only be used in a server.")
        return
    
    response = await set_prefix(ctx.guild.id, prefix, is_guild=True)
    await ctx.send(response)


@bot.command(name="removeguildprefix", description="Remove a guild prefix.", aliases=["rmguildprefix", "rmgprefix", "rmgp"])
@commands.has_permissions(manage_guild=True)
async def removeguildprefix(ctx: commands.Context, prefix: str):
    async with bot.db.acquire() as conn:
        current_prefixes = await conn.fetchval("SELECT prefixes FROM guild_prefixes WHERE guild_id = $1", ctx.guild.id)

        if current_prefixes is None:
            await ctx.send("This guild has no prefixes set.")
            return
        
        current_prefixes = list(current_prefixes)

        if prefix in current_prefixes:
            current_prefixes.remove(prefix)
            await conn.execute("UPDATE guild_prefixes SET prefixes = $1 WHERE guild_id = $2", current_prefixes, ctx.guild.id)
            await ctx.send(f"Removed guild prefix `{prefix}`.")
        else:
            await ctx.send(f"Prefix `{prefix}` is not in the guild prefixes.")

@bot.command(name="listguildprefixes", description="List the guild prefixes.", aliases=["lsguildprefixes", "lsgprefixes", "lsgp"])
async def listguildprefixes(ctx: commands.Context):
    async with bot.db.acquire() as conn:
        prefixes = await conn.fetchval("SELECT prefixes FROM guild_prefixes WHERE guild_id = $1", ctx.guild.id)

        if prefixes is None or len(prefixes) == 0:
            await ctx.send(f"This guild has no prefixes set. Default prefix is `{bot_info.data["prefix"]}`.")
        else:
            await ctx.send(f"Guild prefixes: {', '.join([f'`{p}`' for p in prefixes])}")

# Reloading extensions
@bot.command(description='Reloads extensions.', pass_context=True)
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

@bot.hybrid_command(name="eval", description="Evaluate code.", aliases=["exec"])
@app_commands.describe(code="The code to evaluate.")
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
        def __init__(self, total_pages: int, original_author):
            super().__init__()
            self.current_page = 0
            self.timeout = 60.0
            self.original_author = original_author
            self.message = None
            self.total_pages = total_pages
            self.update_button_states()
        
        def update_button_states(self):
            self.children[0].disabled = self.current_page == 0
            self.children[1].disabled = self.current_page == self.total_pages - 1
        
        async def interaction_check(self, interaction: discord.Interaction):
            if interaction.user != self.original_author:
                await interaction.response.send_message("You can't control this pagination.", ephemeral=True)
                return False
            return True
        
        async def on_timeout(self):
            await self.message.edit(view=None)

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
        async def _stop(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.edit_message(view=None)
            self.stop()
        
        @discord.ui.button(label="🗑️", style=discord.ButtonStyle.danger)
        async def clear(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.message.delete()
            self.stop()
        
        async def update_page(self, interaction: discord.Interaction):
            embed = discord.Embed(title="Evaluation Result", description=f"```py\n{pages[self.current_page]}\n```", color=discord.Color.og_blurple())
            embed.set_footer(text=f"Page {self.current_page + 1}/{self.total_pages}")
            self.update_button_states()
            await interaction.response.edit_message(embed=embed, view=self)

    embed = discord.Embed(title="Evaluation Result", description=f"```py\n{pages[0]}\n```", color=discord.Color.og_blurple())
    embed.set_footer(text=f"Page 1/{len(pages)}")

    view = EvalView(total_pages=len(pages), original_author=ctx.author)

    view.message = await ctx.send(embed=embed, view=view)

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


setup_logger()

# Start the bot
bot.run(bot_info.data['login'], log_handler=None)
