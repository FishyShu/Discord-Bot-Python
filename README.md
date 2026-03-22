<div align="center">

# 🤖 Tagokura Bot

**A feature-rich, self-hosted Discord bot with a web dashboard**

[![Version](https://img.shields.io/badge/version-1.3.0-blue?style=for-the-badge)](https://github.com/FishyShu/Discord-Bot-Python/releases)
[![Python](https://img.shields.io/badge/python-3.12+-yellow?style=for-the-badge&logo=python)](https://python.org)
[![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discordpy.readthedocs.io)
[![License](https://img.shields.io/badge/license-MIT-green?style=for-the-badge)](LICENSE)

[Features](#-features) • [Dashboard](#-web-dashboard) • [Setup](#-getting-started) • [Commands](#-commands) • [Roadmap](#-roadmap)

</div>

---

## ✨ Features

### 🤖 AI Chatbot
A fully configurable AI assistant powered by Google Gemini, Claude, or GPT-4o.
- Responds in **active channels** and to **@mentions** anywhere
- **Personality modes** — Manual system prompt, choose a Preset, or Auto-generate from a description
- **5 built-in presets** — Friendly Helper, Anime Waifu, Professional Assistant, Caine (TADC), Winston (Overwatch)
- **Response length** — Short, Medium, or Long
- **Behaviour flags** — markdown control, emoji toggle, mention on reply, Discord quote-reply, typing indicator
- **Webhook persona** — custom bot name and avatar per server via Discord webhook
- **Long-term memory** — remembers things about each user across conversations
- **Web search** — auto-injects DuckDuckGo results for factual queries
- **URL summarisation** — reads and summarises linked pages
- **Image generation** — `/imagine` via fal.ai or Pollinations.ai fallback
- **Blocklist** — refuse to discuss specific topics per server
- **Bring your own key** — use Claude, GPT-4o, or premium Gemini with your own API key

### 🎵 Music Player
Full-featured music bot powered by yt-dlp.
- Play from **YouTube**, **Spotify**, **Tidal**, or search queries
- **YouTube playlist** support — entire playlist queued at once
- Interactive **search picker** — choose from top results before playing
- **Queue management** — skip, stop, pause, resume, shuffle, loop
- **Audio filters** — bass boost, nightcore, vaporwave, and more
- **SoundCloud fallback** when a stream fails
- Auto-disconnect on inactivity

### 🛡️ Moderation
Keep your server safe with a full moderation suite.
- `/kick`, `/ban`, `/unban`, `/softban`, `/timeout`, `/warn`, `/warnings`, `/purge`
- `/modlog` — queryable history of all mod actions with optional user/moderator filter
- `/delwarn` — delete a specific warning by case ID
- All actions logged persistently with timestamps

### 🚨 Anti-Raid Protection
Automatic server defence against raids and spam.
- **Mass join detection** — triggers lockdown when a flood of accounts joins
- **New account filter** — block accounts younger than a configurable age
- **Mention spam** — auto-mute on excessive pings
- **Message spam** — rate-limit enforcement per user
- `/antiraid set/show/lockdown/unlock` for manual control

### 🌍 Auto-Translate
Automatic message translation per channel.
- Translate messages to any language on the fly (no API key required)
- Per-channel configuration via dashboard

### 🎁 Giveaways
Run timed giveaways directly in Discord.
- Create giveaways with a prize, duration, and winner count
- Auto-end and auto-announce winner(s) when time expires
- `/giveaway reroll` to re-pick a winner
- Dashboard management

### 💾 Server Backup
Export and restore all bot configuration for a server.
- Single-command full backup of all settings as JSON
- Restore from backup on any server

### 🎙️ Text-to-Speech
Speak text aloud in voice channels using Google TTS.
- Supports **multiple languages**
- Per-server default language configuration

### 🔊 Soundboard
Play custom sound effects in voice channels.
- Upload and manage `.mp3` / `.wav` files per server
- Autocomplete from all available sounds

### 🎛️ Voice Separation
AI-powered audio stem separation.
- Upload any audio file and receive separate **vocal** and **instrumental** tracks as `.wav` files

### 🎮 Free Game Alerts
Automatically announces free games across platforms.
- Monitors **Epic Games**, **Steam**, **GOG**, **Ubisoft**, **Humble Bundle**, and more
- **Reddit** `/r/FreeGameFindings` integration
- Per-server **platform filter** and optional **role mention**

### 📺 Streamer Notifications
Go-live alerts for your favourite streamers.
- Track **Twitch** streamers per server
- Rich embeds with game, viewer count, and title

### 🎁 Twitch Drops
Stay on top of active Twitch Drop campaigns.
- Automatic detection of active drops with per-game filtering

### ⭐ Leveling & XP
Gamify your server with a full XP system.
- Configurable XP rate and cooldown
- **Role rewards** at level thresholds
- Customisable level-up messages with variable substitution
- Leaderboard support

### 🛠️ Custom Commands
Build your own commands without code.
- **Text**, **embed**, and **auto-reply** response types
- Trigger on: exact match, contains, regex, links, files, emojis, role mentions
- Per-command cooldowns, role restrictions, and usage statistics

### 👋 Welcome & Goodbye
- Fully customisable welcome and goodbye messages with embed support
- Test command to preview before going live

### 🎭 Reaction Roles
Let members self-assign roles with emoji reactions.

### 🔰 Auto Roles
Automatically assign roles when members join.

### 📋 Audit Log
Track server activity in a dedicated log channel.
- Message edits and deletions, member joins/leaves, role changes
- **Ghost ping detection** — alerts when a mention is removed via edit or delete

### 😄 Fun Commands
Lighthearted commands for entertainment.
- `/meme`, `/joke`, `/8ball`, `/coinflip`, `/roll`, `/mock`, `/ship`, and more

### ℹ️ Utility
- `/help` — categorised, searchable command reference
- `/userinfo`, `/serverinfo`, `/ping`, `/uptime`

---

## 🖥️ Web Dashboard

Manage the entire bot through a clean web interface — no Discord commands required.

| Section | What you can do |
|---|---|
| **Servers** | Overview of all connected servers |
| **AI Chatbot** | Personality, behaviour, webhook persona, channels, blocklist, API key |
| **Custom Commands** | Create, edit, and delete commands |
| **Welcome** | Configure welcome/goodbye messages and channels |
| **Leveling** | XP rates, level-up messages, role rewards |
| **Reaction Roles** | Emoji-to-role mappings |
| **Auto Roles** | Roles assigned on join |
| **Moderation** | View mod log, manage warnings |
| **Anti-Raid** | Configure thresholds and view raid log |
| **Giveaways** | Create and manage giveaways |
| **Backup** | Export or restore server configuration |
| **Auto-Translate** | Per-channel translation settings |
| **Free Stuff** | Alert channels, platform filters, test notifications |
| **Streaming** | Add and remove tracked Twitch streamers |
| **Twitch Drops** | Configure drop alerts and game filters |
| **TTS** | Default language and toggle |
| **Audit Log** | Choose events to log and target channel |

---

## 🚀 Getting Started

### Prerequisites
- Python **3.12+**
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

| Variable | Required | Description |
|---|---|---|
| `DISCORD_TOKEN` | ✅ | Your bot token |
| `DISCORD_CLIENT_ID` | ✅ | OAuth2 client ID |
| `DISCORD_CLIENT_SECRET` | ✅ | OAuth2 client secret |
| `DASHBOARD_SECRET_KEY` | ✅ | Secret key for session cookies |
| `DASHBOARD_PASSWORD` | ✅ | Dashboard login password |
| `DASHBOARD_PORT` | — | Dashboard port (default `5000`) |
| `SPOTIFY_CLIENT_ID` | — | Spotify API client ID *(music)* |
| `SPOTIFY_CLIENT_SECRET` | — | Spotify API client secret *(music)* |
| `FAL_API_KEY` | — | fal.ai key for image generation *(optional, falls back to Pollinations)* |
| `ENCRYPTION_KEY` | — | Fernet key for encrypting user-provided API keys |
| `SYNC_COMMANDS` | — | Set to `1` to force-sync slash commands on startup |

---

## 📖 Commands

All commands use Discord's native slash command system. Use `/help` in Discord for the full searchable reference.

### 🤖 AI
| Command | Description |
|---|---|
| `/ai config personality` | Set personality mode (manual / preset / auto-generate) |
| `/ai config length` | Set response length (short / medium / long) |
| `/ai config formatting` | Configure markdown and emoji usage |
| `/ai config behaviour` | Toggle mentions, reply mode, typing indicator |
| `/ai config language` | Set the response language |
| `/ai config webhook-set` | Configure a webhook persona (custom name + avatar) |
| `/ai config webhook-clear` | Remove the webhook persona |
| `/ai memory` | View what the bot remembers about you |
| `/ai memory clear` | Clear your memory for this server |
| `/ai info` | Show current AI config for this server |
| `/imagine <prompt>` | Generate an image with AI |

### 🎵 Music
| Command | Description |
|---|---|
| `/play <query>` | Play a song or add to queue (YouTube / Spotify / Tidal / search) |
| `/search <query>` | Search YouTube and pick a result |
| `/skip` | Skip the current track |
| `/queue` | Show the current queue |
| `/pause` / `/resume` | Pause or resume playback |
| `/stop` | Stop playback and clear the queue |
| `/nowplaying` | Show the current track |
| `/loop` | Toggle loop mode |
| `/shuffle` | Shuffle the queue |
| `/musicconfig` | Configure music settings (fallback service, etc.) |

### 🛡️ Moderation
| Command | Description |
|---|---|
| `/kick <member>` | Kick a member |
| `/ban <member>` | Ban a member |
| `/unban <user>` | Unban a user |
| `/softban <member>` | Ban and immediately unban (clears messages) |
| `/timeout <member> <duration>` | Timeout a member |
| `/warn <member> <reason>` | Issue a warning |
| `/warnings <member>` | View a member's warnings |
| `/delwarn <id>` | Delete a specific warning |
| `/modlog` | Query the mod action history |
| `/purge <amount>` | Bulk-delete messages |

### 🚨 Anti-Raid
| Command | Description |
|---|---|
| `/antiraid set` | Configure anti-raid thresholds |
| `/antiraid show` | Show current anti-raid settings |
| `/antiraid lockdown` | Manually lock down the server |
| `/antiraid unlock` | Lift a lockdown |

### Other
| Command | Description |
|---|---|
| `/tts <text>` | Speak text in your voice channel |
| `/soundboard <name>` | Play a sound effect |
| `/separate` | Split audio into vocal + instrumental tracks |
| `/imagine <prompt>` | Generate an image |
| `/freestuff setup/check/config` | Free game alert management |
| `/stream add/remove/list` | Twitch streamer tracking |
| `/twitchdrops setup/check` | Twitch Drop notifications |
| `/giveaway create/end/reroll` | Run a giveaway |
| `/xp set/reset` | Manage a member's XP |
| `/customcommand add/edit/delete` | Custom command management |
| `/reactionrole setup/remove` | Reaction role management |
| `/autorole add/remove` | Auto-role management |
| `/welcome set` | Configure welcome messages |
| `/auditlog set` | Configure audit log |
| `/userinfo [member]` | View a member's details |
| `/serverinfo` | View server stats |
| `/help [category]` | Browse all commands |

---

## 🗺️ Roadmap

### Music (ongoing)
- [ ] Seek / rewind — `/seek <seconds>`
- [ ] Queue persistence across restarts
- [ ] DJ role system
- [ ] Track history — `/history`
- [ ] Lyrics integration — `/lyrics` via Genius API
- [ ] Autoplay / recommendations
- [ ] Apple Music support
- [ ] Per-track source badge

### Future Features
- [ ] **Polls & voting** — multi-option timed polls
- [ ] **Ticket system** — support ticket channels with staff routing
- [ ] **Starboard** — community-pinned message highlights
- [ ] **Reminders** — personal and channel scheduled reminders
- [ ] **Birthday announcements** — automated shoutouts
- [ ] **PostgreSQL migration** — replace SQLite for larger deployments

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
