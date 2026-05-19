# Projektiplaan

**AI-põhine treeningkoormuse analüüsija kesk- ja pikamaajooksjatele**

**Autor:** Uku Renek Kronbergs
**Ainekood:** Tehisintellekti rakendamine (Tartu Ülikool, kevad 2026)
**Projekti vorm:** üksi — kõik rollid (projektijuht, AI-insener, andmeinsener, UI-arendaja, kasutaja ja valideerija) on minu kanda

---

## Lühikirjeldus

AI-põhine tööriist kesk- ja pikamaajooksjatele, mis analüüsib treeningandmeid (Strava/Garmin) ja annab keelemudeli abil igapäevaseid soovitusi treeningkoormuse kohandamiseks koos loomulikus keeles põhjendusega. Eesmärk: anda harrastus- ja poolprofessionaalsele jooksjale „andmepõhine teine arvamus" tänase planeeritud treeningu kohta.

## 1. Probleemi püstitus ja väärtuspakkumine

### Probleemi kirjeldus

Harrastus- ja poolprofessionaalsetel kesk-/pikamaajooksjatel (800 m – 10 000 m) puudub süstemaatiline andmepõhine tugi igapäevase treeningkoormuse kohandamiseks. Nutikellad ja rakendused koguvad massiliselt andmeid (GPS, pulss, tempo, uneaeg), kuid neid analüüsitakse harva struktureeritult. Koormuse kohandamine — kui sportlane on väsinud, haige, stressis või vastupidi oodatust paremas vormis — jääb tihti reaktiivseks: sportlane märkab ülekoormust alles pärast kehva treeningut, hommikust väsimust või kerget vigastust.

### Sihtgrupp / klient

- **Primaarne kasutaja:** mina ise — poolprofessionaalne kesk-/pikamaajooksja, kes on ~3 aastat kogunud treeningandmeid Stravas ja Garminis.
- **Laiem sihtgrupp:** harrastus- ja poolprofessionaalsed jooksjad, kes kasutavad juba treeninglogisid (Strava, Garmin Connect, TrainingPeaks), kuid kellele pole olemas praktilist analüüsitööriista. Hinnanguliselt on Eestis ~5 000–10 000 sellist kasutajat.
- **Teisene kasutaja:** treenerid, kes töötavad mitme sportlasega ning kellele „teine arvamus" samade andmete põhjal oleks ajakokkuhoid ja otsustustugi.

### Praegune lahendus

Turu olemasolevad tööriistad ja nende puudused:

- **TrainingPeaks** — võimekas visualiseerija (CTL/ATL/TSB), aga maksuline (~€200/a), nõuab koormusnäitajate mõistmist ega anna konkreetseid soovitusi.
- **Strava Premium** (Fitness & Freshness) — annab väsimuse skoori, aga mitte soovitust järgmise treeningu kohta.
- **Garmin „Training Readiness"** — üks arvuline skoor (0–100), ilma selge põhjenduse ega konteksti-spetsiifilise soovituseta.

Domineeriv praktika on endiselt treeneri kogemustunne + sportlase hommikune enesetunde-raport — see jääb reaktiivseks ja skaleerub treeneri mälu ulatuses.

**Puuduv lüli:** personaalne andmepõhine teine arvamus, mis ühendab objektiivsed näitajad subjektiivsete signaalidega ja põhjendab oma soovituse inimkeeles.

### Pakutud lahendus

Python-põhine veebirakendus (Streamlit), mis iga päev:

1. impordib automaatselt viimased treeningud Strava/Garmin API kaudu;
2. arvutab klassikalised spordianalüütika näitajad (ACWR, TRIMP, monotoonsus, trendid);
3. komplekteerib struktureeritud konteksti (arvulised näitajad + sportlase subjektiivsed märkused + tänane plaan) ja saadab selle keelemudelile;
4. genereerib konkreetse tegevussoovituse + 2–4-lauselise põhjenduse + valikulise plaani-modifikatsiooni.

### Sisendandmed

- **Automaatne import** (Strava/Garmin API): GPS-rajad, südame löögisagedus (pidev), tempo, distants, kestus, kõrguse muutused — viimase 60 päeva kohta (ACWR vajab vähemalt 28-päevast kroonilist akent).
- **Kasutaja sisend (igapäevane):** tänane kavandatud treening (nt „8×400 m intervallid, pulss 170+"), subjektiivne raskushinnang eelmisele treeningule (RPE 1–10), uneaeg ja lühimärkused (haigus, stress, muu kontekst).
- **Kasutaja sisend (ühekordne):** sportlase profiil — vanus, sugu, treeningstaaž, hooaja eesmärgid, tippajad põhidistantsidel.

### Oodatav väljund

- **Soovituse kategooria:** „Jätka plaanipäraselt" / „Vähenda intensiivsust" / „Lisa taastumispäev" / „Alternatiivne treening".
- **Loomulikus keeles põhjendus:** 2–4 lauset, mis viitab konkreetsetele arvudele („viimase 7 päeva koormus on 35% kõrgem kui 28-päeva keskmine, RPE 8 kaks päeva järjest — soovin täna kerget aeroobset 45 min").
- **Konkreetne modifikatsioon (valikuline):** kui algne plaan on liiga intensiivne, pakub mudel asendustreeningu.
- **Tausta kontekst:** ACWR-i joonis, pulsi- ja RPE-trendid, viimase 14 päeva kokkuvõte tabelina, et kasutaja saaks soovituse kriitiliselt hinnata.

### Edu kriteerium

Projekt õnnestub, kui on täidetud nii kvantitatiivne kui kvalitatiivne kriteerium:

- **Kvantitatiivne:** vähemalt 70%-l testperioodi (~14 päeva) päevadel langeb mudeli soovituse kategooria kokku mu treeneri (Ardi Vann) otsusega, kui talle näidatakse samu sisendeid ilma mudeli vastuse nägemata.
- **Kvalitatiivne:** ma ise kasutan tööriista projekti lõpus (01.06 seisuga) vähemalt kaks nädalat järjest iga päev ning kaks treeningkaaslast kinnitavad struktureeritud intervjuus, et kasutaksid seda edaspidi.

**Hindajate pädevus ja sõltumatus:**

- Kvantitatiivse osa hindaja on mu isiklik treener (Ardi Vann, kehtiv III taseme treenerikutse, teinud minuga koostööd ~2 a). Ta on pädev, sest tunneb nii konteksti kui ka üldiseid kesk-/pikamaajooksu koormusprintsiipe.
- Kvalitatiivse osa hindajad on kaks treeningkaaslast, samalaadse tausta ja tasemega; nad ei osale arendusprotsessis ning saavad tööriista näha alles valideerimisfaasis.

## 2. Tehniline arhitektuur ja töövoog

### Töövoog (samm-sammult)

1. Kasutaja avab Streamlit-rakenduse ja sisestab tänase kavandatud treeningu + eelmise treeningu RPE + lühimärkused.
2. Backend pärib Strava/Garmin API-st viimase 60 päeva treeningud (rakendus hoiab kohalikku SQLite-vahemälu, et API-d mitte üle koormata).
3. Andmetöötluse moodul (pandas) arvutab: akuutne koormus (7 päeva), krooniline koormus (28 päeva), ACWR, TRIMP per treening, monotoonsus (nädala koormuse standardhälve), pulsireservi trend viimase 14 päeva üle.
4. Konteksti komplekteerija koostab LLM-le struktureeritud prompti: sportlase profiil + 14 päeva kokkuvõte tabelina + arvutatud näitajad + subjektiivsed sisendid + tänane plaan + selge ülesande kirjeldus.
5. LLM (Claude Sonnet 4.6 või OpenAI GPT-4o) tagastab struktureeritud JSON-i: `{kategooria, põhjendus, modifikatsioon, confidence_low_if: [...] }`.
6. UI kuvab soovituse, põhjenduse ja tausta graafikud (Plotly) — kasutaja saab soovitust kritiseerida ja teha teadliku otsuse.

### Kasutatavad AI tööriistad

- **Põhiline — suur keelemudel (LLM):** eelistus Anthropic Claude Sonnet 4.6 (stabiilne struktureeritud JSON-väljund, tugev pikkade kontekstidega). Varuvariant: OpenAI GPT-4o. Kasutame valmis API-d, mudelit ise ei treeni.
- **Teisejärguline (kui aeg lubab):** kerge reeglipõhine / statistiline moodul (scikit-learn lineaarne regressioon) ACWR-i ajalise trendi prognoosiks; töötab LLM-i kõrval otsuste „turvafiltrina".

Juhendajate tagasiside („kaalu üldisemat/võimsamat AI mudelit") on otse sisse arvestatud — keelemudel on põhikomponent, mitte lisandus.

### Muud tööriistad ja platvormid

- Python 3.11+ (pandas, numpy) — andmetöötlus.
- Streamlit — veebirakenduse raam (kiire UI prototüüpimine).
- stravalib teek (või Strava REST API otsekasutus) — treeningandmete import.
- garminconnect Python-teek (mitteametlik, kuid hooldatav) — Garmini andmed.
- Plotly / matplotlib — koormuse visualisatsioonid.
- SQLite — lokaalne andmete vahemälu (import-tokeni ja API-päringu koormust vähendav).
- Anthropic SDK / OpenAI SDK — LLM-päringud.
- Git + GitHub — versioonihaldus.
- Docker — võimalik later-packaging; MVP-s mitte vajalik.

### Muud andmed

- **API andmed:** Strava (OAuth 2.0) ja Garmin Connect kasutaja enda ajalugu. MVP-s pärin ~60 päeva tagant; valideerimiseks pärin kuni 3 aastat.
- **Staatilised teaduslikud ressursid:** ACWR, TRIMP ja monotoonsuse valemid tulevad avaldatud spordimeditsiini allikatest (Gabbett, Banister); lisan need prompti viidetega, et LLM kasutaks konsensuslikke mõisteid.
- **Kasutaja profiil:** ühekordne konfiguratsioon (vanus, sugu, treeningstaaž, tipptulemused), salvestatud lokaalsesse JSON-faili.
- **Mida EI saadeta LLM-ile:** Üksikud GPS-punktid ega toored pulsi-aegread — ainult agregeeritud näitajad ja trendid, et vähendada privaatsusriski ja konteksti suurust.

## 3. MVP (Minimal Viable Product) — 11.05 seminaris esitletav versioon

### MVP põhifunktsionaalsus

1. Strava API autentimine (OAuth) ja viimase 60 päeva treeningandmete import ühele kasutajale (minule).
2. Põhiliste koormusnäitajate arvutus: ACWR (7/28), TRIMP, monotoonsus — testitud unit-testidega.
3. Üks LLM-päring tänase treeningu kohta: struktureeritud prompt + Claude API + JSON-parsimine.
4. Minimaalne Streamlit-UI ühe vaatega („Sisesta tänane plaan → Vaata soovitust ja põhjendust + ACWR-graafik").
5. Retrospektiivne test 10 varasemal päeval minu ajaloolises andmehulgas — kuvan kõrvuti oma tegeliku otsuse ja mudeli soovituse.

MVP eesmärk on tõestada otsast-otsa toimiv pipeline — andmed tulevad sisse, näitajad arvutatakse, LLM annab loetava ja loogilise soovituse. MVP-s peab olema võimalik demonstreerida mõtestatud soovitust vähemalt 5 erinevat tüüpi päeva kohta (kerge, raske, puhkus, haigus-järgne, vormis).

### Mis jääb MVP-st välja (tuleb lõppversioonis)

- Garmin Connect integratsioon (MVP-s ainult Strava).
- Visuaalne UI-poleering — graafikud MVP-s minimaalsed, põhirõhk loetavusel.
- Kasutaja profiili struktureeritud sisestus UI-s (MVP-s kõvakoodeeritud minu profiil).
- Subjektiivsete andmete (RPE, uni, märkmed) struktureeritud sisestus UI-s — MVP-s käsitsi YAML/JSON-failiga.
- Mitme kasutaja tugi, autentimine, avalik deploy.
- Scikit-learn statistiline moodul (võib-olla üldse, kui LLM üksi on piisav).
- Promptide süstemaatiline A/B-testimine — lõppversioonis võrdlen 2–3 prompti varianti.

## 4. Valideerimise ja testimise plaan

### Kuidas mõõdan edukust

1. **Retrospektiivne test (kvantitatiivne).** Valin varasematest ~3 aasta andmetest 30 päeva, mille konteksti ma tean (kaasa arvatud 5–7 teadaolevalt „kriitilist" päeva — ülekoormus, haigusele eelnev, vormitipp). Jooksutan mudeli neile päevadele, varjates tulemused. Mõõdik: protsent „oleks andnud sobiva soovituse" / „lähedal" / „oleks olnud vale". Eesmärk: ≥70% sobivaid.
2. **Treeneri kõrvutus (kvantitatiivne + kvalitatiivne).** 14 päeva (18.05 – 01.06) login iga päev mudeli soovituse ja paralleelselt näitan samad sisendid treener Ardi Vannile (tema vastab ilma mudeli väljundit nägemata). Mõõdik: kokkulangevuse protsent + struktureeritud kvalitatiivne analüüs, kus ja miks lähevad lahku (konservatiivsem? agressiivsem? ortogonaalne?).
3. **Isiklik igapäevane kasutus (kvalitatiivne).** 14 päeva järjest kasutan tööriista, login 1–5 skaalal iga päev: (a) soovituse kasulikkus, (b) põhjenduse veenvus, (c) kas järgisin ja mis juhtus järgmisel treeningul (subjektiivne enesetunne + objektiivne pulss/tempo).
4. **Struktureeritud intervjuu 2 treeningkaaslasega (kvalitatiivne).** Projekti lõpus ~30-minutiline intervjuu, kus näitan 5–7 reaalset päeva ja mudeli soovitusi. 6 pool-struktureeritud küsimust: usaldusväärsus, kasulikkus, põhjenduse kvaliteet, parimad/halvimad näited, kas ise kasutaksid, mis peaks teisiti olema.

### Valideerimise põhjalikkus — tugevused ja nõrkused

**Mida saan hinnata:** praktiline kasulikkus minu enda päriskontekstis; kooskõla kogenud treeneri otsustega; põhjenduste loogilisus kolme inimese silmis; ajalooline tabavus.

**Tugevused:** valideerimine toimub päris andmetel, päris kasutaja poolt, päris kontekstis (mitte sünteetilistel testjuhtudel); ühe kasutaja pikaajaline päevapõhine kasutus annab rikkalikku kvalitatiivset tagasisidet; retrospektiivne test katab ka haruldasemaid stsenaariume.

### Mis jääb valideerimata

- Statistiliselt usaldusväärne täpsus — valim on väike (n=1 põhikasutaja + 1 treener + 2 kaaslast).
- Pikaajaline mõju vigastusriskile ja võistlussooritusele — 10-nädalane projekti ajaraam on liiga lühike.
- Mudeli käitumine haruldastes stsenaariumides (haigusest taastumine, võistluseelne tippimine, suur treeningpaus) — need ei pruugi perioodi jooksul kõik tekkida.
- Generaliseeruvus teistele jooksjatele, treeneritele ja teistele spordialadele — MVP on häälestatud minu profiilile.

## 5. Riskide maandamine

### Tehnilised riskid

**Risk 1 — LLM soovituste kvaliteet ja konsistentsus.** Kõige ebakindlam komponent. LLM võib anda veenvaid, aga ebatäpseid soovitusi; sama sisend võib anda erinevaid vastuseid.

- **Plaan B1:** piiran kasutusjuhtumit kitsamaks — ainult aeroobsed jooksutreeningud, mitte jõutrenn või tehnilised drillid.
- **Plaan B2:** fikseerin temperature = 0, kasutan tugevamat mudelit (Claude Opus), lisan süsteem-prompti konkreetsed näidis-paarid (few-shot).
- **Plaan B3:** lisan reeglipõhised turvafiltrid: kui ACWR > 1.5 või RPE 8+ kaks päeva järjest, on automaatne soovitus „kerge päev" ja LLM ainult põhjendab seda. Nii katavad reeglid äärejuhud, LLM tegeleb nüanssidega.

**Risk 2 — Strava/Garmin API usaldusväärsus ja limiidid.** Strava piirab API-päringuid (~100/15 min, 1000/päev). Garmini Python-teek on mitteametlik ja võib enne projekti lõppu Garmini-poolsete muudatuste tõttu murduda.

- **Plaan B:** MVP-s ainult Strava. Lokaalne SQLite vahemälu tagab, et iga treening päritakse ainult üks kord. Kui Garmin murdub, on fallback Garmin Connect eksportfail (GPX/FIT) — loen need kohalikust kaustast eraldi parseriga.

**Risk 3 — LLM-API muutused.** Mudelipakkuja võib teenuseaegse „sonnet-latest" versiooni all välja vahetada, muutes väljundeid.

- **Plaan B:** fikseerin konkreetse mudeli versiooni (claude-sonnet-4-6, gpt-4o-2024-08-06), hoian prompti versioneerituna Git'is, logi-failides on alati kasutatud mudeli-string.

**Risk 4 — Ajakava.** Üksi töötades on prioriteedivalikud olulised; võib tekkida kiusatus poleerida UI-d valideerimise arvelt.

- **Plaan B:** valideerimise põhitöö (retrospektiivne test + igapäevane kasutus) algab juba 18.05, mitte 25.05. UI-poleering saab toimuda ainult valideerimise kõrval, mitte selle asemel.

### Juurutamise spetsiifika

- **Riistvara:** MVP jookseb täielikult minu sülearvuti peal (Streamlit + SQLite + Python). Tulevase avaliku kasutamise jaoks oleks vaja lihtsat hostinguid (Streamlit Cloud, Fly.io) ~€5–15/kuus.
- **Tarkvara:** Python 3.11, virtualenv, lukustatud `requirements.txt`. Strava refresh-token lokaalses `.env`-failis, mitte kunagi Git'i.
- **Andmete privaatsus:** Treeningandmed sisaldavad GPS-asukohti (kodu, töö), pulssi, und, stressi, haigusmärke ja vabateksti — neist võib tuletada tervise, taastumise, pohmaka või menstruaaltsükli kohta järeldusi. Seetõttu ei piisa ainult sellest, et “teine kasutaja ei näe”: pilverežiimis peab enne töötlemist olema nõusoleku vorm (`user_consents`) ja treenerile jagamine nõuab eraldi sportlase nõusolekut (`athlete_consent_at`). LLM-ile EI saadeta üksikuid GPS-punkte, toorpulsi ridu ega tokenit, ainult nõusolekuga agregeeritud näitajaid. Strava ja Garmin API tokenid tuleb hoida krüpteeritult.
- **Vastutuspiir:** Tööriist on otsustustugi, mitte asendaja treenerile või arstile. UI-s on selge kõrvaltekst, mis seda rõhutab. Soovitused ei puuduta tervislikke seisundeid (vigastused, haigused) sügavuses — sellistel puhkudel suunab tööriist sportlase pöörduma treeneri/arsti poole.
- **Kulud:** LLM-päring ~$0.01–0.05. 30 päeva testimist ≈ $1–3. Projekti eelarveliselt tühine.

## 6. Tegevusplaan

Üksinda töötades on kõik rollid minu kanda (projektijuht, arendaja, valideerija). Planeeritud tööaeg: ~60 h kokku, keskmiselt 8–10 h nädalas; MVP-nädal ja valideerimisnädalad intensiivsemad.

| Nädal | Seminar / tähtpäev | Peamine eesmärk | Maht |
|---|---|---|---|
| 13.04 – 20.04 | Ideede esitlus 20.04 | Idee kinnistamine, teostatavuse mõistmine | ~8 h |
| 20.04 – 27.04 | Projektiplaanide hindamine 27.04 | Projektiplaan + tehniline ettevalmistus | ~8 h |
| 27.04 – 04.05 | Konsultatsioon 1 (04.05) | Andmepipeline töökorras | ~10 h |
| 04.05 – 11.05 | MVP esitlus 11.05 | MVP valmis + seminari esitlus | ~12 h |
| 11.05 – 18.05 | Konsultatsioon 2 (18.05) | Prompti ja UI iteratsioon MVP tagasiside põhjal | ~8 h |
| 18.05 – 25.05 | Konsultatsioon 3 (25.05) | Valideerimine — põhitöö algab | ~8 h |
| 25.05 – 01.06 | Lõppesitlus 01.06 | Valideerimise lõpetamine, tulemuste analüüs | ~10 h |

Detailne tegevuste loetelu iga nädala kohta on originaaldokumendis (`projektiplaan_Uku.docx`).
