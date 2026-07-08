from typing import List, Union

import discord
from discord import app_commands
from discord.ext import commands


class HelpPaginator(discord.ui.LayoutView):
    def __init__(
        self,
        ctx: commands.Context,
        pages: List[tuple],
        timeout: float = 180.0,
    ):
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.pages = pages
        self.current_page = 0
        self.author_id = ctx.author.id

        self._build_layout()

    def _build_layout(self):
        self.clear_items()

        title, content, color = self.pages[self.current_page]

        container = discord.ui.Container(accent_color=color)

        title_section = discord.ui.Section(
            discord.ui.TextDisplay(f"# {title}"),
            accessory=discord.ui.Thumbnail(self.ctx.author.display_avatar.url),
        )
        container.add_item(title_section)

        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))

        max_display_length = 4000
        if len(content) <= max_display_length:
            container.add_item(discord.ui.TextDisplay(content))
        else:
            chunks = [
                content[i : i + max_display_length]
                for i in range(0, len(content), max_display_length)
            ]
            for chunk in chunks:
                container.add_item(discord.ui.TextDisplay(chunk))

        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))

        footer = discord.ui.TextDisplay(
            f"-# Page {self.current_page + 1}/{len(self.pages)} - Requested by {self.ctx.author.name}"
        )
        container.add_item(footer)

        action_row = discord.ui.ActionRow()

        first_btn = discord.ui.Button(
            label="⏮",
            style=discord.ButtonStyle.secondary,
            custom_id="help_first",
            disabled=(self.current_page == 0),
        )
        first_btn.callback = self.first_button_callback
        action_row.add_item(first_btn)

        prev_btn = discord.ui.Button(
            label="◀",
            style=discord.ButtonStyle.primary,
            custom_id="help_prev",
            disabled=(self.current_page == 0),
        )
        prev_btn.callback = self.previous_button_callback
        action_row.add_item(prev_btn)

        next_btn = discord.ui.Button(
            label="▶",
            style=discord.ButtonStyle.primary,
            custom_id="help_next",
            disabled=(self.current_page == len(self.pages) - 1),
        )
        next_btn.callback = self.next_button_callback
        action_row.add_item(next_btn)

        last_btn = discord.ui.Button(
            label="⏭",
            style=discord.ButtonStyle.secondary,
            custom_id="help_last",
            disabled=(self.current_page == len(self.pages) - 1),
        )
        last_btn.callback = self.last_button_callback
        action_row.add_item(last_btn)

        stop_btn = discord.ui.Button(
            label="⏹ Close", style=discord.ButtonStyle.danger, custom_id="help_stop"
        )
        stop_btn.callback = self.stop_button_callback
        action_row.add_item(stop_btn)

        container.add_item(action_row)
        self.add_item(container)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            error_container = discord.ui.Container(accent_color=discord.Color.red())
            error_container.add_item(
                discord.ui.TextDisplay("You cannot control this help menu.")
            )
            error_view = discord.ui.LayoutView()
            error_view.add_item(error_container)
            await interaction.response.send_message(view=error_view, ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for container in self.children:
            if isinstance(container, discord.ui.Container):
                container.add_item(
                    discord.ui.Separator(spacing=discord.SeparatorSpacing.small)
                )
                container.add_item(
                    discord.ui.TextDisplay("**Help menu has timed out.**")
                )
                for item in container.children:
                    if isinstance(item, discord.ui.ActionRow):
                        for button in item.children:
                            if isinstance(button, discord.ui.Button):
                                button.disabled = True
        if hasattr(self, "message") and self.message:
            await self.message.edit(view=self)
        self.stop()

    async def first_button_callback(self, interaction: discord.Interaction):
        if self.current_page != 0:
            self.current_page = 0
            self._build_layout()
            await interaction.response.edit_message(view=self)

    async def previous_button_callback(self, interaction: discord.Interaction):
        if self.current_page > 0:
            self.current_page -= 1
            self._build_layout()
            await interaction.response.edit_message(view=self)

    async def next_button_callback(self, interaction: discord.Interaction):
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
            self._build_layout()
            await interaction.response.edit_message(view=self)

    async def last_button_callback(self, interaction: discord.Interaction):
        if self.current_page != len(self.pages) - 1:
            self.current_page = len(self.pages) - 1
            self._build_layout()
            await interaction.response.edit_message(view=self)

    async def stop_button_callback(self, interaction: discord.Interaction):
        for container in self.children:
            if isinstance(container, discord.ui.Container):
                for item in container.children:
                    if isinstance(item, discord.ui.ActionRow):
                        for btn in item.children:
                            if isinstance(btn, discord.ui.Button):
                                btn.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()


class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.color = discord.Color.og_blurple()

    @commands.hybrid_command(
        name="help",
        description="Get a list of my commands.",
        aliases=["h", "commands", "c", "cmds", "pleasehelpme"],
    )
    @app_commands.describe(
        command_or_category="The command or category in which you want to see."
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def help(self, ctx: commands.Context, *, command_or_category: str = None):
        if command_or_category is None:
            pages = self.get_general_help_pages(ctx)
        else:
            result = self.get_detailed_help(ctx, command_or_category)
            if isinstance(result, str):
                error_container = discord.ui.Container(
                    accent_color=discord.Color.red().value
                )
                error_container.add_item(discord.ui.TextDisplay("# Error"))
                error_container.add_item(
                    discord.ui.Separator(spacing=discord.SeparatorSpacing.small)
                )
                error_container.add_item(
                    discord.ui.TextDisplay(
                        f"No command or category found for `{command_or_category}`"
                    )
                )

                error_view = discord.ui.LayoutView()
                error_view.add_item(error_container)

                await ctx.send(view=error_view)
                return
            pages = result

        if not pages:
            error_container = discord.ui.Container(
                accent_color=discord.Color.red().value
            )
            error_container.add_item(discord.ui.TextDisplay("# Error"))
            error_container.add_item(
                discord.ui.Separator(spacing=discord.SeparatorSpacing.small)
            )
            error_container.add_item(
                discord.ui.TextDisplay("No commands or categories found.")
            )
            error_view = discord.ui.LayoutView()
            error_view.add_item(error_container)
            await ctx.send(view=error_view)
            return

        paginator = HelpPaginator(ctx, pages)
        await ctx.send(view=paginator)

    def get_general_help_pages(self, ctx: commands.Context) -> List[tuple]:
        pages = []
        MAX_CONTENT_LEN = 3900

        intro = f"""## Welcome to Help Menu

Use `{ctx.prefix}help <command>` or `{ctx.prefix}help <category>` for detailed information about specific commands.

### Available Categories:
"""
        pages.append(("Help Overview", intro, self.color.value))

        current_content = []
        current_length = 0

        for cog_name, cog in self.bot.cogs.items():
            commands_list = [cmd.name for cmd in cog.get_commands() if not cmd.hidden]
            if commands_list:
                category_content = f"### **{cog_name}**\n"
                category_content += ", ".join(f"`{cmd}`" for cmd in commands_list)
                category_content += "\n\n"

                if current_length + len(category_content) > MAX_CONTENT_LEN:
                    pages.append(
                        (
                            f"Commands (Page {len(pages)})",
                            "".join(current_content),
                            self.color.value,
                        )
                    )
                    current_content = [category_content]
                    current_length = len(category_content)
                else:
                    current_content.append(category_content)
                    current_length += len(category_content)

        uncategorized = [
            cmd.name for cmd in self.bot.commands if cmd.cog is None and not cmd.hidden
        ]
        if uncategorized:
            uncat_content = "### **Uncategorized**\n"
            uncat_content += ", ".join(f"`{cmd}`" for cmd in uncategorized)
            uncat_content += "\n\n"

            if current_length + len(uncat_content) > MAX_CONTENT_LEN:
                pages.append(
                    (
                        f"Commands (Page {len(pages)})",
                        "".join(current_content),
                        self.color.value,
                    )
                )
                pages.append(
                    ("Uncategorized Commands", uncat_content, self.color.value)
                )
            else:
                current_content.append(uncat_content)
                pages.append(
                    (
                        f"Commands (Page {len(pages)})",
                        "".join(current_content),
                        self.color.value,
                    )
                )
        elif current_content:
            pages.append(
                (
                    f"Commands (Page {len(pages)})",
                    "".join(current_content),
                    self.color.value,
                )
            )

        return pages

    def get_detailed_help(
        self, ctx: commands.Context, query: str
    ) -> Union[List[tuple], str]:
        cog = self.bot.get_cog(query)
        if cog:
            return self.get_cog_help_pages(ctx, cog)

        cmd = self.bot.get_command(query.lower())
        if cmd:
            return self.get_command_help_page(ctx, cmd)

        return "not_found"

    def get_cog_help_pages(self, ctx: commands.Context, cog) -> List[tuple]:
        content = []

        if cog.description:
            content.append(f"> **{cog.description}**\n\n")

        content.append("## Commands\n\n")

        def get_commands_recursive(cmds, level=0):
            result = []
            indent = "  " * level
            for cmd in cmds:
                if cmd.hidden:
                    continue
                result.append(
                    f"{indent}**`{cmd.name}`** - {cmd.description or 'No description'}\n"
                )
                if isinstance(cmd, commands.Group):
                    result.extend(get_commands_recursive(cmd.commands, level + 1))
            return result

        all_cmds = get_commands_recursive(cog.get_commands())
        content.extend(all_cmds)

        content.append(
            f"\n**Use `{ctx.prefix}help <command>` for more details about a specific command.**"
        )

        return [(f"Category: {cog.qualified_name}", "".join(content), self.color.value)]

    def get_command_help_page(self, ctx: commands.Context, cmd) -> List[tuple]:
        content = []

        content.append(f"## `{ctx.prefix}{cmd.qualified_name}`\n\n")

        content.append(
            f"**Description**\n{cmd.description or 'No description available.'}\n\n"
        )

        if cmd.aliases:
            content.append(
                f"**Aliases**\n{', '.join(f'`{a}`' for a in cmd.aliases)}\n\n"
            )

        content.append(
            f"**Usage**\n`{ctx.prefix}{cmd.qualified_name} {cmd.signature}`\n\n"
        )

        if isinstance(cmd, commands.HybridCommand) and cmd.app_command:
            app_cmd = cmd.app_command
            if app_cmd.parameters:
                content.append("**Parameters**\n")
                for param in app_cmd.parameters:
                    required = "required" if param.required else "optional"
                    param_type = (
                        param.type.name
                        if hasattr(param.type, "name")
                        else str(param.type)
                    )
                    content.append(
                        f"- `{param.name}` ({param_type}, {required}): {param.description or 'No description'}\n"
                    )
                content.append("\n")

        if isinstance(cmd, commands.Group):
            subcmds = [c for c in cmd.commands if not c.hidden]
            if subcmds:
                content.append("**Subcommands**\n")
                for sub in subcmds:
                    content.append(
                        f"- `{sub.name}` - {sub.description or 'No description'}\n"
                    )
                content.append(
                    f"\n**Use `{ctx.prefix}help {cmd.name} <subcommand>` for details.**"
                )

        full_content = "".join(content)
        pages = [(f"Command: {cmd.name}", full_content, self.color.value)]

        if len(full_content) > 3900:
            chunks = [
                full_content[i : i + 3900] for i in range(0, len(full_content), 3900)
            ]
            pages = [
                (f"{cmd.name} (Part {i + 1})", chunk, self.color.value)
                for i, chunk in enumerate(chunks)
            ]

        return pages


async def setup(bot):
    await bot.add_cog(Help(bot))
