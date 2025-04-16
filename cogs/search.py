import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import yt_dlp
import re
from datetime import datetime

class Search(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    def run_yt_dlp_search(self, max_results: int, query: str):
        is_url = query.startswith("http://") or query.startswith("https://")
        if not is_url:
            query = f"ytsearch{max_results}:{query}"
        ydl_opts = {
            'skip_download': True,
            'default_search': f"ytsearch{max_results}",
            'noplaylist': True,
            'ignore_no_formats_error': True,
            'playlist_items': f"1:{max_results}",
            'quiet': True
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(query, download=False)
                entries = info.get("entries", [info])
            except Exception as e:
                raise commands.CommandError(f"An error occurred while searching: {e}")
        return entries
    
    def get_badges(self, entry):
        badges = []
        if entry.get("height"):
            if entry["height"] >= 4320:
                badges.append("8K (4320p)")
            elif entry["height"] >= 2160:
                badges.append("UHD (4K, 2160p)")
            elif entry["height"] >= 1440:
                badges.append("QHD (2K, 1440p)")
            elif entry["height"] >= 1080:
                badges.append("FHD (1080p)")
            elif entry["height"] >= 720:
                badges.append("HD (720p)")
        if entry.get("subtitles"):
            badges.append("Subtitles")
        if entry.get("is_live"):
            badges.append("Live")
        if entry.get("was_live"):
            badges.append("Was Live")
        if entry.get("duration"):
            if entry["duration"] >= 31536000:
                badges.append("...I don't care anymore. (A YEAR OR MORE IN LENGTH)")
            elif entry["duration"] >= 2592000:
                badges.append("... (A MONTH OR MORE IN LENGTH)")
            elif entry["duration"] >= 604800:
                badges.append("Do you really have anything better to do at this point? (A WEEK OR MORE IN LENGTH)")
            elif entry["duration"] >= 259200:
                badges.append("PLEASE, JUST DO SOMETHING ELSE!!! (THREE DAYS OR MORE IN LENGTH)")
            elif entry["duration"] >= 172800:
                badges.append("ARE YOU CRAZY? YOU CAN WATCH SOMETHING ELSE! (TWO DAYS OR MORE IN LENGTH)")
            elif entry["duration"] >= 86400:
                badges.append("INHUMANELY LONG (A DAY OR MORE IN LENGTH)")
            elif entry["duration"] >= 43200:
                badges.append("RIDICULOUSLY LONG (HALF A DAY OR MORE IN LENGTH)")
            elif entry["duration"] >= 21600:
                badges.append("EXTREMELY LONG (SIX HOURS OR MORE IN LENGTH)")
            elif entry["duration"] >= 9300:
                badges.append("Very Long")
            elif entry["duration"] >= 3600:
                badges.append("Long")
            elif entry["duration"] >= 1800:
                badges.append("Medium-Long Length")
            elif entry["duration"] >= 1200:
                badges.append("Medium Length")
            elif entry["duration"] >= 600:
                badges.append("Short-Medium Length")
            else:
                badges.append("Short Length")
        if entry.get("fps"):
            if entry["fps"] == 60:
                badges.append("60 FPS")
        
        return " • ".join(badges)
    

    def format_duration(self, seconds: int) -> str:
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02}:{seconds:02}"
        return f"{minutes}:{seconds:02}"


    def format_result_embed(self, entry, index, total):
        description = entry.get("description") or ""
        embed = discord.Embed(
            title=f"{entry.get('title', 'No Title')}",
            url=entry.get("webpage_url"),
            description=description[:4096],
            color=discord.Color.red()
        )
        uploader = entry.get("uploader", "Unknown")
        uploader_url = entry.get("uploader_url", None)
        embed.set_author(name=uploader, url=uploader_url)
        thumb = entry.get("thumbnail")
        if thumb:
            embed.set_image(url=thumb)
        
        if duration := entry.get("duration"):
            embed.add_field(name="Duration", value=self.format_duration(duration), inline=True)
        
        if views := entry.get("view_count"):
            embed.add_field(name="Views", value=f"{views:,}", inline=True)
        
        if likes := entry.get("like_count"):
            embed.add_field(name="Likes", value=f"{likes:,}", inline=True)
        
        if upload_date := entry.get("upload_date"):
            pretty_date = datetime.strptime(upload_date, "%Y%m%d").strftime("%B %d, %Y")
            embed.add_field(name="Upload Date", value=pretty_date, inline=True)
        
        if badges := self.get_badges(entry):
            embed.add_field(name="Badges", value=badges, inline=False)
        
        embed.set_footer(text=f"Result {index + 1}/{total}")
        return embed
    
    async def paginate_results(self, ctx: commands.Context, entries):

        class MediaNavView(discord.ui.View):
            def __init__(self, cog, entries):
                super().__init__(timeout=60)
                self.cog = cog
                self.message = None
                self.entries = entries
                self.current_page = 0
                self.total = len(entries)

            
            async def update(self, interaction: discord.Interaction = None):
                embed = self.cog.format_result_embed(self.entries[self.current_page], self.current_page, self.total)
                await (interaction.response.edit_message(embed=embed, view=self)
                       if interaction else self.message.edit(embed=embed, view=self))
            
            @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, row=0)
            async def first_page(self, interaction: discord.Interaction, button: discord.ui.Button):
                if self.current_page == 0:
                    await interaction.response.defer()
                    return
                self.current_page = 0
                await self.update(interaction)
            
            @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.primary, row=0)
            async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
                if self.current_page == 0:
                    await interaction.response.defer()
                    return
                if self.current_page > 0:
                    self.current_page -= 1
                    await self.update(interaction)
            
            @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.primary, row=0)
            async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
                if self.current_page == self.total - 1:
                    await interaction.response.defer()
                    return
                if self.current_page < self.total - 1:
                    self.current_page += 1
                    await self.update(interaction)
            
            @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, row=0)
            async def last_page(self, interaction: discord.Interaction, button: discord.ui.Button):
                if self.current_page == self.total - 1:
                    await interaction.response.defer()
                    return
                self.current_page = self.total - 1
                await self.update(interaction)
            
            @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.success, row=1)
            async def random_page(self, interaction: discord.Interaction, button: discord.ui.Button):
                new_page = random.randint(0, self.total - 1)
                if self.current_page == new_page:
                    await interaction.response.defer()
                    return
                self.current_page = new_page
                await self.update(interaction)
            
            @discord.ui.button(emoji="🔢", style=discord.ButtonStyle.primary, row=1)
            async def jump_to_page(self, interaction: discord.Interaction, button: discord.ui.Button):
                view = self
                class PageModal(discord.ui.Modal, title="Go to Page"):
                    page = discord.ui.TextInput(label="Page Number", placeholder=f"1 - {view.total}", required=True)
                    def __init__(self, outer_view):
                        super().__init__()
                        self.outer_view = outer_view

                    async def on_submit(inner_self, interaction: discord.Interaction):
                        try:
                            p = int(inner_self.page.value)
                            if 1 <= p <= view.total:
                                view.current_page = p - 1
                                await view.update(interaction)
                            else:
                                await interaction.response.send_message(f"Invalid page number. Please enter a number between 1 and {view.total}.", ephemeral=True)
                        except ValueError:
                            await interaction.response.send_message("Invalid input. Please enter a valid number.", ephemeral=True)
                
                await interaction.response.send_modal(PageModal(view))
            
            @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, row=2)
            async def hide_ui(self, interaction: discord.Interaction, button: discord.ui.Button):
                await interaction.response.edit_message(view=None)
                self.stop()
            
            @discord.ui.button(emoji="🗑️", style=discord.ButtonStyle.danger, row=2)
            async def delete_message(self, interaction: discord.Interaction, button: discord.ui.Button):
                await interaction.message.delete()
        
        view = MediaNavView(self, entries)
        embed = self.format_result_embed(entries[0], 0, len(entries))
        view.message = await ctx.send(embed=embed, view=view)
    

    @commands.hybrid_command(name="search", description="Search for YouTube.", aliases=["youtube", "yt"])
    @app_commands.describe(query="The search query for YouTube. Add --max N to return up to N results. (default 1, max 15)")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def search(self, ctx: commands.Context, *, query: str = ""):
        await ctx.typing()
        max_results = 1
        if "--max" in query:
            match = re.search(r"--max[ =]+(\d+)", query)
            if match:
                max_results = int(match.group(1))
                query = re.sub(r"--max[ =]+(\d+)", "", query).strip()
        max_results = max(1, min(max_results, 15))
        if not query:
            return await ctx.send("Please provide a search query.")
        
        try:
            entries = await asyncio.to_thread(self.run_yt_dlp_search, max_results, query)
        except Exception as e:
            raise commands.CommandError(f"An error occurred while searching: {e}")
        
        if not entries:
            return await ctx.send("No results found.")
        
        await self.paginate_results(ctx, entries)

async def setup(bot):
    await bot.add_cog(Search(bot))