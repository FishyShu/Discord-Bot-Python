from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from dashboard import db

log = logging.getLogger(__name__)

TWITCH_DROP_COLOR = 0x9146FF


def build_drop_embed(
    drop: dict,
    *,
    embed_color: str | None = None,
    show_game: bool = True,
    show_period: bool = True,
    show_description: bool = True,
    show_image: bool = True,
    show_link: bool = True,
) -> discord.Embed:
    color = int(embed_color.lstrip("#"), 16) if embed_color else TWITCH_DROP_COLOR
    embed = discord.Embed(title=f"New Twitch Drop: {drop['drop_name'][:100]}", color=color)
    if show_game:
        embed.add_field(name="Game", value=drop["game_name"], inline=True)
    if show_period and drop.get("start_date") and drop.get("end_date"):
        embed.add_field(name="Period", value=f"{drop['start_date'][:10]} — {drop['end_date'][:10]}", inline=True)
    if show_description and drop.get("description"):
        embed.add_field(name="Description", value=drop["description"][:200], inline=False)
    if show_image and drop.get("image_url"):
        embed.set_thumbnail(url=drop["image_url"])
    if show_link and drop.get("details_url"):
        embed.add_field(name="Link", value=f"[View Details]({drop['details_url']})", inline=False)
    embed.set_footer(text="Twitch Drops Alert")
    embed.timestamp = datetime.now(timezone.utc)
    return embed


class TwitchDrops(commands.Cog):
    """Notifies servers about new Twitch Drops campaigns."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cache: dict[str, dict] = {}
        self._session: aiohttp.ClientSession | None = None
        self._send_semaphore = asyncio.Semaphore(10)
        self._client_id = os.getenv("TWITCH_CLIENT_ID", "")
        self._client_secret = os.getenv("TWITCH_CLIENT_SECRET", "")
        self._access_token: str | None = None
        self._token_expiry: float = 0.0

    async def cog_load(self):
        await self.refresh_cache()
        self._session = aiohttp.ClientSession()
        self.check_loop.start()

    async def cog_unload(self):
        self.check_loop.cancel()
        if self._session:
            await self._session.close()

    async def refresh_cache(self):
        self._cache = await db.get_all_twitch_drops_configs_dict()

    async def _get_access_token(self) -> str | None:
        """Get or refresh Twitch OAuth app access token."""
        now = time.time()
        if self._access_token and now < self._token_expiry - 60:
            return self._access_token
        if not self._client_id or not self._client_secret:
            return None
        try:
            async with self._session.post(
                "https://id.twitch.tv/oauth2/token",
                params={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "client_credentials",
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    log.warning("Failed to get Twitch access token: %s", resp.status)
                    return None
                data = await resp.json()
                self._access_token = data.get("access_token")
                self._token_expiry = now + data.get("expires_in", 3600)
                log.info("Twitch access token refreshed, expires in %ds", data.get("expires_in", 3600))
                return self._access_token
        except Exception:
            log.exception("Error getting Twitch access token")
            return None

    # --- Slash commands ---

    drops_group = app_commands.Group(
        name="twitchdrops",
        description="Twitch Drops notifications",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @drops_group.command(name="setup", description="Set up Twitch Drops notifications in a channel")
    @app_commands.describe(channel="Channel to send drop alerts to", role="Role to mention with announcements (optional)")
    async def drops_setup(self, interaction: discord.Interaction, channel: discord.TextChannel, role: discord.Role = None):
        guild_id = str(interaction.guild_id)
        kwargs = {"channel_id": str(channel.id), "enabled": 1}
        if role:
            kwargs["mention_role_id"] = str(role.id)
        await db.upsert_twitch_drops_config(guild_id, **kwargs)
        await self.refresh_cache()
        msg = f"Twitch Drops notifications enabled in {channel.mention}!"
        if role:
            msg += f" Mentioning {role.mention} with each alert."
        await interaction.response.send_message(msg, ephemeral=True)

    @drops_group.command(name="disable", description="Disable Twitch Drops notifications")
    async def drops_disable(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        await db.upsert_twitch_drops_config(guild_id, enabled=0)
        await self.refresh_cache()
        await interaction.response.send_message("Twitch Drops notifications disabled.", ephemeral=True)

    async def _game_autocomplete(self, interaction: discord.Interaction, current: str):
        games = await db.get_all_cached_game_statuses()
        return [
            app_commands.Choice(name=g["game_name"], value=g["game_name"])
            for g in games
            if current.lower() in g["game_name"].lower()
        ][:25]

    @drops_group.command(name="filter", description="Set game filter for drop notifications")
    @app_commands.describe(games="Comma-separated list of game names to filter, or leave empty to clear")
    @app_commands.autocomplete(games=_game_autocomplete)
    async def drops_filter(self, interaction: discord.Interaction, games: str = ""):
        guild_id = str(interaction.guild_id)
        if games.strip():
            game_dict = {g.strip(): True for g in games.split(",") if g.strip()}
        else:
            game_dict = {}
        await db.upsert_twitch_drops_config(guild_id, game_filter=json.dumps(game_dict))
        await self.refresh_cache()
        if game_dict:
            await interaction.response.send_message(
                f"Game filter set: **{', '.join(game_dict.keys())}**", ephemeral=True
            )
        else:
            await interaction.response.send_message("Game filter cleared — all games.", ephemeral=True)

    @drops_group.command(name="config", description="Show current Twitch Drops configuration for this server")
    async def drops_config(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        cfg = await db.get_twitch_drops_config(guild_id)
        if not cfg:
            await interaction.response.send_message("No Twitch Drops configuration found. Use `/twitchdrops setup` to get started.", ephemeral=True)
            return

        embed = discord.Embed(title="Twitch Drops Configuration", color=TWITCH_DROP_COLOR)
        channel = interaction.guild.get_channel(int(cfg["channel_id"])) if cfg.get("channel_id") else None
        embed.add_field(name="Channel", value=channel.mention if channel else "Not set", inline=True)
        embed.add_field(name="Enabled", value="Yes" if cfg.get("enabled") else "No", inline=True)

        mention_role_id = cfg.get("mention_role_id")
        if mention_role_id:
            role = interaction.guild.get_role(int(mention_role_id))
            embed.add_field(name="Mention Role", value=role.mention if role else f"<@&{mention_role_id}>", inline=True)

        raw_filter = json.loads(cfg.get("game_filter", "{}"))
        if isinstance(raw_filter, list):
            enabled_games = raw_filter
        elif isinstance(raw_filter, dict):
            enabled_games = [g for g, on in raw_filter.items() if on]
        else:
            enabled_games = []

        if enabled_games:
            game_statuses = {g["game_name"].lower(): g for g in await db.get_all_cached_game_statuses()}
            lines = []
            for game_name in enabled_games:
                status = game_statuses.get(game_name.lower())
                if status and status["is_active"]:
                    indicator = "🟢 Active"
                elif status:
                    end = (status.get("end_date") or "")[:10]
                    indicator = f"🔴 Ended {end}" if end else "🔴 Inactive"
                else:
                    indicator = "❓ Unknown"
                lines.append(f"• {game_name}: {indicator}")
            embed.add_field(name="Game Filter", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Game Filter", value="All games (no filter)", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @drops_group.command(name="history", description="Show all cached Twitch Drops (including past)")
    async def drops_history(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        drops = await db.get_cached_drops(limit=50)
        if not drops:
            await interaction.followup.send("No cached Twitch Drops found.")
            return

        embed = discord.Embed(title="Twitch Drops History", color=TWITCH_DROP_COLOR)
        for drop in drops[:25]:
            discovered = drop.get("discovered_at", "")[:10] if drop.get("discovered_at") else "?"
            end_date = drop.get("end_date")
            if end_date:
                status = "Ended" if end_date < datetime.now(timezone.utc).isoformat() else "Active"
            else:
                status = "Active"
            embed.add_field(
                name=f"{drop['game_name']}: {drop['drop_name'][:40]}",
                value=f"Discovered: {discovered} | Status: {status}",
                inline=False,
            )
        embed.set_footer(text=f"Showing {min(len(drops), 25)} of {len(drops)} cached drops")
        await interaction.followup.send(embed=embed)

    @drops_group.command(name="clearcache", description="Clear the Twitch Drops cache to allow re-announcements")
    async def drops_clearcache(self, interaction: discord.Interaction):
        view = ClearCacheView()
        await interaction.response.send_message(
            "Are you sure you want to clear the entire Twitch Drops cache? "
            "This will allow all drops to be re-announced on the next check.",
            view=view,
            ephemeral=True,
        )

    @drops_group.command(name="check", description="Check for active Twitch Drops campaigns now")
    async def drops_check(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        active = await db.get_active_drops()

        if active:
            embed = discord.Embed(title="Active Twitch Drops", color=TWITCH_DROP_COLOR)
            for drop in active[:15]:
                dates = ""
                if drop.get("start_date") and drop.get("end_date"):
                    dates = f"{drop['start_date'][:10]} — {drop['end_date'][:10]}"
                value = f"{drop.get('description', '')[:80]}"
                if dates:
                    value += f"\n{dates}"
                if drop.get("details_url"):
                    value += f"\n[Details]({drop['details_url']})"
                embed.add_field(
                    name=f"{drop['game_name']}: {drop['drop_name'][:40]}",
                    value=value or "No details",
                    inline=False,
                )
            await interaction.followup.send(
                f"Found **{len(active)}** active drop campaign(s).", embed=embed
            )
        else:
            await interaction.followup.send("No active Twitch Drops campaigns found.")

    # --- Background loop ---

    @tasks.loop(minutes=30)
    async def check_loop(self):
        if self.bot.is_closed():
            return
        try:
            await self._fetch_drops()
        except Exception:
            log.exception("Error in Twitch Drops check loop")

    @check_loop.before_loop
    async def before_check_loop(self):
        await self.bot.wait_until_ready()

    async def _fetch_drops(self) -> list[dict]:
        """Discover games with active Twitch Drops by scanning live streams
        for the 'DropsEnabled' tag via the Helix API."""
        token = await self._get_access_token()
        if not token:
            log.warning("No Twitch access token available, skipping drops check")
            return []

        headers = {
            "Client-ID": self._client_id,
            "Authorization": f"Bearer {token}",
        }

        # Paginate through top live streams and collect games with drops
        games_with_drops: dict[str, dict] = {}  # game_id -> {game_name, image_url}
        cursor = None
        pages = 0
        max_pages = 15  # 1500 streams max

        try:
            while pages < max_pages:
                params = {"first": "100", "type": "live"}
                if cursor:
                    params["after"] = cursor

                async with self._session.get(
                    "https://api.twitch.tv/helix/streams",
                    headers=headers,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 401:
                        self._access_token = None
                        self._token_expiry = 0.0
                        return []
                    if resp.status != 200:
                        log.warning("Twitch Helix streams API returned %s", resp.status)
                        break
                    data = await resp.json()

                streams = data.get("data", [])
                if not streams:
                    break

                for stream in streams:
                    tags = stream.get("tags") or []
                    if "DropsEnabled" in tags:
                        gid = stream.get("game_id", "")
                        if gid and gid not in games_with_drops:
                            box_art = stream.get("thumbnail_url", "")
                            games_with_drops[gid] = {
                                "game_name": stream.get("game_name", "Unknown"),
                                "game_id": gid,
                            }

                cursor = data.get("pagination", {}).get("cursor")
                if not cursor:
                    break
                pages += 1

        except Exception:
            log.exception("Error scanning streams for Twitch Drops")

        if not games_with_drops:
            log.info("No games with active drops found in live streams")
            return []

        # Fetch box art for discovered games
        try:
            game_ids = list(games_with_drops.keys())
            # Helix allows up to 100 game IDs per request
            params = [("id", gid) for gid in game_ids[:100]]
            async with self._session.get(
                "https://api.twitch.tv/helix/games",
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    game_data = await resp.json()
                    for g in game_data.get("data", []):
                        gid = g.get("id", "")
                        if gid in games_with_drops:
                            box_art = g.get("box_art_url", "")
                            if box_art:
                                box_art = box_art.replace("{width}", "144").replace("{height}", "192")
                            games_with_drops[gid]["image_url"] = box_art
        except Exception:
            log.debug("Could not fetch game box art", exc_info=True)

        # Create drop entries for each game
        new_drops = []
        now_iso = datetime.now(timezone.utc).isoformat()
        for game in games_with_drops.values():
            drop_id = f"drops-{game['game_id']}"
            game_name = game["game_name"]
            image_url = game.get("image_url", "")
            details_url = f"https://www.twitch.tv/drops/campaigns"

            inserted_id = await db.add_twitch_drop(
                drop_id=drop_id,
                game_name=game_name,
                game_id=game["game_id"],
                drop_name=f"{game_name} Drops",
                description=f"Active Twitch Drops available for {game_name}",
                start_date=now_iso,
                end_date=None,
                image_url=image_url,
                details_url=details_url,
            )
            if inserted_id:
                new_drops.append({
                    "drop_id": drop_id,
                    "game_name": game_name,
                    "game_id": game["game_id"],
                    "drop_name": f"{game_name} Drops",
                    "description": f"Active Twitch Drops available for {game_name}",
                    "start_date": now_iso,
                    "end_date": "",
                    "image_url": image_url,
                    "details_url": details_url,
                })

        log.info("Found %d games with active Twitch Drops (%d new)", len(games_with_drops), len(new_drops))

        if new_drops:
            await self._notify_guilds(new_drops)

        return new_drops

    async def _send_with_ratelimit(self, channel, embed, content=None):
        async with self._send_semaphore:
            try:
                await channel.send(content=content, embed=embed)
            except discord.HTTPException as e:
                if e.status == 429:
                    retry_after = getattr(e, "retry_after", 5)
                    await asyncio.sleep(retry_after)
                    try:
                        await channel.send(content=content, embed=embed)
                    except discord.HTTPException:
                        log.warning("Failed to send drop notification after retry to %s", channel.id)
                else:
                    log.warning("Failed to send drop notification to %s: %s", channel.id, e)

    async def _notify_guilds(self, drops: list[dict]):
        configs = await db.get_all_twitch_drops_configs()
        send_tasks = []
        for cfg in configs:
            guild = self.bot.get_guild(int(cfg["guild_id"]))
            if not guild:
                continue
            channel = guild.get_channel(int(cfg["channel_id"])) if cfg.get("channel_id") else None
            if not channel:
                continue

            raw_filter = json.loads(cfg.get("game_filter", "{}"))
            if isinstance(raw_filter, list):
                # Backward compat: treat list items as enabled
                enabled_games = [g.lower() for g in raw_filter]
            elif isinstance(raw_filter, dict):
                enabled_games = [g.lower() for g, on in raw_filter.items() if on]
            else:
                enabled_games = []

            mention_role_id = cfg.get("mention_role_id")
            content = f"<@&{mention_role_id}>" if mention_role_id else None

            for drop in drops:
                # Apply game filter (case-insensitive match)
                if enabled_games:
                    if drop["game_name"].lower() not in enabled_games:
                        continue

                embed = build_drop_embed(
                    drop,
                    embed_color=cfg.get("embed_color") or None,
                    show_game=bool(cfg.get("embed_show_game", 1)),
                    show_period=bool(cfg.get("embed_show_period", 1)),
                    show_description=bool(cfg.get("embed_show_description", 1)),
                    show_image=bool(cfg.get("embed_show_image", 1)),
                    show_link=bool(cfg.get("embed_show_link", 1)),
                )

                send_tasks.append(self._send_with_ratelimit(channel, embed, content=content))

        if send_tasks:
            await asyncio.gather(*send_tasks, return_exceptions=True)


class ClearCacheView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Confirm Clear", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        deleted = await db.clear_twitch_drops_cache()
        self.stop()
        await interaction.response.edit_message(
            content=f"Cleared **{deleted}** cached drop(s). New drops will be announced on the next check.",
            view=None,
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="Cache clear cancelled.", view=None)


async def setup(bot: commands.Bot):
    await bot.add_cog(TwitchDrops(bot))
