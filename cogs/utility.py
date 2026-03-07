from __future__ import annotations

import ipaddress
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands, tasks

from dashboard import db
from utils.time_parser import parse_duration, format_duration
from utils.youtube import download_media

log = logging.getLogger(__name__)


HELP_CATEGORIES: dict[str, list[tuple[str, str]]] = {
    "Music": [
        ("play", "Play a song from YouTube/URL"),
        ("search", "Search YouTube and pick a result"),
        ("skip", "Skip the current track"),
        ("pause", "Pause playback"),
        ("resume", "Resume playback"),
        ("stop", "Stop playback and clear the queue"),
        ("queue", "Show the current queue"),
        ("nowplaying", "Show the currently playing track"),
        ("volume", "Set playback volume"),
        ("loop", "Toggle loop mode"),
        ("shuffle", "Shuffle the queue"),
        ("remove", "Remove a track from the queue"),
        ("move", "Move a track in the queue"),
        ("disconnect", "Disconnect the bot from voice"),
    ],
    "Soundboard": [
        ("soundboard", "Play a soundboard clip in voice"),
        ("sb", "Shortcut for /soundboard"),
    ],
    "TTS": [
        ("tts", "Send a text-to-speech message in voice"),
        ("ttsconfig", "Configure TTS voice settings"),
    ],
    "Moderation": [
        ("kick", "Kick a member from the server"),
        ("ban", "Ban a member from the server"),
        ("unban", "Unban a user"),
        ("timeout", "Timeout a member"),
        ("warn", "Warn a member"),
        ("warnings", "View warnings for a member"),
        ("clearwarnings", "Clear warnings for a member"),
        ("purge", "Delete multiple messages"),
        ("clean", "Delete bot messages"),
    ],
    "Leveling": [
        ("rank", "View your or another member's rank"),
        ("leaderboard", "View the server XP leaderboard"),
        ("xp", "Manage XP for a member"),
    ],
    "Utility": [
        ("help", "Show this help menu"),
        ("userinfo", "Show information about a user"),
        ("serverinfo", "Show information about this server"),
        ("avatar", "Show a user's avatar"),
        ("poll", "Create a simple poll"),
        ("remind", "Set a reminder"),
        ("reminders", "List your active reminders"),
        ("cancelreminder", "Cancel a reminder by ID"),
        ("download", "Download audio/video from a URL"),
    ],
    "Notifications": [
        ("freestuff setup", "Set up free game notifications"),
        ("freestuff disable", "Disable free game notifications"),
        ("freestuff config", "View free game notification config"),
        ("freestuff check", "Manually check for free games"),
        ("stream add", "Track a streamer for go-live notifications"),
        ("stream remove", "Stop tracking a streamer"),
        ("stream list", "List tracked streamers"),
    ],
    "Server Config": [
        ("welcome", "Configure welcome messages"),
        ("auditlog", "Configure audit logging"),
        ("reactionrole", "Set up reaction roles"),
        ("customcommand", "Manage custom commands"),
        ("musicconfig", "Configure music settings"),
    ],
}


class Utility(commands.Cog):
    """General-purpose slash commands: userinfo, serverinfo, avatar, poll, remind."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.reminder_loop.start()

    async def cog_unload(self):
        self.reminder_loop.cancel()

    # --- /help ---

    @app_commands.command(name="help", description="Show available bot commands")
    @app_commands.describe(category="Command category to view in detail")
    async def help_command(self, interaction: discord.Interaction, category: str | None = None):
        if category:
            cmds = HELP_CATEGORIES.get(category)
            if cmds is None:
                await interaction.response.send_message("Unknown category.", ephemeral=True)
                return
            embed = discord.Embed(title=f"{category} Commands", color=0x3498DB)
            for name, desc in cmds:
                embed.add_field(name=f"/{name}", value=desc, inline=False)
        else:
            embed = discord.Embed(title="Bot Commands", description="Use `/help <category>` for details.", color=0x3498DB)
            for cat, cmds in HELP_CATEGORIES.items():
                names = "  ".join(f"`/{c[0]}`" for c in cmds)
                embed.add_field(name=cat, value=names, inline=False)

        await interaction.response.send_message(embed=embed)

    @help_command.autocomplete("category")
    async def help_category_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=cat, value=cat)
            for cat in HELP_CATEGORIES
            if current.lower() in cat.lower()
        ][:25]

    # --- /userinfo ---

    @app_commands.command(name="userinfo", description="Show information about a user")
    @app_commands.describe(member="The user to inspect (defaults to you)")
    async def userinfo(self, interaction: discord.Interaction, member: discord.Member | None = None):
        member = member or interaction.user
        embed = discord.Embed(title=str(member), color=member.color or 0x3498DB)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ID", value=member.id)
        embed.add_field(name="Nickname", value=member.nick or "None")
        embed.add_field(name="Top Role", value=member.top_role.mention if member.top_role != member.guild.default_role else "None")
        embed.add_field(name="Joined Server", value=discord.utils.format_dt(member.joined_at, "R") if member.joined_at else "?")
        embed.add_field(name="Account Created", value=discord.utils.format_dt(member.created_at, "R"))
        embed.add_field(name="Roles", value=", ".join(r.mention for r in member.roles[1:][:10]) or "None", inline=False)
        await interaction.response.send_message(embed=embed)

    # --- /serverinfo ---

    @app_commands.command(name="serverinfo", description="Show information about this server")
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        embed = discord.Embed(title=guild.name, color=0x3498DB)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="Owner", value=str(guild.owner))
        embed.add_field(name="Members", value=guild.member_count or 0)
        embed.add_field(name="Roles", value=len(guild.roles))
        embed.add_field(name="Text Channels", value=len(guild.text_channels))
        embed.add_field(name="Voice Channels", value=len(guild.voice_channels))
        embed.add_field(name="Created", value=discord.utils.format_dt(guild.created_at, "R"))
        embed.add_field(name="Boost Level", value=guild.premium_tier)
        embed.add_field(name="Boosts", value=guild.premium_subscription_count or 0)
        await interaction.response.send_message(embed=embed)

    # --- /avatar ---

    @app_commands.command(name="avatar", description="Show a user's avatar")
    @app_commands.describe(member="The user whose avatar to show")
    async def avatar(self, interaction: discord.Interaction, member: discord.Member | None = None):
        member = member or interaction.user
        embed = discord.Embed(title=f"{member}'s Avatar", color=0x3498DB)
        embed.set_image(url=member.display_avatar.with_size(512).url)
        await interaction.response.send_message(embed=embed)

    # --- /poll ---

    @app_commands.command(name="poll", description="Create a simple poll")
    @app_commands.describe(question="The poll question", options="Comma-separated options (2–9)")
    async def poll(self, interaction: discord.Interaction, question: str, options: str):
        choices = [o.strip() for o in options.split(",") if o.strip()]
        if len(choices) < 2 or len(choices) > 9:
            await interaction.response.send_message("Provide 2–9 comma-separated options.", ephemeral=True)
            return
        number_emojis = ["1\u20e3", "2\u20e3", "3\u20e3", "4\u20e3", "5\u20e3", "6\u20e3", "7\u20e3", "8\u20e3", "9\u20e3"]
        desc = "\n".join(f"{number_emojis[i]} {c}" for i, c in enumerate(choices))
        embed = discord.Embed(title=question, description=desc, color=0xF39C12)
        embed.set_footer(text=f"Poll by {interaction.user}")
        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()
        for i in range(len(choices)):
            await msg.add_reaction(number_emojis[i])

    # --- /remind ---

    @app_commands.command(name="remind", description="Set a reminder (e.g. /remind 10m Take out trash)")
    @app_commands.describe(time="Duration like 10m, 1h30m, 2d", message="What to remind you about")
    async def remind(self, interaction: discord.Interaction, time: str, message: str):
        seconds = parse_duration(time)
        if seconds is None or seconds < 10:
            await interaction.response.send_message("Invalid duration. Use formats like `10m`, `1h30m`, `2d`.", ephemeral=True)
            return
        if seconds > 30 * 86400:
            await interaction.response.send_message("Maximum reminder duration is 30 days.", ephemeral=True)
            return

        remind_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        await db.create_reminder(
            guild_id=str(interaction.guild_id),
            channel_id=str(interaction.channel_id),
            user_id=str(interaction.user.id),
            message=message,
            remind_at=remind_at.isoformat(),
        )

        await interaction.response.send_message(
            f"Reminder set! I'll remind you in **{format_duration(seconds)}**."
        )

    # --- Reminder loop ---

    # --- /reminders ---

    @app_commands.command(name="reminders", description="List your active reminders")
    async def reminders(self, interaction: discord.Interaction):
        user_reminders = await db.get_user_reminders(str(interaction.guild_id), str(interaction.user.id))
        if not user_reminders:
            await interaction.response.send_message("You have no active reminders.", ephemeral=True)
            return

        lines = []
        for r in user_reminders:
            remind_at = datetime.fromisoformat(r["remind_at"])
            lines.append(f"**#{r['id']}** — {r['message']}\nDue: {discord.utils.format_dt(remind_at, 'R')}")

        embed = discord.Embed(
            title="Your Reminders",
            description="\n\n".join(lines),
            color=0x3498DB,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- /cancelreminder ---

    @app_commands.command(name="cancelreminder", description="Cancel a reminder by ID")
    @app_commands.describe(reminder_id="The reminder ID to cancel")
    async def cancelreminder(self, interaction: discord.Interaction, reminder_id: int):
        user_reminders = await db.get_user_reminders(str(interaction.guild_id), str(interaction.user.id))
        if not any(r["id"] == reminder_id for r in user_reminders):
            await interaction.response.send_message("Reminder not found or you don't own it.", ephemeral=True)
            return
        await db.delete_reminder(reminder_id)
        await interaction.response.send_message(f"Cancelled reminder **#{reminder_id}**.")

    # --- /download ---

    @staticmethod
    def _is_safe_url(url: str) -> bool:
        """Block non-http(s) schemes and private/reserved IP ranges."""
        try:
            parsed = urlparse(url)
        except Exception:
            return False
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        try:
            addr = ipaddress.ip_address(hostname)
            if addr.is_private or addr.is_reserved or addr.is_loopback or addr.is_link_local:
                return False
        except ValueError:
            # Not an IP literal — check for localhost
            if hostname.lower() in ("localhost", "0.0.0.0"):
                return False
        return True

    @app_commands.command(name="download", description="Download audio or video from a URL")
    @app_commands.describe(
        url="URL to download from (YouTube, etc.)",
        audio_only="Download audio only as mp3 (default: True)",
    )
    async def download(self, interaction: discord.Interaction, url: str, audio_only: bool = True):
        if not self._is_safe_url(url):
            await interaction.response.send_message(
                "Invalid or blocked URL. Only public http/https URLs are allowed.", ephemeral=True
            )
            return
        await interaction.response.defer(thinking=True)
        tmpdir = None
        try:
            result = await download_media(url, audio_only=audio_only)
            if result is None:
                await interaction.followup.send("Failed to download. Check the URL and try again.")
                return

            file_path, filename = result
            tmpdir = os.path.dirname(file_path)

            file_size = os.path.getsize(file_path)
            size_limit = getattr(interaction.guild, "filesize_limit", 25 * 1024 * 1024)
            if file_size > size_limit:
                size_mb = file_size / (1024 * 1024)
                await interaction.followup.send(
                    f"The file is too large to upload ({size_mb:.1f} MB). "
                    f"Discord limit for this server is {size_limit // (1024 * 1024)} MB."
                )
                return

            label = "audio" if audio_only else "video"
            await interaction.followup.send(
                content=f"Here's your {label}:",
                file=discord.File(file_path, filename=filename),
            )
        except Exception:
            log.exception("Error in /download")
            await interaction.followup.send("An error occurred while downloading.")
        finally:
            if tmpdir and os.path.isdir(tmpdir):
                shutil.rmtree(tmpdir, ignore_errors=True)

    # --- Reminder loop ---

    @tasks.loop(seconds=15)
    async def reminder_loop(self):
        now = datetime.now(timezone.utc).isoformat()
        due = await db.get_due_reminders(now)
        for r in due:
            channel = self.bot.get_channel(int(r["channel_id"]))
            if channel is None:
                log.warning("Reminder #%s: channel %s not found, deleting.", r["id"], r["channel_id"])
                await db.delete_reminder(r["id"])
                continue
            try:
                await channel.send(f"<@{r['user_id']}> Reminder: **{r['message']}**")
                await db.delete_reminder(r["id"])
            except discord.Forbidden:
                log.warning("Reminder #%s: Forbidden in channel %s, deleting.", r["id"], r["channel_id"])
                await db.delete_reminder(r["id"])
            except discord.HTTPException:
                # Transient error — increment fail count, delete after 5 failures
                fail_count = await db.increment_reminder_fail_count(r["id"])
                if fail_count >= 5:
                    log.warning("Reminder #%s: failed %d times, deleting.", r["id"], fail_count)
                    await db.delete_reminder(r["id"])
                else:
                    log.warning("Reminder #%s: send failed (%d/5).", r["id"], fail_count)

    @reminder_loop.before_loop
    async def before_reminder_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))
