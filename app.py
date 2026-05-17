"""Streamlit entry point for Vorm.ai.

Run with: ``streamlit run app.py``

UI layout:
- Sidebar: data source, athlete profile, analysis date
- Tab 1 (Tänane soovitus): today's input form → recommendation
- Tab 2 (Koormuse ajalugu): ACWR + daily load + weekly volume + RPE trend
- Tab 3 (Retrospektiivne test): pick a past date, see what the model would advise
"""

from __future__ import annotations

import hashlib
import io
import secrets
import sys
import time
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit, urlunsplit

import pandas as pd
import streamlit as st

from vorm import auth
from vorm.config import CACHE_DIR, load_config
from vorm.data import (
    AthleteProfile,
    DailySubjective,
    StravaConnection,
    TrainingActivity,
    generate_sample_activities,
    load_sample_profile,
)
from vorm.data.csv_loader import load_activities_csv
from vorm.data.garmin import parse_gpx_folder
from vorm.data.storage import ActivityStore, CoachDecision, DailyLogEntry
from vorm.data.strava import (
    STRAVA_ACTIVITY_SCOPE,
    StravaNotConfigured,
    build_authorization_url,
    exchange_code_for_token,
    fetch_with_cache,
)
from vorm.llm import LLMNotAvailable, build_prompt, generate_recommendation
from vorm.metrics import (
    PB_DISTANCES,
    acwr_series,
    build_load_timeseries,
    find_personal_bests,
    forecast_acwr,
    forecast_message,
    summarize_load,
)
from vorm.planning import PlanGenerationError, PlanGoal, generate_training_plan
from vorm.rules import evaluate_safety_rules
from vorm.ui import (
    acwr_chart,
    apply_theme,
    daily_load_chart,
    fitness_form_chart,
    hr_zone_distribution_chart,
    list_linked_coach_names,
    log_heatmap_chart,
    longest_streak,
    pb_progression_chart,
    render_athlete_coach_panel,
    render_coach_home,
    render_fitness_form_explainer,
    render_load_metrics_explainer,
    render_onboarding_wizard,
    render_theme_selector,
    rpe_trend_chart,
    should_show_onboarding,
    streak_count,
    weekly_volume_chart,
)
from vorm.validation import build_validation_report

if __name__ == "__main__" and not st.runtime.exists():
    from streamlit.web import cli as stcli

    sys.argv = ["streamlit", "run", str(Path(__file__).resolve())]
    raise SystemExit(stcli.main())

st.set_page_config(page_title="Vorm.ai — treeningkoormuse analüüsija", page_icon="🏃", layout="wide")

# Inject the active theme's CSS as early as possible so it applies before
# the rest of the page renders (avoids a light-mode flash on dark-theme loads).
apply_theme()

_SOURCE_MANUAL = "Käsitsi lisamine"
_SOURCE_CSV = "CSV-fail"
_SOURCE_STRAVA = "Strava API"
_SOURCE_GARMIN = "Garmin GPX-kaust"
_DEMO_DATA_KEY = "_vorm_demo_data_enabled"
_DATA_SOURCE_KEY = "_vorm_data_source"
_STRAVA_CONNECTION_KEY = "_vorm_strava_connection"
_STRAVA_AUTH_URL_KEY = "_vorm_strava_auth_url"
_STRAVA_AUTH_STATE_KEY = "_vorm_strava_auth_state"
_STRAVA_DISABLE_ENV_KEY = "_vorm_strava_disable_env_connection"
_STRAVA_PENDING_TTL_SECONDS = 15 * 60
_STRAVA_CALLBACK_KEYS = ("code", "scope", "state", "error", "error_description")


@st.cache_resource
def _strava_pending_registry() -> dict:
    return {"lock": RLock(), "pending": {}}


def _remember_pending_strava_oauth(
    state: str,
    *,
    client_id: str,
    client_secret: str,
) -> None:
    registry = _strava_pending_registry()
    with registry["lock"]:
        _prune_pending_strava_oauth(registry["pending"])
        registry["pending"][state] = {
            "client_id": client_id,
            "client_secret": client_secret,
            "created_at": time.time(),
        }


def _pop_pending_strava_oauth(state: str) -> dict | None:
    registry = _strava_pending_registry()
    with registry["lock"]:
        _prune_pending_strava_oauth(registry["pending"])
        return registry["pending"].pop(state, None)


def _prune_pending_strava_oauth(pending: dict) -> None:
    cutoff = time.time() - _STRAVA_PENDING_TTL_SECONDS
    for key, value in list(pending.items()):
        if value.get("created_at", 0) < cutoff:
            pending.pop(key, None)


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


def _clear_strava_query_params() -> None:
    try:
        remaining = dict(st.query_params)
        for key in _STRAVA_CALLBACK_KEYS:
            remaining.pop(key, None)
        st.query_params.clear()
        for key, value in remaining.items():
            st.query_params[key] = value
    except Exception:
        pass


def _current_app_url() -> str:
    try:
        raw_url = str(st.context.url or "")
    except Exception:
        raw_url = ""
    if not raw_url:
        return "http://localhost:8501"
    parts = urlsplit(raw_url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _strava_callback_domain() -> str:
    host = urlsplit(_current_app_url()).hostname or "localhost"
    return host


def _load_saved_strava_connection(cfg) -> StravaConnection | None:
    cached = st.session_state.get(_STRAVA_CONNECTION_KEY)
    if isinstance(cached, StravaConnection):
        return cached

    try:
        saved = _get_user_store().load_strava_connection()
    except Exception:
        saved = None
    if saved:
        st.session_state[_STRAVA_CONNECTION_KEY] = saved
        return saved

    if cfg.has_strava and not st.session_state.get(_STRAVA_DISABLE_ENV_KEY):
        connection = StravaConnection(
            client_id=cfg.strava_client_id or "",
            client_secret=cfg.strava_client_secret or "",
            refresh_token=cfg.strava_refresh_token or "",
            athlete_name="seadistatud .env / secrets kaudu",
            scope=STRAVA_ACTIVITY_SCOPE,
        )
        st.session_state[_STRAVA_CONNECTION_KEY] = connection
        return connection
    return None


def _save_strava_connection(
    connection: StravaConnection,
    *,
    surface_errors: bool = True,
) -> None:
    st.session_state.pop(_STRAVA_DISABLE_ENV_KEY, None)
    st.session_state[_STRAVA_CONNECTION_KEY] = connection
    try:
        _get_user_store().save_strava_connection(connection)
    except Exception as exc:
        if surface_errors:
            st.sidebar.warning(
                f"Strava ühendus töötab selles sessioonis, aga püsiv salvestus ebaõnnestus: {exc}",
                icon="⚠️",
            )


def _delete_strava_connection(*, disable_env: bool = False) -> None:
    st.session_state.pop(_STRAVA_CONNECTION_KEY, None)
    st.session_state.pop(_STRAVA_AUTH_URL_KEY, None)
    st.session_state.pop(_STRAVA_AUTH_STATE_KEY, None)
    if disable_env:
        st.session_state[_STRAVA_DISABLE_ENV_KEY] = True
    try:
        _get_user_store().delete_strava_connection()
    except Exception:
        pass


def _consume_strava_oauth_callback() -> None:
    state = _query_param("state")
    if not state or not state.startswith("vorm-strava-"):
        return

    error = _query_param("error_description") or _query_param("error")
    if error:
        st.sidebar.error(f"Strava autoriseerimine katkestati: {error}")
        _clear_strava_query_params()
        return

    code = _query_param("code")
    if not code:
        st.sidebar.error("Strava ei tagastanud autoriseerimiskoodi. Proovi uuesti.")
        _clear_strava_query_params()
        return

    pending = _pop_pending_strava_oauth(state)
    if not pending:
        st.sidebar.error("Strava ühendamise sessioon aegus. Alusta ühendamist uuesti.")
        _clear_strava_query_params()
        return

    try:
        token = exchange_code_for_token(
            client_id=pending["client_id"],
            client_secret=pending["client_secret"],
            code=code,
        )
    except Exception as exc:
        st.sidebar.error(f"Strava tokeni vahetus ebaõnnestus: {exc}")
        _clear_strava_query_params()
        return

    granted_scope = _query_param("scope") or token.scope
    connection = StravaConnection(
        client_id=pending["client_id"],
        client_secret=pending["client_secret"],
        refresh_token=token.refresh_token,
        athlete_id=token.athlete_id,
        athlete_name=token.athlete_name,
        scope=granted_scope,
    )
    _save_strava_connection(connection)
    st.session_state[_DATA_SOURCE_KEY] = _SOURCE_STRAVA
    st.session_state.pop(_STRAVA_AUTH_URL_KEY, None)
    st.session_state.pop(_STRAVA_AUTH_STATE_KEY, None)
    _clear_strava_query_params()
    st.sidebar.success("Strava ühendatud. Tõmban treeningud.")
    st.rerun()


def _strava_cache_db(connection: StravaConnection, cfg) -> Path:
    if (
        cfg.has_strava
        and connection.athlete_id is None
        and connection.client_id == cfg.strava_client_id
    ):
        return CACHE_DIR / "activities.sqlite"

    user = auth.current_user()
    identity = (
        f"user:{user.id}" if user else connection.athlete_id or connection.client_id or "local"
    )
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return CACHE_DIR / f"activities_strava_{suffix}.sqlite"


def _is_env_strava_connection(connection: StravaConnection, cfg) -> bool:
    return (
        cfg.has_strava
        and connection.athlete_id is None
        and connection.client_id == cfg.strava_client_id
    )


def _get_activities(
    source: str,
    uploaded_csv,
    days: int,
    cfg,
    *,
    strava_connection: StravaConnection | None = None,
    use_demo_data: bool = False,
) -> list[TrainingActivity]:
    if use_demo_data:
        return generate_sample_activities(days=days)
    if source == _SOURCE_MANUAL:
        return []
    if source == _SOURCE_CSV:
        if uploaded_csv is None:
            return []
        try:
            # utf-8-sig strips a BOM if present — Excel-edited Strava exports
            # often have one, vanilla Strava exports don't. Either works.
            return load_activities_csv(io.StringIO(uploaded_csv.getvalue().decode("utf-8-sig")))
        except Exception as exc:
            st.error(f"CSV-i lugemine ebaõnnestus: {exc}")
            return []
    if source == _SOURCE_GARMIN:
        folder = st.session_state.get("garmin_folder", "").strip()
        if not folder:
            st.info("Sisesta vasakul Garmin GPX-i ekspordi kausta tee.")
            return []
        path = Path(folder)
        if not path.is_dir():
            st.error(f"Kaust '{folder}' ei eksisteeri. Eksporti Garmin Connectist GPX-failid sellesse kausta.")
            return []
        try:
            return parse_gpx_folder(path)
        except Exception as exc:
            st.error(f"GPX-failide lugemine ebaõnnestus: {exc}")
            return []
    if source == _SOURCE_STRAVA:
        if strava_connection is None:
            st.info("Ühenda vasakul Strava API, et treeningud automaatselt laadida.")
            return []
        try:
            result = fetch_with_cache(
                client_id=strava_connection.client_id,
                client_secret=strava_connection.client_secret,
                refresh_token=strava_connection.refresh_token,
                cache_db=_strava_cache_db(strava_connection, cfg),
                days=days,
            )
            if result.refresh_token and result.refresh_token != strava_connection.refresh_token:
                _save_strava_connection(
                    replace(strava_connection, refresh_token=result.refresh_token),
                    surface_errors=False,
                )
            if result.api_called:
                msg = f"Strava sünk: {result.fetched_from_api} uut + {result.cache_hits} vahemälust"
                if result.latest_cached_date:
                    msg += f" (viimane: {result.latest_cached_date.isoformat()})"
                st.success(msg)
            else:
                st.info(
                    f"Strava API ei vastanud — kasutan vahemälu "
                    f"({result.cache_hits} treeningut)."
                )
            return result.activities
        except StravaNotConfigured as exc:
            st.error(str(exc))
            return []
        except Exception as exc:
            st.error(f"Strava päring ebaõnnestus: {exc}")
            return []
    return []


def _activity_context_key(
    source: str,
    use_demo_data: bool,
    activities: list[TrainingActivity],
) -> tuple[str, bool, int, str]:
    """Stable enough key for hiding stale evaluations after data changes."""
    digest = hashlib.sha256()
    for activity in sorted(activities, key=lambda a: (a.activity_date, a.id)):
        digest.update(
            "|".join(
                (
                    activity.id,
                    activity.activity_date.isoformat(),
                    activity.activity_type,
                    f"{activity.distance_km:.3f}",
                    f"{activity.duration_min:.1f}",
                    str(activity.avg_hr or ""),
                    str(activity.max_hr_observed or ""),
                    str(activity.avg_pace_min_per_km or ""),
                    str(activity.elevation_gain_m or ""),
                    str(activity.rpe or ""),
                    activity.notes or "",
                )
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return source, bool(use_demo_data), len(activities), digest.hexdigest()


def _profile_context_key(profile: AthleteProfile) -> tuple:
    return (
        profile.name,
        profile.age,
        profile.sex,
        profile.max_hr,
        profile.resting_hr,
        profile.training_years,
        profile.season_goal,
        tuple(sorted((profile.personal_bests or {}).items())),
        profile.threshold_pace_min_per_km,
    )


def _subjective_context_key(subjective: DailySubjective) -> tuple:
    return (
        subjective.rpe_yesterday,
        subjective.sleep_hours,
        subjective.stress_level,
        subjective.illness,
        subjective.notes,
    )


def _evaluation_context_key(
    *,
    data_context_key: tuple[str, bool, int, str],
    profile: AthleteProfile,
    today_plan: str,
    subjective: DailySubjective,
    analysis_date: date,
) -> tuple:
    """Inputs that make an already-rendered recommendation stale when changed."""
    return (
        data_context_key,
        analysis_date.isoformat(),
        _profile_context_key(profile),
        today_plan.strip(),
        _subjective_context_key(subjective),
    )


def _render_profile_editor(default: AthleteProfile) -> AthleteProfile:
    with st.expander("Sportlase profiil", expanded=False):
        name = st.text_input("Nimi", value=default.name)
        col1, col2, col3 = st.columns(3)
        age = col1.number_input("Vanus", min_value=12, max_value=80, value=default.age)
        sex = col2.selectbox("Sugu", ["M", "F"], index=0 if default.sex == "M" else 1)
        years = col3.number_input("Treeningstaaž (a)", min_value=0, max_value=50, value=default.training_years)
        col4, col5 = st.columns(2)
        max_hr = col4.number_input("Maksimaalne pulss", min_value=120, max_value=230, value=default.max_hr)
        rest_hr = col5.number_input("Puhkepulss", min_value=30, max_value=90, value=default.resting_hr)
        goal = st.text_input("Hooaja eesmärk", value=default.season_goal)

        st.markdown("**Tippajad** (formaadis `M:SS` või `MM:SS`)")
        pb_cols = st.columns(4)
        pbs: dict[str, str] = {}
        for col, key, label in zip(
            pb_cols,
            ("1500m", "3000m", "5000m", "10000m"),
            ("1500 m", "3000 m", "5000 m", "10 000 m"),
            strict=False,
        ):
            v = col.text_input(label, value=default.personal_bests.get(key, ""), key=f"pb_{key}")
            if v.strip():
                pbs[key] = v.strip()

        st.markdown("**Künnis-tempo** (jäta 0, et tuletada 10 km PB-st automaatselt)")
        threshold_input = st.number_input(
            "min/km",
            min_value=0.0,
            max_value=10.0,
            value=default.threshold_pace_min_per_km or 0.0,
            step=0.05,
            format="%.2f",
            help="HR-andmete puudumisel kasutatakse seda intensity factor'i arvutamiseks (rTSS-stiilis fallback).",
        )
        threshold_value = threshold_input if threshold_input > 0 else None

    return AthleteProfile(
        name=name,
        age=int(age),
        sex=sex,
        max_hr=int(max_hr),
        resting_hr=int(rest_hr),
        training_years=int(years),
        season_goal=goal,
        personal_bests=pbs or default.personal_bests,
        threshold_pace_min_per_km=threshold_value,
    )


def _recommendation_color(category: str) -> str:
    return {
        "Jätka plaanipäraselt": "#4C956C",
        "Vähenda intensiivsust": "#FFB400",
        "Alternatiivne treening": "#3A86FF",
        "Lisa taastumispäev": "#E55934",
    }.get(category, "#888888")


def _render_verdict_box(verdict, llm_result=None):
    category = llm_result.category if llm_result else verdict.recommendation.value
    color = _recommendation_color(category)
    source_badge = "LLM" if llm_result else "reegel"
    st.markdown(
        f"""
        <div style="border-left: 6px solid {color}; padding: 14px 18px; background: #FAFAFA; border-radius: 4px;">
          <div style="font-size: 12px; color: #666; letter-spacing: 0.5px; text-transform: uppercase;">
            Soovitus — allikas: {source_badge}
          </div>
          <div style="font-size: 22px; font-weight: 600; color: {color}; margin: 4px 0 10px;">
            {category}
          </div>
          <div style="font-size: 15px; line-height: 1.45; color: #222;">
            {(llm_result.rationale if llm_result else "Reeglipõhine soovitus — lisa API võti detailse põhjenduse saamiseks.")}
          </div>
          {"<div style='margin-top: 10px; font-size: 14px; color: #444;'><b>Asendus:</b> " + llm_result.modification + "</div>" if (llm_result and llm_result.modification) else ""}
        </div>
        """,
        unsafe_allow_html=True,
    )
    if llm_result:
        meta = f"Mudel: `{llm_result.model}` · prompt v{llm_result.prompt_version} · kindlus: {llm_result.confidence}"
        if llm_result.input_tokens:
            meta += f" · input tokens: {llm_result.input_tokens} · output tokens: {llm_result.output_tokens}"
        st.caption(meta)


def _render_coach_decision_card(decision: CoachDecision) -> None:
    """Athlete-facing display for one coach decision."""
    with st.container(border=True):
        meta_cols = st.columns([3, 1])
        meta_cols[0].caption(f"Treeneri otsus - {decision.coach_name}")
        meta_cols[1].caption(decision.decision_date.isoformat())
        st.markdown(f"### {decision.recommended_category}")
        if decision.rationale:
            st.markdown(f"**Põhjendus:** {decision.rationale}")
        if decision.notes:
            st.caption(f"Märkused: {decision.notes}")


def _coach_decision_table_rows(
    decisions: list[CoachDecision],
    log_by_date: dict[date, DailyLogEntry] | None = None,
) -> list[dict[str, str]]:
    rows = []
    log_by_date = log_by_date or {}
    for decision in sorted(decisions, key=lambda d: d.decision_date, reverse=True):
        log = log_by_date.get(decision.decision_date)
        row = {
            "Kuupäev": decision.decision_date.isoformat(),
            "Treener": decision.coach_name,
            "Otsus": decision.recommended_category,
            "Põhjendus": decision.rationale or "",
            "Märkused": decision.notes or "",
            "Mudeli soovitus": "",
            "Kattuvus": "",
        }
        if log is not None:
            row["Mudeli soovitus"] = log.recommended_category
            row["Kattuvus"] = _agreement_bucket(
                log.recommended_category,
                decision.recommended_category,
            )
        rows.append(row)
    return rows


@st.fragment(run_every="30s")
def _render_live_coach_decision_for_day(store, day: date) -> None:
    """Poll the athlete's own coach_decisions row so coach saves surface live."""
    if store is None:
        return
    try:
        decision = store.get_coach_decision(day)
    except Exception as exc:
        st.warning(f"Treeneri otsuse laadimine ebaõnnestus: {exc}")
        return
    if decision is None:
        return
    _render_coach_decision_card(decision)


def _render_safety_flags(verdict):
    if not verdict.flags:
        st.success("Ohutusreeglid: kõik korras — kriitilisi ega hoiatusi pole.")
        return
    for f in verdict.flags:
        if f.severity.value == "critical":
            st.error(f"⚠ **{f.code}** — {f.message}")
        else:
            st.warning(f"**{f.code}** — {f.message}")


@st.cache_resource
def _get_local_store() -> ActivityStore:
    """Local SQLite store shared across reruns; cached so we don't reopen per click.

    Used in anonymous mode (no Supabase configured) and as a fallback if the
    Supabase client transiently fails. Per-user isolation is NOT enforced here
    — local SQLite is always single-tenant.
    """
    return ActivityStore(CACHE_DIR / "activities.sqlite")


def _get_user_store():
    """Resolve the user-scoped store for profile + daily logs.

    Returns SupabaseStore when the user is signed in (per-user, RLS-protected),
    else the local SQLite ActivityStore. The local path covers three cases:
    Supabase not configured, user picked 'guest' on the login gate, or the
    Supabase client transiently failed. All three should keep working without
    cloud persistence.
    """
    cfg_now = load_config()
    if cfg_now.has_supabase and not auth.is_guest():
        store = auth.get_store()
        if store is not None:
            return store
    return _get_local_store()


_PROFILE_CACHE_KEY = "_vorm_profile_loaded"
_PROFILE_MISSING = "__MISSING__"


def _load_initial_profile() -> AthleteProfile:
    """Load the saved profile once per Streamlit session.

    Delegates to ``_get_user_store()`` so the same code path covers both
    Supabase (signed-in user) and local SQLite (anonymous mode). Caches in
    session_state to skip the round-trip on every rerun. Falls back to the
    bundled sample profile when no saved row exists yet or the store errors.
    """
    cached = st.session_state.get(_PROFILE_CACHE_KEY)
    if isinstance(cached, AthleteProfile):
        return cached
    if cached == _PROFILE_MISSING:
        return load_sample_profile()
    try:
        loaded = _get_user_store().load_profile()
    except Exception:
        loaded = None
    if loaded:
        st.session_state[_PROFILE_CACHE_KEY] = loaded
        return loaded
    st.session_state[_PROFILE_CACHE_KEY] = _PROFILE_MISSING
    return load_sample_profile()


def _autosave_profile(profile: AthleteProfile) -> None:
    """Persist the profile when it differs from the cached (last-saved) one.

    Streamlit reruns the whole script on every interaction, so the no-op
    equality check is what keeps this from hammering the store. Saves go to
    Supabase when signed in, local SQLite otherwise — same call site either
    way. Failures surface as a quiet sidebar warning so a transient network
    blip doesn't crash the page.
    """
    cached = st.session_state.get(_PROFILE_CACHE_KEY)
    if isinstance(cached, AthleteProfile) and cached == profile:
        return
    try:
        _get_user_store().save_profile(profile)
    except Exception as exc:
        st.sidebar.warning(f"Profiili ei õnnestunud salvestada: {exc}", icon="⚠️")
        return
    st.session_state[_PROFILE_CACHE_KEY] = profile


def _render_strava_connection_panel(
    source: str,
    cfg,
    connection: StravaConnection | None,
) -> StravaConnection | None:
    if source != _SOURCE_STRAVA:
        return connection

    st.sidebar.markdown("#### Strava ühendus")
    if connection:
        label = connection.athlete_name or f"Client ID {connection.client_id}"
        st.sidebar.success(f"Ühendatud: {label}")
        if "activity:read" not in (connection.scope or ""):
            st.sidebar.warning(
                "Strava luba ei sisalda `activity:read_all` õigust. Ühenda uuesti ja luba treeningute lugemine.",
                icon="⚠️",
            )
        col1, col2 = st.sidebar.columns(2)
        if col1.button("Ühenda uuesti", key="_vorm_strava_reconnect", width="stretch"):
            _delete_strava_connection(
                disable_env=_is_env_strava_connection(connection, cfg)
            )
            st.rerun()
        if col2.button("Eemalda", key="_vorm_strava_disconnect", width="stretch"):
            _delete_strava_connection(
                disable_env=_is_env_strava_connection(connection, cfg)
            )
            st.rerun()
        return connection

    callback_domain = _strava_callback_domain()
    redirect_uri = _current_app_url()
    st.sidebar.info(
        "Sisesta Strava API rakenduse Client ID ja Client Secret. "
        "Seejärel suunan sind Stravasse luba andma."
    )
    st.sidebar.caption(
        f"Strava API seadetes peab **Authorization Callback Domain** olema `{callback_domain}`."
    )
    with st.sidebar.form("vorm_strava_connect_form"):
        client_id = st.text_input(
            "Client ID",
            value=cfg.strava_client_id or "",
            key="_vorm_strava_client_id",
            help="Leiad Strava lehelt Settings → My API Application.",
        )
        client_secret = st.text_input(
            "Client Secret",
            value="",
            type="password",
            key="_vorm_strava_client_secret",
        )
        submitted = st.form_submit_button("Valmista Strava ühendus", type="primary")
        if submitted:
            clean_client_id = (client_id or "").strip()
            clean_secret = (client_secret or "").strip()
            if not clean_client_id or not clean_secret:
                st.sidebar.error("Client ID ja Client Secret on kohustuslikud.")
            else:
                try:
                    state = f"vorm-strava-{secrets.token_urlsafe(18)}"
                    url = build_authorization_url(
                        client_id=clean_client_id,
                        redirect_uri=redirect_uri,
                        state=state,
                        scope=STRAVA_ACTIVITY_SCOPE,
                        approval_prompt="force",
                    )
                except Exception as exc:
                    st.sidebar.error(str(exc))
                else:
                    _remember_pending_strava_oauth(
                        state,
                        client_id=clean_client_id,
                        client_secret=clean_secret,
                    )
                    st.session_state[_STRAVA_AUTH_STATE_KEY] = state
                    st.session_state[_STRAVA_AUTH_URL_KEY] = url

    auth_url = st.session_state.get(_STRAVA_AUTH_URL_KEY)
    if auth_url:
        st.sidebar.link_button(
            "Ava Strava autoriseerimine",
            auth_url,
            type="primary",
            width="stretch",
        )
        st.sidebar.caption("Pärast luba andmist tuled automaatselt tagasi siia rakendusse.")

    return None


def _render_daily_log_form(
    log_day: date,
    recommended_category: str,
    rationale: str | None,
) -> None:
    """Project Plan §4.3 — collect the athlete's reaction to the recommendation."""
    store = _get_user_store()
    existing = store.get_daily_log(log_day)
    with st.form(f"daily_log_{log_day.isoformat()}", clear_on_submit=False):
        st.markdown(f"#### Päevalogi — {log_day.isoformat()}")
        st.caption(
            "Salvesta, kui kasulik ja veenev soovitus oli ning kuidas esimene "
            "järgmine treening pärast seda soovitust tundus. Kui järgmist trenni "
            "pole veel olnud, jäta enesetunne keskele ja uuenda logi hiljem."
        )
        col1, col2 = st.columns(2)
        usefulness = col1.slider(
            "Kui kasulik soovitus oli? (1–5)", 1, 5,
            value=existing.usefulness if existing and existing.usefulness else 3,
            help="1 = ei aidanud otsust teha, 3 = enam-vähem kasulik, 5 = väga kasulik.",
        )
        persuasiveness = col2.slider(
            "Kui veenev põhjendus oli? (1–5)", 1, 5,
            value=existing.persuasiveness if existing and existing.persuasiveness else 3,
            help="1 = põhjendus ei veennud, 3 = arusaadav, 5 = väga selge ja usaldusväärne.",
        )
        followed_options = ["Jah", "Osaliselt", "Ei"]
        followed_default = (
            {"yes": 0, "partial": 1, "no": 2}.get(existing.followed, 0)
            if existing else 0
        )
        followed_label = st.radio(
            "Kas järgisid soovitust?", followed_options,
            index=followed_default, horizontal=True,
        )
        st.caption(
            "**Järgmise treeningu enesetunne** tähendab esimest trenni pärast seda "
            "soovitust: kas läksid trenni värske ja kontrollitud tundega või olid "
            "jalad rasked, väsimus suur või pidid trenni kärpima."
        )
        next_feeling = st.slider(
            "Kuidas järgmine treening tundus? (1–5)", 1, 5,
            value=existing.next_session_feeling if existing and existing.next_session_feeling else 3,
            help=(
                "1 = väga halb / pidid katkestama või tugevalt kärpima, "
                "3 = tavaline, 5 = väga hea / värske ja kontrollitud."
            ),
        )
        notes = st.text_area(
            "Märkmed (valikuline)",
            value=existing.notes if existing else "",
            placeholder="Nt: järgmine trenn oli kerge ja kontrollitud; või jalad olid rasked ja kärpisin 15 min.",
            height=70,
        )
        submitted = st.form_submit_button("💾 Salvesta päevalogi", type="primary")
        if submitted:
            followed_code = {"Jah": "yes", "Osaliselt": "partial", "Ei": "no"}[followed_label]
            store.save_daily_log(DailyLogEntry(
                log_date=log_day,
                recommended_category=recommended_category,
                rationale_excerpt=(rationale or "")[:500] or None,
                usefulness=usefulness,
                persuasiveness=persuasiveness,
                followed=followed_code,
                next_session_feeling=next_feeling,
                notes=notes.strip() or None,
            ))
            if existing:
                st.success(f"Päevalogi uuendatud ({log_day.isoformat()}).")
            else:
                st.success(f"Päevalogi salvestatud ({log_day.isoformat()}).")


_WEEKDAY_ET = ["Esmaspäev", "Teisipäev", "Kolmapäev", "Neljapäev", "Reede", "Laupäev", "Pühapäev"]
_PHASE_ET = {
    "base": "Baas",
    "build": "Arendus",
    "peak": "Tipp",
    "taper": "Mahalaadimine",
    "race": "Võistlus",
}


def _format_pace(pace_min_per_km: float | None) -> str:
    """Decimal min/km → `M:SS/km`. Empty for missing/zero."""
    if not pace_min_per_km or pace_min_per_km <= 0:
        return ""
    minutes = int(pace_min_per_km)
    seconds = round((pace_min_per_km - minutes) * 60)
    if seconds == 60:
        minutes += 1
        seconds = 0
    return f"{minutes}:{seconds:02d}/km"


def _build_plan_csv(plan) -> bytes:
    """Build a human-friendly UTF-8-with-BOM CSV from a TrainingPlan.

    BOM lets Excel autodetect UTF-8 (so `ä, ö, ü, õ` don't turn into `Ã¤`).
    Headers, weekday, and phase are translated to Estonian; pace is formatted
    as M:SS/km because that's how runners actually read it.
    """
    rows = []
    for w in plan.weeks:
        phase = _PHASE_ET.get(w.phase.lower(), w.phase)
        for s in w.sessions:
            rows.append({
                "Nädal": w.week_number,
                "Faas": phase,
                "Kuupäev": s.session_date.isoformat(),
                "Nädalapäev": _WEEKDAY_ET[s.session_date.weekday()],
                "Trenni tüüp": s.session_type,
                "Intensiivsus": s.intensity_zone,
                "Kestus (min)": int(round(s.duration_min)) if s.duration_min else 0,
                "Distants (km)": round(s.distance_km, 1) if s.distance_km else "",
                "Sihttempo": _format_pace(s.target_pace_min_per_km),
                "Kirjeldus": (s.description or "").replace("\n", " ").strip(),
                "Nädala maht (km)": round(w.target_volume_km, 1),
                "Nädala märkmed": (w.notes or "").replace("\n", " ").strip(),
            })
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig")


def _summary_table(activities: list[TrainingActivity], today: date) -> pd.DataFrame:
    cutoff = today - timedelta(days=13)
    rows = [
        {
            "Kuupäev": a.activity_date.isoformat(),
            "Tüüp": a.notes or a.activity_type,
            "km": round(a.distance_km, 1),
            "min": round(a.duration_min, 0),
            "avg HR": str(a.avg_hr) if a.avg_hr else "—",
            "RPE": str(a.rpe) if a.rpe is not None else "—",
        }
        for a in sorted(activities, key=lambda x: x.activity_date)
        if cutoff <= a.activity_date <= today
    ]
    return pd.DataFrame(rows)


# --- Sidebar --------------------------------------------------------------
cfg = load_config()

# Auth gate: when Supabase is configured, require login OR guest opt-in
# before any UI renders. Without Supabase the app runs in anonymous mode
# against local SQLite — useful for local dev and offline demos.
auth_user = None
if cfg.has_supabase:
    auth_user = auth.render_login_gate()
    if auth_user is None and not auth.is_guest():
        st.stop()

# Coach-mode short-circuit: when the signed-in user's role is 'coach',
# replace the standard athlete-tab UI with the coach dashboard. Coaches
# don't have their own activity/profile data — they read linked athletes'
# rows through Row-Level Security policies in Supabase.
if auth_user and not auth.is_guest():
    user_role = auth.current_user_role()
    if user_role and user_role.role == "coach":
        st.sidebar.title("🏃 Vorm.ai")
        st.sidebar.caption("AI-põhine treeningkoormuse analüüsija")
        auth.render_sidebar_user_panel()
        st.sidebar.divider()
        render_theme_selector(container=st.sidebar)

        coach_store = auth.get_store()
        if coach_store is None:
            st.error("Sisselogimine on katki. Logi sisse uuesti.")
            st.stop()

        render_coach_home(
            coach_store,
            build_athlete_store=auth.get_store_for,
        )
        st.stop()

# Onboarding wizard: shown once when a signed-in user has no saved profile.
# Skipped for guests and anonymous-mode runs — both already work with sample
# defaults and don't have a place to persist what the wizard would capture.
if auth_user and not auth.is_guest():
    existing_profile = _load_initial_profile()
    has_saved_profile = (
        st.session_state.get(_PROFILE_CACHE_KEY) != _PROFILE_MISSING
        and isinstance(st.session_state.get(_PROFILE_CACHE_KEY), AthleteProfile)
    )
    if should_show_onboarding(has_profile=has_saved_profile):
        def _save_onboarding_profile(p: AthleteProfile) -> None:
            _get_user_store().save_profile(p)
            st.session_state[_PROFILE_CACHE_KEY] = p

        render_onboarding_wizard(
            user_email=auth_user.email,
            on_complete=_save_onboarding_profile,
        )
        st.stop()

st.sidebar.title("🏃 Vorm.ai")
st.sidebar.caption("AI-põhine treeningkoormuse analüüsija")

if auth_user or auth.is_guest():
    auth.render_sidebar_user_panel()
    st.sidebar.divider()

# Athlete-side coach link panel: lets athletes paste a coach's invite code
# and see which coach(es) are currently linked. Only renders for signed-in
# athletes (coaches have their own dashboard; guests / anon mode skip).
athlete_coach_store = None
if auth_user and not auth.is_guest():
    athlete_coach_store = auth.get_store()
    if athlete_coach_store is not None:
        render_athlete_coach_panel(athlete_coach_store)
        st.sidebar.divider()

_consume_strava_oauth_callback()
strava_connection = _load_saved_strava_connection(cfg)

data_source_options = [_SOURCE_MANUAL, _SOURCE_CSV, _SOURCE_STRAVA, _SOURCE_GARMIN]

source = st.sidebar.radio(
    "Andmeallikas",
    data_source_options,
    index=0,
    key=_DATA_SOURCE_KEY,
    help=(
        "Käsitsi lisamine alustab tühjalt. Demo jaoks kasuta all olevat "
        "nuppu; oma andmete jaoks lae CSV või ühenda andmeallikas."
    ),
)
days = st.sidebar.slider(
    "Päevade arv",
    min_value=28,
    max_value=180,
    value=90,
    step=7,
    help="Määrab demoandmete, Strava päringu ja ajaloovaadete akna pikkuse.",
)

if source != _SOURCE_MANUAL:
    st.session_state[_DEMO_DATA_KEY] = False

use_demo_data = source == _SOURCE_MANUAL and bool(st.session_state.get(_DEMO_DATA_KEY))
if source == _SOURCE_MANUAL:
    if use_demo_data:
        st.sidebar.success(f"Demoandmed aktiivsed ({days} päeva).")
        if st.sidebar.button("Tühjenda demoandmed", width="stretch"):
            st.session_state[_DEMO_DATA_KEY] = False
            st.rerun()
    else:
        st.sidebar.caption("Käsitsi lisamine alustab ilma treeningandmeteta.")
        if st.sidebar.button("Täida demoandmetega", width="stretch"):
            st.session_state[_DEMO_DATA_KEY] = True
            st.rerun()

uploaded_csv = None
if source == _SOURCE_CSV:
    uploaded_csv = st.sidebar.file_uploader(
        "Lae Strava-eksport või natiivformaadis CSV",
        type=["csv"],
        help="Natiivne formaat: id, activity_date, activity_type, distance_km, duration_min, avg_hr, rpe, notes. "
        "Strava-eksport (Activity Date, Distance jne) töötab samuti.",
    )

if source == _SOURCE_GARMIN:
    st.sidebar.text_input(
        "Garmin GPX-i ekspordi kaust",
        key="garmin_folder",
        placeholder="C:/Users/.../GarminExport",
        help="Garmin Connect → tegevuse leht → ⚙ → Export GPX. Lae kõik failid ühte kausta. "
        "Project Plan §5 Risk 2 fallback Stravale.",
    )

strava_connection = _render_strava_connection_panel(source, cfg, strava_connection)

st.sidebar.divider()

profile = _render_profile_editor(_load_initial_profile())
_autosave_profile(profile)

# Load activities before the date picker so we can default the date to the
# latest activity. Otherwise picking today() on a stale dataset shows
# ACWR=0/TRIMP=0 because the 7-day window is empty.
activities = _get_activities(
    source,
    uploaded_csv,
    days,
    cfg,
    strava_connection=strava_connection,
    use_demo_data=use_demo_data,
)
has_activities = bool(activities)
manual_without_history = source == _SOURCE_MANUAL and not has_activities
latest_activity_date = max((a.activity_date for a in activities), default=None)
data_context_key = _activity_context_key(source, use_demo_data, activities)

# Reset the widget's session_state when (a) it has never been set, or (b) the
# stored choice is now past the loaded dataset — the latter handles the case
# where the user switches from sample data (latest = today) to a stale CSV
# export (latest = weeks ago) and the cached date is out of range.
default_date = latest_activity_date or date.today()
stored = st.session_state.get("analysis_date")
if stored is None or (latest_activity_date and stored > latest_activity_date):
    st.session_state["analysis_date"] = default_date

st.sidebar.divider()
analysis_date: date = st.sidebar.date_input(
    "Analüüsi kuupäev",
    key="analysis_date",
    help="Vaikimisi viimase laaditud trenni kuupäev. Muuda, et analüüsida mõnd varasemat hetke.",
)

st.sidebar.divider()
if cfg.has_llm:
    st.sidebar.success(f"LLM aktiivne: {cfg.llm_provider} / {cfg.llm_model}")
else:
    st.sidebar.info("LLM pole seadistatud — reeglivastus kuvatakse. Lisa ANTHROPIC_API_KEY .env-i täieliku analüüsi jaoks.")

st.sidebar.divider()
render_theme_selector(container=st.sidebar)

st.sidebar.divider()
st.sidebar.markdown(
    "**⚠ Vastutuspiir.** Tööriist on **otsustustugi**, mitte asendaja "
    "treenerile ega arstile. **Vigastuse, valu või haiguskahtluse puhul** "
    "lõpeta treening ja pöördu spetsialisti poole — mudel ei tee meditsiinilist "
    "hinnangut."
)

# --- Main -----------------------------------------------------------------

st.title("Treeningkoormuse analüüs")
# Top-level disclaimer banner. Repeats the sidebar callout so users entering
# from a deep-link or scroll-to-tab still see the limits before reading any
# recommendation. Project Plan §5 "Vastutuspiir".
with st.container(border=True):
    st.markdown(
        "**Vastutuspiir.** Vorm.ai on **otsustustugi** — andmepõhine teine arvamus, "
        "mitte asendaja kvalifitseeritud treenerile ega arstile. Soovitus tugineb "
        "ainult sinu logitud objektiivsele koormusele + subjektiivsele enesetundele; "
        "**vigastuse, ägeda valu või haiguskahtluse puhul** lõpeta treening ja "
        "pöördu treeneri/arsti poole. Mudel ei diagnoosi ega ravi."
    )

if not has_activities:
    if manual_without_history:
        st.info(
            "Käsitsi lisamine alustab tühjalt. Lae vasakult CSV, ühenda andmeallikas "
            "või vajuta **Täida demoandmetega**, et näidist kohe proovida. "
            "Tänase plaani ja treeningkava kohta saad LLM-ilt küsida ka ilma ajaloofailita."
        )
    else:
        st.info("Andmed pole veel laaditud. Kontrolli vasakul valitud andmeallikat või lae CSV.")
        st.stop()

if latest_activity_date and analysis_date > latest_activity_date:
    gap_days = (analysis_date - latest_activity_date).days
    st.warning(
        f"Valitud kuupäev on {gap_days} päeva pärast viimast trenni "
        f"({latest_activity_date.isoformat()}). 7-päeva aknas ei pruugi olla andmeid — "
        "ACWR ja akuutne TRIMP võivad näidata 0. Liiguta kuupäev tagasi viimasele trenni-päevale."
    )

current_summary = summarize_load(activities, profile, as_of=analysis_date)
daily_load = build_load_timeseries(activities, profile, end=analysis_date)

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(
    ["Tänane soovitus", "Koormuse ajalugu", "Tippajad",
     "Retrospektiivne test", "Treeningkava", "Päevalogi", "Treeneri võrdlus"]
)

# --- Tab 1: today's recommendation
with tab1:
    st.subheader(f"Analüüsi seisuga {analysis_date.isoformat()}")
    if athlete_coach_store is not None:
        _render_live_coach_decision_for_day(athlete_coach_store, analysis_date)

    summary = current_summary

    if not has_activities:
        st.info(
            "Treeningajalugu puudub, seega ACWR/TRIMP numbrid on tühjad. "
            "LLM kasutab sinu profiili, tänast plaani ja subjektiivseid sisendeid."
        )

    col_metrics = st.columns(4)
    col_metrics[0].metric(
        "ACWR",
        f"{summary.acwr:.2f}" if summary.acwr is not None else "—",
        help="Acute 7 p / Chronic 28 p keskmine koormus. Sweet-spot 0.8–1.3.",
    )
    col_metrics[1].metric("7 p TRIMP", f"{summary.acute_7d:.0f}")
    col_metrics[2].metric("28 p TRIMP", f"{summary.chronic_28d:.0f}")
    col_metrics[3].metric(
        "Monotoonsus",
        f"{summary.monotony:.2f}" if summary.monotony is not None else "—",
        help="Foster monotony = 7-päeva mean / std. ≥ 2.0 = vähe varieeruvust.",
    )

    render_load_metrics_explainer()

    if has_activities:
        hr_coverage = sum(1 for a in activities if a.avg_hr) / len(activities)
    else:
        hr_coverage = 0.0
    if has_activities and hr_coverage < 0.5:
        threshold = profile.effective_threshold_pace
        if threshold:
            st.info(
                f"Pulsiandmeid ainult {hr_coverage * 100:.0f}%-l treeningutest. "
                f"Kasutan tempo-põhist fallback'i (rTSS-stiilis), threshold-tempo **{threshold:.2f} min/km**. "
                f"Sea profiilis täpselt või lisa 10 km PB."
            )
        else:
            st.warning(
                f"Pulsiandmeid ainult {hr_coverage * 100:.0f}%-l treeningutest ja künnis-tempo pole määratud. "
                f"Koormus arvutub 0-ks. Lisa profiili threshold-tempo või 10 km PB."
            )

    st.divider()

    c1, c2 = st.columns([1, 1])
    with c1:
        st.markdown("#### Tänane plaan + subjektiivsed sisendid")
        today_plan = st.text_area(
            "Täna planeeritud treening",
            placeholder="Nt: 8×400 m 75 s pauside vahel; või 45 min kerge aeroobne.",
            height=100,
        )
        col_a, col_b = st.columns(2)
        rpe_yesterday = col_a.slider("Eilse treeningu RPE (1–10)", min_value=1, max_value=10, value=5)
        sleep_hours = col_b.number_input("Uneaeg (h)", min_value=0.0, max_value=14.0, value=7.5, step=0.5)
        col_c, col_d = st.columns(2)
        stress = col_c.slider("Stressitase (1–5)", min_value=1, max_value=5, value=2)
        illness = col_d.checkbox("Haigus / tundsin end halvasti")
        notes = st.text_input("Märkmed (valikuline)", placeholder="Nt: kerge köha, jalg pinges...")

    with c2:
        st.markdown("#### Ohutusreeglid")
        subjective = DailySubjective(
            entry_date=analysis_date,
            rpe_yesterday=rpe_yesterday,
            sleep_hours=sleep_hours,
            stress_level=stress,
            illness=illness,
            notes=notes or None,
        )
        verdict = evaluate_safety_rules(summary, subjective)
        _render_safety_flags(verdict)

        # Statistiline turvafilter (PROJECT_PLAN §2): kui ACWR trend tõuseb,
        # näita projektsiooni ja "ületab ohu" hoiatust enne reegli fire-imist.
        acwr_ts = acwr_series(daily_load)["acwr"]
        acwr_forecast = forecast_acwr(acwr_ts)
        forecast_msg = forecast_message(acwr_forecast)
        if forecast_msg:
            if acwr_forecast and acwr_forecast.crosses_danger_in_days is not None:
                st.warning(f"📈 {forecast_msg}")
            else:
                st.info(f"📈 {forecast_msg}")

    evaluation_context_key = _evaluation_context_key(
        data_context_key=data_context_key,
        profile=profile,
        today_plan=today_plan,
        subjective=subjective,
        analysis_date=analysis_date,
    )

    st.divider()

    if st.button("Hinda koormust", type="primary", width="stretch"):
        prompt_bundle = build_prompt(
            profile=profile,
            activities=activities,
            summary=summary,
            verdict=verdict,
            today_plan=today_plan,
            subjective=subjective,
            today=analysis_date,
        )

        llm_result = None
        if cfg.has_llm and today_plan.strip():
            with st.spinner("Küsin LLM-lt soovitust..."):
                try:
                    llm_result = generate_recommendation(prompt_bundle, cfg)
                except LLMNotAvailable as exc:
                    st.warning(f"LLM kättesaamatu: {exc}. Näitan reeglipõhist vastust.")
                except Exception as exc:
                    st.error(f"LLM viga: {exc}")
        elif not today_plan.strip():
            st.warning("Sisesta täna planeeritud treening, et saada LLM-soovitust.")

        # Stash the evaluation so it survives the rerun that fires when the
        # daily-log form is submitted. Without this, the form is conditionally
        # rendered inside an `if st.button()` and Streamlit's "button True only
        # on the rerun after click" semantics means a submit causes the entire
        # block (including the form's submit handler) to vanish before it
        # runs — daily logs silently never persist.
        st.session_state["last_evaluation"] = {
            "evaluation_context_key": evaluation_context_key,
            "verdict": verdict,
            "llm_result": llm_result,
            "prompt_text": prompt_bundle.user,
        }

    eval_state = st.session_state.get("last_evaluation")
    if (
        eval_state
        and eval_state.get("evaluation_context_key") == evaluation_context_key
    ):
        _render_verdict_box(eval_state["verdict"], eval_state["llm_result"])

        with st.expander("Näita LLM-i kasutatud prompti (diagnostika)"):
            st.code(eval_state["prompt_text"], language="markdown")

        st.divider()
        _render_daily_log_form(
            log_day=analysis_date,
            recommended_category=(
                eval_state["llm_result"].category
                if eval_state["llm_result"]
                else eval_state["verdict"].recommendation.value
            ),
            rationale=(
                eval_state["llm_result"].rationale
                if eval_state["llm_result"]
                else None
            ),
        )

# --- Tab 2: history
with tab2:
    daily = daily_load
    if not has_activities:
        st.info("Koormuse ajalugu ilmub siia siis, kui lisad CSV/andmeallika või käivitad demoandmed.")
    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(acwr_chart(daily), width="stretch")
    with col2:
        st.plotly_chart(daily_load_chart(daily), width="stretch")

    col3, col4 = st.columns(2)
    with col3:
        st.plotly_chart(weekly_volume_chart(activities), width="stretch")
    with col4:
        st.plotly_chart(rpe_trend_chart(activities, profile), width="stretch")

    st.markdown("#### Fitness / Fatigue / Form (Banister)")
    st.caption(
        "**CTL** (sinine) on krooniline koormus — vorm. **ATL** (punane) on akuutne koormus — väsimus. "
        "**TSB** (roheline, paremal teljel) = CTL − ATL = vorm. Negatiivne TSB = väsinud, "
        "TSB +5…+25 = võistluseks valmis (rohelisel ribal)."
    )
    st.plotly_chart(fitness_form_chart(daily), width="stretch")
    render_fitness_form_explainer()

    st.markdown("#### HR-tsoonide nädalane jaotus")
    st.caption(
        "Iga jooks klassifitseeritakse keskmise pulsi järgi tsooni Z1–Z5 (Karvonen). "
        "Kui pulsiandmeid pole, kasutatakse tempo-suhet künnis-tempoga. "
        "Polariseeritud treening (Seiler): ~80% nädala mahust Z1–Z2, ~20% Z4–Z5."
    )
    st.plotly_chart(hr_zone_distribution_chart(activities, profile), width="stretch")

    st.markdown("#### Viimase 14 päeva kokkuvõte")
    recent_summary = _summary_table(activities, analysis_date)
    if recent_summary.empty:
        st.info("Viimase 14 päeva treeninguid pole.")
    else:
        st.dataframe(recent_summary, width="stretch", hide_index=True)

    # Post-hoc RPE/notes editing. Persists to the local SQLite cache that
    # `fetch_with_cache` reads from, so the next rerun shows the edits. Only
    # offered for Strava-sourced activities — those have stable IDs that
    # survive across runs. CSV/Garmin/sample IDs are ephemeral, so editing
    # them would feel broken (next rerun would re-generate different IDs).
    if source == _SOURCE_STRAVA and has_activities:
        with st.expander("✏️ Muuda treeningu RPE / märkmeid"):
            recent_activities = sorted(
                activities, key=lambda a: a.activity_date, reverse=True,
            )[:30]
            label_for = {
                a.id: (
                    f"{a.activity_date.isoformat()} — {a.distance_km:.1f} km"
                    + (f" — {(a.notes or '').strip()[:30]}" if a.notes else "")
                )
                for a in recent_activities
            }
            selected_id = st.selectbox(
                "Treening",
                options=[a.id for a in recent_activities],
                format_func=lambda aid: label_for[aid],
                key="edit_activity_select",
            )
            selected = next(a for a in recent_activities if a.id == selected_id)
            col_rpe, col_notes = st.columns([1, 2])
            new_rpe = col_rpe.slider(
                "RPE (1-10)",
                min_value=1, max_value=10,
                value=selected.rpe or 5,
                key=f"edit_rpe_{selected.id}",
                help="Subjektiivne raskushinnang. Salvestub lokaalsesse Strava-vahemällu, "
                "ei sünkroniseeru tagasi Stravasse.",
            )
            new_notes = col_notes.text_input(
                "Märkmed",
                value=selected.notes or "",
                key=f"edit_notes_{selected.id}",
                placeholder="Nt: kerge köha, jalg pinges, hea tempo viimasel km-l.",
            )
            if st.button("💾 Salvesta", key=f"save_edit_{selected.id}", type="primary"):
                try:
                    _get_local_store().set_rpe(
                        selected.id, int(new_rpe), new_notes.strip() or None,
                    )
                except Exception as exc:
                    st.error(f"Salvestamine ebaõnnestus: {exc}")
                else:
                    st.success("Salvestatud. Andmed värskenduvad kohe.")
                    st.rerun()

# --- Tab 3: personal bests
with tab3:
    st.markdown(
        "Tippajad on tuvastatud iga jooksu põhjal, mille distants on standardse võistlus-distantsi "
        "lähedal (±5%). See püüab nii võistlused kui tempo-trennid, mille pikkus juhtus täpselt "
        "5/10 km olema — kummalgi juhul on jooksja praeguse vormi-lae markerina kasutatav."
    )

    pbs = find_personal_bests(activities)
    if not pbs:
        st.info("Ühtegi standard-distantsi PB-d ei tuvastatud. Lae rohkem andmeid.")
    else:
        rows = [
            {
                "Distants": p.distance_label,
                "Aeg": p.time_formatted,
                "Tempo": f"{p.pace_min_per_km:.2f} min/km",
                "Tegelik km": f"{p.activity_distance_km:.2f}",
                "Kuupäev": p.activity_date.isoformat(),
                "Kommentaar": (p.activity_notes or "")[:60],
            }
            for p in pbs
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

        st.markdown("#### Progressioon ajas")
        labels_with_data = [(label, km) for label, km in PB_DISTANCES if any(p.distance_label == label for p in pbs)]
        if labels_with_data:
            chosen = st.selectbox(
                "Vali distants",
                options=[label for label, _ in labels_with_data],
                index=0,
                key="pb_distance",
            )
            chosen_km = next(km for label, km in labels_with_data if label == chosen)
            st.plotly_chart(pb_progression_chart(activities, chosen, chosen_km), width="stretch")

# --- Tab 4: retrospective test
with tab4:
    st.markdown(
        "Retrospektiivne test: vali varasem kuupäev, mille puhul näed mudeli soovitust, "
        "arvestades ainult *selleks päevaks* teadaolevaid andmeid. Järgi plaani "
        "(10 varasemat päeva) — võrdle oma tegeliku otsusega."
    )

    if not has_activities:
        st.info("Retrospektiivne test vajab treeningajalugu. Tänase plaani jaoks kasuta esimest tabi.")
    else:
        earliest = min(a.activity_date for a in activities)
        latest = max(a.activity_date for a in activities)
        if latest <= earliest + timedelta(days=30):
            st.warning("Liiga lühike andmeloend retrospektiivseks testiks (vaja ≥ 30 päeva).")
        else:
            retro_date = st.date_input(
                "Retrospektiivne kuupäev",
                value=latest - timedelta(days=7),
                min_value=earliest + timedelta(days=28),
                max_value=latest,
                key="retro_date",
            )
            retro_plan = st.text_input(
                "Mida sa sel päeval tegid (või pidid tegema)?",
                placeholder="Nt: 5x1000m @ 3:25",
                key="retro_plan",
            )
            retro_rpe = st.slider("Eilse treeningu RPE", 1, 10, 5, key="retro_rpe")

            if st.button("Käivita retrospektiivne hindamine"):
                past_activities = [a for a in activities if a.activity_date <= retro_date]
                retro_summary = summarize_load(past_activities, profile, as_of=retro_date)
                retro_subjective = DailySubjective(
                    entry_date=retro_date,
                    rpe_yesterday=retro_rpe,
                )
                retro_verdict = evaluate_safety_rules(retro_summary, retro_subjective)

                st.markdown(f"#### Seis {retro_date.isoformat()} kohta")
                col_a, col_b, col_c = st.columns(3)
                col_a.metric("ACWR", f"{retro_summary.acwr:.2f}" if retro_summary.acwr else "—")
                col_b.metric("7 p TRIMP", f"{retro_summary.acute_7d:.0f}")
                col_c.metric("28 p TRIMP", f"{retro_summary.chronic_28d:.0f}")

                retro_llm = None
                if cfg.has_llm and retro_plan.strip():
                    retro_prompt = build_prompt(
                        profile=profile,
                        activities=past_activities,
                        summary=retro_summary,
                        verdict=retro_verdict,
                        today_plan=retro_plan,
                        subjective=retro_subjective,
                        today=retro_date,
                    )
                    with st.spinner("LLM retrospektiivne hinnang..."):
                        try:
                            retro_llm = generate_recommendation(retro_prompt, cfg)
                        except Exception as exc:
                            st.error(f"LLM viga: {exc}")

                _render_safety_flags(retro_verdict)
                _render_verdict_box(retro_verdict, retro_llm)

# --- Tab 5: training plan generator
with tab5:
    st.markdown(
        "Genereeri **täielik päev-haaval treeningkava** võistluseks. Mudel arvestab sinu profiili, "
        "tippaegu, praegust vormi (ACWR/monotoonsus) ja valitud sihtaega. Kulu ~€0.001–0.01 per plaan "
        "sõltuvalt mudelist ja nädalate arvust."
    )

    if not cfg.has_llm:
        st.warning("LLM pole seadistatud — plaani genereerimine vajab LLM-i. Lisa API võti .env-i.")
    else:
        col1, col2, col3 = st.columns(3)
        event_name = col1.text_input("Võistluse nimi", value="Tallinna 10 km", key="plan_event")
        distance_km = col2.number_input(
            "Distants (km)", min_value=1.0, max_value=100.0, value=10.0, step=0.1, key="plan_distance"
        )
        event_date = col3.date_input(
            "Võistluse kuupäev",
            value=analysis_date + timedelta(weeks=10),
            min_value=analysis_date + timedelta(weeks=1),
            key="plan_event_date",
        )

        col4, col5 = st.columns(2)
        target_min = col4.number_input(
            "Sihtaeg (minutid)",
            min_value=3.0, max_value=360.0, value=35.0, step=0.25,
            help="Kokku minutites. Nt 34:40 = 34.67.",
            key="plan_target_min",
        )
        plan_start_date = col5.date_input(
            "Plaani algus",
            value=analysis_date,
            min_value=analysis_date,
            max_value=event_date - timedelta(days=7),
            key="plan_start",
        )

        weeks_between = (event_date - plan_start_date).days // 7
        st.caption(f"Plaani pikkus: **{weeks_between} nädalat**, {weeks_between * 7} seansi-kirjet.")

        if st.button(
            "Genereeri treeningkava",
            type="primary",
            width="stretch",
            key="plan_generate",
        ):
            goal = PlanGoal(
                event_name=event_name,
                distance_km=float(distance_km),
                target_time_minutes=float(target_min),
                event_date=event_date,
            )
            summary_for_plan = current_summary if has_activities else None

            with st.spinner(f"Genereerin {weeks_between}-nädalast kava ({cfg.llm_model})..."):
                try:
                    plan = generate_training_plan(
                        profile=profile,
                        goal=goal,
                        summary=summary_for_plan,
                        plan_start=plan_start_date,
                        config=cfg,
                    )
                except (PlanGenerationError, LLMNotAvailable) as exc:
                    st.error(f"Plaani genereerimine ebaõnnestus: {exc}")
                    st.stop()
                except Exception as exc:
                    st.error(f"Ootamatu viga: {exc}")
                    st.stop()

            st.success(
                f"Plaan valmis: {plan.total_weeks} nädalat, {len(plan.all_sessions)} seanssi "
                f"(mudel: `{plan.model}`)"
            )

            if plan.overview:
                st.markdown("### Ülevaade")
                st.write(plan.overview)

            st.markdown("### Nädalad")
            for week in plan.weeks:
                with st.expander(
                    f"Nädal {week.week_number} ({week.week_start.isoformat()}) — "
                    f"{week.phase.upper()}, siht {week.target_volume_km:.0f} km",
                    expanded=(week.week_number == 1),
                ):
                    if week.notes:
                        st.caption(week.notes)
                    # Stringify numeric columns where missing values use em-dash —
                    # mixed float/str columns make pyarrow log a noisy warning.
                    rows = [
                        {
                            "Kuupäev": s.session_date.isoformat(),
                            "Nädalapäev": ["E", "T", "K", "N", "R", "L", "P"][s.session_date.weekday()],
                            "Tüüp": s.session_type,
                            "Tsoon": s.intensity_zone,
                            "Kestus (min)": int(round(s.duration_min)),
                            "km": f"{s.distance_km:.1f}" if s.distance_km else "—",
                            "Sihttempo": _format_pace(s.target_pace_min_per_km) or "—",
                            "Kirjeldus": s.description,
                        }
                        for s in week.sessions
                    ]
                    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

            st.markdown("### Eksport")
            csv_bytes = _build_plan_csv(plan)
            st.download_button(
                "Lae alla CSV-failina",
                data=csv_bytes,
                file_name=f"treeningkava_{goal.event_name.replace(' ', '_')}_{goal.event_date.isoformat()}.csv",
                mime="text/csv",
            )

# --- Tab 6: daily usage log history (Project Plan §4.3)
with tab6:
    st.markdown(
        "Päevalogi kogub lühikese tagasiside iga kasutuskorra kohta: kui kasulik "
        "soovitus oli, kas järgisid seda ning kuidas esimene järgmine treening pärast "
        "soovitust tundus. Need andmed lähevad valideerimise §4.3 analüüsi."
    )

    log_store = _get_user_store()
    logs = log_store.list_daily_logs()
    if not logs:
        st.info(
            "Päevalogisid pole veel. Mine **Tänane soovitus**-tabi, vajuta "
            "_Hinda koormust_ ja täida päevalogi vorm."
        )
    else:
        # Streak banner — sits above the table so the discipline metric is
        # the first thing the user sees on this tab.
        today_real = date.today()
        current_streak = streak_count(logs, today_real)
        best_streak = longest_streak(logs)
        streak_cols = st.columns([1, 1, 2])
        streak_cols[0].metric(
            "🔥 Praegune seeria",
            f"{current_streak} päeva",
            help="Järjestikused päevad, mil oled päevalogi täitnud (kuni eilseni / täna).",
        )
        streak_cols[1].metric(
            "🏆 Pikim seeria",
            f"{best_streak} päeva",
            help="Pikim järjestikune seeria kogu logimise ajaloo jooksul.",
        )
        with streak_cols[2]:
            if current_streak >= 14:
                st.success(
                    f"§4.3 valideerimise lävi ({current_streak} ≥ 14 päeva) on täidetud."
                )
            else:
                st.info(
                    f"§4.3 valideerimisele on vaja 14 järjestikust päeva — "
                    f"jäänud **{max(14 - current_streak, 0)}**."
                )

        st.plotly_chart(
            log_heatmap_chart(logs, today_real, weeks=12),
            width="stretch",
        )
        st.divider()

        followed_map = {"yes": "Jah", "partial": "Osaliselt", "no": "Ei", None: "—"}
        rows = [
            {
                "Kuupäev": e.log_date.isoformat(),
                "Soovitus": e.recommended_category,
                "Kasulikkus": e.usefulness if e.usefulness else "—",
                "Veenvus": e.persuasiveness if e.persuasiveness else "—",
                "Järgisin": followed_map.get(e.followed, "—"),
                "Järgmise treeningu enesetunne": e.next_session_feeling if e.next_session_feeling else "—",
                "Märkmed": (e.notes or "")[:80],
            }
            for e in logs
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

        st.markdown("#### Koondnäitajad")
        col1, col2, col3, col4 = st.columns(4)
        with_useful = [e.usefulness for e in logs if e.usefulness]
        with_pers = [e.persuasiveness for e in logs if e.persuasiveness]
        followed_yes = sum(1 for e in logs if e.followed == "yes")
        feel = [e.next_session_feeling for e in logs if e.next_session_feeling]
        col1.metric(
            "Päevi logitud", len(logs),
            help="Iga päev = üks sissekanne. Eesmärk §4.3: 14 päeva järjest.",
        )
        col2.metric(
            "Keskmine kasulikkus",
            f"{sum(with_useful) / len(with_useful):.1f}" if with_useful else "—",
        )
        col3.metric(
            "Keskmine veenvus",
            f"{sum(with_pers) / len(with_pers):.1f}" if with_pers else "—",
        )
        col4.metric(
            "Järgisid soovitust",
            f"{followed_yes}/{len(logs)}",
            help="Mitu päeva valisid 'Jah' (mitte 'Osaliselt' ega 'Ei').",
        )
        if feel:
            st.caption(
                f"Järgmise treeningu enesetunde keskmine: **{sum(feel) / len(feel):.1f}/5** "
                "(1 = väga halb, 3 = tavaline, 5 = väga hea) "
                f"(n={len(feel)} päeva)"
            )

        # Convenience: CSV download for the project report
        csv_bytes = pd.DataFrame([
            {
                "log_date": e.log_date.isoformat(),
                "recommended_category": e.recommended_category,
                "usefulness": e.usefulness,
                "persuasiveness": e.persuasiveness,
                "followed": e.followed,
                "next_session_feeling": e.next_session_feeling,
                "notes": e.notes or "",
                "rationale_excerpt": e.rationale_excerpt or "",
            } for e in logs
        ]).to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "📥 Lae logi CSV-na",
            data=csv_bytes,
            file_name=f"vorm_daily_log_{date.today().isoformat()}.csv",
            mime="text/csv",
        )

# --- Tab 7: coach comparison (Project Plan §4.2) -------------------------
_CATEGORY_OPTIONS = (
    "Jätka plaanipäraselt",
    "Vähenda intensiivsust",
    "Alternatiivne treening",
    "Lisa taastumispäev",
)
_CAREFUL_CATEGORIES = {
    "Vähenda intensiivsust", "Alternatiivne treening", "Lisa taastumispäev",
}


def _agreement_bucket(model: str, coach: str) -> str:
    """match / close / wrong — same buckets as scripts/validate.py uses for §4.

    `close` = both fall in the "careful" family (any reduce/alternative/recover),
    `wrong` = one says "Jätka plaanipäraselt" while the other says be careful.
    """
    if model == coach:
        return "match"
    if model in _CAREFUL_CATEGORIES and coach in _CAREFUL_CATEGORIES:
        return "close"
    return "wrong"


with tab7:
    st.markdown(
        "**Treeneri pimemenetluse võrdlus (§4.2).** Treener sisestab Vorm.ai "
        "väljundit nägemata oma päevaotsuse iga päeva kohta, mille puhul on "
        "olemas päevalogi. Kattuvus mõõdetakse kolmes ämbris: **match** (täpne "
        "kategooria), **close** (mõlemad ettevaatlikud, aga erinev tüüp), "
        "**wrong** (üks ütleb 'jätka', teine 'olge ettevaatlikud')."
    )

    coach_store = _get_user_store()

    # If the athlete is linked to coaches, tell them their coach can enter
    # decisions directly — the local form is then a fallback for in-person
    # interview transcription (or when the coach isn't on Vorm.ai).
    linked_coach_names = []
    if coach_store is not None and auth_user and not auth.is_guest():
        try:
            linked_coach_names = list_linked_coach_names(coach_store)
        except Exception:
            linked_coach_names = []
        if linked_coach_names:
            names_str = ", ".join(f"**{n}**" for n in linked_coach_names)
            st.success(
                f"🧑‍🏫 Sinuga on seotud: {names_str}. Tema otsused ilmuvad "
                "siia tabelisse automaatselt — alloleva vormi saad jätta "
                "kasutamata, välja arvatud juhul, kui transkribeerid intervjuust."
            )

    existing_logs = coach_store.list_daily_logs()
    try:
        existing_decisions = coach_store.list_coach_decisions()
    except Exception:
        existing_decisions = []

    log_by_date = {e.log_date: e for e in existing_logs}
    if existing_decisions:
        st.markdown("#### Treeneri otsused")
        st.dataframe(
            pd.DataFrame(_coach_decision_table_rows(existing_decisions, log_by_date)),
            hide_index=True,
            width="stretch",
        )
        latest = max(existing_decisions, key=lambda d: d.decision_date)
        if latest.decision_date >= date.today() - timedelta(days=7):
            _render_coach_decision_card(latest)

    # --- Entry form
    manual_form_label = (
        "➕ Manuaalne varuvariant: sisesta treeneri otsus"
        if linked_coach_names
        else "➕ Sisesta treeneri otsus"
    )
    with st.expander(
        manual_form_label,
        expanded=not existing_decisions and not linked_coach_names,
    ):
        log_dates = sorted({e.log_date for e in existing_logs}, reverse=True)
        if not log_dates:
            st.info(
                "Päevalogi kirjeid pole — sisesta enne **Päevalogi** tabis vähemalt "
                "üks päev, et oleks võrreldav baas."
            )
        else:
            day_options = {d.isoformat(): d for d in log_dates}
            decisions_by_date = {d.decision_date: d for d in existing_decisions}
            with st.form("vorm_coach_decision_form", clear_on_submit=False):
                selected_label = st.selectbox(
                    "Kuupäev",
                    options=list(day_options.keys()),
                    key="_vorm_coach_date",
                )
                selected_day = day_options[selected_label]
                existing = decisions_by_date.get(selected_day)

                # Show coach the date + activity context but NOT the model's
                # category — keeps the blind-comparison methodology intact.
                same_day_log = next(
                    (e for e in existing_logs if e.log_date == selected_day), None,
                )
                if same_day_log:
                    st.caption(
                        f"Mudeli soovitus selle päeva kohta on varjatud — sisesta "
                        f"oma otsus enne, kui võrdluse all näed. "
                        f"({selected_day.isoformat()})"
                    )

                coach_name = st.text_input(
                    "Treeneri nimi",
                    value=existing.coach_name if existing else "Ille Kukk",
                    key="_vorm_coach_name",
                )
                default_idx = (
                    _CATEGORY_OPTIONS.index(existing.recommended_category)
                    if existing and existing.recommended_category in _CATEGORY_OPTIONS
                    else 0
                )
                category = st.radio(
                    "Treeneri soovitus",
                    options=_CATEGORY_OPTIONS,
                    index=default_idx,
                    key="_vorm_coach_category",
                )
                rationale = st.text_area(
                    "Põhjendus (1-2 lauset)",
                    value=existing.rationale if existing and existing.rationale else "",
                    key="_vorm_coach_rationale",
                    placeholder="Nt: ACWR liiga kõrge, eile RPE 8 — täna kerge.",
                    height=80,
                )
                notes = st.text_input(
                    "Märkmed (valikuline)",
                    value=existing.notes if existing and existing.notes else "",
                    key="_vorm_coach_notes",
                )
                submitted = st.form_submit_button(
                    "💾 Salvesta otsus", type="primary", width="stretch",
                )
                if submitted:
                    try:
                        coach_store.save_coach_decision(CoachDecision(
                            decision_date=selected_day,
                            coach_name=coach_name.strip() or "Ille Kukk",
                            recommended_category=category,
                            rationale=rationale.strip() or None,
                            notes=notes.strip() or None,
                        ))
                    except Exception as exc:
                        st.error(f"Salvestamine ebaõnnestus: {exc}")
                    else:
                        st.success(f"Otsus salvestatud ({selected_day.isoformat()}).")
                        st.rerun()

    # --- Comparison results
    if not existing_decisions:
        st.info(
            "Treeneri otsuseid pole veel sisestatud. Lisa esimene otsus ülal — "
            "kattuvuse arvutus tekib kohe, kui mõlemad pooled on olemas."
        )
    else:
        pairs = []
        for d in existing_decisions:
            log = log_by_date.get(d.decision_date)
            if log is None:
                continue
            pairs.append({
                "Kuupäev": d.decision_date.isoformat(),
                "Mudel": log.recommended_category,
                "Treener": d.recommended_category,
                "Kattuvus": _agreement_bucket(log.recommended_category, d.recommended_category),
                "Põhjus (treener)": (d.rationale or "")[:80],
            })

        if not pairs:
            st.warning(
                "Ühelgi treeneri otsuse päeval pole vastavat päevalogi. "
                "Lisa päevalogi sissekanne või vali teine kuupäev."
            )
        else:
            n = len(pairs)
            match = sum(1 for p in pairs if p["Kattuvus"] == "match")
            close = sum(1 for p in pairs if p["Kattuvus"] == "close")
            wrong = sum(1 for p in pairs if p["Kattuvus"] == "wrong")

            metric_cols = st.columns(4)
            metric_cols[0].metric(
                "Võrreldud päevi", n,
                help="§4.2 sihtmäär on 14 järjestikust päeva — kogutud andmete arv.",
            )
            metric_cols[1].metric(
                "✓ Match",
                f"{match} ({match / n * 100:.0f}%)",
                help="Sama kategooria.",
            )
            metric_cols[2].metric(
                "~ Close",
                f"{close} ({close / n * 100:.0f}%)",
                help="Mõlemad ettevaatlikud, erinev tüüp.",
            )
            metric_cols[3].metric(
                "✗ Wrong",
                f"{wrong} ({wrong / n * 100:.0f}%)",
                help="Mudel ütleb jätka, treener ettevaatust või vastupidi.",
            )

            st.dataframe(
                pd.DataFrame(pairs).rename(columns={"Kattuvus": "Kattuvuse ämber"}),
                hide_index=True,
                width="stretch",
            )

            # CSV download for the project report
            coach_csv = pd.DataFrame([
                {
                    "decision_date": d.decision_date.isoformat(),
                    "coach_name": d.coach_name,
                    "coach_category": d.recommended_category,
                    "coach_rationale": d.rationale or "",
                    "coach_notes": d.notes or "",
                    "model_category": (
                        log_by_date[d.decision_date].recommended_category
                        if d.decision_date in log_by_date else ""
                    ),
                    "agreement": (
                        _agreement_bucket(
                            log_by_date[d.decision_date].recommended_category,
                            d.recommended_category,
                        )
                        if d.decision_date in log_by_date else ""
                    ),
                }
                for d in existing_decisions
            ]).to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "📥 Lae treeneri võrdluse CSV-na",
                data=coach_csv,
                file_name=f"vorm_coach_comparison_{date.today().isoformat()}.csv",
                mime="text/csv",
            )

    st.divider()
    st.markdown("#### Valideerimisaruanne (PDF)")
    st.caption(
        "Pakib profiili, §4.3 igapäevase logimise koondnäitajad ja §4.2 treeneri "
        "võrdluse ühte A4-PDF-i. Sobib otse projekti-aruandesse lisamiseks."
    )
    try:
        pdf_bytes = build_validation_report(
            profile=profile,
            daily_logs=existing_logs,
            coach_decisions=existing_decisions,
        )
        st.download_button(
            "📄 Lae valideerimisaruanne PDF-na",
            data=pdf_bytes,
            file_name=f"vorm_validation_report_{date.today().isoformat()}.pdf",
            mime="application/pdf",
            type="primary",
        )
    except Exception as exc:
        st.error(f"PDF-i genereerimine ebaõnnestus: {exc}")
