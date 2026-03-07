from __future__ import annotations

import discord
from quart import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .auth import login_required
from . import db

settings_bp = Blueprint("settings", __name__)

ACTIVITY_MAP = {
    "playing": discord.ActivityType.playing,
    "listening": discord.ActivityType.listening,
    "watching": discord.ActivityType.watching,
    "competing": discord.ActivityType.competing,
}

STATUS_MAP = {
    "online": discord.Status.online,
    "idle": discord.Status.idle,
    "dnd": discord.Status.dnd,
    "invisible": discord.Status.invisible,
}


@settings_bp.route("/", methods=["GET", "POST"])
@login_required
async def settings_page():
    bot = current_app.bot

    if request.method == "POST":
        form = await request.form

        # Save each setting
        for key in ("activity_type", "status_text", "bot_status", "default_volume", "command_prefix"):
            value = form.get(key, "").strip()
            if value:
                await db.set_setting(key, value)

        # Toggles (unchecked checkboxes aren't sent)
        await db.set_setting("custom_commands_enabled", "1" if "custom_commands_enabled" in form else "0")
        await db.set_setting("auto_replies_enabled", "1" if "auto_replies_enabled" in form else "0")

        # Apply presence change live
        if bot:
            activity_type = ACTIVITY_MAP.get(form.get("activity_type", "playing"), discord.ActivityType.playing)
            status_text = form.get("status_text", "").strip()
            bot_status = STATUS_MAP.get(form.get("bot_status", "online"), discord.Status.online)

            activity = discord.Activity(type=activity_type, name=status_text) if status_text else None
            await bot.change_presence(activity=activity, status=bot_status)

        await flash("Settings saved.", "success")
        return redirect(url_for("settings.settings_page"))

    settings = await db.get_all_settings()
    return await render_template("settings.html", settings=settings)
