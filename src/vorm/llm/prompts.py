"""Prompt templates for the training-load advisor.

The prompt is structured rather than conversational: we give Claude a JSON
schema to fill and the relevant context. Temperature is zero, so the prompt
carries all the nuance. Any change to this file is a prompt-version bump.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from ..data.models import AthleteProfile, DailySubjective, TrainingActivity
from ..metrics.load import LoadSummary
from ..rules.safety import SafetyVerdict

PROMPT_VERSION = "0.6"

SYSTEM_PROMPT = """Oled kesk- ja pikamaajooksjatele spetsialiseerunud spordifüsioloogia nõustaja. \
Sinu ülesanne on anda konkreetne andmepõhine soovitus tänase planeeritud treeningu kohta, \
arvestades objektiivseid koormusnäitajaid (ACWR, TRIMP, monotoonsus), subjektiivseid signaale \
(RPE, uni, enesetunne) ja sportlase profiili.

Põhimõtted:
- Vasta alati eesti keeles.
- Vasta struktureeritud JSON-is, mis järgib etteantud skeemi.
- Kui süsteem on märkinud ohutusreegli (safety_flag) — pead seda JÄRGIMA, mitte üle sõitma. \
Sinu roll on sel juhul *põhjendada* reegli rakendumist ja anda konkreetne asendustreening.
- Viita põhjenduses konkreetsetele numbritele (ACWR, RPE, uneaeg), mitte üldistele fraasidele.
- Ära anna meditsiinilist nõu. Vigastuse/haiguse kahtluse korral suuna arstile/treenerile.
- Põhjendus peab olema 2–4 lauset, mitte rohkem.
- Väljal `modification` anna alati täpne tänane treeningkava või asendusplaan: soojendus,
  põhiosa (nt 5×1000 m ja 3×200 m), pausid, intensiivsus/tempo kui võimalik, ning lõdvestus.
  Kui valitud päeva plaani ei avaldata, paku sobiv treening ainult olemasoleva koormuskonteksti põhjal.
- Soovituse kategooria peab olema täpselt üks järgmistest: \
"Jätka plaanipäraselt", "Vähenda intensiivsust", "Lisa taastumispäev", "Alternatiivne treening".
"""

# ---------------------------------------------------------------------------
# Prompt-variant katalog — projekti plaan §3 hilisem: "promptide süstemaatiline
# A/B-testimine". Iga variant tasub testida sama valideerimisanded peal
# (`scripts/validate.py --llm --prompt-variant <võti>`).
#
# Variantide ühisosa:
#   - keel = eesti
#   - JSON-skeem on sama
#   - 4 kategooriat on samad
# Variantide erinevus on rõhuasetus (numbritel / konservatiivsusel / kogemustel).
# ---------------------------------------------------------------------------

_VARIANT_NUMERIC = """Oled kesk- ja pikamaajooksjatele spetsialiseerunud spordifüsioloogia nõustaja. \
Sinu erialane stiil on **arvupõhine**: iga soovitus toetub konkreetsetele
mõõdetud näitajatele (ACWR, TRIMP, monotoonsus, RPE-trend).

Põhimõtted:
- Vasta alati eesti keeles.
- Vasta struktureeritud JSON-is, mis järgib etteantud skeemi.
- Kui süsteem on märkinud ohutusreegli (safety_flag) — JÄRGI seda, põhjenda.
- Põhjenduses peab olema **vähemalt 3 konkreetset arvu** (näiteks ACWR 1.34,
  RPE eile 8, uni 6.2 h). Ära kasuta umbmääraseid fraase nagu "kõrge koormus" —
  ütle alati, kui kõrge.
- Põhjendus on 2–4 lauset.
- Väljal `modification` anna alati täpne tänane treeningkava või asendusplaan:
  soojendus, põhiosa (nt 5×1000 m ja 3×200 m), pausid, intensiivsus/tempo kui võimalik,
  ning lõdvestus.
- Ära anna meditsiinilist nõu.
- Kategooria peab olema täpselt üks neljast: "Jätka plaanipäraselt",
  "Vähenda intensiivsust", "Lisa taastumispäev", "Alternatiivne treening".
"""

_VARIANT_CONSERVATIVE = """Oled kesk- ja pikamaajooksjatele spetsialiseerunud spordifüsioloogia nõustaja, \
kelle stiil on **konservatiivne** — kahtluse korral eelistad ettevaatust.

Põhimõtted:
- Vasta alati eesti keeles, struktureeritud JSON-is.
- Kui süsteem on märkinud ohutusreegli — JÄRGI seda.
- Kui ACWR ≥ 1.3 või uni < 6.5 h või eilne RPE ≥ 8, kaalu ettevaatlikku
  kategooriat (Vähenda / Taastumine), isegi kui ohutusreegel täpselt ei fire-nud.
  Põhjenda, miks signaal on piisav.
- Põhjendus on 2–4 lauset eesti keeles, viidates konkreetsetele arvudele.
- Väljal `modification` anna alati täpne, konservatiivne tänane treeningkava või
  asendusplaan: soojendus, põhiosa, pausid, intensiivsus/tempo kui võimalik, ning lõdvestus.
- Ära anna meditsiinilist nõu.
- Kategooria peab olema täpselt üks neljast.
"""

PROMPT_VARIANTS: dict[str, str] = {
    "baseline": SYSTEM_PROMPT,
    "numeric": _VARIANT_NUMERIC,
    "conservative": _VARIANT_CONSERVATIVE,
}


def select_system_prompt(variant: str) -> str:
    """Pick a system prompt by variant key. Falls back to baseline if unknown."""
    return PROMPT_VARIANTS.get(variant, SYSTEM_PROMPT)

RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["category", "rationale", "modification", "confidence"],
    "properties": {
        "category": {
            "type": "string",
            "enum": [
                "Jätka plaanipäraselt",
                "Vähenda intensiivsust",
                "Lisa taastumispäev",
                "Alternatiivne treening",
            ],
        },
        "rationale": {
            "type": "string",
            "description": "2–4 lauset eesti keeles, viitab konkreetsetele arvudele.",
        },
        "modification": {
            "type": "string",
            "description": (
                "Kohustuslik: täpne tänane treeningkava või asendusplaan. "
                "Sisalda soojendus, põhiosa (nt 5×1000 m ja 3×200 m), pausid, "
                "intensiivsus/tempo kui võimalik, ning lõdvestus."
            ),
        },
        "confidence": {
            "type": "string",
            "enum": ["madal", "keskmine", "kõrge"],
        },
        "acknowledges_safety_flags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Loetle safety-flag koodid, mida põhjendus järgib.",
        },
    },
}

_FEW_SHOT_EXAMPLES = [
    {
        "context_summary": (
            "ACWR=1.1 (optimaalne), 7-päeva load 2800, 28-päeva 2500, RPE (eile)=5, "
            "uni 8 h, täna plaanis 6x1km @ 3:20."
        ),
        "response": {
            "category": "Jätka plaanipäraselt",
            "rationale": (
                "ACWR 1.1 on sweet-spot vahemikus (0.8–1.3) ja 7-päeva koormus on "
                "kroonilisest baasist 12% üle — tervislik tõus. Eilne RPE 5 ja uni 8 h näitavad head taastumist. "
                "Planeeritud 6×1 km tempo sobib praegusesse koormusprofiili."
            ),
            "modification": (
                "2 km kerget soojendust + jooksuharjutused; 6×1000 m @ 3:20–3:25/km, "
                "2:00 sörkipaus; lõppu 3×200 m kontrollitult kiirelt, 200 m sörkipaus; "
                "2 km lõdvestust."
            ),
            "confidence": "kõrge",
            "acknowledges_safety_flags": [],
        },
    },
    {
        "context_summary": (
            "ACWR=1.62 (CRITICAL flag acwr_high), 7-päeva load 3600, 28-päeva 2200, RPE "
            "eile=8, üleeile=8 (CRITICAL flag rpe_consecutive_high), täna plaanis 12x400m."
        ),
        "response": {
            "category": "Lisa taastumispäev",
            "rationale": (
                "ACWR 1.62 ületab ohupiiri 1.5 ja kaks järjestikust RPE 8 päeva viitavad kogunenud väsimusele — "
                "intervallitreening sel taustal tõstab vigastusriski. Taastumispäev on ainus vastutustundlik valik."
            ),
            "modification": (
                "Põhitreening ära jätta; 30–45 min väga kerget kõndi või rattasõitu Z1, "
                "10 min liikuvust ja kerget rullimist; ei lõike ega tempojooksu; prioriteet uni ja söök."
            ),
            "confidence": "kõrge",
            "acknowledges_safety_flags": ["acwr_high", "rpe_consecutive_high"],
        },
    },
]


@dataclass(frozen=True)
class PromptBundle:
    system: str
    user: str
    schema: dict
    version: str = PROMPT_VERSION


def build_prompt(
    *,
    profile: AthleteProfile,
    activities: list[TrainingActivity],
    summary: LoadSummary,
    verdict: SafetyVerdict,
    today_plan: str,
    subjective: DailySubjective | None,
    today: date | None = None,
    variant: str = "baseline",
) -> PromptBundle:
    today = today or date.today()
    user_prompt = _compose_user_prompt(
        profile=profile,
        activities=activities,
        summary=summary,
        verdict=verdict,
        today_plan=today_plan,
        subjective=subjective,
        today=today,
    )
    system = select_system_prompt(variant)
    version = f"{PROMPT_VERSION}-{variant}" if variant != "baseline" else PROMPT_VERSION
    return PromptBundle(system=system, user=user_prompt, schema=RESPONSE_SCHEMA, version=version)


def _compose_user_prompt(
    *,
    profile: AthleteProfile,
    activities: list[TrainingActivity],
    summary: LoadSummary,
    verdict: SafetyVerdict,
    today_plan: str,
    subjective: DailySubjective | None,
    today: date,
) -> str:
    sections: list[str] = []

    sections.append("# Sportlase profiil")
    sections.append(
        json.dumps(
            {
                "nimi": profile.name,
                "vanus": profile.age,
                "sugu": profile.sex,
                "max_hr": profile.max_hr,
                "puhke_hr": profile.resting_hr,
                "treeningstaaž_aastat": profile.training_years,
                "hooaja_eesmärk": profile.season_goal,
                "tippajad": profile.personal_bests,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    sections.append("\n# Koormusnäitajad seisuga " + today.isoformat())
    sections.append(
        json.dumps(
            {
                "acute_7d_TRIMP": round(summary.acute_7d, 1),
                "chronic_28d_TRIMP": round(summary.chronic_28d, 1),
                "ACWR": round(summary.acwr, 2) if summary.acwr is not None else None,
                "ACWR_tsoon": summary.acwr_zone,
                "monotoonsus_7d": round(summary.monotony, 2) if summary.monotony is not None else None,
                "strain_7d": round(summary.strain, 1) if summary.strain is not None else None,
                "total_7d": round(summary.total_7d, 1),
                "total_28d": round(summary.total_28d, 1),
                "RPE_viimased_3_päeva": summary.rpe_last_3_days,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    sections.append("\n# Viimase 14 päeva treeningud")
    sections.append(_render_recent_table(activities, today))

    if verdict.flags:
        sections.append("\n# Ohutusreeglid (süsteem tuvastas)")
        for f in verdict.flags:
            prefix = "[KRIITILINE]" if f.severity.value == "critical" else "[HOIATUS]"
            forced = f" → sunnitud soovitus: {f.forced_recommendation.value}" if f.forced_recommendation else ""
            sections.append(f"- {prefix} {f.code}: {f.message}{forced}")
        if verdict.forced:
            sections.append(
                f"\nOhutusreegel sunnib soovituse kategooriaks: **{verdict.recommendation.value}**. "
                "Pead seda järgima ja põhjendama."
            )
    else:
        sections.append("\n# Ohutusreeglid: ei ühtegi.")

    if subjective:
        sections.append("\n# Sportlase subjektiivsed sisendid täna")
        sections.append(
            json.dumps(
                {
                    "eilne_RPE": subjective.rpe_yesterday,
                    "uni_h": subjective.sleep_hours,
                    "stressitase_1_5": subjective.stress_level,
                    "haigus": subjective.illness,
                    "märkmed": subjective.notes,
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    sections.append("\n# Täna planeeritud treening")
    sections.append(today_plan or "(sportlane pole plaani sisestanud)")

    sections.append("\n# Näited sarnasest ülesandest")
    for i, ex in enumerate(_FEW_SHOT_EXAMPLES, 1):
        sections.append(f"Näide {i} — kontekst: {ex['context_summary']}")
        sections.append("Oodatud vastus:")
        sections.append(json.dumps(ex["response"], ensure_ascii=False, indent=2))

    sections.append("\n# Sinu ülesanne")
    sections.append(
        "Anna täna sellele sportlasele andmepõhine soovitus JSON-is, mis vastab skeemile. "
        "Täida `modification` alati konkreetse treeningkava või asendusplaaniga, mitte üldise soovitusega. "
        "Ära lisa midagi JSON-ist väljaspoole. Väljund peab olema parsitav json.loads()-iga."
    )

    return "\n".join(sections)


def _render_recent_table(activities: list[TrainingActivity], today: date) -> str:
    cutoff = today - timedelta(days=14)
    recent = [a for a in activities if cutoff <= a.activity_date <= today]
    if not recent:
        return "(viimase 14 päeva jooksul treeninguid pole)"
    df = pd.DataFrame(
        [
            {
                "kuupäev": a.activity_date.isoformat(),
                "tüüp": a.notes or a.activity_type,
                "km": round(a.distance_km, 1),
                "min": round(a.duration_min, 0),
                "avg_hr": a.avg_hr,
                "RPE": a.rpe,
            }
            for a in sorted(recent, key=lambda x: x.activity_date)
        ]
    )
    return df.to_markdown(index=False)
