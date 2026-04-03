from __future__ import annotations

import asyncio
import io
import json
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from dashboard import db
from utils.version import BOT_VERSION

log = logging.getLogger(__name__)


class Backup(commands.Cog):
    """Export and restore all guild bot configuration as a JSON file."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _collect(self, guild_id: str) -> dict:
        """Gather all bot configuration for a guild into a dict."""
        (
            guild_settings, welcome_cfg, audit_cfg, xp_cfg, xp_rewards,
            reaction_roles, autoroles, custom_cmds, freestuff_cfg,
            autotranslate_cfg, antiraid_cfg, active_giveaways,
        ) = await asyncio.gather(
            db.get_all_guild_settings(guild_id),
            db.get_welcome_config(guild_id),
            db.get_audit_config(guild_id),
            db.get_xp_config(guild_id),
            db.get_xp_role_rewards(guild_id),
            db.get_reaction_roles(guild_id),
            db.get_autoroles(guild_id),
            db.get_commands(guild_id),
            db.get_freestuff_config(guild_id),
            db.get_autotranslate_config(guild_id),
            db.get_antiraid_config(guild_id),
            db.get_active_giveaways(guild_id),
        )
        return {
            "version": BOT_VERSION,
            "guild_id": guild_id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "guild_settings": guild_settings,
            "welcome_config": welcome_cfg or {},
            "audit_config": audit_cfg or {},
            "xp_config": xp_cfg or {},
            "xp_role_rewards": xp_rewards,
            "reaction_roles": reaction_roles,
            "autoroles": autoroles,
            "custom_commands": custom_cmds,
            "freestuff_config": freestuff_cfg or {},
            "autotranslate_config": autotranslate_cfg or {},
            "antiraid_config": antiraid_cfg or {},
            "giveaways_active": active_giveaways,
        }

    async def _restore(self, guild_id: str, data: dict) -> list[str]:
        """Restore guild configuration from backup dict. Returns list of restored sections."""
        log.info("Starting restore for guild %s (backup from %s)", guild_id, data.get("exported_at", "unknown"))
        restored = []

        try:
          return await self._restore_inner(guild_id, data, restored)
        except Exception:
            log.exception("Restore failed for guild %s after restoring: %s", guild_id, restored)
            raise

    async def _restore_inner(self, guild_id: str, data: dict, restored: list[str]) -> list[str]:
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

        log.info("Restore complete for guild %s — sections: %s", guild_id, restored)
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
