import asyncio
import io
import math
import random
import re
from datetime import datetime
from math import fmod

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw
from webcolors import hex_to_name, name_to_hex


class Info(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @staticmethod
    def parse_gradient_input(gradient_input):
        colors = []
        positions = []
        gradient_parts = gradient_input.split(",")
        for part in gradient_parts:
            match = re.match(r"(.+)\s+(\d+)%?", part.strip())
            if match:
                color, position = match.groups()
                colors.append(color.strip())
                positions.append(int(position))
            else:
                colors.append(part.strip())
                positions.append(None)

        total_colors = len(colors)
        if any(pos is None for pos in positions):
            auto_positions = [
                round(i * 100 / (total_colors - 1)) for i in range(total_colors)
            ]
            for i, pos in enumerate(positions):
                if pos is None:
                    positions[i] = auto_positions[i]

        return colors, positions

    def generate_gradient_image(
        self, colors, positions, width=800, height=100, background=(255, 255, 255)
    ):
        gradient = Image.new("RGBA", (width, height))
        draw = ImageDraw.Draw(gradient)
        positions = [round(pos * width / 100) for pos in positions]
        for i in range(len(colors) - 1):
            start_color = self.parse_color(colors[i])
            end_color = self.parse_color(colors[i + 1])
            start_x = positions[i]
            end_x = positions[i + 1]
            for x in range(start_x, end_x):
                factor = (x - start_x) / (end_x - start_x)
                r = round(start_color[0] + factor * (end_color[0] - start_color[0]))
                g = round(start_color[1] + factor * (end_color[1] - start_color[1]))
                b = round(start_color[2] + factor * (end_color[2] - start_color[2]))
                a = round(start_color[3] + factor * (end_color[3] - start_color[3]))
                blended_r = round(r * (a / 255) + background[0] * (1 - a / 255))
                blended_g = round(g * (a / 255) + background[1] * (1 - a / 255))
                blended_b = round(b * (a / 255) + background[2] * (1 - a / 255))
                draw.line([(x, 0), (x, height)], (blended_r, blended_g, blended_b, a))
        return gradient

    @staticmethod
    def parse_color(color_input):
        if color_input.startswith("#"):
            color_input = color_input.lstrip("#")
            if len(color_input) == 6:
                r, g, b = (
                    int(color_input[0:2], 16),
                    int(color_input[2:4], 16),
                    int(color_input[4:6], 16),
                )
                return r, g, b, 255
            elif len(color_input) == 8:
                r, g, b = (
                    int(color_input[0:2], 16),
                    int(color_input[2:4], 16),
                    int(color_input[4:6], 16),
                )
                a = int(color_input[6:8], 16)
                return r, g, b, a
        else:
            raise ValueError(f"Invalid color format: {color_input}")

    @staticmethod
    def hsl_to_rgb(h, s, ll):
        s /= 100
        ll /= 100
        c = (1 - abs(2 * ll - 1)) * s
        x = c * (1 - abs((h / 60) % 2 - 1))
        m = ll - c / 2

        if 0 <= h < 60:
            r, g, b = c, x, 0
        elif 60 <= h < 120:
            r, g, b = x, c, 0
        elif 120 <= h < 180:
            r, g, b = 0, c, x
        elif 180 <= h < 240:
            r, g, b = 0, x, c
        elif 240 <= h < 300:
            r, g, b = x, 0, c
        else:
            r, g, b = c, 0, x

        r = round((r + m) * 255)
        g = round((g + m) * 255)
        b = round((b + m) * 255)
        return r, g, b

    @staticmethod
    def hsv_to_rgb(h, s, v):
        s /= 100
        v /= 100
        c = v * s
        x = c * (1 - abs((h / 60) % 2 - 1))
        m = v - c

        if 0 <= h < 60:
            r, g, b = c, x, 0
        elif 60 <= h < 120:
            r, g, b = x, c, 0
        elif 120 <= h < 180:
            r, g, b = 0, c, x
        elif 180 <= h < 240:
            r, g, b = 0, x, c
        elif 240 <= h < 300:
            r, g, b = x, 0, c
        else:
            r, g, b = c, 0, x

        r = round((r + m) * 255)
        g = round((g + m) * 255)
        b = round((b + m) * 255)
        return r, g, b

    @staticmethod
    def cmyk_to_rgb(c, m, y, k):
        r = round((1 - c / 100) * (1 - k / 100) * 255)
        g = round((1 - m / 100) * (1 - k / 100) * 255)
        b = round((1 - y / 100) * (1 - k / 100) * 255)
        return r, g, b

    @staticmethod
    def hex_to_rgba(hex_color: str):
        hex_color = hex_color.lstrip("#")
        r, g, b = tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
        return r, g, b, 1.0

    @staticmethod
    def rgba_to_cmyk(r: int, g: int, b: int, a: float):
        if (r, g, b) == (0, 0, 0):
            return 0, 0, 0, 100
        c = 1 - r / 255
        m = 1 - g / 255
        y = 1 - b / 255
        k = min(c, m, y)
        c = (c - k) / (1 - k)
        m = (m - k) / (1 - k)
        y = (y - k) / (1 - k)
        return round(c * 100), round(m * 100), round(y * 100), round(k * 100)

    @staticmethod
    def rgba_to_hsl(r: int, g: int, b: int, a: float):
        r, g, b = r / 255, g / 255, b / 255
        max_val, min_val = max(r, g, b), min(r, g, b)
        ll = (max_val + min_val) / 2
        if max_val == min_val:
            h = s = 0
        else:
            d = max_val - min_val
            s = d / (2 - max_val - min_val) if ll > 0.5 else d / (max_val + min_val)
            if max_val == r:
                h = (g - b) / d + (6 if g < b else 0)
            elif max_val == g:
                h = (b - r) / d + 2
            elif max_val == b:
                h = (r - g) / d + 4
            h = fmod(h * 60, 360)
        return round(h), round(s * 100), round(ll * 100), round(a * 100)

    @staticmethod
    def rgba_to_hsv(r: int, g: int, b: int, a: float):
        r, g, b = r / 255, g / 255, b / 255
        max_val, min_val = max(r, g, b), min(r, g, b)
        v = max_val
        d = max_val - min_val
        s = 0 if max_val == 0 else d / max_val
        if max_val == min_val:
            h = 0
        else:
            if max_val == r:
                h = (g - b) / d + (6 if g < b else 0)
            elif max_val == g:
                h = (b - r) / d + 2
            elif max_val == b:
                h = (r - g) / d + 4
            h = fmod(h * 60, 360)
        return round(h), round(s * 100), round(v * 100), round(a * 100)

    @commands.hybrid_command(
        name="userinfo",
        aliases=["user", "member", "memberinfo"],
        description="Displays information about a user. Defaults to the author.",
    )
    @app_commands.describe(member="Member or user to get information out of.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def userinfo(self, ctx: commands.Context, *, member=None):
        await ctx.typing()
        member = member or ctx.author

        if not isinstance(member, (discord.Member, discord.User)):
            try:
                member = await commands.MemberConverter().convert(ctx, member)
            except commands.BadArgument:
                try:
                    member = await commands.UserConverter().convert(ctx, member)
                except commands.BadArgument:
                    await ctx.send(
                        "Could not find user. Please use an user ID instead."
                    )
                    return
        if isinstance(member, discord.Member) and ctx.guild:
            guild = ctx.guild
            if guild:
                try:
                    member = guild.get_member(member.id)
                except discord.NotFound:
                    pass

        user = await self.bot.fetch_user(member.id)
        embed = discord.Embed(
            title=f"User Info - {member.name}",
            color=getattr(member, "color", discord.Color.default()),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(
            url=member.display_avatar.url if member.avatar else member.default_avatar
        )
        embed.add_field(name="ID", value=member.id, inline=True)
        embed.add_field(name="Name", value=member.name, inline=True)
        embed.add_field(name="Bot?", value=member.bot, inline=True)
        embed.add_field(
            name="Joined Discord",
            value=member.created_at.strftime(
                "%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)"
            )
            if member.created_at
            else "Unknown",
            inline=True,
        )
        if isinstance(member, discord.Member) and ctx.guild:
            embed.add_field(name="Display Name", value=member.global_name, inline=True)
            embed.add_field(
                name="Nickname",
                value=member.nick if member.nick else "None",
                inline=True,
            )
            embed.add_field(name="Mention", value=member.mention, inline=True)
            embed.add_field(
                name="Joined Server",
                value=member.joined_at.strftime(
                    "%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)"
                )
                if member.joined_at
                else "Unknown",
                inline=True,
            )
            if ctx.guild:
                roles = [
                    role.mention
                    for role in member.roles
                    if role != ctx.guild.default_role
                ]
                embed.add_field(
                    name="Roles",
                    value=", ".join(roles) if roles else "None",
                    inline=False,
                )
                top_role = next(
                    (
                        role
                        for role in reversed(member.roles)
                        if role != ctx.guild.default_role
                    ),
                    None,
                )
                embed.add_field(
                    name="Top Role",
                    value=top_role.mention if top_role else "None",
                    inline=True,
                )
            if member.voice:
                embed.add_field(
                    name="Voice Channel",
                    value=f"{member.voice.channel.mention} | {member.voice.channel.name} ({member.voice.channel.id}) (Muted: {member.voice.self_mute} (Server Muted: {member.voice.mute}) | Deafened: {member.voice.self_deaf} (Server Deafened: {member.voice.deaf}) | Video: {member.voice.self_video} | Stream: {member.voice.self_stream})"
                    if member.voice.channel
                    else "None",
                    inline=True,
                )
            status_desktop = (
                member.desktop_status.name.capitalize()
                if isinstance(member.desktop_status, discord.Status)
                else str(member.desktop_status).capitalize()
            )
            status_mobile = (
                member.mobile_status.name.capitalize()
                if isinstance(member.mobile_status, discord.Status)
                else str(member.mobile_status).capitalize()
            )
            status_web = (
                member.web_status.name.capitalize()
                if isinstance(member.web_status, discord.Status)
                else str(member.web_status).capitalize()
            )

            status_value = (
                f"{member.status.name.capitalize()} "
                f"(Desktop: {status_desktop} | "
                f"Mobile: {status_mobile} | "
                f"Web: {status_web})"
            )
            embed.add_field(name="Status", value=status_value, inline=False)

            custom_status = None
            if member.activities:
                for activity in member.activities:
                    if isinstance(activity, discord.CustomActivity):
                        custom_status = (
                            f"{activity.emoji} {activity.name}"
                            if activity.emoji
                            else activity.name
                        )
                        break
            if custom_status:
                embed.add_field(name="Custom Status", value=custom_status, inline=False)

            if member.activities:
                for i, activity in enumerate(member.activities):
                    if isinstance(activity, discord.CustomActivity):
                        continue
                    activity_title = f"Activity {i + 1}: {activity.name}"
                    activity_details = []
                    if (
                        hasattr(activity, "type")
                        and activity.type != discord.ActivityType.custom
                    ):
                        activity_details.append(
                            f"Type: {activity.type.name.capitalize()}"
                        )
                    if hasattr(activity, "buttons") and activity.buttons:
                        activity_details.append(
                            f"Buttons: `{', '.join(activity.buttons)}`"
                        )
                    if hasattr(activity, "details") and activity.details:
                        activity_details.append(f"Details: {activity.details}")
                    if hasattr(activity, "state") and activity.state:
                        activity_details.append(f"State: {activity.state}")
                    if hasattr(activity, "start") and activity.start:
                        start_time = datetime.strftime(
                            activity.start, "%Y-%m-%d %H:%M:%S"
                        )
                        activity_details.append(f"Started: {start_time}")
                    if hasattr(activity, "end") and activity.end:
                        end_time = datetime.strftime(activity.end, "%Y-%m-%d %H:%M:%S")
                        activity_details.append(f"Ends: {end_time}")
                    if hasattr(activity, "application_id") and activity.application_id:
                        activity_details.append(f"App ID: {activity.application_id}")

                    if activity_details:
                        embed.add_field(
                            name=activity_title,
                            value="\n".join(activity_details),
                            inline=False,
                        )
        if hasattr(user, "accent_color") and user.accent_color:
            embed.add_field(
                name="Banner Color",
                value=f"{user.accent_color} rgb{user.accent_color.to_rgb()}",
                inline=True,
            )
        avatar_urls = []
        if member.avatar:
            avatar_urls.append(f"[Avatar URL]({member.avatar.url})")
        if hasattr(member, "display_avatar") and member.display_avatar != member.avatar:
            avatar_urls.append(f"[Guild Avatar URL]({member.display_avatar.url})")
        avatar_str = " | ".join(avatar_urls) if avatar_urls else "None"

        banner_str = "None"
        banner_url = None
        if hasattr(user, "banner") and user.banner:
            banner_global_url = user.banner.url
            banner_str = f"[Banner URL]({banner_global_url})"
            banner_url = banner_global_url
        if (
            isinstance(member, discord.Member)
            and hasattr(member, "display_banner")
            and member.display_banner
        ):
            banner_guild_url = member.display_banner.url
            if banner_guild_url != banner_global_url:
                banner_str += f" | [Guild Banner URL]({banner_guild_url})"
                banner_url = banner_guild_url

        embed.add_field(
            name="URLs",
            value=f"**Avatar:** {avatar_str}\n**Banner:** {banner_str}",
            inline=False,
        )
        if banner_url:
            embed.set_image(url=banner_url)
        embed.set_author(
            name=f"{member.name}#{member.discriminator}",
            icon_url=member.display_avatar.url,
            url=f"https://discord.com/users/{member.id}",
        )
        embed.set_footer(
            text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="serverinfo",
        aliases=["server", "guild", "guildinfo"],
        description="Displays information about a server. Defaults to the current server.",
    )
    @app_commands.describe(guild="The server to get information out of.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def serverinfo(self, ctx: commands.Context, *, guild: discord.Guild = None):
        if guild is None:
            guild = ctx.guild
        else:
            guild = discord.utils.get(self.bot.guilds, id=guild.id)
        embed = discord.Embed(
            title=f"Server Info - {guild.name}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
        embed.add_field(name="ID", value=guild.id, inline=True)
        embed.add_field(
            name="Owner",
            value=guild.owner.mention if guild.owner else "Unknown",
            inline=True,
        )
        embed.add_field(name="Owner ID", value=guild.owner_id, inline=True)
        embed.add_field(name="Description", value=guild.description, inline=False)
        embed.add_field(
            name="Verification Level",
            value=str(guild.verification_level).capitalize(),
            inline=True,
        )
        embed.add_field(
            name="NSFW Level",
            value=f"{guild.nsfw_level.name} ({guild.nsfw_level.value})",
            inline=True,
        )
        embed.add_field(
            name="Created At",
            value=guild.created_at.strftime(
                "%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)"
            ),
            inline=True,
        )
        embed.add_field(
            name="Members", value=f"{guild.member_count} members", inline=True
        )
        embed.add_field(
            name="Channels", value=f"{len(guild.channels)} total", inline=True
        )
        embed.add_field(
            name="Text Channels", value=f"{len(guild.text_channels)} text", inline=True
        )
        embed.add_field(
            name="Voice Channels",
            value=f"{len(guild.voice_channels)} voice",
            inline=True,
        )
        embed.add_field(
            name="Categories", value=f"{len(guild.categories)} categories", inline=True
        )
        embed.add_field(name="Emojis", value=f"{len(guild.emojis)} emojis", inline=True)
        embed.add_field(
            name="Stickers", value=f"{len(guild.stickers)} stickers", inline=True
        )
        embed.add_field(name="Roles", value=f"{len(guild.roles)} roles", inline=True)
        embed.add_field(name="Boost Tier", value=guild.premium_tier, inline=True)
        embed.add_field(
            name="Boosts",
            value=f"{guild.premium_subscription_count} boosts",
            inline=True,
        )
        embed.set_author(
            name=guild.name,
            icon_url=guild.icon.url if guild.icon else None,
            url=f"https://discord.com/channels/{guild.id}",
        )
        embed.set_footer(
            text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="channelinfo",
        aliases=["channel"],
        description="Displays information about a text channel. Defaults to the current channel.",
    )
    @app_commands.describe(channel="The text channel to get information out of.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def channelinfo(
        self, ctx: commands.Context, *, channel: discord.TextChannel = None
    ):
        channel = channel or ctx.channel
        embed = discord.Embed(
            title=f"Channel Info - {channel.name}",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="ID", value=channel.id, inline=True)
        embed.add_field(name="Name", value=channel.name, inline=True)
        embed.add_field(name="Type", value=str(channel.type).capitalize(), inline=True)
        embed.add_field(
            name="Category",
            value=channel.category.name if channel.category else None,
            inline=True,
        )
        embed.add_field(
            name="Topic",
            value=channel.topic if channel.topic else "No topic",
            inline=False,
        )
        embed.add_field(
            name="Slowmode Delay",
            value=f"{channel.slowmode_delay} seconds"
            if channel.slowmode_delay
            else None,
            inline=True,
        )
        embed.add_field(name="NSFW?", value=channel.is_nsfw(), inline=True)
        embed.add_field(
            name="Permissions Synced?", value=channel.permissions_synced, inline=True
        )
        embed.add_field(
            name="Position",
            value=f"{channel.position}/{len(channel.guild.channels)}",
            inline=True,
        )
        embed.add_field(name="Members", value=len(channel.members), inline=False)
        embed.add_field(
            name="Last Message ID", value=channel.last_message_id, inline=True
        )
        embed.add_field(
            name="Last Message Timestamp",
            value=channel.last_message.created_at.strftime(
                "%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)"
            )
            if channel.last_message
            else None,
            inline=True,
        )
        embed.add_field(
            name="Created At",
            value=channel.created_at.strftime(
                "%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)"
            ),
            inline=True,
        )
        embed.set_author(
            name=channel.name,
            icon_url=channel.guild.icon.url if channel.guild.icon else None,
            url=f"https://discord.com/channels/{channel.guild.id}/{channel.id}",
        )
        embed.set_footer(
            text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="voiceinfo",
        aliases=["vc", "vcinfo", "voice"],
        description="Displays information about a voice channel. Defaults to the current voice channel the author is in.",
    )
    @app_commands.describe(channel="The voice channel to get information out of.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def voiceinfo(
        self, ctx: commands.Context, *, channel: discord.VoiceChannel = None
    ):
        if channel is None:
            if ctx.author.voice and ctx.author.voice.channel:
                channel = ctx.author.voice.channel
            else:
                await ctx.send(
                    "You are not in a voice channel. Please specify a voice channel instead."
                )
                return
        embed = discord.Embed(
            title=f"Voice Channel Info - {channel.name}",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="ID", value=channel.id, inline=True)
        embed.add_field(name="Name", value=channel.name, inline=True)
        embed.add_field(
            name="Category",
            value=channel.category.name if channel.category else "None",
            inline=True,
        )
        embed.add_field(
            name="Bitrate", value=f"{channel.bitrate // 1000} kbps", inline=True
        )
        embed.add_field(
            name="User Limit", value=channel.user_limit or "Unlimited", inline=True
        )
        embed.add_field(name="Region", value=channel.rtc_region, inline=True)
        embed.add_field(name="NSFW?", value=channel.is_nsfw(), inline=True)
        embed.add_field(
            name="Connected Members",
            value=", ".join([member.mention for member in channel.members]) or None,
            inline=False,
        )
        embed.add_field(
            name="Created At",
            value=channel.created_at.strftime(
                "%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)"
            ),
            inline=True,
        )
        embed.add_field(
            name="Permissions Synced?", value=channel.permissions_synced, inline=True
        )
        embed.add_field(
            name="Position",
            value=f"{channel.position}/{len(channel.guild.channels)}",
            inline=True,
        )
        embed.add_field(
            name="Last Message ID",
            value=channel.last_message_id if channel.last_message else None,
            inline=True,
        )
        embed.add_field(
            name="Last Message Timestamp",
            value=channel.last_message.created_at.strftime(
                "%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)"
            )
            if channel.last_message
            else None,
            inline=True,
        )
        embed.set_author(
            name=channel.name,
            icon_url=channel.members[0].display_avatar.url
            if channel.members
            else channel.guild.icon.url,
            url=f"https://discord.com/users/{channel.members[0].id}"
            if channel.members
            else f"https://discord.com/channels/{channel.guild.id}/{channel.id}",
        )
        embed.set_footer(
            text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="threadinfo",
        aliases=["thread"],
        description="Displays information about a text channel's thread.",
    )
    @app_commands.describe(
        thread="The discord channel thread to get information out of."
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    async def threadinfo(self, ctx: commands.Context, *, thread: discord.Thread):
        embed = discord.Embed(
            title=f"Thread Info - {thread.name}",
            color=discord.Color.purple(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="ID", value=thread.id, inline=True)
        embed.add_field(
            name="Owner",
            value=thread.owner.mention if thread.owner else "Unknown",
            inline=True,
        )
        embed.add_field(name="Message Count", value=thread.message_count, inline=True)
        embed.add_field(
            name="Created At",
            value=thread.created_at.strftime(
                "%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)"
            ),
            inline=True,
        )
        embed.add_field(name="Archived", value=thread.archived, inline=True)
        embed.set_author(
            name=thread.name,
            icon_url=thread.owner.display_avatar.url,
            url=f"https://discord.com/users/{thread.owner.id}",
        )
        embed.set_footer(
            text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="messageinfo",
        aliases=["msg", "message", "msginfo"],
        description="Displays information about a message.",
    )
    @app_commands.describe(message="The text message to get information out of.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def messageinfo(self, ctx: commands.Context, *, message: discord.Message):
        embed = discord.Embed(
            title=f"Message Info - {message.id}",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="ID", value=message.id, inline=True)
        embed.add_field(name="Author", value=message.author.mention, inline=True)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        embed.add_field(name="Content", value=message.content or None, inline=False)
        embed.add_field(
            name="Created At",
            value=message.created_at.strftime(
                "%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)"
            ),
            inline=True,
        )
        embed.add_field(
            name="Edited At",
            value=message.edited_at.strftime(
                "%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)"
            )
            if message.edited_at
            else None,
            inline=True,
        )
        embed.add_field(
            name="Attachments",
            value=", ".join([attachment.url for attachment in message.attachments])
            or None,
            inline=False,
        )
        embed_titles = []
        for e in message.embeds:
            if e.title:
                embed_titles.append(e.title)
            elif e.description:
                embed_titles.append(f"(Description: {e.description[:50]}...)")
            elif e.url:
                embed_titles.append(f"(URL: {e.url})")
            elif hasattr(e, "video") and e.video:
                embed_titles.append("(Video Embed)")
            elif hasattr(e, "image") and e.image:
                embed_titles.append("(Image Embed)")
            else:
                embed_titles.append("(Embed with no title)")
        embed.add_field(
            name="Embeds", value=", ".join(embed_titles) or None, inline=False
        )
        embed.add_field(
            name="Reactions",
            value=", ".join([reaction.emoji for reaction in message.reactions]) or None,
            inline=False,
        )
        embed.add_field(
            name="Mentions",
            value=", ".join([mention.mention for mention in message.mentions]) or None,
            inline=False,
        )
        embed.set_author(
            name=f"{message.author.name}#{message.author.discriminator}",
            icon_url=message.author.display_avatar.url,
            url=f"https://discord.com/channels/{message.guild.id}/{message.channel.id}/{message.id}",
        )
        embed.set_footer(
            text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="emojiinfo",
        aliases=["emoji"],
        description="Displays information about an emoji.",
    )
    @app_commands.describe(emoji="The server emoji to get information out of.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def emojiinfo(self, ctx: commands.Context, *, emoji: discord.Emoji):
        embed = discord.Embed(
            title=f"Emoji Info - {emoji.name}",
            color=discord.Color.dark_orange(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="ID", value=emoji.id, inline=True)
        embed.add_field(
            name="Type", value="Animated" if emoji.animated else "Static", inline=True
        )
        embed.add_field(
            name="Created At",
            value=emoji.created_at.strftime(
                "%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)"
            ),
            inline=True,
        )
        embed.add_field(
            name="Guild",
            value=emoji.guild.name if emoji.guild else "None",
            inline=False,
        )
        embed.set_thumbnail(url=emoji.url)
        embed.set_author(name=emoji.name, url=emoji.url, icon_url=emoji.url)
        embed.set_footer(
            text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="stickerinfo",
        aliases=["sticker"],
        description="Displays information about a sticker.",
    )
    @app_commands.describe(sticker="The server sticker to get information out of.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def stickerinfo(
        self, ctx: commands.Context, *, sticker: discord.GuildSticker
    ):
        embed = discord.Embed(
            title=f"Sticker Info - {sticker.name}",
            color=discord.Color.dark_green(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(name="ID", value=sticker.id, inline=True)
        embed.add_field(
            name="Guild",
            value=sticker.guild.name if sticker.guild else None,
            inline=True,
        )
        if sticker.description:
            embed.add_field(name="Description", value=sticker.description, inline=False)
        embed.add_field(
            name="Created At",
            value=sticker.created_at.strftime(
                "%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)"
            ),
            inline=True,
        )
        embed.set_image(url=sticker.url)
        embed.set_author(name=sticker.name, url=sticker.url, icon_url=sticker.url)
        embed.set_footer(
            text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
        )

        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="inviteinfo", description="Displays information about an invite code."
    )
    @app_commands.describe(
        invite="The discord server invite link to get information out of."
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    async def inviteinfo(self, ctx: commands.Context, *, invite: discord.Invite):
        embed = discord.Embed(
            title=f"Invite Info - {invite.code}",
            color=discord.Color.dark_purple(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Guild", value=invite.guild.name, inline=True)
        embed.add_field(name="Channel", value=invite.channel.name, inline=True)
        embed.add_field(
            name="Uses",
            value=f"{invite.uses}/{invite.max_uses}"
            if invite.max_uses
            else invite.uses,
            inline=True,
        )
        embed.add_field(
            name="Inviter",
            value=invite.inviter.mention if invite.inviter else "Unknown",
            inline=True,
        )
        embed.add_field(
            name="Temporary?",
            value="True" if invite.temporary else "False",
            inline=True,
        )
        embed.add_field(
            name="Expires At",
            value=invite.expires_at.strftime(
                "%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)"
            )
            if invite.expires_at
            else "Never",
            inline=True,
        )
        embed.add_field(
            name="Created At",
            value=invite.created_at.strftime(
                "%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)"
            )
            if invite.created_at
            else "Unknown",
            inline=True,
        )
        embed.set_thumbnail(url=invite.guild.icon.url if invite.guild.icon else None)
        embed.set_author(
            name=invite.code,
            url=invite.url,
            icon_url=invite.guild.icon.url if invite.guild.icon else None,
        )
        embed.set_footer(
            text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="permissions",
        aliases=["perms"],
        description="Displays a user's permissions in a channel. Defaults to the current channel and author.",
    )
    @app_commands.describe(
        member="The server member to get permission information.",
        channel="Optional text channel to get the permissions at.",
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    async def permissions(
        self,
        ctx: commands.Context,
        member: discord.Member = None,
        channel: discord.TextChannel = None,
    ):
        member = member or ctx.author
        channel = channel or ctx.channel
        perms = channel.permissions_for(member)
        permissions = [perm.replace("_", " ").title() for perm, value in perms if value]
        embed = discord.Embed(
            title=f"Permissions Info - {member} in {channel.name}",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(
            name="Permissions", value=", ".join(permissions) or None, inline=False
        )
        embed.set_author(
            name=f"{member.name}#{member.discriminator}",
            icon_url=member.display_avatar.url,
            url=f"https://discord.com/users/{member.id}",
        )
        embed.set_footer(
            text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="roleinfo",
        aliases=["role"],
        description="Displays information about a role. Defaults to the everyone role.",
    )
    @app_commands.describe(role="The server role to get information out of.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def roleinfo(self, ctx: commands.Context, *, role: discord.Role = None):
        role = role or ctx.guild.default_role
        embed = discord.Embed(
            title=f"Role Info - {role.name}",
            color=role.color,
            timestamp=discord.utils.utcnow(),
        )
        role_color = role.color.to_rgb()
        role_color_image = await asyncio.to_thread(
            Image.new, "RGB", (512, 512), role_color
        )
        buffer = io.BytesIO()
        await asyncio.to_thread(role_color_image.save, buffer, "PNG")
        buffer.seek(0)
        embed.add_field(name="ID", value=role.id, inline=True)
        embed.add_field(name="Name", value=role.name, inline=True)
        embed.add_field(name="Color", value=str(role.color), inline=True)
        embed.add_field(
            name="Mentionable", value="Yes" if role.mentionable else "No", inline=True
        )
        embed.add_field(
            name="Position", value=f"{role.position}/{len(role.guild.roles)}"
        )
        embed.add_field(
            name="Created At",
            value=role.created_at.strftime(
                "%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)"
            ),
            inline=True,
        )
        embed.add_field(
            name="Permissions",
            value=", ".join(
                perm[0].replace("_", " ").title()
                for perm in role.permissions
                if perm[1]
            )
            or "None",
            inline=False,
        )
        embed.set_author(name=role.name, icon_url="attachment://role_color.png")
        embed.set_footer(
            text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
        )
        await ctx.send(embed=embed, file=discord.File(buffer, "role_color.png"))

    @commands.hybrid_command(
        name="baninfo", description="Displays information about a banned user."
    )
    @commands.has_permissions(ban_members=True)
    @app_commands.describe(user="The banned user to get. ID only.")
    @app_commands.allowed_installs(guilds=True, users=False)
    async def baninfo(self, ctx: commands.Context, *, user: discord.User):
        ban_entry = await ctx.guild.fetch_ban(user)
        embed = discord.Embed(
            title=f"Ban Info - {user}",
            color=discord.Color.dark_red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Reason", value=ban_entry.reason or None, inline=False)
        embed.set_author(
            name=f"{user.name}#{user.discriminator}",
            icon_url=user.avatar.url,
            url=f"https://discord.com/users/{user.id}",
        )
        embed.set_footer(
            text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="botinfo", description="Displays information about the bot."
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def botinfo(self, ctx: commands.Context):
        embed = discord.Embed(
            title=f"Bot Info - {self.bot.user.name}",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="ID", value=self.bot.user.id, inline=True)
        embed.add_field(name="Servers", value=len(self.bot.guilds), inline=True)
        embed.add_field(
            name="Users", value=len(set(self.bot.get_all_members())), inline=True
        )
        embed.add_field(
            name="Developers",
            value="[nkrasn](https://github.com/nkrasn 'Original Developer.'), [MiniatureEge2006](https://github.com/MiniatureEge2006 'Current Developer.')",
            inline=True,
        )
        embed.add_field(
            name="Source Code",
            value="https://github.com/MiniatureEge2006/g-man",
            inline=True,
        )
        embed.set_thumbnail(url=self.bot.user.avatar.url)
        embed.set_author(
            name=f"{self.bot.user.name}#{self.bot.user.discriminator}",
            icon_url=self.bot.user.avatar.url,
            url=f"https://discord.com/users/{self.bot.user.id}",
        )
        embed.set_footer(
            text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
        )
        await ctx.send(embed=embed)

    @staticmethod
    async def _generate_map_image(
        lat: float,
        lon: float,
        zoom: int = 11,
        width: int = 600,
        height: int = 400,
    ) -> io.BytesIO:

        TILE_SIZE = 256

        def _deg_to_tile(lat_deg, lon_deg, z):
            lat_r = math.radians(lat_deg)
            n = 2**z
            x = (lon_deg + 180) / 360 * n
            y = (1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * n
            return x, y

        tx_f, ty_f = _deg_to_tile(lat, lon, zoom)

        cols = math.ceil(width / TILE_SIZE) + 2
        rows = math.ceil(height / TILE_SIZE) + 2
        tx0 = int(tx_f) - cols // 2
        ty0 = int(ty_f) - rows // 2

        cx_px = (tx_f - tx0) * TILE_SIZE
        cy_px = (ty_f - ty0) * TILE_SIZE

        left = int(cx_px - width / 2)
        top = int(cy_px - height / 2)

        canvas = await asyncio.to_thread(
            Image.new, "RGB", (cols * TILE_SIZE, rows * TILE_SIZE)
        )

        headers = {
            "User-Agent": "DiscordBot/1.0 (g-man; https://codeberg.org/MiniatureEge2006/g-man)"
        }
        n_tiles = 2**zoom

        async with aiohttp.ClientSession() as session:
            for row in range(rows):
                for col in range(cols):
                    tx = (tx0 + col) % n_tiles
                    ty = ty0 + row
                    if ty < 0 or ty >= n_tiles:
                        continue
                    tile_url = f"https://tile.openstreetmap.org/{zoom}/{tx}/{ty}.png"
                    async with session.get(tile_url, headers=headers) as resp:
                        if resp.status == 200:
                            tile_bytes = await resp.read()
                            tile_img = await asyncio.to_thread(
                                Image.open, io.BytesIO(tile_bytes)
                            )
                            canvas.paste(tile_img, (col * TILE_SIZE, row * TILE_SIZE))

        map_img = canvas.crop((left, top, left + width, top + height))

        draw = await asyncio.to_thread(ImageDraw.Draw, map_img)
        cx, cy = width // 2, height // 2
        r = 8
        draw.ellipse(
            [cx - r + 2, cy - r + 2, cx + r + 2, cy + r + 2], fill=(0, 0, 0, 120)
        )
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            fill=(220, 30, 30),
            outline=(255, 255, 255),
            width=2,
        )
        draw.line([(cx, cy - r - 6), (cx, cy + r + 6)], fill=(220, 30, 30), width=2)
        draw.line([(cx - r - 6, cy), (cx + r + 6, cy)], fill=(220, 30, 30), width=2)

        buf = io.BytesIO()
        await asyncio.to_thread(map_img.save, buf, "PNG")
        buf.seek(0)
        return buf

    @staticmethod
    def _wind_direction_label(deg: float) -> str:
        directions = [
            "N",
            "NNE",
            "NE",
            "ENE",
            "E",
            "ESE",
            "SE",
            "SSE",
            "S",
            "SSW",
            "SW",
            "WSW",
            "W",
            "WNW",
            "NW",
            "NNW",
        ]
        idx = round(deg / 22.5) % 16
        return directions[idx]

    @staticmethod
    def _wmo_description(code: int) -> tuple[str, str]:
        wmo_map = {
            0: ("Clear sky", "☀️"),
            1: ("Mainly clear", "🌤️"),
            2: ("Partly cloudy", "⛅"),
            3: ("Overcast", "☁️"),
            45: ("Fog", "🌫️"),
            48: ("Depositing rime fog", "🌫️"),
            51: ("Light drizzle", "🌦️"),
            53: ("Moderate drizzle", "🌦️"),
            55: ("Dense drizzle", "🌧️"),
            56: ("Light freezing drizzle", "🌨️"),
            57: ("Heavy freezing drizzle", "🌨️"),
            61: ("Slight rain", "🌧️"),
            63: ("Moderate rain", "🌧️"),
            65: ("Heavy rain", "🌧️"),
            66: ("Light freezing rain", "🌨️"),
            67: ("Heavy freezing rain", "🌨️"),
            71: ("Slight snowfall", "❄️"),
            73: ("Moderate snowfall", "❄️"),
            75: ("Heavy snowfall", "❄️"),
            77: ("Snow grains", "🌨️"),
            80: ("Slight rain showers", "🌦️"),
            81: ("Moderate rain showers", "🌧️"),
            82: ("Violent rain showers", "⛈️"),
            85: ("Slight snow showers", "🌨️"),
            86: ("Heavy snow showers", "🌨️"),
            95: ("Thunderstorm", "⛈️"),
            96: ("Thunderstorm with slight hail", "⛈️"),
            99: ("Thunderstorm with heavy hail", "⛈️"),
        }
        return wmo_map.get(code, ("Unknown conditions", "🌡️"))

    @commands.hybrid_command(
        name="weatherinfo",
        description="Displays information about the weather in a location.",
        aliases=["weather"],
    )
    @app_commands.describe(
        location="The location for which you want to know the weather."
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def weatherinfo(self, ctx: commands.Context, *, location: str):
        await ctx.typing()

        geocode_url = "https://geocoding-api.open-meteo.com/v1/search"
        geo_params = {"name": location, "count": 1, "language": "en", "format": "json"}

        async with aiohttp.ClientSession() as session:
            async with session.get(geocode_url, params=geo_params) as geo_response:
                if geo_response.status != 200:
                    await ctx.send(
                        f"Error: Geocoding service returned status {geo_response.status}."
                    )
                    return
                geo_data = await geo_response.json()

            results = geo_data.get("results")
            if not results:
                await ctx.send(
                    f"Error: Could not find any location matching **{location}**."
                )
                return

            place = results[0]
            lat = place["latitude"]
            lon = place["longitude"]
            city_name = place.get("name", location)
            country_name = place.get("country", "")
            country_code = place.get("country_code", "").upper()
            admin1 = place.get("admin1", "")
            timezone = place.get("timezone", "UTC")
            elevation_m = place.get("elevation", None)
            population = place.get("population", None)

            weather_url = "https://api.open-meteo.com/v1/forecast"
            weather_params = {
                "latitude": lat,
                "longitude": lon,
                "current": (
                    "temperature_2m,"
                    "relative_humidity_2m,"
                    "apparent_temperature,"
                    "is_day,"
                    "precipitation,"
                    "rain,"
                    "showers,"
                    "snowfall,"
                    "weather_code,"
                    "cloud_cover,"
                    "pressure_msl,"
                    "surface_pressure,"
                    "wind_speed_10m,"
                    "wind_direction_10m,"
                    "wind_gusts_10m,"
                    "visibility"
                ),
                "daily": (
                    "temperature_2m_max,"
                    "temperature_2m_min,"
                    "sunrise,"
                    "sunset,"
                    "uv_index_max,"
                    "precipitation_probability_max,"
                    "precipitation_sum,"
                    "wind_speed_10m_max"
                ),
                "timezone": timezone,
                "forecast_days": 1,
                "wind_speed_unit": "ms",
            }

            async with session.get(weather_url, params=weather_params) as w_response:
                if w_response.status != 200:
                    await ctx.send(
                        f"Error: Weather service returned status {w_response.status}."
                    )
                    return
                w_data = await w_response.json()

        cur = w_data.get("current", {})
        daily = w_data.get("daily", {})

        temp_c = cur.get("temperature_2m")
        temp_f = round(temp_c * 9 / 5 + 32, 1) if temp_c is not None else None
        feels_c = cur.get("apparent_temperature")
        feels_f = round(feels_c * 9 / 5 + 32, 1) if feels_c is not None else None
        humidity = cur.get("relative_humidity_2m")
        cloud_cover = cur.get("cloud_cover")
        pressure_msl = cur.get("pressure_msl")
        surface_pressure = cur.get("surface_pressure")
        wind_speed = cur.get("wind_speed_10m")
        wind_dir_deg = cur.get("wind_direction_10m")
        wind_gusts = cur.get("wind_gusts_10m")
        precipitation = cur.get("precipitation")
        rain = cur.get("rain")
        snowfall = cur.get("snowfall")
        visibility_m = cur.get("visibility")
        wmo_code = cur.get("weather_code", 0)
        is_day = cur.get("is_day", 1)
        current_time = cur.get("time", "")

        description, condition_emoji = self._wmo_description(wmo_code)
        wind_label = (
            self._wind_direction_label(wind_dir_deg)
            if wind_dir_deg is not None
            else "?"
        )
        visibility_km = (
            round(visibility_m / 1000, 1) if visibility_m is not None else None
        )

        def _first(lst):
            return lst[0] if lst else None

        temp_max_c = _first(daily.get("temperature_2m_max", []))
        temp_min_c = _first(daily.get("temperature_2m_min", []))
        temp_max_f = (
            round(temp_max_c * 9 / 5 + 32, 1) if temp_max_c is not None else None
        )
        temp_min_f = (
            round(temp_min_c * 9 / 5 + 32, 1) if temp_min_c is not None else None
        )
        sunrise_str = _first(daily.get("sunrise", []))
        sunset_str = _first(daily.get("sunset", []))
        uv_index_max = _first(daily.get("uv_index_max", []))
        precip_prob = _first(daily.get("precipitation_probability_max", []))
        precip_sum = _first(daily.get("precipitation_sum", []))
        wind_max_daily = _first(daily.get("wind_speed_10m_max", []))

        def uv_risk(uv):
            if uv is None:
                return "N/A"
            if uv < 3:
                return f"{uv} (Low)"
            if uv < 6:
                return f"{uv} (Moderate)"
            if uv < 8:
                return f"{uv} (High)"
            if uv < 11:
                return f"{uv} (Very High)"
            return f"{uv} (Extreme)"

        location_parts = [p for p in [city_name, admin1, country_name] if p]
        location_title = ", ".join(location_parts)

        maps_link = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"

        embed_color = discord.Color.blue() if is_day else discord.Color.dark_blue()

        embed = discord.Embed(
            title=f"{condition_emoji} Weather in {location_title}",
            url=maps_link,
            description=(
                f"**{description}**\n"
                f"**{temp_c}°C / {temp_f}°F** - feels like **{feels_c}°C / {feels_f}°F**\n"
                f"Updated: `{current_time}`"
            ),
            color=embed_color,
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="Temperature",
            value=(
                f"Current: **{temp_c}°C / {temp_f}°F**\n"
                f"Feels like: **{feels_c}°C / {feels_f}°F**\n"
                f"Today high: **{temp_max_c}°C / {temp_max_f}°F**\n"
                f"Today low: **{temp_min_c}°C / {temp_min_f}°F**"
            ),
            inline=True,
        )

        embed.add_field(
            name="Wind",
            value=(
                f"Speed: **{wind_speed} m/s**\n"
                f"Direction: **{wind_dir_deg}° ({wind_label})**\n"
                f"Gusts: **{wind_gusts} m/s**\n"
                f"Daily max: **{wind_max_daily} m/s**"
            ),
            inline=True,
        )

        embed.add_field(
            name="Atmosphere",
            value=(
                f"Humidity: **{humidity}%**\n"
                f"Cloud cover: **{cloud_cover}%**\n"
                f"Visibility: **{visibility_km} km**\n"
                f"Pressure (MSL): **{pressure_msl} hPa**\n"
                f"Surface pressure: **{surface_pressure} hPa**"
            ),
            inline=True,
        )

        embed.add_field(
            name="Precipitation",
            value=(
                f"Current: **{precipitation} mm**\n"
                f"Rain: **{rain} mm** | Snow: **{snowfall} cm**\n"
                f"Today total: **{precip_sum} mm**\n"
                f"Chance today: **{precip_prob}%**"
            ),
            inline=True,
        )

        embed.add_field(
            name="Sun & UV",
            value=(
                f"Sunrise: **{sunrise_str}**\n"
                f"Sunset: **{sunset_str}**\n"
                f"UV Index (max): **{uv_risk(uv_index_max)}**\n"
                f"Daylight: **{'Yes' if is_day else 'No'}**"
            ),
            inline=True,
        )

        pop_str = f"{population:,}" if population else "N/A"
        elev_str = f"{elevation_m} m" if elevation_m is not None else "N/A"
        embed.add_field(
            name="Location",
            value=(
                f"City: **{city_name}**\n"
                f"Region: **{admin1 or 'N/A'}**\n"
                f"Country: **{country_name} ({country_code})**\n"
                f"Coordinates: **[{lat}, {lon}]({maps_link})**\n"
                f"Elevation: **{elev_str}**\n"
                f"Population: **{pop_str}**\n"
                f"Timezone: **{timezone}**"
            ),
            inline=False,
        )

        embed.set_author(
            name=f"{ctx.author.name}#{ctx.author.discriminator}",
            icon_url=ctx.author.display_avatar.url,
            url=f"https://discord.com/users/{ctx.author.id}",
        )
        embed.set_footer(
            text="Open-Meteo API",
        )

        try:
            map_buf = await self._generate_map_image(
                lat, lon, zoom=11, width=600, height=400
            )
            map_file = discord.File(map_buf, filename="map.png")
            embed.set_image(url="attachment://map.png")
            await ctx.send(embed=embed, file=map_file)
        except Exception:
            await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="colorinfo",
        description="Displays information about a color. Defaults to a random color.",
        aliases=["color"],
    )
    @app_commands.describe(
        color="The color name or color code (HEX, RGB/A, HSL/A, HSV/A or CMYK)"
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def colorinfo(self, ctx: commands.Context, color: str = None):
        await ctx.typing()
        try:
            if color is None or color.lower() == "random":
                r = random.randint(0, 255)
                g = random.randint(0, 255)
                b = random.randint(0, 255)
                a = random.uniform(0, 1)
                hex_color = f"#{r:02x}{g:02x}{b:02x}"
            else:
                if color.startswith("#"):
                    if len(color) == 9:
                        hex_color = color
                        r = int(color[1:3], 16)
                        g = int(color[3:5], 16)
                        b = int(color[5:7], 16)
                        a = int(color[7:9], 16) / 255.0
                    elif len(color) == 7:
                        hex_color = color
                        r = int(color[1:3], 16)
                        g = int(color[3:5], 16)
                        b = int(color[5:7], 16)
                        a = 1.0
                    else:
                        raise ValueError(f"Invalid color format: {color}")

                elif color.lower().startswith("rgba("):
                    rgba_values = list(map(float, re.findall(r"\d+\.?\d*", color)))
                    r, g, b, a = rgba_values
                    hex_color = f"#{int(r):02x}{int(g):02x}{int(b):02x}"
                elif color.lower().startswith("rgb("):
                    rgb_values = list(map(int, re.findall(r"\d+", color)))
                    r, g, b = rgb_values
                    a = 1.0
                    hex_color = f"#{r:02x}{g:02x}{b:02x}"
                elif color.lower().startswith("hsla("):
                    hsla_values = list(map(float, re.findall(r"\d+\.?\d*", color)))
                    h, s, h, a = hsla_values
                    r, g, b = self.hsl_to_rgb(h, s, h)
                    hex_color = f"#{r:02x}{g:02x}{b:02x}"
                elif color.lower().startswith("hsl("):
                    hsl_values = list(map(float, re.findall(r"\d+\.?\d*", color)))
                    h, s, h = hsl_values
                    a = 1.0
                    r, g, b = self.hsl_to_rgb(h, s, h)
                    hex_color = f"#{r:02x}{g:02x}{b:02x}"
                elif color.lower().startswith("hsva("):
                    hsva_values = list(map(float, re.findall(r"\d+\.?\d*", color)))
                    h, s, v, a = hsva_values
                    r, g, b = self.hsv_to_rgb(h, s, v)
                    hex_color = f"#{r:02x}{g:02x}{b:02x}"
                elif color.lower().startswith("hsv("):
                    hsv_values = list(map(float, re.findall(r"\d+\.?\d*", color)))
                    h, s, v = hsv_values
                    a = 1.0
                    r, g, b = self.hsv_to_rgb(h, s, v)
                    hex_color = f"#{r:02x}{g:02x}{b:02x}"
                elif color.lower().startswith("cmyka("):
                    cmyka_values = list(map(float, re.findall(r"\d+\.?\d*", color)))
                    c, m, y, k, a = cmyka_values
                    r, g, b = self.cmyk_to_rgb(c, m, y, k)
                    hex_color = f"#{r:02x}{g:02x}{b:02x}"
                elif color.lower().startswith("cmyk("):
                    cmyk_values = list(map(float, re.findall(r"\d+\.?\d*", color)))
                    c, m, y, k = cmyk_values
                    r, g, b = self.cmyk_to_rgb(c, m, y, k)
                    a = 1.0
                    hex_color = f"#{r:02x}{g:02x}{b:02x}"
                else:
                    hex_color = name_to_hex(color)
                    r, g, b, a = self.hex_to_rgba(hex_color)

            cmyk = self.rgba_to_cmyk(r, g, b, a)
            hsl = self.rgba_to_hsl(r, g, b, a)
            hsv = self.rgba_to_hsv(r, g, b, a)
            closest_name = None
            try:
                closest_name = hex_to_name(hex_color)
            except ValueError:
                closest_name = "Unknown"

            img = await asyncio.to_thread(
                Image.new, "RGBA", (100, 100), (int(r), int(g), int(b), int(a * 255))
            )
            buffer = io.BytesIO()
            await asyncio.to_thread(img.save, buffer, "PNG")
            buffer.seek(0)

            embed = discord.Embed(
                title=f"Color Info - {closest_name.capitalize()}",
                description=f"Details for the color `{color}`",
                color=int(hex_color[:7].lstrip("#"), 16),
            )
            embed.add_field(name="HEX", value=hex_color.upper(), inline=True)
            embed.add_field(
                name="RGB/A", value=f"({r}, {g}, {b}, {a:.2f})", inline=True
            )
            embed.add_field(
                name="CMYK",
                value=f"{cmyk[0]}%, {cmyk[1]}%, {cmyk[2]}%, {cmyk[3]}%",
                inline=True,
            )
            embed.add_field(
                name="HSL/A",
                value=f"{hsl[0]}°, {hsl[1]}%, {hsl[2]}%, {hsl[3]}%",
                inline=True,
            )
            embed.add_field(
                name="HSV/A",
                value=f"{hsv[0]}°, {hsv[1]}%, {hsv[2]}%, {hsv[3]}%",
                inline=True,
            )
            embed.set_thumbnail(url="attachment://color.png")
            embed.set_author(
                name=f"{ctx.author.name}#{ctx.author.discriminator}",
                icon_url=ctx.author.display_avatar.url,
                url=f"https://discord.com/users/{ctx.author.id}",
            )
            embed.set_footer(
                text=f"Color with HEX {hex_color}", icon_url="attachment://color.png"
            )
            await ctx.send(embed=embed, file=discord.File(buffer, "color.png"))
        except Exception as e:
            await ctx.send(
                f"Invalid color format. Please provide a valid color name or color code (HEX, RGB/A, HSL/A, HSV/A or CMYK).\nError: {e}"
            )

    @commands.hybrid_command(
        name="gradientinfo",
        description="Displays information about a gradient. Defaults to a random gradient.",
        aliases=["gradient"],
    )
    @app_commands.describe(
        colors="Comma-separated list of colors in HEX format with optional positions (e.g., '#FF0000 0%, #00FF00 50%, #0000FF 100%')"
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def gradientinfo(self, ctx: commands.Context, *, colors: str = None):
        await ctx.typing()
        try:
            if not colors or colors.lower() == "random":
                num_colors = random.randint(2, 10)
                colors = [
                    f"#{random.randint(0, 0xFFFFFF):06x}" for _ in range(num_colors)
                ]
                positions = sorted([random.randint(0, 100) for _ in range(num_colors)])
            else:
                colors, positions = self.parse_gradient_input(colors)
                if len(colors) > 10:
                    await ctx.send(
                        "You can only create a gradient with up to 10 colors."
                    )
                    return
            gradient = await asyncio.to_thread(
                self.generate_gradient_image, colors, positions
            )
            buffer = io.BytesIO()
            await asyncio.to_thread(gradient.save, buffer, "PNG")
            buffer.seek(0)

            embed = discord.Embed(
                title="Gradient Info",
                description="Details for the gradient",
                color=discord.Color.light_gray(),
            )
            embed.add_field(name="Colors", value="\n".join(colors), inline=True)
            embed.add_field(
                name="Positions",
                value="\n".join(f"{pos}%" for pos in positions),
                inline=True,
            )
            embed.set_image(url="attachment://gradient.png")
            embed.set_author(
                name=f"{ctx.author.name}#{ctx.author.discriminator}",
                icon_url=ctx.author.display_avatar.url,
                url=f"https://discord.com/users/{ctx.author.id}",
            )
            embed.set_footer(
                text=f"Gradient with {len(colors)} colors",
                icon_url="attachment://gradient.png",
            )
            await ctx.send(embed=embed, file=discord.File(buffer, "gradient.png"))
        except Exception as e:
            await ctx.send(
                f"Invalid color format. Please provide a valid HEX/A color code.\nError: {e}"
            )


async def setup(bot):
    await bot.add_cog(Info(bot))
