from __future__ import annotations

import json
import logging
import re
import urllib.request
from typing import Optional

import yt_dlp

log = logging.getLogger(__name__)

TIDAL_TRACK_RE    = re.compile(r"tidal\.com/(?:browse/)?track/(\d+)")
TIDAL_PLAYLIST_RE = re.compile(r"tidal\.com/(?:browse/)?playlist/([\w-]+)")
TIDAL_ALBUM_RE    = re.compile(r"tidal\.com/(?:browse/)?album/(\d+)")
TIDAL_MIX_RE      = re.compile(r"tidal\.com/(?:browse/)?mix/([\w]+)")


def is_tidal_url(url: str) -> bool:
    return "tidal.com" in url


def _ydlp_extract_tidal(url: str) -> list[dict]:
    """Try to extract Tidal content via yt-dlp. Returns list of track dicts."""
    opts = {"noplaylist": False, "quiet": True, "ignoreerrors": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                return []
            entries = info.get("entries") or [info]
            results = []
            for e in entries:
                if e is None:
                    continue
                title = e.get("title", "")
                artist = e.get("artist") or e.get("uploader") or ""
                query = f"{title} {artist}".strip() if artist else title
                if not query:
                    continue
                results.append({
                    "query": query,
                    "title": f"{title} - {artist}" if artist else title,
                    "duration": e.get("duration"),
                })
            return results
    except Exception:
        return []


def _scrape_tidal_embed(url: str) -> list[dict]:
    """Scrape Tidal embed pages for JSON-LD structured data."""
    track_match = TIDAL_TRACK_RE.search(url)
    album_match = TIDAL_ALBUM_RE.search(url)

    embed_urls: list[str] = []
    if track_match:
        embed_urls.append(f"https://embed.tidal.com/tracks/{track_match.group(1)}")
    elif album_match:
        embed_urls.append(f"https://embed.tidal.com/albums/{album_match.group(1)}")
    else:
        return []

    results = []
    for embed_url in embed_urls:
        try:
            req = urllib.request.Request(embed_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8")

            for match in re.finditer(
                r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL
            ):
                try:
                    data = json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue

                # Single MusicRecording
                if data.get("@type") == "MusicRecording":
                    title = data.get("name", "")
                    artist = ""
                    by_artist = data.get("byArtist")
                    if isinstance(by_artist, dict):
                        artist = by_artist.get("name", "")
                    elif isinstance(by_artist, list) and by_artist:
                        artist = by_artist[0].get("name", "")
                    query = f"{title} {artist}".strip() if artist else title
                    if query:
                        dur = data.get("duration")
                        results.append({
                            "query": query,
                            "title": f"{title} - {artist}" if artist else title,
                            "duration": _parse_iso_duration(dur),
                        })

                # MusicAlbum with tracks
                elif data.get("@type") == "MusicAlbum":
                    for track in data.get("track", []):
                        title = track.get("name", "")
                        artist = ""
                        by_artist = track.get("byArtist")
                        if isinstance(by_artist, dict):
                            artist = by_artist.get("name", "")
                        elif isinstance(by_artist, list) and by_artist:
                            artist = by_artist[0].get("name", "")
                        query = f"{title} {artist}".strip() if artist else title
                        if query:
                            dur = track.get("duration")
                            results.append({
                                "query": query,
                                "title": f"{title} - {artist}" if artist else title,
                                "duration": _parse_iso_duration(dur),
                            })

        except Exception:
            log.debug("Tidal embed scrape failed for %s", embed_url, exc_info=True)

    return results


def _parse_iso_duration(duration: Optional[str]) -> Optional[int]:
    """Parse ISO 8601 duration (e.g. PT3M45S) to seconds."""
    if not duration:
        return None
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not m:
        return None
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    seconds = int(m.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def get_tracks_from_tidal_url(url: str) -> list[dict]:
    """Blocking. Returns list of {"query", "title", "duration"}."""
    results = _ydlp_extract_tidal(url)
    if results:
        return results
    return _scrape_tidal_embed(url)
