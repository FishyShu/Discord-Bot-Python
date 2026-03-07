from __future__ import annotations

import logging
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from dashboard import db

log = logging.getLogger(__name__)


def xp_for_level(level: int) -> int:
    """XP required to reach the given level (cumulative threshold)."""
    return 5 * level * level + 50 * level + 100


def level_from_xp(xp: int) -> int:
    """Determine level from total XP."""
    level = 0
    while xp >= xp_for_level(level + 1):
        level += 1
    return level


class Leveling(commands.Cog):
    """Message-based XP system with level-ups, role rewards, /rank, and /leaderboard."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._config_cache: dict[str, dict] = {}
        self._reward_cache: dict[str, list[dict]] = {}
        # In-memory cooldown: (guild_id, user_id) -> last_xp_timestamp
        self._cooldowns: dict[tuple[str, str], float] = {}
        self._cooldown_cleanup_counter = 0

    async def cog_load(self):
        await self.refresh_cache()

    async def refresh_cache(self):
        self._config_cache = await db.get_all_xp_configs()
        self._reward_cache = await db.get_all_xp_role_rewards()
        log.info("Leveling cache refreshed: %d guild configs", len(self._config_cache))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        gid = str(message.guild.id)
        cfg = self._config_cache.get(gid)
        if not cfg or not cfg.get("enabled"):
            return

        uid = str(message.author.id)
        cooldown = cfg.get("xp_cooldown", 60)
        now = time.time()
        key = (gid, uid)

        # Cooldown check
        last = self._cooldowns.get(key, 0)
        if now - last < cooldown:
            return
        self._cooldowns[key] = now

        # Periodic cleanup of stale cooldown entries
        self._cooldown_cleanup_counter += 1
        if self._cooldown_cleanup_counter >= 1000:
            self._cooldown_cleanup_counter = 0
            # Use max configured cooldown + 60s as cutoff, not a fixed 300s
            max_cd = max((c.get("xp_cooldown", 60) for c in self._config_cache.values()), default=60)
            cutoff = now - (max_cd + 60)
            self._cooldowns = {k: v for k, v in self._cooldowns.items() if v > cutoff}

        # Grant XP
        xp_amount = cfg.get("xp_per_message", 15) + random.randint(-5, 5)
        if xp_amount < 1:
            xp_amount = 1

        # Atomic increment to avoid read-modify-write race
        now_iso = datetime.now(timezone.utc).isoformat()
        result = await db.increment_xp_user(gid, uid, xp_amount, now_iso)
        new_xp = result["xp"]
        old_level = result["level"]
        new_level = level_from_xp(new_xp)

        # Log XP gain
        await db.add_xp_log_entry(
            guild_id=gid, user_id=uid, xp_gained=xp_amount,
            total_xp=new_xp, level=new_level,
            channel_id=str(message.channel.id),
            created_at=now_iso,
        )

        # Update level if changed
        if new_level != old_level:
            await db.update_xp_level(gid, uid, new_level)
            await self._handle_levelup(message, cfg, old_level, new_level)

    async def _handle_levelup(self, message: discord.Message, cfg: dict, old_level: int, new_level: int):
        gid = str(message.guild.id)

        # Send level-up message
        levelup_msg = cfg.get("levelup_message", "Congrats {user}, you reached level {level}!")
        text = levelup_msg.replace("{user}", message.author.mention).replace("{level}", str(new_level))

        channel_id = cfg.get("levelup_channel_id")
        channel = message.guild.get_channel(int(channel_id)) if channel_id else message.channel
        if channel:
            image_path = cfg.get("levelup_image_path")
            image_url = cfg.get("levelup_image_url")
            try:
                if image_path:
                    upload_dir = Path(__file__).resolve().parent.parent / "data" / "uploads"
                    filepath = upload_dir / image_path
                    if filepath.is_file():
                        embed = discord.Embed(description=text, color=0xF39C12)
                        file = discord.File(str(filepath), filename=image_path)
                        embed.set_image(url=f"attachment://{image_path}")
                        await channel.send(embed=embed, file=file)
                    else:
                        await channel.send(text)
                elif image_url:
                    embed = discord.Embed(description=text, color=0xF39C12)
                    embed.set_image(url=image_url)
                    await channel.send(embed=embed)
                else:
                    await channel.send(text)
            except discord.HTTPException:
                pass

        # Check role rewards — use range to catch intermediate level jumps
        rewards = self._reward_cache.get(gid, [])
        for reward in rewards:
            if old_level < reward["level"] <= new_level:
                role = message.guild.get_role(int(reward["role_id"]))
                if role and role not in message.author.roles:
                    try:
                        await message.author.add_roles(role, reason=f"Level {reward['level']} reward")
                    except discord.HTTPException as e:
                        log.warning("Failed to add level reward role: %s", e)

    # --- Admin XP commands ---

    xp_group = app_commands.Group(
        name="xp",
        description="Manage XP settings",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @xp_group.command(name="set", description="Set a member's XP to a specific amount")
    @app_commands.describe(member="Target member", amount="XP amount to set")
    async def xp_set(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        gid = str(interaction.guild_id)
        level = level_from_xp(amount)
        await db.upsert_xp_user(gid, str(member.id), amount, level, datetime.now(timezone.utc).isoformat())
        await interaction.response.send_message(
            f"Set {member.mention}'s XP to **{amount:,}** (level {level}).", ephemeral=True
        )

    @xp_group.command(name="reset", description="Reset a member's XP and level to 0")
    @app_commands.describe(member="Target member")
    async def xp_reset(self, interaction: discord.Interaction, member: discord.Member):
        gid = str(interaction.guild_id)
        await db.upsert_xp_user(gid, str(member.id), 0, 0, datetime.now(timezone.utc).isoformat())
        await interaction.response.send_message(f"Reset {member.mention}'s XP and level to 0.", ephemeral=True)

    @xp_group.command(name="config", description="Show the current XP configuration")
    async def xp_config(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        cfg = await db.get_xp_config(gid)
        if not cfg:
            await interaction.response.send_message("XP system is not configured for this server.", ephemeral=True)
            return

        embed = discord.Embed(title="XP Configuration", color=0xF39C12)
        embed.add_field(name="Enabled", value="Yes" if cfg.get("enabled") else "No")
        embed.add_field(name="XP per Message", value=str(cfg.get("xp_per_message", 15)))
        embed.add_field(name="Cooldown", value=f"{cfg.get('xp_cooldown', 60)}s")
        ch_id = cfg.get("levelup_channel_id")
        embed.add_field(name="Level-up Channel", value=f"<#{ch_id}>" if ch_id else "Current channel")
        embed.add_field(name="Level-up Message", value=cfg.get("levelup_message", "Default"), inline=False)
        # Show role rewards
        rewards = await db.get_xp_role_rewards(gid)
        if rewards:
            lines = []
            for r in rewards:
                role = interaction.guild.get_role(int(r["role_id"]))
                rname = role.mention if role else f"Role #{r['role_id']}"
                lines.append(f"Level {r['level']} → {rname}")
            embed.add_field(name="Role Rewards", value="\n".join(lines), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @xp_group.command(name="enable", description="Enable the XP system")
    async def xp_enable(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        await db.upsert_xp_config(gid, enabled=1)
        await self.refresh_cache()
        await interaction.response.send_message("XP system enabled.", ephemeral=True)

    @xp_group.command(name="disable", description="Disable the XP system")
    async def xp_disable(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        await db.upsert_xp_config(gid, enabled=0)
        await self.refresh_cache()
        await interaction.response.send_message("XP system disabled.", ephemeral=True)

    @xp_group.command(name="setrate", description="Set XP per message and cooldown")
    @app_commands.describe(
        xp_per_message="Base XP awarded per message (1-1000)",
        cooldown="Seconds between XP gains per user (0-3600)",
    )
    async def xp_setrate(
        self,
        interaction: discord.Interaction,
        xp_per_message: app_commands.Range[int, 1, 1000],
        cooldown: app_commands.Range[int, 0, 3600],
    ):
        gid = str(interaction.guild_id)
        await db.upsert_xp_config(gid, xp_per_message=xp_per_message, xp_cooldown=cooldown)
        await self.refresh_cache()
        await interaction.response.send_message(
            f"XP rate set to **{xp_per_message}** per message with **{cooldown}s** cooldown.", ephemeral=True
        )

    @xp_group.command(name="setchannel", description="Set the level-up notification channel")
    @app_commands.describe(channel="Channel for level-up messages (omit for current channel)")
    async def xp_setchannel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ):
        gid = str(interaction.guild_id)
        ch_id = str(channel.id) if channel else ""
        await db.upsert_xp_config(gid, levelup_channel_id=ch_id)
        await self.refresh_cache()
        if channel:
            await interaction.response.send_message(f"Level-up messages will be sent in {channel.mention}.", ephemeral=True)
        else:
            await interaction.response.send_message("Level-up messages will be sent in the current channel.", ephemeral=True)

    @xp_group.command(name="setmessage", description="Set the level-up message template")
    @app_commands.describe(message="Message template ({user}, {level})")
    async def xp_setmessage(self, interaction: discord.Interaction, message: str):
        gid = str(interaction.guild_id)
        await db.upsert_xp_config(gid, levelup_message=message)
        await self.refresh_cache()
        await interaction.response.send_message(f"Level-up message set to: {message}", ephemeral=True)

    @xp_group.command(name="addreward", description="Add a role reward for reaching a level")
    @app_commands.describe(level="Level required", role="Role to award")
    async def xp_addreward(
        self,
        interaction: discord.Interaction,
        level: app_commands.Range[int, 1, 1000],
        role: discord.Role,
    ):
        gid = str(interaction.guild_id)
        try:
            await db.create_xp_role_reward(gid, level, str(role.id))
        except Exception:
            await interaction.response.send_message(f"A reward for level {level} already exists.", ephemeral=True)
            return
        await self.refresh_cache()
        await interaction.response.send_message(
            f"Role {role.mention} will be awarded at level **{level}**.", ephemeral=True
        )

    @xp_group.command(name="removereward", description="Remove a role reward by level")
    @app_commands.describe(level="Level of the reward to remove")
    async def xp_removereward(self, interaction: discord.Interaction, level: int):
        gid = str(interaction.guild_id)
        rewards = await db.get_xp_role_rewards(gid)
        target = next((r for r in rewards if r["level"] == level), None)
        if not target:
            await interaction.response.send_message(f"No reward found for level {level}.", ephemeral=True)
            return
        await db.delete_xp_role_reward(target["id"])
        await self.refresh_cache()
        await interaction.response.send_message(f"Removed role reward for level **{level}**.", ephemeral=True)

    # --- /rank ---

    @app_commands.command(name="rank", description="Show your or another user's level and XP")
    @app_commands.describe(member="User to check (defaults to you)")
    async def rank(self, interaction: discord.Interaction, member: discord.Member | None = None):
        member = member or interaction.user
        gid = str(interaction.guild_id)
        user_data = await db.get_xp_user(gid, str(member.id))

        xp = user_data["xp"] if user_data else 0
        level = user_data["level"] if user_data else 0
        next_level_xp = xp_for_level(level + 1)

        # Get rank position
        rank_pos = await db.get_xp_rank(gid, str(member.id))

        embed = discord.Embed(title=f"{member}'s Rank", color=member.color or 0x3498DB)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Rank", value=f"#{rank_pos}")
        embed.add_field(name="Level", value=str(level))
        embed.add_field(name="XP", value=f"{xp:,} / {next_level_xp:,}")
        await interaction.response.send_message(embed=embed)

    # --- /leaderboard ---

    @app_commands.command(name="leaderboard", description="Show the server XP leaderboard")
    async def leaderboard(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        lb = await db.get_xp_leaderboard(gid, limit=10)
        if not lb:
            await interaction.response.send_message("No XP data yet!", ephemeral=True)
            return

        lines = []
        for i, entry in enumerate(lb, 1):
            user = interaction.guild.get_member(int(entry["user_id"]))
            name = str(user) if user else f"User {entry['user_id']}"
            lines.append(f"**#{i}** {name} — Level {entry['level']} ({entry['xp']:,} XP)")

        embed = discord.Embed(
            title=f"{interaction.guild.name} Leaderboard",
            description="\n".join(lines),
            color=0xF39C12,
        )
        await interaction.response.send_message(embed=embed)


    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        gid = str(guild.id)
        self._config_cache.pop(gid, None)
        self._reward_cache.pop(gid, None)
        self._cooldowns = {k: v for k, v in self._cooldowns.items() if k[0] != gid}


async def setup(bot: commands.Bot):
    await bot.add_cog(Leveling(bot))
