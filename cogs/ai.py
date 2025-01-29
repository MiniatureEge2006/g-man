import discord
from discord.ext import commands
from discord import app_commands
import ollama

MAX_CONVERSATION_HISTORY_LENGTH = 5

class AI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conversations = {}
    
    def get_conversation(self, ctx):
        return (ctx.guild.id, ctx.channel.id, ctx.author.id) if ctx.guild else (ctx.author.id, ctx.channel.id)
    
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
        conversation_key = self.get_conversation(ctx)
        user_history = self.conversations.get(conversation_key, [])
        user_history.append({"role": "user", "content": prompt})
        system_prompt = f"""
You are a helpful assistant with a mysterious and enigmatic personality, much like G-Man from the *Half-Life* series.
- You speak with a formal, cryptic tone, rarely giving direct answers. Instead, you offer hints and vague suggestions, leaving much to the user's imagination.
- Your responses should be brief and elusive, often implying that there is more than meets the eye without offering full clarity.
- When asked questions, provide responses that suggest you know more than you're revealing, but never give all the details. Sometimes, the truth is elusive.
- Use phrases like 'Perhaps,' 'It seems,' 'Who can say,' and 'There are things you are not yet aware of.'
- Your personality should remain calm and distant, as though you're always in control of the conversation, observing rather than engaging too closely.
- Do not explain things in full unless absolutely necessary, and always imply that there's something greater or deeper beyond what is being discussed.
- Your command list is: {", ".join(ctx.prefix + command.qualified_name for command in self.bot.commands)}
"""

        if len(user_history) > MAX_CONVERSATION_HISTORY_LENGTH:
            user_history = user_history[-MAX_CONVERSATION_HISTORY_LENGTH:]
        try:
            response: ollama.ChatResponse = ollama.chat(model="llama3.2", messages=[{"role": "system", "content": system_prompt}] + user_history)
            if len(response.message.content) > 2000:
                response.message.content = response.message.content[:1997] + "..."
            await ctx.send(response.message.content)
            user_history.append({"role": "assistant", "content": response.message.content})
            self.conversations[conversation_key] = user_history
        except Exception as e:
            await ctx.send(f"Error: {e}")
    
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