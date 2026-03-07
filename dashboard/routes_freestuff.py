from __future__ import annotations

import json
from datetime import datetime, timezone

import discord
from quart import Blueprint, current_app, redirect, render_template, request, url_for, flash

from .auth import login_required
from . import db

freestuff_bp = Blueprint("freestuff", __name__)


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

    roles = sorted(guild.roles, key=lambda r: r.position, reverse=True)

    return await render_template(
        "freestuff_edit.html",
        guild=guild,
        cfg=cfg,
        channels=channels,
        recent_games=recent_games,
        platforms=platforms,
        roles=roles,
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

    mention_role_id = form.get("mention_role_id", "") or None

    await db.upsert_freestuff_config(
        str(guild_id),
        channel_id=channel_id,
        enabled=enabled,
        platforms=json.dumps(selected_platforms),
        mention_role_id=mention_role_id,
    )

    cog = bot.get_cog("FreeStuff")
    if cog:
        await cog.refresh_cache()

    await flash("Free stuff settings saved.", "success")
    return redirect(url_for("freestuff.freestuff_edit", guild_id=guild_id))


@freestuff_bp.route("/<int:guild_id>/test", methods=["POST"])
@login_required
async def freestuff_test(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("freestuff.freestuff_list"))

    cfg = await db.get_freestuff_config(str(guild_id))
    if not cfg or not cfg.get("channel_id"):
        await flash("Please configure a notification channel first.", "warning")
        return redirect(url_for("freestuff.freestuff_edit", guild_id=guild_id))

    channel = guild.get_channel(int(cfg["channel_id"]))
    if not channel:
        await flash("Notification channel not found.", "danger")
        return redirect(url_for("freestuff.freestuff_edit", guild_id=guild_id))

    # Send example embeds for different platforms
    examples = [
        {
            "title": "Celeste",
            "platform": "Epic",
            "price": "$19.99",
            "url": "https://store.epicgames.com/p/celeste",
            "color": 0x2F2F2F,
            "thumb": "https://cdn2.unrealengine.com/egs-celeste-mattmakesgames-ic1-400x400-e04e0470c3e4.png",
        },
        {
            "title": "Portal 2",
            "platform": "Steam",
            "price": "$9.99",
            "url": "https://store.steampowered.com/app/620/Portal_2/",
            "color": 0x1B2838,
            "thumb": "",
        },
        {
            "title": "Shadow of the Tomb Raider",
            "platform": "GOG",
            "price": "$29.99",
            "url": "https://www.gog.com/game/shadow_of_the_tomb_raider",
            "color": 0x86328A,
            "thumb": "",
        },
    ]

    mention_role_id = cfg.get("mention_role_id")
    content = f"<@&{mention_role_id}>" if mention_role_id else None

    sent = 0
    for ex in examples:
        embed = discord.Embed(
            title=f"Free: {ex['title']}",
            url=ex["url"],
            color=ex["color"],
        )
        embed.add_field(name="Platform", value=ex["platform"], inline=True)
        embed.add_field(name="Original Price", value=ex["price"], inline=True)
        if ex["thumb"]:
            embed.set_thumbnail(url=ex["thumb"])
        embed.set_footer(text="Free Game Alert (TEST)")
        embed.timestamp = datetime.now(timezone.utc)
        try:
            await channel.send(content=content, embed=embed)
            sent += 1
        except discord.HTTPException:
            pass

    if sent:
        await flash(f"Sent {sent} test notification(s) to #{channel.name}.", "success")
    else:
        await flash("Failed to send test notifications. Check bot permissions.", "danger")
    return redirect(url_for("freestuff.freestuff_edit", guild_id=guild_id))
