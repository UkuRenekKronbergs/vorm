"""Core data models.

Intentionally simple dataclasses rather than Pydantic — the boundary conversions
(CSV/JSON/Strava API) are all in the loader modules, so the domain stays flat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

DATA_CONSENT_VERSION = "2026-05-19"


@dataclass(frozen=True)
class TrainingActivity:
    id: str
    activity_date: date
    activity_type: str
    distance_km: float
    duration_min: float
    avg_hr: int | None = None
    max_hr_observed: int | None = None
    avg_pace_min_per_km: float | None = None
    elevation_gain_m: float | None = None
    rpe: int | None = None
    notes: str | None = None

    def is_run(self) -> bool:
        return self.activity_type.lower() in {"run", "trailrun", "virtualrun"}


@dataclass(frozen=True)
class DailySubjective:
    """Daily user-reported inputs that complement objective training data."""

    entry_date: date
    rpe_yesterday: int | None = None
    sleep_hours: float | None = None
    stress_level: int | None = None  # 1-5, user-reported
    illness: bool = False
    notes: str | None = None


@dataclass(frozen=True)
class StravaConnection:
    client_id: str
    client_secret: str = field(repr=False)
    refresh_token: str = field(repr=False)
    athlete_id: str | None = None
    athlete_name: str = ""
    scope: str = ""


@dataclass(frozen=True)
class AthleteProfile:
    name: str
    age: int
    sex: str  # "M" or "F"
    max_hr: int
    resting_hr: int
    training_years: int
    season_goal: str = ""
    personal_bests: dict[str, str] = field(default_factory=dict)
    # Manually-set threshold pace (1-hour sustainable). If None, derived from PBs.
    threshold_pace_min_per_km: float | None = None

    @property
    def hr_reserve(self) -> int:
        return max(self.max_hr - self.resting_hr, 1)

    @property
    def effective_threshold_pace(self) -> float | None:
        """Threshold (~1-hour-sustainable) pace in min/km.

        Falls back to PB-derived estimate when not explicitly set:
        - 10 km PB pace × 1.03 (threshold ≈ 3% slower than 10K race pace)
        - else 5 km PB pace × 1.07 (threshold ≈ 7% slower than 5K race pace)

        Used by metrics.load.trimp() as an HR-less fallback.
        """
        if self.threshold_pace_min_per_km:
            return self.threshold_pace_min_per_km
        for distance_key, multiplier in (("10000m", 1.03), ("5000m", 1.07), ("3000m", 1.10)):
            pb = self.personal_bests.get(distance_key)
            if not pb:
                continue
            pace = _parse_pb_to_pace_per_km(pb, _distance_meters(distance_key))
            if pace:
                return round(pace * multiplier, 3)
        return None


@dataclass(frozen=True)
class UserRole:
    """Vorm.ai konto roll: kas sportlane või treener.

    Treener ei oma athlete_profile rida — tema andmed (sportlaste loend,
    nende profiilid + päevalogid) tulevad coach_athlete_links seoste kaudu.
    ``display_name`` on UI-s näidatav nimi (treenerile eelkõige tähtis,
    sest sportlasele kuvatakse ta seda nime saates).
    """

    role: str  # 'athlete' | 'coach'
    display_name: str = ""


@dataclass(frozen=True)
class UserConsent:
    """Legal-basis consent flags for processing sensitive training data.

    Training history, pulse, sleep, stress, illness flags, notes and derived
    readiness/load metrics can reveal health-related state. In Supabase mode we
    therefore keep an explicit consent row before storing or processing that
    data beyond a local demo session.
    """

    consent_version: str = DATA_CONSENT_VERSION
    sensitive_data_accepted_at: datetime | None = None
    llm_aggregate_accepted_at: datetime | None = None
    coach_access_terms_accepted_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def athlete_processing_ready(self) -> bool:
        return (
            self.sensitive_data_accepted_at is not None
            and self.llm_aggregate_accepted_at is not None
        )

    @property
    def coach_terms_ready(self) -> bool:
        return self.coach_access_terms_accepted_at is not None


@dataclass(frozen=True)
class CoachAthleteLink:
    """Treener ↔ sportlane seos kutsekoodi kaudu.

    Eluts: ``pending`` (treener lõi koodi, sportlane pole veel sisestanud)
    → ``active`` (sportlane sisestas koodi, andmed on jagatud) → ``revoked``
    (treener tühistas seose).
    """

    id: str
    coach_user_id: str
    athlete_user_id: str | None
    invite_code: str
    status: str  # 'pending' | 'active' | 'revoked'
    created_at: datetime | None = None
    accepted_at: datetime | None = None
    athlete_consent_at: datetime | None = None
    athlete_consent_version: str | None = None

    @property
    def has_active_data_consent(self) -> bool:
        return self.status == "active" and self.athlete_consent_at is not None


def _distance_meters(key: str) -> int:
    return {"1500m": 1500, "3000m": 3000, "5000m": 5000, "10000m": 10000}.get(key, 0)


def _parse_pb_to_pace_per_km(pb: str, distance_m: int) -> float | None:
    """Parse a `M:SS` or `MM:SS` PB string into average pace (min/km)."""
    if not pb or distance_m <= 0:
        return None
    try:
        parts = pb.strip().split(":")
        if len(parts) != 2:
            return None
        total_min = int(parts[0]) + int(parts[1]) / 60.0
        return total_min / (distance_m / 1000.0)
    except (TypeError, ValueError):
        return None
