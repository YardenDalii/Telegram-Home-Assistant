"""Bot framework — builds the Telegram Application and registers all handlers.

Security model (layered defence-in-depth):
  Layer 1 — Application filter: every handler uses ``filters.User`` so messages
             from non-whitelisted user IDs never reach a handler function.
  Layer 2 — Catch-all handler: any message from an unauthorized user is silently
             dropped with no reply — the bot appears non-existent to outsiders.
  Layer 3 — ``@require_auth`` decorator: secondary auth check inside each handler.
  Layer 4 — ``@rate_limit`` decorator: per-user sliding-window rate limiting.
"""

from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from ai.assistant import handle_chat, reschedule_pending_reminders
from commands.calendar import cmd_calendar
from commands.help import cmd_help
from commands.reminders import cmd_cancelreminder, cmd_remind, cmd_reminders
from commands.shopping import cmd_add, cmd_clearshop, cmd_done, cmd_shop
from commands.system import cmd_clearall, cmd_reload, cmd_start
from config import Config
from utils.logger import get_logger

logger = get_logger(__name__)


def _build_auth_filter() -> filters.BaseFilter:
    """Build a User filter from the current authorized user list.

    Returns:
        filters.BaseFilter: Filter that passes only whitelisted user IDs.
    """
    if not Config.AUTHORIZED_USERS:
        logger.critical("AUTHORIZED_USERS is empty — bot will reject everyone")
    return filters.User(user_id=Config.AUTHORIZED_USERS)


async def _handle_unauthorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Silently drop any message from a non-whitelisted user.

    No reply is sent. From the sender's perspective the bot does not exist.
    """
    user = update.effective_user
    if user:
        logger.warning(
            f"[SECURITY] Message silently dropped — "
            f"user_id={user.id} username=@{user.username} "
            f"text='{str(update.message.text or '')[:50]}'"
        )


async def _handle_unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tell authorized users when they send an unrecognised command."""
    user = update.effective_user
    logger.info(f"User {user.id} sent unknown command: {update.message.text[:50]}")
    await update.message.reply_text("פקודה לא ידועה. השתמש ב-/help לרשימת הפקודות.")


class HomeBot:
    """Telegram bot wrapper for the home automation system.

    Args:
        token: Telegram bot token from @BotFather. Defaults to ``Config.BOT_TOKEN``.
    """

    def __init__(self, token: str | None = None) -> None:
        self._token = token or Config.BOT_TOKEN
        self._auth_filter = _build_auth_filter()
        self._app: Application = Application.builder().token(self._token).build()
        self._setup_handlers()
        logger.info("HomeBot initialized")

    def _setup_handlers(self) -> None:
        """Register all handlers with security filters applied.

        Handler evaluation order (within group 0):
          1. Authorised-user CommandHandlers  — matched first if user is whitelisted
          2. Unknown command handler          — catches any unrecognised command from authorised users
          3. Catch-all unauthorized handler   — drops everything else silently
        """
        auth = self._auth_filter

        # --- Authorised command handlers ---
        self._app.add_handler(CommandHandler("start", cmd_start, filters=auth))
        self._app.add_handler(CommandHandler("help", cmd_help, filters=auth))

        # Shopping
        self._app.add_handler(CommandHandler("shop", cmd_shop, filters=auth))
        self._app.add_handler(CommandHandler("add", cmd_add, filters=auth))
        self._app.add_handler(CommandHandler("done", cmd_done, filters=auth))
        self._app.add_handler(CommandHandler("clearshop", cmd_clearshop, filters=auth))

        # Calendar
        self._app.add_handler(CommandHandler("calendar", cmd_calendar, filters=auth))

        # Reminders
        self._app.add_handler(CommandHandler("reminders", cmd_reminders, filters=auth))
        self._app.add_handler(CommandHandler("remind", cmd_remind, filters=auth))
        self._app.add_handler(CommandHandler("cancelreminder", cmd_cancelreminder, filters=auth))

        # Admin
        self._app.add_handler(CommandHandler("clearall", cmd_clearall, filters=auth))
        self._app.add_handler(CommandHandler("reload", cmd_reload, filters=auth))

        # --- Plain text → Ollama AI ---
        self._app.add_handler(
            MessageHandler(auth & filters.TEXT & ~filters.COMMAND, handle_chat)
        )

        # --- Unknown commands (authorised users only) ---
        self._app.add_handler(
            MessageHandler(auth & filters.COMMAND, _handle_unknown_command)
        )

        # --- Catch-all: silently drop everything from unauthorized users ---
        # This covers commands, plain text, photos, stickers, voice, etc.
        self._app.add_handler(
            MessageHandler(~self._auth_filter, _handle_unauthorized)
        )

        logger.debug("Security handlers registered")

    async def _set_commands(self, _application: Application | None = None) -> None:
        """Push the command list to Telegram so it shows in the UI."""
        commands = [
            BotCommand("start", "הודעת פתיחה"),
            BotCommand("help", "רשימת פקודות"),
            # Shopping
            BotCommand("shop", "הצג רשימת קניות"),
            BotCommand("add", "הוסף פריט/ים — /add חלב, ביצים"),
            BotCommand("done", "הסר פריט — /done 2"),
            BotCommand("clearshop", "נקה רשימה (מנהל)"),
            # Calendar
            BotCommand("calendar", "ניהול יומן Apple — חיבור, סטטוס, ברירת מחדל"),
            # Reminders
            BotCommand("reminders", "הצג תזכורות פעילות"),
            BotCommand("remind", "קבע תזכורת — /remind 30 לצאת"),
            BotCommand("cancelreminder", "בטל תזכורת — /cancelreminder 1"),
            # Admin
            BotCommand("clearall", "נקה את כל הנתונים (מנהל בלבד)"),
        ]
        await self._app.bot.set_my_commands(commands)
        logger.info("Bot commands registered with Telegram")

    async def _post_init(self, application: Application) -> None:
        """Run after the Application is built but before polling starts."""
        await self._set_commands(application)
        if application.job_queue:
            reschedule_pending_reminders(application.job_queue)
            logger.info("Pending reminders re-scheduled on startup")

    def run(self) -> None:
        """Start the bot in polling mode (blocking).

        Registers bot commands on Telegram, then starts the polling loop.
        The bot will run until interrupted (Ctrl-C or SIGTERM).
        """
        logger.info(f"Starting Home Automation Bot... (model: {Config.OLLAMA_MODEL})")

        # Register commands and re-schedule reminders on startup
        self._app.post_init = self._post_init

        self._app.run_polling(
            allowed_updates=["message"],
            drop_pending_updates=True,
        )
        logger.info("Bot stopped.")
