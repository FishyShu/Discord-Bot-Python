from __future__ import annotations

import json

from quart import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .auth import login_required
from .utils import _save_upload
from . import db

commands_bp = Blueprint("commands", __name__)


@commands_bp.route("/")
@login_required
async def command_list():
    commands = await db.get_commands()
    bot = current_app.bot
    guild_names = {}
    if bot:
        guild_names = {str(g.id): g.name for g in bot.guilds}
    return await render_template("commands.html", commands=commands, guild_names=guild_names)


@commands_bp.route("/new", methods=["GET", "POST"])
@login_required
async def command_new():
    bot = current_app.bot
    guilds = bot.guilds if bot else []

    if request.method == "POST":
        form = await request.form
        files = await request.files
        guild_id = form.get("guild_id") or None
        cooldown = int(form.get("cooldown", 0) or 0)
        required_role_id = form.get("required_role_id", "").strip() or None
        tts = "tts" in form

        attachment_path = _save_upload(files.get("attachment_file"))
        embed_image_path = _save_upload(files.get("embed_image_file"))
        embed_thumbnail_path = _save_upload(files.get("embed_thumbnail_file"))

        # Parse new advanced auto-reply fields
        use_regex = "use_regex" in form
        trigger_patterns_raw = form.get("trigger_patterns", "").strip()
        trigger_patterns = json.dumps([p.strip() for p in trigger_patterns_raw.splitlines() if p.strip()]) if trigger_patterns_raw else None
        reaction_emojis_raw = form.get("reaction_emojis", "").strip()
        reaction_emojis = json.dumps([e.strip() for e in reaction_emojis_raw.split(",") if e.strip()]) if reaction_emojis_raw else None
        auto_delete_seconds = int(form.get("auto_delete_seconds", 0) or 0)
        delete_trigger = "delete_trigger" in form
        mod_action = form.get("mod_action", "").strip() or None
        mod_action_value = form.get("mod_action_value", "").strip() or None
        response_image_url = form.get("response_image_url", "").strip() or None
        priority = int(form.get("priority", 0) or 0)
        no_prefix = "no_prefix" in form
        match_mode = form.get("match_mode", "contains") or "contains"

        await db.create_command(
            guild_id=guild_id,
            name=form["name"].strip(),
            type=form.get("type", "text"),
            trigger_pattern=form.get("trigger_pattern", "").strip() or None,
            response_text=form.get("response_text", "").strip() or None,
            embed_json=form.get("embed_json", "").strip() or None,
            enabled="enabled" in form,
            cooldown=cooldown,
            required_role_id=required_role_id,
            tts=tts,
            filter_has_link="filter_has_link" in form,
            filter_has_file="filter_has_file" in form,
            filter_has_emoji="filter_has_emoji" in form,
            filter_has_role_mention="filter_has_role_mention" in form,
            attachment_path=attachment_path,
            embed_image_path=embed_image_path,
            embed_thumbnail_path=embed_thumbnail_path,
            use_regex=use_regex,
            trigger_patterns=trigger_patterns,
            reaction_emojis=reaction_emojis,
            auto_delete_seconds=auto_delete_seconds,
            delete_trigger=delete_trigger,
            mod_action=mod_action,
            mod_action_value=mod_action_value,
            response_image_url=response_image_url,
            priority=priority,
            no_prefix=no_prefix,
            match_mode=match_mode,
        )
        await _refresh_cog_cache()
        await flash("Command created.", "success")
        return redirect(url_for("commands.command_list"))

    return await render_template("command_form.html", command=None, guilds=guilds)


@commands_bp.route("/<int:cmd_id>/edit", methods=["GET", "POST"])
@login_required
async def command_edit(cmd_id: int):
    command = await db.get_command(cmd_id)
    if not command:
        await flash("Command not found.", "danger")
        return redirect(url_for("commands.command_list"))

    bot = current_app.bot
    guilds = bot.guilds if bot else []

    if request.method == "POST":
        form = await request.form
        files = await request.files
        guild_id = form.get("guild_id") or None
        cooldown = int(form.get("cooldown", 0) or 0)
        required_role_id = form.get("required_role_id", "").strip() or None
        tts = "tts" in form

        # Handle file uploads — keep existing if no new upload, clear if requested
        attachment_path = command.get("attachment_path")
        if form.get("clear_attachment"):
            attachment_path = None
        new_att = _save_upload(files.get("attachment_file"))
        if new_att:
            attachment_path = new_att

        embed_image_path = command.get("embed_image_path")
        if form.get("clear_embed_image"):
            embed_image_path = None
        new_img = _save_upload(files.get("embed_image_file"))
        if new_img:
            embed_image_path = new_img

        embed_thumbnail_path = command.get("embed_thumbnail_path")
        if form.get("clear_embed_thumbnail"):
            embed_thumbnail_path = None
        new_thumb = _save_upload(files.get("embed_thumbnail_file"))
        if new_thumb:
            embed_thumbnail_path = new_thumb

        # Parse new advanced auto-reply fields
        use_regex = "use_regex" in form
        trigger_patterns_raw = form.get("trigger_patterns", "").strip()
        trigger_patterns = json.dumps([p.strip() for p in trigger_patterns_raw.splitlines() if p.strip()]) if trigger_patterns_raw else None
        reaction_emojis_raw = form.get("reaction_emojis", "").strip()
        reaction_emojis = json.dumps([e.strip() for e in reaction_emojis_raw.split(",") if e.strip()]) if reaction_emojis_raw else None
        auto_delete_seconds = int(form.get("auto_delete_seconds", 0) or 0)
        delete_trigger = "delete_trigger" in form
        mod_action = form.get("mod_action", "").strip() or None
        mod_action_value = form.get("mod_action_value", "").strip() or None
        response_image_url = form.get("response_image_url", "").strip() or None
        priority = int(form.get("priority", 0) or 0)
        no_prefix = "no_prefix" in form
        match_mode = form.get("match_mode", "contains") or "contains"

        await db.update_command(
            cmd_id,
            guild_id=guild_id,
            name=form["name"].strip(),
            type=form.get("type", "text"),
            trigger_pattern=form.get("trigger_pattern", "").strip() or None,
            response_text=form.get("response_text", "").strip() or None,
            embed_json=form.get("embed_json", "").strip() or None,
            enabled="enabled" in form,
            cooldown=cooldown,
            required_role_id=required_role_id,
            tts=tts,
            filter_has_link="filter_has_link" in form,
            filter_has_file="filter_has_file" in form,
            filter_has_emoji="filter_has_emoji" in form,
            filter_has_role_mention="filter_has_role_mention" in form,
            attachment_path=attachment_path,
            embed_image_path=embed_image_path,
            embed_thumbnail_path=embed_thumbnail_path,
            use_regex=use_regex,
            trigger_patterns=trigger_patterns,
            reaction_emojis=reaction_emojis,
            auto_delete_seconds=auto_delete_seconds,
            delete_trigger=delete_trigger,
            mod_action=mod_action,
            mod_action_value=mod_action_value,
            response_image_url=response_image_url,
            priority=priority,
            no_prefix=no_prefix,
            match_mode=match_mode,
        )
        await _refresh_cog_cache()
        await flash("Command updated.", "success")
        return redirect(url_for("commands.command_list"))

    return await render_template("command_form.html", command=command, guilds=guilds)


@commands_bp.route("/<int:cmd_id>/delete", methods=["DELETE"])
@login_required
async def command_delete(cmd_id: int):
    await db.delete_command(cmd_id)
    await _refresh_cog_cache()
    return "", 200


@commands_bp.route("/stats")
@login_required
async def command_stats():
    all_commands = await db.get_commands()
    auto_types = {"auto_reply", "contains_link", "contains_file", "contains_emoji", "contains_role_mention"}
    stats_commands = [c for c in all_commands if c["type"] in auto_types]
    stats_commands.sort(key=lambda c: c.get("usage_count", 0), reverse=True)
    return await render_template("command_stats.html", commands=stats_commands)


async def _refresh_cog_cache():
    """Tell the custom_commands cog to reload its cache."""
    bot = current_app.bot
    if bot:
        cog = bot.get_cog("CustomCommands")
        if cog:
            await cog.refresh_cache()
