from __future__ import annotations

from quart import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .auth import login_required
from . import db

tts_bp = Blueprint("tts", __name__)

TTS_LANGUAGES = [
    ("en", "English"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("ja", "Japanese"),
    ("pt", "Portuguese"),
    ("ru", "Russian"),
    ("ko", "Korean"),
]


@tts_bp.route("/")
@login_required
async def tts_list():
    bot = current_app.bot
    guilds = sorted(bot.guilds, key=lambda g: g.name.lower()) if bot else []
    statuses = {}
    for g in guilds:
        enabled = await db.get_guild_setting(str(g.id), "tts_enabled", "0")
        statuses[g.id] = enabled == "1"
    return await render_template("tts.html", guilds=guilds, statuses=statuses)


@tts_bp.route("/<int:guild_id>", methods=["GET"])
@login_required
async def tts_guild(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("tts.tts_list"))
    enabled = await db.get_guild_setting(str(guild_id), "tts_enabled", "0")
    lang = await db.get_guild_setting(str(guild_id), "tts_default_lang", "en")
    return await render_template(
        "tts_guild.html", guild=guild, tts_enabled=(enabled == "1"),
        tts_lang=lang, languages=TTS_LANGUAGES,
    )


@tts_bp.route("/<int:guild_id>", methods=["POST"])
@login_required
async def tts_save(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("tts.tts_list"))
    form = await request.form
    await db.set_guild_setting(str(guild_id), "tts_enabled", "1" if "tts_enabled" in form else "0")
    await db.set_guild_setting(str(guild_id), "tts_default_lang", form.get("tts_default_lang", "en"))
    await flash("TTS settings saved.", "success")
    return redirect(url_for("tts.tts_guild", guild_id=guild_id))
