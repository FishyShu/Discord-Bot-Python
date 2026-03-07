from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class LoopMode(Enum):
    OFF = "off"
    SINGLE = "single"
    QUEUE = "queue"


@dataclass
class TrackInfo:
    title: str
    url: str  # original URL or search query
    duration: Optional[int] = None  # seconds
    thumbnail: Optional[str] = None
    requester: Optional[str] = None
    stream_url: Optional[str] = None  # resolved lazily before playback

    @property
    def duration_str(self) -> str:
        if self.duration is None:
            return "Unknown"
        mins, secs = divmod(int(self.duration), 60)
        hours, mins = divmod(mins, 60)
        if hours:
            return f"{hours}:{mins:02d}:{secs:02d}"
        return f"{mins}:{secs:02d}"


class GuildMusicPlayer:
    """Per-guild music state: queue, volume, loop mode, current track."""

    def __init__(self):
        self.queue: list[TrackInfo] = []
        self.current: Optional[TrackInfo] = None
        self.volume: float = 0.5  # 0.0 – 1.0
        self.loop_mode: LoopMode = LoopMode.OFF
        self.text_channel = None  # for sending "now playing" messages
        self.now_playing_message: Optional[object] = None  # discord.Message
        self._idle_task: Optional[asyncio.Task] = None

    def add(self, track: TrackInfo):
        self.queue.append(track)

    def skip(self) -> Optional[TrackInfo]:
        """Advance to the next track based on loop mode. Returns the next track or None."""
        if self.loop_mode == LoopMode.SINGLE and self.current:
            return self.current
        if self.loop_mode == LoopMode.QUEUE and self.current:
            self.queue.append(self.current)
        if self.queue:
            self.current = self.queue.pop(0)
            return self.current
        self.current = None
        return None

    def shuffle(self):
        random.shuffle(self.queue)

    def remove(self, position: int) -> Optional[TrackInfo]:
        """Remove track at 1-based position. Returns removed track or None."""
        idx = position - 1
        if 0 <= idx < len(self.queue):
            return self.queue.pop(idx)
        return None

    def move(self, from_pos: int, to_pos: int) -> Optional[TrackInfo]:
        """Move a track from one 1-based position to another. Returns moved track or None."""
        fi, ti = from_pos - 1, to_pos - 1
        if not (0 <= fi < len(self.queue)) or not (0 <= ti < len(self.queue)):
            return None
        track = self.queue.pop(fi)
        self.queue.insert(ti, track)
        return track

    def clear(self):
        self.queue.clear()
        self.current = None

    def cancel_idle_timer(self):
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
            self._idle_task = None

    def start_idle_timer(self, coro):
        """Start a 5-minute idle timer that runs the given coroutine when expired."""
        self.cancel_idle_timer()
        self._idle_task = asyncio.create_task(coro)
