<div align="center">

# 🤖 Discord Bot

**A feature-rich, self-hosted Discord bot with a web dashboard**

[![Version](https://img.shields.io/badge/version-1.1.0-blue?style=for-the-badge)](https://github.com/FishyShu/Discord-Bot-Python/releases)
[![Python](https://img.shields.io/badge/python-3.11+-yellow?style=for-the-badge&logo=python)](https://python.org)
[![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discordpy.readthedocs.io)
[![License](https://img.shields.io/badge/license-MIT-green?style=for-the-badge)](LICENSE)

[Features](#-features) • [Dashboard](#-web-dashboard) • [Setup](#-getting-started) • [Commands](#-commands) • [Roadmap](#-roadmap)

</div>

---

## ✨ Features

### 🎵 Music Player
Full-featured music bot powered by yt-dlp.
- Play songs from **YouTube URLs**, **Spotify links**, or search queries
- Interactive **search picker** — choose from top results before playing
- **Queue management** with skip, stop, pause, and resume
- Auto-disconnect on inactivity

### 🎙️ Text-to-Speech
Speak text aloud in voice channels using Google TTS.
- Supports **8 languages**: English, Spanish, French, German, Japanese, Portuguese, Russian, Korean
- Per-server default language configuration

### 🔊 Soundboard
Play custom sound effects in voice channels.
- Upload and manage `.mp3` / `.wav` files per server
- Autocomplete from all available sounds
- `/soundboard` and `/sb` shortcut commands

### 🎛️ Voice Separation
AI-powered audio stem separation.
- Upload any audio file and get back **separate vocal and instrumental tracks**
- Delivered directly in Discord as downloadable `.wav` files

### 🎮 Free Game Alerts
Automatically announces free games across platforms.
- Monitors **Epic Games**, **Steam**, **GOG**, **Ubisoft**, **Humble Bundle**, and more
- **Reddit** `/r/FreeGameFindings` integration for community-sourced finds
- Per-server **platform filter** — only see alerts you care about
- Optional **role mention** with each alert
- Manual `/freestuff check` command to fetch on demand

### 📺 Streamer Notifications
Go-live alerts for your favorite streamers.
- Track **Twitch** streamers per server
- Rich embeds with game, viewer count, and stream title
- Optional role mention on go-live

### 🎁 Twitch Drops
Stay on top of active Twitch Drop campaigns.
- Automatic detection of active drops
- Per-game filter — only see drops for games you care about
- Drop history and cache management commands

### ⭐ Leveling & XP
Gamify your server with a full XP system.
- XP earned per message with configurable rate and cooldown
- Customizable **level-up messages** with variable substitution (`{user}`, `{level}`, etc.)
- **Role rewards** automatically assigned at configurable level thresholds
- Custom level-up images (URL or file upload)
- Leaderboard support

### 🛠️ Custom Commands
Build your own commands without writing code.
- **Text**, **embed**, and **auto-reply** response types
- Trigger on: exact match, contains, regex, links, files, emojis, role mentions
- Variable substitution: `{user}`, `{server}`, `{args}`, and more
- Per-command **cooldowns** and **role restrictions**
- Attachments and custom embed images/thumbnails
- Usage statistics tracked automatically

### 👋 Welcome & Goodbye
Greet new members and farewell departing ones.
- Fully customizable **welcome** and **goodbye** messages
- Separate channels for each event
- Rich embed support with colors and images
- Test command to preview before going live

### 🎭 Reaction Roles
Let members self-assign roles with emoji reactions.
- Attach any emoji to any role on any message
- Multiple reaction roles per message

### 🔰 Auto Roles
Automatically assign roles when members join.
- Multiple roles per server
- Instant assignment on member join

### 📋 Audit Log
Track server activity in a dedicated log channel.
- **Message edits** and **deletions**
- **Member joins** and **leaves**
- **Role changes**
- Enable only the events you need

### ℹ️ Utility
General-purpose commands for everyday use.
- `/help` — categorized, searchable command reference
- `/userinfo` — member details, roles, and join date
- `/serverinfo` — server stats at a glance

---

## 🖥️ Web Dashboard

Manage the entire bot through a clean web interface — no Discord commands required.

| Section | What you can do |
|---|---|
| **Servers** | Overview of all connected servers |
| **Custom Commands** | Create, edit, and delete commands with a full form UI |
| **Welcome** | Configure welcome/goodbye messages and channels |
| **Leveling** | Set XP rates, level-up messages, and role rewards |
| **Reaction Roles** | Manage emoji-to-role mappings |
| **Auto Roles** | Configure roles assigned on join |
| **Free Stuff** | Set alert channels, platform filters, and send test notifications |
| **Streaming** | Add and remove tracked streamers |
| **Twitch Drops** | Configure drop alerts and game filters |
| **TTS** | Set default language and toggle per server |
| **Audit Log** | Choose which events to log and where |
| **Music** | View queue and playback status |

---

## 🚀 Getting Started

### Prerequisites
- Python **3.11+**
- **FFmpeg** installed and on `PATH`
- A Discord bot token — [create one here](https://discord.com/developers/applications)

### Option A — Local / VPS

```bash
# 1. Clone the repo
git clone https://github.com/FishyShu/Discord-Bot-Python.git
cd Discord-Bot-Python

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your tokens and settings

# 4. Run
python bot.py
```

### Option B — Docker

```bash
cp .env.example .env
# Edit .env

docker compose up -d
```

### Environment Variables

| Variable | Description |
|---|---|
| `DISCORD_TOKEN` | Your bot token |
| `DISCORD_CLIENT_ID` | OAuth2 client ID |
| `DISCORD_CLIENT_SECRET` | OAuth2 client secret |
| `DASHBOARD_SECRET_KEY` | Secret key for session cookies |
| `DASHBOARD_HOST` | Dashboard host (default `0.0.0.0`) |
| `DASHBOARD_PORT` | Dashboard port (default `5000`) |
| `SPOTIFY_CLIENT_ID` | Spotify API client ID *(for music)* |
| `SPOTIFY_CLIENT_SECRET` | Spotify API client secret *(for music)* |

---

## 📖 Commands

All commands use Discord's native slash command system.

| Command | Description |
|---|---|
| `/play <query>` | Play a song or add to the queue |
| `/search <query>` | Search YouTube and pick a result |
| `/tts <text>` | Speak text in your voice channel |
| `/soundboard <name>` | Play a sound effect |
| `/separate` | Upload audio and receive split vocal/instrumental tracks |
| `/freestuff setup` | Enable free game alerts in a channel |
| `/freestuff check` | Manually check for new free games now |
| `/freestuff config` | Configure which platforms to track |
| `/stream add <username>` | Track a Twitch streamer for go-live alerts |
| `/twitchdrops setup` | Enable Twitch Drop notifications |
| `/twitchdrops check` | Manually check for active drops |
| `/xp set / reset` | Manage a member's XP |
| `/customcommand add` | Create a custom command |
| `/reactionrole setup` | Add a reaction role to a message |
| `/autorole add` | Add an auto-assigned join role |
| `/welcome set` | Configure the welcome message |
| `/auditlog set` | Configure audit log channel and events |
| `/userinfo [member]` | View a member's details |
| `/serverinfo` | View server stats |
| `/help [category]` | Browse all commands |

---

## 🗺️ Roadmap

Planned features for upcoming releases:

- [ ] **Moderation suite** — warn, mute, kick, ban with case history and mod logs
- [ ] **Giveaway system** — timed giveaways with role requirements and winner selection
- [ ] **Polls & voting** — multi-option timed polls
- [ ] **Ticket system** — support ticket channels with staff routing
- [ ] **Starboard** — community-pinned message highlights
- [ ] **Economy system** — coins, daily rewards, and shop
- [ ] **Reminders** — personal and channel scheduled reminders
- [ ] **Auto-moderation** — filter links, slurs, and spam with configurable actions
- [ ] **Birthday announcements** — automated birthday shoutouts
- [ ] **Rich free game embeds** — FreeStuff-style cards with banners, descriptions, and genre tags
- [ ] **Dashboard dark mode**

---

## 🐳 Deployment

For full VPS deployment with systemd, see [`deploy/DEPLOY.md`](deploy/DEPLOY.md).

---

## 📄 License

MIT — free to use, modify, and self-host.

---

<div align="center">
Made with ❤️ &nbsp;·&nbsp; <a href="https://github.com/FishyShu/Discord-Bot-Python/releases">Releases</a> &nbsp;·&nbsp; <a href="https://github.com/FishyShu/Discord-Bot-Python/issues">Issues</a>
</div>
