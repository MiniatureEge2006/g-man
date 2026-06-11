import base64
import html
import inspect
import io
import json
import re
import time
from typing import Optional

import aiohttp
import asyncpg
import discord
from discord import app_commands
from discord.ext import commands

import bot_info


class AI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conversations = {}
        self.db: Optional[asyncpg.Pool] = None
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

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
        base_prompt = (
            bot_info.data["llama_system_prompt"]
            or "You are G-Man from the Half-Life series. You are speaking with Dr. Gordon Freeman."
        )
        if self.db:
            if ctx.guild:
                server_row = await self.db.fetchrow(
                    "SELECT prompt FROM guild_prompts WHERE guild_id = $1",
                    ctx.guild.id,
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

        tags = ctx.bot.get_cog("Tags")
        if tags and hasattr(tags, "formatter"):
            try:
                text, _, _, _ = await tags.formatter.format(base_prompt, ctx)
                if text:
                    base_prompt = text
            except Exception:
                pass

        return base_prompt.strip()

    async def get_ai_tools(
        self,
        ctx: commands.Context,
        content: str,
        tools_list: list,
        add_tools_list: list,
        remove_tools_list: list,
    ) -> list:
        tags_cog = ctx.bot.get_cog("Tags")
        if (
            not tags_cog
            or not hasattr(tags_cog, "formatter")
            or not hasattr(tags_cog.formatter, "functions")
        ):
            return []

        available_functions = tags_cog.formatter.functions
        available_function_names = set(available_functions.keys())

        potential_function_mentions = set(re.findall(r"\{(\w+)(?:[^\}]*)\}", content))
        content_words = set(re.findall(r"\b\w+\b", content))
        direct_name_mentions = content_words.intersection(available_function_names)
        mentioned_function_names = potential_function_mentions.union(
            direct_name_mentions
        )

        if tools_list == ["*"]:
            target_function_names = set(available_function_names)
        elif tools_list == ["-*"]:
            target_function_names = set()
        elif tools_list:
            target_function_names = set(tools_list).intersection(
                available_function_names
            )
        else:
            target_function_names = mentioned_function_names.intersection(
                available_function_names
            )

        if add_tools_list:
            target_function_names.update(
                set(add_tools_list).intersection(available_function_names)
            )

        if remove_tools_list:
            target_function_names.difference_update(set(remove_tools_list))

        tools = []
        for name in target_function_names:
            func = available_functions.get(name)
            if func:
                docstring = inspect.getdoc(func)
                if docstring:
                    lines = docstring.strip().splitlines()
                    cleaned_lines = [line.strip() for line in lines if line.strip()]
                    cleaned_doc = "\n".join(cleaned_lines)
                else:
                    cleaned_doc = f"No documentation string found for {name}."

                tool_def = {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": cleaned_doc,
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "arguments": {
                                    "type": "string",
                                    "description": "The arguments or content to pass to the tag function. Do not include the curly braces or the function name.",
                                }
                            },
                            "required": ["arguments"],
                        },
                    },
                }
                tools.append(tool_def)

        return tools

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
            stream_mode = re.search(r"(^|\s)--stream($|\s)", prompt) is not None
            if stream_mode:
                prompt = re.sub(r"(^|\s)--stream($|\s)", " ", prompt).strip()
            use_match = re.search(r"(^|\s)--use\s+(\S+)", prompt)
            model_name = use_match.group(2) if use_match else None
            if use_match:
                prompt = re.sub(r"(^|\s)--use\s+\S+", " ", prompt).strip()
            debug_mode = re.search(r"(^|\s)--debug($|\s)", prompt) is not None
            if debug_mode:
                prompt = re.sub(r"(^|\s)--debug($|\s)", " ", prompt).strip()

            media_flag = re.search(r"(^|\s)--media($|\s)", prompt) is not None
            if media_flag:
                prompt = re.sub(r"(^|\s)--media($|\s)", " ", prompt).strip()

            media_url = None
            media_url_match = re.search(r"(^|\s)--media-url\s+(\S+)", prompt)
            if media_url_match:
                media_url = media_url_match.group(2)
                prompt = re.sub(r"(^|\s)--media-url\s+\S+", " ", prompt).strip()

            shared_mode = re.search(r"(^|\s)--shared($|\s)", prompt) is not None
            if shared_mode:
                prompt = re.sub(r"(^|\s)--shared($|\s)", " ", prompt).strip()

            tools_list = []
            tools_match = re.search(r"(^|\s)--tools\s+(\S+)", prompt)
            if tools_match:
                tools_str = tools_match.group(2)
                prompt = re.sub(r"(^|\s)--tools\s+\S+", " ", prompt).strip()
                if tools_str == "*":
                    tools_list = ["*"]
                elif tools_str == "-*":
                    tools_list = ["-*"]
                else:
                    tools_list = [t.strip() for t in tools_str.split(",")]

            add_tools_list = []
            add_tools_match = re.search(r"(^|\s)--add-tools\s+(\S+)", prompt)
            if add_tools_match:
                add_tools_str = add_tools_match.group(2)
                prompt = re.sub(r"(^|\s)--add-tools\s+\S+", " ", prompt).strip()
                add_tools_list = [t.strip() for t in add_tools_str.split(",")]

            remove_tools_list = []
            remove_tools_match = re.search(r"(^|\s)--remove-tools\s+(\S+)", prompt)
            if remove_tools_match:
                remove_tools_str = remove_tools_match.group(2)
                prompt = re.sub(r"(^|\s)--remove-tools\s+\S+", " ", prompt).strip()
                remove_tools_list = [t.strip() for t in remove_tools_str.split(",")]

            ref_message_content = None
            if ctx.message.reference and ctx.message.reference.message_id:
                try:
                    ref_msg = await ctx.channel.fetch_message(
                        ctx.message.reference.message_id
                    )
                    ref_author = (
                        ref_msg.author.display_name
                        if isinstance(ref_msg.author, discord.Member)
                        else ref_msg.author.name
                    )
                    ref_text = ref_msg.content or "[No text content]"

                    ref_media_parts = []
                    for attachment in ref_msg.attachments:
                        if (
                            attachment.content_type
                            and attachment.content_type.startswith(
                                ("image/", "audio/", "video/")
                            )
                        ):
                            try:
                                async with self.session.get(attachment.url) as resp:
                                    if resp.status == 200:
                                        media_data = await resp.read()
                                        b64_data = base64.b64encode(media_data).decode(
                                            "utf-8"
                                        )

                                        if attachment.content_type.startswith("image/"):
                                            ref_media_parts.append(
                                                {
                                                    "type": "image_url",
                                                    "image_url": {
                                                        "url": f"data:{attachment.content_type};base64,{b64_data}"
                                                    },
                                                }
                                            )
                                        elif attachment.content_type.startswith(
                                            "audio/"
                                        ):
                                            raw_format = (
                                                attachment.content_type.replace(
                                                    "audio/", ""
                                                ).lower()
                                            )
                                            if (
                                                "mpeg" in raw_format
                                                or "mp3" in raw_format
                                            ):
                                                audio_format = "mp3"
                                            elif "wav" in raw_format:
                                                audio_format = "wav"
                                            elif "flac" in raw_format:
                                                audio_format = "flac"
                                            elif (
                                                "ogg" in raw_format
                                                or "opus" in raw_format
                                            ):
                                                audio_format = raw_format
                                            else:
                                                audio_format = "mp3"
                                            ref_media_parts.append(
                                                {
                                                    "type": "input_audio",
                                                    "input_audio": {
                                                        "data": b64_data,
                                                        "format": audio_format,
                                                    },
                                                }
                                            )
                                        elif attachment.content_type.startswith(
                                            "video/"
                                        ):
                                            ref_media_parts.append(
                                                {
                                                    "type": "input_video",
                                                    "input_video": {"data": b64_data},
                                                }
                                            )
                            except Exception:
                                pass

                    if ref_media_parts:
                        ref_message_content = [
                            {
                                "type": "text",
                                "text": f"Replying to {ref_author}: {ref_text}",
                            }
                        ] + ref_media_parts
                    else:
                        ref_message_content = f"Replying to {ref_author}: {ref_text}"
                except Exception:
                    pass

            author_name = (
                ctx.author.display_name
                if hasattr(ctx.author, "display_name")
                else ctx.author.name
            )
            if shared_mode:
                prompt = f"[{author_name}]: {prompt}"
            else:
                prompt = prompt

            media_parts = []
            if media_flag and ctx.message.attachments:
                for attachment in ctx.message.attachments:
                    if attachment.content_type and attachment.content_type.startswith(
                        ("image/", "audio/", "video/")
                    ):
                        try:
                            async with self.session.get(attachment.url) as resp:
                                if resp.status == 200:
                                    media_data = await resp.read()
                                    b64_data = base64.b64encode(media_data).decode(
                                        "utf-8"
                                    )
                                    if attachment.content_type.startswith("image/"):
                                        media_parts.append(
                                            {
                                                "type": "image_url",
                                                "image_url": {
                                                    "url": f"data:{attachment.content_type};base64,{b64_data}"
                                                },
                                            }
                                        )
                                    elif attachment.content_type.startswith("audio/"):
                                        raw_format = attachment.content_type.replace(
                                            "audio/", ""
                                        ).lower()
                                        if "mpeg" in raw_format or "mp3" in raw_format:
                                            audio_format = "mp3"
                                        elif "wav" in raw_format:
                                            audio_format = "wav"
                                        elif "flac" in raw_format:
                                            audio_format = "flac"
                                        elif (
                                            "ogg" in raw_format or "opus" in raw_format
                                        ):
                                            audio_format = raw_format
                                        media_parts.append(
                                            {
                                                "type": "input_audio",
                                                "input_audio": {
                                                    "data": f"{b64_data}",
                                                    "format": audio_format,
                                                },
                                            }
                                        )
                                    elif attachment.content_type.startswith("video/"):
                                        media_parts.append(
                                            {
                                                "type": "input_video",
                                                "input_video": {"data": f"{b64_data}"},
                                            }
                                        )
                                    break
                        except Exception:
                            pass

            if media_url:
                try:
                    async with self.session.get(media_url) as resp:
                        if (
                            resp.status == 200
                            and resp.content_type
                            and resp.content_type.startswith(
                                ("image/", "audio/", "video/")
                            )
                        ):
                            media_data = await resp.read()
                            b64_data = base64.b64encode(media_data).decode("utf-8")
                            if resp.content_type.startswith("image/"):
                                media_parts.append(
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:{resp.content_type};base64,{b64_data}"
                                        },
                                    }
                                )
                            elif resp.content_type.startswith("audio/"):
                                raw_format = resp.content_type.replace(
                                    "audio/", ""
                                ).lower()
                                if "mpeg" in raw_format or "mp3" in raw_format:
                                    audio_format = "mp3"
                                elif "wav" in raw_format:
                                    audio_format = "wav"
                                elif "flac" in raw_format:
                                    audio_format = "flac"
                                elif "ogg" in raw_format or "opus" in raw_format:
                                    audio_format = raw_format
                                media_parts.append(
                                    {
                                        "type": "input_audio",
                                        "input_audio": {
                                            "data": f"{b64_data}",
                                            "format": audio_format,
                                        },
                                    }
                                )
                            elif resp.content_type.startswith("video/"):
                                media_parts.append(
                                    {
                                        "type": "input_video",
                                        "input_video": {"data": f"{b64_data}"},
                                    }
                                )
                except Exception:
                    pass

            if media_parts:
                user_content = [{"type": "text", "text": prompt}] + media_parts
            else:
                user_content = prompt

            if shared_mode:
                conversation_key = (
                    (ctx.guild.id, ctx.channel.id) if ctx.guild else (ctx.channel.id,)
                )
            else:
                conversation_key = self.get_conversation(ctx)
            user_history = await self.get_conversation_history(conversation_key)
            system_prompt = await self.create_system_prompt(ctx, prompt)

            if web_mode:
                system_prompt += (
                    "\n\n[MANDATORY INSTRUCTION]: You are currently operating in web search mode. "
                    "You MUST use the 'web_search' and 'web_fetch' tools to find information before formulating your response. "
                    "Do not rely on your internal knowledge. Always perform a web search first for any user query."
                )

            if not user_history or user_history[0].get("role") != "system":
                user_history.insert(0, {"role": "system", "content": system_prompt})
            else:
                user_history[0]["content"] = system_prompt

            conversation_turns = [
                msg
                for msg in user_history[1:]
                if msg.get("role") in ("user", "assistant")
            ]

            messages = [{"role": "system", "content": system_prompt}]
            messages.extend(conversation_turns)
            if ref_message_content is not None:
                messages.append({"role": "user", "content": ref_message_content})
            messages.append({"role": "user", "content": user_content})

            tools = await self.get_ai_tools(
                ctx, prompt, tools_list, add_tools_list, remove_tools_list
            )

            if stream_mode and not web_mode and not tools:
                final_content = await self.stream_ai_response(
                    ctx, messages, think_mode, show_thinking, model_name, start_time
                )
                if final_content is None:
                    return

                user_history.append({"role": "user", "content": user_content})
                user_history.append({"role": "assistant", "content": final_content})
                await self.save_conversation_history(conversation_key, user_history)
                return

            response_data = await self.get_ai_response(
                ctx, messages, think_mode, web_mode, model_name, tools
            )
            final_content = response_data["choices"][0]["message"]["content"]
            display_content = final_content
            tool_embeds = response_data.get("_tool_embeds", [])
            tool_view = response_data.get("_tool_view", None)
            tool_files = response_data.get("_tool_files", [])

            if debug_mode:
                usage = response_data.get("usage", {})
                timings = response_data.get("timings", {})
                tool_debug_lines = []
                for msg in messages:
                    if msg.get("role") == "assistant" and "tool_calls" in msg:
                        for tc in msg["tool_calls"]:
                            tool_name = tc["function"]["name"]
                            tool_args = tc["function"].get("arguments", "{}")
                            tool_debug_lines.append(
                                f"Called Tool: `{tool_name}`\n"
                                f"Arguments: ```json\n{tool_args}\n```"
                            )
                    elif msg.get("role") == "tool":
                        tool_id = msg.get("tool_call_id", "unknown")
                        tool_content = msg.get("content", "")

                        if len(tool_content) > 600:
                            tool_content = tool_content[:600] + "\n... *[truncated]*"
                        tool_debug_lines.append(
                            f"Tool Result (ID: `{tool_id}`):\n```\n{tool_content}\n```"
                        )

                tool_stats = (
                    "\n\n".join(tool_debug_lines)
                    if tool_debug_lines
                    else "No tools were called."
                )
                stats_text = (
                    "**Debug**\n"
                    f"Model: {response_data.get('model', 'unknown')}\n"
                    f"Prompt Tokens: {usage.get('prompt_tokens', 'N/A')}\n"
                    f"Completion Tokens: {usage.get('completion_tokens', 'N/A')}\n"
                    f"Total Tokens: {usage.get('total_tokens', 'N/A')}\n"
                    f"Prompt ms: {timings.get('prompt_ms', 'N/A')}\n"
                    f"Predicted ms: {timings.get('predicted_ms', 'N/A')}\n"
                    f"Predicted per second: {timings.get('predicted_per_second', 'N/A')}\n"
                    f"Tool Execution:\n{tool_stats}"
                )
                display_content = f"{stats_text}\n\n{display_content}"

            if show_thinking:
                reasoning = response_data["choices"][0]["message"].get(
                    "reasoning_content"
                )
                if reasoning:
                    display_content = (
                        "**Thinking...**\n"
                        f"{reasoning}\n"
                        "**...done thinking.**\n"
                        f"{final_content}"
                    )

            if (
                not final_content
                and not tool_embeds
                and not tool_view
                and not tool_files
            ):
                await ctx.reply("AI returned no content.")
                return

            tags = ctx.bot.get_cog("Tags")

            final_text = display_content
            final_embeds = list(tool_embeds)
            final_view = tool_view
            final_files = list(tool_files)

            if tags and hasattr(tags, "formatter"):
                try:
                    text, embeds, view, files = await tags.formatter.format(
                        display_content, ctx
                    )

                    if text:
                        final_text = text

                    if embeds:
                        final_embeds.extend(embeds)

                    if files:
                        final_files.extend(files)

                    if view and view.children:
                        if final_view is None:
                            final_view = view
                        else:
                            for item in view.children:
                                final_view.add_item(item)

                    if len(final_text) > 2000:
                        embed = discord.Embed(
                            title="G-AI Response",
                            description=final_text[:4096],
                            color=discord.Color.blurple(),
                        )
                        embed.set_author(
                            name=f"{ctx.author.name}#{ctx.author.discriminator}",
                            icon_url=ctx.author.display_avatar.url,
                            url=f"https://discord.com/users/{ctx.author.id}",
                        )
                        embed.set_footer(
                            text=f"AI response took {time.time() - start_time:.2f} seconds"
                        )
                        await ctx.reply(
                            embed=embed,
                            view=final_view
                            if final_view and final_view.children
                            else None,
                            files=final_files[:10],
                        )
                    else:
                        await ctx.reply(
                            content=final_text if final_text else None,
                            embeds=final_embeds[:10],
                            view=final_view
                            if final_view and final_view.children
                            else None,
                            files=final_files[:10],
                        )

                    user_history.append({"role": "user", "content": user_content})
                    user_history.append({"role": "assistant", "content": final_content})
                    await self.save_conversation_history(conversation_key, user_history)
                    return

                except Exception:
                    pass

            if len(final_text) > 2000:
                embed = discord.Embed(
                    title="G-AI Response",
                    description=final_text[:4096],
                    color=discord.Color.blurple(),
                )
                embed.set_author(
                    name=f"{ctx.author.name}#{ctx.author.discriminator}",
                    icon_url=ctx.author.display_avatar.url,
                    url=f"https://discord.com/users/{ctx.author.id}",
                )
                embed.set_footer(
                    text=f"AI response took {time.time() - start_time:.2f} seconds"
                )
                await ctx.reply(
                    embed=embed,
                    view=final_view if final_view and final_view.children else None,
                    files=final_files[:10],
                )
            else:
                await ctx.reply(
                    final_text if final_text else None,
                    view=final_view if final_view and final_view.children else None,
                    files=final_files[:10],
                )

            user_history.append({"role": "user", "content": user_content})
            user_history.append({"role": "assistant", "content": final_content})
            await self.save_conversation_history(conversation_key, user_history)

        except Exception as e:
            raise commands.CommandError(str(e))

    async def stream_ai_response(
        self,
        ctx: commands.Context,
        messages: list,
        think_mode: bool = False,
        show_thinking: bool = False,
        model_name: Optional[str] = None,
        start_time: float = None,
    ) -> Optional[str]:
        EDIT_INTERVAL = 2
        PLACEHOLDER = "*Generating...*"

        base_url = bot_info.data.get("llama_base_url", "http://localhost:8080")
        api_key = bot_info.data.get("llama_api_key")
        headers = {
            "Content-Type": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": model_name or bot_info.data.get("llama_model", "default"),
            "messages": messages,
            "stream": True,
        }
        payload["chat_template_kwargs"] = (
            {"enable_thinking": True} if think_mode else {"enable_thinking": False}
        )

        try:
            sent_message = await ctx.reply(PLACEHOLDER)
            accumulated = ""
            accumulated_thinking = ""
            thinking_done = False
            last_edit = time.time()

            async with self.session.post(
                f"{base_url}/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=600),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise commands.CommandError(
                        f"llama-server error (status {resp.status}): {text}"
                    )

                async for line in resp.content:
                    line = line.decode("utf-8").strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break

                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    delta = chunk["choices"][0].get("delta", {})
                    raw_thinking = delta.get("reasoning_content")
                    if raw_thinking and isinstance(raw_thinking, str):
                        accumulated_thinking += raw_thinking

                    content = delta.get("content") or ""
                    if content and accumulated_thinking:
                        thinking_done = True
                    accumulated += content

                    now = time.time()
                    if now - last_edit >= EDIT_INTERVAL:
                        if show_thinking and accumulated_thinking:
                            if thinking_done:
                                display = f"**Thinking...**\n{accumulated_thinking}\n**...done thinking.**\n\n{accumulated}"
                            else:
                                display = f"**Thinking...**\n{accumulated_thinking}"
                        else:
                            display = accumulated
                        if display.strip():
                            try:
                                await sent_message.edit(content=display[:2000])
                            except discord.HTTPException:
                                pass
                            last_edit = now

            if not accumulated:
                await sent_message.edit(content="AI returned no content.")
                return None

            tags = ctx.bot.get_cog("Tags")
            if tags and hasattr(tags, "formatter"):
                try:
                    text, embeds, view, files = await tags.formatter.format(
                        accumulated, ctx
                    )

                    if embeds or (view and view.children) or files:
                        await sent_message.delete()

                        message_content = text[:2000] if text else None
                        await ctx.reply(
                            content=message_content,
                            embeds=embeds[:10],
                            view=view if view and view.children else None,
                            files=files[:10],
                        )
                        return accumulated
                    elif text:
                        accumulated = text
                except Exception:
                    pass

            if show_thinking and accumulated_thinking:
                display_content = f"**Thinking...**\n{accumulated_thinking}\n**...done thinking.**\n\n{accumulated}"
            else:
                display_content = accumulated

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
                if start_time:
                    embed.set_footer(
                        text=f"AI response took {time.time() - start_time:.2f} seconds"
                    )

                await sent_message.delete()
                await ctx.reply(embed=embed)
            else:
                await sent_message.edit(content=display_content)

            return accumulated
        except aiohttp.ClientConnectorError:
            raise commands.CommandError(
                "Cannot connect to llama-server, likely the server is off, sorry."
            )
        except TimeoutError:
            raise commands.CommandError("AI stream timed out")
        except Exception as e:
            raise commands.CommandError(f"AI stream failed: {str(e)}")

    async def get_ai_response(
        self,
        ctx: commands.Context,
        messages: list,
        think_mode: bool = False,
        web_mode: bool = False,
        model_name: Optional[str] = None,
        tools: list = None,
    ) -> dict:
        base_url = bot_info.data.get("llama_base_url", "http://localhost:8080")
        api_key = bot_info.data.get("llama_api_key")
        headers = {
            "Content-Type": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": model_name or bot_info.data.get("llama_model", "default"),
            "messages": messages,
        }
        payload["chat_template_kwargs"] = (
            {"enable_thinking": True} if think_mode else {"enable_thinking": False}
        )

        if tools:
            payload["tools"] = tools

        if web_mode:
            web_tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "description": "Search the web for information",
                        "parameters": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "web_fetch",
                        "description": "Fetch a webpage",
                        "parameters": {
                            "type": "object",
                            "properties": {"url": {"type": "string"}},
                            "required": ["url"],
                        },
                    },
                },
            ]
            if "tools" in payload:
                payload["tools"].extend(web_tools)
            else:
                payload["tools"] = web_tools

        all_tool_embeds = []
        all_tool_view = None
        all_tool_files = []

        try:
            while True:
                async with self.session.post(
                    f"{base_url}/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=600),
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        raise RuntimeError(
                            f"llama-server error (status {resp.status}): {text}"
                        )
                    response_data = await resp.json()

                msg = response_data["choices"][0]["message"]

                if msg.get("tool_calls"):
                    messages.append(msg)
                    for tool_call in msg["tool_calls"]:
                        func = tool_call["function"]
                        tool_name = func["name"]
                        try:
                            args = json.loads(func["arguments"])
                        except json.JSONDecodeError:
                            args = {}

                        result = ""
                        tool_embeds = []
                        tool_view = None
                        tool_files = []

                        if tool_name == "web_search":
                            result = await self._web_search(args.get("query", ""))
                        elif tool_name == "web_fetch":
                            result = await self._web_fetch(args.get("url", ""))
                        else:
                            tags_cog = ctx.bot.get_cog("Tags")
                            if tags_cog and hasattr(tags_cog, "formatter"):
                                func_obj = tags_cog.formatter.functions.get(tool_name)
                                if func_obj:
                                    try:
                                        arg_str = args.get("arguments", "")
                                        result_obj = await func_obj(ctx, arg_str)
                                        if isinstance(result_obj, tuple):
                                            text, embeds, view, files = result_obj
                                            result = (
                                                text
                                                or "[Tag function executed successfully]"
                                            )
                                            tool_embeds.extend(embeds)
                                            tool_files.extend(files)
                                            if view:
                                                if tool_view is None:
                                                    tool_view = view
                                                else:
                                                    for item in view.children:
                                                        tool_view.add_item(item)
                                        else:
                                            result = str(result_obj)
                                    except Exception as e:
                                        result = f"[Tag function error: {str(e)}]"
                                else:
                                    result = f"[Tool {tool_name} not found]"
                            else:
                                result = "[Tags cog not found]"

                        if tool_embeds:
                            all_tool_embeds.extend(tool_embeds)
                        if tool_files:
                            all_tool_files.extend(tool_files)
                        if tool_view:
                            if all_tool_view is None:
                                all_tool_view = tool_view
                            else:
                                for item in tool_view.children:
                                    all_tool_view.add_item(item)

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call["id"],
                                "content": str(result)[:4000],
                            }
                        )
                    continue

                response_data["_tool_embeds"] = all_tool_embeds
                response_data["_tool_view"] = all_tool_view
                response_data["_tool_files"] = all_tool_files
                return response_data
        except aiohttp.ClientConnectorError:
            raise commands.CommandError(
                "Cannot connect to llama-server, likely the server is off, sorry."
            )
        except TimeoutError:
            raise commands.CommandError("AI request timed out")
        except Exception as e:
            raise commands.CommandError(f"AI request failed: {str(e)}")

    async def _web_search(self, query: str) -> str:
        if not query:
            return "No query provided"

        searx_url = bot_info.data.get("searxng_url", "http://localhost:7070")

        params = {
            "q": query,
            "format": "json",
            "language": "en-US",
        }

        try:
            async with self.session.get(
                f"{searx_url}/search",
                params=params,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    return f"SearXNG returned status {resp.status}"
                data = await resp.json()

            results = data.get("results", [])
            if not results:
                return f"No search results found for '{query}'"

            formatted = []
            for r in results[:5]:
                title = r.get("title", "")
                url = r.get("url", "")
                content = r.get("content", "")
                if title:
                    formatted.append(f"{title}\n{url}\n{content}")

            return "\n\n".join(formatted)

        except Exception as e:
            return f"Web search failed: {str(e)}"

    async def _web_fetch(self, url: str) -> str:
        if not url:
            return "No URL provided"
        try:
            async with self.session.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                text = await resp.text()
                text = re.sub(r"<[^>]+>", "", text)
                text = html.unescape(text)
                text = " ".join(text.split())
                return text[:2000]
        except Exception as e:
            return f"Web fetch failed: {str(e)}"

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
            await ctx.send("Database not initialized.")

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
    @app_commands.describe(
        shared="Export the shared channel-wide history instead of your personal history."
    )
    async def exportchat(self, ctx: commands.Context, shared: bool = False):
        await ctx.typing()

        if shared:
            key = (ctx.guild.id, ctx.channel.id) if ctx.guild else (ctx.channel.id,)
            filename = f"g-ai_shared_conversation_{ctx.guild.id if ctx.guild else 'dm'}_{ctx.channel.id}.json"
        else:
            key = self.get_conversation(ctx)
            filename = f"g-ai_conversation_{ctx.author.id}.json"

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
                await ctx.send(
                    f"No {'shared channel' if shared else 'active'} conversation history to export."
                )
                return

            buffer = io.BytesIO()
            buffer.write(json.dumps(history, indent=2).encode("utf-8"))
            buffer.seek(0)

            await ctx.send(
                f"Here is {'the shared channel' if shared else 'your'} conversation history:",
                file=discord.File(buffer, filename=filename),
            )
        except Exception as e:
            await ctx.send(f"Failed to export conversation: {e}")

    @commands.hybrid_command(
        name="importchat", description="Import conversation history into G-AI."
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(
        attachment="The JSON file to import.",
        shared="Import to the shared channel-wide history instead of your personal history.",
    )
    async def importchat(
        self,
        ctx: commands.Context,
        attachment: discord.Attachment,
        shared: bool = False,
    ):
        await ctx.typing()

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

            if shared:
                key = (ctx.guild.id, ctx.channel.id) if ctx.guild else (ctx.channel.id,)
            else:
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

            await ctx.send(
                f"Conversation history imported successfully to {'shared channel' if shared else 'your'} history."
            )

        except json.JSONDecodeError:
            await ctx.send("Invalid JSON file.")
        except Exception as e:
            await ctx.send(f"Failed to import conversation: {e}")

    @commands.hybrid_command(
        name="resetai", description="Reset the conversation history of G-AI."
    )
    @app_commands.describe(
        shared="Whether it should reset a channel-wide history instead of your own."
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def resetai(self, ctx: commands.Context, shared: bool = False):
        await ctx.typing()

        if shared:
            conversation_key = (
                (ctx.guild.id, ctx.channel.id) if ctx.guild else (ctx.channel.id,)
            )
        else:
            conversation_key = self.get_conversation(ctx)

        try:
            if self.db:
                result = await self.db.execute(
                    "DELETE FROM ai_conversations WHERE conversation_key = $1",
                    json.dumps(conversation_key),
                )
                if result != "DELETE 0":
                    await ctx.send(
                        f"{'Shared channel' if shared else 'Your'} conversation history has been reset."
                    )
                else:
                    if conversation_key in self.conversations:
                        del self.conversations[conversation_key]
                        await ctx.send(
                            f"{'Shared channel' if shared else 'Your'} local conversation history has been reset."
                        )
                    else:
                        await ctx.send(
                            f"No {'shared channel' if shared else 'active'} conversation found to reset."
                        )
            else:
                if conversation_key in self.conversations:
                    del self.conversations[conversation_key]
                    await ctx.send(
                        f"{'Shared channel' if shared else 'Your'} local conversation history has been reset."
                    )
                else:
                    await ctx.send(
                        f"No {'shared channel' if shared else 'active'} conversation found to reset."
                    )

        except Exception as e:
            await ctx.send(f"Failed to reset conversation: {e}")

    async def cog_unload(self):
        if self._session and not self._session.closed:
            await self._session.close()


async def setup(bot):
    cog = AI(bot)
    cog.db = await asyncpg.create_pool(bot_info.data["database"])
    await bot.add_cog(cog)
