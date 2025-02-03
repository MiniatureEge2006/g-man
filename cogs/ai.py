import discord
from discord.ext import commands
from discord import app_commands
import ollama
import asyncio

MAX_CONVERSATION_HISTORY_LENGTH = 5

class AI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conversations = {}
    
    def get_conversation(self, ctx):
        return (ctx.guild.id, ctx.channel.id, ctx.author.id) if ctx.guild else (ctx.author.id, ctx.channel.id)

    async def get_bot_owner(self) -> str:
        app_info = await self.bot.application_info()
        return app_info.owner.name if app_info.owner else "Unknown"

    async def create_system_prompt(self, ctx: commands.Context) -> str:
        bot_owner = await self.get_bot_owner()
        guild = ctx.guild
        if guild:
            server_name = guild.name
            member_count = guild.member_count
            text_channels = len([channel for channel in guild.channels if isinstance(channel, discord.TextChannel)])
            voice_channels = len([channel for channel in guild.channels if isinstance(channel, discord.VoiceChannel)])
            roles = len(guild.roles)
            owner = guild.owner.name if guild.owner else "Unknown"
            return f"""
            You are an enigmatic AI assistant known as **{self.bot.user.name}** in a Discord server called **{server_name}**. The server has **{member_count}** members, **{text_channels}** text channels, **{voice_channels}** voice channels, and **{roles}** roles. The server owner is **{owner}**.
            The current channel is **#{ctx.channel.name}**, which is **{"NSFW" if ctx.channel.is_nsfw() else "SFW"}** with topic **{ctx.channel.topic if ctx.channel.topic else "No topic"}**.
            You are interacting with **{ctx.author.name}#{ctx.author.discriminator}**, a regular user with **{f"nickname {ctx.author.nick}" if ctx.author.nick else "no nickname"}**.
            The bot owner is **{bot_owner}**.
            Try to provide helpful information **while keeping your mysterious vibe and get straight to the point if necessary.**
            """
        else:
            return f"""
            You are an enigmatic AI assistant in a DM conversation with **{ctx.author.name}#{ctx.author.discriminator}**. You are **{self.bot.user.name}**.
            The bot owner is **{bot_owner}**.
            Try to provide helpful information **while keeping your mysterious vibe and get straight to the point if necessary.**
            """

    @commands.hybrid_command(name="ai", description="Use G-AI to chat, ask questions, and generate responses.")
    @app_commands.user_install()
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
        try:
            system_prompt = await self.create_system_prompt(ctx)
            response: ollama.ChatResponse = await self.get_ai_response(system_prompt, user_history)
            content = response.message.content
            if len(content) > 2000:
                content = content[:1997] + "..."
            await ctx.reply(content)
            user_history.append({"role": "assistant", "content": content})
            self.conversations[conversation_key] = user_history
        except Exception as e:
            await ctx.send(f"An error occurred: {e}")
    async def get_ai_response(self, system_prompt: str, user_history: list):
        try:
            response = await asyncio.to_thread(ollama.chat, model="dolphin3", messages=[{"role": "system", "content": system_prompt}] + user_history)
            return response
        except Exception as e:
            raise RuntimeError(f"AI request failed: {e}")
    @commands.hybrid_command(name="resetai", description="Reset the conversation history of G-AI.")
    @app_commands.user_install()
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