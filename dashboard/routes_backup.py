from __future__ import annotations

import json

from quart import Blueprint, current_app, flash, redirect, render_template, request, url_for, Response

from .auth import login_required
from . import db

backup_bp = Blueprint("backup", __name__)


@backup_bp.route("/")
@login_required
async def backup_list():
    bot = current_app.bot
    guilds = sorted(bot.guilds, key=lambda g: g.name.lower()) if bot else []
    return await render_template("backup.html", guilds=guilds)


@backup_bp.route("/<int:guild_id>")
@login_required
async def backup_guild(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("backup.backup_list"))
    return await render_template("backup_guild.html", guild=guild)


@backup_bp.route("/<int:guild_id>/export")
@login_required
async def backup_export(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("backup.backup_list"))

    cog = bot.get_cog("Backup") if bot else None
    if cog and hasattr(cog, "_collect"):
        data = await cog._collect(guild)
    else:
        # Fallback: collect common config sections directly
        data = {
            "guild_id": str(guild_id),
            "guild_name": guild.name,
            "welcome": await db.get_welcome_config(str(guild_id)),
            "audit": await db.get_audit_config(str(guild_id)),
            "antiraid": await db.get_antiraid_config(str(guild_id)),
        }

    payload = json.dumps(data, indent=2, default=str)
    filename = f"backup_{guild_id}.json"
    return Response(
        payload,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@backup_bp.route("/<int:guild_id>/restore", methods=["POST"])
@login_required
async def backup_restore(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("backup.backup_list"))

    files = await request.files
    upload = files.get("backup_file")
    if not upload:
        await flash("No file uploaded.", "danger")
        return redirect(url_for("backup.backup_guild", guild_id=guild_id))

    raw = upload.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        await flash("Invalid JSON file.", "danger")
        return redirect(url_for("backup.backup_guild", guild_id=guild_id))

    cog = bot.get_cog("Backup") if bot else None
    if cog and hasattr(cog, "_restore"):
        restored = await cog._restore(guild, data)
        await flash(f"Restore complete. Sections restored: {restored}", "success")
    else:
        await flash("Backup cog not available for restore.", "warning")

    return redirect(url_for("backup.backup_guild", guild_id=guild_id))
