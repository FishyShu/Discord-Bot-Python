"""Shared dashboard utilities: CSRF protection, safe type conversions, file uploads."""
from __future__ import annotations

import os
import secrets
import uuid

from quart import abort, current_app, request, session


def _safe_int(value, default: int = 0) -> int:
    """Safely convert a value to int, returning default on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def generate_csrf_token() -> str:
    """Return (and cache in session) a CSRF token."""
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]


async def validate_csrf() -> None:
    """Validate the CSRF token on a POST request. Aborts 403 on mismatch."""
    form = await request.form
    token = form.get("_csrf_token", "")
    if not token or token != session.get("_csrf_token"):
        abort(403, "CSRF token missing or invalid.")


def _save_upload(file_storage) -> str | None:
    """Validate and save an uploaded file. Returns stored filename or None."""
    if not file_storage or not file_storage.filename:
        return None
    ext = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
    allowed = current_app.config["ALLOWED_EXTENSIONS"]
    if ext not in allowed:
        return None
    data = file_storage.read()
    if len(data) > current_app.config["MAX_UPLOAD_SIZE"]:
        return None
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(current_app.config["UPLOAD_DIR"], stored_name)
    with open(path, "wb") as f:
        f.write(data)
    return stored_name
