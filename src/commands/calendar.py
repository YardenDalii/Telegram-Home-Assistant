"""Calendar slash command — /calendar.

Subcommands:
  /calendar                              — connection status + list calendars
  /calendar connect email / app-password — connect iCloud Calendar
  /calendar default <name>               — set default calendar for new events
  /calendar disconnect                   — remove iCloud credentials
"""

from telegram import Update
from telegram.ext import ContextTypes

from cal.apple_cal import list_calendars, test_connection
from database.models import (
    get_user_profile,
    set_default_apple_calendar,
    set_icloud_credentials,
)
from utils.decorators import rate_limit, require_auth
from utils.logger import get_logger

logger = get_logger(__name__)

_USAGE = (
    "*פקודות יומן:*\n"
    "`/calendar` — סטטוס + רשימת יומנים\n"
    "`/calendar connect your@email.com / xxxx-xxxx-xxxx-xxxx` — חבר iCloud\n"
    "`/calendar default <שם יומן>` — הגדר יומן ברירת מחדל\n"
    "`/calendar disconnect` — נתק iCloud"
)

_CONNECT_INSTRUCTIONS = (
    "כדי לקבל סיסמת אפליקציה:\n"
    "1. כנס ל-`appleid.apple.com`\n"
    "2. Security → App-Specific Passwords\n"
    "3. לחץ על ＋ וצור סיסמה חדשה\n"
    "4. העתק את הסיסמה (פורמט: `xxxx-xxxx-xxxx-xxxx`)"
)


@require_auth
@rate_limit
async def cmd_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /calendar with optional subcommand."""
    user = update.effective_user
    args = context.args or []
    sub = args[0].lower() if args else ""

    if sub == "connect":
        await _connect(update, args[1:], user.id)
    elif sub == "default":
        await _set_default(update, args[1:], user.id)
    elif sub == "disconnect":
        await _disconnect(update, user.id)
    else:
        await _status(update, user.id)


# ---------------------------------------------------------------------------
# /calendar  (no subcommand) — status + calendar list
# ---------------------------------------------------------------------------

async def _status(update: Update, user_id: int) -> None:
    profile = get_user_profile(user_id)

    if not profile or not profile.icloud_username:
        await update.message.reply_text(
            "❌ *iCloud לא מחובר.*\n\n"
            f"{_USAGE}\n\n"
            f"{_CONNECT_INSTRUCTIONS}",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text("🔄 בודק חיבור ל-iCloud...")

    ok = test_connection(profile.icloud_username, profile.icloud_app_password)
    if not ok:
        await update.message.reply_text(
            f"⚠️ *iCloud מוגדר אך לא מגיב*\n`{profile.icloud_username}`\n\n"
            "בדוק חיבור לאינטרנט או נסה שוב מאוחר יותר.\n\n"
            + _USAGE,
            parse_mode="Markdown",
        )
        return

    calendars = list_calendars(profile.icloud_username, profile.icloud_app_password)
    default = profile.default_apple_calendar

    lines = [f"✅ *iCloud מחובר*\n`{profile.icloud_username}`\n"]
    if calendars:
        lines.append("*יומנים זמינים:*")
        for name in calendars:
            marker = " ← ברירת מחדל" if name == default else ""
            lines.append(f"• {name}{marker}")
    else:
        lines.append("_לא נמצאו יומנים._")

    if default:
        lines.append(f"\n*ברירת מחדל:* {default}")
    else:
        lines.append("\n_ברירת מחדל: לא הוגדרה (ישמר ביומן הראשון)_")

    lines.append("\n" + _USAGE)
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /calendar connect email / password
# ---------------------------------------------------------------------------

async def _connect(update: Update, rest: list[str], user_id: int) -> None:
    raw = " ".join(rest).strip()
    if "/" not in raw:
        await update.message.reply_text(
            "⚠️ פורמט לא תקין.\n\n"
            "שלח:\n`/calendar connect your@email.com / xxxx-xxxx-xxxx-xxxx`\n\n"
            + _CONNECT_INSTRUCTIONS,
            parse_mode="Markdown",
        )
        return

    email, _, password = raw.partition("/")
    email    = email.strip()
    password = password.strip()

    if not email or not password:
        await update.message.reply_text(
            "⚠️ נדרש אימייל וסיסמה.\n`/calendar connect your@email.com / xxxx-xxxx-xxxx-xxxx`",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text("🔄 בודק פרטי התחברות ל-iCloud...")

    ok = test_connection(email, password)
    if not ok:
        await update.message.reply_text(
            "❌ *פרטי ההתחברות שגויים.*\n\n"
            "ודא ש:\n"
            "• האימייל הוא Apple ID שלך\n"
            "• הסיסמה היא *App-Specific Password* (לא סיסמת Apple ID הרגילה)\n\n"
            + _CONNECT_INSTRUCTIONS,
            parse_mode="Markdown",
        )
        return

    set_icloud_credentials(user_id, email, password)

    calendars = list_calendars(email, password)
    lines = ["✅ *iCloud חובר בהצלחה!*\n"]
    if calendars:
        lines.append("*יומנים זמינים:*")
        for name in calendars:
            lines.append(f"• {name}")
        lines.append(
            "\nכדי להגדיר יומן ברירת מחדל:\n"
            "`/calendar default <שם יומן>`"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /calendar default <name>
# ---------------------------------------------------------------------------

async def _set_default(update: Update, rest: list[str], user_id: int) -> None:
    name = " ".join(rest).strip()
    if not name:
        await update.message.reply_text(
            "⚠️ ציין שם יומן.\n`/calendar default <שם יומן>`",
            parse_mode="Markdown",
        )
        return

    profile = get_user_profile(user_id)
    if not profile or not profile.icloud_username:
        await update.message.reply_text(
            "❌ iCloud לא מחובר. השתמש ב-`/calendar connect` תחילה.",
            parse_mode="Markdown",
        )
        return

    calendars = list_calendars(profile.icloud_username, profile.icloud_app_password)
    name_lower = name.lower()
    match = next((c for c in calendars if name_lower in c.lower()), None)

    if not match:
        cal_list = "\n".join(f"• {c}" for c in calendars) if calendars else "_אין יומנים_"
        await update.message.reply_text(
            f"⚠️ לא מצאתי יומן בשם *{name}*.\n\n*יומנים זמינים:*\n{cal_list}",
            parse_mode="Markdown",
        )
        return

    set_default_apple_calendar(user_id, match)
    await update.message.reply_text(
        f"✅ ברירת מחדל הוגדרה: *{match}*\n\n"
        "אירועים חדשים יישמרו ביומן זה כאשר לא מציינים יומן ספציפי.",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# /calendar disconnect
# ---------------------------------------------------------------------------

async def _disconnect(update: Update, user_id: int) -> None:
    profile = get_user_profile(user_id)
    if not profile or not profile.icloud_username:
        await update.message.reply_text("ℹ️ iCloud כבר לא מחובר.")
        return

    set_icloud_credentials(user_id, "", "")
    set_default_apple_calendar(user_id, "")
    await update.message.reply_text("✅ iCloud נותק בהצלחה.")
