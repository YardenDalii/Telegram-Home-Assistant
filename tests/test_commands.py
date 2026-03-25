"""Tests for Telegram command handlers."""

from unittest.mock import MagicMock

import pytest

from commands.help import cmd_help
from commands.system import cmd_start, cmd_status, cmd_test


def _ctx(args=None):
    """Minimal mock context — inline helper so we don't import conftest directly."""
    ctx = MagicMock()
    ctx.args = args or []
    ctx.job_queue = None
    return ctx


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

class TestCmdStart:
    """/start sends a greeting appropriate to the user's registration state."""

    async def test_new_user_gets_generic_welcome(self, authorized_update, db):
        """/start with no profile sends the generic welcome."""
        await cmd_start(authorized_update, _ctx())
        authorized_update.message.reply_text.assert_called_once()
        text = authorized_update.message.reply_text.call_args[0][0]
        assert "שלום" in text or "ברוך הבא" in text

    async def test_onboarded_user_gets_personalised_greeting(self, authorized_update, onboarded_user):
        """/start with a complete profile sends a personalised greeting."""
        await cmd_start(authorized_update, _ctx())
        authorized_update.message.reply_text.assert_called_once()
        text = authorized_update.message.reply_text.call_args[0][0]
        assert "ישראל ישראלי" in text  # display name set by onboarded_user fixture

    async def test_unauthorized_user_gets_no_reply(self, unauthorized_update):
        """@require_auth silently drops messages from non-whitelisted users."""
        await cmd_start(unauthorized_update, _ctx())
        unauthorized_update.message.reply_text.assert_not_called()


# ---------------------------------------------------------------------------
# /status
# ---------------------------------------------------------------------------

class TestCmdStatus:
    """/status returns bot uptime and system information."""

    async def test_status_replies_to_authorized_user(self, authorized_update):
        await cmd_status(authorized_update, _ctx())
        authorized_update.message.reply_text.assert_called_once()
        text = authorized_update.message.reply_text.call_args[0][0]
        assert "Status" in text
        assert "Online" in text or "✅" in text

    async def test_status_includes_uptime(self, authorized_update):
        await cmd_status(authorized_update, _ctx())
        text = authorized_update.message.reply_text.call_args[0][0]
        assert "Uptime" in text


# ---------------------------------------------------------------------------
# /test
# ---------------------------------------------------------------------------

class TestCmdTest:
    """/test confirms bot connectivity."""

    async def test_replies_with_success_message(self, authorized_update):
        await cmd_test(authorized_update, _ctx())
        authorized_update.message.reply_text.assert_called_once()
        text = authorized_update.message.reply_text.call_args[0][0]
        assert "✅" in text or "successful" in text.lower()


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------

class TestCmdHelp:
    """/help returns the full command reference."""

    async def test_help_replies_to_authorized_user(self, authorized_update):
        await cmd_help(authorized_update, _ctx())
        authorized_update.message.reply_text.assert_called_once()

    async def test_help_text_contains_slash_commands(self, authorized_update):
        await cmd_help(authorized_update, _ctx())
        text = authorized_update.message.reply_text.call_args[0][0]
        for cmd in ["/shop", "/add", "/done", "/reminders", "/remind", "/cancelreminder"]:
            assert cmd in text, f"Expected '{cmd}' in help text"

    async def test_help_text_covers_all_feature_areas(self, authorized_update):
        await cmd_help(authorized_update, _ctx())
        text = authorized_update.message.reply_text.call_args[0][0]
        for keyword in ["קניות", "תזכורות", "זיכרון", "משימות", "לוח שנה", "משפחה"]:
            assert keyword in text, f"Expected feature area '{keyword}' in help text"

    async def test_unauthorized_user_gets_no_reply(self, unauthorized_update):
        await cmd_help(unauthorized_update, _ctx())
        unauthorized_update.message.reply_text.assert_not_called()
