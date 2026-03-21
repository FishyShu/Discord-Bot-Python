import asyncio
import glob
import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

# Ensure ffmpeg is on PATH (winget installs it outside the default PATH)
_ffmpeg_matches = glob.glob(
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "ffmpeg*", "bin")
)
for _p in _ffmpeg_matches:
    if os.path.isfile(os.path.join(_p, "ffmpeg.exe")) and _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")
        break

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("bot")

BOT_VERSION = "1.2.0"


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
        ]
        for ext in cog_extensions:
            try:
                await self.load_extension(ext)
            except Exception:
                log.exception("Failed to load extension %s", ext)

        if os.getenv("SYNC_COMMANDS", "0") == "1":
            synced = await self.tree.sync()
            log.info("Synced %d slash commands", len(synced))
        else:
            log.info("Skipping command sync (set SYNC_COMMANDS=1 to sync)")

    async def on_ready(self):
        log.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        for guild in self.guilds:
            log.info("  - %s (ID: %s)", guild.name, guild.id)
        log.info("Connected to %d server(s)", len(self.guilds))


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
