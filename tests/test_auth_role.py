"""Tests for vorm.auth role caching + sign_up role plumbing.

Multi-tenancy adds two new responsibilities to auth:

1. ``current_user_role()`` returns the signed-in user's role and caches
   the result in session_state to spare the DB on every Streamlit rerun.
2. ``sign_up()`` carries the chosen role into Supabase ``raw_user_meta_data``
   so the first sign-in after email confirmation can bootstrap the
   ``user_roles`` row from metadata, even cross-browser.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from vorm import auth
from vorm.data.models import UserRole

# --- current_user_role caching ----------------------------------------------

def test_current_user_role_returns_none_when_anon(monkeypatch):
    monkeypatch.setattr(auth.st, "session_state", {})
    assert auth.current_user_role() is None


def test_current_user_role_returns_cached_value_without_db_hit(monkeypatch):
    """When ``_ROLE_CACHE_KEY`` is populated, no client/DB is needed."""
    user = auth.AuthUser(
        id="u1", email="x@y.z",
        access_token="at", refresh_token="rt",
    )
    cached = UserRole(role="coach", display_name="Test Coach")
    monkeypatch.setattr(auth.st, "session_state", {
        auth._USER_KEY: user,
        auth._ROLE_CACHE_KEY: cached,
    })

    def _should_not_be_called():
        raise AssertionError(
            "current_user_role() should hit cache, not build a Supabase client"
        )

    monkeypatch.setattr(auth, "_get_client", _should_not_be_called)

    assert auth.current_user_role() == cached


def test_invalidate_role_cache_removes_entry(monkeypatch):
    state = {auth._ROLE_CACHE_KEY: UserRole(role="athlete")}
    monkeypatch.setattr(auth.st, "session_state", state)
    auth.invalidate_role_cache()
    assert auth._ROLE_CACHE_KEY not in state


def test_invalidate_role_cache_is_noop_when_absent(monkeypatch):
    """Calling invalidate without a cached value mustn't crash."""
    state: dict = {}
    monkeypatch.setattr(auth.st, "session_state", state)
    auth.invalidate_role_cache()  # should not raise


# --- read requested_role from metadata --------------------------------------

def test_read_requested_role_from_metadata_returns_coach(monkeypatch):
    """The auth.users metadata may carry ``requested_role`` set at signup."""
    fake_user_obj = SimpleNamespace(
        user_metadata={"requested_role": "coach"},
    )
    fake_resp = SimpleNamespace(user=fake_user_obj)
    fake_client = SimpleNamespace(
        auth=SimpleNamespace(get_user=lambda: fake_resp),
    )
    assert auth._read_requested_role_from_metadata(fake_client) == "coach"


def test_read_requested_role_from_metadata_rejects_unknown_value():
    fake_user_obj = SimpleNamespace(
        user_metadata={"requested_role": "admin"},
    )
    fake_resp = SimpleNamespace(user=fake_user_obj)
    fake_client = SimpleNamespace(
        auth=SimpleNamespace(get_user=lambda: fake_resp),
    )
    assert auth._read_requested_role_from_metadata(fake_client) is None


def test_read_requested_role_from_metadata_handles_missing_user():
    """An unauthenticated call returns a response with ``user=None``."""
    fake_client = SimpleNamespace(
        auth=SimpleNamespace(get_user=lambda: SimpleNamespace(user=None)),
    )
    assert auth._read_requested_role_from_metadata(fake_client) is None


# --- sign_up role passthrough -----------------------------------------------

def test_sign_up_rejects_unknown_role(monkeypatch):
    """Defensive guard: a typo'd role must fail before any network call."""
    captured = []
    monkeypatch.setattr(
        auth, "_get_client",
        lambda: SimpleNamespace(
            auth=SimpleNamespace(sign_up=lambda payload: captured.append(payload)),
        ),
    )
    with pytest.raises(ValueError):
        auth.sign_up("x@y.z", "pw1234", role="admin")
    assert captured == []  # never reached the client


def test_sign_up_passes_role_in_metadata(monkeypatch):
    captured: dict = {}

    def fake_sign_up(payload):
        captured.update(payload)
        return SimpleNamespace(user=None, session=None)

    monkeypatch.setattr(
        auth, "_get_client",
        lambda: SimpleNamespace(auth=SimpleNamespace(sign_up=fake_sign_up)),
    )

    auth.sign_up("athlete@example.com", "secret123", role="coach")

    assert captured["email"] == "athlete@example.com"
    assert captured["password"] == "secret123"
    assert captured["options"] == {
        "data": {"requested_role": "coach", "language": "et"}
    }


def test_sign_up_defaults_to_athlete(monkeypatch):
    """Backwards compat: callers that omit ``role`` shouldn't break."""
    captured: dict = {}

    def fake_sign_up(payload):
        captured.update(payload)
        return SimpleNamespace(user=None, session=None)

    monkeypatch.setattr(
        auth, "_get_client",
        lambda: SimpleNamespace(auth=SimpleNamespace(sign_up=fake_sign_up)),
    )

    auth.sign_up("a@b.c", "secret123")

    assert captured["options"]["data"] == {
        "requested_role": "athlete",
        "language": "et",
    }
