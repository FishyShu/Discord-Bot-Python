from __future__ import annotations

from quart import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .auth import login_required
from . import db

music_bp = Blueprint("music", __name__)


@music_bp.route("/")
@login_required
async def music_list():
    bot = current_app.bot
    guilds = sorted(bot.guilds, key=lambda g: g.name.lower()) if bot else []
    playing = {}
    cog = bot.get_cog("Music") if bot else None
    for g in guilds:
        if cog and g.id in cog.players and cog.players[g.id].current:
            playing[g.id] = True
        else:
            playing[g.id] = False
    return await render_template("music.html", guilds=guilds, playing=playing)


@music_bp.route("/<int:guild_id>", methods=["GET"])
@login_required
async def music_guild(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("music.music_list"))

    cog = bot.get_cog("Music") if bot else None
    player = cog.players.get(guild_id) if cog else None
    current_track = player.current if player else None
    queue = list(player.queue[:25]) if player else []
    volume = await db.get_guild_setting(str(guild_id), "music_default_volume", "50")
    max_queue = await db.get_guild_setting(str(guild_id), "music_max_queue_size", "500")
    return await render_template(
        "music_guild.html", guild=guild, current_track=current_track,
        queue=queue, volume=volume, max_queue=max_queue,
    )


@music_bp.route("/<int:guild_id>", methods=["POST"])
@login_required
async def music_save(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("music.music_list"))
    form = await request.form
    volume = form.get("music_default_volume", "50")
    max_queue = form.get("music_max_queue_size", "500")
    await db.set_guild_setting(str(guild_id), "music_default_volume", volume)
    await db.set_guild_setting(str(guild_id), "music_max_queue_size", max_queue)
    await flash("Music settings saved.", "success")
    return redirect(url_for("music.music_guild", guild_id=guild_id))
