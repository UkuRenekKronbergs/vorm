"""Orchestrator: prompt → LLM → structured TrainingPlan.

Reuses the LLM clients from `llm.client` — we just expose a different entry
point that returns a TrainingPlan instead of an LLMRecommendation.

Failure mode: plan JSON is large (~several thousand tokens), so we catch
parse errors, missing fields, and bad dates with a single structured retry.
If the second attempt also fails, `PlanGenerationError` is raised so the UI
can show a clean error rather than a traceback.
"""

from __future__ import annotations

from datetime import date, datetime

from ..config import OPENROUTER_BASE_URL, Config, openrouter_extra_body
from ..data.models import AthleteProfile
from ..llm._json_utils import extract_json_object
from ..llm.client import LLMNotAvailable
from ..metrics.load import LoadSummary
from .models import PlanGoal, PlannedSession, TrainingPlan, WeekPlan
from .prompts import build_plan_prompt


class PlanGenerationError(RuntimeError):
    pass


def generate_training_plan(
    *,
    profile: AthleteProfile,
    goal: PlanGoal,
    summary: LoadSummary | None,
    plan_start: date,
    config: Config,
) -> TrainingPlan:
    if not config.has_llm:
        raise LLMNotAvailable(
            f"No credentials for provider '{config.llm_provider}'. "
            "Plan generation requires an LLM."
        )

    bundle = build_plan_prompt(
        profile=profile,
        goal=goal,
        summary=summary,
        plan_start=plan_start,
    )

    raw_text = _call_llm(bundle.system, bundle.user, config)
    try:
        parsed = _extract_json(raw_text)
    except ValueError as exc:
        retry_user = (
            f"{bundle.user}\n\n"
            f"EELMINE VÄLJUND EI PARSITUD ({exc}). Anna AINULT kehtiv JSON, "
            f"mis algab `{{` ja lõppeb `}}`. Mitte midagi muud."
        )
        raw_text = _call_llm(bundle.system, retry_user, config)
        try:
            parsed = _extract_json(raw_text)
        except ValueError as exc2:
            raise PlanGenerationError(f"LLM-i väljund pole kehtiv JSON: {exc2}") from exc2

    try:
        plan = _plan_from_json(parsed, goal=goal, model=config.llm_model, raw_text=raw_text)
    except (KeyError, ValueError, TypeError) as exc:
        raise PlanGenerationError(f"JSON ei vasta skeemile: {exc}") from exc
    return plan


def _call_llm(system: str, user: str, config: Config) -> str:
    """Provider dispatch — reuses the same backends as the daily advisor."""
    if config.llm_provider == "anthropic":
        return _call_anthropic(system, user, config)
    if config.llm_provider in ("openai", "openrouter"):
        return _call_openai_compatible(system, user, config)
    raise LLMNotAvailable(f"Unknown provider: {config.llm_provider}")


def _call_anthropic(system: str, user: str, config: Config) -> str:
    try:
        import anthropic
    except ImportError as exc:
        raise LLMNotAvailable("anthropic SDK not installed") from exc
    client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    # Cache the system prompt — same wording across attempts and any retry, so
    # the second call lands within the 5-min TTL and avoids re-billing the
    # ~1k-token coaching preamble.
    resp = client.messages.create(
        model=config.llm_model,
        max_tokens=8192,  # plan is large
        temperature=config.llm_temperature,
        system=[
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user}],
    )
    return resp.content[0].text if resp.content else ""


def _call_openai_compatible(system: str, user: str, config: Config) -> str:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise LLMNotAvailable("openai SDK not installed") from exc

    client_kwargs: dict = {}
    if config.llm_provider == "openrouter":
        client_kwargs["api_key"] = config.openrouter_api_key
        client_kwargs["base_url"] = OPENROUTER_BASE_URL
        client_kwargs["default_headers"] = {
            "HTTP-Referer": "https://github.com/UkuRenekKronbergs/vorm",
            "X-Title": "Vorm.ai",
        }
    else:
        client_kwargs["api_key"] = config.openai_api_key

    client = OpenAI(**client_kwargs)
    create_kwargs: dict = {
        "model": config.llm_model,
        "temperature": config.llm_temperature,
        "max_tokens": 8192,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    # Native OpenAI supports strict JSON mode and benefits from it on a 7000-
    # token plan response. Skip on OpenRouter — many proxied open models 400
    # when given response_format.
    if config.llm_provider == "openai":
        create_kwargs["response_format"] = {"type": "json_object"}
    if config.llm_provider == "openrouter":
        extra_body = openrouter_extra_body(config)
        if extra_body:
            create_kwargs["extra_body"] = extra_body

    resp = client.chat.completions.create(**create_kwargs)
    return resp.choices[0].message.content or ""


def _extract_json(text: str) -> dict:
    return extract_json_object(text)


def _plan_from_json(
    parsed: dict,
    *,
    goal: PlanGoal,
    model: str,
    raw_text: str,
) -> TrainingPlan:
    weeks_raw = parsed.get("weeks")
    # Tolerance: some models (Gemma, Llama) flatten the structure into a single
    # top-level array under keys like `training_plan`, `sessions`, or `schedule`.
    # Detect that shape and group into 7-day weeks here.
    if not weeks_raw:
        flat = _find_flat_sessions(parsed)
        if flat:
            weeks_raw = _group_sessions_into_weeks(flat)

    weeks: list[WeekPlan] = []
    for w in weeks_raw or []:
        sessions: list[PlannedSession] = []
        for s in w.get("sessions") or []:
            sessions.append(
                PlannedSession(
                    session_date=_parse_date(s["session_date"]),
                    session_type=str(s.get("session_type", "")).strip() or "Treening",
                    duration_min=float(s.get("duration_min") or 0),
                    intensity_zone=str(s.get("intensity_zone", "Z2")).strip(),
                    target_pace_min_per_km=_opt_float(s.get("target_pace_min_per_km")),
                    distance_km=_opt_float(s.get("distance_km")),
                    description=str(s.get("description") or "").strip(),
                )
            )
        weeks.append(
            WeekPlan(
                week_number=int(w["week_number"]),
                week_start=_parse_date(w["week_start"]),
                phase=str(w.get("phase", "base")).strip(),
                target_volume_km=float(w.get("target_volume_km") or 0),
                sessions=sessions,
                notes=str(w.get("notes") or "").strip(),
            )
        )
    return TrainingPlan(
        goal=goal,
        generated_at=datetime.now(),
        model=model,
        weeks=weeks,
        overview=str(parsed.get("overview") or "").strip(),
        raw_text=raw_text,
    )


def _find_flat_sessions(parsed: dict) -> list[dict] | None:
    """Recover from flat-shape variants open models sometimes emit."""
    for key in ("training_plan", "sessions", "schedule", "plan", "days"):
        candidate = parsed.get(key)
        if isinstance(candidate, list) and candidate and isinstance(candidate[0], dict):
            if "session_date" in candidate[0]:
                return candidate
    return None


def _group_sessions_into_weeks(sessions: list[dict]) -> list[dict]:
    """Rebucket a flat list of session dicts into weekly dicts matching our schema.

    Week boundary = every 7 consecutive calendar days starting from the first
    session date, regardless of weekday. Phase defaults to `base` since flat
    formats usually omit it — overview hopefully compensates.
    """
    if not sessions:
        return []
    sessions_sorted = sorted(sessions, key=lambda s: str(s.get("session_date", "")))
    first_date = _parse_date(sessions_sorted[0]["session_date"])
    buckets: dict[int, list[dict]] = {}
    for s in sessions_sorted:
        try:
            d = _parse_date(s["session_date"])
        except (KeyError, ValueError):
            continue
        week_idx = (d - first_date).days // 7
        buckets.setdefault(week_idx, []).append(s)

    weeks_raw: list[dict] = []
    for week_idx in sorted(buckets):
        week_sessions = buckets[week_idx]
        week_start = _parse_date(week_sessions[0]["session_date"])
        volume = sum(float(s.get("distance_km") or 0) for s in week_sessions)
        weeks_raw.append(
            {
                "week_number": week_idx + 1,
                "week_start": week_start.isoformat(),
                "phase": "base",
                "target_volume_km": round(volume, 1),
                "sessions": week_sessions,
                "notes": "",
            }
        )
    return weeks_raw


def _parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _opt_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
