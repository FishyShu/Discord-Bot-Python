from __future__ import annotations

import math

from quart import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .auth import login_required
from .utils import _safe_int, _save_upload
from . import db

leveling_bp = Blueprint("leveling", __name__)


@leveling_bp.route("/")
@login_required
async def leveling_list():
    bot = current_app.bot
    guilds = sorted(bot.guilds, key=lambda g: g.name.lower()) if bot else []
    configs = {}
    for g in guilds:
        cfg = await db.get_xp_config(str(g.id))
        configs[g.id] = cfg
    return await render_template("leveling.html", guilds=guilds, configs=configs)


@leveling_bp.route("/<int:guild_id>", methods=["GET"])
@login_required
async def leveling_edit(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("leveling.leveling_list"))

    cfg = await db.get_xp_config(str(guild_id)) or {}
    rewards = await db.get_xp_role_rewards(str(guild_id))
    # Resolve role names
    for r in rewards:
        role = guild.get_role(int(r["role_id"]))
        r["role_name"] = role.name if role else "Deleted Role"

    return await render_template("leveling_edit.html", guild=guild, cfg=cfg, rewards=rewards)


@leveling_bp.route("/<int:guild_id>", methods=["POST"])
@login_required
async def leveling_save(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("leveling.leveling_list"))

    form = await request.form
    files = await request.files

    # Handle level-up image
    cfg = await db.get_xp_config(str(guild_id)) or {}
    levelup_image_path = cfg.get("levelup_image_path")
    levelup_image_url = cfg.get("levelup_image_url", "")

    if form.get("clear_levelup_image"):
        levelup_image_path = None
        levelup_image_url = ""

    new_upload = _save_upload(files.get("levelup_image_file"))
    if new_upload:
        levelup_image_path = new_upload
        levelup_image_url = ""
    elif not new_upload and not form.get("clear_levelup_image"):
        url_val = form.get("levelup_image_url", "").strip()
        if url_val:
            levelup_image_url = url_val
            levelup_image_path = None

    await db.upsert_xp_config(
        str(guild_id),
        enabled=int("enabled" in form),
        xp_per_message=_safe_int(form.get("xp_per_message", 15), 15),
        xp_cooldown=_safe_int(form.get("xp_cooldown", 60), 60),
        levelup_channel_id=form.get("levelup_channel_id", ""),
        levelup_message=form.get("levelup_message", "Congrats {user}, you reached level {level}!"),
        levelup_image_path=levelup_image_path,
        levelup_image_url=levelup_image_url,
    )

    cog = bot.get_cog("Leveling")
    if cog:
        await cog.refresh_cache()

    await flash("Leveling settings saved.", "success")
    return redirect(url_for("leveling.leveling_edit", guild_id=guild_id))


@leveling_bp.route("/<int:guild_id>/reward/add", methods=["POST"])
@login_required
async def leveling_reward_add(guild_id: int):
    bot = current_app.bot
    form = await request.form
    level = _safe_int(form.get("level", 0), 0)
    role_id = form.get("role_id", "").strip()

    if level < 1 or not role_id:
        await flash("Level and role are required.", "danger")
        return redirect(url_for("leveling.leveling_edit", guild_id=guild_id))

    try:
        await db.create_xp_role_reward(str(guild_id), level, role_id)
    except Exception as e:
        await flash(f"Error: {e}", "danger")
        return redirect(url_for("leveling.leveling_edit", guild_id=guild_id))

    cog = bot.get_cog("Leveling")
    if cog:
        await cog.refresh_cache()

    await flash(f"Role reward for level {level} added.", "success")
    return redirect(url_for("leveling.leveling_edit", guild_id=guild_id))


@leveling_bp.route("/<int:guild_id>/reward/delete/<int:reward_id>", methods=["POST"])
@login_required
async def leveling_reward_delete(guild_id: int, reward_id: int):
    bot = current_app.bot
    # Verify reward belongs to this guild (IDOR protection)
    rewards = await db.get_xp_role_rewards(str(guild_id))
    if not any(r["id"] == reward_id for r in rewards):
        await flash("Reward not found in this server.", "danger")
        return redirect(url_for("leveling.leveling_edit", guild_id=guild_id))
    await db.delete_xp_role_reward(reward_id)

    cog = bot.get_cog("Leveling")
    if cog:
        await cog.refresh_cache()

    await flash("Role reward deleted.", "success")
    return redirect(url_for("leveling.leveling_edit", guild_id=guild_id))


@leveling_bp.route("/<int:guild_id>/leaderboard")
@login_required
async def leaderboard(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("leveling.leveling_list"))

    lb = await db.get_xp_leaderboard(str(guild_id), limit=50)
    # Resolve usernames
    for entry in lb:
        member = guild.get_member(int(entry["user_id"]))
        entry["username"] = str(member) if member else f"User {entry['user_id']}"

    return await render_template("leaderboard.html", guild=guild, leaderboard=lb)


@leveling_bp.route("/<int:guild_id>/xp-log")
@login_required
async def xp_log(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("leveling.leveling_list"))

    page = max(1, _safe_int(request.args.get("page", 1), 1))
    per_page = 50
    offset = (page - 1) * per_page

    entries = await db.get_xp_log(str(guild_id), limit=per_page, offset=offset)
    total = await db.get_xp_log_count(str(guild_id))
    total_pages = max(1, math.ceil(total / per_page))

    # Resolve user and channel names
    for entry in entries:
        member = guild.get_member(int(entry["user_id"]))
        entry["username"] = str(member) if member else f"User {entry['user_id']}"
        ch = guild.get_channel(int(entry["channel_id"])) if entry.get("channel_id") else None
        entry["channel_name"] = f"#{ch.name}" if ch else entry.get("channel_id", "—")

    return await render_template(
        "xp_log.html", guild=guild, entries=entries,
        page=page, total_pages=total_pages,
    )
