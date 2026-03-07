from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import time
from datetime import timedelta
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from dashboard import db

log = logging.getLogger(__name__)

LINK_RE = re.compile(r"https?://\S+", re.IGNORECASE)
CUSTOM_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")
UNICODE_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "]+",
)

STANDALONE_TYPES = {"contains_link", "contains_file", "contains_emoji", "contains_role_mention"}

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"


class CustomCommands(commands.Cog):
    """Handles custom text, embed, and auto-reply commands stored in the database."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cache: dict[str, list[dict]] = {}
        self._cooldowns: dict[tuple[str, str, int], float] = {}
        self._cooldown_cleanup_counter = 0
        self._settings_cache: dict[str, tuple[str, float]] = {}
        self._SETTINGS_TTL = 60
        self._regex_cache: dict[int, list[re.Pattern]] = {}

    async def cog_load(self):
        await self.refresh_cache()

    async def refresh_cache(self):
        """Reload all commands from the database into memory."""
        all_cmds = await db.get_commands()
        self._cache.clear()
        self._regex_cache.clear()
        for cmd in all_cmds:
            if not cmd["enabled"]:
                continue
            key = cmd["guild_id"] or "__global__"
            self._cache.setdefault(key, []).append(cmd)
        log.info("Custom commands cache refreshed: %d commands loaded", len(all_cmds))

    async def _cached_setting(self, key: str, default: str = "1") -> str:
        now = time.time()
        cached = self._settings_cache.get(key)
        if cached and now - cached[1] < self._SETTINGS_TTL:
            return cached[0]
        value = await db.get_setting(key, default)
        self._settings_cache[key] = (value, now)
        return value

    async def _cached_guild_setting(self, guild_id: str, key: str, default: str = "") -> str:
        cache_key = f"{guild_id}:{key}"
        now = time.time()
        cached = self._settings_cache.get(cache_key)
        if cached and now - cached[1] < self._SETTINGS_TTL:
            return cached[0]
        value = await db.get_guild_setting(guild_id, key)
        if value is None:
            value = await db.get_setting(key, default)
        self._settings_cache[cache_key] = (value, now)
        return value

    def _get_commands_for(self, guild_id: str) -> list[dict]:
        result = list(self._cache.get("__global__", []))
        result.extend(self._cache.get(guild_id, []))
        result.sort(key=lambda c: c.get("priority", 0), reverse=True)
        return result

    @staticmethod
    def _substitute_variables(text: str, message: discord.Message, args: str = "") -> str:
        if not text:
            return text
        replacements = {
            "{user}": message.author.mention,
            "{username}": str(message.author),
            "{server}": message.guild.name if message.guild else "",
            "{channel}": message.channel.name if hasattr(message.channel, "name") else "",
            "{membercount}": str(message.guild.member_count) if message.guild else "0",
            "{args}": args,
        }
        for key, value in replacements.items():
            text = text.replace(key, value)
        return text

    @staticmethod
    def _pick_response(text: str) -> str:
        if not text:
            return text
        parts = [p.strip() for p in text.split("---") if p.strip()]
        return random.choice(parts) if parts else text

    @staticmethod
    def _check_filters(message: discord.Message, cmd: dict) -> bool:
        """Check if the message passes all additional filter requirements."""
        if cmd.get("filter_has_link") and not LINK_RE.search(message.content):
            return False
        if cmd.get("filter_has_file") and not message.attachments:
            return False
        if cmd.get("filter_has_emoji"):
            if not CUSTOM_EMOJI_RE.search(message.content) and not UNICODE_EMOJI_RE.search(message.content):
                return False
        if cmd.get("filter_has_role_mention") and not message.role_mentions:
            return False
        return True

    @staticmethod
    def _check_standalone_trigger(message: discord.Message, trigger_type: str) -> bool:
        """Check if a message matches a standalone trigger type."""
        if trigger_type == "contains_link":
            return bool(LINK_RE.search(message.content))
        if trigger_type == "contains_file":
            return bool(message.attachments)
        if trigger_type == "contains_emoji":
            return bool(CUSTOM_EMOJI_RE.search(message.content) or UNICODE_EMOJI_RE.search(message.content))
        if trigger_type == "contains_role_mention":
            return bool(message.role_mentions)
        return False

    def _get_trigger_patterns(self, cmd: dict) -> list[str]:
        """Get list of trigger patterns from multi-trigger JSON or single pattern."""
        raw = cmd.get("trigger_patterns")
        if raw:
            try:
                patterns = json.loads(raw)
                if isinstance(patterns, list) and patterns:
                    return [p for p in patterns if p]
            except (json.JSONDecodeError, TypeError):
                pass
        single = cmd.get("trigger_pattern", "")
        return [single] if single else []

    def _get_compiled_regex(self, cmd: dict) -> list[re.Pattern]:
        """Get compiled regex patterns for a command, using cache."""
        cmd_id = cmd["id"]
        if cmd_id in self._regex_cache:
            return self._regex_cache[cmd_id]
        patterns = self._get_trigger_patterns(cmd)
        compiled = []
        for p in patterns:
            try:
                compiled.append(re.compile(p, re.IGNORECASE))
            except re.error:
                log.warning("Invalid regex pattern for cmd %d: %s", cmd_id, p)
        self._regex_cache[cmd_id] = compiled
        return compiled

    def _matches_triggers(self, cmd: dict, content: str) -> bool:
        """Check if content matches any trigger pattern (regex or substring)."""
        use_regex = bool(cmd.get("use_regex", 0))
        if use_regex:
            compiled = self._get_compiled_regex(cmd)
            return any(p.search(content) for p in compiled)
        else:
            patterns = self._get_trigger_patterns(cmd)
            content_lower = content.lower()
            return any(p.lower() in content_lower for p in patterns)

    async def _apply_reactions(self, message: discord.Message, cmd: dict):
        """React to the triggering message with configured emojis."""
        raw = cmd.get("reaction_emojis")
        if not raw:
            return
        try:
            emojis = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return
        for emoji_str in emojis:
            emoji_str = emoji_str.strip()
            if not emoji_str:
                continue
            try:
                await message.add_reaction(emoji_str)
            except discord.HTTPException:
                log.warning("Failed to add reaction %s to message %d", emoji_str, message.id)

    async def _schedule_auto_delete(self, bot_message: discord.Message, seconds: int):
        """Schedule deletion of the bot's response after N seconds."""
        async def _delete():
            await asyncio.sleep(seconds)
            try:
                await bot_message.delete()
            except discord.HTTPException:
                pass
        asyncio.create_task(_delete())

    async def _apply_mod_action(self, message: discord.Message, cmd: dict):
        """Apply moderation action to the triggering user."""
        action = cmd.get("mod_action")
        value = cmd.get("mod_action_value", "")
        if not action:
            return
        member = message.author
        guild = message.guild
        try:
            if action == "warn":
                try:
                    await member.send(f"Warning from **{guild.name}**: Your message triggered a moderation rule.")
                except discord.HTTPException:
                    pass
            elif action == "timeout":
                seconds = int(value) if value else 60
                await member.timeout(timedelta(seconds=seconds), reason="Auto-reply mod action")
            elif action == "add_role":
                role = guild.get_role(int(value))
                if role:
                    await member.add_roles(role, reason="Auto-reply mod action")
        except Exception as e:
            log.error("Failed mod action %s for cmd %s: %s", action, cmd["name"], e)

    # --- Slash commands ---

    cc_group = app_commands.Group(
        name="customcommand",
        description="Manage custom commands",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @cc_group.command(name="add", description="Add a custom text command")
    @app_commands.describe(name="Command name (without prefix)", response="The text response")
    async def cc_add(self, interaction: discord.Interaction, name: str, response: str):
        guild_id = str(interaction.guild_id)
        await db.create_command(guild_id=guild_id, name=name, type="text", response_text=response)
        await self.refresh_cache()
        await interaction.response.send_message(f"Custom command `{name}` created.", ephemeral=True)

    @cc_group.command(name="remove", description="Remove a custom command")
    @app_commands.describe(name="Command name to remove")
    async def cc_remove(self, interaction: discord.Interaction, name: str):
        guild_id = str(interaction.guild_id)
        deleted = await db.delete_command_by_name_and_guild(guild_id, name)
        if not deleted:
            await interaction.response.send_message(f"No command named `{name}` found.", ephemeral=True)
            return
        await self.refresh_cache()
        await interaction.response.send_message(f"Custom command `{name}` removed.", ephemeral=True)

    @cc_group.command(name="list", description="List all custom commands in this server")
    async def cc_list(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        cmds = await db.get_commands(guild_id)
        if not cmds:
            await interaction.response.send_message("No custom commands configured.", ephemeral=True)
            return

        lines = []
        for cmd in cmds:
            scope = "Global" if cmd["guild_id"] is None else "Server"
            status = "Enabled" if cmd["enabled"] else "Disabled"
            uses = cmd.get("usage_count", 0)
            lines.append(f"`{cmd['name']}` — {cmd['type']} ({scope}, {status}) | {uses} uses")

        embed = discord.Embed(
            title="Custom Commands",
            description="\n".join(lines),
            color=0x3498DB,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        enabled = await self._cached_setting("custom_commands_enabled", "1")
        if enabled != "1":
            return

        guild_id = str(message.guild.id)
        cmds = self._get_commands_for(guild_id)
        if not cmds:
            return

        content = message.content.strip()
        prefix = await self._cached_guild_setting(guild_id, "command_prefix", "!")

        for cmd in cmds:
            cmd_type = cmd["type"]

            if cmd_type == "auto_reply":
                ar_enabled = await self._cached_setting("auto_replies_enabled", "1")
                if ar_enabled != "1":
                    continue
                if self._matches_triggers(cmd, content):
                    if not self._check_filters(message, cmd):
                        continue
                    args = ""
                    if await self._check_and_apply(message, cmd, guild_id, args):
                        # Delete triggering message if configured
                        if cmd.get("delete_trigger"):
                            try:
                                await message.delete()
                            except discord.HTTPException:
                                pass
                        await self._send_response(message, cmd, args)
                        await self._apply_reactions(message, cmd)
                        await self._apply_mod_action(message, cmd)
                    return

            elif cmd_type in STANDALONE_TYPES:
                ar_enabled = await self._cached_setting("auto_replies_enabled", "1")
                if ar_enabled != "1":
                    continue
                if not self._check_standalone_trigger(message, cmd_type):
                    continue
                if not self._check_filters(message, cmd):
                    continue
                args = ""
                if await self._check_and_apply(message, cmd, guild_id, args):
                    if cmd.get("delete_trigger"):
                        try:
                            await message.delete()
                        except discord.HTTPException:
                            pass
                    await self._send_response(message, cmd, args)
                    await self._apply_reactions(message, cmd)
                    await self._apply_mod_action(message, cmd)
                return

            else:
                # Prefix command (text / embed)
                matched = False
                trigger = f"{prefix}{cmd['name']}"
                if content.lower() == trigger.lower() or content.lower().startswith(trigger.lower() + " "):
                    args = content[len(trigger):].strip()
                    matched = True
                elif cmd.get("no_prefix"):
                    name = cmd["name"]
                    if content.lower() == name.lower() or content.lower().startswith(name.lower() + " "):
                        args = content[len(name):].strip()
                        matched = True
                if matched:
                    if await self._check_and_apply(message, cmd, guild_id, args):
                        await self._send_response(message, cmd, args)
                    return

    async def _check_and_apply(self, message: discord.Message, cmd: dict, guild_id: str, args: str) -> bool:
        user_id = str(message.author.id)
        cmd_id = cmd["id"]

        required_role_id = cmd.get("required_role_id")
        if required_role_id:
            member = message.author
            if not any(str(r.id) == required_role_id for r in member.roles):
                return False

        cooldown = cmd.get("cooldown", 0)
        if cooldown and cooldown > 0:
            key = (guild_id, user_id, cmd_id)
            now = time.time()
            last_used = self._cooldowns.get(key, 0)
            if now - last_used < cooldown:
                return False
            self._cooldowns[key] = now

        await db.increment_usage_count(cmd_id)

        self._cooldown_cleanup_counter += 1
        if self._cooldown_cleanup_counter >= 500:
            self._cooldown_cleanup_counter = 0
            now = time.time()
            self._cooldowns = {
                k: v for k, v in self._cooldowns.items()
                if now - v < 3600
            }

        return True

    async def _send_response(self, message: discord.Message, cmd: dict, args: str = ""):
        channel = message.channel
        use_tts = bool(cmd.get("tts", 0))
        response_image_url = cmd.get("response_image_url")
        auto_delete = cmd.get("auto_delete_seconds", 0) or 0

        # Prepare attachment file if configured
        attachment_file = None
        attachment_path = cmd.get("attachment_path")
        if attachment_path:
            full_path = UPLOAD_DIR / attachment_path
            if full_path.is_file():
                attachment_file = discord.File(str(full_path), filename=attachment_path)

        sent_msg = None

        if cmd["type"] == "embed" and cmd.get("embed_json"):
            try:
                data = json.loads(cmd["embed_json"])
                title = self._substitute_variables(data.get("title", ""), message, args)
                description = self._substitute_variables(data.get("description", ""), message, args)
                description = self._pick_response(description)

                embed = discord.Embed(
                    title=title,
                    description=description,
                    color=data.get("color", 0x3498db),
                )
                footer = data.get("footer")
                if footer:
                    embed.set_footer(text=self._substitute_variables(footer, message, args))
                if data.get("thumbnail"):
                    embed.set_thumbnail(url=data["thumbnail"])
                for field in data.get("fields", []):
                    embed.add_field(
                        name=self._substitute_variables(field.get("name", ""), message, args),
                        value=self._substitute_variables(field.get("value", ""), message, args),
                        inline=field.get("inline", True),
                    )

                # Embed image / thumbnail from uploaded files
                files_to_send = []
                embed_image_path = cmd.get("embed_image_path")
                if embed_image_path:
                    img_full = UPLOAD_DIR / embed_image_path
                    if img_full.is_file():
                        files_to_send.append(discord.File(str(img_full), filename=embed_image_path))
                        embed.set_image(url=f"attachment://{embed_image_path}")

                embed_thumb_path = cmd.get("embed_thumbnail_path")
                if embed_thumb_path:
                    thumb_full = UPLOAD_DIR / embed_thumb_path
                    if thumb_full.is_file():
                        files_to_send.append(discord.File(str(thumb_full), filename=embed_thumb_path))
                        embed.set_thumbnail(url=f"attachment://{embed_thumb_path}")

                if attachment_file:
                    files_to_send.append(attachment_file)

                content_text = cmd.get("response_text")
                if content_text:
                    content_text = self._pick_response(content_text)
                    content_text = self._substitute_variables(content_text, message, args)

                sent_msg = await channel.send(
                    content=content_text, embed=embed, tts=use_tts,
                    files=files_to_send if files_to_send else None,
                )
            except (json.JSONDecodeError, Exception) as e:
                log.error("Failed to build embed for command %s: %s", cmd["name"], e)
                if cmd.get("response_text"):
                    text = self._pick_response(cmd["response_text"])
                    text = self._substitute_variables(text, message, args)
                    sent_msg = await channel.send(text, tts=use_tts)
        elif cmd.get("response_text"):
            text = self._pick_response(cmd["response_text"])
            text = self._substitute_variables(text, message, args)
            files_to_send = [attachment_file] if attachment_file else None

            # Wrap in embed if response_image_url is set and type is not embed
            if response_image_url and cmd["type"] != "embed":
                embed = discord.Embed(description=text, color=0x3498db)
                embed.set_image(url=response_image_url)
                sent_msg = await channel.send(embed=embed, tts=use_tts, files=files_to_send)
            else:
                sent_msg = await channel.send(text, tts=use_tts, files=files_to_send)
        elif response_image_url and cmd["type"] != "embed":
            embed = discord.Embed(color=0x3498db)
            embed.set_image(url=response_image_url)
            sent_msg = await channel.send(embed=embed, tts=use_tts)
        elif attachment_file:
            sent_msg = await channel.send(files=[attachment_file], tts=use_tts)

        # Schedule auto-delete of bot response
        if sent_msg and auto_delete > 0:
            await self._schedule_auto_delete(sent_msg, auto_delete)


async def setup(bot: commands.Bot):
    await bot.add_cog(CustomCommands(bot))
