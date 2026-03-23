from __future__ import annotations

import json
from datetime import datetime, timezone

import discord
from quart import Blueprint, current_app, jsonify, redirect, render_template, request, url_for, flash

from .auth import login_required
from . import db

freestuff_bp = Blueprint("freestuff", __name__)

ALL_CATEGORIES = ["free_to_keep", "free_weekend", "other_freebies", "gamedev_assets", "giveaways_rewards"]

_CATEGORY_EXAMPLES = {
    "free_to_keep": {
        "title": "Celeste",
        "platform": "epic",
        "original_price": "$19.99",
        "url": "https://store.epicgames.com/p/celeste",
        "image_url": "https://cdn2.unrealengine.com/egs-celeste-mattmakesgames-ic1-400x400-e04e0470c3e4.png",
        "end_date": "2026-04-01",
        "category": "free_to_keep",
    },
    "free_weekend": {
        "title": "Deep Rock Galactic (Free Weekend)",
        "platform": "steam",
        "original_price": "$29.99",
        "url": "https://store.steampowered.com/app/548430/Deep_Rock_Galactic/",
        "image_url": "",
        "end_date": "2026-03-25",
        "category": "free_weekend",
    },
    "other_freebies": {
        "title": "Exclusive DLC Pack — Tomb Raider",
        "platform": "steam",
        "original_price": "$4.99",
        "url": "https://store.steampowered.com/app/208050/",
        "image_url": "",
        "end_date": "",
        "category": "other_freebies",
    },
    "gamedev_assets": {
        "title": "Synty Polygon City Pack (Unity Asset)",
        "platform": "humble",
        "original_price": "$59.99",
        "url": "https://www.humblebundle.com/",
        "image_url": "",
        "end_date": "2026-04-15",
        "category": "gamedev_assets",
    },
    "giveaways_rewards": {
        "title": "Prime Gaming: Control (Key Giveaway)",
        "platform": "other",
        "original_price": "$29.99",
        "url": "https://gaming.amazon.com/",
        "image_url": "",
        "end_date": "2026-03-31",
        "category": "giveaways_rewards",
    },
}


@freestuff_bp.route("/")
@login_required
async def freestuff_list():
    bot = current_app.bot
    guilds = sorted(bot.guilds, key=lambda g: g.name.lower()) if bot else []
    configs = {}
    for guild in guilds:
        cfg = await db.get_freestuff_config(str(guild.id))
        configs[guild.id] = cfg
    return await render_template("freestuff.html", guilds=guilds, configs=configs)


@freestuff_bp.route("/<int:guild_id>")
@login_required
async def freestuff_edit(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("freestuff.freestuff_list"))

    cfg = await db.get_freestuff_config(str(guild_id)) or {}
    channels = sorted(guild.text_channels, key=lambda c: c.position)
    recent_games = await db.get_free_games(limit=20)

    platforms = json.loads(cfg.get("platforms", "[]")) if cfg else []
    content_filters = json.loads(cfg.get("content_filters") or
        '["free_to_keep","free_weekend","other_freebies","gamedev_assets","giveaways_rewards"]')

    roles = sorted(guild.roles, key=lambda r: r.position, reverse=True)

    return await render_template(
        "freestuff_edit.html",
        guild=guild,
        cfg=cfg,
        channels=channels,
        recent_games=recent_games,
        platforms=platforms,
        content_filters=content_filters,
        roles=roles,
        all_categories=ALL_CATEGORIES,
    )


@freestuff_bp.route("/<int:guild_id>", methods=["POST"])
@login_required
async def freestuff_save(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("freestuff.freestuff_list"))

    form = await request.form
    channel_id = form.get("channel_id", "")
    enabled = 1 if form.get("enabled") else 0

    platform_options = ["steam", "epic", "gog", "ubisoft", "origin", "humble", "other"]
    selected_platforms = [p for p in platform_options if form.get(f"platform_{p}")]
    if not selected_platforms:
        selected_platforms = platform_options

    selected_filters = [c for c in ALL_CATEGORIES if form.get(f"filter_{c}")]
    if not selected_filters:
        selected_filters = ALL_CATEGORIES

    mention_role_id = form.get("mention_role_id", "") or None

    await db.upsert_freestuff_config(
        str(guild_id),
        channel_id=channel_id,
        enabled=enabled,
        platforms=json.dumps(selected_platforms),
        content_filters=json.dumps(selected_filters),
        mention_role_id=mention_role_id,
    )

    cog = bot.get_cog("FreeStuff")
    if cog:
        await cog.refresh_cache()

    await flash("Free stuff settings saved.", "success")
    return redirect(url_for("freestuff.freestuff_edit", guild_id=guild_id))


@freestuff_bp.route("/<int:guild_id>/test/<category>", methods=["POST"])
@login_required
async def freestuff_test(guild_id: int, category: str):
    if category not in ALL_CATEGORIES:
        return jsonify({"message": "Invalid category."}), 400

    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        return jsonify({"message": "Server not found."}), 404

    cfg = await db.get_freestuff_config(str(guild_id))
    if not cfg or not cfg.get("channel_id"):
        return jsonify({"message": "Please configure a notification channel first."}), 400

    channel = guild.get_channel(int(cfg["channel_id"]))
    if not channel:
        return jsonify({"message": "Notification channel not found."}), 400

    ex = _CATEGORY_EXAMPLES[category]

    # Import here to avoid circular; build_game_embed is a plain function
    from cogs.freestuff import build_game_embed, PLATFORM_LABELS
    embed = build_game_embed(
        title=ex["title"],
        url=ex["url"],
        platform=ex["platform"],
        image_url=ex["image_url"],
        original_price=ex["original_price"],
        end_date=ex["end_date"],
        category=ex["category"],
    )
    embed.set_footer(text=f"{PLATFORM_LABELS.get(ex['platform'], ex['platform'].title())} • Free Games Bot (TEST)")
    embed.timestamp = datetime.now(timezone.utc)

    mention_role_id = cfg.get("mention_role_id")
    content = f"<@&{mention_role_id}>" if mention_role_id else None

    try:
        await channel.send(content=content, embed=embed)
        return jsonify({"message": f"Test embed sent to #{channel.name}."})
    except discord.HTTPException as e:
        return jsonify({"message": f"Failed to send: {e}"}), 500
