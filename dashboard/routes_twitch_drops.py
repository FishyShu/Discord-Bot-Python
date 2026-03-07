from __future__ import annotations

import json
from datetime import datetime, timezone

import discord
from quart import Blueprint, current_app, redirect, render_template, request, url_for, flash

from .auth import login_required
from . import db

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

    # Parse game_filter (handle both old list and new dict formats)
    raw_filter = json.loads(cfg.get("game_filter", "{}")) if cfg else {}
    if isinstance(raw_filter, list):
        game_filter_dict = {g: True for g in raw_filter}
    elif isinstance(raw_filter, dict):
        game_filter_dict = raw_filter
    else:
        game_filter_dict = {}

    # Collect unique game names from active drops and merge with existing filter
    active_games = sorted(set(d["game_name"] for d in active_drops))
    game_toggles = {}
    for game in active_games:
        game_toggles[game] = game_filter_dict.get(game, False)

    roles = sorted(guild.roles, key=lambda r: r.position, reverse=True)

    return await render_template(
        "twitch_drops_edit.html",
        guild=guild,
        cfg=cfg,
        channels=channels,
        active_drops=active_drops,
        game_toggles=game_toggles,
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

    embed = discord.Embed(
        title="New Twitch Drop: Exclusive In-Game Reward",
        color=0x9146FF,
    )
    embed.add_field(name="Game", value="Example Game", inline=True)
    embed.add_field(name="Period", value="2026-03-01 — 2026-03-31", inline=True)
    embed.add_field(name="Description", value="Watch 2 hours of any Example Game stream to earn an exclusive cosmetic item!", inline=False)
    embed.set_footer(text="Twitch Drops Alert (TEST)")
    embed.timestamp = datetime.now(timezone.utc)

    mention_role_id = cfg.get("mention_role_id")
    content = f"<@&{mention_role_id}>" if mention_role_id else None

    try:
        await channel.send(content=content, embed=embed)
        await flash(f"Sent test notification to #{channel.name}.", "success")
    except discord.HTTPException:
        await flash("Failed to send test notification. Check bot permissions.", "danger")

    return redirect(url_for("twitch_drops.twitch_drops_edit", guild_id=guild_id))
