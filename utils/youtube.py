from __future__ import annotations

import asyncio
import functools
import logging
import os
import re
import tempfile
from typing import Optional

import yt_dlp

log = logging.getLogger(__name__)

YDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "extract_flat": False,
    "geo_bypass": True,
    "ignoreerrors": True,
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


def _extract(query: str, *, search: bool = False) -> dict | list[dict] | None:
    """Blocking yt-dlp extraction. Run in executor."""
    opts = {**YDL_OPTIONS}
    if search:
        # Explicitly prefix with ytsearch5: so yt-dlp doesn't misinterpret
        # non-Latin characters as extractor patterns.
        opts["default_search"] = "ytsearch5"
        opts["extract_flat"] = "in_playlist"
        if not query.startswith(("http://", "https://", "ytsearch")):
            query = f"ytsearch5:{query}"

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(query, download=False)
            if info is None:
                return None
            if "entries" in info:
                entries = [e for e in info["entries"] if e is not None]
                if search:
                    return entries
                return entries[0] if entries else None
            return info
    except Exception as e:
        log.debug("yt-dlp failed for %s: %s", query, e)
        return None


async def extract_info(query: str) -> Optional[dict]:
    """Extract info for a single URL or search query. Returns dict with title, url, duration, thumbnail."""
    loop = asyncio.get_running_loop()
    try:
        info = await asyncio.wait_for(
            loop.run_in_executor(None, functools.partial(_extract, query)),
            timeout=30,
        )
    except asyncio.TimeoutError:
        return None
    if info is None:
        return None
    if isinstance(info, list):
        return info[0] if info else None
    return info


async def search_youtube(query: str, count: int = 5) -> list[dict]:
    """Search YouTube and return up to `count` results."""
    loop = asyncio.get_running_loop()
    try:
        results = await asyncio.wait_for(
            loop.run_in_executor(None, functools.partial(_extract, query, search=True)),
            timeout=30,
        )
    except asyncio.TimeoutError:
        return []
    if results is None:
        return []
    if isinstance(results, dict):
        return [results]
    return results[:count]


async def get_stream_url(url: str) -> Optional[str]:
    """Get a fresh stream URL for playback. Called right before playing."""
    loop = asyncio.get_running_loop()
    opts = {**YDL_OPTIONS, "extract_flat": False, "ignoreerrors": True}

    # For ytsearch queries, request multiple results so we can fall back
    # if the first result is unavailable
    is_search = url.startswith("ytsearch:")
    if is_search:
        search_query = url.replace("ytsearch:", "ytsearch3:", 1)
    else:
        search_query = url

    def _get():
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(search_query, download=False)
                if info is None:
                    return None
                if info.get("url"):
                    return info["url"]
                if "entries" in info:
                    for entry in info["entries"]:
                        if entry is not None and entry.get("url"):
                            return entry["url"]
                return None
        except Exception as e:
            log.debug("yt-dlp failed for %s: %s", search_query, e)
            return None

    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _get),
            timeout=30,
        )
    except asyncio.TimeoutError:
        return None


def _sanitize_filename(name: str) -> str:
    """Remove characters that are unsafe for filenames."""
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    return name.strip()[:100] or "audio"


def _download(url: str, *, audio_only: bool = True) -> tuple[str, str] | None:
    """Blocking download. Returns (file_path, filename) or None."""
    tmpdir = tempfile.mkdtemp(prefix="dlbot_")
    opts = {
        **YDL_OPTIONS,
        "outtmpl": f"{tmpdir}/%(title)s.%(ext)s",
    }
    if audio_only:
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
        target_ext = ".mp3"
    else:
        opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
        opts["merge_output_format"] = "mp4"
        target_ext = ".mp4"

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                return None
            if "entries" in info:
                entries = [e for e in info["entries"] if e is not None]
                info = entries[0] if entries else None
            if info is None:
                return None
            title = info.get("title", "download")
            safe_title = _sanitize_filename(title)
            for f in os.listdir(tmpdir):
                if f.endswith(target_ext):
                    return os.path.join(tmpdir, f), f"{safe_title}{target_ext}"
            return None
    except Exception as e:
        log.debug("yt-dlp failed for %s: %s", url, e)
        return None


async def download_media(url: str, *, audio_only: bool = True) -> tuple[str, str] | None:
    """Download media from a URL. Returns (file_path, filename) or None.

    The caller is responsible for cleaning up the parent temp directory.
    """
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, functools.partial(_download, url, audio_only=audio_only)),
            timeout=120,
        )
    except asyncio.TimeoutError:
        return None


def is_youtube_playlist(url: str) -> bool:
    return ("youtube.com" in url or "youtu.be" in url) and (
        "list=" in url or "/playlist" in url
    )


async def extract_playlist(url: str) -> list[dict]:
    opts = {**YDL_OPTIONS, "noplaylist": False, "extract_flat": "in_playlist"}

    def _get():
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info is None:
                    return []
                return [e for e in info.get("entries", []) if e is not None]
        except Exception as e:
            log.debug("yt-dlp failed for %s: %s", url, e)
            return []

    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(loop.run_in_executor(None, _get), timeout=60)
    except asyncio.TimeoutError:
        return []


# Backwards-compatible alias
download_audio = functools.partial(download_media, audio_only=True)
