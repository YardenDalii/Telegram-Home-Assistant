"""Authentication and authorization module.

Provides functions to check whether a Telegram user is allowed to use
the bot and whether they have admin privileges.
"""

from config import Config
from utils.logger import get_logger

logger = get_logger(__name__)


def authenticate_user(user_id: int) -> bool:
    """Check if a Telegram user is in the authorized whitelist.

    Args:
        user_id: The Telegram numeric user ID.

    Returns:
        bool: True if authorized, False otherwise.
    """
    authorized = user_id in Config.AUTHORIZED_USERS
    if not authorized:
        logger.warning(f"Unauthorized access attempt from user_id={user_id}")
    return authorized


def is_admin(user_id: int) -> bool:
    """Check if a Telegram user has admin privileges.

    Args:
        user_id: The Telegram numeric user ID.

    Returns:
        bool: True if the user is an admin, False otherwise.
    """
    return user_id in Config.ADMIN_USERS
