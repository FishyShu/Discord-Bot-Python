from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import aiosqlite

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "bot.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS custom_commands (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    TEXT,               -- NULL = global
    name        TEXT NOT NULL,
    type        TEXT NOT NULL DEFAULT 'text',  -- text | embed | auto_reply | contains_link | contains_file | contains_emoji | contains_role_mention
    trigger_pattern TEXT,           -- for auto_reply: regex or substring
    response_text   TEXT,
    embed_json      TEXT,           -- JSON string for embed fields
    enabled     INTEGER NOT NULL DEFAULT 1,
    cooldown         INTEGER NOT NULL DEFAULT 0,
    required_role_id TEXT,
    usage_count      INTEGER NOT NULL DEFAULT 0,
    tts              INTEGER NOT NULL DEFAULT 0,
    filter_has_link         INTEGER NOT NULL DEFAULT 0,
    filter_has_file         INTEGER NOT NULL DEFAULT 0,
    filter_has_emoji        INTEGER NOT NULL DEFAULT 0,
    filter_has_role_mention INTEGER NOT NULL DEFAULT 0,
    attachment_path    TEXT,
    embed_image_path   TEXT,
    embed_thumbnail_path TEXT,
    match_mode  TEXT NOT NULL DEFAULT 'contains',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bot_settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id TEXT NOT NULL,
    key      TEXT NOT NULL,
    value    TEXT,
    PRIMARY KEY (guild_id, key)
);

CREATE TABLE IF NOT EXISTS welcome_config (
    guild_id TEXT PRIMARY KEY,
    welcome_channel_id TEXT, welcome_message TEXT, welcome_embed_json TEXT,
    welcome_enabled INTEGER NOT NULL DEFAULT 0,
    goodbye_channel_id TEXT, goodbye_message TEXT, goodbye_embed_json TEXT,
    goodbye_enabled INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS audit_config (
    guild_id TEXT PRIMARY KEY,
    log_channel_id TEXT,
    log_edits INTEGER NOT NULL DEFAULT 1, log_deletes INTEGER NOT NULL DEFAULT 1,
    log_joins INTEGER NOT NULL DEFAULT 1, log_leaves INTEGER NOT NULL DEFAULT 1,
    log_role_changes INTEGER NOT NULL DEFAULT 1,
    log_ghost_pings INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS autotranslate_config (
    guild_id    TEXT PRIMARY KEY,
    channel_id  TEXT NOT NULL,
    target_lang TEXT NOT NULL DEFAULT 'en',
    enabled     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS giveaways (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id     TEXT NOT NULL,
    channel_id   TEXT NOT NULL,
    message_id   TEXT,
    prize        TEXT NOT NULL,
    winner_count INTEGER NOT NULL DEFAULT 1,
    ends_at      TEXT NOT NULL,
    ended        INTEGER NOT NULL DEFAULT 0,
    winners      TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS warnings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id     TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    moderator_id TEXT NOT NULL,
    reason       TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS antiraid_config (
    guild_id               TEXT PRIMARY KEY,
    enabled                INTEGER NOT NULL DEFAULT 0,
    mass_join_enabled      INTEGER NOT NULL DEFAULT 1,
    mass_join_threshold    INTEGER NOT NULL DEFAULT 10,
    new_account_enabled    INTEGER NOT NULL DEFAULT 0,
    new_account_days       INTEGER NOT NULL DEFAULT 7,
    mention_spam_enabled   INTEGER NOT NULL DEFAULT 1,
    mention_spam_threshold INTEGER NOT NULL DEFAULT 5,
    message_spam_enabled   INTEGER NOT NULL DEFAULT 1,
    message_spam_threshold INTEGER NOT NULL DEFAULT 8,
    action                 TEXT NOT NULL DEFAULT 'timeout'
);

CREATE TABLE IF NOT EXISTS reaction_roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT NOT NULL, channel_id TEXT NOT NULL,
    message_id TEXT NOT NULL, emoji TEXT NOT NULL, role_id TEXT NOT NULL,
    UNIQUE(message_id, emoji)
);

CREATE TABLE IF NOT EXISTS xp_config (
    guild_id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    xp_per_message INTEGER NOT NULL DEFAULT 15,
    xp_cooldown INTEGER NOT NULL DEFAULT 60,
    levelup_channel_id TEXT,
    levelup_message TEXT DEFAULT 'Congrats {user}, you reached level {level}!'
);

CREATE TABLE IF NOT EXISTS xp_users (
    guild_id TEXT NOT NULL, user_id TEXT NOT NULL,
    xp INTEGER NOT NULL DEFAULT 0, level INTEGER NOT NULL DEFAULT 0,
    last_xp_at TEXT,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS xp_role_rewards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT NOT NULL, level INTEGER NOT NULL, role_id TEXT NOT NULL,
    UNIQUE(guild_id, level)
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT NOT NULL, channel_id TEXT NOT NULL, user_id TEXT NOT NULL,
    message TEXT NOT NULL, remind_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS autoroles (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT NOT NULL,
    role_id  TEXT NOT NULL,
    UNIQUE(guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS freestuff_config (
    guild_id    TEXT PRIMARY KEY,
    channel_id  TEXT,
    enabled     INTEGER NOT NULL DEFAULT 1,
    platforms   TEXT NOT NULL DEFAULT '["steam","epic","gog","ubisoft","origin","humble","other"]',
    min_rating  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS free_games (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    url             TEXT NOT NULL UNIQUE,
    platform        TEXT NOT NULL,
    image_url       TEXT,
    original_price  TEXT,
    source          TEXT NOT NULL,
    discovered_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS twitch_drops_config (
    guild_id    TEXT PRIMARY KEY,
    channel_id  TEXT,
    enabled     INTEGER NOT NULL DEFAULT 1,
    game_filter TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS twitch_drops_cache (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    drop_id       TEXT NOT NULL UNIQUE,
    game_name     TEXT NOT NULL,
    game_id       TEXT,
    drop_name     TEXT NOT NULL,
    description   TEXT,
    start_date    TEXT,
    end_date      TEXT,
    image_url     TEXT,
    details_url   TEXT,
    discovered_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS streaming_config (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id        TEXT NOT NULL,
    channel_id      TEXT NOT NULL,
    streamer_url    TEXT NOT NULL,
    streamer_name   TEXT NOT NULL,
    platform        TEXT NOT NULL,
    last_notified   TEXT,
    last_stream_id  TEXT,
    enabled         INTEGER NOT NULL DEFAULT 1,
    UNIQUE(guild_id, streamer_url)
);

CREATE TABLE IF NOT EXISTS xp_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    xp_gained INTEGER NOT NULL,
    total_xp INTEGER NOT NULL,
    level INTEGER NOT NULL,
    channel_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_xp_log_guild ON xp_log(guild_id, created_at DESC);

CREATE TABLE IF NOT EXISTS modlog (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id     TEXT NOT NULL,
    action       TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    moderator_id TEXT NOT NULL,
    reason       TEXT,
    extra        TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_modlog_guild ON modlog(guild_id);
CREATE INDEX IF NOT EXISTS idx_modlog_user  ON modlog(guild_id, user_id);

CREATE TABLE IF NOT EXISTS track_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   TEXT NOT NULL,
    title      TEXT NOT NULL,
    url        TEXT NOT NULL,
    source     TEXT,
    requester  TEXT,
    played_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_track_history_guild ON track_history(guild_id, played_at DESC);

CREATE TABLE IF NOT EXISTS ai_config (
    guild_id      TEXT PRIMARY KEY,
    enabled       INTEGER NOT NULL DEFAULT 0,
    ai_channel_id TEXT,
    personality   TEXT NOT NULL DEFAULT 'You are a helpful and friendly Discord bot assistant.',
    model         TEXT NOT NULL DEFAULT 'gemini-2.0-flash',
    max_history   INTEGER NOT NULL DEFAULT 20
);

CREATE TABLE IF NOT EXISTS ai_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ai_history_channel ON ai_history(guild_id, channel_id, created_at DESC);

CREATE TABLE IF NOT EXISTS soundboard_config (
    guild_id        TEXT PRIMARY KEY,
    volume_mode     TEXT NOT NULL DEFAULT 'off',
    fixed_volume    REAL NOT NULL DEFAULT 0.8
);

CREATE TABLE IF NOT EXISTS fun_config (
    guild_id         TEXT NOT NULL,
    command          TEXT NOT NULL,
    enabled          INTEGER NOT NULL DEFAULT 1,
    allowed_channels TEXT NOT NULL DEFAULT '[]',
    cooldown         INTEGER NOT NULL DEFAULT 0,
    allowed_roles    TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (guild_id, command)
);
"""


async def init_db():
    """Create the database and tables if they don't exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.execute("PRAGMA journal_mode=WAL")
        await db.executescript("""
            CREATE INDEX IF NOT EXISTS idx_reminders_remind_at ON reminders(remind_at);
            CREATE INDEX IF NOT EXISTS idx_xp_users_guild_xp ON xp_users(guild_id, xp DESC);
            CREATE INDEX IF NOT EXISTS idx_custom_commands_guild ON custom_commands(guild_id);
            CREATE INDEX IF NOT EXISTS idx_reaction_roles_message ON reaction_roles(message_id, emoji);
            CREATE INDEX IF NOT EXISTS idx_autoroles_guild ON autoroles(guild_id);
            CREATE INDEX IF NOT EXISTS idx_free_games_discovered ON free_games(discovered_at DESC);
            CREATE INDEX IF NOT EXISTS idx_streaming_config_guild ON streaming_config(guild_id);
            CREATE INDEX IF NOT EXISTS idx_twitch_drops_cache_discovered ON twitch_drops_cache(discovered_at DESC);
        """)
        # Migrate existing databases: add new columns safely
        for col, definition in [
            ("cooldown", "INTEGER NOT NULL DEFAULT 0"),
            ("required_role_id", "TEXT"),
            ("usage_count", "INTEGER NOT NULL DEFAULT 0"),
            ("tts", "INTEGER NOT NULL DEFAULT 0"),
            ("filter_has_link", "INTEGER NOT NULL DEFAULT 0"),
            ("filter_has_file", "INTEGER NOT NULL DEFAULT 0"),
            ("filter_has_emoji", "INTEGER NOT NULL DEFAULT 0"),
            ("filter_has_role_mention", "INTEGER NOT NULL DEFAULT 0"),
            ("attachment_path", "TEXT"),
            ("embed_image_path", "TEXT"),
            ("embed_thumbnail_path", "TEXT"),
            ("use_regex", "INTEGER DEFAULT 0"),
            ("trigger_patterns", "TEXT"),
            ("reaction_emojis", "TEXT"),
            ("auto_delete_seconds", "INTEGER DEFAULT 0"),
            ("delete_trigger", "INTEGER DEFAULT 0"),
            ("mod_action", "TEXT"),
            ("mod_action_value", "TEXT"),
            ("response_image_url", "TEXT"),
            ("priority", "INTEGER DEFAULT 0"),
            ("no_prefix", "INTEGER DEFAULT 0"),
            ("match_mode", "TEXT DEFAULT 'contains'"),
        ]:
            try:
                await db.execute(f"ALTER TABLE custom_commands ADD COLUMN {col} {definition}")
            except aiosqlite.OperationalError:
                pass
        # Add fail_count to reminders for retry tracking
        try:
            await db.execute("ALTER TABLE reminders ADD COLUMN fail_count INTEGER NOT NULL DEFAULT 0")
        except aiosqlite.OperationalError:
            pass  # column already exists
        # Add level-up image columns to xp_config
        for col, definition in [
            ("levelup_image_path", "TEXT"),
            ("levelup_image_url", "TEXT"),
        ]:
            try:
                await db.execute(f"ALTER TABLE xp_config ADD COLUMN {col} {definition}")
            except aiosqlite.OperationalError:
                pass
        # Add mention_role_id to announcement configs
        for table in ["freestuff_config", "twitch_drops_config", "streaming_config"]:
            try:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN mention_role_id TEXT")
            except aiosqlite.OperationalError:
                pass
        # Add log_ghost_pings to audit_config
        try:
            await db.execute("ALTER TABLE audit_config ADD COLUMN log_ghost_pings INTEGER NOT NULL DEFAULT 0")
        except aiosqlite.OperationalError:
            pass
        # Add content_filters to freestuff_config
        try:
            await db.execute(
                "ALTER TABLE freestuff_config ADD COLUMN content_filters TEXT NOT NULL DEFAULT "
                "'[\"free_to_keep\",\"free_weekend\",\"other_freebies\",\"gamedev_assets\",\"giveaways_rewards\"]'"
            )
        except aiosqlite.OperationalError:
            pass
        # Add embed customization columns to freestuff_config
        for col, definition in [
            ("embed_show_price",    "INTEGER NOT NULL DEFAULT 1"),
            ("embed_show_category", "INTEGER NOT NULL DEFAULT 1"),
            ("embed_show_platform", "INTEGER NOT NULL DEFAULT 1"),
            ("embed_show_expiry",   "INTEGER NOT NULL DEFAULT 1"),
            ("embed_show_image",    "INTEGER NOT NULL DEFAULT 1"),
            ("embed_color",         "TEXT"),
        ]:
            try:
                await db.execute(f"ALTER TABLE freestuff_config ADD COLUMN {col} {definition}")
            except aiosqlite.OperationalError:
                pass
        # Add platform_mention_roles to freestuff_config
        try:
            await db.execute(
                "ALTER TABLE freestuff_config ADD COLUMN platform_mention_roles TEXT NOT NULL DEFAULT '{}'"
            )
        except aiosqlite.OperationalError:
            pass
        # Add category to free_games
        try:
            await db.execute("ALTER TABLE free_games ADD COLUMN category TEXT NOT NULL DEFAULT 'free_to_keep'")
        except aiosqlite.OperationalError:
            pass
        # Add source_url and description to free_games
        for col, definition in [
            ("source_url",  "TEXT"),
            ("description", "TEXT"),
            ("gp_type",     "TEXT"),
        ]:
            try:
                await db.execute(f"ALTER TABLE free_games ADD COLUMN {col} {definition}")
            except aiosqlite.OperationalError:
                pass
        # Add new feature columns to freestuff_config
        for col, definition in [
            ("use_epic_api",           "INTEGER NOT NULL DEFAULT 1"),
            ("use_reddit",             "INTEGER NOT NULL DEFAULT 0"),
            ("use_gamerpower",         "INTEGER NOT NULL DEFAULT 1"),
            ("link_type",              "TEXT NOT NULL DEFAULT 'store'"),
            ("embed_show_client_link", "INTEGER NOT NULL DEFAULT 1"),
            ("embed_show_description", "INTEGER NOT NULL DEFAULT 1"),
            ("embed_clean_titles",     "INTEGER NOT NULL DEFAULT 0"),
            ("use_gg_deals",           "INTEGER NOT NULL DEFAULT 0"),
        ]:
            try:
                await db.execute(f"ALTER TABLE freestuff_config ADD COLUMN {col} {definition}")
            except aiosqlite.OperationalError:
                pass
        # Add embed customization columns to twitch_drops_config
        for col, definition in [
            ("embed_show_game",        "INTEGER NOT NULL DEFAULT 1"),
            ("embed_show_period",      "INTEGER NOT NULL DEFAULT 1"),
            ("embed_show_description", "INTEGER NOT NULL DEFAULT 1"),
            ("embed_show_image",       "INTEGER NOT NULL DEFAULT 1"),
            ("embed_show_link",        "INTEGER NOT NULL DEFAULT 1"),
            ("embed_color",            "TEXT"),
        ]:
            try:
                await db.execute(f"ALTER TABLE twitch_drops_config ADD COLUMN {col} {definition}")
            except aiosqlite.OperationalError:
                pass
        # soundboard_config columns (table created by SCHEMA; add column if older DBs lack it)
        try:
            await db.execute("ALTER TABLE soundboard_config ADD COLUMN fixed_volume REAL NOT NULL DEFAULT 0.8")
        except aiosqlite.OperationalError:
            pass
        # Add pending_reset to freestuff_config for per-guild reset
        try:
            await db.execute("ALTER TABLE freestuff_config ADD COLUMN pending_reset INTEGER NOT NULL DEFAULT 0")
        except aiosqlite.OperationalError:
            pass
        await db.commit()


def _connect():
    """Return an aiosqlite connection context manager with Row factory."""
    return _ConnectionCM()


class _ConnectionCM:
    """Async context manager that opens an aiosqlite connection with row_factory set."""

    async def __aenter__(self):
        self._db = await aiosqlite.connect(DB_PATH)
        self._db.row_factory = aiosqlite.Row
        return self._db

    async def __aexit__(self, *exc):
        await self._db.close()


# --------------- Custom Commands ---------------

async def get_commands(guild_id: Optional[str] = None) -> list[dict]:
    """Get all commands, optionally filtered by guild_id. Includes global (NULL guild_id)."""
    async with _connect() as db:
        if guild_id:
            cursor = await db.execute(
                "SELECT * FROM custom_commands WHERE guild_id IS NULL OR guild_id = ? ORDER BY name",
                (guild_id,),
            )
        else:
            cursor = await db.execute("SELECT * FROM custom_commands ORDER BY name")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_command(cmd_id: int) -> Optional[dict]:
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM custom_commands WHERE id = ?", (cmd_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def create_command(*, guild_id: Optional[str], name: str, type: str = "text",
                         trigger_pattern: Optional[str] = None, response_text: Optional[str] = None,
                         embed_json: Optional[str] = None, enabled: bool = True,
                         cooldown: int = 0, required_role_id: Optional[str] = None,
                         tts: bool = False,
                         filter_has_link: bool = False, filter_has_file: bool = False,
                         filter_has_emoji: bool = False, filter_has_role_mention: bool = False,
                         attachment_path: Optional[str] = None,
                         embed_image_path: Optional[str] = None,
                         embed_thumbnail_path: Optional[str] = None,
                         use_regex: bool = False,
                         trigger_patterns: Optional[str] = None,
                         reaction_emojis: Optional[str] = None,
                         auto_delete_seconds: int = 0,
                         delete_trigger: bool = False,
                         mod_action: Optional[str] = None,
                         mod_action_value: Optional[str] = None,
                         response_image_url: Optional[str] = None,
                         priority: int = 0,
                         no_prefix: bool = False,
                         match_mode: str = "contains") -> int:
    async with _connect() as db:
        cursor = await db.execute(
            """INSERT INTO custom_commands
               (guild_id, name, type, trigger_pattern, response_text, embed_json, enabled,
                cooldown, required_role_id, tts,
                filter_has_link, filter_has_file, filter_has_emoji, filter_has_role_mention,
                attachment_path, embed_image_path, embed_thumbnail_path,
                use_regex, trigger_patterns, reaction_emojis, auto_delete_seconds,
                delete_trigger, mod_action, mod_action_value, response_image_url, priority,
                no_prefix, match_mode)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (guild_id, name, type, trigger_pattern, response_text, embed_json,
             int(enabled), cooldown, required_role_id, int(tts),
             int(filter_has_link), int(filter_has_file), int(filter_has_emoji),
             int(filter_has_role_mention), attachment_path, embed_image_path,
             embed_thumbnail_path, int(use_regex), trigger_patterns, reaction_emojis,
             auto_delete_seconds, int(delete_trigger), mod_action, mod_action_value,
             response_image_url, priority, int(no_prefix), match_mode),
        )
        await db.commit()
        return cursor.lastrowid


async def increment_usage_count(cmd_id: int) -> None:
    async with _connect() as db:
        await db.execute(
            "UPDATE custom_commands SET usage_count = usage_count + 1 WHERE id = ?",
            (cmd_id,),
        )
        await db.commit()


async def update_command(cmd_id: int, **kwargs) -> bool:
    allowed = {"guild_id", "name", "type", "trigger_pattern", "response_text",
               "embed_json", "enabled", "cooldown", "required_role_id", "tts",
               "filter_has_link", "filter_has_file", "filter_has_emoji",
               "filter_has_role_mention", "attachment_path", "embed_image_path",
               "embed_thumbnail_path", "use_regex", "trigger_patterns",
               "reaction_emojis", "auto_delete_seconds", "delete_trigger",
               "mod_action", "mod_action_value", "response_image_url", "priority",
               "no_prefix", "match_mode"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return False
    if "enabled" in fields:
        fields["enabled"] = int(fields["enabled"])
    if "tts" in fields:
        fields["tts"] = int(fields["tts"])
    for bk in ("filter_has_link", "filter_has_file", "filter_has_emoji",
                "filter_has_role_mention", "use_regex", "delete_trigger", "no_prefix"):
        if bk in fields:
            fields[bk] = int(fields[bk])
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [cmd_id]
    async with _connect() as db:
        cursor = await db.execute(f"UPDATE custom_commands SET {sets} WHERE id = ?", vals)
        await db.commit()
        return cursor.rowcount > 0


async def delete_command(cmd_id: int) -> bool:
    async with _connect() as db:
        cursor = await db.execute("DELETE FROM custom_commands WHERE id = ?", (cmd_id,))
        await db.commit()
        return cursor.rowcount > 0


async def delete_command_by_name_and_guild(guild_id: str, name: str) -> bool:
    async with _connect() as db:
        cursor = await db.execute(
            "DELETE FROM custom_commands WHERE guild_id = ? AND name = ?",
            (guild_id, name),
        )
        await db.commit()
        return cursor.rowcount > 0


# --------------- Bot Settings ---------------

async def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    async with _connect() as db:
        cursor = await db.execute("SELECT value FROM bot_settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row["value"] if row else default


async def set_setting(key: str, value: str):
    async with _connect() as db:
        await db.execute(
            "INSERT INTO bot_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
            (key, value, value),
        )
        await db.commit()


async def get_all_settings() -> dict[str, str]:
    async with _connect() as db:
        cursor = await db.execute("SELECT key, value FROM bot_settings")
        rows = await cursor.fetchall()
        return {r["key"]: r["value"] for r in rows}


# --------------- Guild Settings ---------------

async def get_guild_setting(guild_id: str, key: str, default: Optional[str] = None) -> Optional[str]:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT value FROM guild_settings WHERE guild_id = ? AND key = ?",
            (guild_id, key),
        )
        row = await cursor.fetchone()
        return row["value"] if row else default


async def set_guild_setting(guild_id: str, key: str, value: str):
    async with _connect() as db:
        await db.execute(
            """INSERT INTO guild_settings (guild_id, key, value) VALUES (?, ?, ?)
               ON CONFLICT(guild_id, key) DO UPDATE SET value = ?""",
            (guild_id, key, value, value),
        )
        await db.commit()


async def get_all_guild_settings(guild_id: str) -> dict[str, str]:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT key, value FROM guild_settings WHERE guild_id = ?", (guild_id,)
        )
        rows = await cursor.fetchall()
        return {r["key"]: r["value"] for r in rows}


# --------------- Welcome Config ---------------

async def get_welcome_config(guild_id: str) -> Optional[dict]:
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM welcome_config WHERE guild_id = ?", (guild_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def upsert_welcome_config(guild_id: str, **kwargs) -> None:
    async with _connect() as db:
        kwargs["guild_id"] = guild_id
        cols = list(kwargs.keys())
        vals = list(kwargs.values())
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{k} = excluded.{k}" for k in cols if k != "guild_id")
        await db.execute(
            f"INSERT INTO welcome_config ({', '.join(cols)}) VALUES ({placeholders})"
            f" ON CONFLICT(guild_id) DO UPDATE SET {updates}",
            vals,
        )
        await db.commit()


# --------------- Audit Config ---------------

async def get_audit_config(guild_id: str) -> Optional[dict]:
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM audit_config WHERE guild_id = ?", (guild_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def upsert_audit_config(guild_id: str, **kwargs) -> None:
    async with _connect() as db:
        kwargs["guild_id"] = guild_id
        cols = list(kwargs.keys())
        vals = list(kwargs.values())
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{k} = excluded.{k}" for k in cols if k != "guild_id")
        await db.execute(
            f"INSERT INTO audit_config ({', '.join(cols)}) VALUES ({placeholders})"
            f" ON CONFLICT(guild_id) DO UPDATE SET {updates}",
            vals,
        )
        await db.commit()


# --------------- Reaction Roles ---------------

async def get_reaction_roles(guild_id: str) -> list[dict]:
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM reaction_roles WHERE guild_id = ? ORDER BY id", (guild_id,))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_reaction_role_by_message_emoji(message_id: str, emoji: str) -> Optional[dict]:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM reaction_roles WHERE message_id = ? AND emoji = ?",
            (message_id, emoji),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_all_reaction_role_message_ids() -> list[str]:
    async with _connect() as db:
        cursor = await db.execute("SELECT DISTINCT message_id FROM reaction_roles")
        rows = await cursor.fetchall()
        return [r["message_id"] for r in rows]


async def create_reaction_role(*, guild_id: str, channel_id: str, message_id: str, emoji: str, role_id: str) -> int:
    async with _connect() as db:
        cursor = await db.execute(
            "INSERT INTO reaction_roles (guild_id, channel_id, message_id, emoji, role_id) VALUES (?, ?, ?, ?, ?)",
            (guild_id, channel_id, message_id, emoji, role_id),
        )
        await db.commit()
        return cursor.lastrowid


async def delete_reaction_role(rr_id: int) -> bool:
    async with _connect() as db:
        cursor = await db.execute("DELETE FROM reaction_roles WHERE id = ?", (rr_id,))
        await db.commit()
        return cursor.rowcount > 0


async def delete_reaction_role_by_message_emoji(message_id: str, emoji: str) -> bool:
    async with _connect() as db:
        cursor = await db.execute(
            "DELETE FROM reaction_roles WHERE message_id = ? AND emoji = ?",
            (message_id, emoji),
        )
        await db.commit()
        return cursor.rowcount > 0


# --------------- XP Config ---------------

async def get_xp_config(guild_id: str) -> Optional[dict]:
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM xp_config WHERE guild_id = ?", (guild_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def upsert_xp_config(guild_id: str, **kwargs) -> None:
    async with _connect() as db:
        kwargs["guild_id"] = guild_id
        cols = list(kwargs.keys())
        vals = list(kwargs.values())
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{k} = excluded.{k}" for k in cols if k != "guild_id")
        await db.execute(
            f"INSERT INTO xp_config ({', '.join(cols)}) VALUES ({placeholders})"
            f" ON CONFLICT(guild_id) DO UPDATE SET {updates}",
            vals,
        )
        await db.commit()


# --------------- XP Users ---------------

async def get_xp_user(guild_id: str, user_id: str) -> Optional[dict]:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM xp_users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def upsert_xp_user(guild_id: str, user_id: str, xp: int, level: int, last_xp_at: str) -> None:
    async with _connect() as db:
        await db.execute(
            """INSERT INTO xp_users (guild_id, user_id, xp, level, last_xp_at) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(guild_id, user_id) DO UPDATE SET xp = ?, level = ?, last_xp_at = ?""",
            (guild_id, user_id, xp, level, last_xp_at, xp, level, last_xp_at),
        )
        await db.commit()


async def increment_xp_user(guild_id: str, user_id: str, xp_delta: int, last_xp_at: str) -> dict:
    """Atomically increment XP and return the new (xp, level) values."""
    async with _connect() as db:
        await db.execute(
            """INSERT INTO xp_users (guild_id, user_id, xp, level, last_xp_at)
               VALUES (?, ?, ?, 0, ?)
               ON CONFLICT(guild_id, user_id) DO UPDATE SET
                   xp = xp + ?,
                   last_xp_at = ?""",
            (guild_id, user_id, xp_delta, last_xp_at, xp_delta, last_xp_at),
        )
        cursor = await db.execute(
            "SELECT xp, level FROM xp_users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = await cursor.fetchone()
        await db.commit()
        return {"xp": row["xp"], "level": row["level"]}


async def update_xp_level(guild_id: str, user_id: str, level: int) -> None:
    """Update only the level field for a user."""
    async with _connect() as db:
        await db.execute(
            "UPDATE xp_users SET level = ? WHERE guild_id = ? AND user_id = ?",
            (level, guild_id, user_id),
        )
        await db.commit()


async def get_xp_leaderboard(guild_id: str, limit: int = 50) -> list[dict]:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM xp_users WHERE guild_id = ? ORDER BY xp DESC LIMIT ?",
            (guild_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_xp_rank(guild_id: str, user_id: str) -> int:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT COUNT(*) + 1 FROM xp_users WHERE guild_id = ? AND xp > "
            "(SELECT COALESCE((SELECT xp FROM xp_users WHERE guild_id = ? AND user_id = ?), 0))",
            (guild_id, guild_id, user_id),
        )
        row = await cursor.fetchone()
        return row[0]


# --------------- XP Role Rewards ---------------

async def get_xp_role_rewards(guild_id: str) -> list[dict]:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM xp_role_rewards WHERE guild_id = ? ORDER BY level",
            (guild_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def create_xp_role_reward(guild_id: str, level: int, role_id: str) -> int:
    async with _connect() as db:
        cursor = await db.execute(
            "INSERT INTO xp_role_rewards (guild_id, level, role_id) VALUES (?, ?, ?)",
            (guild_id, level, role_id),
        )
        await db.commit()
        return cursor.lastrowid


async def delete_xp_role_reward(reward_id: int) -> bool:
    async with _connect() as db:
        cursor = await db.execute("DELETE FROM xp_role_rewards WHERE id = ?", (reward_id,))
        await db.commit()
        return cursor.rowcount > 0


# --------------- XP Log ---------------

async def add_xp_log_entry(guild_id: str, user_id: str, xp_gained: int,
                            total_xp: int, level: int, channel_id: str,
                            created_at: str) -> int:
    async with _connect() as db:
        cursor = await db.execute(
            """INSERT INTO xp_log (guild_id, user_id, xp_gained, total_xp, level, channel_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (guild_id, user_id, xp_gained, total_xp, level, channel_id, created_at),
        )
        await db.commit()
        return cursor.lastrowid


async def get_xp_log(guild_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM xp_log WHERE guild_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (guild_id, limit, offset),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_xp_log_count(guild_id: str) -> int:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM xp_log WHERE guild_id = ?", (guild_id,)
        )
        row = await cursor.fetchone()
        return row[0]


# --------------- Reminders ---------------

async def create_reminder(*, guild_id: str, channel_id: str, user_id: str, message: str, remind_at: str) -> int:
    async with _connect() as db:
        cursor = await db.execute(
            "INSERT INTO reminders (guild_id, channel_id, user_id, message, remind_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, channel_id, user_id, message, remind_at),
        )
        await db.commit()
        return cursor.lastrowid


async def get_due_reminders(now_iso: str) -> list[dict]:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM reminders WHERE remind_at <= ? LIMIT 50", (now_iso,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_user_reminders(guild_id: str, user_id: str) -> list[dict]:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM reminders WHERE guild_id = ? AND user_id = ? ORDER BY remind_at",
            (guild_id, user_id),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def increment_reminder_fail_count(reminder_id: int) -> int:
    """Increment fail_count and return the new value."""
    async with _connect() as db:
        await db.execute(
            "UPDATE reminders SET fail_count = fail_count + 1 WHERE id = ?", (reminder_id,)
        )
        cursor = await db.execute("SELECT fail_count FROM reminders WHERE id = ?", (reminder_id,))
        row = await cursor.fetchone()
        await db.commit()
        return row[0] if row else 0


async def delete_reminder(reminder_id: int) -> bool:
    async with _connect() as db:
        cursor = await db.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        await db.commit()
        return cursor.rowcount > 0


async def get_guild_reminders(guild_id: str) -> list[dict]:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM reminders WHERE guild_id = ? ORDER BY remind_at",
            (guild_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# --------------- Autoroles ---------------

async def get_autoroles(guild_id: str) -> list[dict]:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM autoroles WHERE guild_id = ? ORDER BY id", (guild_id,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def add_autorole(guild_id: str, role_id: str) -> int:
    async with _connect() as db:
        cursor = await db.execute(
            "INSERT OR IGNORE INTO autoroles (guild_id, role_id) VALUES (?, ?)",
            (guild_id, role_id),
        )
        await db.commit()
        return cursor.lastrowid


async def remove_autorole(guild_id: str, role_id: str) -> bool:
    async with _connect() as db:
        cursor = await db.execute(
            "DELETE FROM autoroles WHERE guild_id = ? AND role_id = ?",
            (guild_id, role_id),
        )
        await db.commit()
        return cursor.rowcount > 0


# --------------- Bulk Config Queries ---------------

async def get_all_xp_configs() -> dict[str, dict]:
    """Return all XP configs keyed by guild_id."""
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM xp_config")
        rows = await cursor.fetchall()
        return {r["guild_id"]: dict(r) for r in rows}


async def get_all_xp_role_rewards() -> dict[str, list[dict]]:
    """Return all XP role rewards grouped by guild_id."""
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM xp_role_rewards ORDER BY level")
        rows = await cursor.fetchall()
        result: dict[str, list[dict]] = {}
        for r in rows:
            result.setdefault(r["guild_id"], []).append(dict(r))
        return result


async def get_all_autoroles_dict() -> dict[str, list[str]]:
    """Return all autoroles grouped by guild_id."""
    async with _connect() as db:
        cursor = await db.execute("SELECT guild_id, role_id FROM autoroles ORDER BY id")
        rows = await cursor.fetchall()
        result: dict[str, list[str]] = {}
        for r in rows:
            result.setdefault(r["guild_id"], []).append(r["role_id"])
        return result


async def get_all_reaction_roles_dict() -> dict[str, dict[str, str]]:
    """Return all reaction roles grouped by message_id -> {emoji: role_id}."""
    async with _connect() as db:
        cursor = await db.execute("SELECT message_id, emoji, role_id FROM reaction_roles")
        rows = await cursor.fetchall()
        result: dict[str, dict[str, str]] = {}
        for r in rows:
            result.setdefault(r["message_id"], {})[r["emoji"]] = r["role_id"]
        return result


async def get_all_freestuff_configs_dict() -> dict[str, dict]:
    """Return all freestuff configs keyed by guild_id."""
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM freestuff_config")
        rows = await cursor.fetchall()
        return {r["guild_id"]: dict(r) for r in rows}


async def get_all_welcome_configs() -> dict[str, dict]:
    """Return all welcome configs keyed by guild_id."""
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM welcome_config")
        rows = await cursor.fetchall()
        return {r["guild_id"]: dict(r) for r in rows}


async def get_all_audit_configs() -> dict[str, dict]:
    """Return all audit configs keyed by guild_id."""
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM audit_config")
        rows = await cursor.fetchall()
        return {r["guild_id"]: dict(r) for r in rows}


# --------------- Feature Config Counts ---------------

async def count_feature_configs() -> dict[str, int]:
    """Count active feature configs in a single pass."""
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM welcome_config WHERE welcome_enabled = 1 OR goodbye_enabled = 1"
        )
        welcome = (await cursor.fetchone())["cnt"]

        cursor = await db.execute("SELECT COUNT(*) as cnt FROM xp_config WHERE enabled = 1")
        leveling = (await cursor.fetchone())["cnt"]

        cursor = await db.execute("SELECT COUNT(*) as cnt FROM reaction_roles")
        rr = (await cursor.fetchone())["cnt"]

        cursor = await db.execute("SELECT COUNT(*) as cnt FROM audit_config WHERE log_channel_id IS NOT NULL AND log_channel_id != ''")
        audit = (await cursor.fetchone())["cnt"]

        cursor = await db.execute("SELECT COUNT(*) as cnt FROM autoroles")
        autoroles = (await cursor.fetchone())["cnt"]

        cursor = await db.execute("SELECT COUNT(*) as cnt FROM twitch_drops_config WHERE enabled = 1")
        twitch_drops = (await cursor.fetchone())["cnt"]

        return {
            "welcome": welcome,
            "leveling": leveling,
            "reaction_roles": rr,
            "audit": audit,
            "autoroles": autoroles,
            "twitch_drops": twitch_drops,
        }


# --------------- Dashboard Overview Queries ---------------

async def get_recent_warnings(limit: int = 10) -> list[dict]:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM warnings ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_recent_automod_actions(limit: int = 10) -> list[dict]:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM automod_actions_log ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_recent_tickets(limit: int = 10) -> list[dict]:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM tickets ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_feature_status_summary() -> dict[str, dict[str, bool]]:
    """Return per-guild On/Off matrix for all features."""
    async with _connect() as db:
        result: dict[str, dict[str, bool]] = {}

        cursor = await db.execute("SELECT guild_id, welcome_enabled, goodbye_enabled FROM welcome_config")
        for r in await cursor.fetchall():
            gid = r["guild_id"]
            result.setdefault(gid, {})["welcome"] = bool(r["welcome_enabled"] or r["goodbye_enabled"])

        cursor = await db.execute("SELECT guild_id, enabled FROM xp_config")
        for r in await cursor.fetchall():
            gid = r["guild_id"]
            result.setdefault(gid, {})["leveling"] = bool(r["enabled"])

        cursor = await db.execute("SELECT DISTINCT guild_id FROM reaction_roles")
        for r in await cursor.fetchall():
            result.setdefault(r["guild_id"], {})["reaction_roles"] = True

        cursor = await db.execute("SELECT guild_id, log_channel_id FROM audit_config")
        for r in await cursor.fetchall():
            gid = r["guild_id"]
            result.setdefault(gid, {})["audit"] = bool(r["log_channel_id"])

        cursor = await db.execute("SELECT DISTINCT guild_id FROM autoroles")
        for r in await cursor.fetchall():
            result.setdefault(r["guild_id"], {})["autoroles"] = True

        cursor = await db.execute("SELECT guild_id, enabled FROM twitch_drops_config")
        for r in await cursor.fetchall():
            gid = r["guild_id"]
            result.setdefault(gid, {})["twitch_drops"] = bool(r["enabled"])

        return result


# --------------- Free Stuff Notifications ---------------

async def get_freestuff_config(guild_id: str) -> Optional[dict]:
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM freestuff_config WHERE guild_id = ?", (guild_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def upsert_freestuff_config(guild_id: str, **kwargs) -> None:
    async with _connect() as db:
        kwargs["guild_id"] = guild_id
        cols = list(kwargs.keys())
        vals = list(kwargs.values())
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{k} = excluded.{k}" for k in cols if k != "guild_id")
        await db.execute(
            f"INSERT INTO freestuff_config ({', '.join(cols)}) VALUES ({placeholders})"
            f" ON CONFLICT(guild_id) DO UPDATE SET {updates}",
            vals,
        )
        await db.commit()


async def get_all_freestuff_configs() -> list[dict]:
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM freestuff_config WHERE enabled = 1")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_free_games(limit: int = 50) -> list[dict]:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM free_games ORDER BY discovered_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_free_games_by_category(category: str, limit: int = 1) -> list[dict]:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM free_games WHERE category = ? ORDER BY discovered_at DESC LIMIT ?",
            (category, limit)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def add_free_game(*, title: str, url: str, platform: str,
                         image_url: Optional[str] = None, original_price: Optional[str] = None,
                         source: str, category: str = "free_to_keep",
                         source_url: Optional[str] = None, description: Optional[str] = None,
                         gp_type: Optional[str] = None) -> Optional[int]:
    """Insert a free game, returns None if URL already exists. Updates category/gp_type on conflict."""
    async with _connect() as db:
        try:
            cursor = await db.execute(
                "INSERT INTO free_games (title, url, platform, image_url, original_price, source, category, source_url, description, gp_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (title, url, platform, image_url, original_price, source, category, source_url, description, gp_type),
            )
            await db.commit()
            return cursor.lastrowid
        except aiosqlite.IntegrityError:
            await db.execute(
                "UPDATE free_games SET category = ?, gp_type = ? WHERE url = ?",
                (category, gp_type, url),
            )
            await db.commit()
            return None


async def clear_free_games() -> int:
    """Delete all cached free game entries (forces re-announcement on next fetch). Returns rows deleted."""
    async with _connect() as db:
        cursor = await db.execute("DELETE FROM free_games")
        await db.commit()
        return cursor.rowcount


# --------------- Twitch Drops Notifications ---------------

async def get_twitch_drops_config(guild_id: str) -> Optional[dict]:
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM twitch_drops_config WHERE guild_id = ?", (guild_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def upsert_twitch_drops_config(guild_id: str, **kwargs) -> None:
    async with _connect() as db:
        kwargs["guild_id"] = guild_id
        cols = list(kwargs.keys())
        vals = list(kwargs.values())
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{k} = excluded.{k}" for k in cols if k != "guild_id")
        await db.execute(
            f"INSERT INTO twitch_drops_config ({', '.join(cols)}) VALUES ({placeholders})"
            f" ON CONFLICT(guild_id) DO UPDATE SET {updates}",
            vals,
        )
        await db.commit()


async def delete_twitch_drops_config(guild_id: str) -> bool:
    async with _connect() as db:
        cursor = await db.execute("DELETE FROM twitch_drops_config WHERE guild_id = ?", (guild_id,))
        await db.commit()
        return cursor.rowcount > 0


async def get_all_twitch_drops_configs() -> list[dict]:
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM twitch_drops_config WHERE enabled = 1")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_all_twitch_drops_configs_dict() -> dict[str, dict]:
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM twitch_drops_config")
        rows = await cursor.fetchall()
        return {r["guild_id"]: dict(r) for r in rows}


async def add_twitch_drop(*, drop_id: str, game_name: str, game_id: Optional[str] = None,
                            drop_name: str, description: Optional[str] = None,
                            start_date: Optional[str] = None, end_date: Optional[str] = None,
                            image_url: Optional[str] = None,
                            details_url: Optional[str] = None) -> Optional[int]:
    """Insert a twitch drop, returns None if drop_id already exists (dedup)."""
    async with _connect() as db:
        try:
            cursor = await db.execute(
                """INSERT INTO twitch_drops_cache
                   (drop_id, game_name, game_id, drop_name, description, start_date, end_date, image_url, details_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (drop_id, game_name, game_id, drop_name, description, start_date, end_date, image_url, details_url),
            )
            await db.commit()
            return cursor.lastrowid
        except aiosqlite.IntegrityError:
            return None


async def get_cached_drops(limit: int = 50) -> list[dict]:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM twitch_drops_cache ORDER BY discovered_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_active_drops() -> list[dict]:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM twitch_drops_cache WHERE end_date IS NULL OR end_date >= datetime('now') ORDER BY discovered_at DESC"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_all_cached_game_statuses() -> list[dict]:
    """Return one row per unique game_name with is_active flag and latest end_date."""
    async with _connect() as db:
        cursor = await db.execute("""
            SELECT game_name,
                   MAX(end_date) AS end_date,
                   MAX(CASE WHEN end_date IS NULL OR end_date >= datetime('now') THEN 1 ELSE 0 END) AS is_active
            FROM twitch_drops_cache
            GROUP BY game_name
            ORDER BY is_active DESC, game_name ASC
        """)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def clear_twitch_drops_cache() -> int:
    """Delete all entries from the twitch drops cache. Returns rows deleted."""
    async with _connect() as conn:
        cursor = await conn.execute("DELETE FROM twitch_drops_cache")
        await conn.commit()
        return cursor.rowcount


# --------------- Streaming Notifications ---------------

async def get_streaming_configs(guild_id: str) -> list[dict]:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM streaming_config WHERE guild_id = ? ORDER BY streamer_name", (guild_id,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_all_streaming_configs() -> list[dict]:
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM streaming_config WHERE enabled = 1")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def add_streaming_config(*, guild_id: str, channel_id: str, streamer_url: str,
                                 streamer_name: str, platform: str,
                                 mention_role_id: str | None = None) -> Optional[int]:
    async with _connect() as db:
        try:
            cursor = await db.execute(
                """INSERT INTO streaming_config (guild_id, channel_id, streamer_url, streamer_name, platform, mention_role_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (guild_id, channel_id, streamer_url, streamer_name, platform, mention_role_id),
            )
            await db.commit()
            return cursor.lastrowid
        except aiosqlite.IntegrityError:
            return None


async def remove_streaming_config(config_id: int) -> bool:
    async with _connect() as db:
        cursor = await db.execute("DELETE FROM streaming_config WHERE id = ?", (config_id,))
        await db.commit()
        return cursor.rowcount > 0


async def update_streaming_notified(config_id: int, last_stream_id: str) -> None:
    async with _connect() as db:
        await db.execute(
            "UPDATE streaming_config SET last_notified = datetime('now'), last_stream_id = ? WHERE id = ?",
            (last_stream_id, config_id),
        )
        await db.commit()


async def update_streaming_mention_role(config_id: int, mention_role_id: str | None) -> None:
    async with _connect() as db:
        await db.execute(
            "UPDATE streaming_config SET mention_role_id = ? WHERE id = ?",
            (mention_role_id, config_id),
        )
        await db.commit()


# --------------- Auto-Translate Config ---------------

async def get_autotranslate_config(guild_id: str) -> Optional[dict]:
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM autotranslate_config WHERE guild_id = ?", (guild_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def upsert_autotranslate_config(guild_id: str, **kwargs) -> None:
    async with _connect() as db:
        kwargs["guild_id"] = guild_id
        cols = list(kwargs.keys())
        vals = list(kwargs.values())
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{k} = excluded.{k}" for k in cols if k != "guild_id")
        await db.execute(
            f"INSERT INTO autotranslate_config ({', '.join(cols)}) VALUES ({placeholders})"
            f" ON CONFLICT(guild_id) DO UPDATE SET {updates}",
            vals,
        )
        await db.commit()


async def delete_autotranslate_config(guild_id: str) -> None:
    async with _connect() as db:
        await db.execute("DELETE FROM autotranslate_config WHERE guild_id = ?", (guild_id,))
        await db.commit()


async def get_all_autotranslate_configs() -> dict[str, dict]:
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM autotranslate_config WHERE enabled = 1")
        rows = await cursor.fetchall()
        return {r["guild_id"]: dict(r) for r in rows}


# --------------- Giveaways ---------------

async def create_giveaway(*, guild_id: str, channel_id: str, prize: str,
                           winner_count: int, ends_at: str) -> int:
    async with _connect() as db:
        cursor = await db.execute(
            "INSERT INTO giveaways (guild_id, channel_id, prize, winner_count, ends_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, channel_id, prize, winner_count, ends_at),
        )
        await db.commit()
        return cursor.lastrowid


async def set_giveaway_message_id(giveaway_id: int, message_id: str) -> None:
    async with _connect() as db:
        await db.execute("UPDATE giveaways SET message_id = ? WHERE id = ?", (message_id, giveaway_id))
        await db.commit()


async def get_giveaway(giveaway_id: int) -> Optional[dict]:
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM giveaways WHERE id = ?", (giveaway_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_giveaway_by_message(message_id: str) -> Optional[dict]:
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM giveaways WHERE message_id = ?", (message_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_active_giveaways(guild_id: str) -> list[dict]:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM giveaways WHERE guild_id = ? AND ended = 0 ORDER BY ends_at", (guild_id,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_all_active_giveaways() -> list[dict]:
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM giveaways WHERE ended = 0 ORDER BY ends_at")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def end_giveaway(giveaway_id: int, winners: list[str]) -> None:
    import json as _json
    async with _connect() as db:
        await db.execute(
            "UPDATE giveaways SET ended = 1, winners = ? WHERE id = ?",
            (_json.dumps(winners), giveaway_id),
        )
        await db.commit()


# --------------- Warnings ---------------

async def add_warning(*, guild_id: str, user_id: str, moderator_id: str,
                       reason: Optional[str] = None) -> int:
    async with _connect() as db:
        cursor = await db.execute(
            "INSERT INTO warnings (guild_id, user_id, moderator_id, reason) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, moderator_id, reason),
        )
        await db.commit()
        return cursor.lastrowid


async def get_warnings(guild_id: str, user_id: str) -> list[dict]:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM warnings WHERE guild_id = ? AND user_id = ? ORDER BY created_at DESC",
            (guild_id, user_id),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def clear_warnings(guild_id: str, user_id: str) -> int:
    async with _connect() as db:
        cursor = await db.execute(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        await db.commit()
        return cursor.rowcount


async def get_warning(warning_id: int, guild_id: str) -> Optional[dict]:
    """Fetch a single warning by ID, scoped to guild."""
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM warnings WHERE id = ? AND guild_id = ?", (warning_id, guild_id)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def delete_warning(warning_id: int, guild_id: str) -> bool:
    """Delete a single warning by ID. Returns True if a row was deleted."""
    async with _connect() as db:
        cursor = await db.execute(
            "DELETE FROM warnings WHERE id = ? AND guild_id = ?", (warning_id, guild_id)
        )
        await db.commit()
        return cursor.rowcount > 0


# --------------- Modlog ---------------

async def add_modlog_entry(*, guild_id: str, action: str, user_id: str,
                            moderator_id: str, reason: Optional[str] = None,
                            extra: Optional[str] = None) -> int:
    async with _connect() as db:
        cursor = await db.execute(
            "INSERT INTO modlog (guild_id, action, user_id, moderator_id, reason, extra)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, action, user_id, moderator_id, reason, extra),
        )
        await db.commit()
        return cursor.lastrowid


async def get_modlog(guild_id: str, *, user_id: Optional[str] = None,
                     moderator_id: Optional[str] = None, limit: int = 20) -> list[dict]:
    conditions = ["guild_id = ?"]
    params: list = [guild_id]
    if user_id:
        conditions.append("user_id = ?")
        params.append(user_id)
    if moderator_id:
        conditions.append("moderator_id = ?")
        params.append(moderator_id)
    params.append(limit)
    async with _connect() as db:
        cursor = await db.execute(
            f"SELECT * FROM modlog WHERE {' AND '.join(conditions)} ORDER BY created_at DESC LIMIT ?",
            params,
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# --------------- Anti-Raid Config ---------------

async def get_antiraid_config(guild_id: str) -> Optional[dict]:
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM antiraid_config WHERE guild_id = ?", (guild_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def upsert_antiraid_config(guild_id: str, **kwargs) -> None:
    async with _connect() as db:
        kwargs["guild_id"] = guild_id
        cols = list(kwargs.keys())
        vals = list(kwargs.values())
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{k} = excluded.{k}" for k in cols if k != "guild_id")
        await db.execute(
            f"INSERT INTO antiraid_config ({', '.join(cols)}) VALUES ({placeholders})"
            f" ON CONFLICT(guild_id) DO UPDATE SET {updates}",
            vals,
        )
        await db.commit()


async def get_all_antiraid_configs() -> dict[str, dict]:
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM antiraid_config WHERE enabled = 1")
        rows = await cursor.fetchall()
        return {r["guild_id"]: dict(r) for r in rows}


# --------------- Track History ---------------

async def add_track_history(guild_id: str, title: str, url: str,
                             source: Optional[str], requester: Optional[str]) -> None:
    async with _connect() as db:
        await db.execute(
            "INSERT INTO track_history (guild_id, title, url, source, requester) VALUES (?, ?, ?, ?, ?)",
            (guild_id, title, url, source, requester),
        )
        # Keep only last 100 per guild
        await db.execute(
            """DELETE FROM track_history WHERE guild_id = ? AND id NOT IN (
                SELECT id FROM track_history WHERE guild_id = ? ORDER BY played_at DESC LIMIT 100
            )""",
            (guild_id, guild_id),
        )
        await db.commit()


async def get_track_history(guild_id: str, limit: int = 25) -> list[dict]:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT * FROM track_history WHERE guild_id = ? ORDER BY played_at DESC LIMIT ?",
            (guild_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# --------------- AI Config ---------------

async def get_ai_config(guild_id: str) -> Optional[dict]:
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM ai_config WHERE guild_id = ?", (guild_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def upsert_ai_config(guild_id: str, **kwargs) -> None:
    async with _connect() as db:
        kwargs["guild_id"] = guild_id
        cols = list(kwargs.keys())
        vals = list(kwargs.values())
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{k} = excluded.{k}" for k in cols if k != "guild_id")
        await db.execute(
            f"INSERT INTO ai_config ({', '.join(cols)}) VALUES ({placeholders})"
            f" ON CONFLICT(guild_id) DO UPDATE SET {updates}",
            vals,
        )
        await db.commit()


# --------------- AI History ---------------

async def get_ai_history(guild_id: str, channel_id: str, limit: int = 20) -> list[dict]:
    async with _connect() as db:
        cursor = await db.execute(
            """SELECT role, content FROM ai_history
               WHERE guild_id = ? AND channel_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (guild_id, channel_id, limit),
        )
        rows = await cursor.fetchall()
        return list(reversed([dict(r) for r in rows]))


async def add_ai_message(guild_id: str, channel_id: str, role: str, content: str) -> None:
    async with _connect() as db:
        await db.execute(
            "INSERT INTO ai_history (guild_id, channel_id, role, content) VALUES (?, ?, ?, ?)",
            (guild_id, channel_id, role, content),
        )
        await db.commit()


async def clear_ai_history(guild_id: str, channel_id: str) -> None:
    async with _connect() as db:
        await db.execute(
            "DELETE FROM ai_history WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )
        await db.commit()


# --------------- Soundboard Config ---------------

async def get_soundboard_config(guild_id: str) -> Optional[dict]:
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM soundboard_config WHERE guild_id = ?", (guild_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_fun_guild_config(guild_id: str) -> dict[str, dict]:
    """Return {command: config_dict} for all fun commands configured for this guild."""
    async with _connect() as db:
        cursor = await db.execute("SELECT * FROM fun_config WHERE guild_id = ?", (guild_id,))
        rows = await cursor.fetchall()
        return {r["command"]: dict(r) for r in rows}


async def upsert_fun_command_config(guild_id: str, command: str, **kwargs) -> None:
    async with _connect() as db:
        kwargs["guild_id"] = guild_id
        kwargs["command"] = command
        cols = list(kwargs.keys())
        vals = list(kwargs.values())
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{k} = excluded.{k}" for k in cols if k not in ("guild_id", "command"))
        await db.execute(
            f"INSERT INTO fun_config ({', '.join(cols)}) VALUES ({placeholders})"
            f" ON CONFLICT(guild_id, command) DO UPDATE SET {updates}",
            vals,
        )
        await db.commit()


async def upsert_soundboard_config(guild_id: str, **kwargs) -> None:
    async with _connect() as db:
        kwargs["guild_id"] = guild_id
        cols = list(kwargs.keys())
        vals = list(kwargs.values())
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{k} = excluded.{k}" for k in cols if k != "guild_id")
        await db.execute(
            f"INSERT INTO soundboard_config ({', '.join(cols)}) VALUES ({placeholders})"
            f" ON CONFLICT(guild_id) DO UPDATE SET {updates}",
            vals,
        )
        await db.commit()
