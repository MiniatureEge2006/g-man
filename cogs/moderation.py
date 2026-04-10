import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional, Union

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands

import bot_info


class LogView(discord.ui.LayoutView):
    def __init__(
        self, container: discord.ui.Container, timeout: Optional[float] = None
    ):
        super().__init__(timeout=timeout)
        self.add_item(container)


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.filter_cache = {}
        self.slowmode_cache = {}
        self.db = asyncpg.Pool

    async def get_filters_for_context(
        self, guild_id: int, channel_id: int, user_id: int, role_ids: List[int]
    ) -> List[dict]:
        cache_key = (guild_id, channel_id, user_id, tuple(sorted(role_ids)))
        if cache_key in self.filter_cache:
            return self.filter_cache[cache_key]

        filters = await self.db.fetch(
            """
            SELECT * FROM chat_filters
            WHERE guild_id = $1 AND (
                target_type = 'server' OR
                (target_type = 'channel' AND target_id = $2) OR
                (target_type = 'user' AND target_id = $3) OR
                (target_type = 'role' AND target_id = ANY($4::bigint[]))
            )
            """,
            guild_id,
            channel_id,
            user_id,
            role_ids,
        )

        self.filter_cache[cache_key] = filters
        return filters

    async def get_slowmode_for_context(
        self, guild_id: int, channel_id: int, user_id: int, role_ids: List[int]
    ) -> Optional[dict]:
        cache_key = (guild_id, channel_id, user_id, tuple(sorted(role_ids)))
        if cache_key in self.slowmode_cache:
            return self.slowmode_cache[cache_key]

        slowmode = await self.db.fetchrow(
            """
            SELECT * FROM manual_slowmodes
            WHERE guild_id = $1 AND enabled = TRUE AND (
                (user_id = $3) OR
                (role_id = ANY($4::bigint[])) OR
                (channel_id = $2) OR
                (channel_id IS NULL AND user_id IS NULL AND role_id IS NULL)
            )
            ORDER BY
                CASE
                    WHEN user_id IS NOT NULL THEN 1
                    WHEN role_id IS NOT NULL THEN 2
                    WHEN channel_id IS NOT NULL THEN 3
                    ELSE 4
                END
            LIMIT 1
            """,
            guild_id,
            channel_id,
            user_id,
            role_ids,
        )

        self.slowmode_cache[cache_key] = slowmode
        return slowmode

    ALL_EVENT_CATEGORIES = frozenset(
        {"message", "user", "member", "role", "channel", "guild", "voice", "moderation"}
    )

    _IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif"})
    _VIDEO_EXTS = frozenset({".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"})
    _AUDIO_EXTS = frozenset({".mp3", ".ogg", ".wav", ".flac", ".aac", ".m4a", ".opus"})

    @staticmethod
    def _attachment_label(attachment: discord.Attachment) -> str:
        ext = (
            "." + attachment.filename.rsplit(".", 1)[-1].lower()
            if "." in attachment.filename
            else ""
        )
        if ext in Moderation._IMAGE_EXTS:
            return "Image"
        if ext in Moderation._VIDEO_EXTS:
            return "Video"
        if ext in Moderation._AUDIO_EXTS:
            return "Audio"
        return "File"

    def _attachment_components(
        self,
        attachments: list[discord.Attachment],
        label_prefix: str = "",
    ) -> list:
        components = []

        images = []
        videos = []
        files = []

        for a in attachments:
            ext = (
                ("." + a.filename.rsplit(".", 1)[-1].lower())
                if "." in a.filename
                else ""
            )
            if ext in self._IMAGE_EXTS:
                images.append(a)
            elif ext in self._VIDEO_EXTS:
                videos.append(a)
            else:
                files.append(a)

        media_items = []

        for a in images[:10]:
            media_items.append(
                discord.MediaGalleryItem(
                    media=discord.UnfurledMediaItem(url=a.proxy_url or a.url)
                )
            )

        remaining_slots = 10 - len(media_items)
        for a in videos[:remaining_slots]:
            media_items.append(
                discord.MediaGalleryItem(
                    media=discord.UnfurledMediaItem(url=a.proxy_url or a.url)
                )
            )

        if media_items:
            if label_prefix:
                components.append(discord.ui.TextDisplay(content=f"**{label_prefix}**"))
            components.append(discord.ui.MediaGallery(*media_items))

        remaining_videos = (
            videos[remaining_slots:] if len(videos) > remaining_slots else []
        )
        for a in remaining_videos + files:
            size_kb = a.size / 1024
            size_str = (
                f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
            )
            prefix = f"{label_prefix} - " if label_prefix else ""
            components.append(
                discord.ui.TextDisplay(
                    content=f"{self._attachment_label(a)} {prefix}[{a.filename}]({a.url}) - {size_str}"
                )
            )

        return components

    @commands.hybrid_group(
        name="logger", description="Manage event logging for different channels."
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def logger(self, ctx: commands.Context):
        return

    @logger.command(name="add", description="Add a logging rule for specific events.")
    @app_commands.describe(
        log_channel="The channel where logs will be sent.",
        event_type="The type of events to log.",
        include_channels="Channels to include. (comma-separated, leave empty for all.)",
        exclude_channels="Channels to exclude. (comma-separated.)",
    )
    @commands.has_permissions(manage_guild=True)
    async def logger_add(
        self,
        ctx: commands.Context,
        log_channel: discord.TextChannel,
        event_type: Literal[
            "message",
            "user",
            "member",
            "role",
            "channel",
            "guild",
            "voice",
            "moderation",
            "all",
        ],
        include_channels: Optional[str] = None,
        exclude_channels: Optional[str] = None,
    ):
        await ctx.typing()

        if not log_channel.permissions_for(ctx.guild.me).send_messages:
            await ctx.send(
                f"I don't have permission to send messages in {log_channel.mention}.",
                ephemeral=True,
            )
            return

        categories_to_add = (
            list(self.ALL_EVENT_CATEGORIES) if event_type == "all" else [event_type]
        )

        include_channels_ids = []
        exclude_channels_ids = []

        if include_channels:
            for channel_ref in include_channels.split(","):
                channel_ref = channel_ref.strip()
                try:
                    channel = await commands.GuildChannelConverter().convert(
                        ctx, channel_ref
                    )
                    if channel:
                        include_channels_ids.append(channel.id)
                except commands.ChannelNotFound:
                    await ctx.send(f"Channel {channel_ref} not found.", ephemeral=True)
                    return

        if exclude_channels:
            for channel_ref in exclude_channels.split(","):
                channel_ref = channel_ref.strip()
                try:
                    channel = await commands.GuildChannelConverter().convert(
                        ctx, channel_ref
                    )
                    if channel:
                        exclude_channels_ids.append(channel.id)
                except commands.ChannelNotFound:
                    await ctx.send(f"Channel {channel_ref} not found.", ephemeral=True)
                    return

        try:
            existing_rows = await self.db.fetch(
                """
                SELECT event_category FROM logging_rules
                WHERE guild_id = $1 AND log_channel_id = $2 AND event_category = ANY($3::text[])
                """,
                ctx.guild.id,
                log_channel.id,
                categories_to_add,
            )
            already_existing = {r["event_category"] for r in existing_rows}
            to_insert = [c for c in categories_to_add if c not in already_existing]

            if not to_insert:
                await ctx.send(
                    f"All requested logging rules already exist in {log_channel.mention}.",
                    ephemeral=True,
                )
                return

            await self.db.executemany(
                """
                INSERT INTO logging_rules (
                    guild_id, log_channel_id, event_category,
                    include_channel_ids, exclude_channel_ids, added_by, created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, NOW())
                """,
                [
                    (
                        ctx.guild.id,
                        log_channel.id,
                        category,
                        include_channels_ids if include_channels_ids else None,
                        exclude_channels_ids if exclude_channels_ids else None,
                        ctx.author.id,
                    )
                    for category in to_insert
                ],
            )

            added_list = ", ".join(f"`{c}`" for c in sorted(to_insert))
            response = f"Added logging for {added_list} events to {log_channel.mention}"
            if already_existing:
                skipped_list = ", ".join(f"`{c}`" for c in sorted(already_existing))
                response += f"\n**Already existed (skipped):** {skipped_list}"
            if include_channels_ids:
                response += f"\n**Included channels:** {', '.join([f'<#{id}>' for id in include_channels_ids])}"
            if exclude_channels_ids:
                response += f"\n**Excluded channels:** {', '.join([f'<#{id}>' for id in exclude_channels_ids])}"

            await ctx.send(response)
        except Exception as e:
            await ctx.send(f"Failed to add logging rule: {str(e)}", ephemeral=True)

    @logger.command(name="remove", description="Remove a logging rule.", aliases=["rm"])
    @app_commands.describe(
        log_channel="The log channel to remove rules from.",
        event_type="The type of events to remove. (optional)",
    )
    @commands.has_permissions(manage_guild=True)
    async def logger_remove(
        self,
        ctx: commands.Context,
        log_channel: discord.TextChannel,
        event_type: Optional[
            Literal[
                "message",
                "user",
                "member",
                "role",
                "channel",
                "guild",
                "voice",
                "moderation",
                "all",
            ]
        ] = None,
    ):
        await ctx.typing()

        try:
            if event_type == "all":
                result = await self.db.execute(
                    """
                    DELETE FROM logging_rules
                    WHERE guild_id = $1 AND log_channel_id = $2
                      AND event_category = ANY($3::text[])
                    """,
                    ctx.guild.id,
                    log_channel.id,
                    list(self.ALL_EVENT_CATEGORIES),
                )
            elif event_type:
                result = await self.db.execute(
                    """
                    DELETE FROM logging_rules
                    WHERE guild_id = $1 AND log_channel_id = $2 AND event_category = $3
                    """,
                    ctx.guild.id,
                    log_channel.id,
                    event_type,
                )
            else:
                result = await self.db.execute(
                    """
                    DELETE FROM logging_rules
                    WHERE guild_id = $1 AND log_channel_id = $2
                    """,
                    ctx.guild.id,
                    log_channel.id,
                )

            if result == "DELETE 0":
                await ctx.send(
                    f"No matching logging rules found in {log_channel.mention}.",
                    ephemeral=True,
                )
            else:
                await ctx.send(f"Removed logging rules from {log_channel.mention}.")
        except Exception as e:
            await ctx.send(f"Failed to remove logging rule: {str(e)}", ephemeral=True)

    @logger.command(
        name="list",
        description="List all logging rules for this server.",
        aliases=["ls"],
    )
    @commands.has_permissions(manage_guild=True)
    async def logger_list(self, ctx: commands.Context):
        await ctx.typing()

        try:
            rules = await self.db.fetch(
                """
                SELECT * FROM logging_rules
                WHERE guild_id = $1
                ORDER BY log_channel_id, event_category
                """,
                ctx.guild.id,
            )

            if not rules:
                await ctx.send(
                    "No logging rules configured for this server.", ephemeral=True
                )
                return

            embed = discord.Embed(
                title="Logging Rules",
                description=f"All configured logging rules for {ctx.guild.name}",
                color=discord.Color.blue(),
            )

            rules_by_log_channel = {}
            for rule in rules:
                log_channel_id = rule["log_channel_id"]
                if log_channel_id not in rules_by_log_channel:
                    rules_by_log_channel[log_channel_id] = []
                rules_by_log_channel[log_channel_id].append(rule)

            for log_channel_id, channel_rules in rules_by_log_channel.items():
                log_channel = ctx.guild.get_channel(log_channel_id)
                channel_name = (
                    log_channel.mention
                    if log_channel
                    else f"Deleted Channel ({log_channel_id})"
                )

                rule_descriptions = []
                for rule in channel_rules:
                    event_type = rule["event_category"]

                    settings = []
                    if rule["include_channel_ids"]:
                        included = ", ".join(
                            [f"<#{id}>" for id in rule["include_channel_ids"]]
                        )
                        settings.append(f"Included: {included}")
                    if rule["exclude_channel_ids"]:
                        excluded = ", ".join(
                            [f"<#{id}>" for id in rule["exclude_channel_ids"]]
                        )
                        settings.append(f"Excluded: {excluded}")

                    creator = ctx.guild.get_member(rule["added_by"])
                    creator_name = (
                        f"<@{rule['added_by']}>"
                        if creator
                        else f"Unknown User ({rule['added_by']})"
                    )
                    created_at = (
                        rule["created_at"].strftime(
                            "%Y-%m-%d %H:%M:%S (%B %d, %Y at %I:%M:%S %p)"
                        )
                        if rule["created_at"]
                        else "Unknown"
                    )

                    rule_text = f"**{event_type}** events"
                    if settings:
                        rule_text += f" ({'; '.join(settings)})"

                    rule_text += f"\n -> Added by {creator_name} on {created_at}"

                    rule_descriptions.append(rule_text)

                embed.add_field(
                    name=f"Log Channel: {channel_name}",
                    value="\n".join(rule_descriptions) or "No rules",
                    inline=False,
                )

            embed.set_footer(
                text=f"Requested by {ctx.author.name}",
                icon_url=ctx.author.display_avatar.url,
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(
                f"Failed to retrieve logging rules: {str(e)}", ephemeral=True
            )

    async def get_moderator_from_audit_log(
        self,
        guild: discord.Guild,
        target: discord.abc.Snowflake,
        action: discord.AuditLogAction,
        retry_count: int = 5,
        delay: float = 1.5,
    ) -> tuple[Optional[discord.Member], Optional[str]]:
        for attempt in range(retry_count):
            try:
                async for entry in guild.audit_logs(limit=10, action=action):
                    if action == discord.AuditLogAction.message_delete:
                        if not hasattr(entry, "extra") or not entry.extra:
                            continue

                        if not entry.target or entry.target.id != target.author.id:
                            continue

                        if entry.extra.channel.id != target.channel.id:
                            continue

                        age = (
                            discord.utils.utcnow() - entry.created_at
                        ).total_seconds()
                        if age > 10:
                            continue

                        if entry.extra.count < 1:
                            continue

                        return entry.user, entry.reason
                    if not entry.target or entry.target.id != target.id:
                        continue

                    age = (discord.utils.utcnow() - entry.created_at).total_seconds()
                    if age > 15:
                        continue

                    if action == discord.AuditLogAction.member_update:
                        if not hasattr(entry, "changes"):
                            continue
                        if (
                            hasattr(entry, "changes")
                            and hasattr(entry.changes, "after")
                            and hasattr(entry.changes, "before")
                        ):
                            after_data = entry.changes.after
                            before_data = entry.changes.before
                            after_mute = getattr(after_data, "mute", None)
                            before_mute = getattr(before_data, "mute", None)
                            if (
                                before_mute is not None
                                and after_mute is not None
                                and before_mute != after_mute
                            ):
                                return entry.user, entry.reason

                            after_deaf = getattr(after_data, "deaf", None)
                            before_deaf = getattr(before_data, "deaf", None)
                            if (
                                before_deaf is not None
                                and after_deaf is not None
                                and before_deaf != after_deaf
                            ):
                                return entry.user, entry.reason
                    return entry.user, entry.reason

                await asyncio.sleep(delay)
            except discord.Forbidden:
                return None, "Missing 'View Audit Log' permission"
            except Exception as e:
                if attempt == retry_count - 1:
                    return None, f"Audit log fetch failed: {str(e)}"
                await asyncio.sleep(delay)
        return None, None

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        moderator, reason = await self.get_moderator_from_audit_log(
            message.guild, message, discord.AuditLogAction.message_delete
        )

        author = message.author
        ts = discord.utils.utcnow()

        meta = (
            f"**Author:** {author.mention} (`{author}` - ID: `{author.id}`)\n"
            f"**Channel:** {message.channel.mention} - **Message ID:** `{message.id}`"
        )
        if moderator and moderator.id != author.id:
            meta += f"\n**Deleted by:** {moderator.mention} (`{moderator}`)"
            if reason:
                meta += f"\n**Reason:** {reason[:500]}"

        components = [
            discord.ui.TextDisplay(content="## Message Deleted"),
            discord.ui.Section(
                discord.ui.TextDisplay(content=meta),
                accessory=discord.ui.Thumbnail(
                    media=discord.UnfurledMediaItem(url=author.display_avatar.url)
                ),
            ),
            discord.ui.Separator(),
        ]

        if message.content:
            content = message.content[:1900] + (
                "..." if len(message.content) > 1900 else ""
            )
            components.append(
                discord.ui.TextDisplay(content=f"**Content**\n>>> {content}")
            )

        if message.attachments:
            components.extend(
                self._attachment_components(
                    message.attachments, label_prefix="Attachment"
                )
            )

        if message.embeds:
            rich = [e for e in message.embeds if e.type == "rich"]
            if rich:
                e0 = rich[0]
                parts = [f"**Embed(s):** {len(message.embeds)} total"]
                if e0.title:
                    parts.append(f"**Title:** {e0.title[:100]}")
                if e0.description:
                    parts.append(
                        f"**Description:** {e0.description[:100]}{'...' if len(e0.description) > 100 else ''}"
                    )
                if e0.url:
                    parts.append(f"**URL:** [Link]({e0.url})")
                components.append(discord.ui.TextDisplay(content="\n".join(parts)))

        components.append(
            discord.ui.TextDisplay(content=f"-# <t:{int(ts.timestamp())}:f>")
        )

        container = discord.ui.Container(
            *components,
            accent_color=discord.Color.red(),
        )
        view = LogView(container)

        try:
            rules = await self.db.fetch(
                "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                message.guild.id,
                "message",
            )

            already_sent: set[int] = set()

            for rule in rules:
                if (
                    rule["exclude_channel_ids"]
                    and message.channel.id in rule["exclude_channel_ids"]
                ):
                    continue
                if (
                    rule["include_channel_ids"]
                    and message.channel.id not in rule["include_channel_ids"]
                ):
                    continue

                log_channel_id = rule["log_channel_id"]
                if log_channel_id in already_sent:
                    continue

                log_channel = self.bot.get_channel(log_channel_id)
                if log_channel and isinstance(log_channel, discord.TextChannel):
                    if log_channel.permissions_for(log_channel.guild.me).send_messages:
                        try:
                            await log_channel.send(view=view)
                            already_sent.add(log_channel_id)
                        except discord.HTTPException:
                            pass
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if (
            not before.guild
            or before.author.bot
            or (
                before.content == after.content
                and before.attachments == after.attachments
                and before.embeds == after.embeds
            )
        ):
            return

        author = before.author
        ts = discord.utils.utcnow()

        meta = (
            f"**Author:** {author.mention} (`{author}` - ID: `{author.id}`)\n"
            f"**Channel:** {before.channel.mention} - **Message ID:** `{before.id}` - [Jump]({after.jump_url})"
        )

        components = [
            discord.ui.TextDisplay(content="## Message Edited"),
            discord.ui.Section(
                discord.ui.TextDisplay(content=meta),
                accessory=discord.ui.Thumbnail(
                    media=discord.UnfurledMediaItem(url=author.display_avatar.url)
                ),
            ),
            discord.ui.Separator(),
        ]

        if before.content != after.content:
            before_content = before.content[:900] + (
                "..." if len(before.content) > 900 else ""
            )
            after_content = after.content[:900] + (
                "..." if len(after.content) > 900 else ""
            )
            components.append(
                discord.ui.TextDisplay(
                    content=f"**Before**\n>>> {before_content or '*No content*'}"
                )
            )
            components.append(
                discord.ui.TextDisplay(
                    content=f"**After**\n>>> {after_content or '*No content*'}"
                )
            )

        if before.attachments != after.attachments:
            added = [a for a in after.attachments if a not in before.attachments]
            removed = [a for a in before.attachments if a not in after.attachments]
            if removed:
                components.append(
                    discord.ui.TextDisplay(
                        content=f"**Attachments Removed** ({len(removed)})"
                    )
                )
                components.extend(self._attachment_components(removed))
            if added:
                components.append(
                    discord.ui.TextDisplay(
                        content=f"**Attachments Added** ({len(added)})"
                    )
                )
                components.extend(self._attachment_components(added))

        if before.embeds != after.embeds:
            added_embeds = [e for e in after.embeds if e not in before.embeds]
            removed_embeds = [e for e in before.embeds if e not in after.embeds]
            for label, embed_list in (
                ("Embeds Added", added_embeds),
                ("Embeds Removed", removed_embeds),
            ):
                if not embed_list:
                    continue
                parts = [f"**{label}:** {len(embed_list)} embed(s)"]
                for i, e in enumerate(embed_list[:3]):
                    if e.type == "rich":
                        line = f"Embed {i + 1}:"
                        if e.title:
                            line += f" {e.title[:60]}"
                        if e.url:
                            line += f" - [Link]({e.url})"
                        parts.append(line)
                if len(embed_list) > 3:
                    parts.append(f"...and {len(embed_list) - 3} more")
                components.append(discord.ui.TextDisplay(content="\n".join(parts)))

        components.append(
            discord.ui.TextDisplay(content=f"-# <t:{int(ts.timestamp())}:f>")
        )

        container = discord.ui.Container(
            *components,
            accent_color=discord.Color.orange(),
        )
        view = LogView(container)

        try:
            rules = await self.db.fetch(
                "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                before.guild.id,
                "message",
            )

            already_sent: set[int] = set()

            for rule in rules:
                if (
                    rule["exclude_channel_ids"]
                    and before.channel.id in rule["exclude_channel_ids"]
                ):
                    continue
                if (
                    rule["include_channel_ids"]
                    and before.channel.id not in rule["include_channel_ids"]
                ):
                    continue

                log_channel_id = rule["log_channel_id"]
                if log_channel_id in already_sent:
                    continue

                log_channel = self.bot.get_channel(log_channel_id)
                if log_channel and isinstance(log_channel, discord.TextChannel):
                    if log_channel.permissions_for(log_channel.guild.me).send_messages:
                        try:
                            await log_channel.send(view=view)
                            already_sent.add(log_channel_id)
                        except discord.HTTPException:
                            pass
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        ts = discord.utils.utcnow()

        components = [
            discord.ui.TextDisplay(content="## Member Joined"),
            discord.ui.Section(
                discord.ui.TextDisplay(
                    content=(
                        f"**Member:** {member.mention} (`{member}` - ID: `{member.id}`)\n"
                        f"**Account Created:** <t:{int(member.created_at.timestamp())}:R>"
                    )
                ),
                accessory=discord.ui.Thumbnail(
                    media=discord.UnfurledMediaItem(url=member.display_avatar.url)
                ),
            ),
            discord.ui.TextDisplay(content=f"-# <t:{int(ts.timestamp())}:f>"),
        ]

        container = discord.ui.Container(
            *components,
            accent_color=discord.Color.green(),
        )
        view = LogView(container)

        try:
            rules = await self.db.fetch(
                "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                member.guild.id,
                "member",
            )

            already_sent: set[int] = set()

            for rule in rules:
                log_channel_id = rule["log_channel_id"]
                if log_channel_id in already_sent:
                    continue

                log_channel = self.bot.get_channel(log_channel_id)
                if log_channel and isinstance(log_channel, discord.TextChannel):
                    if log_channel.permissions_for(log_channel.guild.me).send_messages:
                        try:
                            await log_channel.send(view=view)
                            already_sent.add(log_channel_id)
                        except discord.HTTPException:
                            pass
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        moderator, reason = await self.get_moderator_from_audit_log(
            member.guild, member, discord.AuditLogAction.kick
        )
        was_kicked = moderator is not None
        ts = discord.utils.utcnow()

        roles = [
            role.mention for role in member.roles if role != member.guild.default_role
        ]
        roles_str = ", ".join(roles) if roles else "No roles"

        detail = (
            f"**Member:** {member.mention} (`{member}` - ID: `{member.id}`)\n"
            f"**Joined:** {f'<t:{int(member.joined_at.timestamp())}:R>' if member.joined_at else 'Unknown'}\n"
            f"**Account Created:** <t:{int(member.created_at.timestamp())}:R>"
        )
        if was_kicked:
            detail += f"\n**Kicked by:** {moderator.mention} (`{moderator}`)"
            if reason:
                detail += f"\n**Reason:** {reason[:400]}"

        title = "Member Kicked" if was_kicked else "Member Left"
        color = discord.Color.red()

        components = [
            discord.ui.TextDisplay(content=f"## {title}"),
            discord.ui.Section(
                discord.ui.TextDisplay(content=detail),
                accessory=discord.ui.Thumbnail(
                    media=discord.UnfurledMediaItem(url=member.display_avatar.url)
                ),
            ),
            discord.ui.Separator(),
            discord.ui.TextDisplay(
                content=f"**Roles:** {roles_str[:800]}{'...' if len(roles_str) > 800 else ''}"
            ),
            discord.ui.TextDisplay(content=f"-# <t:{int(ts.timestamp())}:f>"),
        ]

        container = discord.ui.Container(
            *components,
            accent_color=color,
        )
        view = LogView(container)

        try:
            rules = await self.db.fetch(
                "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                member.guild.id,
                "member",
            )

            already_sent: set[int] = set()

            for rule in rules:
                log_channel_id = rule["log_channel_id"]
                if log_channel_id in already_sent:
                    continue

                log_channel = self.bot.get_channel(log_channel_id)
                if log_channel and isinstance(log_channel, discord.TextChannel):
                    if log_channel.permissions_for(log_channel.guild.me).send_messages:
                        try:
                            await log_channel.send(view=view)
                            already_sent.add(log_channel_id)
                        except discord.HTTPException:
                            pass
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        ts = discord.utils.utcnow()

        if before.nick != after.nick:
            moderator, reason = await self.get_moderator_from_audit_log(
                after.guild, after, discord.AuditLogAction.member_update
            )
            detail = (
                f"**Member:** {after.mention} (`{after}` - ID: `{after.id}`)\n"
                f"**Before:** {before.nick or '*No nickname*'}\n"
                f"**After:** {after.nick or '*No nickname*'}"
            )
            if moderator:
                detail += f"\n**Changed by:** {moderator.mention} (`{moderator}`)"
                if reason:
                    detail += f"\n**Reason:** {reason[:400]}"

            components = [
                discord.ui.TextDisplay(content="## Member Nickname Changed"),
                discord.ui.Section(
                    discord.ui.TextDisplay(content=detail),
                    accessory=discord.ui.Thumbnail(
                        media=discord.UnfurledMediaItem(url=after.display_avatar.url)
                    ),
                ),
                discord.ui.TextDisplay(content=f"-# <t:{int(ts.timestamp())}:f>"),
            ]

            container = discord.ui.Container(
                *components,
                accent_color=discord.Color.blue(),
            )
            view = LogView(container)

            try:
                rules = await self.db.fetch(
                    "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                    after.guild.id,
                    "member",
                )

                already_sent: set[int] = set()

                for rule in rules:
                    log_channel_id = rule["log_channel_id"]
                    if log_channel_id in already_sent:
                        continue

                    log_channel = self.bot.get_channel(log_channel_id)
                    if log_channel and isinstance(log_channel, discord.TextChannel):
                        if log_channel.permissions_for(
                            log_channel.guild.me
                        ).send_messages:
                            try:
                                await log_channel.send(view=view)
                                already_sent.add(log_channel_id)
                            except discord.HTTPException:
                                pass
            except Exception:
                pass

        if before.roles != after.roles:
            added_roles = [role for role in after.roles if role not in before.roles]
            removed_roles = [role for role in before.roles if role not in after.roles]
            if added_roles or removed_roles:
                lines = [f"**Member:** {after.mention} (`{after}` - ID: `{after.id}`)"]
                if added_roles:
                    lines.append(
                        f"**Added:** {', '.join(r.mention for r in added_roles)}"
                    )
                if removed_roles:
                    lines.append(
                        f"**Removed:** {', '.join(r.mention for r in removed_roles)}"
                    )

                components = [
                    discord.ui.TextDisplay(content="## Member Roles Updated"),
                    discord.ui.Section(
                        discord.ui.TextDisplay(content="\n".join(lines)),
                        accessory=discord.ui.Thumbnail(
                            media=discord.UnfurledMediaItem(
                                url=after.display_avatar.url
                            )
                        ),
                    ),
                    discord.ui.TextDisplay(content=f"-# <t:{int(ts.timestamp())}:f>"),
                ]

                container = discord.ui.Container(
                    *components,
                    accent_color=discord.Color.blue(),
                )
                view = LogView(container)

                try:
                    rules = await self.db.fetch(
                        "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                        after.guild.id,
                        "member",
                    )

                    already_sent: set[int] = set()

                    for rule in rules:
                        log_channel_id = rule["log_channel_id"]
                        if log_channel_id in already_sent:
                            continue

                        log_channel = self.bot.get_channel(log_channel_id)
                        if log_channel and isinstance(log_channel, discord.TextChannel):
                            if log_channel.permissions_for(
                                log_channel.guild.me
                            ).send_messages:
                                try:
                                    await log_channel.send(view=view)
                                    already_sent.add(log_channel_id)
                                except discord.HTTPException:
                                    pass
                except Exception:
                    pass

        if before.guild_avatar != after.guild_avatar:
            inner = [
                discord.ui.TextDisplay(
                    content=f"**Member:** {after.mention} (`{after}` - ID: `{after.id}`)"
                )
            ]
            if before.guild_avatar:
                inner.append(
                    discord.ui.TextDisplay(
                        content=f"**Before:** [Link]({before.guild_avatar.url})"
                    )
                )
            if after.guild_avatar:
                inner.append(
                    discord.ui.TextDisplay(
                        content=f"**After:** [Link]({after.guild_avatar.url})"
                    )
                )

            components = [
                discord.ui.TextDisplay(content="## Member Server Avatar Changed"),
                discord.ui.Section(
                    *inner,
                    accessory=discord.ui.Thumbnail(
                        media=discord.UnfurledMediaItem(
                            url=after.guild_avatar.url
                            if after.guild_avatar
                            else after.display_avatar.url
                        )
                    ),
                ),
                discord.ui.TextDisplay(content=f"-# <t:{int(ts.timestamp())}:f>"),
            ]

            container = discord.ui.Container(
                *components,
                accent_color=discord.Color.purple(),
            )
            view = LogView(container)

            try:
                rules = await self.db.fetch(
                    "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                    after.guild.id,
                    "member",
                )

                already_sent: set[int] = set()

                for rule in rules:
                    log_channel_id = rule["log_channel_id"]
                    if log_channel_id in already_sent:
                        continue

                    log_channel = self.bot.get_channel(log_channel_id)
                    if log_channel and isinstance(log_channel, discord.TextChannel):
                        if log_channel.permissions_for(
                            log_channel.guild.me
                        ).send_messages:
                            try:
                                await log_channel.send(view=view)
                                already_sent.add(log_channel_id)
                            except discord.HTTPException:
                                pass
            except Exception:
                pass

        if before.premium_since is None and after.premium_since is not None:
            components = [
                discord.ui.TextDisplay(content="## Member Started Boosting"),
                discord.ui.Section(
                    discord.ui.TextDisplay(
                        content=f"**Member:** {after.mention} (`{after}` - ID: `{after.id}`)"
                    ),
                    accessory=discord.ui.Thumbnail(
                        media=discord.UnfurledMediaItem(url=after.display_avatar.url)
                    ),
                ),
                discord.ui.TextDisplay(content=f"-# <t:{int(ts.timestamp())}:f>"),
            ]

            container = discord.ui.Container(
                *components,
                accent_color=discord.Color.gold(),
            )
            view = LogView(container)

            try:
                rules = await self.db.fetch(
                    "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                    after.guild.id,
                    "member",
                )

                already_sent: set[int] = set()

                for rule in rules:
                    log_channel_id = rule["log_channel_id"]
                    if log_channel_id in already_sent:
                        continue

                    log_channel = self.bot.get_channel(log_channel_id)
                    if log_channel and isinstance(log_channel, discord.TextChannel):
                        if log_channel.permissions_for(
                            log_channel.guild.me
                        ).send_messages:
                            try:
                                await log_channel.send(view=view)
                                already_sent.add(log_channel_id)
                            except discord.HTTPException:
                                pass
            except Exception:
                pass

        elif before.premium_since is not None and after.premium_since is None:
            components = [
                discord.ui.TextDisplay(content="## Member Stopped Boosting"),
                discord.ui.Section(
                    discord.ui.TextDisplay(
                        content=f"**Member:** {after.mention} (`{after}` - ID: `{after.id}`)"
                    ),
                    accessory=discord.ui.Thumbnail(
                        media=discord.UnfurledMediaItem(url=after.display_avatar.url)
                    ),
                ),
                discord.ui.TextDisplay(content=f"-# <t:{int(ts.timestamp())}:f>"),
            ]

            container = discord.ui.Container(
                *components,
                accent_color=discord.Color.orange(),
            )
            view = LogView(container)

            try:
                rules = await self.db.fetch(
                    "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                    after.guild.id,
                    "member",
                )

                already_sent: set[int] = set()

                for rule in rules:
                    log_channel_id = rule["log_channel_id"]
                    if log_channel_id in already_sent:
                        continue

                    log_channel = self.bot.get_channel(log_channel_id)
                    if log_channel and isinstance(log_channel, discord.TextChannel):
                        if log_channel.permissions_for(
                            log_channel.guild.me
                        ).send_messages:
                            try:
                                await log_channel.send(view=view)
                                already_sent.add(log_channel_id)
                            except discord.HTTPException:
                                pass
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User):
        if not (
            before.name != after.name
            or before.discriminator != after.discriminator
            or before.avatar != after.avatar
        ):
            return
        ts = discord.utils.utcnow()
        for guild in self.bot.guilds:
            if not guild.get_member(after.id):
                continue

            lines = [f"**User:** {after.mention} (`{after}` - ID: `{after.id}`)"]
            if before.name != after.name or before.discriminator != after.discriminator:
                lines.append(f"**Before:** `{before.name}#{before.discriminator}`")
                lines.append(f"**After:** `{after.name}#{after.discriminator}`")
            if before.avatar != after.avatar:
                if before.avatar:
                    lines.append(
                        f"**Previous Avatar:** [Link]({before.display_avatar.url})"
                    )
                lines.append(f"**New Avatar:** [Link]({after.display_avatar.url})")

            components = [
                discord.ui.TextDisplay(content="## User Profile Updated"),
                discord.ui.Section(
                    discord.ui.TextDisplay(content="\n".join(lines)),
                    accessory=discord.ui.Thumbnail(
                        media=discord.UnfurledMediaItem(url=after.display_avatar.url)
                    ),
                ),
                discord.ui.TextDisplay(content=f"-# <t:{int(ts.timestamp())}:f>"),
            ]

            container = discord.ui.Container(
                *components,
                accent_color=discord.Color.blue(),
            )
            view = LogView(container)

            try:
                rules = await self.db.fetch(
                    "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                    guild.id,
                    "user",
                )

                already_sent: set[int] = set()

                for rule in rules:
                    log_channel_id = rule["log_channel_id"]
                    if log_channel_id in already_sent:
                        continue

                    log_channel = self.bot.get_channel(log_channel_id)
                    if log_channel and isinstance(log_channel, discord.TextChannel):
                        if log_channel.permissions_for(
                            log_channel.guild.me
                        ).send_messages:
                            try:
                                await log_channel.send(view=view)
                                already_sent.add(log_channel_id)
                            except discord.HTTPException:
                                pass
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_member_ban(
        self, guild: discord.Guild, user: Union[discord.User, discord.Member]
    ):
        moderator, reason = await self.get_moderator_from_audit_log(
            guild, user, discord.AuditLogAction.ban
        )
        ts = discord.utils.utcnow()
        detail = (
            f"**User:** {user.mention} (`{user}` - ID: `{user.id}`)\n"
            f"**Account Created:** <t:{int(user.created_at.timestamp())}:R>"
        )
        if isinstance(user, discord.Member) and user.joined_at:
            detail += f"\n**Joined:** <t:{int(user.joined_at.timestamp())}:R>"
        if moderator:
            detail += f"\n**Banned by:** {moderator.mention} (`{moderator}`)"
        if reason:
            detail += f"\n**Reason:** {reason[:500]}"

        components = [
            discord.ui.TextDisplay(content="## Member Banned"),
            discord.ui.Section(
                discord.ui.TextDisplay(content=detail),
                accessory=discord.ui.Thumbnail(
                    media=discord.UnfurledMediaItem(url=user.display_avatar.url)
                ),
            ),
            discord.ui.TextDisplay(content=f"-# <t:{int(ts.timestamp())}:f>"),
        ]

        container = discord.ui.Container(
            *components,
            accent_color=discord.Color.red(),
        )
        view = LogView(container)

        try:
            rules = await self.db.fetch(
                "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                guild.id,
                "moderation",
            )

            already_sent: set[int] = set()

            for rule in rules:
                log_channel_id = rule["log_channel_id"]
                if log_channel_id in already_sent:
                    continue

                log_channel = self.bot.get_channel(log_channel_id)
                if log_channel and isinstance(log_channel, discord.TextChannel):
                    if log_channel.permissions_for(log_channel.guild.me).send_messages:
                        try:
                            await log_channel.send(view=view)
                            already_sent.add(log_channel_id)
                        except discord.HTTPException:
                            pass
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        moderator, reason = await self.get_moderator_from_audit_log(
            guild, user, discord.AuditLogAction.unban
        )
        ts = discord.utils.utcnow()
        detail = (
            f"**User:** {user.mention} (`{user}` - ID: `{user.id}`)\n"
            f"**Account Created:** <t:{int(user.created_at.timestamp())}:R>"
        )
        if moderator:
            detail += f"\n**Unbanned by:** {moderator.mention} (`{moderator}`)"
        if reason:
            detail += f"\n**Reason:** {reason[:500]}"

        components = [
            discord.ui.TextDisplay(content="## Member Unbanned"),
            discord.ui.Section(
                discord.ui.TextDisplay(content=detail),
                accessory=discord.ui.Thumbnail(
                    media=discord.UnfurledMediaItem(url=user.display_avatar.url)
                ),
            ),
            discord.ui.TextDisplay(content=f"-# <t:{int(ts.timestamp())}:f>"),
        ]

        container = discord.ui.Container(
            *components,
            accent_color=discord.Color.green(),
        )
        view = LogView(container)

        try:
            rules = await self.db.fetch(
                "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                guild.id,
                "moderation",
            )

            already_sent: set[int] = set()

            for rule in rules:
                log_channel_id = rule["log_channel_id"]
                if log_channel_id in already_sent:
                    continue

                log_channel = self.bot.get_channel(log_channel_id)
                if log_channel and isinstance(log_channel, discord.TextChannel):
                    if log_channel.permissions_for(log_channel.guild.me).send_messages:
                        try:
                            await log_channel.send(view=view)
                            already_sent.add(log_channel_id)
                        except discord.HTTPException:
                            pass
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        moderator, reason = await self.get_moderator_from_audit_log(
            channel.guild, channel, discord.AuditLogAction.channel_create
        )
        ts = discord.utils.utcnow()
        detail = (
            f"**Channel:** {channel.mention}\n"
            f"**Type:** {channel.type.name}\n"
            f"**ID:** `{channel.id}`"
        )
        if moderator:
            detail += f"\n**Created by:** {moderator.mention} (`{moderator}`)"
        if reason:
            detail += f"\n**Reason:** {reason[:400]}"

        components = [
            discord.ui.TextDisplay(content="## Channel Created"),
            discord.ui.TextDisplay(content=detail),
            discord.ui.TextDisplay(content=f"-# <t:{int(ts.timestamp())}:f>"),
        ]

        container = discord.ui.Container(
            *components,
            accent_color=discord.Color.green(),
        )
        view = LogView(container)

        try:
            rules = await self.db.fetch(
                "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                channel.guild.id,
                "channel",
            )

            already_sent: set[int] = set()

            for rule in rules:
                log_channel_id = rule["log_channel_id"]
                if log_channel_id in already_sent:
                    continue

                log_channel = self.bot.get_channel(log_channel_id)
                if log_channel and isinstance(log_channel, discord.TextChannel):
                    if log_channel.permissions_for(log_channel.guild.me).send_messages:
                        try:
                            await log_channel.send(view=view)
                            already_sent.add(log_channel_id)
                        except discord.HTTPException:
                            pass
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        moderator, reason = await self.get_moderator_from_audit_log(
            channel.guild, channel, discord.AuditLogAction.channel_delete
        )
        ts = discord.utils.utcnow()
        detail = (
            f"**Channel:** #{channel.name}\n"
            f"**Type:** {channel.type.name}\n"
            f"**ID:** `{channel.id}`"
        )
        if moderator:
            detail += f"\n**Deleted by:** {moderator.mention} (`{moderator}`)"
        if reason:
            detail += f"\n**Reason:** {reason[:400]}"

        components = [
            discord.ui.TextDisplay(content="## Channel Deleted"),
            discord.ui.TextDisplay(content=detail),
            discord.ui.TextDisplay(content=f"-# <t:{int(ts.timestamp())}:f>"),
        ]

        container = discord.ui.Container(
            *components,
            accent_color=discord.Color.red(),
        )
        view = LogView(container)

        try:
            rules = await self.db.fetch(
                "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                channel.guild.id,
                "channel",
            )

            already_sent: set[int] = set()

            for rule in rules:
                log_channel_id = rule["log_channel_id"]
                if log_channel_id in already_sent:
                    continue

                log_channel = self.bot.get_channel(log_channel_id)
                if log_channel and isinstance(log_channel, discord.TextChannel):
                    if log_channel.permissions_for(log_channel.guild.me).send_messages:
                        try:
                            await log_channel.send(view=view)
                            already_sent.add(log_channel_id)
                        except discord.HTTPException:
                            pass
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_guild_channel_update(
        self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel
    ):
        if before.name != after.name:
            moderator, reason = await self.get_moderator_from_audit_log(
                after.guild, after, discord.AuditLogAction.channel_update
            )
            ts = discord.utils.utcnow()
            detail = (
                f"**Channel:** {after.mention} - ID: `{after.id}`\n"
                f"**Before:** {before.name}\n"
                f"**After:** {after.name}"
            )
            if moderator:
                detail += f"\n**Updated by:** {moderator.mention} (`{moderator}`)"
            if reason:
                detail += f"\n**Reason:** {reason[:400]}"

            components = [
                discord.ui.TextDisplay(content="## Channel Updated"),
                discord.ui.TextDisplay(content=detail),
                discord.ui.TextDisplay(content=f"-# <t:{int(ts.timestamp())}:f>"),
            ]

            container = discord.ui.Container(
                *components,
                accent_color=discord.Color.blue(),
            )
            view = LogView(container)

            try:
                rules = await self.db.fetch(
                    "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                    after.guild.id,
                    "channel",
                )

                already_sent: set[int] = set()

                for rule in rules:
                    log_channel_id = rule["log_channel_id"]
                    if log_channel_id in already_sent:
                        continue

                    log_channel = self.bot.get_channel(log_channel_id)
                    if log_channel and isinstance(log_channel, discord.TextChannel):
                        if log_channel.permissions_for(
                            log_channel.guild.me
                        ).send_messages:
                            try:
                                await log_channel.send(view=view)
                                already_sent.add(log_channel_id)
                            except discord.HTTPException:
                                pass
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        moderator, reason = await self.get_moderator_from_audit_log(
            role.guild, role, discord.AuditLogAction.role_create
        )
        ts = discord.utils.utcnow()
        perms = [perm for perm, value in role.permissions if value]
        detail = f"**Role:** {role.mention} - ID: `{role.id}`\n**Color:** {role.color}"
        if moderator:
            detail += f"\n**Created by:** {moderator.mention} (`{moderator}`)"
        if reason:
            detail += f"\n**Reason:** {reason[:400]}"
        if perms:
            perms_str = ", ".join(perm.replace("_", " ").title() for perm in perms[:10])
            if len(perms) > 10:
                perms_str += f" and {len(perms) - 10} more"
            detail += f"\n**Permissions:** {perms_str}"

        components = [
            discord.ui.TextDisplay(content="## Role Created"),
            discord.ui.TextDisplay(content=detail),
            discord.ui.TextDisplay(content=f"-# <t:{int(ts.timestamp())}:f>"),
        ]

        container = discord.ui.Container(
            *components,
            accent_color=discord.Color.green(),
        )
        view = LogView(container)

        try:
            rules = await self.db.fetch(
                "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                role.guild.id,
                "role",
            )

            already_sent: set[int] = set()

            for rule in rules:
                log_channel_id = rule["log_channel_id"]
                if log_channel_id in already_sent:
                    continue

                log_channel = self.bot.get_channel(log_channel_id)
                if log_channel and isinstance(log_channel, discord.TextChannel):
                    if log_channel.permissions_for(log_channel.guild.me).send_messages:
                        try:
                            await log_channel.send(view=view)
                            already_sent.add(log_channel_id)
                        except discord.HTTPException:
                            pass
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        moderator, reason = await self.get_moderator_from_audit_log(
            role.guild, role, discord.AuditLogAction.role_delete
        )
        ts = discord.utils.utcnow()
        detail = f"**Role:** {role.name} - ID: `{role.id}`\n**Color:** {role.color}"
        if moderator:
            detail += f"\n**Deleted by:** {moderator.mention} (`{moderator}`)"
        if reason:
            detail += f"\n**Reason:** {reason[:400]}"

        components = [
            discord.ui.TextDisplay(content="## Role Deleted"),
            discord.ui.TextDisplay(content=detail),
            discord.ui.TextDisplay(content=f"-# <t:{int(ts.timestamp())}:f>"),
        ]

        container = discord.ui.Container(
            *components,
            accent_color=discord.Color.red(),
        )
        view = LogView(container)

        try:
            rules = await self.db.fetch(
                "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                role.guild.id,
                "role",
            )

            already_sent: set[int] = set()

            for rule in rules:
                log_channel_id = rule["log_channel_id"]
                if log_channel_id in already_sent:
                    continue

                log_channel = self.bot.get_channel(log_channel_id)
                if log_channel and isinstance(log_channel, discord.TextChannel):
                    if log_channel.permissions_for(log_channel.guild.me).send_messages:
                        try:
                            await log_channel.send(view=view)
                            already_sent.add(log_channel_id)
                        except discord.HTTPException:
                            pass
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        changes = []
        if before.name != after.name:
            changes.append(f"**Name:** {before.name} -> {after.name}")
        if before.color != after.color:
            changes.append(f"**Color:** {before.color} -> {after.color}")
        if before.permissions != after.permissions:
            added_perms = [
                perm
                for perm, value in after.permissions
                if value and not getattr(before.permissions, perm, False)
            ]
            removed_perms = [
                perm
                for perm, value in before.permissions
                if value and not getattr(after.permissions, perm, False)
            ]
            if added_perms:
                s = ", ".join(p.replace("_", " ").title() for p in added_perms[:5])
                if len(added_perms) > 5:
                    s += f" and {len(added_perms) - 5} more"
                changes.append(f"**Added Permissions:** {s}")
            if removed_perms:
                s = ", ".join(p.replace("_", " ").title() for p in removed_perms[:5])
                if len(removed_perms) > 5:
                    s += f" and {len(removed_perms) - 5} more"
                changes.append(f"**Removed Permissions:** {s}")

        if not changes:
            return

        moderator, reason = await self.get_moderator_from_audit_log(
            after.guild, after, discord.AuditLogAction.role_update
        )
        ts = discord.utils.utcnow()
        detail = f"**Role:** {after.mention} - ID: `{after.id}`\n" + "\n".join(changes)
        if moderator:
            detail += f"\n**Updated by:** {moderator.mention} (`{moderator}`)"
        if reason:
            detail += f"\n**Reason:** {reason[:400]}"

        components = [
            discord.ui.TextDisplay(content="## Role Updated"),
            discord.ui.TextDisplay(content=detail),
            discord.ui.TextDisplay(content=f"-# <t:{int(ts.timestamp())}:f>"),
        ]

        container = discord.ui.Container(
            *components,
            accent_color=discord.Color.blue(),
        )
        view = LogView(container)

        try:
            rules = await self.db.fetch(
                "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                after.guild.id,
                "role",
            )

            already_sent: set[int] = set()

            for rule in rules:
                log_channel_id = rule["log_channel_id"]
                if log_channel_id in already_sent:
                    continue

                log_channel = self.bot.get_channel(log_channel_id)
                if log_channel and isinstance(log_channel, discord.TextChannel):
                    if log_channel.permissions_for(log_channel.guild.me).send_messages:
                        try:
                            await log_channel.send(view=view)
                            already_sent.add(log_channel_id)
                        except discord.HTTPException:
                            pass
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        ts = discord.utils.utcnow()
        member_str = f"**Member:** {member.mention} (`{member}` - ID: `{member.id}`)"

        def _make_voice_components(title: str, color: discord.Color, detail: str):
            return [
                discord.ui.TextDisplay(content=f"## {title}"),
                discord.ui.Section(
                    discord.ui.TextDisplay(content=detail),
                    accessory=discord.ui.Thumbnail(
                        media=discord.UnfurledMediaItem(url=member.display_avatar.url)
                    ),
                ),
                discord.ui.TextDisplay(content=f"-# <t:{int(ts.timestamp())}:f>"),
            ]

        if not before.channel and after.channel:
            detail = f"{member_str}\n**Channel:** {after.channel.mention}"
            components = _make_voice_components(
                "Voice Channel Joined", discord.Color.green(), detail
            )
            container = discord.ui.Container(
                *components,
                accent_color=discord.Color.green(),
            )
            view = LogView(container)

            try:
                rules = await self.db.fetch(
                    "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                    member.guild.id,
                    "voice",
                )

                already_sent: set[int] = set()

                for rule in rules:
                    if (
                        rule["exclude_channel_ids"]
                        and after.channel.id in rule["exclude_channel_ids"]
                    ):
                        continue
                    if (
                        rule["include_channel_ids"]
                        and after.channel.id not in rule["include_channel_ids"]
                    ):
                        continue

                    log_channel_id = rule["log_channel_id"]
                    if log_channel_id in already_sent:
                        continue

                    log_channel = self.bot.get_channel(log_channel_id)
                    if log_channel and isinstance(log_channel, discord.TextChannel):
                        if log_channel.permissions_for(
                            log_channel.guild.me
                        ).send_messages:
                            try:
                                await log_channel.send(view=view)
                                already_sent.add(log_channel_id)
                            except discord.HTTPException:
                                pass
            except Exception:
                pass

        elif before.channel and not after.channel:
            detail = f"{member_str}\n**Channel:** {before.channel.mention}"
            components = _make_voice_components(
                "Voice Channel Left", discord.Color.red(), detail
            )
            container = discord.ui.Container(
                *components,
                accent_color=discord.Color.red(),
            )
            view = LogView(container)

            try:
                rules = await self.db.fetch(
                    "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                    member.guild.id,
                    "voice",
                )

                already_sent: set[int] = set()

                for rule in rules:
                    if (
                        rule["exclude_channel_ids"]
                        and before.channel.id in rule["exclude_channel_ids"]
                    ):
                        continue
                    if (
                        rule["include_channel_ids"]
                        and before.channel.id not in rule["include_channel_ids"]
                    ):
                        continue

                    log_channel_id = rule["log_channel_id"]
                    if log_channel_id in already_sent:
                        continue

                    log_channel = self.bot.get_channel(log_channel_id)
                    if log_channel and isinstance(log_channel, discord.TextChannel):
                        if log_channel.permissions_for(
                            log_channel.guild.me
                        ).send_messages:
                            try:
                                await log_channel.send(view=view)
                                already_sent.add(log_channel_id)
                            except discord.HTTPException:
                                pass
            except Exception:
                pass

        elif before.channel and after.channel and before.channel != after.channel:
            detail = f"{member_str}\n**From:** {before.channel.mention} -> **To:** {after.channel.mention}"
            components = _make_voice_components(
                "Voice Channel Moved", discord.Color.blue(), detail
            )
            container = discord.ui.Container(
                *components,
                accent_color=discord.Color.blue(),
            )
            view = LogView(container)

            try:
                rules = await self.db.fetch(
                    "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                    member.guild.id,
                    "voice",
                )

                already_sent: set[int] = set()

                for rule in rules:
                    if (
                        rule["exclude_channel_ids"]
                        and after.channel.id in rule["exclude_channel_ids"]
                    ):
                        continue
                    if (
                        rule["include_channel_ids"]
                        and after.channel.id not in rule["include_channel_ids"]
                    ):
                        continue

                    log_channel_id = rule["log_channel_id"]
                    if log_channel_id in already_sent:
                        continue

                    log_channel = self.bot.get_channel(log_channel_id)
                    if log_channel and isinstance(log_channel, discord.TextChannel):
                        if log_channel.permissions_for(
                            log_channel.guild.me
                        ).send_messages:
                            try:
                                await log_channel.send(view=view)
                                already_sent.add(log_channel_id)
                            except discord.HTTPException:
                                pass
            except Exception:
                pass

        elif (
            before.mute != after.mute
            or before.deaf != after.deaf
            or before.self_mute != after.self_mute
            or before.self_deaf != after.self_deaf
        ):
            changes = []
            moderator_info = {}

            if before.self_mute != after.self_mute:
                changes.append(
                    f"**Self Mute:** {before.self_mute} -> {after.self_mute}"
                )
            if before.self_deaf != after.self_deaf:
                changes.append(
                    f"**Self Deafen:** {before.self_deaf} -> {after.self_deaf}"
                )
            if before.mute != after.mute:
                moderator, reason = await self.get_moderator_from_audit_log(
                    member.guild, member, discord.AuditLogAction.member_update
                )
                changes.append(f"**Server Muted:** {before.mute} -> {after.mute}")
                if moderator:
                    moderator_info["mute"] = (moderator, reason)
            if before.deaf != after.deaf:
                moderator, reason = await self.get_moderator_from_audit_log(
                    member.guild, member, discord.AuditLogAction.member_update
                )
                changes.append(f"**Server Deafened:** {before.deaf} -> {after.deaf}")
                if moderator:
                    moderator_info["deaf"] = (moderator, reason)

            if not changes:
                return

            final_moderator, final_reason = next(
                (
                    v
                    for v in (moderator_info.get("mute"), moderator_info.get("deaf"))
                    if v
                ),
                (None, None),
            )
            channel_ref = after.channel.mention if after.channel else "*Unknown*"
            detail = f"{member_str}\n**Channel:** {channel_ref}\n" + "\n".join(changes)
            if final_moderator:
                detail += (
                    f"\n**Action by:** {final_moderator.mention} (`{final_moderator}`)"
                )
            if final_reason:
                detail += f"\n**Reason:** {final_reason[:400]}"

            components = _make_voice_components(
                "Voice State Updated", discord.Color.orange(), detail
            )
            container = discord.ui.Container(
                *components,
                accent_color=discord.Color.orange(),
            )
            view = LogView(container)

            try:
                rules = await self.db.fetch(
                    "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                    member.guild.id,
                    "voice",
                )

                already_sent: set[int] = set()

                for rule in rules:
                    channel_check = after.channel.id if after.channel else None
                    if channel_check:
                        if (
                            rule["exclude_channel_ids"]
                            and channel_check in rule["exclude_channel_ids"]
                        ):
                            continue
                        if (
                            rule["include_channel_ids"]
                            and channel_check not in rule["include_channel_ids"]
                        ):
                            continue

                    log_channel_id = rule["log_channel_id"]
                    if log_channel_id in already_sent:
                        continue

                    log_channel = self.bot.get_channel(log_channel_id)
                    if log_channel and isinstance(log_channel, discord.TextChannel):
                        if log_channel.permissions_for(
                            log_channel.guild.me
                        ).send_messages:
                            try:
                                await log_channel.send(view=view)
                                already_sent.add(log_channel_id)
                            except discord.HTTPException:
                                pass
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        changes = []

        if before.name != after.name:
            changes.append(f"**Name:** {before.name} -> {after.name}")
        if before.description != after.description:
            changes.append(
                f"**Description:** {before.description or 'None'} -> {after.description or 'None'}"
            )
        if before.icon != after.icon:
            changes.append(
                f"**Icon:** {'[Changed](' + after.icon.url + ')' if after.icon else 'Removed'}"
            )
        if before.banner != after.banner:
            changes.append(
                f"**Banner:** {'[Changed](' + after.banner.url + ')' if after.banner else 'Removed'}"
            )
        if before.splash != after.splash:
            changes.append(
                f"**Invite Splash:** {'[Changed](' + after.splash.url + ')' if after.splash else 'Removed'}"
            )
        if before.discovery_splash != after.discovery_splash:
            changes.append(
                f"**Discovery Splash:** {'[Changed](' + after.discovery_splash.url + ')' if after.discovery_splash else 'Removed'}"
            )
        if before.afk_channel != after.afk_channel:
            changes.append(
                f"**AFK Channel:** {before.afk_channel.mention if before.afk_channel else 'None'} -> {after.afk_channel.mention if after.afk_channel else 'None'}"
            )
        if before.afk_timeout != after.afk_timeout:
            changes.append(
                f"**AFK Timeout:** {before.afk_timeout}s -> {after.afk_timeout}s"
            )
        if before.system_channel != after.system_channel:
            changes.append(
                f"**System Channel:** {before.system_channel.mention if before.system_channel else 'None'} -> {after.system_channel.mention if after.system_channel else 'None'}"
            )
        if before.rules_channel != after.rules_channel:
            changes.append(
                f"**Rules Channel:** {before.rules_channel.mention if before.rules_channel else 'None'} -> {after.rules_channel.mention if after.rules_channel else 'None'}"
            )
        if before.public_updates_channel != after.public_updates_channel:
            changes.append(
                f"**Public Updates Channel:** {before.public_updates_channel.mention if before.public_updates_channel else 'None'} -> {after.public_updates_channel.mention if after.public_updates_channel else 'None'}"
            )
        if before.verification_level != after.verification_level:
            changes.append(
                f"**Verification Level:** {before.verification_level.name} -> {after.verification_level.name}"
            )
        if before.explicit_content_filter != after.explicit_content_filter:
            changes.append(
                f"**Content Filter:** {before.explicit_content_filter.name} -> {after.explicit_content_filter.name}"
            )
        if before.default_notifications != after.default_notifications:
            changes.append(
                f"**Default Notifications:** {before.default_notifications.name} -> {after.default_notifications.name}"
            )
        if before.vanity_url_code != after.vanity_url_code:
            changes.append(
                f"**Vanity URL:** {before.vanity_url_code or 'None'} -> {after.vanity_url_code or 'Removed'}"
            )
        if before.premium_progress_bar_enabled != after.premium_progress_bar_enabled:
            changes.append(
                f"**Premium Progress Bar:** {'Enabled' if after.premium_progress_bar_enabled else 'Disabled'}"
            )

        if not changes:
            return

        moderator, reason = await self.get_moderator_from_audit_log(
            after, after, discord.AuditLogAction.guild_update
        )
        ts = discord.utils.utcnow()

        components = [
            discord.ui.TextDisplay(content="## Server Updated"),
        ]

        changes_text = "\n".join(changes)
        if after.icon:
            components.append(
                discord.ui.Section(
                    discord.ui.TextDisplay(content=changes_text),
                    accessory=discord.ui.Thumbnail(
                        media=discord.UnfurledMediaItem(url=after.icon.url)
                    ),
                )
            )
        else:
            components.append(discord.ui.TextDisplay(content=changes_text))

        components.append(discord.ui.Separator())

        footer = f"Server ID: `{after.id}`"
        if moderator:
            footer += f" - Updated by {moderator.mention} (`{moderator}`)"
        if reason:
            footer += f"\n**Reason:** {reason[:300]}"

        components.append(discord.ui.TextDisplay(content=footer))
        components.append(
            discord.ui.TextDisplay(content=f"-# <t:{int(ts.timestamp())}:f>")
        )

        container = discord.ui.Container(
            *components,
            accent_color=discord.Color.blue(),
        )
        view = LogView(container)

        try:
            rules = await self.db.fetch(
                "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                after.id,
                "guild",
            )

            already_sent: set[int] = set()

            for rule in rules:
                log_channel_id = rule["log_channel_id"]
                if log_channel_id in already_sent:
                    continue

                log_channel = self.bot.get_channel(log_channel_id)
                if log_channel and isinstance(log_channel, discord.TextChannel):
                    if log_channel.permissions_for(log_channel.guild.me).send_messages:
                        try:
                            await log_channel.send(view=view)
                            already_sent.add(log_channel_id)
                        except discord.HTTPException:
                            pass
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if (
            message.author.bot
            or not message.guild
            or message.author.guild_permissions.manage_messages
        ):
            return

        role_ids = [role.id for role in getattr(message.author, "roles", [])]

        slowmode = await self.get_slowmode_for_context(
            message.guild.id, message.channel.id, message.author.id, role_ids
        )

        if slowmode:
            last_message = None
            async for msg in message.channel.history(limit=10):
                if msg.author == message.author and msg.id != message.id:
                    last_message = msg
                    break

            if (
                last_message
                and (
                    datetime.now(timezone.utc) - last_message.created_at
                ).total_seconds()
                < slowmode["delay_seconds"]
            ):
                try:
                    await message.delete()
                    await message.channel.send(
                        f"{message.author.mention}, your message was deleted due to slowmode. Please wait {slowmode['delay_seconds']} seconds between messages.",
                        delete_after=10,
                        allowed_mentions=discord.AllowedMentions(users=True),
                    )
                except discord.Forbidden:
                    pass
                return

        filters = await self.get_filters_for_context(
            message.guild.id, message.channel.id, message.author.id, role_ids
        )

        for filter in filters:
            try:
                if filter["filter_type"] == "regex":
                    if re.search(filter["pattern"], message.content, re.IGNORECASE):
                        await self.handle_filter_trigger(filter, message)
                elif filter["filter_type"] == "word":
                    if any(
                        word.lower() in message.content.lower()
                        for word in filter["pattern"].split(",")
                    ):
                        await self.handle_filter_trigger(filter, message)
                elif filter["filter_type"] == "link":
                    if any(
                        link in message.content.lower()
                        for link in filter["pattern"].split(",")
                    ):
                        await self.handle_filter_trigger(filter, message)
            except Exception:
                pass

    async def handle_filter_trigger(self, filter: dict, message: discord.Message):
        try:
            await message.delete()
            if filter["custom_message"]:
                try:
                    await message.author.send(filter["custom_message"])
                except discord.Forbidden:
                    pass
            if filter["action"] == "delete":
                pass
            elif filter["action"] == "warn":
                await message.channel.send(
                    f"{message.author.mention}, your message was deleted because it was violating the chat filter.",
                    delete_after=10,
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
            elif filter["action"] == "mute":
                try:
                    duration_minutes = filter.get("duration_minutes", 60)
                    duration = timedelta(minutes=duration_minutes)
                    await message.author.timeout(
                        duration, reason="Violated chat filter."
                    )
                    await message.channel.send(
                        f"{message.author.mention} has been timed out for {duration_minutes} minutes for violating the chat filter.",
                        delete_after=10,
                        allowed_mentions=discord.AllowedMentions(users=True),
                    )
                except discord.Forbidden:
                    pass
            elif filter["action"] == "kick":
                try:
                    await message.author.kick(reason="Violated the chat filter.")
                except discord.Forbidden:
                    pass
            elif filter["action"] == "ban":
                try:
                    await message.author.ban(
                        reason="Violated the chat filter.", delete_message_seconds=0
                    )
                except discord.Forbidden:
                    pass
        except discord.Forbidden:
            pass

    @commands.hybrid_group(name="filter", description="Manage chat filter rules.")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def filter_group(self, ctx: commands.Context):
        return

    @filter_group.command(name="server", description="Add a server-wide filter.")
    @commands.has_permissions(manage_messages=True)
    @app_commands.describe(
        filter_type="Type of filter.",
        pattern="Pattern to match.",
        action="Action to take.",
        custom_message="Optional DM.",
        duration_minutes="Timeout duration for mute action.",
    )
    async def filter_server(
        self,
        ctx: commands.Context,
        filter_type: Literal["regex", "word", "link"],
        pattern: str,
        action: Literal["delete", "warn", "mute", "kick", "ban"],
        custom_message: Optional[str] = None,
        duration_minutes: Optional[int] = 60,
    ):
        await ctx.typing()
        await self._add_filter(
            ctx,
            "server",
            None,
            filter_type,
            pattern,
            action,
            custom_message,
            duration_minutes,
        )

    @filter_group.command(name="channel", description="Add a channel specific filter.")
    @commands.has_permissions(manage_messages=True)
    @app_commands.describe(
        channel="Channel to target.",
        filter_type="Type of filter.",
        pattern="Pattern to match.",
        action="Action to take.",
        custom_message="Optional DM.",
        duration_minutes="Timeout duration for mute action.",
    )
    async def filter_channel(
        self,
        ctx: commands.Context,
        channel: discord.abc.GuildChannel | discord.Thread,
        filter_type: Literal["regex", "word", "link"],
        pattern: str,
        action: Literal["delete", "warn", "mute", "kick", "ban"],
        custom_message: Optional[str] = None,
        duration_minutes: Optional[int] = 60,
    ):
        await ctx.typing()
        await self._add_filter(
            ctx,
            "channel",
            channel.id,
            filter_type,
            pattern,
            action,
            custom_message,
            duration_minutes,
        )

    @filter_group.command(name="user", description="Add a user specific filter.")
    @commands.has_permissions(manage_messages=True)
    @app_commands.describe(
        user="User to target.",
        filter_type="Type of filter.",
        pattern="Pattern to match.",
        action="Action to take.",
        custom_message="Optional DM.",
        duration_minutes="Timeout duration for mute action.",
    )
    async def filter_user(
        self,
        ctx: commands.Context,
        user: discord.User,
        filter_type: Literal["regex", "word", "link"],
        pattern: str,
        action: Literal["delete", "warn", "mute", "kick", "ban"],
        custom_message: Optional[str] = None,
        duration_minutes: Optional[int] = 60,
    ):
        await ctx.typing()
        await self._add_filter(
            ctx,
            "user",
            user.id,
            filter_type,
            pattern,
            action,
            custom_message,
            duration_minutes,
        )

    @filter_group.command(name="role", description="Add a role specific filter.")
    @commands.has_permissions(manage_messages=True)
    @app_commands.describe(
        role="Role to target.",
        filter_type="Type of filter.",
        pattern="Pattern to match.",
        action="Action to take.",
        custom_message="Optional DM.",
        duration_minutes="Timeout duration for mute action.",
    )
    async def filter_role(
        self,
        ctx: commands.Context,
        role: discord.Role,
        filter_type: Literal["regex", "word", "link"],
        pattern: str,
        action: Literal["delete", "warn", "mute", "kick", "ban"],
        custom_message: Optional[str] = None,
        duration_minutes: Optional[int] = 60,
    ):
        await ctx.typing()
        await self._add_filter(
            ctx,
            "role",
            role.id,
            filter_type,
            pattern,
            action,
            custom_message,
            duration_minutes,
        )

    async def _add_filter(
        self,
        ctx: commands.Context,
        target_type: str,
        target_id: Optional[int],
        filter_type: str,
        pattern: str,
        action: str,
        custom_message: Optional[str],
        duration_minutes: Optional[int],
    ):
        if action == "mute":
            if not duration_minutes or duration_minutes <= 0:
                await ctx.send(
                    "Timeout duration must be greater than 0.", ephemeral=True
                )
                return
            if duration_minutes > 40320:
                await ctx.send(
                    "Maximum timeout is 28 days. (40320 minutes)", ephemeral=True
                )
                return
        else:
            duration_minutes = None

        try:
            if filter_type == "regex":
                re.compile(pattern)
        except re.error:
            await ctx.send("Invalid regex pattern.", ephemeral=True)
            return

        try:
            await self.db.execute(
                """
                INSERT INTO chat_filters (
                    guild_id, filter_type, pattern, action,
                    target_type, target_id, custom_message,
                    duration_minutes, added_by
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                ctx.guild.id,
                filter_type,
                pattern,
                action,
                target_type,
                target_id,
                custom_message,
                duration_minutes,
                ctx.author.id,
            )
            self.filter_cache.clear()
            target_name = {
                "server": "server-wide",
                "channel": f"<#{target_id}>",
                "user": f"<@{target_id}>",
                "role": f"<@&{target_id}>",
            }[target_type]
            response = f"Added **{filter_type}** filter for {target_name} -> `{action}`"
            if action == "mute":
                response += f" ({duration_minutes}m)"
            await ctx.send(response)
        except Exception as e:
            await ctx.send(f"Failed to add filter: {str(e)}")

    @filter_group.command(name="list", description="List all filters.", aliases=["ls"])
    @commands.has_permissions(manage_messages=True)
    async def filter_list(self, ctx: commands.Context):
        await ctx.typing()
        rows = await self.db.fetch(
            "SELECT * FROM chat_filters WHERE guild_id = $1 ORDER BY target_type, id",
            ctx.guild.id,
        )
        if not rows:
            await ctx.send("No filters were set up.", ephemeral=True)
            return

        embed = discord.Embed(title="Chat Filters", color=discord.Color.blurple())
        for r in rows:
            target = "Server-wide"
            if r["target_type"] == "channel":
                target = f"<#{r['target_id']}>"
            elif r["target_type"] == "user":
                target = f"<@{r['target_id']}>"
            elif r["target_type"] == "role":
                target = f"<@&{r['target_id']}>"

            embed.add_field(
                name=f"ID `{r['id']}` | {r['filter_type'].upper()} -> {r['action'].upper()}",
                value=(
                    f"**Pattern:** `{r['pattern'][:60]}{'...' if len(r['pattern']) > 60 else ''}`\n"
                    f"**Target:** {target}\n"
                    f"**Duration:** {r.get('duration_minutes', 'N/A')} min\n"
                    f"**Added by:** <@{r['added_by']}>"
                ),
                inline=False,
            )
        embed.set_footer(
            text=f"Requested by {ctx.author.name}",
            icon_url=ctx.author.display_avatar.url,
        )
        await ctx.send(embed=embed)

    @filter_group.command(
        name="remove", description="Remove a filter by ID.", aliases=["rm"]
    )
    @commands.has_permissions(manage_messages=True)
    @app_commands.describe(filter_id="The filter ID to remove.")
    async def filter_remove(self, ctx: commands.Context, filter_id: int):
        await ctx.typing()
        result = await self.db.fetchrow(
            "DELETE FROM chat_filters WHERE guild_id = $1 AND id = $2 RETURNING *",
            ctx.guild.id,
            filter_id,
        )
        if result:
            self.filter_cache.clear()
            await ctx.send(f"Filter ID `{filter_id}` removed.")
        else:
            await ctx.send(f"No filter with ID `{filter_id}` exists.", ephemeral=True)

    @commands.hybrid_group(
        name="slowmode", description="Set manual slowmode on any target."
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def slowmode_group(self, ctx: commands.Context):
        return

    @slowmode_group.command(
        name="server", description="Set server-wide manual slowmode."
    )
    @commands.has_permissions(manage_channels=True)
    @app_commands.describe(delay="Slowmode in seconds.")
    async def slowmode_server(self, ctx: commands.Context, delay: int):
        await self._set_slowmode(ctx, "server", None, delay)

    @slowmode_group.command(
        name="channel", description="Set manual slowmode for a specific channel."
    )
    @commands.has_permissions(manage_channels=True)
    @app_commands.describe(channel="Channel to target.", delay="Slowmode in seconds.")
    async def slowmode_channel(
        self,
        ctx: commands.Context,
        channel: discord.abc.GuildChannel | discord.Thread,
        delay: int,
    ):
        await self._set_slowmode(ctx, "channel", channel.id, delay)

    @slowmode_group.command(
        name="user", description="Set manual slowmode for a specific user."
    )
    @commands.has_permissions(manage_channels=True)
    @app_commands.describe(user="User to target.", delay="Slowmode in seconds.")
    async def slowmode_user(
        self, ctx: commands.Context, user: discord.User, delay: int
    ):
        await self._set_slowmode(ctx, "user", user.id, delay)

    @slowmode_group.command(
        name="role", description="Set manual slowmode for a specific role."
    )
    @commands.has_permissions(manage_channels=True)
    @app_commands.describe(role="Role to target.", delay="Slowmode in seconds.")
    async def slowmode_role(
        self, ctx: commands.Context, role: discord.Role, delay: int
    ):
        await self._set_slowmode(ctx, "role", role.id, delay)

    @slowmode_group.command(
        name="list",
        description="List all active manual slowmode rules.",
        aliases=["ls"],
    )
    @commands.has_permissions(manage_channels=True)
    async def slowmode_list(self, ctx: commands.Context):
        await ctx.typing()
        rows = await self.db.fetch(
            """
            SELECT * FROM manual_slowmodes
            WHERE guild_id = $1 AND enabled = TRUE
            ORDER BY
                user_id NULLS LAST,
                role_id NULLS LAST,
                channel_id NULLS LAST
            """,
            ctx.guild.id,
        )
        if not rows:
            await ctx.send("No active manual slowmode rules were set.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Manual Slowmode Rules", color=discord.Color.orange()
        )
        for r in rows:
            if r["user_id"] is not None:
                target = f"<@{r['user_id']}>"
            elif r["role_id"] is not None:
                target = f"<@&{r['role_id']}>"
            elif r["channel_id"] is not None:
                target = f"<#{r['channel_id']}>"
            else:
                target = "Server-wide"

            embed.add_field(
                name=f"ID `{r['id']}`",
                value=(
                    f"**Target:** {target}\n"
                    f"**Delay:** {r['delay_seconds']} second(s)\n"
                    f"**Added by:** <@{r['added_by']}>"
                ),
                inline=False,
            )
        embed.set_footer(
            text=f"Requested by {ctx.author.name}",
            icon_url=ctx.author.display_avatar.url,
        )
        await ctx.send(embed=embed)

    @slowmode_group.command(
        name="remove",
        description="Remove a manual slowmode rule by ID.",
        aliases=["rm"],
    )
    @commands.has_permissions(manage_channels=True)
    @app_commands.describe(rule_id="The manual slowmode rule ID to remove.")
    async def slowmode_remove(self, ctx: commands.Context, rule_id: int):
        await ctx.typing()
        result = await self.db.fetchrow(
            "DELETE FROM manual_slowmodes WHERE guild_id = $1 AND id = $2 RETURNING *",
            ctx.guild.id,
            rule_id,
        )
        if result:
            self.slowmode_cache.clear()
            target = "Server-wide"
            if result["user_id"]:
                target = f"User <@{result['user_id']}>"
            elif result["role_id"]:
                target = f"Role <@&{result['role_id']}>"
            elif result["channel_id"]:
                target = f"Channel <#{result['channel_id']}>"

            await ctx.send(f"Slowmode rule ID `{rule_id}` ({target}) has been removed.")
        else:
            await ctx.send(
                f"No slowmode rule found with ID `{rule_id}`.", ephemeral=True
            )

    async def _set_slowmode(
        self,
        ctx: commands.Context,
        target_type: str,
        target_id: Optional[int],
        delay: int,
    ):
        await ctx.typing()
        if delay < 0:
            await ctx.send("Delay cannot be negative.", ephemeral=True)
            return
        enabled = delay > 0

        channel_id = target_id if target_type == "channel" else None
        user_id = target_id if target_type == "user" else None
        role_id = target_id if target_type == "role" else None

        try:
            await self.db.execute(
                """
            INSERT INTO manual_slowmodes (
                guild_id, channel_id, user_id, role_id,
                delay_seconds, enabled, added_by
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (guild_id, channel_id, user_id, role_id)
            DO UPDATE SET
                delay_seconds = EXCLUDED.delay_seconds,
                enabled = EXCLUDED.enabled
            """,
                ctx.guild.id,
                channel_id,
                user_id,
                role_id,
                delay,
                enabled,
                ctx.author.id,
            )
            self.slowmode_cache.clear()

            target_name = {
                "server": "Server-wide",
                "channel": f"<#{target_id}>",
                "user": f"<@{target_id}>",
                "role": f"<@&{target_id}>",
            }[target_type]
            status = f"set to {delay}s" if enabled else "disabled"
            await ctx.send(f"{target_name} slowmode {status}.")
        except Exception as e:
            await ctx.send(f"Setting manual slowmode failed: {str(e)}", ephemeral=True)

    @commands.hybrid_command(
        name="ban", description="Bans provided member(s) or user(s)."
    )
    @app_commands.describe(
        members="Members or users to ban. Can be multiple.",
        delete_days="Number of days worth of messages to delete.",
        reason="Reason for the ban.",
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @commands.has_permissions(ban_members=True)
    async def ban(
        self,
        ctx: commands.Context,
        members: commands.Greedy[discord.User],
        delete_days: Optional[int] = 0,
        *,
        reason: str = "No reason provided.",
    ):
        await ctx.typing()
        delete_seconds = delete_days * 86400
        audit_log_reason = f"Timestamp: {datetime.now(timezone.utc)}\nAdmin: {ctx.author}\nReason: {reason}"

        banned_users = []
        guild = ctx.guild

        for user in members:
            if user == ctx.author:
                await ctx.send("You cannot ban yourself.")
                continue

            member = guild.get_member(user.id)

            if member is not None:
                if member.top_role >= ctx.author.top_role:
                    await ctx.send(
                        f"You can't ban `{member}` because they have an equal or higher role than you."
                    )
                    continue

                if member.top_role >= ctx.me.top_role:
                    await ctx.send(
                        f"I can't ban `{member}` because they have an equal or higher role than me."
                    )
                    continue

            try:
                await guild.ban(
                    user, delete_message_seconds=delete_seconds, reason=audit_log_reason
                )
                banned_users.append(str(user))
            except discord.Forbidden:
                await ctx.send(f"I don't have permission to ban `{user}`.")
            except discord.HTTPException as e:
                await ctx.send(f"Failed to ban `{user}`: {e}")

        if banned_users:
            await ctx.send(
                f"Banned member(s): `{', '.join(banned_users)}`\n**Reason:** `{reason}`\n(Messages will be deleted up to {delete_days} day(s) back)"
            )

        reference = ctx.message.reference
        if reference and isinstance(reference.resolved, discord.Message):
            replied_msg = reference.resolved
            replied_user = replied_msg.author

            if replied_user == ctx.author:
                await ctx.send("You cannot ban yourself via reply.")
                return

            replied_member = guild.get_member(replied_user.id)

            if replied_member:
                if replied_member.top_role >= ctx.author.top_role:
                    await ctx.send(
                        f"You can't ban `{replied_member}` because they have an equal or higher role than you."
                    )
                    return

                if replied_member.top_role >= ctx.me.top_role:
                    await ctx.send(
                        f"I can't ban `{replied_member}` because they have an equal or higher role than me."
                    )
                    return

            try:
                await guild.ban(
                    replied_user,
                    delete_message_seconds=delete_seconds,
                    reason=audit_log_reason,
                )
                await ctx.send(
                    f"Banned replied user: `{replied_user}`\n**Reason:** `{reason}`\n(Messages will be deleted up to {delete_days} day(s) back)"
                )
            except discord.Forbidden:
                await ctx.send(f"I don't have permission to ban `{replied_user}`.")
            except discord.HTTPException as e:
                await ctx.send(f"Failed to ban `{replied_user}`: {e}")

    @commands.hybrid_command(name="kick", description="Kicks provided member(s).")
    @app_commands.describe(
        members="Members to kick. Can be multiple.", reason="Reason for the kick."
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @commands.has_permissions(kick_members=True)
    async def kick(
        self,
        ctx: commands.Context,
        members: commands.Greedy[discord.Member],
        *,
        reason: str = "No reason provided.",
    ):
        await ctx.typing()
        audit_log_reason = f"Timestamp: {datetime.now(timezone.utc)}\nAdmin: {ctx.author}\nReason: {reason}"

        kicked_users = []
        guild = ctx.guild

        for member in members:
            if member == ctx.author:
                await ctx.send("You cannot kick yourself.")
                continue

            if member.top_role >= ctx.author.top_role:
                await ctx.send(
                    f"You can't kick `{member}` because they have an equal or higher role than you."
                )
                continue

            if member.top_role >= ctx.me.top_role:
                await ctx.send(
                    f"I can't kick `{member}` because they have an equal or higher role than me."
                )
                continue

            try:
                await member.kick(reason=audit_log_reason)
                kicked_users.append(str(member))
            except discord.Forbidden:
                await ctx.send(f"I don't have permission to kick `{member}`.")
            except discord.HTTPException as e:
                await ctx.send(f"Failed to kick `{member}`: {e}")

        if kicked_users:
            await ctx.send(
                f"Kicked member(s): `{', '.join(kicked_users)}`\n**Reason:** `{reason}`"
            )

        reference = ctx.message.reference
        if reference and isinstance(reference.resolved, discord.Message):
            replied_msg = reference.resolved
            replied_member = replied_msg.author

            if not isinstance(replied_member, discord.Member):
                replied_member = guild.get_member(replied_member.id)
                if replied_member is None:
                    await ctx.send("Replied user is not in this server.")
                    return

            if replied_member == ctx.author:
                await ctx.send("You cannot kick yourself via reply.")
                return

            if replied_member.top_role >= ctx.author.top_role:
                await ctx.send(
                    f"You can't kick `{replied_member}` because they have an equal or higher role than you."
                )
                return

            if replied_member.top_role >= ctx.me.top_role:
                await ctx.send(
                    f"I can't kick `{replied_member}` because they have an equal or higher role than me."
                )
                return

            try:
                await replied_member.kick(reason=audit_log_reason)
                await ctx.send(
                    f"Kicked replied user: `{replied_member}`\n**Reason:** `{reason}`"
                )
            except discord.Forbidden:
                await ctx.send(f"I don't have permission to kick `{replied_member}`.")
            except discord.HTTPException as e:
                await ctx.send(f"Failed to kick `{replied_member}`: {e}")


async def setup(bot):
    cog = Moderation(bot)
    cog.db = await asyncpg.create_pool(bot_info.data["database"])
    await bot.add_cog(cog)
