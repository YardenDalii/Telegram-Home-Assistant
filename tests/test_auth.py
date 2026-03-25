"""Tests for the authentication and authorization module (src/auth.py)."""

import pytest
from auth import authenticate_user, is_admin


class TestAuthenticateUser:
    """Tests for ``authenticate_user()``."""

    def test_authorized_user_returns_true(self):
        """Users in AUTHORIZED_USERS list are authenticated."""
        assert authenticate_user(111111111) is True

    def test_second_authorized_user_returns_true(self):
        """All users in the authorized list are accepted."""
        assert authenticate_user(222222222) is True

    def test_unauthorized_user_returns_false(self):
        """Users NOT in the list are rejected."""
        assert authenticate_user(999999999) is False

    def test_unknown_user_returns_false(self):
        """Completely unknown user IDs are rejected."""
        assert authenticate_user(0) is False


class TestIsAdmin:
    """Tests for ``is_admin()``."""

    def test_admin_user_returns_true(self):
        """Users in ADMIN_USERS list have admin privileges."""
        assert is_admin(111111111) is True

    def test_non_admin_authorized_user_returns_false(self):
        """Authorized users NOT in ADMIN_USERS are not admins."""
        assert is_admin(222222222) is False

    def test_unauthorized_user_is_not_admin(self):
        """Users not in the authorized list are never admins."""
        assert is_admin(999999999) is False
