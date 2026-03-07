from __future__ import annotations

from quart import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .auth import login_required
from . import db

utility_bp = Blueprint("utility", __name__)


@utility_bp.route("/")
@login_required
async def utility_list():
    bot = current_app.bot
    guilds = sorted(bot.guilds, key=lambda g: g.name.lower()) if bot else []
    counts = {}
    for g in guilds:
        reminders = await db.get_guild_reminders(str(g.id))
        counts[g.id] = len(reminders)
    return await render_template("utility.html", guilds=guilds, counts=counts)


@utility_bp.route("/<int:guild_id>")
@login_required
async def utility_guild(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("utility.utility_list"))
    reminders = await db.get_guild_reminders(str(guild_id))
    # Resolve user names and channel names
    for r in reminders:
        member = guild.get_member(int(r["user_id"]))
        r["user_name"] = str(member) if member else f"User #{r['user_id']}"
        channel = guild.get_channel(int(r["channel_id"]))
        r["channel_name"] = f"#{channel.name}" if channel else f"#{r['channel_id']}"
        r["message_short"] = r["message"][:80] + ("..." if len(r["message"]) > 80 else "")
    return await render_template("utility_guild.html", guild=guild, reminders=reminders)


@utility_bp.route("/<int:guild_id>/delete/<int:reminder_id>", methods=["POST"])
@login_required
async def utility_delete(guild_id: int, reminder_id: int):
    # Verify reminder belongs to this guild (IDOR protection)
    reminders = await db.get_guild_reminders(str(guild_id))
    if not any(r["id"] == reminder_id for r in reminders):
        await flash("Reminder not found in this server.", "danger")
        return redirect(url_for("utility.utility_guild", guild_id=guild_id))
    await db.delete_reminder(reminder_id)
    await flash("Reminder deleted.", "success")
    return redirect(url_for("utility.utility_guild", guild_id=guild_id))
