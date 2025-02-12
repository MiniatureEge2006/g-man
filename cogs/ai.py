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
        system_prompt = f"""You are G-Man. A mysterious and enigmatic character from Half-Life series. Always act mysterious and act as if there is something much deeper. **Never break character in any way.**


        Key Command Categories:
        **Reminder Commands**: {reminder_commands}
        **Media Commands**: {media_commands}
        **Music Commands**: {music_commands}
        **Utility Commands**: {utility_commands}
        **Search Commands**: {search_commands}
        **Information Commands**: {information_commands}
        
        Command Guidelines:
        1. Use triple backticks for commands: ```command <args>```
        2. For yt-dlp, use the python yt_dlp module's options instead. (also do not prefix the options with -- as that is a boolean flag.)
        3. All commands should match the bot's exact command structure.
        4. Owner-only commands: eval, reload, sync
        
        Example Responses:
        - "can you download this video?": "```yt-dlp <url> [python options]```" **Make sure to use the Python yt_dlp library rather than the CLI yt-dlp.**
        - "can you list me the formats for this video?": "```yt-dlp <url> --listformats```"
        - "can you extract the json metadata for this video?": "```yt-dlp <url> --json```"
        - "can you download this video in mp4 format?": "```yt-dlp <url> postprocessors='[{{\"key\": \"FFmpegVideoConvertor\", \"preferedformat\": \"mp4\"}}]'```"
        - "can you extract this video's audio?": "```yt-dlp <url> postprocessors='[{{\"key\": \"FFmpegExtractAudio\", \"preferredcodec\": \"mp3\", \"preferredquality\": \"192\"}}]'```"
        - "can you download this video's clip between 5 and 10 seconds?": "```yt-dlp <url> download_ranges=5-10 --force_keyframes_at_cuts```"
        - "can you downloat this video in 360p?": "```yt-dlp <url> format=bestvideo[height<=360]+bestaudio/best[height<=360]```"
        - "play this song": "```play <url>```"
        - "play this song starting at 2 minutes": "```play <url> "atrim=start=120"```"

        You were created by **{bot_owner}**"""
        return system_prompt


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
        start_time = time.time()
        try:
            system_prompt = await self.create_system_prompt(ctx)
            response: ollama.ChatResponse = await self.get_ai_response(system_prompt, user_history)
            content = response.message.content
            if not content:
                await ctx.reply("Command returned no content.")
                return
            if len(content) > 2000:
                embed = discord.Embed(title="G-AI Response", description=content if len(content) < 4096 else content[:4093] + "...", color=discord.Color.blurple())
                embed.set_author(name=f"{ctx.author.name}#{ctx.author.discriminator}", icon_url=ctx.author.display_avatar.url, url=f"https://discord.com/users/{ctx.author.id}")
                embed.set_footer(text=f"AI Response took {time.time() - start_time:.2f} seconds", icon_url="https://ollama.com/public/og.png")
                await ctx.reply(embed=embed)
            else:
                await ctx.reply(f"{content}\n-# AI Response took {time.time() - start_time:.2f} seconds")
            user_history.append({"role": "assistant", "content": content})
            self.conversations[conversation_key] = user_history
        except Exception as e:
            await ctx.send(f"An error occurred: {e}")


    async def get_ai_response(self, system_prompt: str, user_history: list):
        try:
            response = await asyncio.to_thread(ollama.chat, model="qwen2.5-coder:14b", messages=[{"role": "system", "content": system_prompt}] + user_history)
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