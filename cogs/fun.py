from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from dashboard import db

log = logging.getLogger(__name__)

_8BALL_RESPONSES = [
    "It is certain.", "It is decidedly so.", "Without a doubt.",
    "Yes, definitely.", "You may rely on it.", "As I see it, yes.",
    "Most likely.", "Outlook good.", "Yes.", "Signs point to yes.",
    "Reply hazy, try again.", "Ask again later.", "Better not tell you now.",
    "Cannot predict now.", "Concentrate and ask again.",
    "Don't count on it.", "My reply is no.", "My sources say no.",
    "Outlook not so good.", "Very doubtful.",
]

_ANIMAL_TYPES = ["dog", "cat", "fox", "panda", "koala", "bird"]


class Fun(commands.Cog):
    """Fun commands: memes, animals, 8ball, mock text, ship score."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # {guild_id: {command: {user_id: last_used_timestamp}}}
        self._cooldowns: dict[str, dict[str, dict[str, float]]] = {}

    async def _check(self, interaction: discord.Interaction, command: str) -> bool:
        """
        Enforce fun command config (enabled, channel restriction, role restriction, cooldown).
        Returns True if the command should proceed, False (and sends ephemeral error) if blocked.
        """
        if not interaction.guild_id:
            return True

        guild_id = str(interaction.guild_id)
        configs = await db.get_fun_guild_config(guild_id)
        cfg = configs.get(command, {})

        # Enabled check (default: enabled)
        if not cfg.get("enabled", 1):
            await interaction.response.send_message(
                f"The `/{command}` command is disabled on this server.", ephemeral=True
            )
            return False

        # Channel restriction
        allowed_channels = json.loads(cfg.get("allowed_channels", "[]"))
        if allowed_channels and str(interaction.channel_id) not in allowed_channels:
            names = ", ".join(f"<#{c}>" for c in allowed_channels)
            await interaction.response.send_message(
                f"`/{command}` can only be used in: {names}", ephemeral=True
            )
            return False

        # Role restriction
        allowed_roles = json.loads(cfg.get("allowed_roles", "[]"))
        if allowed_roles:
            member_role_ids = {str(r.id) for r in interaction.user.roles}
            if not member_role_ids.intersection(allowed_roles):
                await interaction.response.send_message(
                    f"You don't have the required role to use `/{command}`.", ephemeral=True
                )
                return False

        # Cooldown
        cooldown = cfg.get("cooldown", 0)
        if cooldown > 0:
            user_id = str(interaction.user.id)
            guild_cd = self._cooldowns.setdefault(guild_id, {})
            cmd_cd = guild_cd.setdefault(command, {})
            last = cmd_cd.get(user_id, 0)
            remaining = cooldown - (time.monotonic() - last)
            if remaining > 0:
                await interaction.response.send_message(
                    f"`/{command}` is on cooldown. Try again in **{remaining:.1f}s**.", ephemeral=True
                )
                return False
            cmd_cd[user_id] = time.monotonic()

        return True

    @app_commands.command(name="meme", description="Fetch a random meme from Reddit")
    async def meme(self, interaction: discord.Interaction):
        if not await self._check(interaction, "meme"):
            return
        await interaction.response.defer()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://meme-api.com/gimme", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        await interaction.followup.send("Failed to fetch a meme. Try again later.")
                        return
                    data = await resp.json()
            embed = discord.Embed(title=data.get("title", "Meme"), color=0xFF6B35)
            embed.set_image(url=data.get("url", ""))
            embed.set_footer(text=f"r/{data.get('subreddit', '?')} • 👍 {data.get('ups', 0)}")
            await interaction.followup.send(embed=embed)
        except Exception as exc:
            log.warning("Meme fetch failed: %s", exc)
            await interaction.followup.send("Could not fetch a meme right now.")

    @app_commands.command(name="animal", description="Fetch a cute animal image")
    @app_commands.describe(animal="Type of animal")
    @app_commands.choices(animal=[
        app_commands.Choice(name=a.capitalize(), value=a) for a in _ANIMAL_TYPES
    ])
    async def animal(self, interaction: discord.Interaction, animal: str):
        if not await self._check(interaction, "animal"):
            return
        await interaction.response.defer()
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://some-random-api.com/animal/{animal}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        await interaction.followup.send("Could not fetch an image right now.")
                        return
                    data = await resp.json()
            embed = discord.Embed(title=f"Here's a {animal}! 🐾", color=0x2ECC71)
            embed.set_image(url=data.get("image", ""))
            if data.get("fact"):
                embed.set_footer(text=f"Fun fact: {data['fact'][:200]}")
            await interaction.followup.send(embed=embed)
        except Exception as exc:
            log.warning("Animal fetch failed: %s", exc)
            await interaction.followup.send("Could not fetch an animal image right now.")

    @app_commands.command(name="8ball", description="Ask the magic 8-ball a question")
    @app_commands.describe(question="Your question")
    async def eightball(self, interaction: discord.Interaction, question: str):
        if not await self._check(interaction, "8ball"):
            return
        response = random.choice(_8BALL_RESPONSES)
        embed = discord.Embed(color=0x1A1A2E)
        embed.add_field(name="🎱 Question", value=question, inline=False)
        embed.add_field(name="Answer", value=response, inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="mock", description="Spongebob-mock someone's text")
    @app_commands.describe(text="Text to mock")
    async def mock(self, interaction: discord.Interaction, text: str):
        if not await self._check(interaction, "mock"):
            return
        mocked = "".join(
            c.upper() if i % 2 == 0 else c.lower() for i, c in enumerate(text)
        )
        await interaction.response.send_message(f"🧽 {mocked}")

    @app_commands.command(name="avatar", description="Show a user's avatar")
    @app_commands.describe(user="User to show avatar for (defaults to you)")
    async def avatar(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        if not await self._check(interaction, "avatar"):
            return
        target = user or interaction.user
        av = target.display_avatar
        is_animated = av.is_animated()
        embed = discord.Embed(title=f"{target.display_name}'s avatar", color=0x5865F2)
        embed.set_image(url=av.with_size(1024).url)
        formats = [f"[PNG]({av.with_format('png').url})", f"[WEBP]({av.with_format('webp').url})"]
        if is_animated:
            formats.append(f"[GIF]({av.with_format('gif').url})")
        embed.add_field(name="Download", value=" | ".join(formats))
        embed.set_footer(text=f"{'Animated' if is_animated else 'Static'} • User ID: {target.id}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ship", description="Calculate love compatibility between two users")
    @app_commands.describe(user1="First user", user2="Second user (defaults to you)")
    async def ship(self, interaction: discord.Interaction, user1: discord.Member,
                   user2: Optional[discord.Member] = None):
        if not await self._check(interaction, "ship"):
            return
        if user2 is None:
            user2 = interaction.user
        combined = "".join(sorted([str(user1.id), str(user2.id)]))
        score = int(hashlib.md5(combined.encode()).hexdigest(), 16) % 101
        if score >= 80:
            verdict = "❤️ Perfect match!"
        elif score >= 60:
            verdict = "💛 Pretty good!"
        elif score >= 40:
            verdict = "💙 It's complicated."
        elif score >= 20:
            verdict = "🖤 Not looking great..."
        else:
            verdict = "💔 Yikes."
        bar = "█" * (score // 10) + "░" * (10 - score // 10)
        embed = discord.Embed(title="💘 Compatibility Score", color=0xFF69B4)
        embed.description = f"{user1.mention} + {user2.mention}"
        embed.add_field(name="Score", value=f"`{bar}` {score}%", inline=False)
        embed.add_field(name="Verdict", value=verdict)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="echo", description="Send a message as another user via webhook")
    @app_commands.describe(user="User to impersonate", text="Message to send")
    async def echo(self, interaction: discord.Interaction, user: discord.Member, text: str):
        if not await self._check(interaction, "echo"):
            return
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        try:
            webhooks = await channel.webhooks()
            webhook = discord.utils.get(webhooks, name="EchoBot")
            if webhook is None:
                webhook = await channel.create_webhook(name="EchoBot")
            await webhook.send(
                content=text,
                username=user.display_name,
                avatar_url=user.display_avatar.url,
            )
            await interaction.followup.send("Done.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(
                "I need the **Manage Webhooks** permission to use this command.", ephemeral=True
            )
        except Exception as exc:
            log.warning("Echo webhook failed: %s", exc)
            await interaction.followup.send("Something went wrong.", ephemeral=True)

    @app_commands.command(name="verify", description="Complete a quick human verification CAPTCHA")
    async def verify(self, interaction: discord.Interaction):
        if not await self._check(interaction, "verify"):
            return
        challenge = random.choice(_CAPTCHA_CHALLENGES)
        view = VerifyCaptchaView(challenge)
        embed = discord.Embed(
            title="🤖 Human Verification Required",
            description=challenge,
            color=0xEB459E,
        )
        embed.set_footer(text="Powered by TotallyRealCAPTCHA™ v9.4.1")
        await interaction.response.send_message(embed=embed, view=view)


_CAPTCHA_CHALLENGES = [
    "Select all squares containing a **fire hydrant**.",
    "Click the button that is **NOT red**.",
    "Solve this: If a train leaves at 60 mph and a duck quacks at noon, how many pancakes fit in a doghouse?",
    "Please **check the box** below to continue.",
    "Type the letters you see in the image above.",
]

_FAILURE_MESSAGES = [
    "❌ Incorrect. A human would have known that.",
    "❌ Our AI detected **4 robot behaviors** in your click pattern.",
    "❌ Error: Too human-like. Please try again.",
    "❌ FAILED: You blinked while clicking.",
]


class VerifyCaptchaView(discord.ui.View):
    def __init__(self, challenge: str, attempt: int = 1):
        super().__init__(timeout=60)
        self.challenge = challenge
        self.attempt = attempt

    def _build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🤖 Human Verification Required",
            description=self.challenge,
            color=0xEB459E,
        )
        embed.set_footer(text="Powered by TotallyRealCAPTCHA™ v9.4.1")
        return embed

    async def _handle_click(self, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True

        failure = random.choice(_FAILURE_MESSAGES)

        if self.attempt >= 2:
            # Give up after 2 failures
            embed = discord.Embed(
                title="✅ Verification Complete",
                description="We've decided to trust you. (We gave up.)\n\nWelcome, *probably-human*.",
                color=0x57F287,
            )
            embed.set_footer(text="TotallyRealCAPTCHA™ — protecting the internet, sort of")
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            # Show failure + Try Again
            new_challenge = random.choice(_CAPTCHA_CHALLENGES)
            retry_view = VerifyCaptchaView(new_challenge, attempt=self.attempt + 1)
            embed = discord.Embed(
                title="🤖 Human Verification Required",
                description=f"{failure}\n\n**New challenge:** {new_challenge}",
                color=0xED4245,
            )
            embed.set_footer(text="Powered by TotallyRealCAPTCHA™ v9.4.1")
            await interaction.response.edit_message(embed=embed, view=retry_view)

    @discord.ui.button(label="1", style=discord.ButtonStyle.secondary)
    async def btn_1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction)

    @discord.ui.button(label="2", style=discord.ButtonStyle.secondary)
    async def btn_2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction)

    @discord.ui.button(label="3", style=discord.ButtonStyle.secondary)
    async def btn_3(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_click(interaction)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.danger)
    async def btn_skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        embed = discord.Embed(
            title="✅ Verification Complete",
            description="Skipping counts as passing. Welcome, *probably-human*.\n\n(We gave up.)",
            color=0x57F287,
        )
        embed.set_footer(text="TotallyRealCAPTCHA™ — protecting the internet, sort of")
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


async def setup(bot: commands.Bot):
    await bot.add_cog(Fun(bot))
