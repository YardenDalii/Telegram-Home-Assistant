"""Tests for AI assistant logic.

Covers:
  - Tool dispatcher: _TOOL_REGISTRY population, @_tool decorator, unknown tool fallback
  - Tool routing: _select_tools() keyword matching
  - Family member resolution: _resolve_family_member()
  - Tool execution: _execute_tool() for all shopping and reminder tools
  - Conversation history helpers
"""

from datetime import datetime, timedelta, timezone

import pytest

USER_ID = 111111111


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

class TestToolDispatcher:
    """_TOOL_REGISTRY is populated correctly by the @_tool decorator."""

    def test_registry_contains_all_shopping_tools(self):
        from ai.assistant import _TOOL_REGISTRY
        for name in ("add_shopping_items", "get_shopping_list", "remove_shopping_item",
                     "remove_shopping_item_by_name", "edit_shopping_item",
                     "edit_shopping_item_by_name", "clear_shopping_list"):
            assert name in _TOOL_REGISTRY, f"Missing from registry: {name}"

    def test_registry_contains_all_reminder_tools(self):
        from ai.assistant import _TOOL_REGISTRY
        for name in ("set_reminder", "list_reminders", "cancel_reminder"):
            assert name in _TOOL_REGISTRY, f"Missing from registry: {name}"

    def test_registered_handlers_are_callable(self):
        from ai.assistant import _TOOL_REGISTRY
        for name, handler in _TOOL_REGISTRY.items():
            assert callable(handler), f"Handler for '{name}' is not callable"

    def test_tool_decorator_registers_under_correct_name(self):
        """@_tool('x') must store the function under exactly 'x'."""
        import asyncio
        from ai.assistant import _TOOL_REGISTRY, _tool

        @_tool("__test_sentinel__")
        async def _dummy(args, user_id, username, job_queue):
            return "ok"

        assert "__test_sentinel__" in _TOOL_REGISTRY
        assert asyncio.iscoroutinefunction(_TOOL_REGISTRY["__test_sentinel__"])
        # clean up so we don't pollute other tests
        del _TOOL_REGISTRY["__test_sentinel__"]

    async def test_execute_tool_dispatches_to_correct_handler(self, db):
        """_execute_tool routes to the right handler based on the tool name."""
        from ai.assistant import _execute_tool
        result = await _execute_tool("get_shopping_list", {}, USER_ID, "test")
        # Empty list produces a "no items" message (not a warning)
        assert "⚠️" not in result

    async def test_execute_tool_unknown_name_returns_warning(self, db):
        from ai.assistant import _execute_tool
        result = await _execute_tool("totally_unknown_tool", {}, USER_ID, "test")
        assert "⚠️" in result

    def test_registry_does_not_contain_unknown_tools(self):
        from ai.assistant import _KNOWN_TOOLS, _TOOL_REGISTRY
        # Every name in the registry must also be declared in _KNOWN_TOOLS
        unregistered = set(_TOOL_REGISTRY) - _KNOWN_TOOLS - {"__test_sentinel__"}
        assert not unregistered, f"Tools in registry but not in _KNOWN_TOOLS: {unregistered}"


# ---------------------------------------------------------------------------
# Tool routing
# ---------------------------------------------------------------------------

class TestSelectTools:
    """_select_tools() maps Hebrew keywords to the correct tool groups."""

    def test_shopping_keyword_selects_shopping_tools(self):
        from ai.assistant import _SHOPPING_TOOLS, _select_tools
        result = _select_tools("תוסיף חלב לרשימה")
        names = {t["function"]["name"] for t in result}
        assert "add_shopping_items" in names
        assert "set_reminder" not in names

    def test_reminder_keyword_selects_reminder_tools(self):
        from ai.assistant import _REMINDER_TOOLS, _select_tools
        result = _select_tools("תזכיר לי עוד שעה לאכול")
        names = {t["function"]["name"] for t in result}
        assert "set_reminder" in names
        assert "add_shopping_items" not in names

    def test_greeting_returns_empty_list(self):
        from ai.assistant import _select_tools
        assert _select_tools("שלום, מה נשמע?") == []

    def test_thanks_returns_empty_list(self):
        from ai.assistant import _select_tools
        assert _select_tools("תודה רבה!") == []

    def test_ambiguous_mah_yesh_returns_all_tools(self):
        from ai.assistant import _select_tools
        result = _select_tools("מה יש לי?")
        names = {t["function"]["name"] for t in result}
        assert "add_shopping_items" in names
        assert "set_reminder" in names

    def test_ambiguous_matzav_returns_all_tools(self):
        from ai.assistant import _select_tools
        result = _select_tools("מה המצב?")
        names = {t["function"]["name"] for t in result}
        assert "add_shopping_items" in names

    def test_mixed_keywords_selects_both_groups(self):
        from ai.assistant import _select_tools
        result = _select_tools("תוסיף חלב ותזכיר לי לקנות עוד")
        names = {t["function"]["name"] for t in result}
        assert "add_shopping_items" in names
        assert "set_reminder" in names

    def test_remove_keyword_selects_shopping(self):
        from ai.assistant import _select_tools
        result = _select_tools("הסר את הפריט הראשון")
        names = {t["function"]["name"] for t in result}
        assert "remove_shopping_item" in names

    def test_list_reminders_keyword(self):
        from ai.assistant import _select_tools
        result = _select_tools("אילו תזכורות יש לי?")
        names = {t["function"]["name"] for t in result}
        assert "list_reminders" in names


# ---------------------------------------------------------------------------
# Family member resolution
# ---------------------------------------------------------------------------

class TestResolveFamilyMember:
    """_resolve_family_member() matches profiles by name or role substring."""

    def test_match_by_display_name(self, db):
        from ai.assistant import _resolve_family_member
        from database.models import create_user_profile, set_user_name, set_user_role
        create_user_profile(200)
        set_user_name(200, "שרה")
        set_user_role(200, "אמא")
        result = _resolve_family_member("שרה")
        assert result is not None
        assert result.user_id == 200

    def test_no_match_returns_none(self, db):
        from ai.assistant import _resolve_family_member
        result = _resolve_family_member("nobody_with_this_name_xyz")
        assert result is None

    def test_partial_name_match(self, db):
        from ai.assistant import _resolve_family_member
        from database.models import create_user_profile, set_user_name, set_user_role
        create_user_profile(202)
        set_user_name(202, "ישראל ישראלי")
        set_user_role(202, "סבא")
        result = _resolve_family_member("ישראל")
        assert result is not None

    def test_no_match_returns_none(self, db):
        from ai.assistant import _resolve_family_member
        result = _resolve_family_member("אורח_לא_קיים")
        assert result is None

    def test_case_insensitive_match(self, db):
        from ai.assistant import _resolve_family_member
        from database.models import create_user_profile, set_user_name, set_user_role
        create_user_profile(203)
        set_user_name(203, "DAVID")
        set_user_role(203, "בן")
        result = _resolve_family_member("david")
        assert result is not None


# ---------------------------------------------------------------------------
# _execute_tool — shopping
# ---------------------------------------------------------------------------

class TestExecuteToolShopping:
    """_execute_tool() for shopping-list operations."""

    async def test_add_single_item(self, onboarded_user):
        from ai.assistant import _execute_tool
        result = await _execute_tool(
            "add_shopping_items", {"items": ["חלב"]}, onboarded_user, "test"
        )
        assert "חלב" in result
        assert "🛒" in result

    async def test_add_multiple_items(self, onboarded_user):
        from ai.assistant import _execute_tool
        result = await _execute_tool(
            "add_shopping_items", {"items": ["חלב", "ביצים", "לחם"]}, onboarded_user, "test"
        )
        assert "חלב" in result
        assert "ביצים" in result
        assert "לחם" in result

    async def test_add_empty_items_returns_warning(self, onboarded_user):
        from ai.assistant import _execute_tool
        result = await _execute_tool(
            "add_shopping_items", {"items": []}, onboarded_user, "test"
        )
        assert "⚠️" in result

    async def test_get_shopping_list_empty(self, onboarded_user):
        from ai.assistant import _execute_tool
        result = await _execute_tool("get_shopping_list", {}, onboarded_user, "test")
        assert "ריקה" in result

    async def test_get_shopping_list_populated(self, onboarded_user):
        from ai.assistant import _execute_tool
        from database.models import add_shopping_item
        add_shopping_item("גבינה", onboarded_user, "test")
        result = await _execute_tool("get_shopping_list", {}, onboarded_user, "test")
        assert "גבינה" in result
        assert "1." in result  # numbered list

    async def test_remove_item_by_number(self, onboarded_user):
        from ai.assistant import _execute_tool
        from database.models import add_shopping_item
        add_shopping_item("תפוח", onboarded_user, "test")
        result = await _execute_tool(
            "remove_shopping_item", {"item_number": 1}, onboarded_user, "test"
        )
        assert "תפוח" in result
        assert "✅" in result

    async def test_remove_item_out_of_range_returns_warning(self, onboarded_user):
        from ai.assistant import _execute_tool
        result = await _execute_tool(
            "remove_shopping_item", {"item_number": 99}, onboarded_user, "test"
        )
        assert "⚠️" in result

    async def test_remove_item_by_name(self, onboarded_user):
        from ai.assistant import _execute_tool
        from database.models import add_shopping_item
        add_shopping_item("אורז", onboarded_user, "test")
        result = await _execute_tool(
            "remove_shopping_item_by_name", {"item_name": "אורז"}, onboarded_user, "test"
        )
        assert "אורז" in result
        assert "✅" in result

    async def test_remove_by_name_not_found_returns_warning(self, onboarded_user):
        from ai.assistant import _execute_tool
        result = await _execute_tool(
            "remove_shopping_item_by_name", {"item_name": "מוצר_לא_קיים"}, onboarded_user, "test"
        )
        assert "⚠️" in result

    async def test_edit_item_by_number(self, onboarded_user):
        from ai.assistant import _execute_tool
        from database.models import add_shopping_item
        add_shopping_item("חלב 1%", onboarded_user, "test")
        result = await _execute_tool(
            "edit_shopping_item",
            {"item_number": 1, "new_name": "חלב 3%"},
            onboarded_user,
            "test",
        )
        assert "חלב 3%" in result
        assert "✏️" in result

    async def test_edit_item_by_name(self, onboarded_user):
        from ai.assistant import _execute_tool
        from database.models import add_shopping_item
        add_shopping_item("ביצים רגילות", onboarded_user, "test")
        result = await _execute_tool(
            "edit_shopping_item_by_name",
            {"item_name": "ביצים", "new_name": "ביצים חופשיות"},
            onboarded_user,
            "test",
        )
        assert "ביצים חופשיות" in result

    async def test_clear_shopping_list(self, onboarded_user):
        from ai.assistant import _execute_tool
        from database.models import add_shopping_item
        add_shopping_item("פריט א", onboarded_user)
        add_shopping_item("פריט ב", onboarded_user)
        result = await _execute_tool("clear_shopping_list", {}, onboarded_user, "test")
        assert "נוקתה" in result or "הוסרו" in result

    async def test_clear_already_empty_list(self, onboarded_user):
        from ai.assistant import _execute_tool
        result = await _execute_tool("clear_shopping_list", {}, onboarded_user, "test")
        assert "ריקה" in result


# ---------------------------------------------------------------------------
# _execute_tool — reminders
# ---------------------------------------------------------------------------

class TestExecuteToolReminders:
    """_execute_tool() for reminder operations."""

    async def test_set_reminder_basic(self, onboarded_user):
        from ai.assistant import _execute_tool
        result = await _execute_tool(
            "set_reminder", {"text": "לשתות מים", "minutes": 30}, onboarded_user, "test"
        )
        assert "תזכורת" in result
        assert "30" in result

    async def test_set_reminder_zero_minutes_returns_warning(self, onboarded_user):
        from ai.assistant import _execute_tool
        result = await _execute_tool(
            "set_reminder", {"text": "test", "minutes": 0}, onboarded_user, "test"
        )
        assert "⚠️" in result

    async def test_set_reminder_empty_text_returns_warning(self, onboarded_user):
        from ai.assistant import _execute_tool
        result = await _execute_tool(
            "set_reminder", {"text": "", "minutes": 10}, onboarded_user, "test"
        )
        assert "⚠️" in result

    async def test_set_recurring_reminder(self, onboarded_user):
        from ai.assistant import _execute_tool
        from database.models import get_pending_reminders
        result = await _execute_tool(
            "set_reminder",
            {"text": "לשתות מים", "minutes": 1440, "recurring": True, "recurrence_type": "daily"},
            onboarded_user,
            "test",
        )
        assert "כל יום" in result
        reminders = get_pending_reminders(onboarded_user)
        assert reminders[0].recurring is True

    async def test_set_reminder_with_cross_user_recipient(self, onboarded_user, db):
        """Reminder targeted at another family member sends to their user_id."""
        from ai.assistant import _execute_tool
        from database.models import (
            create_user_profile, get_pending_reminders, set_user_name, set_user_role,
        )
        # Create target family member
        create_user_profile(300)
        set_user_name(300, "שרה")
        set_user_role(300, "אמא")

        result = await _execute_tool(
            "set_reminder",
            {"text": "לקחת תרופות", "minutes": 60, "recipient": "שרה"},
            onboarded_user,
            "test",
        )
        assert "שרה" in result
        # Reminder stored for the recipient, not the caller
        assert len(get_pending_reminders(300)) == 1
        assert len(get_pending_reminders(onboarded_user)) == 0

    async def test_set_reminder_unknown_recipient_returns_warning(self, onboarded_user):
        from ai.assistant import _execute_tool
        result = await _execute_tool(
            "set_reminder",
            {"text": "test", "minutes": 30, "recipient": "אדם_לא_קיים"},
            onboarded_user,
            "test",
        )
        assert "⚠️" in result

    async def test_list_reminders_empty(self, onboarded_user):
        from ai.assistant import _execute_tool
        result = await _execute_tool("list_reminders", {}, onboarded_user, "test")
        assert "אין" in result

    async def test_list_reminders_populated(self, onboarded_user):
        from ai.assistant import _execute_tool
        from database.models import add_reminder
        future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
        add_reminder(onboarded_user, "להתקשר לרופא", future)
        result = await _execute_tool("list_reminders", {}, onboarded_user, "test")
        assert "להתקשר לרופא" in result
        assert "1." in result

    async def test_list_reminders_shows_recurring_flag(self, onboarded_user):
        from ai.assistant import _execute_tool
        from database.models import add_reminder
        future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=2)
        add_reminder(onboarded_user, "כל יום", future, recurring=True, recurrence_type="daily")
        result = await _execute_tool("list_reminders", {}, onboarded_user, "test")
        assert "🔁" in result

    async def test_cancel_reminder(self, onboarded_user):
        from ai.assistant import _execute_tool
        from database.models import add_reminder, get_pending_reminders
        future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
        add_reminder(onboarded_user, "לבטל", future)
        result = await _execute_tool(
            "cancel_reminder", {"reminder_number": 1}, onboarded_user, "test"
        )
        assert "בוטלה" in result
        assert get_pending_reminders(onboarded_user) == []

    async def test_cancel_out_of_range_returns_warning(self, onboarded_user):
        from ai.assistant import _execute_tool
        result = await _execute_tool(
            "cancel_reminder", {"reminder_number": 5}, onboarded_user, "test"
        )
        assert "⚠️" in result

    async def test_unknown_tool_returns_warning(self, onboarded_user):
        from ai.assistant import _execute_tool
        result = await _execute_tool("nonexistent_tool", {}, onboarded_user, "test")
        assert "⚠️" in result


# ---------------------------------------------------------------------------
# Conversation history helpers
# ---------------------------------------------------------------------------

class TestConversationHistory:
    """In-memory history ring-buffer."""

    def test_append_and_retrieve(self):
        from ai.assistant import _append_history, _get_history
        uid = 999001
        _append_history(uid, "user", "שלום")
        _append_history(uid, "assistant", "שלום גם לך")
        history = _get_history(uid)
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"

    def test_history_trimmed_to_max_pairs(self):
        from ai.assistant import _MAX_HISTORY_PAIRS, _append_history, _get_history
        uid = 999002
        max_msgs = _MAX_HISTORY_PAIRS * 2
        # Overfill by 4 messages
        for i in range(max_msgs + 4):
            _append_history(uid, "user", f"msg {i}")
        history = _get_history(uid)
        assert len(history) == max_msgs

    def test_separate_histories_per_user(self):
        from ai.assistant import _append_history, _get_history
        _append_history(999003, "user", "הודעה של א")
        _append_history(999004, "user", "הודעה של ב")
        assert len(_get_history(999003)) == 1
        assert _get_history(999003)[0]["content"] == "הודעה של א"


# ---------------------------------------------------------------------------
# Fallback JSON parser
# ---------------------------------------------------------------------------

class TestParseToolFromContent:
    """_parse_tool_from_content() extracts tool calls from model text."""

    def test_parse_json_blob(self):
        from ai.assistant import _parse_tool_from_content
        content = '{"name": "get_shopping_list", "arguments": {}}'
        result = _parse_tool_from_content(content)
        assert result is not None
        name, args = result
        assert name == "get_shopping_list"

    def test_parse_tool_name_in_text(self):
        from ai.assistant import _parse_tool_from_content
        content = "I will call add_shopping_items to add items."
        result = _parse_tool_from_content(content)
        assert result is not None
        assert result[0] == "add_shopping_items"

    def test_unknown_tool_name_returns_none(self):
        from ai.assistant import _parse_tool_from_content
        content = "I will call nonexistent_function to do stuff."
        assert _parse_tool_from_content(content) is None

    def test_no_tool_in_plain_text_returns_none(self):
        from ai.assistant import _parse_tool_from_content
        content = "שלום! איך אני יכול לעזור?"
        assert _parse_tool_from_content(content) is None
