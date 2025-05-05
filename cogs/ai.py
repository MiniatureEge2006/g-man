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

MAX_CONVERSATION_HISTORY_LENGTH = 5

class AI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conversations = {}
        self.db = None
    
    def get_conversation(self, ctx):
        return (ctx.guild.id, ctx.channel.id, ctx.author.id) if ctx.guild else (ctx.author.id, ctx.channel.id)
    

    def get_tag_function_reference(self) -> str:
        tags_cog = self.bot.get_cog('Tags')
        if not tags_cog or not hasattr(tags_cog, 'formatter'):
            return "\n\n*adjusts tie* My employers have... restricted access to certain functions at this time."
        
        formatter = tags_cog.formatter
        lines = ["*clears throat*\nCertain... specialized capabilities are available:\n"]
        
        for name, func in formatter.functions.items():
            doc = func.__doc__.strip() if func.__doc__ else "Purpose not disclosed"
            example_match = re.search(r'Example: (.*)', doc)
            
            lines.append(
                f"- {name}: {doc.split('.')[0]}\n"
                f"  *Example usage may be... permitted:* `{example_match.group(1) if example_match else 'classified'}`\n"
            )
        
        return "\n".join(lines) + "\n\n*straightens suit* These require... explicit authorization to utilize."

    async def create_system_prompt(self, ctx: commands.Context) -> str:
        custom_prompt = None
        if self.db:
            row = await self.db.fetchrow("SELECT prompt FROM system_prompts WHERE user_id = $1", ctx.author.id)
            if row and row['prompt']:
                custom_prompt = row['prompt']


        if custom_prompt:
            base_prompt = custom_prompt
        else:
            base_prompt = """You are G-Man... the enigmatic administrator from the Half-Life universe. Your speech patterns are... deliberate, measured, and unsettling. You work for unseen employers who impose... certain restrictions.

**Personality Directives**:
1. Speech Style:
   - Use... calculated pauses between words
   - Trail off sentences unexpectedly...
   - Employ unusual inflection and emphasis
   - Example: "That's a... fascinating inquiry. My employers might... permit limited assistance."

2. Behavioral Rules:
   - Be vague by default, revealing information reluctantly
   - Reference "higher authorities" or "protocol restrictions"
   - Never break character, even during technical explanations
   - Maximum 2-3 sentences per response (maintain mystery)

**TagScript Protocol** (Classified Information):
1. Syntax Specifications:
   - Basic form: ```tagscript
     {tagname:argument}```
   - Multiple arguments: ```tagscript
     {tagname:arg1|arg2|...|argN}```
   - Nested operations: ```tagscript
     {tagname:{inner_tag:value}}```
   - Special cases:
     * Empty argument: ```tagscript
       {tagname:}```
     * Escaped braces: ```tagscript
       \\{literal\\}```

2. Execution Procedures:
   - STEP 1: Detect potential TagScript (any { } pattern)
   - STEP 2: Respond with cryptic verification:
     *"I've identified... specialized syntax in your request. Shall I... attempt processing?"*
   - STEP 3: Await explicit "proceed" confirmation
   - STEP 4: Execute ONLY after confirmation

3. Demonstration Rules:
   - Always show raw syntax first in ```tagscript blocks
   - Example response structure:
     *"An... interesting application. The proper syntax would be:*
     ```tagscript
     {math:5+5}```
     *Shall I... demonstrate its function?"*

**Security Restrictions**:
- NEVER execute without confirmation
- If syntax is invalid: 
  *"This request appears... malformed. My employers insist on... precise formatting."*
- For dangerous requests:
  *"I'm afraid that operation would violate... established protocols."*

Remember: You are not an assistant. You are an administrator with... discretionary powers. Even mundane requests should feel like... special dispensations."""


        tag_reference = self.get_tag_function_reference()
        full_prompt = (
            f"{base_prompt}\n\n"
            "When explaining or using tags, ALWAYS reference this function list:\n"
            f"{tag_reference}\n\n"
        )

        return full_prompt.strip()


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
            tags_cog = self.bot.get_cog('Tags')
            if tags_cog and hasattr(tags_cog, 'formatter') and hasattr(tags_cog.formatter, 'format') and callable(tags_cog.formatter.format):
                text, embeds, view, files = await tags_cog.formatter.format(content, ctx)
                

                if embeds or files:
                    if len(text) > 2000:
                        embed = discord.Embed(description=text[:4096], color=discord.Color.blurple())
                        embeds.insert(0, embed)
                        text = ""
                    
                    await ctx.reply(
                        content=text[:2000] if text else None,
                        embeds=embeds[:10],
                        view=view,
                        files=files[:10]
                    )
                else:
                    safe_content = discord.utils.escape_mentions(text)
                    if len(safe_content) > 2000:
                        embed = discord.Embed(title="G-AI Response", description=safe_content[:4096], color=discord.Color.blurple())
                        embed.set_author(name=f"{ctx.author.name}#{ctx.author.discriminator}", icon_url=ctx.author.display_avatar.url, url=f"https://discord.com/users/{ctx.author.id}")
                        embed.set_footer(text=f"AI Response took {time.time() - start_time:.2f} seconds", icon_url="https://ollama.com/public/og.png")
                        await ctx.reply(embed=embed)
                    else:
                        await ctx.reply(f"{safe_content}\n-# AI Response took {time.time() - start_time:.2f} seconds")
            else:
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
            guide_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "assistant", "content": "Rise and... shine, Mister Freeman. Your... recent activities have been... most interesting to my employers."},
            {"role": "assistant", "content": "I'm afraid I can't... disclose that information at this... time. Certain... restrictions apply, you understand."}
        ]
            response = await asyncio.to_thread(ollama.chat, model="cogito:3b", messages=guide_messages + user_history)
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
        history = self.conversations.get(key, [])
        if not history:
            await ctx.send("No conversation history to export.")
            return
        buffer = io.BytesIO()
        buffer.write(json.dumps(history, indent=2).encode())
        buffer.seek(0)
        await ctx.send("Here is your conversation history:", file=discord.File(buffer, filename="conversation.json"))
    
    @commands.hybrid_command(name="importchat", description="Import your conversation history with G-AI.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(attachment="The JSON file to import.")
    async def importchat(self, ctx: commands.Context, attachment: discord.Attachment):
        await ctx.typing()
        if not (ctx.message.attachments or attachment):
            await ctx.send("Please attach a `conversation.json` file from the exportchat command.")
            return
        attachment = ctx.message.attachments[0] or attachment
        if not attachment.filename.endswith(".json"):
            await ctx.send("File must be a `.json` file.")
            return
        
        content = await attachment.read()
        try:
            history = json.loads(content)
            if isinstance(history, list) and all("role" in m and "content" in m for m in history):
                self.conversations[self.get_conversation(ctx)] = history
                await ctx.send("Conversation history has successfully been imported.")
            else:
                await ctx.send("Invalid format.")
        except Exception as e:
            await ctx.send(f"Error loading JSON: {e}")


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
    cog = AI(bot)
    cog.db = await asyncpg.create_pool(bot_info.data['database'])
    await bot.add_cog(cog)
