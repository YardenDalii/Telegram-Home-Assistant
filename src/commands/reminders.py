"""Reminder command handlers.

/reminders — list active reminders
/remind <minutes> <text> — set a reminder
/cancelreminder <number> — cancel a reminder
"""

from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from database.models import add_reminder, cancel_reminder, get_pending_reminders
from utils.decorators import rate_limit, require_auth
from utils.logger import get_logger

logger = get_logger(__name__)


@require_auth
@rate_limit
async def cmd_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /reminders — list all active reminders for the user."""
    user = update.effective_user
    logger.info(f"User {user.id} listed reminders")

    reminders = get_pending_reminders(user.id)
    if not reminders:
        await update.message.reply_text("📭 אין תזכורות פעילות.")
        return

    now = datetime.utcnow()
    lines = ["⏰ *תזכורות פעילות*\n"]
    for i, r in enumerate(reminders, 1):
        diff = r.remind_at - now
        mins = max(int(diff.total_seconds() / 60), 0)
        recur = f" ({r.recurrence_type})" if r.recurring else ""
        lines.append(f"{i}. {r.text} — בעוד {mins} דק׳{recur}")

    lines.append("\nלביטול: /cancelreminder <מספר>")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@require_auth
@rate_limit
async def cmd_remind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /remind <minutes> <text> — set a reminder.

    Usage: /remind 30 לצאת לריצה
    """
    user = update.effective_user

    if not context.args or len(context.args) < 2 or not context.args[0].isdigit():
        await update.message.reply_text(
            "שימוש: /remind <דקות> <טקסט>\nלדוגמה: /remind 30 לצאת לריצה"
        )
        return

    minutes = int(context.args[0])
    text = " ".join(context.args[1:])

    if minutes <= 0:
        await update.message.reply_text("⚠️ יש להזין מספר דקות חיובי.")
        return

    remind_at = datetime.utcnow() + timedelta(minutes=minutes)
    reminder = add_reminder(user.id, text, remind_at)

    if not reminder:
        await update.message.reply_text("❌ לא הצלחתי לשמור את התזכורת.")
        return

    # Schedule the job
    if context.job_queue:
        from ai.assistant import _send_reminder
        context.job_queue.run_once(
            _send_reminder,
            when=timedelta(minutes=minutes),
            data={"chat_id": user.id, "text": text, "reminder_id": reminder.id},
            name=f"reminder_{reminder.id}",
        )

    logger.info(f"User {user.id} set reminder '{text}' in {minutes} min")
    await update.message.reply_text(
        f"⏰ תזכורת נקבעה! אזכיר לך *{text}* בעוד {minutes} דקות.",
        parse_mode="Markdown",
    )


@require_auth
@rate_limit
async def cmd_cancelreminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /cancelreminder <number> — cancel a reminder by list position."""
    user = update.effective_user

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "שימוש: /cancelreminder <מספר>\nהשתמש ב-/reminders לצפייה ברשימה."
        )
        return

    n = int(context.args[0])
    reminders = get_pending_reminders(user.id)

    if n < 1 or n > len(reminders):
        await update.message.reply_text(f"⚠️ אין תזכורת מספר {n}.")
        return

    r = reminders[n - 1]
    cancel_reminder(r.id)
    logger.info(f"User {user.id} cancelled reminder {r.id}")
    await update.message.reply_text(
        f"🗑️ תזכורת בוטלה: *{r.text}*", parse_mode="Markdown"
    )
