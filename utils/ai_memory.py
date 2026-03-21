from __future__ import annotations

import time
import logging
from typing import Optional
from collections import defaultdict

from utils.ai_db import get_user_memory, upsert_user_memory

log = logging.getLogger(__name__)

MAX_MESSAGES = 20          # per conversation key
EVICT_AFTER_SECONDS = 3600  # 1 hour
SUMMARIZE_EVERY = 10       # turns before updating long-term memory


class ConversationMemory:
    """
    Manages short-term (in-memory) and long-term (SQLite) conversation history.

    Key format: "{server_id}:{user_id}"  or  "dm:{user_id}"
    """

    def __init__(self) -> None:
        # {key: [{"role": str, "content": str, "ts": float}]}
        self._history: dict[str, list[dict]] = defaultdict(list)
        # {key: int} — turn counter for triggering long-term summarization
        self._turn_counts: dict[str, int] = defaultdict(int)

    def _make_key(self, server_id: Optional[str], user_id: str) -> str:
        if server_id is None:
            return f"dm:{user_id}"
        return f"{server_id}:{user_id}"

    def _evict_old(self, key: str) -> None:
        now = time.monotonic()
        self._history[key] = [
            m for m in self._history[key]
            if now - m["ts"] < EVICT_AFTER_SECONDS
        ]

    def get(self, server_id: Optional[str], user_id: str) -> list[dict]:
        """Return the short-term history as a list of {role, content} dicts."""
        key = self._make_key(server_id, user_id)
        self._evict_old(key)
        return [{"role": m["role"], "content": m["content"]} for m in self._history[key]]

    def add(self, server_id: Optional[str], user_id: str, role: str, content: str) -> None:
        """Append a message to short-term history."""
        key = self._make_key(server_id, user_id)
        self._evict_old(key)
        self._history[key].append({"role": role, "content": content, "ts": time.monotonic()})
        # Enforce max length
        if len(self._history[key]) > MAX_MESSAGES:
            self._history[key] = self._history[key][-MAX_MESSAGES:]
        self._turn_counts[key] += 1

    def should_summarize(self, server_id: Optional[str], user_id: str) -> bool:
        """Return True every SUMMARIZE_EVERY turns."""
        key = self._make_key(server_id, user_id)
        return self._turn_counts[key] > 0 and self._turn_counts[key] % SUMMARIZE_EVERY == 0

    def clear(self, server_id: Optional[str], user_id: str) -> None:
        key = self._make_key(server_id, user_id)
        self._history.pop(key, None)
        self._turn_counts.pop(key, None)

    async def update_long_term_memory(
        self,
        server_id: Optional[str],
        user_id: str,
        ai_summary: str,
    ) -> None:
        """Persist an AI-generated summary of the conversation as long-term memory."""
        await upsert_user_memory(user_id, server_id, ai_summary)

    async def get_long_term_memory(
        self,
        server_id: Optional[str],
        user_id: str,
    ) -> Optional[str]:
        return await get_user_memory(user_id, server_id)


# Shared singleton
conversation_memory = ConversationMemory()
