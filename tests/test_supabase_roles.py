"""Tests for SupabaseStore role + invite-link methods.

Exercises the input-validation surface and the row-parsing helpers without
hitting a real Supabase backend. Network-bound integration tests would
require fixtures we don't run in CI; the value here is catching local
regressions in the typed boundaries.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vorm.data.models import (
    DATA_CONSENT_VERSION,
    CoachAthleteLink,
    UserConsent,
    UserRole,
)
from vorm.data.supabase_store import (
    SupabaseStore,
    _row_to_link,
    _row_to_user_consent,
    generate_invite_code,
)

_INVITE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


# --- invite code generator ---------------------------------------------------

def test_generate_invite_code_is_eight_chars_from_safe_alphabet():
    """Invite codes must be 8 chars long and only use the unambiguous alphabet
    (no I/L/O/0/1 — those get misread on the receiving end)."""
    code = generate_invite_code()
    assert len(code) == 8
    assert all(ch in _INVITE_ALPHABET for ch in code), code


def test_generate_invite_code_uses_csprng_so_collisions_are_rare():
    """100 codes from a CSPRNG should be ~all unique (32**8 keyspace)."""
    codes = {generate_invite_code() for _ in range(100)}
    assert len(codes) >= 99


# --- dataclasses -------------------------------------------------------------

def test_user_role_dataclass_defaults():
    role = UserRole(role="athlete")
    assert role.role == "athlete"
    assert role.display_name == ""


def test_user_consent_dataclass_flags():
    consent = UserConsent()
    assert not consent.athlete_processing_ready
    assert not consent.coach_terms_ready


def test_coach_athlete_link_dataclass_construction():
    link = CoachAthleteLink(
        id="link-1",
        coach_user_id="coach-1",
        athlete_user_id=None,
        invite_code="ABCD2345",
        status="pending",
    )
    assert link.status == "pending"
    assert link.athlete_user_id is None
    assert link.accepted_at is None
    assert not link.has_active_data_consent


def test_coach_athlete_link_requires_consent_for_active_access():
    link = CoachAthleteLink(
        id="link-1",
        coach_user_id="coach-1",
        athlete_user_id="athlete-1",
        invite_code="ABCD2345",
        status="active",
    )
    assert not link.has_active_data_consent


# --- _row_to_link ------------------------------------------------------------

def test_row_to_link_parses_active_link_with_timestamps():
    row = {
        "id": "abc",
        "coach_user_id": "c1",
        "athlete_user_id": "a1",
        "invite_code": "XYZ23456",
        "status": "active",
        "created_at": "2026-05-01T10:00:00+00:00",
        "accepted_at": "2026-05-02T11:00:00+00:00",
        "athlete_consent_at": "2026-05-02T11:00:00+00:00",
        "athlete_consent_version": DATA_CONSENT_VERSION,
    }
    link = _row_to_link(row)
    assert link.id == "abc"
    assert link.coach_user_id == "c1"
    assert link.athlete_user_id == "a1"
    assert link.invite_code == "XYZ23456"
    assert link.status == "active"
    assert link.created_at is not None and link.created_at.year == 2026
    assert link.accepted_at is not None and link.accepted_at.day == 2
    assert link.has_active_data_consent
    assert link.athlete_consent_version == DATA_CONSENT_VERSION


def test_row_to_link_handles_missing_optional_fields():
    """Pending invites have NULL athlete_user_id and NULL accepted_at."""
    row = {
        "id": "abc",
        "coach_user_id": "c1",
        "athlete_user_id": None,
        "invite_code": "PENDING2",
        "status": "pending",
        "created_at": None,
        "accepted_at": None,
    }
    link = _row_to_link(row)
    assert link.athlete_user_id is None
    assert link.created_at is None
    assert link.accepted_at is None


def test_row_to_link_handles_z_suffix_timestamps():
    """Postgres can serialize as ``...Z`` instead of ``...+00:00``."""
    row = {
        "id": "x",
        "coach_user_id": "c",
        "athlete_user_id": "a",
        "invite_code": "CODE2345",
        "status": "active",
        "created_at": "2026-05-01T10:00:00Z",
        "accepted_at": None,
    }
    link = _row_to_link(row)
    assert link.created_at is not None
    assert link.created_at.hour == 10


def test_row_to_user_consent_parses_flags():
    consent = _row_to_user_consent({
        "consent_version": DATA_CONSENT_VERSION,
        "sensitive_data_accepted_at": "2026-05-19T10:00:00Z",
        "llm_aggregate_accepted_at": "2026-05-19T10:01:00Z",
        "coach_access_terms_accepted_at": None,
        "updated_at": "2026-05-19T10:02:00Z",
    })
    assert consent.athlete_processing_ready
    assert not consent.coach_terms_ready
    assert consent.updated_at is not None


# --- set_role validation ----------------------------------------------------

def test_set_role_rejects_unknown_role():
    store = SupabaseStore(client=MagicMock(), user_id="u1")
    with pytest.raises(ValueError, match="role must be"):
        store.set_role("admin")


def test_set_role_writes_athlete_payload_to_supabase():
    """Happy path: athlete role with display_name reaches client.table().upsert()."""
    client = MagicMock()
    upsert = client.table.return_value.upsert
    upsert.return_value.execute.return_value = MagicMock(data=[])
    store = SupabaseStore(client=client, user_id="u1")

    role = store.set_role("athlete", "Eesnimi Perekonnanimi")

    assert role.role == "athlete"
    assert role.display_name == "Eesnimi Perekonnanimi"
    client.table.assert_called_with("user_roles")
    payload, _ = upsert.call_args[0], upsert.call_args[1]
    sent = payload[0]
    assert sent == {
        "user_id": "u1",
        "role": "athlete",
        "display_name": "Eesnimi Perekonnanimi",
    }


def test_save_user_consent_writes_acceptance_timestamps(monkeypatch):
    client = MagicMock()
    upsert = client.table.return_value.upsert
    upsert.return_value.execute.return_value = MagicMock(data=[])
    store = SupabaseStore(client=client, user_id="u1")
    monkeypatch.setattr(store, "load_user_consent", lambda: None)

    consent = store.save_user_consent(
        accept_sensitive_data=True,
        accept_llm_aggregate=True,
    )

    assert consent.athlete_processing_ready
    client.table.assert_called_with("user_consents")
    sent = upsert.call_args[0][0]
    assert sent["user_id"] == "u1"
    assert sent["consent_version"] == DATA_CONSENT_VERSION
    assert sent["sensitive_data_accepted_at"] is not None
    assert sent["llm_aggregate_accepted_at"] is not None


# --- accept_invite validation -----------------------------------------------

@pytest.mark.parametrize("bad", ["", "   ", "\n\t"])
def test_accept_invite_rejects_empty_code(bad):
    store = SupabaseStore(client=MagicMock(), user_id="u1")
    with pytest.raises(ValueError, match="Kutsekood"):
        store.accept_invite(bad)


def test_accept_invite_requires_share_consent_before_rpc():
    client = MagicMock()
    store = SupabaseStore(client=client, user_id="athlete-1")

    with pytest.raises(ValueError, match="nõusolekut"):
        store.accept_invite("ABCDEFGH")

    client.rpc.assert_not_called()


def test_accept_invite_raises_lookup_error_when_no_row_matches():
    """No matching pending row → tell the athlete the code is invalid."""
    client = MagicMock()
    client.rpc.return_value.execute.return_value = MagicMock(data=[])  # 0 rows matched
    store = SupabaseStore(client=client, user_id="athlete-1")

    with pytest.raises(LookupError, match="ei kehti"):
        store.accept_invite("BADCODE1", consent_to_share_sensitive_data=True)
    client.rpc.assert_called_once_with(
        "accept_coach_invite",
        {
            "p_invite_code": "BADCODE1",
            "p_athlete_consent": True,
            "p_consent_version": DATA_CONSENT_VERSION,
        },
    )


def test_accept_invite_uppercases_input_before_lookup():
    """Codes are stored in uppercase; lowercase input shouldn't miss them."""
    client = MagicMock()
    client.rpc.return_value.execute.return_value = MagicMock(data=[{
        "id": "link-1",
        "coach_user_id": "coach-1",
        "athlete_user_id": "athlete-1",
        "invite_code": "ABCDEFGH",
        "status": "active",
        "created_at": "2026-05-01T10:00:00Z",
        "accepted_at": "2026-05-01T10:00:00Z",
        "athlete_consent_at": "2026-05-01T10:00:00Z",
        "athlete_consent_version": DATA_CONSENT_VERSION,
    }])
    store = SupabaseStore(client=client, user_id="athlete-1")

    link = store.accept_invite(
        "  abcdefgh  ",
        consent_to_share_sensitive_data=True,
    )

    assert link.status == "active"
    assert link.has_active_data_consent
    client.rpc.assert_called_once_with(
        "accept_coach_invite",
        {
            "p_invite_code": "ABCDEFGH",
            "p_athlete_consent": True,
            "p_consent_version": DATA_CONSENT_VERSION,
        },
    )


def test_accept_invite_explains_missing_schema_rpc():
    client = MagicMock()
    client.rpc.return_value.execute.side_effect = Exception(
        "Could not find the function public.accept_coach_invite"
    )
    store = SupabaseStore(client=client, user_id="athlete-1")

    with pytest.raises(RuntimeError, match="Supabase skeem vajab uuendamist"):
        store.accept_invite("ABCDEFGH", consent_to_share_sensitive_data=True)


def test_grant_link_consent_calls_rpc():
    client = MagicMock()
    client.rpc.return_value.execute.return_value = MagicMock(data=[{
        "id": "link-1",
        "coach_user_id": "coach-1",
        "athlete_user_id": "athlete-1",
        "invite_code": "ABCDEFGH",
        "status": "active",
        "created_at": "2026-05-01T10:00:00Z",
        "accepted_at": "2026-05-01T10:00:00Z",
        "athlete_consent_at": "2026-05-19T10:00:00Z",
        "athlete_consent_version": DATA_CONSENT_VERSION,
    }])
    store = SupabaseStore(client=client, user_id="athlete-1")

    link = store.grant_link_consent("link-1")

    assert link.has_active_data_consent
    client.rpc.assert_called_once_with(
        "grant_coach_link_consent",
        {
            "p_link_id": "link-1",
            "p_athlete_consent": True,
            "p_consent_version": DATA_CONSENT_VERSION,
        },
    )


def test_accept_invite_has_schema_rpc_without_pending_select_policy():
    """The SQL schema should claim invites by RPC, not by exposing all pending codes."""
    schema = (
        Path(__file__).resolve().parents[1] / "docs" / "supabase_schema.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE OR REPLACE FUNCTION private.accept_coach_invite" in schema
    assert "CREATE OR REPLACE FUNCTION public.accept_coach_invite" in schema
    assert "p_athlete_consent BOOLEAN DEFAULT false" in schema
    assert "athlete_consent_at IS NOT NULL" in schema
    assert "CREATE OR REPLACE FUNCTION private.grant_coach_link_consent" in schema
    assert 'CREATE POLICY "Links select pending by code"' not in schema
    assert 'CREATE POLICY "Links accept by athlete"' not in schema
