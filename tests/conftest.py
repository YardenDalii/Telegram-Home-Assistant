"""Pytest configuration and shared fixtures.

Provides mock Telegram objects and a patched Config so tests can run
without a real bot token, database, or Raspberry Pi GPIO.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure src/ is importable from the test suite
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture(autouse=True)
def mock_config(monkeypatch):
    """Patch Config with safe test values for every test."""
    monkeypatch.setattr("config.Config.BOT_TOKEN", "test-token-123")
    monkeypatch.setattr("config.Config.AUTHORIZED_USERS", [111111111, 222222222])
    monkeypatch.setattr("config.Config.ADMIN_USERS", [111111111])
    monkeypatch.setattr("config.Config.RATE_LIMIT", 10)
    monkeypatch.setattr("config.Config.LOG_LEVEL", "DEBUG")
    monkeypatch.setattr("config.Config.DATABASE_URL", "sqlite:///:memory:")


def make_update(user_id: int = 111111111, username: str = "testuser") -> MagicMock:
    """Create a minimal mock Telegram Update object.

    Args:
        user_id: Telegram user ID to embed in the mock.
        username: Telegram username to embed in the mock.

    Returns:
        MagicMock: Mocked Update with effective_user and message.reply_text.
    """
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.username = username
    update.effective_user.first_name = "Test"
    update.message.reply_text = AsyncMock()
    return update


def make_context(args: list[str] | None = None) -> MagicMock:
    """Create a minimal mock Telegram CallbackContext.

    Args:
        args: List of argument strings (context.args).

    Returns:
        MagicMock: Mocked context with args attribute.
    """
    context = MagicMock()
    context.args = args or []
    return context


@pytest.fixture
def authorized_update():
    """Telegram Update from an authorized user (ID 111111111)."""
    return make_update(user_id=111111111, username="admin_user")


@pytest.fixture
def unauthorized_update():
    """Telegram Update from a user NOT in the authorized list."""
    return make_update(user_id=999999999, username="hacker")


@pytest.fixture
def admin_update():
    """Telegram Update from a user with admin privileges."""
    return make_update(user_id=111111111, username="admin_user")


@pytest.fixture
def non_admin_update():
    """Telegram Update from an authorized but non-admin user."""
    return make_update(user_id=222222222, username="regular_user")


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    """Initialize a fresh in-memory SQLite database for each test.

    Resets the module-level engine before and after so tests are fully isolated.
    Depends on mock_config (autouse) having already patched DATABASE_URL.
    """
    import database.models as _m
    _m._engine = None  # ensure clean slate
    from database.models import init_db
    init_db()
    yield
    _m._engine = None


@pytest.fixture
def onboarded_user(db):
    """Create and return the user_id of a fully onboarded user (ID 111111111)."""
    from database.models import (
        create_user_profile,
        mark_calendar_onboarding_done,
        set_user_name,
        set_user_role,
    )
    user_id = 111111111
    create_user_profile(user_id)
    set_user_name(user_id, "ישראל ישראלי")
    set_user_role(user_id, "אבא")
    mark_calendar_onboarding_done(user_id)
    return user_id


# ---------------------------------------------------------------------------
# Service-availability fixture (session-scoped, avoids repeated HTTP calls)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def ollama_up() -> bool:
    """True if the local Ollama server is reachable at test-session start."""
    try:
        import httpx
        from config import Config
        r = httpx.get(f"{Config.OLLAMA_HOST}/api/tags", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


@pytest.fixture(scope="session")
def telegram_up() -> bool:
    """True if the Telegram Bot API responds with ok=True for the configured token."""
    try:
        import httpx
        from config import Config
        r = httpx.get(
            f"https://api.telegram.org/bot{Config.BOT_TOKEN}/getMe", timeout=10
        )
        return r.json().get("ok") is True
    except Exception:
        return False
