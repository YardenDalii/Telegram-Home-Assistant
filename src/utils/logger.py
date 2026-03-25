"""Logging configuration for the Home Automation Bot.

Provides a centralized logger factory with colored console output
and optional file logging, controlled by the LOG_LEVEL environment variable.
"""

import logging
import os
import sys
from pathlib import Path


# ANSI color codes for console output
_COLORS = {
    "DEBUG": "\033[36m",      # Cyan
    "INFO": "\033[32m",       # Green
    "WARNING": "\033[33m",    # Yellow
    "ERROR": "\033[31m",      # Red
    "CRITICAL": "\033[35m",   # Magenta
    "RESET": "\033[0m",
}

_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
_LOG_DIR = Path(__file__).parent.parent.parent / "logs"

_initialized = False


class _ColorFormatter(logging.Formatter):
    """Logging formatter that adds ANSI color codes to level names."""

    def format(self, record: logging.LogRecord) -> str:
        color = _COLORS.get(record.levelname, _COLORS["RESET"])
        reset = _COLORS["RESET"]
        record.levelname = f"{color}{record.levelname:<8}{reset}"
        return super().format(record)


def _setup_root_logger() -> None:
    """Configure the root logger once on first call."""
    global _initialized
    if _initialized:
        return

    level = getattr(logging, _LOG_LEVEL, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    # Console handler with color
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(
        _ColorFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(console)

    # Suppress noisy third-party HTTP polling logs (Telegram getUpdates heartbeat)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # File handler (plain text, no colors)
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(_LOG_DIR / "bot.log", encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root.addHandler(file_handler)
    except OSError:
        # Non-fatal: if logs dir can't be created, console-only logging is fine
        pass

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """Return a named logger with color console and file output.

    Args:
        name: Logger name, typically ``__name__`` of the calling module.

    Returns:
        logging.Logger: Configured logger instance.
    """
    _setup_root_logger()
    return logging.getLogger(name)
