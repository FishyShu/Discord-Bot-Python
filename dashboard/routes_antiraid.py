from __future__ import annotations

from quart import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .auth import login_required
from . import db

antiraid_bp = Blueprint("antiraid", __name__)


@antiraid_bp.route("/")
@login_required
async def antiraid_list():
    bot = current_app.bot
    guilds = sorted(bot.guilds, key=lambda g: g.name.lower()) if bot else []
    configs = {}
    for g in guilds:
        cfg = await db.get_antiraid_config(str(g.id))
        configs[g.id] = cfg
    return await render_template("antiraid.html", guilds=guilds, configs=configs)


@antiraid_bp.route("/<int:guild_id>", methods=["GET"])
@login_required
async def antiraid_edit(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("antiraid.antiraid_list"))
    cfg = await db.get_antiraid_config(str(guild_id)) or {}
    return await render_template("antiraid_edit.html", guild=guild, cfg=cfg)


@antiraid_bp.route("/<int:guild_id>", methods=["POST"])
@login_required
async def antiraid_save(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("antiraid.antiraid_list"))

    form = await request.form
    await db.upsert_antiraid_config(
        str(guild_id),
        enabled=int("enabled" in form),
        action=form.get("action", "kick"),
        mass_join_threshold=int(form.get("mass_join_threshold") or 10),
        new_account_age=int(form.get("new_account_age") or 7),
        mention_spam_threshold=int(form.get("mention_spam_threshold") or 5),
        message_spam_threshold=int(form.get("message_spam_threshold") or 10),
    )
    await flash("Anti-raid settings saved.", "success")
    return redirect(url_for("antiraid.antiraid_edit", guild_id=guild_id))


@antiraid_bp.route("/<int:guild_id>/lockdown", methods=["POST"])
@login_required
async def antiraid_lockdown(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("antiraid.antiraid_list"))
    cog = bot.get_cog("AntiRaid") if bot else None
    if cog and hasattr(cog, "lockdown"):
        await cog.lockdown(guild)
        await flash("Server locked down.", "success")
    else:
        await flash("AntiRaid cog not available.", "warning")
    return redirect(url_for("antiraid.antiraid_edit", guild_id=guild_id))


@antiraid_bp.route("/<int:guild_id>/unlock", methods=["POST"])
@login_required
async def antiraid_unlock(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("antiraid.antiraid_list"))
    cog = bot.get_cog("AntiRaid") if bot else None
    if cog and hasattr(cog, "unlock"):
        await cog.unlock(guild)
        await flash("Server unlocked.", "success")
    else:
        await flash("AntiRaid cog not available.", "warning")
    return redirect(url_for("antiraid.antiraid_edit", guild_id=guild_id))
