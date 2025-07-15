import re
from typing import List
import discord
import aiohttp
from discord.ext import commands
from discord import app_commands
import time
from io import BytesIO
import asyncio

class CodeInputModal(discord.ui.Modal, title="Code Input"):
    def __init__(self, cog, language="bash"):
        super().__init__()
        self.cog = cog
        self.language = language
        self.code_input = discord.ui.TextInput(
            label=f"Enter your {language} code",
            style=discord.TextStyle.paragraph,
            placeholder="Put your code here...",
            required=True,
            max_length=4000
        )
        self.add_item(self.code_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        class ModalContext:
            def __init__(self, interaction):
                self.bot = interaction.client
                self.author = interaction.user
                self.interaction = interaction
                self.send = interaction.followup.send
                self.typing = lambda: interaction.response.defer()
                self.message = None
        
        ctx = ModalContext(interaction)
        await self.cog._execute_code(ctx, self.language, self.code_input.value)

class CodePaginator(discord.ui.View):
    def __init__(self, total_pages: List[str], original_author):
        super().__init__()
        self.current_page = 0
        self.timeout = 60
        self.original_author = original_author
        self.message = None
        self.total_pages = total_pages
        self.language = "bash"
    
    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user != self.original_author:
            await interaction.response.send_message("You can't control this pagination.", ephemeral=True)
            return False
        return True
    
    async def on_timeout(self):
        await self.message.edit(view=None)
    
    async def update_message(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title=f"{self.language.capitalize()} Execution",
            description=f"```{self.language}\n{self.total_pages[self.current_page]}\n```",
            color=interaction.message.embeds[0].color
        )
        original_embed = interaction.message.embeds[0]
        if original_embed.author:
            embed.set_author(
                name=original_embed.author.name,
                icon_url=original_embed.author.icon_url,
                url=original_embed.author.url
            )
        if original_embed.footer:
            footer_text = original_embed.footer.text.split("|")[0].strip()
            embed.set_footer(
                text=f"{footer_text} | Page {self.current_page + 1}/{len(self.total_pages)}",
                icon_url=original_embed.footer.icon_url
            )
        
        await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label="⏮️", style=discord.ButtonStyle.blurple)
    async def first_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = 0
        await self.update_message(interaction)
    
    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.blurple)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_message(interaction)

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.blurple)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.total_pages) - 1:
            self.current_page += 1
            await self.update_message(interaction)

    @discord.ui.button(label="⏭️", style=discord.ButtonStyle.blurple)
    async def last_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = len(self.total_pages) - 1
        await self.update_message(interaction)

    @discord.ui.button(label="🔢", style=discord.ButtonStyle.green)
    async def jump_to_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = JumpToPageModal(paginator_view=self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🗑️", style=discord.ButtonStyle.red)
    async def delete_message(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()
        self.stop()

    @discord.ui.button(label="⏹️", style=discord.ButtonStyle.gray)
    async def hide_components(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.edit(view=None)
        self.stop()

class JumpToPageModal(discord.ui.Modal):
    def __init__(self, paginator_view: CodePaginator):
        super().__init__(title="Jump to Page")
        self.paginator_view = paginator_view
        self.page_input = discord.ui.TextInput(
            label="Page Number",
            placeholder=f"Enter a number between 1 and {len(self.paginator_view.total_pages)}",
            required=True
        )
        self.add_item(self.page_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            page = int(self.page_input.value) - 1
            if 0 <= page < len(self.paginator_view.total_pages):
                self.paginator_view.current_page = page
                await self.paginator_view.update_message(interaction)
            else:
                await interaction.response.send_message("Invalid page number.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Please enter a valid number.", ephemeral=True)


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
    
    async def _execute_code(self, ctx: commands.Context, language, code, files=None):
        start_time = time.time()
        send = getattr(ctx, 'send', None)
        if send is None:
            send = ctx.interaction.followup.send if hasattr(ctx, 'interaction') else None
        if send is None:
            raise ValueError("Cannot determine send method for this context")
        try:
            result = await self.execute_code(language, code, files=files)
            output = result.get("output", "").replace('\r\n', '\n').strip()
            status = result.get("error", False) or ("error" in result.get("output", "").lower())
            
            if not output:
                output = "Code execution succeeded with no console output" if not status else "Code execution failed with no output"
            
            pages = [output[i:i+1980] for i in range(0, len(output), 1980)]

            embed = discord.Embed(
                title=f"{language.capitalize()} Execution",
                description=f"```{language}\n{pages[0]}\n```",
                color=discord.Color.red() if status else discord.Color.green()
            )

            view = CodePaginator(total_pages=pages, original_author=ctx.author)
            view.language = language

            embed.set_author(
                name=f"{ctx.author.name}",
                icon_url=ctx.author.display_avatar.url,
                url=f"https://discord.com/users/{ctx.author.id}"
            )
            embed.set_footer(
                text=f"Executed in {time.time() - start_time:.2f}s | Page 1/{len(pages)}",
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
                    view.message = await send(embed=embed, files=file_objs, view=view)
                    return
            
            view.message = await send(embed=embed, view=view)

        except Exception as e:
            error_embed = discord.Embed(
                title="Code execution Error",
                description=f"```\n{str(e)[:2000]}\n```",
                color=discord.Color.red()
            )
            await send(embed=error_embed)
    
    @commands.hybrid_command(name="code", description="Execute code.", with_app_command=True)
    @app_commands.describe(
        language="The programming language. (default: bash)",
        code="The code to execute. (leave empty to open code input modal.)"
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def code(self, ctx: commands.Context, language: str = "bash", *, code: str = None):
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
            "kt": "kotlin",
            "nim": "nim"
        }.get(language.lower(), language.lower())
        
        if code is None and isinstance(ctx.interaction, discord.Interaction):
            modal = CodeInputModal(self, language)
            await ctx.interaction.response.send_modal(modal)
            return
        await ctx.typing()
        
        attachments = ctx.message.attachments if hasattr(ctx, 'message') else []
        files = attachments if attachments else []

        if not ctx.interaction and language == "bash" and code is None:
            await ctx.send("Available languages: `python (py)`, `javascript (node, js)`, `typescript (ts)`, `php`, `ruby (rb)`, `lua`, `go`, `rust (rs)`, `c`, `c++ (cpp)`, `c# (cs, csharp)`, `zig`, `java`, `kotlin (kt)`, `nim`")
            return

        markdown_match = re.match(r"```(\w+)\s*([\s\S]+?)```", code)
        if markdown_match:
            extracted_language = markdown_match.group(1).lower()
            extracted_code = markdown_match.group(2).strip()
            if extracted_language:
                language = extracted_language
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
                    "kt": "kotlin",
                    "nim": "nim"
                }.get(language.lower(), language.lower())
            code = extracted_code
        else:
            inline_match = re.match(r"`([^`]+)`", code)
            if inline_match:
                code = inline_match.group(1).strip()
            else:
                code = code.strip()

        await self._execute_code(ctx, language, code, files)

    def cog_unload(self):
        if self.session and not self.session.closed:
            asyncio.create_task(self.session.close())

async def setup(bot):
    await bot.add_cog(Code(bot))