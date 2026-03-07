from __future__ import annotations

from quart import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .auth import login_required
from . import db

reaction_roles_bp = Blueprint("reaction_roles", __name__)


@reaction_roles_bp.route("/")
@login_required
async def rr_list():
    bot = current_app.bot
    guilds = sorted(bot.guilds, key=lambda g: g.name.lower()) if bot else []
    return await render_template("reaction_roles.html", guilds=guilds)


@reaction_roles_bp.route("/<int:guild_id>")
@login_required
async def rr_guild(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("reaction_roles.rr_list"))

    rrs = await db.get_reaction_roles(str(guild_id))

    # Resolve role names
    for rr in rrs:
        role = guild.get_role(int(rr["role_id"]))
        rr["role_name"] = role.name if role else "Deleted Role"
        ch = guild.get_channel(int(rr["channel_id"]))
        rr["channel_name"] = f"#{ch.name}" if ch else "Unknown"

    return await render_template("reaction_roles_guild.html", guild=guild, rrs=rrs)


@reaction_roles_bp.route("/<int:guild_id>/add", methods=["POST"])
@login_required
async def rr_add(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("reaction_roles.rr_list"))

    form = await request.form
    channel_id = form.get("channel_id", "").strip()
    message_id = form.get("message_id", "").strip()
    emoji = form.get("emoji", "").strip()
    role_id = form.get("role_id", "").strip()

    if not all([channel_id, message_id, emoji, role_id]):
        await flash("All fields are required.", "danger")
        return redirect(url_for("reaction_roles.rr_guild", guild_id=guild_id))

    try:
        await db.create_reaction_role(
            guild_id=str(guild_id),
            channel_id=channel_id,
            message_id=message_id,
            emoji=emoji,
            role_id=role_id,
        )
    except Exception as e:
        await flash(f"Error: {e}", "danger")
        return redirect(url_for("reaction_roles.rr_guild", guild_id=guild_id))

    cog = bot.get_cog("ReactionRoles")
    if cog:
        await cog.refresh_cache()

    await flash("Reaction role added.", "success")
    return redirect(url_for("reaction_roles.rr_guild", guild_id=guild_id))


@reaction_roles_bp.route("/<int:guild_id>/delete/<int:rr_id>", methods=["POST"])
@login_required
async def rr_delete(guild_id: int, rr_id: int):
    bot = current_app.bot
    # Verify reaction role belongs to this guild (IDOR protection)
    rr_list = await db.get_reaction_roles(str(guild_id))
    if not any(r["id"] == rr_id for r in rr_list):
        await flash("Reaction role not found in this server.", "danger")
        return redirect(url_for("reaction_roles.rr_guild", guild_id=guild_id))
    await db.delete_reaction_role(rr_id)

    cog = bot.get_cog("ReactionRoles")
    if cog:
        await cog.refresh_cache()

    await flash("Reaction role deleted.", "success")
    return redirect(url_for("reaction_roles.rr_guild", guild_id=guild_id))
