"""First-run onboarding wizard.

Activates the first time a signed-in user reaches the main app without a
saved profile. Two screens: a welcome blurb explaining what Vorm.ai does +
the disclaimer, then a profile form that captures the minimum fields the
TRIMP/ACWR pipeline needs to produce non-degenerate output.

The wizard is opt-out: a "Vahele jätta" button on the welcome screen marks
the wizard finished for the session without saving a profile. That path lets
returning evaluators or testers reach the main UI quickly even before the
new profile is filled out.
"""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from ..data.models import AthleteProfile

_STEP_KEY = "_vorm_onboarding_step"
_DONE_SENTINEL = "done"


def should_show_wizard(*, has_profile: bool) -> bool:
    """True when the wizard should take over the main area.

    Skipped when the user already has a saved profile or has dismissed the
    wizard this session.
    """
    if has_profile:
        return False
    return st.session_state.get(_STEP_KEY) != _DONE_SENTINEL


def render_wizard(
    *,
    user_email: str,
    on_complete: Callable[[AthleteProfile], None],
) -> None:
    """Render the active wizard step. Caller is responsible for ``st.stop()``."""
    step = st.session_state.get(_STEP_KEY, 1)
    if step == 2:
        _render_profile_form(on_complete)
    else:
        _render_welcome(user_email)


def _render_welcome(user_email: str) -> None:
    st.title("🏃 Tere tulemast Vorm.ai-sse!")
    st.caption(f"Oled sisse logitud kontoga **{user_email}**.")
    st.markdown(
        """
        ### Mida Vorm.ai teeb?

        - 📊 Arvutab treeningandmetest **ACWR**, **TRIMP**, **monotoonsuse**
          ja **Banister CTL/ATL/TSB** näitajad
        - 🚦 Käivitab ohutusreeglid (vigastusriski-piirid)
        - 🤖 Annab LLM-soovituse tänase treeningu kohta nelja kategoorias:
          *jätka / vähenda / alternatiiv / taastumine*
        - 📈 Visualiseerib viimase 90 päeva trende Plotly-graafikutel
        - 📅 Genereerib päev-haaval treeningkava võistlusteks

        ### Privaatsus

        Sinu andmed salvestuvad sinu **enda Supabase-kontosse** pärast
        andmetöötluse nõusolekut. LLM näeb ainult **agregeeritud näitajaid**
        (ACWR, RPE, TRIMP) — GPS-rajad, toorpulsiread ja tokenid jäävad LLM-ist
        välja. Treener näeb andmeid ainult siis, kui annad kutsekoodi juures
        eraldi jagamisnõusoleku.

        ### Vastutuspiir

        Vorm.ai on **otsustustugi**, mitte asendaja treenerile ega arstile.
        Vigastuse, valu või haiguskahtluse puhul lõpeta treening ja pöördu
        spetsialisti poole.
        """
    )
    st.divider()

    col_skip, col_next = st.columns([1, 2])
    if col_skip.button("Vahele jätta", key="_vorm_onb_skip", width="stretch"):
        st.session_state[_STEP_KEY] = _DONE_SENTINEL
        st.rerun()
    if col_next.button(
        "Edasi → sisesta profiil",
        key="_vorm_onb_next",
        width="stretch",
        type="primary",
    ):
        st.session_state[_STEP_KEY] = 2
        st.rerun()


def _render_profile_form(on_complete: Callable[[AthleteProfile], None]) -> None:
    st.title("🏃 Vorm.ai")
    st.markdown("### Samm 2 / 2 — sportlase profiil")
    st.caption(
        "Need andmed määravad TRIMP-i ja ohutusreeglite arvutuse. Saad neid "
        "hiljem sidebarist alati muuta."
    )

    with st.form("vorm_onboarding_profile"):
        col1, col2 = st.columns(2)
        name = col1.text_input("Nimi", placeholder="Eesnimi Perekonnanimi")
        sex = col2.selectbox("Sugu", ["M", "F"], index=0)

        col3, col4, col5 = st.columns(3)
        age = col3.number_input("Vanus", min_value=12, max_value=80, value=30)
        training_years = col4.number_input(
            "Treeningstaaž (a)", min_value=0, max_value=50, value=5,
        )
        season_goal = col5.text_input(
            "Hooaja eesmärk", placeholder="Nt: sub-35 10 km",
        )

        col6, col7 = st.columns(2)
        max_hr = col6.number_input(
            "Maksimaalne pulss",
            min_value=120, max_value=230, value=190,
            help="Mõõdetud testidega või tuletatud (`220 − vanus` on toores hinnang).",
        )
        resting_hr = col7.number_input(
            "Puhkepulss",
            min_value=30, max_value=90, value=55,
            help="Hommikul ärgates, enne kohvi. Ideaalselt mitme päeva keskmine.",
        )

        st.markdown("**Tippajad** (valikuline, formaat `MM:SS`)")
        col8, col9, col10, col11 = st.columns(4)
        pb_1500 = col8.text_input("1500 m", placeholder="5:30", key="onb_pb_1500")
        pb_3000 = col9.text_input("3000 m", placeholder="11:20", key="onb_pb_3000")
        pb_5000 = col10.text_input("5000 m", placeholder="18:50", key="onb_pb_5000")
        pb_10000 = col11.text_input("10000 m", placeholder="40:30", key="onb_pb_10000")

        col_back, col_save = st.columns([1, 2])
        back = col_back.form_submit_button("← Tagasi", width="stretch")
        save = col_save.form_submit_button(
            "Salvesta profiil ja alusta", type="primary", width="stretch",
        )

        if back:
            st.session_state[_STEP_KEY] = 1
            st.rerun()

        if save:
            if not name.strip():
                st.error("Nimi on kohustuslik.")
                return
            if max_hr <= resting_hr:
                st.error("Maksimaalne pulss peab olema suurem kui puhkepulss.")
                return

            personal_bests = {}
            for key, value in (
                ("1500m", pb_1500), ("3000m", pb_3000),
                ("5000m", pb_5000), ("10000m", pb_10000),
            ):
                v = (value or "").strip()
                if v:
                    personal_bests[key] = v

            profile = AthleteProfile(
                name=name.strip(),
                age=int(age),
                sex=sex,
                max_hr=int(max_hr),
                resting_hr=int(resting_hr),
                training_years=int(training_years),
                season_goal=season_goal.strip(),
                personal_bests=personal_bests,
            )
            try:
                on_complete(profile)
            except Exception as exc:
                st.error(f"Profiili salvestamine ebaõnnestus: {exc}")
                return
            st.session_state[_STEP_KEY] = _DONE_SENTINEL
            st.success(f"Tere tulemast, {profile.name}! Suuname rakendusse...")
            st.rerun()
