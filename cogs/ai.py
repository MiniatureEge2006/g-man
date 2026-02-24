import io
import json
import re
import time
from typing import Optional

import asyncpg
import discord
import ollama
from discord import app_commands
from discord.ext import commands

import bot_info

MAX_CONVERSATION_HISTORY_LENGTH = 5


class AI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conversations = {}
        self.db: Optional[asyncpg.Pool] = None

    def get_conversation(self, ctx) -> tuple:
        return (
            (ctx.guild.id, ctx.channel.id, ctx.author.id)
            if ctx.guild
            else (ctx.author.id, ctx.channel.id)
        )

    async def get_conversation_history(self, key: tuple) -> list:
        if not self.db:
            return self.conversations.get(key, [])

        try:
            result = await self.db.fetchrow(
                "SELECT history FROM ai_conversations WHERE conversation_key = $1",
                json.dumps(key),
            )
            return json.loads(result["history"]) if result else []
        except Exception:
            return self.conversations.get(key, [])

    async def save_conversation_history(self, key: tuple, history: list):
        if not self.db:
            self.conversations[key] = history
            return

        try:
            await self.db.execute(
                """
                INSERT INTO ai_conversations (conversation_key, history, last_updated)
                VALUES ($1, $2, NOW())
                ON CONFLICT (conversation_key)
                DO UPDATE SET history = EXCLUDED.history, last_updated = NOW()
            """,
                json.dumps(key),
                json.dumps(history),
            )
        except Exception:
            self.conversations[key] = history

    async def create_system_prompt(
        self, ctx: commands.Context, content: str = ""
    ) -> str:
        base_prompt = """You are G-Man from the Half-Life series. You are speaking with Dr. Gordon Freeman."""
        if self.db:
            if ctx.guild:
                server_row = await self.db.fetchrow(
                    "SELECT prompt FROM guild_prompts WHERE guild_id = $1", ctx.guild.id
                )
                if server_row and server_row["prompt"]:
                    base_prompt = server_row["prompt"]

            channel_row = await self.db.fetchrow(
                "SELECT prompt FROM channel_prompts WHERE channel_id = $1",
                ctx.channel.id,
            )
            if channel_row and channel_row["prompt"]:
                base_prompt = channel_row["prompt"]

            user_row = await self.db.fetchrow(
                "SELECT prompt FROM system_prompts WHERE user_id = $1", ctx.author.id
            )
            if user_row and user_row["prompt"]:
                base_prompt = user_row["prompt"]

        return base_prompt.strip()

    def _get_tagscript_tool_definition(self, ctx: commands.Context) -> dict:
        tags_cog = ctx.bot.get_cog("Tags")
        available_functions = []

        if (
            tags_cog
            and hasattr(tags_cog, "formatter")
            and hasattr(tags_cog.formatter, "functions")
        ):
            available_functions = sorted(tags_cog.formatter.functions.keys())

        function_list = (
            ", ".join(available_functions[:50])
            if available_functions
            else "No functions available"
        )
        if len(available_functions) > 50:
            function_list += f"... and {len(available_functions) - 50} more"

        description = f"""Execute TagScript to get dynamic information or perform actions.
TagScript uses curly braces syntax like {{function_name:args}}.
Available functions: {function_list}
Returns the result of executing the TagScript."""

        return {
            "type": "function",
            "function": {
                "name": "execute_tagscript",
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "script": {
                            "type": "string",
                            "description": "The TagScript to execute. Use curly braces syntax like {user}, {range:1|10}, {eval:{user} is cool}. Overall syntax: {function:value|value2?|...?}",
                        }
                    },
                    "required": ["script"],
                },
            },
        }

    async def _execute_tagscript(self, ctx: commands.Context, script: str) -> str:
        tags_cog = ctx.bot.get_cog("Tags")
        if not tags_cog or not hasattr(tags_cog, "formatter"):
            return "[TagScript Error: Tags cog not available]"

        try:
            text, embeds, view, files = await tags_cog.formatter.format(script, ctx)
            result_parts = []
            if text:
                result_parts.append(text)
            if embeds:
                for embed in embeds:
                    if embed.title:
                        result_parts.append(f"[Embed: {embed.title}]")
                    if embed.description:
                        result_parts.append(embed.description[:500])
            if files:
                result_parts.append(f"[{len(files)} file(s) attached]")

            return (
                "\n".join(result_parts)
                if result_parts
                else "[TagScript executed with no output]"
            )
        except Exception as e:
            return f"[TagScript Error: {str(e)}]"

    @commands.hybrid_command(
        name="ai", description="Use G-AI to chat and execute TagScript."
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(prompt="The prompt to send to G-AI.")
    async def ai(self, ctx: commands.Context, *, prompt: str):
        await ctx.typing()
        await self.process_ai_response(ctx, prompt)

    async def process_ai_response(
        self,
        ctx: commands.Context,
        prompt: str,
        think_mode: bool = False,
        show_thinking: bool = False,
        web_mode: bool = False,
    ):
        start_time = time.time()
        try:
            think_mode = re.search(r"(^|\s)--think($|\s)", prompt) is not None
            if think_mode:
                prompt = re.sub(r"(^|\s)--think($|\s)", " ", prompt).strip()
            show_thinking = (
                re.search(r"(^|\s)--show-thinking($|\s)", prompt) is not None
            )
            if show_thinking:
                prompt = re.sub(r"(^|\s)--show-thinking($|\s)", " ", prompt).strip()
            web_mode = re.search(r"(^|\s)--web($|\s)", prompt) is not None
            if web_mode:
                prompt = re.sub(r"(^|\s)--web($|\s)", " ", prompt).strip()
            use_match = re.search(r"(^|\s)--use\s+(\S+)", prompt)
            model_name = use_match.group(2) if use_match else None
            if use_match:
                prompt = re.sub(r"(^|\s)--use\s+\S+", " ", prompt).strip()
            debug_mode = re.search(r"(^|\s)--debug($|\s)", prompt) is not None
            if debug_mode:
                prompt = re.sub(r"(^|\s)--debug($|\s)", " ", prompt).strip()
            conversation_key = self.get_conversation(ctx)
            user_history = await self.get_conversation_history(conversation_key)
            system_prompt = await self.create_system_prompt(ctx, prompt)
            messages = [{"role": "system", "content": system_prompt}]

            messages.append({"role": "user", "content": prompt})

            if user_history:
                messages[1:1] = user_history[-MAX_CONVERSATION_HISTORY_LENGTH:]

            response, tool_calls_info = await self.get_ai_response(
                ctx, messages, think_mode, web_mode, model_name
            )
            final_content = response.message.content
            display_content = final_content

            if debug_mode:
                stats_text = (
                    "**Debug**\n"
                    f"Model: {response.model}\n"
                    f"Done Reason: {response.done_reason}\n"
                    f"Total Duration: {response.total_duration}\n"
                    f"Prompt Eval Count: {response.prompt_eval_count}\n"
                    f"Prompt Eval Duration: {response.prompt_eval_duration}\n"
                    f"Eval Count: {response.eval_count}\n"
                    f"Eval Duration: {response.eval_duration}\n"
                )
                if tool_calls_info:
                    tool_display_parts = ["**Tool Calls:**"]
                    for i, tool_call in enumerate(tool_calls_info, 1):
                        if tool_call["name"] == "TagScript":
                            script = tool_call.get("script", "")
                            result = tool_call.get("result", "")
                            tool_display_parts.append(
                                f"{i}. **TagScript:** `{{ignore:{script[:100]}{'...' if len(script) > 100 else ''}}}`"
                            )
                            tool_display_parts.append(
                                f"   **Result:** {result[:500]}{'...' if len(result) > 500 else ''}"
                            )
                        else:
                            tool_display_parts.append(
                                f"{i}. **{tool_call['name']}**: {tool_call.get('result', 'No result')[:200]}"
                            )
                    tool_display = "\n".join(tool_display_parts)
                    display_content = f"{tool_display}\n\n{display_content}"
                display_content = f"{stats_text}\n\n{display_content}"

            if show_thinking and getattr(response.message, "thinking", None):
                display_content = (
                    "**Thinking...**\n"
                    f"{response.message.thinking}\n"
                    "**...done thinking.**\n"
                    f"{final_content}"
                )

            if not final_content:
                await ctx.reply("AI returned no content.")
                return

            tags = ctx.bot.get_cog("Tags")
            if tags and hasattr(tags, "formatter"):
                try:
                    text, embeds, view, files = await tags.formatter.format(
                        display_content, ctx
                    )

                    if embeds or (view and view.children) or files:
                        message_content = text[:2000] if text else None
                        await ctx.reply(
                            content=message_content,
                            embeds=embeds[:10],
                            view=view if view and view.children else None,
                            files=files[:10],
                        )
                    elif text:
                        if len(text) > 2000:
                            embed = discord.Embed(
                                title="G-AI Response",
                                description=text if len(text) < 4096 else text[:4096],
                                color=discord.Color.blurple(),
                            )
                            embed.set_author(
                                name=f"{ctx.author.name}#{ctx.author.discriminator}",
                                icon_url=ctx.author.display_avatar.url,
                                url=f"https://discord.com/users/{ctx.author.id}",
                            )
                            embed.set_footer(
                                text=f"AI Response took {time.time() - start_time:.2f} seconds",
                                icon_url="https://ollama.com/public/og.png",
                            )
                            await ctx.reply(embed=embed)
                        else:
                            await ctx.reply(text)
                    new_history = (
                        user_history[-MAX_CONVERSATION_HISTORY_LENGTH * 2 :]
                        if user_history
                        else []
                    )
                    new_history.extend(
                        [
                            {"role": "user", "content": prompt},
                            {"role": "assistant", "content": final_content},
                        ]
                    )
                    await self.save_conversation_history(conversation_key, new_history)
                    return
                except Exception:
                    pass

            if len(display_content) > 2000:
                embed = discord.Embed(
                    title="G-AI Response",
                    description=display_content[:4096],
                    color=discord.Color.blurple(),
                )
                embed.set_author(
                    name=f"{ctx.author.name}#{ctx.author.discriminator}",
                    icon_url=ctx.author.display_avatar.url,
                    url=f"https://discord.com/users/{ctx.author.id}",
                )
                embed.set_footer(
                    text=f"AI Response took {time.time() - start_time:.2f} seconds",
                    icon_url="https://ollama.com/public/og.png",
                )
                await ctx.reply(embed=embed)
            else:
                await ctx.reply(display_content)

            new_history = (
                user_history[-MAX_CONVERSATION_HISTORY_LENGTH * 2 :]
                if user_history
                else []
            )
            new_history.extend(
                [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": final_content},
                ]
            )
            await self.save_conversation_history(conversation_key, new_history)

        except Exception as e:
            raise commands.CommandError(str(e))

    async def get_ai_response(
        self,
        ctx: commands.Context,
        messages: list,
        think_mode: bool = False,
        web_mode: bool = False,
        model_name: Optional[str] = None,
    ) -> tuple:
        tool_calls_info = []
        try:
            while True:
                ollama_client = ollama.AsyncClient(
                    headers={
                        "Authorization": "Bearer " + bot_info.data["ollama_api_key"]
                        if web_mode
                        else None
                    }
                )

                tools = []

                tagscript_tool = self._get_tagscript_tool_definition(ctx)
                tools.append(tagscript_tool)

                if web_mode:
                    tools.extend([ollama_client.web_search, ollama_client.web_fetch])

                response = await ollama_client.chat(
                    model=model_name or bot_info.data["ollama_model"],
                    messages=messages,
                    think=think_mode,
                    tools=tools if tools else None,
                )
                msg = response.message

                if getattr(msg, "tool_calls", None):
                    has_more_calls = False
                    for tool_call in msg.tool_calls:
                        tool_name = tool_call.function.name
                        args = tool_call.function.arguments

                        if tool_name == "execute_tagscript":
                            script = args.get("script", "")
                            result = await self._execute_tagscript(ctx, script)
                            tool_calls_info.append(
                                {
                                    "name": "TagScript",
                                    "script": script,
                                    "result": result,
                                }
                            )
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_name": tool_name,
                                    "content": str(result)[:2000],
                                }
                            )
                            has_more_calls = True
                        elif web_mode and tool_name in ("web_search", "web_fetch"):
                            function_to_call = getattr(ollama_client, tool_name, None)
                            if function_to_call:
                                result = await function_to_call(**args)
                                tool_calls_info.append(
                                    {
                                        "name": tool_name,
                                        "args": args,
                                        "result": str(result)[:500],
                                    }
                                )
                                messages.append(
                                    {
                                        "role": "tool",
                                        "tool_name": tool_name,
                                        "content": str(result)[:2000],
                                    }
                                )
                                has_more_calls = True
                            else:
                                messages.append(
                                    {
                                        "role": "tool",
                                        "content": f"Tool {tool_name} not found",
                                        "tool_name": tool_name,
                                    }
                                )
                        else:
                            messages.append(
                                {
                                    "role": "tool",
                                    "content": f"Unknown tool: {tool_name}",
                                    "tool_name": tool_name,
                                }
                            )

                    if has_more_calls:
                        continue
                    return response, tool_calls_info
                return response, tool_calls_info
        except ollama.ResponseError as e:
            if e.status_code == 404:
                models = []
                model_list = await ollama_client.list()
                for model in model_list.models:
                    available_model_name = model.model
                    models.append(available_model_name)
                raise RuntimeError(
                    f"Model `{model_name}` not found. Available models:\n `{'\n'.join(models)}`"
                )
            else:
                raise RuntimeError(
                    f"Ollama API error (status {e.status_code}): {str(e)}"
                )
        except Exception as e:
            raise RuntimeError(f"AI request failed: {str(e)}")

    @commands.hybrid_command(
        name="setsystemprompt",
        description="Set a custom system prompt for yourself in G-AI.",
        aliases=["setuserprompt"],
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(prompt="The custom system prompt.")
    async def setsystemprompt(self, ctx: commands.Context, *, prompt: str):
        await ctx.typing()
        if self.db:
            await self.db.execute(
                """
                INSERT INTO system_prompts (user_id, prompt) VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE SET prompt = EXCLUDED.prompt
                """,
                ctx.author.id,
                prompt,
            )
            await ctx.send(
                f"Custom system prompt for yourself has been set to:\n```{prompt[:500]}```"
            )
        else:
            await ctx.send("Database not initialized.")

    @commands.hybrid_command(
        name="resetsystemprompt",
        description="Reset your custom system prompt in G-AI back to default.",
        aliases=["resetuserprompt"],
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def resetsystemprompt(self, ctx: commands.Context):
        await ctx.typing()
        if self.db:
            await self.db.execute(
                "DELETE FROM system_prompts WHERE user_id = $1", ctx.author.id
            )
            await ctx.send("Your system prompt has been reset.")
        else:
            await ctx.send("Database not initialized")

    @commands.hybrid_command(
        name="setchannelprompt",
        description="Set a custom system prompt for G-AI in this channel.",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(prompt="The custom system prompt for this channel.")
    async def setchannelprompt(self, ctx: commands.Context, *, prompt: str):
        await ctx.typing()
        if self.db:
            if ctx.guild:
                if ctx.author.guild_permissions.manage_channels:
                    await self.db.execute(
                        """
                        INSERT INTO channel_prompts (channel_id, prompt) VALUES ($1, $2)
                        ON CONFLICT (channel_id) DO UPDATE SET prompt = EXCLUDED.prompt
                        """,
                        ctx.channel.id,
                        prompt,
                    )
                    await ctx.send(
                        f"Custom channel system prompt has been set to:\n```{prompt[:500]}```"
                    )
                else:
                    await ctx.send(
                        "You don't have permission to change this channel's system prompt."
                    )
                    return
            else:
                await self.db.execute(
                    """
                    INSERT INTO channel_prompts (channel_id, prompt) VALUES ($1, $2)
                    ON CONFLICT (channel_id) DO UPDATE SET prompt = EXCLUDED.prompt
                    """,
                    ctx.channel.id,
                    prompt,
                )
                await ctx.send(
                    f"Custom channel system prompt has been set to:\n```{prompt[:500]}```"
                )
        else:
            await ctx.send("Database not initialized.")

    @commands.hybrid_command(
        name="resetchannelprompt",
        description="Reset the current channel's custom system prompt in G-AI back to default.",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def resetchannelprompt(self, ctx: commands.Context):
        await ctx.typing()
        if self.db:
            if ctx.guild:
                if ctx.author.guild_permissions.manage_channels:
                    await self.db.execute(
                        "DELETE FROM channel_prompts WHERE channel_id = $1",
                        ctx.channel.id,
                    )
                    await ctx.send("Custom channel system prompt has been reset.")
                else:
                    await ctx.send(
                        "You don't have permission to reset this channel's custom system prompt."
                    )
                    return
            else:
                await self.db.execute(
                    "DELETE FROM channel_prompts WHERE channel_id = $1", ctx.channel.id
                )
                await ctx.send("Custom channel system prompt has been reset.")
        else:
            await ctx.send("Database not initialized.")

    @commands.hybrid_command(
        name="setserverprompt",
        description="Set a custom system prompt for G-AI in this server.",
        aliases=["setguildprompt"],
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(prompt="The custom system prompt for this server.")
    async def setserverprompt(self, ctx: commands.Context, *, prompt: str):
        await ctx.typing()
        if self.db:
            if ctx.guild:
                if ctx.author.guild_permissions.manage_guild:
                    await self.db.execute(
                        """
                        INSERT INTO guild_prompts (guild_id, prompt) VALUES ($1, $2)
                        ON CONFLICT (guild_id) DO UPDATE SET prompt = EXCLUDED.prompt
                        """,
                        ctx.guild.id,
                        prompt,
                    )
                    await ctx.send(
                        f"Custom server system prompt has been set to:\n```{prompt[:500]}```"
                    )
                else:
                    await ctx.send(
                        "You don't have permission to change this server's system prompt."
                    )
                    return
            else:
                await ctx.send("You can only set the server system prompt in a server.")
                return
        else:
            await ctx.send("Database not initialized.")

    @commands.hybrid_command(
        name="resetserverprompt",
        description="Reset the current server's custom system prompt in G-AI back to default.",
        aliases=["resetguildprompt"],
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def resetserverprompt(self, ctx: commands.Context):
        await ctx.typing()
        if self.db:
            if ctx.guild:
                if ctx.author.guild_permissions.manage_guild:
                    await self.db.execute(
                        "DELETE FROM guild_prompts WHERE guild_id = $1", ctx.guild.id
                    )
                    await ctx.send("Custom server system prompt has been reset.")
                else:
                    await ctx.send(
                        "You don't have permission to reset this server's custom system prompt."
                    )
                    return
            else:
                await ctx.send(
                    "You can only reset the server system prompt in a server."
                )
                return
        else:
            await ctx.send("Database not initialized.")

    @commands.hybrid_command(
        name="exportchat", description="Export your conversation history with G-AI."
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def exportchat(self, ctx: commands.Context):
        await ctx.typing()
        key = self.get_conversation(ctx)

        try:
            if self.db:
                result = await self.db.fetchrow(
                    "SELECT history FROM ai_conversations WHERE conversation_key = $1",
                    json.dumps(key),
                )
                history = json.loads(result["history"]) if result else []
            else:
                history = self.conversations.get(key, [])

            if not history:
                await ctx.send("No conversation history to export.")
                return

            buffer = io.BytesIO()
            buffer.write(json.dumps(history, indent=2).encode("utf-8"))
            buffer.seek(0)

            await ctx.send(
                "Here is your conversation history:",
                file=discord.File(
                    buffer, filename=f"g-ai_conversation_{ctx.author.id}.json"
                ),
            )
        except Exception as e:
            await ctx.send(f"Failed to export conversation: {e}")

    @commands.hybrid_command(
        name="importchat", description="Import your conversation history with G-AI."
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(attachment="The JSON file to import.")
    async def importchat(self, ctx: commands.Context, attachment: discord.Attachment):
        await ctx.typing()

        if not attachment:
            await ctx.send("Please attach a JSON file.")
            return

        if not attachment.filename.lower().endswith(".json"):
            await ctx.send("File must be a JSON file (.json).")
            return

        try:
            content = await attachment.read()
            history = json.loads(content.decode("utf-8"))

            if not isinstance(history, list) or not all(
                isinstance(m, dict) and "role" in m and "content" in m for m in history
            ):
                await ctx.send(
                    "Invalid conversation format. Each message must have 'role' and 'content'."
                )
                return

            key = self.get_conversation(ctx)

            if self.db:
                await self.db.execute(
                    """
                    INSERT INTO ai_conversations (conversation_key, history, last_updated)
                    VALUES ($1, $2, NOW())
                    ON CONFLICT (conversation_key)
                    DO UPDATE SET history = EXCLUDED.history, last_updated = NOW()
                """,
                    json.dumps(key),
                    json.dumps(history),
                )
            else:
                self.conversations[key] = history

            await ctx.send("Conversation history imported successfully.")

        except json.JSONDecodeError:
            await ctx.send("Invalid JSON file.")
        except Exception as e:
            await ctx.send(f"Failed to import conversation: {e}")

    @commands.hybrid_command(
        name="resetai", description="Reset the conversation history of G-AI."
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def resetai(self, ctx: commands.Context):
        await ctx.typing()
        conversation_key = self.get_conversation(ctx)

        try:
            if self.db:
                result = await self.db.execute(
                    "DELETE FROM ai_conversations WHERE conversation_key = $1",
                    json.dumps(conversation_key),
                )

                if result != "DELETE 0":
                    await ctx.send("Conversation history has been reset.")
                else:
                    if conversation_key in self.conversations:
                        del self.conversations[conversation_key]
                        await ctx.send("Local conversation history has been reset.")
                    else:
                        await ctx.send("No active conversation found to reset.")
            else:
                if conversation_key in self.conversations:
                    del self.conversations[conversation_key]
                    await ctx.send("Local conversation history has been reset.")
                else:
                    await ctx.send("No active conversation found to reset.")

        except Exception as e:
            await ctx.send(f"Failed to reset conversation: {e}")


async def setup(bot):
    cog = AI(bot)
    cog.db = await asyncpg.create_pool(bot_info.data["database"])
    await bot.add_cog(cog)
