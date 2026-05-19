"""Coach-mode dashboard.

When the signed-in user's role is ``'coach'``, this UI replaces the regular
athlete-tab layout. The coach can:

1. Generate invite codes for new athletes (athlete pastes the code into
   their own sidebar and accepts the consent form → link becomes readable).
2. See linked athletes + their recent daily-log entries (RLS-mediated
   read of ``athlete_profiles`` + ``daily_logs``).
3. Enter blind §4.2 päevaotsuseid for any linked athlete. The decision is
   written into ``public.coach_decisions`` with the athlete's ``user_id``
   (RLS allows this only for active links).

Coaches do NOT see Strava-connection data — the privacy boundary stays
at the metrics level.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from ..data.models import DATA_CONSENT_VERSION
from ..data.storage import CoachDecision
from ..data.supabase_store import SupabaseStore

_CATEGORY_OPTIONS = (
    "Jätka plaanipäraselt",
    "Vähenda intensiivsust",
    "Alternatiivne treening",
    "Lisa taastumispäev",
)

_SELECTED_ATHLETE_KEY = "_vorm_coach_selected_athlete"
_LAST_INVITE_KEY = "_vorm_coach_last_invite_code"
_COACH_SHARE_CONSENT_TEXT = (
    "Treener saab näha sinu sportlase profiili, päevalogi, soovituse ajalugu, "
    "subjektiivseid sisendeid (RPE, uni, stress, haigusmärge, märkmed) ja neist "
    "tuletatud koormusnäitajaid. Need võivad võimaldada tervise, taastumise, "
    "pohmaka või menstruaaltsükli kohta järeldusi. Treener ei näe Strava tokenit, "
    "GPS-rajapunkte ega toorpulsi ridu."
)


def render_coach_home(
    coach_store: SupabaseStore,
    *,
    build_athlete_store: Callable[[str], SupabaseStore | None],
) -> None:
    """Render the coach-mode UI. Caller should ``st.stop()`` afterwards."""
    selected = st.session_state.get(_SELECTED_ATHLETE_KEY)
    if selected:
        athlete_store = build_athlete_store(selected)
        if athlete_store is None:
            st.error("Sportlase andmetele ligipääs puudub. Logi sisse uuesti.")
            st.session_state.pop(_SELECTED_ATHLETE_KEY, None)
            return
        _render_athlete_view(coach_store, selected, athlete_store)
    else:
        _render_home(coach_store, build_athlete_store)


# --- Home: invite + athletes list ------------------------------------------


def _render_home(
    coach_store: SupabaseStore,
    build_athlete_store: Callable[[str], SupabaseStore | None],
) -> None:
    role = coach_store.get_role()
    display_name = (role.display_name if role else "") or "Treener"

    st.title(f"🧑‍🏫 Treeneri töölaud — {display_name}")
    st.caption(
        "Halda kutsekoode, vaata sportlasi, sisesta päevaotsuseid §4.2 "
        "pimemenetluses (sa ei näe Vorm.ai soovitust enne enda otsust)."
    )

    with st.expander("✏️ Muuda enda nähtavat nime"):
        new_name = st.text_input(
            "Nähtav nimi",
            value=display_name if display_name != "Treener" else "",
            placeholder="Ille Kukk",
            key="_coach_name_input",
            help="Sportlasele kuvatakse seda nime sinu otsuste juures.",
        )
        if st.button("Salvesta nimi", key="_coach_name_save"):
            coach_store.set_role("coach", new_name.strip())
            from .. import auth  # local import to avoid cycle at module load
            auth.invalidate_role_cache()
            st.success("Nähtav nimi salvestatud.")
            st.rerun()

    st.divider()
    _render_invites_section(coach_store)
    st.divider()
    _render_athletes_section(coach_store, build_athlete_store)


def _render_invites_section(coach_store: SupabaseStore) -> None:
    st.markdown("### 🎟️ Kutsed")
    st.caption(
        "Iga sportlane sisestab oma sidebari osasse 'Mul on treener' alloleva "
        "8-tähelise koodi ja kinnitab eraldi nõusoleku. Kutsekood üksi ei anna "
        "ligipääsu tundlikele andmetele."
    )

    if st.button(
        "➕ Loo uus kutsekood",
        key="_coach_new_invite",
        type="primary",
        width="stretch",
    ):
        try:
            link = coach_store.create_invite()
        except Exception as exc:
            st.error(f"Kutse loomine ebaõnnestus: {exc}")
        else:
            st.session_state[_LAST_INVITE_KEY] = link.invite_code
            st.rerun()

    last_code = st.session_state.get(_LAST_INVITE_KEY)
    if last_code:
        st.success(
            f"Anna sportlasele see kood: **`{last_code}`** "
            "(kehtib seni, kuni sportlane selle koos nõusolekuga kasutab)"
        )

    try:
        all_links = coach_store.list_coach_links(statuses=("pending", "active"))
    except Exception as exc:
        st.warning(f"Kutsete lugemine ebaõnnestus: {exc}")
        return
    pending = [link for link in all_links if link.status == "pending"]
    if not pending:
        return

    st.markdown("**Ootel olevad kutsed**")
    for link in pending:
        col_code, col_action = st.columns([3, 1])
        col_code.code(link.invite_code, language=None)
        if col_action.button(
            "Tühista", key=f"_coach_invite_revoke_{link.id}", width="stretch",
        ):
            try:
                coach_store.delete_link(link.id)
            except Exception as exc:
                st.error(f"Kustutamine ebaõnnestus: {exc}")
            else:
                if st.session_state.get(_LAST_INVITE_KEY) == link.invite_code:
                    st.session_state.pop(_LAST_INVITE_KEY, None)
                st.rerun()


def _render_athletes_section(
    coach_store: SupabaseStore,
    build_athlete_store: Callable[[str], SupabaseStore | None],
) -> None:
    st.markdown("### 👥 Sinu sportlased")
    try:
        active_links = coach_store.list_coach_links(statuses=("active",))
    except Exception as exc:
        st.error(f"Sportlaste loendi lugemine ebaõnnestus: {exc}")
        return

    if not active_links:
        st.info(
            "Veel pole ühtegi sportlast ühendatud. Loo ülal kutsekood ja "
            "anna see sportlasele."
        )
        return

    for link in active_links:
        athlete_store = build_athlete_store(link.athlete_user_id or "")
        if athlete_store is None:
            continue
        with st.container(border=True):
            _render_athlete_card(link, athlete_store)


def _render_athlete_card(link, athlete_store: SupabaseStore) -> None:
    if not link.has_active_data_consent:
        col_info, col_action = st.columns([4, 1])
        col_info.markdown("**Sportlane - nõusolek puudub**")
        col_info.caption(
            "Seos on olemas, kuid sportlane pole veel kinnitanud tundlike "
            "andmete jagamise nõusolekut. Profiili ja päevalogi ei kuvata."
        )
        col_action.button(
            "Ootel",
            key=f"_coach_view_blocked_{link.id}",
            disabled=True,
            width="stretch",
        )
        return

    try:
        profile = athlete_store.load_profile()
    except Exception:
        profile = None
    athlete_name = (profile.name if profile else None) or "Sportlane (profiil puudub)"

    col_info, col_action = st.columns([4, 1])
    col_info.markdown(f"**{athlete_name}**")
    if profile:
        col_info.caption(
            f"{profile.age} a · {profile.sex} · staaž {profile.training_years} a"
        )
    else:
        col_info.caption("Profiili pole veel täidetud.")

    try:
        recent = athlete_store.list_daily_logs(
            since=date.today() - timedelta(days=14)
        )
    except Exception:
        recent = []
    col_info.caption(
        f"Viimase 14 päeva päevalogid: **{len(recent)}**"
    )

    if col_action.button(
        "Vaata →",
        key=f"_coach_view_{link.id}",
        type="primary",
        width="stretch",
    ):
        st.session_state[_SELECTED_ATHLETE_KEY] = link.athlete_user_id
        st.rerun()


# --- Athlete view: read-only metrics + decision form ----------------------


def _render_athlete_view(
    coach_store: SupabaseStore,
    athlete_user_id: str,
    athlete_store: SupabaseStore,
) -> None:
    if st.button(
        "← Tagasi sportlaste loendisse",
        key="_coach_back",
    ):
        st.session_state.pop(_SELECTED_ATHLETE_KEY, None)
        st.rerun()

    try:
        profile = athlete_store.load_profile()
    except Exception:
        profile = None
    athlete_name = (profile.name if profile else None) or "Sportlane"

    st.title(f"👤 {athlete_name}")
    st.caption(
        "Sa ei näe Vorm.ai soovitust ega ühtegi mudeli arvutust — see hoiab "
        "§4.2 pimemenetlust puhtana. Sisesta otsus enda iseseisva hinnangu järgi."
    )

    if profile:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Vanus", f"{profile.age} a")
        c2.metric("Treeningstaaž", f"{profile.training_years} a")
        c3.metric("Max HR", str(profile.max_hr))
        c4.metric("Puhke HR", str(profile.resting_hr))
        if profile.season_goal:
            st.caption(f"🎯 Hooaja eesmärk: **{profile.season_goal}**")

    st.divider()

    _render_recent_daily_logs(athlete_store)
    st.divider()
    _render_decision_form(coach_store, athlete_store, athlete_user_id)
    st.divider()
    _render_existing_decisions(athlete_store)
    st.divider()
    _render_revoke_section(coach_store, athlete_user_id, athlete_name)


def _render_revoke_section(
    coach_store: SupabaseStore,
    athlete_user_id: str,
    athlete_name: str,
) -> None:
    """Destructive: drop the coach↔athlete link. Folded into an expander so
    it's a deliberate click, not a stray-finger accident on the home grid."""
    with st.expander("⚠️ Lõpeta seos sportlasega"):
        st.caption(
            f"Kustutab sinu ja **{athlete_name}** vahelise seose. Kaotad "
            "kohe juurdepääsu tema profiilile ja päevalogile. Sportlane "
            "ise oma andmeid ei kaota. Seda saad teha ainult sina; "
            "sportlane peab paluma sul tagasi siduda uue koodiga."
        )
        try:
            active_links = coach_store.list_coach_links(statuses=("active",))
        except Exception as exc:
            st.error(f"Seose lugemine ebaõnnestus: {exc}")
            return
        match = next(
            (
                link for link in active_links
                if link.athlete_user_id == athlete_user_id
            ),
            None,
        )
        if match is None:
            st.caption("Aktiivset seost ei leitud.")
            return
        if st.button(
            "Jah, kustuta seos",
            key=f"_coach_revoke_confirm_{match.id}",
            width="stretch",
        ):
            try:
                coach_store.delete_link(match.id)
            except Exception as exc:
                st.error(f"Lõpetamine ebaõnnestus: {exc}")
                return
            st.session_state.pop(_SELECTED_ATHLETE_KEY, None)
            st.success("Seos lõpetatud.")
            st.rerun()


def _render_recent_daily_logs(athlete_store: SupabaseStore) -> None:
    st.markdown("### 📋 Sportlase päevalog (viimased 14 päeva)")
    try:
        logs = athlete_store.list_daily_logs(
            since=date.today() - timedelta(days=14)
        )
    except Exception as exc:
        st.warning(f"Päevalogi lugemine ebaõnnestus: {exc}")
        return
    if not logs:
        st.caption("Viimase 14 päeva jooksul pole sportlane päevalogi täitnud.")
        return

    rows = []
    for entry in sorted(logs, key=lambda e: e.log_date, reverse=True):
        rows.append({
            "Kuupäev": entry.log_date.isoformat(),
            "Mudeli soovitus": entry.recommended_category,
            "Kasulikkus (1-5)": entry.usefulness or "—",
            "Järgis": entry.followed or "—",
            "Enesetunne (1-5)": entry.next_session_feeling or "—",
            "Märkused": (entry.notes or "")[:80],
        })
    st.dataframe(
        pd.DataFrame(rows), hide_index=True, width="stretch",
    )


def _render_decision_form(
    coach_store: SupabaseStore,
    athlete_store: SupabaseStore,
    athlete_user_id: str,
) -> None:
    st.markdown("### ✍️ Sisesta päevaotsus (§4.2 pimemenetlus)")

    role = coach_store.get_role()
    coach_display_name = (role.display_name if role else "") or "Treener"

    existing = None
    try:
        existing = athlete_store.get_coach_decision(date.today())
    except Exception:
        existing = None
    if existing:
        st.info(
            f"Tänase päeva otsus on juba salvestatud: **{existing.recommended_category}**. "
            "Allpool vorm kirjutab selle uue salvestusega üle."
        )

    with st.form(f"vorm_coach_decision_form_{athlete_user_id}"):
        decision_date = st.date_input(
            "Kuupäev",
            value=date.today(),
            key=f"_coach_dec_date_{athlete_user_id}",
        )
        category = st.selectbox(
            "Sinu soovitus",
            _CATEGORY_OPTIONS,
            key=f"_coach_dec_cat_{athlete_user_id}",
        )
        rationale = st.text_area(
            "Põhjendus (lühike)",
            placeholder="Nt: viimased 3 päeva oli RPE 8, parem teha taastumispäev",
            key=f"_coach_dec_rat_{athlete_user_id}",
            height=80,
        )
        notes = st.text_input(
            "Lisamärkused (valikuline)",
            key=f"_coach_dec_notes_{athlete_user_id}",
        )
        save = st.form_submit_button(
            "Salvesta otsus", type="primary", width="stretch",
        )
        if save:
            try:
                athlete_store.save_coach_decision(CoachDecision(
                    decision_date=decision_date,
                    recommended_category=category,
                    coach_name=coach_display_name,
                    rationale=rationale.strip() or None,
                    notes=notes.strip() or None,
                ))
            except Exception as exc:
                st.error(f"Salvestamine ebaõnnestus: {exc}")
                return
            st.success(
                f"Otsus salvestatud kuupäevale {decision_date.isoformat()}."
            )
            st.rerun()


def render_athlete_coach_panel(athlete_store: SupabaseStore) -> None:
    """Sidebar widget for athletes: see linked coaches + claim invite codes.

    Render this inside the athlete's normal sidebar — it does NOT take over
    the page. Coach name comes from the active link's coach ``user_roles``
    row, which the athlete can read thanks to a dedicated RLS policy.
    """
    st.sidebar.markdown("### 🧑‍🏫 Treener")

    try:
        links = athlete_store.list_athlete_links(statuses=("active",))
    except Exception:
        links = []

    if links:
        for link in links:
            coach_name = _read_coach_display_name(athlete_store, link.coach_user_id)
            if not link.has_active_data_consent:
                st.sidebar.warning(f"Seos ootel: **{coach_name}**")
                st.sidebar.caption(
                    "Treener ei näe sinu profiili ega päevalogi enne, kui annad "
                    "selgesõnalise jagamise nõusoleku."
                )
                with st.sidebar.expander(f"Nõusolek: {coach_name}"):
                    st.markdown(_COACH_SHARE_CONSENT_TEXT)
                    renewed_ok = st.checkbox(
                        "Annan sellele treenerile nõusoleku neid andmeid näha ja "
                        "töödelda treeningsoovituse ning valideerimise eesmärgil.",
                        key=f"_vorm_link_consent_{link.id}",
                    )
                    st.caption(f"Nõusoleku versioon: {DATA_CONSENT_VERSION}")
                    if st.button(
                        "Salvesta nõusolek",
                        key=f"_vorm_link_consent_save_{link.id}",
                        type="primary",
                        disabled=not renewed_ok,
                        width="stretch",
                    ):
                        try:
                            athlete_store.grant_link_consent(link.id)
                        except Exception as exc:
                            st.error(f"Nõusoleku salvestamine ebaõnnestus: {exc}")
                            return
                        st.success("Nõusolek salvestatud.")
                        st.rerun()
                continue

            st.sidebar.success(f"Seotud: **{coach_name}**")
            st.sidebar.caption(
                "Andsid nõusoleku: treener näeb sinu profiili, päevalogi ja "
                "saab sinule saata otsuseid §4.2 pimemenetluses. Tema **ei** "
                "näe sinu Strava-ühendust, GPS-radu ega toorpulsiandmeid."
            )
        _render_sidebar_latest_coach_decision(athlete_store)
    else:
        st.sidebar.caption(
            "Sa pole ühegi treeneriga seotud. Kui treener andis sulle "
            "kutsekoodi, sisesta see alloleva nupu alt."
        )

    with st.sidebar.expander("Mul on uus kutsekood"):
        code = st.text_input(
            "Kutsekood",
            key="_vorm_athlete_invite_code",
            placeholder="ABCDEFGH",
            max_chars=12,
            help="8-täheline kood, mille treener sulle saatis.",
        )
        st.markdown(_COACH_SHARE_CONSENT_TEXT)
        share_ok = st.checkbox(
            "Annan sellele treenerile nõusoleku neid andmeid näha ja töödelda "
            "treeningsoovituse ning valideerimise eesmärgil.",
            key="_vorm_athlete_invite_consent",
        )
        st.caption(f"Nõusoleku versioon: {DATA_CONSENT_VERSION}")
        if st.button(
            "Seo treeneriga",
            key="_vorm_athlete_invite_accept",
            type="primary",
            disabled=not share_ok,
            width="stretch",
        ):
            cleaned = (code or "").strip().upper()
            if not cleaned:
                st.error("Kutsekood on kohustuslik.")
                return
            try:
                athlete_store.accept_invite(
                    cleaned,
                    consent_to_share_sensitive_data=share_ok,
                )
            except LookupError as exc:
                st.error(str(exc))
                return
            except ValueError as exc:
                st.error(str(exc))
                return
            except Exception as exc:
                st.error(f"Sidumine ebaõnnestus: {exc}")
                return
            st.success("Treener seotud!")
            st.rerun()


def _render_sidebar_latest_coach_decision(athlete_store: SupabaseStore) -> None:
    try:
        decisions = athlete_store.list_coach_decisions(
            since=date.today() - timedelta(days=14),
        )
    except Exception:
        return
    if not decisions:
        return
    latest = max(decisions, key=lambda d: d.decision_date)
    st.sidebar.info(
        f"Viimane treeneri otsus ({latest.decision_date.isoformat()}): "
        f"**{latest.recommended_category}**"
    )


def _read_coach_display_name(athlete_store: SupabaseStore, coach_user_id: str) -> str:
    """Read the linked coach's display name. RLS policy 'Athletes select
    coach role' lets the athlete see this single column for active links."""
    try:
        resp = (
            athlete_store.client.table("user_roles")
            .select("display_name")
            .eq("user_id", coach_user_id)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
    except Exception:
        return "Treener"
    if not rows:
        return "Treener"
    return (rows[0].get("display_name") or "").strip() or "Treener"


def list_linked_coach_names(athlete_store: SupabaseStore) -> list[str]:
    """Display names of the athlete's active coaches.

    Convenience for athlete-facing UI that wants to say "your coach: X".
    Returns ``[]`` when the athlete has no active links or when the lookup
    fails (offline, RLS denial). Coaches without a display name show as
    ``"Treener"``.
    """
    try:
        links = athlete_store.list_athlete_links(statuses=("active",))
    except Exception:
        return []
    return [
        _read_coach_display_name(athlete_store, link.coach_user_id)
        for link in links
        if link.has_active_data_consent
    ]


def _render_existing_decisions(athlete_store: SupabaseStore) -> None:
    st.markdown("### 📜 Varasemad otsused (30 päeva)")
    try:
        decisions = athlete_store.list_coach_decisions(
            since=date.today() - timedelta(days=30)
        )
    except Exception as exc:
        st.warning(f"Otsuste lugemine ebaõnnestus: {exc}")
        return
    if not decisions:
        st.caption("Viimase 30 päeva jooksul pole salvestatud otsuseid.")
        return

    for d in sorted(decisions, key=lambda x: x.decision_date, reverse=True):
        with st.container(border=True):
            col_date, col_cat = st.columns([1, 3])
            col_date.markdown(f"**{d.decision_date.isoformat()}**")
            col_cat.markdown(f"_{d.recommended_category}_")
            if d.rationale:
                col_cat.caption(d.rationale)
            if d.notes:
                col_cat.caption(f"📝 {d.notes}")
