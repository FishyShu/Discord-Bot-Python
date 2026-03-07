from __future__ import annotations

import functools
import logging
import os
import time

from quart import Blueprint, redirect, render_template, request, session, url_for

log = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "admin")
if DASHBOARD_PASSWORD == "admin":
    log.warning("DASHBOARD_PASSWORD is set to the default 'admin'. Change it in production!")

# Rate limiting: {ip: [timestamps]}
_login_attempts: dict[str, list[float]] = {}
_RATE_LIMIT_MAX = 5
_RATE_LIMIT_WINDOW = 300  # 5 minutes


def login_required(func):
    """Decorator that redirects to login if the user is not authenticated."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("auth.login"))
        return await func(*args, **kwargs)
    return wrapper


@auth_bp.route("/login", methods=["GET", "POST"])
async def login():
    error = None
    if request.method == "POST":
        ip = request.remote_addr or "unknown"
        now = time.time()

        # Prune stale IPs to prevent memory leak
        stale_ips = [k for k, v in _login_attempts.items() if not v or now - v[-1] > _RATE_LIMIT_WINDOW]
        for k in stale_ips:
            del _login_attempts[k]

        # Rate limiting
        attempts = _login_attempts.get(ip, [])
        attempts = [t for t in attempts if now - t < _RATE_LIMIT_WINDOW]
        _login_attempts[ip] = attempts

        if len(attempts) >= _RATE_LIMIT_MAX:
            error = "Too many attempts. Please try again later."
            return await render_template("login.html", error=error)

        form = await request.form
        password = form.get("password", "")
        if password == DASHBOARD_PASSWORD:
            session["authenticated"] = True
            session.permanent = True
            return redirect(url_for("dashboard.overview"))
        attempts.append(now)
        _login_attempts[ip] = attempts
        error = "Invalid password."
    return await render_template("login.html", error=error)


@auth_bp.route("/logout", methods=["POST"])
async def logout():
    session.clear()
    return redirect(url_for("auth.login"))
