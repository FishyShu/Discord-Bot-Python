from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)

SOUNDS_DIR = Path(__file__).resolve().parent.parent / "sounds"
ALLOWED_EXTENSIONS = {".mp3", ".wav", ".ogg"}


class Soundboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _list_sounds(self) -> list[Path]:
        """Return sorted list of sound files in the sounds directory."""
        if not SOUNDS_DIR.is_dir():
            return []
        return sorted(
            p for p in SOUNDS_DIR.iterdir()
            if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS
        )

    async def sound_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        sounds = self._list_sounds()
        choices = []
        for p in sounds:
            name = p.stem
            if current.lower() in name.lower():
                choices.append(app_commands.Choice(name=name[:100], value=p.name))
            if len(choices) >= 25:
                break
        return choices

    async def _play_sound(self, interaction: discord.Interaction, sound: str):
        # Validate the sound file
        file_path = (SOUNDS_DIR / sound).resolve()
        if not str(file_path).startswith(str(SOUNDS_DIR.resolve())):
            await interaction.response.send_message("Invalid sound name.", ephemeral=True)
            return
        if not file_path.is_file() or file_path.suffix.lower() not in ALLOWED_EXTENSIONS:
            # List available sounds if none found
            sounds = self._list_sounds()
            if not sounds:
                await interaction.response.send_message("No sounds available. Add `.mp3`, `.wav`, or `.ogg` files to the `sounds/` folder.", ephemeral=True)
            else:
                await interaction.response.send_message(f"Sound `{sound}` not found.", ephemeral=True)
            return

        # Ensure user is in a voice channel
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("You need to be in a voice channel.", ephemeral=True)
            return

        channel = interaction.user.voice.channel
        vc = interaction.guild.voice_client
        was_connected = vc is not None

        # Check if audio is already playing
        if vc and (vc.is_playing() or vc.is_paused()):
            await interaction.response.send_message("Audio is already playing.", ephemeral=True)
            return

        # Connect if needed
        if vc is None:
            vc = await channel.connect()
        elif vc.channel != channel:
            await vc.move_to(channel)

        await interaction.response.defer()

        source = discord.FFmpegPCMAudio(str(file_path), options="-vn")
        source = discord.PCMVolumeTransformer(source, volume=0.8)

        def after_play(error):
            if error:
                log.error("Soundboard playback error: %s", error)
            if not was_connected:
                asyncio.run_coroutine_threadsafe(vc.disconnect(), self.bot.loop)

        vc.play(source, after=after_play)

        await interaction.followup.send(
            embed=discord.Embed(
                description=f"Playing **{file_path.stem}**",
                color=discord.Color.blurple(),
            )
        )

    @app_commands.command(name="soundboard", description="Play a sound effect from the soundboard")
    @app_commands.describe(sound="Sound to play")
    @app_commands.autocomplete(sound=sound_autocomplete)
    async def soundboard(self, interaction: discord.Interaction, sound: str):
        await self._play_sound(interaction, sound)

    @app_commands.command(name="sb", description="Play a sound effect (shortcut)")
    @app_commands.describe(sound="Sound to play")
    @app_commands.autocomplete(sound=sound_autocomplete)
    async def sb(self, interaction: discord.Interaction, sound: str):
        await self._play_sound(interaction, sound)


async def setup(bot: commands.Bot):
    await bot.add_cog(Soundboard(bot))
