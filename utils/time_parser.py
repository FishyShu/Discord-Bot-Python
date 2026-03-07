"""Parse human-readable duration strings like '10m', '1h30m', '2d' into seconds."""

from __future__ import annotations

import re

_PATTERN = re.compile(r"(\d+)\s*([dhms])", re.IGNORECASE)

_MULTIPLIERS = {
    "d": 86400,
    "h": 3600,
    "m": 60,
    "s": 1,
}


def parse_duration(text: str) -> int | None:
    """Return total seconds for a duration string, or None if unparseable.

    Examples:
        '10m'    -> 600
        '1h30m'  -> 5400
        '2d'     -> 172800
        '90s'    -> 90
    """
    matches = _PATTERN.findall(text)
    if not matches:
        return None
    total = 0
    for amount, unit in matches:
        total += int(amount) * _MULTIPLIERS[unit.lower()]
    return total


def format_duration(seconds: int) -> str:
    """Format seconds into a human-readable string like '1h 30m'."""
    parts = []
    for unit, mult in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if seconds >= mult:
            val, seconds = divmod(seconds, mult)
            parts.append(f"{val}{unit}")
    return " ".join(parts) or "0s"
