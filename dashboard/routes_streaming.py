from __future__ import annotations

from datetime import datetime, timezone

import discord
from quart import Blueprint, current_app, redirect, render_template, request, url_for, flash

from .auth import login_required
from . import db

streaming_bp = Blueprint("streaming", __name__)


@streaming_bp.route("/")
@login_required
async def streaming_list():
    bot = current_app.bot
    guilds = sorted(bot.guilds, key=lambda g: g.name.lower()) if bot else []
    streamer_counts = {}
    for guild in guilds:
        configs = await db.get_streaming_configs(str(guild.id))
        streamer_counts[guild.id] = len(configs)
    return await render_template("streaming.html", guilds=guilds, streamer_counts=streamer_counts)


@streaming_bp.route("/<int:guild_id>")
@login_required
async def streaming_edit(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("streaming.streaming_list"))

    configs = await db.get_streaming_configs(str(guild_id))
    channels = sorted(guild.text_channels, key=lambda c: c.position)
    roles = sorted(guild.roles, key=lambda r: r.position, reverse=True)

    return await render_template(
        "streaming_edit.html",
        guild=guild,
        configs=configs,
        channels=channels,
        roles=roles,
    )


@streaming_bp.route("/<int:guild_id>/add", methods=["POST"])
@login_required
async def streaming_add(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("streaming.streaming_list"))

    form = await request.form
    url = form.get("streamer_url", "").strip()
    channel_id = form.get("channel_id", "")

    if not url or not channel_id:
        await flash("Please provide both a URL and a channel.", "danger")
        return redirect(url_for("streaming.streaming_edit", guild_id=guild_id))

    # Import parsing from the cog
    from cogs.streaming import Streaming
    parsed = Streaming.parse_streamer_url(url)
    if not parsed:
        await flash("Invalid URL. Use twitch.tv/username or youtube.com/channel/ID or youtube.com/@handle", "danger")
        return redirect(url_for("streaming.streaming_edit", guild_id=guild_id))

    platform, username, canonical_url = parsed

    # Resolve @handle to UC... channel ID for YouTube
    if platform == "youtube" and not username.startswith("UC"):
        import aiohttp
        from cogs.streaming import _resolve_youtube_channel_id
        async with aiohttp.ClientSession() as session:
            resolved = await _resolve_youtube_channel_id(session, username)
        if not resolved:
            await flash(f"Could not resolve YouTube handle @{username} to a channel ID.", "danger")
            return redirect(url_for("streaming.streaming_edit", guild_id=guild_id))
        username = resolved
        canonical_url = f"https://youtube.com/channel/{resolved}"

    mention_role_id = form.get("mention_role_id", "") or None

    result = await db.add_streaming_config(
        guild_id=str(guild_id),
        channel_id=channel_id,
        streamer_url=canonical_url,
        streamer_name=username,
        platform=platform,
        mention_role_id=mention_role_id,
    )
    if result is None:
        await flash("This streamer is already tracked in this server.", "warning")
    else:
        await flash(f"Now tracking {username} ({platform.title()}).", "success")

    return redirect(url_for("streaming.streaming_edit", guild_id=guild_id))


@streaming_bp.route("/<int:guild_id>/role/<int:config_id>", methods=["POST"])
@login_required
async def streaming_update_role(guild_id: int, config_id: int):
    configs = await db.get_streaming_configs(str(guild_id))
    if not any(c["id"] == config_id for c in configs):
        await flash("Streamer config not found in this server.", "danger")
        return redirect(url_for("streaming.streaming_edit", guild_id=guild_id))

    form = await request.form
    mention_role_id = form.get("mention_role_id", "") or None
    await db.update_streaming_mention_role(config_id, mention_role_id)
    await flash("Mention role updated.", "success")
    return redirect(url_for("streaming.streaming_edit", guild_id=guild_id))


@streaming_bp.route("/<int:guild_id>/remove/<int:config_id>", methods=["POST"])
@login_required
async def streaming_remove(guild_id: int, config_id: int):
    # Verify config belongs to this guild (IDOR protection)
    configs = await db.get_streaming_configs(str(guild_id))
    if not any(c["id"] == config_id for c in configs):
        await flash("Streamer config not found in this server.", "danger")
        return redirect(url_for("streaming.streaming_edit", guild_id=guild_id))
    await db.remove_streaming_config(config_id)
    await flash("Streamer removed.", "success")
    return redirect(url_for("streaming.streaming_edit", guild_id=guild_id))


@streaming_bp.route("/<int:guild_id>/test", methods=["POST"])
@login_required
async def streaming_test(guild_id: int):
    bot = current_app.bot
    guild = bot.get_guild(guild_id) if bot else None
    if not guild:
        await flash("Server not found.", "danger")
        return redirect(url_for("streaming.streaming_list"))

    form = await request.form
    channel_id = form.get("test_channel_id", "")
    if not channel_id:
        await flash("Please select a channel for the test notification.", "warning")
        return redirect(url_for("streaming.streaming_edit", guild_id=guild_id))

    channel = guild.get_channel(int(channel_id))
    if not channel:
        await flash("Channel not found.", "danger")
        return redirect(url_for("streaming.streaming_edit", guild_id=guild_id))

    # Check if any streamer configs for this guild have a mention role
    configs = await db.get_streaming_configs(str(guild_id))
    mention_role_id = None
    for cfg in configs:
        if cfg.get("mention_role_id"):
            mention_role_id = cfg["mention_role_id"]
            break
    content = f"<@&{mention_role_id}>" if mention_role_id else None

    sent = 0

    # Twitch example
    twitch_embed = discord.Embed(
        title="ExampleStreamer is live on Twitch!",
        url="https://twitch.tv/examplestreamer",
        description="Playing Valorant - Ranked Grind!",
        color=0x9146FF,
    )
    twitch_embed.add_field(name="Game", value="Valorant", inline=True)
    twitch_embed.add_field(name="Viewers", value="1,234", inline=True)
    twitch_embed.set_image(url="https://static-cdn.jtvnw.net/previews-ttv/live_user_examplestreamer-440x248.jpg")
    twitch_embed.set_footer(text="Twitch Go-Live (TEST)")
    twitch_embed.timestamp = datetime.now(timezone.utc)
    try:
        await channel.send(content=content, embed=twitch_embed)
        sent += 1
    except discord.HTTPException:
        pass

    # YouTube example
    yt_embed = discord.Embed(
        title="TechChannel uploaded a new video!",
        url="https://youtube.com/watch?v=dQw4w9WgXcQ",
        description="Building a Mass Production Server - Full Guide 2025",
        color=0xFF0000,
    )
    yt_embed.set_thumbnail(url="https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg")
    yt_embed.set_footer(text="YouTube Upload (TEST)")
    yt_embed.timestamp = datetime.now(timezone.utc)
    try:
        await channel.send(content=content, embed=yt_embed)
        sent += 1
    except discord.HTTPException:
        pass

    if sent:
        await flash(f"Sent {sent} test notification(s) to #{channel.name}.", "success")
    else:
        await flash("Failed to send test notifications. Check bot permissions.", "danger")
    return redirect(url_for("streaming.streaming_edit", guild_id=guild_id))
