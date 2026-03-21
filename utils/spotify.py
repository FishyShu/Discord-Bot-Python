from __future__ import annotations

import json
import logging
import os
import re
import threading
import urllib.request
import urllib.parse
from typing import Optional

import spotipy
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyClientCredentials

log = logging.getLogger(__name__)

# Spotify URL patterns
TRACK_RE = re.compile(r"open\.spotify\.com/track/([a-zA-Z0-9]+)")
PLAYLIST_RE = re.compile(r"open\.spotify\.com/playlist/([a-zA-Z0-9]+)")
ALBUM_RE = re.compile(r"open\.spotify\.com/album/([a-zA-Z0-9]+)")

_client: Optional[spotipy.Spotify] = None
_client_lock = threading.Lock()


def _reset_client() -> None:
    """Force re-creation of the Spotify client on next use."""
    global _client
    with _client_lock:
        _client = None


def get_client() -> Optional[spotipy.Spotify]:
    """Lazy-init Spotify client. Returns None if credentials aren't set."""
    global _client
    if _client is not None:
        return _client

    with _client_lock:
        if _client is not None:
            return _client

        client_id = os.getenv("SPOTIFY_CLIENT_ID")
        client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
        if not client_id or not client_secret:
            return None

        _client = spotipy.Spotify(
            auth_manager=SpotifyClientCredentials(
                client_id=client_id, client_secret=client_secret
            )
        )
        return _client


def is_spotify_url(url: str) -> bool:
    return "open.spotify.com" in url


def _track_to_query(track: dict) -> str:
    """Convert a Spotify track dict to a YouTube search query."""
    name = track["name"]
    artists = " ".join(a["name"] for a in track["artists"])
    return f"{name} {artists}"


def _embed_fallback(url: str) -> list[dict]:
    """Fallback: scrape Spotify's embed page for track data (no credentials needed).

    Works for tracks, playlists, and albums by extracting __NEXT_DATA__ JSON.
    """
    # Determine embed URL from the original URL
    track_match = TRACK_RE.search(url)
    playlist_match = PLAYLIST_RE.search(url)
    album_match = ALBUM_RE.search(url)

    if track_match:
        embed_url = f"https://open.spotify.com/embed/track/{track_match.group(1)}"
    elif playlist_match:
        embed_url = f"https://open.spotify.com/embed/playlist/{playlist_match.group(1)}"
    elif album_match:
        embed_url = f"https://open.spotify.com/embed/album/{album_match.group(1)}"
    else:
        return []

    try:
        req = urllib.request.Request(embed_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8")

        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            html, re.DOTALL,
        )
        if not match:
            log.debug("No __NEXT_DATA__ found in embed page for %s", url)
            return _oembed_fallback(url)

        data = json.loads(match.group(1))
        entity = data["props"]["pageProps"]["state"]["data"]["entity"]
        track_list = entity.get("trackList", [])

        if not track_list:
            # Single track page may have the entity itself
            title = entity.get("title", "")
            subtitle = entity.get("subtitle", "")
            if title:
                full = f"{title} - {subtitle}" if subtitle else title
                query = f"{title} {subtitle}" if subtitle else title
                duration = entity.get("duration")
                return [{"query": query, "title": full,
                         "duration": duration // 1000 if duration else None}]
            return _oembed_fallback(url)

        results = []
        for track in track_list:
            if not track.get("isPlayable", True):
                continue
            title = track.get("title", "")
            subtitle = track.get("subtitle", "")
            if not title:
                continue
            full = f"{title} - {subtitle}" if subtitle else title
            query = f"{title} {subtitle}" if subtitle else title
            duration = track.get("duration")
            results.append({
                "query": query,
                "title": full,
                "duration": duration // 1000 if duration else None,
            })
        return results

    except Exception:
        log.debug("Embed fallback failed for %s, trying oEmbed", url, exc_info=True)
        return _oembed_fallback(url)


def _oembed_fallback(url: str) -> list[dict]:
    """Last-resort fallback: use Spotify's oEmbed API (no credentials needed).

    Returns only a single entry with the title (no per-track breakdown).
    """
    try:
        oembed_url = f"https://open.spotify.com/oembed?url={urllib.parse.quote(url, safe='')}"
        req = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        title = data.get("title", "")
        if not title:
            return []
        return [{"query": title, "title": title, "duration": None}]
    except Exception:
        log.debug("oEmbed fallback also failed for %s", url)
        return []


def get_tracks_from_url(url: str) -> list[dict]:
    """
    Parse a Spotify URL and return list of dicts with 'query', 'title', 'duration'.
    Supports tracks, playlists, and albums.
    Falls back to oEmbed API if credentials fail.
    """
    sp = get_client()
    if sp is None:
        # No credentials configured — try oEmbed
        return _embed_fallback(url)

    try:
        track_match = TRACK_RE.search(url)
        if track_match:
            track = sp.track(track_match.group(1))
            return [
                {
                    "query": _track_to_query(track),
                    "title": f"{track['name']} - {', '.join(a['name'] for a in track['artists'])}",
                    "duration": track["duration_ms"] // 1000,
                }
            ]

        playlist_match = PLAYLIST_RE.search(url)
        if playlist_match:
            results = []
            playlist = sp.playlist_tracks(playlist_match.group(1))
            while True:
                for item in playlist["items"]:
                    track = item.get("track")
                    if track:
                        results.append(
                            {
                                "query": _track_to_query(track),
                                "title": f"{track['name']} - {', '.join(a['name'] for a in track['artists'])}",
                                "duration": track["duration_ms"] // 1000,
                            }
                        )
                if playlist["next"]:
                    playlist = sp.next(playlist)
                else:
                    break
            return results

        album_match = ALBUM_RE.search(url)
        if album_match:
            results = []
            album = sp.album_tracks(album_match.group(1))
            for track in album["items"]:
                results.append(
                    {
                        "query": _track_to_query(track),
                        "title": f"{track['name']} - {', '.join(a['name'] for a in track['artists'])}",
                        "duration": track["duration_ms"] // 1000,
                    }
                )
            return results
    except SpotifyException as exc:
        log.warning("Spotify API error %s for URL %s: %s", exc.http_status, url, exc.msg)
        if exc.http_status in (401, 403):
            _reset_client()
            log.info("Reset Spotify client due to %s, falling back to oEmbed", exc.http_status)
        return _embed_fallback(url)
    except Exception:
        log.warning("Failed to get tracks from Spotify URL: %s", url, exc_info=True)
        return _embed_fallback(url)

    return []
