"""
Colourful console utilities — startup banner + sparkly log formatter.
"""
from __future__ import annotations

import logging
import random
import sys

# ANSI colour codes (work on Windows 10+ and most terminals)
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"

# Foreground colours
BLACK   = "\033[30m"
RED     = "\033[31m"
GREEN   = "\033[32m"
YELLOW  = "\033[33m"
BLUE    = "\033[34m"
MAGENTA = "\033[35m"
CYAN    = "\033[36m"
WHITE   = "\033[37m"

# Bright foreground
BRIGHT_RED     = "\033[91m"
BRIGHT_GREEN   = "\033[92m"
BRIGHT_YELLOW  = "\033[93m"
BRIGHT_BLUE    = "\033[94m"
BRIGHT_MAGENTA = "\033[95m"
BRIGHT_CYAN    = "\033[96m"
BRIGHT_WHITE   = "\033[97m"

# Background
BG_BLUE    = "\033[44m"
BG_MAGENTA = "\033[45m"
BG_CYAN    = "\033[46m"

SPARKLES = ["✨", "⭐", "🌟", "💫", "✦", "❇️", "🔮", "💎", "🌈"]

def _sparkle() -> str:
    return random.choice(SPARKLES)

def _gradient_line(text: str, colours: list[str]) -> str:
    """Apply a cycling colour gradient to each character of text."""
    out = []
    colour_chars = [c for c in text]
    for i, ch in enumerate(colour_chars):
        out.append(colours[i % len(colours)] + ch)
    out.append(RESET)
    return "".join(out)

_BANNER_GRADIENT = [BRIGHT_MAGENTA, BRIGHT_CYAN, BRIGHT_BLUE, BRIGHT_MAGENTA, BRIGHT_CYAN]

# Enable ANSI on Windows
def _enable_ansi():
    if sys.platform == "win32":
        import os, ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)

def print_banner(version: str):
    _enable_ansi()
    sp = _sparkle()
    lines = [
        f"",
        f"  {sp}  {_gradient_line('Tagokura Bot', _BANNER_GRADIENT)}  {sp}",
        f"  {BRIGHT_CYAN}{'─' * 34}{RESET}",
        f"  {DIM}Version{RESET}  {BRIGHT_YELLOW}{version}{RESET}",
        f"  {DIM}Discord{RESET}  {BRIGHT_BLUE}discord.py{RESET}",
        f"  {BRIGHT_CYAN}{'─' * 34}{RESET}",
        f"",
    ]
    for line in lines:
        print(line)

# ── Log formatter ────────────────────────────────────────────────────────────

_LEVEL_COLOURS = {
    "DEBUG":    DIM + WHITE,
    "INFO":     BRIGHT_CYAN,
    "WARNING":  BRIGHT_YELLOW,
    "ERROR":    BRIGHT_RED,
    "CRITICAL": BOLD + BRIGHT_RED,
}

_LEVEL_ICONS = {
    "DEBUG":    "·",
    "INFO":     "✦",
    "WARNING":  "⚠",
    "ERROR":    "✖",
    "CRITICAL": "💥",
}

class SparklyFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        lvl      = record.levelname
        colour   = _LEVEL_COLOURS.get(lvl, WHITE)
        icon     = _LEVEL_ICONS.get(lvl, " ")
        ts       = self.formatTime(record, "%H:%M:%S")
        name     = record.name[:20].ljust(20)
        message  = record.getMessage()
        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)

        return (
            f"{DIM}{ts}{RESET} "
            f"{colour}{icon} {lvl:<8}{RESET} "
            f"{BRIGHT_BLUE}{name}{RESET} "
            f"{message}"
        )

def print_shutdown():
    _enable_ansi()
    sp = _sparkle()
    lines = [
        f"",
        f"  {sp}  {_gradient_line('Shutting down…', _BANNER_GRADIENT)}  {sp}",
        f"  {BRIGHT_CYAN}{'─' * 34}{RESET}",
        f"  {DIM}Disconnecting from Discord{RESET}",
        f"  {DIM}Stopping dashboard{RESET}",
        f"  {BRIGHT_CYAN}{'─' * 34}{RESET}",
        f"  {BRIGHT_YELLOW}Goodbye! ✦{RESET}",
        f"",
    ]
    for line in lines:
        print(line)


def setup_logging(level: int = logging.INFO):
    _enable_ansi()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(SparklyFormatter())
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)
