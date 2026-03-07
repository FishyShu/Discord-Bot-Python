from __future__ import annotations

from quart import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .auth import login_required
from . import db

welcome_bp = Blueprint("welcome", __name__)


@welcome_bp.route("/")
@login_required
async def welcome_list():
    bot = current_app.bot
    guilds = sorted(bot.guilds, key=lambda g: g.name.lower()) if bot else []
    configs = {}
    for g in guilds:
        cfg = await db.get_welcome_config(str(g.id))
        configs[g.id] = cfg
    return await render_template("welcome.html", guilds=guilds, configs=configs)


@welcome_bp.route("/<int:guild_id>", methods=["GET"])
@login_required
async def welcome_edit(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("welcome.welcome_list"))
    cfg = await db.get_welcome_config(str(guild_id)) or {}
    return await render_template("welcome_edit.html", guild=guild, cfg=cfg)


@welcome_bp.route("/<int:guild_id>", methods=["POST"])
@login_required
async def welcome_save(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("welcome.welcome_list"))

    form = await request.form
    await db.upsert_welcome_config(
        str(guild_id),
        welcome_enabled=int("welcome_enabled" in form),
        welcome_channel_id=form.get("welcome_channel_id", ""),
        welcome_message=form.get("welcome_message", ""),
        welcome_embed_json=form.get("welcome_embed_json", ""),
        goodbye_enabled=int("goodbye_enabled" in form),
        goodbye_channel_id=form.get("goodbye_channel_id", ""),
        goodbye_message=form.get("goodbye_message", ""),
        goodbye_embed_json=form.get("goodbye_embed_json", ""),
    )

    # Refresh cog cache
    cog = bot.get_cog("Welcome")
    if cog:
        await cog.refresh_cache()

    await flash("Welcome/Goodbye settings saved.", "success")
    return redirect(url_for("welcome.welcome_edit", guild_id=guild_id))
