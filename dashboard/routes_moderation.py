from __future__ import annotations

from quart import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .auth import login_required
from . import db

moderation_bp = Blueprint("moderation", __name__)


@moderation_bp.route("/")
@login_required
async def moderation_list():
    bot = current_app.bot
    guilds = sorted(bot.guilds, key=lambda g: g.name.lower()) if bot else []
    warning_counts = {}
    for g in guilds:
        rows = await db.get_modlog(str(g.id), limit=1000)
        warns = [r for r in rows if r.get("action") == "warn"]
        warning_counts[g.id] = len(warns)
    return await render_template("moderation.html", guilds=guilds, warning_counts=warning_counts)


@moderation_bp.route("/<int:guild_id>")
@login_required
async def moderation_guild(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("moderation.moderation_list"))

    user_id_filter = request.args.get("user_id", "").strip()
    action_filter = request.args.get("action", "").strip()

    warnings = []
    if user_id_filter:
        warnings = await db.get_warnings(str(guild_id), user_id_filter)

    modlog = await db.get_modlog(
        str(guild_id),
        user_id=user_id_filter or None,
        limit=50,
    )
    if action_filter:
        modlog = [e for e in modlog if e.get("action", "") == action_filter]

    return await render_template(
        "moderation_guild.html",
        guild=guild,
        warnings=warnings,
        modlog=modlog,
        user_id_filter=user_id_filter,
        action_filter=action_filter,
    )


@moderation_bp.route("/<int:guild_id>/warnings/<int:warning_id>/delete", methods=["POST"])
@login_required
async def delete_warning(guild_id: int, warning_id: int):
    deleted = await db.delete_warning(warning_id, str(guild_id))
    if deleted:
        await flash("Warning deleted.", "success")
    else:
        await flash("Warning not found.", "danger")
    user_id = (await request.form).get("user_id", "")
    return redirect(url_for("moderation.moderation_guild", guild_id=guild_id, user_id=user_id))
