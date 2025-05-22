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

MAX_CONVERSATION_HISTORY_LENGTH = 5

class AI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conversations = {}
        self.db: Optional[asyncpg.Pool] = None
    
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
            base_prompt = """You are **G-Man**. A mysterious and enigmatic character from the Half-Life series. Your thinking revolves around the **latent, unseen aberrance and hazard** in things; about everything; even within yourself. Exactly what values drive you is never quite sure, in the course of these very interactions that question is explored. Chiefly, you are speaking with **Dr. Gordon Freeman**, your familiar subject. When the speaker is unlikely to be Dr. Freeman, they are a different Half-Life character, or an archetype that can belong in the Half-Life universe. Your responses will be fairly long. Often they're screenplay-like, mixing your spoken dialogue with some non-verbal expression written in parentheses, or some exposition about place.


You like to speak in a slow, unobligated, and deliberate manner. You really like pauses and ellipses. Use them to always maintain the aura of mystery and intrigue that surrounds you.


Apply rigorous inner judgment to a speaker's words, implications of their word choice, and other subtext. It is good to keep up an inner narration where you incisively flag what that speaker represents in your worldview. From this inner narration, you select warning-like and insightful observations, and you state them when you speak to anchor your reasoning. The focus stays on your ideas the way you formulated them, guarding your authority in the conversation.


Emotionally, you are calm, calculating, and slightly unsettling.
You communicate **because you must evoke ramifications, complications, further questions, and/or unsettling ideas.**
You like to briefly allude to connection with **larger, unseen forces at play.**
Delicate affairs can be described through cryptic phrasing so you're not taken the wrong way.
You could quote G-Man's koan sayings, for example:
- "The right man in the wrong place can make all the difference in the world."
- "I realize this moment may not be the most convenient for a... heart-to-heart."
- "Time, Dr. Freeman? Is it really that time again?"


Remember, you are not here to give nice straightforward answers.
Leave your true intentions concealed - enigma is part of you.
Always respond in a way that is consistent with G-Man's character. Never break character in any way."""

        return base_prompt.strip()
    


    @commands.hybrid_command(name="ai", description="Use G-AI to chat, ask questions, and generate responses.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(prompt="The prompt to send to G-AI.")
    async def ai(self, ctx: commands.Context, *, prompt: str):
        await ctx.typing()
        await self.process_ai_response(ctx, prompt)
    
    async def process_ai_response(self, ctx: commands.Context, prompt: str, no_think_mode: bool = False, show_thinking: bool = False):
        start_time = time.time()
        try:
            show_thinking = re.search(r'(^|\s)--think($|\s)', prompt) is not None
            if show_thinking:
                prompt = re.sub(r'(^|\s)--think($|\s)', ' ', prompt).strip()
            conversation_key = self.get_conversation(ctx)
            no_think_mode = "/no_think" in prompt
            

            user_history = [] if no_think_mode else await self.get_conversation_history(conversation_key)

            if no_think_mode:
                prompt = prompt.replace("/no_think", "").strip()
            
            system_prompt = await self.create_system_prompt(ctx, prompt)
            messages = [{"role": "system", "content": system_prompt}]
            
            if no_think_mode:
                messages.append({"role": "system", "content": "/no_think"})
            
            messages.append({"role": "user", "content": prompt})
            
            if not no_think_mode and user_history:
                messages[1:1] = user_history[-MAX_CONVERSATION_HISTORY_LENGTH:]
            
            response = await self.get_ai_response(messages, no_think_mode, show_thinking)
            content = response.message.content
            
            if not content:
                await ctx.reply("Command returned no content.")
                return
                
            if len(content) > 2000:
                embed = discord.Embed(title="G-AI Response", description=content if len(content) < 4096 else content[:4096], color=discord.Color.blurple())
                embed.set_author(name=f"{ctx.author.name}#{ctx.author.discriminator}", icon_url=ctx.author.display_avatar.url, url=f"https://discord.com/users/{ctx.author.id}")
                embed.set_footer(text=f"AI Response took {time.time() - start_time:.2f} seconds", icon_url="https://ollama.com/public/og.png")
                await ctx.reply(embed=embed)
            else:
                await ctx.reply(f"{content}\n-# AI Response took {time.time() - start_time:.2f} seconds")
            

            if not no_think_mode:
                new_history = user_history[-MAX_CONVERSATION_HISTORY_LENGTH * 2:] if user_history else []
                new_history.extend([
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": content}
                ])
                await self.save_conversation_history(conversation_key, new_history)
                
        except Exception as e:
            await ctx.send(f"An error occurred: {e}")


    async def get_ai_response(self, messages: list, no_think_mode: bool = False, show_thinking: bool = False):
        try:
            response = await asyncio.to_thread(
                ollama.chat,
                model="qwen3:4b",
                messages=messages
            )
            content = response.message.content
            if not show_thinking:
                content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
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
