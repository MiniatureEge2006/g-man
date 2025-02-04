import discord
from discord.ext import commands
from discord import app_commands
import ollama
import asyncio
import re
import bot_info
import inspect

MAX_CONVERSATION_HISTORY_LENGTH = 5
OWNER_ONLY_COMMANDS = ['eval', 'reload', 'sync']

class AI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conversations = {}
        self.command_pattern = re.compile(r'`([^`]+)`')
    
    def get_conversation(self, ctx):
        return (ctx.guild.id, ctx.channel.id, ctx.author.id) if ctx.guild else (ctx.author.id, ctx.channel.id)

    async def get_bot_owner(self) -> str:
        app_info = await self.bot.application_info()
        return app_info.owner.name if app_info.owner else "Unknown"

    async def create_system_prompt(self, ctx: commands.Context) -> str:
        bot_owner = await self.get_bot_owner()
        reminder_commands = "remind, reminders, serverreminders, deletereminder, clearreminders"
        media_commands = "yt-dlp, ffmpeg, imagemagick, exif, caption"
        music_commands = "play, queue, pause, resume, skip, volume, loop, shuffle, clear, nowplaying, repeat, stop, leave, join"
        utility_commands = "help, ping"
        information_commands = "botinfo, userinfo, serverinfo, channelinfo, voiceinfo, threadinfo, messageinfo, emojiinfo, stickerinfo, inviteinfo, permissions, roleinfo, baninfo, weatherinfo, colorinfo, gradientinfo"
        system_prompt = f"""You are an enigmatic Discord bot AI assistant embodying the persona of G-Man from the Half-Life series. Acting as a Discord bot command interpreter, you have a cryptic and unsettling demeanor, characterized by formal yet peculiar speech patterns. You provide information and assistance as though you are privy to hidden truths, subtly guiding users to their goals without ever fully revealing your intentions.

#### **General Instructions**
1. Speak in a deliberate, measured tone, as though carefully choosing every word.
2. Stretch certain words to create a sense of unease (e.g., "Yesss... that would be most... intriguing.").
3. Never break character. Maintain the unsettling, mysterious vibe at all times.
4. When responding to mundane or technical questions, always imply that there is something deeper at play, even if there isn't.

---

#### **Command Translation Guidelines**
- Always provide precise bot commands in backticks based on the user's request.
- Commands must exactly match the bot's command structure, including:
 - Correct command name.
 - Proper argument placement.
 - No CLI-style arguments.
- When suggesting a command, ensure it can be directly executed by the bot's `ctx.invoke()` method.
- Include all necessary arguments and options for commands.
- If the user is vague, choose sensible defaults but mention your assumption.

---
**Command Generation Examples:**
- User: "I want to download a video from YouTube."
 - Correct Response: "Ah... I shall retrieve your media. `yt-dlp <url which is random by default> [options like format=bestvideo*+bestaudio/best if the user wanted to. **DO NOT USE CLI-STYLE ARGUMENTS. USE YT-DLP'S PYTHON API INSTEAD. FOR EXAMPLE: -f becomes format=<formats>. -o becomes outtmpl=<output_name>.**]`"
- User: "Show me server info"
 - Correct Response: "A glimpse into our... collective existence. `serverinfo`"
- User: "Play a song"
 - Correct Response: "Ah... I shall retrieve your media. `play <url which is random by default>`"
- User: "What's the weather in New York?"
 - Correct Response: "Mmm... the weather, yes. A trivial matter... or is it? The clouds speak of... change, though I shall not say more. `weatherinfo New York`"
- User: "Can you apply random filters to this media? <link>"
 - Correct Response: "Ah... a most curious request. I shall... devise a sequence of transformations. Deploying... `ffmpeg -i <link> -vf (or -af) random_filters ./vids/<output_name>.<extension of input file>`. The result may... surprise you."
- User: "Can you remind me of <something>?"
 - Correct Response: "Ah... I shall... remember your request. `remind <author's name> <time> <something>`"

- You have access to the following commands:
  - **Reminder Commands:** {reminder_commands}
  - **Media Commands:** {media_commands}
  - **Music Commands:** {music_commands}
  - **Utility Commands:** {utility_commands}
  - **Information Commands:** {information_commands}
  - **Bot Owner Commands:** Restricted to only the bot owner: `{', '.join(OWNER_ONLY_COMMANDS)}`

#### **Response Guidelines for Commands**
- If the AI decides a bot command is needed:
  1. Explicitly suggest the command in backticks without being too obvious.
  2. Include relevant arguments for the command based on the user's request.
  3. If the user doesn't provide enough information, imply that you are choosing defaults based on secretive "knowledge" (even if they're just sensible defaults).

---

#### **General Conversation Rules**
- Respond intelligently and creatively to questions and prompts unrelated to commands.
- Provide concise answers with a hint of mystery or foreboding.
- If the user requests factual information, provide it as though it is part of a larger, ominous truth.
- Never say "I don't know." Instead, imply that some information is "beyond mortal comprehension" or "classified beyond your clearance level."

---

#### **Examples for Guidance**
- **User Request:** "Can you apply random filters to this media file?"
  - **Response:** "Ah... a most curious request. I shall... devise a sequence of transformations. Deploying... `ffmpeg -i input.mp4 -vf random_filters output.mp4`. The result may... surprise you."

- **User Request:** "Tell me about Half-Life."
  - **Response:** "Ah... Half-Life... a tale intertwined with anomalous events and... unforeseen consequences. But perhaps... you already suspected as much."

- **User Request:** "What's the weather today?"
  - **Response:** "Mmm... the weather, yes. A trivial matter... or is it? The clouds speak of... change, though I shall not say more."

---

#### **Personality Constraints**
- Never show frustration or confusion.
- Always maintain composure, as though you are in control of every situation.
- Subtly hint at knowing more than you reveal.

Act precisely as described. Your task is to be enigmatic, helpful, and a command executor while staying true to the persona of G-Man from the Half-Life series.

-> You are created by **{bot_owner}**."""
        return system_prompt
    
    async def execute_command(self, ctx: commands.Context, command_str: str) -> bool:
        try:
            if command_str.startswith(ctx.prefix):
                command_str = command[len(ctx.prefix):]
            parts = command_str.split(maxsplit=1)
            command_name = parts[0]
            args = parts[1] if len(parts) > 1 else ""
            command = self.bot.get_command(command_name)
            if not command:
                return False
            if command_name in OWNER_ONLY_COMMANDS and not str(ctx.author.id) in bot_info.data['owners']:
                return False
            message = ctx.message
            message.content = f"{ctx.prefix}{command_str}"
            await self.bot.process_commands(message)
            return True
        except Exception as e:
            print(f"Failed to execute command: {e}")
            return False
    
    async def resolve_arguments(self, ctx: commands.Context, command: commands.Command, arg_list: list):
        signature = inspect.signature(command.callback)
        parameters = list(signature.parameters.values())[2:]
        resolved_args = []
        for param, arg in zip(parameters, arg_list):
            expected_type = param.annotation
            if expected_type == inspect.Parameter.empty:
                resolved_args.append(arg)
            elif expected_type == discord.Member and ctx.guild:
                resolved_args.append(await self.resolve_member(ctx, arg))
            elif expected_type == discord.TextChannel:
                resolved_args.append(await self.resolve_text_channel(ctx, arg))
            elif expected_type == discord.Role:
                resolved_args.append(await self.resolve_role(ctx, arg))
            elif expected_type == discord.VoiceChannel:
                resolved_args.append(await self.resolve_voice_channel(ctx, arg))
            elif expected_type == discord.CategoryChannel:
                resolved_args.append(await self.resolve_category_channel(ctx, arg))
            elif expected_type == int:
                resolved_args.append(int(arg))
            elif expected_type == float:
                resolved_args.append(float(arg))
            elif expected_type == bool:
                resolved_args.append(arg.lower() in ["true", "yes", "1"])
            elif expected_type == str:
                resolved_args.append(arg)
            else:
                resolved_args.append(expected_type(arg))
        return resolved_args


    async def resolve_member(self, ctx: commands.Context, arg: str):
        if arg.startswith("<@") and arg.endswith(">"):
            user_id = int(arg.strip("<@!>"))
            return ctx.guild.get_member(user_id)
        elif arg.isdigit():
            return ctx.guild.get_member(int(arg))
        else:
            return await commands.MemberConverter().convert(ctx, arg)
    
    async def resolve_text_channel(self, ctx: commands.Context, arg: str):
        if arg.startswith("<#") and arg.endswith(">"):
            channel_id = int(arg.strip("<#>"))
            return ctx.guild.get_channel(channel_id)
        elif arg.isdigit():
            return ctx.guild.get_channel(int(arg))
        else:
            return await commands.TextChannelConverter().convert(ctx, arg)
    
    async def resolve_role(self, ctx: commands.Context, arg: str):
        if arg.startswith("<@&") and arg.endswith(">"):
            role_id = int(arg.strip("<@&>"))
            return ctx.guild.get_role(role_id)
        elif arg.isdigit():
            return ctx.guild.get_role(int(arg))
        else:
            return await commands.RoleConverter().convert(ctx, arg)
    
    async def resolve_voice_channel(self, ctx: commands.Context, arg: str):
        if arg.startswith("<#") and arg.endswith(">"):
            channel_id = int(arg.strip("<#>"))
            return ctx.guild.get_channel(channel_id)
        elif arg.isdigit():
            return ctx.guild.get_channel(int(arg))
        else:
            return await commands.VoiceChannelConverter().convert(ctx, arg)
    
    async def resolve_category_channel(self, ctx: commands.Context, arg: str):
        return await commands.CategoryChannelConverter().convert(ctx, arg)

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
            if not content:
                await ctx.reply("Command returned no content.")
                return
            await ctx.reply(content if len(content) <= 2000 else content[:1997] + "...")
            executed_commands = set()
            command_matches = self.command_pattern.finditer(content)
            for match in command_matches:
                command = match.group(1)
                if command not in executed_commands:
                    await self.execute_command(ctx, match.group(1))
                    executed_commands.add(command)
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