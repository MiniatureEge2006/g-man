import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
from typing import Optional, Dict, List
import asyncio
import random
import spotipy
import bot_info

class Search(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.search_prefixes = {
            'youtube': 'ytsearch',
            'soundcloud': 'scsearch',
            'spotify': 'spsearch',
            'yt': 'ytsearch',
            'sc': 'scsearch',
            'sp': 'spsearch',
        }
        self.active_searches: Dict[int, List[dict]] = {}
        self.spotify = None
        if bot_info.data['spotify_client_id'] and bot_info.data['spotify_client_secret']:
            self.spotify = spotipy.Spotify(
                auth_manager=spotipy.SpotifyClientCredentials(
                    client_id=bot_info.data['spotify_client_id'],
                    client_secret=bot_info.data['spotify_client_secret']
                )
            )
    
    async def search_platform(self, platform: str, query: str, max_results: int = 5) -> List[dict]:
        platform = platform.lower()

        if platform in ('spotify', 'sp') and self.spotify:
            return await self.search_spotify(query, max_results)
        
        prefix = self.search_prefixes.get(platform, 'ytsearch')
        search_query = f"{prefix}{max_results}:{query}"

        ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'noplaylist': True
        }
        try:
            def do_search():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    results = ydl.extract_info(search_query, download=False)
                    if not results:
                        return []
                    return results.get('entries', [])[:max_results]
            return await asyncio.to_thread(do_search)
        except Exception as e:
            print(f"Error during search: {e}")
            return []
    
    async def search_spotify(self, query: str, max_results: int) -> List[dict]:
        try:
            def do_spotify_search():
                results = self.spotify.search(q=query, type='track', limit=max_results)
                tracks = results.get('tracks', {}).get('items', [])

                formatted_results = []
                for track in tracks:
                    artists = ", ".join([artist['name'] for artist in track['artists']])
                    duration_ms = track.get('duration_ms', 0)
                    duration = duration_ms // 1000 if duration_ms else 0

                    formatted_results.append({
                        'title': f"{track['name']} - {artists}",
                        'url': track['external_urls']['spotify'],
                        'duration': duration,
                        'thumbnail': track['album']['images'][0]['url'] if track['album']['images'] else None,
                        'album': track['album']['name'],
                        'release_date': track['album']['release_date'],
                        'id': track['id']
                    })
                return formatted_results
            return await asyncio.to_thread(do_spotify_search)
        except Exception as e:
            print(f"Error during Spotify search: {e}")
            return []
    
    async def create_search_embed(self, platform: str, query: str, results: List[dict], page: int = 0, per_page: int = 1) -> discord.Embed:
        index = page * per_page
        if index >= len(results):
            return discord.Embed(title="No more results.", color=discord.Color.red())
        
        entry = results[index]
        title = entry.get('title', 'Unknown Title')
        url = entry.get('webpage_url', None)
        duration = entry.get('duration_string', 'Unknown Duration')
        thumbnail = entry.get('thumbnail') or (
            entry.get('thumbnails', [{}])[0].get('url') if entry.get('thumbnails') else None
        )
        uploader = entry.get('uploader', 'Unknown')
        uploader_url = entry.get('uploader_url', 'No URL')
        video_id = entry.get('id', 'Unknown')
        likes = entry.get('like_count', 0)
        views = entry.get('view_count', 0)
        concurrent_viewers = entry.get('concurrent_view_count', 0)
        badges = []
        height = entry.get('height')
        if height:
            if height >= 4320:
                badges.append("8K (4320p)")
            elif height >= 2160:
                badges.append("4K (2160p)")
            elif height >= 1440:
                badges.append("2K (1440p)")
            elif height >= 1080:
                badges.append("HD (1080p)")
        
        fps = entry.get('fps')
        if fps and fps >= 60:
            badges.append("60 FPS")
        
        if entry.get('dynamic_range') == 'HDR':
            badges.append("HDR")
        
        if entry.get('subtitles'):
            badges.append("Subtitles")
        elif entry.get('automatic_captions'):
            badges.append("Auto Captions")
        
        if entry.get('is_live'):
            badges.append("Live")
        
        if entry.get('live_status') == 'upcoming':
            badges.append("Premiere")
        
        total_pages = (len(results) + per_page - 1) // per_page
        embed = discord.Embed(
            title=title[:256],
            url=url,
            color=discord.Color.red() if platform == 'youtube' or 'yt' else discord.Color.orange() if platform == 'soundcloud' or 'sc' else discord.Color.green(),
        )
        if platform == 'spotify' or platform == 'sp':
            if entry.get('id'):
                embed.add_field(name="Track ID", value=entry['id'], inline=True)
            if entry.get('url'):
                embed.add_field(name="URL", value=entry['url'], inline=True)
            if isinstance(entry.get('duration'), int):
                duration = f"{entry['duration'] // 60}:{entry['duration'] % 60:02d}"
                embed.add_field(name="Duration", value=duration, inline=True)
            if entry.get('album'):
                embed.add_field(name="Album", value=entry['album'], inline=True)
            if entry.get('release_date'):
                embed.add_field(name="Release Date", value=entry['release_date'], inline=True)
        else:
            if video_id:
                embed.add_field(name="ID", value=video_id, inline=True)
            if badges:
                embed.add_field(name="Badges", value=", ".join(badges), inline=True)
            if duration:
                embed.add_field(name="Duration", value=duration, inline=True)
            if uploader:
                embed.add_field(name="Uploader", value=f"[{uploader}]({uploader_url})", inline=True)
            if likes:
                embed.add_field(name="Likes", value=f"{likes:,}", inline=True)
            if views:
                embed.add_field(name="Views", value=f"{views:,}", inline=True)
            if concurrent_viewers:
                embed.add_field(name="Concurrent Viewers", value=f"{concurrent_viewers:,}", inline=True)
        
        if thumbnail:
            embed.set_image(url=thumbnail)
        
        embed.set_footer(text=f"Page {page + 1}/{total_pages} | {len(results)} results")
        return embed

    
    @commands.hybrid_command(name="search", description="Search for media on various platforms.")
    @app_commands.describe(
        platform="Platform to search on (youtube, soundcloud, spotify).",
        query="Search query.",
        max_results="Maximum number of results to display. Default is 1, max can be 20.",
    )
    @app_commands.choices(
        platform=[
            app_commands.Choice(name="YouTube", value="youtube"),
            app_commands.Choice(name="SoundCloud", value="soundcloud"),
            app_commands.Choice(name="Spotify", value="spotify")
        ]
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def search(self, ctx: commands.Context, query: str, platform: Optional[str] = "youtube", max_results: Optional[int] = 1):
        await ctx.typing()
        max_results = min(max(1, max_results), 20)

        if platform.lower() not in self.search_prefixes:
            await ctx.send("Invalid platform. Please use `youtube`, `soundcloud`, or `spotify`.")
            return
        
        if platform.lower() in ('spotify', 'sp') and not self.spotify:
            await ctx.send("Spotify search is not configured.")
            return
        
        results = await self.search_platform(platform, query, max_results)

        if not results:
            return await ctx.send("No results found.")
        
        embed = await self.create_search_embed(platform, query, results)
        view = SearchPaginator(self, results, platform, query, ctx.author)

        message = await ctx.send(embed=embed, view=view)
        self.active_searches[message.id] = results
    
class SeekModal(discord.ui.Modal, title="Jump to Page"):
    page_num = discord.ui.TextInput(
        label="Page Number",
        placeholder="Enter a page number between 1 and ...",
        required=True
    )
    def __init__(self, max_page: int, paginator: discord.ui.View):
        super().__init__()
        self.max_page = max_page
        self.paginator = paginator
        self.page_num.placeholder = f"Enter a page number between 1 and {self.max_page}"
        
    async def on_submit(self, interaction: discord.Interaction):
        try:
            page = int(self.page_num.value) - 1
            if 0 <= page < self.max_page:
                self.paginator.page = page
                await self.paginator.update_embed(interaction)
            else:
                await interaction.response.send_message(f"Please enter a valid page number between 1 and {self.max_page}.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Invalid input. Please enter a number.", ephemeral=True)
        
class SearchPaginator(discord.ui.View):
    def __init__(self, cog: Search, results: List[dict], platform: str, query: str, author: discord.User, page: int = 0, per_page: int = 1):
        super().__init__(timeout=180)
        self.cog = cog
        self.results = results
        self.platform = platform
        self.query = query
        self.author = author
        self.page = page
        self.per_page = per_page
        self.total_pages = (len(results) + per_page - 1) // per_page
        self.update_buttons()
    
    def update_buttons(self):
        self.first_page.disabled = self.page == 0
        self.prev_page.disabled = self.page == 0
        self.next_page.disabled = self.page >= self.total_pages - 1
        self.last_page.disabled = self.page >= self.total_pages - 1
    
    async def update_embed(self, interaction: discord.Interaction):
        embed = await self.cog.create_search_embed(self.platform, self.query, self.results, self.page, self.per_page)
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, row=0)
    async def first_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            return await interaction.response.send_message("You can't control this search.", ephemeral=True)
        self.page = 0
        await self.update_embed(interaction)
    
    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.primary, row=0)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            return await interaction.response.send_message("You can't control this search.", ephemeral=True)
        self.page = max(0, self.page - 1)
        await self.update_embed(interaction)
    
    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.primary, row=0)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            return await interaction.response.send_message("You can't control this search.", ephemeral=True)
        self.page = min(self.total_pages - 1, self.page + 1)
        await self.update_embed(interaction)
    
    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, row=0)
    async def last_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            return await interaction.response.send_message("You can't control this search.", ephemeral=True)
        self.page = self.total_pages - 1
        await self.update_embed(interaction)
    
    @discord.ui.button(emoji="🔢", style=discord.ButtonStyle.primary, row=1)
    async def seek_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            return await interaction.response.send_message("You can't control this search.", ephemeral=True)
        await interaction.response.send_modal(SeekModal(self.total_pages, self))
    
    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.success, row=1)
    async def shuffle_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            return await interaction.response.send_message("You can't control this search.", ephemeral=True)
        self.page = random.randint(0, self.total_pages - 1)
        await self.update_embed(interaction)
    
    @discord.ui.button(emoji="🗑️", style=discord.ButtonStyle.danger, row=1)
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            return await interaction.response.send_message("You can't control this search.", ephemeral=True)
        await interaction.message.delete()
    
    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, row=1)
    async def hide_components(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            return await interaction.response.send_message("You can't control this search.", ephemeral=True)
        await interaction.response.edit_message(view=None)
        self.stop()
    
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if hasattr(self, 'message'):
            await self.message.edit(view=self)

async def setup(bot):
    await bot.add_cog(Search(bot))