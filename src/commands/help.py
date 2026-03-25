"""Help command handler.

Displays a list of all available bot commands with descriptions.
"""

from telegram import Update
from telegram.ext import ContextTypes

from utils.decorators import rate_limit, require_auth
from utils.logger import get_logger

logger = get_logger(__name__)

_HELP_TEXT = """*🏠 בוט הבית החכם*

*פקודות מהירות*
/shop — הצג רשימת קניות
/add חלב, ביצים — הוסף פריט/ים לרשימה
/done 2 — הסר פריט לפי מספר
/reminders — הצג תזכורות פעילות
/remind 30 לצאת לריצה — קבע תזכורת בעוד N דקות
/cancelreminder 1 — בטל תזכורת לפי מספר
/calendar — סטטוס iCloud + רשימת יומנים
`/calendar connect your@email.com / xxxx-xxxx-xxxx-xxxx` — חבר iCloud
`/calendar default שם יומן` — הגדר יומן ברירת מחדל
`/calendar disconnect` — נתק iCloud
/clearshop — נקה רשימת קניות _(מנהל בלבד)_
/clearall — נקה את כל הנתונים _(מנהל בלבד)_

💬 *שיחה חופשית — פשוט כתוב לי בעברית*

🛒 *קניות*
"הוסף חלב" · "תוציא ביצים" · "מה יש ברשימה?"
"ערוך פריט 2 ל-חלב 3%" · "נקה את הרשימה"

⏰ *תזכורות*
"תזכיר לי עוד 20 דקות לצאת לריצה"
"תזכיר לאבא עוד שעה לקחת תרופות"
"תזכיר לי כל יום ב-8:00 לשתות מים"
"תזכיר לי כל שנה ב-15 במרץ יום הולדת של אמא"

🧠 *זיכרון*
"תזכור שאני רגיש לגלוטן"
"מה אתה זוכר עליי?" · "שכח זיכרון 2"

📋 *משימות*
"הוסף מטלה לשטוף כלים"
"תוסיף משימה לאבא לשלם חשבון חשמל עד מחר"
"הצג משימות" · "סיימתי 1" · "מחק משימה 3"

🚿 *דוד חשמלי (Switcher Touch 340A)*
"הדלק את הדוד" · "כבה את הדוד"
"מה מצב הדוד?" · "הצג את כל המכשירים"

🗓️ *לוח שנה*
"מה יש לי היום?" · "מה יש השבוע?" · "מה יש מחר?"
"הוסף פגישה מחר ב-14:00" — שמירה ביומן הפנימי
"הוסף לאייקלאוד: פגישה עם רופא ב-10:00" — שמירה ב-iCloud
לחיבור iCloud: `/calendar connect your@email.com / xxxx-xxxx-xxxx-xxxx`

👨‍👩‍👧 *משפחה*
"שלח לכולם: ארוחת ערב מוכנה!"
"תשאיר לאמא הודעה שהתקשרו מבית הספר"
"שלח לי סיכום בוקר כל יום ב-7:00" · "בטל את הבריפינג"

_רק משתמשים מורשים יכולים לתקשר עם הבוט._
"""


@require_auth
@rate_limit
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command.

    Args:
        update: Incoming Telegram update.
        context: Callback context provided by the bot framework.
    """
    user = update.effective_user
    logger.info(f"User {user.id} requested help")
    await update.message.reply_text(_HELP_TEXT, parse_mode="Markdown")
