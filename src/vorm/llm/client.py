"""LLM client with Anthropic + OpenAI backends.

Both backends return a `LLMRecommendation` built from the same JSON schema
(prompts.RESPONSE_SCHEMA). If the first JSON parse fails, we retry once with
an explicit reminder — per the project plan's risk B1/B2 on consistency.

Model versions are pinned in `config.py` rather than floating on `*-latest` —
risk 3 in the plan.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import OPENROUTER_BASE_URL, Config, openrouter_extra_body
from ._json_utils import extract_json_object
from .prompts import PromptBundle


class LLMNotAvailable(RuntimeError):
    """Raised when no LLM provider credentials are configured."""


class LLMParseError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMRecommendation:
    category: str
    rationale: str
    modification: str | None
    confidence: str
    acknowledges_safety_flags: list[str]
    raw_text: str
    model: str
    prompt_version: str
    input_tokens: int | None = None
    output_tokens: int | None = None


def generate_recommendation(prompt: PromptBundle, config: Config) -> LLMRecommendation:
    if not config.has_llm:
        raise LLMNotAvailable(
            f"No credentials for provider '{config.llm_provider}'. "
            "Set ANTHROPIC_API_KEY / OPENAI_API_KEY / OPENROUTER_API_KEY / "
            "GOOGLE_API_KEY in .env, or switch the UI to metrics-only mode."
        )

    if config.llm_provider == "anthropic":
        return _generate_anthropic(prompt, config)
    if config.llm_provider == "openai":
        return _generate_openai(prompt, config)
    if config.llm_provider == "openrouter":
        return _generate_openrouter(prompt, config)
    if config.llm_provider == "google":
        return _generate_google(prompt, config)
    raise LLMNotAvailable(f"Unknown provider: {config.llm_provider}")


def _generate_anthropic(prompt: PromptBundle, config: Config) -> LLMRecommendation:
    try:
        import anthropic
    except ImportError as exc:
        raise LLMNotAvailable("anthropic SDK not installed — run `pip install anthropic`") from exc

    client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    # Cache the system prompt — stable across calls, so saves tokens on repeat queries.
    response = client.messages.create(
        model=config.llm_model,
        max_tokens=1024,
        temperature=config.llm_temperature,
        system=[
            {
                "type": "text",
                "text": prompt.system,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": prompt.user}],
    )
    text = response.content[0].text if response.content else ""
    parsed = _parse_json_with_retry(text, client, prompt, config, _generate_anthropic_retry)
    usage = getattr(response, "usage", None)
    return _build_recommendation(
        parsed,
        raw_text=text,
        model=config.llm_model,
        prompt_version=prompt.version,
        input_tokens=getattr(usage, "input_tokens", None) if usage else None,
        output_tokens=getattr(usage, "output_tokens", None) if usage else None,
    )


def _generate_anthropic_retry(prompt: PromptBundle, config: Config, error: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    response = client.messages.create(
        model=config.llm_model,
        max_tokens=1024,
        temperature=config.llm_temperature,
        system=prompt.system,
        messages=[
            {"role": "user", "content": prompt.user},
            {"role": "assistant", "content": "Vabandust, annan kehtiva JSON-i."},
            {
                "role": "user",
                "content": (
                    f"Eelmine väljund ei parsitud ({error}). "
                    "Palun anna AINULT kehtiv JSON, mis vastab skeemile."
                ),
            },
        ],
    )
    return response.content[0].text if response.content else ""


def _generate_openai(prompt: PromptBundle, config: Config) -> LLMRecommendation:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise LLMNotAvailable("openai SDK not installed — run `pip install openai`") from exc

    client = OpenAI(api_key=config.openai_api_key)
    response = client.chat.completions.create(
        model=config.llm_model,
        temperature=config.llm_temperature,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": prompt.system},
            {"role": "user", "content": prompt.user},
        ],
    )
    text = response.choices[0].message.content or ""
    parsed = _parse_json_with_retry(text, client, prompt, config, _generate_openai_retry)
    usage = getattr(response, "usage", None)
    return _build_recommendation(
        parsed,
        raw_text=text,
        model=config.llm_model,
        prompt_version=prompt.version,
        input_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
        output_tokens=getattr(usage, "completion_tokens", None) if usage else None,
    )


def _generate_openrouter(prompt: PromptBundle, config: Config) -> LLMRecommendation:
    """OpenRouter via the OpenAI SDK (OpenRouter is API-compatible).

    Handy because one key gives access to Claude, GPT, Llama, Gemini etc — the
    model name is the `provider/model` slug on https://openrouter.ai/models.
    """
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise LLMNotAvailable("openai SDK not installed — run `pip install openai`") from exc

    client = OpenAI(
        api_key=config.openrouter_api_key,
        base_url=OPENROUTER_BASE_URL,
        default_headers={
            "HTTP-Referer": "https://github.com/UkuRenekKronbergs/vorm",
            "X-Title": "Vorm.ai",
        },
    )
    # We intentionally omit response_format here: OpenRouter proxies many open
    # models (Gemma, Llama, etc) where strict JSON mode isn't supported. The
    # prompt already instructs JSON-only output and _parse_json_with_retry
    # retries once on parse failure — that combo beats getting a hard 400 from
    # a model that doesn't speak OpenAI JSON mode.
    create_kwargs: dict = {
        "model": config.llm_model,
        "temperature": config.llm_temperature,
        "messages": [
            {"role": "system", "content": prompt.system},
            {"role": "user", "content": prompt.user},
        ],
    }
    extra_body = openrouter_extra_body(config)
    if extra_body:
        create_kwargs["extra_body"] = extra_body
    response = client.chat.completions.create(**create_kwargs)
    text = response.choices[0].message.content or ""

    def _retry(prompt: PromptBundle, config: Config, error: str) -> str:
        retry_kwargs: dict = {
            "model": config.llm_model,
            "temperature": config.llm_temperature,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
                {"role": "assistant", "content": "Vabandust, annan kehtiva JSON-i."},
                {
                    "role": "user",
                    "content": (
                        f"Eelmine väljund ei parsitud ({error}). "
                        "Palun anna AINULT kehtiv JSON, mis vastab skeemile."
                    ),
                },
            ],
        }
        if extra_body:
            retry_kwargs["extra_body"] = extra_body
        retry = client.chat.completions.create(**retry_kwargs)
        return retry.choices[0].message.content or ""

    parsed = _parse_json_with_retry(text, client, prompt, config, _retry)
    usage = getattr(response, "usage", None)
    model = getattr(response, "model", None) or config.llm_model
    return _build_recommendation(
        parsed,
        raw_text=text,
        model=model,
        prompt_version=prompt.version,
        input_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
        output_tokens=getattr(usage, "completion_tokens", None) if usage else None,
    )


def _generate_openai_retry(prompt: PromptBundle, config: Config, error: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=config.openai_api_key)
    response = client.chat.completions.create(
        model=config.llm_model,
        temperature=config.llm_temperature,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": prompt.system},
            {"role": "user", "content": prompt.user},
            {"role": "assistant", "content": "Vabandust, annan kehtiva JSON-i."},
            {
                "role": "user",
                "content": (
                    f"Eelmine väljund ei parsitud ({error}). "
                    "Palun anna AINULT kehtiv JSON, mis vastab skeemile."
                ),
            },
        ],
    )
    return response.choices[0].message.content or ""


def _generate_google(prompt: PromptBundle, config: Config) -> LLMRecommendation:
    """Native Google AI Studio (Gemini) backend via google-genai SDK.

    Uses Gemini's `response_mime_type="application/json"` so the model returns
    a JSON-only body — no parser tolerance needed for the happy path. On parse
    failure we still retry once with an explicit reminder, mirroring the other
    backends.

    Free tier (15 RPM, 1500 RPD on Flash-Lite) is generous enough for the
    full 45-day validation run without rate-limit handling. Get your key:
    https://aistudio.google.com/app/apikey
    """
    try:
        from google import genai
        from google.genai import types as genai_types
    except ImportError as exc:
        raise LLMNotAvailable(
            "google-genai SDK not installed — run `pip install google-genai`"
        ) from exc

    client = genai.Client(api_key=config.google_api_key)
    gen_config = genai_types.GenerateContentConfig(
        system_instruction=prompt.system,
        temperature=config.llm_temperature,
        response_mime_type="application/json",
    )
    response = client.models.generate_content(
        model=config.llm_model,
        contents=prompt.user,
        config=gen_config,
    )
    text = response.text or ""

    def _retry(prompt: PromptBundle, config: Config, error: str) -> str:
        retry_user = (
            f"{prompt.user}\n\n"
            f"EELMINE VÄLJUND EI PARSITUD ({error}). "
            "Anna AINULT kehtiv JSON, mis vastab skeemile — mitte midagi muud."
        )
        retry_resp = client.models.generate_content(
            model=config.llm_model,
            contents=retry_user,
            config=gen_config,
        )
        return retry_resp.text or ""

    parsed = _parse_json_with_retry(text, client, prompt, config, _retry)
    usage = getattr(response, "usage_metadata", None)
    return _build_recommendation(
        parsed,
        raw_text=text,
        model=config.llm_model,
        prompt_version=prompt.version,
        input_tokens=getattr(usage, "prompt_token_count", None) if usage else None,
        output_tokens=getattr(usage, "candidates_token_count", None) if usage else None,
    )


def _parse_json_with_retry(text: str, _client, prompt: PromptBundle, config: Config, retry_fn) -> dict:
    try:
        return _extract_json(text)
    except LLMParseError as exc:
        retry_text = retry_fn(prompt, config, str(exc))
        return _extract_json(retry_text)


def _extract_json(text: str) -> dict:
    try:
        return extract_json_object(text)
    except ValueError as exc:
        raise LLMParseError(str(exc)) from exc


def _build_recommendation(
    parsed: dict,
    *,
    raw_text: str,
    model: str,
    prompt_version: str,
    input_tokens: int | None,
    output_tokens: int | None,
) -> LLMRecommendation:
    return LLMRecommendation(
        category=str(parsed.get("category", "")).strip(),
        rationale=str(parsed.get("rationale", "")).strip(),
        modification=(parsed.get("modification") or None),
        confidence=str(parsed.get("confidence", "keskmine")).strip(),
        acknowledges_safety_flags=list(parsed.get("acknowledges_safety_flags") or []),
        raw_text=raw_text,
        model=model,
        prompt_version=prompt_version,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
