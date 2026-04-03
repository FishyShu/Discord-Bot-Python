from __future__ import annotations

import logging
import re
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from dashboard import db

log = logging.getLogger(__name__)

# Max recent messages to cache per guild for ghost-ping detection
_GHOST_CACHE_SIZE = 500


class AuditLog(commands.Cog):
    """Log server events (edits, deletes, joins, leaves, role changes) to a configured channel."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cache: dict[str, dict] = {}
        # {guild_id: OrderedDict{msg_id: {"mentions": set_of_user_ids, "content": str}}}
        self._msg_mention_cache: dict[str, OrderedDict] = {}

    async def cog_load(self):
        await self.refresh_cache()

    async def refresh_cache(self):
        self._cache = await db.get_all_audit_configs()
        log.info("AuditLog cache refreshed: %d guild configs loaded", len(self._cache))

    def _get_log_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        cfg = self._cache.get(str(guild.id))
        if not cfg or not cfg.get("log_channel_id"):
            return None
        return guild.get_channel(int(cfg["log_channel_id"]))

    def _is_enabled(self, guild_id: str, event: str) -> bool:
        cfg = self._cache.get(guild_id)
        return bool(cfg and cfg.get(event))

    async def _send_log(self, guild: discord.Guild, embed: discord.Embed) -> None:
        """Send an embed to the log channel, using a webhook URL if configured."""
        cfg = self._cache.get(str(guild.id), {})
        webhook_url = cfg.get("audit_webhook_url") or await db.get_guild_setting(
            str(guild.id), "audit_webhook_url"
        )
        if webhook_url:
            try:
                async with aiohttp.ClientSession() as session:
                    wh = discord.Webhook.from_url(webhook_url, session=session)
                    await wh.send(embed=embed)
                return
            except Exception as exc:
                log.warning("Webhook delivery failed for guild %s: %s", guild.id, exc)
        channel = self._get_log_channel(guild)
        if channel:
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass

    def _track_mentions(self, message: discord.Message) -> None:
        if not message.guild:
            return
        gid = str(message.guild.id)
        if gid not in self._msg_mention_cache:
            self._msg_mention_cache[gid] = OrderedDict()
        cache = self._msg_mention_cache[gid]
        cache[str(message.id)] = {
            "mentions": {str(u.id) for u in message.mentions},
            "content": message.content,
        }
        # Trim to size
        while len(cache) > _GHOST_CACHE_SIZE:
            cache.popitem(last=False)

    # --- Slash commands ---

    auditlog_group = app_commands.Group(
        name="auditlog",
        description="Configure audit logging",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @auditlog_group.command(name="set", description="Configure audit log channel and events")
    @app_commands.describe(
        channel="Channel to send log messages to",
        edits="Log message edits",
        deletes="Log message deletes",
        joins="Log member joins",
        leaves="Log member leaves",
        role_changes="Log role changes",
        log_ghost_pings="Log ghost pings (mention removed after sending)",
        webhook_url="Optional webhook URL to route log messages through",
    )
    async def auditlog_set(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        edits: Optional[bool] = True,
        deletes: Optional[bool] = True,
        joins: Optional[bool] = True,
        leaves: Optional[bool] = True,
        role_changes: Optional[bool] = True,
        log_ghost_pings: Optional[bool] = False,
        webhook_url: Optional[str] = None,
    ):
        gid = str(interaction.guild_id)
        _WEBHOOK_RE = re.compile(r"^https://discord(?:app)?\.com/api/webhooks/\d+/[\w-]+$")
        if webhook_url is not None and not _WEBHOOK_RE.match(webhook_url):
            await interaction.response.send_message(
                "Invalid webhook URL. Must be a Discord webhook URL (https://discord.com/api/webhooks/...).",
                ephemeral=True,
            )
            return
        await db.upsert_audit_config(
            gid,
            log_channel_id=str(channel.id),
            log_edits=int(edits),
            log_deletes=int(deletes),
            log_joins=int(joins),
            log_leaves=int(leaves),
            log_role_changes=int(role_changes),
            log_ghost_pings=int(log_ghost_pings),
        )
        if webhook_url is not None:
            await db.set_guild_setting(gid, "audit_webhook_url", webhook_url)
        await self.refresh_cache()
        await interaction.response.send_message(
            f"Audit logging configured in {channel.mention}.", ephemeral=True
        )

    @auditlog_group.command(name="show", description="Show the current audit log configuration")
    async def auditlog_show(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        cfg = await db.get_audit_config(gid)
        if not cfg or not cfg.get("log_channel_id"):
            await interaction.response.send_message("Audit logging is not configured.", ephemeral=True)
            return
        webhook_url = await db.get_guild_setting(gid, "audit_webhook_url", "")
        embed = discord.Embed(title="Audit Log Config", color=0x3498DB)
        embed.add_field(name="Channel", value=f"<#{cfg['log_channel_id']}>")
        embed.add_field(name="Message Edits", value="Yes" if cfg.get("log_edits") else "No")
        embed.add_field(name="Message Deletes", value="Yes" if cfg.get("log_deletes") else "No")
        embed.add_field(name="Member Joins", value="Yes" if cfg.get("log_joins") else "No")
        embed.add_field(name="Member Leaves", value="Yes" if cfg.get("log_leaves") else "No")
        embed.add_field(name="Role Changes", value="Yes" if cfg.get("log_role_changes") else "No")
        embed.add_field(name="Ghost Pings", value="Yes" if cfg.get("log_ghost_pings") else "No")
        embed.add_field(name="Webhook URL", value=webhook_url or "*(not set)*", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @auditlog_group.command(name="disable", description="Disable audit logging")
    async def auditlog_disable(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        await db.upsert_audit_config(gid, log_channel_id="")
        await self.refresh_cache()
        await interaction.response.send_message("Audit logging disabled.", ephemeral=True)

    # --- Listeners ---

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        self._track_mentions(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or not before.guild:
            return

        gid = str(before.guild.id)

        # Ghost ping check
        if self._is_enabled(gid, "log_ghost_pings"):
            before_ids = {str(u.id) for u in before.mentions}
            after_ids = {str(u.id) for u in after.mentions}
            ghosted_ids = before_ids - after_ids
            if ghosted_ids:
                ghosted = [before.guild.get_member(int(uid)) or f"<@{uid}>" for uid in ghosted_ids]
                ghosted_str = ", ".join(
                    m.mention if isinstance(m, discord.Member) else m for m in ghosted
                )
                embed = discord.Embed(
                    title="👻 Ghost Ping Detected",
                    color=0x9B59B6,
                    timestamp=datetime.now(timezone.utc),
                )
                embed.set_author(name=str(before.author), icon_url=before.author.display_avatar.url)
                embed.add_field(name="Ghosted", value=ghosted_str, inline=False)
                embed.add_field(name="Channel", value=before.channel.mention)
                embed.add_field(
                    name="Jump to Message",
                    value=f"[Click here]({after.jump_url})",
                    inline=False,
                )
                embed.set_footer(text=f"Author ID: {before.author.id}")
                await self._send_log(before.guild, embed)

        # Update mention cache
        self._track_mentions(after)

        # Regular edit log
        if before.content == after.content:
            return
        if not self._is_enabled(gid, "log_edits"):
            return

        embed = discord.Embed(
            title="Message Edited",
            color=0xF39C12,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=str(before.author), icon_url=before.author.display_avatar.url)
        embed.add_field(name="Before", value=before.content[:1024] or "*empty*", inline=False)
        embed.add_field(name="After", value=after.content[:1024] or "*empty*", inline=False)
        embed.add_field(name="Channel", value=before.channel.mention)
        embed.set_footer(text=f"User ID: {before.author.id}")
        await self._send_log(before.guild, embed)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        gid = str(message.guild.id)

        # Ghost ping check
        if self._is_enabled(gid, "log_ghost_pings"):
            cache = self._msg_mention_cache.get(gid, {})
            cached_entry = cache.pop(str(message.id), None)
            if cached_entry is not None:
                cached_ids = cached_entry["mentions"]
                cached_content = cached_entry["content"]
            else:
                # Fall back to current mentions/content on the message object
                cached_ids = {str(u.id) for u in message.mentions}
                cached_content = message.content
            if cached_ids:
                ghosted = [message.guild.get_member(int(uid)) or f"<@{uid}>" for uid in cached_ids]
                ghosted_str = ", ".join(
                    m.mention if isinstance(m, discord.Member) else m for m in ghosted
                )
                embed = discord.Embed(
                    title="👻 Ghost Ping Detected",
                    color=0x9B59B6,
                    timestamp=datetime.now(timezone.utc),
                )
                embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
                embed.add_field(name="Ghosted", value=ghosted_str, inline=False)
                embed.add_field(name="Channel", value=message.channel.mention)
                embed.add_field(name="Original Message", value=cached_content[:512] or "*empty*", inline=False)
                embed.set_footer(text=f"Author ID: {message.author.id}")
                await self._send_log(message.guild, embed)
                return  # Don't double-log as a regular delete if it was a ghost ping

        if not self._is_enabled(gid, "log_deletes"):
            return

        embed = discord.Embed(
            title="Message Deleted",
            color=0xE74C3C,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
        embed.add_field(name="Content", value=message.content[:1024] or "*empty/embed*", inline=False)
        embed.add_field(name="Channel", value=message.channel.mention)
        embed.set_footer(text=f"User ID: {message.author.id}")
        await self._send_log(message.guild, embed)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not self._is_enabled(str(member.guild.id), "log_joins"):
            return

        embed = discord.Embed(
            title="Member Joined",
            description=f"{member.mention} ({member})",
            color=0x2ECC71,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Account Created", value=discord.utils.format_dt(member.created_at, "R"))
        embed.set_footer(text=f"User ID: {member.id}")
        await self._send_log(member.guild, embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if not self._is_enabled(str(member.guild.id), "log_leaves"):
            return

        embed = discord.Embed(
            title="Member Left",
            description=f"{member} left the server.",
            color=0xE74C3C,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"User ID: {member.id}")
        await self._send_log(member.guild, embed)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if not self._is_enabled(str(before.guild.id), "log_role_changes"):
            return
        if before.roles == after.roles:
            return

        added = set(after.roles) - set(before.roles)
        removed = set(before.roles) - set(after.roles)

        embed = discord.Embed(
            title="Member Roles Updated",
            color=0x3498DB,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=str(after), icon_url=after.display_avatar.url)
        if added:
            embed.add_field(name="Added", value=", ".join(r.mention for r in added), inline=False)
        if removed:
            embed.add_field(name="Removed", value=", ".join(r.mention for r in removed), inline=False)
        embed.set_footer(text=f"User ID: {after.id}")
        await self._send_log(after.guild, embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(AuditLog(bot))
