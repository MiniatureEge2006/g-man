import discord
from discord import app_commands
from discord.ext import commands
import time
import psutil

class Ping(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = time.time()
    

    @commands.hybrid_command(name="ping", description="Get info and latency about G-Man.", aliases=["pong", "latency", "whatsmylatency"])
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def ping(self, ctx: commands.Context):
        ws_latency = round(self.bot.latency * 1000, 2)

        start_time = time.perf_counter()
        message = await ctx.send("Pinging...")
        end_time = time.perf_counter()
        api_response_time = round((end_time - start_time) * 1000, 2)

        current_time = time.time()
        uptime_seconds = int(current_time - self.start_time)
        uptime = self.format_uptime(uptime_seconds)

        cpu_usage = psutil.cpu_percent()
        memory_info = psutil.virtual_memory()
        memory_usage = round(memory_info.used / (1024 ** 2), 2)
        memory_total = round(memory_info.total / (1024 ** 2), 2)

        embed = discord.Embed(title="Pong!", color=discord.Color.green())
        embed.add_field(name="WebSocket Latency", value=f"{ws_latency}ms", inline=True)
        embed.add_field(name="API Response Time", value=f"{api_response_time}ms", inline=True)
        embed.add_field(name="Uptime", value=uptime, inline=False)
        embed.add_field(name="CPU Usage", value=f"{cpu_usage}%", inline=True)
        embed.add_field(
            name="Memory Usage",
            value=f"{memory_usage} MB / {memory_total} MB",
            inline=True
        )
        embed.set_author(name=f"{ctx.author.name}#{ctx.author.discriminator}", url=f"https://discord.com/users/{ctx.author.id}", icon_url=ctx.author.display_avatar.url)
        embed.timestamp = discord.utils.utcnow()

        await message.edit(content=None, embed=embed)
    
    def format_uptime(self, seconds):
        days, seconds = divmod(seconds, 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        parts.append(f"{seconds}s")
        return " ".join(parts)
    

async def setup(bot):
    await bot.add_cog(Ping(bot))