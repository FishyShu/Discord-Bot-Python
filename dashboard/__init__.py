from __future__ import annotations

import json
import logging
import os
import platform
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

import discord
from quart import Quart, jsonify, request, send_from_directory

log = logging.getLogger(__name__)


def create_app(bot=None) -> Quart:
    app = Quart(
        __name__,
        static_folder="static",
        template_folder="templates",
    )
    secret = os.getenv("DASHBOARD_SECRET", "change-me-in-production")
    if secret in ("change-me-in-production", "change-me-to-a-random-string"):
        if os.getenv("ALLOW_DEFAULT_SECRETS", "0") != "1":
            log.error(
                "DASHBOARD_SECRET is set to a default value. "
                "Set a secure random string in .env or set ALLOW_DEFAULT_SECRETS=1 for development."
            )
            raise SystemExit(1)
        log.warning("DASHBOARD_SECRET is set to the default value. Change it in production!")
    app.secret_key = secret
    app.permanent_session_lifetime = timedelta(hours=24)
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.jinja_env.auto_reload = True

    def _from_json_or_empty(value):
        if not value:
            return []
        try:
            result = json.loads(value)
            return result if isinstance(result, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    app.jinja_env.filters["from_json_or_empty"] = _from_json_or_empty
    app.bot = bot
    app.bot_start_time = datetime.now(timezone.utc)

    # File upload config
    upload_dir = Path(__file__).resolve().parent.parent / "data" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    app.config["UPLOAD_DIR"] = str(upload_dir)
    app.config["ALLOWED_EXTENSIONS"] = {"png", "jpg", "jpeg", "gif", "webp", "txt", "pdf"}
    app.config["MAX_UPLOAD_SIZE"] = 8 * 1024 * 1024  # 8 MB

    from .auth import auth_bp
    from .routes_commands import commands_bp
    from .routes_settings import settings_bp
    from .routes_servers import servers_bp
    from .routes_welcome import welcome_bp
    from .routes_audit import audit_bp
    from .routes_reaction_roles import reaction_roles_bp
    from .routes_leveling import leveling_bp
    from .routes_utility import utility_bp
    from .routes_music import music_bp
    from .routes_tts import tts_bp
    from .routes_autorole import autorole_bp
    from .routes_freestuff import freestuff_bp
    from .routes_streaming import streaming_bp
    from .routes_twitch_drops import twitch_drops_bp
    from .routes_moderation import moderation_bp
    from .routes_antiraid import antiraid_bp
    from .routes_giveaways import giveaways_bp
    from .routes_backup import backup_bp
    from .routes_ai import ai_bp
    from .routes_soundboard import soundboard_bp

    # Dashboard overview blueprint (inline — small)
    from quart import Blueprint, redirect, render_template, url_for
    from .auth import login_required
    from . import db as _db

    dashboard_bp = Blueprint("dashboard", __name__)

    @dashboard_bp.route("/")
    @login_required
    async def overview():
        bot = app.bot
        guild_count = len(bot.guilds) if bot else 0
        member_count = sum(g.member_count or 0 for g in bot.guilds) if bot else 0
        uptime = datetime.now(timezone.utc) - app.bot_start_time

        # Count active voice connections
        active_players = 0
        if bot:
            for guild in bot.guilds:
                if guild.voice_client and guild.voice_client.is_playing():
                    active_players += 1

        total_seconds = int(uptime.total_seconds())
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        if days > 0:
            uptime_str = f"{days}d {hours}h {minutes}m"
        else:
            uptime_str = f"{hours}h {minutes}m {seconds}s"

        # Count feature configs
        counts = await _db.count_feature_configs()

        # Bot health
        latency_ms = round(bot.latency * 1000) if bot else 0
        python_version = sys.version.split()[0]
        dpy_version = discord.__version__
        cog_count = len(bot.cogs) if bot else 0

        # Feature status per guild
        feature_status = await _db.get_feature_status_summary()
        guilds = sorted(bot.guilds, key=lambda g: g.name.lower()) if bot else []

        return await render_template(
            "dashboard.html",
            guild_count=guild_count,
            member_count=member_count,
            active_players=active_players,
            uptime=uptime_str,
            counts=counts,
            latency_ms=latency_ms,
            python_version=python_version,
            dpy_version=dpy_version,
            cog_count=cog_count,
            feature_status=feature_status,
            guilds=guilds,
            bot_name=str(bot.user) if bot and bot.user else "Bot",
            bot_avatar=bot.user.display_avatar.url if bot and bot.user else "",
        )

    @dashboard_bp.route("/restart", methods=["POST"])
    @login_required
    async def restart():
        log.info("Restart requested from dashboard")
        # Respond before restarting so the user sees the redirect
        import asyncio

        async def _do_restart():
            await asyncio.sleep(1)
            os.execv(sys.executable, [sys.executable] + sys.argv)

        asyncio.get_event_loop().create_task(_do_restart())
        from quart import flash as _flash
        await _flash("Bot is restarting...", "success")
        return redirect(url_for("dashboard.overview"))

    @app.context_processor
    async def inject_bot_info():
        from bot import BOT_VERSION
        b = app.bot
        return {
            "bot_name": str(b.user) if b and b.user else "Music Bot",
            "bot_avatar": b.user.display_avatar.url if b and b.user else "",
            "bot_version": BOT_VERSION,
        }

    @app.route("/health")
    @login_required
    async def health():
        b = app.bot
        return jsonify({
            "status": "ok",
            "bot_connected": b is not None and b.is_ready(),
            "guilds": len(b.guilds) if b else 0,
        })

    # CSRF protection: inject token into templates, validate on POST
    from .utils import generate_csrf_token, validate_csrf

    @app.context_processor
    async def inject_csrf_token():
        return {"csrf_token": generate_csrf_token}

    @app.before_request
    async def _csrf_protect():
        if request.method == "POST":
            # Skip CSRF for login (no session yet)
            if request.endpoint == "auth.login":
                return
            await validate_csrf()

    @app.after_request
    async def set_security_headers(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' https://cdn.discordapp.com data:; "
            "frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    @app.route("/uploads/<filename>")
    @login_required
    async def uploaded_file(filename):
        return await send_from_directory(app.config["UPLOAD_DIR"], filename)

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(commands_bp, url_prefix="/commands")
    app.register_blueprint(settings_bp, url_prefix="/settings")
    app.register_blueprint(servers_bp, url_prefix="/servers")
    app.register_blueprint(welcome_bp, url_prefix="/welcome")
    app.register_blueprint(audit_bp, url_prefix="/audit")
    app.register_blueprint(reaction_roles_bp, url_prefix="/reaction-roles")
    app.register_blueprint(leveling_bp, url_prefix="/leveling")
    app.register_blueprint(utility_bp, url_prefix="/utility")
    app.register_blueprint(music_bp, url_prefix="/music")
    app.register_blueprint(tts_bp, url_prefix="/tts")
    app.register_blueprint(autorole_bp, url_prefix="/autorole")
    app.register_blueprint(freestuff_bp, url_prefix="/freestuff")
    app.register_blueprint(streaming_bp, url_prefix="/streaming")
    app.register_blueprint(twitch_drops_bp, url_prefix="/twitch-drops")
    app.register_blueprint(moderation_bp, url_prefix="/moderation")
    app.register_blueprint(antiraid_bp, url_prefix="/antiraid")
    app.register_blueprint(giveaways_bp, url_prefix="/giveaways")
    app.register_blueprint(backup_bp, url_prefix="/backup")
    app.register_blueprint(ai_bp, url_prefix="/ai")
    app.register_blueprint(soundboard_bp, url_prefix="/soundboard")

    return app
