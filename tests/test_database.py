"""Unit tests for all database CRUD helpers.

Covers ShoppingItem, Reminder (including recurrence), and UserProfile.
Every test uses the `db` fixture for a fresh in-memory SQLite database.
"""

from datetime import datetime, timedelta

import pytest

USER_A = 111111111
USER_B = 222222222


# ---------------------------------------------------------------------------
# Shopping list
# ---------------------------------------------------------------------------

class TestShoppingList:
    """add / get / update / remove / clear helpers."""

    def test_add_item_returns_object(self, db):
        from database.models import add_shopping_item
        item = add_shopping_item("חלב", USER_A, "testuser")
        assert item is not None
        assert item.id is not None
        assert item.name == "חלב"
        assert item.added_by_id == USER_A

    def test_get_items_returns_all_in_insertion_order(self, db):
        from database.models import add_shopping_item, get_shopping_items
        add_shopping_item("ביצים", USER_A)
        add_shopping_item("לחם", USER_A)
        add_shopping_item("חמאה", USER_A)
        items = get_shopping_items()
        assert len(items) == 3
        assert [i.name for i in items] == ["ביצים", "לחם", "חמאה"]

    def test_get_items_empty_list(self, db):
        from database.models import get_shopping_items
        assert get_shopping_items() == []

    def test_update_item_renames_correctly(self, db):
        from database.models import add_shopping_item, get_shopping_items, update_shopping_item
        item = add_shopping_item("חלב 1%", USER_A)
        result = update_shopping_item(item.id, "חלב 3%")
        assert result is True
        items = get_shopping_items()
        assert items[0].name == "חלב 3%"

    def test_update_nonexistent_item_returns_false(self, db):
        from database.models import update_shopping_item
        assert update_shopping_item(99999, "anything") is False

    def test_remove_item_deletes_it(self, db):
        from database.models import add_shopping_item, get_shopping_items, remove_shopping_item
        item = add_shopping_item("גבינה", USER_A)
        assert remove_shopping_item(item.id) is True
        assert get_shopping_items() == []

    def test_remove_nonexistent_item_returns_false(self, db):
        from database.models import remove_shopping_item
        assert remove_shopping_item(99999) is False

    def test_clear_shopping_list_returns_count(self, db):
        from database.models import add_shopping_item, clear_shopping_list, get_shopping_items
        add_shopping_item("א", USER_A)
        add_shopping_item("ב", USER_A)
        add_shopping_item("ג", USER_A)
        count = clear_shopping_list()
        assert count == 3
        assert get_shopping_items() == []

    def test_clear_empty_list_returns_zero(self, db):
        from database.models import clear_shopping_list
        assert clear_shopping_list() == 0

    def test_multiple_users_share_list(self, db):
        from database.models import add_shopping_item, get_shopping_items
        add_shopping_item("אפרסמון", USER_A)
        add_shopping_item("תפוח", USER_B)
        items = get_shopping_items()
        assert len(items) == 2


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------

class TestReminders:
    """add / get_pending / mark_fired / cancel / recurrence helpers."""

    def _future(self, minutes: int = 30) -> datetime:
        return datetime.utcnow() + timedelta(minutes=minutes)

    def test_add_reminder_returns_object(self, db):
        from database.models import add_reminder
        r = add_reminder(USER_A, "לשתות מים", self._future())
        assert r is not None
        assert r.id is not None
        assert r.text == "לשתות מים"
        assert r.fired is False

    def test_get_pending_only_returns_unfired(self, db):
        from database.models import add_reminder, get_pending_reminders, mark_reminder_fired
        r1 = add_reminder(USER_A, "בעוד 30", self._future(30))
        r2 = add_reminder(USER_A, "בעוד 60", self._future(60))
        mark_reminder_fired(r1.id)
        pending = get_pending_reminders(USER_A)
        assert len(pending) == 1
        assert pending[0].id == r2.id

    def test_get_pending_ordered_soonest_first(self, db):
        from database.models import add_reminder, get_pending_reminders
        add_reminder(USER_A, "שלישי", self._future(90))
        add_reminder(USER_A, "ראשון", self._future(10))
        add_reminder(USER_A, "שני", self._future(30))
        pending = get_pending_reminders(USER_A)
        assert [r.text for r in pending] == ["ראשון", "שני", "שלישי"]

    def test_get_pending_scoped_to_user(self, db):
        from database.models import add_reminder, get_pending_reminders
        add_reminder(USER_A, "של א", self._future())
        add_reminder(USER_B, "של ב", self._future())
        assert len(get_pending_reminders(USER_A)) == 1
        assert len(get_pending_reminders(USER_B)) == 1

    def test_get_all_pending_returns_all_users(self, db):
        from database.models import add_reminder, get_all_pending_reminders
        add_reminder(USER_A, "א", self._future())
        add_reminder(USER_B, "ב", self._future())
        assert len(get_all_pending_reminders()) == 2

    def test_mark_reminder_fired_sets_flag(self, db):
        from database.models import add_reminder, get_pending_reminders, mark_reminder_fired
        r = add_reminder(USER_A, "test", self._future())
        mark_reminder_fired(r.id)
        assert get_pending_reminders(USER_A) == []

    def test_recurring_reminder_creates_next_row(self, db):
        """mark_reminder_fired() on a daily reminder should insert a new row."""
        from database.models import add_reminder, get_all_pending_reminders, mark_reminder_fired
        remind_at = self._future(1440)  # 1 day from now
        r = add_reminder(USER_A, "כל יום", remind_at, recurring=True, recurrence_type="daily")
        mark_reminder_fired(r.id)
        pending = get_all_pending_reminders()
        assert len(pending) == 1
        # Next occurrence should be ~2 days from now (not 1 day)
        expected_next = remind_at + timedelta(days=1)
        diff = abs((pending[0].remind_at - expected_next).total_seconds())
        assert diff < 5, f"Next occurrence off by {diff}s"

    def test_non_recurring_reminder_no_next_row(self, db):
        from database.models import add_reminder, get_all_pending_reminders, mark_reminder_fired
        r = add_reminder(USER_A, "חד פעמי", self._future())
        mark_reminder_fired(r.id)
        assert get_all_pending_reminders() == []

    def test_cancel_reminder_deletes_row(self, db):
        from database.models import add_reminder, cancel_reminder, get_pending_reminders
        r = add_reminder(USER_A, "לבטל", self._future())
        assert cancel_reminder(r.id) is True
        assert get_pending_reminders(USER_A) == []

    def test_cancel_nonexistent_returns_false(self, db):
        from database.models import cancel_reminder
        assert cancel_reminder(99999) is False

    def test_recurring_reminder_is_stored(self, db):
        from database.models import add_reminder, get_pending_reminders
        r = add_reminder(USER_A, "כל שבוע", self._future(), recurring=True, recurrence_type="weekly")
        pending = get_pending_reminders(USER_A)
        assert pending[0].recurring is True
        assert pending[0].recurrence_type == "weekly"


class TestNextOccurrence:
    """_next_occurrence() helper — pure logic, no DB needed."""

    def _base(self):
        return datetime(2026, 3, 5, 10, 0, 0)

    def test_daily(self):
        from database.models import _next_occurrence
        result = _next_occurrence(self._base(), "daily")
        assert result == datetime(2026, 3, 6, 10, 0, 0)

    def test_weekly(self):
        from database.models import _next_occurrence
        result = _next_occurrence(self._base(), "weekly")
        assert result == datetime(2026, 3, 12, 10, 0, 0)

    def test_monthly(self):
        from database.models import _next_occurrence
        result = _next_occurrence(self._base(), "monthly")
        assert result == datetime(2026, 4, 5, 10, 0, 0)

    def test_monthly_year_rollover(self):
        from database.models import _next_occurrence
        dt = datetime(2026, 12, 15, 8, 0, 0)
        result = _next_occurrence(dt, "monthly")
        assert result == datetime(2027, 1, 15, 8, 0, 0)

    def test_yearly(self):
        from database.models import _next_occurrence
        result = _next_occurrence(self._base(), "yearly")
        assert result == datetime(2027, 3, 5, 10, 0, 0)

    def test_unknown_type_returns_none(self):
        from database.models import _next_occurrence
        assert _next_occurrence(self._base(), "hourly") is None


# ---------------------------------------------------------------------------
# User profile
# ---------------------------------------------------------------------------

class TestUserProfile:
    """create / set_name / set_role / mark_onboarding / get_all helpers."""

    def test_create_profile_returns_object(self, db):
        from database.models import create_user_profile
        p = create_user_profile(USER_A)
        assert p is not None
        assert p.user_id == USER_A
        assert p.display_name is None
        assert p.role is None

    def test_get_profile_after_create(self, db):
        from database.models import create_user_profile, get_user_profile
        create_user_profile(USER_A)
        p = get_user_profile(USER_A)
        assert p is not None
        assert p.user_id == USER_A

    def test_get_nonexistent_profile_returns_none(self, db):
        from database.models import get_user_profile
        assert get_user_profile(99999) is None

    def test_set_user_name(self, db):
        from database.models import create_user_profile, get_user_profile, set_user_name
        create_user_profile(USER_A)
        set_user_name(USER_A, "שרה")
        p = get_user_profile(USER_A)
        assert p.display_name == "שרה"

    def test_set_user_name_nonexistent_returns_false(self, db):
        from database.models import set_user_name
        assert set_user_name(99999, "אף אחד") is False

    def test_set_user_role_and_sets_onboarded_at(self, db):
        from database.models import create_user_profile, get_user_profile, set_user_role
        create_user_profile(USER_A)
        set_user_role(USER_A, "אמא")
        p = get_user_profile(USER_A)
        assert p.role == "אמא"
        assert p.onboarded_at is not None

    def test_mark_calendar_onboarding_done(self, db):
        from database.models import (
            create_user_profile, get_user_profile, mark_calendar_onboarding_done,
        )
        create_user_profile(USER_A)
        mark_calendar_onboarding_done(USER_A)
        p = get_user_profile(USER_A)
        assert p.calendar_onboarding_done is True

    def test_get_all_profiles_only_returns_fully_onboarded(self, db):
        """get_all_user_profiles() filters out partially registered users."""
        from database.models import (
            create_user_profile, get_all_user_profiles,
            set_user_name, set_user_role,
        )
        # USER_A: fully onboarded
        create_user_profile(USER_A)
        set_user_name(USER_A, "ישראל")
        set_user_role(USER_A, "אבא")
        # USER_B: only name set (incomplete)
        create_user_profile(USER_B)
        set_user_name(USER_B, "שרה")

        profiles = get_all_user_profiles()
        ids = [p.user_id for p in profiles]
        assert USER_A in ids
        assert USER_B not in ids

    def test_set_icloud_credentials(self, db):
        from database.models import create_user_profile, get_user_profile, set_icloud_credentials
        create_user_profile(USER_A)
        result = set_icloud_credentials(USER_A, "user@icloud.com", "xxxx-xxxx")
        assert result is True
        p = get_user_profile(USER_A)
        assert p.icloud_username == "user@icloud.com"
        assert p.icloud_app_password == "xxxx-xxxx"

    def test_set_briefing_time(self, db):
        from database.models import create_user_profile, get_user_profile, set_briefing_time
        create_user_profile(USER_A)
        set_briefing_time(USER_A, 7, 30)
        p = get_user_profile(USER_A)
        assert p.briefing_hour == 7
        assert p.briefing_minute == 30

    def test_clear_briefing_time(self, db):
        from database.models import (
            clear_briefing_time, create_user_profile, get_user_profile, set_briefing_time,
        )
        create_user_profile(USER_A)
        set_briefing_time(USER_A, 7, 0)
        clear_briefing_time(USER_A)
        p = get_user_profile(USER_A)
        assert p.briefing_hour is None
        assert p.briefing_minute is None
