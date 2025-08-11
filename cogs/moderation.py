import discord
from discord.ext import commands
from discord import app_commands
import re
import asyncpg
import bot_info
from typing import Optional, List, Literal
from datetime import datetime, timezone, timedelta

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.filter_cache = {}
        self.slowmode_cache = {}
        self.db = asyncpg.Pool
    
    async def get_filters_for_context(self, guild_id: int, channel_id: int, user_id: int, role_ids: List[int]) -> List[dict]:
        cache_key = (guild_id, channel_id, user_id, tuple(sorted(role_ids)))
        if cache_key in self.filter_cache:
            return self.filter_cache[cache_key]
        
        filters = await self.db.fetch(
            """
            SELECT * FROM chat_filters
            WHERE guild_id = $1 AND (
                target_type = 'server' OR
                (target_type = 'channel' AND target_id = $2) OR
                (target_type = 'user' AND target_id = $3) OR
                (target_type = 'role' AND target_id = ANY($4::bigint[]))
            )
            """,
            guild_id, channel_id, user_id, role_ids
        )

        self.filter_cache[cache_key] = filters
        return filters
    
    async def get_slowmode_for_context(self, guild_id: int, channel_id: int, user_id: int, role_ids: List[int]) -> Optional[dict]:
        cache_key = (guild_id, channel_id, user_id, tuple(sorted(role_ids)))
        if cache_key in self.slowmode_cache:
            return self.slowmode_cache[cache_key]
        
        slowmode = await self.db.fetchrow(
            """
            SELECT * FROM manual_slowmodes 
            WHERE guild_id = $1 AND enabled = TRUE AND (
                (user_id = $3) OR
                (role_id = ANY($4::bigint[])) OR
                (channel_id = $2) OR
                (channel_id IS NULL AND user_id IS NULL AND role_id IS NULL)
            )
            ORDER BY 
                CASE 
                    WHEN user_id IS NOT NULL THEN 1
                    WHEN role_id IS NOT NULL THEN 2
                    WHEN channel_id IS NOT NULL THEN 3
                    ELSE 4
                END
            LIMIT 1
            """,
            guild_id, channel_id, user_id, role_ids
        )
        
        self.slowmode_cache[cache_key] = slowmode
        return slowmode
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or message.author.guild_permissions.manage_messages:
            return
        
        role_ids = [role.id for role in getattr(message.author, 'roles', [])]

        slowmode = await self.get_slowmode_for_context(
            message.guild.id,
            message.channel.id,
            message.author.id,
            role_ids
        )

        if slowmode:
            last_message = None
            async for msg in message.channel.history(limit=10):
                if msg.author == message.author and msg.id != message.id:
                    last_message = msg
                    break
            
            if last_message and (datetime.now(timezone.utc) - last_message.created_at).total_seconds() < slowmode['delay_seconds']:
                try:
                    await message.delete()
                    await message.channel.send(f"{message.author.mention}, your message was deleted due to slowmode. Please wait {slowmode['delay_seconds']} seconds between messages.", delete_after=10, allowed_mentions=discord.AllowedMentions(users=True))
                except discord.Forbidden:
                    pass
                return
        
        filters = await self.get_filters_for_context(
            message.guild.id,
            message.channel.id,
            message.author.id,
            role_ids
        )

        for filter in filters:
            try:
                if filter['filter_type'] == 'regex':
                    if re.search(filter['pattern'], message.content, re.IGNORECASE):
                        await self.handle_filter_trigger(filter, message)
                elif filter['filter_type'] == 'word':
                    if any(word.lower() in message.content.lower() for word in filter['pattern'].split(',')):
                        await self.handle_filter_trigger(filter, message)
                elif filter['filter_type'] == 'link':
                    if any(link in message.content.lower() for link in filter['pattern'].split(',')):
                        await self.handle_filter_trigger(filter, message)
            except Exception:
                pass
    
    async def handle_filter_trigger(self, filter: dict, message: discord.Message):
        try:
            await message.delete()
            if filter['custom_message']:
                try:
                    await message.author.send(filter['custom_message'])
                except discord.Forbidden:
                    pass
            if filter['action'] == 'delete':
                pass
            elif filter['action'] == 'warn':
                await message.channel.send(f"{message.author.mention}, your message was deleted because it was violating the chat filter.", delete_after=10, allowed_mentions=discord.AllowedMentions(users=True))
            elif filter['action'] == 'mute':
                try:
                    duration_minutes = filter.get('duration_minutes', 60)
                    duration = timedelta(minutes=duration_minutes)
                    await message.author.timeout(duration, reason="Violated chat filter.")
                    await message.channel.send(f"{message.author.mention} has been timed out for {duration_minutes} minutes for violating the chat filter.", delete_after=10, allowed_mentions=discord.AllowedMentions(users=True))
                except discord.Forbidden:
                    pass
            elif filter['action'] == 'kick':
                try:
                    await message.author.kick(reason="Violated the chat filter.")
                except discord.Forbidden:
                    pass
            elif filter['action'] == 'ban':
                try:
                    await message.author.ban(reason="Violated the chat filter.", delete_message_seconds=0)
                except discord.Forbidden:
                    pass
        except discord.Forbidden:
            pass
    
    @commands.hybrid_group(name="filter", description="Manage chat filter rules.")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def filter_group(self, ctx: commands.Context):
        return
    
    @filter_group.command(name="server", description="Add a server-wide filter.")
    @commands.has_permissions(manage_messages=True)
    @app_commands.describe(
        filter_type="Type of filter.",
        pattern="Pattern to match.",
        action="Action to take.",
        custom_message="Optional DM.",
        duration_minutes="Timeout duration for mute action."
    )
    async def filter_server(
        self,
        ctx: commands.Context,
        filter_type: Literal['regex', 'word', 'link'],
        pattern: str,
        action: Literal['delete', 'warn', 'mute', 'kick', 'ban'],
        custom_message: Optional[str] = None,
        duration_minutes: Optional[int] = 60
    ):
        await ctx.typing()
        await self._add_filter(ctx, 'server', None, filter_type, pattern, action, custom_message, duration_minutes)
    
    @filter_group.command(name="channel", description="Add a channel specific filter.")
    @commands.has_permissions(manage_messages=True)
    @app_commands.describe(
        channel="Channel to target.",
        filter_type="Type of filter.",
        pattern="Pattern to match.",
        action="Action to take.",
        custom_message="Optional DM.",
        duration_minutes="Timeout duration for mute action."
    )
    async def filter_channel(
        self,
        ctx: commands.Context,
        channel: discord.abc.GuildChannel | discord.Thread,
        filter_type: Literal['regex', 'word', 'link'],
        pattern: str,
        action: Literal['delete', 'warn', 'mute', 'kick', 'ban'],
        custom_message: Optional[str] = None,
        duration_minutes: Optional[int] = 60
    ):
        await ctx.typing()
        await self._add_filter(ctx, 'channel', channel.id, filter_type, pattern, action, custom_message, duration_minutes)
    
    @filter_group.command(name="user", description="Add a user specific filter.")
    @commands.has_permissions(manage_messages=True)
    @app_commands.describe(
        user="User to target.",
        filter_type="Type of filter.",
        pattern="Pattern to match.",
        action="Action to take.",
        custom_message="Optional DM.",
        duration_minutes="Timeout duration for mute action."
    )
    async def filter_user(
        self,
        ctx: commands.Context,
        user: discord.User,
        filter_type: Literal['regex', 'word', 'link'],
        pattern: str,
        action: Literal['delete', 'warn', 'mute', 'kick', 'ban'],
        custom_message: Optional[str] = None,
        duration_minutes: Optional[int] = 60
    ):
        await ctx.typing()
        await self._add_filter(ctx, 'user', user.id, filter_type, pattern, action, custom_message, duration_minutes)
    
    @filter_group.command(name="role", description="Add a role specific filter.")
    @commands.has_permissions(manage_messages=True)
    @app_commands.describe(
        role="Role to target.",
        filter_type="Type of filter.",
        pattern="Pattern to match.",
        action="Action to take.",
        custom_message="Optional DM.",
        duration_minutes="Timeout duration for mute action."
    )
    async def filter_role(
        self,
        ctx: commands.Context,
        role: discord.Role,
        filter_type: Literal['regex', 'word', 'link'],
        pattern: str,
        action: Literal['delete', 'warn', 'mute', 'kick', 'ban'],
        custom_message: Optional[str] = None,
        duration_minutes: Optional[int] = 60
    ):
        await ctx.typing()
        await self._add_filter(ctx, 'role', role.id, filter_type, pattern, action, custom_message, duration_minutes)
    
    async def _add_filter(
        self,
        ctx: commands.Context,
        target_type: str,
        target_id: Optional[int],
        filter_type: str,
        pattern: str,
        action: str,
        custom_message: Optional[str],
        duration_minutes: Optional[int]
    ):
        if action == 'mute':
            if not duration_minutes or duration_minutes <= 0:
                await ctx.send("Timeout duration must be greater than 0.", ephemeral=True)
                return
            if duration_minutes > 40320:
                await ctx.send("Maximum timeout is 28 days. (40320 minutes)", ephemeral=True)
                return
        else:
            duration_minutes = None
        
        try:
            if filter_type == 'regex':
                re.compile(pattern)
        except re.error:
            await ctx.send("Invalid regex pattern.", ephemeral=True)
            return
        
        try:
            await self.db.execute(
                """
                INSERT INTO chat_filters (
                    guild_id, filter_type, pattern, action,
                    target_type, target_id, custom_message,
                    duration_minutes, added_by
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                ctx.guild.id, filter_type, pattern, action,
                target_type, target_id, custom_message,
                duration_minutes, ctx.author.id
            )
            self.filter_cache.clear()
            target_name = {
                'server': 'server-wide',
                'channel': f"<#{target_id}>",
                'user': f"<@{target_id}>",
                'role': f"<@&{target_id}>"
            }[target_type]
            response = f"Added **{filter_type}** filter for {target_name} -> `{action}`"
            if action == 'mute':
                response += f" ({duration_minutes}m)"
            await ctx.send(response)
        except Exception as e:
            await ctx.send(f"Failed to add filter: {str(e)}")
    
    @filter_group.command(name="list", description="List all filters.", aliases=["ls"])
    @commands.has_permissions(manage_messages=True)
    async def filter_list(self, ctx: commands.Context):
        await ctx.typing()
        rows = await self.db.fetch(
            "SELECT * FROM chat_filters WHERE guild_id = $1 ORDER BY target_type, id",
            ctx.guild.id
        )
        if not rows:
            await ctx.send("No filters were set up.", ephemeral=True)
            return

        embed = discord.Embed(title="Chat Filters", color=discord.Color.blurple())
        for r in rows:
            target = "Server-wide"
            if r['target_type'] == 'channel':
                target = f"<#{r['target_id']}>"
            elif r['target_type'] == 'user':
                target = f"<@{r['target_id']}>"
            elif r['target_type'] == 'role':
                target = f"<@&{r['target_id']}>"

            embed.add_field(
                name=f"ID `{r['id']}` | {r['filter_type'].upper()} -> {r['action'].upper()}",
                value=(
                    f"**Pattern:** `{r['pattern'][:60]}{'...' if len(r['pattern']) > 60 else ''}`\n"
                    f"**Target:** {target}\n"
                    f"**Duration:** {r.get('duration_minutes', 'N/A')} min\n"
                    f"**Added by:** <@{r['added_by']}>"
                ),
                inline=False
            )
        embed.set_footer(text=f"Requested by {ctx.author.name}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)
    
    @filter_group.command(name="remove", description="Remove a filter by ID.", aliases=["rm"])
    @commands.has_permissions(manage_messages=True)
    @app_commands.describe(filter_id="The filter ID to remove.")
    async def filter_remove(self, ctx: commands.Context, filter_id: int):
        await ctx.typing()
        result = await self.db.fetchrow(
            "DELETE FROM chat_filters WHERE guild_id = $1 AND id = $2 RETURNING *",
            ctx.guild.id, filter_id
        )
        if result:
            self.filter_cache.clear()
            await ctx.send(f"Filter ID `{filter_id}` removed.")
        else:
            await ctx.send(f"No filter with ID `{filter_id}` exists.", ephemeral=True)
    
    @commands.hybrid_group(name="slowmode", description="Set manual slowmode on any target.")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def slowmode_group(self, ctx: commands.Context):
        return
    
    @slowmode_group.command(name="server", description="Set server-wide manual slowmode.")
    @commands.has_permissions(manage_channels=True)
    @app_commands.describe(delay="Slowmode in seconds.")
    async def slowmode_server(self, ctx: commands.Context, delay: int):
        await self._set_slowmode(ctx, 'server', None, delay)
    
    @slowmode_group.command(name="channel", description="Set manual slowmode for a specific channel.")
    @commands.has_permissions(manage_channels=True)
    @app_commands.describe(channel="Channel to target.", delay="Slowmode in seconds.")
    async def slowmode_channel(self, ctx: commands.Context, channel: discord.abc.GuildChannel | discord.Thread, delay: int):
        await self._set_slowmode(ctx, 'channel', channel.id, delay)
    
    @slowmode_group.command(name="user", description="Set manual slowmode for a specific user.")
    @commands.has_permissions(manage_channels=True)
    @app_commands.describe(user="User to target.", delay="Slowmode in seconds.")
    async def slowmode_user(self, ctx: commands.Context, user: discord.User, delay: int):
        await self._set_slowmode(ctx, 'user', user.id, delay)
    
    @slowmode_group.command(name="role", description="Set manual slowmode for a specific role.")
    @commands.has_permissions(manage_channels=True)
    @app_commands.describe(role="Role to target.", delay="Slowmode in seconds.")
    async def slowmode_role(self, ctx: commands.Context, role: discord.Role, delay: int):
        await self._set_slowmode(ctx, 'role', role.id, delay)
    
    @slowmode_group.command(name="list", description="List all active manual slowmode rules.", aliases=["ls"])
    @commands.has_permissions(manage_channels=True)
    async def slowmode_list(self, ctx: commands.Context):
        await ctx.typing()
        rows = await self.db.fetch(
            """
            SELECT * FROM manual_slowmodes 
            WHERE guild_id = $1 AND enabled = TRUE
            ORDER BY 
                user_id NULLS LAST,
                role_id NULLS LAST,
                channel_id NULLS LAST
            """,
            ctx.guild.id
        )
        if not rows:
            await ctx.send("No active manual slowmode rules were set.", ephemeral=True)
            return

        embed = discord.Embed(title="Manual Slowmode Rules", color=discord.Color.orange())
        for r in rows:
            if r['user_id'] is not None:
                target = f"<@{r['user_id']}>"
            elif r['role_id'] is not None:
                target = f"<@&{r['role_id']}>"
            elif r['channel_id'] is not None:
                target = f"<#{r['channel_id']}>"
            else:
                target = "Server-wide"

            embed.add_field(
                name=f"ID `{r['id']}`",
                value=(
                    f"**Target:** {target}\n"
                    f"**Delay:** {r['delay_seconds']} second(s)\n"
                    f"**Added by:** <@{r['added_by']}>"
                ),
                inline=False
            )
        embed.set_footer(text=f"Requested by {ctx.author.name}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)
    
    @slowmode_group.command(name="remove", description="Remove a manual slowmode rule by ID.", aliases=["rm"])
    @commands.has_permissions(manage_channels=True)
    @app_commands.describe(rule_id="The manual slowmode rule ID to remove.")
    async def slowmode_remove(self, ctx: commands.Context, rule_id: int):
        await ctx.typing()
        result = await self.db.fetchrow(
            "DELETE FROM manual_slowmodes WHERE guild_id = $1 AND id = $2 RETURNING *",
            ctx.guild.id, rule_id
        )
        if result:
            self.slowmode_cache.clear()
            target = "Server-wide"
            if result['user_id']:
                target = f"User <@{result['user_id']}>"
            elif result['role_id']:
                target = f"Role <@&{result['role_id']}>"
            elif result['channel_id']:
                target = f"Channel <#{result['channel_id']}>"

            await ctx.send(f"Slowmode rule ID `{rule_id}` ({target}) has been removed.")
        else:
            await ctx.send(f"No slowmode rule found with ID `{rule_id}`.", ephemeral=True)
    
    async def _set_slowmode(self, ctx: commands.Context, target_type: str, target_id: Optional[int], delay: int):
        await ctx.typing()
        if delay < 0:
            await ctx.send("Delay cannot be negative.", ephemeral=True)
            return
        enabled = delay > 0

        channel_id = target_id if target_type == 'channel' else None
        user_id = target_id if target_type == 'user' else None
        role_id = target_id if target_type == 'role' else None

        try:
            await self.db.execute(
            """
            INSERT INTO manual_slowmodes (
                guild_id, channel_id, user_id, role_id,
                delay_seconds, enabled, added_by
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (guild_id, channel_id, user_id, role_id)
            DO UPDATE SET
                delay_seconds = EXCLUDED.delay_seconds,
                enabled = EXCLUDED.enabled
            """,
            ctx.guild.id, channel_id, user_id, role_id,
            delay, enabled, ctx.author.id
        )
            self.slowmode_cache.clear()

            target_name = {
                'server': 'Server-wide',
                'channel': f"<#{target_id}>",
                'user': f"<@{target_id}>",
                'role': f"<@&{target_id}>"
            }[target_type]
            status = f"set to {delay}s" if enabled else "disabled"
            await ctx.send(f"{target_name} slowmode {status}.")
        except Exception as e:
            await ctx.send(f"Setting manual slowmode failed: {str(e)}", ephemeral=True)

    @commands.hybrid_command(name="ban", description="Bans provided member(s) or user(s).")
    @app_commands.describe(
        members="Members or users to ban. Can be multiple.",
        delete_days="Number of days worth of messages to delete.",
        reason="Reason for the ban."
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx: commands.Context, members: commands.Greedy[discord.User], delete_days: Optional[int] = 0, *, reason: str = "No reason provided."):
        await ctx.typing()
        delete_seconds = delete_days * 86400
        audit_log_reason = f"Timestamp: {datetime.now(timezone.utc)}\nAdmin: {ctx.author}\nReason: {reason}"

        banned_users = []
        guild = ctx.guild

        for user in members:
            if user == ctx.author:
                await ctx.send("You cannot ban yourself.")
                continue


            member = guild.get_member(user.id)


            if member is not None:
                if member.top_role >= ctx.author.top_role:
                    await ctx.send(f"You can't ban `{member}` because they have an equal or higher role than you.")
                    continue


                if member.top_role >= ctx.me.top_role:
                    await ctx.send(f"I can't ban `{member}` because they have an equal or higher role than me.")
                    continue

            try:
                await guild.ban(user, delete_message_seconds=delete_seconds, reason=audit_log_reason)
                banned_users.append(str(user))
            except discord.Forbidden:
                await ctx.send(f"I don't have permission to ban `{user}`.")
            except discord.HTTPException as e:
                await ctx.send(f"Failed to ban `{user}`: {e}")

        if banned_users:
            await ctx.send(f"Banned member(s): `{', '.join(banned_users)}`\n**Reason:** `{reason}`\n(Messages will be deleted up to {delete_days} day(s) back)")
        else:
            pass


        reference = ctx.message.reference
        if reference and isinstance(reference.resolved, discord.Message):
            replied_msg = reference.resolved
            replied_user = replied_msg.author

            if replied_user == ctx.author:
                await ctx.send("You cannot ban yourself via reply.")
                return

            replied_member = guild.get_member(replied_user.id)

            if replied_member:
                if replied_member.top_role >= ctx.author.top_role:
                    await ctx.send(f"You can't ban `{replied_member}` because they have an equal or higher role than you.")
                    return

                if replied_member.top_role >= ctx.me.top_role:
                    await ctx.send(f"I can't ban `{replied_member}` because they have an equal or higher role than me.")
                    return

            try:
                await guild.ban(replied_user, delete_message_seconds=delete_seconds, reason=audit_log_reason)
                await ctx.send(f"Banned replied user: `{replied_user}`\n**Reason:** `{reason}`\n(Messages will be deleted up to {delete_days} day(s) back)")
            except discord.Forbidden:
                await ctx.send(f"I don't have permission to ban `{replied_user}`.")
            except discord.HTTPException as e:
                await ctx.send(f"Failed to ban `{replied_user}`: {e}")
    
    @commands.hybrid_command(name="kick", description="Kicks provided member(s).")
    @app_commands.describe(
        members="Members to kick. Can be multiple.",
        reason="Reason for the kick."
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx: commands.Context, members: commands.Greedy[discord.Member], *, reason: str = "No reason provided."):
        await ctx.typing()
        audit_log_reason = f"Timestamp: {datetime.now(timezone.utc)}\nAdmin: {ctx.author}\nReason: {reason}"

        kicked_users = []
        guild = ctx.guild

        for member in members:
            if member == ctx.author:
                await ctx.send("You cannot kick yourself.")
                continue


            if member.top_role >= ctx.author.top_role:
                await ctx.send(f"You can't kick `{member}` because they have an equal or higher role than you.")
                continue

            if member.top_role >= ctx.me.top_role:
                await ctx.send(f"I can't kick `{member}` because they have an equal or higher role than me.")
                continue

            try:
                await member.kick(reason=audit_log_reason)
                kicked_users.append(str(member))
            except discord.Forbidden:
                await ctx.send(f"I don't have permission to kick `{member}`.")
            except discord.HTTPException as e:
                await ctx.send(f"Failed to kick `{member}`: {e}")

        if kicked_users:
            await ctx.send(f"Kicked member(s): `{', '.join(kicked_users)}`\n**Reason:** `{reason}`")
        else:
            pass


        reference = ctx.message.reference
        if reference and isinstance(reference.resolved, discord.Message):
            replied_msg = reference.resolved
            replied_member = replied_msg.author

            if not isinstance(replied_member, discord.Member):
                replied_member = guild.get_member(replied_member.id)
                if replied_member is None:
                    await ctx.send("Replied user is not in this server.")
                    return

            if replied_member == ctx.author:
                await ctx.send("You cannot kick yourself via reply.")
                return

            if replied_member.top_role >= ctx.author.top_role:
                await ctx.send(f"You can't kick `{replied_member}` because they have an equal or higher role than you.")
                return

            if replied_member.top_role >= ctx.me.top_role:
                await ctx.send(f"I can't kick `{replied_member}` because they have an equal or higher role than me.")
                return

            try:
                await replied_member.kick(reason=audit_log_reason)
                await ctx.send(f"Kicked replied user: `{replied_member}`\n**Reason:** `{reason}`")
            except discord.Forbidden:
                await ctx.send(f"I don't have permission to kick `{replied_member}`.")
            except discord.HTTPException as e:
                await ctx.send(f"Failed to kick `{replied_member}`: {e}")

async def setup(bot):
    cog = Moderation(bot)
    cog.db = await asyncpg.create_pool(bot_info.data['database'])
    await bot.add_cog(cog)