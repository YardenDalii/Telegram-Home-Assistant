"""Conversational AI home assistant using a local Ollama model.

Handles plain-text messages from authorized users. Uses Ollama's tool-calling
API (OpenAI-compatible format) to detect intent and dispatch to tool functions.
All user-facing messages are in Hebrew.

Tested models:
  - gemma4:e4b  — better Hebrew quality; set OLLAMA_MODEL=gemma4:e4b
  - qwen3.5:9b  — reliable tool calling, good Hebrew; safe fallback
  NOTE: System prompts must be in English for reliable tool calling.
  NOTE: think=False suppresses chain-of-thought on models that support it (qwen3).
        _clean_response() strips any leaked <think>...</think> blocks as a fallback.

Setup on the Pi:
    curl -fsSL https://ollama.com/install.sh | sh
    ollama pull gemma4:e4b   # or qwen3.5:9b
"""

import asyncio
import json
import re
from datetime import date, datetime, timedelta, timezone
from collections.abc import Callable
from typing import Any

import ollama
from telegram import ReactionTypeEmoji, Update
from telegram.ext import ContextTypes

from cal.apple_cal import create_event, get_events_for_date, get_events_for_range
import devices.switcher as _switcher_dev
from database.models import (
    add_note,
    add_reminder,
    add_shopping_item,
    cancel_reminder,
    clear_shopping_list,
    create_user_profile,
    get_all_pending_reminders,
    get_all_user_profiles,
    get_pending_reminders,
    get_shopping_items,
    get_user_profile,
    mark_notes_delivered,
    mark_reminder_fired,
    get_pending_notes,
    remove_shopping_item,
    set_user_gender,
    set_user_name,
    update_shopping_item,
)
from utils.decorators import rate_limit, require_auth
from utils.logger import get_logger

logger = get_logger(__name__)


# Per-model tuning profiles — matched by substring against OLLAMA_MODEL.
# Keys checked in order; first match wins. "default" is the fallback.
# think: False suppresses chain-of-thought on models that support it (qwen3).
#        Ignored silently by models that don't.
_MODEL_PROFILES: list[tuple[str, dict]] = [
    ("gemma4", {
        "first_predict":  300,
        "second_predict": 180,
        "num_ctx":        2048,
        "think":          False,
        "temperature":    0.7,
        "top_k":          20,
    }),
    ("qwen3.5", {
        "first_predict":  400,
        "second_predict": 350,
        "num_ctx":        4096,
        "think":          False,
        "temperature":    None,
        "top_k":          None,
    }),
    ("default", {
        "first_predict":  400,
        "second_predict": 350,
        "num_ctx":        4096,
        "think":          False,
        "temperature":    None,
        "top_k":          None,
    }),
]


def _get_model_profile() -> dict:
    """Return the tuning profile for the currently configured model."""
    from config import Config
    model = Config.OLLAMA_MODEL.lower()
    for key, profile in _MODEL_PROFILES:
        if key == "default" or key in model:
            return profile
    return _MODEL_PROFILES[-1][1]  # unreachable, but safe


# Module-level Ollama client — created once on first use, reused for every message.
_ollama_client: ollama.Client | None = None


def _resolve_family_member(hint: str):
    """Return the UserProfile whose name matches hint, or None."""
    hint_lower = hint.lower()
    for p in get_all_user_profiles():
        if p.display_name and hint_lower in p.display_name.lower():
            return p
    return None


def _get_ollama_client() -> ollama.Client:
    global _ollama_client
    if _ollama_client is None:
        from config import Config
        _ollama_client = ollama.Client(host=Config.OLLAMA_HOST)
    return _ollama_client


# ---------------------------------------------------------------------------
# Known smart devices — add new entries here as more devices are added.
# "keywords" are Hebrew/English terms the user might say to refer to this device.
# ---------------------------------------------------------------------------

_KNOWN_DEVICES = [
    {
        "id": "switcher",
        "type": "switcher",
        "keywords": ["switcher", "דוד", "בוילר", "מתג", "מאוורר", "מפסק", "חשמל", "מכשיר"],
    },
    {
        "id": "marova",
        "type": "palgate",
        "keywords": ["מרווה", "תריס", "שטר", "שער", "גייט", "gate", "palgate"],
    },
]


def _find_device(hint: str) -> dict | None:
    """Return the first known device whose keywords match the user's hint."""
    h = hint.lower()
    for dev in _KNOWN_DEVICES:
        if any(kw in h for kw in dev["keywords"]):
            return dev
    return None


# ---------------------------------------------------------------------------
# Per-task system prompts — only the relevant ones are injected per message
# To add a new feature: add a _PROMPT_XXX string and a check in handle_chat
# ---------------------------------------------------------------------------

# System prompts are intentionally in English.
# qwen3.5:9b (the recommended model) fails to emit tool calls when the system prompt
# is in Hebrew — it reasons about calling tools but outputs natural language instead.
# English prompts fix this while the model still responds to users in Hebrew.

_PROMPT_BASE = (
    "/no_think\n"
    "You MUST call a tool for every action request — never describe an action without executing it. "
    "Respond to the user in Hebrew only. You are a friendly and warm smart home assistant. "
    "Add at most one emoji if truly relevant — do not overdo it."
)

_PROMPT_SHOPPING = (
    "\n\n== Shopping list ==\n"
    "Add/remove/edit items by position number or name. Clear all when asked."
)

_PROMPT_REMINDERS = (
    "\n\n== Reminders ==\n"
    "CRITICAL: You MUST call set_reminder — never just promise or say you will remind. No tool call = no reminder.\n"
    "Calculate minutes from now: 1 hour=60, 1.5 hours=90, 1 day=1440.\n"
    "'at HH:MM' → minutes until that time (next day if already past).\n"
    "Recurring reminder: recurring=true + recurrence_type.\n"
    "Remind someone else: recipient=name/role.\n"
    "If relative to a calendar event ('after work', 'when meeting ends'): "
    "FIRST call get_schedule for today, find the event end time, calculate minutes from now, THEN call set_reminder. "
    "If the event is not found, ask the user what time it ends."
)

_PROMPT_FAMILY = (
    "\n\n== Family ==\n"
    "broadcast_message: send to all family members (excluding sender).\n"
    "leave_note: send directly to a specific person — delivered immediately.\n"
    "Do not add translations or English explanations to family messages."
)

_PROMPT_GENERAL = "\n\nFor greetings and questions answer directly in Hebrew without tools. For unclear requests ask a short clarifying question."

_PROMPT_CALENDAR = (
    "\n\n== Apple Calendar ==\n"
    "ALWAYS call the function — never describe an action that was not executed!\n"
    "get_schedule: period=today/tomorrow/week — show events from iCloud.\n"
    "add_event: title, date_str (YYYY-MM-DD), time_str (HH:MM), duration_minutes (default 60), calendar_name (optional).\n"
    "date_str must be YYYY-MM-DD — use the day table provided in the prompt."
)

_PROMPT_HK = (
    "\n\n== Smart device control ==\n"
    "You MUST call a tool for every device request. NEVER respond with text only.\n"
    "hk_turn_on: call this whenever the user wants a device ON immediately.\n"
    "hk_turn_off: call this whenever the user wants a device OFF immediately.\n"
    "schedule_device_action: call this when the user wants a device turned on/off AFTER a delay "
    "('בעוד 5 דקות', 'בעוד שעה'). Use action='turn_on' or action='turn_off'.\n"
    "hk_get_status: ONLY when user asks for current state ('מה מצב', 'האם דולק').\n"
    "hk_list_devices: list all devices.\n"
    "hk_set_brightness: brightness 0-100.\n"
    "CRITICAL: 'תוכל להדליק?' is a command, not a question. Call hk_turn_on immediately."
)

# ---------------------------------------------------------------------------
# Tool schemas (OpenAI-compatible format used by Ollama)
# ---------------------------------------------------------------------------

_SHOPPING_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_shopping_items",
            "description": "Add one or more items to the shopping list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of item names to add",
                    }
                },
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_shopping_list",
            "description": "Get the current shopping list.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_shopping_item",
            "description": "Remove an item from the shopping list by its 1-based position number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_number": {
                        "type": "integer",
                        "description": "1-based position of the item in the list",
                    }
                },
                "required": ["item_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_shopping_item_by_name",
            "description": "Remove an item from the shopping list by its name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {
                        "type": "string",
                        "description": "The name of the item to remove (partial/case-insensitive match)",
                    }
                },
                "required": ["item_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_shopping_item",
            "description": "Rename an item in the shopping list by its 1-based position number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_number": {"type": "integer", "description": "1-based position of the item to edit"},
                    "new_name": {"type": "string", "description": "The new name for the item"},
                },
                "required": ["item_number", "new_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_shopping_item_by_name",
            "description": "Rename an item in the shopping list by its current name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {"type": "string", "description": "Current name of the item (partial match OK)"},
                    "new_name": {"type": "string", "description": "The new name for the item"},
                },
                "required": ["item_name", "new_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_shopping_list",
            "description": "Delete every item from the shopping list. Use only when explicitly asked.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

_REMINDER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": (
                "Schedule a reminder for the current user or another family member. "
                "Use 'recipient' to target someone else. "
                "Use 'recurring' + 'recurrence_type' for repeating reminders."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "What to remind about"},
                    "minutes": {
                        "type": "integer",
                        "description": "How many minutes from now to send the reminder (1 hour = 60 minutes)",
                    },
                    "recipient": {
                        "type": "string",
                        "description": "Name or role of the family member to remind instead of the current user",
                    },
                    "recurring": {
                        "type": "boolean",
                        "description": "True if this reminder should repeat automatically",
                    },
                    "recurrence_type": {
                        "type": "string",
                        "enum": ["daily", "weekly", "monthly", "yearly"],
                        "description": "How often to repeat",
                    },
                },
                "required": ["text", "minutes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_reminders",
            "description": "Show all pending (unfired) reminders for this user.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_reminder",
            "description": "Cancel a pending reminder by its 1-based position in the list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reminder_number": {
                        "type": "integer",
                        "description": "1-based position of the reminder to cancel",
                    }
                },
                "required": ["reminder_number"],
            },
        },
    },
]

_FAMILY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "broadcast_message",
            "description": (
                "Send a message to all family members except the sender. "
                "Use when the user says 'שלח לכולם', 'תודיע לכולם', etc. "
                "Extract only the actual message content — not the instruction itself. "
                "Example: 'שלח לכולם שארוחת ערב מוכנה' → message='ארוחת ערב מוכנה'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Only the message content to broadcast, extracted from the user's request.",
                    },
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "leave_note",
            "description": (
                "Send a message directly to a specific family member right now. "
                "Use when the user says 'תגיד ל...', 'שלח ל...', 'תעביר ל...', 'תשאיר ל...' etc. "
                "Extract only the actual message content, not the instruction. "
                "Example: 'תשאיר לאמא שהתקשרו מבית הספר' → recipient='אמא', message='התקשרו מבית הספר'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient": {
                        "type": "string",
                        "description": "Name of the recipient family member (e.g. 'אמא', 'ירדן')",
                    },
                    "message": {
                        "type": "string",
                        "description": "Only the message content to leave, extracted from the user's request.",
                    },
                },
                "required": ["recipient", "message"],
            },
        },
    },
]


_HK_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "hk_list_devices",
            "description": "List all HomeKit accessories and their current on/off and brightness state.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hk_turn_on",
            "description": "Turn a HomeKit accessory on.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_name": {
                        "type": "string",
                        "description": "Name of the device as the user said it (Hebrew or English)",
                    }
                },
                "required": ["device_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hk_turn_off",
            "description": "Turn a HomeKit accessory off.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_name": {
                        "type": "string",
                        "description": "Name of the device as the user said it (Hebrew or English)",
                    }
                },
                "required": ["device_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hk_set_brightness",
            "description": "Set the brightness of a HomeKit light (0-100).",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_name": {
                        "type": "string",
                        "description": "Name of the light device",
                    },
                    "brightness": {
                        "type": "integer",
                        "description": "Brightness level 0-100",
                    },
                },
                "required": ["device_name", "brightness"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hk_get_status",
            "description": "Get the current state of a specific HomeKit accessory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_name": {
                        "type": "string",
                        "description": "Name of the device to check",
                    }
                },
                "required": ["device_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_device_action",
            "description": (
                "Schedule a device to turn on or off automatically after a delay. "
                "Use this when the user says 'in X minutes', 'in an hour', etc. "
                "Do NOT use hk_turn_on/hk_turn_off for delayed requests — use this instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "device_name": {
                        "type": "string",
                        "description": "Device name as the user said it (Hebrew or English)",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["turn_on", "turn_off"],
                        "description": "Action to perform when the timer fires",
                    },
                    "minutes": {
                        "type": "integer",
                        "description": "Minutes from now to execute the action",
                    },
                },
                "required": ["device_name", "action", "minutes"],
            },
        },
    },
]

_CALENDAR_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_schedule",
            "description": "Show the user's upcoming events from Apple Calendar (iCloud).",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "enum": ["today", "tomorrow", "week"],
                        "description": "Time period to show: today, tomorrow, or week",
                    }
                },
                "required": ["period"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_event",
            "description": (
                "Create a new event in Apple Calendar (iCloud). "
                "date_str must be YYYY-MM-DD (use the day table from the prompt). "
                "time_str is HH:MM in 24h format."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Event title"},
                    "date_str": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                    "time_str": {"type": "string", "description": "Start time in HH:MM (24h)"},
                    "duration_minutes": {
                        "type": "integer",
                        "description": "Duration in minutes (default 60)",
                    },
                    "calendar_name": {
                        "type": "string",
                        "description": "Calendar name to save to (optional — uses default if omitted)",
                    },
                },
                "required": ["title", "date_str", "time_str"],
            },
        },
    },
]


def _build_tools() -> list:
    """Return the full tool list for Ollama."""
    return (
        list(_SHOPPING_TOOLS) + list(_REMINDER_TOOLS) + list(_FAMILY_TOOLS) +
        list(_CALENDAR_TOOLS) + list(_HK_TOOLS)
    )


# ---------------------------------------------------------------------------
# Keyword sets for intent-based tool routing
# ---------------------------------------------------------------------------

_KW_SHOPPING = [
    "קניות", "רשימה", "רשימת", "הוסף", "תוסיף", "הסר", "תוציא",
    "מחק", "שנה", "ערוך", "עדכן", "פריט", "נקה", "לקנות",
]
_KW_REMINDERS = [
    "תזכיר", "תזכורת", "תזמן", "דקות", "שעות", "בעוד", "תזכורות",
    "להזכיר", "הזכר", "הזכירי", "תזכירי", "לזכור", "אל תשכח", "אל תשכחי",
    "remind", "reminder",
]
_KW_FAMILY = [
    "לכולם", "לכל המשפחה", "תשאיר ל", "השאר ל", "תגיד ל", "תעביר ל",
    "שלח ל", "שלחי ל", "תודיע ל", "broadcast",
]
_KW_CALENDAR = [
    "יומן", "אירוע", "פגישה", "לוח זמנים", "לוז", "סדר יום",
    "icloud", "calendar", "אייקלאוד", "לאייקלאוד",
    "מה יש לי היום", "מה יש לי מחר", "מה יש לי השבוע",
    "מה יש היום", "מה יש מחר", "מה יש השבוע",
]
_KW_HK = [
    "הדלק", "כבה", "תדליק", "תכבה", "הפעל", "כיבוי", "הפעלה",
    "בהירות", "אור", "אורות", "מאוורר", "מתג", "תריס",
    "דוד", "בוילר", "מכשיר", "מכשירים", "homekit", "homebridge",
    "מה דולק", "מה פועל", "מה כבוי",
]


def _select_tools(user_text: str) -> list:
    """Return only the tool categories relevant to this message.

    Matches Hebrew keywords to determine which tool groups to include.
    Returns an empty list for purely conversational messages so the model
    skips tool-call processing entirely — significantly faster.
    """
    text = user_text.lower()
    tools: list = []

    has_calendar = any(kw in text for kw in _KW_CALENDAR)
    # Only add shopping tools when there are no calendar keywords — "הוסף פגישה"
    # means "add event", not "add to shopping list". Mixing both tool sets confuses the model.
    if any(kw in text for kw in _KW_SHOPPING) and not has_calendar:
        tools.extend(_SHOPPING_TOOLS)
    if any(kw in text for kw in _KW_REMINDERS):
        tools.extend(_REMINDER_TOOLS)
        # If the reminder references a calendar event time ("after work", "before meeting"),
        # also include calendar tools so the model can look up the event end time first.
        _KW_EVENT_TIME = ["אחרי", "לפני", "אחרי ה", "לפני ה", "כשיגמר", "כשמסתיים", "בסוף"]
        if any(kw in text for kw in _KW_EVENT_TIME):
            tools.extend(_CALENDAR_TOOLS)
    if any(kw in text for kw in _KW_FAMILY):
        tools.extend(_FAMILY_TOOLS)
    if has_calendar:
        tools.extend(_CALENDAR_TOOLS)
    if any(kw in text for kw in _KW_HK):
        tools.extend(_HK_TOOLS)

    # Ambiguous queries like "מה יש לי?" / "מה המצב?" — return all tools
    _AMBIGUOUS = ["מה יש", "מה המצב", "תן לי סיכום", "מה יש לי", "הכל"]
    if not tools and any(kw in text for kw in _AMBIGUOUS):
        return _build_tools()

    return tools


# ---------------------------------------------------------------------------
# Reminder job callback + startup re-scheduler
# ---------------------------------------------------------------------------

async def _send_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback — fires when a scheduled reminder is due.

    If the reminder has an action_type, executes the device command automatically
    and notifies the user of the result instead of a plain reminder text.
    """
    data = context.job.data
    action_type = data.get("action_type")
    action_payload = data.get("action_payload")

    if action_type:
        # Execute the scheduled device action
        action_ok = False
        try:
            if action_type == "hk_turn_on" and action_payload == "switcher":
                await _switcher_dev.turn_on()
                action_ok = True
            elif action_type == "hk_turn_off" and action_payload == "switcher":
                await _switcher_dev.turn_off()
                action_ok = True
        except Exception as exc:
            logger.error(f"Scheduled device action '{action_type}' failed: {exc}")
        status = "✅" if action_ok else "❌ נכשל —"
        await context.bot.send_message(
            chat_id=data["chat_id"],
            text=f"⏰ {status} *{data['text']}*",
            parse_mode="Markdown",
        )
    else:
        await context.bot.send_message(
            chat_id=data["chat_id"],
            text=f"⏰ *תזכורת:* {data['text']}",
            parse_mode="Markdown",
        )

    mark_reminder_fired(data["reminder_id"])

    # Re-schedule next occurrence for recurring reminders.
    # mark_reminder_fired() already created the next DB row — we just need to arm the job.
    if data.get("recurring"):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for r in get_all_pending_reminders():
            if (
                r.user_id == data["chat_id"]
                and r.text == data["text"]
                and r.id != data["reminder_id"]
            ):
                delay = max((r.remind_at - now).total_seconds(), 5)
                context.job_queue.run_once(
                    _send_reminder,
                    when=delay,
                    data={
                        "chat_id": r.user_id,
                        "text": r.text,
                        "reminder_id": r.id,
                        "recurring": True,
                        "action_type": r.action_type,
                        "action_payload": r.action_payload,
                    },
                    name=f"reminder_{r.id}",
                )
                logger.info(f"Re-scheduled recurring reminder {r.id} for user {r.user_id}")
                break


def reschedule_pending_reminders(job_queue: Any) -> None:
    """Re-arm all unfired reminders after a bot restart."""
    pending = get_all_pending_reminders()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for r in pending:
        delay = max((r.remind_at - now).total_seconds(), 5)
        job_queue.run_once(
            _send_reminder,
            when=delay,
            data={
                "chat_id": r.user_id,
                "text": r.text,
                "reminder_id": r.id,
                "recurring": r.recurring,
                "action_type": r.action_type,
                "action_payload": r.action_payload,
            },
            name=f"reminder_{r.id}",
        )
    if pending:
        logger.info(f"Re-scheduled {len(pending)} pending reminder(s) after restart")


# ---------------------------------------------------------------------------
# Tool dispatcher
#
# Register a handler:  @_tool("tool_name")
#                      async def _handle_xxx(args, user_id, username, job_queue, bot) -> str: ...
#
# To add a new tool: define a @_tool(...) function here + add its schema to
# _SHOPPING_TOOLS / _REMINDER_TOOLS above + add its name to _KNOWN_TOOLS below.
# The dispatcher itself never needs to change.
# ---------------------------------------------------------------------------

_ToolHandler = Callable[..., Any]
_TOOL_REGISTRY: dict[str, _ToolHandler] = {}


def _tool(name: str) -> Callable[[_ToolHandler], _ToolHandler]:
    """Decorator — register an async function as the handler for *name*."""
    def decorator(fn: _ToolHandler) -> _ToolHandler:
        _TOOL_REGISTRY[name] = fn
        return fn
    return decorator


async def _execute_tool(
    name: str,
    args: dict[str, Any],
    user_id: int,
    username: str | None,
    job_queue: Any = None,
    bot: Any = None,
) -> str:
    """Look up and call the registered handler for *name*."""
    handler = _TOOL_REGISTRY.get(name)
    if handler is None:
        logger.warning(f"Unknown tool requested by Ollama: {name}")
        return "⚠️ פעולה לא מוכרת."
    return await handler(args, user_id, username, job_queue, bot)


# ---- Shopping ----------------------------------------------------------------

@_tool("add_shopping_items")
async def _handle_add_shopping_items(args, user_id, username, job_queue, bot) -> str:
    items: list[str] = list(args.get("items", []))
    added = []
    for item_name in items:
        item_name = str(item_name).strip()
        if not item_name:
            continue
        if add_shopping_item(name=item_name, user_id=user_id, username=username):
            added.append(item_name)
    if not added:
        return "⚠️ לא הצלחתי להוסיף את הפריטים."
    if len(added) == 1:
        return f"🛒 נוסף לרשימה: *{added[0]}*"
    return f"🛒 נוספו {len(added)} פריטים לרשימה:\n" + "\n".join(f"• {n}" for n in added)


@_tool("get_shopping_list")
async def _handle_get_shopping_list(args, user_id, username, job_queue, bot) -> str:
    items_db = get_shopping_items()
    if not items_db:
        return "🛒 רשימת הקניות ריקה."
    lines = [f"🛒 *רשימת קניות* ({len(items_db)} פריטים)\n"]
    for i, item in enumerate(items_db, start=1):
        lines.append(f"{i}. {item.name}")
    return "\n".join(lines)


@_tool("remove_shopping_item")
async def _handle_remove_shopping_item(args, user_id, username, job_queue, bot) -> str:
    n = int(args.get("item_number", 0))
    items_db = get_shopping_items()
    if n < 1 or n > len(items_db):
        return f"⚠️ אין פריט מספר {n} ברשימה."
    item = items_db[n - 1]
    if remove_shopping_item(item.id):
        return f"✅ הוסר מהרשימה: *{item.name}*"
    return "❌ לא הצלחתי להסיר את הפריט."


@_tool("remove_shopping_item_by_name")
async def _handle_remove_shopping_item_by_name(args, user_id, username, job_queue, bot) -> str:
    query = str(args.get("item_name", "")).strip().lower()
    items_db = get_shopping_items()
    matches = [it for it in items_db if query in it.name.lower()]
    if not matches:
        return f"⚠️ לא נמצא פריט בשם *{args.get('item_name')}* ברשימה."
    if len(matches) > 1:
        names = ", ".join(f"*{it.name}*" for it in matches)
        return f"⚠️ נמצאו כמה פריטים שמתאימים: {names}. נסה שם מדויק יותר."
    item = matches[0]
    if remove_shopping_item(item.id):
        return f"✅ הוסר מהרשימה: *{item.name}*"
    return "❌ לא הצלחתי להסיר את הפריט."


@_tool("edit_shopping_item")
async def _handle_edit_shopping_item(args, user_id, username, job_queue, bot) -> str:
    n = int(args.get("item_number", 0))
    new_name = str(args.get("new_name", "")).strip()
    items_db = get_shopping_items()
    if n < 1 or n > len(items_db):
        return f"⚠️ אין פריט מספר {n} ברשימה."
    if not new_name:
        return "⚠️ לא קיבלתי שם חדש."
    item = items_db[n - 1]
    if update_shopping_item(item.id, new_name):
        return f"✏️ עודכן: *{item.name}* ← *{new_name}*"
    return "❌ לא הצלחתי לעדכן את הפריט."


@_tool("edit_shopping_item_by_name")
async def _handle_edit_shopping_item_by_name(args, user_id, username, job_queue, bot) -> str:
    query = str(args.get("item_name", "")).strip().lower()
    new_name = str(args.get("new_name", "")).strip()
    if not new_name:
        return "⚠️ לא קיבלתי שם חדש."
    items_db = get_shopping_items()
    matches = [it for it in items_db if query in it.name.lower()]
    if not matches:
        return f"⚠️ לא נמצא פריט בשם *{args.get('item_name')}* ברשימה."
    if len(matches) > 1:
        names = ", ".join(f"*{it.name}*" for it in matches)
        return f"⚠️ נמצאו כמה פריטים שמתאימים: {names}. נסה שם מדויק יותר."
    item = matches[0]
    if update_shopping_item(item.id, new_name):
        return f"✏️ עודכן: *{item.name}* ← *{new_name}*"
    return "❌ לא הצלחתי לעדכן את הפריט."


@_tool("clear_shopping_list")
async def _handle_clear_shopping_list(args, user_id, username, job_queue, bot) -> str:
    count = clear_shopping_list()
    if count == 0:
        return "🛒 הרשימה כבר ריקה."
    return f"🗑️ הרשימה נוקתה — הוסרו {count} פריטים."


# ---- Reminders ---------------------------------------------------------------

@_tool("set_reminder")
async def _handle_set_reminder(args, user_id, username, job_queue, bot) -> str:
    text = str(args.get("text", "")).strip()
    minutes = int(args.get("minutes", 0))
    recipient_hint = str(args.get("recipient", "")).strip()
    recurring = bool(args.get("recurring", False))
    recurrence_type = args.get("recurrence_type") or None

    if not text:
        return "⚠️ לא קיבלתי על מה להזכיר."
    if minutes <= 0:
        return "⚠️ יש להזין מספר דקות חיובי."

    target_id = user_id
    target_name: str | None = None
    if recipient_hint:
        match = _resolve_family_member(recipient_hint)
        if match is None:
            return f"⚠️ לא מצאתי משתמש בשם או תפקיד *{recipient_hint}* ברשימת המשפחה."
        target_id = match.user_id
        target_name = match.display_name

    remind_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=minutes)
    reminder = add_reminder(target_id, text, remind_at, recurring=recurring, recurrence_type=recurrence_type)
    if not reminder:
        return "❌ לא הצלחתי לשמור את התזכורת."
    if job_queue:
        job_queue.run_once(
            _send_reminder,
            when=timedelta(minutes=minutes),
            data={"chat_id": target_id, "text": text, "reminder_id": reminder.id, "recurring": recurring},
            name=f"reminder_{reminder.id}",
        )
    recur_label = ""
    if recurring and recurrence_type:
        _RECUR_LABELS = {"daily": "כל יום", "weekly": "כל שבוע", "monthly": "כל חודש", "yearly": "כל שנה"}
        recur_label = f" ({_RECUR_LABELS.get(recurrence_type, recurrence_type)})"
    if target_name:
        return f"✅ תזכורת נקבעה{recur_label}! בעוד {minutes} דקות ישלח ל*{target_name}*: *{text}*"
    return f"⏰ תזכורת נקבעה{recur_label}! אזכיר לך *{text}* בעוד {minutes} דקות."


@_tool("list_reminders")
async def _handle_list_reminders(args, user_id, username, job_queue, bot) -> str:
    reminders = get_pending_reminders(user_id)
    if not reminders:
        return "📭 אין תזכורות פעילות."
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    lines = ["⏰ *תזכורות פעילות*\n"]
    for i, r in enumerate(reminders, 1):
        mins = max(int((r.remind_at - now).total_seconds() / 60), 0)
        recur = " 🔁" if r.recurring else ""
        lines.append(f"{i}. {r.text} — בעוד {mins} דק׳{recur}")
    return "\n".join(lines)


@_tool("cancel_reminder")
async def _handle_cancel_reminder(args, user_id, username, job_queue, bot) -> str:
    reminders = get_pending_reminders(user_id)
    n = int(args.get("reminder_number", 0))
    if n < 1 or n > len(reminders):
        return f"⚠️ אין תזכורת מספר {n}."
    r = reminders[n - 1]
    cancel_reminder(r.id)
    return f"🗑️ תזכורת בוטלה: *{r.text}*"


# ---- Family ------------------------------------------------------------------

@_tool("broadcast_message")
async def _handle_broadcast_message(args, user_id, username, job_queue, bot) -> str:
    message = str(args.get("message", "")).strip()
    if not message:
        return "⚠️ לא קיבלתי הודעה לשליחה."
    if bot is None:
        return "⚠️ לא ניתן לשלוח הודעות כרגע."

    sender_profile = get_user_profile(user_id)
    sender_name = sender_profile.display_name if sender_profile else (username or "מישהו")

    recipients = [p for p in get_all_user_profiles() if p.user_id != user_id]
    if not recipients:
        return "⚠️ אין בני משפחה נוספים רשומים במערכת."

    sent = 0
    for p in recipients:
        try:
            await bot.send_message(
                chat_id=p.user_id,
                text=f"📢 *{sender_name} אמר/ה:* {message}",
                parse_mode="Markdown",
            )
            sent += 1
        except Exception as e:
            logger.warning(f"Could not send broadcast to {p.user_id}: {e}")

    if sent == 0:
        return "❌ לא הצלחתי לשלוח את ההודעה לאף אחד."
    names = ", ".join(p.display_name for p in recipients if p.display_name)
    return f"✅ ההודעה נשלחה ל-{sent} אנשים ({names})."


@_tool("leave_note")
async def _handle_leave_note(args, user_id, username, job_queue, bot) -> str:
    recipient_hint = str(args.get("recipient", "")).strip()
    message = str(args.get("message", "")).strip()

    if not recipient_hint:
        return "⚠️ למי להשאיר את ההודעה?"
    if not message:
        return "⚠️ לא קיבלתי הודעה להשאיר."

    target = _resolve_family_member(recipient_hint)
    if target is None:
        return f"⚠️ לא מצאתי משתמש בשם *{recipient_hint}* ברשימת המשפחה."

    sender_profile = get_user_profile(user_id)
    sender_name = sender_profile.display_name if sender_profile else (username or "מישהו")

    if bot:
        try:
            await bot.send_message(
                chat_id=target.user_id,
                text=f"📬 *הודעה מ-{sender_name}:*\n{message}",
                parse_mode="Markdown",
            )
            return f"✅ ההודעה נשלחה ל*{target.display_name}* כרגע."
        except Exception as exc:
            logger.warning(f"leave_note direct send failed: {exc} — falling back to stored note")

    # Fallback: store for next interaction if bot is unavailable
    add_note(
        from_user_id=user_id,
        from_user_name=sender_name,
        to_user_id=target.user_id,
        message=message,
    )
    return f"📝 ההודעה תועבר ל*{target.display_name}* בפעם הבאה שישלח הודעה."


# ---- Calendar ----------------------------------------------------------------

_HE_DAYS = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]


@_tool("get_schedule")
async def _handle_get_schedule(args, user_id, username, job_queue, bot) -> str:
    period = str(args.get("period", "today")).lower().strip()
    profile = get_user_profile(user_id)
    if not profile or not profile.icloud_username:
        return "❌ לא מחובר ל-Apple Calendar. השתמש ב-`/calendar connect` כדי לחבר."

    today = date.today()
    if period == "tomorrow":
        target_date = today + timedelta(days=1)
        events = get_events_for_date(profile.icloud_username, profile.icloud_app_password, target_date)
        date_label = "מחר"
    elif period == "week":
        end_date = today + timedelta(days=6)
        events = get_events_for_range(profile.icloud_username, profile.icloud_app_password, today, end_date)
        date_label = "השבוע"
    else:
        events = get_events_for_date(profile.icloud_username, profile.icloud_app_password, today)
        date_label = "היום"

    if not events:
        return f"📅 אין אירועים {date_label}."

    lines = [f"📅 *לוח זמנים {date_label}*\n"]
    for ev in events:
        if ev["all_day"]:
            time_str_ev = "כל היום"
        elif ev["start"]:
            start_utc = ev["start"].replace(tzinfo=timezone.utc)
            start_local = start_utc.astimezone()
            time_str_ev = start_local.strftime("%H:%M")
        else:
            time_str_ev = ""

        cal_name = ev.get("calendar", "")
        cal_suffix = f" _[{cal_name}]_" if cal_name else ""

        # Show date prefix in week view
        date_prefix = ""
        if period == "week" and ev.get("date"):
            date_prefix = ev["date"].strftime("%d/%m") + " "

        lines.append(f"• {date_prefix}{time_str_ev} — {ev['title']}{cal_suffix}")
    return "\n".join(lines)


@_tool("add_event")
async def _handle_add_event(args, user_id, username, job_queue, bot) -> str:
    title = str(args.get("title", "")).strip()
    date_str = str(args.get("date_str", "")).strip()
    time_str = str(args.get("time_str", "")).strip()
    duration_minutes = int(args.get("duration_minutes", 60) or 60)
    calendar_name = args.get("calendar_name") or None

    if not title:
        return "⚠️ לא קיבלתי כותרת לאירוע."

    profile = get_user_profile(user_id)
    if not profile or not profile.icloud_username:
        return "❌ לא מחובר ל-Apple Calendar. השתמש ב-`/calendar connect` כדי לחבר."

    if not calendar_name and profile.default_apple_calendar:
        calendar_name = profile.default_apple_calendar

    today = date.today()
    try:
        if date_str in ("today", "היום", ""):
            target_date = today
        elif date_str in ("tomorrow", "מחר"):
            target_date = today + timedelta(days=1)
        else:
            target_date = date.fromisoformat(date_str)
    except ValueError:
        return f"⚠️ לא הצלחתי לפרש את התאריך: {date_str}"

    try:
        hour, minute = map(int, time_str.split(":")) if ":" in time_str else (9, 0)
    except ValueError:
        return f"⚠️ לא הצלחתי לפרש את השעה: {time_str}"

    start_dt = datetime(target_date.year, target_date.month, target_date.day, hour, minute)
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    cal_used = create_event(
        profile.icloud_username,
        profile.icloud_app_password,
        title,
        start_dt,
        end_dt,
        calendar_name,
    )
    if not cal_used:
        return "❌ לא הצלחתי ליצור את האירוע ב-Apple Calendar."

    date_label = target_date.strftime("%d/%m/%Y")
    msg = f"✅ נוסף ל-Apple Calendar: *{title}*\n📅 {date_label} {hour:02d}:{minute:02d}\n📁 יומן: *{cal_used}*"
    if not profile.default_apple_calendar:
        msg += f"\n\n💡 _אם האירוע לא מופיע, בדוק שהיומן \"{cal_used}\" מופעל בטלפון, או הגדר יומן ברירת מחדל: `/calendar default {cal_used}`_"
    return msg


# ---- HomeKit / direct device control ----------------------------------------

def _device_display_name(dev: dict) -> str:
    from config import Config
    if dev["type"] == "switcher":
        return Config.SWITCHER_NAME
    return dev["id"]


def _no_match_msg(device_name: str) -> str:
    names = [_device_display_name(d) for d in _KNOWN_DEVICES]
    name_list = "\n".join(f"• {n}" for n in names)
    return f"⚠️ לא מצאתי מכשיר בשם *{device_name}*.\n\n*מכשירים זמינים:*\n{name_list}"


def _switcher_configured() -> bool:
    from config import Config
    return bool(Config.SWITCHER_IP and Config.SWITCHER_ID)


@_tool("hk_list_devices")
async def _handle_hk_list_devices(args, user_id, username, job_queue, bot) -> str:
    from config import Config
    lines = ["🏠 *מכשירי הבית החכם*\n"]

    # Switcher Touch — live state
    if _switcher_configured():
        try:
            state = await _switcher_dev.get_state()
            status = "✅ דולק" if state["is_on"] else "⭕ כבוי"
            power = f" ({state['power_w']}W)" if state.get("power_w") else ""
            lines.append(f"• {Config.SWITCHER_NAME}: {status}{power}")
        except Exception as exc:
            logger.error(f"hk_list_devices switcher error: {exc}")
            lines.append(f"• {Config.SWITCHER_NAME}: ⚠️ לא ניתן לקרוא")
    else:
        lines.append("• Switcher Touch: ⚙️ לא מוגדר (.env חסר SWITCHER_DEVICE_IP/ID)")

    # PalGate / מרווה — not yet implemented
    lines.append("• מרווה: ⚙️ בקרה ישירה — בקרוב")

    return "\n".join(lines)


@_tool("hk_turn_on")
async def _handle_hk_turn_on(args, user_id, username, job_queue, bot) -> str:
    device_name = str(args.get("device_name", "")).strip()
    dev = _find_device(device_name)
    if not dev:
        return _no_match_msg(device_name)
    if dev["type"] == "switcher":
        if not _switcher_configured():
            return "⚙️ ה-Switcher לא מוגדר. הוסף SWITCHER_DEVICE_IP ו-SWITCHER_DEVICE_ID ל-.env."
        try:
            await _switcher_dev.turn_on()
            return f"✅ *{_device_display_name(dev)}* הופעל."
        except Exception as exc:
            logger.error(f"hk_turn_on switcher error: {exc}")
            return "⚠️ שגיאה בהפעלת ה-Switcher. ודא שהוא מחובר לרשת."
    return f"⚙️ בקרה ישירה של *{_device_display_name(dev)}* עדיין לא ממומשת."


@_tool("hk_turn_off")
async def _handle_hk_turn_off(args, user_id, username, job_queue, bot) -> str:
    device_name = str(args.get("device_name", "")).strip()
    dev = _find_device(device_name)
    if not dev:
        return _no_match_msg(device_name)
    if dev["type"] == "switcher":
        if not _switcher_configured():
            return "⚙️ ה-Switcher לא מוגדר. הוסף SWITCHER_DEVICE_IP ו-SWITCHER_DEVICE_ID ל-.env."
        try:
            await _switcher_dev.turn_off()
            return f"✅ *{_device_display_name(dev)}* כובה."
        except Exception as exc:
            logger.error(f"hk_turn_off switcher error: {exc}")
            return "⚠️ שגיאה בכיבוי ה-Switcher. ודא שהוא מחובר לרשת."
    return f"⚙️ בקרה ישירה של *{_device_display_name(dev)}* עדיין לא ממומשת."


@_tool("hk_set_brightness")
async def _handle_hk_set_brightness(args, user_id, username, job_queue, bot) -> str:
    device_name = str(args.get("device_name", "")).strip()
    dev = _find_device(device_name)
    if not dev:
        return _no_match_msg(device_name)
    return f"⚙️ *{_device_display_name(dev)}* אינו תומך בכוונון בהירות."


@_tool("hk_get_status")
async def _handle_hk_get_status(args, user_id, username, job_queue, bot) -> str:
    device_name = str(args.get("device_name", "")).strip()
    dev = _find_device(device_name)
    if not dev:
        return _no_match_msg(device_name)
    if dev["type"] == "switcher":
        if not _switcher_configured():
            return "⚙️ ה-Switcher לא מוגדר."
        try:
            state = await _switcher_dev.get_state()
            status = "דולק ✅" if state["is_on"] else "כבוי ⭕"
            from config import Config
            lines = [f"🏠 *{Config.SWITCHER_NAME}*\n", f"• מצב: {status}"]
            if state.get("power_w"):
                lines.append(f"• צריכת חשמל: {state['power_w']}W")
            return "\n".join(lines)
        except Exception as exc:
            logger.error(f"hk_get_status switcher error: {exc}")
            return "⚠️ שגיאה בקריאת מצב ה-Switcher."
    return f"⚙️ קריאת מצב *{_device_display_name(dev)}* עדיין לא ממומשת."


@_tool("schedule_device_action")
async def _handle_schedule_device_action(args, user_id, username, job_queue, bot) -> str:
    """Schedule a device turn-on or turn-off to happen automatically after a delay."""
    device_name = str(args.get("device_name", "")).strip()
    action = str(args.get("action", "")).strip()
    minutes = int(args.get("minutes", 0))

    if minutes <= 0:
        return "⚠️ יש להזין מספר דקות חיובי."
    if action not in ("turn_on", "turn_off"):
        return "⚠️ פעולה לא מוכרת — השתמש ב-turn_on או turn_off."

    dev = _find_device(device_name)
    if not dev:
        return _no_match_msg(device_name)
    if dev["type"] != "switcher":
        return f"⚙️ תזמון פעולה עבור *{_device_display_name(dev)}* עדיין לא נתמך."
    if not _switcher_configured():
        return "⚙️ ה-Switcher לא מוגדר. הוסף SWITCHER_DEVICE_IP ו-SWITCHER_DEVICE_ID ל-.env."

    action_label = "הדלקת" if action == "turn_on" else "כיבוי"
    dev_name = _device_display_name(dev)
    reminder_text = f"{action_label} {dev_name}"
    action_type = f"hk_{action}"

    remind_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=minutes)
    reminder = add_reminder(
        user_id, reminder_text, remind_at,
        action_type=action_type, action_payload=dev["id"],
    )
    if not reminder:
        return "❌ לא הצלחתי לתזמן את הפעולה."

    if job_queue:
        job_queue.run_once(
            _send_reminder,
            when=timedelta(minutes=minutes),
            data={
                "chat_id": user_id,
                "text": reminder_text,
                "reminder_id": reminder.id,
                "recurring": False,
                "action_type": action_type,
                "action_payload": dev["id"],
            },
            name=f"reminder_{reminder.id}",
        )

    verb = "יידלק" if action == "turn_on" else "יכבה"
    return f"⏱️ מתוזמן! *{dev_name}* {verb} בעוד {minutes} דקות."


# ---------------------------------------------------------------------------
# Fallback: parse tool calls leaked as plain text
# ---------------------------------------------------------------------------

_KNOWN_TOOLS = {
    "add_shopping_items", "get_shopping_list",
    "remove_shopping_item", "remove_shopping_item_by_name",
    "edit_shopping_item", "edit_shopping_item_by_name", "clear_shopping_list",
    "set_reminder", "list_reminders", "cancel_reminder",
    "broadcast_message", "leave_note",
    "get_schedule", "add_event",
    "hk_list_devices", "hk_turn_on", "hk_turn_off", "hk_set_brightness", "hk_get_status",
    "schedule_device_action",
}

# Tools whose output is returned verbatim — no AI second-pass summarization.
# Prevents hallucinated events and loss of calendar-name / device-state details.
_CALENDAR_PASSTHROUGH = {"get_schedule", "add_event"}
_HK_PASSTHROUGH = {"hk_list_devices", "hk_get_status", "hk_turn_on", "hk_turn_off", "hk_set_brightness"}
_SHOPPING_PASSTHROUGH = {"get_shopping_list"}
_PASSTHROUGH = _CALENDAR_PASSTHROUGH | _HK_PASSTHROUGH | _SHOPPING_PASSTHROUGH


# ---------------------------------------------------------------------------
# Per-user conversation history (in-memory, cleared on restart)
# ---------------------------------------------------------------------------

# Stores the last _MAX_HISTORY_PAIRS (user, assistant) exchange pairs per user.
# Cleared on bot restart — that's intentional (keeps context fresh per session).
_conversation_history: dict[int, list[dict]] = {}
from config import Config as _CfgHistory  # noqa: E402
_MAX_HISTORY_PAIRS = _CfgHistory.OLLAMA_HISTORY_PAIRS


def _get_history(user_id: int) -> list[dict]:
    return _conversation_history.setdefault(user_id, [])


def _append_history(user_id: int, role: str, content: str) -> None:
    history = _get_history(user_id)
    history.append({"role": role, "content": content})
    # Trim to last _MAX_HISTORY_PAIRS pairs (2 messages per pair)
    max_msgs = _MAX_HISTORY_PAIRS * 2
    if len(history) > max_msgs:
        _conversation_history[user_id] = history[-max_msgs:]


def _parse_tool_from_content(content: str) -> tuple[str, dict] | None:
    """Try to extract a tool call from model text when tool_calls is empty.

    qwen2.5 occasionally outputs JSON or function-name syntax instead of
    using the structured tool-calling API. This catches those cases.
    """
    match = re.search(
        r'\{"name":\s*"(\w+)",\s*"arguments":\s*(\{.*?\})\}',
        content,
        re.DOTALL,
    )
    if match:
        name = match.group(1)
        if name in _KNOWN_TOOLS:
            try:
                args = json.loads(match.group(2))
                logger.debug(f"Fallback parsed tool '{name}' from content")
                return name, args
            except (json.JSONDecodeError, ValueError):
                pass

    for tool in _KNOWN_TOOLS:
        if tool in content:
            logger.debug(f"Fallback detected tool '{tool}' by name in content")
            return tool, {}

    return None


def _strip_think_tags(text: str) -> str:
    """Remove Qwen3 chain-of-thought blocks from model output.

    Qwen3.5 may still emit <think>...</think> even when think=False is set
    (e.g. older Ollama server versions). Strip them before sending to users
    or parsing tool calls so they don't appear in responses.
    """
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


_HEBREW_RE = re.compile(r"[\u0590-\u05FF]")


def _clean_response(text: str) -> str:
    """Strip think tags AND any leading English reasoning before Hebrew content.

    qwen3:4b ignores think=False and outputs reasoning as plain English before
    the Hebrew reply — sometimes on the same line (e.g. "Let me answer: שלום!").
    We find the first Hebrew character and return everything from that point.
    A short prefix guard (≤ 4 chars, e.g. an emoji) is left untouched.
    """
    text = _strip_think_tags(text)
    match = _HEBREW_RE.search(text)
    if match and match.start() > 4:
        return text[match.start():].strip()
    return text


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

@require_auth
@rate_limit
async def handle_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle plain-text messages via a local Ollama model."""
    from config import Config  # late import to avoid circular dependency

    user = update.effective_user
    user_text = update.message.text
    logger.info(f"User {user.id} sent chat message: {user_text[:60]!r}")

    # ------------------------------------------------------------------
    # Onboarding gate — 2 steps: name → done
    # ------------------------------------------------------------------
    profile = get_user_profile(user.id)

    if profile is None:
        create_user_profile(user.id)
        logger.info(f"New user {user.id} — starting onboarding")
        await update.message.reply_text(
            "👋 שלום! אני הבוט הביתי של המשפחה שלך.\n\nאיך קוראים לך?"
        )
        return

    if profile.display_name is None:
        name = user_text.strip()
        if not name or len(name) > 50:
            await update.message.reply_text("אנא שלח שם תקין (עד 50 תווים).")
            return
        set_user_name(user.id, name)
        logger.info(f"User {user.id} registered name as '{name}'")
        await update.message.reply_text(
            f"נעים מאוד, *{name}*! 😊\n\n"
            "אתה זכר או נקבה?\nשלח *זכר* או *נקבה*.",
            parse_mode="Markdown",
        )
        return

    if profile.gender is None:
        answer = user_text.strip().lower()
        if any(w in answer for w in ["זכר", "בן", "גבר", "ילד", "אבא"]):
            gender = "male"
        elif any(w in answer for w in ["נקבה", "בת", "אישה", "ילדה", "אמא"]):
            gender = "female"
        else:
            await update.message.reply_text("אנא שלח *זכר* או *נקבה*.", parse_mode="Markdown")
            return
        set_user_gender(user.id, gender)
        logger.info(f"User {user.id} registered gender as '{gender}'")
        await update.message.reply_text(
            f"מעולה! 🏠 ברוך{'ה' if gender == 'female' else ''} הבא{'ה' if gender == 'female' else ''}, *{profile.display_name}*!\n"
            "שאל אותי כל דבר בעברית, או שלח /help.",
            parse_mode="Markdown",
        )
        return

    # ------------------------------------------------------------------
    # Fully registered — proceed with AI
    # ------------------------------------------------------------------
    if not Config.OLLAMA_MODEL:
        await update.message.reply_text("⚠️ עוזר הבינה המלאכותית אינו מוגדר.")
        return

    try:
        ollama_client = _get_ollama_client()

        # Deliver any pending notes left by family members
        pending_notes = get_pending_notes(user.id)
        if pending_notes:
            for note in pending_notes:
                sender = note.from_user_name or "מישהו"
                await update.message.reply_text(
                    f"📬 *הודעה מ-{sender}:*\n{note.message}",
                    parse_mode="Markdown",
                )
            mark_notes_delivered(user.id)

        # Select tools once — reused for both the Ollama call and prompt assembly
        selected_tools = _select_tools(user_text)

        # Build focused system prompt: inject only what this message needs
        today = date.today()
        gender_note = ""
        if profile.gender == "female":
            gender_note = " Use feminine Hebrew grammar when addressing this user."
        elif profile.gender == "male":
            gender_note = " Use masculine Hebrew grammar when addressing this user."
        task_prompt = (
            f"היום: {today.strftime('%Y-%m-%d')}. מחר: {(today + timedelta(days=1)).strftime('%Y-%m-%d')}.\n"
            f"משתמש: {profile.display_name}"
            + (f" ({profile.role})" if profile.role else "")
            + ".\n"
            + _PROMPT_BASE
            + gender_note
        )
        if any(t["function"]["name"] == "add_shopping_items" for t in selected_tools):
            task_prompt += _PROMPT_SHOPPING
        if any(t["function"]["name"] == "set_reminder" for t in selected_tools):
            task_prompt += _PROMPT_REMINDERS
        if any(t["function"]["name"] in ("set_reminder", "broadcast_message", "leave_note") for t in selected_tools):
            others = [p for p in get_all_user_profiles() if p.user_id != user.id and p.display_name]
            if others:
                members = ", ".join(p.display_name for p in others)
                task_prompt += f"\nAvailable family members: {members}"
        if any(t["function"]["name"] == "broadcast_message" for t in selected_tools):
            task_prompt += _PROMPT_FAMILY
        if any(t["function"]["name"] in ("get_schedule", "add_event") for t in selected_tools):
            task_prompt += _PROMPT_CALENDAR
            # Inject a day-of-week → date table so the model can resolve Hebrew day names
            day_lines = []
            for i in range(7):
                d = today + timedelta(days=i)
                he_idx = (d.weekday() + 1) % 7  # Python Mon=0 → Hebrew ראשון=Sun=0
                day_lines.append(f"{_HE_DAYS[he_idx]}={d.strftime('%Y-%m-%d')}")
            task_prompt += "\nComing days: " + ", ".join(day_lines)
        if any(t["function"]["name"].startswith("hk_") for t in selected_tools):
            task_prompt += _PROMPT_HK
        if not selected_tools:
            task_prompt += _PROMPT_GENERAL

        job_queue = context.job_queue

        # Build messages: system + recent history + current user message
        _append_history(user.id, "user", user_text)
        messages = [{"role": "system", "content": task_prompt}] + _get_history(user.id)

        # React with 🤔 to acknowledge the message while processing
        await update.message.set_reaction([ReactionTypeEmoji(emoji="🤔")])
        _done_reaction = "👍"  # will flip to 😱 on error

        _mp = _get_model_profile()
        _base_opts: dict = {
            "num_ctx":     Config.OLLAMA_NUM_CTX or _mp["num_ctx"],
            "num_predict": _mp["first_predict"],
        }
        _pass2_opts: dict = {
            "num_ctx":     min(Config.OLLAMA_NUM_CTX or _mp["num_ctx"], 1536),
            "num_predict": _mp["second_predict"],
        }
        if _mp["temperature"] is not None:
            _base_opts["temperature"] = _mp["temperature"]
            _pass2_opts["temperature"] = _mp["temperature"]
        if _mp["top_k"] is not None:
            _base_opts["top_k"] = _mp["top_k"]
            _pass2_opts["top_k"] = _mp["top_k"]

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: ollama_client.chat(
                model=Config.OLLAMA_MODEL,
                messages=messages,
                tools=selected_tools,
                think=_mp["think"],
                options=_base_opts,
                keep_alive=Config.OLLAMA_KEEP_ALIVE,
            ),
        )

        msg = response.message
        # Strip any <think>...</think> blocks Qwen3 may still emit as a safety net
        msg_content = _clean_response(msg.content or "")

        if msg.tool_calls:
            # --- Execute all tool calls and collect results ---
            tool_results: list[dict] = []
            for tool_call in msg.tool_calls:
                t_name = tool_call.function.name
                t_args = dict(tool_call.function.arguments) if tool_call.function.arguments else {}
                t_result = await _execute_tool(t_name, t_args, user.id, user.username, job_queue, context.bot)
                tool_results.append({"name": t_name, "result": t_result})

            combined_results = "\n\n".join(tr["result"] for tr in tool_results)

            # Passthrough tools: return raw output directly — no second-pass AI summary.
            # Prevents hallucinated events/device states and loss of detail.
            if any(tr["name"] in _PASSTHROUGH for tr in tool_results):
                await update.message.reply_text(combined_results, parse_mode="Markdown")
                _append_history(user.id, "assistant", combined_results)
                return

            # --- Second-pass: let the model generate a natural Hebrew response ---
            pass2_messages = [
                {
                    "role": "system",
                    "content": (
                        "אתה עוזר בית חכם ידידותי. ענה בעברית בלבד. "
                        "צור תגובה קצרה וחמה (1-2 משפטים) שמסכמת מה נעשה. "
                        "אפשר להוסיף אמוג׳י אחד בלבד אם הוא ממש מתאים — אל תגזים. "
                        "אל תחזור על פרטים טכניים — פשוט אשר בחום."
                    ),
                },
                {"role": "user", "content": user_text},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": tr["name"], "arguments": {}}} for tr in tool_results
                    ],
                },
                {"role": "tool", "content": combined_results},
            ]
            response2 = await loop.run_in_executor(
                None,
                lambda: ollama_client.chat(
                    model=Config.OLLAMA_MODEL,
                    messages=pass2_messages,
                    think=_mp["think"],
                    options=_pass2_opts,
                ),
            )
            final_text = _clean_response(response2.message.content or "")
            # Fallback to raw results if second pass returned nothing useful
            if not final_text or len(final_text) < 3:
                final_text = combined_results

            await update.message.reply_text(final_text, parse_mode="Markdown")
            _append_history(user.id, "assistant", final_text)

        elif msg_content:
            parsed = _parse_tool_from_content(msg_content)
            if parsed:
                t_name, t_args = parsed
                t_result = await _execute_tool(t_name, t_args, user.id, user.username, job_queue, context.bot)
                # Passthrough tools: return raw result directly (no second pass)
                if t_name in _PASSTHROUGH:
                    await update.message.reply_text(t_result, parse_mode="Markdown")
                    _append_history(user.id, "assistant", t_result)
                    return
                # Second pass for fallback-parsed tools too
                pass2_messages = [
                    {
                        "role": "system",
                        "content": (
                            "אתה עוזר בית חכם ידידותי. ענה בעברית בלבד. "
                            "צור תגובה קצרה וחמה (1-2 משפטים). "
                            "אפשר אמוג׳י אחד בלבד אם ממש מתאים. אל תחזור על פרטים טכניים."
                        ),
                    },
                    {"role": "user", "content": user_text},
                    {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": t_name, "arguments": {}}}]},
                    {"role": "tool", "content": t_result},
                ]
                response2 = await loop.run_in_executor(
                    None,
                    lambda: ollama_client.chat(
                        model=Config.OLLAMA_MODEL,
                        messages=pass2_messages,
                        think=_mp["think"],
                        options=_pass2_opts,
                    ),
                )
                final_text = _clean_response(response2.message.content or "") or t_result
                await update.message.reply_text(final_text, parse_mode="Markdown")
                _append_history(user.id, "assistant", final_text)
            else:
                await update.message.reply_text(msg_content, parse_mode="Markdown")
                _append_history(user.id, "assistant", msg_content)
        else:
            await update.message.reply_text("מצטער, לא הצלחתי לעבד את הבקשה. נסה שוב.")

    except ollama.ResponseError as exc:
        _done_reaction = "😱"
        logger.error(f"Ollama response error for user {user.id}: {exc}")
        if "model" in str(exc).lower():
            await update.message.reply_text(
                f"❌ המודל *{Config.OLLAMA_MODEL}* לא נמצא.\n"
                f"הרץ: `ollama pull {Config.OLLAMA_MODEL}`",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("❌ שגיאה בעיבוד הבקשה. נסה שוב.")
    except Exception as exc:
        _done_reaction = "😱"
        logger.error(f"Ollama error for user {user.id}: {exc}")
        await update.message.reply_text(
            "❌ לא ניתן להתחבר ל-Ollama. ודא שהוא פועל על הרספברי פאי."
        )
    finally:
        try:
            await update.message.set_reaction([ReactionTypeEmoji(emoji=_done_reaction)])
        except Exception:
            pass  # Reactions are non-critical — never crash the handler
