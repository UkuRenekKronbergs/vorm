# Vorm.ai

**AI-põhine treeningkoormuse analüüsija kesk- ja pikamaajooksjatele.**

Tööriist võtab sisse sinu viimased treeningud (Strava / Garmini CSV / Polari JSON-eksport / näidisandmed), arvutab spordimeditsiinilised koormusnäitajad (TRIMP, ACWR, Banister CTL/ATL/TSB, monotoonsus), käivitab ohutusreeglite filtrid, tuvastab tippajad ja küsib suurest keelemudelist konkreetse soovituse tänase treeningu kohta koos loomuliku keele põhjendusega.

Projekt valmib Tartu Ülikooli *Tehisintellekti rakendamine*-aine raames kevadel 2026. Autor: Uku Renek Kronbergs.

---

## Miks seda on vaja

Harrastus- ja poolprofessionaalsetel jooksjatel on palju andmeid (nutikell, GPS, pulss, uni), aga vähe aega neid struktureeritult analüüsida. Olemasolevad tööriistad annavad kas ainult numbreid (Garmin Training Readiness) või maksavad palju ja eeldavad treeneri-tasemel tõlgendusoskust (TrainingPeaks). **Vorm.ai** annab **andmepõhise teise arvamuse** tänase planeeritud treeningu kohta — kas seda peaks jätkama, vähendama, asendama või vahele jätma — koos inimkeele põhjendusega, mis viitab konkreetsetele numbritele.

## Mis rakendus teeb

- **Ostab endasse** viimase 60 päeva treeningud (Strava API cache'iga / Strava-eksport CSV / Garmin GPX-kaust / lokaalne näidisandmestik).
- **Arvutab** akuutne 7-päeva koormus, krooniline 28-päeva koormus, ACWR, Banisteri TRIMP, Fosteri monotoonsus ja strain. Pulsiandmete puudumisel kasutab tempo-põhist rTSS-stiilis fallback'i (künnis-tempo tuletub 10 km PB-st).
- **Käivitab ohutusreeglid** — kui ACWR > 1.5, RPE ≥ 8 kaks päeva järjest, haigus või uni < 6 h, sunnitakse vastus ohutu kategooria suunas.
- **Prognoosib ACWR-trendi** scikit-learn lineaarse regressiooniga (viimased 14 päeva) — hoiatab juba enne, kui kasvav trend lõikab läbi ohulõike 1.5.
- **Küsib LLM-ilt soovituse** neljas kategoorias (jätka / vähenda / taastumispäev / alternatiivne) koos 2–4-lauselise põhjendusega. Toetab 3 prompti-varianti A/B-testimiseks (`baseline` / `numeric` / `conservative`).
- **Näitab** ACWR-kõverat, päevakoormust, nädalamahtu ja RPE-trendi Plotly-interaktiivgraafikutena.
- **Retrospektiivne test** — vali mineviku kuupäev, näita mudeli soovitust nii, nagu see päev oleks olnud täna.
- **Päevalogi** — pärast soovitust salvesta 1–5 hinnang kasulikkusele ja veenvusele, kas järgisid soovitust ning kuidas järgmine treening tundus. Vajalik valideerimise §4.3 jaoks.
- **Treeningkava** — genereerib täieliku päev-haaval struktureeritud võistluse-ettevalmistuse kava (base → build → peak → taper), arvestades sinu praegust vormi ja tippaegu. CSV-eksport TrainingPeaksi-sõbralik.

## Kiire alustamine

```bash
# 1. Kloonige
git clone https://github.com/UkuRenekKronbergs/vorm.git
cd vorm

# 2. Virtual environment + sõltuvused
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .                    # registreerib `vorm` paketi Pythoni teele

# 3. (Valikuline) LLM võtmed
cp .env.example .env
# Sisesta üks järgmistest: ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY.
# Provideri valimiseks sea LLM_PROVIDER=anthropic|openai|openrouter (vaikimisi: anthropic).
# Mudeli valimiseks sea LLM_MODEL (nt openrouter puhul: anthropic/claude-sonnet-4.6,
# deepseek/deepseek-v4-flash, meta-llama/llama-3.3-70b-instruct jne).

# 4. Käivita
streamlit run app.py
```

Esimesel käivitamisel on andmeallikas **Käsitsi lisamine** ja vaade algab tühjalt. Demo proovimiseks vajuta sidebar'is **Täida demoandmetega** — 90 päeva deterministlikult genereeritud näidisjooksu valmistavad terve UI demoks ette. Strava ühendamiseks vali sidebar'is **Strava API**, sisesta oma Strava API rakenduse **Client ID** ja **Client Secret** ning luba treeningute lugemine Strava lehel. Ilma LLM-võtmeta jookseb kõik peale soovituse teksti — ACWR, graafikud ja reeglitepõhine vastus töötavad ka offline.

### Strava-andmete vahemälu

Kui valid sidebari **Strava API**, kasutab rakendus `fetch_with_cache()`-i: lokaalsesse SQLite-faili (`data/cache/activities*.sqlite`) salvestatakse iga kunagi päritud treening. Igal järgneval käivitusel küsitakse Stravalt ainult delta (alates viimase cache-treeningu kuupäevast − 1 päev, et viimase päeva nimetuse muudatused korjata). API tõrke korral (429, võrk maas) tagastatakse vahemälu sisu — sünk ei kaota andmeid. Vt projekti plaan §5 Risk 2.

## Andmete formaat

Rakendus toetab kaht CSV-formaati:

**Natiivne** (soovituslik, kasutab rakendus ise lokaalses vahemälus):
```csv
id,activity_date,activity_type,distance_km,duration_min,avg_hr,max_hr_observed,avg_pace_min_per_km,elevation_gain_m,rpe,notes
a1,2026-04-18,Run,10.5,48.5,148,172,4.62,55,5,Easy aerobic
```

**Strava eksport** (https://www.strava.com/athlete/delete_your_account → Get a copy of your data):
```csv
Activity ID,Activity Date,Activity Type,Distance,Elapsed Time,Average Heart Rate,Max Heart Rate,Elevation Gain,Activity Name
12345,"Apr 18, 2026, 06:00:00 AM",Run,10500,2910,148,172,55,Morning Run
```

Rakendus tuvastab formaadi veergude järgi automaatselt.

## Arhitektuur

```
src/vorm/
├── config.py                # env-põhine konfiguratsioon (Config dataclass)
├── auth.py                  # Supabase email+parool login, reset ja sidebar user panel
├── data/
│   ├── models.py            # TrainingActivity, AthleteProfile, DailySubjective
│   ├── storage.py           # Lokaalne SQLite vahemälu + päevalogi (anon režiim)
│   ├── supabase_store.py    # Multi-user Supabase-store (profile + daily_log)
│   ├── strava.py            # stravalib OAuth-klient + cache-teadlik delta-sync
│   ├── garmin.py            # GPX-kaust fallback parser (§5 Risk 2)
│   ├── csv_loader.py        # Natiivne + Strava-eksport parser
│   ├── polar.py             # Polar Flow JSON → Strava HR-täiendus
│   └── sample.py            # Deterministlik näidisgeneraator
├── metrics/
│   ├── load.py              # TRIMP, ACWR, monotoonsus, Banister CTL/ATL/TSB, RPE-süntees
│   ├── forecast.py          # sklearn ACWR-trend prognoos (§2 statistiline turvafilter)
│   └── personal_bests.py    # Tippajad standard-distantsidele
├── rules/
│   └── safety.py            # Reeglipõhised ohutusfiltrid
├── llm/
│   ├── prompts.py           # Igapäevane prompt + few-shot näited + 3 A/B-varianti
│   ├── _json_utils.py       # Tolerantne JSON-parser (avatud mudelite jaoks)
│   └── client.py            # Anthropic + OpenAI + OpenRouter taustakliendid
├── planning/
│   ├── models.py            # PlanGoal, PlannedSession, WeekPlan, TrainingPlan
│   ├── prompts.py           # Treeningkava prompt + JSON skeem
│   └── generator.py         # LLM orkestreerimine, tolerantne parser
└── ui/
    └── charts.py            # Plotly graafikud
app.py                       # Streamlit entry point
scripts/
├── enrich_strava_with_polar.py   # CLI: Polari pulsiandmed Strava CSV-sse
├── strava_bootstrap.py           # CLI: legacy Strava refresh-token bootstrap
└── validate.py                   # CLI: PROJECT_PLAN §4 valideerimisharness
docs/
├── interview_script.md           # §4.4 kvalitatiivse intervjuu protokoll
├── supabase_auth_email_templates.md   # Supabase Auth emailide eestikeelsed mallid
├── supabase_auth_email_templates.json # Sama Management API payloadina
└── supabase_schema.sql           # Supabase DDL + RLS poliitikad (jooksuta Dashboardis)
```

Andmevoog:
```
Strava/CSV/Sample ─► TrainingActivity[] ─► Metrics (ACWR, TRIMP) ─► Safety rules ─► LLM prompt ─► JSON soovitus ─► UI
```

## Arenduskäik

```bash
# Testid
pytest
pytest --cov=src/vorm

# Linting (valikuline)
pip install ruff
ruff check .
```

Unit-testid katavad praegu (106 testi):
- Banisteri TRIMP-i käsitsi arvutatud referentsväärtused
- ACWR konvergeerub 1.0-le konstantse koormuse juures
- ACWR hüppab ohupiirile, kui 7-päeva koormus kolmekordistub
- Monotoonsus = None nullvariantsi puhul
- Safety rules — iga reegli fire-kontekst + precedence order
- CSV-parseri mõlemad formaadid
- Strava delta-sync: külm/soe vahemälu, API tõrke fallback, mitte-jooks filtreering
- Garmin GPX-parser: HR-aggregatsioon, mitte-jooksu filtreering, kaust-laadimine
- ACWR-trend regressioon: tasakaalu trend, danger-crossing, müra-supressioon
- Päevalogi SQLite roundtrip + upsert + skaala-valideerimine

CI töötab GitHub Actionsis iga push-i peal Python 3.11 ja 3.12 all.

## Valideerimisplaan

Projekt valideeritakse nelja etapina (vt [PROJECT_PLAN.md](PROJECT_PLAN.md) jaotis 4):

1. **Retrospektiivne test** 30 varasemal päeval (sh 5–7 teadaolevalt „kriitilist" päeva). Edu = ≥ 70% kattumist mu omaaegse otsusega.
2. **Treeneri kõrvutus** 14 järjestikusel päeval (18.05 – 01.06). Treener Ille Kukk hindab samu sisendeid ilma mudeli väljundit nägemata.
3. **Isiklik igapäevane kasutus** 14 päeva järjest — UI-s päevalogi (`Päevalogi` tab), kus iga päev login: kasulikkus (1–5), veenvus (1–5), kas järgisin ja järgmise treeningu enesetunne (1–5).
4. **Kvalitatiivne intervjuu** 2 treeningkaaslasega projekti lõpus. Skript: [docs/interview_script.md](docs/interview_script.md) (6 pool-struktureeritud küsimust).

### Valideerimisharness

[`scripts/validate.py`](scripts/validate.py) on automatiseeritud harness etappide 1 ja 2 jaoks. Kasutab pikendatud näidisandmestikku (Jan 2026 – 1. juuni 2026, sh kaks tehislikult induce'itud ülekoormusakent ja üks haiguseaken), arvutab iga päeva koormusnäitajad sama torujuhtmega nagu live-rakendus, ja võrdleb mudeli soovitust simuleeritud sportlase + treeneri otsustega. Päris valideerimine asendab simuleeritud otsused logitud tõe-väärtustega.

```bash
# Reegli-režiim (offline, kohene, deterministlik)
python scripts/validate.py

# LLM-režiim — kasutab .env-i providerit (Anthropic / OpenAI / OpenRouter)
python scripts/validate.py --llm

# Sundi värsked LLM-päringud (ignoreeri validation_llm_cache.json)
python scripts/validate.py --llm --no-cache

# Suitsutest — 5 päeva kummalgi etapil
python scripts/validate.py --llm --limit 5

# A/B-testi prompti varianti (baseline / numeric / conservative)
python scripts/validate.py --llm --prompt-variant numeric
```

Väljundid:
- `validation_report.md` — markdown-aruanne (kokkuvõte, metoodika, päeva-tabelid, lahkuminekute klassifikatsioon).
- `validation_data.csv` — per-day võrdlustabel.
- `validation_llm_cache.json` — ainult `--llm` režiimis; LLM-vastused (cache-võti = sisendi hash + mudel + prompti versioon, automaatne invalideerimine).

## Tasuta deploy — Streamlit Community Cloud

Rakendus on cloud-deploy-valmis. Failisüsteemil ei pea olema kirjeldatud sõltuvusi peale `requirements.txt`-i; saladused tulevad Streamlit Cloud'i settings'ist.

### Sammud

1. **Logi sisse** [share.streamlit.io](https://share.streamlit.io) GitHubi kaudu.
2. **Deploy app** → repo: `UkuRenekKronbergs/vorm`, branch: `main`, main file: `app.py`.
3. **Advanced settings → Python version:** vali `3.13` (matches [`runtime.txt`](runtime.txt)).
4. **App settings → Secrets** — kleebi TOML-vormingus (näide OpenRouteri tasuta DeepSeek V4 Flash-iga, 1M context):
   ```toml
   LLM_PROVIDER = "openrouter"
   LLM_MODEL = "deepseek/deepseek-v4-flash:free"
   LLM_TEMPERATURE = "0"
   OPENROUTER_API_KEY = "sk-or-v1-..."   # https://openrouter.ai/keys
   # Alternatiivid (kontrollitud 2026-05 seisuga):
   # LLM_MODEL = "openai/gpt-oss-120b:free"                    # 120B, tasuta
   # LLM_MODEL = "nousresearch/hermes-3-llama-3.1-405b:free"   # 405B, tasuta
   # Google AI Studio (parem tasuta-kvoot: 15 RPM / 1500 RPD):
   # LLM_PROVIDER = "google"
   # LLM_MODEL = "gemini-3.1-flash-lite"
   # GOOGLE_API_KEY = "AIza..."   # https://aistudio.google.com/app/apikey
   # Tasuline (kõrgeim kvaliteet, ~$0.01-0.05 päringu kohta):
   # LLM_PROVIDER = "anthropic"
   # LLM_MODEL = "claude-sonnet-4-6"
   # ANTHROPIC_API_KEY = "sk-ant-..."
   # OPENAI_API_KEY    = "sk-..."
   # Strava (valikuline vana/admin voog — kasutaja saab selle nüüd ka UI-s ühendada):
   # STRAVA_CLIENT_ID     = "12345"
   # STRAVA_CLIENT_SECRET = "..."
   # STRAVA_REFRESH_TOKEN = "..."
   ```
5. Saad URL-i kujul `https://vorm-ai.streamlit.app`.

Cloud-režiimis vaikimisi andmeallikas on **Käsitsi lisamine** ja see on tühi. Täielik demo töötab ilma isikuandmeteta sidebar'i **Täida demoandmetega** nupu kaudu. Külalisrežiim on nüüd ainult demoandmetele: CSV/Strava/Garmin import ja LLM-päringud on külalisel piiratud, et tundlikke treeningu- või terviseandmeid ei töödeldaks ilma nõusolekuta.

### Cloud-spetsiifika

- **Failisüsteem on efemeerne.** SQLite vahemälu (`data/cache/activities.sqlite`) kaob iga restardi peal — kuid sportlase profiil ja päevalogi saab püsima jätta läbi **Supabase-režiimi** (vt allpool). Anonüümses režiimis (ilma Supabase'ita) ka päevalogi efemeerne.
- **App magab 7 päeva idle järel.** Esmase päringu cold-start ~30 s.
- **Strava OAuth** töötab nüüd veebis. Strava API rakenduse seadetes pane **Authorization Callback Domain** samaks domeeniks, mida sidebar kuvab (nt `vorm-ai.streamlit.app` või lokaalselt `localhost`).
- **RAM ~1 GB.** Praegune sõltuvuste komplekt (Streamlit + pandas + scikit-learn) mahub ära ~400 MB peal.

### Konfiguratsiooni resolutsioon

`vorm.config.load_config()` otsib iga võtit kahest kohast (esimese leitu võidab):

1. Process environment / `.env`-fail (lokaalne arendus, `python-dotenv` laeb)
2. `streamlit.secrets` (Streamlit Cloud)

Sama kood töötab mõlemas keskkonnas.

## Multi-user režiim (Supabase)

Vaikimisi käivitub rakendus **anonüümses ühe-kasutaja režiimis** lokaalse SQLite'iga. Kui seadistad **Supabase'i** (URL + anon-võti), lülitub rakendus **multi-user režiimi**:

- **Sisselogimine** email + parooliga. Esmakordsel registreerumisel saadab Supabase kinnitusmaili — pärast lingile klikkimist pole kinnitamist enam vaja, ainult email + parool.
- **Parooli taastamine** on login-väravas eraldi tabina olemas. Kasutaja saab taastamislingi emailile, avab lingi ja määrab uue parooli samas Streamlit rakenduses.
- **Brauseri refresh ei logi välja.** Rakendus hoiab brauseri URL-is ainult juhuslikku sessiooni-ID-d (`?s=...`); Supabase tokenid jäävad serveripoole registrisse ja sessioon taastatakse refresh-tokeniga. Serveri restart/redeploy nõuab uuesti sisselogimist.
- **Sportlase profiil**, **päevalogi** ja **Strava ühendus** salvestuvad pilve — säilivad redeploy'de vahel, näha igast seadmest. Profiil **salvestub automaatselt** kui väärtusi muudad.
- **Andmetöötluse nõusolek** — enne pilverežiimis profiili, päevalogi, Strava ühenduse või LLM-ile minevate agregeeritud näitajate kasutamist peab sportlane kinnitama nõusoleku. Treener peab kinnitama, et töötleb sportlase andmeid ainult kokkulepitud eesmärgil.
- **Row-Level Security** — iga kasutaja näeb ainult enda andmeid; PostgreSQL võtab vastutuse, mitte rakenduse-kood.
- **Treeneriga jagamine** — kutsekood ei ole ise nõusolek. Sportlane peab kutsekoodi sisestamisel eraldi kinnitama, et treener võib näha profiili, päevalogi, subjektiivseid sisendeid ja tuletatud koormusnäitajaid. Vanad treeneri lingid ilma `athlete_consent_at` ajatemplita ei anna treenerile tundlikele ridadele ligipääsu.
- **Strava-vahemälu** jääb endiselt lokaalseks SQLite'iks, aga cache-fail on kasutaja/ühenduse järgi eristatud.

### Seadistamine

1. **Loo projekt** [supabase.com/dashboard](https://supabase.com/dashboard) → New project (tasuta tier: 500 MB DB, 50 000 kuist kasutajat).
2. **Loo skeem** — Dashboard → SQL Editor → New query → kleebi [`docs/supabase_schema.sql`](docs/supabase_schema.sql) → Run. Loob tabelid `user_consents`, `athlete_profiles`, `daily_logs`, `coach_athlete_links` jm koos RLS-poliitikatega.
3. **Võta võtmed** — Settings → API → kopeeri `Project URL` ja `anon` / `publishable` võti. **Ära kasuta** `service_role` / `secret` võtit — see läbib RLS-i ja on admin-võti, mida rakendus ei vaja.
4. **Confirm email** — Authentication → Sign In / Providers → Email → veendu, et **"Confirm email" on ON** (vaikimisi nii). Nii saab kasutaja esmaregistreerumisel kinnitusmaili; pärast kinnitamist piisab edaspidi ainult email + parool.
5. **Email template eesti keelde** — Authentication → Email Templates → "Confirm signup" ja "Reset password". Valmis mallid on failis [`docs/supabase_auth_email_templates.md`](docs/supabase_auth_email_templates.md); Management API payload on failis [`docs/supabase_auth_email_templates.json`](docs/supabase_auth_email_templates.json). Uutele kasutajatele läheb signup metadata sisse `language = "et"`, nii et sama template'i saab hiljem mitmekeelseks teha.
6. **Custom SMTP** (soovitatav väljaspool demot) — Authentication → Settings → SMTP Settings. Supabase vaikimisi emailiserver sobib testimiseks, aga tootmises/demos võib rate-limit või lubatud aadresside piirang segada kinnitus- ja taastamiskirju.
7. **Site URL** — Authentication → URL Configuration → Site URL = `http://localhost:8501` (lokaalseks arenduseks) või `https://your-app.streamlit.app` (cloud). Kinnitus- ja parooli taastamise lingile klikkides suunab Supabase siia tagasi.
8. **Konfigureeri** — lisa `.env`-i (lokaalne) või Streamlit Secrets'i (cloud):
   ```toml
   SUPABASE_URL = "https://xxxxx.supabase.co"
   SUPABASE_ANON_KEY = "sb_publishable_..."     # või vanem JWT-vormingus anon-võti
   ```
9. **Käivita** rakendus — login-värav ilmub automaatselt, kui mõlemad võtmed on olemas. Tabid: **Logi sisse**, **Loo uus konto** ja **Taasta parool**.

### Anonüümse režiimi tagasi lülitamine

Eemalda `SUPABASE_URL` ja `SUPABASE_ANON_KEY` env-ist või Streamlit secrets'ist — rakendus läheb tagasi lokaalse SQLite'i + ilma-login'i peale (kasulik offline-demoks või lokaalseks arenduseks).

## Privaatsus

- Treeningandmed (GPS-punktid, tooraine pulsiribaread) **ei** liigu LLM-pakkuja serverisse — LLM näeb ainult agregeeritud näitajaid ja metaandmeid.
- Strava ühendus hoitakse lokaalses SQLite'is või Supabase multi-user režiimis kasutaja enda `strava_connections` reas. `.env` / Streamlit secrets voog töötab endiselt admin-seadistusena, aga võtmeid ei tohi commit'ida.
- **Multi-user režiimis** (Supabase) — profiil, päevalogi ja Strava ühendus salvestuvad pilve alles pärast nõusoleku vormi. Row-Level Security tagab, et iga kasutaja näeb ainult enda andmeid. Anon-võti on disainilt avalik (kaitstud RLS-iga); `service_role` võtit rakendus ei kasuta.
- **Treeneri ligipääs** tekib ainult sportlase eraldi jagamisnõusoleku korral. Andmed võivad võimaldada järeldusi tervise, taastumise, pohmaka või menstruaaltsükli kohta, seega ei piisa sellest, et “teine kasutaja ei näe”: ka treeneril või projekti haldajal peab töötlemiseks olema õiguslik alus.

## Vastutuspiir

Tööriist on **otsustustugi**, mitte asendaja treenerile ega arstile. Vigastuse, haiguse või treeningplaani põhimõttelise küsimuse puhul pöördu oma treeneri või arsti poole. Soovitus on sama usaldusväärne kui sisendandmed ja mudeli tõlgendus — kriitilist mõtlemist ei saa sellele delegeerida.

## Litsents

MIT — vt [LICENSE](LICENSE).

## Autor

Uku Renek Kronbergs ([@ukurenek](https://github.com/ukurenek))
