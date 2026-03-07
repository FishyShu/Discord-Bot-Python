from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from dashboard import db

log = logging.getLogger(__name__)


class AutoRole(commands.Cog):
    """Automatically assign roles to new members on join."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cache: dict[str, list[str]] = {}

    async def cog_load(self):
        await self.refresh_cache()

    async def refresh_cache(self):
        self._cache = await db.get_all_autoroles_dict()
        log.info("AutoRole cache refreshed: %d guilds with autoroles", len(self._cache))

    autorole_group = app_commands.Group(
        name="autorole",
        description="Configure roles automatically assigned on join",
        default_permissions=discord.Permissions(manage_roles=True),
    )

    @autorole_group.command(name="add", description="Add a role to auto-assign on join")
    @app_commands.describe(role="Role to auto-assign")
    async def autorole_add(self, interaction: discord.Interaction, role: discord.Role):
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                "I cannot assign that role — it's above my highest role.", ephemeral=True
            )
            return
        if role.is_default() or role.managed:
            await interaction.response.send_message("That role cannot be assigned.", ephemeral=True)
            return

        gid = str(interaction.guild_id)
        await db.add_autorole(gid, str(role.id))
        await self.refresh_cache()
        await interaction.response.send_message(f"Added {role.mention} to autoroles.", ephemeral=True)

    @autorole_group.command(name="remove", description="Remove a role from auto-assign")
    @app_commands.describe(role="Role to remove")
    async def autorole_remove(self, interaction: discord.Interaction, role: discord.Role):
        gid = str(interaction.guild_id)
        removed = await db.remove_autorole(gid, str(role.id))
        if removed:
            await self.refresh_cache()
            await interaction.response.send_message(f"Removed {role.mention} from autoroles.", ephemeral=True)
        else:
            await interaction.response.send_message("That role is not in the autorole list.", ephemeral=True)

    @autorole_group.command(name="list", description="Show configured autoroles")
    async def autorole_list(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        role_ids = self._cache.get(gid, [])
        if not role_ids:
            await interaction.response.send_message("No autoroles configured.", ephemeral=True)
            return
        lines = []
        for rid in role_ids:
            role = interaction.guild.get_role(int(rid))
            lines.append(f"- {role.mention}" if role else f"- Unknown role ({rid})")
        embed = discord.Embed(
            title="Auto-Roles",
            description="\n".join(lines),
            color=0x3498DB,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        gid = str(member.guild.id)
        role_ids = self._cache.get(gid)
        if not role_ids:
            return
        roles_to_add = []
        for rid in role_ids:
            role = member.guild.get_role(int(rid))
            if role and role < member.guild.me.top_role and not role.managed:
                roles_to_add.append(role)
        if roles_to_add:
            try:
                await member.add_roles(*roles_to_add, reason="AutoRole on join")
            except discord.HTTPException as e:
                log.warning("AutoRole failed for %s in %s: %s", member, member.guild, e)


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoRole(bot))
