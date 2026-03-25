"""Function decorators for Telegram command handlers.

Provides ``@require_auth``, ``@require_admin``, and ``@rate_limit`` decorators.
All unauthorized rejections are silent — no reply is sent to the requester,
so the bot appears non-existent to anyone not on the whitelist.
"""

import functools
import time
from collections import defaultdict, deque
from typing import Callable

from telegram import Update
from telegram.ext import ContextTypes

from auth import authenticate_user, is_admin
from utils.logger import get_logger

logger = get_logger(__name__)

# Per-user sliding window: user_id → deque of timestamps (monotonic seconds)
_rate_windows: dict[int, deque] = defaultdict(deque)
_RATE_WINDOW_SECONDS = 60


def require_auth(func: Callable) -> Callable:
    """Decorator: silently drop requests from unauthorized users.

    This is a secondary defence layer — the primary filter is applied at
    the Application level in bot.py. If somehow an unauthorized message
    slips through, this decorator drops it with no reply.

    Args:
        func: The async command handler to protect.

    Returns:
        Callable: Wrapped handler that checks auth first.
    """
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if user is None:
            return
        if not authenticate_user(user.id):
            # Silent drop — no reply, no acknowledgement
            logger.warning(
                f"[AUTH] Unauthorized message silently dropped — user_id={user.id}"
            )
            return
        return await func(update, context)
    return wrapper


def require_admin(func: Callable) -> Callable:
    """Decorator: restrict a handler to admin users only.

    Non-admin authorized users receive a generic "unknown command" reply,
    not an "admin required" message, to avoid revealing command existence.

    Args:
        func: The async command handler to protect.

    Returns:
        Callable: Wrapped handler that checks admin status.
    """
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if user is None:
            return
        if not authenticate_user(user.id):
            logger.warning(
                f"[AUTH] Unauthorized message silently dropped — user_id={user.id}"
            )
            return
        if not is_admin(user.id):
            logger.warning(
                f"[AUTH] Non-admin user {user.id} attempted admin-only command"
            )
            await update.message.reply_text(
                "פקודה לא ידועה. השתמש ב-/help לרשימת הפקודות."
            )
            return
        return await func(update, context)
    return wrapper


def rate_limit(func: Callable) -> Callable:
    """Decorator: enforce per-user rate limiting using a sliding window.

    Tracks command timestamps per user over a 60-second window.
    The maximum number of calls is read from ``Config.RATE_LIMIT``.
    Excess requests are silently dropped (no reply) and logged as warnings.

    Args:
        func: The async command handler to rate-limit.

    Returns:
        Callable: Wrapped handler that enforces rate limiting.
    """
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        from config import Config  # late import to avoid circular dependency

        user = update.effective_user
        if user is None:
            return

        now = time.monotonic()
        window = _rate_windows[user.id]

        # Evict timestamps outside the sliding window
        while window and window[0] < now - _RATE_WINDOW_SECONDS:
            window.popleft()

        if len(window) >= Config.RATE_LIMIT:
            logger.warning(
                f"[RATE] User {user.id} exceeded rate limit "
                f"({Config.RATE_LIMIT} req/{_RATE_WINDOW_SECONDS}s) — request dropped"
            )
            await update.message.reply_text("⏳ יותר מדי הודעות בפרק זמן קצר. נסה שוב עוד רגע.")
            return

        window.append(now)
        return await func(update, context)
    return wrapper
