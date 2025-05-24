import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
from datetime import datetime, timezone

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="ban", description="Bans provided member(s) or user(s).")
    @app_commands.describe(
        members="Members or users to ban. Can be multiple.",
        delete_days="Number of days worth of messages to delete.",
        reason="Reason for the ban."
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx: commands.Context, members: commands.Greedy[discord.User], delete_days: Optional[int] = 0, reason: str = "No reason provided."):
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
    async def kick(self, ctx: commands.Context, members: commands.Greedy[discord.Member], reason: str = "No reason provided."):
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
    await bot.add_cog(Moderation(bot))