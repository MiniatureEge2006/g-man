import discord
from discord.ext import commands
from discord import app_commands
import roblox
from roblox.utilities.iterators import SortOrder

class Roblox(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.client = roblox.Client()
    
    @commands.hybrid_command(name="ruserinfo", description="Get information about a Roblox user.", aliases=["ruser"])
    @app_commands.describe(user="The Roblox username or id of the user to get information about.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def ruserinfo(self, ctx: commands.Context, user):
        await ctx.typing()
        client = self.client
        try:
            if user.isdigit():
                user_info = await client.get_user(user)
            else:
                user_info = await client.get_user_by_username(user)
            user_thumbnails = await client.thumbnails.get_user_avatar_thumbnails(users=[user_info.id], type=roblox.thumbnails.AvatarThumbnailType.full_body, size=(420, 420))
            user_avatar = await client.thumbnails.get_user_avatar_thumbnails(users=[user_info.id], type=roblox.thumbnails.AvatarThumbnailType.headshot, size=(420, 420))
            embed = discord.Embed(title=f"Roblox User Info - {user_info.name}", color=0xFF0000, timestamp=discord.utils.utcnow())
            embed.add_field(name="ID", value=user_info.id, inline=True)
            embed.add_field(name="Display Name", value=user_info.display_name, inline=True)
            if user_info.username_history(sort_order=SortOrder.Descending) and not user_info.is_banned:
                embed.add_field(name="Past Usernames", value=", ".join(await user_info.username_history(sort_order=SortOrder.Descending).flatten()), inline=False)
            embed.add_field(name="Banned?", value=user_info.is_banned, inline=True)
            if user_info.description:
                embed.add_field(name="Description", value=user_info.description, inline=False)
            embed.add_field(name="Joined At", value=user_info.created.strftime("%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)"), inline=True)
            embed.add_field(name="Friends", value=await user_info.get_friend_count(), inline=True)
            embed.add_field(name="Followers", value=await user_info.get_follower_count(), inline=True)
            embed.add_field(name="Following", value=await user_info.get_following_count(), inline=True)
            embed.set_thumbnail(url=user_thumbnails[0].image_url)
            embed.set_author(name=user_info.name, url=f"https://www.roblox.com/users/{user_info.id}/profile", icon_url=user_avatar[0].image_url)
            embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
            await ctx.send(embed=embed)
        except roblox.RobloxException as e:
            raise commands.CommandError(f"Unable to find user {user}. Error: {e}")
    

    @commands.hybrid_command(name="rgameinfo", description="Get information about a Roblox game.", aliases=["rgame"])
    @app_commands.describe(game="The Roblox game id of the game to get information about. Not to be confused with the place id!")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def rgameinfo(self, ctx: commands.Context, game):
        await ctx.typing()
        client = self.client
        try:
            game_info = await client.get_universe(game)
            game_thumbnails = await client.thumbnails.get_universe_thumbnails(universes=[game_info.id], size=(768, 432))
            game_icons = await client.thumbnails.get_universe_icons(universes=[game_info.id], size=(50, 50))
            embed = discord.Embed(title=f"Roblox Game Info - {game_info.name}", color=0x0000FF, timestamp=discord.utils.utcnow())
            embed.add_field(name="ID", value=game_info.id, inline=True)
            embed.add_field(name="Description", value=game_info.description, inline=False)
            embed.add_field(name="Created At", value=game_info.created.strftime("%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)"))
            embed.add_field(name="Last Updated", value=game_info.updated.strftime("%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)"))
            embed.add_field(name="Creator", value=game_info.creator.name, inline=True)
            embed.add_field(name="Creator ID", value=game_info.creator.id, inline=True)
            embed.add_field(name="Creator Type", value=game_info.creator_type.name, inline=True)
            embed.add_field(name="Players Playing", value=game_info.playing, inline=True)
            embed.add_field(name="Max Players", value=game_info.max_players, inline=True)
            embed.add_field(name="Price", value=game_info.price, inline=True)
            embed.add_field(name="Favorites", value=game_info.favorited_count, inline=True)
            embed.set_image(url=game_thumbnails[0].thumbnails[0].image_url)
            embed.set_author(name=game_info.name, url=f"https://www.roblox.com/games/{game_info.root_place.id}", icon_url=game_icons[0].image_url)
            embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
            await ctx.send(embed=embed)
        except roblox.RobloxException as e:
            raise commands.CommandError(f"Unable to find game {game}. Error: {e}")

async def setup(bot):
    await bot.add_cog(Roblox(bot))
