# Telegram Home Assistant

A secure, self-hosted **family home assistant** running on Raspberry Pi, controlled entirely via **Telegram**.
All interaction happens in **Hebrew** through natural language — no commands to memorize.
An on-device Ollama LLM (`qwen3.5:9b`) interprets requests and dispatches to tool functions.

> This project was built entirely with [Claude Code](https://claude.ai/code) — Anthropic's agentic CLI coding tool.
> For full technical context, architecture decisions, and known gotchas, see [CLAUDE.md](CLAUDE.md).

---

## Features

| Feature | Description |
|---|---|
| **Shopping List** | Add, remove, and view a shared household shopping list via natural language |
| **Reminders** | One-shot and recurring reminders, including cross-user ("remind Dad in an hour") |
| **Tasks / Chores** | Assign household tasks with optional due dates and assignees |
| **AI Memory** | The bot remembers personal facts you share ("I'm gluten-sensitive") |
| **Family Notes** | Leave messages for other family members, delivered on their next interaction |
| **Family Broadcast** | Send a message to all registered family members at once |
| **Internal Calendar** | Add and query events stored locally |
| **Apple Calendar** | Sync with iCloud CalDAV — view and create events from Telegram |
| **Morning Briefing** | Daily scheduled summary of events, tasks, reminders, and shopping list |
| **Smart Devices** | Control a Switcher Touch boiler directly over LAN via `aioswitcher` |

---

## Tech Stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Bot framework | python-telegram-bot 21.x |
| Database ORM | SQLAlchemy 2.x (SQLite) |
| Scheduler | APScheduler via PTB's built-in job_queue |
| Local AI | Ollama (`qwen3.5:9b`) — OpenAI-compatible tool-calling |
| Calendar sync | `caldav` library → iCloud CalDAV |
| Smart devices | `aioswitcher` — direct LAN control for Switcher Touch |
| Process manager | systemd |

---

## Project Structure

```
src/
├── main.py                    # Entry point
├── config.py                  # All settings from .env
├── bot.py                     # Handler registration
├── auth.py                    # User authentication
├── ai/
│   └── assistant.py           # Ollama tool-calling engine
├── cal/
│   └── apple_cal.py           # iCloud CalDAV client
├── commands/                  # Telegram command handlers
├── database/
│   └── models.py              # ORM models + CRUD helpers
├── devices/
│   └── switcher.py            # Switcher Touch LAN control
└── utils/                     # Decorators, logger, validators
```

---

## Quick Start

### 1. Prerequisites

- Python 3.11+
- [Ollama](https://ollama.com) installed and running (`ollama serve`)
- Telegram bot token from [@BotFather](https://t.me/BotFather)

### 2. Setup

```bash
# Clone the repo
git clone https://github.com/YardenDalii/Telegram-Home-Assistant.git
cd Telegram-Home-Assistant

# Run setup script (creates venv + .env template)
bash scripts/setup.sh

# Fill in your credentials
nano .env
```

### 3. Pull the AI model

```bash
ollama pull qwen3.5:9b
```

### 4. Run

```bash
source venv/bin/activate
python src/main.py
```

---

## Environment Variables

Create a `.env` file in the project root (never committed to git):

```
BOT_TOKEN=<from @BotFather>
AUTHORIZED_USERS=<comma-separated Telegram user IDs>
ADMIN_USERS=<comma-separated admin IDs>
DATABASE_URL=sqlite:///bot.db
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen3.5:9b

# Optional — Switcher Touch boiler
SWITCHER_DEVICE_IP=<from discovery script>
SWITCHER_DEVICE_ID=<from discovery script>
SWITCHER_DEVICE_KEY=00000000
```

---

## Raspberry Pi Deployment

```bash
# Pull the model on the Pi first
ollama pull qwen3.5:9b

# Install as a systemd service
sudo bash scripts/install_service.sh

# Check status
sudo systemctl status homebot
sudo journalctl -u homebot -f
```

---

## Security

- Only whitelisted Telegram user IDs can interact with the bot (3-layer auth)
- `.env`, `*.db`, `venv/`, and `logs/` are excluded from version control
- All user input is sanitized and validated
- Per-user sliding-window rate limiting
- All actions are audit-logged

---

## Built With Claude Code

This entire project — architecture, features, code, and deployment scripts — was designed and implemented
using [Claude Code](https://claude.ai/code), Anthropic's agentic CLI coding assistant.

The [CLAUDE.md](CLAUDE.md) file in this repo serves as the persistent project context file that Claude Code
uses to understand the codebase. It documents the full feature set, design decisions, known gotchas,
and implementation patterns. It's a useful read if you want to understand how the project is structured
or contribute to it.
