"""Entry point for the Home Automation Bot.

Validates configuration, initialises the database, registers devices,
and starts the Telegram bot polling loop.
"""

import importlib
import signal
import sys
from pathlib import Path

# Ensure src/ is on the Python path when running directly
sys.path.insert(0, str(Path(__file__).parent))

from bot import HomeBot
from config import Config
from database.models import init_db
from utils.logger import get_logger

logger = get_logger(__name__)


def _reload_assistant(signum, frame) -> None:
    """SIGHUP handler — reload ai.assistant without restarting the bot.

    Trigger from the terminal:
        kill -HUP $(pgrep -f main.py)
    """
    try:
        import ai.assistant as assistant_module
        importlib.reload(assistant_module)
        logger.info("SIGHUP received — ai.assistant reloaded successfully")
    except Exception as exc:
        logger.error(f"SIGHUP reload failed: {exc}")


def main() -> None:
    """Validate config, initialise all subsystems, and start the bot."""
    signal.signal(signal.SIGHUP, _reload_assistant)
    # --- 1. Validate configuration ---
    errors = Config.validate()
    if errors:
        for error in errors:
            logger.critical(f"Configuration error: {error}")
        logger.critical("Fix the errors above in your .env file and restart.")
        sys.exit(1)

    logger.info("Configuration validated successfully")

    # --- 2. Initialise database ---
    init_db()

    # --- 3. Create bot ---
    bot = HomeBot()

    # --- 4. Run ---
    logger.info(
        f"Bot starting — authorized users: {Config.AUTHORIZED_USERS}"
    )
    bot.run()


if __name__ == "__main__":
    main()
