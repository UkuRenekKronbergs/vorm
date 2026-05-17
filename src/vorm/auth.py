"""Streamlit auth helpers backed by Supabase Auth (email + password).

Flow:
1. **Sign up** → user enters email + password. Supabase sends a confirm-email
   link (requires *Confirm email* ON in Supabase Auth settings — the default).
   User clicks the link once → account is confirmed.
2. **Sign in** → user enters email + password. Returns a Session that we cache
   in ``st.session_state`` and remember server-side for this browser.
3. **Forgot password** → user requests a recovery email, opens the Supabase
   link, and sets a new password inside this Streamlit app.

Refresh-survival uses a server-side session registry keyed by an opaque random
token attached as a URL query parameter (``?s=<token>``). The URL survives
browser refresh without any JS/cookie bridge — ``st.query_params`` reads and
writes synchronously, so there's no flash-of-login on reload. Only the lookup
key lives in the URL; Supabase tokens stay server-side.

Trade-off: the token is visible in the address bar, so anyone who copies the
URL gets the session. The registry is process-local: server restart or redeploy
still requires re-signing-in. Both are acceptable for the course-project demo;
they would NOT be acceptable for a production multi-user app.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from threading import RLock
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import streamlit as st

from .config import load_config
from .data.models import UserRole
from .data.supabase_store import SupabaseNotConfigured, SupabaseStore

if TYPE_CHECKING:
    from supabase import Client


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str
    access_token: str
    refresh_token: str


_CLIENT_KEY = "_vorm_supabase_client"
_USER_KEY = "_vorm_auth_user"
_ROLE_CACHE_KEY = "_vorm_auth_user_role"
_PENDING_CONFIRM_KEY = "_vorm_auth_pending_confirm_email"
_PASSWORD_RECOVERY_KEY = "_vorm_password_recovery_active"
_PASSWORD_RESET_DONE_KEY = "_vorm_password_reset_done"
_GUEST_KEY = "_vorm_guest_mode"
_SESSION_QUERY_KEY = "s"  # opaque session token in the URL, lookup key for the registry
_PASSWORD_RESET_FLOW = "password_reset"
_AUTH_QUERY_KEYS = (
    "access_token",
    "auth_flow",
    "code",
    "error",
    "error_code",
    "error_description",
    "expires_at",
    "expires_in",
    "refresh_token",
    "token_hash",
    "token_type",
    "type",
)
_PERSIST_TTL_SECONDS = 60 * 60 * 24 * 14
_DEFAULT_AUTH_EMAIL_LANGUAGE = "et"


@dataclass(frozen=True)
class _PersistedSession:
    kind: str  # "user" | "guest"
    user: AuthUser | None
    updated_at: float


@st.cache_resource
def _persistent_sessions() -> dict:
    """Process-local auth registry shared across Streamlit reruns/sessions."""
    return {"lock": RLock(), "sessions": {}}


def _is_valid_session_id(value: str | None) -> bool:
    if not value or not (24 <= len(value) <= 128):
        return False
    return all(ch.isalnum() or ch in "-_" for ch in value)


def _read_session_token() -> str | None:
    """Read the opaque session token from ``?s=<token>`` in the URL."""
    try:
        raw = st.query_params.get(_SESSION_QUERY_KEY)
    except Exception:
        return None
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if raw is None:
        return None
    token = str(raw)
    return token if _is_valid_session_id(token) else None


def _write_session_token(token: str) -> None:
    """Persist the opaque session token into the URL.

    No-op if the URL already carries this exact value — avoids triggering an
    extra Streamlit rerun just to write the same string back.
    """
    if _read_session_token() == token:
        return
    try:
        st.query_params[_SESSION_QUERY_KEY] = token
    except Exception:
        pass


def _clear_session_token() -> None:
    try:
        if _SESSION_QUERY_KEY in st.query_params:
            del st.query_params[_SESSION_QUERY_KEY]
    except Exception:
        pass


def _prune_persistent_sessions(sessions: dict[str, _PersistedSession]) -> None:
    cutoff = time.time() - _PERSIST_TTL_SECONDS
    for key, value in list(sessions.items()):
        if value.updated_at < cutoff:
            sessions.pop(key, None)


def _remember_persistent_session(kind: str, user: AuthUser | None = None) -> None:
    """Register a session in the server-side registry and mirror its token
    into the URL so the browser ships it back after refresh.

    Reuses the existing URL token when present; only mints a fresh one for
    brand-new sessions, so navigation within an authenticated session stays
    stable.
    """
    token = _read_session_token() or secrets.token_urlsafe(32)
    registry = _persistent_sessions()
    with registry["lock"]:
        sessions = registry["sessions"]
        _prune_persistent_sessions(sessions)
        sessions[token] = _PersistedSession(
            kind=kind, user=user, updated_at=time.time()
        )
    _write_session_token(token)


def _forget_persistent_session() -> None:
    token = _read_session_token()
    if token:
        registry = _persistent_sessions()
        with registry["lock"]:
            registry["sessions"].pop(token, None)
    _clear_session_token()


def _load_persistent_session() -> _PersistedSession | None:
    token = _read_session_token()
    if not token:
        return None
    registry = _persistent_sessions()
    with registry["lock"]:
        sessions = registry["sessions"]
        _prune_persistent_sessions(sessions)
        persisted = sessions.get(token)
        if persisted is not None:
            # Bump TTL so live sessions don't get pruned out from under us.
            sessions[token] = _PersistedSession(
                kind=persisted.kind,
                user=persisted.user,
                updated_at=time.time(),
            )
        return persisted


def _query_param(name: str) -> str | None:
    try:
        value = st.query_params.get(name)
    except Exception:
        return None
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return None
    return str(value)


def _clear_auth_query_params() -> None:
    try:
        remaining = dict(st.query_params)
        for key in _AUTH_QUERY_KEYS:
            remaining.pop(key, None)
        st.query_params.clear()
        for key, value in remaining.items():
            st.query_params[key] = value
    except Exception:
        pass


def _password_reset_redirect_url() -> str | None:
    """Current Streamlit URL with a marker so recovery links are unambiguous."""
    try:
        raw_url = st.context.url
    except Exception:
        return None
    if not raw_url:
        return None

    parts = urlsplit(str(raw_url))
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["auth_flow"] = _PASSWORD_RESET_FLOW
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _surface_auth_hash_params() -> None:
    """Expose Supabase implicit-flow recovery fragments to Streamlit.

    Streamlit's Python side cannot read URL fragments, but some Supabase
    recovery links return tokens after ``#``. This tiny client-side bridge
    converts only auth-related recovery fragments into query params, and the
    Python code clears them as soon as it consumes the session.
    """
    # `st.iframe` auto-detects raw HTML (no scheme / path prefix) and is the
    # Streamlit 1.57+ replacement for the deprecated `components.html`.
    st.iframe(
        """
<script>
(() => {
  try {
    const parentUrl = new URL(window.parent.location.href);
    if (!parentUrl.hash || parentUrl.hash.length <= 1) return;

    const hashParams = new URLSearchParams(parentUrl.hash.slice(1));
    const hasResetMarker = parentUrl.searchParams.get("auth_flow") === "password_reset";
    const isRecovery =
      hasResetMarker ||
      parentUrl.searchParams.get("type") === "recovery" ||
      hashParams.get("type") === "recovery";
    if (!isRecovery) return;

    const keys = [
      "access_token",
      "error",
      "error_code",
      "error_description",
      "expires_at",
      "expires_in",
      "refresh_token",
      "token_hash",
      "token_type",
      "type",
    ];
    parentUrl.searchParams.set("auth_flow", "password_reset");
    for (const key of keys) {
      if (hashParams.has(key)) parentUrl.searchParams.set(key, hashParams.get(key));
    }
    parentUrl.hash = "";
    window.parent.location.replace(parentUrl.toString());
  } catch (_) {}
})();
</script>
        """,
        # `st.iframe` rejects height=0 (must be a positive int, "content", or
        # "stretch"). 1 px is the smallest legal value and keeps the bridge
        # effectively invisible.
        height=1,
    )


def _build_client() -> Client:
    cfg = load_config()
    if not (cfg.supabase_url and cfg.supabase_anon_key):
        raise SupabaseNotConfigured(
            "Supabase pole seadistatud (SUPABASE_URL + SUPABASE_ANON_KEY puudu)."
        )
    try:
        from supabase import create_client  # noqa: PLC0415
    except ImportError as exc:
        raise SupabaseNotConfigured(
            "Supabase Python klient pole installitud. Lisa requirements.txt-i 'supabase>=2.0' "
            "ja jooksuta `pip install -r requirements.txt`."
        ) from exc
    return create_client(cfg.supabase_url, cfg.supabase_anon_key)


def _get_client() -> Client:
    """One client per Streamlit user session, cached in session_state.

    We don't use ``@st.cache_resource`` because that shares across all users;
    the supabase-py client holds auth state internally and sharing it would
    leak sessions between users.
    """
    client = st.session_state.get(_CLIENT_KEY)
    if client is None:
        client = _build_client()
        st.session_state[_CLIENT_KEY] = client
    return client


def current_user() -> AuthUser | None:
    return st.session_state.get(_USER_KEY)


def is_authenticated() -> bool:
    return current_user() is not None


def is_guest() -> bool:
    """True when the user picked 'continue as guest' on the login gate.

    Guests bypass the login but their data goes to local SQLite — same code
    path as anonymous mode (no Supabase configured at all). Nothing they
    enter touches the cloud, so reruns within the session persist but
    deploys / hard-refreshes lose state.
    """
    return bool(st.session_state.get(_GUEST_KEY))


def enter_guest_mode() -> None:
    st.session_state[_GUEST_KEY] = True
    _remember_persistent_session("guest")


def exit_guest_mode() -> None:
    st.session_state.pop(_GUEST_KEY, None)
    _forget_persistent_session()


def _bind_session(client: Client, user: AuthUser) -> None:
    """Restore the user's JWT on the client so PostgREST requests pass RLS.

    The client persists auth state in memory by default, but Streamlit may
    reconstruct the client on a rerun if session_state was cleared — so we
    re-bind defensively. Catches errors silently because the next API call
    will raise the real error if the session is genuinely invalid.
    """
    try:
        client.auth.set_session(user.access_token, user.refresh_token)
    except Exception:
        pass


def _user_from_auth_response(resp, *, fallback_email: str = "") -> AuthUser:
    session = getattr(resp, "session", None)
    user = getattr(resp, "user", None)
    if not session or not user:
        raise RuntimeError("Sisselogimise sessiooni ei õnnestunud taastada.")
    return AuthUser(
        id=user.id,
        email=user.email or fallback_email,
        access_token=session.access_token,
        refresh_token=session.refresh_token,
    )


def _user_from_session(session, *, fallback_email: str = "") -> AuthUser:
    user = getattr(session, "user", None)
    if not session or not user:
        raise RuntimeError("Sisselogimise sessiooni ei õnnestunud taastada.")
    return AuthUser(
        id=user.id,
        email=user.email or fallback_email,
        access_token=session.access_token,
        refresh_token=session.refresh_token,
    )


def _store_current_user(user: AuthUser, *, remember: bool = True) -> None:
    st.session_state.pop(_GUEST_KEY, None)
    st.session_state[_USER_KEY] = user
    if remember:
        _remember_persistent_session("user", user)
    else:
        _forget_persistent_session()


def _refresh_user_session(client: Client, user: AuthUser) -> AuthUser:
    """Refresh Supabase tokens from the persisted refresh token."""
    resp = client.auth.refresh_session(user.refresh_token)
    return _user_from_auth_response(resp, fallback_email=user.email)


def _restore_persistent_session() -> AuthUser | None:
    """Restore auth after a browser refresh, if this browser was remembered."""
    if current_user():
        return current_user()
    if is_guest():
        return None

    persisted = _load_persistent_session()
    if persisted is None:
        return None
    if persisted.kind == "guest":
        st.session_state[_GUEST_KEY] = True
        return None
    if persisted.kind != "user" or persisted.user is None:
        _forget_persistent_session()
        return None

    client = _get_client()
    try:
        user = _refresh_user_session(client, persisted.user)
    except Exception:
        _forget_persistent_session()
        return None
    _store_current_user(user)
    return user


def sign_up(email: str, password: str, role: str = "athlete") -> bool:
    """Create a new account. Supabase sends a confirm-email link.

    The chosen ``role`` (``"athlete"`` or ``"coach"``) is stored in Supabase
    ``raw_user_meta_data`` so the *first* sign-in after email-confirmation
    can bootstrap the ``user_roles`` row — even if confirmation happens in
    a different browser session.

    Does NOT sign the user in. Returns True on success; raises on auth API
    errors (existing user, weak password, network).
    """
    if role not in ("athlete", "coach"):
        raise ValueError(f"role must be 'athlete' or 'coach', got {role!r}")
    client = _get_client()
    client.auth.sign_up({
        "email": email,
        "password": password,
        "options": {
            "data": {
                "requested_role": role,
                "language": _DEFAULT_AUTH_EMAIL_LANGUAGE,
            }
        },
    })
    return True


def sign_in(email: str, password: str) -> AuthUser:
    """Sign in with existing credentials. Stashes the session in state."""
    client = _get_client()
    resp = client.auth.sign_in_with_password(
        {"email": email, "password": password}
    )
    user = _user_from_auth_response(resp, fallback_email=email)
    _store_current_user(user)
    return user


def request_password_reset(email: str) -> None:
    """Send Supabase password recovery email for an existing account."""
    client = _get_client()
    redirect_url = _password_reset_redirect_url()
    options = {"redirect_to": redirect_url} if redirect_url else None
    client.auth.reset_password_for_email(email, options)


def update_password(new_password: str) -> AuthUser:
    """Update the password for the recovery session and keep the user signed in."""
    user = current_user()
    if not user:
        raise RuntimeError("Parooli muutmise sessioon puudub. Ava taastamislink uuesti.")

    client = _get_client()
    _bind_session(client, user)
    client.auth.update_user({"password": new_password})

    updated_user = user
    try:
        session = client.auth.get_session()
    except Exception:
        session = None
    if session:
        updated_user = _user_from_session(session, fallback_email=user.email)

    _store_current_user(updated_user)
    return updated_user


def _is_password_recovery_query() -> bool:
    return (
        _query_param("auth_flow") == _PASSWORD_RESET_FLOW
        or _query_param("type") == "recovery"
    )


def _consume_password_recovery_from_url() -> AuthUser | None:
    if not _is_password_recovery_query():
        return None

    error = _query_param("error_description") or _query_param("error")
    if error:
        st.error(_humanize_auth_error(RuntimeError(error)))
        _clear_auth_query_params()
        return None

    code = _query_param("code")
    token_hash = _query_param("token_hash")
    access_token = _query_param("access_token")
    refresh_token = _query_param("refresh_token")
    if not any((code, token_hash, access_token and refresh_token)):
        if (
            _query_param("auth_flow") == _PASSWORD_RESET_FLOW
            or _query_param("type") == "recovery"
        ):
            return None
        st.error(
            "Taastamislink ei sisaldanud kehtivat sessioonikoodi. "
            "Küsi uus link ja proovi uuesti."
        )
        _clear_auth_query_params()
        return None

    try:
        client = _get_client()
        if access_token and refresh_token:
            resp = client.auth.set_session(access_token, refresh_token)
        elif token_hash:
            resp = client.auth.verify_otp(
                {"token_hash": token_hash, "type": "recovery"}
            )
        else:
            resp = client.auth.exchange_code_for_session({"auth_code": code})
        user = _user_from_auth_response(resp)
    except SupabaseNotConfigured as exc:
        st.error(str(exc))
        return None
    except Exception as exc:
        st.error(_humanize_auth_error(exc))
        _clear_auth_query_params()
        return None

    _store_current_user(user, remember=False)
    st.session_state[_PASSWORD_RECOVERY_KEY] = True
    st.session_state.pop(_PENDING_CONFIRM_KEY, None)
    _clear_auth_query_params()
    return user


def sign_out() -> None:
    _forget_persistent_session()
    client = st.session_state.get(_CLIENT_KEY)
    if client is not None:
        try:
            client.auth.sign_out()
        except Exception:
            # Local-only sign-out is fine even if the remote call fails (e.g.
            # offline) — clearing session_state below is what matters here.
            pass
    for key in (
        _USER_KEY,
        _ROLE_CACHE_KEY,
        _PENDING_CONFIRM_KEY,
        _PASSWORD_RECOVERY_KEY,
        _PASSWORD_RESET_DONE_KEY,
        _CLIENT_KEY,
    ):
        st.session_state.pop(key, None)


def get_store() -> SupabaseStore | None:
    """SupabaseStore for the signed-in user, or None if not authenticated.

    Re-binds the session on every call so RLS-protected reads/writes succeed
    even after a Streamlit script rerun.
    """
    user = current_user()
    if not user:
        return None
    client = _get_client()
    _bind_session(client, user)
    return SupabaseStore(client=client, user_id=user.id)


def get_store_for(target_user_id: str) -> SupabaseStore | None:
    """Coach-mode store: act on a *different* user's rows under the current JWT.

    The bound JWT is still the coach's — RLS lets the coach read the linked
    athlete's profile/daily_logs and read+write coach_decisions where
    ``user_id == target_user_id``. Construct with the *athlete's* user_id so
    queries naturally target their rows.
    """
    user = current_user()
    if not user:
        return None
    client = _get_client()
    _bind_session(client, user)
    return SupabaseStore(client=client, user_id=target_user_id)


def current_user_role() -> UserRole | None:
    """Resolve the signed-in user's role, bootstrapping it on first sign-in.

    Cached in ``st.session_state`` to avoid hitting the DB on every rerun.
    When the ``user_roles`` row is missing (very first sign-in after
    confirmation), reads ``raw_user_meta_data.requested_role`` from the
    Supabase user and writes the row with that value — falling back to
    ``"athlete"`` if the signup metadata is missing.
    """
    user = current_user()
    if not user:
        return None
    cached = st.session_state.get(_ROLE_CACHE_KEY)
    if isinstance(cached, UserRole):
        return cached

    client = _get_client()
    _bind_session(client, user)
    store = SupabaseStore(client=client, user_id=user.id)
    try:
        role = store.get_role()
    except Exception:
        return None
    if role is None:
        requested = _read_requested_role_from_metadata(client) or "athlete"
        try:
            role = store.set_role(requested)
        except Exception:
            return None
    st.session_state[_ROLE_CACHE_KEY] = role
    return role


def _read_requested_role_from_metadata(client: Client) -> str | None:
    """Read ``requested_role`` from Supabase user metadata, if any."""
    try:
        resp = client.auth.get_user()
    except Exception:
        return None
    auth_user_obj = getattr(resp, "user", None)
    if auth_user_obj is None:
        return None
    meta = getattr(auth_user_obj, "user_metadata", None) or {}
    if not isinstance(meta, dict):
        return None
    value = meta.get("requested_role")
    if value in ("athlete", "coach"):
        return value
    return None


def invalidate_role_cache() -> None:
    """Drop the cached role; next ``current_user_role()`` re-fetches it.

    Call after the coach sets / changes their ``display_name`` so the new
    value is visible in the same session.
    """
    st.session_state.pop(_ROLE_CACHE_KEY, None)


def _humanize_auth_error(exc: Exception) -> str:
    """Translate Supabase auth errors into Estonian one-liners.

    Supabase returns these as ``AuthApiError`` with a ``message`` attribute;
    we match on substrings because the structured error codes differ across
    supabase-py versions.
    """
    msg = str(exc).lower()
    if "invalid login credentials" in msg or "invalid_credentials" in msg:
        return "Vale email või parool."
    if "email not confirmed" in msg or "email_not_confirmed" in msg:
        return (
            "Email pole veel kinnitatud. Kontrolli postkasti — saatsime "
            "esmasel registreerumisel kinnitusmaili. Klikka seal lingile "
            "ja proovi seejärel uuesti."
        )
    if "user already registered" in msg or "already_exists" in msg:
        return "See email on juba registreeritud. Logi sisse 'Logi sisse' tabist."
    if "password" in msg and ("short" in msg or "weak" in msg or "6 char" in msg):
        return "Parool on liiga lühike — peab olema vähemalt 6 märki."
    if "expired" in msg or "otp_expired" in msg or "invalid token" in msg:
        return "Parooli taastamise link ei kehti enam. Küsi uus link ja proovi uuesti."
    if "session" in msg and ("missing" in msg or "puudub" in msg):
        return "Parooli muutmise sessioon puudub. Ava taastamislink uuesti."
    if "rate limit" in msg or "429" in msg:
        return "Liiga palju katseid. Oota minut ja proovi uuesti."
    return f"Tõrge: {exc}"


def _render_password_recovery_form() -> AuthUser | None:
    user = current_user()
    st.title("🏃 Vorm.ai")
    st.markdown("### 🔑 Määra uus parool")

    if not user:
        st.error("Parooli muutmise sessioon puudub. Ava taastamislink uuesti.")
        if st.button(
            "Tagasi sisselogimise juurde",
            key="_vorm_recovery_back_to_login",
            width="stretch",
        ):
            st.session_state.pop(_PASSWORD_RECOVERY_KEY, None)
            st.rerun()
        return None

    st.info(
        f"Taastad parooli kontole **{user.email}**. "
        "Pärast salvestamist jääd sisse logituks."
    )
    with st.form("vorm_password_recovery_form"):
        new_password = st.text_input(
            "Uus parool",
            type="password",
            key="_vorm_recovery_password",
            help="Vähemalt 6 märki.",
        )
        new_password_confirm = st.text_input(
            "Korda uut parooli",
            type="password",
            key="_vorm_recovery_password_confirm",
        )
        submitted = st.form_submit_button(
            "Salvesta uus parool", type="primary", width="stretch"
        )
        if submitted:
            if not new_password:
                st.error("Uus parool on kohustuslik.")
                return None
            if new_password != new_password_confirm:
                st.error("Paroolid ei klapi.")
                return None
            if len(new_password) < 6:
                st.error("Parool peab olema vähemalt 6 märki.")
                return None
            try:
                update_password(new_password)
            except SupabaseNotConfigured as exc:
                st.error(str(exc))
                return None
            except Exception as exc:
                st.error(_humanize_auth_error(exc))
                return None
            st.session_state.pop(_PASSWORD_RECOVERY_KEY, None)
            st.session_state[_PASSWORD_RESET_DONE_KEY] = True
            st.rerun()

    if st.button(
        "Katkesta ja logi välja",
        key="_vorm_recovery_cancel",
        width="stretch",
    ):
        sign_out()
        st.rerun()

    return None


def render_login_gate() -> AuthUser | None:
    """Block the app behind an email/password login form. Returns the user or None.

    Call near the top of ``app.py``. If the return is None **and**
    ``is_guest()`` is False, the caller should ``st.stop()`` — nothing else
    should render until the user either signs in or picks guest mode.
    """
    _surface_auth_hash_params()
    _consume_password_recovery_from_url()
    if st.session_state.get(_PASSWORD_RECOVERY_KEY):
        return _render_password_recovery_form()

    user = _restore_persistent_session()
    if user:
        if st.session_state.pop(_PASSWORD_RESET_DONE_KEY, False):
            st.toast("Parool uuendatud. Oled sisse logitud.", icon="✅")
        return user
    # Guests have already bypassed the gate; don't re-render the form.
    if is_guest():
        return None

    st.title("🏃 Vorm.ai")
    st.markdown("### 🔐 Logi sisse, et jätkata")

    # If we just sent a confirm-email, surface that prominently above the tabs
    # so the user knows what to do next.
    pending = st.session_state.get(_PENDING_CONFIRM_KEY)
    if pending:
        st.success(
            f"✉️ Konto loodud. Saatsime kinnitusmaili aadressile **{pending}**. "
            "Klikka seal lingile, et email kinnitada — seejärel saad allpool sisse logida."
        )

    login_tab, signup_tab, reset_tab = st.tabs(
        ["Logi sisse", "Loo uus konto", "Taasta parool"]
    )

    with login_tab:
        with st.form("vorm_login_form"):
            email = st.text_input(
                "Email", placeholder="sinu@email.ee", key="_vorm_login_email",
            )
            password = st.text_input(
                "Parool", type="password", key="_vorm_login_password",
            )
            submitted = st.form_submit_button(
                "Logi sisse", type="primary", width="stretch"
            )
            if submitted:
                cleaned_email = (email or "").strip().lower()
                if not cleaned_email or not password:
                    st.error("Email ja parool on kohustuslikud.")
                    return None
                try:
                    sign_in(cleaned_email, password)
                except SupabaseNotConfigured as exc:
                    st.error(str(exc))
                    return None
                except Exception as exc:
                    st.error(_humanize_auth_error(exc))
                    return None
                st.session_state.pop(_PENDING_CONFIRM_KEY, None)
                st.rerun()

    with signup_tab:
        with st.form("vorm_signup_form"):
            new_email = st.text_input(
                "Email", placeholder="sinu@email.ee", key="_vorm_signup_email",
            )
            new_password = st.text_input(
                "Parool",
                type="password",
                key="_vorm_signup_password",
                help="Vähemalt 6 märki.",
            )
            new_password_confirm = st.text_input(
                "Korda parooli",
                type="password",
                key="_vorm_signup_password_confirm",
            )
            role_label = st.radio(
                "Kes sa Vorm.ai-s oled?",
                options=("Sportlane", "Treener"),
                horizontal=True,
                key="_vorm_signup_role",
                help=(
                    "Sportlane: logib treeningud, näeb iga päeva soovitust. "
                    "Treener: ühendub kutsekoodiga sportlastega ja näeb "
                    "nende koormust + sisestab pimemenetluses päevaotsuseid."
                ),
            )
            submitted = st.form_submit_button(
                "Loo konto", type="primary", width="stretch"
            )
            if submitted:
                cleaned_email = (new_email or "").strip().lower()
                if not cleaned_email or not new_password:
                    st.error("Email ja parool on kohustuslikud.")
                    return None
                if "@" not in cleaned_email or "." not in cleaned_email.split("@")[-1]:
                    st.error("Vigane email-aadress.")
                    return None
                if new_password != new_password_confirm:
                    st.error("Paroolid ei klapi.")
                    return None
                if len(new_password) < 6:
                    st.error("Parool peab olema vähemalt 6 märki.")
                    return None
                chosen_role = "coach" if role_label == "Treener" else "athlete"
                try:
                    sign_up(cleaned_email, new_password, role=chosen_role)
                except SupabaseNotConfigured as exc:
                    st.error(str(exc))
                    return None
                except Exception as exc:
                    st.error(_humanize_auth_error(exc))
                    return None
                st.session_state[_PENDING_CONFIRM_KEY] = cleaned_email
                st.rerun()

    with reset_tab:
        st.caption(
            "Sisesta konto email. Saadame lingi, millega saad siin rakenduses "
            "uue parooli määrata."
        )
        with st.form("vorm_reset_request_form"):
            reset_email = st.text_input(
                "Email", placeholder="sinu@email.ee", key="_vorm_reset_email",
            )
            submitted = st.form_submit_button(
                "Saada taastamislink", type="primary", width="stretch"
            )
            if submitted:
                cleaned_email = (reset_email or "").strip().lower()
                if not cleaned_email:
                    st.error("Email on kohustuslik.")
                    return None
                if "@" not in cleaned_email or "." not in cleaned_email.split("@")[-1]:
                    st.error("Vigane email-aadress.")
                    return None
                try:
                    request_password_reset(cleaned_email)
                except SupabaseNotConfigured as exc:
                    st.error(str(exc))
                    return None
                except Exception as exc:
                    st.error(_humanize_auth_error(exc))
                    return None
                st.success(
                    f"Kui konto on olemas, saatsime taastamislingi aadressile "
                    f"**{cleaned_email}**."
                )

    # Guest-mode escape hatch — useful for course-project demos and reviewers
    # who don't want to create an account just to poke at the UI.
    st.divider()
    st.caption(
        "Soovid lihtsalt rakendust katsetada ilma kontot loomata? "
        "Külalisrežiimis sinu andmed **ei salvestu pilve** — kõik on "
        "ainult selle brauserisessiooni jaoks."
    )
    if st.button(
        "👤 Jätka külalisena",
        key="_vorm_enter_guest",
        width="stretch",
    ):
        enter_guest_mode()
        st.rerun()

    return None


def render_sidebar_user_panel() -> None:
    """Show the signed-in user or guest banner + sign-out button in the sidebar."""
    user = current_user()
    if user:
        with st.sidebar:
            st.markdown(f"👤 **{user.email}**")
            if st.button("Logi välja", key="_vorm_sign_out", width="stretch"):
                sign_out()
                st.rerun()
        return
    if is_guest():
        with st.sidebar:
            st.markdown("👤 **Külaline**")
            st.caption("Andmed ei salvestu pilve.")
            if st.button(
                "Logi sisse / loo konto",
                key="_vorm_exit_guest",
                width="stretch",
            ):
                exit_guest_mode()
                st.rerun()
