from __future__ import annotations

import json
import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from dashboard import db

log = logging.getLogger(__name__)


class Welcome(commands.Cog):
    """Send welcome/goodbye messages when members join or leave."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cache: dict[str, dict] = {}

    async def cog_load(self):
        await self.refresh_cache()

    async def refresh_cache(self):
        self._cache = await db.get_all_welcome_configs()
        log.info("Welcome cache refreshed: %d guild configs loaded", len(self._cache))

    def _apply_placeholders(self, text: str, member: discord.Member) -> str:
        return (
            text.replace("{user}", member.mention)
            .replace("{username}", str(member))
            .replace("{server}", member.guild.name)
            .replace("{membercount}", str(member.guild.member_count or 0))
        )

    def _build_embed(self, embed_json: str, member: discord.Member) -> discord.Embed | None:
        try:
            data = json.loads(embed_json)
        except (json.JSONDecodeError, TypeError):
            return None
        title = self._apply_placeholders(data.get("title", ""), member)
        desc = self._apply_placeholders(data.get("description", ""), member)
        embed = discord.Embed(
            title=title, description=desc, color=data.get("color", 0x3498DB)
        )
        if data.get("footer"):
            embed.set_footer(text=self._apply_placeholders(data["footer"], member))
        if data.get("thumbnail") == "{avatar}":
            embed.set_thumbnail(url=member.display_avatar.url)
        elif data.get("thumbnail"):
            embed.set_thumbnail(url=data["thumbnail"])
        return embed

    # --- Slash commands ---

    welcome_group = app_commands.Group(
        name="welcome",
        description="Configure welcome and goodbye messages",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @welcome_group.command(name="set", description="Configure the welcome message")
    @app_commands.describe(
        channel="Channel for welcome messages",
        message="Welcome text ({user}, {username}, {server}, {membercount})",
        embed_json="Optional embed JSON",
        enabled="Enable or disable",
    )
    async def welcome_set(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        message: Optional[str] = None,
        embed_json: Optional[str] = None,
        enabled: Optional[bool] = True,
    ):
        gid = str(interaction.guild_id)
        kwargs = {
            "welcome_enabled": int(enabled),
            "welcome_channel_id": str(channel.id),
        }
        if message is not None:
            kwargs["welcome_message"] = message
        if embed_json is not None:
            try:
                embed_data = json.loads(embed_json)
            except json.JSONDecodeError:
                await interaction.response.send_message("Invalid JSON for embed.", ephemeral=True)
                return
            if len(embed_json) > 4096:
                await interaction.response.send_message("Embed JSON too large (max 4096 chars).", ephemeral=True)
                return
            if len(embed_data.get("title", "")) > 256:
                await interaction.response.send_message("Embed title exceeds 256 characters.", ephemeral=True)
                return
            if len(embed_data.get("description", "")) > 4096:
                await interaction.response.send_message("Embed description exceeds 4096 characters.", ephemeral=True)
                return
            kwargs["welcome_embed_json"] = embed_json
        await db.upsert_welcome_config(gid, **kwargs)
        await self.refresh_cache()
        await interaction.response.send_message(
            f"Welcome message {'enabled' if enabled else 'disabled'} in {channel.mention}.",
            ephemeral=True,
        )

    @welcome_group.command(name="goodbye", description="Configure the goodbye message")
    @app_commands.describe(
        channel="Channel for goodbye messages",
        message="Goodbye text ({user}, {username}, {server}, {membercount})",
        embed_json="Optional embed JSON",
        enabled="Enable or disable",
    )
    async def welcome_goodbye(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        message: Optional[str] = None,
        embed_json: Optional[str] = None,
        enabled: Optional[bool] = True,
    ):
        gid = str(interaction.guild_id)
        kwargs = {
            "goodbye_enabled": int(enabled),
            "goodbye_channel_id": str(channel.id),
        }
        if message is not None:
            kwargs["goodbye_message"] = message
        if embed_json is not None:
            try:
                embed_data = json.loads(embed_json)
            except json.JSONDecodeError:
                await interaction.response.send_message("Invalid JSON for embed.", ephemeral=True)
                return
            if len(embed_json) > 4096:
                await interaction.response.send_message("Embed JSON too large (max 4096 chars).", ephemeral=True)
                return
            if len(embed_data.get("title", "")) > 256:
                await interaction.response.send_message("Embed title exceeds 256 characters.", ephemeral=True)
                return
            if len(embed_data.get("description", "")) > 4096:
                await interaction.response.send_message("Embed description exceeds 4096 characters.", ephemeral=True)
                return
            kwargs["goodbye_embed_json"] = embed_json
        await db.upsert_welcome_config(gid, **kwargs)
        await self.refresh_cache()
        await interaction.response.send_message(
            f"Goodbye message {'enabled' if enabled else 'disabled'} in {channel.mention}.",
            ephemeral=True,
        )

    @welcome_group.command(name="show", description="Show the current welcome/goodbye config")
    async def welcome_show(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        cfg = await db.get_welcome_config(gid)
        if not cfg:
            await interaction.response.send_message("No welcome config for this server.", ephemeral=True)
            return
        embed = discord.Embed(title="Welcome / Goodbye Config", color=0x3498DB)
        # Welcome
        w_ch = f"<#{cfg['welcome_channel_id']}>" if cfg.get("welcome_channel_id") else "Not set"
        embed.add_field(name="Welcome Enabled", value="Yes" if cfg.get("welcome_enabled") else "No")
        embed.add_field(name="Welcome Channel", value=w_ch)
        embed.add_field(name="Welcome Message", value=cfg.get("welcome_message") or "*None*", inline=False)
        # Goodbye
        g_ch = f"<#{cfg['goodbye_channel_id']}>" if cfg.get("goodbye_channel_id") else "Not set"
        embed.add_field(name="Goodbye Enabled", value="Yes" if cfg.get("goodbye_enabled") else "No")
        embed.add_field(name="Goodbye Channel", value=g_ch)
        embed.add_field(name="Goodbye Message", value=cfg.get("goodbye_message") or "*None*", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @welcome_group.command(name="test", description="Send a test welcome message in the current channel")
    async def welcome_test(self, interaction: discord.Interaction):
        cfg = self._cache.get(str(interaction.guild_id))
        if not cfg or not cfg.get("welcome_message"):
            await interaction.response.send_message("No welcome message configured.", ephemeral=True)
            return
        content = self._apply_placeholders(cfg["welcome_message"], interaction.user)
        embed = None
        if cfg.get("welcome_embed_json"):
            embed = self._build_embed(cfg["welcome_embed_json"], interaction.user)
        await interaction.response.send_message(content=content or None, embed=embed)

    @welcome_group.command(name="disable", description="Disable both welcome and goodbye messages")
    async def welcome_disable(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        await db.upsert_welcome_config(gid, welcome_enabled=0, goodbye_enabled=0)
        await self.refresh_cache()
        await interaction.response.send_message("Welcome and goodbye messages disabled.", ephemeral=True)

    # --- Listeners ---

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        cfg = self._cache.get(str(member.guild.id))
        if not cfg or not cfg.get("welcome_enabled"):
            return
        channel_id = cfg.get("welcome_channel_id")
        if not channel_id:
            return
        channel = member.guild.get_channel(int(channel_id))
        if not channel:
            return

        content = None
        embed = None
        if cfg.get("welcome_message"):
            content = self._apply_placeholders(cfg["welcome_message"], member)
        if cfg.get("welcome_embed_json"):
            embed = self._build_embed(cfg["welcome_embed_json"], member)

        if content or embed:
            try:
                await channel.send(content=content, embed=embed)
            except discord.HTTPException as e:
                log.warning("Failed to send welcome message in %s: %s", channel_id, e)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        cfg = self._cache.get(str(member.guild.id))
        if not cfg or not cfg.get("goodbye_enabled"):
            return
        channel_id = cfg.get("goodbye_channel_id")
        if not channel_id:
            return
        channel = member.guild.get_channel(int(channel_id))
        if not channel:
            return

        content = None
        embed = None
        if cfg.get("goodbye_message"):
            content = self._apply_placeholders(cfg["goodbye_message"], member)
        if cfg.get("goodbye_embed_json"):
            embed = self._build_embed(cfg["goodbye_embed_json"], member)

        if content or embed:
            try:
                await channel.send(content=content, embed=embed)
            except discord.HTTPException as e:
                log.warning("Failed to send goodbye message in %s: %s", channel_id, e)


async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
