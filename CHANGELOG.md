# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
