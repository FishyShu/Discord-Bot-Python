from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from dashboard import db

log = logging.getLogger(__name__)

_LANG_CHOICES = [
    app_commands.Choice(name="English", value="en"),
    app_commands.Choice(name="Spanish", value="es"),
    app_commands.Choice(name="French", value="fr"),
    app_commands.Choice(name="German", value="de"),
    app_commands.Choice(name="Japanese", value="ja"),
]


def _translate(text: str, target: str) -> str | None:
    """Translate text using deep-translator (Google Translate, no key required)."""
    try:
        from deep_translator import GoogleTranslator, single_detection  # type: ignore
        detected = single_detection(text, api_key=None)  # free tier
        if detected == target:
            return None  # already in target language
        translated = GoogleTranslator(source="auto", target=target).translate(text)
        return translated
    except Exception as exc:
        log.warning("Translation failed: %s", exc)
        return None


class AutoTranslate(commands.Cog):
    """Auto-translate messages in configured channels."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # {guild_id: config_dict}
        self._cache: dict[str, dict] = {}

    async def cog_load(self):
        self._cache = await db.get_all_autotranslate_configs()
        log.info("AutoTranslate cache loaded: %d guild(s)", len(self._cache))

    at_group = app_commands.Group(
        name="autotranslate",
        description="Configure automatic message translation",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @at_group.command(name="set", description="Enable auto-translate for a channel")
    @app_commands.describe(
        channel="Channel to enable translation in",
        target_lang="Language to translate messages into",
    )
    @app_commands.choices(target_lang=_LANG_CHOICES)
    async def at_set(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        target_lang: str = "en",
    ):
        gid = str(interaction.guild_id)
        await db.upsert_autotranslate_config(
            gid,
            channel_id=str(channel.id),
            target_lang=target_lang,
            enabled=1,
        )
        self._cache[gid] = {"channel_id": str(channel.id), "target_lang": target_lang, "enabled": 1}
        await interaction.response.send_message(
            f"Auto-translate enabled in {channel.mention} → `{target_lang}`.", ephemeral=True
        )

    @at_group.command(name="disable", description="Disable auto-translate for this server")
    async def at_disable(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        await db.delete_autotranslate_config(gid)
        self._cache.pop(gid, None)
        await interaction.response.send_message("Auto-translate disabled.", ephemeral=True)

    @at_group.command(name="show", description="Show current auto-translate configuration")
    async def at_show(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        cfg = self._cache.get(gid) or await db.get_autotranslate_config(gid)
        if not cfg:
            await interaction.response.send_message("Auto-translate is not configured.", ephemeral=True)
            return
        embed = discord.Embed(title="Auto-Translate Config", color=0x3498DB)
        embed.add_field(name="Channel", value=f"<#{cfg['channel_id']}>")
        embed.add_field(name="Target Language", value=cfg["target_lang"])
        embed.add_field(name="Enabled", value="Yes" if cfg.get("enabled") else "No")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not message.content:
            return
        gid = str(message.guild.id)
        cfg = self._cache.get(gid)
        if not cfg or not cfg.get("enabled"):
            return
        if str(message.channel.id) != cfg.get("channel_id"):
            return

        target = cfg.get("target_lang", "en")
        try:
            translated = await self.bot.loop.run_in_executor(
                None, _translate, message.content, target
            )
        except Exception as exc:
            log.warning("Translation executor error: %s", exc)
            return
        if not translated:
            return

        try:
            await message.add_reaction("🌐")
            await message.reply(f"🌐 **Translation ({target}):** {translated}", mention_author=False)
        except discord.HTTPException as e:
            log.debug("Failed to send translation reply in channel %s: %s", message.channel.id, e)


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoTranslate(bot))
