from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import aiosqlite

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "bot.db"

AI_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_server_config (
    server_id      TEXT PRIMARY KEY,
    system_prompt  TEXT NOT NULL DEFAULT 'You are a helpful assistant.',
    active_channels TEXT NOT NULL DEFAULT '[]',
    language       TEXT NOT NULL DEFAULT 'auto',
    tone           TEXT NOT NULL DEFAULT 'casual',
    blocklist      TEXT NOT NULL DEFAULT '[]',
    api_key        TEXT,
    model          TEXT,
    thinking_enabled INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ai_user_memory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    server_id   TEXT,
    memory_text TEXT,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, server_id)
);

CREATE TABLE IF NOT EXISTS ai_conversations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id  TEXT,
    user_id    TEXT NOT NULL,
    channel_id TEXT,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    timestamp  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ai_conversations_channel
    ON ai_conversations(server_id, channel_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_ai_conversations_user
    ON ai_conversations(server_id, user_id, timestamp DESC);
"""


_NEW_COLUMNS = [
    ("enabled",                "INTEGER", "1"),
    ("response_length",        "TEXT",    "'medium'"),
    ("personality_mode",       "TEXT",    "'manual'"),
    ("personality_preset",     "TEXT",    "'helper'"),
    ("personality_auto_prompt","TEXT",    "''"),
    ("markdown_enabled",       "INTEGER", "1"),
    ("markdown_frequency",     "TEXT",    "'sometimes'"),
    ("emojis_enabled",         "INTEGER", "1"),
    ("mentions_enabled",       "INTEGER", "0"),
    ("reply_mode",             "INTEGER", "1"),
    ("show_typing",            "INTEGER", "1"),
    ("webhook_url",            "TEXT",    "NULL"),
    ("webhook_name",           "TEXT",    "'Tagokura AI'"),
    ("webhook_avatar",         "TEXT",    "NULL"),
]


async def init_ai_db() -> None:
    """Create AI tables if they don't exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(AI_SCHEMA)
        # Migrate: add new columns if they don't exist yet
        for col, col_type, default in _NEW_COLUMNS:
            try:
                await db.execute(
                    f"ALTER TABLE ai_server_config ADD COLUMN {col} {col_type} DEFAULT {default}"
                )
            except Exception:
                pass  # column already exists
        await db.commit()


def _connect():
    return _CM()


class _CM:
    async def __aenter__(self):
        self._db = await aiosqlite.connect(DB_PATH)
        self._db.row_factory = aiosqlite.Row
        return self._db

    async def __aexit__(self, *exc):
        await self._db.close()


# --------------- ai_server_config ---------------

async def get_server_config(server_id: str) -> Optional[dict]:
    async with _connect() as db:
        cur = await db.execute(
            "SELECT * FROM ai_server_config WHERE server_id = ?", (server_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def upsert_server_config(server_id: str, **kwargs) -> None:
    async with _connect() as db:
        kwargs["server_id"] = server_id
        cols = list(kwargs.keys())
        vals = list(kwargs.values())
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{k} = excluded.{k}" for k in cols if k != "server_id")
        await db.execute(
            f"INSERT INTO ai_server_config ({', '.join(cols)}) VALUES ({placeholders})"
            f" ON CONFLICT(server_id) DO UPDATE SET {updates}",
            vals,
        )
        await db.commit()


async def get_all_server_configs() -> list[dict]:
    async with _connect() as db:
        cur = await db.execute("SELECT * FROM ai_server_config")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


# --------------- ai_user_memory ---------------

async def get_user_memory(user_id: str, server_id: Optional[str]) -> Optional[str]:
    async with _connect() as db:
        if server_id is None:
            cur = await db.execute(
                "SELECT memory_text FROM ai_user_memory WHERE user_id = ? AND server_id IS NULL",
                (user_id,),
            )
        else:
            cur = await db.execute(
                "SELECT memory_text FROM ai_user_memory WHERE user_id = ? AND server_id = ?",
                (user_id, server_id),
            )
        row = await cur.fetchone()
        return row["memory_text"] if row else None


async def upsert_user_memory(user_id: str, server_id: Optional[str], memory_text: str) -> None:
    async with _connect() as db:
        await db.execute(
            """INSERT INTO ai_user_memory (user_id, server_id, memory_text, updated_at)
               VALUES (?, ?, ?, datetime('now'))
               ON CONFLICT(user_id, server_id) DO UPDATE SET
                   memory_text = excluded.memory_text,
                   updated_at  = excluded.updated_at""",
            (user_id, server_id, memory_text),
        )
        await db.commit()


async def delete_user_memory(user_id: str, server_id: Optional[str]) -> None:
    async with _connect() as db:
        if server_id is None:
            await db.execute(
                "DELETE FROM ai_user_memory WHERE user_id = ? AND server_id IS NULL", (user_id,)
            )
        else:
            await db.execute(
                "DELETE FROM ai_user_memory WHERE user_id = ? AND server_id = ?",
                (user_id, server_id),
            )
        await db.commit()


async def get_all_user_memories(server_id: Optional[str] = None) -> list[dict]:
    async with _connect() as db:
        if server_id is None:
            cur = await db.execute(
                "SELECT * FROM ai_user_memory ORDER BY updated_at DESC"
            )
        else:
            cur = await db.execute(
                "SELECT * FROM ai_user_memory WHERE server_id = ? ORDER BY updated_at DESC",
                (server_id,),
            )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


# --------------- ai_conversations ---------------

async def save_conversation_turn(
    server_id: Optional[str],
    user_id: str,
    channel_id: Optional[str],
    role: str,
    content: str,
) -> None:
    async with _connect() as db:
        await db.execute(
            "INSERT INTO ai_conversations (server_id, user_id, channel_id, role, content)"
            " VALUES (?, ?, ?, ?, ?)",
            (server_id, user_id, channel_id, role, content),
        )
        await db.commit()


async def get_recent_logs(
    server_id: Optional[str] = None,
    *,
    user_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    conditions = []
    params: list = []
    if server_id is not None:
        conditions.append("server_id = ?")
        params.append(server_id)
    if user_id:
        conditions.append("user_id = ?")
        params.append(user_id)
    if channel_id:
        conditions.append("channel_id = ?")
        params.append(channel_id)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    async with _connect() as db:
        cur = await db.execute(
            f"SELECT * FROM ai_conversations {where} ORDER BY timestamp DESC LIMIT ?",
            params,
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def clear_conversations(server_id: str, channel_id: Optional[str] = None) -> None:
    async with _connect() as db:
        if channel_id:
            await db.execute(
                "DELETE FROM ai_conversations WHERE server_id = ? AND channel_id = ?",
                (server_id, channel_id),
            )
        else:
            await db.execute(
                "DELETE FROM ai_conversations WHERE server_id = ?", (server_id,)
            )
        await db.commit()
