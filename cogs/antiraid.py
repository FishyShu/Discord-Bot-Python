from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from dashboard import db

log = logging.getLogger(__name__)


class AntiRaid(commands.Cog):
    """Anti-raid protection: mass joins, new account filter, mention spam, message spam."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # {guild_id: config_dict}
        self._cache: dict[str, dict] = {}
        # Sliding-window join timestamps per guild: {guild_id: deque of timestamps}
        self._join_windows: dict[str, deque] = defaultdict(deque)
        # Message timestamps per (guild_id, user_id): deque of timestamps
        self._msg_windows: dict[tuple, deque] = defaultdict(deque)

    async def cog_load(self):
        self._cache = await db.get_all_antiraid_configs()
        log.info("AntiRaid cache loaded: %d guild(s)", len(self._cache))

    def _cfg(self, guild_id: str) -> dict | None:
        return self._cache.get(guild_id)

    async def _alert(self, guild: discord.Guild, embed: discord.Embed) -> None:
        """Post alert to audit log channel."""
        cfg_audit = await db.get_audit_config(str(guild.id))
        if cfg_audit and cfg_audit.get("log_channel_id"):
            ch = guild.get_channel(int(cfg_audit["log_channel_id"]))
            if ch:
                try:
                    await ch.send(embed=embed)
                except discord.HTTPException as e:
                    log.debug("Failed to send antiraid alert to audit log channel: %s", e)

    async def _take_action(self, guild: discord.Guild, member: discord.Member,
                            action: str, reason: str) -> None:
        """Kick, ban, or timeout a member."""
        try:
            if action == "kick":
                await member.kick(reason=reason)
            elif action == "ban":
                await member.ban(reason=reason, delete_message_days=0)
            else:  # timeout (default)
                until = datetime.now(timezone.utc) + timedelta(hours=1)
                await member.timeout(until, reason=reason)
        except (discord.Forbidden, discord.HTTPException) as exc:
            log.warning("AntiRaid action '%s' failed on %s: %s", action, member, exc)

    # --- Listeners ---

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        gid = str(member.guild.id)
        cfg = self._cfg(gid)
        if not cfg or not cfg.get("enabled"):
            return

        now = time.monotonic()

        # New account check
        if cfg.get("new_account_enabled"):
            days = cfg.get("new_account_days", 7)
            age = (datetime.now(timezone.utc) - member.created_at).days
            if age < days:
                embed = discord.Embed(title="🚨 New Account Blocked", color=0xE74C3C,
                                       timestamp=datetime.now(timezone.utc))
                embed.add_field(name="User", value=f"{member} ({member.id})")
                embed.add_field(name="Account Age", value=f"{age} day(s)")
                await self._alert(member.guild, embed)
                await self._take_action(member.guild, member, cfg.get("action", "kick"),
                                         f"Account too new ({age}d < {days}d threshold)")
                return

        # Mass join check
        if cfg.get("mass_join_enabled"):
            threshold = cfg.get("mass_join_threshold", 10)
            window = self._join_windows[gid]
            window.append(now)
            # Keep only joins in the last 10 seconds
            while window and now - window[0] > 10:
                window.popleft()
            if len(window) >= threshold:
                window.clear()  # reset to avoid repeated triggers
                embed = discord.Embed(title="🚨 Mass Join Detected — Raid Alert!", color=0xE74C3C,
                                       timestamp=datetime.now(timezone.utc))
                embed.add_field(name="Threshold", value=f"{threshold} joins in 10s")
                await self._alert(member.guild, embed)
                # Kick all recently joined members
                for m in list(member.guild.members)[-threshold:]:
                    if not m.bot and m != member.guild.owner:
                        await self._take_action(member.guild, m, "kick", "AntiRaid: mass join")
                return

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        gid = str(message.guild.id)
        cfg = self._cfg(gid)
        if not cfg or not cfg.get("enabled"):
            return

        member = message.author
        now = time.monotonic()
        action = cfg.get("action", "timeout")

        # Mention spam check
        if cfg.get("mention_spam_enabled"):
            threshold = cfg.get("mention_spam_threshold", 5)
            if len(message.mentions) >= threshold:
                embed = discord.Embed(title="🚨 Mention Spam Detected", color=0xE74C3C,
                                       timestamp=datetime.now(timezone.utc))
                embed.add_field(name="User", value=f"{member} ({member.id})")
                embed.add_field(name="Mentions", value=str(len(message.mentions)))
                embed.add_field(name="Channel", value=message.channel.mention)
                await self._alert(message.guild, embed)
                await self._take_action(message.guild, member, action, "AntiRaid: mention spam")
                try:
                    await message.delete()
                except discord.HTTPException as e:
                    log.debug("Failed to delete mention-spam message in guild %s: %s", message.guild.id, e)
                return

        # Message spam check
        if cfg.get("message_spam_enabled"):
            threshold = cfg.get("message_spam_threshold", 8)
            key = (gid, str(member.id))
            window = self._msg_windows[key]
            window.append(now)
            while window and now - window[0] > 5:
                window.popleft()
            if len(window) >= threshold:
                window.clear()
                embed = discord.Embed(title="🚨 Message Spam Detected", color=0xE74C3C,
                                       timestamp=datetime.now(timezone.utc))
                embed.add_field(name="User", value=f"{member} ({member.id})")
                embed.add_field(name="Messages", value=f"{threshold} in 5s")
                await self._alert(message.guild, embed)
                await self._take_action(message.guild, member, action, "AntiRaid: message spam")

    # --- Commands ---

    ar_group = app_commands.Group(
        name="antiraid",
        description="Configure anti-raid protection",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @ar_group.command(name="set", description="Configure anti-raid settings")
    @app_commands.describe(
        enabled="Enable or disable anti-raid globally",
        action="Action to take (kick / ban / timeout)",
        mass_join_enabled="Enable mass-join detection",
        mass_join_threshold="Join count threshold for mass-join (in 10s window)",
        new_account_enabled="Enable new account detection",
        new_account_days="Min account age in days",
        mention_spam_enabled="Enable mention spam detection",
        mention_spam_threshold="Max mentions per message",
        message_spam_enabled="Enable message spam detection",
        message_spam_threshold="Max messages in 5s",
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Timeout (1h)", value="timeout"),
        app_commands.Choice(name="Kick", value="kick"),
        app_commands.Choice(name="Ban", value="ban"),
    ])
    async def ar_set(
        self,
        interaction: discord.Interaction,
        enabled: Optional[bool] = None,
        action: Optional[str] = None,
        mass_join_enabled: Optional[bool] = None,
        mass_join_threshold: Optional[int] = None,
        new_account_enabled: Optional[bool] = None,
        new_account_days: Optional[int] = None,
        mention_spam_enabled: Optional[bool] = None,
        mention_spam_threshold: Optional[int] = None,
        message_spam_enabled: Optional[bool] = None,
        message_spam_threshold: Optional[int] = None,
    ):
        gid = str(interaction.guild_id)
        kwargs = {}
        if enabled is not None:
            kwargs["enabled"] = int(enabled)
        if action is not None:
            kwargs["action"] = action
        if mass_join_enabled is not None:
            kwargs["mass_join_enabled"] = int(mass_join_enabled)
        if mass_join_threshold is not None:
            kwargs["mass_join_threshold"] = mass_join_threshold
        if new_account_enabled is not None:
            kwargs["new_account_enabled"] = int(new_account_enabled)
        if new_account_days is not None:
            kwargs["new_account_days"] = new_account_days
        if mention_spam_enabled is not None:
            kwargs["mention_spam_enabled"] = int(mention_spam_enabled)
        if mention_spam_threshold is not None:
            kwargs["mention_spam_threshold"] = mention_spam_threshold
        if message_spam_enabled is not None:
            kwargs["message_spam_enabled"] = int(message_spam_enabled)
        if message_spam_threshold is not None:
            kwargs["message_spam_threshold"] = message_spam_threshold

        if not kwargs:
            await interaction.response.send_message("No settings changed.", ephemeral=True)
            return

        await db.upsert_antiraid_config(gid, **kwargs)
        self._cache = await db.get_all_antiraid_configs()
        await interaction.response.send_message("Anti-raid settings updated.", ephemeral=True)

    @ar_group.command(name="show", description="Show current anti-raid configuration")
    async def ar_show(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        cfg = await db.get_antiraid_config(gid)
        if not cfg:
            await interaction.response.send_message("Anti-raid is not configured.", ephemeral=True)
            return
        embed = discord.Embed(title="Anti-Raid Configuration", color=0xE74C3C)
        embed.add_field(name="Enabled", value="Yes" if cfg.get("enabled") else "No")
        embed.add_field(name="Action", value=cfg.get("action", "timeout"))
        embed.add_field(name="Mass Join", value=f"{'On' if cfg.get('mass_join_enabled') else 'Off'} (threshold: {cfg.get('mass_join_threshold', 10)})")
        embed.add_field(name="New Account", value=f"{'On' if cfg.get('new_account_enabled') else 'Off'} (min: {cfg.get('new_account_days', 7)} days)")
        embed.add_field(name="Mention Spam", value=f"{'On' if cfg.get('mention_spam_enabled') else 'Off'} (max: {cfg.get('mention_spam_threshold', 5)} mentions)")
        embed.add_field(name="Message Spam", value=f"{'On' if cfg.get('message_spam_enabled') else 'Off'} (max: {cfg.get('message_spam_threshold', 8)} msgs/5s)")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ar_group.command(name="lockdown", description="Lock all channels (remove @everyone Send Messages)")
    async def ar_lockdown(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        everyone = interaction.guild.default_role
        locked = 0
        for ch in interaction.guild.text_channels:
            try:
                overwrite = ch.overwrites_for(everyone)
                overwrite.send_messages = False
                await ch.set_permissions(everyone, overwrite=overwrite, reason="AntiRaid lockdown")
                locked += 1
            except discord.HTTPException:
                pass
        await interaction.followup.send(f"🔒 Lockdown active — {locked} channel(s) locked.", ephemeral=True)

    @ar_group.command(name="unlock", description="Reverse lockdown (restore @everyone Send Messages)")
    async def ar_unlock(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        everyone = interaction.guild.default_role
        unlocked = 0
        for ch in interaction.guild.text_channels:
            try:
                overwrite = ch.overwrites_for(everyone)
                overwrite.send_messages = None  # reset to default
                await ch.set_permissions(everyone, overwrite=overwrite, reason="AntiRaid unlock")
                unlocked += 1
            except discord.HTTPException:
                pass
        await interaction.followup.send(f"🔓 Lockdown lifted — {unlocked} channel(s) unlocked.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AntiRaid(bot))
