from __future__ import annotations

import time
from collections import defaultdict


class RateLimiter:
    """Sliding-window per-user per-command rate limiter (in-memory, no Redis needed)."""

    def __init__(self) -> None:
        # key: "{user_id}:{command}" -> list of monotonic timestamps
        self._usage: dict[str, list[float]] = defaultdict(list)

    def is_limited(self, user_id: int, command: str, *, limit: int, window: int) -> bool:
        """Return True if the user has exceeded `limit` calls in the last `window` seconds."""
        key = f"{user_id}:{command}"
        now = time.monotonic()
        # Drop timestamps outside the window
        recent = [t for t in self._usage[key] if now - t < window]
        if len(recent) >= limit:
            self._usage[key] = recent
            return True
        recent.append(now)
        self._usage[key] = recent
        return False

    def reset(self, user_id: int, command: str) -> None:
        """Manually clear the bucket for a user/command."""
        self._usage.pop(f"{user_id}:{command}", None)


# Shared singleton — import and use directly in cogs
rate_limiter = RateLimiter()
