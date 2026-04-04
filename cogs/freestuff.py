from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from dashboard import db

log = logging.getLogger(__name__)

_log_level = os.environ.get("FREESTUFF_LOG_LEVEL", "").upper()
if _log_level:
    log.setLevel(getattr(logging, _log_level, logging.INFO))

GAMERPOWER_API_URL = "https://www.gamerpower.com/api/giveaways"
EPIC_API = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
FREESTUFFGG_PUBKEY = os.getenv("FREESTUFFGG_PUBKEY", "")

_TITLE_NOISE_RE = re.compile(
    r"^\((?:game|dlc|loot|beta|early access)\)\s*"
    r"|\s*\((?:epic\s*games?|steam|gog|itch\.?io|xbox|playstation|ubisoft|humble)[^)]*\)"
    r"\s*(?:key\s+)?giveaway\s*$",
    re.IGNORECASE,
)


def _clean_title_noise(title: str) -> str:
    """Strip common GamerPower prefixes like '(Game)', '(DLC)', etc."""
    return _TITLE_NOISE_RE.sub("", title).strip() or title


def _normalize_title(title: str) -> str:
    """Lowercase, strip accents, remove non-alphanumeric for cross-source dedup."""
    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", t.lower())


_GAMERPOWER_PLATFORM_MAP: dict[str, str] = {
    "epic games store": "epic",
    "steam":            "steam",
    "gog":              "gog",
    "humble bundle":    "humble",
    "ubisoft":          "ubisoft",
    "origin":           "origin",
    "ea app":           "origin",
    "itch.io":          "itchio",
    "xbox one":         "xbox",
    "xbox 360":         "xbox",
    "xbox series x|s":  "xbox",
    "playstation 4":    "playstation",
    "playstation 5":    "playstation",
    "ps4":              "playstation",
    "ps5":              "playstation",
    "nintendo switch":  "nintendo",
}

_FREESTUFFGG_PLATFORM_MAP: dict[str, str] = {
    "steam":       "steam",
    "epic":        "epic",
    "epic games":  "epic",
    "gog":         "gog",
    "humble":      "humble",
    "humble bundle": "humble",
    "ubisoft":     "ubisoft",
    "itch":        "itchio",
    "itch.io":     "itchio",
    "xbox":        "xbox",
    "microsoft":   "xbox",
    "playstation": "playstation",
    "psn":         "playstation",
    "nintendo":    "nintendo",
    "switch":      "nintendo",
}

PLATFORM_COLORS = {
    "epic":    0x2D2D2D,
    "steam":   0x1B2838,
    "gog":     0x7C3AED,
    "ubisoft": 0x0070F3,
    "origin":  0xF26000,
    "humble":  0xCC3D0D,
    "itchio":  0xFA5C5C,
    "xbox":    0x107C10,
    "playstation": 0x003087,
    "nintendo": 0xE60012,
    "other":   0x5865F2,
}

CATEGORY_LABELS = {
    "free_to_keep":      "🎁 Free to Keep",
    "free_weekend":      "⏳ Free Weekend",
    "dlc":               "📦 DLC",
    "loot":              "🎁 In-Game Loot",
    "other_freebies":    "🎮 Freebie",
    "gamedev_assets":    "🛠️ Game Dev Asset",
    "giveaways_rewards": "🎟️ Giveaway / Reward",
}

CATEGORY_KEYWORDS = {
    "free_weekend":      ["free weekend", "free to play weekend", "[weekend]", "play for free this weekend"],
    "gamedev_assets":    ["asset", "game dev", "unity", "unreal", "blender", "template", "plugin", "tool for dev"],
    "giveaways_rewards": ["giveaway", "key giveaway", "redeem", "reward code", "prime gaming", "humble choice",
                          "emblem code", "bonus code", "key", "steam key", "activation code",
                          "gift code", "claim your key", "copy is free"],
    "dlc":               ["dlc", "expansion", "content pack", "add-on", "addon", "bonus content"],
    "loot":              ["in-game", "loot", "cosmetic", "skin", "emblem", "gift pack", "pack key",
                          "item key", "unlock key"],
    "other_freebies":    [],
}

ALL_CATEGORIES = ["free_to_keep", "free_weekend", "dlc", "loot", "other_freebies", "gamedev_assets", "giveaways_rewards"]

ALL_PLATFORMS = ["steam", "epic", "gog", "ubisoft", "origin", "humble", "itchio", "xbox", "playstation", "nintendo", "other"]

PLATFORM_LABELS = {
    "steam": "Steam",
    "epic": "Epic Games",
    "gog": "GOG",
    "ubisoft": "Ubisoft",
    "origin": "Origin / EA",
    "humble": "Humble Bundle",
    "itchio": "itch.io",
    "xbox": "Xbox",
    "playstation": "PlayStation",
    "nintendo": "Nintendo",
    "other": "Other",
}

PLATFORM_ICONS = {
    "steam":       "https://img.icons8.com/color/256/steam.png",
    "epic":        "https://img.icons8.com/color/256/epic-games.png",
    "gog":         "https://img.icons8.com/fluency/256/gog-galaxy.png",
    "ubisoft":     "https://img.icons8.com/color/256/ubisoft.png",
    "origin":      "https://img.icons8.com/color/256/origin.png",
    "humble":      "https://img.icons8.com/color/256/controller.png",
    "itchio":      "https://img.icons8.com/color/256/controller.png",
    "xbox":        "https://img.icons8.com/color/256/xbox.png",
    "playstation": "https://img.icons8.com/color/256/play-station.png",
    "nintendo":    "https://img.icons8.com/color/256/nintendo-switch.png",
    "other":       "https://img.icons8.com/color/256/controller.png",
}

_GP_TYPE_TO_CATEGORY: dict[str, str] = {
    "game":          "free_to_keep",
    "loot":          "loot",
    "beta":          "giveaways_rewards",
    "early access":  "giveaways_rewards",
    "dlc":           "dlc",
}


def classify_item(title: str, flair: str | None, platform: str, is_free_weekend: bool, *, gp_type: str | None = None, description: str | None = None) -> str:
    if is_free_weekend:
        return "free_weekend"
    if gp_type:
        mapped = _GP_TYPE_TO_CATEGORY.get(gp_type.lower())
        if mapped:
            return mapped
    text = (title + " " + (flair or "") + " " + (description or "")).lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return category
    return "free_to_keep"


_PLATFORM_DOMAIN_MAP: list[tuple[str, str]] = [
    ("steampowered.com", "steam"),
    ("epicgames.com", "epic"),
    ("gog.com", "gog"),
    ("ubisoft.com", "ubisoft"),
    ("ubi.com", "ubisoft"),
    ("ea.com", "origin"),
    ("origin.com", "origin"),
    ("humblebundle.com", "humble"),
    ("itch.io", "itchio"),
    ("xbox.com", "xbox"),
    ("microsoft.com/store", "xbox"),
    ("playstation.com", "playstation"),
    ("nintendo.com", "nintendo"),
]

_OFFICIAL_PLATFORMS: set[str] = {
    "steam", "epic", "gog", "ubisoft", "origin", "humble", "itchio", "xbox", "playstation", "nintendo"
}


async def _steam_search_url(session: aiohttp.ClientSession, title: str) -> str | None:
    """Search Steam store by title and return store.steampowered.com/app/{id}/ URL."""
    try:
        params = {"term": title, "cc": "US", "l": "en"}
        async with session.get(
            "https://store.steampowered.com/api/storesearch/",
            params=params,
            timeout=aiohttp.ClientTimeout(total=10),
            headers={"User-Agent": "DiscordBot/1.0"},
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            items = data.get("items") or []
            if not items:
                return None
            appid = items[0].get("id")
            if not appid:
                return None
            log.debug("GamerPower Steam search: %r → app/%s", title, appid)
            return f"https://store.steampowered.com/app/{appid}/"
    except Exception as exc:
        log.debug("GamerPower Steam search failed for %r: %s", title, exc)
        return None


async def _resolve_gamerpower_store_url(
    session: aiohttp.ClientSession, title: str, platform: str, fallback_url: str
) -> str:
    """Derive a direct store URL for a GamerPower game from its title and platform."""
    clean = _clean_title_noise(title)
    if platform == "steam":
        return await _steam_search_url(session, clean) or fallback_url
    return fallback_url


def _parse_price_cents(price_str: str) -> int | None:
    """Parse '$19.99' or '19.99 USD' → 1999 cents. Returns None if unparseable."""
    m = re.search(r"[\d.]+", (price_str or "").replace(",", ""))
    return int(float(m.group()) * 100) if m else None


def _detect_platform_from_url(url: str) -> str | None:
    """Detect platform from URL domain. Returns None if no match."""
    lower = url.lower()
    for domain, plat in _PLATFORM_DOMAIN_MAP:
        if domain in lower:
            return plat
    return None


def build_game_embed(
    title: str, url: str, platform: str, image_url: str,
    original_price: str, end_date: str, category: str,
    *,
    embed_color: str | None = None,
    show_price: bool = True,
    show_category: bool = True,
    show_platform: bool = True,
    show_expiry: bool = True,
    show_image: bool = True,
    description: str = "",
    show_description: bool = True,
    show_client_link: bool = True,
    store_url: str = "",
    clean_titles: bool = False,
    source: str = "",
) -> discord.Embed:
    if clean_titles:
        title = _clean_title_noise(title)
    color = int(embed_color.lstrip("#"), 16) if embed_color else PLATFORM_COLORS.get(platform, 0x5865F2)
    embed = discord.Embed(title=title, url=url, color=color)

    icon = PLATFORM_ICONS.get(platform)
    if icon:
        embed.set_author(name=PLATFORM_LABELS.get(platform, platform.title()))
        embed.set_thumbnail(url=icon)

    if original_price and original_price.upper() in ("N/A", "FREE", "UNKNOWN"):
        original_price = ""

    desc_lines = []
    if show_description and description:
        truncated = description[:200] + ("…" if len(description) > 200 else "")
        desc_lines.append(truncated)
        desc_lines.append("")
    if show_price:
        price_str = f"~~{original_price}~~ -> **FREE**" if original_price else "**FREE**"
        desc_lines.append(price_str)
    if show_expiry and end_date:
        try:
            dt = datetime.fromisoformat(end_date)
            unix = int(dt.replace(tzinfo=timezone.utc).timestamp())
            desc_lines.append(f"🕐 Free until: <t:{unix}:D>")
        except ValueError:
            desc_lines.append(f"🕐 Free until: {end_date}")
    if desc_lines:
        embed.description = "\n".join(desc_lines)

    if show_category:
        embed.add_field(name="Category", value=CATEGORY_LABELS.get(category, category), inline=True)
    if show_platform:
        embed.add_field(name="Platform", value=PLATFORM_LABELS.get(platform, platform.title()), inline=True)

    if url:
        embed.add_field(name="Links", value=f"[🌐 Open in Browser]({url})", inline=False)

    if show_image and image_url:
        embed.set_image(url=image_url)
    source_label = SOURCE_LABELS.get(source, "")
    footer_parts = [PLATFORM_LABELS.get(platform, platform.title())]
    if source_label:
        footer_parts.append(f"via {source_label}")
    footer_parts.append("Free Games Bot")
    embed.set_footer(text=" • ".join(footer_parts))
    return embed


SOURCE_LABELS = {
    "epic":        "Epic Games API",
    "freestuffgg": "FreeStuff.gg",
    "gamerpower":  "GamerPower",
}

PLATFORM_EMOJIS = {
    "steam": "\U0001f3ae",
    "epic": "\U0001f3f0",
    "gog": "\U0001f4bf",
    "ubisoft": "\U0001f5a5",
    "origin": "\U0001f3c3",
    "humble": "\U00002764",
    "itchio": "\U0001f3b2",
    "xbox": "\U0001f7e2",
    "playstation": "\U0001f535",
    "nintendo": "\U0001f534",
    "other": "\U0001f4e6",
}


class PlatformSelect(discord.ui.Select):
    def __init__(self, current_platforms: list[str], guild_id: str):
        self.guild_id = guild_id
        options = []
        for p in ALL_PLATFORMS:
            options.append(discord.SelectOption(
                label=PLATFORM_LABELS[p],
                value=p,
                emoji=PLATFORM_EMOJIS[p],
                default=p in current_platforms,
            ))
        super().__init__(
            placeholder="Select platforms to track...",
            min_values=1,
            max_values=len(ALL_PLATFORMS),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        selected = self.values
        await db.upsert_freestuff_config(self.guild_id, platforms=json.dumps(selected))

        cog = interaction.client.get_cog("FreeStuff")
        if cog:
            await cog.refresh_cache()

        labels = ", ".join(PLATFORM_LABELS.get(p, p) for p in selected)
        await interaction.response.edit_message(
            content=f"Platforms updated: **{labels}**",
            view=None,
        )


class PlatformConfigView(discord.ui.View):
    def __init__(self, current_platforms: list[str], guild_id: str):
        super().__init__(timeout=120)
        self.add_item(PlatformSelect(current_platforms, guild_id))


class _ResetConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)
        self.confirmed = False

    @discord.ui.button(label="Yes, reset", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.stop()


class FreeStuff(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cache: dict[str, dict] = {}
        self._session: aiohttp.ClientSession | None = None

    async def cog_load(self):
        await self.refresh_cache()
        self._session = aiohttp.ClientSession()
        self._gamerpower_task.start()
        self._epic_task.start()
        self._cleanup_seen_task.start()

    async def cog_unload(self):
        self._gamerpower_task.cancel()
        self._epic_task.cancel()
        self._cleanup_seen_task.cancel()
        if self._session:
            await self._session.close()

    async def refresh_cache(self):
        self._cache = await db.get_all_freestuff_configs_dict()

    # --- Slash commands ---

    freestuff_group = app_commands.Group(
        name="freestuff",
        description="Free game notifications",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @freestuff_group.command(name="setup", description="Set up free game notifications in a channel")
    @app_commands.describe(channel="Channel to send free game alerts to", role="Role to mention with announcements (optional)")
    async def freestuff_setup(self, interaction: discord.Interaction, channel: discord.TextChannel, role: discord.Role = None):
        guild_id = str(interaction.guild_id)
        kwargs = {"channel_id": str(channel.id), "enabled": 1}
        if role:
            kwargs["mention_role_id"] = str(role.id)
        await db.upsert_freestuff_config(guild_id, **kwargs)
        await self.refresh_cache()
        msg = f"Free game notifications enabled in {channel.mention}!"
        if role:
            msg += f" Mentioning {role.mention} with each alert."
        await interaction.response.send_message(msg, ephemeral=True)

    @freestuff_group.command(name="disable", description="Disable free game notifications")
    async def freestuff_disable(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        await db.upsert_freestuff_config(guild_id, enabled=0)
        await self.refresh_cache()
        await interaction.response.send_message("Free game notifications disabled.", ephemeral=True)

    @freestuff_group.command(name="config", description="Configure free game notification platforms")
    async def freestuff_config(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        cfg = await db.get_freestuff_config(guild_id)
        if not cfg:
            await interaction.response.send_message(
                "Free game notifications are not set up. Use `/freestuff setup <channel>` first.",
                ephemeral=True,
            )
            return

        channel = interaction.guild.get_channel(int(cfg["channel_id"])) if cfg.get("channel_id") else None
        platforms = json.loads(cfg.get("platforms", "[]"))
        enabled = bool(cfg.get("enabled"))
        freestuffgg_on = bool(cfg.get("freestuffgg_enabled", 1))
        gamerpower_on = bool(cfg.get("use_gamerpower", 1))
        epic_on = bool(cfg.get("use_epic_api", 1))
        webhook_configured = bool(FREESTUFFGG_PUBKEY)

        embed = discord.Embed(title="Free Stuff Config", color=0x43B581)
        embed.add_field(name="Enabled", value="Yes" if enabled else "No", inline=True)
        embed.add_field(name="Channel", value=channel.mention if channel else "Not set", inline=True)
        embed.add_field(
            name="FreeStuff.gg",
            value=("\u2705 On" if freestuffgg_on else "\u274c Off") +
                  (" (webhook configured)" if webhook_configured else " ⚠️ webhook secret not set"),
            inline=True,
        )
        embed.add_field(name="GamerPower", value="\u2705 On" if gamerpower_on else "\u274c Off", inline=True)
        embed.add_field(name="Epic Games API", value="\u2705 On" if epic_on else "\u274c Off", inline=True)

        platform_lines = []
        for p in ALL_PLATFORMS:
            emoji = PLATFORM_EMOJIS.get(p, "")
            label = PLATFORM_LABELS.get(p, p)
            indicator = "\u2705" if p in platforms else "\u274c"
            platform_lines.append(f"{emoji} {label}: {indicator}")
        embed.add_field(name="Platforms", value="\n".join(platform_lines), inline=False)

        platform_roles = json.loads(cfg.get("platform_mention_roles") or "{}")
        if platform_roles:
            role_lines = []
            for p, rid in platform_roles.items():
                role_lines.append(f"{PLATFORM_EMOJIS.get(p, '')} {PLATFORM_LABELS.get(p, p)}: <@&{rid}>")
            embed.add_field(name="Platform Mention Roles", value="\n".join(role_lines), inline=False)

        embed.set_footer(text="Use the dropdown below to change tracked platforms")

        view = PlatformConfigView(platforms, guild_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @freestuff_group.command(name="setrole", description="Set a role to mention for a specific platform")
    @app_commands.describe(platform="Game platform", role="Role to mention")
    @app_commands.choices(platform=[app_commands.Choice(name=PLATFORM_LABELS[p], value=p) for p in ALL_PLATFORMS])
    async def freestuff_setrole(self, interaction: discord.Interaction, platform: str, role: discord.Role):
        guild_id = str(interaction.guild_id)
        cfg = await db.get_freestuff_config(guild_id)
        if not cfg:
            await interaction.response.send_message(
                "Free game notifications are not set up. Use `/freestuff setup <channel>` first.",
                ephemeral=True,
            )
            return
        roles = json.loads(cfg.get("platform_mention_roles") or "{}")
        roles[platform] = str(role.id)
        await db.upsert_freestuff_config(guild_id, platform_mention_roles=json.dumps(roles))
        await self.refresh_cache()
        await interaction.response.send_message(
            f"{role.mention} will now be mentioned for **{PLATFORM_LABELS[platform]}** games.",
            ephemeral=True,
        )

    @freestuff_group.command(name="clearrole", description="Remove a per-platform mention role")
    @app_commands.describe(platform="Game platform")
    @app_commands.choices(platform=[app_commands.Choice(name=PLATFORM_LABELS[p], value=p) for p in ALL_PLATFORMS])
    async def freestuff_clearrole(self, interaction: discord.Interaction, platform: str):
        guild_id = str(interaction.guild_id)
        cfg = await db.get_freestuff_config(guild_id)
        roles = json.loads((cfg or {}).get("platform_mention_roles") or "{}")
        roles.pop(platform, None)
        await db.upsert_freestuff_config(guild_id, platform_mention_roles=json.dumps(roles))
        await self.refresh_cache()
        await interaction.response.send_message(
            f"Removed mention role for **{PLATFORM_LABELS[platform]}**.",
            ephemeral=True,
        )

    @freestuff_group.command(name="reset", description="Re-announce all current freebies to this server")
    async def freestuff_reset(self, interaction: discord.Interaction):
        view = _ResetConfirmView()
        await interaction.response.send_message(
            "⚠️ This will re-announce every current freebie to this server. Continue?",
            view=view,
            ephemeral=True,
        )
        await view.wait()
        if not view.confirmed:
            await interaction.edit_original_response(content="Cancelled.", view=None)
            return
        guild_id = str(interaction.guild_id)
        await db.upsert_freestuff_config(guild_id, pending_reset=1)
        await interaction.edit_original_response(
            content="Re-announcing all current freebies...", view=None
        )
        count = await self._handle_pending_resets()
        await interaction.edit_original_response(
            content=f"Re-announced **{count}** game(s) to this server."
        )

    @freestuff_group.command(name="check", description="Manually trigger a GamerPower and Epic Games check now")
    async def freestuff_check(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await asyncio.gather(self._poll_gamerpower(), self._poll_epic())
        recent = await db.get_free_games(limit=10)
        msg = "GamerPower + Epic check complete — new games (if any) have been announced.\n\n"
        if recent:
            embed = discord.Embed(title="Recent Free Games (GamerPower)", color=0x43B581)
            for game in recent[:10]:
                platform = game.get("platform", "?").title()
                price = game.get("original_price") or "Free"
                discovered = game.get("discovered_at", "")[:10]
                embed.add_field(
                    name=f"{game['title'][:50]}",
                    value=f"{platform} | Was {price} | Found {discovered}\n[Link]({game['url']})",
                    inline=False,
                )
            await interaction.followup.send(content=msg, embed=embed)
        else:
            await interaction.followup.send(msg + "No free games discovered yet.")

    # --- Background tasks ---

    @tasks.loop(minutes=30)
    async def _gamerpower_task(self):
        if self.bot.is_closed():
            return
        try:
            await self._poll_gamerpower()
        except Exception:
            log.exception("Error in GamerPower poll task")

    @_gamerpower_task.before_loop
    async def _before_gamerpower_task(self):
        await self.bot.wait_until_ready()

    @tasks.loop(hours=24)
    async def _cleanup_seen_task(self):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        deleted = await db.cleanup_expired_seen(cutoff)
        log.info("FreeStuff: cleaned up %d expired seen entries (cutoff=%s)", deleted, cutoff)

    @_cleanup_seen_task.before_loop
    async def _before_cleanup_seen_task(self):
        await self.bot.wait_until_ready()

    # --- Epic Games API polling ---

    @tasks.loop(hours=4)
    async def _epic_task(self):
        if self.bot.is_closed():
            return
        try:
            await self._poll_epic()
        except Exception:
            log.exception("Error in Epic Games poll task")

    @_epic_task.before_loop
    async def _before_epic_task(self):
        await self.bot.wait_until_ready()

    async def _poll_epic(self):
        """Fetch Epic free games and announce new ones to all guilds."""
        configs = await db.get_all_freestuff_configs()
        if not configs:
            return

        any_epic = any(cfg.get("use_epic_api", 1) for cfg in configs)
        if not any_epic:
            log.debug("Epic: skipped -- no guilds have use_epic_api enabled")
            return

        games = await self._fetch_epic()
        if not games:
            return

        now_iso = datetime.now(timezone.utc).isoformat()

        async def _send_game_to_guild(cfg: dict, game: dict):
            guild_id = cfg["guild_id"]
            if not cfg.get("use_epic_api", 1):
                log.debug("Epic: %r → guild %s — skipped (epic disabled)", game["title"], guild_id)
                return
            game_id = game["game_id"]
            if await db.is_game_seen(guild_id, "epic", game_id):
                log.debug("Epic: %r → guild %s — skipped (already announced, same source)", game["title"], guild_id)
                return
            norm = _normalize_title(game["title"])
            if await db.is_game_seen_by_title(guild_id, norm):
                log.debug("Epic: %r → guild %s — skipped (already announced by different source)", game["title"], guild_id)
                return

            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                log.debug("Epic: %r → guild %s — skipped (guild not found)", game["title"], guild_id)
                return
            channel = guild.get_channel(int(cfg["channel_id"])) if cfg.get("channel_id") else None
            if not channel:
                log.debug("Epic: %r → guild %s — skipped (channel not found)", game["title"], guild_id)
                return

            allowed_platforms = json.loads(cfg.get("platforms", "[]"))
            guild_filters = json.loads(cfg.get("content_filters") or
                '["free_to_keep","free_weekend","other_freebies","gamedev_assets","giveaways_rewards"]')

            if allowed_platforms and "epic" not in allowed_platforms:
                log.debug("Epic: %r → guild %s — skipped (platform 'epic' not in guild filter)", game["title"], guild_id)
                return
            if game.get("category", "free_to_keep") not in guild_filters:
                log.debug("Epic: %r → guild %s — skipped (category %r not in guild filter)", game["title"], guild_id, game.get("category"))
                return

            min_price = cfg.get("min_original_price_cents", 0) or 0
            if min_price > 0:
                price_cents = _parse_price_cents(game.get("original_price", ""))
                if price_cents is not None and price_cents < min_price:
                    log.debug("Epic: %r → guild %s — skipped (price %s < min %d cents)", game["title"], guild_id, game.get("original_price"), min_price)
                    return

            blocklist = json.loads(cfg.get("keyword_blocklist") or "[]")
            if any(kw.lower() in game["title"].lower() for kw in blocklist if kw.strip()):
                matched = next(kw for kw in blocklist if kw.strip() and kw.lower() in game["title"].lower())
                log.debug("Epic: %r → guild %s — skipped (keyword %r in title)", game["title"], guild_id, matched)
                return

            mention_parts = []
            if cfg.get("mention_role_id"):
                mention_parts.append(f"<@&{cfg['mention_role_id']}>")
            platform_roles = json.loads(cfg.get("platform_mention_roles") or "{}")
            if "epic" in platform_roles:
                mention_parts.append(f"<@&{platform_roles['epic']}>")
            content = " ".join(mention_parts) or None

            embed = build_game_embed(
                title=game["title"], url=game["url"], platform="epic",
                image_url=game.get("image_url", ""),
                original_price=game.get("original_price", ""),
                end_date=game.get("end_date", ""),
                category=game.get("category", "free_to_keep"),
                embed_color=cfg.get("embed_color") or None,
                show_price=bool(cfg.get("embed_show_price", 1)),
                show_category=bool(cfg.get("embed_show_category", 1)),
                show_platform=bool(cfg.get("embed_show_platform", 1)),
                show_expiry=bool(cfg.get("embed_show_expiry", 1)),
                show_image=bool(cfg.get("embed_show_image", 1)),
                description=game.get("description", ""),
                show_description=bool(cfg.get("embed_show_description", 1)),
                show_client_link=bool(cfg.get("embed_show_client_link", 1)),
                store_url=game.get("url", ""),
                clean_titles=bool(cfg.get("embed_clean_titles", 0)),
                source="epic",
            )
            embed.timestamp = datetime.now(timezone.utc)

            try:
                await channel.send(content=content, embed=embed)
                await db.mark_game_seen(guild_id, "epic", game_id, now_iso, game.get("end_date") or None, normalized_title=norm)
                log.info("Epic: %r → guild %s — announced (category=%s, url=%s)", game["title"], guild_id, game.get("category"), game.get("url"))
            except discord.HTTPException as e:
                log.warning("Epic: failed to send to guild %s: %s", guild_id, e)

        # Deduplicate by normalized title — Epic API can return multiple promotions
        # for the same underlying game (different slugs), which would both pass
        # is_game_seen and be announced in the same asyncio.gather batch.
        seen_norms: set[str] = set()
        unique_games = []
        for g in games:
            n = _normalize_title(g["title"])
            if n not in seen_norms:
                seen_norms.add(n)
                unique_games.append(g)
            else:
                log.debug("Epic: deduped %r (same normalized title)", g["title"])
        games = unique_games

        log.info("Epic: fetched %d game(s), sending to %d guild(s)", len(games), len(configs))
        send_tasks = [
            _send_game_to_guild(cfg, game)
            for cfg in configs
            for game in games
        ]
        await asyncio.gather(*send_tasks, return_exceptions=True)

    async def _fetch_epic(self) -> list[dict]:
        """Fetch current Epic Games Store free promotions. Returns list of game dicts."""
        games = []
        try:
            params = {"locale": "en-US", "country": "US", "allowCountries": "US"}
            headers = {"User-Agent": "DiscordBot/1.0"}
            async with self._session.get(EPIC_API, params=params, headers=headers,
                                         timeout=aiohttp.ClientTimeout(total=15)) as resp:
                log.debug("Epic API response status: %d", resp.status)
                if resp.status != 200:
                    return []
                data = await resp.json()

            elements = (
                data.get("data", {})
                    .get("Catalog", {})
                    .get("searchStore", {})
                    .get("elements", [])
            )
            log.debug("Epic: %d elements returned", len(elements))
            now = datetime.now(timezone.utc)

            for item in elements:
                promotions = item.get("promotions") or {}
                promo_offers = (
                    promotions.get("promotionalOffers") or []
                )
                # Only current promotions (not upcoming)
                active_offers = []
                for offer_group in promo_offers:
                    for offer in offer_group.get("promotionalOffers") or []:
                        discount = offer.get("discountSetting", {})
                        if discount.get("discountPercentage", 100) == 0:
                            # 0% discount = free
                            try:
                                start = datetime.fromisoformat(
                                    offer["startDate"].replace("Z", "+00:00")
                                )
                                end = datetime.fromisoformat(
                                    offer["endDate"].replace("Z", "+00:00")
                                )
                                if start <= now <= end:
                                    active_offers.append((start, end))
                            except Exception:
                                pass

                if not active_offers:
                    continue

                end_dt = max(e for _, e in active_offers)
                end_date_iso = end_dt.isoformat()

                title = (item.get("title") or "").strip()
                if not title:
                    continue

                # page_slug or productSlug as game_id
                slug = ""
                catalog_ns = item.get("catalogNs") or {}
                mappings = catalog_ns.get("mappings") or []
                if mappings:
                    slug = mappings[0].get("pageSlug") or ""
                if not slug:
                    slug = item.get("productSlug") or item.get("urlSlug") or ""
                if not slug:
                    import hashlib
                    slug = hashlib.md5(title.encode()).hexdigest()[:12]

                url = f"https://store.epicgames.com/p/{slug}" if slug else "https://store.epicgames.com/free-games"

                # Key image (OfferImageWide or Thumbnail)
                image_url = ""
                for key_img in item.get("keyImages") or []:
                    if key_img.get("type") in ("OfferImageWide", "DieselStoreFrontWide", "Thumbnail"):
                        image_url = key_img.get("url", "")
                        if image_url:
                            break

                # Original price
                price_info = item.get("price") or {}
                total_price = price_info.get("totalPrice") or {}
                original_price_cents = total_price.get("originalPrice", 0)
                currency = total_price.get("currencyCode", "USD")
                original_price = ""
                if original_price_cents and original_price_cents > 0:
                    original_price = f"${original_price_cents / 100:.2f}"

                description = (item.get("description") or "")[:300]
                category = classify_item(title, None, "epic", False)

                await db.add_free_game(
                    title=title, url=url, platform="epic",
                    image_url=image_url, original_price=original_price,
                    source="epic", category=category,
                    description=description,
                    expires_at=end_date_iso,
                )

                games.append({
                    "game_id":        slug,
                    "title":          title,
                    "url":            url,
                    "platform":       "epic",
                    "image_url":      image_url,
                    "original_price": original_price,
                    "end_date":       end_date_iso,
                    "category":       category,
                    "source":         "epic",
                    "description":    description,
                })

        except Exception:
            log.exception("Error fetching Epic free games")
        log.debug("Epic: fetch complete -- %d item(s)", len(games))
        return games

    # --- FreeStuff.gg webhook handler ---

    async def handle_freestuffgg_event(self, envelope: dict):
        """Called by the dashboard webhook route after Ed25519 verification.

        Envelope structure (Standard Webhooks):
          { "type": "fsb:event:announcement_created",
            "timestamp": "...",
            "data": { "id": ..., "resolvedProducts": [...] } }

        Each product in resolvedProducts:
          id, title, description, kind, type, store, until (unix ms),
          prices ([{oldValue, newValue, currency}]),
          images ([{url, priority}]), urls ([{url, priority, flags}])
        """
        event_type = envelope.get("type", "")
        if "announcement" not in event_type:
            log.debug("FreeStuff.gg: ignoring event type %r", event_type)
            return

        announcement = envelope.get("data", {})
        products = announcement.get("resolvedProducts") or []
        if not products:
            # Fallback: treat the data itself as a single product (future-proofing)
            products = [announcement]

        for product in products:
            await self._handle_freestuffgg_product(product)

    async def _handle_freestuffgg_product(self, data: dict):
        """Process one FreeStuff.gg product and announce to eligible guilds."""
        game_id = str(data.get("id", ""))
        title = data.get("title") or ""
        if not game_id or not title:
            log.warning("FreeStuff.gg: product missing id or title, skipping")
            return
        description = (data.get("description") or "")[:300]

        # Best URL: pick the highest-priority url (lowest priority number = better)
        urls_list = sorted(data.get("urls") or [], key=lambda u: u.get("priority", 999))
        url = urls_list[0]["url"] if urls_list else ""

        # Best image: highest-priority image
        images_list = sorted(data.get("images") or [], key=lambda i: i.get("priority", 999))
        thumbnail = images_list[0]["url"] if images_list else ""

        # Original price from prices array (oldValue is in smallest currency unit, e.g. cents)
        price_original = ""
        prices_list = data.get("prices") or []
        if prices_list:
            p = prices_list[0]
            old_val = p.get("oldValue", 0)
            currency = p.get("currency", "USD")
            if old_val and old_val > 0:
                price_original = f"{old_val / 100:.2f} {currency}"

        # until is unix timestamp in milliseconds
        expires_at_raw = data.get("until")
        platform_raw = (data.get("store") or "other").lower()

        # Map FreeStuff.gg store names to our platform keys
        platform = _FREESTUFFGG_PLATFORM_MAP.get(platform_raw, "other")
        if platform == "other" and url:
            url_platform = _detect_platform_from_url(url)
            if url_platform:
                platform = url_platform

        category = classify_item(title, None, platform, False)

        # Normalize expires_at to ISO string (until is ms since Unix epoch)
        expires_iso: str | None = None
        if expires_at_raw is not None:
            try:
                ts_s = expires_at_raw / 1000 if expires_at_raw > 1e10 else expires_at_raw
                expires_iso = datetime.fromtimestamp(ts_s, tz=timezone.utc).isoformat()
            except Exception:
                pass

        if price_original.upper() in ("N/A", "FREE", "UNKNOWN"):
            price_original = ""

        now_iso = datetime.now(timezone.utc).isoformat()

        # Insert into free_games history
        await db.add_free_game(
            title=title, url=url, platform=platform,
            image_url=thumbnail, original_price=price_original,
            source="freestuffgg", category=category,
            expires_at=expires_iso, description=description,
        )

        configs = await db.get_all_freestuff_configs()

        async def _send_to_guild(cfg: dict):
            guild_id = cfg["guild_id"]
            if not cfg.get("freestuffgg_enabled", 1):
                log.debug("FreeStuff.gg: %r → guild %s — skipped (freestuffgg disabled)", title, guild_id)
                return
            if await db.is_game_seen(guild_id, "freestuffgg", game_id):
                log.debug("FreeStuff.gg: %r → guild %s — skipped (already announced, same source)", title, guild_id)
                return
            norm = _normalize_title(title)
            if await db.is_game_seen_by_title(guild_id, norm):
                log.debug("FreeStuff.gg: %r → guild %s — skipped (already announced by different source)", title, guild_id)
                return

            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                log.debug("FreeStuff.gg: %r → guild %s — skipped (guild not found)", title, guild_id)
                return
            channel = guild.get_channel(int(cfg["channel_id"])) if cfg.get("channel_id") else None
            if not channel:
                log.debug("FreeStuff.gg: %r → guild %s — skipped (channel not found)", title, guild_id)
                return

            allowed_platforms = json.loads(cfg.get("platforms", "[]"))
            guild_filters = json.loads(cfg.get("content_filters") or
                '["free_to_keep","free_weekend","other_freebies","gamedev_assets","giveaways_rewards"]')

            if allowed_platforms and platform not in allowed_platforms:
                log.debug("FreeStuff.gg: %r → guild %s — skipped (platform %r not in guild filter)", title, guild_id, platform)
                return
            if category not in guild_filters:
                log.debug("FreeStuff.gg: %r → guild %s — skipped (category %r not in guild filter)", title, guild_id, category)
                return

            min_price = cfg.get("min_original_price_cents", 0) or 0
            if min_price > 0:
                price_cents = _parse_price_cents(price_original)
                if price_cents is not None and price_cents < min_price:
                    log.debug("FreeStuff.gg: %r → guild %s — skipped (price %s < min %d cents)", title, guild_id, price_original, min_price)
                    return

            blocklist = json.loads(cfg.get("keyword_blocklist") or "[]")
            if any(kw.lower() in title.lower() for kw in blocklist if kw.strip()):
                matched = next(kw for kw in blocklist if kw.strip() and kw.lower() in title.lower())
                log.debug("FreeStuff.gg: %r → guild %s — skipped (keyword %r in title)", title, guild_id, matched)
                return

            mention_parts = []
            if cfg.get("mention_role_id"):
                mention_parts.append(f"<@&{cfg['mention_role_id']}>")
            platform_roles = json.loads(cfg.get("platform_mention_roles") or "{}")
            if platform in platform_roles:
                mention_parts.append(f"<@&{platform_roles[platform]}>")
            content = " ".join(mention_parts) or None

            embed = build_game_embed(
                title=title, url=url, platform=platform,
                image_url=thumbnail,
                original_price=price_original,
                end_date=expires_iso or "",
                category=category,
                embed_color=cfg.get("embed_color") or None,
                show_price=bool(cfg.get("embed_show_price", 1)),
                show_category=bool(cfg.get("embed_show_category", 1)),
                show_platform=bool(cfg.get("embed_show_platform", 1)),
                show_expiry=bool(cfg.get("embed_show_expiry", 1)),
                show_image=bool(cfg.get("embed_show_image", 1)),
                description=description,
                show_description=bool(cfg.get("embed_show_description", 1)),
                show_client_link=bool(cfg.get("embed_show_client_link", 1)),
                store_url=url,
                clean_titles=bool(cfg.get("embed_clean_titles", 0)),
                source="freestuffgg",
            )
            embed.timestamp = datetime.now(timezone.utc)

            try:
                await channel.send(content=content, embed=embed)
                await db.mark_game_seen(guild_id, "freestuffgg", game_id, now_iso, expires_iso, normalized_title=norm)
                log.info("FreeStuff.gg: %r → guild %s — announced (platform=%s, category=%s, url=%s)", title, guild_id, platform, category, url)
            except discord.HTTPException as e:
                log.warning("FreeStuff.gg: failed to send to guild %s: %s", guild_id, e)

        log.info("FreeStuff.gg: processing event for %r (game_id=%s), sending to %d guild(s)", title, game_id, len(configs))
        await asyncio.gather(*[_send_to_guild(cfg) for cfg in configs], return_exceptions=True)

    # --- GamerPower polling ---

    async def _poll_gamerpower(self):
        """Fetch GamerPower and announce new games to all guilds concurrently."""
        configs = await db.get_all_freestuff_configs()
        if not configs:
            return

        any_gp = any(cfg.get("use_gamerpower", 1) for cfg in configs)
        if not any_gp:
            log.debug("GamerPower: skipped -- no guilds have use_gamerpower enabled")
            return

        games = await self._fetch_gamerpower()
        if not games:
            return

        now_iso = datetime.now(timezone.utc).isoformat()

        async def _send_game_to_guild(cfg: dict, game: dict):
            guild_id = cfg["guild_id"]
            if not cfg.get("use_gamerpower", 1):
                log.debug("GamerPower: %r → guild %s — skipped (gamerpower disabled)", game["title"], guild_id)
                return
            # Skip Epic games from GamerPower if Epic API is also enabled (avoids duplicates)
            if game["platform"] == "epic" and cfg.get("use_epic_api", 1):
                log.debug("GamerPower: %r → guild %s — skipped (Epic API handles this)", game["title"], guild_id)
                return
            game_id = game["game_id"]
            if await db.is_game_seen(guild_id, "gamerpower", game_id):
                log.debug("GamerPower: %r → guild %s — skipped (already announced, same source)", game["title"], guild_id)
                return
            norm = _normalize_title(game["title"])
            if await db.is_game_seen_by_title(guild_id, norm):
                log.debug("GamerPower: %r → guild %s — skipped (already announced by different source)", game["title"], guild_id)
                return

            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                log.debug("GamerPower: %r → guild %s — skipped (guild not found)", game["title"], guild_id)
                return
            channel = guild.get_channel(int(cfg["channel_id"])) if cfg.get("channel_id") else None
            if not channel:
                log.debug("GamerPower: %r → guild %s — skipped (channel not found)", game["title"], guild_id)
                return

            allowed_platforms = json.loads(cfg.get("platforms", "[]"))
            guild_filters = json.loads(cfg.get("content_filters") or
                '["free_to_keep","free_weekend","other_freebies","gamedev_assets","giveaways_rewards"]')

            if allowed_platforms and game["platform"] not in allowed_platforms:
                log.debug("GamerPower: %r → guild %s — skipped (platform %r not in guild filter)", game["title"], guild_id, game["platform"])
                return
            if game.get("category", "free_to_keep") not in guild_filters:
                log.debug("GamerPower: %r → guild %s — skipped (category %r not in guild filter)", game["title"], guild_id, game.get("category"))
                return

            min_price = cfg.get("min_original_price_cents", 0) or 0
            if min_price > 0:
                price_cents = _parse_price_cents(game.get("original_price", ""))
                if price_cents is not None and price_cents < min_price:
                    log.debug("GamerPower: %r → guild %s — skipped (price %s < min %d cents)", game["title"], guild_id, game.get("original_price"), min_price)
                    return

            blocklist = json.loads(cfg.get("keyword_blocklist") or "[]")
            if any(kw.lower() in game["title"].lower() for kw in blocklist if kw.strip()):
                matched = next(kw for kw in blocklist if kw.strip() and kw.lower() in game["title"].lower())
                log.debug("GamerPower: %r → guild %s — skipped (keyword %r in title)", game["title"], guild_id, matched)
                return

            if cfg.get("gamerpower_official_only", 0):
                if not (_detect_platform_from_url(game["url"]) or game.get("platform") in _OFFICIAL_PLATFORMS):
                    log.debug("GamerPower: %r → guild %s — skipped (not official store, url=%s platform=%s)", game["title"], guild_id, game["url"], game.get("platform"))
                    return

            mention_parts = []
            if cfg.get("mention_role_id"):
                mention_parts.append(f"<@&{cfg['mention_role_id']}>")
            platform_roles = json.loads(cfg.get("platform_mention_roles") or "{}")
            if game["platform"] in platform_roles:
                mention_parts.append(f"<@&{platform_roles[game['platform']]}>")
            content = " ".join(mention_parts) or None

            link_type = cfg.get("link_type", "store")
            game_url = game["url"]
            if link_type == "gamerpower" and game.get("source_url"):
                game_url = game["source_url"]

            embed = build_game_embed(
                title=game["title"], url=game_url, platform=game["platform"],
                image_url=game.get("image_url", ""),
                original_price=game.get("original_price", ""),
                end_date=game.get("end_date", ""),
                category=game.get("category", "free_to_keep"),
                embed_color=cfg.get("embed_color") or None,
                show_price=bool(cfg.get("embed_show_price", 1)),
                show_category=bool(cfg.get("embed_show_category", 1)),
                show_platform=bool(cfg.get("embed_show_platform", 1)),
                show_expiry=bool(cfg.get("embed_show_expiry", 1)),
                show_image=bool(cfg.get("embed_show_image", 1)),
                description=game.get("description", ""),
                show_description=bool(cfg.get("embed_show_description", 1)),
                show_client_link=bool(cfg.get("embed_show_client_link", 1)),
                store_url=game.get("url", ""),
                clean_titles=bool(cfg.get("embed_clean_titles", 0)),
                source="gamerpower",
            )
            embed.timestamp = datetime.now(timezone.utc)

            try:
                await channel.send(content=content, embed=embed)
                await db.mark_game_seen(guild_id, "gamerpower", game_id, now_iso, game.get("end_date") or None, normalized_title=norm)
                log.info("GamerPower: %r → guild %s — announced (platform=%s, category=%s, url=%s)", game["title"], guild_id, game["platform"], game.get("category"), game.get("url"))
            except discord.HTTPException as e:
                log.warning("GamerPower: failed to send to guild %s: %s", guild_id, e)

        # Deduplicate by normalized title within the fetched batch
        seen_norms: set[str] = set()
        unique_games = []
        for g in games:
            n = _normalize_title(g["title"])
            if n not in seen_norms:
                seen_norms.add(n)
                unique_games.append(g)
            else:
                log.debug("GamerPower: deduped %r (same normalized title)", g["title"])
        games = unique_games

        log.info("GamerPower: fetched %d game(s), sending to %d guild(s)", len(games), len(configs))
        send_tasks = [
            _send_game_to_guild(cfg, game)
            for cfg in configs
            for game in games
        ]
        await asyncio.gather(*send_tasks, return_exceptions=True)

    async def _fetch_gamerpower(self) -> list[dict]:
        """Fetch current GamerPower giveaways. Returns list of game dicts."""
        games = []
        try:
            headers = {"User-Agent": "DiscordBot/1.0"}
            async with self._session.get(GAMERPOWER_API_URL, headers=headers,
                                         timeout=aiohttp.ClientTimeout(total=15)) as resp:
                log.debug("GamerPower API response status: %d", resp.status)
                if resp.status != 200:
                    return []
                items = await resp.json()

            log.debug("GamerPower: %d items returned", len(items))
            for item in items:
                # Skip non-game types (articles, news posts, etc.)
                gp_type_raw = (item.get("type") or "").lower()
                _KNOWN_GP_TYPES = ("game", "loot", "beta", "early access", "dlc", "")
                if gp_type_raw not in _KNOWN_GP_TYPES:
                    log.debug("GamerPower: skipping %r -- unsupported type %r", item.get("title"), gp_type_raw)
                    continue

                title = _clean_title_noise((item.get("title") or "").strip())
                gp_url = item.get("open_giveaway_url") or ""  # redirect → store
                gp_page_url = item.get("giveaway_url") or gp_url  # GamerPower detail page
                game_id = str(item.get("id", ""))
                if not title or not gp_url or not game_id:
                    log.debug("GamerPower: skipping item -- missing title, URL, or id")
                    continue

                # Skip mobile-only (no PC/store platform)
                platforms_str = (item.get("platforms") or "").lower()
                pc_stores = ("pc", "steam", "epic", "gog", "humble", "ubisoft", "origin", "drm-free", "itch",
                             "xbox", "playstation", "ps4", "ps5", "nintendo", "switch")
                if not any(p in platforms_str for p in pc_stores):
                    log.debug("GamerPower: skipping %r -- mobile-only (platforms=%r)", title, platforms_str)
                    continue

                # Skip past end_date
                end_date_str = item.get("end_date") or ""
                end_date_display = ""
                gp_expires_iso: str | None = None
                if end_date_str and end_date_str != "N/A":
                    try:
                        end_dt = datetime.strptime(end_date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                        if end_dt < datetime.now(timezone.utc):
                            log.debug("GamerPower: skipping %r -- expired (%s)", title, end_date_str)
                            continue
                        end_date_display = end_date_str[:10]
                        gp_expires_iso = end_dt.isoformat()
                    except Exception:
                        pass

                # Detect platform from platforms field
                platform = "other"
                for key, val in _GAMERPOWER_PLATFORM_MAP.items():
                    if key in platforms_str:
                        platform = val
                        break

                image_url = item.get("image") or item.get("thumbnail") or ""
                original_price = item.get("worth") or ""
                if original_price.upper() in ("N/A", "FREE", "UNKNOWN"):
                    original_price = ""
                description = (item.get("description") or "")[:300]
                category = classify_item(title, platforms_str, platform, False, gp_type=item.get("type"), description=description)

                log.debug("GamerPower: %r -- gp_type=%s, platform=%s, category=%s", title, item.get("type"), platform, category)

                # Resolve to direct store URL (Steam search API / Epic slug construction)
                gp_url = await _resolve_gamerpower_store_url(self._session, title, platform, gp_url)

                # Insert into free_games history (for dashboard display / reset)
                await db.add_free_game(
                    title=title, url=gp_url, platform=platform,
                    image_url=image_url, original_price=original_price,
                    source="gamerpower", category=category,
                    source_url=gp_page_url, description=description,
                    gp_type=item.get("type"),
                    expires_at=gp_expires_iso,
                )

                games.append({
                    "game_id":       game_id,
                    "title":         title,
                    "url":           gp_url,
                    "platform":      platform,
                    "image_url":     image_url,
                    "original_price": original_price,
                    "end_date":      end_date_display,
                    "category":      category,
                    "source":        "gamerpower",
                    "source_url":    gp_page_url,
                    "description":   description,
                })

        except Exception:
            log.exception("Error fetching GamerPower giveaways")
        log.debug("GamerPower: fetch complete -- %d item(s)", len(games))
        return games

    # --- Pending resets (dashboard / slash command) ---

    async def _handle_pending_resets(self) -> int:
        """Re-announce all known GamerPower games to guilds with pending_reset=1. Returns count sent."""
        configs = await db.get_all_freestuff_configs()
        pending = [c for c in configs if c.get("pending_reset")]
        if not pending:
            return 0

        all_games = await db.get_free_games(limit=200)
        if not all_games:
            for cfg in pending:
                await db.upsert_freestuff_config(cfg["guild_id"], pending_reset=0)
            return 0

        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        FALLBACK_TTL_DAYS = 30
        games = []
        for g in all_games:
            expires = g.get("expires_at")
            if expires:
                if expires < now_iso:
                    log.debug("pending_reset: skipping %r — expired (%s)", g.get("title"), expires)
                    continue
            else:
                discovered = g.get("discovered_at", "")
                if discovered:
                    try:
                        disc_dt = datetime.fromisoformat(discovered.replace(" ", "T"))
                        if disc_dt.tzinfo is None:
                            disc_dt = disc_dt.replace(tzinfo=timezone.utc)
                        if now_dt - disc_dt > timedelta(days=FALLBACK_TTL_DAYS):
                            log.debug("pending_reset: skipping %r — no expiry, discovered %s (>%dd ago)",
                                      g.get("title"), discovered[:10], FALLBACK_TTL_DAYS)
                            continue
                    except Exception:
                        pass
            stored_gp_type = g.get("gp_type")
            category = classify_item(g["title"], None, g.get("platform", "other"), False, gp_type=stored_gp_type)
            games.append({
                "title": g["title"], "url": g["url"], "platform": g.get("platform", "other"),
                "image_url": g.get("image_url", ""), "original_price": g.get("original_price", ""),
                "end_date": (g.get("expires_at") or g.get("discovered_at") or "")[:10],
                "category": category,
                "source": g.get("source", ""), "source_url": g.get("source_url", ""),
                "description": g.get("description", ""),
            })

        count = 0
        for cfg in pending:
            guild = self.bot.get_guild(int(cfg["guild_id"]))
            if not guild:
                await db.upsert_freestuff_config(cfg["guild_id"], pending_reset=0)
                continue
            channel = guild.get_channel(int(cfg["channel_id"])) if cfg.get("channel_id") else None
            if not channel:
                await db.upsert_freestuff_config(cfg["guild_id"], pending_reset=0)
                continue

            allowed_platforms = json.loads(cfg.get("platforms", "[]"))
            guild_filters = json.loads(cfg.get("content_filters") or
                '["free_to_keep","free_weekend","other_freebies","gamedev_assets","giveaways_rewards"]')

            allowed_sources: set[str] = set()
            if cfg.get("use_epic_api", 1):        allowed_sources.add("epic")
            if cfg.get("use_gamerpower", 1):      allowed_sources.add("gamerpower")
            if cfg.get("freestuffgg_enabled", 1): allowed_sources.add("freestuffgg")

            seen_titles_this_reset: set[str] = set()
            for game in games:
                if allowed_platforms and game["platform"] not in allowed_platforms:
                    continue
                if game.get("category", "free_to_keep") not in guild_filters:
                    continue
                if game.get("source") not in allowed_sources:
                    continue

                min_price = cfg.get("min_original_price_cents", 0) or 0
                if min_price > 0:
                    price_cents = _parse_price_cents(game.get("original_price", ""))
                    if price_cents is not None and price_cents < min_price:
                        continue

                blocklist = json.loads(cfg.get("keyword_blocklist") or "[]")
                if any(kw.lower() in game["title"].lower() for kw in blocklist if kw.strip()):
                    continue

                if cfg.get("gamerpower_official_only", 0) and game.get("source") == "gamerpower":
                    if not (_detect_platform_from_url(game["url"]) or game.get("platform") in _OFFICIAL_PLATFORMS):
                        continue

                norm = _normalize_title(game["title"])
                if norm in seen_titles_this_reset:
                    log.debug("pending_reset: %r → guild %s — skipped (already announced by different source)", game["title"], cfg["guild_id"])
                    continue
                seen_titles_this_reset.add(norm)

                link_type = cfg.get("link_type", "store")
                game_url = game["url"]
                if link_type == "gamerpower" and game.get("source_url"):
                    game_url = game["source_url"]

                mention_parts = []
                if cfg.get("mention_role_id"):
                    mention_parts.append(f"<@&{cfg['mention_role_id']}>")
                platform_roles = json.loads(cfg.get("platform_mention_roles") or "{}")
                if game["platform"] in platform_roles:
                    mention_parts.append(f"<@&{platform_roles[game['platform']]}>")
                content = " ".join(mention_parts) or None

                embed = build_game_embed(
                    title=game["title"], url=game_url, platform=game["platform"],
                    image_url=game.get("image_url", ""),
                    original_price=game.get("original_price", ""),
                    end_date=game.get("end_date", ""),
                    category=game.get("category", "free_to_keep"),
                    embed_color=cfg.get("embed_color") or None,
                    show_price=bool(cfg.get("embed_show_price", 1)),
                    show_category=bool(cfg.get("embed_show_category", 1)),
                    show_platform=bool(cfg.get("embed_show_platform", 1)),
                    show_expiry=bool(cfg.get("embed_show_expiry", 1)),
                    show_image=bool(cfg.get("embed_show_image", 1)),
                    description=game.get("description", ""),
                    show_description=bool(cfg.get("embed_show_description", 1)),
                    show_client_link=bool(cfg.get("embed_show_client_link", 1)),
                    store_url=game.get("url", ""),
                    clean_titles=bool(cfg.get("embed_clean_titles", 0)),
                    source=game.get("source", ""),
                )
                embed.timestamp = datetime.now(timezone.utc)
                try:
                    await channel.send(content=content, embed=embed)
                    count += 1
                except discord.HTTPException as e:
                    log.warning("Failed to re-announce to %s: %s", channel.id, e)

            await db.upsert_freestuff_config(cfg["guild_id"], pending_reset=0)

        return count


async def setup(bot: commands.Bot):
    await bot.add_cog(FreeStuff(bot))
