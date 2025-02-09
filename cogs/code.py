import discord
from discord.ext import commands
import aiohttp
import json
import time
import re


class Code(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()
    
    async def execute_code(self, language: str, code: str):
        url = "https://emkc.org/api/v2/piston/execute"
        payload = {
            "language": language,
            "version": "*",
            "files": [{"content": code}]
        }
        headers = {"Content-Type": "application/json"}
        async with self.session.post(url, data=json.dumps(payload), headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                return data.get("run", {}).get("output", "No output")
            else:
                return f"Error: {response.status} - {await response.text()}"
    
    @commands.command(name="code", description="Execute code.")
    async def code(self, ctx: commands.Context, *, code: str):
        await ctx.typing()
        markdown_match = re.match(r"```(\w+)?\n([\s\S]+?)```", code)
        if markdown_match:
            language = markdown_match.group(1)
            code = markdown_match.group(2)
        else:
            parts = code.split(maxsplit=1)
            if len(parts) < 2:
                await ctx.send("Invalid code format. Either specify a language and code or use the markdown format.")
                return
            language, code = parts
        if not language:
            await ctx.send("Please specify a programming language.")
            return
        language = language.lower()
        start_time = time.time()
        output = await self.execute_code(language, code)
        embed = discord.Embed(
            title=f"Code Execution Result - {language.capitalize()}",
            description=f"```{language}\n{output if len(output) < 2000 else output[:2000]}```",
            color=discord.Color.light_gray()
        )
        embed.set_footer(text=f"Executed in {round(time.time() - start_time, 2)} seconds", icon_url=self.bot.user.avatar.url)
        embed.set_author(name=f"{ctx.author.name}#{ctx.author.discriminator}", icon_url=ctx.author.display_avatar.url, url=f"https://discord.com/users/{ctx.author.id}")
        await ctx.send(embed=embed)
    
    async def cog_unload(self):
        await self.session.close()


async def setup(bot):
    await bot.add_cog(Code(bot))