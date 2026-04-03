from __future__ import annotations

import re
from pathlib import Path

from quart import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .auth import login_required
from . import db

soundboard_bp = Blueprint("soundboard", __name__)

_GLOBAL_SOUNDS_DIR = Path(__file__).resolve().parent.parent / "sounds"
SOUNDS_DIR = Path(__file__).resolve().parent.parent / "data" / "sounds"
ALLOWED_EXTENSIONS = {".mp3", ".wav", ".ogg"}


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _list_guild_sounds(guild_id: str) -> list[dict]:
    guild_dir = SOUNDS_DIR / guild_id
    if not guild_dir.is_dir():
        return []
    sounds = []
    for p in sorted(guild_dir.iterdir(), key=lambda x: x.stem.lower()):
        if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS:
            sounds.append({
                "name": p.stem,
                "filename": p.name,
                "size_human": _human_size(p.stat().st_size),
                "ext": p.suffix.lstrip(".").upper(),
            })
    return sounds


def _sound_count(guild_id: str) -> int:
    guild_dir = SOUNDS_DIR / str(guild_id)
    if not guild_dir.is_dir():
        return 0
    return sum(1 for p in guild_dir.iterdir()
               if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS)


@soundboard_bp.route("/")
@login_required
async def soundboard_list():
    bot = current_app.bot
    guilds = sorted(bot.guilds, key=lambda g: g.name.lower()) if bot else []
    sound_counts = {g.id: _sound_count(str(g.id)) for g in guilds}
    return await render_template("soundboard.html", guilds=guilds, sound_counts=sound_counts)


@soundboard_bp.route("/<int:guild_id>")
@login_required
async def soundboard_guild(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("soundboard.soundboard_list"))
    sounds = _list_guild_sounds(str(guild_id))
    cfg = await db.get_soundboard_config(str(guild_id)) or {"volume_mode": "off", "fixed_volume": 0.8}
    return await render_template("soundboard_guild.html", guild=guild, sounds=sounds, cfg=cfg)


@soundboard_bp.route("/<int:guild_id>/upload", methods=["POST"])
@login_required
async def soundboard_upload(guild_id: int):
    files = await request.files
    form = await request.form
    sound_file = files.get("sound_file")
    if not sound_file or not sound_file.filename:
        await flash("No file selected.", "danger")
        return redirect(url_for("soundboard.soundboard_guild", guild_id=guild_id))

    ext = Path(sound_file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        await flash(f"File type {ext} not allowed. Use .mp3, .wav, or .ogg.", "danger")
        return redirect(url_for("soundboard.soundboard_guild", guild_id=guild_id))

    raw_name = form.get("sound_name", "").strip() or Path(sound_file.filename).stem
    safe_name = re.sub(r"[^\w\-]", "_", raw_name)[:50]
    if not safe_name:
        safe_name = "sound"

    guild_dir = SOUNDS_DIR / str(guild_id)
    guild_dir.mkdir(parents=True, exist_ok=True)

    dest = (guild_dir / f"{safe_name}{ext}").resolve()
    if not str(dest).startswith(str(guild_dir.resolve())):
        await flash("Invalid filename.", "danger")
        return redirect(url_for("soundboard.soundboard_guild", guild_id=guild_id))

    await sound_file.save(dest)
    await flash(f"Uploaded {safe_name}{ext}.", "success")
    return redirect(url_for("soundboard.soundboard_guild", guild_id=guild_id))


@soundboard_bp.route("/<int:guild_id>/delete", methods=["POST"])
@login_required
async def soundboard_delete(guild_id: int):
    form = await request.form
    filename = form.get("filename", "")
    guild_dir = (SOUNDS_DIR / str(guild_id)).resolve()
    target = (guild_dir / filename).resolve()
    if not str(target).startswith(str(guild_dir)):
        await flash("Invalid filename.", "danger")
        return redirect(url_for("soundboard.soundboard_guild", guild_id=guild_id))
    if target.is_file():
        target.unlink()
        await flash(f"Deleted {filename}.", "success")
    else:
        await flash("File not found.", "danger")
    return redirect(url_for("soundboard.soundboard_guild", guild_id=guild_id))


@soundboard_bp.route("/<int:guild_id>/settings", methods=["POST"])
@login_required
async def soundboard_settings(guild_id: int):
    form = await request.form
    volume_mode = form.get("volume_mode", "off")
    if volume_mode not in ("off", "fixed"):
        volume_mode = "off"
    try:
        fixed_volume = float(form.get("fixed_volume", 0.8))
        fixed_volume = max(0.1, min(2.0, fixed_volume))
    except (ValueError, TypeError):
        fixed_volume = 0.8
    await db.upsert_soundboard_config(str(guild_id), volume_mode=volume_mode, fixed_volume=fixed_volume)
    await flash("Volume settings saved.", "success")
    return redirect(url_for("soundboard.soundboard_guild", guild_id=guild_id))
