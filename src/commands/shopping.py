"""Shopping list command handlers.

All authorized users can add items, view the list, and mark items as done.
Clearing the entire list requires admin privileges.
All user-facing messages are in Hebrew.
"""

from telegram import Update
from telegram.ext import ContextTypes

from database.models import (
    add_shopping_item,
    clear_shopping_list,
    get_shopping_items,
    log_command,
    remove_shopping_item,
)
from utils.decorators import rate_limit, require_admin, require_auth
from utils.logger import get_logger
from utils.validators import sanitize_input

logger = get_logger(__name__)


@require_auth
@rate_limit
async def cmd_shop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /shop — display the current shopping list.

    Args:
        update: Incoming Telegram update.
        context: Callback context provided by the bot framework.
    """
    user = update.effective_user
    logger.info(f"User {user.id} viewed shopping list")

    items = get_shopping_items()

    if not items:
        await update.message.reply_text(
            "🛒 רשימת הקניות ריקה.\nהשתמש ב-/add <פריט> להוספה."
        )
        return

    lines = [f"🛒 *רשימת קניות* ({len(items)} פריטים)\n"]
    for i, item in enumerate(items, start=1):
        lines.append(f"{i}. {item.name}")

    lines.append("\nהשתמש ב-/add להוספה, /done <מספר> להסרה.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@require_auth
@rate_limit
async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /add <item(s)> — add one or more items to the shopping list.

    Supports comma-separated items: /add milk, eggs, bread

    Args:
        update: Incoming Telegram update.
        context: Callback context provided by the bot framework.
    """
    user = update.effective_user

    if not context.args:
        await update.message.reply_text(
            "שימוש: /add <פריט> או /add חלב, ביצים, לחם"
        )
        return

    raw_text = " ".join(context.args)
    # Split on commas to support multiple items in one message
    raw_items = [sanitize_input(part) for part in raw_text.split(",")]
    valid_items = [name for name in raw_items if 0 < len(name) <= 100]

    if not valid_items:
        await update.message.reply_text(
            "⚠️ לא נמצאו פריטים תקינים להוספה."
        )
        return

    added: list[str] = []
    for name in valid_items:
        item = add_shopping_item(
            name=name,
            user_id=user.id,
            username=user.username,
        )
        if item:
            added.append(name)

    log_command(
        user_id=user.id,
        command="/add",
        username=user.username,
        arguments=", ".join(added),
        success=bool(added),
    )

    if len(added) == 1:
        await update.message.reply_text(f"🛒 נוסף לרשימה: *{added[0]}*", parse_mode="Markdown")
    else:
        bullet_list = "\n".join(f"• {name}" for name in added)
        await update.message.reply_text(
            f"🛒 נוספו {len(added)} פריטים לרשימה:\n{bullet_list}",
            parse_mode="Markdown",
        )

    logger.info(f"User {user.id} added {len(added)} item(s): {added}")


@require_auth
@rate_limit
async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /done <number> — remove an item by its list position.

    Args:
        update: Incoming Telegram update.
        context: Callback context provided by the bot framework.
    """
    user = update.effective_user

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "שימוש: /done <מספר> (לדוגמה: /done 2)"
        )
        return

    n = int(context.args[0])
    items = get_shopping_items()

    if n < 1 or n > len(items):
        await update.message.reply_text(
            f"⚠️ אין פריט מספר {n}. השתמש ב-/shop לצפייה ברשימה."
        )
        return

    item = items[n - 1]
    success = remove_shopping_item(item.id)

    log_command(
        user_id=user.id,
        command="/done",
        username=user.username,
        arguments=str(n),
        success=success,
    )

    if success:
        logger.info(f"User {user.id} removed item '{item.name}' (position {n})")
        await update.message.reply_text(
            f"✅ הוסר: *{item.name}*", parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("❌ לא הצלחתי להסיר את הפריט. נסה שוב.")


@require_admin
@rate_limit
async def cmd_clearshop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /clearshop — delete every item from the shopping list (admin only).

    Args:
        update: Incoming Telegram update.
        context: Callback context provided by the bot framework.
    """
    user = update.effective_user
    count = clear_shopping_list()

    log_command(
        user_id=user.id,
        command="/clearshop",
        username=user.username,
        arguments=f"cleared {count} items",
        success=True,
    )

    logger.info(f"Admin {user.id} cleared the shopping list ({count} items)")
    await update.message.reply_text(
        f"🗑️ רשימת הקניות נוקתה (הוסרו {count} פריטים)."
    )
