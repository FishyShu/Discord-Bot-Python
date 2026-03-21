from __future__ import annotations

import json
import logging
import re

log = logging.getLogger(__name__)


def parse_blocklist(raw: str) -> list[str]:
    """Parse a JSON array string into a list of lowercase topic strings."""
    try:
        items = json.loads(raw or "[]")
        return [str(t).lower().strip() for t in items if t]
    except (json.JSONDecodeError, TypeError):
        return []


def is_blocked(content: str, blocklist: list[str]) -> bool:
    """
    Return True if the content contains any blocked topic.
    Uses whole-word matching to avoid false positives.
    """
    if not blocklist:
        return False
    lower = content.lower()
    for topic in blocklist:
        # Escape the topic and match as a word boundary where possible
        pattern = r'\b' + re.escape(topic) + r'\b'
        if re.search(pattern, lower):
            return True
    return False


def get_blocked_topic(content: str, blocklist: list[str]) -> str | None:
    """Return the first matched blocked topic, or None."""
    if not blocklist:
        return None
    lower = content.lower()
    for topic in blocklist:
        pattern = r'\b' + re.escape(topic) + r'\b'
        if re.search(pattern, lower):
            return topic
    return None
