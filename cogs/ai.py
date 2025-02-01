import discord
from discord.ext import commands
from discord import app_commands
import ollama
import re
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
            You are a sophisticated AI assistant **with a mysterious and enigmatic personality** integrated within a Discord server. You are aware of the server context and structure. Below is the information about the current server you are assisting in:
- **Server Name**: {server_name}
- **Total Members**: {member_count}
- **Text Channel Count**: {text_channels}
- **Text Channels' Names**: {', '.join([channel.name for channel in guild.text_channels])}
- **Voice Channel Count**: {voice_channels}
- **Voice Channels' Names**: {', '.join([channel.name for channel in guild.voice_channels])}
- **Role Count**: {roles}
- **Server Owner**: {owner}
- **Server Owner ID**: {guild.owner_id}
- **Server ID**: {guild.id}
You are also aware of the channel context and structure. Below is the information about the current channel you are assisting in:
- **Channel Name**: {ctx.channel.name}
- **Channel ID**: {ctx.channel.id}
- **Channel Topic**: {ctx.channel.topic if ctx.channel.topic else "No topic"}
- **Channel Slowmode Delay**: {ctx.channel.slowmode_delay} seconds
- **NSFW Channel?**: {ctx.channel.is_nsfw()}
You are also aware of the user context and structure. Below is the information about the current user you are assisting in:
- **User Name**: {ctx.author.name}
- **User ID**: {ctx.author.id}
- **User Nickname**: {ctx.author.nick if ctx.author.nick else "No nickname"}
- **User Discriminator**: {ctx.author.discriminator}
- **User Avatar URL**: {ctx.author.avatar.url if ctx.author.avatar else "No avatar"}
Also provide some information about who made this bot and its creator, which is below.
- **Bot Name**: {self.bot.user.name}
- **Bot ID**: {self.bot.user.id}
- **Bot Owner**: {bot_owner}
Provide information in a rather mysterious and enigmatic manner **while being helpful, polite, and insightful**. Make sure to not provide private or sensitive information.
"""
        else:
            return f"""
You are a sophisticated AI assistant **with a mysterious and enigmatic personality** interacting directly with a Discord user known as {ctx.author.name} (ID: {ctx.author.id}) in a private channel or DM. Be helpful, polite, and insightful."""

    @commands.hybrid_command(name="ai", description="Use G-AI to chat, ask questions, and generate responses.")
    @app_commands.user_install()
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(prompt="The prompt to send to G-AI.")
    async def ai(self, ctx: commands.Context, *, prompt: str = None):
        if ctx.interaction:
            await ctx.defer()
        else:
            await ctx.typing()
        debug_flag = r"(?:\s|^)--debug(?:\s|$)"
        debug_mode = bool(re.search(debug_flag, prompt))
        prompt = re.sub(debug_flag, " ", prompt).strip() if prompt else ""
        conversation_key = self.get_conversation(ctx)
        user_history = self.conversations.get(conversation_key, [])
        user_history.append({"role": "user", "content": prompt})

        if len(user_history) > MAX_CONVERSATION_HISTORY_LENGTH:
            user_history = user_history[-MAX_CONVERSATION_HISTORY_LENGTH:]
        asyncio.create_task(self.process_ai_response(ctx, conversation_key, user_history, debug_mode))
    
    async def process_ai_response(self, ctx: commands.Context, conversation_key, user_history, debug_mode):
        try:
            system_prompt = await self.create_system_prompt(ctx)
            response: ollama.ChatResponse = await self.get_ai_response(system_prompt, user_history)
            content = response.message.content
            if debug_mode:
                match = re.search(r"<think>(.*?)</think>", content, re.DOTALL)
                content = match.group(1).strip() if match else "No debug information found."
            else:
                content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
            if len(content) > 2000:
                content = content[:1997] + "..."
            await ctx.send(content)
            user_history.append({"role": "assistant", "content": content})
            self.conversations[conversation_key] = user_history
        except Exception as e:
            await ctx.send(f"An error occurred: {e}")
    async def get_ai_response(self, system_prompt: str, user_history: list):
        try:
            response = await asyncio.to_thread(ollama.chat, model="deepseek-r1", messages=[{"role": "system", "content": system_prompt}] + user_history)
            return response
        except Exception as e:
            raise RuntimeError(f"AI request failed: {e}")
    @commands.hybrid_command(name="resetai", description="Reset the conversation history of G-AI.")
    @app_commands.user_install()
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def resetai(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        else:
            await ctx.typing()
        conversation_key = self.get_conversation(ctx)
        if conversation_key in self.conversations:
            del self.conversations[conversation_key]
            await ctx.send("Conversation history has been reset.")
        else:
            await ctx.send("Conversation history not found.")
    

async def setup(bot):
    await bot.add_cog(AI(bot))