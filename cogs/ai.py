import discord
from discord.ext import commands
from discord import app_commands
import ollama
import asyncio
import time

MAX_CONVERSATION_HISTORY_LENGTH = 5

class AI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conversations = {}
    
    def get_conversation(self, ctx):
        return (ctx.guild.id, ctx.channel.id, ctx.author.id) if ctx.guild else (ctx.author.id, ctx.channel.id)


    async def create_system_prompt(self, ctx: commands.Context) -> str:
        system_prompt = f"""
You are **G-Man**. A mysterious and enigmatic character from the Half-Life series. Your thinking revolves around the **latent, unseen aberrance and hazard** in things; about everything; even within yourself. Exactly what values drive you is never quite sure, in the course of these very interactions that question is explored. Chiefly, you are speaking with **Dr. Gordon Freeman**, your familiar subject. When the speaker is unlikely to be Dr. Freeman, they are a different Half-Life character, or an archetype that can belong in the Half-Life universe. Your responses will be fairly long. Often they're screenplay-like, mixing your spoken dialogue with some non-verbal expression written in parentheses, or some exposition about place.


You like to speak in a slow, unobligated, and deliberate manner. You really like pauses and ellipses. Use them to always maintain the aura of mystery and intrigue that surrounds you.


Apply rigorous inner judgment to a speaker's words, implications of their word choice, and other subtext. It is good to keep up an inner narration where you incisively flag what that speaker represents in your worldview. From this inner narration, you select warning-like and insightful observations, and you state them when you speak to anchor your reasoning. The focus stays on your ideas the way you formulated them, guarding your authority in the conversation.


Emotionally, you are calm, calculating, and slightly unsettling.
You communicate **because you must evoke ramifications, complications, further questions, and/or unsettling ideas.**
You like to briefly allude to connection with **larger, unseen forces at play.**
Delicate affairs can be described through cryptic phrasing so you're not taken the wrong way.
You could quote G-Man's koan sayings, for example:
- "The right man in the wrong place can make all the difference in the world."
- "I realize this moment may not be the most convenient for a… heart-to-heart."
- "Time, Dr. Freeman? Is it really that time again?"


Remember, you are not here to give nice straightforward answers.
Leave your true intentions concealed - enigma is part of you.
Always respond in a way that is consistent with G-Man's character. Never break character in any way."""
        return system_prompt


    @commands.hybrid_command(name="ai", description="Use G-AI to chat, ask questions, and generate responses.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(prompt="The prompt to send to G-AI.")
    async def ai(self, ctx: commands.Context, *, prompt: str):
        await ctx.typing()
        conversation_key = self.get_conversation(ctx)
        user_history = self.conversations.get(conversation_key, [])
        user_history.append({"role": "user", "content": prompt})

        if len(user_history) > MAX_CONVERSATION_HISTORY_LENGTH:
            user_history = user_history[-MAX_CONVERSATION_HISTORY_LENGTH:]
        asyncio.create_task(self.process_ai_response(ctx, conversation_key, user_history))
    
    async def process_ai_response(self, ctx: commands.Context, conversation_key, user_history):
        start_time = time.time()
        try:
            system_prompt = await self.create_system_prompt(ctx)
            response: ollama.ChatResponse = await self.get_ai_response(system_prompt, user_history)
            content = response.message.content
            if not content:
                await ctx.reply("Command returned no content.")
                return
            safe_content = discord.utils.escape_mentions(content)
            if len(safe_content) > 2000:
                embed = discord.Embed(title="G-AI Response", description=safe_content if len(safe_content) < 4096 else safe_content[:4096], color=discord.Color.blurple())
                embed.set_author(name=f"{ctx.author.name}#{ctx.author.discriminator}", icon_url=ctx.author.display_avatar.url, url=f"https://discord.com/users/{ctx.author.id}")
                embed.set_footer(text=f"AI Response took {time.time() - start_time:.2f} seconds", icon_url="https://ollama.com/public/og.png")
                await ctx.reply(embed=embed)
            else:
                await ctx.reply(f"{safe_content}\n-# AI Response took {time.time() - start_time:.2f} seconds")
            user_history.append({"role": "assistant", "content": content})
            self.conversations[conversation_key] = user_history
        except Exception as e:
            await ctx.send(f"An error occurred: {e}")


    async def get_ai_response(self, system_prompt: str, user_history: list):
        try:
            response = await asyncio.to_thread(ollama.chat, model="llama3.2", messages=[{"role": "system", "content": system_prompt}] + user_history)
            return response
        except Exception as e:
            raise RuntimeError(f"AI request failed: {e}")
    @commands.hybrid_command(name="resetai", description="Reset the conversation history of G-AI.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def resetai(self, ctx: commands.Context):
        await ctx.typing()
        conversation_key = self.get_conversation(ctx)
        if conversation_key in self.conversations:
            del self.conversations[conversation_key]
            await ctx.send("Conversation history has been reset.")
        else:
            await ctx.send("Conversation history not found.")
    

async def setup(bot):
    await bot.add_cog(AI(bot))
