-- Vorm.ai — Supabase skeem
--
-- Käivita see üks kord:
--   Supabase Dashboard → SQL Editor → New query → kleebi sisu → Run.
--
-- Loob kuus kasutaja-skoobiga tabelit ja kutsekoodi aktsepteerimise RPC:
--   - user_roles          — sportlane vs treener (üks rida per kasutaja)
--   - coach_athlete_links — treener ↔ sportlane seos (kutsekoodiga)
--   - athlete_profiles    — sportlase profiil (üks rida per sportlane)
--   - daily_logs          — päeva-logi (Project Plan §4.3, üks rida per kasutaja+kuupäev)
--   - strava_connections  — kasutaja Strava OAuth seos (üks rida per kasutaja)
--   - coach_decisions     — treeneri pimemenetluses tehtud päevaotsused (§4.2)
--
-- Row-Level Security on igal tabelil sees: iga kasutaja näeb/muudab AINULT
-- enda ridu. Treener näeb LISAKS oma seotud sportlaste profiili, päevalogi
-- ja coach_decisions ridu (read + kirjuta coach_decisions-i jaoks).
--
-- Skript on idempotentne — võid uuesti käivitada, ilma andmeid kaotamata.

GRANT USAGE ON SCHEMA public TO authenticated;

-- ===== user_roles ====================================================
-- Iga konto on kas 'athlete' (sportlane) või 'coach' (treener).
-- Treenerid ei oma athlete_profiles rida — nad seovad end coach_athlete_links
-- kaudu sportlastega ja näevad sportlaste andmeid läbi nende seoste.
CREATE TABLE IF NOT EXISTS public.user_roles (
    user_id      UUID        PRIMARY KEY
                             REFERENCES auth.users(id)
                             ON DELETE CASCADE,
    role         TEXT        NOT NULL DEFAULT 'athlete'
                             CHECK (role IN ('athlete', 'coach')),
    display_name TEXT        NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.user_roles ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.user_roles TO authenticated;

DROP POLICY IF EXISTS "Users select own role" ON public.user_roles;
DROP POLICY IF EXISTS "Users insert own role" ON public.user_roles;
DROP POLICY IF EXISTS "Users update own role" ON public.user_roles;
DROP POLICY IF EXISTS "Users delete own role" ON public.user_roles;

CREATE POLICY "Users select own role" ON public.user_roles
    FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Users insert own role" ON public.user_roles
    FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Users update own role" ON public.user_roles
    FOR UPDATE USING (auth.uid() = user_id)
                WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Users delete own role" ON public.user_roles
    FOR DELETE USING (auth.uid() = user_id);

-- NB: kaks ristkooslast poliisi (treener näeb sportlase rolli, sportlane
-- näeb treeneri rolli) on defineeritud allpool, pärast coach_athlete_links
-- tabeli ja is_active_coach_of() funktsiooni loomist — muidu CREATE POLICY
-- viskaks "relation does not exist" vea.

-- Olemasolevad kasutajad → vaikimisi sportlasteks (et juba registreerunud
-- testkasutajad ei jääks rollideta). ON CONFLICT hoiab idempotentseks.
INSERT INTO public.user_roles (user_id, role)
SELECT id, 'athlete' FROM auth.users
ON CONFLICT (user_id) DO NOTHING;


-- ===== coach_athlete_links ============================================
-- Treener loob kutsekoodi (athlete_user_id = NULL, status = 'pending').
-- Sportlane sisestab koodi → public.accept_coach_invite(...) uuendab rea:
-- athlete_user_id = tema id, status = 'active'. Üks (treener, sportlane) paar on unikaalne, aga
-- sportlasel võib olla mitu treenerit ja vastupidi.
CREATE TABLE IF NOT EXISTS public.coach_athlete_links (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_user_id    UUID        NOT NULL
                                 REFERENCES auth.users(id) ON DELETE CASCADE,
    athlete_user_id  UUID        REFERENCES auth.users(id) ON DELETE CASCADE,
    invite_code      TEXT        NOT NULL UNIQUE,
    status           TEXT        NOT NULL DEFAULT 'pending'
                                 CHECK (status IN ('pending', 'active', 'revoked')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    accepted_at      TIMESTAMPTZ,
    UNIQUE (coach_user_id, athlete_user_id)
);

CREATE INDEX IF NOT EXISTS idx_links_coach ON public.coach_athlete_links (coach_user_id);
CREATE INDEX IF NOT EXISTS idx_links_athlete ON public.coach_athlete_links (athlete_user_id);

ALTER TABLE public.coach_athlete_links ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.coach_athlete_links TO authenticated;

DROP POLICY IF EXISTS "Links select coach side" ON public.coach_athlete_links;
DROP POLICY IF EXISTS "Links select athlete side" ON public.coach_athlete_links;
DROP POLICY IF EXISTS "Links select pending by code" ON public.coach_athlete_links;
DROP POLICY IF EXISTS "Links insert by coach" ON public.coach_athlete_links;
DROP POLICY IF EXISTS "Links accept by athlete" ON public.coach_athlete_links;
DROP POLICY IF EXISTS "Links update by coach" ON public.coach_athlete_links;
DROP POLICY IF EXISTS "Links delete by coach" ON public.coach_athlete_links;

-- Treener näeb enda loodud seoseid.
CREATE POLICY "Links select coach side" ON public.coach_athlete_links
    FOR SELECT USING (auth.uid() = coach_user_id);
-- Sportlane näeb seoseid, mis tema kontot puudutavad.
CREATE POLICY "Links select athlete side" ON public.coach_athlete_links
    FOR SELECT USING (auth.uid() = athlete_user_id);
-- Treener loob seose (athlete_user_id = NULL invite-vormis).
CREATE POLICY "Links insert by coach" ON public.coach_athlete_links
    FOR INSERT WITH CHECK (auth.uid() = coach_user_id);
-- Sportlane EI saa pending-kutseridu otse SELECT-ida/UPDATE-ida: Postgres RLS
-- nõuaks UPDATE jaoks ka SELECT-poliitikat ja see lekiks kasutamata kutsekoodid.
-- Koodi aktsepteerimine käib allpool defineeritud public.accept_coach_invite(...)
-- RPC kaudu.
-- Treener saab oma seose tühistada (status='revoked') või kustutada.
CREATE POLICY "Links update by coach" ON public.coach_athlete_links
    FOR UPDATE USING (auth.uid() = coach_user_id)
                WITH CHECK (auth.uid() = coach_user_id);
CREATE POLICY "Links delete by coach" ON public.coach_athlete_links
    FOR DELETE USING (auth.uid() = coach_user_id);


-- ===== private helperid + kutse RPC ====================================
-- SECURITY DEFINER helperid elavad private skeemis, mitte public Data API
-- skeemis. Publicus on ainult õhuke security-invoker RPC wrapper, mida
-- Streamlit klient saab kutsuda.
CREATE SCHEMA IF NOT EXISTS private;
REVOKE ALL ON SCHEMA private FROM PUBLIC;
GRANT USAGE ON SCHEMA private TO authenticated;

-- Helper: tagastab TRUE, kui auth.uid() on aktiivne treener antud
-- sportlasele. Kasutame seda teiste tabelite RLS-poliisides, et treener
-- näeks ainult seotud sportlaste andmeid. SECURITY DEFINER on vajalik,
-- sest muidu coach_athlete_links-i enda RLS blokeeriks lookup'i, kui
-- seda kasutatakse teise tabeli policy-kontekstis.
CREATE OR REPLACE FUNCTION private.is_active_coach_of(p_athlete_user_id UUID)
RETURNS BOOLEAN
LANGUAGE SQL
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.coach_athlete_links
        WHERE coach_user_id = auth.uid()
          AND athlete_user_id = p_athlete_user_id
          AND status = 'active'
    );
$$;

REVOKE ALL ON FUNCTION private.is_active_coach_of(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION private.is_active_coach_of(UUID) TO authenticated;

-- Sportlane aktsepteerib kutsekoodi. See on RPC, mitte tabeli otse-UPDATE,
-- sest pending invite'i SELECT-poliitika lekiks kõik kasutamata koodid.
CREATE OR REPLACE FUNCTION private.accept_coach_invite(p_invite_code TEXT)
RETURNS SETOF public.coach_athlete_links
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_actor UUID := auth.uid();
    v_cleaned TEXT := upper(btrim(coalesce(p_invite_code, '')));
BEGIN
    IF v_actor IS NULL OR v_cleaned = '' THEN
        RETURN;
    END IF;

    RETURN QUERY
    UPDATE public.coach_athlete_links AS link
       SET athlete_user_id = v_actor,
           status = 'active',
           accepted_at = now()
     WHERE link.invite_code = v_cleaned
       AND link.status = 'pending'
       AND link.athlete_user_id IS NULL
       AND link.coach_user_id <> v_actor
       AND NOT EXISTS (
           SELECT 1
             FROM public.coach_athlete_links AS existing
            WHERE existing.coach_user_id = link.coach_user_id
              AND existing.athlete_user_id = v_actor
              AND existing.status = 'active'
       )
     RETURNING link.*;
END;
$$;

REVOKE ALL ON FUNCTION private.accept_coach_invite(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION private.accept_coach_invite(TEXT) TO authenticated;

CREATE OR REPLACE FUNCTION public.accept_coach_invite(p_invite_code TEXT)
RETURNS SETOF public.coach_athlete_links
LANGUAGE SQL
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
    SELECT * FROM private.accept_coach_invite(p_invite_code);
$$;

REVOKE ALL ON FUNCTION public.accept_coach_invite(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.accept_coach_invite(TEXT) TO authenticated;


-- ===== user_roles ristkooslased poliisid =============================
-- Need defineeritakse alles nüüd, sest need viitavad coach_athlete_links
-- tabelile ja is_active_coach_of() funktsioonile, mille olemasolu
-- CREATE POLICY kontrollib defineerimishetkel.

-- Sportlane näeb oma seotud treeneri rolli/display_name'i, et UI saaks
-- kuvada "Treener: Ille Kukk" UUIDi asemel.
DROP POLICY IF EXISTS "Athletes select coach role" ON public.user_roles;
CREATE POLICY "Athletes select coach role" ON public.user_roles
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM public.coach_athlete_links
            WHERE athlete_user_id = auth.uid()
              AND coach_user_id = user_roles.user_id
              AND status = 'active'
        )
    );

-- Treener näeb oma seotud sportlase rolli (peamiselt mugavus, kasutab
-- juba olemasolevat is_active_coach_of() helperit).
DROP POLICY IF EXISTS "Coaches select athlete role" ON public.user_roles;
CREATE POLICY "Coaches select athlete role" ON public.user_roles
    FOR SELECT USING (private.is_active_coach_of(user_id));


-- ===== athlete_profiles ==============================================
CREATE TABLE IF NOT EXISTS public.athlete_profiles (
    user_id                   UUID        PRIMARY KEY
                                          REFERENCES auth.users(id)
                                          ON DELETE CASCADE,
    name                      TEXT        NOT NULL,
    age                       INTEGER     NOT NULL CHECK (age BETWEEN 10 AND 100),
    sex                       TEXT        NOT NULL CHECK (sex IN ('M', 'F')),
    max_hr                    INTEGER     NOT NULL CHECK (max_hr BETWEEN 100 AND 240),
    resting_hr                INTEGER     NOT NULL CHECK (resting_hr BETWEEN 20 AND 100),
    training_years            INTEGER     NOT NULL DEFAULT 0 CHECK (training_years >= 0),
    season_goal               TEXT        DEFAULT '',
    personal_bests            JSONB       DEFAULT '{}'::jsonb,
    threshold_pace_min_per_km REAL,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.athlete_profiles ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.athlete_profiles TO authenticated;

DROP POLICY IF EXISTS "Users select own profile" ON public.athlete_profiles;
DROP POLICY IF EXISTS "Users insert own profile" ON public.athlete_profiles;
DROP POLICY IF EXISTS "Users update own profile" ON public.athlete_profiles;
DROP POLICY IF EXISTS "Users delete own profile" ON public.athlete_profiles;

CREATE POLICY "Users select own profile" ON public.athlete_profiles
    FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Users insert own profile" ON public.athlete_profiles
    FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Users update own profile" ON public.athlete_profiles
    FOR UPDATE USING (auth.uid() = user_id)
                WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Users delete own profile" ON public.athlete_profiles
    FOR DELETE USING (auth.uid() = user_id);

-- Treener näeb seotud sportlase profiili (read-only).
DROP POLICY IF EXISTS "Coaches select linked athlete profile" ON public.athlete_profiles;
CREATE POLICY "Coaches select linked athlete profile" ON public.athlete_profiles
    FOR SELECT USING (private.is_active_coach_of(user_id));

-- Hoia updated_at jooksvalt värske.
CREATE OR REPLACE FUNCTION public.tg_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_profiles_updated_at ON public.athlete_profiles;
CREATE TRIGGER trg_profiles_updated_at
    BEFORE UPDATE ON public.athlete_profiles
    FOR EACH ROW EXECUTE FUNCTION public.tg_set_updated_at();

DROP TRIGGER IF EXISTS trg_user_roles_updated_at ON public.user_roles;
CREATE TRIGGER trg_user_roles_updated_at
    BEFORE UPDATE ON public.user_roles
    FOR EACH ROW EXECUTE FUNCTION public.tg_set_updated_at();


-- ===== strava_connections ============================================
CREATE TABLE IF NOT EXISTS public.strava_connections (
    user_id       UUID        PRIMARY KEY
                              REFERENCES auth.users(id)
                              ON DELETE CASCADE,
    client_id     TEXT        NOT NULL,
    client_secret TEXT        NOT NULL,
    refresh_token TEXT        NOT NULL,
    athlete_id    TEXT,
    athlete_name  TEXT,
    scope         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.strava_connections ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.strava_connections TO authenticated;

DROP POLICY IF EXISTS "Users select own Strava connection" ON public.strava_connections;
DROP POLICY IF EXISTS "Users insert own Strava connection" ON public.strava_connections;
DROP POLICY IF EXISTS "Users update own Strava connection" ON public.strava_connections;
DROP POLICY IF EXISTS "Users delete own Strava connection" ON public.strava_connections;

CREATE POLICY "Users select own Strava connection" ON public.strava_connections
    FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Users insert own Strava connection" ON public.strava_connections
    FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Users update own Strava connection" ON public.strava_connections
    FOR UPDATE USING (auth.uid() = user_id)
                WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Users delete own Strava connection" ON public.strava_connections
    FOR DELETE USING (auth.uid() = user_id);

DROP TRIGGER IF EXISTS trg_strava_connections_updated_at ON public.strava_connections;
CREATE TRIGGER trg_strava_connections_updated_at
    BEFORE UPDATE ON public.strava_connections
    FOR EACH ROW EXECUTE FUNCTION public.tg_set_updated_at();


-- ===== daily_logs ====================================================
CREATE TABLE IF NOT EXISTS public.daily_logs (
    user_id              UUID        NOT NULL
                                     REFERENCES auth.users(id)
                                     ON DELETE CASCADE,
    log_date             DATE        NOT NULL,
    recommended_category TEXT        NOT NULL,
    rationale_excerpt    TEXT,
    usefulness           INTEGER     CHECK (usefulness BETWEEN 1 AND 5),
    persuasiveness       INTEGER     CHECK (persuasiveness BETWEEN 1 AND 5),
    followed             TEXT        CHECK (followed IN ('yes', 'no', 'partial')),
    next_session_feeling INTEGER     CHECK (next_session_feeling BETWEEN 1 AND 5),
    notes                TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, log_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_logs_user_date
    ON public.daily_logs (user_id, log_date DESC);

ALTER TABLE public.daily_logs ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.daily_logs TO authenticated;

DROP POLICY IF EXISTS "Users select own logs" ON public.daily_logs;
DROP POLICY IF EXISTS "Users insert own logs" ON public.daily_logs;
DROP POLICY IF EXISTS "Users update own logs" ON public.daily_logs;
DROP POLICY IF EXISTS "Users delete own logs" ON public.daily_logs;

CREATE POLICY "Users select own logs" ON public.daily_logs
    FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Users insert own logs" ON public.daily_logs
    FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Users update own logs" ON public.daily_logs
    FOR UPDATE USING (auth.uid() = user_id)
                WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Users delete own logs" ON public.daily_logs
    FOR DELETE USING (auth.uid() = user_id);

-- Treener näeb seotud sportlase päevalogi (read-only).
DROP POLICY IF EXISTS "Coaches select linked athlete logs" ON public.daily_logs;
CREATE POLICY "Coaches select linked athlete logs" ON public.daily_logs
    FOR SELECT USING (private.is_active_coach_of(user_id));


-- ===== coach_decisions ================================================
-- §4.2 valideerimisetapp: treener sisestab oma päevaotsuse Vorm.ai-st
-- nägemata. Üks rida per (kasutaja, kuupäev) — kui sama päeva peale
-- saadetakse uus otsus, varasem kirjutatakse üle.
CREATE TABLE IF NOT EXISTS public.coach_decisions (
    user_id              UUID        NOT NULL
                                     REFERENCES auth.users(id)
                                     ON DELETE CASCADE,
    decision_date        DATE        NOT NULL,
    coach_name           TEXT        NOT NULL DEFAULT 'Ille Kukk',
    recommended_category TEXT        NOT NULL,
    rationale            TEXT,
    notes                TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, decision_date)
);

CREATE INDEX IF NOT EXISTS idx_coach_decisions_user_date
    ON public.coach_decisions (user_id, decision_date DESC);

ALTER TABLE public.coach_decisions ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.coach_decisions TO authenticated;

DROP POLICY IF EXISTS "Users select own coach decisions" ON public.coach_decisions;
DROP POLICY IF EXISTS "Users insert own coach decisions" ON public.coach_decisions;
DROP POLICY IF EXISTS "Users update own coach decisions" ON public.coach_decisions;
DROP POLICY IF EXISTS "Users delete own coach decisions" ON public.coach_decisions;

CREATE POLICY "Users select own coach decisions" ON public.coach_decisions
    FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Users insert own coach decisions" ON public.coach_decisions
    FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Users update own coach decisions" ON public.coach_decisions
    FOR UPDATE USING (auth.uid() = user_id)
                WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Users delete own coach decisions" ON public.coach_decisions
    FOR DELETE USING (auth.uid() = user_id);

-- Treener saab seotud sportlase päevaotsuseid lugeda, lisada ja muuta —
-- §4.2 pimemenetluses sisestab treener oma otsuse otse sportlase
-- konteksti (varem tegi seda sportlane ise ümberkirjutajana).
DROP POLICY IF EXISTS "Coaches select linked athlete decisions" ON public.coach_decisions;
DROP POLICY IF EXISTS "Coaches insert linked athlete decisions" ON public.coach_decisions;
DROP POLICY IF EXISTS "Coaches update linked athlete decisions" ON public.coach_decisions;
DROP POLICY IF EXISTS "Coaches delete linked athlete decisions" ON public.coach_decisions;
CREATE POLICY "Coaches select linked athlete decisions" ON public.coach_decisions
    FOR SELECT USING (private.is_active_coach_of(user_id));
CREATE POLICY "Coaches insert linked athlete decisions" ON public.coach_decisions
    FOR INSERT WITH CHECK (private.is_active_coach_of(user_id));
CREATE POLICY "Coaches update linked athlete decisions" ON public.coach_decisions
    FOR UPDATE USING (private.is_active_coach_of(user_id))
                WITH CHECK (private.is_active_coach_of(user_id));
CREATE POLICY "Coaches delete linked athlete decisions" ON public.coach_decisions
    FOR DELETE USING (private.is_active_coach_of(user_id));

-- Vanemates skeemi versioonides oli SECURITY DEFINER helper public skeemis.
-- Kõik poliitikad kasutavad nüüd private.is_active_coach_of(...), nii et vana
-- public-funktsiooni võib turvaliselt eemaldada.
DROP FUNCTION IF EXISTS public.is_active_coach_of(UUID);
