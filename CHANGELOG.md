# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `/delwarn <id>` — delete a single warning by case ID (scoped to guild, requires `manage_messages`)
- `/modlog [user] [moderator]` — query last 20 mod actions with optional filters
- Modlog DB table (`modlog`) — persists all kick, ban, softban, unban, timeout, and warn actions
- `get_warning` / `delete_warning` DB helpers for per-case warning management
- Anti-raid protection cog (`cogs/antiraid.py`) — mass join detection, new account filter, mention spam, message spam, `/antiraid set/show/lockdown/unlock`
- Ghost ping detection in audit log — alerts on mention removed via edit or deleted message (`/auditlog set log_ghost_pings:True`)

---

## [1.2.0] - 2026-03-21

### Added
- Tidal support in `/play` — tracks, albums, and playlists resolved via yt-dlp with embed-page scrape fallback
- YouTube playlist support in `/play` — all tracks are queued instead of only the first
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
- Dashboard improvements (better UI, additional stats)
- Miscellaneous bug fixes and stability improvements

## [1.0.0] - 2025

### Added
- Initial public release
- Moderation cog (kick, ban, mute, warn, purge)
- Fun cog (meme, jokes, trivia, 8ball)
- Utility cog (ping, uptime, server info, user info)
- Music cog (YouTube playback via yt-dlp)
- Economy cog (balance, daily, transfer, leaderboard)
- Web dashboard (Flask-based, real-time stats)
- `.env`-based configuration (no hardcoded secrets)
- PostgreSQL support via SQLAlchemy

---

## Roadmap

Features planned for future releases (in priority order):

### v1.3.0 — Moderation & Safety ✅
- [x] **Moderation cog** — `/kick`, `/ban`, `/unban`, `/softban`, `/timeout`, `/warn`, `/warnings`, `/purge`
- [x] **Anti-raid protection** — mass join detection, new account filter, mention/message spam detection + lockdown
- [x] **Ghost ping detection** — audit log alert when a mention is edited/deleted

### v1.4.0 — Utility Upgrades
- [ ] **Auto-translate** — per-channel automatic message translation (Google Translate, no API key)
- [ ] **Giveaway system** — create, auto-end, roll winner(s), reroll
- [ ] **Server backup & restore** — export/import all guild bot configuration as JSON
- [ ] **Webhook notification delivery** — route audit logs through a Discord webhook URL

### v1.5.0 — Fun & Entertainment
- [ ] **Fun commands** — `/meme`, `/animal`, `/8ball`, `/mock`, `/ship`

### Music (ongoing)
- [ ] Seek / rewind — `/seek <seconds>`
- [ ] Per-track source badge (YouTube / Spotify / Tidal)
- [ ] Queue persistence across restarts
- [ ] DJ role system
- [ ] Track history — `/history`
- [ ] Lyrics integration — `/lyrics` via Genius API
- [ ] Audio filters / EQ (bass boost, nightcore)
- [ ] Autoplay / recommendations
- [ ] SoundCloud native URL support
- [ ] Apple Music support
