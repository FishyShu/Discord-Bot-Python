from __future__ import annotations

import asyncio
import functools
import logging
import os
import tempfile
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from gtts import gTTS

from dashboard import db

log = logging.getLogger(__name__)

LANG_CHOICES = [
    app_commands.Choice(name="English", value="en"),
    app_commands.Choice(name="Spanish", value="es"),
    app_commands.Choice(name="French", value="fr"),
    app_commands.Choice(name="German", value="de"),
    app_commands.Choice(name="Japanese", value="ja"),
    app_commands.Choice(name="Portuguese", value="pt"),
    app_commands.Choice(name="Russian", value="ru"),
    app_commands.Choice(name="Korean", value="ko"),
]


class TTS(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _ensure_voice(self, interaction: discord.Interaction) -> Optional[discord.VoiceClient]:
        """Ensure the bot is in the user's voice channel. Returns VoiceClient or None."""
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("You need to be in a voice channel.", ephemeral=True)
            return None

        channel = interaction.user.voice.channel
        vc = interaction.guild.voice_client

        if vc is None:
            vc = await channel.connect()
        elif vc.channel != channel:
            await vc.move_to(channel)

        return vc

    @app_commands.command(name="tts", description="Speak text aloud in your voice channel")
    @app_commands.describe(text="The text to speak", lang="Language for speech")
    @app_commands.choices(lang=LANG_CHOICES)
    async def tts(
        self,
        interaction: discord.Interaction,
        text: str,
        lang: Optional[app_commands.Choice[str]] = None,
    ):
        cfg = await db.get_tts_config(str(interaction.guild_id)) or {}
        if not cfg.get("tts_enabled", True):
            await interaction.response.send_message("TTS is disabled in this server.", ephemeral=True)
            return

        vc = await self._ensure_voice(interaction)
        if vc is None:
            return

        if vc.is_playing():
            await interaction.response.send_message("Audio is already playing.", ephemeral=True)
            return

        await interaction.response.defer()

        lang_code = lang.value if lang else "en"

        # Generate TTS audio in a thread (blocking I/O)
        loop = asyncio.get_running_loop()
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp_path = tmp.name
        tmp.close()

        try:
            await loop.run_in_executor(
                None,
                functools.partial(self._generate_tts, text, lang_code, tmp_path),
            )
        except Exception as e:
            os.unlink(tmp_path)
            await interaction.followup.send(f"TTS generation failed: {e}", ephemeral=True)
            return

        source = discord.FFmpegPCMAudio(tmp_path, options="-vn")
        source = discord.PCMVolumeTransformer(source, volume=0.8)

        def after_play(error):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            if error:
                log.error("TTS playback error: %s", error)

        vc.play(source, after=after_play)

        display_text = text if len(text) <= 100 else text[:100] + "..."
        await interaction.followup.send(
            embed=discord.Embed(
                description=f"Speaking: {display_text}",
                color=discord.Color.blurple(),
            )
        )

    @staticmethod
    def _generate_tts(text: str, lang: str, path: str):
        tts = gTTS(text=text, lang=lang)
        tts.save(path)

    # --- Config commands ---

    ttsconfig_group = app_commands.Group(
        name="ttsconfig",
        description="Configure TTS settings for this server",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @ttsconfig_group.command(name="set", description="Configure TTS settings")
    @app_commands.describe(
        enabled="Enable or disable TTS for this server",
        language="Default language for TTS",
    )
    @app_commands.choices(language=LANG_CHOICES)
    async def ttsconfig_set(
        self,
        interaction: discord.Interaction,
        enabled: Optional[bool] = None,
        language: Optional[app_commands.Choice[str]] = None,
    ):
        gid = str(interaction.guild_id)
        parts = []
        if enabled is not None:
            await db.set_guild_setting(gid, "tts_enabled", "1" if enabled else "0")
            parts.append(f"TTS {'enabled' if enabled else 'disabled'}")
        if language is not None:
            await db.set_guild_setting(gid, "tts_default_lang", language.value)
            parts.append(f"Default language set to **{language.name}**")
        if not parts:
            await interaction.response.send_message("No changes specified.", ephemeral=True)
            return
        await interaction.response.send_message(". ".join(parts) + ".", ephemeral=True)

    @ttsconfig_group.command(name="show", description="Show current TTS configuration")
    async def ttsconfig_show(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        enabled = await db.get_guild_setting(gid, "tts_enabled", "0")
        lang = await db.get_guild_setting(gid, "tts_default_lang", "en")
        lang_name = next((c.name for c in LANG_CHOICES if c.value == lang), lang)
        embed = discord.Embed(title="TTS Configuration", color=0x3498DB)
        embed.add_field(name="Enabled", value="Yes" if enabled == "1" else "No")
        embed.add_field(name="Default Language", value=lang_name)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(TTS(bot))
