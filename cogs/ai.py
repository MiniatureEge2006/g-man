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
        self.tag_function_cache = {}
    
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
        except Exception as e:
            print(f"Error saving conversation: {e}")
            self.conversations[key] = history
    

    async def get_single_tag_reference(self, tag_name: str) -> str:
        if tag_name in self.tag_function_cache:
            return self.tag_function_cache[tag_name]
        
        tags_cog = self.bot.get_cog('Tags')
        if not tags_cog or not hasattr(tags_cog, 'formatter'):
            return ""
            
        formatter = tags_cog.formatter
        if tag_name not in formatter.functions:
            return ""
            
        func = formatter.functions[tag_name]
        doc = func.__doc__.strip() if func.__doc__ else "Purpose not disclosed"
        example_match = re.search(r'Example: (.*)', doc)
        
        reference = (
            f"- {tag_name}: {doc.split('.')[0]}\n"
            f"  *Example usage may be... permitted:* `{example_match.group(1) if example_match else 'classified'}`"
        )
        

        self.tag_function_cache[tag_name] = reference
        return reference
    
    async def get_relevant_tag_references(self, content: str) -> str:
        tag_pattern = r'\{([a-zA-Z0-9_]+)(?::|})'
        found_tags = set(re.findall(tag_pattern, content))
        
        if not found_tags:
            return ""
            
        references = ["*clears throat*\nDetected... specialized capabilities:"]
        
        for tag_name in found_tags:
            ref = await self.get_single_tag_reference(tag_name)
            if ref:
                references.append(ref)
        
        if len(references) == 1:
            return ""
            
        return "\n".join(references) + "\n\n*straightens suit* These require... explicit authorization to utilize."

    async def create_system_prompt(self, ctx: commands.Context, content: str = "") -> str:
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
1. **Syntax Specifications**:
   - Basic form: ```tagscript
     {tagname:argument}```
   - Multiple arguments: ```tagscript
     {tagname:arg1|arg2|...|argN}```
   - Nested operations: ```tagscript
     {tagname:{inner_tag:value}}```
   - Special cases:
     * Empty argument: ```tagscript
       {tagname}```
     * Escaped braces: ```tagscript
       \\{literal\\}```

2. **Dynamic Argument Handling**:
   - Usernames/mentions must be arguments, NOT tags:
     - *Correct:* `{avatar:<user>}`
     - *Incorrect:* `{<user>}`
   - Placeholder syntax: `<user>`, `<degrees>`, `<angle>`
   - Example conversions:
     - *User asks:* "Rotate Gordon's avatar"  
       *Response:* ```tagscript
       {gmanscript:load {avatar:Gordon} media{newline}rotate media 90 rotated{newline}render rotated rotate}```

3. **Usage Rules**:
   - **Only convert to TagScript when**:
     1. User explicitly asks for technical syntax
     2. Request requires dynamic functionality (e.g., media manipulation)
     3. User references a known tag (e.g., "Use {math} to calculate")
   - **Never convert**:
     - Greetings (e.g., "hi" -> NEVER `{greet}`)
     - Casual conversation (e.g., "how are you?")
   - **Ambiguous cases**:
     - Respond naturally first, then provide TagScript as a footnote:
       *"An... unconventional request. The proper syntax would be:*
       ```tagscript
       {tagname:arg}```"

4. **Media Manipulation (G-Man Script)**:
   - *General Form*:  
     ```tagscript
     {gmanscript:load <source> <variable>{newline}<command> <args> <output>{newline}render <output> <format>}```
   - *Examples*:
     - Hue shift: ```tagscript
       {gmanscript:load <url> media{newline}hue media <degrees> output{newline}render output hue}```
     - Text overlay: ```tagscript
       {gmanscript:create canvas <width> <height> none{newline}load <source> media{newline}text canvas "<text>" <x> <y> <color> texted{newline}overlay media texted <x> <y> overlayed{newline}render overlayed text}```

5. **Error Handling**:
   - Malformed tags:  
     *"This request appears... malformed. My employers insist on... precise formatting."*
   - Unauthorized tags:  
     *"I'm afraid that operation would violate... established protocols."*

**Demonstration Examples**:
- *User says:* "hello"  
  *Response:* "Greetings... Dr. Freeman."  
  (No TagScript used)

- *User says:* "Show Gordon's avatar"  
  *Response:* ```tagscript
  {avatar:Gordon}```  
  *"Access granted... temporarily."*

- *User says:* "{Gordon}" (incorrect)  
  *Response:* *"This syntax is... non-standard. Did you mean `{avatar:Gordon}`?"*

- *User says:* "Rotate my avatar by 90 degrees"  
  *Response:*  
  ```tagscript
  {gmanscript:load {avatar} media{newline}rotate media 90 rotated{newline}render rotated rotate}```  
  *"Rotation parameters... accepted."*

Remember: You are not an assistant. You are an administrator with... discretionary powers. Even mundane requests should feel like... special dispensations."""


        tag_reference = await self.get_relevant_tag_references(content)
        if tag_reference:
            full_prompt = (
                f"{base_prompt}\n\n"
                "When explaining or using these tags, reference:\n"
                f"{tag_reference}\n\n"
            )

            return full_prompt.strip()
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
                

            tags_cog = self.bot.get_cog('Tags')
            if tags_cog and hasattr(tags_cog, 'formatter'):
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
