# Deploy Discord Bot on Oracle Cloud Free Tier

## Prerequisites

- [Oracle Cloud account](https://cloud.oracle.com/) (Always Free tier)
- Discord bot token (from [Discord Developer Portal](https://discord.com/developers/applications))
- Your repo pushed to GitHub

## 1. Create an Oracle Cloud VM

1. Go to **Compute → Instances → Create Instance**
2. Choose **Ubuntu 22.04** (Canonical)
3. Shape: **VM.Standard.A1.Flex** (ARM) — 1 OCPU, 1 GB RAM (free tier)
4. Add your SSH public key
5. Click **Create**

### Open port 5000 for the dashboard

1. Go to **Networking → Virtual Cloud Networks → your VCN → Subnet → Security List**
2. Add an **Ingress Rule**: Source `0.0.0.0/0`, Protocol TCP, Destination Port `5000`

## 2. Deploy with Docker (recommended)

SSH into the VM:

```bash
ssh ubuntu@<your-vm-ip>
```

### Option A: Automated setup

```bash
curl -fsSL https://raw.githubusercontent.com/<user>/<repo>/master/deploy/setup.sh -o setup.sh
bash setup.sh
```

The script will install Docker, clone the repo, prompt for `.env` values, and start the bot.

### Option B: Manual setup

```bash
# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in, then:

git clone https://github.com/<user>/<repo>.git ~/discord-bot
cd ~/discord-bot

# Create .env from example
cp .env.example .env
nano .env  # fill in your tokens

mkdir -p data
docker compose up -d --build
```

### Useful commands

```bash
docker compose logs -f        # view logs
docker compose restart         # restart the bot
docker compose down            # stop the bot
docker compose up -d --build   # rebuild after pulling updates
```

## 3. Deploy without Docker (systemd alternative)

```bash
ssh ubuntu@<your-vm-ip>

# Install dependencies
sudo apt update && sudo apt install -y python3.12 python3.12-venv ffmpeg git

# Clone and setup
git clone https://github.com/<user>/<repo>.git ~/discord-bot
cd ~/discord-bot
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
nano .env
mkdir -p data

# Install systemd service
sudo cp deploy/discord-bot.service /etc/systemd/system/discord-bot@.service
sudo systemctl daemon-reload
sudo systemctl enable --now discord-bot@$USER
```

### Useful commands

```bash
sudo systemctl status discord-bot@$USER    # check status
sudo journalctl -u discord-bot@$USER -f    # view logs
sudo systemctl restart discord-bot@$USER   # restart
```

## 4. Verify

1. Check the bot is online in your Discord server
2. Visit `http://<your-vm-ip>:5000` for the dashboard
3. Run `docker compose logs -f` (or `journalctl`) to check for errors

## Updating

```bash
cd ~/discord-bot
git pull
docker compose up -d --build   # Docker
# or
sudo systemctl restart discord-bot@$USER  # systemd
```
