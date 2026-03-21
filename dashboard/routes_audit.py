from __future__ import annotations

from quart import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .auth import login_required
from . import db

audit_bp = Blueprint("audit", __name__)


@audit_bp.route("/")
@login_required
async def audit_list():
    bot = current_app.bot
    guilds = sorted(bot.guilds, key=lambda g: g.name.lower()) if bot else []
    configs = {}
    for g in guilds:
        cfg = await db.get_audit_config(str(g.id))
        configs[g.id] = cfg
    return await render_template("audit.html", guilds=guilds, configs=configs)


@audit_bp.route("/<int:guild_id>", methods=["GET"])
@login_required
async def audit_edit(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("audit.audit_list"))
    cfg = await db.get_audit_config(str(guild_id)) or {}
    return await render_template("audit_edit.html", guild=guild, cfg=cfg)


@audit_bp.route("/<int:guild_id>", methods=["POST"])
@login_required
async def audit_save(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("audit.audit_list"))

    form = await request.form
    await db.upsert_audit_config(
        str(guild_id),
        log_channel_id=form.get("log_channel_id", ""),
        log_edits=int("log_edits" in form),
        log_deletes=int("log_deletes" in form),
        log_joins=int("log_joins" in form),
        log_leaves=int("log_leaves" in form),
        log_role_changes=int("log_role_changes" in form),
        log_ghost_pings=int("log_ghost_pings" in form),
    )
    webhook_url = form.get("webhook_url", "").strip()
    if webhook_url:
        await db.set_guild_setting(str(guild_id), "audit_webhook_url", webhook_url)

    cog = bot.get_cog("AuditLog")
    if cog:
        await cog.refresh_cache()

    await flash("Audit log settings saved.", "success")
    return redirect(url_for("audit.audit_edit", guild_id=guild_id))
