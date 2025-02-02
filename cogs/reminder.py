import asyncio
import discord
from discord.ext import commands
from discord import app_commands
import asyncpg
from datetime import datetime, timezone
import dateparser
import bot_info

class Reminder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_pool = None
        self.reminder_task = None
    
    async def cog_load(self):
        if not self.db_pool:
            self.db_pool = await asyncpg.create_pool(bot_info.data['database'])
        if self.reminder_task is not None:
            self.reminder_task.cancel()
            await asyncio.sleep(1)
        self.reminder_task = self.bot.loop.create_task(self.reminder_check())
    
    def cog_unload(self):
        if self.reminder_task is not None:
            self.reminder_task.cancel()
    
    
    async def get_next_reminder_id(self, guild_id: int) -> int:
        query = "SELECT COALESCE(MAX(reminder_id), 0) + 1 AS next_id FROM reminders WHERE guild_id = $1;"
        result = await self.db_pool.fetchval(query, guild_id)
        return result if result else 1

    async def add_reminder(self, user_id: int, guild_id: int, channel_id: int, reminder_text: str, reminder_time: datetime):
        reminder_id = await self.get_next_reminder_id(guild_id) if guild_id else None
        query = "INSERT INTO reminders (user_id, guild_id, channel_id, reminder_id, reminder, reminder_time) VALUES ($1, $2, $3, $4, $5, $6);"
        await self.db_pool.execute(query, user_id, guild_id, channel_id, reminder_id, reminder_text, reminder_time)
    
    @commands.hybrid_command(name="remind", description="Set a reminder for yourself.", aliases=["remindme", "reminder"])
    @app_commands.user_install()
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(user="The user you want to set a reminder for.", time="The time you want to set the reminder for.", reminder_text="What you want to be reminded of.")
    async def remind(self, ctx: commands.Context, user: discord.Member = None, time: str = None, *, reminder_text: str):
        await ctx.typing()
        if not time or not reminder_text:
            await ctx.send("Please provide both a time and a reminder message.")
            return
        if user:
            if not (str(ctx.author.id) in bot_info.data['owners'] or not ctx.author.guild_permissions.manage_guild):
                await ctx.send("You need the `Manage Guild` permission to set a reminder for another user.")
                return
            target_user = user
        else:
            target_user = ctx.author
        reminder_time = dateparser.parse(time, settings={"TIMEZONE": "UTC", "RETURN_AS_TIMEZONE_AWARE": True})
        if not reminder_time:
            await ctx.send("Invalid time format. Please use a format like `tomorrow at 3pm`, `in 1 hour`, or `2 weeks`.")
            return
        current_time = datetime.now(timezone.utc)
        if reminder_time <= current_time:
            await ctx.send("You cannot set a reminder in the past.")
            return
        guild_id = ctx.guild.id if ctx.guild else None
        await self.add_reminder(target_user.id, guild_id, ctx.channel.id, reminder_text, reminder_time)
        await ctx.reply(f"Okay, I'll remind you in <t:{int(reminder_time.timestamp())}:R> (<t:{int(reminder_time.timestamp())}:F>, {reminder_time.strftime('%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)')}) about `{reminder_text}`." if user is ctx.author else f"Okay, I'll remind {target_user.mention} in <t:{int(reminder_time.timestamp())}:R> (<t:{int(reminder_time.timestamp())}:F>, {reminder_time.strftime('%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)')}) about `{reminder_text}`.")
    
    @commands.hybrid_command(name="reminders", description="View your reminders.")
    @app_commands.user_install()
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(user="The user whose reminders you want to view.", global_view="View reminders for an user globally.")
    async def reminders(self, ctx: commands.Context, user: discord.Member = None, global_view: bool = False):
        await ctx.typing()
        query = ""
        params = []
        target_user = user or ctx.author
        if global_view:
            query = "SELECT reminder_id, reminder, reminder_time, guild_id FROM reminders WHERE user_id = $1 ORDER BY reminder_time;"
            params = [target_user.id]
        else:
            query = "SELECT reminder_id, reminder, reminder_time, guild_id FROM reminders WHERE user_id = $1 AND guild_id = $2 ORDER BY reminder_time;"
            params = [target_user.id, ctx.guild.id if ctx.guild else None]
        reminders = await self.db_pool.fetch(query, *params)
        if not reminders:
            if global_view:
                if target_user == ctx.author:
                    await ctx.send("You have no reminders.")
                else:
                    await ctx.send(f"{target_user.display_name} has no reminders.")
            else:
                if target_user == ctx.author:
                    await ctx.send("You have no reminders for this server.")
                else:
                    await ctx.send(f"{target_user.display_name} has no reminders for this server.")
            return
        embed = discord.Embed(title=f"{len(reminders)} {'Global ' if global_view else ''}Reminder(s) for {target_user.display_name}", color=discord.Color.blue())
        for reminder in reminders:
            guild_name = self.bot.get_guild(reminder.get('guild_id')).name if reminder.get('guild_id') and self.bot.get_guild(reminder.get('guild_id')) else "DMs"
            timestamp = int(reminder['reminder_time'].timestamp())
            embed.add_field(name=f"ID: {reminder['reminder_id']}", value=f"Server: {guild_name}\nMessage: {reminder['reminder']}\nTime: <t:{timestamp}:F> (<t:{timestamp}:R>, {reminder['reminder_time'].strftime('%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p')}))", inline=False)
        await ctx.send(embed=embed)
    
    
    @commands.hybrid_command(name="serverreminders", description="View all reminders for the server.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def serverreminders(self, ctx: commands.Context):
        await ctx.typing()
        if not ctx.guild:
            await ctx.send("This command can only be used in a server.")
            return
        query = "SELECT reminder_id, reminder, reminder_time, user_id FROM reminders WHERE guild_id = $1 ORDER BY reminder_time;"
        reminders = await self.db_pool.fetch(query, ctx.guild.id)
        if not reminders:
            await ctx.send("This server has no reminders.")
            return
        embed = discord.Embed(title=f"{len(reminders)} Reminder(s) for {ctx.guild.name}", color=discord.Color.dark_blue())
        for reminder in reminders:
            user_object = self.bot.get_user(reminder['user_id'])
            user_name = user_object.mention if user_object else "Unknown"
            timestamp = int(reminder['reminder_time'].timestamp())
            embed.add_field(name=f"ID: {reminder['reminder_id']}", value=f"**User:** {user_name}\n**Message:** {reminder['reminder']}\n**Time:** <t:{timestamp}:F> (<t:{timestamp}:R>, {reminder['reminder_time'].strftime('%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p')}))", inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="deletereminder", description="Delete a reminder, optionally an user's reminders if you have manage server permissions.", aliases=["reminderdelete", "delreminder"])
    @app_commands.user_install()
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(reminder_id="The ID of the reminder to delete.", user="The user whose reminders you want to delete if you have manage server permissions.")
    async def deletereminder(self, ctx: commands.Context, reminder_id: int, user: discord.Member = None):
        await ctx.typing()
        if ctx.guild is None:
            target_user_id = ctx.author.id
        else:
            if user and (str(ctx.author.id) in bot_info.data['owners'] or ctx.author.guild_permissions.manage_guild):
                target_user_id = user.id
            else:
                target_user_id = ctx.author.id
        query = "DELETE FROM reminders WHERE user_id = $1 AND reminder_id = $2;"
        result = await self.db_pool.execute(query, target_user_id, reminder_id)
        if result.split(" ")[1] == "1":
            await ctx.send(f"Reminder for {user.display_name} with ID {reminder_id} has been deleted.")
        else:
            await ctx.send(f"No reminder with ID {reminder_id} found for {user.display_name}.")
    
    @commands.hybrid_command(name="clearreminders", description="Clear all reminders for yourself or user/server if you have manage server permissions.", aliases=["remindersclear", "clreminders"])
    @app_commands.user_install()
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(user="The user whose reminders you want to clear if you have manage server permissions.", server="Clear all reminders for the server if you have manage server permissions.")
    async def clearreminders(self, ctx: commands.Context, server: bool = False, user: discord.Member = None):
        await ctx.typing()
        if ctx.guild is None:
            if user or server:
                await ctx.send("You can only clear other users' or server reminders in a server.")
                return
            target_user_id = ctx.author.id
            query = "DELETE FROM reminders WHERE user_id = $1;"
            await self.db_pool.execute(query, target_user_id)
            await ctx.send(f"All your reminders have been cleared.")
            return
        if server:
            if not (str(ctx.author.id) in bot_info.data['owners'] or not ctx.author.guild_permissions.manage_guild):
                await ctx.send("You need the `Manage Guild` permission to clear reminders for the server.")
                return
            query = "DELETE FROM reminders WHERE guild_id = $1;"
            await self.db_pool.execute(query, ctx.guild.id)
            await ctx.send(f"All reminders for {ctx.guild.name} have been cleared.")
        else:
            target_user_id = user.id if user and (ctx.author.id in bot_info.data['owners'] or ctx.author.guild_permissions.manage_guild) else ctx.author.id
            query = "DELETE FROM reminders WHERE user_id = $1;"
            await self.db_pool.execute(query, target_user_id)
            await ctx.send(f"All reminders for {user.display_name if user else 'you'} have been cleared.")
    
    async def reminder_check(self):
        if not self.db_pool:
            return
        while True:
            query = "SELECT id, user_id, guild_id, channel_id, reminder_id, reminder, reminder_time FROM reminders WHERE reminder_time > $1 ORDER BY reminder_time ASC LIMIT 1;"
            current_time = datetime.now(timezone.utc)
            reminder = await self.db_pool.fetchrow(query, current_time)
            if reminder is None:
                await asyncio.sleep(5)
                continue
            reminder_time = reminder['reminder_time']
            time_to_sleep = max(0, (reminder_time - current_time).total_seconds())
            await asyncio.sleep(time_to_sleep)
            confirmation_query = "SELECT reminder_id FROM reminders WHERE reminder_id = $1;"
            confirmed_reminder = await self.db_pool.fetchval(confirmation_query, reminder['reminder_id'])
            if confirmed_reminder:
                channel = self.bot.get_channel(reminder['channel_id'])
                user = self.bot.get_user(reminder['user_id'])
                if user:
                    try:
                        if channel:
                            await channel.send(f"{user.mention}, reminder from <t:{int(reminder_time.timestamp())}:R> (<t:{int(reminder_time.timestamp())}:F>, {reminder_time.strftime('%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)')}): `{reminder['reminder']}`")
                        else:
                            dm_channel = await user.create_dm()
                            await dm_channel.send(f"{user.mention}, reminder from <t:{int(reminder_time.timestamp())}:R> (<t:{int(reminder_time.timestamp())}:F>, {reminder_time.strftime('%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)')}): `{reminder['reminder']}`")
                    except (discord.Forbidden, AttributeError):
                        pass
                delete_query = "DELETE FROM reminders WHERE reminder_id = $1;"
                await self.db_pool.execute(delete_query, reminder['reminder_id'])
    

async def setup(bot):
    await bot.add_cog(Reminder(bot))