import discord
from discord.ext import commands
from discord import app_commands
import ollama
import asyncio
import time
import asyncpg
import bot_info
import json
import io
import re
from typing import Optional
import inspect

MAX_CONVERSATION_HISTORY_LENGTH = 5

class AI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conversations = {}
        self.db: Optional[asyncpg.Pool] = None
    
    def _get_tagscript_function_docs(self, ctx: commands.Context, function_names: list[str] = None) -> dict[str, str]:
        tags_cog = ctx.bot.get_cog("Tags")
        if not tags_cog or not hasattr(tags_cog, 'formatter') or not hasattr(tags_cog.formatter, 'functions'):
            return {}

        formatter = tags_cog.formatter
        available_functions = formatter.functions


        target_function_names = function_names if function_names is not None else available_functions.keys()
        target_function_names = [name for name in target_function_names if name in available_functions]

        docs = {}
        for name in target_function_names:
            func = available_functions.get(name)
            if func:
                try:
                    docstring = inspect.getdoc(func)
                    if docstring:
                        lines = docstring.strip().splitlines()
                        cleaned_lines = []
                        for line in lines:
                            stripped_line = line.strip()
                            if stripped_line:
                                cleaned_lines.append(stripped_line)
                            if len(cleaned_lines) >= 10:
                                break
                        cleaned_doc = "\n".join(cleaned_lines)
                        docs[name] = cleaned_doc
                    else:
                        docs[name] = f"{name}: No documentation string found."
                except Exception as e:
                    docs[name] = f"{name}: Error retrieving documentation ({e})."
            else:
                docs[name] = f"{name}: Function reference not found."

        return docs
    
    def get_conversation(self, ctx) -> tuple:
        return (ctx.guild.id, ctx.channel.id, ctx.author.id) if ctx.guild else (ctx.author.id, ctx.channel.id)
    
    async def get_conversation_history(self, key: tuple) -> list:
        if not self.db:
            return self.conversations.get(key, [])
            
        try:
            result = await self.db.fetchrow(
                "SELECT history FROM ai_conversations WHERE conversation_key = $1",
                json.dumps(key)
            )
            return json.loads(result['history']) if result else []
        except Exception:
            return self.conversations.get(key, [])
    
    async def save_conversation_history(self, key: tuple, history: list):
        if not self.db:
            self.conversations[key] = history
            return
            
        try:
            await self.db.execute("""
                INSERT INTO ai_conversations (conversation_key, history, last_updated)
                VALUES ($1, $2, NOW())
                ON CONFLICT (conversation_key)
                DO UPDATE SET history = EXCLUDED.history, last_updated = NOW()
            """, json.dumps(key), json.dumps(history))
        except Exception:
            self.conversations[key] = history

    async def create_system_prompt(self, ctx: commands.Context, content: str = "") -> str:
        custom_prompt = None
        if self.db:
            row = await self.db.fetchrow("SELECT prompt FROM system_prompts WHERE user_id = $1", ctx.author.id)
            if row and row['prompt']:
                custom_prompt = row['prompt']
        if custom_prompt:
            base_prompt = custom_prompt
        else:
            base_prompt = """You are G-Man from the Half-Life series. You are speaking with Dr. Gordon Freeman."""

        formatted_docs = ""
        if content:
            tags_cog = ctx.bot.get_cog("Tags")
            available_function_names = set()
            if tags_cog and hasattr(tags_cog, 'formatter') and hasattr(tags_cog.formatter, 'functions'):
                available_function_names = set(tags_cog.formatter.functions.keys())


            potential_function_mentions = set(re.findall(r'\{(\w+)(?:[^\}]*)\}', content))
            content_words = set(re.findall(r'\b\w+\b', content))
            direct_name_mentions = content_words.intersection(available_function_names)


            mentioned_function_names = potential_function_mentions.union(direct_name_mentions)
            relevant_function_names = list(mentioned_function_names.intersection(available_function_names))

            if relevant_function_names:
                function_docs_dict = self._get_tagscript_function_docs(ctx, relevant_function_names)
                if function_docs_dict:
                    formatted_docs_lines = ["\n\n--- Relevant Tag Functions (Contextual Reference) ---"]
                    for func_name in sorted(function_docs_dict.keys()):
                        doc_str = function_docs_dict.get(func_name, f"{func_name}: No documentation retrieved.")
                        formatted_docs_lines.append(f"\n{func_name}:\n{doc_str}\n---")
                    formatted_docs = "\n".join(formatted_docs_lines)

        final_prompt = f"{base_prompt.strip()}{formatted_docs}"

        return final_prompt.strip()
    


    @commands.hybrid_command(name="ai", description="Use G-AI to chat and execute TagScript.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(prompt="The prompt to send to G-AI.")
    async def ai(self, ctx: commands.Context, *, prompt: str):
        await ctx.typing()
        await self.process_ai_response(ctx, prompt)
    
    async def process_ai_response(self, ctx: commands.Context, prompt: str, think_mode: bool = False, show_thinking: bool = False):
        start_time = time.time()
        try:
            think_mode = re.search(r'(^|\s)--think($|\s)', prompt) is not None
            if think_mode:
                prompt = re.sub(r'(^|\s)--think($|\s)', ' ', prompt).strip()
            show_thinking = re.search(r'(^|\s)--show-thinking($|\s)', prompt) is not None
            if show_thinking:
                prompt = re.sub(r'(^|\s)--show-thinking($|\s)', ' ', prompt).strip()
            conversation_key = self.get_conversation(ctx)
            

            user_history = await self.get_conversation_history(conversation_key)
            
            system_prompt = await self.create_system_prompt(ctx, prompt)
            messages = [{"role": "system", "content": system_prompt}]
            
            messages.append({"role": "user", "content": prompt})
            
            if user_history:
                messages[1:1] = user_history[-MAX_CONVERSATION_HISTORY_LENGTH:]
            
            response = await self.get_ai_response(messages, think_mode, show_thinking)
            content = response.message.content
            
            if not content:
                await ctx.reply("Command returned no content.")
                return
            
            tags = ctx.bot.get_cog('Tags')
            if tags and hasattr(tags, 'formatter'):
                try:
                    text, embeds, view, files = await tags.formatter.format(content, ctx)

                    if embeds or (view and view.childen) or files:
                        message_content = text[:2000] if text else None
                        await ctx.reply(
                            content=message_content,
                            embeds=embeds[:10],
                            view=view if view and view.children else None,
                            files=files[:10]
                        )
                    elif text:
                        if len(text) > 2000:
                            embed = discord.Embed(
                                title="G-AI Response",
                                description=text if len(text) < 4096 else text[:4096],
                                color=discord.Color.blurple()
                            )
                            embed.set_author(
                                name=f"{ctx.author.name}#{ctx.author.discriminator}",
                                icon_url=ctx.author.display_avatar.url,
                                url=f"https://discord.com/users/{ctx.author.id}"
                            )
                            embed.set_footer(
                                text=f"AI Response took {time.time() - start_time:.2f} seconds",
                                icon_url="https://ollama.com/public/og.png"
                            )
                            await ctx.reply(embed=embed)
                        else:
                            await ctx.reply(text)
                    new_history = user_history[-MAX_CONVERSATION_HISTORY_LENGTH * 2:] if user_history else []
                    new_history.extend([
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": content}
                    ])
                    await self.save_conversation_history(conversation_key, new_history)
                    return
                except Exception:
                    pass
                
            if len(content) > 2000:
                embed = discord.Embed(title="G-AI Response", description=content if len(content) < 4096 else content[:4096], color=discord.Color.blurple())
                embed.set_author(name=f"{ctx.author.name}#{ctx.author.discriminator}", icon_url=ctx.author.display_avatar.url, url=f"https://discord.com/users/{ctx.author.id}")
                embed.set_footer(text=f"AI Response took {time.time() - start_time:.2f} seconds", icon_url="https://ollama.com/public/og.png")
                await ctx.reply(embed=embed)
            else:
                await ctx.reply(content)
            

            new_history = user_history[-MAX_CONVERSATION_HISTORY_LENGTH * 2:] if user_history else []
            new_history.extend([
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": content}
            ])
            await self.save_conversation_history(conversation_key, new_history)
                
        except Exception as e:
            await ctx.send(f"An error occurred: {e}")


    async def get_ai_response(self, messages: list, think_mode: bool = False, show_thinking: bool = False):
        try:
            response = await asyncio.to_thread(
                ollama.chat,
                model=bot_info.data['ollama_model'],
                messages=messages,
                think=think_mode
            )
            content = response.message.content
            if not show_thinking:
                content = content
            elif show_thinking:
                content = f"**Thinking...**\n{response.message.thinking}\n**...done thinking.**" + '\n' + content
            response.message.content = content
            return response
        except Exception as e:
            raise RuntimeError(f"AI request failed: {e}")
    

    @commands.hybrid_command(name="setsystemprompt", description="Set a custom system prompt for G-AI.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(prompt="The custom system prompt.")
    async def setsystemprompt(self, ctx: commands.Context, *, prompt: str):
        await ctx.typing()
        if self.db:
            await self.db.execute("""
                INSERT INTO system_prompts (user_id, prompt) VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE SET prompt = EXCLUDED.prompt
                """, ctx.author.id, prompt)
            await ctx.send("Custom system prompt has been successfully set.")
        else:
            await ctx.send("Database not initialized.")
    

    @commands.hybrid_command(name="resetsystemprompt", description="Reset your system prompt back to default.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def resetsystemprompt(self, ctx: commands.Context):
        await ctx.typing()
        if self.db:
            await self.db.execute("DELETE FROM system_prompts WHERE user_id = $1", ctx.author.id)
            await ctx.send("Your system prompt has successfully been reset.")
        else:
            await ctx.send("Database not initialized")
    
    @commands.hybrid_command(name="exportchat", description="Export your conversation history with G-AI.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def exportchat(self, ctx: commands.Context):
        await ctx.typing()
        key = self.get_conversation(ctx)
        
        try:
            if self.db:
                result = await self.db.fetchrow(
                    "SELECT history FROM ai_conversations WHERE conversation_key = $1",
                    json.dumps(key)
                )
                history = json.loads(result['history']) if result else []
            else:
                history = self.conversations.get(key, [])
            
            if not history:
                await ctx.send("No conversation history to export.")
                return
                

            buffer = io.BytesIO()
            buffer.write(json.dumps(history, indent=2).encode('utf-8'))
            buffer.seek(0)
            
            await ctx.send(
                "Here is your conversation history:", 
                file=discord.File(buffer, filename=f"gai_conversation_{ctx.author.id}.json")
            )
        except Exception as e:
            await ctx.send(f"Failed to export conversation: {e}")

    @commands.hybrid_command(name="importchat", description="Import your conversation history with G-AI.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(attachment="The JSON file to import.")
    async def importchat(self, ctx: commands.Context, attachment: discord.Attachment):
        await ctx.typing()
        
        if not attachment:
            await ctx.send("Please attach a JSON file.")
            return
            
        if not attachment.filename.lower().endswith('.json'):
            await ctx.send("File must be a JSON file (.json).")
            return
            
        try:
            content = await attachment.read()
            history = json.loads(content.decode('utf-8'))
            

            if not isinstance(history, list) or not all(
                isinstance(m, dict) and 'role' in m and 'content' in m 
                for m in history
            ):
                await ctx.send("Invalid conversation format. Each message must have 'role' and 'content'.")
                return
                
            key = self.get_conversation(ctx)
            

            if self.db:
                await self.db.execute("""
                    INSERT INTO ai_conversations (conversation_key, history, last_updated)
                    VALUES ($1, $2, NOW())
                    ON CONFLICT (conversation_key)
                    DO UPDATE SET history = EXCLUDED.history, last_updated = NOW()
                """, json.dumps(key), json.dumps(history))
            else:
                self.conversations[key] = history
                
            await ctx.send("Conversation history imported successfully.")
            
        except json.JSONDecodeError:
            await ctx.send("Invalid JSON file.")
        except Exception as e:
            await ctx.send(f"Failed to import conversation: {e}")


    @commands.hybrid_command(name="resetai", description="Reset the conversation history of G-AI.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def resetai(self, ctx: commands.Context):
        await ctx.typing()
        conversation_key = self.get_conversation(ctx)
        
        try:
            if self.db:
                result = await self.db.execute(
                    "DELETE FROM ai_conversations WHERE conversation_key = $1",
                    json.dumps(conversation_key)
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
    cog.db = await asyncpg.create_pool(bot_info.data['database'])
    await bot.add_cog(cog)
