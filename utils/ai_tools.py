from __future__ import annotations

import logging
import os
import urllib.parse
from typing import Optional

import aiohttp

log = logging.getLogger(__name__)

FAL_API_KEY = os.getenv("FAL_API_KEY")

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


async def generate_image_fal(prompt: str) -> Optional[str]:
    """
    Generate an image via fal.ai flux/schnell and return the image URL.
    Falls back to Pollinations.ai if FAL_API_KEY is not set.
    """
    if not FAL_API_KEY:
        return _pollinations_url(prompt)

    try:
        headers = {
            "Authorization": f"Key {FAL_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "prompt": prompt,
            "image_size": "landscape_4_3",
            "num_images": 1,
        }
        async with aiohttp.ClientSession() as session:
            # Submit job
            async with session.post(
                "https://queue.fal.run/fal-ai/flux/schnell",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status not in (200, 201, 202):
                    return _pollinations_url(prompt)
                submit_data = await resp.json()

            request_id = submit_data.get("request_id")
            if not request_id:
                return _pollinations_url(prompt)

            # Poll for result (up to 30s)
            import asyncio
            for _ in range(15):
                await asyncio.sleep(2)
                async with session.get(
                    f"https://queue.fal.run/fal-ai/flux/schnell/requests/{request_id}",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as poll:
                    result = await poll.json()
                    if result.get("status") == "COMPLETED":
                        images = result.get("response", {}).get("images", [])
                        if images:
                            return images[0].get("url")
                    elif result.get("status") in ("FAILED", "CANCELLED"):
                        break

        return _pollinations_url(prompt)
    except Exception as e:
        log.warning("fal.ai image generation failed: %s", e)
        return _pollinations_url(prompt)


def _pollinations_url(prompt: str) -> str:
    """Fallback: Pollinations.ai image URL (no API key required)."""
    encoded = urllib.parse.quote(prompt)
    return f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true"
