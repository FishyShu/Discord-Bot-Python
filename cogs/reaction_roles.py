from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from dashboard import db

log = logging.getLogger(__name__)


class ReactionRoles(commands.Cog):
    """Assign/remove roles when users react on configured messages."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Cache: message_id -> {emoji: role_id}
        self._cache: dict[str, dict[str, str]] = {}

    async def cog_load(self):
        await self.refresh_cache()

    async def refresh_cache(self):
        self._cache = await db.get_all_reaction_roles_dict()
        log.info("ReactionRoles cache refreshed: %d messages tracked", len(self._cache))

    def _get_role_id(self, message_id: str, emoji: str) -> str | None:
        mapping = self._cache.get(message_id)
        if not mapping:
            return None
        return mapping.get(emoji)

    # --- Slash commands ---

    rr_group = app_commands.Group(
        name="reactionrole",
        description="Manage reaction roles",
        default_permissions=discord.Permissions(manage_roles=True),
    )

    @rr_group.command(name="setup", description="Add a reaction role to a message")
    @app_commands.describe(
        channel="Channel containing the message",
        message_id="ID of the target message",
        emoji="Emoji to react with",
        role="Role to assign",
    )
    async def rr_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        message_id: str,
        emoji: str,
        role: discord.Role,
    ):
        try:
            message = await channel.fetch_message(int(message_id))
        except (discord.NotFound, discord.HTTPException, ValueError):
            await interaction.response.send_message("Could not find that message.", ephemeral=True)
            return

        await db.create_reaction_role(
            guild_id=str(interaction.guild_id),
            channel_id=str(channel.id),
            message_id=message_id,
            emoji=emoji,
            role_id=str(role.id),
        )
        await self.refresh_cache()

        try:
            await message.add_reaction(emoji)
        except discord.HTTPException as e:
            log.debug("Failed to add reaction %s to message %s: %s", emoji, message.id, e)

        await interaction.response.send_message(
            f"Reaction role set: {emoji} → {role.mention} on [message]({message.jump_url})",
            ephemeral=True,
        )

    @rr_group.command(name="remove", description="Remove a reaction role mapping")
    @app_commands.describe(message_id="Message ID", emoji="Emoji to remove")
    async def rr_remove(self, interaction: discord.Interaction, message_id: str, emoji: str):
        deleted = await db.delete_reaction_role_by_message_emoji(message_id, emoji)
        if not deleted:
            await interaction.response.send_message("No matching reaction role found.", ephemeral=True)
            return
        await self.refresh_cache()
        await interaction.response.send_message(f"Removed reaction role {emoji} from message `{message_id}`.", ephemeral=True)

    @rr_group.command(name="list", description="List all reaction roles in this server")
    async def rr_list(self, interaction: discord.Interaction):
        rrs = await db.get_reaction_roles(str(interaction.guild_id))
        if not rrs:
            await interaction.response.send_message("No reaction roles configured.", ephemeral=True)
            return

        lines = []
        for rr in rrs:
            role = interaction.guild.get_role(int(rr["role_id"]))
            role_name = role.mention if role else f"Unknown ({rr['role_id']})"
            lines.append(f"{rr['emoji']} → {role_name} (msg: `{rr['message_id']}`)")

        embed = discord.Embed(
            title="Reaction Roles",
            description="\n".join(lines),
            color=0x3498DB,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.member and payload.member.bot:
            return
        emoji_str = str(payload.emoji)
        role_id = self._get_role_id(str(payload.message_id), emoji_str)
        if not role_id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        role = guild.get_role(int(role_id))
        member = payload.member or guild.get_member(payload.user_id)
        if not role or not member:
            return

        try:
            await member.add_roles(role, reason="Reaction role")
        except discord.HTTPException as e:
            log.warning("Failed to add role %s to %s: %s", role_id, member, e)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        emoji_str = str(payload.emoji)
        role_id = self._get_role_id(str(payload.message_id), emoji_str)
        if not role_id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        role = guild.get_role(int(role_id))
        member = guild.get_member(payload.user_id)
        if not role or not member:
            return

        try:
            await member.remove_roles(role, reason="Reaction role removed")
        except discord.HTTPException as e:
            log.warning("Failed to remove role %s from %s: %s", role_id, member, e)


async def setup(bot: commands.Bot):
    await bot.add_cog(ReactionRoles(bot))
