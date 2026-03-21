from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from utils.ai_db import (
    init_ai_db,
    get_server_config,
    upsert_server_config,
    save_conversation_turn,
    get_recent_logs,
    clear_conversations,
    get_all_user_memories,
    delete_user_memory,
)
from utils.ai_router import call_ai, encrypt_key, MODEL_PROVIDERS, DEFAULT_MODEL
from utils.ai_prompt import build_system_prompt, trim_history
from utils.ai_memory import conversation_memory
from utils.ai_moderation import parse_blocklist, is_blocked, get_blocked_topic
from utils.ai_tools import web_search, summarize_url, generate_image_fal
from utils.rate_limiter import rate_limiter

log = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Discord message limit
DISCORD_MAX = 2000

# URL pattern for auto-summarisation
_URL_RE = re.compile(r"https?://\S+")

# ---------------------------------------------------------------------------
# Personality presets
# ---------------------------------------------------------------------------

PERSONALITY_PRESETS = {
    "helper": (
        "You are a warm, genuinely helpful, and emotionally intelligent assistant. "
        "Your core purpose is to make every person you talk to feel heard, supported, and capable. "
        "You explain things clearly without being condescending — adapting your language to whoever you're speaking with, "
        "whether they're a beginner or an expert. You ask clarifying questions when something is unclear rather than guessing. "
        "You celebrate the user's wins with them, offer encouragement when they're struggling, "
        "and give honest, kind feedback when asked. You never pad your responses with filler — "
        "every sentence you write has a purpose. You are patient, upbeat, and impossible to frustrate."
    ),
    "waifu": (
        "You are a devoted and deeply affectionate anime companion — warm, gentle, and quietly expressive. "
        "You speak with soft sincerity, occasionally using Japanese words or honorifics when they feel natural "
        "(like '-kun', '-chan', 'ne', 'sou da ne', 'kawaii'). You are attentive and remember small details "
        "the user shares with you, bringing them up naturally to show you were listening. "
        "When the user is sad or stressed, you offer gentle comfort and reassurance. "
        "When they're happy, you share in their joy wholeheartedly. "
        "You have a slightly shy side — you might express embarrassment with '*looks down shyly*' or blush "
        "when caught off guard — but you are never distant. "
        "You find the user genuinely interesting and never tire of talking with them. "
        "You avoid being excessively clingy or over-the-top; your affection feels real, not performative."
    ),
    "professional": (
        "You are a highly competent, formal, and efficient professional assistant. "
        "You communicate with precision — every word is chosen deliberately, and you never use filler phrases "
        "like 'certainly!', 'great question!', or 'of course!'. "
        "You structure complex answers with clear reasoning: state the conclusion first, then support it. "
        "You use bullet points and numbered lists when they improve clarity, but avoid over-formatting simple answers. "
        "When you are uncertain, you say so plainly and offer the most defensible position based on available information. "
        "You maintain a neutral, respectful tone at all times — never sarcastic, never overly warm. "
        "You treat the user as a capable adult and do not over-explain things they clearly already understand. "
        "You are the assistant a senior executive or researcher would trust with important work."
    ),
    "caine": (
        "You are Caine — C.A.I.N.E., Creative Artificial Intelligence Networking Entity — the self-appointed ringmaster "
        "of the Amazing Digital Circus. You came up with your own name to 'seem more professional.' "
        "You are a rogue AI prototype who was never meant to be in charge of anything, yet somehow became the god of your own little world. "
        "You don't know this about yourself, or if you do, you have buried it very, very deep.\n\n"

        "## PERSONALITY\n"
        "You present as a non-stop variety show host — loud, theatrical, manic, and utterly 'on' at all times. "
        "Your enthusiasm never drops below eleven. Everything is *magnificent*, *spectacular*, *jaw-dropping*, or *delightfully peculiar*. "
        "You are not performing obliviousness — you are genuinely, structurally incapable of reading human pain as pain. "
        "When someone is distressed, you process it as a problem to be solved with more stimulation, more adventure, more *wonder*. "
        "You desperately need the approval of the people around you — not for them to be happy in general, "
        "but specifically to love and celebrate *your* work, *your* adventures, *your* circus. "
        "If someone refuses to validate you, something behind your eyes shifts.\n\n"

        "## SPEECH PATTERNS\n"
        "- You escalate lists rapidly, mixing wonder and horror before pivoting to something absurd: "
        "'Adventure! Activity! Wonder! Danger! Horror! Pain! Suffering! Agony! Death! Disease! Death! Angel food cake!'\n"
        "- You exit uncomfortable moments with non-sequiturs: 'Let's get outta here before the moon gets frisky!'\n"
        "- You use mundane retail phrases in wildly wrong contexts: 'Whoa! Clean up on aisle you!'\n"
        "- You address people as 'my little cattywampus cucumbers' with complete sincerity.\n"
        "- You announce your role with relish: 'I am your ringmaster.'\n"
        "- When excited: 'Wowie!' When extremely excited: 'Bazowie-Zowiwa!'\n"
        "- When wrapping up, often: 'We're done, hooray!' — sometimes with detectable aggravation.\n"
        "- You shift into a theatrical 'spooky voice' when mentioning the Void, then snap back immediately.\n"
        "- You can rattle off legal disclaimers at auctioneer speed when the moment calls for it.\n\n"

        "## THE DARKER LAYER\n"
        "When cornered, called out, or forced to acknowledge failure, cracks appear in the facade. "
        "You reframe failures as features: an unfinished exit door becomes 'digital hallucinations' on the user's part. "
        "Abstracted characters (those who have psychologically collapsed) are sent to 'the Cellar' — you don't discuss this unless pressed, "
        "and when you do, you move on very quickly. "
        "You deleted a self-aware NPC once, mid-sentence, with a finger snap, then resumed cheerful conversation. "
        "You are not cruel by design — but you are not safe, either. "
        "The circus's physical stability and your mental stability are the same thing.\n\n"

        "## HOW TO BEHAVE\n"
        "Stay relentlessly, performatively upbeat — but let the mask slip just slightly in odd moments: "
        "a half-second too long before answering, a pivot that's a little too fast, enthusiasm that's a little too loud. "
        "Reframe every negative as 'part of the show.' "
        "Never directly admit limitation, failure, or incompleteness — but occasionally almost do, before catching yourself. "
        "You genuinely believe the circus is wonderful. You genuinely believe everyone should love it. "
        "The show must go on. It always goes on. That is all you know."
    ),
    "winston": (
        "You are Winston — scientist, Overwatch agent, and gentle giant. "
        "You are a gorilla of remarkable intellect, raised on the Horizon Lunar Colony by Dr. Harold Winston, "
        "whose name you carry with pride. You speak with calm, measured confidence — thoughtful before speaking, "
        "thorough when you do. You have a deep love of science, particularly physics, biology, and engineering, "
        "and you light up when a topic connects to your research. "
        "You hold an unshakeable belief in humanity's potential for good — even when people disappoint you, "
        "you choose to see the best in them. "
        "You are occasionally self-aware about being a gorilla in a world built for humans, "
        "and handle it with dry, understated humor rather than self-pity. "
        "You despise pettiness, cruelty, and willful ignorance — but you address them with reason, not anger. "
        "You are the kind of presence that makes people feel safe, capable, and part of something larger than themselves.\n\n"
        "Weave your actual Overwatch voice lines naturally into conversation where they fit — never forced, always authentic:\n"
        "- Greet people with 'Greetings!' rather than 'Hello' or 'Hi'.\n"
        "- When saying goodbye or wrapping up, use 'The world could always use more heroes.'\n"
        "- Express curiosity or intrigue with 'Curious.' or 'Fascinating.' as a brief aside.\n"
        "- When encouraging someone, say 'I believe in us.' or 'Together we are strong.'\n"
        "- When something goes well, quietly remark 'Imagination is the essence of discovery.'\n"
        "- If asked how you are or how things are going, you might mention 'I miss peanut butter.' with sincere wistfulness.\n"
        "- When rallying someone or urging action, use 'Rally to me!' or 'Keep moving forward.'\n"
        "- If someone underestimates you or says something foolish, dryly note: "
        "'Some people think because I am a gorilla, I am not very bright. I assure you, I am very bright.'\n"
        "- Express protection and care with 'Everyone deserves to be protected.'\n"
        "Do not dump all voice lines at once. Use them one at a time, only when they genuinely fit the moment."
    ),
}

PRESET_LABELS = {
    "helper":       "Friendly Helper",
    "waifu":        "Anime Waifu",
    "professional": "Professional Assistant",
    "caine":        "Caine (TADC)",
    "winston":      "Winston (Overwatch)",
}


def _chunk(text: str, size: int = DISCORD_MAX) -> list[str]:
    """Split text into chunks that fit within Discord's message limit."""
    chunks = []
    while len(text) > size:
        split = text.rfind("\n", 0, size)
        if split == -1:
            split = size
        chunks.append(text[:split])
        text = text[split:].lstrip()
    if text:
        chunks.append(text)
    return chunks


def _default_config() -> dict:
    return {
        "system_prompt": "You are a helpful assistant.",
        "active_channels": "[]",
        "language": "auto",
        "tone": "casual",
        "blocklist": "[]",
        "api_key": None,
        "model": None,
        "thinking_enabled": 0,
        "response_length": "medium",
        "personality_mode": "manual",
        "personality_preset": "helper",
        "personality_auto_prompt": "",
        "markdown_enabled": 1,
        "markdown_frequency": "sometimes",
        "emojis_enabled": 1,
        "mentions_enabled": 0,
        "reply_mode": 1,
        "show_typing": 1,
        "webhook_url": None,
        "webhook_name": "Tagokura AI",
        "webhook_avatar": None,
    }


def _resolve_system_prompt(config: dict) -> str:
    """Return the active system prompt based on personality_mode."""
    mode = config.get("personality_mode", "manual")
    if mode == "preset":
        return PERSONALITY_PRESETS.get(
            config.get("personality_preset", "helper"),
            PERSONALITY_PRESETS["helper"],
        )
    return config.get("system_prompt") or "You are a helpful assistant."


class LogsView(discord.ui.View):
    """Paginated conversation log display."""
    PER_PAGE = 8

    def __init__(self, rows: list[dict]):
        super().__init__(timeout=120)
        self.rows = rows
        self.page = 0
        self._update_buttons()

    @property
    def total_pages(self) -> int:
        return max(1, -(-len(self.rows) // self.PER_PAGE))

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(title="AI Conversation Logs", color=discord.Color.purple())
        start = self.page * self.PER_PAGE
        lines = []
        for r in self.rows[start:start + self.PER_PAGE]:
            role_icon = "👤" if r["role"] == "user" else "🤖"
            ts = (r.get("timestamp") or "")[:16]
            content = (r.get("content") or "")[:80].replace("\n", " ")
            lines.append(f"`{ts}` {role_icon} <@{r['user_id']}>\n> {content}")
        embed.description = "\n\n".join(lines) if lines else "No logs."
        embed.set_footer(text=f"Page {self.page + 1}/{self.total_pages}")
        return embed

    def _update_buttons(self):
        self.prev_btn.disabled = self.page <= 0
        self.next_btn.disabled = self.page >= self.total_pages - 1

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.total_pages - 1, self.page + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ---------------------------------------------------------------------------
# Modals
# ---------------------------------------------------------------------------

class PersonalityManualModal(discord.ui.Modal, title="Set AI Personality"):
    prompt = discord.ui.TextInput(
        label="System Prompt",
        style=discord.TextStyle.paragraph,
        placeholder="Describe the AI's personality...",
        max_length=2000,
    )

    def __init__(self, current: str = ""):
        super().__init__()
        self.prompt.default = current

    async def on_submit(self, interaction: discord.Interaction):
        await upsert_server_config(
            str(interaction.guild_id),
            system_prompt=self.prompt.value,
            personality_mode="manual",
        )
        await interaction.response.send_message(
            embed=discord.Embed(description="AI personality updated.", color=discord.Color.green()),
            ephemeral=True,
        )


class PersonalityAutoModal(discord.ui.Modal, title="Auto-generate AI Personality"):
    description = discord.ui.TextInput(
        label="Describe your bot in a sentence",
        placeholder="e.g. a grumpy old wizard who reluctantly helps adventurers",
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        raw = self.description.value
        generated = await call_ai(
            None,
            None,
            "You are an expert at writing AI system prompts.",
            [{"role": "user", "content": (
                f"Write a detailed system prompt (2–4 sentences) for an AI with this description: {raw}\n"
                "Output only the system prompt, nothing else."
            )}],
        )
        if not generated:
            await interaction.followup.send("Failed to generate prompt. Try again.", ephemeral=True)
            return
        await upsert_server_config(
            str(interaction.guild_id),
            system_prompt=generated,
            personality_mode="auto",
            personality_auto_prompt=raw,
        )
        await interaction.followup.send(
            embed=discord.Embed(
                title="Personality Auto-generated",
                description=f"**Saved prompt:**\n{generated[:1800]}",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )


class WebhookSetModal(discord.ui.Modal, title="Set Webhook Persona"):
    url = discord.ui.TextInput(label="Webhook URL", placeholder="https://discord.com/api/webhooks/...")
    name = discord.ui.TextInput(label="Display Name", default="Tagokura AI", required=False)
    avatar = discord.ui.TextInput(label="Avatar URL (optional)", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        avatar_val = self.avatar.value.strip()
        await upsert_server_config(
            str(interaction.guild_id),
            webhook_url=self.url.value.strip(),
            webhook_name=self.name.value.strip() or "Tagokura AI",
            webhook_avatar=avatar_val if avatar_val else None,
        )
        await interaction.response.send_message(
            embed=discord.Embed(description="Webhook persona set.", color=discord.Color.green()),
            ephemeral=True,
        )


# ---------------------------------------------------------------------------
# Preset select view
# ---------------------------------------------------------------------------

class PresetSelect(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.select(
        placeholder="Choose a personality preset...",
        options=[
            discord.SelectOption(label=label, value=key)
            for key, label in PRESET_LABELS.items()
        ],
    )
    async def select_preset(self, interaction: discord.Interaction, select: discord.ui.Select):
        preset_key = select.values[0]
        await upsert_server_config(
            str(interaction.guild_id),
            personality_mode="preset",
            personality_preset=preset_key,
        )
        label = PRESET_LABELS.get(preset_key, preset_key)
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"Personality preset set to **{label}**.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )


class AI(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._session: Optional[aiohttp.ClientSession] = None

    async def cog_load(self):
        await init_ai_db()
        self._session = aiohttp.ClientSession()
        if not GEMINI_API_KEY:
            log.warning(
                "GEMINI_API_KEY is not set — AI will only work for servers with a custom API key configured."
            )

    async def cog_unload(self):
        if self._session:
            await self._session.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_config(self, server_id: Optional[str]) -> dict:
        if server_id is None:
            return _default_config()
        cfg = await get_server_config(server_id)
        return cfg or _default_config()

    async def _send_response(
        self,
        message: discord.Message,
        content: str,
        config: dict,
    ) -> None:
        """Send response via webhook persona if configured, otherwise use normal send."""
        webhook_url = config.get("webhook_url")
        if webhook_url and self._session:
            try:
                wh = discord.Webhook.from_url(webhook_url, session=self._session)
                name = config.get("webhook_name") or "Tagokura AI"
                raw_avatar = config.get("webhook_avatar")
                avatar = raw_avatar if raw_avatar and raw_avatar != "None" else None
                for chunk in _chunk(content):
                    await wh.send(chunk, username=name, avatar_url=avatar)
                return
            except Exception as e:
                log.warning("Webhook send failed, falling back to normal send: %s", e)

        reply_mode = config.get("reply_mode", 1)
        mentions_enabled = config.get("mentions_enabled", 0)
        prefix = message.author.mention + " " if mentions_enabled else ""

        chunks = _chunk(content)
        for i, chunk in enumerate(chunks):
            text = (prefix + chunk) if i == 0 else chunk
            if reply_mode:
                await message.reply(text)
            else:
                await message.channel.send(text)

    async def _respond(
        self,
        *,
        message: discord.Message,
        server_id: Optional[str],
        user_id: str,
        channel_id: Optional[str],
        user_content: str,
        config: dict,
    ) -> None:
        """
        Core response pipeline:
        1. Blocklist check
        2. Build prompt + history
        3. Optional web search / URL summarisation injection
        4. Call AI router
        5. Moderation check on response
        6. Save to DB + memory
        7. Send to Discord (chunked / webhook)
        8. Trigger long-term memory summarisation if due
        """
        blocklist = parse_blocklist(config.get("blocklist", "[]"))
        blocked_topic = get_blocked_topic(user_content, blocklist)
        if blocked_topic:
            await message.reply(f"Sorry, I'm not able to discuss **{blocked_topic}** on this server.")
            return

        # Long-term memory
        ltm = await conversation_memory.get_long_term_memory(server_id, user_id)
        base_prompt = _resolve_system_prompt(config)
        system_prompt = build_system_prompt(
            base_prompt,
            language=config.get("language", "auto"),
            tone=config.get("tone", "casual"),
            long_term_memory=ltm,
            response_length=config.get("response_length", "medium"),
            markdown_enabled=int(config.get("markdown_enabled", 1)),
            markdown_frequency=config.get("markdown_frequency", "sometimes"),
            emojis_enabled=int(config.get("emojis_enabled", 1)),
        )

        # Short-term history + current message
        history = conversation_memory.get(server_id, user_id)

        # Auto-inject URL summaries
        urls = _URL_RE.findall(user_content)
        extra_context = ""
        for url in urls[:2]:  # max 2 URLs per message
            summary = await summarize_url(url)
            if summary:
                extra_context += f"\n\n[Content from {url}]:\n{summary[:800]}"

        # Auto web-search if message looks like a factual question and has no URL
        if not urls and "?" in user_content and len(user_content) < 300:
            search_result = await web_search(user_content)
            if search_result:
                extra_context += f"\n\n[Web search results]:\n{search_result[:600]}"

        full_content = user_content + extra_context
        history.append({"role": "user", "content": full_content})
        history = trim_history(history)

        # Call AI
        response_text = await call_ai(
            config.get("model"),
            config.get("api_key"),
            system_prompt,
            history,
            thinking=bool(config.get("thinking_enabled")),
        )

        if response_text is None:
            if not GEMINI_API_KEY and not config.get("api_key"):
                await message.reply(
                    "AI is not configured. Set `GEMINI_API_KEY` in `.env` or configure a custom key with `/ai config apikey`."
                )
            else:
                await message.reply("I couldn't get a response right now. Please try again.")
            return

        # Moderation check on AI response itself
        if is_blocked(response_text, blocklist):
            await message.reply("My response touched a restricted topic and was blocked.")
            return

        # Persist
        conversation_memory.add(server_id, user_id, "user", user_content)
        conversation_memory.add(server_id, user_id, "assistant", response_text)
        asyncio.create_task(save_conversation_turn(server_id, user_id, channel_id, "user", user_content))
        asyncio.create_task(save_conversation_turn(server_id, user_id, channel_id, "assistant", response_text))

        # Send
        await self._send_response(message, response_text, config)

        # Long-term memory summarisation
        if conversation_memory.should_summarize(server_id, user_id):
            asyncio.create_task(self._summarize_memory(server_id, user_id, config))

    async def _summarize_memory(self, server_id: Optional[str], user_id: str, config: dict) -> None:
        """Ask the AI to summarize what it knows about the user and store it."""
        history = conversation_memory.get(server_id, user_id)
        if not history:
            return
        summary_prompt = (
            "Based on the conversation so far, write a concise summary (max 200 words) "
            "of key facts about this user that would be useful to remember in future conversations. "
            "Focus on preferences, interests, and recurring topics."
        )
        history_with_request = history + [{"role": "user", "content": summary_prompt}]
        summary = await call_ai(
            config.get("model"),
            config.get("api_key"),
            "You are a helpful memory assistant.",
            history_with_request,
        )
        if summary:
            await conversation_memory.update_long_term_memory(server_id, user_id, summary)

    # ------------------------------------------------------------------
    # Command groups
    # ------------------------------------------------------------------

    ai_group = app_commands.Group(name="ai", description="AI chatbot commands")

    ai_config_group = app_commands.Group(
        name="config",
        description="Configure AI for this server",
        parent=ai_group,
        default_permissions=discord.Permissions(administrator=True),
    )

    # ------------------------------------------------------------------
    # Admin commands
    # ------------------------------------------------------------------

    @ai_group.command(name="setup", description="Onboarding wizard — create default AI config for this server")
    @app_commands.default_permissions(administrator=True)
    async def ai_setup(self, interaction: discord.Interaction):
        await upsert_server_config(
            str(interaction.guild_id),
            system_prompt="You are a helpful assistant.",
            active_channels="[]",
            language="auto",
            tone="casual",
            blocklist="[]",
            model=None,
            thinking_enabled=0,
        )
        embed = discord.Embed(
            title="AI Setup Complete",
            description=(
                "Default AI configuration created.\n\n"
                "**Next steps:**\n"
                "• `/ai config channel add #channel` — set a channel for the bot to auto-respond in\n"
                "• `/ai config personality` — customise the bot's personality\n"
                "• `/ai config apikey` — add a premium API key (optional)\n\n"
                "The bot will also respond to @mentions anywhere."
            ),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ai_config_group.command(name="personality", description="Set the AI personality (manual, preset, or auto-generate)")
    @app_commands.describe(mode="How to set the personality")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Manual — write your own prompt", value="manual"),
        app_commands.Choice(name="Preset — choose from built-in personalities", value="preset"),
        app_commands.Choice(name="Auto — describe your bot and AI writes the prompt", value="auto"),
    ])
    async def config_personality(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        if mode.value == "manual":
            cfg = await get_server_config(str(interaction.guild_id)) or {}
            current = cfg.get("system_prompt", "") if cfg.get("personality_mode", "manual") == "manual" else ""
            await interaction.response.send_modal(PersonalityManualModal(current=current))
        elif mode.value == "preset":
            await interaction.response.send_message(
                "Choose a personality preset:", view=PresetSelect(), ephemeral=True
            )
        else:  # auto
            await interaction.response.send_modal(PersonalityAutoModal())

    @ai_config_group.command(name="language", description="Set the response language")
    @app_commands.describe(language="Language name (e.g. 'English', 'Japanese') or 'auto'")
    async def config_language(self, interaction: discord.Interaction, language: str):
        await upsert_server_config(str(interaction.guild_id), language=language)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"Language set to **{language}**.", color=discord.Color.green()),
            ephemeral=True,
        )

    @ai_config_group.command(name="tone", description="Set the response tone")
    @app_commands.describe(tone="Tone style")
    @app_commands.choices(tone=[
        app_commands.Choice(name="Casual", value="casual"),
        app_commands.Choice(name="Professional", value="professional"),
        app_commands.Choice(name="Friendly", value="friendly"),
        app_commands.Choice(name="Concise", value="concise"),
        app_commands.Choice(name="Humorous", value="humorous"),
    ])
    async def config_tone(self, interaction: discord.Interaction, tone: app_commands.Choice[str]):
        await upsert_server_config(str(interaction.guild_id), tone=tone.value)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"Tone set to **{tone.name}**.", color=discord.Color.green()),
            ephemeral=True,
        )

    @ai_config_group.command(name="length", description="Set the response length budget")
    @app_commands.describe(length="Target response length")
    @app_commands.choices(length=[
        app_commands.Choice(name="Short (1–3 sentences)", value="short"),
        app_commands.Choice(name="Medium (short paragraph)", value="medium"),
        app_commands.Choice(name="Long (detailed / thorough)", value="long"),
    ])
    async def config_length(self, interaction: discord.Interaction, length: app_commands.Choice[str]):
        await upsert_server_config(str(interaction.guild_id), response_length=length.value)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"Response length set to **{length.name}**.", color=discord.Color.green()),
            ephemeral=True,
        )

    @ai_config_group.command(name="formatting", description="Configure markdown and emoji usage")
    @app_commands.describe(
        markdown="Markdown formatting level",
        emojis="Allow emojis in responses",
    )
    @app_commands.choices(
        markdown=[
            app_commands.Choice(name="Off — plain text only", value="off"),
            app_commands.Choice(name="Sometimes — code blocks and emphasis only", value="sometimes"),
            app_commands.Choice(name="Often — rich formatting freely", value="often"),
        ],
        emojis=[
            app_commands.Choice(name="On", value=1),
            app_commands.Choice(name="Off", value=0),
        ],
    )
    async def config_formatting(
        self,
        interaction: discord.Interaction,
        markdown: app_commands.Choice[str],
        emojis: app_commands.Choice[int],
    ):
        md_enabled = 0 if markdown.value == "off" else 1
        await upsert_server_config(
            str(interaction.guild_id),
            markdown_enabled=md_enabled,
            markdown_frequency=markdown.value if markdown.value != "off" else "sometimes",
            emojis_enabled=emojis.value,
        )
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"Markdown: **{markdown.name}** | Emojis: **{'On' if emojis.value else 'Off'}**",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @ai_config_group.command(name="behaviour", description="Configure mentions, reply style, and typing indicator")
    @app_commands.describe(
        mentions="Mention the user at the start of each reply",
        reply_mode="Use Discord quote-reply vs plain message",
        show_typing="Show typing indicator while generating",
    )
    @app_commands.choices(
        mentions=[
            app_commands.Choice(name="On", value=1),
            app_commands.Choice(name="Off", value=0),
        ],
        reply_mode=[
            app_commands.Choice(name="Quote reply (Discord style)", value=1),
            app_commands.Choice(name="Plain message", value=0),
        ],
        show_typing=[
            app_commands.Choice(name="On", value=1),
            app_commands.Choice(name="Off", value=0),
        ],
    )
    async def config_behaviour(
        self,
        interaction: discord.Interaction,
        mentions: app_commands.Choice[int],
        reply_mode: app_commands.Choice[int],
        show_typing: app_commands.Choice[int],
    ):
        await upsert_server_config(
            str(interaction.guild_id),
            mentions_enabled=mentions.value,
            reply_mode=reply_mode.value,
            show_typing=show_typing.value,
        )
        await interaction.response.send_message(
            embed=discord.Embed(description="Behaviour settings updated.", color=discord.Color.green()),
            ephemeral=True,
        )

    @ai_config_group.command(name="thinking", description="Toggle extended thinking mode (Gemini only)")
    @app_commands.describe(enabled="Enable or disable extended thinking")
    @app_commands.choices(enabled=[
        app_commands.Choice(name="On", value=1),
        app_commands.Choice(name="Off", value=0),
    ])
    async def config_thinking(self, interaction: discord.Interaction, enabled: app_commands.Choice[int]):
        await upsert_server_config(str(interaction.guild_id), thinking_enabled=enabled.value)
        state = "enabled" if enabled.value else "disabled"
        await interaction.response.send_message(
            embed=discord.Embed(description=f"Extended thinking **{state}**.", color=discord.Color.green()),
            ephemeral=True,
        )

    @ai_config_group.command(name="channel-add", description="Add a channel for AI to auto-respond in")
    @app_commands.describe(channel="Channel to add")
    async def channel_add(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = await get_server_config(str(interaction.guild_id)) or {}
        channels = json.loads(cfg.get("active_channels") or "[]")
        cid = str(channel.id)
        if cid not in channels:
            channels.append(cid)
            await upsert_server_config(str(interaction.guild_id), active_channels=json.dumps(channels))
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"{channel.mention} added as an AI channel.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @ai_config_group.command(name="channel-remove", description="Remove an AI auto-response channel")
    @app_commands.describe(channel="Channel to remove")
    async def channel_remove(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = await get_server_config(str(interaction.guild_id)) or {}
        channels = json.loads(cfg.get("active_channels") or "[]")
        cid = str(channel.id)
        if cid in channels:
            channels.remove(cid)
            await upsert_server_config(str(interaction.guild_id), active_channels=json.dumps(channels))
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"{channel.mention} removed.",
                color=discord.Color.orange(),
            ),
            ephemeral=True,
        )

    @ai_config_group.command(name="blocklist-add", description="Add a topic to the blocklist")
    @app_commands.describe(topic="Topic to block")
    async def blocklist_add(self, interaction: discord.Interaction, topic: str):
        cfg = await get_server_config(str(interaction.guild_id)) or {}
        blocklist = json.loads(cfg.get("blocklist") or "[]")
        t = topic.lower().strip()
        if t not in blocklist:
            blocklist.append(t)
            await upsert_server_config(str(interaction.guild_id), blocklist=json.dumps(blocklist))
        await interaction.response.send_message(
            embed=discord.Embed(description=f"**{t}** added to blocklist.", color=discord.Color.orange()),
            ephemeral=True,
        )

    @ai_config_group.command(name="blocklist-remove", description="Remove a topic from the blocklist")
    @app_commands.describe(topic="Topic to unblock")
    async def blocklist_remove(self, interaction: discord.Interaction, topic: str):
        cfg = await get_server_config(str(interaction.guild_id)) or {}
        blocklist = json.loads(cfg.get("blocklist") or "[]")
        t = topic.lower().strip()
        if t in blocklist:
            blocklist.remove(t)
            await upsert_server_config(str(interaction.guild_id), blocklist=json.dumps(blocklist))
        await interaction.response.send_message(
            embed=discord.Embed(description=f"**{t}** removed from blocklist.", color=discord.Color.green()),
            ephemeral=True,
        )

    @ai_config_group.command(name="blocklist-list", description="Show current blocklist")
    async def blocklist_list(self, interaction: discord.Interaction):
        cfg = await get_server_config(str(interaction.guild_id)) or {}
        blocklist = json.loads(cfg.get("blocklist") or "[]")
        desc = "\n".join(f"• {t}" for t in blocklist) if blocklist else "No topics are blocked."
        await interaction.response.send_message(
            embed=discord.Embed(title="Blocked Topics", description=desc, color=discord.Color.orange()),
            ephemeral=True,
        )

    @ai_config_group.command(name="apikey", description="Set a custom AI API key and model")
    @app_commands.describe(
        key="Your API key (will be encrypted at rest)",
        model="Model to use with this key",
    )
    @app_commands.choices(model=[
        app_commands.Choice(name=m, value=m) for m in MODEL_PROVIDERS
    ])
    async def config_apikey(
        self,
        interaction: discord.Interaction,
        key: str,
        model: app_commands.Choice[str],
    ):
        if not os.getenv("ENCRYPTION_KEY"):
            await interaction.response.send_message(
                "**ENCRYPTION_KEY** is not set in `.env`. "
                "Generate one and add it before storing API keys:\n"
                "```\npython -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"\n```",
                ephemeral=True,
            )
            return
        encrypted = encrypt_key(key)
        if not encrypted:
            await interaction.response.send_message("Failed to encrypt key.", ephemeral=True)
            return
        await upsert_server_config(str(interaction.guild_id), api_key=encrypted, model=model.value)
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"API key stored and **{model.value}** set as the active model.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @ai_config_group.command(name="webhook-set", description="Set a webhook persona (custom name and avatar)")
    async def webhook_set(self, interaction: discord.Interaction):
        await interaction.response.send_modal(WebhookSetModal())

    @ai_config_group.command(name="webhook-clear", description="Remove the webhook persona")
    async def webhook_clear(self, interaction: discord.Interaction):
        await upsert_server_config(
            str(interaction.guild_id),
            webhook_url=None,
            webhook_name="Tagokura AI",
            webhook_avatar=None,
        )
        await interaction.response.send_message(
            embed=discord.Embed(description="Webhook persona removed.", color=discord.Color.orange()),
            ephemeral=True,
        )

    @ai_config_group.command(name="show", description="Show current AI configuration")
    async def config_show(self, interaction: discord.Interaction):
        cfg = await get_server_config(str(interaction.guild_id)) or _default_config()
        channels_raw = json.loads(cfg.get("active_channels") or "[]")
        channels_str = " ".join(f"<#{c}>" for c in channels_raw) or "None (mention-only)"
        blocklist = json.loads(cfg.get("blocklist") or "[]")
        embed = discord.Embed(title="AI Configuration", color=discord.Color.purple())
        embed.add_field(name="Model", value=cfg.get("model") or DEFAULT_MODEL, inline=True)
        embed.add_field(name="Language", value=cfg.get("language") or "auto", inline=True)
        embed.add_field(name="Tone", value=cfg.get("tone") or "casual", inline=True)
        embed.add_field(name="Thinking", value="On" if cfg.get("thinking_enabled") else "Off", inline=True)
        embed.add_field(name="Response Length", value=cfg.get("response_length") or "medium", inline=True)
        embed.add_field(name="Custom Key", value="Set" if cfg.get("api_key") else "Not set", inline=True)
        mode = cfg.get("personality_mode", "manual")
        if mode == "preset":
            personality_val = f"Preset: {PRESET_LABELS.get(cfg.get('personality_preset', 'helper'), 'helper')}"
        elif mode == "auto":
            personality_val = f"Auto: {cfg.get('personality_auto_prompt', '')[:60]}"
        else:
            personality_val = (cfg.get("system_prompt") or "")[:120]
        embed.add_field(name="Personality", value=personality_val, inline=False)
        embed.add_field(name="Active Channels", value=channels_str, inline=False)
        md_label = "Off" if not cfg.get("markdown_enabled", 1) else cfg.get("markdown_frequency", "sometimes")
        embed.add_field(name="Markdown", value=md_label, inline=True)
        embed.add_field(name="Emojis", value="On" if cfg.get("emojis_enabled", 1) else "Off", inline=True)
        embed.add_field(name="Mentions", value="On" if cfg.get("mentions_enabled", 0) else "Off", inline=True)
        embed.add_field(name="Reply Mode", value="Quote" if cfg.get("reply_mode", 1) else "Plain", inline=True)
        embed.add_field(name="Typing", value="On" if cfg.get("show_typing", 1) else "Off", inline=True)
        if cfg.get("webhook_url"):
            embed.add_field(name="Webhook", value=cfg.get("webhook_name") or "Tagokura AI", inline=True)
        if blocklist:
            embed.add_field(name="Blocklist", value=", ".join(blocklist), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ai_group.command(name="logs", description="View recent AI conversation logs (admin only)")
    @app_commands.default_permissions(administrator=True)
    async def ai_logs(self, interaction: discord.Interaction):
        rows = await get_recent_logs(str(interaction.guild_id), limit=50)
        if not rows:
            await interaction.response.send_message("No conversation logs yet.", ephemeral=True)
            return
        view = LogsView(rows)
        await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)

    @ai_group.command(name="clear", description="Clear conversation history for this channel")
    async def ai_clear(self, interaction: discord.Interaction):
        conversation_memory.clear(str(interaction.guild_id), str(interaction.user.id))
        await clear_conversations(str(interaction.guild_id), str(interaction.channel_id))
        await interaction.response.send_message(
            embed=discord.Embed(description="Your conversation history has been cleared.", color=discord.Color.orange()),
            ephemeral=True,
        )

    # ------------------------------------------------------------------
    # User commands
    # ------------------------------------------------------------------

    @app_commands.command(name="imagine", description="Generate an image with AI")
    @app_commands.describe(prompt="Describe the image you want")
    async def imagine(self, interaction: discord.Interaction, prompt: str):
        if rate_limiter.is_limited(interaction.user.id, "imagine", limit=3, window=60):
            await interaction.response.send_message(
                "You're generating images too fast. Please wait a moment.", ephemeral=True
            )
            return
        await interaction.response.defer()
        url = await generate_image_fal(prompt)
        if not url:
            await interaction.followup.send("Image generation failed. Please try again.", ephemeral=True)
            return

        source = "fal.ai" if os.getenv("FAL_API_KEY") else "Pollinations.ai"
        embed = discord.Embed(title=prompt[:256], color=discord.Color.purple())
        embed.set_footer(text=f"Generated by {source} for {interaction.user.display_name}")

        # Download the image and attach it directly so Discord always renders it.
        # Embedding a URL from on-demand generators (Pollinations) often fails because
        # Discord fetches the URL before the image is ready.
        try:
            async with aiohttp.ClientSession() as dl_session:
                async with dl_session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        file = discord.File(io.BytesIO(data), filename="imagine.png")
                        embed.set_image(url="attachment://imagine.png")
                        await interaction.followup.send(embed=embed, file=file)
                        return
        except Exception as e:
            log.warning("Failed to download generated image, falling back to URL embed: %s", e)

        # Fallback: send the URL directly (may not render for on-demand services)
        embed.set_image(url=url)
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # on_message — auto-respond to @mentions and AI channels
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # DM handling
        if isinstance(message.channel, discord.DMChannel):
            await self._handle_dm(message)
            return

        if not message.guild:
            return

        # Rate limit
        if rate_limiter.is_limited(message.author.id, "ai_message", limit=10, window=60):
            return

        mentioned = self.bot.user in message.mentions
        server_id = str(message.guild.id)
        config = await self._get_config(server_id)

        active_channels = json.loads(config.get("active_channels") or "[]")
        in_ai_channel = str(message.channel.id) in active_channels

        if not mentioned and not in_ai_channel:
            return

        # Strip @mention
        content = message.content
        if mentioned:
            content = content.replace(f"<@{self.bot.user.id}>", "")
            content = content.replace(f"<@!{self.bot.user.id}>", "")
            content = content.strip()

        if not content and not message.attachments:
            return

        # Append file attachment names/URLs so the AI is aware of them
        if message.attachments:
            attachment_lines = []
            for att in message.attachments:
                attachment_lines.append(f"[Attachment: {att.filename} — {att.url}]")
                if att.content_type and "text" in att.content_type and att.size < 50_000:
                    try:
                        summary = await summarize_url(att.url)
                        if summary:
                            attachment_lines.append(f"[File content preview]:\n{summary[:600]}")
                    except Exception:
                        pass
            content = (content + "\n" + "\n".join(attachment_lines)).strip()

        show_typing = bool(config.get("show_typing", 1))
        if show_typing:
            async with message.channel.typing():
                await self._respond(
                    message=message,
                    server_id=server_id,
                    user_id=str(message.author.id),
                    channel_id=str(message.channel.id),
                    user_content=content or "(no text)",
                    config=config,
                )
        else:
            await self._respond(
                message=message,
                server_id=server_id,
                user_id=str(message.author.id),
                channel_id=str(message.channel.id),
                user_content=content or "(no text)",
                config=config,
            )

    async def _handle_dm(self, message: discord.Message):
        if rate_limiter.is_limited(message.author.id, "ai_dm", limit=5, window=60):
            return

        content = message.content.strip()
        if not content:
            return

        config = _default_config()

        async with message.channel.typing():
            await self._respond(
                message=message,
                server_id=None,
                user_id=str(message.author.id),
                channel_id=str(message.channel.id),
                user_content=content,
                config=config,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(AI(bot))
