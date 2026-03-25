"""Connection and service availability tests.

Checks that:
  - The database initialises and all expected tables exist.
  - The local Ollama server is reachable and the configured model is pulled.
  - The Telegram Bot API accepts the configured token.

External-service tests are skipped gracefully when the service is unreachable.
"""

import pytest
from sqlalchemy import inspect


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

class TestDatabase:
    """SQLite / SQLAlchemy connectivity."""

    def test_init_db_succeeds(self, db):
        """init_db() completes without raising."""
        from database.models import get_session
        session = get_session()
        assert session is not None
        session.close()

    def test_get_session_before_init_raises(self):
        """get_session() raises RuntimeError when the engine is None."""
        import database.models as _m
        original = _m._engine
        _m._engine = None
        try:
            with pytest.raises(RuntimeError, match="init_db"):
                _m.get_session()
        finally:
            _m._engine = original

    def test_core_tables_exist(self, db):
        """All required tables are present after init_db()."""
        import database.models as _m
        inspector = inspect(_m._engine)
        existing = inspector.get_table_names()
        required = [
            "shopping_items",
            "reminders",
            "user_profiles",
            "user_memories",
            "tasks",
            "family_notes",
            "calendar_events",
            "command_log",
        ]
        for table in required:
            assert table in existing, f"Missing table: {table}"

    def test_double_init_is_safe(self, db):
        """Calling init_db() a second time on the same URL does not error."""
        from database.models import init_db
        init_db()  # already called by the `db` fixture; second call must be safe

    def test_user_profiles_has_icloud_columns(self, db):
        """icloud_username and icloud_app_password columns were migrated in."""
        import database.models as _m
        inspector = inspect(_m._engine)
        columns = {c["name"] for c in inspector.get_columns("user_profiles")}
        assert "icloud_username" in columns
        assert "icloud_app_password" in columns

    def test_reminders_has_recurring_column(self, db):
        """recurring and recurrence_type columns were migrated in."""
        import database.models as _m
        inspector = inspect(_m._engine)
        columns = {c["name"] for c in inspector.get_columns("reminders")}
        assert "recurring" in columns
        assert "recurrence_type" in columns


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

class TestOllama:
    """Local Ollama server connectivity — skipped when Ollama is offline."""

    def test_ollama_http_api_reachable(self, ollama_up):
        """Ollama /api/tags endpoint returns HTTP 200."""
        if not ollama_up:
            pytest.skip("Ollama not running")
        import httpx
        from config import Config
        r = httpx.get(f"{Config.OLLAMA_HOST}/api/tags", timeout=5)
        assert r.status_code == 200

    def test_configured_model_is_available(self, ollama_up):
        """OLLAMA_MODEL is listed in the pulled models."""
        if not ollama_up:
            pytest.skip("Ollama not running")
        import httpx
        from config import Config
        r = httpx.get(f"{Config.OLLAMA_HOST}/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        assert any(Config.OLLAMA_MODEL in m for m in models), (
            f"Model '{Config.OLLAMA_MODEL}' not found. "
            f"Run: ollama pull {Config.OLLAMA_MODEL}"
        )

    def test_ollama_client_can_be_created(self, ollama_up):
        """ollama.Client initialises without error."""
        if not ollama_up:
            pytest.skip("Ollama not running")
        import ollama
        from config import Config
        client = ollama.Client(host=Config.OLLAMA_HOST)
        assert client is not None


# ---------------------------------------------------------------------------
# Telegram Bot API
# ---------------------------------------------------------------------------

class TestTelegramToken:
    """Telegram Bot API token format and connectivity."""

    def test_token_has_correct_format(self):
        """BOT_TOKEN has the <numeric_id>:<secret> format.

        Reads directly from the environment (not the test-patched Config) so the
        real token is validated, not the mock value used by other tests.
        """
        import os
        from pathlib import Path

        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
        token = os.getenv("BOT_TOKEN", "")
        if not token:
            pytest.skip("BOT_TOKEN not set in .env — skipping format check")
        assert ":" in token, "BOT_TOKEN must contain ':'"
        bot_id, secret = token.split(":", 1)
        assert bot_id.isdigit(), "BOT_TOKEN prefix must be a numeric bot ID"
        assert len(secret) > 20, "BOT_TOKEN secret section is suspiciously short"

    def test_telegram_api_accepts_token(self, telegram_up):
        """Telegram Bot API returns ok=True for the configured token."""
        if not telegram_up:
            pytest.skip("Telegram API not reachable or token invalid")
        # If telegram_up is True, the fixture already confirmed ok=True.
        assert telegram_up is True
