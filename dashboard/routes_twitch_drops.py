from __future__ import annotations

import json

import discord
from quart import Blueprint, current_app, redirect, render_template, request, url_for, flash

from .auth import login_required
from . import db
from cogs.twitch_drops import build_drop_embed

twitch_drops_bp = Blueprint("twitch_drops", __name__)


@twitch_drops_bp.route("/")
@login_required
async def twitch_drops_list():
    bot = current_app.bot
    guilds = sorted(bot.guilds, key=lambda g: g.name.lower()) if bot else []
    configs = {}
    for guild in guilds:
        cfg = await db.get_twitch_drops_config(str(guild.id))
        configs[guild.id] = cfg
    return await render_template("twitch_drops.html", guilds=guilds, configs=configs)


@twitch_drops_bp.route("/<int:guild_id>")
@login_required
async def twitch_drops_edit(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("twitch_drops.twitch_drops_list"))

    cfg = await db.get_twitch_drops_config(str(guild_id)) or {}
    channels = sorted(guild.text_channels, key=lambda c: c.position)
    active_drops = await db.get_active_drops()
    all_game_statuses = await db.get_all_cached_game_statuses()

    # Parse game_filter (handle both old list and new dict formats)
    raw_filter = json.loads(cfg.get("game_filter", "{}")) if cfg else {}
    if isinstance(raw_filter, list):
        enabled_set = {g.lower() for g in raw_filter}
        raw_filter = {g: True for g in raw_filter}
    elif isinstance(raw_filter, dict):
        enabled_set = {g.lower() for g, on in raw_filter.items() if on}
    else:
        enabled_set = set()
        raw_filter = {}

    game_toggles = {}
    for g in all_game_statuses:
        name = g["game_name"]
        game_toggles[name] = {
            "enabled": name.lower() in enabled_set or not raw_filter,
            "is_active": bool(g["is_active"]),
            "end_date": (g.get("end_date") or "")[:10],
        }

    embed_settings = {
        "show_game":        bool(cfg.get("embed_show_game", 1)),
        "show_period":      bool(cfg.get("embed_show_period", 1)),
        "show_description": bool(cfg.get("embed_show_description", 1)),
        "show_image":       bool(cfg.get("embed_show_image", 1)),
        "show_link":        bool(cfg.get("embed_show_link", 1)),
        "color":            cfg.get("embed_color") or "",
    }

    roles = sorted(guild.roles, key=lambda r: r.position, reverse=True)

    return await render_template(
        "twitch_drops_edit.html",
        guild=guild,
        cfg=cfg,
        channels=channels,
        active_drops=active_drops,
        game_toggles=game_toggles,
        embed_settings=embed_settings,
        roles=roles,
    )


@twitch_drops_bp.route("/<int:guild_id>", methods=["POST"])
@login_required
async def twitch_drops_save(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("twitch_drops.twitch_drops_list"))

    form = await request.form
    channel_id = form.get("channel_id", "")
    enabled = 1 if form.get("enabled") else 0

    # Build game filter dict from per-game toggle checkboxes
    game_names = form.getlist("game_names")
    game_filter_dict = {}
    for game in game_names:
        game_filter_dict[game] = f"game_toggle_{game}" in form

    mention_role_id = form.get("mention_role_id", "") or None

    await db.upsert_twitch_drops_config(
        str(guild_id),
        channel_id=channel_id,
        enabled=enabled,
        game_filter=json.dumps(game_filter_dict),
        mention_role_id=mention_role_id,
        embed_show_game=1 if form.get("embed_show_game") else 0,
        embed_show_period=1 if form.get("embed_show_period") else 0,
        embed_show_description=1 if form.get("embed_show_description") else 0,
        embed_show_image=1 if form.get("embed_show_image") else 0,
        embed_show_link=1 if form.get("embed_show_link") else 0,
        embed_color=form.get("embed_color", "").strip() or None,
    )

    cog = bot.get_cog("TwitchDrops")
    if cog:
        await cog.refresh_cache()

    await flash("Twitch Drops settings saved.", "success")
    return redirect(url_for("twitch_drops.twitch_drops_edit", guild_id=guild_id))


@twitch_drops_bp.route("/<int:guild_id>/test", methods=["POST"])
@login_required
async def twitch_drops_test(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("twitch_drops.twitch_drops_list"))

    cfg = await db.get_twitch_drops_config(str(guild_id))
    if not cfg or not cfg.get("channel_id"):
        await flash("Please configure a notification channel first.", "warning")
        return redirect(url_for("twitch_drops.twitch_drops_edit", guild_id=guild_id))

    channel = guild.get_channel(int(cfg["channel_id"]))
    if not channel:
        await flash("Notification channel not found.", "danger")
        return redirect(url_for("twitch_drops.twitch_drops_edit", guild_id=guild_id))

    test_drop = {
        "drop_name": "Exclusive In-Game Reward",
        "game_name": "Example Game",
        "start_date": "2026-03-01",
        "end_date": "2026-03-31",
        "description": "Watch 2 hours of any Example Game stream to earn an exclusive cosmetic item!",
        "image_url": "",
        "details_url": "",
    }
    embed = build_drop_embed(
        test_drop,
        embed_color=cfg.get("embed_color") or None,
        show_game=bool(cfg.get("embed_show_game", 1)),
        show_period=bool(cfg.get("embed_show_period", 1)),
        show_description=bool(cfg.get("embed_show_description", 1)),
        show_image=bool(cfg.get("embed_show_image", 1)),
        show_link=bool(cfg.get("embed_show_link", 1)),
    )
    embed.set_footer(text="Twitch Drops Alert (TEST)")

    mention_role_id = cfg.get("mention_role_id")
    content = f"<@&{mention_role_id}>" if mention_role_id else None

    try:
        await channel.send(content=content, embed=embed)
        await flash(f"Sent test notification to #{channel.name}.", "success")
    except discord.HTTPException:
        await flash("Failed to send test notification. Check bot permissions.", "danger")

    return redirect(url_for("twitch_drops.twitch_drops_edit", guild_id=guild_id))
