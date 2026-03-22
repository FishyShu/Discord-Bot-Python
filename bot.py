import asyncio
import glob
import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

from utils.console import setup_logging, print_banner

setup_logging()
log = logging.getLogger("bot")

# Ensure ffmpeg is on PATH (winget installs it outside the default PATH)
_ffmpeg_matches = glob.glob(
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "ffmpeg*", "bin")
)
for _p in _ffmpeg_matches:
    if os.path.isfile(os.path.join(_p, "ffmpeg.exe")) and _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")
        break

# Refuse to start with default secrets unless explicitly allowed (dev mode)
_default_pw = os.getenv("DASHBOARD_PASSWORD", "") in ("change-me", "")
_allow_defaults = os.getenv("ALLOW_DEFAULT_SECRETS", "0") == "1"
if _default_pw and not _allow_defaults:
    log.error(
        "DASHBOARD_PASSWORD is set to a default or empty value. "
        "Set a secure password in .env, or set ALLOW_DEFAULT_SECRETS=1 for development."
    )
    raise SystemExit(1)

# HTTPS enforcement warning — dashboard runs plain HTTP; warn once when not in dev mode
if not _allow_defaults and os.getenv("_HTTPS_WARNED") != "1":
    os.environ["_HTTPS_WARNED"] = "1"
    log.warning(
        "SECURITY REMINDER: The dashboard runs over plain HTTP. "
        "In production, place it behind a reverse proxy with TLS (nginx, Caddy, Traefik). "
        "See deploy/ for setup guides."
    )

BOT_VERSION = "1.3.0"
print_banner(BOT_VERSION)


class MusicBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        from dashboard.db import init_db
        await init_db()

        cog_extensions = [
            "cogs.music", "cogs.custom_commands", "cogs.welcome",
            "cogs.audit_log", "cogs.utility", "cogs.reaction_roles",
            "cogs.leveling", "cogs.tts",
            "cogs.soundboard", "cogs.autorole",
            "cogs.freestuff", "cogs.streaming",
            "cogs.twitch_drops", "cogs.voice_separate",
            "cogs.moderation", "cogs.fun", "cogs.autotranslate",
            "cogs.giveaways", "cogs.antiraid", "cogs.backup",
            "cogs.ai",
        ]
        for ext in cog_extensions:
            try:
                await self.load_extension(ext)
            except Exception:
                log.exception("Failed to load extension %s", ext)

        if os.getenv("SYNC_COMMANDS", "0") == "1":
            synced = await self.tree.sync()
            log.info("Global sync: %d slash commands", len(synced))
        else:
            log.info("Skipping command sync (set SYNC_COMMANDS=1 to sync)")

    async def on_ready(self):
        from utils.console import BRIGHT_GREEN, BRIGHT_MAGENTA, BRIGHT_YELLOW, BRIGHT_CYAN, DIM, RESET, _sparkle
        log.info("%s%s%s logged in as %s%s%s (ID: %s)",
                 BRIGHT_MAGENTA, _sparkle(), RESET,
                 BRIGHT_GREEN, self.user, RESET, self.user.id)
        for guild in self.guilds:
            log.info("  %s❯%s %s%s%s %s(%s)%s",
                     BRIGHT_CYAN, RESET,
                     BRIGHT_YELLOW, guild.name, RESET,
                     DIM, guild.id, RESET)
        log.info("%s✦ Connected to %d server(s)%s", BRIGHT_GREEN, len(self.guilds), RESET)



async def run_dashboard(bot):
    """Start the Quart dashboard alongside the bot."""
    from hypercorn.asyncio import serve
    from hypercorn.config import Config
    from dashboard import create_app

    app = create_app(bot)
    config = Config()
    port = int(os.getenv("DASHBOARD_PORT", "5000"))
    config.bind = [f"0.0.0.0:{port}"]
    config.loglevel = "info"

    log.info("Dashboard starting on http://localhost:%d", port)
    await serve(app, config, shutdown_trigger=lambda: asyncio.Future())


async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        log.error("DISCORD_TOKEN not set in .env")
        return

    bot = MusicBot()

    async with bot:
        results = await asyncio.gather(
            bot.start(token),
            run_dashboard(bot),
            return_exceptions=True,
        )
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                name = "bot" if i == 0 else "dashboard"
                log.error("Task '%s' failed: %s", name, result)


if __name__ == "__main__":
    asyncio.run(main())
