from __future__ import annotations

import io
import logging
import os

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)

VOICE_STUDIO_URL = os.getenv("VOICE_STUDIO_URL", "http://localhost:8001")
MAX_UPLOAD_MB = 50  # Discord attachment size limit we enforce on input


class VoiceSeparate(commands.Cog):
    """Slash command to separate vocals from instrumentals using Voice Cover Studio."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="separate",
        description="Separate vocals and instrumentals from an audio file",
    )
    @app_commands.describe(
        audio="Audio file to separate (MP3, WAV, FLAC, OGG, M4A — max 50 MB)",
    )
    async def separate(self, interaction: discord.Interaction, audio: discord.Attachment):
        # Validate file type by extension
        allowed = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".webm", ".aac"}
        ext = os.path.splitext(audio.filename)[1].lower()
        if ext not in allowed:
            await interaction.response.send_message(
                f"Unsupported file type `{ext}`. Allowed: MP3, WAV, FLAC, OGG, M4A, AAC.",
                ephemeral=True,
            )
            return

        if audio.size > MAX_UPLOAD_MB * 1024 * 1024:
            await interaction.response.send_message(
                f"File is too large ({audio.size / 1024 / 1024:.1f} MB). Max is {MAX_UPLOAD_MB} MB.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)

        try:
            # Download the attachment
            async with aiohttp.ClientSession() as session:
                async with session.get(audio.url) as resp:
                    if resp.status != 200:
                        await interaction.followup.send("Failed to download your attachment.")
                        return
                    audio_bytes = await resp.read()

                # Upload to Voice Cover Studio and separate
                form = aiohttp.FormData()
                form.add_field(
                    "file",
                    audio_bytes,
                    filename=audio.filename,
                    content_type=audio.content_type or "audio/mpeg",
                )

                async with session.post(
                    f"{VOICE_STUDIO_URL}/api/separate",
                    data=form,
                    timeout=aiohttp.ClientTimeout(total=300),
                ) as resp:
                    if resp.status == 400:
                        body = await resp.json()
                        await interaction.followup.send(
                            f"Separation unavailable: {body.get('detail', 'unknown error')}.\n"
                            "Make sure the Voice Cover Studio backend is running with `audio-separator` installed."
                        )
                        return
                    if resp.status != 200:
                        body = await resp.text()
                        log.error("Separate API error %d: %s", resp.status, body)
                        await interaction.followup.send("Separation failed. Check that the Voice Cover Studio backend is running.")
                        return
                    result = await resp.json()

                vocals_filename = result.get("vocals_filename")
                instrumental_filename = result.get("instrumental_filename")
                stem_id = result.get("stem_id", "?")

                files_to_send: list[discord.File] = []
                size_limit = getattr(interaction.guild, "filesize_limit", 25 * 1024 * 1024)

                for label, filename in [("vocals", vocals_filename), ("instrumental", instrumental_filename)]:
                    if not filename:
                        continue
                    async with session.get(
                        f"{VOICE_STUDIO_URL}/api/separate/{filename}/audio",
                        timeout=aiohttp.ClientTimeout(total=120),
                    ) as stem_resp:
                        if stem_resp.status != 200:
                            log.warning("Could not fetch %s stem: %s", label, stem_resp.status)
                            continue
                        stem_bytes = await stem_resp.read()

                    if len(stem_bytes) > size_limit:
                        size_mb = len(stem_bytes) / 1024 / 1024
                        log.warning("%s stem too large for Discord (%s MB)", label, f"{size_mb:.1f}")
                        await interaction.followup.send(
                            f"The **{label}** stem is {size_mb:.1f} MB — too large to upload to Discord "
                            f"(server limit: {size_limit // 1024 // 1024} MB). "
                            "Boost the server for a higher limit, or fetch the file directly from the backend.",
                            ephemeral=True,
                        )
                        continue

                    files_to_send.append(
                        discord.File(io.BytesIO(stem_bytes), filename=f"{stem_id}_{label}.wav")
                    )

        except aiohttp.ClientConnectorError:
            await interaction.followup.send(
                "Cannot connect to Voice Cover Studio backend. "
                f"Make sure it's running at `{VOICE_STUDIO_URL}`."
            )
            return
        except Exception:
            log.exception("Error in /separate")
            await interaction.followup.send("An unexpected error occurred during separation.")
            return

        if not files_to_send:
            await interaction.followup.send("Separation produced no output files.")
            return

        embed = discord.Embed(
            title="Vocal Separation Complete",
            description=f"Separated **{audio.filename}** into vocals and instrumental.",
            color=0x7C3AED,
        )
        embed.set_footer(text=f"Stem ID: {stem_id} • Powered by Voice Cover Studio")

        await interaction.followup.send(embed=embed, files=files_to_send)


async def setup(bot: commands.Bot):
    await bot.add_cog(VoiceSeparate(bot))
