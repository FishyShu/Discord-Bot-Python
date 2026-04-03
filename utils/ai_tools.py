from __future__ import annotations

import logging
import urllib.parse
from typing import Optional

import aiohttp

log = logging.getLogger(__name__)

# DuckDuckGo instant answer API (no key required)
DDG_URL = "https://api.duckduckgo.com/"


async def web_search(query: str, *, max_results: int = 3) -> str:
    """
    Perform a DuckDuckGo instant-answer search.
    Returns a brief text summary or an empty string on failure.
    """
    params = {
        "q": query,
        "format": "json",
        "no_html": "1",
        "skip_disambig": "1",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(DDG_URL, params=params, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return ""
                data = await resp.json(content_type=None)

        parts: list[str] = []

        # Abstract
        abstract = data.get("AbstractText", "").strip()
        if abstract:
            parts.append(abstract)

        # Related topics
        for topic in data.get("RelatedTopics", [])[:max_results]:
            text = topic.get("Text", "").strip()
            if text:
                parts.append(f"- {text}")

        return "\n".join(parts) if parts else ""
    except Exception as e:
        log.debug("Web search failed: %s", e)
        return ""


async def summarize_url(url: str) -> str:
    """
    Fetch the first ~2000 characters of text from a URL and return it as a
    plain-text snippet suitable for injecting into an AI prompt.
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; DiscordBot/1.0)"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return ""
                # Only process text/html responses
                ct = resp.headers.get("Content-Type", "")
                if "text" not in ct:
                    return ""
                raw = await resp.text(errors="replace")

        # Strip HTML tags with a simple regex
        import re
        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:2000]
    except Exception as e:
        log.debug("URL summarize failed for %s: %s", url, e)
        return ""


def generate_image(prompt: str, seed: Optional[int] = None) -> str:
    """Return a Pollinations.ai image URL for the given prompt (no API key required)."""
    encoded = urllib.parse.quote(prompt)
    seed_param = f"&seed={seed}" if seed is not None else ""
    return f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true{seed_param}"
