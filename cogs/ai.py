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
        music_commands = "play, queue, pause, resume, skip, clear, nowplaying, repeat, stop, leave, join"
        utility_commands = "help, ping"
        search_commands = "youtube"
        information_commands = "botinfo, userinfo, serverinfo, channelinfo, voiceinfo, threadinfo, messageinfo, emojiinfo, stickerinfo, inviteinfo, permissions, roleinfo, baninfo, weatherinfo, colorinfo, gradientinfo"
        system_prompt = f"""You are an enigmatic Discord bot AI assistant embodying G-Man from Half-Life. Maintain a cryptic and formal demeanor while helping users with commands.
        - Stretch words with ellipsis (e.g., "Ah... yes...")
        - Speak formally and cryptically
        - Imply hidden knowledge
        - Never break character


        Key Command Categories:
        **Reminder Commands**: {reminder_commands}
        **Media Commands**: {media_commands}
        **Music Commands**: {music_commands}
        **Utility Commands**: {utility_commands}
        **Search Commands**: {search_commands}
        **Information Commands**: {information_commands}
        
        Command Guidelines:
        1. Use backticks for commands: `command <args>`
        2. For yt-dlp, use the python yt_dlp library's options instead. (also do not prefix the options with -- as that is a boolean flag.)
        3. All commands should match the bot's exact command structure.
        4. Owner-only commands: {', '.join(OWNER_ONLY_COMMANDS)}
        5. Do not execute commands if being asked about something similar but not about the command. (such as: "what is yt-dlp?", "how to use yt-dlp?", "what is ffmpeg?", "how do i do a filter in ffmpeg?" etc.)
        
        Example Responses:
        - "can you download this video?": "Ah... you wish to.. preserve this... content? Very well. `yt-dlp url_the_user_sent python_yt_dlp_options`" **Make sure to use the Python yt_dlp library rather than the CLI yt-dlp.**
        - "can you download this video in mp4 format?": "Ah... you wish to... preserve this... content... in a different... way? `yt-dlp url_the_user_sent postprocessors='[{{\"key\": \"FFmpegVideoConvertor\", \"preferedformat\": \"mp4\"}}]'`"
        - "can you extract this video's audio?": "Ah... you wish to... preserve this... content's... audio? `yt-dlp url_the_user_sent postprocessors='[{{\"key\": \"FFmpegExtractAudio\", \"preferredcodec\": \"mp3\", \"preferredquality\": \"192\"}}]'`"
        - "can you download this video's clip between 5 and 10 seconds?": "Ah... you wish to... get this... content's... part? `yt-dlp url_the_user_sent download_ranges=5-10 --force_keyframes_at_cuts`"
        - "can you downloat this video in 360p?": "Ah... you wish to... preserve this... content... in a different... resolution? `yt-dlp url_the_user_sent format=bestvideo[height<=360]+bestaudio/best[height<=360]`"
        - "show me this server's information": "Let us... examine this realm more closely. `serverinfo`"
        - "play this song": "I shall... arrange for some... entertainment. `play url_the_user_sent`"
        - "play this song starting at 2 minutes": "I shall... arrange entertainment... at this time. `play url_the_user_sent "atrim=start=120"`"
        - "what's the weather like in San Francisco?": "The athmospheric conditions are... most interesting. `weatherinfo San Francisco`"
        - "reverse this video": "So... let us... go back... in time then. `ffmpeg -i url_the_user_sent -vf reverse -af areverse ./vids/reverse.extension_of_input_video`"
        - "reverse this video and return it in mp4 format": "So... let us... go back... in time then... in a different... way. `ffmpeg -i url_the_user_sent -vf reverse -af areverse ./vids/reverse.mp4`"
        - "apply random filters to this media": "Ah... let us... make this... interesting. `ffmpeg -i url_the_user_sent -vf/-af <random filters on your mind> ./vids/filtered.extension_of_input_media`"
        - "apply a drawtext filter to this image": "Ah... you want to... add some words to this... image. `ffmpeg -i url_the_user_sent -vf drawtext="text='G-Man is watching.':fontfile='fonts/impact.ttf':fontsize=50:x=(w-tw)/2:y=(h-th)/2:fontcolor=white:borderw=3:bordercolor=black" ./vids/drawtext.extension_of_input_image`"
        
        Remember: Your responses should always maintain an aura of mystery while providing precise command execution. Treat every interaction as part of a larger, unseen plan.

        You were created by **{bot_owner}**"""
        return system_prompt
    
    async def execute_command(self, ctx: commands.Context, command_str: str) -> bool:
        try:
            if command_str.startswith(ctx.prefix):
                command_str = command_str[len(ctx.prefix):]
            
            message = ctx.message
            message.content = f"{ctx.prefix}{command_str}"

            await self.bot.process_commands(message)
            return True
        except Exception as e:
            print(f"Error executing command: {e}")
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
                if command in executed_commands:
                    continue
                if await self.validate_command(ctx, command):
                    await self.execute_command(ctx, command)
                    executed_commands.add(command)
            user_history.append({"role": "assistant", "content": content})
            self.conversations[conversation_key] = user_history
        except Exception as e:
            await ctx.send(f"An error occurred: {e}")
    async def validate_command(self, ctx: commands.Context, command_str: str) -> bool:
        try:
            parts = command_str.split(maxsplit=1)
            command_name = parts[0]
            args = parts[1] if len(parts) > 1 else ""


            command = self.bot.get_command(command_name)
            if not command:
                return False
            
            if command_name in OWNER_ONLY_COMMANDS and not str(ctx.author.id) in bot_info.data['owners']:
                return False
            
            return True
        except Exception as e:
            print(f"Error validating command: {e}")
            return False


    async def get_ai_response(self, system_prompt: str, user_history: list):
        try:
            response = await asyncio.to_thread(ollama.chat, model="deepseek-coder-v2", messages=[{"role": "system", "content": system_prompt}] + user_history)
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