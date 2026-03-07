from __future__ import annotations

from quart import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .auth import login_required
from . import db

autorole_bp = Blueprint("autorole", __name__)


@autorole_bp.route("/")
@login_required
async def autorole_list():
    bot = current_app.bot
    guilds = sorted(bot.guilds, key=lambda g: g.name.lower()) if bot else []
    counts = {}
    for g in guilds:
        rows = await db.get_autoroles(str(g.id))
        counts[g.id] = len(rows)
    return await render_template("autorole.html", guilds=guilds, counts=counts)


@autorole_bp.route("/<int:guild_id>", methods=["GET"])
@login_required
async def autorole_edit(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("autorole.autorole_list"))
    rows = await db.get_autoroles(str(guild_id))
    active_role_ids = {r["role_id"] for r in rows}
    return await render_template("autorole_edit.html", guild=guild, active_role_ids=active_role_ids)


@autorole_bp.route("/<int:guild_id>", methods=["POST"])
@login_required
async def autorole_save(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("autorole.autorole_list"))

    form = await request.form
    selected_role_ids = set(form.getlist("role_ids"))

    existing = await db.get_autoroles(str(guild_id))
    existing_ids = {r["role_id"] for r in existing}

    for rid in selected_role_ids - existing_ids:
        await db.add_autorole(str(guild_id), rid)
    for rid in existing_ids - selected_role_ids:
        await db.remove_autorole(str(guild_id), rid)

    cog = bot.get_cog("AutoRole")
    if cog:
        await cog.refresh_cache()

    await flash("Auto-role settings saved.", "success")
    return redirect(url_for("autorole.autorole_edit", guild_id=guild_id))
