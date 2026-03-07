from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from xml.etree import ElementTree

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from dashboard import db

log = logging.getLogger(__name__)

TWITCH_RE = re.compile(r"(?:https?://)?(?:www\.)?twitch\.tv/(\w+)", re.IGNORECASE)
YOUTUBE_CHANNEL_RE = re.compile(r"(?:https?://)?(?:www\.)?youtube\.com/channel/([\w-]+)", re.IGNORECASE)
YOUTUBE_HANDLE_RE = re.compile(r"(?:https?://)?(?:www\.)?youtube\.com/@([\w.-]+)", re.IGNORECASE)

TWITCH_COLOR = 0x9146FF
YOUTUBE_COLOR = 0xFF0000

_YT_CHANNEL_ID_RE = re.compile(r'"channelId":"(UC[\w-]+)"')


async def _resolve_youtube_channel_id(session: aiohttp.ClientSession, handle: str) -> str | None:
    """Fetch youtube.com/@handle and extract the real UC... channel ID."""
    try:
        url = f"https://www.youtube.com/@{handle}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return None
            text = await resp.text()
        m = _YT_CHANNEL_ID_RE.search(text)
        return m.group(1) if m else None
    except Exception:
        log.warning("Failed to resolve YouTube handle @%s", handle)
        return None


class Streaming(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._session: aiohttp.ClientSession | None = None
        self._twitch_token: str | None = None
        self._twitch_client_id = os.getenv("TWITCH_CLIENT_ID", "")
        self._twitch_client_secret = os.getenv("TWITCH_CLIENT_SECRET", "")

    async def cog_load(self):
        self._session = aiohttp.ClientSession()
        self.check_loop.start()

    async def cog_unload(self):
        self.check_loop.cancel()
        if self._session:
            await self._session.close()

    # --- URL parsing ---

    @staticmethod
    def parse_streamer_url(url: str) -> tuple[str, str, str] | None:
        """Returns (platform, username/id, canonical_url) or None."""
        m = TWITCH_RE.match(url)
        if m:
            username = m.group(1).lower()
            return ("twitch", username, f"https://twitch.tv/{username}")

        m = YOUTUBE_CHANNEL_RE.match(url)
        if m:
            channel_id = m.group(1)
            return ("youtube", channel_id, f"https://youtube.com/channel/{channel_id}")

        m = YOUTUBE_HANDLE_RE.match(url)
        if m:
            handle = m.group(1)
            return ("youtube", handle, f"https://youtube.com/@{handle}")

        return None

    # --- Twitch auth ---

    async def _get_twitch_token(self) -> str | None:
        if not self._twitch_client_id or not self._twitch_client_secret:
            return None
        try:
            async with self._session.post(
                "https://id.twitch.tv/oauth2/token",
                data={
                    "client_id": self._twitch_client_id,
                    "client_secret": self._twitch_client_secret,
                    "grant_type": "client_credentials",
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._twitch_token = data.get("access_token")
                    return self._twitch_token
        except Exception:
            log.exception("Failed to get Twitch token")
        return None

    async def _twitch_api(self, endpoint: str, params: dict) -> dict | None:
        if not self._twitch_token:
            await self._get_twitch_token()
        if not self._twitch_token:
            return None

        headers = {
            "Client-ID": self._twitch_client_id,
            "Authorization": f"Bearer {self._twitch_token}",
        }
        try:
            async with self._session.get(
                f"https://api.twitch.tv/helix/{endpoint}",
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 401:
                    # Token expired, refresh and retry once
                    await self._get_twitch_token()
                    if not self._twitch_token:
                        return None
                    headers["Authorization"] = f"Bearer {self._twitch_token}"
                    async with self._session.get(
                        f"https://api.twitch.tv/helix/{endpoint}",
                        headers=headers,
                        params=params,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as retry_resp:
                        if retry_resp.status == 200:
                            return await retry_resp.json()
                        return None
                if resp.status == 200:
                    return await resp.json()
        except Exception:
            log.exception("Twitch API error: %s", endpoint)
        return None

    # --- Slash commands ---

    stream_group = app_commands.Group(
        name="stream",
        description="Streamer go-live notifications",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @stream_group.command(name="add", description="Track a streamer for go-live notifications")
    @app_commands.describe(url="Twitch or YouTube channel URL", channel="Channel to send notifications to", role="Role to mention with announcements (optional)")
    async def stream_add(self, interaction: discord.Interaction, url: str, channel: discord.TextChannel, role: discord.Role = None):
        parsed = self.parse_streamer_url(url)
        if not parsed:
            await interaction.response.send_message(
                "Invalid URL. Supported: `twitch.tv/username`, `youtube.com/channel/ID`, `youtube.com/@handle`",
                ephemeral=True,
            )
            return

        platform, username, canonical_url = parsed
        guild_id = str(interaction.guild_id)

        # Resolve @handle to UC... channel ID for YouTube
        if platform == "youtube" and not username.startswith("UC"):
            await interaction.response.defer(ephemeral=True)
            resolved = await _resolve_youtube_channel_id(self._session, username)
            if not resolved:
                await interaction.followup.send(
                    f"Could not resolve YouTube handle `@{username}` to a channel ID.", ephemeral=True
                )
                return
            username = resolved
            canonical_url = f"https://youtube.com/channel/{resolved}"

        result = await db.add_streaming_config(
            guild_id=guild_id,
            channel_id=str(channel.id),
            streamer_url=canonical_url,
            streamer_name=username,
            platform=platform,
            mention_role_id=str(role.id) if role else None,
        )
        send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        if result is None:
            await send("This streamer is already being tracked in this server.", ephemeral=True)
            return

        msg = f"Now tracking **{username}** ({platform.title()}) in {channel.mention}!"
        if role:
            msg += f" Mentioning {role.mention} with each alert."
        await send(msg, ephemeral=True)

    @stream_group.command(name="remove", description="Stop tracking a streamer")
    @app_commands.describe(url="Twitch or YouTube channel URL to stop tracking")
    async def stream_remove(self, interaction: discord.Interaction, url: str):
        parsed = self.parse_streamer_url(url)
        if not parsed:
            await interaction.response.send_message("Invalid URL.", ephemeral=True)
            return

        _, _, canonical_url = parsed
        guild_id = str(interaction.guild_id)
        configs = await db.get_streaming_configs(guild_id)
        target = next((c for c in configs if c["streamer_url"] == canonical_url), None)
        if not target:
            await interaction.response.send_message("This streamer is not being tracked.", ephemeral=True)
            return

        await db.remove_streaming_config(target["id"])
        await interaction.response.send_message(
            f"Stopped tracking **{target['streamer_name']}**.", ephemeral=True
        )

    @stream_group.command(name="list", description="List all tracked streamers")
    async def stream_list(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        configs = await db.get_streaming_configs(guild_id)
        if not configs:
            await interaction.response.send_message("No streamers are being tracked.", ephemeral=True)
            return

        lines = []
        for c in configs:
            ch = interaction.guild.get_channel(int(c["channel_id"]))
            ch_name = ch.mention if ch else f"#{c['channel_id']}"
            lines.append(f"**{c['streamer_name']}** ({c['platform'].title()}) -> {ch_name}")

        embed = discord.Embed(
            title="Tracked Streamers",
            description="\n".join(lines),
            color=TWITCH_COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- Background loop ---

    @tasks.loop(minutes=2)
    async def check_loop(self):
        try:
            configs = await db.get_all_streaming_configs()
            twitch_configs = [c for c in configs if c["platform"] == "twitch"]
            youtube_configs = [c for c in configs if c["platform"] == "youtube"]

            if twitch_configs:
                await self._check_twitch(twitch_configs)
            if youtube_configs:
                await self._check_youtube(youtube_configs)
        except Exception:
            log.exception("Error in streaming check loop")

    @check_loop.before_loop
    async def before_check_loop(self):
        await self.bot.wait_until_ready()

    async def _check_twitch(self, configs: list[dict]):
        if not self._twitch_client_id:
            return

        # Batch by username
        by_name: dict[str, list[dict]] = {}
        for c in configs:
            by_name.setdefault(c["streamer_name"], []).append(c)

        # Check in batches of 100 (Twitch limit)
        names = list(by_name.keys())
        for i in range(0, len(names), 100):
            batch = names[i:i + 100]
            data = await self._twitch_api("streams", {"user_login": batch})
            if not data:
                continue

            live_streams = {s["user_login"].lower(): s for s in data.get("data", [])}

            for name in batch:
                stream = live_streams.get(name.lower())
                for cfg in by_name[name]:
                    if stream:
                        stream_id = stream["id"]
                        if cfg.get("last_stream_id") == stream_id:
                            continue
                        # New stream detected
                        await db.update_streaming_notified(cfg["id"], stream_id)
                        await self._send_twitch_notification(cfg, stream)

    async def _send_twitch_notification(self, cfg: dict, stream: dict):
        guild = self.bot.get_guild(int(cfg["guild_id"]))
        if not guild:
            return
        channel = guild.get_channel(int(cfg["channel_id"]))
        if not channel:
            return

        title = stream.get("title", "Live Stream")
        game = stream.get("game_name", "")
        viewers = stream.get("viewer_count", 0)
        username = stream.get("user_name", cfg["streamer_name"])
        thumbnail = stream.get("thumbnail_url", "").replace("{width}", "440").replace("{height}", "248")

        embed = discord.Embed(
            title=f"{username} is live on Twitch!",
            url=f"https://twitch.tv/{cfg['streamer_name']}",
            description=title,
            color=TWITCH_COLOR,
        )
        if game:
            embed.add_field(name="Game", value=game, inline=True)
        embed.add_field(name="Viewers", value=str(viewers), inline=True)
        if thumbnail:
            embed.set_image(url=thumbnail)
        embed.timestamp = datetime.now(timezone.utc)

        mention_role_id = cfg.get("mention_role_id")
        content = f"<@&{mention_role_id}>" if mention_role_id else None

        try:
            await channel.send(content=content, embed=embed)
        except discord.HTTPException:
            log.warning("Failed to send Twitch notification for %s in %s/%s", username, guild.id, channel.id)

    async def _check_youtube(self, configs: list[dict]):
        # Group configs by channel ID to avoid N+1 HTTP requests
        by_channel: dict[str, list[dict]] = {}
        for cfg in configs:
            streamer_name = cfg["streamer_name"]
            channel_id = streamer_name if streamer_name.startswith("UC") else streamer_name
            by_channel.setdefault(channel_id, []).append(cfg)

        for channel_id, cfgs in by_channel.items():
            try:
                feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
                async with self._session.get(feed_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        continue
                    text = await resp.text()

                root = ElementTree.fromstring(text)
                ns = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
                entries = root.findall("atom:entry", ns)
                if not entries:
                    continue

                latest = entries[0]
                video_id_elem = latest.find("yt:videoId", ns)
                if video_id_elem is None:
                    continue
                video_id = video_id_elem.text

                title_elem = latest.find("atom:title", ns)
                title = title_elem.text if title_elem is not None else "New Video"
                author_elem = root.find("atom:title", ns)
                author = author_elem.text if author_elem is not None else channel_id

                # Notify each guild tracking this channel
                for cfg in cfgs:
                    if cfg.get("last_stream_id") == video_id:
                        continue
                    await db.update_streaming_notified(cfg["id"], video_id)
                    await self._send_youtube_notification(cfg, video_id, title, author)
            except Exception:
                log.exception("Error checking YouTube for channel %s", channel_id)

    async def _send_youtube_notification(self, cfg: dict, video_id: str, title: str, author: str):
        guild = self.bot.get_guild(int(cfg["guild_id"]))
        if not guild:
            return
        channel = guild.get_channel(int(cfg["channel_id"]))
        if not channel:
            return

        url = f"https://youtube.com/watch?v={video_id}"
        embed = discord.Embed(
            title=f"{author} uploaded a new video!",
            url=url,
            description=title,
            color=YOUTUBE_COLOR,
        )
        embed.set_thumbnail(url=f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg")
        embed.timestamp = datetime.now(timezone.utc)

        mention_role_id = cfg.get("mention_role_id")
        content = f"<@&{mention_role_id}>" if mention_role_id else None

        try:
            await channel.send(content=content, embed=embed)
        except discord.HTTPException:
            log.warning("Failed to send YouTube notification for %s in %s/%s", author, guild.id, channel.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(Streaming(bot))
