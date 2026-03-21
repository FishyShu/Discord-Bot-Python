# Contributing to Discord-Bot-Python

Thank you for your interest in contributing! Below are guidelines to get you started.

## Getting Started

### Fork & Clone

```bash
# 1. Fork the repo on GitHub, then clone your fork
git clone https://github.com/<your-username>/Discord-Bot-Python.git
cd Discord-Bot-Python

# 2. Add the upstream remote
git remote add upstream https://github.com/FishyShu/Discord-Bot-Python.git
```

### Running Locally

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Copy the example env and fill in your values
cp .env.example .env

# 3. Start the bot
python bot.py
```

> **Note:** You will need a Discord bot token, a test server, and (optionally) a PostgreSQL database. See the README for full setup details.

### Running with Docker

```bash
docker-compose up --build
```

## Making Changes

1. Create a feature branch from `master`:
   ```bash
   git checkout -b feat/my-feature
   ```
2. Make your changes and commit with a clear message:
   ```bash
   git commit -m "feat: add my feature"
   ```
3. Keep your branch up to date:
   ```bash
   git fetch upstream
   git rebase upstream/master
   ```

## Submitting a Pull Request

- Open a PR against the `master` branch.
- Describe **what** you changed and **why**.
- Reference any related issues (e.g. `Closes #42`).
- Ensure there are no merge conflicts.
- Be responsive to review feedback.

## Reporting Bugs & Requesting Features

Please use [GitHub Issues](https://github.com/FishyShu/Discord-Bot-Python/issues).

- **Bug report:** Include steps to reproduce, expected vs. actual behavior, and your environment (Python version, OS, etc.).
- **Feature request:** Describe the problem it solves and any alternatives you considered.

## Code Style

- Follow [PEP 8](https://peps.python.org/pep-0008/).
- Keep cogs self-contained; avoid coupling cogs to each other.
- Do **not** commit `.env` or any secrets.
