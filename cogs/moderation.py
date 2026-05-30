import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional, Union
from urllib.parse import urlparse

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
        self.react_cache = {}
        self.reply_cache = {}
        self.db = asyncpg.Pool

    async def _evaluate_tagscript(self, template: str, ctx_data: dict) -> tuple:
        try:
            if not template:
                return "", [], None, []

            tags = self.bot.get_cog("Tags")

            class FakeContext:
                def __init__(self, data, bot):
                    self.author = data.get("author")
                    self.guild = data.get("guild")
                    self.channel = data.get("channel")
                    self.bot = bot
                    self.message = data.get("message")
                    self.me = bot.user if bot else None

            fake_ctx = FakeContext(ctx_data, self.bot)
            kwargs = {
                k: v
                for k, v in ctx_data.items()
                if k not in ("author", "guild", "channel", "message")
            }

            if "message" in ctx_data:
                msg = ctx_data["message"]
                kwargs["message_id"] = str(getattr(msg, "id", ""))
                kwargs["message_content"] = getattr(msg, "content", "") or ""
                kwargs["message_clean_content"] = (
                    getattr(msg, "clean_content", "") or ""
                )
                kwargs["message_jump_url"] = getattr(msg, "jump_url", "")
                kwargs["message_created_at"] = (
                    msg.created_at.isoformat()
                    if getattr(msg, "created_at", None)
                    else ""
                )
                kwargs["message_edited_at"] = (
                    msg.edited_at.isoformat() if getattr(msg, "edited_at", None) else ""
                )

                msg_embeds = getattr(msg, "embeds", []) or []
                msg_attachments = getattr(msg, "attachments", []) or []

                kwargs["message_has_embeds"] = str(len(msg_embeds) > 0).lower()
                kwargs["message_embed_count"] = str(len(msg_embeds))
                kwargs["message_has_attachments"] = str(
                    len(msg_attachments) > 0
                ).lower()
                kwargs["message_attachment_count"] = str(len(msg_attachments))

                kwargs["message_embed_titles"] = []
                kwargs["message_embed_descriptions"] = []
                kwargs["message_embed_urls"] = []

                for i, embed in enumerate(msg_embeds):
                    kwargs[f"message_embed_title_{i}"] = (
                        getattr(embed, "title", "") or ""
                    )
                    kwargs[f"message_embed_description_{i}"] = (
                        getattr(embed, "description", "") or ""
                    )
                    kwargs[f"message_embed_url_{i}"] = getattr(embed, "url", "") or ""
                    kwargs[f"message_embed_color_{i}"] = (
                        str(embed.color) if getattr(embed, "color", None) else ""
                    )
                    kwargs[f"message_embed_image_{i}"] = (
                        embed.image.url if getattr(embed, "image", None) else ""
                    )
                    kwargs[f"message_embed_thumbnail_{i}"] = (
                        embed.thumbnail.url if getattr(embed, "thumbnail", None) else ""
                    )

                    if getattr(embed, "title", None):
                        kwargs["message_embed_titles"].append(embed.title)
                    if getattr(embed, "description", None):
                        kwargs["message_embed_descriptions"].append(embed.description)
                    if getattr(embed, "url", None):
                        kwargs["message_embed_urls"].append(embed.url)

                if msg_embeds:
                    embed = msg_embeds[0]
                    kwargs["message_embed_title"] = getattr(embed, "title", "") or ""
                    kwargs["message_embed_description"] = (
                        getattr(embed, "description", "") or ""
                    )
                    kwargs["message_embed_url"] = getattr(embed, "url", "") or ""
                    kwargs["message_embed_color"] = (
                        str(embed.color) if getattr(embed, "color", None) else ""
                    )
                    kwargs["message_embed_image"] = (
                        embed.image.url if getattr(embed, "image", None) else ""
                    )
                    kwargs["message_embed_thumbnail"] = (
                        embed.thumbnail.url if getattr(embed, "thumbnail", None) else ""
                    )

                kwargs["message_attachment_filenames"] = []
                kwargs["message_attachment_urls"] = []
                kwargs["message_attachment_proxy_urls"] = []

                for i, att in enumerate(msg_attachments):
                    kwargs[f"message_attachment_filename_{i}"] = getattr(
                        att, "filename", ""
                    )
                    kwargs[f"message_attachment_url_{i}"] = getattr(att, "url", "")
                    kwargs[f"message_attachment_proxy_url_{i}"] = getattr(
                        att, "proxy_url", ""
                    )
                    kwargs[f"message_attachment_size_{i}"] = str(
                        getattr(att, "size", "0")
                    )
                    kwargs[f"message_attachment_content_type_{i}"] = (
                        getattr(att, "content_type", "") or ""
                    )

                    if getattr(att, "filename", None):
                        kwargs["message_attachment_filenames"].append(att.filename)
                    if getattr(att, "url", None):
                        kwargs["message_attachment_urls"].append(att.url)
                    if getattr(att, "proxy_url", None):
                        kwargs["message_attachment_proxy_urls"].append(att.proxy_url)

                if msg_attachments:
                    att = msg_attachments[0]
                    kwargs["message_attachment_filename"] = getattr(att, "filename", "")
                    kwargs["message_attachment_url"] = getattr(att, "url", "")
                    kwargs["message_attachment_proxy_url"] = getattr(
                        att, "proxy_url", ""
                    )
                    kwargs["message_attachment_size"] = str(getattr(att, "size", "0"))
                    kwargs["message_attachment_content_type"] = (
                        getattr(att, "content_type", "") or ""
                    )

            if "before_message" in ctx_data:
                before = ctx_data["before_message"]
                kwargs["before_content"] = getattr(before, "content", "") or ""
                kwargs["before_clean_content"] = (
                    getattr(before, "clean_content", "") or ""
                )

                before_embeds = getattr(before, "embeds", []) or []
                before_attachments = getattr(before, "attachments", []) or []

                kwargs["before_has_embeds"] = str(len(before_embeds) > 0).lower()
                kwargs["before_embed_count"] = str(len(before_embeds))
                kwargs["before_has_attachments"] = str(
                    len(before_attachments) > 0
                ).lower()
                kwargs["before_attachment_count"] = str(len(before_attachments))

                kwargs["before_embed_titles"] = []
                kwargs["before_embed_descriptions"] = []
                kwargs["before_embed_urls"] = []

                for i, embed in enumerate(before_embeds):
                    kwargs[f"before_embed_title_{i}"] = (
                        getattr(embed, "title", "") or ""
                    )
                    kwargs[f"before_embed_description_{i}"] = (
                        getattr(embed, "description", "") or ""
                    )
                    kwargs[f"before_embed_url_{i}"] = getattr(embed, "url", "") or ""
                    kwargs[f"before_embed_color_{i}"] = (
                        str(embed.color) if getattr(embed, "color", None) else ""
                    )
                    kwargs[f"before_embed_image_{i}"] = (
                        embed.image.url if getattr(embed, "image", None) else ""
                    )
                    kwargs[f"before_embed_thumbnail_{i}"] = (
                        embed.thumbnail.url if getattr(embed, "thumbnail", None) else ""
                    )

                    if getattr(embed, "title", None):
                        kwargs["before_embed_titles"].append(embed.title)
                    if getattr(embed, "description", None):
                        kwargs["before_embed_descriptions"].append(embed.description)
                    if getattr(embed, "url", None):
                        kwargs["before_embed_urls"].append(embed.url)

                if before_embeds:
                    embed = before_embeds[0]
                    kwargs["before_embed_title"] = getattr(embed, "title", "") or ""
                    kwargs["before_embed_description"] = (
                        getattr(embed, "description", "") or ""
                    )
                    kwargs["before_embed_url"] = getattr(embed, "url", "") or ""
                    kwargs["before_embed_color"] = (
                        str(embed.color) if getattr(embed, "color", None) else ""
                    )
                    kwargs["before_embed_image"] = (
                        embed.image.url if getattr(embed, "image", None) else ""
                    )
                    kwargs["before_embed_thumbnail"] = (
                        embed.thumbnail.url if getattr(embed, "thumbnail", None) else ""
                    )

                kwargs["before_attachment_filenames"] = []
                kwargs["before_attachment_urls"] = []
                kwargs["before_attachment_proxy_urls"] = []

                for i, att in enumerate(before_attachments):
                    kwargs[f"before_attachment_filename_{i}"] = getattr(
                        att, "filename", ""
                    )
                    kwargs[f"before_attachment_url_{i}"] = getattr(att, "url", "")
                    kwargs[f"before_attachment_proxy_url_{i}"] = getattr(
                        att, "proxy_url", ""
                    )
                    kwargs[f"before_attachment_size_{i}"] = str(
                        getattr(att, "size", "0")
                    )
                    kwargs[f"before_attachment_content_type_{i}"] = (
                        getattr(att, "content_type", "") or ""
                    )

                    if getattr(att, "filename", None):
                        kwargs["before_attachment_filenames"].append(att.filename)
                    if getattr(att, "url", None):
                        kwargs["before_attachment_urls"].append(att.url)
                    if getattr(att, "proxy_url", None):
                        kwargs["before_attachment_proxy_urls"].append(att.proxy_url)

                if before_attachments:
                    att = before_attachments[0]
                    kwargs["before_attachment_filename"] = getattr(att, "filename", "")
                    kwargs["before_attachment_url"] = getattr(att, "url", "")
                    kwargs["before_attachment_proxy_url"] = getattr(
                        att, "proxy_url", ""
                    )
                    kwargs["before_attachment_size"] = str(getattr(att, "size", "0"))
                    kwargs["before_attachment_content_type"] = (
                        getattr(att, "content_type", "") or ""
                    )

            if "after_message" in ctx_data:
                after = ctx_data["after_message"]
                kwargs["after_content"] = getattr(after, "content", "") or ""
                kwargs["after_clean_content"] = (
                    getattr(after, "clean_content", "") or ""
                )

                after_embeds = getattr(after, "embeds", []) or []
                after_attachments = getattr(after, "attachments", []) or []

                kwargs["after_has_embeds"] = str(len(after_embeds) > 0).lower()
                kwargs["after_embed_count"] = str(len(after_embeds))
                kwargs["after_has_attachments"] = str(
                    len(after_attachments) > 0
                ).lower()
                kwargs["after_attachment_count"] = str(len(after_attachments))

                kwargs["after_embed_titles"] = []
                kwargs["after_embed_descriptions"] = []
                kwargs["after_embed_urls"] = []

                for i, embed in enumerate(after_embeds):
                    kwargs[f"after_embed_title_{i}"] = getattr(embed, "title", "") or ""
                    kwargs[f"after_embed_description_{i}"] = (
                        getattr(embed, "description", "") or ""
                    )
                    kwargs[f"after_embed_url_{i}"] = getattr(embed, "url", "") or ""
                    kwargs[f"after_embed_color_{i}"] = (
                        str(embed.color) if getattr(embed, "color", None) else ""
                    )
                    kwargs[f"after_embed_image_{i}"] = (
                        embed.image.url if getattr(embed, "image", None) else ""
                    )
                    kwargs[f"after_embed_thumbnail_{i}"] = (
                        embed.thumbnail.url if getattr(embed, "thumbnail", None) else ""
                    )

                    if getattr(embed, "title", None):
                        kwargs["after_embed_titles"].append(embed.title)
                    if getattr(embed, "description", None):
                        kwargs["after_embed_descriptions"].append(embed.description)
                    if getattr(embed, "url", None):
                        kwargs["after_embed_urls"].append(embed.url)

                if after_embeds:
                    embed = after_embeds[0]
                    kwargs["after_embed_title"] = getattr(embed, "title", "") or ""
                    kwargs["after_embed_description"] = (
                        getattr(embed, "description", "") or ""
                    )
                    kwargs["after_embed_url"] = getattr(embed, "url", "") or ""
                    kwargs["after_embed_color"] = (
                        str(embed.color) if getattr(embed, "color", None) else ""
                    )
                    kwargs["after_embed_image"] = (
                        embed.image.url if getattr(embed, "image", None) else ""
                    )
                    kwargs["after_embed_thumbnail"] = (
                        embed.thumbnail.url if getattr(embed, "thumbnail", None) else ""
                    )

                kwargs["after_attachment_filenames"] = []
                kwargs["after_attachment_urls"] = []
                kwargs["after_attachment_proxy_urls"] = []

                for i, att in enumerate(after_attachments):
                    kwargs[f"after_attachment_filename_{i}"] = getattr(
                        att, "filename", ""
                    )
                    kwargs[f"after_attachment_url_{i}"] = getattr(att, "url", "")
                    kwargs[f"after_attachment_proxy_url_{i}"] = getattr(
                        att, "proxy_url", ""
                    )
                    kwargs[f"after_attachment_size_{i}"] = str(
                        getattr(att, "size", "0")
                    )
                    kwargs[f"after_attachment_content_type_{i}"] = (
                        getattr(att, "content_type", "") or ""
                    )

                    if getattr(att, "filename", None):
                        kwargs["after_attachment_filenames"].append(att.filename)
                    if getattr(att, "url", None):
                        kwargs["after_attachment_urls"].append(att.url)
                    if getattr(att, "proxy_url", None):
                        kwargs["after_attachment_proxy_urls"].append(att.proxy_url)

                if after_attachments:
                    att = after_attachments[0]
                    kwargs["after_attachment_filename"] = getattr(att, "filename", "")
                    kwargs["after_attachment_url"] = getattr(att, "url", "")
                    kwargs["after_attachment_proxy_url"] = getattr(att, "proxy_url", "")
                    kwargs["after_attachment_size"] = str(getattr(att, "size", "0"))
                    kwargs["after_attachment_content_type"] = (
                        getattr(att, "content_type", "") or ""
                    )

            kwargs["event_type"] = ctx_data.get("event", "")

            text, embeds, view, files = await tags.formatter.format(
                template, fake_ctx, **kwargs
            )
            text = text.strip() if text else ""
            return text, embeds, view, files
        except Exception as e:
            return f"[TagScript Error: {e}]", [], None, []

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
            SELECT slowmode_id, delay_seconds, custom_message FROM manual_slowmodes
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

    async def get_next_filter_id(self, guild_id: int) -> int:
        query = """
            SELECT COALESCE(
                (SELECT f1.filter_id + 1
                 FROM chat_filters f1
                 WHERE f1.guild_id = $1
                 AND NOT EXISTS (
                     SELECT 1 FROM chat_filters f2
                     WHERE f2.guild_id = $1
                     AND f2.filter_id = f1.filter_id + 1
                 )
                 ORDER BY f1.filter_id
                 LIMIT 1), 1) AS next_id
        """
        result = await self.db.fetchval(query, guild_id)
        return result if result else 1

    async def get_next_slowmode_id(self, guild_id: int) -> int:
        query = """
            SELECT COALESCE(
                (SELECT s1.slowmode_id + 1
                 FROM manual_slowmodes s1
                 WHERE s1.guild_id = $1
                 AND NOT EXISTS (
                     SELECT 1 FROM manual_slowmodes s2
                     WHERE s2.guild_id = $1
                     AND s2.slowmode_id = s1.slowmode_id + 1
                 )
                 ORDER BY s1.slowmode_id
                 LIMIT 1), 1) AS next_id
        """
        result = await self.db.fetchval(query, guild_id)
        return result if result else 1

    async def get_next_reaction_id(self, guild_id: int) -> int:
        q = """
            SELECT COALESCE(
                (SELECT r1.reaction_id + 1
                FROM chat_reactions r1
                WHERE r1.guild_id = $1
                AND NOT EXISTS (
                    SELECT 1 FROM chat_reactions r2
                    WHERE r2.guild_id = $1
                    AND r2.reaction_id = r1.reaction_id + 1
                ) ORDER BY r1.reaction_id
                LIMIT 1), 1)
                """
        return await self.db.fetchval(q, guild_id) or 1

    async def get_next_reply_id(self, guild_id: int) -> int:
        q = """
        SELECT COALESCE(
            (SELECT r1.reply_id + 1
            FROM chat_replies r1
            WHERE r1.guild_id = $1 AND NOT EXISTS (
                SELECT 1 FROM chat_replies r2
                WHERE r2.guild_id = $1
                AND r2.reply_id = r1.reply_id + 1
            ) ORDER BY r1.reply_id
            LIMIT 1), 1)
            """
        return await self.db.fetchval(q, guild_id) or 1

    async def get_reactions_for_context(self, guild_id, channel_id, user_id, role_ids):
        k = (guild_id, channel_id, user_id, tuple(sorted(role_ids)))
        if k in self.react_cache:
            return self.react_cache[k]
        r = await self.db.fetch(
            """
            SELECT * FROM chat_reactions
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
        self.react_cache[k] = r
        return r

    async def get_replies_for_context(self, guild_id, channel_id, user_id, role_ids):
        k = (guild_id, channel_id, user_id, tuple(sorted(role_ids)))
        if k in self.reply_cache:
            return self.reply_cache[k]
        r = await self.db.fetch(
            """
            SELECT * FROM chat_replies
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
        self.reply_cache[k] = r
        return r

    async def handle_filter_trigger(self, filter: dict, message: discord.Message):
        try:
            await message.delete()

            del_after = filter.get("delete_after", 10)
            delete_kwarg = {"delete_after": del_after} if del_after > 0 else {}

            if filter.get("custom_message"):
                ctx_data = {
                    "author": message.author,
                    "guild": message.guild,
                    "channel": message.channel,
                    "message": message,
                    "filter_type": filter["filter_type"],
                    "pattern": filter["pattern"],
                    "action": filter["action"],
                    "filter_id": filter.get("filter_id"),
                }
                text, embeds, view, files = await self._evaluate_tagscript(
                    filter["custom_message"], ctx_data
                )
                kwargs = {}
                if text:
                    kwargs["content"] = text[:2000]
                if embeds:
                    kwargs["embeds"] = embeds[:10]
                if view:
                    kwargs["view"] = view
                if files:
                    kwargs["files"] = files[:10]

                kwargs.update(delete_kwarg)
                await message.channel.send(**kwargs)

            if filter["action"] == "delete":
                pass
            elif filter["action"] == "warn":
                if not filter.get("custom_message"):
                    warn_kw = {
                        **delete_kwarg,
                        "allowed_mentions": discord.AllowedMentions(users=True),
                    }
                    await message.channel.send(
                        f"{message.author.mention}, your message was deleted because it was violating the chat filter.",
                        **warn_kw,
                    )
            elif filter["action"] == "mute":
                try:
                    duration_minutes = filter.get("timeout_minutes", 60)
                    duration = timedelta(minutes=duration_minutes)
                    await message.author.timeout(
                        duration, reason="Violated chat filter."
                    )
                    if not filter.get("custom_message"):
                        mute_kw = {
                            **delete_kwarg,
                            "allowed_mentions": discord.AllowedMentions(users=True),
                        }
                        await message.channel.send(
                            f"{message.author.mention} has been timed out for {duration_minutes} minutes for violating the chat filter.",
                            **mute_kw,
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
                        reason="Violated the chat filter.",
                        delete_message_seconds=filter.get("delete_seconds", 0),
                    )
                except discord.Forbidden:
                    pass
        except discord.Forbidden:
            pass

    async def handle_react_trigger(self, reaction: dict, message: discord.Message):
        try:
            await message.add_reaction(reaction["emoji"])
        except discord.HTTPException:
            pass

    async def handle_reply_trigger(self, reply: dict, message: discord.Message):
        try:
            ctx_data = {
                "author": message.author,
                "guild": message.guild,
                "channel": message.channel,
                "message": message,
                "trigger_type": reply["trigger_type"],
                "pattern": reply["pattern"],
                "reply_id": reply.get("reply_id"),
            }
            text, embeds, view, files = await self._evaluate_tagscript(
                reply["response_message"], ctx_data
            )
            kwargs = {}
            if text:
                kwargs["content"] = text[:2000]
            if embeds:
                kwargs["embeds"] = embeds[:10]
            if view:
                kwargs["view"] = view
            if files:
                kwargs["files"] = files[:10]

            if kwargs:
                send_kwargs = {**kwargs, "reference": message, "mention_author": False}
                del_after = reply.get("delete_after", 10)
                if del_after > 0:
                    send_kwargs["delete_after"] = del_after
                await message.channel.send(**send_kwargs)
        except discord.HTTPException:
            pass

    @commands.hybrid_group(
        name="chat",
        description="Manage automated chat actions (filters, reactions, replies).",
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def chat_group(self, ctx: commands.Context):
        pass

    @chat_group.group(name="filter", description="Manage chat filter rules.")
    async def filter_group(self, ctx: commands.Context):
        pass

    @chat_group.group(name="react", description="Manage auto-reactions.")
    async def react_group(self, ctx: commands.Context):
        pass

    @chat_group.group(name="reply", description="Manage auto-replies.")
    async def reply_group(self, ctx: commands.Context):
        pass

    @filter_group.command(name="add", description="Add a chat filter rule.")
    @commands.has_permissions(manage_messages=True)
    @app_commands.describe(
        target="What type to target.",
        target_id="ID, name, or mention of the target. (for channel/user/role)",
        filter_type="Type of filter.",
        pattern="Pattern to match. (regex pattern, comma-separated words, or domain list)",
        action="Action to take when triggered.",
        custom_message="Custom message sent in channel when triggered. (supports TagScript.)",
        timeout_minutes="Timeout duration for mute action. (1-40320 minutes)",
        delete_days="Days of messages to delete for ban action. (0-7)",
        delete_after="Seconds to auto-delete response. (0 = keep forever)",
    )
    async def filter_add(
        self,
        ctx: commands.Context,
        target: Literal["server", "channel", "user", "role"],
        target_id: Optional[str] = None,
        filter_type: Literal["regex", "word", "link"] = "word",
        pattern: Optional[str] = None,
        action: Literal["delete", "warn", "mute", "kick", "ban"] = "delete",
        custom_message: Optional[str] = None,
        timeout_minutes: Optional[int] = 60,
        delete_days: Optional[int] = 1,
        delete_after: Optional[int] = 10,
    ):
        await ctx.typing()

        resolved_target_id = None
        target_name = "server-wide"
        if pattern is None:
            await ctx.send("A pattern for filtering is required.", ephemeral=True)
            return
        if target == "server":
            resolved_target_id = None
        elif target == "channel":
            try:
                channel = await commands.TextChannelConverter().convert(ctx, target_id)
                resolved_target_id = channel.id
                target_name = channel.mention
            except Exception:
                await ctx.send(f"Invalid channel: {target_id}", ephemeral=True)
                return
        elif target == "user":
            try:
                user = await commands.UserConverter().convert(ctx, target_id)
                resolved_target_id = user.id
                target_name = user.mention
            except Exception:
                await ctx.send(f"Invalid user: {target_id}", ephemeral=True)
                return
        elif target == "role":
            try:
                role = await commands.RoleConverter().convert(ctx, target_id)
                resolved_target_id = role.id
                target_name = role.mention
            except Exception:
                await ctx.send(f"Invalid role: {target_id}", ephemeral=True)
                return

        if action == "mute":
            if timeout_minutes < 1:
                await ctx.send("Timeout must be at least 1 minute.", ephemeral=True)
                return
            if timeout_minutes > 40320:
                await ctx.send(
                    "Timeout cannot exceed 28 days (40320 minutes).", ephemeral=True
                )
                return

        if action == "ban":
            if delete_days < 0 or delete_days > 7:
                await ctx.send("Delete days must be between 0 and 7.", ephemeral=True)
                return

        delete_seconds = delete_days * 86400 if action == "ban" else None

        if filter_type == "regex":
            try:
                re.compile(pattern)
            except re.error as e:
                await ctx.send(f"Invalid regex pattern: {str(e)}", ephemeral=True)
                return

        if filter_type in ("word", "link"):
            words = [w.strip().lower() for w in pattern.split(",") if w.strip()]
            if not words:
                await ctx.send("No valid patterns provided.", ephemeral=True)
                return
            pattern = ",".join(words)

        try:
            filter_id = await self.get_next_filter_id(ctx.guild.id)

            existing = await self.db.fetchrow(
                """
                SELECT filter_id FROM chat_filters
                WHERE guild_id = $1 AND target_type = $2
                AND (target_id = $3 OR (target_id IS NULL AND $3 IS NULL))
                 AND filter_type = $4 AND pattern = $5
                """,
                ctx.guild.id,
                target,
                resolved_target_id,
                filter_type,
                pattern,
            )

            if existing:
                await ctx.send(
                    f"A similar filter already exists (ID: {existing['filter_id']}).",
                    ephemeral=True,
                )
                return

            await self.db.execute(
                """
                INSERT INTO chat_filters (
                    filter_id, guild_id, target_type, target_id, filter_type, pattern, action,
                    custom_message, timeout_minutes, delete_seconds, delete_after, added_by, created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW())
                """,
                filter_id,
                ctx.guild.id,
                target,
                resolved_target_id,
                filter_type,
                pattern,
                action,
                custom_message,
                timeout_minutes if action == "mute" else None,
                delete_seconds,
                delete_after,
                ctx.author.id,
            )

            self.filter_cache.clear()

            response = f"Added **{filter_type}** filter for {target_name} -> `{action}`"
            if action == "mute":
                response += f" ({timeout_minutes}m)"
            elif action == "ban":
                response += f" (delete {delete_days}d)"
            response += f"\nAuto-delete response: {'Disabled' if delete_after == 0 else f'{delete_after}s'}"
            if custom_message:
                response += f"\nCustom message: {custom_message[:100]}"

            await ctx.send(response)

        except Exception as e:
            await ctx.send(f"Failed to add filter: {str(e)}")

    @filter_group.command(
        name="list", description="List all chat filters.", aliases=["ls"]
    )
    @commands.has_permissions(manage_messages=True)
    async def filter_list(self, ctx: commands.Context):
        await ctx.typing()

        rows = await self.db.fetch(
            """
            SELECT f.*, COUNT(*) OVER() as total
            FROM chat_filters f
            WHERE guild_id = $1
            ORDER BY target_type, created_at DESC
            """,
            ctx.guild.id,
        )

        if not rows:
            await ctx.send("No chat filters were set up.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"Chat Filters ({len(rows)})", color=discord.Color.blurple()
        )

        for r in rows:
            if r["target_type"] == "server":
                target = "Server-wide"
            elif r["target_type"] == "channel":
                target = f"{ctx.guild.get_channel(r['target_id']).mention or f'Channel:{r["target_id"]}'}"
            elif r["target_type"] == "user":
                target = f"{ctx.guild.get_member(r['target_id']).mention or f'User:{r["target_id"]}'}"
            else:
                target = f"{ctx.guild.get_role(r['target_id']).mention or f'Role:{r["target_id"]}'}"

            pattern_display = r["pattern"][:50] + (
                "..." if len(r["pattern"]) > 50 else ""
            )
            del_status = (
                "Keep Forever"
                if r.get("delete_after") == 0
                else f"Delete after {r.get('delete_after', 10)}s"
            )

            embed.add_field(
                name=f"`#{r['filter_id']}` {r['filter_type']} -> {r['action']}",
                value=(
                    f"**Target:** {target}\n"
                    f"**Pattern:** `{pattern_display}`\n"
                    f"**Auto-Delete:** {del_status}\n"
                    f"**Added:** <t:{int(r['created_at'].timestamp())}:R>"
                    + ("\n**Custom Message:** Yes" if r.get("custom_message") else "")
                ),
                inline=False,
            )

        await ctx.send(embed=embed)

    @filter_group.command(
        name="remove", description="Remove a filter by ID.", aliases=["rm"]
    )
    @commands.has_permissions(manage_messages=True)
    @app_commands.describe(filter_id="The filter rule ID to remove.")
    async def filter_remove(self, ctx: commands.Context, filter_id: int):
        await ctx.typing()

        result = await self.db.fetchrow(
            "DELETE FROM chat_filters WHERE guild_id = $1 AND filter_id = $2 RETURNING filter_type, target_type",
            ctx.guild.id,
            filter_id,
        )

        if result:
            self.filter_cache.clear()
            await ctx.send(
                f"Removed filter `#{filter_id}` ({result['filter_type']} -> {result['target_type']})."
            )
        else:
            await ctx.send(f"No filter found with ID `{filter_id}`.", ephemeral=True)

    @filter_group.command(name="clear", description="Remove all filters for a target.")
    @commands.has_permissions(manage_messages=True)
    @app_commands.describe(
        target="Target type to clear filters from.",
        target_id="ID, name, or mention of the target. (for channel/user/role)",
    )
    async def filter_clear(
        self,
        ctx: commands.Context,
        target: Literal["server", "channel", "user", "role"],
        target_id: Optional[str] = None,
    ):
        await ctx.typing()

        resolved_target_id = None
        if target == "channel" and target_id:
            try:
                channel = await commands.TextChannelConverter().convert(ctx, target_id)
                resolved_target_id = channel.id
            except Exception:
                await ctx.send(f"Invalid channel: {target_id}", ephemeral=True)
                return
        elif target == "user" and target_id:
            try:
                user = await commands.UserConverter().convert(ctx, target_id)
                resolved_target_id = user.id
            except Exception:
                await ctx.send(f"Invalid user: {target_id}", ephemeral=True)
                return
        elif target == "role" and target_id:
            try:
                role = await commands.RoleConverter().convert(ctx, target_id)
                resolved_target_id = role.id
            except Exception:
                await ctx.send(f"Invalid role: {target_id}", ephemeral=True)
                return

        result = await self.db.execute(
            """
            DELETE FROM chat_filters
            WHERE guild_id = $1 AND target_type = $2
            AND (target_id = $3 OR (target_id IS NULL AND $3 IS NULL))
            """,
            ctx.guild.id,
            target,
            resolved_target_id,
        )

        count = int(result.split()[1]) if result.startswith("DELETE") else 0

        if count > 0:
            self.filter_cache.clear()
            await ctx.send(f"Removed {count} filter(s) from {target} target.")
        else:
            await ctx.send(
                f"No filters found for that {target} target.", ephemeral=True
            )

    @react_group.command(name="add", description="Add an auto-reaction rule.")
    @commands.has_permissions(manage_messages=True)
    @app_commands.describe(
        target="What type to target.",
        target_id="ID, name, or mention of the target. (for channel/user/role)",
        trigger_type="Trigger type.",
        pattern="Pattern to match.",
        emoji="Emoji to react with. (unicode or <:name:id>)",
    )
    async def react_add(
        self,
        ctx,
        target: Literal["server", "channel", "user", "role"],
        target_id: Optional[str] = None,
        trigger_type: Literal["regex", "word", "link"] = "word",
        pattern: Optional[str] = None,
        emoji: str = "👍",
    ):
        await ctx.typing()
        if not pattern:
            return await ctx.send("Pattern required.", ephemeral=True)
        resolved_target_id, target_name = None, "server-wide"
        if target == "server":
            pass
        elif target == "channel":
            try:
                ch = await commands.TextChannelConverter().convert(ctx, target_id)
                resolved_target_id = ch.id
                target_name = ch.mention
            except Exception:
                return await ctx.send(f"Invalid channel: {target_id}", ephemeral=True)
        elif target == "user":
            try:
                u = await commands.UserConverter().convert(ctx, target_id)
                resolved_target_id = u.id
                target_name = u.mention
            except Exception:
                return await ctx.send(f"Invalid user: {target_id}", ephemeral=True)
        elif target == "role":
            try:
                r = await commands.RoleConverter().convert(ctx, target_id)
                resolved_target_id = r.id
                target_name = r.mention
            except Exception:
                return await ctx.send(f"Invalid role: {target_id}", ephemeral=True)

        if trigger_type in ("word", "link"):
            pattern = ",".join(
                w.strip().lower() for w in pattern.split(",") if w.strip()
            )
        rid = await self.get_next_reaction_id(ctx.guild.id)
        try:
            await self.db.execute(
                """INSERT INTO chat_reactions
                    (reaction_id, guild_id, trigger_type, pattern, emoji, target_type, target_id, added_by)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                rid,
                ctx.guild.id,
                trigger_type,
                pattern,
                emoji,
                target,
                resolved_target_id,
                ctx.author.id,
            )
            self.react_cache.clear()
            await ctx.send(f"Added react rule `#{rid}` for {target_name} -> `{emoji}`")
        except Exception as e:
            await ctx.send(f"Failed: {e}")

    @react_group.command(
        name="list", description="List auto-reaction rules.", aliases=["ls"]
    )
    @commands.has_permissions(manage_messages=True)
    async def react_list(self, ctx):
        await ctx.typing()
        rows = await self.db.fetch(
            "SELECT * FROM chat_reactions WHERE guild_id = $1 ORDER BY created_at DESC",
            ctx.guild.id,
        )
        if not rows:
            return await ctx.send("No react rules set.", ephemeral=True)
        e = discord.Embed(
            title=f"Auto-Reactions ({len(rows)})", color=discord.Color.gold()
        )
        for r in rows:
            target = (
                "Server-wide"
                if r["target_type"] == "server"
                else f"{ctx.guild.get_channel(r['target_id']).mention if r['target_type'] == 'channel' else ctx.guild.get_member(r['target_id']).mention if r['target_type'] == 'user' else ctx.guild.get_role(r['target_id']).mention}"
            )
            e.add_field(
                name=f"`#{r['reaction_id']}` {r['trigger_type']} -> {r['emoji']}",
                value=f"**Target:** {target}\n**Pattern:** `{r['pattern'][:40]}`",
                inline=False,
            )
        await ctx.send(embed=e)

    @react_group.command(
        name="remove", description="Remove a react rule by ID.", aliases=["rm"]
    )
    @app_commands.describe(rule_id="The react rule ID to remove.")
    @commands.has_permissions(manage_messages=True)
    async def react_remove(self, ctx, rule_id: int):
        await ctx.typing()
        res = await self.db.fetchrow(
            "DELETE FROM chat_reactions WHERE guild_id = $1 AND reaction_id = $2 RETURNING target_type",
            ctx.guild.id,
            rule_id,
        )
        if res:
            self.react_cache.clear()
            await ctx.send(f"Removed react rule `#{rule_id}` ({res['target_type']}).")
        else:
            await ctx.send(f"No rule `#{rule_id}` found.", ephemeral=True)

    @react_group.command(
        name="clear", description="Clear all react rules for a target."
    )
    @app_commands.describe(
        target="What type to target.",
        target_id="ID, name, or mention of the target. (for channel/user/role)",
    )
    @commands.has_permissions(manage_messages=True)
    async def react_clear(
        self,
        ctx,
        target: Literal["server", "channel", "user", "role"],
        target_id: Optional[str] = None,
    ):
        await ctx.typing()
        resolved = None
        if target in ("channel", "user", "role") and target_id:
            try:
                conv = (
                    commands.TextChannelConverter()
                    if target == "channel"
                    else commands.UserConverter()
                    if target == "user"
                    else commands.RoleConverter()
                )
                obj = await conv.convert(ctx, target_id)
                resolved = obj.id
            except Exception:
                return await ctx.send(f"Invalid {target}: {target_id}", ephemeral=True)
        res = await self.db.execute(
            "DELETE FROM chat_reactions WHERE guild_id = $1 AND target_type = $2 AND (target_id = $3 OR (target_id IS NULL AND $3 IS NULL))",
            ctx.guild.id,
            target,
            resolved,
        )
        cnt = int(res.split()[1]) if res.startswith("DELETE") else 0
        if cnt > 0:
            self.react_cache.clear()
            await ctx.send(f"Cleared {cnt} react rule(s).")
        else:
            await ctx.send("No rules found.", ephemeral=True)

    @reply_group.command(name="add", description="Add an auto-reply rule.")
    @commands.has_permissions(manage_messages=True)
    @app_commands.describe(
        target="What type to target.",
        target_id="ID, name, or mention of the target. (for channel/user/role)",
        trigger_type="Trigger type.",
        pattern="Pattern to match.",
        response_message="Reply message. (supports TagScript.)",
        delete_after="Seconds to auto-delete reply. (0 = keep forever)",
    )
    async def reply_add(
        self,
        ctx,
        target: Literal["server", "channel", "user", "role"],
        target_id: Optional[str] = None,
        trigger_type: Literal["regex", "word", "link"] = "word",
        pattern: Optional[str] = None,
        response_message: Optional[str] = None,
        delete_after: int = 10,
    ):
        await ctx.typing()
        if not pattern or not response_message:
            return await ctx.send(
                "Pattern and response message required.", ephemeral=True
            )
        resolved_target_id, target_name = None, "server-wide"
        if target == "server":
            pass
        elif target == "channel":
            try:
                ch = await commands.TextChannelConverter().convert(ctx, target_id)
                resolved_target_id = ch.id
                target_name = ch.mention
            except Exception:
                return await ctx.send(f"Invalid channel: {target_id}", ephemeral=True)
        elif target == "user":
            try:
                u = await commands.UserConverter().convert(ctx, target_id)
                resolved_target_id = u.id
                target_name = u.mention
            except Exception:
                return await ctx.send(f"Invalid user: {target_id}", ephemeral=True)
        elif target == "role":
            try:
                r = await commands.RoleConverter().convert(ctx, target_id)
                resolved_target_id = r.id
                target_name = r.mention
            except Exception:
                return await ctx.send(f"Invalid role: {target_id}", ephemeral=True)

        if trigger_type in ("word", "link"):
            pattern = ",".join(
                w.strip().lower() for w in pattern.split(",") if w.strip()
            )
        rid = await self.get_next_reply_id(ctx.guild.id)
        try:
            await self.db.execute(
                """INSERT INTO chat_replies
                (reply_id, guild_id, trigger_type, pattern, response_message, target_type, target_id, delete_after, added_by)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                rid,
                ctx.guild.id,
                trigger_type,
                pattern,
                response_message,
                target,
                resolved_target_id,
                delete_after,
                ctx.author.id,
            )
            self.reply_cache.clear()
            await ctx.send(
                f"Added reply rule `#{rid}` for {target_name}\nAuto-delete: {'Disabled' if delete_after == 0 else f'{delete_after}s'}"
            )
        except Exception as e:
            await ctx.send(f"Failed: {e}")

    @reply_group.command(
        name="list", description="List auto-reply rules.", aliases=["ls"]
    )
    @commands.has_permissions(manage_messages=True)
    async def reply_list(self, ctx):
        await ctx.typing()
        rows = await self.db.fetch(
            "SELECT * FROM chat_replies WHERE guild_id = $1 ORDER BY created_at DESC",
            ctx.guild.id,
        )
        if not rows:
            return await ctx.send("No reply rules set.", ephemeral=True)
        e = discord.Embed(
            title=f"Auto-Replies ({len(rows)})", color=discord.Color.teal()
        )
        for r in rows:
            target = (
                "Server-wide"
                if r["target_type"] == "server"
                else f"{ctx.guild.get_channel(r['target_id']).mention if r['target_type'] == 'channel' else ctx.guild.get_member(r['target_id']).mention if r['target_type'] == 'user' else ctx.guild.get_role(r['target_id']).mention}"
            )
            del_status = (
                "Keep Forever"
                if r.get("delete_after") == 0
                else f"{r['delete_after']}s"
            )
            e.add_field(
                name=f"`#{r['reply_id']}` {r['trigger_type']}",
                value=f"**Target:** {target}\n**Pattern:** `{r['pattern'][:40]}`\n**Reply:** `{r['response_message'][:30]}...`\n**Auto-Delete:** {del_status}",
                inline=False,
            )
        await ctx.send(embed=e)

    @reply_group.command(
        name="remove", description="Remove a reply rule by ID.", aliases=["rm"]
    )
    @app_commands.describe(rule_id="The reply rule ID to remove.")
    @commands.has_permissions(manage_messages=True)
    async def reply_remove(self, ctx, rule_id: int):
        await ctx.typing()
        res = await self.db.fetchrow(
            "DELETE FROM chat_replies WHERE guild_id = $1 AND reply_id = $2 RETURNING target_type",
            ctx.guild.id,
            rule_id,
        )
        if res:
            self.reply_cache.clear()
            await ctx.send(f"Removed reply rule `#{rule_id}` ({res['target_type']}).")
        else:
            await ctx.send(f"No rule `#{rule_id}` found.", ephemeral=True)

    @reply_group.command(
        name="clear", description="Clear all reply rules for a target."
    )
    @app_commands.describe(
        target="What type to target.",
        target_id="ID, name, or mention of the target. (for channel/user/role)",
    )
    @commands.has_permissions(manage_messages=True)
    async def reply_clear(
        self,
        ctx,
        target: Literal["server", "channel", "user", "role"],
        target_id: Optional[str] = None,
    ):
        await ctx.typing()
        resolved = None
        if target in ("channel", "user", "role") and target_id:
            try:
                conv = (
                    commands.TextChannelConverter()
                    if target == "channel"
                    else commands.UserConverter()
                    if target == "user"
                    else commands.RoleConverter()
                )
                obj = await conv.convert(ctx, target_id)
                resolved = obj.id
            except Exception:
                return await ctx.send(f"Invalid {target}: {target_id}", ephemeral=True)
        res = await self.db.execute(
            "DELETE FROM chat_replies WHERE guild_id=$1 AND target_type=$2 AND (target_id=$3 OR (target_id IS NULL AND $3 IS NULL))",
            ctx.guild.id,
            target,
            resolved,
        )
        cnt = int(res.split()[1]) if res.startswith("DELETE") else 0
        if cnt > 0:
            self.reply_cache.clear()
            await ctx.send(f"Cleared {cnt} reply rule(s).")
        else:
            await ctx.send("No rules found.", ephemeral=True)

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
        template="Custom TagScript template. (replaces default layout.)",
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
        template: Optional[str] = None,
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
                    include_channel_ids, exclude_channel_ids, added_by, created_at, template
                )
                VALUES ($1, $2, $3, $4, $5, $6, NOW(), $7)
                """,
                [
                    (
                        ctx.guild.id,
                        log_channel.id,
                        category,
                        include_channels_ids if include_channels_ids else None,
                        exclude_channels_ids if exclude_channels_ids else None,
                        ctx.author.id,
                        template,
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
            if template:
                response += f"\n**Custom template:** {template[:100]}"

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
                    if rule.get("template"):
                        settings.append("Custom template")

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

    async def _send_log(
        self,
        rules: List[dict],
        event_category: str,
        ctx_data: dict,
        default_view_builder: callable = None,
        default_container_builder: callable = None,
    ):
        already_sent: set[int] = set()

        for rule in rules:
            log_channel_id = rule["log_channel_id"]
            if log_channel_id in already_sent:
                continue

            channel = ctx_data.get("channel")
            if (
                channel
                and rule.get("exclude_channel_ids")
                and channel.id in rule["exclude_channel_ids"]
            ):
                continue
            if (
                channel
                and rule.get("include_channel_ids")
                and channel.id not in rule["include_channel_ids"]
            ):
                continue

            log_channel = self.bot.get_channel(log_channel_id)
            if not log_channel or not isinstance(log_channel, discord.TextChannel):
                continue

            if not log_channel.permissions_for(log_channel.guild.me).send_messages:
                continue

            try:
                if rule.get("template"):
                    text, embeds, view, files = await self._evaluate_tagscript(
                        rule["template"], ctx_data
                    )
                    if text.startswith("[TagScript Error: "):
                        await log_channel.send(text[:2000])
                        already_sent.add(log_channel_id)
                        continue
                    kwargs = {}
                    if text:
                        kwargs["content"] = text[:2000]
                    if embeds:
                        kwargs["embeds"] = embeds[:10]
                    if view:
                        kwargs["view"] = view
                    if files:
                        kwargs["files"] = files[:10]
                    if not kwargs:
                        await log_channel.send("Log template produced no output.")
                    else:
                        await log_channel.send(**kwargs)
                elif default_view_builder:
                    view = await default_view_builder()
                    await log_channel.send(view=view)
                elif default_container_builder:
                    container = await default_container_builder()
                    view = LogView(container)
                    await log_channel.send(view=view)
                else:
                    await log_channel.send(f"Log event: {event_category}")

                already_sent.add(log_channel_id)
            except discord.HTTPException as e:
                await log_channel.send(f"Log failed to send: {str(e)}")

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        moderator, reason = await self.get_moderator_from_audit_log(
            message.guild, message, discord.AuditLogAction.message_delete
        )

        author = message.author
        ts = discord.utils.utcnow()

        async def build_default_view():
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

            if message.message_snapshots:
                snapshot = message.message_snapshots[0]
                snap_components = []

                if snapshot.content:
                    snap_content = snapshot.content[:1900] + (
                        "..." if len(snapshot.content) > 1900 else ""
                    )
                    snap_components.append(
                        discord.ui.TextDisplay(
                            content=f"**Forwarded Content**\n>>> {snap_content}"
                        )
                    )

                if snapshot.attachments:
                    snap_components.extend(
                        self._attachment_components(
                            snapshot.attachments, label_prefix="Forwarded Attachment"
                        )
                    )

                if snapshot.embeds:
                    rich = [e for e in snapshot.embeds if e.type == "rich"]
                    if rich:
                        e0 = rich[0]
                        parts = [
                            f"**Forwarded Embed(s):** {len(snapshot.embeds)} total"
                        ]
                        if e0.title:
                            parts.append(f"**Title:** {e0.title[:100]}")
                        if e0.description:
                            parts.append(
                                f"**Description:** {e0.description[:100]}{'...' if len(e0.description) > 100 else ''}"
                            )
                        if e0.url:
                            parts.append(f"**URL:** [Link]({e0.url})")

                        snap_components.append(
                            discord.ui.TextDisplay(content="\n".join(parts))
                        )

                if snap_components:
                    components.extend(snap_components)

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
            return LogView(container)

        try:
            rules = await self.db.fetch(
                "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                message.guild.id,
                "message",
            )

            ctx_data = {
                "author": message.author,
                "guild": message.guild,
                "channel": message.channel,
                "message": message,
                "moderator": moderator,
                "reason": reason,
                "deleted_at": ts,
                "message_id": message.id,
                "jump_url": message.jump_url,
                "event": "message_delete",
            }

            await self._send_log(
                rules, "message", ctx_data, default_view_builder=build_default_view
            )
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

        async def build_default_view():
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
                            line = f"Embed {i + 1}: "
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
            return LogView(container)

        try:
            rules = await self.db.fetch(
                "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                before.guild.id,
                "message",
            )

            ctx_data = {
                "author": before.author,
                "guild": before.guild,
                "channel": before.channel,
                "before_message": before,
                "after_message": after,
                "edited_at": ts,
                "message_id": before.id,
                "jump_url": after.jump_url,
                "event": "message_edit",
            }

            await self._send_log(
                rules, "message", ctx_data, default_view_builder=build_default_view
            )
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        ts = discord.utils.utcnow()

        async def build_default_view():
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
            return LogView(container)

        try:
            rules = await self.db.fetch(
                "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                member.guild.id,
                "member",
            )

            ctx_data = {
                "member": member,
                "guild": member.guild,
                "joined_at": ts,
                "account_created": member.created_at,
                "event": "member_join",
            }

            await self._send_log(
                rules, "member", ctx_data, default_view_builder=build_default_view
            )
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

        async def build_default_view():
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
            return LogView(container)

        try:
            rules = await self.db.fetch(
                "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                member.guild.id,
                "member",
            )

            ctx_data = {
                "member": member,
                "guild": member.guild,
                "moderator": moderator,
                "reason": reason,
                "was_kicked": was_kicked,
                "left_at": ts,
                "roles": roles,
                "event": "member_remove",
            }

            await self._send_log(
                rules, "member", ctx_data, default_view_builder=build_default_view
            )
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        ts = discord.utils.utcnow()

        if before.nick != after.nick:
            moderator, reason = await self.get_moderator_from_audit_log(
                after.guild, after, discord.AuditLogAction.member_update
            )

            async def build_default_view():
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
                return LogView(container)

            try:
                rules = await self.db.fetch(
                    "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                    after.guild.id,
                    "member",
                )

                ctx_data = {
                    "member": after,
                    "guild": after.guild,
                    "before_nick": before.nick,
                    "after_nick": after.nick,
                    "moderator": moderator,
                    "reason": reason,
                    "changed_at": ts,
                    "event": "member_nickname_change",
                }

                await self._send_log(
                    rules, "member", ctx_data, default_view_builder=build_default_view
                )
            except Exception:
                pass

        if before.roles != after.roles:
            added_roles = [role for role in after.roles if role not in before.roles]
            removed_roles = [role for role in before.roles if role not in after.roles]
            if added_roles or removed_roles:

                async def build_default_view():
                    lines = [
                        f"**Member:** {after.mention} (`{after}` - ID: `{after.id}`)"
                    ]
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
                        discord.ui.TextDisplay(
                            content=f"-# <t:{int(ts.timestamp())}:f>"
                        ),
                    ]

                    container = discord.ui.Container(
                        *components,
                        accent_color=discord.Color.blue(),
                    )
                    return LogView(container)

                try:
                    rules = await self.db.fetch(
                        "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                        after.guild.id,
                        "member",
                    )

                    ctx_data = {
                        "member": after,
                        "guild": after.guild,
                        "added_roles": added_roles,
                        "removed_roles": removed_roles,
                        "updated_at": ts,
                        "event": "member_roles_update",
                    }

                    await self._send_log(
                        rules,
                        "member",
                        ctx_data,
                        default_view_builder=build_default_view,
                    )
                except Exception:
                    pass

        if before.guild_avatar != after.guild_avatar:

            async def build_default_view():
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
                return LogView(container)

            try:
                rules = await self.db.fetch(
                    "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                    after.guild.id,
                    "member",
                )

                ctx_data = {
                    "member": after,
                    "guild": after.guild,
                    "before_avatar": before.guild_avatar,
                    "after_avatar": after.guild_avatar,
                    "updated_at": ts,
                    "event": "member_avatar_change",
                }

                await self._send_log(
                    rules, "member", ctx_data, default_view_builder=build_default_view
                )
            except Exception:
                pass

        if before.premium_since is None and after.premium_since is not None:

            async def build_default_view():
                components = [
                    discord.ui.TextDisplay(content="## Member Started Boosting"),
                    discord.ui.Section(
                        discord.ui.TextDisplay(
                            content=f"**Member:** {after.mention} (`{after}` - ID: `{after.id}`)"
                        ),
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
                    accent_color=discord.Color.gold(),
                )
                return LogView(container)

            try:
                rules = await self.db.fetch(
                    "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                    after.guild.id,
                    "member",
                )

                ctx_data = {
                    "member": after,
                    "guild": after.guild,
                    "boosted_at": ts,
                    "event": "member_boost_start",
                }

                await self._send_log(
                    rules, "member", ctx_data, default_view_builder=build_default_view
                )
            except Exception:
                pass

        elif before.premium_since is not None and after.premium_since is None:

            async def build_default_view():
                components = [
                    discord.ui.TextDisplay(content="## Member Stopped Boosting"),
                    discord.ui.Section(
                        discord.ui.TextDisplay(
                            content=f"**Member:** {after.mention} (`{after}` - ID: `{after.id}`)"
                        ),
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
                    accent_color=discord.Color.orange(),
                )
                return LogView(container)

            try:
                rules = await self.db.fetch(
                    "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                    after.guild.id,
                    "member",
                )

                ctx_data = {
                    "member": after,
                    "guild": after.guild,
                    "stopped_at": ts,
                    "event": "member_boost_stop",
                }

                await self._send_log(
                    rules, "member", ctx_data, default_view_builder=build_default_view
                )
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

            async def build_default_view():
                lines = [f"**User:** {after.mention} (`{after}` - ID: `{after.id}`)"]
                if (
                    before.name != after.name
                    or before.discriminator != after.discriminator
                ):
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
                return LogView(container)

            try:
                rules = await self.db.fetch(
                    "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                    guild.id,
                    "user",
                )

                ctx_data = {
                    "user": after,
                    "guild": guild,
                    "before_user": before,
                    "after_user": after,
                    "updated_at": ts,
                    "event": "user_update",
                }

                await self._send_log(
                    rules, "user", ctx_data, default_view_builder=build_default_view
                )
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

        async def build_default_view():
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
            return LogView(container)

        try:
            rules = await self.db.fetch(
                "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                guild.id,
                "moderation",
            )

            ctx_data = {
                "user": user,
                "guild": guild,
                "moderator": moderator,
                "reason": reason,
                "banned_at": ts,
                "event": "member_ban",
            }

            await self._send_log(
                rules, "moderation", ctx_data, default_view_builder=build_default_view
            )
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        moderator, reason = await self.get_moderator_from_audit_log(
            guild, user, discord.AuditLogAction.unban
        )
        ts = discord.utils.utcnow()

        async def build_default_view():
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
            return LogView(container)

        try:
            rules = await self.db.fetch(
                "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                guild.id,
                "moderation",
            )

            ctx_data = {
                "user": user,
                "guild": guild,
                "moderator": moderator,
                "reason": reason,
                "unbanned_at": ts,
                "event": "member_unban",
            }

            await self._send_log(
                rules, "moderation", ctx_data, default_view_builder=build_default_view
            )
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        moderator, reason = await self.get_moderator_from_audit_log(
            channel.guild, channel, discord.AuditLogAction.channel_create
        )
        ts = discord.utils.utcnow()

        async def build_default_view():
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
            return LogView(container)

        try:
            rules = await self.db.fetch(
                "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                channel.guild.id,
                "channel",
            )

            ctx_data = {
                "channel": channel,
                "guild": channel.guild,
                "moderator": moderator,
                "reason": reason,
                "created_at": ts,
                "event": "channel_create",
            }

            await self._send_log(
                rules, "channel", ctx_data, default_view_builder=build_default_view
            )
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        moderator, reason = await self.get_moderator_from_audit_log(
            channel.guild, channel, discord.AuditLogAction.channel_delete
        )
        ts = discord.utils.utcnow()

        async def build_default_view():
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
            return LogView(container)

        try:
            rules = await self.db.fetch(
                "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                channel.guild.id,
                "channel",
            )

            ctx_data = {
                "channel": channel,
                "guild": channel.guild,
                "moderator": moderator,
                "reason": reason,
                "deleted_at": ts,
                "event": "channel_delete",
            }

            await self._send_log(
                rules, "channel", ctx_data, default_view_builder=build_default_view
            )
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

            async def build_default_view():
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
                return LogView(container)

            try:
                rules = await self.db.fetch(
                    "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                    after.guild.id,
                    "channel",
                )

                ctx_data = {
                    "before_channel": before,
                    "after_channel": after,
                    "guild": after.guild,
                    "moderator": moderator,
                    "reason": reason,
                    "updated_at": ts,
                    "event": "channel_update",
                }

                await self._send_log(
                    rules, "channel", ctx_data, default_view_builder=build_default_view
                )
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        moderator, reason = await self.get_moderator_from_audit_log(
            role.guild, role, discord.AuditLogAction.role_create
        )
        ts = discord.utils.utcnow()
        perms = [perm for perm, value in role.permissions if value]

        async def build_default_view():
            detail = (
                f"**Role:** {role.mention} - ID: `{role.id}`\n**Color:** {role.color}"
            )
            if moderator:
                detail += f"\n**Created by:** {moderator.mention} (`{moderator}`)"
            if reason:
                detail += f"\n**Reason:** {reason[:400]}"
            if perms:
                perms_str = ", ".join(
                    perm.replace("_", " ").title() for perm in perms[:10]
                )
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
            return LogView(container)

        try:
            rules = await self.db.fetch(
                "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                role.guild.id,
                "role",
            )

            ctx_data = {
                "role": role,
                "guild": role.guild,
                "moderator": moderator,
                "reason": reason,
                "permissions": perms,
                "created_at": ts,
                "event": "role_create",
            }

            await self._send_log(
                rules, "role", ctx_data, default_view_builder=build_default_view
            )
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        moderator, reason = await self.get_moderator_from_audit_log(
            role.guild, role, discord.AuditLogAction.role_delete
        )
        ts = discord.utils.utcnow()

        async def build_default_view():
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
            return LogView(container)

        try:
            rules = await self.db.fetch(
                "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                role.guild.id,
                "role",
            )

            ctx_data = {
                "role": role,
                "guild": role.guild,
                "moderator": moderator,
                "reason": reason,
                "deleted_at": ts,
                "event": "role_delete",
            }

            await self._send_log(
                rules, "role", ctx_data, default_view_builder=build_default_view
            )
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

        async def build_default_view():
            detail = f"**Role:** {after.mention} - ID: `{after.id}`\n" + "\n".join(
                changes
            )
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
            return LogView(container)

        try:
            rules = await self.db.fetch(
                "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                after.guild.id,
                "role",
            )

            ctx_data = {
                "before_role": before,
                "after_role": after,
                "guild": after.guild,
                "moderator": moderator,
                "reason": reason,
                "changes": changes,
                "updated_at": ts,
                "event": "role_update",
            }

            await self._send_log(
                rules, "role", ctx_data, default_view_builder=build_default_view
            )
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

        def make_default_components(title: str, color: discord.Color, detail: str):
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

            async def build_default_view():
                detail = f"{member_str}\n**Channel:** {after.channel.mention}"
                components = make_default_components(
                    "Voice Channel Joined", discord.Color.green(), detail
                )
                container = discord.ui.Container(
                    *components,
                    accent_color=discord.Color.green(),
                )
                return LogView(container)

            try:
                rules = await self.db.fetch(
                    "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                    member.guild.id,
                    "voice",
                )

                ctx_data = {
                    "member": member,
                    "guild": member.guild,
                    "before_channel": before.channel,
                    "after_channel": after.channel,
                    "joined_at": ts,
                    "event": "voice_join",
                }

                await self._send_log(
                    rules, "voice", ctx_data, default_view_builder=build_default_view
                )
            except Exception:
                pass

        elif before.channel and not after.channel:

            async def build_default_view():
                detail = f"{member_str}\n**Channel:** {before.channel.mention}"
                components = make_default_components(
                    "Voice Channel Left", discord.Color.red(), detail
                )
                container = discord.ui.Container(
                    *components,
                    accent_color=discord.Color.red(),
                )
                return LogView(container)

            try:
                rules = await self.db.fetch(
                    "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                    member.guild.id,
                    "voice",
                )

                ctx_data = {
                    "member": member,
                    "guild": member.guild,
                    "before_channel": before.channel,
                    "after_channel": after.channel,
                    "left_at": ts,
                    "event": "voice_leave",
                }

                await self._send_log(
                    rules, "voice", ctx_data, default_view_builder=build_default_view
                )
            except Exception:
                pass

        elif before.channel and after.channel and before.channel != after.channel:

            async def build_default_view():
                detail = f"{member_str}\n**From:** {before.channel.mention} -> **To:** {after.channel.mention}"
                components = make_default_components(
                    "Voice Channel Moved", discord.Color.blue(), detail
                )
                container = discord.ui.Container(
                    *components,
                    accent_color=discord.Color.blue(),
                )
                return LogView(container)

            try:
                rules = await self.db.fetch(
                    "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                    member.guild.id,
                    "voice",
                )

                ctx_data = {
                    "member": member,
                    "guild": member.guild,
                    "before_channel": before.channel,
                    "after_channel": after.channel,
                    "moved_at": ts,
                    "event": "voice_move",
                }

                await self._send_log(
                    rules, "voice", ctx_data, default_view_builder=build_default_view
                )
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

            async def build_default_view():
                detail = f"{member_str}\n**Channel:** {channel_ref}\n" + "\n".join(
                    changes
                )
                if final_moderator:
                    detail += f"\n**Action by:** {final_moderator.mention} (`{final_moderator}`)"
                if final_reason:
                    detail += f"\n**Reason:** {final_reason[:400]}"

                components = make_default_components(
                    "Voice State Updated", discord.Color.orange(), detail
                )
                container = discord.ui.Container(
                    *components,
                    accent_color=discord.Color.orange(),
                )
                return LogView(container)

            try:
                rules = await self.db.fetch(
                    "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                    member.guild.id,
                    "voice",
                )

                ctx_data = {
                    "member": member,
                    "guild": member.guild,
                    "before_state": before,
                    "after_state": after,
                    "moderator": final_moderator,
                    "reason": final_reason,
                    "changes": changes,
                    "updated_at": ts,
                    "event": "voice_state_update",
                }

                await self._send_log(
                    rules, "voice", ctx_data, default_view_builder=build_default_view
                )
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

        async def build_default_view():
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
            return LogView(container)

        try:
            rules = await self.db.fetch(
                "SELECT * FROM logging_rules WHERE guild_id = $1 AND event_category = $2",
                after.id,
                "guild",
            )

            ctx_data = {
                "before_guild": before,
                "after_guild": after,
                "moderator": moderator,
                "reason": reason,
                "changes": changes,
                "updated_at": ts,
                "event": "guild_update",
            }

            await self._send_log(
                rules, "guild", ctx_data, default_view_builder=build_default_view
            )
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        role_ids = [role.id for role in getattr(message.author, "roles", [])]

        slowmode = await self.get_slowmode_for_context(
            message.guild.id, message.channel.id, message.author.id, role_ids
        )

        if slowmode and not message.author.guild_permissions.bypass_slowmode:
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

                    if slowmode.get("custom_message"):
                        ctx_data = {
                            "author": message.author,
                            "guild": message.guild,
                            "channel": message.channel,
                            "slowmode_delay": slowmode["delay_seconds"],
                            "slowmode_rule_id": slowmode["slowmode_id"],
                            "message": message,
                        }
                        text, embeds, view, files = await self._evaluate_tagscript(
                            slowmode["custom_message"], ctx_data
                        )
                        kwargs = {}
                        if text:
                            kwargs["content"] = text[:2000]
                        if embeds:
                            kwargs["embeds"] = embeds[:10]
                        if view:
                            kwargs["view"] = view
                        if files:
                            kwargs["files"] = files[:10]
                        await message.channel.send(
                            delete_after=10,
                            **kwargs,
                        )
                    else:
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
        if filters and not message.author.guild_permissions.manage_messages:
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
                        if self.check_forbidden_links(
                            message.content, filter["pattern"]
                        ):
                            await self.handle_filter_trigger(filter, message)
                except Exception:
                    pass

        reactions = await self.get_reactions_for_context(
            message.guild.id, message.channel.id, message.author.id, role_ids
        )
        if reactions:
            for r in reactions:
                try:
                    match = False
                    if r["trigger_type"] == "regex" and re.search(
                        r["pattern"], message.content, re.IGNORECASE
                    ):
                        match = True
                    elif r["trigger_type"] == "word" and any(
                        w.lower() in message.content.lower()
                        for w in r["pattern"].split(",")
                    ):
                        match = True
                    elif r["trigger_type"] == "link" and self.check_forbidden_links(
                        message.content, r["pattern"]
                    ):
                        match = True
                    if match:
                        await self.handle_react_trigger(r, message)
                except Exception:
                    pass

        replies = await self.get_replies_for_context(
            message.guild.id, message.channel.id, message.author.id, role_ids
        )
        if replies:
            for r in replies:
                try:
                    match = False
                    if r["trigger_type"] == "regex" and re.search(
                        r["pattern"], message.content, re.IGNORECASE
                    ):
                        match = True
                    elif r["trigger_type"] == "word" and any(
                        w.lower() in message.content.lower()
                        for w in r["pattern"].split(",")
                    ):
                        match = True
                    elif r["trigger_type"] == "link" and self.check_forbidden_links(
                        message.content, r["pattern"]
                    ):
                        match = True
                    if match:
                        await self.handle_reply_trigger(r, message)
                except Exception:
                    pass

    def check_forbidden_links(self, content: str, pattern: str) -> bool:
        forbidden = [d.strip().lower() for d in pattern.split(",") if d.strip()]

        urls = re.findall(
            r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+(?:/[^\s<>"\']*)?',
            content,
            re.IGNORECASE,
        )
        domains = re.findall(
            r'(?:^|\s)(?:[\w-]+\.)+[\w-]{2,}(?:\.[\w-]+)*(?:/[^\s<>"\']*)?(?=\s|$|\.\s)',
            content,
        )

        obfuscated = re.findall(
            r"(?:[\w-]+)\s*[\[\(\{]?\s*[.]\s*[\]\)\}]?\s*[\w-]+", content
        )
        for obs in obfuscated:
            clean = (
                re.sub(r"[\[\](){}]", "", obs).replace("•", ".").replace(" dot ", ".")
            )
            clean = re.sub(r"\s+", ".", clean)
            if "." in clean:
                domains.append(clean)

        for url in urls + domains:
            try:
                parsed = urlparse(url if "://" in url else f"http://{url}")
                domain = parsed.netloc.lower()
                if domain.startswith("www."):
                    domain = domain[4:]

                for f in forbidden:
                    if domain == f or domain.endswith(f".{f}") or f in url.lower():
                        return True
            except Exception:
                if any(f in url.lower() for f in forbidden):
                    return True

        return False

    @commands.hybrid_group(
        name="slowmode", description="Set manual slowmode on any target."
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    async def slowmode_group(self, ctx: commands.Context):
        return

    @slowmode_group.command(
        name="add", description="Add or update a manual slowmode rule for a target."
    )
    @commands.has_permissions(manage_channels=True)
    @app_commands.describe(
        target="Type of target.",
        target_id="ID or mention of the target. (required for channel, user, role)",
        delay="Slowmode delay in seconds. (0 to disable)",
        custom_message="Custom message sent when slowmode is triggered. (supports TagScript.)",
    )
    async def slowmode_add(
        self,
        ctx: commands.Context,
        target: Literal["server", "channel", "user", "role"],
        target_id: Optional[str] = None,
        delay: int = 0,
        custom_message: Optional[str] = None,
    ):
        await ctx.typing()

        resolved_target_id = None
        if target == "server":
            resolved_target_id = None
        elif target == "channel":
            try:
                channel = await commands.TextChannelConverter().convert(ctx, target_id)
                resolved_target_id = channel.id
            except Exception:
                await ctx.send(f"Invalid channel: {target_id}", ephemeral=True)
                return
        elif target == "user":
            try:
                user = await commands.UserConverter().convert(ctx, target_id)
                resolved_target_id = user.id
            except Exception:
                await ctx.send(f"Invalid user: {target_id}", ephemeral=True)
                return
        elif target == "role":
            try:
                role = await commands.RoleConverter().convert(ctx, target_id)
                resolved_target_id = role.id
            except Exception:
                await ctx.send(f"Invalid role: {target_id}", ephemeral=True)
                return

        await self._set_slowmode(ctx, target, resolved_target_id, delay, custom_message)

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
                name=f"ID `{r['slowmode_id']}`",
                value=(
                    f"**Target:** {target}\n"
                    f"**Delay:** {r['delay_seconds']} second(s)\n"
                    f"**Added by:** <@{r['added_by']}>"
                    + ("\n**Custom Message:** Yes" if r.get("custom_message") else "")
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
            "DELETE FROM manual_slowmodes WHERE guild_id = $1 AND slowmode_id = $2 RETURNING *",
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
        custom_message: Optional[str] = None,
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
            existing = await self.db.fetchrow(
                "SELECT slowmode_id FROM manual_slowmodes WHERE guild_id = $1 AND channel_id = $2 AND user_id = $3 AND role_id = $4",
                ctx.guild.id,
                channel_id,
                user_id,
                role_id,
            )

            if existing:
                await self.db.execute(
                    """
                    UPDATE manual_slowmodes
                    SET delay_seconds = $1, enabled = $2, added_by = $3, added_at = NOW(), custom_message = $5
                    WHERE guild_id = $4 AND channel_id = $6 AND user_id = $7 AND role_id = $8
                    """,
                    delay,
                    enabled,
                    ctx.author.id,
                    ctx.guild.id,
                    custom_message,
                    channel_id,
                    user_id,
                    role_id,
                )
                slowmode_id = existing["slowmode_id"]
            else:
                slowmode_id = await self.get_next_slowmode_id(ctx.guild.id)
                await self.db.execute(
                    """
                    INSERT INTO manual_slowmodes (
                        slowmode_id, guild_id, channel_id, user_id, role_id,
                        delay_seconds, enabled, added_by, added_at, custom_message
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), $9)
                    """,
                    slowmode_id,
                    ctx.guild.id,
                    channel_id,
                    user_id,
                    role_id,
                    delay,
                    enabled,
                    ctx.author.id,
                    custom_message,
                )

            self.slowmode_cache.clear()

            target_name = {
                "server": "Server-wide",
                "channel": f"<#{target_id}>",
                "user": f"<@{target_id}>",
                "role": f"<@&{target_id}>",
            }[target_type]
            status = f"set to {delay}s" if enabled else "disabled"
            response = f"{target_name} slowmode {status}."
            if custom_message:
                response += f"\nCustom message: {custom_message[:100]}"
            await ctx.send(response)
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
