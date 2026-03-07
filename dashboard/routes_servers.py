from __future__ import annotations

from quart import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .auth import login_required
from . import db

servers_bp = Blueprint("servers", __name__)


@servers_bp.route("/")
@login_required
async def server_list():
    bot = current_app.bot
    guilds = sorted(bot.guilds, key=lambda g: g.name.lower()) if bot else []
    return await render_template("servers.html", guilds=guilds)


@servers_bp.route("/<int:guild_id>")
@login_required
async def server_detail(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("servers.server_list"))

    # Get music player state
    player = None
    music_cog = bot.get_cog("Music") if bot else None
    if music_cog and guild_id in music_cog.players:
        player = music_cog.players[guild_id]

    guild_settings = await db.get_all_guild_settings(str(guild_id))

    # Scoped commands for this guild
    all_commands = await db.get_commands(str(guild_id))
    scoped_commands = [c for c in all_commands if c["guild_id"] == str(guild_id)]

    # Feature configs
    gid = str(guild_id)
    welcome_cfg = await db.get_welcome_config(gid) or {}
    audit_cfg = await db.get_audit_config(gid) or {}
    xp_cfg = await db.get_xp_config(gid) or {}
    rr_list = await db.get_reaction_roles(gid)

    return await render_template(
        "server_detail.html",
        guild=guild,
        player=player,
        guild_settings=guild_settings,
        scoped_commands=scoped_commands,
        welcome_cfg=welcome_cfg,
        audit_cfg=audit_cfg,
        xp_cfg=xp_cfg,
        rr_count=len(rr_list),
    )


@servers_bp.route("/<int:guild_id>/settings", methods=["POST"])
@login_required
async def server_settings(guild_id: int):
    form = await request.form
    gid = str(guild_id)

    for key in ("dj_role", "default_volume", "command_prefix"):
        value = form.get(key, "").strip()
        if value:
            await db.set_guild_setting(gid, key, value)

    await flash("Guild settings saved.", "success")
    return redirect(url_for("servers.server_detail", guild_id=guild_id))
