from __future__ import annotations

import json

from quart import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .auth import login_required
from utils.ai_db import (
    get_server_config,
    upsert_server_config,
    get_recent_logs,
    clear_conversations,
    get_all_user_memories,
    delete_user_memory,
)
from utils.ai_router import call_ai, encrypt_key, MODEL_PROVIDERS

ai_bp = Blueprint("ai", __name__)


@ai_bp.route("/")
@login_required
async def ai_list():
    bot = current_app.bot
    guilds = sorted(bot.guilds, key=lambda g: g.name.lower()) if bot else []
    configs = {}
    for g in guilds:
        cfg = await get_server_config(str(g.id))
        configs[g.id] = cfg
    return await render_template("ai.html", guilds=guilds, configs=configs)


@ai_bp.route("/<int:guild_id>", methods=["GET"])
@login_required
async def ai_edit(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("ai.ai_list"))
    cfg = await get_server_config(str(guild_id)) or {}
    active_channels_raw = json.loads(cfg.get("active_channels") or "[]")
    blocklist = json.loads(cfg.get("blocklist") or "[]")
    channels = [c for c in guild.text_channels]
    from cogs.ai import PERSONALITY_PRESETS, PRESET_LABELS
    return await render_template(
        "ai_edit.html",
        guild=guild,
        cfg=cfg,
        channels=channels,
        active_channels=active_channels_raw,
        blocklist=blocklist,
        models=list(MODEL_PROVIDERS.keys()),
        model_groups={
            "🆓 Groq (Free)": [m for m, p in MODEL_PROVIDERS.items() if p == "groq"],
            "✦ Gemini": [m for m, p in MODEL_PROVIDERS.items() if p == "gemini"],
            "✦ Anthropic (Claude)": [m for m, p in MODEL_PROVIDERS.items() if p == "anthropic"],
            "✦ OpenAI": [m for m, p in MODEL_PROVIDERS.items() if p == "openai"],
        },
        preset_labels=PRESET_LABELS,
        presets=list(PERSONALITY_PRESETS.keys()),
    )


@ai_bp.route("/<int:guild_id>", methods=["POST"])
@login_required
async def ai_save(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("ai.ai_list"))

    form = await request.form
    # Active channels — multi-select checkbox values
    selected_channels = form.getlist("active_channels")
    blocklist_raw = form.get("blocklist", "")
    blocklist = [t.strip().lower() for t in blocklist_raw.split(",") if t.strip()]

    # Personality mode handling
    personality_mode = form.get("personality_mode", "manual")
    system_prompt = form.get("system_prompt", "You are a helpful assistant.")
    personality_auto_prompt = form.get("personality_auto_prompt", "").strip()
    if personality_mode == "auto" and personality_auto_prompt:
        generated = await call_ai(
            None,
            None,
            "You are an expert at writing AI system prompts.",
            [{"role": "user", "content": (
                f"Write a detailed system prompt (2–4 sentences) for an AI with this description: {personality_auto_prompt}\n"
                "Output only the system prompt, nothing else."
            )}],
        )
        if generated:
            system_prompt = generated

    update_kwargs: dict = {
        "system_prompt": system_prompt,
        "active_channels": json.dumps(selected_channels),
        "language": form.get("language", "auto"),
        "tone": form.get("tone", "casual"),
        "blocklist": json.dumps(blocklist),
        "thinking_enabled": int("thinking_enabled" in form),
        "response_length": form.get("response_length", "medium"),
        "personality_mode": personality_mode,
        "personality_preset": form.get("personality_preset", "helper"),
        "personality_auto_prompt": personality_auto_prompt,
        "markdown_enabled": int(form.get("markdown", "sometimes") != "off"),
        "markdown_frequency": form.get("markdown", "sometimes") if form.get("markdown", "sometimes") != "off" else "sometimes",
        "emojis_enabled": int("emojis_enabled" in form),
        "mentions_enabled": int("mentions_enabled" in form),
        "reply_mode": int("reply_mode" in form),
        "show_typing": int("show_typing" in form),
        "webhook_name": form.get("webhook_name", "").strip() or "Tagokura AI",
        "webhook_avatar": form.get("webhook_avatar", "").strip() or None,
    }

    # Webhook URL — only update if provided; keep existing if blank
    new_webhook_url = form.get("webhook_url", "").strip()
    if new_webhook_url:
        update_kwargs["webhook_url"] = new_webhook_url
    elif "webhook_clear" in form:
        update_kwargs["webhook_url"] = None

    model_val = form.get("model", "").strip()
    if model_val:
        update_kwargs["model"] = model_val

    # API key — only update if a new value was provided
    new_key = form.get("api_key", "").strip()
    if new_key:
        encrypted = encrypt_key(new_key)
        if encrypted:
            update_kwargs["api_key"] = encrypted
        else:
            await flash("ENCRYPTION_KEY not set — API key not saved.", "warning")

    await upsert_server_config(str(guild_id), **update_kwargs)
    await flash("AI configuration saved.", "success")
    return redirect(url_for("ai.ai_edit", guild_id=guild_id))


@ai_bp.route("/<int:guild_id>/logs", methods=["GET"])
@login_required
async def ai_logs(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("ai.ai_list"))
    user_filter = request.args.get("user_id")
    channel_filter = request.args.get("channel_id")
    rows = await get_recent_logs(
        str(guild_id),
        user_id=user_filter or None,
        channel_id=channel_filter or None,
        limit=100,
    )
    channels = guild.text_channels
    return await render_template(
        "ai_logs.html",
        guild=guild,
        rows=rows,
        channels=channels,
        user_filter=user_filter or "",
        channel_filter=channel_filter or "",
    )


@ai_bp.route("/<int:guild_id>/logs/clear", methods=["POST"])
@login_required
async def ai_logs_clear(guild_id: int):
    await clear_conversations(str(guild_id))
    await flash("All conversation logs cleared.", "success")
    return redirect(url_for("ai.ai_logs", guild_id=guild_id))


@ai_bp.route("/<int:guild_id>/memory", methods=["GET"])
@login_required
async def ai_memory(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("ai.ai_list"))
    memories = await get_all_user_memories(str(guild_id))
    return await render_template("ai_memory.html", guild=guild, memories=memories)


@ai_bp.route("/<int:guild_id>/memory/<user_id>/delete", methods=["POST"])
@login_required
async def ai_memory_delete(guild_id: int, user_id: str):
    await delete_user_memory(user_id, str(guild_id))
    await flash("Memory deleted.", "success")
    return redirect(url_for("ai.ai_memory", guild_id=guild_id))
