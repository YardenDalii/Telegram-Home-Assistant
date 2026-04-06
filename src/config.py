"""Configuration loader for the Home Automation Bot.

Reads all settings from environment variables (loaded from .env).
Import and use the ``Config`` class everywhere — never read os.getenv directly.
"""

import os
import sys
from pathlib import Path
from typing import ClassVar

from dotenv import load_dotenv

# Load .env from project root (two levels up from src/)
_ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH)


def _parse_int_list(value: str) -> list[int]:
    """Parse a comma-separated string of integers.

    Args:
        value: Comma-separated integer string, e.g. "123,456".

    Returns:
        list[int]: Parsed list, empty list on blank input.
    """
    if not value:
        return []
    return [int(uid.strip()) for uid in value.split(",") if uid.strip().isdigit()]


class Config:
    """Centralised, typed access to all environment configuration.

    All attributes are class-level — instantiation is not required.
    Call ``Config.validate()`` at startup to catch missing values early.
    """

    # Telegram
    BOT_TOKEN: ClassVar[str] = os.getenv("BOT_TOKEN", "")

    # Authorization
    AUTHORIZED_USERS: ClassVar[list[int]] = _parse_int_list(
        os.getenv("AUTHORIZED_USERS", "")
    )
    ADMIN_USERS: ClassVar[list[int]] = _parse_int_list(
        os.getenv("ADMIN_USERS", "")
    )

    # Logging
    LOG_LEVEL: ClassVar[str] = os.getenv("LOG_LEVEL", "INFO").upper()

    # Database
    DATABASE_URL: ClassVar[str] = os.getenv("DATABASE_URL", "sqlite:///bot.db")

    # Rate limiting
    RATE_LIMIT: ClassVar[int] = int(os.getenv("RATE_LIMIT", "10"))

    # Ollama local AI (conversational assistant — optional, leave blank to disable)
    OLLAMA_HOST: ClassVar[str] = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    OLLAMA_MODEL: ClassVar[str] = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")
    OLLAMA_NUM_CTX: ClassVar[int] = int(os.getenv("OLLAMA_NUM_CTX", "2048"))
    OLLAMA_KEEP_ALIVE: ClassVar[str] = os.getenv("OLLAMA_KEEP_ALIVE", "1h")
    OLLAMA_HISTORY_PAIRS: ClassVar[int] = int(os.getenv("OLLAMA_HISTORY_PAIRS", "5"))

    # Switcher Touch — direct LAN control via aioswitcher (no Homebridge needed)
    SWITCHER_NAME: ClassVar[str] = os.getenv("SWITCHER_DEVICE_NAME", "Switcher Touch")
    SWITCHER_IP: ClassVar[str] = os.getenv("SWITCHER_DEVICE_IP", "")
    SWITCHER_ID: ClassVar[str] = os.getenv("SWITCHER_DEVICE_ID", "")
    SWITCHER_KEY: ClassVar[str] = os.getenv("SWITCHER_DEVICE_KEY", "00000000")

    @classmethod
    def validate(cls) -> list[str]:
        """Check for missing or invalid configuration values.

        Returns:
            list[str]: List of error messages; empty list means config is valid.
        """
        errors: list[str] = []

        if not cls.BOT_TOKEN or cls.BOT_TOKEN == "your_telegram_bot_token_here":
            errors.append("BOT_TOKEN is not set — get one from @BotFather on Telegram")

        if not cls.AUTHORIZED_USERS:
            errors.append(
                "AUTHORIZED_USERS is empty — add at least one Telegram user ID"
            )

        if cls.RATE_LIMIT <= 0:
            errors.append("RATE_LIMIT must be a positive integer")

        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if cls.LOG_LEVEL not in valid_levels:
            errors.append(f"LOG_LEVEL must be one of {valid_levels}")

        return errors
