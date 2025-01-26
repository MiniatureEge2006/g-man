import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import bot_info
import isodate
import random

YOUTUBE_API_KEY = bot_info.data['youtube_api_key']

class YouTube(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.hybrid_command(name="youtube", description="Search YouTube.", aliases=["yt"])
    @app_commands.describe(query="The query to search for.")
    @app_commands.user_install()
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def youtube(self, ctx: commands.Context, *, query: str):
        if ctx.interaction:
            await ctx.defer()
        else:
            await ctx.typing()
        search_url = "https://www.googleapis.com/youtube/v3/search"
        video_url = "https://www.googleapis.com/youtube/v3/videos"
        params = {
            "part": "snippet",
            "q": query,
            "type": "video,channel,playlist",
            "maxResults": 10,
            "key": YOUTUBE_API_KEY
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(search_url, params=params) as response:
                if response.status != 200:
                    await ctx.send("Failed to fetch YouTube search results.")
                    return
                data = await response.json()
                if not data.get("items"):
                    await ctx.send("No results found.")
                    return
                embeds = []
                for item in data["items"]:
                    snippet = item["snippet"]
                    kind = item["id"]["kind"]
                    if kind == "youtube#video":
                        video_id = item["id"]["videoId"]
                        video_params = {
                            "part": "contentDetails,statistics",
                            "id": video_id,
                            "key": YOUTUBE_API_KEY
                        }
                        async with session.get(video_url, params=video_params) as video_response:
                            if video_response.status != 200:
                                continue
                            video_data = await video_response.json()
                            video_details = video_data["items"][0]
                        title = snippet["title"]
                        url = f"https://www.youtube.com/watch?v={video_id}"
                        uploader = snippet["channelTitle"]
                        uploader_url = f"https://www.youtube.com/channel/{snippet['channelId']}"
                        publish_date = isodate.parse_datetime(snippet["publishedAt"])
                        formatted_date = publish_date.strftime("%B %d, %Y at %I:%M %p")
                        duration = isodate.parse_duration(video_details["contentDetails"]["duration"])
                        total_seconds = int(duration.total_seconds())
                        hours, remainder = divmod(total_seconds, 3600)
                        minutes, seconds = divmod(remainder, 60)
                        formatted_duration = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                        views = int(video_details["statistics"].get("viewCount", "0"))

                        embed = discord.Embed(
                            title=title,
                            url=url,
                            color=discord.Color.red(),
                            description=(
                                f"**Uploader:** [{uploader}]({uploader_url})\n"
                                f"**ID:** {video_id}\n"
                                f"**Published At:** {formatted_date}\n"
                                f"**Duration:** {formatted_duration}\n"
                                f"**Views:** {int(views):,}"
                            )
                        )
                        embed.set_image(url=f'{snippet["thumbnails"]["high"]["url"]}')
                        embed.set_author(name=f"{ctx.author.name}#{ctx.author.discriminator}", icon_url=ctx.author.display_avatar.url, url=f"https://discord.com/users/{ctx.author.id}")
                        embed.set_footer(text=f"YouTube search results for '{query}'")
                        embeds.append(embed)
                    elif kind == "youtube#channel":
                        title = snippet["title"]
                        channel_id = item["id"]["channelId"]
                        url = f"https://www.youtube.com/channel/{channel_id}"
                        subscriber_count = snippet.get("subscriberCount", 0)
                        description = snippet.get("description", "No description available.")

                        embed = discord.Embed(
                            title=title,
                            url=url,
                            color=discord.Color.blue(),
                            description=f"**Description:** {description[:200]}...\n**Subscribers:** {subscriber_count}"
                        )
                        embed.set_image(url=snippet["thumbnails"]["high"]["url"])
                        embed.set_author(name=f"{ctx.author.name}#{ctx.author.discriminator}", icon_url=ctx.author.display_avatar.url, url=f"https://discord.com/users/{ctx.author.id}")
                        embed.set_footer(text=f"YouTube search results for '{query}'")
                        embeds.append(embed)
                    elif kind == "youtube#playlist":
                        title = snippet["title"]
                        playlist_id = item["id"]["playlistId"]
                        url = f"https://www.youtube.com/playlist?list={playlist_id}"
                        uploader = snippet["channelTitle"]

                        embed = discord.Embed(
                            title=title,
                            url=url,
                            color=discord.Color.green(),
                            description=f"**Uploader:** {uploader}"
                        )
                        embed.set_image(url=snippet["thumbnails"]["high"]["url"])
                        embed.set_author(name=f"{ctx.author.name}#{ctx.author.discriminator}", icon_url=ctx.author.display_avatar.url, url=f"https://discord.com/users/{ctx.author.id}")
                        embed.set_footer(text=f"YouTube search results for '{query}'")
                        embeds.append(embed)
                
                class Paginator(discord.ui.View):
                    def __init__(self, embeds):
                        super().__init__()
                        self.embeds = embeds
                        self.current_page = 0
                    
                    async def update_embed(self, interaction: discord.Interaction):
                        embed = self.embeds[self.current_page]
                        await interaction.response.edit_message(embed=embed)
                    
                    @discord.ui.button(label="Previous", style=discord.ButtonStyle.primary)
                    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
                        if self.current_page > 0:
                            self.current_page -= 1
                            await self.update_embed(interaction)
                        
                    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
                    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
                        if self.current_page < len(self.embeds) - 1:
                            self.current_page += 1
                            await self.update_embed(interaction)
                    
                    @discord.ui.button(label="Shuffle", style=discord.ButtonStyle.primary)
                    async def shuffle(self, interaction: discord.Interaction, button: discord.ui.Button):
                        self.current_page = random.randint(0, len(self.embeds) - 1)
                        await self.update_embed(interaction)
                    
                    @discord.ui.button(label="Jump", style=discord.ButtonStyle.primary)
                    async def jump(self, interaction: discord.Interaction, button: discord.ui.Button):
                        class JumpView(discord.ui.Modal):
                            def __init__(self, paginator):
                                super().__init__(title="Jump to Page")
                                self.paginator = paginator
                                self.page_input = discord.ui.TextInput(
                                    label="Page Number",
                                    placeholder=f"Enter a number between 1 and {len(paginator.embeds)}",
                                    required=True
                                )
                                self.add_item(self.page_input)
                            
                            async def on_submit(self, interaction: discord.Interaction):
                                try:
                                    page = int(self.page_input.value)
                                    if 1 <= page <= len(self.paginator.embeds):
                                        self.paginator.current_page = page - 1
                                        await self.paginator.update_embed(interaction)
                                    else:
                                        await interaction.response.send_message("Invalid page number.", ephemeral=True)
                                except ValueError:
                                    await interaction.response.send_message("Invalid input. Please enter a number.", ephemeral=True)
                        
                        await interaction.response.send_modal(JumpView(self))
                    
                    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger)
                    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
                        await interaction.response.defer()
                        await interaction.message.delete()
                    
                    @discord.ui.button(label="Remove buttons", style=discord.ButtonStyle.danger)
                    async def remove_buttons(self, interaction: discord.Interaction, button: discord.ui.Button):
                        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=None)
                
                paginator = Paginator(embeds)
                await ctx.send(embed=embeds[0], view=paginator)

async def setup(bot):
    await bot.add_cog(YouTube(bot))