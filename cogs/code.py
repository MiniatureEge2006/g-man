import re
import discord
import aiohttp
from discord.ext import commands
import time
from io import BytesIO
import asyncio

class Code(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session = None
    
    async def ensure_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
    
    async def execute_code(self, language: str, code: str, files: list = None):
        await self.ensure_session()
        url = f"http://localhost:8000/{language}/execute"
        data = aiohttp.FormData()
        data.add_field("code", code)
        
        if files:
            for file in files:
                file_bytes = await file.read()
                data.add_field(
                    "files",
                    BytesIO(file_bytes),
                    filename=file.filename,
                    content_type=file.content_type or "application/octet-stream"
                )
        
        async with self.session.post(url, data=data) as response:
            return await response.json()
    
    @commands.command(name="code", description="Execute code.")
    async def code(self, ctx: commands.Context, *, code: str):
        await ctx.typing()
        start_time = time.time()
        
        attachments = ctx.message.attachments
        files = attachments if attachments else []


        markdown_match = re.match(r"```(\w+)\s*([\s\S]+?)```", code)
        if markdown_match:
            language = markdown_match.group(1).lower()
            code = markdown_match.group(2).strip()
        else:
            parts = code.split(maxsplit=1)
            language = parts[0].lower() if len(parts) > 1 else "bash"
            code = parts[1].strip() if len(parts) > 1 else code.strip()


        language = {
            "py": "python",
            "sh": "bash",
            "js": "javascript",
            "node": "javascript",
            "ts": "typescript",
            "php": "php",
            "rb": "ruby",
            "lua": "lua",
            "go": "go",
            "rs": "rust",
            "c": "c",
            "c++": "cpp",
            "cs": "csharp",
            "c#": "csharp",
            "zig": "zig",
            "java": "java",
            "kt": "kotlin"
        }.get(language, language)

        try:
            result = await self.execute_code(language, code, files=files)
            output = result.get("output", "").replace('\r\n', '\n').strip()
            status = result.get("error", False) or ("error" in result.get("output", "").lower())
            

            if not output:
                output = "Code execution succeeded with no console output" if not status else "Code execution failed with no output"


            if len(output) > 2000:
                output = output[:2000]

            embed = discord.Embed(
                title=f"{language.capitalize()} Execution",
                description=f"```{language}\n{output}\n```",
                color=discord.Color.red() if status else discord.Color.green()
            )

            embed.set_author(
                name=f"{ctx.author.name}#{ctx.author.discriminator}",
                icon_url=ctx.author.display_avatar.url,
                url=f"https://discord.com/users/{ctx.author.id}"
            )
            embed.set_footer(
                text=f"Executed in {time.time() - start_time:.2f}s",
                icon_url=self.bot.user.avatar.url
            )


            if result.get('files'):
                file_objs = []
                for filename in result['files'][:10]:
                    file_url = f"http://localhost:8000/files/{filename}"
                    try:
                        async with self.session.get(file_url) as resp:
                            if resp.status == 200:
                                file_data = await resp.read()
                                file_objs.append(discord.File(
                                    BytesIO(file_data), 
                                    filename=filename
                                ))
                    except Exception as e:
                        output += f"\nFailed to fetch {filename}: {str(e)}"
    
                if file_objs:
                    await ctx.send(embed=embed, files=file_objs)
                    return
            
            
            await ctx.send(embed=embed)

        except Exception as e:
            error_embed = discord.Embed(
                title="Code execution Error",
                description=f"```\n{str(e)[:2000]}\n```",
                color=discord.Color.red()
            )
            await ctx.send(embed=error_embed)
    
    

    def cog_unload(self):
        if self.session and not self.session.closed:
            asyncio.create_task(self.session.close())

async def setup(bot):
    await bot.add_cog(Code(bot))