from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from dashboard import db

log = logging.getLogger(__name__)


class Moderation(commands.Cog):
    """Moderation commands with persistent warning history."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _post_audit(self, guild: discord.Guild, embed: discord.Embed) -> None:
        """Post to audit log channel if configured."""
        cfg = await db.get_audit_config(str(guild.id))
        if not cfg or not cfg.get("log_channel_id"):
            return
        channel = guild.get_channel(int(cfg["log_channel_id"]))
        if channel:
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass

    async def _dm(self, user: discord.User | discord.Member, embed: discord.Embed) -> None:
        try:
            await user.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    # --- Kick ---

    @app_commands.command(name="kick", description="Kick a member from the server")
    @app_commands.describe(member="Member to kick", reason="Reason for kick")
    @app_commands.default_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member,
                   reason: Optional[str] = None):
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message("I cannot kick this member (role hierarchy).", ephemeral=True)
            return
        dm_embed = discord.Embed(title=f"You were kicked from {interaction.guild.name}",
                                  color=0xE74C3C)
        dm_embed.add_field(name="Reason", value=reason or "No reason provided")
        await self._dm(member, dm_embed)
        await member.kick(reason=reason)
        embed = discord.Embed(title="Member Kicked", color=0xE74C3C,
                               timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Member", value=f"{member} ({member.id})")
        embed.add_field(name="Moderator", value=str(interaction.user))
        embed.add_field(name="Reason", value=reason or "No reason provided", inline=False)
        await self._post_audit(interaction.guild, embed)
        await db.add_modlog_entry(guild_id=str(interaction.guild_id), action="kick",
                                   user_id=str(member.id), moderator_id=str(interaction.user.id),
                                   reason=reason)
        await interaction.response.send_message(f"Kicked {member}.", ephemeral=True)

    # --- Ban ---

    @app_commands.command(name="ban", description="Ban a member from the server")
    @app_commands.describe(member="Member to ban", reason="Reason for ban",
                            delete_days="Days of messages to delete (0-7)")
    @app_commands.default_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member,
                  reason: Optional[str] = None, delete_days: int = 0):
        delete_days = max(0, min(7, delete_days))
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message("I cannot ban this member (role hierarchy).", ephemeral=True)
            return
        dm_embed = discord.Embed(title=f"You were banned from {interaction.guild.name}",
                                  color=0xE74C3C)
        dm_embed.add_field(name="Reason", value=reason or "No reason provided")
        await self._dm(member, dm_embed)
        await member.ban(reason=reason, delete_message_days=delete_days)
        embed = discord.Embed(title="Member Banned", color=0xE74C3C,
                               timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Member", value=f"{member} ({member.id})")
        embed.add_field(name="Moderator", value=str(interaction.user))
        embed.add_field(name="Reason", value=reason or "No reason provided", inline=False)
        await self._post_audit(interaction.guild, embed)
        await db.add_modlog_entry(guild_id=str(interaction.guild_id), action="ban",
                                   user_id=str(member.id), moderator_id=str(interaction.user.id),
                                   reason=reason)
        await interaction.response.send_message(f"Banned {member}.", ephemeral=True)

    # --- Unban ---

    @app_commands.command(name="unban", description="Unban a user by ID")
    @app_commands.describe(user_id="User ID to unban", reason="Reason for unban")
    @app_commands.default_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str,
                    reason: Optional[str] = None):
        try:
            uid = int(user_id)
        except ValueError:
            await interaction.response.send_message("Invalid user ID.", ephemeral=True)
            return
        try:
            ban_entry = await interaction.guild.fetch_ban(discord.Object(id=uid))
        except discord.NotFound:
            await interaction.response.send_message("That user is not banned.", ephemeral=True)
            return
        await interaction.guild.unban(ban_entry.user, reason=reason)
        embed = discord.Embed(title="Member Unbanned", color=0x2ECC71,
                               timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Member", value=f"{ban_entry.user} ({ban_entry.user.id})")
        embed.add_field(name="Moderator", value=str(interaction.user))
        await self._post_audit(interaction.guild, embed)
        await db.add_modlog_entry(guild_id=str(interaction.guild_id), action="unban",
                                   user_id=str(ban_entry.user.id), moderator_id=str(interaction.user.id),
                                   reason=reason)
        await interaction.response.send_message(f"Unbanned {ban_entry.user}.", ephemeral=True)

    # --- Softban ---

    @app_commands.command(name="softban", description="Ban then immediately unban (clears messages, no permanent ban)")
    @app_commands.describe(member="Member to softban", reason="Reason",
                            delete_days="Days of messages to delete (1-7, default 1)")
    @app_commands.default_permissions(ban_members=True)
    async def softban(self, interaction: discord.Interaction, member: discord.Member,
                      reason: Optional[str] = None, delete_days: int = 1):
        delete_days = max(1, min(7, delete_days))
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message("I cannot softban this member (role hierarchy).", ephemeral=True)
            return
        dm_embed = discord.Embed(title=f"You were softbanned from {interaction.guild.name}",
                                  color=0xE67E22)
        dm_embed.add_field(name="Reason", value=reason or "No reason provided")
        await self._dm(member, dm_embed)
        await member.ban(reason=f"Softban: {reason}", delete_message_days=delete_days)
        await interaction.guild.unban(member, reason="Softban — immediately unbanning")
        embed = discord.Embed(title="Member Softbanned", color=0xE67E22,
                               timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Member", value=f"{member} ({member.id})")
        embed.add_field(name="Moderator", value=str(interaction.user))
        embed.add_field(name="Reason", value=reason or "No reason provided", inline=False)
        await self._post_audit(interaction.guild, embed)
        await db.add_modlog_entry(guild_id=str(interaction.guild_id), action="softban",
                                   user_id=str(member.id), moderator_id=str(interaction.user.id),
                                   reason=reason)
        await interaction.response.send_message(f"Softbanned {member}.", ephemeral=True)

    # --- Timeout ---

    @app_commands.command(name="timeout", description="Timeout a member")
    @app_commands.describe(member="Member to timeout", duration="Duration (e.g. 10m, 1h, 1d)",
                            reason="Reason for timeout")
    @app_commands.default_permissions(moderate_members=True)
    async def timeout(self, interaction: discord.Interaction, member: discord.Member,
                      duration: str, reason: Optional[str] = None):
        from utils.time_parser import parse_duration
        seconds = parse_duration(duration)
        if not seconds or seconds <= 0:
            await interaction.response.send_message("Invalid duration. Use e.g. `10m`, `1h`, `2d`.", ephemeral=True)
            return
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message("I cannot timeout that member — their role is equal or higher than mine.", ephemeral=True)
            return
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            await interaction.response.send_message("You cannot timeout a member with an equal or higher role.", ephemeral=True)
            return
        until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        await member.timeout(until, reason=reason)
        dm_embed = discord.Embed(title=f"You were timed out in {interaction.guild.name}",
                                  color=0xF39C12)
        dm_embed.add_field(name="Duration", value=duration)
        dm_embed.add_field(name="Reason", value=reason or "No reason provided")
        await self._dm(member, dm_embed)
        embed = discord.Embed(title="Member Timed Out", color=0xF39C12,
                               timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Member", value=f"{member} ({member.id})")
        embed.add_field(name="Duration", value=duration)
        embed.add_field(name="Moderator", value=str(interaction.user))
        embed.add_field(name="Reason", value=reason or "No reason provided", inline=False)
        await self._post_audit(interaction.guild, embed)
        await db.add_modlog_entry(guild_id=str(interaction.guild_id), action="timeout",
                                   user_id=str(member.id), moderator_id=str(interaction.user.id),
                                   reason=reason, extra=duration)
        await interaction.response.send_message(f"Timed out {member} for {duration}.", ephemeral=True)

    # --- Warn ---

    @app_commands.command(name="warn", description="Add a warning to a member's record")
    @app_commands.describe(member="Member to warn", reason="Reason for warning")
    @app_commands.default_permissions(manage_messages=True)
    async def warn(self, interaction: discord.Interaction, member: discord.Member,
                   reason: Optional[str] = None):
        warning_id = await db.add_warning(
            guild_id=str(interaction.guild_id),
            user_id=str(member.id),
            moderator_id=str(interaction.user.id),
            reason=reason,
        )
        dm_embed = discord.Embed(title=f"You received a warning in {interaction.guild.name}",
                                  color=0xF39C12)
        dm_embed.add_field(name="Reason", value=reason or "No reason provided")
        dm_embed.set_footer(text=f"Warning ID: {warning_id}")
        await self._dm(member, dm_embed)
        embed = discord.Embed(title="Member Warned", color=0xF39C12,
                               timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Member", value=f"{member} ({member.id})")
        embed.add_field(name="Moderator", value=str(interaction.user))
        embed.add_field(name="Reason", value=reason or "No reason provided", inline=False)
        embed.set_footer(text=f"Warning ID: {warning_id}")
        await self._post_audit(interaction.guild, embed)
        await db.add_modlog_entry(guild_id=str(interaction.guild_id), action="warn",
                                   user_id=str(member.id), moderator_id=str(interaction.user.id),
                                   reason=reason, extra=str(warning_id))
        await interaction.response.send_message(
            f"Warning #{warning_id} added for {member}.", ephemeral=True
        )

    # --- Warnings ---

    @app_commands.command(name="warnings", description="List warnings for a member")
    @app_commands.describe(member="Member to check")
    @app_commands.default_permissions(manage_messages=True)
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        rows = await db.get_warnings(str(interaction.guild_id), str(member.id))
        if not rows:
            await interaction.response.send_message(f"{member} has no warnings.", ephemeral=True)
            return
        embed = discord.Embed(title=f"Warnings for {member}", color=0xF39C12)
        shown = rows[:10]
        for w in shown:
            mod = interaction.guild.get_member(int(w["moderator_id"]))
            mod_str = str(mod) if mod else f"<@{w['moderator_id']}>"
            embed.add_field(
                name=f"#{w['id']} — {w['created_at'][:10]}",
                value=f"**Reason:** {w['reason'] or 'N/A'}\n**By:** {mod_str}",
                inline=False,
            )
        footer = f"Total warnings: {len(rows)}"
        if len(rows) > 10:
            footer += f" (showing 10 of {len(rows)})"
        embed.set_footer(text=footer)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- Clear Warnings ---

    @app_commands.command(name="clearwarnings", description="Clear all warnings for a member")
    @app_commands.describe(member="Member to clear warnings for")
    @app_commands.default_permissions(manage_guild=True)
    async def clearwarnings(self, interaction: discord.Interaction, member: discord.Member):
        count = await db.clear_warnings(str(interaction.guild_id), str(member.id))
        await interaction.response.send_message(
            f"Cleared {count} warning(s) for {member}.", ephemeral=True
        )

    # --- Delete Warning ---

    @app_commands.command(name="delwarn", description="Delete a single warning by ID")
    @app_commands.describe(warning_id="Warning ID to remove")
    @app_commands.default_permissions(manage_messages=True)
    async def delwarn(self, interaction: discord.Interaction, warning_id: int):
        warning = await db.get_warning(warning_id, str(interaction.guild_id))
        if not warning:
            await interaction.response.send_message(
                f"Warning #{warning_id} not found in this server.", ephemeral=True
            )
            return
        await db.delete_warning(warning_id, str(interaction.guild_id))
        embed = discord.Embed(title="Warning Deleted", color=0x2ECC71,
                               timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Warning ID", value=f"#{warning_id}")
        embed.add_field(name="User", value=f"<@{warning['user_id']}>")
        embed.add_field(name="Original Reason", value=warning["reason"] or "N/A", inline=False)
        embed.add_field(name="Deleted by", value=str(interaction.user), inline=False)
        await self._post_audit(interaction.guild, embed)
        await interaction.response.send_message(f"Warning #{warning_id} deleted.", ephemeral=True)

    # --- Mod Log ---

    @app_commands.command(name="modlog", description="View moderation action history")
    @app_commands.describe(user="Filter by target user", moderator="Filter by moderator")
    @app_commands.default_permissions(manage_messages=True)
    async def modlog(self, interaction: discord.Interaction,
                     user: Optional[discord.Member] = None,
                     moderator: Optional[discord.Member] = None):
        entries = await db.get_modlog(
            str(interaction.guild_id),
            user_id=str(user.id) if user else None,
            moderator_id=str(moderator.id) if moderator else None,
            limit=50,
        )
        if not entries:
            await interaction.response.send_message("No modlog entries found.", ephemeral=True)
            return
        title = "Moderation Log"
        if user:
            title += f" — {user}"
        elif moderator:
            title += f" — by {moderator}"
        embed = discord.Embed(title=title, color=0x3498DB,
                               timestamp=datetime.now(timezone.utc))
        for e in entries:
            mod = interaction.guild.get_member(int(e["moderator_id"]))
            mod_str = str(mod) if mod else f"<@{e['moderator_id']}>"
            target = interaction.guild.get_member(int(e["user_id"]))
            target_str = str(target) if target else f"<@{e['user_id']}>"
            value = f"**User:** {target_str}\n**By:** {mod_str}"
            if e["reason"]:
                value += f"\n**Reason:** {e['reason']}"
            if e["extra"] and e["action"] == "timeout":
                value += f"\n**Duration:** {e['extra']}"
            embed.add_field(
                name=f"#{e['id']} — {e['action'].upper()} — {e['created_at'][:10]}",
                value=value,
                inline=False,
            )
        embed.set_footer(text=f"Showing {len(entries)} entr{'y' if len(entries) == 1 else 'ies'} (max 50)")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- Purge ---

    @app_commands.command(name="purge", description="Bulk delete messages in a channel (up to 100)")
    @app_commands.describe(amount="Number of messages to delete (1–100)")
    @app_commands.default_permissions(manage_messages=True)
    async def purge(self, interaction: discord.Interaction, amount: int):
        amount = max(1, min(100, amount))
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"Deleted {len(deleted)} message(s).", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
