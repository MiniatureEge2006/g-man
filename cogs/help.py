import discord
from discord import app_commands
from discord.ext import commands

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.color = discord.Color.og_blurple()
    

    @commands.hybrid_command(name="help", description="Get a list of my commands.", aliases=["h", "commands", "c", "cmds", "pleasehelpme"])
    @app_commands.describe(command_or_category="The command or category in which you want to see.")
    @app_commands.user_install()
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def help(self, ctx: commands.Context, *, command_or_category: str = None):
        if command_or_category is None:
            embed = self.get_general_help(ctx)
        else:
            embed = self.get_detailed_help(ctx, command_or_category)
        
        await ctx.send(embed=embed)

    def get_general_help(self, ctx: commands.Context):
        embed = discord.Embed(
            title="Help - Command Categories",
            description=f"Use `{ctx.prefix}help <command>` or `{ctx.prefix}help <category>` for more details.",
            color=self.color
        )

        for cog_name, cog in self.bot.cogs.items():
            commands_list = [cmd.name for cmd in cog.get_commands() if not cmd.hidden]
            if commands_list:
                embed.add_field(
                    name=f"**{cog_name}**",
                    value=", ".join(f"`{cmd}`" for cmd in commands_list),
                    inline=False
                )
        
        uncategorized = [cmd.name for cmd in self.bot.commands if cmd.cog is None and not cmd.hidden]
        if uncategorized:
            embed.add_field(
                name="**Uncategorized**",
                value=", ".join(f"`{cmd}`" for cmd in uncategorized),
                inline=False
            )
        
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
        return embed
    
    def get_detailed_help(self, ctx: commands.Context, query):
        cog = self.bot.get_cog(query)
        if cog:
            return self.get_cog_help(ctx, cog)
        
        cmd = self.bot.get_command(query)
        if cmd:
            return self.get_command_help(ctx, cmd)
        
        embed = discord.Embed(
            title="Error",
            description=f"No command or category found for `{query}`",
            color=discord.Color.red()
        )
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
        return embed
    
    def get_cog_help(self, ctx: commands.Context, cog):
        embed = discord.Embed(
            title=f"Category: {cog.qualified_name}",
            description=cog.description or "No description available.",
            color=self.color
        )

        for cmd in cog.get_commands():
            if not cmd.hidden:
                embed.add_field(
                    name=f"`{cmd.name}`",
                    value=cmd.description or "No description available.",
                    inline=False
                )
        
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
        return embed
    
    def get_command_help(self, ctx: commands.Context, cmd):
        embed = discord.Embed(
            title=f"Command: {cmd.name}",
            color=self.color
        )
        embed.add_field(name="Description", value=cmd.description or "No description available.", inline=False)

        aliases = ", ".join(f"`{alias}`" for alias in cmd.aliases) if cmd.aliases else "None"
        embed.add_field(name="Aliases", value=aliases, inline=False)
        embed.add_field(
            name="Usage",
            value=f"`{ctx.prefix}{cmd.qualified_name} {cmd.signature}`",
            inline=False
        )

        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
        return embed


async def setup(bot):
    await bot.add_cog(Help(bot))