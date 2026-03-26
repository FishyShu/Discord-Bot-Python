from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from dashboard import db

log = logging.getLogger(__name__)

EPIC_API            = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
GAMERPOWER_API_URL  = "https://www.gamerpower.com/api/giveaways"
GG_DEALS_PRICES_URL = "https://api.gg.deals/v1/prices/by-steam-app-id/"
GG_DEALS_API_KEY    = os.getenv("GG_DEALS_API_KEY", "")

_STEAM_APP_RE = re.compile(r'store\.steampowered\.com/app/(\d+)', re.IGNORECASE)

_GAMERPOWER_PLATFORM_MAP: dict[str, str] = {
    "epic games store": "epic",
    "steam":            "steam",
    "gog":              "gog",
    "humble bundle":    "humble",
    "ubisoft":          "ubisoft",
    "origin":           "origin",
    "ea app":           "origin",
}

PLATFORM_COLORS = {
    "epic":    0x2D2D2D,
    "steam":   0x1B2838,
    "gog":     0x7C3AED,
    "ubisoft": 0x0070F3,
    "origin":  0xF26000,
    "humble":  0xCC3D0D,
    "other":   0x5865F2,
}

CATEGORY_LABELS = {
    "free_to_keep":      "🎁 Free to Keep",
    "free_weekend":      "⏳ Free Weekend",
    "other_freebies":    "🎮 Freebie",
    "gamedev_assets":    "🛠️ Game Dev Asset",
    "giveaways_rewards": "🎟️ Giveaway / Reward",
}

CATEGORY_KEYWORDS = {
    "free_weekend":      ["free weekend", "free to play weekend", "[weekend]", "play for free this weekend"],
    "gamedev_assets":    ["asset", "game dev", "unity", "unreal", "blender", "template", "plugin", "tool for dev"],
    "giveaways_rewards": ["giveaway", "key giveaway", "redeem", "reward code", "prime gaming", "humble choice"],
    "other_freebies":    ["dlc", "in-game", "cosmetic", "skin", "pack", "bundle", "item", "loot"],
}

ALL_CATEGORIES = ["free_to_keep", "free_weekend", "other_freebies", "gamedev_assets", "giveaways_rewards"]

ALL_PLATFORMS = ["steam", "epic", "gog", "ubisoft", "origin", "humble", "other"]

PLATFORM_LABELS = {
    "steam": "Steam",
    "epic": "Epic Games",
    "gog": "GOG",
    "ubisoft": "Ubisoft",
    "origin": "Origin / EA",
    "humble": "Humble Bundle",
    "other": "Other",
}


def classify_item(title: str, flair: str | None, platform: str, is_free_weekend: bool) -> str:
    text = (title + " " + (flair or "")).lower()
    if is_free_weekend:
        return "free_weekend"
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return category
    return "free_to_keep"


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
) -> discord.Embed:
    color = int(embed_color.lstrip("#"), 16) if embed_color else PLATFORM_COLORS.get(platform, 0x5865F2)
    embed = discord.Embed(title=title, url=url, color=color)

    # Description: price + expiry (prominent, top of embed)
    desc_lines = []
    if show_price:
        price_str = f"~~{original_price}~~ → **FREE**" if original_price else "**FREE**"
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

    # Secondary inline fields
    if show_category:
        embed.add_field(name="Category", value=CATEGORY_LABELS.get(category, category), inline=True)
    if show_platform:
        embed.add_field(name="Platform", value=PLATFORM_LABELS.get(platform, platform.title()), inline=True)

    if show_image and image_url:
        embed.set_image(url=image_url)
    embed.set_footer(text=f"{PLATFORM_LABELS.get(platform, platform.title())} • Free Games Bot")
    return embed

PLATFORM_EMOJIS = {
    "steam": "\U0001f3ae",      # controller
    "epic": "\U0001f3f0",       # castle
    "gog": "\U0001f4bf",        # disc
    "ubisoft": "\U0001f5a5",    # desktop
    "origin": "\U0001f3c3",     # runner
    "humble": "\U00002764",     # heart
    "other": "\U0001f4e6",      # package
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
        self._send_semaphore = asyncio.Semaphore(1)

    async def cog_load(self):
        await self.refresh_cache()
        self._session = aiohttp.ClientSession()
        # If reset was triggered (via dashboard or /freestuff reset), skip silent seeding
        flag = await db.get_setting("freestuff_force_announce", "0")
        if flag == "1":
            self._seeded = True
            await db.set_setting("freestuff_force_announce", "0")
        else:
            self._seeded = False
        self.check_loop.start()

    async def cog_unload(self):
        self.check_loop.cancel()
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

        embed = discord.Embed(title="Free Stuff Config", color=0x43B581)
        embed.add_field(name="Enabled", value="Yes" if enabled else "No", inline=True)
        embed.add_field(name="Channel", value=channel.mention if channel else "Not set", inline=True)

        platform_lines = []
        for p in ALL_PLATFORMS:
            status = "enabled" if p in platforms else "disabled"
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

    @freestuff_group.command(name="reset", description="Clear free game history so all current freebies are re-announced (testing)")
    async def freestuff_reset(self, interaction: discord.Interaction):
        view = _ResetConfirmView()
        await interaction.response.send_message(
            "⚠️ This will delete all cached free game entries and re-announce every current freebie. Continue?",
            view=view,
            ephemeral=True,
        )
        await view.wait()
        if not view.confirmed:
            await interaction.edit_original_response(content="Cancelled.", view=None)
            return
        deleted = await db.clear_free_games()
        self._seeded = True  # next _fetch_all will announce instead of silently seed
        await db.set_setting("freestuff_force_announce", "1")
        await interaction.edit_original_response(
            content=f"Cleared **{deleted}** cached entries. Running fetch now...", view=None
        )
        new_games = await self._fetch_all()
        await interaction.edit_original_response(
            content=f"Cleared **{deleted}** cached entries. Re-announced **{len(new_games)}** game(s)."
        )

    @freestuff_group.command(name="check", description="Manually check for free games now")
    async def freestuff_check(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # Fetch from sources (adds new ones to DB, notifies guilds)
        new_games = await self._fetch_all()

        # Always show recent games from the DB so the user sees what's tracked
        recent = await db.get_free_games(limit=10)

        if new_games:
            msg = f"Found **{len(new_games)}** new free game(s)! Notifications sent.\n\n"
        else:
            msg = "No *new* free games found right now.\n\n"

        if recent:
            embed = discord.Embed(title="Recent Free Games", color=0x43B581)
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
            msg += "No free games have been discovered yet. The bot checks every 20 minutes."
            await interaction.followup.send(msg)

    # --- Background loop ---

    @tasks.loop(minutes=20)
    async def check_loop(self):
        try:
            await self._fetch_all()
        except Exception:
            log.exception("Error in freestuff check loop")

    @check_loop.before_loop
    async def before_check_loop(self):
        await self.bot.wait_until_ready()

    async def _fetch_all(self) -> list[dict]:
        """Fetch from all sources, dedup, notify guilds. Returns list of new games."""
        new_games = []
        new_games.extend(await self._fetch_epic())
        new_games.extend(await self._fetch_gamerpower())
        await self._enrich_steam_prices(new_games)

        if not self._seeded:
            # First run after startup: silently seed the DB so existing freebies
            # are not treated as new. No notifications sent.
            self._seeded = True
            log.info("FreeStuff: seeded %d game(s) on startup — no notifications sent.", len(new_games))
            return []

        if new_games:
            await self._notify_guilds(new_games)

        return new_games

    async def _fetch_epic(self) -> list[dict]:
        new_games = []
        try:
            async with self._session.get(EPIC_API, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()

            elements = data.get("data", {}).get("Catalog", {}).get("searchStore", {}).get("elements", [])
            for elem in elements:
                title = elem.get("title", "")
                offers = elem.get("promotions")
                if not offers:
                    continue

                promo_list = offers.get("promotionalOffers", [])
                for promo_group in promo_list:
                    for offer in promo_group.get("promotionalOffers", []):
                        discount_pct = offer.get("discountSetting", {}).get("discountPercentage", 0)
                        if discount_pct != 0:
                            continue

                        start_date_str = offer.get("startDate", "")
                        if start_date_str:
                            try:
                                start_dt = datetime.fromisoformat(start_date_str.replace("Z", "+00:00"))
                                if start_dt > datetime.now(timezone.utc):
                                    continue  # offer not live yet — skip to avoid blocking future send
                            except ValueError:
                                pass

                        slug = elem.get("catalogNs", {}).get("mappings", [{}])
                        page_slug = slug[0].get("pageSlug", "") if slug else ""
                        url = f"https://store.epicgames.com/p/{page_slug}" if page_slug else ""
                        if not url:
                            url = f"https://store.epicgames.com/browse?q={title.replace(' ', '+')}"

                        image_url = ""
                        for img in elem.get("keyImages", []):
                            if img.get("type") in ("OfferImageWide", "DieselStoreFrontWide", "Thumbnail"):
                                image_url = img.get("url", "")
                                break

                        price_info = (elem.get("price") or {}).get("totalPrice", {})
                        original = (price_info.get("fmtPrice") or {}).get("originalPrice", "")

                        # Detect free weekend: end date within 4 days
                        end_date_str = offer.get("endDate", "")
                        is_free_weekend = False
                        if end_date_str:
                            try:
                                end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                                if end_dt < datetime.now(timezone.utc):
                                    continue  # already expired
                                delta = end_dt - datetime.now(timezone.utc)
                                is_free_weekend = 0 < delta.days <= 4
                            except Exception as e:
                                log.debug("Skipping malformed Epic item: %s", e)

                        category = classify_item(title, None, "epic", is_free_weekend)
                        end_date_display = end_date_str[:10] if end_date_str else ""

                        game_id = await db.add_free_game(
                            title=title, url=url, platform="epic",
                            image_url=image_url, original_price=original, source="epic",
                            category=category,
                        )
                        if game_id:
                            new_games.append({
                                "title": title, "url": url, "platform": "epic",
                                "image_url": image_url, "original_price": original,
                                "end_date": end_date_display, "category": category,
                            })
        except Exception:
            log.exception("Error fetching Epic free games")
        return new_games

    async def _fetch_gamerpower(self) -> list[dict]:
        new_games = []
        try:
            headers = {"User-Agent": "DiscordBot/1.0"}
            async with self._session.get(GAMERPOWER_API_URL, headers=headers,
                                         timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return []
                items = await resp.json()

            for item in items:
                title = (item.get("title") or "").strip()
                gp_url = item.get("open_giveaway_url") or ""
                if not title or not gp_url:
                    continue

                # Skip mobile-only (no PC/store platform)
                platforms_str = (item.get("platforms") or "").lower()
                pc_stores = ("pc", "steam", "epic", "gog", "humble", "ubisoft", "origin", "drm-free", "itch")
                if not any(p in platforms_str for p in pc_stores):
                    continue

                # Skip items with a past end_date
                end_date_str = item.get("end_date") or ""
                end_date_display = ""
                if end_date_str and end_date_str != "N/A":
                    try:
                        end_dt = datetime.strptime(end_date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                        if end_dt < datetime.now(timezone.utc):
                            continue
                        end_date_display = end_date_str[:10]
                    except Exception:
                        pass

                # Detect platform from platforms field
                platform = "other"
                for key, val in _GAMERPOWER_PLATFORM_MAP.items():
                    if key in platforms_str:
                        platform = val
                        break

                # Follow redirect to get direct store URL
                url = gp_url
                try:
                    async with self._session.head(gp_url, allow_redirects=False,
                                                  timeout=aiohttp.ClientTimeout(total=5)) as r:
                        location = r.headers.get("Location", "")
                        if location:
                            url = location
                except Exception:
                    pass  # fall back to gamerpower URL

                image_url = item.get("thumbnail") or item.get("image") or ""
                original_price = item.get("worth") or ""
                category = classify_item(title, platforms_str, platform, False)

                game_id = await db.add_free_game(
                    title=title, url=url, platform=platform,
                    image_url=image_url, original_price=original_price,
                    source="gamerpower", category=category,
                )
                if game_id:
                    new_games.append({
                        "title": title, "url": url, "platform": platform,
                        "image_url": image_url, "original_price": original_price,
                        "end_date": end_date_display, "category": category,
                    })
        except Exception:
            log.exception("Error fetching GamerPower giveaways")
        return new_games

    async def _enrich_steam_prices(self, games: list[dict]) -> None:
        """Fill original_price from GG.deals Prices API for Steam games with a Steam App ID."""
        if not GG_DEALS_API_KEY:
            return

        app_id_map: dict[str, dict] = {}
        for game in games:
            if game["platform"] != "steam" or game.get("original_price"):
                continue
            search_str = game.get("url", "") + game.get("_desc", "")
            m = _STEAM_APP_RE.search(search_str)
            if m:
                app_id_map[m.group(1)] = game

        if not app_id_map:
            return

        ids = list(app_id_map.keys())
        for i in range(0, len(ids), 100):
            chunk = ids[i:i + 100]
            try:
                params = {"key": GG_DEALS_API_KEY, "ids": ",".join(chunk)}
                async with self._session.get(GG_DEALS_PRICES_URL, params=params,
                                             timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                for app_id, entry in (data.get("data") or {}).items():
                    if entry and app_id in app_id_map:
                        prices = entry.get("prices") or {}
                        hist = prices.get("historicalRetail")
                        currency = prices.get("currency", "USD")
                        if hist:
                            app_id_map[app_id]["original_price"] = f"{hist} {currency}"
            except Exception:
                log.exception("Error fetching GG.deals prices (chunk %d)", i)

    async def _send_with_ratelimit(self, channel, embed, content=None):
        """Send one message at a time with a fixed delay to avoid per-channel 429s."""
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
                        log.warning("Failed to send free game notification after retry to %s", channel.id)
                else:
                    log.warning("Failed to send free game notification to %s: %s", channel.id, e)
            finally:
                await asyncio.sleep(1.5)  # stay well under Discord's 5 msg/5s channel limit

    async def _notify_guilds(self, games: list[dict]):
        configs = await db.get_all_freestuff_configs()
        tasks = []
        for cfg in configs:
            guild = self.bot.get_guild(int(cfg["guild_id"]))
            if not guild:
                continue
            channel = guild.get_channel(int(cfg["channel_id"])) if cfg.get("channel_id") else None
            if not channel:
                continue

            allowed_platforms = json.loads(cfg.get("platforms", "[]"))
            guild_filters = json.loads(cfg.get("content_filters") or
                '["free_to_keep","free_weekend","other_freebies","gamedev_assets","giveaways_rewards"]')

            for game in games:
                if allowed_platforms and game["platform"] not in allowed_platforms:
                    continue
                if game.get("category", "free_to_keep") not in guild_filters:
                    continue

                mention_parts = []
                if cfg.get("mention_role_id"):
                    mention_parts.append(f"<@&{cfg['mention_role_id']}>")
                platform_roles = json.loads(cfg.get("platform_mention_roles") or "{}")
                if game["platform"] in platform_roles:
                    mention_parts.append(f"<@&{platform_roles[game['platform']]}>")
                content = " ".join(mention_parts) or None

                embed = build_game_embed(
                    title=game["title"],
                    url=game["url"],
                    platform=game["platform"],
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
                )
                embed.timestamp = datetime.now(timezone.utc)

                tasks.append(self._send_with_ratelimit(channel, embed, content=content))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(FreeStuff(bot))
