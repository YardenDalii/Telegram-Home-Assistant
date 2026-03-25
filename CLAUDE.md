# Home Automation Bot — Project Checkpoint

## Overview

A secure, self-hosted **family home assistant** running on Raspberry Pi, controlled entirely via **Telegram**.
All interaction happens in **Hebrew** through natural language — the user never types commands manually;
an on-device Ollama LLM (qwen3.5:9b) interprets requests and dispatches to tool functions.

**Status: Feature-complete for the core family-assistant scope. Ready for production testing on Pi.**

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
| HTTP client | `httpx` (sync, wrapped in asyncio.to_thread) |
| Smart devices | `aioswitcher` — direct LAN control for Switcher Touch |
| Process manager | systemd |

---

## Project Structure

```
src/
├── main.py                    # Entry point — init_db() then HomeBot().run()
├── config.py                  # Config class — all settings from .env
├── bot.py                     # HomeBot class — handler registration, _post_init
├── auth.py                    # authenticate_user(), is_admin()
├── ai/
│   └── assistant.py           # Ollama tool-calling engine (handle_chat, _execute_tool)
├── cal/
│   └── apple_cal.py           # iCloud CalDAV client (get_events, create_event, test_connection)
├── commands/
│   ├── calendar.py            # /calendar connect/default/disconnect/status handlers
│   ├── shopping.py            # /shop /add /done /clearshop command handlers
│   ├── system.py              # /start /clearall /reload command handlers
│   └── help.py                # /help command handler (Hebrew help text)
├── database/
│   └── models.py              # All ORM models + CRUD helpers + init_db()
├── devices/
│   └── switcher.py            # Switcher Touch — direct LAN control via aioswitcher
└── utils/
    ├── decorators.py          # @require_auth, @require_admin, @rate_limit
    ├── logger.py              # get_logger(__name__)
    └── validators.py          # sanitize_input(), validate_command()
```

---

## Implemented Features

### Security (all layers active)
- Layer 1: `filters.User` — messages from non-whitelisted IDs never reach handlers
- Layer 2: Catch-all silent-drop handler for unauthorized users
- Layer 3: `@require_auth` decorator on every handler
- Layer 4: `@rate_limit` sliding-window per-user rate limiting

### Onboarding (first contact flow)
New users go through a 4-step registration before reaching the AI:
1. Ask for display name
2. Ask for household role (אבא, אמא, ילד, etc.)
3. Offer Apple Calendar connection (email + app-specific password)
4. Welcome complete → normal AI chat begins

State tracked in `UserProfile` via nullable columns (`display_name`, `role`, `calendar_onboarding_done`).

### Shopping List (`ShoppingItem` model)
- `/shop` — show list
- `/add item1, item2` — add items (slash command)
- `/done N` — remove by position
- `/clearshop` — clear all (admin only)
- Natural language: "הוסף חלב", "תוציא ביצים", "מה יש ברשימה?", "שנה פריט 2 ל-חלב 3%"

### Reminders (`Reminder` model)
- One-shot: "תזכיר לי עוד 20 דקות לצאת לריצה"
- Recurring: daily / weekly / monthly / yearly — "תזכיר לי כל שנה ב-15 במרץ יום הולדת של אמא"
- Cross-user: "תזכיר לאבא עוד שעה לקחת תרופות" — fires to target user's chat
- Confirmation sent to requester when reminder targets another person
- Survives bot restart: `reschedule_pending_reminders()` re-arms all unfired reminders from DB on startup

### AI Memory (`UserMemory` model)
- "תזכור שאני רגיש לגלוטן" — stored fact injected into every future system prompt
- "מה אתה זוכר עלי?" — list stored memories
- "שכח זיכרון 2" — delete by position

### Tasks / Chores (`Task` model)
- "הוסף מטלה לשטוף כלים" — unassigned task
- "תוסיף משימה לאבא לשלם חשמל עד מחר" — assigned with due date
- "הצג משימות" — numbered list with assignee and due date
- "סיימתי 1" — mark complete; "מחק משימה 3" — delete

### Internal Calendar (`CalendarEvent` model)
- "הוסף פגישה מחר ב-14:00" — stores event in SQLite
- "מה יש לי היום?" / "מה יש השבוע?" — shows internal + Apple Calendar events merged
- "מחק אירוע 2" — delete by position

### Apple Calendar (iCloud CalDAV)
- Credentials stored per-user in `UserProfile` (`icloud_username`, `icloud_app_password`)
- App-specific password required (generated at appleid.apple.com)
- "חבר Apple Calendar: user@icloud.com / xxxx-xxxx-xxxx-xxxx" — tests + saves
- Events from iCloud merged into `get_today_schedule` / `get_week_schedule` responses
- "הוסף לאייקלאוד: פגישה עם רופא מחר ב-10:00" — creates event in iCloud

### Family Coordination (`FamilyNote` model)
- **Broadcast**: "שלח לכולם: ארוחת ערב מוכנה!" — Telegram message to every other registered user
- **Leave a note**: "תשאיר לאמא הודעה שהתקשרו מבית הספר" — delivered next time recipient messages the bot
- Family member list (name + role) injected into system prompt for cross-user references

### Morning Briefing
- "שלח לי סיכום בוקר כל יום ב-7:00" — schedules daily job per user
- Briefing includes: today's events (internal + Apple), active reminders count, open tasks, shopping list count
- Time stored in `UserProfile.briefing_hour/minute`
- Survives restart: `reschedule_all_briefings()` re-arms all scheduled briefings on startup

### Smart Device Control
- 5 AI tools: `hk_list_devices`, `hk_turn_on`, `hk_turn_off`, `hk_set_brightness`, `hk_get_status`
- Device registry in `assistant.py` (`_KNOWN_DEVICES`) maps name keywords → device type
- **Switcher Touch 340A**: direct LAN control via `aioswitcher` — `src/devices/switcher.py`
  - Config: `SWITCHER_DEVICE_IP`, `SWITCHER_DEVICE_ID`, `SWITCHER_DEVICE_KEY` in `.env`
  - Run `python3 /tmp/discover_switcher.py` (after `pip install aioswitcher`) to find these values
- **PalGate / מרווה**: not yet implemented (direct API TBD)
- Keyword routing: `_KW_HK` in `assistant.py` triggers HK tools
- Passthrough: `hk_list_devices` + `hk_get_status` bypass second-pass AI

---

## Database Models

| Model | Table | Purpose |
|---|---|---|
| `CommandLog` | `command_log` | Audit log for all commands |
| `ShoppingItem` | `shopping_items` | Shared household shopping list |
| `Reminder` | `reminders` | One-shot and recurring reminders |
| `UserMemory` | `user_memories` | Per-user persistent facts for AI context |
| `Task` | `tasks` | Household chores with optional assignee + due date |
| `FamilyNote` | `family_notes` | Held messages delivered on next contact |
| `UserProfile` | `user_profiles` | Per-user settings, iCloud creds, briefing time |

Schema migrations run automatically via `init_db()` — ALTER TABLE statements catch columns added after initial creation.

---

## AI System (`src/ai/assistant.py`)

The entire conversational interface runs through `handle_chat`:

1. Onboarding gate (4 steps before reaching AI)
2. Pending notes delivered to recipient
3. Build `system` prompt: identity + `_SYSTEM_PROMPT` + today's date + family members + memories + Hebrew language reinforcement
4. Call Ollama (blocking, run in executor)
5. Dispatch tool calls via `_execute_tool(name, args, user_id, username, job_queue, context)`
6. Fall back to `_parse_tool_from_content()` for models that embed JSON in text instead of using native tool calls

**Known tool categories:** shopping (6 tools), reminders (3 tools), memory (3 tools), tasks (4 tools), calendar (6 tools), family (4 tools), smart devices (5 tools).

**Language enforcement** — system prompts are in English; user-facing output is always Hebrew:
- `_PROMPT_BASE` (English): `"Respond to the user in Hebrew only."` — primary language lock
- All `_PROMPT_*` constants are in English — **required** for qwen3.5:9b to emit tool calls reliably
- Second-pass summarisation prompts remain in Hebrew (no tool calling, so no regression risk)
- Broadcast tool: explicit instruction not to add English translations to family messages

**Response cleaning** — `_clean_response()` is applied to all user-facing output. It strips `<think>...</think>` blocks and any leading English text that appears before the first Hebrew character (defensive guard against models that leak reasoning as plain text).

---

## Environment Variables (`.env`)

```
BOT_TOKEN=<from @BotFather>
AUTHORIZED_USERS=<comma-separated Telegram user IDs>
ADMIN_USERS=<comma-separated admin IDs>
LOG_LEVEL=INFO
DATABASE_URL=sqlite:///bot.db
RATE_LIMIT=10
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen3.5:9b
SWITCHER_DEVICE_NAME=Switcher Touch
SWITCHER_DEVICE_IP=<from discovery script>
SWITCHER_DEVICE_ID=<from discovery script>
SWITCHER_DEVICE_KEY=00000000
```

---

## IMPORTANT: Keeping `/help` Up to Date

**Every time a feature is added, changed, or removed, update `src/commands/help.py`.**

The `_HELP_TEXT` constant in that file is what users see via `/help`. It must reflect the actual current capabilities of the bot — including natural-language examples, slash commands, and device names. If a device is renamed, a tool is added, or a feature changes behaviour, the corresponding line in `_HELP_TEXT` must be updated in the same change.

---

## Known Patterns & Gotchas

- **`src/cal/` not `src/calendar/`** — The directory must stay named `cal`. A directory named `calendar` in the Python path shadows the stdlib `calendar` module, breaking `http.cookiejar` → `httpx` → `ollama`.
- **System prompts must be in English** — `qwen3.5:9b` reasons about tool calls internally but outputs natural language when the system prompt is in Hebrew. All `_PROMPT_*` constants in `assistant.py` must remain in English. `qwen3:8b` is a safe fallback if tool-calling breaks.
- **Ollama must be running** before starting the bot. On Pi: `ollama serve` + `ollama pull qwen3.5:9b`.
- **`job_queue` requires PTB's scheduler extra** — `python-telegram-bot[job-queue]` or explicit APScheduler install.
- **Datetimes in DB are UTC** — the AI system prompt injects today's local date so the model can resolve "מחר", "ביום ראשון", etc. correctly.
- **Cross-user reminders** target the recipient's `user_id` as `chat_id` — works only if the recipient has previously started the bot (Telegram restriction).
- **iCloud app-specific passwords** are separate from the Apple ID password — generated at appleid.apple.com → Security → App-Specific Passwords.
- **Homebridge REST API + Socket.IO are not used** — The Homebridge Config UI X REST API only returns the bridge device itself, not child bridge accessories. Socket.IO events time out silently. Direct device control via `aioswitcher` is used instead.
- **macOS Local Network privacy**: run the bot from Terminal.app, not VSCode's integrated terminal. macOS may deny LAN TCP from VSCode's process even when ping works.

---

## Running the Bot

```bash
source venv/bin/activate
python src/main.py
```

## Deployment (Raspberry Pi)

```bash
ollama pull qwen3.5:9b          # first-time setup
sudo bash scripts/install_service.sh
sudo systemctl status homebot
sudo journalctl -u homebot -f
```

---

## What's Not Yet Done

- **PalGate / מרווה direct control** — device is listed in `_KNOWN_DEVICES` but control not implemented; API TBD
- **Unit tests** — `tests/` directory exists but no tests written for the new features
- **Web dashboard** — not planned for current phase
- **Multi-timezone support** — briefing times are treated as local server time, no per-user timezone
