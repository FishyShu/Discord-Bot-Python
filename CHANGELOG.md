# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

---

## [1.5.0] - 2026-03-23

### Added
- **Soundboard dashboard** (`dashboard/routes_soundboard.py`) — per-guild sound libraries, upload/delete sounds, volume settings
- **Fun Commands dashboard** (`dashboard/routes_fun.py`) — per-command enabled toggle, channel/role restrictions, cooldowns
- **Shutdown animation** — colourful console animation on Ctrl+C

---

## [1.4.0] - 2026-03-22

### Added
- **Free Games** — content filters, embed customisation, per-category test notifications
- **Twitch Drops** — embed customisation, game filter overhaul with active/inactive state

### Fixed
- `IndexError` on empty `link_flair_richtext` in Reddit fetch

---

## [1.3.0] - 2026-03-22

### Added
- **AI Chatbot system** (`cogs/ai.py`, `utils/ai_db.py`, `utils/ai_prompt.py`, `utils/ai_router.py`)
  - Responds in configured active channels and to @mentions everywhere
  - Response length control (Short / Medium / Long) via `/ai config length` and dashboard
  - Three personality modes: Manual system prompt, Preset, Auto-generate from description
  - Five built-in presets: Friendly Helper, Anime Waifu, Professional Assistant, Caine (TADC), Winston (Overwatch)
  - Behaviour flags: markdown frequency, emoji toggle, mention on reply, Discord quote-reply, typing indicator
  - Webhook persona — custom name and avatar per server via Discord webhook
  - Long-term memory per user via `/ai memory`
  - Web search injection (DuckDuckGo) and URL summarisation
  - Image generation via `/imagine` (fal.ai with Pollinations.ai fallback)
  - Per-server blocklist — refuse to discuss configured topics
  - Bring-your-own API key support (Claude, GPT-4o, premium Gemini) with encryption
  - AI dashboard section: personality, behaviour, webhook persona, channels, blocklist, API key
- **AI image generation fix** — `/imagine` now downloads the image before sending as a `discord.File` attachment (was showing a blank embed)
- **Sparkly console output** (`utils/console.py`) — colourful startup banner, per-level icons and colours, ANSI support on Windows
- **Dashboard: Tone improvements** — dropdown shows descriptions, Custom tone option with free-text input
- **Language enforcement** — language rule is now prepended as a highest-priority directive so it is respected even with strong character presets
- **Moderation cog** (`cogs/moderation.py`) — `/kick`, `/ban`, `/unban`, `/softban`, `/timeout`, `/warn`, `/warnings`, `/purge`
- **Mod log** — `/modlog [user] [moderator]` queries persistent action history; `/delwarn <id>` deletes a warning by case ID
- **Anti-raid protection** (`cogs/antiraid.py`) — mass join detection, new account filter, mention/message spam; `/antiraid set/show/lockdown/unlock`
- **Ghost ping detection** — audit log alerts when a mention is removed via edit or deleted message
- **Giveaway system** (`cogs/giveaways.py`) — timed giveaways with auto-end, winner announcement, and reroll
- **Server backup** (`cogs/backup.py`) — export/import full server bot configuration as JSON
- **Auto-translate** (`cogs/autotranslate.py`) — per-channel automatic message translation
- **Fun commands** (`cogs/fun.py`) — `/meme`, `/joke`, `/8ball`, `/coinflip`, `/roll`, `/mock`, `/ship`, and more

### Fixed
- Webhook avatar stored as string `"None"` instead of SQL NULL causing webhook sends to fail silently
- `/imagine` sending a blank embed — fixed by downloading image before attaching

---

## [1.2.3] - 2026-03-21

### Fixed
- Fixed 9 slash command audit issues

## [1.2.1] - 2026-03-21

### Fixed
- `/help` command, dashboard moderation/antiraid/giveaways/backup sections

## [1.2.0] - 2026-03-21

### Added
- Tidal support in `/play` — tracks, albums, and playlists resolved via yt-dlp with embed-page scrape fallback
- YouTube playlist support in `/play` — all tracks queued instead of only the first
- `/musicconfig set fallback_service` — choose YouTube (default) or SoundCloud as fallback when a stream fails
- `/musicconfig show` now displays Fallback Service

### Fixed
- Spotify embed fallback infinite recursion — three self-recursive `_embed_fallback` calls now correctly call `_oembed_fallback`

## [1.1.1] - 2026-03-21

### Changed
- Fixed clone snippet in README (`cd Claude_Code` → `cd Discord-Bot-Python`)
- Added LICENSE file (MIT)
- Added CHANGELOG.md, CONTRIBUTING.md, SECURITY.md for OSS readiness

## [1.1.0] - 2025

### Added
- Voice cog with join/leave/play/pause/skip/queue commands
- Docker support (`Dockerfile`, `docker-compose.yml`)
- Dashboard improvements
- Miscellaneous bug fixes and stability improvements

## [1.0.0] - 2025

### Added
- Initial public release
- Moderation cog (kick, ban, mute, warn, purge)
- Fun cog (meme, jokes, trivia, 8ball)
- Utility cog (ping, uptime, server info, user info)
- Music cog (YouTube playback via yt-dlp)
- Web dashboard (Quart-based, SQLite)
- `.env`-based configuration

---

## Roadmap

### Music (ongoing)
- [ ] Seek / rewind — `/seek <seconds>`
- [ ] Queue persistence across restarts
- [ ] DJ role system
- [ ] Track history — `/history`
- [ ] Lyrics — `/lyrics` via Genius API
- [ ] Autoplay / recommendations
- [ ] Apple Music support

### Future
- [ ] Polls & voting
- [ ] Ticket system
- [ ] Starboard
- [ ] Reminders
- [ ] Birthday announcements
- [ ] PostgreSQL migration
