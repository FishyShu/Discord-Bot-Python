#!/usr/bin/env bash
set -euo pipefail

# ── Discord Bot — Oracle Cloud VM Setup ──────────────────────────────
# Run on a fresh Ubuntu 22.04 ARM instance:
#   curl -fsSL https://raw.githubusercontent.com/<user>/<repo>/master/deploy/setup.sh | bash
# Or clone the repo first and run:  bash deploy/setup.sh

REPO_URL="${REPO_URL:-}"
APP_DIR="$HOME/discord-bot"

echo "=== Discord Bot Setup ==="

# ── 1. Install Docker ────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    echo "Docker installed. You may need to log out and back in for group changes."
fi

# Ensure docker compose plugin is available
if ! docker compose version &>/dev/null; then
    echo "Installing Docker Compose plugin..."
    sudo apt-get update && sudo apt-get install -y docker-compose-plugin
fi

# ── 2. Clone or update repo ─────────────────────────────────────────
if [ -d "$APP_DIR" ]; then
    echo "Updating existing repo in $APP_DIR..."
    cd "$APP_DIR" && git pull
else
    if [ -z "$REPO_URL" ]; then
        read -rp "GitHub repo URL (e.g. https://github.com/user/repo): " REPO_URL
    fi
    echo "Cloning $REPO_URL..."
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# ── 3. Create .env if missing ───────────────────────────────────────
if [ ! -f .env ]; then
    echo ""
    echo "No .env file found — let's create one."
    cp .env.example .env

    read -rp "Discord bot token: " token
    sed -i "s|DISCORD_TOKEN=.*|DISCORD_TOKEN=$token|" .env

    read -rp "Dashboard password: " dash_pass
    sed -i "s|DASHBOARD_PASSWORD=.*|DASHBOARD_PASSWORD=$dash_pass|" .env

    secret=$(openssl rand -hex 32)
    sed -i "s|DASHBOARD_SECRET=.*|DASHBOARD_SECRET=$secret|" .env

    read -rp "Spotify Client ID (leave blank to skip): " sp_id
    [ -n "$sp_id" ] && sed -i "s|SPOTIFY_CLIENT_ID=.*|SPOTIFY_CLIENT_ID=$sp_id|" .env
    read -rp "Spotify Client Secret (leave blank to skip): " sp_secret
    [ -n "$sp_secret" ] && sed -i "s|SPOTIFY_CLIENT_SECRET=.*|SPOTIFY_CLIENT_SECRET=$sp_secret|" .env

    read -rp "Twitch Client ID (leave blank to skip): " tw_id
    [ -n "$tw_id" ] && sed -i "s|TWITCH_CLIENT_ID=.*|TWITCH_CLIENT_ID=$tw_id|" .env
    read -rp "Twitch Client Secret (leave blank to skip): " tw_secret
    [ -n "$tw_secret" ] && sed -i "s|TWITCH_CLIENT_SECRET=.*|TWITCH_CLIENT_SECRET=$tw_secret|" .env

    echo ".env created."
fi

# ── 4. Create data directory ────────────────────────────────────────
mkdir -p data

# ── 5. Open firewall for dashboard ──────────────────────────────────
if command -v ufw &>/dev/null; then
    sudo ufw allow 5000/tcp 2>/dev/null || true
fi
if command -v iptables &>/dev/null; then
    sudo iptables -I INPUT -p tcp --dport 5000 -j ACCEPT 2>/dev/null || true
fi

# ── 6. Build and start ──────────────────────────────────────────────
echo "Building and starting the bot..."
docker compose up -d --build

echo ""
echo "=== Done! ==="
echo "Bot is running. Check logs with: docker compose logs -f"
echo "Dashboard: http://$(curl -s ifconfig.me):5000"
