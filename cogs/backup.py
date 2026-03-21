from __future__ import annotations

import io
import json
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from dashboard import db
from bot import BOT_VERSION

log = logging.getLogger(__name__)


class Backup(commands.Cog):
    """Export and restore all guild bot configuration as a JSON file."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _collect(self, guild_id: str) -> dict:
        """Gather all bot configuration for a guild into a dict."""
        data: dict = {
            "version": BOT_VERSION,
            "guild_id": guild_id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }

        data["guild_settings"] = await db.get_all_guild_settings(guild_id)
        data["welcome_config"] = await db.get_welcome_config(guild_id) or {}
        data["audit_config"] = await db.get_audit_config(guild_id) or {}
        data["xp_config"] = await db.get_xp_config(guild_id) or {}
        data["xp_role_rewards"] = await db.get_xp_role_rewards(guild_id)
        data["reaction_roles"] = await db.get_reaction_roles(guild_id)
        data["autoroles"] = await db.get_autoroles(guild_id)
        data["custom_commands"] = await db.get_commands(guild_id)
        data["freestuff_config"] = await db.get_freestuff_config(guild_id) or {}
        data["autotranslate_config"] = await db.get_autotranslate_config(guild_id) or {}
        data["antiraid_config"] = await db.get_antiraid_config(guild_id) or {}
        data["giveaways_active"] = await db.get_active_giveaways(guild_id)

        return data

    async def _restore(self, guild_id: str, data: dict) -> list[str]:
        """Restore guild configuration from backup dict. Returns list of restored sections."""
        restored = []

        if data.get("guild_settings"):
            for key, value in data["guild_settings"].items():
                await db.set_guild_setting(guild_id, key, value)
            restored.append("guild_settings")

        if data.get("welcome_config"):
            cfg = dict(data["welcome_config"])
            cfg.pop("guild_id", None)
            await db.upsert_welcome_config(guild_id, **cfg)
            restored.append("welcome_config")

        if data.get("audit_config"):
            cfg = dict(data["audit_config"])
            cfg.pop("guild_id", None)
            await db.upsert_audit_config(guild_id, **cfg)
            restored.append("audit_config")

        if data.get("xp_config"):
            cfg = dict(data["xp_config"])
            cfg.pop("guild_id", None)
            await db.upsert_xp_config(guild_id, **cfg)
            restored.append("xp_config")

        if data.get("freestuff_config"):
            cfg = dict(data["freestuff_config"])
            cfg.pop("guild_id", None)
            await db.upsert_freestuff_config(guild_id, **cfg)
            restored.append("freestuff_config")

        if data.get("autotranslate_config"):
            cfg = dict(data["autotranslate_config"])
            cfg.pop("guild_id", None)
            if cfg:
                await db.upsert_autotranslate_config(guild_id, **cfg)
                restored.append("autotranslate_config")

        if data.get("antiraid_config"):
            cfg = dict(data["antiraid_config"])
            cfg.pop("guild_id", None)
            if cfg:
                await db.upsert_antiraid_config(guild_id, **cfg)
                restored.append("antiraid_config")

        return restored

    backup_group = app_commands.Group(
        name="backup",
        description="Export or restore all bot configuration for this server",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @backup_group.command(name="export", description="Export all bot config to a JSON file (sent via DM)")
    async def backup_export(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        gid = str(interaction.guild_id)
        data = await self._collect(gid)

        json_bytes = json.dumps(data, indent=2, default=str).encode("utf-8")
        filename = f"backup_{gid}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        file = discord.File(io.BytesIO(json_bytes), filename=filename)

        try:
            await interaction.user.send(
                f"📦 Backup for **{interaction.guild.name}** exported.",
                file=file,
            )
            await interaction.followup.send("Backup sent to your DMs!", ephemeral=True)
        except discord.Forbidden:
            # Can't DM — send in channel instead
            file = discord.File(io.BytesIO(json_bytes), filename=filename)
            await interaction.followup.send(
                "Could not DM you — posting here (delete when done).",
                file=file,
                ephemeral=True,
            )

    @backup_group.command(name="restore", description="Restore bot config from an uploaded backup JSON file")
    @app_commands.describe(backup_file="The backup JSON file produced by /backup export")
    async def backup_restore(self, interaction: discord.Interaction,
                              backup_file: discord.Attachment):
        if not backup_file.filename.endswith(".json"):
            await interaction.response.send_message("Please upload a `.json` backup file.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        try:
            raw = await backup_file.read()
            data = json.loads(raw)
        except Exception as exc:
            await interaction.followup.send(f"Failed to parse backup file: {exc}", ephemeral=True)
            return

        if data.get("guild_id") and data["guild_id"] != str(interaction.guild_id):
            await interaction.followup.send(
                "⚠️ This backup was created for a different server. Restoring anyway...",
                ephemeral=True,
            )

        restored = await self._restore(str(interaction.guild_id), data)

        # Refresh AuditLog cache if it's loaded
        cog = self.bot.get_cog("AuditLog")
        if cog:
            await cog.refresh_cache()

        embed = discord.Embed(title="✅ Backup Restored", color=0x2ECC71)
        embed.add_field(
            name="Restored sections",
            value="\n".join(f"• {s}" for s in restored) or "*(none)*",
            inline=False,
        )
        if data.get("exported_at"):
            embed.set_footer(text=f"Backup was from: {data['exported_at']}")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Backup(bot))
