from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from dashboard import db

log = logging.getLogger(__name__)


class AuditLog(commands.Cog):
    """Log server events (edits, deletes, joins, leaves, role changes) to a configured channel."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cache: dict[str, dict] = {}

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
    ):
        gid = str(interaction.guild_id)
        await db.upsert_audit_config(
            gid,
            log_channel_id=str(channel.id),
            log_edits=int(edits),
            log_deletes=int(deletes),
            log_joins=int(joins),
            log_leaves=int(leaves),
            log_role_changes=int(role_changes),
        )
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
        embed = discord.Embed(title="Audit Log Config", color=0x3498DB)
        embed.add_field(name="Channel", value=f"<#{cfg['log_channel_id']}>")
        embed.add_field(name="Message Edits", value="Yes" if cfg.get("log_edits") else "No")
        embed.add_field(name="Message Deletes", value="Yes" if cfg.get("log_deletes") else "No")
        embed.add_field(name="Member Joins", value="Yes" if cfg.get("log_joins") else "No")
        embed.add_field(name="Member Leaves", value="Yes" if cfg.get("log_leaves") else "No")
        embed.add_field(name="Role Changes", value="Yes" if cfg.get("log_role_changes") else "No")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @auditlog_group.command(name="disable", description="Disable audit logging")
    async def auditlog_disable(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        await db.upsert_audit_config(gid, log_channel_id="")
        await self.refresh_cache()
        await interaction.response.send_message("Audit logging disabled.", ephemeral=True)

    # --- Listeners ---

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or not before.guild:
            return
        if before.content == after.content:
            return
        if not self._is_enabled(str(before.guild.id), "log_edits"):
            return
        channel = self._get_log_channel(before.guild)
        if not channel:
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

        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if not self._is_enabled(str(message.guild.id), "log_deletes"):
            return
        channel = self._get_log_channel(message.guild)
        if not channel:
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

        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not self._is_enabled(str(member.guild.id), "log_joins"):
            return
        channel = self._get_log_channel(member.guild)
        if not channel:
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

        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if not self._is_enabled(str(member.guild.id), "log_leaves"):
            return
        channel = self._get_log_channel(member.guild)
        if not channel:
            return

        embed = discord.Embed(
            title="Member Left",
            description=f"{member} left the server.",
            color=0xE74C3C,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"User ID: {member.id}")

        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if not self._is_enabled(str(before.guild.id), "log_role_changes"):
            return
        if before.roles == after.roles:
            return
        channel = self._get_log_channel(before.guild)
        if not channel:
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

        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(AuditLog(bot))
