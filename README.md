# Home Automation Bot

A secure, self-hosted Telegram bot for home automation running on Raspberry Pi.

---

## Quick Start

### 1. Prerequisites
- Python 3.11+
- Telegram account
- Raspberry Pi (for deployment)

### 2. Get your credentials

1. **Bot Token**: Message [@BotFather](https://t.me/BotFather) on Telegram → `/newbot` → copy the token
2. **Your User ID**: Message [@userinfobot](https://t.me/userinfobot) → copy your numeric ID

### 3. Setup

```bash
# Clone and enter the project
cd whatsapp-bot

# Run setup script (creates venv + .env)
bash scripts/setup.sh

# Fill in your credentials
nano .env
```

### 4. Run locally

```bash
source venv/bin/activate
python src/main.py
```

### 5. Test the bot

Open Telegram and send `/start` to your bot — it should reply with a welcome message.

---

## Available Commands

| Command | Description | Auth required |
|---------|-------------|---------------|
| `/start` | Start the bot and show welcome message | Yes |
| `/help` | List all available commands | Yes |
| `/status` | Show bot and system status | Yes |
| `/test` | Test the connection | Yes |
| `/lights on\|off` | Control lights | Yes |
| `/device <name> on\|off` | Control a named device | Yes |

---

## Raspberry Pi Deployment

```bash
# On your Raspberry Pi, run:
bash scripts/install_service.sh

# The bot will now start automatically on boot
# Check status with:
sudo systemctl status homebot
```

---

## Project Structure

```
src/
├── main.py          # Entry point
├── config.py        # Environment configuration
├── bot.py           # Bot framework and handler registration
├── auth.py          # User authentication
├── commands/        # Telegram command handlers
├── devices/         # Device abstraction layer
├── utils/           # Shared utilities
└── database/        # Data persistence
tests/               # Unit tests
scripts/             # Setup and deployment scripts
systemd/             # systemd service file
```

---

## Development

```bash
# Run tests
pytest tests/ -v

# Format code
black src/

# Lint
pylint src/
```

---

## Security Notes

- All secrets are stored in `.env` (never committed to git)
- Only whitelisted Telegram user IDs can interact with the bot
- All user input is validated and sanitized
- Rate limiting prevents abuse
- All actions are logged for audit
