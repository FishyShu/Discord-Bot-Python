from __future__ import annotations

import random

from quart import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .auth import login_required
from . import db

giveaways_bp = Blueprint("giveaways", __name__)


@giveaways_bp.route("/")
@login_required
async def giveaways_list():
    bot = current_app.bot
    guilds = sorted(bot.guilds, key=lambda g: g.name.lower()) if bot else []
    active_counts = {}
    for g in guilds:
        rows = await db.get_active_giveaways(str(g.id))
        active_counts[g.id] = len(rows)
    return await render_template("giveaways.html", guilds=guilds, active_counts=active_counts)


@giveaways_bp.route("/<int:guild_id>")
@login_required
async def giveaways_guild(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("giveaways.giveaways_list"))
    active = await db.get_active_giveaways(str(guild_id))
    # Past giveaways: fetch all and filter ended ones
    past = await db.get_past_giveaways(str(guild_id)) if hasattr(db, "get_past_giveaways") else []
    return await render_template("giveaways_guild.html", guild=guild, active=active, past=past)


@giveaways_bp.route("/<int:guild_id>/end/<int:giveaway_id>", methods=["POST"])
@login_required
async def end_giveaway(guild_id: int, giveaway_id: int):
    giveaway = await db.get_giveaway(giveaway_id)
    if not giveaway or str(giveaway.get("guild_id", "")) != str(guild_id):
        await flash("Giveaway not found.", "danger")
        return redirect(url_for("giveaways.giveaways_guild", guild_id=guild_id))

    # Pick random winners from entrants
    entrants = giveaway.get("entrants") or []
    if isinstance(entrants, str):
        import json
        try:
            entrants = json.loads(entrants)
        except Exception:
            entrants = []

    winner_count = int(giveaway.get("winner_count", 1))
    winners = random.sample(entrants, min(winner_count, len(entrants))) if entrants else []
    await db.end_giveaway(giveaway_id, winners)
    await flash(f"Giveaway ended. Winners: {', '.join(f'<@{w}>' for w in winners) or 'None'}", "success")
    return redirect(url_for("giveaways.giveaways_guild", guild_id=guild_id))
