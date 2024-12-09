import discord
from discord.ext import commands

class Info(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    

    @commands.command(name="userinfo", aliases=["user", "member", "memberinfo"], description="Displays information about a user.")
    async def userinfo(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        roles = [role.mention for role in member.roles if role != ctx.guild.default_role]
        embed = discord.Embed(
            title=f"User Info - {member}",
            color=member.color,
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url if member.avatar else member.default_avatar)
        embed.add_field(name="ID", value=member.id, inline=True)
        embed.add_field(name="Name", value=str(member), inline=True)
        embed.add_field(name="Created At", value=member.created_at.strftime("%Y-%m-%d %H:%M:%S"), inline=True)
        embed.add_field(name="Joined Server", value=member.joined_at.strftime("%Y-%m-%d %H:%M:%S"), inline=True)
        embed.add_field(name="Roles", value=", ".join(roles) if roles else "None", inline=False)
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)
    
    @commands.command(name="serverinfo", aliases=["server", "guild", "guildinfo"], description="Displays information about the server.")
    async def serverinfo(self, ctx: commands.Context):
        guild = ctx.guild
        embed = discord.Embed(
            title=f"Server Info - {guild.name}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=guild.icon.url if guild.icon else "")
        embed.add_field(name="ID", value=guild.id, inline=True)
        embed.add_field(name="Owner", value=guild.owner.mention if guild.owner else "Unknown", inline=True)
        embed.add_field(name="Created At", value=guild.created_at.strftime("%Y-%m-%d %H:%M:%S"), inline=True)
        embed.add_field(name="Members", value=f"{guild.member_count} members", inline=True)
        embed.add_field(name="Channels", value=f"{len(guild.channels)} total", inline=True)
        embed.add_field(name="Roles", value=f"{len(guild.roles)} roles", inline=True)
        embed.add_field(name="Boosts", value=f"{guild.premium_subscription_count} boosts", inline=True)
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)
    
    @commands.command(name="channelinfo", aliases=["channel"], description="Displays information about a text channel.")
    async def channelinfo(self, ctx: commands.Context, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        embed = discord.Embed(
            title=f"Channel Info - {channel.name}",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="ID", value=channel.id, inline=True)
        embed.add_field(name="Name", value=channel.name, inline=True)
        embed.add_field(name="Type", value=str(channel.type).capitalize(), inline=True)
        embed.add_field(name="Category", value=channel.category.name if channel.category else "None", inline=True)
        embed.add_field(name="Topic", value=channel.topic if channel.topic else "No topic", inline=False)
        embed.add_field(name="Created At", value=channel.created_at.strftime("%Y-%m-%d %H:%M:%S"), inline=True)
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name="voiceinfo", description="Displays information about a voice channel.")
    async def voiceinfo(self, ctx: commands.Context, channel: discord.VoiceChannel = None):
        channel = channel or ctx.author.voice.channel
        embed = discord.Embed(
            title=f"Voice Channel Info - {channel.name}",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="ID", value=channel.id, inline=True)
        embed.add_field(name="Name", value=channel.name, inline=True)
        embed.add_field(name="Category", value=channel.category.name if channel.category else "None", inline=True)
        embed.add_field(name="Bitrate", value=f"{channel.bitrate // 1000} kbps", inline=True)
        embed.add_field(name="User Limit", value=channel.user_limit or "Unlimited", inline=True)
        embed.add_field(name="Connected Members", value=", ".join([member.mention for member in channel.members]) or "None", inline=False)
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)
    
    @commands.command(name="threadinfo", aliases=["thread"], description="Displays information about a text channel's thread.")
    async def threadinfo(self, ctx: commands.Context, thread: discord.Thread):
        embed = discord.Embed(
            title=f"Thread Info - {thread.name}",
            color=discord.Color.purple(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="ID", value=thread.id, inline=True)
        embed.add_field(name="Owner", value=thread.owner.mention if thread.owner else "Unknown", inline=True)
        embed.add_field(name="Participants", value=", ".join([member.mention for member in thread.members]) or "None", inline=False)
        embed.add_field(name="Message Count", value=thread.message_count, inline=True)
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)
    
    @commands.command(name="messageinfo", description="Displays information about a message.")
    async def messageinfo(self, ctx: commands.Context, message: discord.Message):
        embed = discord.Embed(
            title=f"Message Info - {message.id}",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="ID", value=message.id, inline=True)
        embed.add_field(name="Author", value=message.author.mention, inline=True)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        embed.add_field(name="Content", value=message.content or "None", inline=False)
        embed.add_field(name="Created At", value=message.created_at.strftime("%Y-%m-%d %H:%M:%S"), inline=True)
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)
    
    @commands.command(name="permissions", aliases=["perms"], description="Displays a user's permissions in a channel.")
    async def permissions(self, ctx: commands.Context, member: discord.Member = None, channel: discord.TextChannel = None):
        member = member or ctx.author
        channel = channel or ctx.channel
        perms = channel.permissions_for(member)
        permissions = [perm.replace("_", " ").title() for perm, value in perms if value]
        embed = discord.Embed(
            title=f"Permissions Info - {member} in {channel.name}",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="Permissions", value=", ".join(permissions) or "None", inline=False)
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)
    
    @commands.command(name="baninfo", description="Displays information about a banned user.")
    @commands.has_permissions(ban_members=True)
    async def baninfo(self, ctx: commands.Context, user: discord.User):
        try:
            ban_entry = await ctx.guild.fetch_ban(user)
            embed = discord.Embed(
                title=f"Ban Info - {user}",
                color=discord.Color.dark_red(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="Reason", value=ban_entry.reason or "None", inline=False)
            embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
            await ctx.send(embed=embed)
        except PermissionError:
            await ctx.send("You do not have permission to run this command.")
            return
    
    @commands.command(name="botinfo", description="Displays information about the bot.")
    async def botinfo(self, ctx: commands.Context):
        embed = discord.Embed(
            title=f"Bot Info - {self.bot.user.name}",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="ID", value=self.bot.user.id, inline=True)
        embed.add_field(name="Servers", value=len(self.bot.guilds), inline=True)
        embed.add_field(name="Users", value=len(set(self.bot.get_all_members())), inline=True)
        embed.add_field(name="Developers", value="[nkrasn](https://github.com/nkrasn 'Original Developer.'), [MiniatureEge2006](https://github.com/MiniatureEge2006 'Current Developer.')", inline=True)
        embed.set_thumbnail(url=self.bot.user.avatar.url)
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Info(bot))