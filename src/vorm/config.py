"""Environment-based configuration.

Resolution order for every key:
1. Process environment / `.env` (via python-dotenv) — local-dev path.
2. `streamlit.secrets` — populated from Streamlit Community Cloud's
   *App settings → Secrets* TOML editor.

All values are optional so the app runs in sample-data mode even without
any credentials.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _is_source_checkout() -> bool:
    """True when this module is imported from a checked-out repo (editable
    install or `streamlit run` against the source tree). False when imported
    from a wheel installed into site-packages — in that case PROJECT_ROOT
    points inside the venv and is read-only on hosts like Streamlit Cloud.
    """
    return (PROJECT_ROOT / "pyproject.toml").is_file()


if _is_source_checkout():
    DATA_DIR = PROJECT_ROOT / "data"
else:
    # Streamlit Cloud / any installed-package deployment. `~` resolves to a
    # writable per-user directory (`/home/adminuser` on Streamlit Cloud).
    DATA_DIR = Path.home() / ".vorm"

CACHE_DIR = DATA_DIR / "cache"
USER_DIR = DATA_DIR / "user"


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL_OPTIONS = (
    ("deepseek/deepseek-v4-flash:free", "Automaatne"),
    ("nvidia/nemotron-3-super-120b-a12b:free", "NVIDIA Nemotron 3 Super (free)"),
    ("google/gemma-4-31b-it:free", "Google Gemma 4 31B (free)"),
)
OPENROUTER_MODEL_IDS = tuple(model_id for model_id, _label in OPENROUTER_MODEL_OPTIONS)
DEFAULT_OPENROUTER_FALLBACK_MODELS = OPENROUTER_MODEL_IDS[1:]


def _from_streamlit_secrets(key: str) -> str | None:
    """Look up `key` in `st.secrets` if Streamlit is importable AND a
    `secrets.toml` is configured. Returns None on any failure so CLI use
    (`scripts/validate.py`) doesn't crash when Streamlit isn't running."""
    try:
        import streamlit as st  # noqa: PLC0415 — defer import; CLI path may not have streamlit installed
    except ImportError:
        return None
    try:
        secrets = st.secrets
    except Exception:
        # streamlit raises StreamlitSecretNotFoundError when no secrets.toml exists.
        return None
    try:
        value = secrets[key]
    except (KeyError, FileNotFoundError):
        return None
    return str(value) if value else None


def _get(key: str, default: str | None = None) -> str | None:
    """Env-first, Streamlit-secrets-fallback lookup."""
    value = os.getenv(key)
    if value:
        return value
    secret = _from_streamlit_secrets(key)
    if secret:
        return secret
    return default


@dataclass(frozen=True)
class Config:
    anthropic_api_key: str | None
    openai_api_key: str | None
    openrouter_api_key: str | None
    google_api_key: str | None
    strava_client_id: str | None
    strava_client_secret: str | None
    strava_refresh_token: str | None
    supabase_url: str | None
    supabase_anon_key: str | None
    llm_provider: str
    llm_model: str
    llm_temperature: float
    openrouter_fallback_models: tuple[str, ...] = DEFAULT_OPENROUTER_FALLBACK_MODELS

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_openrouter(self) -> bool:
        return bool(self.openrouter_api_key)

    @property
    def has_google(self) -> bool:
        return bool(self.google_api_key)

    @property
    def has_strava(self) -> bool:
        return bool(
            self.strava_client_id
            and self.strava_client_secret
            and self.strava_refresh_token
        )

    @property
    def has_supabase(self) -> bool:
        """True when Supabase auth + DB is wired up. Drives the multi-user
        login-required code path; when False, app falls back to local SQLite +
        anonymous single-user mode."""
        return bool(self.supabase_url and self.supabase_anon_key)

    @property
    def has_llm(self) -> bool:
        if self.llm_provider == "anthropic":
            return self.has_anthropic
        if self.llm_provider == "openai":
            return self.has_openai
        if self.llm_provider == "openrouter":
            return self.has_openrouter
        if self.llm_provider == "google":
            return self.has_google
        return False


_DEFAULT_MODEL_BY_PROVIDER = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o-2024-08-06",
    # OpenRouter proxies many models. Keep the default on the free primary
    # route; DEFAULT_OPENROUTER_FALLBACK_MODELS supplies the backup order.
    "openrouter": "deepseek/deepseek-v4-flash:free",
    # Google AI Studio: free tier 15 RPM, 1500 RPD on Flash-Lite models.
    # Get key from https://aistudio.google.com/app/apikey
    "google": "gemini-3.1-flash-lite",
}


def _parse_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def openrouter_fallback_models_after(model_id: str) -> tuple[str, ...]:
    """Fallback models that come after `model_id` in the in-app OpenRouter list."""
    if model_id not in OPENROUTER_MODEL_IDS:
        return DEFAULT_OPENROUTER_FALLBACK_MODELS
    index = OPENROUTER_MODEL_IDS.index(model_id)
    return OPENROUTER_MODEL_IDS[index + 1:]


def openrouter_extra_body(config: Config) -> dict[str, list[str]]:
    """OpenRouter-only request body additions.

    The OpenAI SDK passes OpenRouter's model fallback array through
    `extra_body`. The primary model stays in `model`; this array is tried only
    if the primary errors, is rate-limited, or is unavailable.
    """
    if config.llm_provider != "openrouter":
        return {}
    fallbacks = [
        model
        for model in config.openrouter_fallback_models
        if model and model != config.llm_model
    ]
    return {"models": fallbacks} if fallbacks else {}


def load_config() -> Config:
    provider = (_get("LLM_PROVIDER") or "anthropic").lower()
    default_model = _DEFAULT_MODEL_BY_PROVIDER.get(provider, "claude-sonnet-4-6")
    llm_model = _get("LLM_MODEL", default_model)
    # Accept either GOOGLE_API_KEY (AI Studio's canonical name) or GEMINI_API_KEY
    # (the genai SDK's auto-pickup name) — both are common in the wild.
    google_key = _get("GOOGLE_API_KEY") or _get("GEMINI_API_KEY")
    return Config(
        anthropic_api_key=_get("ANTHROPIC_API_KEY") or None,
        openai_api_key=_get("OPENAI_API_KEY") or None,
        openrouter_api_key=_get("OPENROUTER_API_KEY") or None,
        google_api_key=google_key or None,
        strava_client_id=_get("STRAVA_CLIENT_ID") or None,
        strava_client_secret=_get("STRAVA_CLIENT_SECRET") or None,
        strava_refresh_token=_get("STRAVA_REFRESH_TOKEN") or None,
        supabase_url=_get("SUPABASE_URL") or None,
        supabase_anon_key=_get("SUPABASE_ANON_KEY") or None,
        llm_provider=provider,
        llm_model=llm_model,
        llm_temperature=float(_get("LLM_TEMPERATURE", "0") or "0"),
        openrouter_fallback_models=(
            _parse_csv(_get("OPENROUTER_FALLBACK_MODELS"))
            or openrouter_fallback_models_after(llm_model)
        ),
    )
