"""System command handlers: /start, /clearall, /reload."""

import importlib
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ContextTypes

from database.models import clear_all_data, get_user_profile
from utils.decorators import rate_limit, require_admin, require_auth
from utils.logger import get_logger

logger = get_logger(__name__)

_START_TIME = datetime.now(timezone.utc)


@require_auth
@rate_limit
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command — welcome new users or greet returning ones.

    Args:
        update: Incoming Telegram update.
        context: Callback context provided by the bot framework.
    """
    user = update.effective_user
    logger.info(f"User {user.id} (@{user.username}) sent /start")

    profile = get_user_profile(user.id)

    if profile and profile.display_name and profile.role:
        # Fully registered — personalised greeting.
        await update.message.reply_text(
            f"ברוך הבא בחזרה, *{profile.display_name}*! 😊\n\n"
            f"איך אני יכול לעזור לך היום?\n"
            "השתמש ב-/help לרשימת הפקודות.",
            parse_mode="Markdown",
        )
    elif profile and profile.display_name:
        # Name set but role missing — nudge to finish onboarding.
        await update.message.reply_text(
            f"שלום שוב, *{profile.display_name}*! 👋\n\n"
            "עוד לא סיימנו את ההגדרה — שלח לי הודעה כלשהי כדי להמשיך.",
            parse_mode="Markdown",
        )
    else:
        # New user or onboarding not started — generic welcome.
        await update.message.reply_text(
            "שלום! 🏠 ברוך הבא לבוט הבית החכם.\n\n"
            "שלח לי הודעה כלשהי כדי להתחיל.",
        )



@require_admin
async def cmd_reload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /reload — hot-reload the AI assistant module (admin only).

    Reloads ai.assistant in-place: refreshes the system prompt, tool schemas,
    tool handlers, and conversation history without restarting the bot.
    Slash command registrations and DB schema are unaffected.
    """
    user = update.effective_user
    logger.info(f"Admin {user.id} triggered /reload")
    await update.message.reply_text("🔄 טוען מחדש את מודול ה-AI...")

    try:
        import ai.assistant as assistant_module
        importlib.reload(assistant_module)
        logger.info("ai.assistant reloaded successfully")
        await update.message.reply_text(
            "✅ מודול ה-AI נטען מחדש בהצלחה.\n"
            "_פרומפט, כלים והיסטוריית שיחות אופסו._",
            parse_mode="Markdown",
        )
    except Exception as exc:
        logger.error(f"Failed to reload ai.assistant: {exc}")
        await update.message.reply_text(f"❌ שגיאה בטעינה מחדש:\n`{exc}`", parse_mode="Markdown")


@require_admin
async def cmd_clearall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /clearall — delete all content except user profiles (admin only).

    Args:
        update: Incoming Telegram update.
        context: Callback context provided by the bot framework.
    """
    user = update.effective_user
    logger.warning(f"Admin {user.id} triggered /clearall")

    counts = clear_all_data()
    if not counts:
        await update.message.reply_text("❌ לא הצלחתי לנקות את הנתונים.")
        return

    total = sum(counts.values())
    lines = ["🗑️ *כל הנתונים נמחקו* (משתמשים נשמרו)\n"]
    labels = {
        "shopping_items": "רשימת קניות",
        "reminders": "תזכורות",
        "user_memories": "זיכרונות",
        "tasks": "משימות",
        "family_notes": "הודעות משפחה",
        "command_log": "יומן פקודות",
    }
    for key, label in labels.items():
        n = counts.get(key, 0)
        if n:
            lines.append(f"• {label}: {n}")
    lines.append(f"\nסה\"כ: {total} רשומות נמחקו.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
