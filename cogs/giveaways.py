from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from dashboard import db
from utils.time_parser import format_duration, parse_duration

log = logging.getLogger(__name__)

GIVEAWAY_EMOJI = "🎉"


class Giveaways(commands.Cog):
    """Full giveaway lifecycle: create, auto-end, reroll."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._check_giveaways.start()

    def cog_unload(self):
        self._check_giveaways.cancel()

    @tasks.loop(seconds=30)
    async def _check_giveaways(self):
        now = datetime.now(timezone.utc).isoformat()
        active = await db.get_all_active_giveaways()
        for gw in active:
            if gw["ends_at"] <= now:
                await self._end_giveaway(gw)

    @_check_giveaways.before_loop
    async def _before_check(self):
        await self.bot.wait_until_ready()

    async def _end_giveaway(self, gw: dict) -> list[discord.Member] | None:
        """Pick winners, update DB, and announce result."""
        guild = self.bot.get_guild(int(gw["guild_id"]))
        if not guild:
            await db.end_giveaway(gw["id"], [])
            return None
        channel = guild.get_channel(int(gw["channel_id"]))
        if not channel:
            await db.end_giveaway(gw["id"], [])
            return None

        winners: list[discord.Member] = []
        if gw.get("message_id"):
            try:
                msg = await channel.fetch_message(int(gw["message_id"]))
                reaction = discord.utils.get(msg.reactions, emoji=GIVEAWAY_EMOJI)
                if reaction:
                    users = [u async for u in reaction.users() if not u.bot]
                    k = min(gw["winner_count"], len(users))
                    winners = random.sample(users, k) if users else []
            except (discord.NotFound, discord.HTTPException):
                pass

        winner_ids = [str(w.id) for w in winners]
        await db.end_giveaway(gw["id"], winner_ids)

        embed = discord.Embed(title="🎉 Giveaway Ended!", color=0xFFD700,
                               timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Prize", value=gw["prize"], inline=False)
        if winners:
            embed.add_field(name="Winner(s)", value=", ".join(w.mention for w in winners), inline=False)
            winner_mentions = " ".join(w.mention for w in winners)
            content = f"Congratulations {winner_mentions}! You won **{gw['prize']}**! 🎉"
        else:
            embed.add_field(name="Winners", value="No valid entries.", inline=False)
            content = f"The giveaway for **{gw['prize']}** ended with no valid entries."

        try:
            await channel.send(content=content, embed=embed)
        except discord.HTTPException:
            pass
        return winners

    gw_group = app_commands.Group(
        name="giveaway",
        description="Manage giveaways",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @gw_group.command(name="start", description="Start a new giveaway")
    @app_commands.describe(
        prize="What are you giving away?",
        duration="Duration (e.g. 10m, 2h, 1d)",
        winners="Number of winners (default 1)",
    )
    async def gw_start(self, interaction: discord.Interaction, prize: str,
                        duration: str, winners: int = 1):
        seconds = parse_duration(duration)
        if not seconds or seconds <= 0:
            await interaction.response.send_message(
                "Invalid duration. Use e.g. `10m`, `2h`, `1d`.", ephemeral=True
            )
            return
        winners = max(1, winners)
        ends_at = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() + seconds, tz=timezone.utc
        ).isoformat()

        gw_id = await db.create_giveaway(
            guild_id=str(interaction.guild_id),
            channel_id=str(interaction.channel_id),
            prize=prize,
            winner_count=winners,
            ends_at=ends_at,
        )

        embed = discord.Embed(
            title=f"🎉 Giveaway — {prize}",
            description=f"React with {GIVEAWAY_EMOJI} to enter!\n\n"
                        f"**Ends in:** {format_duration(seconds)}\n"
                        f"**Winners:** {winners}",
            color=0xFFD700,
            timestamp=datetime.fromisoformat(ends_at),
        )
        embed.set_footer(text=f"Ends at • Giveaway ID: {gw_id}")

        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()
        await msg.add_reaction(GIVEAWAY_EMOJI)
        await db.set_giveaway_message_id(gw_id, str(msg.id))

    @gw_group.command(name="end", description="End a giveaway early by its ID")
    @app_commands.describe(giveaway_id="Giveaway ID (from /giveaway list)")
    async def gw_end(self, interaction: discord.Interaction, giveaway_id: int):
        gw = await db.get_giveaway(giveaway_id)
        if not gw or gw["guild_id"] != str(interaction.guild_id):
            await interaction.response.send_message("Giveaway not found.", ephemeral=True)
            return
        if gw["ended"]:
            await interaction.response.send_message("That giveaway has already ended.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self._end_giveaway(gw)
        await interaction.followup.send(f"Giveaway #{giveaway_id} ended.", ephemeral=True)

    @gw_group.command(name="reroll", description="Reroll winner(s) for a finished giveaway")
    @app_commands.describe(giveaway_id="Giveaway ID")
    async def gw_reroll(self, interaction: discord.Interaction, giveaway_id: int):
        gw = await db.get_giveaway(giveaway_id)
        if not gw or gw["guild_id"] != str(interaction.guild_id):
            await interaction.response.send_message("Giveaway not found.", ephemeral=True)
            return
        if not gw["ended"]:
            await interaction.response.send_message("That giveaway has not ended yet.", ephemeral=True)
            return

        channel = interaction.guild.get_channel(int(gw["channel_id"]))
        new_winners: list[discord.Member] = []
        if channel and gw.get("message_id"):
            try:
                msg = await channel.fetch_message(int(gw["message_id"]))
                reaction = discord.utils.get(msg.reactions, emoji=GIVEAWAY_EMOJI)
                if reaction:
                    users = [u async for u in reaction.users() if not u.bot]
                    k = min(gw["winner_count"], len(users))
                    new_winners = random.sample(users, k) if users else []
            except (discord.NotFound, discord.HTTPException):
                pass

        if new_winners:
            winner_mentions = " ".join(w.mention for w in new_winners)
            await db.end_giveaway(giveaway_id, [str(w.id) for w in new_winners])
            await interaction.response.send_message(
                f"🎉 New winner(s) for **{gw['prize']}**: {winner_mentions}"
            )
        else:
            await interaction.response.send_message(
                "Could not determine new winners (no reactions found).", ephemeral=True
            )

    @gw_group.command(name="list", description="List active giveaways in this server")
    async def gw_list(self, interaction: discord.Interaction):
        rows = await db.get_active_giveaways(str(interaction.guild_id))
        if not rows:
            await interaction.response.send_message("No active giveaways.", ephemeral=True)
            return
        embed = discord.Embed(title="Active Giveaways", color=0xFFD700)
        for gw in rows[:10]:
            embed.add_field(
                name=f"#{gw['id']} — {gw['prize']}",
                value=f"Ends: <t:{int(datetime.fromisoformat(gw['ends_at']).timestamp())}:R> | "
                      f"Winners: {gw['winner_count']} | "
                      f"<#{gw['channel_id']}>",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Giveaways(bot))
