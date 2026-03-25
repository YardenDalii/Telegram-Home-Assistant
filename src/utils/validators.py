"""Input validation and sanitization utilities.

All user input from Telegram messages must pass through these functions
before being processed or logged.
"""

import re
from utils.logger import get_logger

logger = get_logger(__name__)

# Allowed characters in commands and device names
_COMMAND_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")
_SAFE_TEXT_PATTERN = re.compile(r"[^\w\s\-.,!?@#]", re.UNICODE)


def sanitize_input(text: str) -> str:
    """Strip dangerous characters from user-provided text.

    Removes non-printable characters and limits length to 500 chars.

    Args:
        text: Raw user input string.

    Returns:
        str: Sanitized string safe for logging and processing.
    """
    if not isinstance(text, str):
        return ""
    # Remove control characters, keep printable Unicode
    cleaned = _SAFE_TEXT_PATTERN.sub("", text)
    return cleaned.strip()[:500]


def validate_command(command: str) -> bool:
    """Validate that a command or argument matches the allowed pattern.

    Only alphanumeric characters, underscores, and hyphens are allowed.

    Args:
        command: The command string or argument to validate.

    Returns:
        bool: True if valid, False otherwise.

    Raises:
        ValueError: If command is None.
    """
    if command is None:
        raise ValueError("Command cannot be None")
    is_valid = bool(_COMMAND_PATTERN.match(command))
    if not is_valid:
        logger.warning(f"Invalid command format rejected: '{command[:50]}'")
    return is_valid
