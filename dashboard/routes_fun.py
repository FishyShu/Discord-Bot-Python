from __future__ import annotations

import json

import discord
from quart import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .auth import login_required
from . import db

fun_bp = Blueprint("fun", __name__)

FUN_COMMANDS = [
    {"name": "meme",   "description": "Fetch a random meme from Reddit"},
    {"name": "animal", "description": "Fetch a cute animal image"},
    {"name": "8ball",  "description": "Ask the magic 8-ball a question"},
    {"name": "mock",   "description": "Spongebob-mock someone's text"},
    {"name": "avatar", "description": "Show a user's avatar"},
    {"name": "ship",   "description": "Calculate love compatibility between two users"},
    {"name": "echo",   "description": "Send a message as another user via webhook"},
]

_DEFAULT_CFG = {"enabled": 1, "allowed_channels": "[]", "cooldown": 0, "allowed_roles": "[]"}


def _merge_configs(raw: dict[str, dict]) -> dict[str, dict]:
    """Return a config dict for every known command, filling defaults for unconfigured ones."""
    return {
        cmd["name"]: raw.get(cmd["name"], dict(_DEFAULT_CFG, command=cmd["name"]))
        for cmd in FUN_COMMANDS
    }


@fun_bp.route("/")
@login_required
async def fun_list():
    bot = current_app.bot
    guilds = sorted(bot.guilds, key=lambda g: g.name.lower()) if bot else []
    # Count disabled commands per guild from DB
    disabled_counts: dict[int, int] = {}
    for g in guilds:
        cfg = await db.get_fun_guild_config(str(g.id))
        disabled_counts[g.id] = sum(1 for c in cfg.values() if not c.get("enabled", 1))
    return await render_template("fun.html", guilds=guilds, disabled_counts=disabled_counts,
                                 total=len(FUN_COMMANDS))


@fun_bp.route("/<int:guild_id>")
@login_required
async def fun_guild(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("fun.fun_list"))

    raw = await db.get_fun_guild_config(str(guild_id))
    configs = _merge_configs(raw)

    # Text channels and roles for restriction pickers
    channels = sorted(
        [c for c in guild.channels if isinstance(c, discord.TextChannel)],
        key=lambda c: c.name,
    )
    roles = sorted(
        [r for r in guild.roles if not r.is_default()],
        key=lambda r: r.name,
    )

    return await render_template(
        "fun_guild.html",
        guild=guild,
        configs=configs,
        commands=FUN_COMMANDS,
        channels=channels,
        roles=roles,
    )


@fun_bp.route("/<int:guild_id>/save/<command>", methods=["POST"])
@login_required
async def fun_save(guild_id: int, command: str):
    if command not in {c["name"] for c in FUN_COMMANDS}:
        await flash("Unknown command.", "danger")
        return redirect(url_for("fun.fun_guild", guild_id=guild_id))

    form = await request.form
    enabled = 1 if form.get("enabled") else 0
    try:
        cooldown = max(0, int(form.get("cooldown", 0)))
    except ValueError:
        cooldown = 0

    allowed_channels = json.dumps(form.getlist("allowed_channels"))
    allowed_roles = json.dumps(form.getlist("allowed_roles"))

    await db.upsert_fun_command_config(
        str(guild_id), command,
        enabled=enabled,
        cooldown=cooldown,
        allowed_channels=allowed_channels,
        allowed_roles=allowed_roles,
    )
    await flash(f"/{command} settings saved.", "success")
    return redirect(url_for("fun.fun_guild", guild_id=guild_id))
