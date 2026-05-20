from __future__ import annotations

from vorm.config import (
    DEFAULT_OPENROUTER_FALLBACK_MODELS,
    Config,
    openrouter_fallback_models_after,
    openrouter_extra_body,
)


def _config(
    *,
    provider: str = "openrouter",
    model: str = "deepseek/deepseek-v4-flash:free",
    fallbacks: tuple[str, ...] = DEFAULT_OPENROUTER_FALLBACK_MODELS,
) -> Config:
    return Config(
        anthropic_api_key=None,
        openai_api_key=None,
        openrouter_api_key="sk-or-test",
        google_api_key=None,
        strava_client_id=None,
        strava_client_secret=None,
        strava_refresh_token=None,
        supabase_url=None,
        supabase_anon_key=None,
        llm_provider=provider,
        llm_model=model,
        llm_temperature=0,
        openrouter_fallback_models=fallbacks,
    )


def test_openrouter_extra_body_routes_to_requested_free_fallbacks() -> None:
    assert openrouter_extra_body(_config()) == {
        "models": [
            "nvidia/nemotron-3-super-120b-a12b:free",
            "google/gemma-4-31b-it:free",
        ]
    }


def test_openrouter_extra_body_skips_duplicate_primary_model() -> None:
    assert openrouter_extra_body(
        _config(model="nvidia/nemotron-3-super-120b-a12b:free")
    ) == {"models": ["google/gemma-4-31b-it:free"]}


def test_openrouter_extra_body_is_empty_for_other_providers() -> None:
    assert openrouter_extra_body(_config(provider="openai")) == {}


def test_openrouter_fallback_models_follow_in_app_model_order() -> None:
    assert openrouter_fallback_models_after("deepseek/deepseek-v4-flash:free") == (
        "nvidia/nemotron-3-super-120b-a12b:free",
        "google/gemma-4-31b-it:free",
    )
    assert openrouter_fallback_models_after("nvidia/nemotron-3-super-120b-a12b:free") == (
        "google/gemma-4-31b-it:free",
    )
    assert openrouter_fallback_models_after("google/gemma-4-31b-it:free") == ()
