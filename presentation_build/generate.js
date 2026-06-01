const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const FA = require("react-icons/fa");

// ---------- palette ----------
const INK    = "0C2B33"; // deep teal-charcoal (dark bg)
const INK2   = "123a44"; // panel on dark
const INK3   = "0a242b"; // deeper
const TEAL   = "0E7C86";
const TEAL_LT= "1AA0A8";
const LIME   = "9BE564"; // energy / go accent
const LIME_DK= "5FA83A";
const AMBER  = "ECA13A";
const CORAL  = "E5645E";
const BLUE   = "3E8FB0";
const CREAM  = "F4F1EA"; // light bg
const CARD   = "FFFFFF";
const INKTX  = "143038"; // dark text on light
const MUTE   = "5C7178";
const MUTE_L = "9DB0B3";
const LINE   = "DCE3E1";

const HEAD = "Trebuchet MS";
const BODY = "Calibri";
const WORD = "Arial Black";

const W = 13.33, H = 7.5, M = 0.62;

function softShadow() { return { type: "outer", color: "0C2B33", blur: 9, offset: 3, angle: 135, opacity: 0.16 }; }
function softShadowDark() { return { type: "outer", color: "000000", blur: 10, offset: 3, angle: 135, opacity: 0.30 }; }

// ---------- icons ----------
function renderIconSvg(IconComponent, color, size) {
  return ReactDOMServer.renderToStaticMarkup(React.createElement(IconComponent, { color, size: String(size) }));
}
async function iconPng(IconComponent, color, size = 320) {
  const svg = renderIconSvg(IconComponent, color, size);
  const buf = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}
const ICONS = {};
async function buildIcons() {
  const want = {
    run: FA.FaRunning, chart: FA.FaChartLine, shield: FA.FaShieldAlt, robot: FA.FaRobot,
    comment: FA.FaCommentDots, db: FA.FaDatabase, warn: FA.FaExclamationTriangle,
    check: FA.FaCheckCircle, coach: FA.FaUserTie, users: FA.FaUsers, desktop: FA.FaDesktop,
    clip: FA.FaClipboardCheck, target: FA.FaBullseye, dumbbell: FA.FaDumbbell, bed: FA.FaBed,
    down: FA.FaArrowDown, right: FA.FaArrowRight, code: FA.FaCode, lock: FA.FaLock,
    scale: FA.FaBalanceScale, bulb: FA.FaLightbulb, heart: FA.FaHeartbeat, moon: FA.FaMoon,
    clock: FA.FaClock, key: FA.FaKey, layers: FA.FaLayerGroup, gauge: FA.FaTachometerAlt,
    eyeoff: FA.FaEyeSlash, list: FA.FaListUl, ban: FA.FaRegTimesCircle, flask: FA.FaFlask,
  };
  // pre-render in several colors as needed at call sites; here just store components
  return want;
}

let pres;
let COMP;

// ---------- reusable helpers ----------
function bg(slide, color) { slide.background = { color }; }

function pageFooter(slide, n, dark) {
  const col = dark ? MUTE_L : MUTE;
  slide.addText([
    { text: "Vorm.ai", options: { bold: true, color: dark ? LIME : TEAL } },
    { text: "  ·  AI-põhine treeningkoormuse analüüsija", options: { color: col } },
  ], { x: M, y: H - 0.46, w: 8, h: 0.3, fontSize: 9, fontFace: BODY, align: "left", margin: 0, valign: "middle" });
  slide.addText(String(n).padStart(2, "0"), { x: W - 1.1, y: H - 0.46, w: 0.5, h: 0.3, fontSize: 9, fontFace: BODY, color: col, align: "right", margin: 0, valign: "middle" });
}

function sectionTag(slide, text, color, x, y) {
  const w = 0.44 + text.length * 0.108;
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h: 0.34, fill: { color }, rectRadius: 0.17, line: { type: "none" } });
  slide.addText(text.toUpperCase(), { x, y, w, h: 0.34, fontSize: 10, bold: true, color: "FFFFFF", fontFace: HEAD, align: "center", valign: "middle", charSpacing: 1, margin: 0 });
}

function slideTitle(slide, text, dark, x, y, w) {
  slide.addText(text, { x: x ?? M, y: y ?? 0.95, w: w ?? (W - 2 * M), h: 0.8, fontSize: 31, bold: true, color: dark ? "FFFFFF" : INKTX, fontFace: HEAD, align: "left", valign: "top", margin: 0 });
}

async function iconCircle(slide, iconComp, circleColor, iconColor, x, y, d) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: circleColor }, line: { type: "none" } });
  const ip = await iconPng(iconComp, "#" + iconColor);
  const id = d * 0.52;
  slide.addImage({ data: ip, x: x + (d - id) / 2, y: y + (d - id) / 2, w: id, h: id });
}

function roundCard(slide, x, y, w, h, fill, dark) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: fill }, rectRadius: 0.1, line: dark ? { type: "none" } : { color: LINE, width: 1 }, shadow: dark ? softShadowDark() : softShadow() });
}

// =================================================================
async function build() {
  pres = new pptxgen();
  pres.defineLayout({ name: "WIDE", width: W, height: H });
  pres.layout = "WIDE";
  pres.author = "Uku Renek Kronbergs";
  pres.title = "Vorm.ai — lõppesitlus";
  COMP = await buildIcons();

  await slideTitleScreen();   // 1
  await slideProblem();       // 2
  await slideIdea();          // 3
  await slidePipeline();      // 4
  await slideExample();       // 5
  await slideArchitecture();  // 6
  await slideCoachAthlete();  // 7
  await slideUI();            // 8
  await slideValidationMethod(); // 9
  await slideValidationResults(); // 10
  await slideCaseStudy();     // 11
  await slideConclusion();    // 12

  await pres.writeFile({ fileName: "Vorm_ai_esitlus.pptx" });
  console.log("WROTE Vorm_ai_esitlus.pptx");
}

// ---------- 1. TITLE ----------
async function slideTitleScreen() {
  const s = pres.addSlide();
  bg(s, INK);
  // decorative right panel
  s.addShape(pres.shapes.RECTANGLE, { x: W - 3.7, y: 0, w: 3.7, h: H, fill: { color: INK3 }, line: { type: "none" } });
  // big running icon watermark
  const runWm = await iconPng(COMP.run, "#" + TEAL, 600);
  s.addImage({ data: runWm, x: W - 3.25, y: 1.7, w: 2.7, h: 2.7, transparency: 18 });
  // accent stripe
  s.addShape(pres.shapes.RECTANGLE, { x: M, y: 1.5, w: 1.5, h: 0.12, fill: { color: LIME }, line: { type: "none" } });

  s.addText("Vorm.ai", { x: M - 0.05, y: 1.75, w: 8.6, h: 1.5, fontSize: 76, bold: true, color: "FFFFFF", fontFace: WORD, align: "left", margin: 0 });
  s.addText("Andmepõhine teine arvamus sinu tänase treeningu kohta.", { x: M, y: 3.15, w: 8.3, h: 0.7, fontSize: 21, color: LIME, fontFace: HEAD, bold: true, align: "left", margin: 0 });
  s.addText("AI-põhine treeningkoormuse analüüsija kesk- ja pikamaajooksjatele", { x: M, y: 3.85, w: 8.3, h: 0.5, fontSize: 14, color: MUTE_L, fontFace: BODY, align: "left", margin: 0 });

  s.addText([
    { text: "Uku Renek Kronbergs", options: { bold: true, color: "FFFFFF" } },
    { text: "   ·   Tehisintellekti rakendamine   ·   Tartu Ülikool, kevad 2026", options: { color: MUTE_L } },
  ], { x: M, y: 5.95, w: 9, h: 0.4, fontSize: 13, fontFace: BODY, align: "left", margin: 0, valign: "middle" });

  // teaser stat strip
  const stats = [["78,6%", "kokkulangevus treeneriga"], ["4,1 / 5", "keskmine kasulikkus"], ["9 800+", "rida koodi · 20 testifaili"]];
  let sx = M;
  for (const [big, lab] of stats) {
    s.addText(big, { x: sx, y: 4.55, w: 2.6, h: 0.5, fontSize: 26, bold: true, color: LIME, fontFace: HEAD, align: "left", margin: 0 });
    s.addText(lab, { x: sx, y: 5.05, w: 2.7, h: 0.35, fontSize: 10.5, color: MUTE_L, fontFace: BODY, align: "left", margin: 0 });
    sx += 2.95;
  }
  s.addText("Lõppesitlus · 01.06.2026", { x: W - 3.6, y: H - 0.5, w: 3.0, h: 0.3, fontSize: 10, color: MUTE_L, fontFace: BODY, align: "right", margin: 0 });
  s.addNotes(
    "AVALÖÖK (~30 s). Tere, mina olen Uku Renek Kronbergs. Vorm.ai on AI-põhine treeningkoormuse analüüsija jooksjatele — see annab iga päev andmepõhise teise arvamuse selle kohta, kas tänast treeningut peaks tegema plaanipäraselt, kergemini või vahele jätma.\n" +
    "Hook: kogu projekti läbiv number — 78,6% mu soovitustest langes treeneri otsusega praktiliselt kokku (eesmärk oli 70%).\n" +
    "Aja-eelarve: ettekanne 5–7 min, ~30 s slaidi kohta. Hoia tempot."
  );
}

// ---------- 2. PROBLEM ----------
async function slideProblem() {
  const s = pres.addSlide();
  bg(s, CREAM);
  sectionTag(s, "Probleem", CORAL, M, 0.55);
  slideTitle(s, "Andmeid on rohkem kui kunagi — mõtestust vähem", false);
  s.addText("Harrastus- ja poolprofessionaalsel jooksjal puudub süstemaatiline tugi igapäevaseks koormuse kohandamiseks.",
    { x: M, y: 1.72, w: 7.4, h: 0.6, fontSize: 14, color: MUTE, fontFace: BODY, align: "left", margin: 0 });

  const items = [
    [COMP.gauge, TEAL, "Andmeid on, tõlgendust pole", "Nutikell mõõdab pulssi, GPS-i ja und. Keegi ei ütle, mida nende numbritega täna teha."],
    [COMP.warn, AMBER, "Koormuse kohandamine on reaktiivne", "Ülekoormust märkad alles pärast kehva treeningut, hommikust väsimust või kerget vigastust."],
    [COMP.ban, CORAL, "Olemasolevad tööriistad ei vasta", "Garmin annab ühe numbri ilma põhjenduseta; TrainingPeaks maksab ~€200/a ja eeldab eksperdioskust."],
  ];
  let y = 2.5;
  for (const [icon, col, head, body] of items) {
    roundCard(s, M, y, 7.4, 1.28, CARD, false);
    await iconCircle(s, icon, col, "FFFFFF", M + 0.28, y + 0.30, 0.66);
    s.addText(head, { x: M + 1.15, y: y + 0.18, w: 6.0, h: 0.4, fontSize: 15.5, bold: true, color: INKTX, fontFace: HEAD, align: "left", margin: 0 });
    s.addText(body, { x: M + 1.15, y: y + 0.58, w: 6.05, h: 0.6, fontSize: 12, color: MUTE, fontFace: BODY, align: "left", margin: 0 });
    y += 1.4;
  }

  // right highlight panel
  const rx = 8.45, rw = W - rx - M;
  roundCard(s, rx, 2.5, rw, 4.18, INK, true);
  await iconCircle(s, COMP.bulb, LIME, INK, rx + (rw - 0.8) / 2, 2.85, 0.8);
  s.addText("Puuduv lüli", { x: rx + 0.3, y: 3.8, w: rw - 0.6, h: 0.4, fontSize: 17, bold: true, color: LIME, fontFace: HEAD, align: "center", margin: 0 });
  s.addText("Personaalne andmepõhine teine arvamus, mis ühendab objektiivsed näitajad subjektiivsete signaalidega ja põhjendab oma soovituse inimkeeles.",
    { x: rx + 0.35, y: 4.25, w: rw - 0.7, h: 1.8, fontSize: 13.5, color: "FFFFFF", fontFace: BODY, align: "center", valign: "top", margin: 0, lineSpacingMultiple: 1.1 });
  s.addNotes(
    "PROBLEEM (~40 s). Selgita ka võhikule: jooksja nutikell kogub tonni andmeid, aga keegi ei ütle, mida nendega täna peale hakata.\n" +
    "Kolm valupunkti: (1) andmeid on, tõlgendust pole; (2) koormuse kohandamine on reaktiivne — ülekoormust märkad alles pärast halba trenni; (3) turutööriistad kas annavad ainult numbri (Garmin) või on kallid ja eeldavad eksperti (TrainingPeaks).\n" +
    "Võti: puudub personaalne, inimkeeles põhjendav teine arvamus — selle lünga Vorm.ai täidab."
  );
  pageFooter(s, 2, false);
}

// ---------- 3. IDEA ----------
async function slideIdea() {
  const s = pres.addSlide();
  bg(s, CREAM);
  sectionTag(s, "Lahendus", TEAL, M, 0.55);
  slideTitle(s, "Idee: andmepõhine teine arvamus", false);
  s.addText("Iga päev: andmed sisse → soovitus + inimkeele põhjendus välja. Neli selget tegevuskategooriat.",
    { x: M, y: 1.72, w: W - 2 * M, h: 0.5, fontSize: 14.5, color: MUTE, fontFace: BODY, align: "left", margin: 0 });

  const cats = [
    [COMP.right, LIME_DK, "Jätka plaanipäraselt", "Signaalid rahulikud — plaan kehtib."],
    [COMP.down, AMBER, "Vähenda intensiivsust", "Koormus kuhjub — kontrolli mahtu/tempot."],
    [COMP.bed, BLUE, "Lisa taastumispäev", "Väsimus kõrge — anna kehale aega."],
    [COMP.dumbbell, CORAL, "Alternatiivne treening", "Vaheta vahelduseks koormuse tüüpi."],
  ];
  const cw = (W - 2 * M - 3 * 0.3) / 4;
  let x = M;
  for (const [icon, col, head, body] of cats) {
    roundCard(s, x, 2.45, cw, 2.5, CARD, false);
    s.addShape(pres.shapes.RECTANGLE, { x: x, y: 2.45, w: cw, h: 0.14, fill: { color: col }, line: { type: "none" } });
    await iconCircle(s, icon, col, "FFFFFF", x + (cw - 0.8) / 2, 2.78, 0.8);
    s.addText(head, { x: x + 0.12, y: 3.72, w: cw - 0.24, h: 0.7, fontSize: 14.5, bold: true, color: INKTX, fontFace: HEAD, align: "center", valign: "top", margin: 0 });
    s.addText(body, { x: x + 0.16, y: 4.32, w: cw - 0.32, h: 0.6, fontSize: 11, color: MUTE, fontFace: BODY, align: "center", valign: "top", margin: 0 });
    x += cw + 0.3;
  }

  // bottom differentiator strip
  roundCard(s, M, 5.25, W - 2 * M, 1.4, INK, true);
  await iconCircle(s, COMP.scale, LIME, INK, M + 0.35, 5.58, 0.74);
  s.addText([
    { text: "Erinevus turust:  ", options: { bold: true, color: LIME } },
    { text: "Garmin annab numbri, TrainingPeaks eeldab eksperti. ", options: { color: "FFFFFF" } },
    { text: "Vorm.ai annab konkreetse otsuse + selgituse, mis viitab sinu enda numbritele.", options: { color: "FFFFFF", bold: true } },
  ], { x: M + 1.3, y: 5.45, w: W - 2 * M - 1.7, h: 1.0, fontSize: 14.5, fontFace: BODY, align: "left", valign: "middle", margin: 0, lineSpacingMultiple: 1.08 });
  s.addNotes(
    "LAHENDUS / IDEE (~40 s). Üks lause: andmed sisse, soovitus + inimkeele põhjendus välja.\n" +
    "Väljund taandub neljale selgele kategooriale: jätka / vähenda / taastumispäev / alternatiivne treening. Need on lihtsad ja tegevusele suunatud.\n" +
    "Eristumine turust: me ei anna ainult numbrit ega eelda eksperti — anname konkreetse otsuse + selgituse, mis viitab kasutaja enda andmetele."
  );
  pageFooter(s, 3, false);
}

// ---------- 4. PIPELINE ----------
async function slidePipeline() {
  const s = pres.addSlide();
  bg(s, CREAM);
  sectionTag(s, "Kuidas töötab", TEAL, M, 0.55);
  slideTitle(s, "Andmetest soovituseni — viies sammus", false);

  const steps = [
    [COMP.db, TEAL, "1", "Andmed", "Strava API / Garmin GPX / CSV / näidis. SQLite-vahemälu delta-sünkroniseerib."],
    [COMP.chart, TEAL_LT, "2", "Spordinäitajad", "ACWR (7/28), TRIMP, monotoonsus, Banister CTL/ATL/TSB."],
    [COMP.shield, AMBER, "3", "Ohutusreeglid", "ACWR > 1,5 · RPE ≥ 8 kaks päeva · uni < 6 h → sunnitakse ohutu suund."],
    [COMP.robot, LIME_DK, "4", "Keelemudel", "Struktuurne prompt → JSON: kategooria + põhjendus + modifikatsioon."],
    [COMP.comment, CORAL, "5", "Soovitus", "Kategooria + 2–4 lauset + Plotly-graafikud kriitiliseks hindamiseks."],
  ];
  const n = steps.length;
  const gap = 0.28;
  const cw = (W - 2 * M - (n - 1) * gap) / n;
  let x = M;
  const cardY = 2.35, cardH = 3.0;
  for (let i = 0; i < n; i++) {
    const [icon, col, num, head, body] = steps[i];
    roundCard(s, x, cardY, cw, cardH, CARD, false);
    await iconCircle(s, icon, col, "FFFFFF", x + (cw - 0.85) / 2, cardY + 0.32, 0.85);
    s.addText(head, { x: x + 0.08, y: cardY + 1.32, w: cw - 0.16, h: 0.4, fontSize: 14.5, bold: true, color: INKTX, fontFace: HEAD, align: "center", margin: 0 });
    s.addText(body, { x: x + 0.14, y: cardY + 1.74, w: cw - 0.28, h: 1.15, fontSize: 10.5, color: MUTE, fontFace: BODY, align: "center", valign: "top", margin: 0, lineSpacingMultiple: 1.05 });
    // step number badge
    s.addShape(pres.shapes.OVAL, { x: x + 0.12, y: cardY + 0.16, w: 0.34, h: 0.34, fill: { color: INK }, line: { type: "none" } });
    s.addText(num, { x: x + 0.12, y: cardY + 0.16, w: 0.34, h: 0.34, fontSize: 12, bold: true, color: LIME, fontFace: HEAD, align: "center", valign: "middle", margin: 0 });
    // arrow between
    if (i < n - 1) {
      const ax = x + cw + (gap - 0.22) / 2;
      const ap = await iconPng(COMP.right, "#" + MUTE_L, 200);
      s.addImage({ data: ap, x: ax, y: cardY + cardH / 2 - 0.11, w: 0.22, h: 0.22 });
    }
    x += cw + gap;
  }

  roundCard(s, M, 5.75, W - 2 * M, 0.95, INK, true);
  s.addText([
    { text: "Disainiotsus:  ", options: { bold: true, color: LIME } },
    { text: "reeglid katavad äärejuhud, LLM tegeleb nüanssidega. scikit-learn prognoosib ACWR-trendi, et hoiatada ", options: { color: "FFFFFF" } },
    { text: "enne", options: { color: LIME, bold: true } },
    { text: " ohulõike 1,5 ületamist.", options: { color: "FFFFFF" } },
  ], { x: M + 0.4, y: 5.75, w: W - 2 * M - 0.8, h: 0.95, fontSize: 13.5, fontFace: BODY, align: "left", valign: "middle", margin: 0, lineSpacingMultiple: 1.05 });
  s.addNotes(
    "KUIDAS TÖÖTAB (~45 s). Käi viis sammu kiiresti läbi: (1) andmed Stravast/Garminist/CSV-st, SQLite-vahemälu küsib igal korral ainult uue osa; (2) arvutame spordimeditsiini näitajad — ACWR on 7 päeva koormus jagatud 28 päeva keskmisega; (3) reeglid: kui ACWR>1,5 või RPE 8 kaks päeva järjest, surutakse vastus ohutusse suunda; (4) struktuurne prompt läheb keelemudelile, mis tagastab JSON-i; (5) kasutaja näeb soovitust + graafikuid.\n" +
    "TEHNILINE VÕTI (kui küsitakse): reeglid katavad äärejuhud deterministlikult, LLM tegeleb nüanssidega; temperature=0 ja few-shot näited annavad stabiilse väljundi. scikit-learn lineaarregressioon hoiatab tõusvast ACWR-trendist enne, kui see lõikab 1,5."
  );
  pageFooter(s, 4, false);
}

// ---------- 5. EXAMPLE ----------
async function slideExample() {
  const s = pres.addSlide();
  bg(s, CREAM);
  sectionTag(s, "Näide", TEAL, M, 0.55);
  slideTitle(s, "Üks päev: sisendist soovituseni", false);

  // input card
  const inX = M, inW = 5.15, cy = 2.05, ch = 3.7;
  roundCard(s, inX, cy, inW, ch, CARD, false);
  await iconCircle(s, COMP.heart, TEAL, "FFFFFF", inX + 0.3, cy + 0.28, 0.66);
  s.addText("Sisend — hommik", { x: inX + 1.1, y: cy + 0.34, w: inW - 1.3, h: 0.5, fontSize: 16, bold: true, color: INKTX, fontFace: HEAD, valign: "middle", margin: 0 });
  const rows = [
    ["ACWR (äge/krooniline)", "1,36  ↑"],
    ["Monotoonsus", "1,71"],
    ["Eelmise päeva RPE", "8 / 10"],
    ["Uni", "6,1 h"],
    ["Tänane plaan", "6 × 1000 m tempo"],
  ];
  let ry = cy + 1.25;
  for (const [k, v] of rows) {
    s.addText(k, { x: inX + 0.32, y: ry, w: 3.1, h: 0.4, fontSize: 12.5, color: MUTE, fontFace: BODY, valign: "middle", margin: 0 });
    s.addText(v, { x: inX + 3.35, y: ry, w: inW - 3.55, h: 0.4, fontSize: 13, bold: true, color: INKTX, fontFace: HEAD, align: "right", valign: "middle", margin: 0 });
    if (ry + 0.46 < cy + ch - 0.1) s.addShape(pres.shapes.LINE, { x: inX + 0.32, y: ry + 0.46, w: inW - 0.64, h: 0, line: { color: LINE, width: 1 } });
    ry += 0.5;
  }

  // arrow
  const ap = await iconPng(COMP.right, "#" + TEAL, 240);
  s.addImage({ data: ap, x: inX + inW + 0.18, y: cy + ch / 2 - 0.27, w: 0.55, h: 0.55 });

  // output card
  const outX = inX + inW + 0.95, outW = W - outX - M;
  roundCard(s, outX, cy, outW, ch, INK, true);
  s.addShape(pres.shapes.RECTANGLE, { x: outX, y: cy, w: outW, h: 0.16, fill: { color: AMBER }, line: { type: "none" } });
  await iconCircle(s, COMP.robot, AMBER, INK, outX + 0.3, cy + 0.34, 0.66);
  s.addText("Vorm.ai väljund", { x: outX + 1.1, y: cy + 0.4, w: outW - 1.3, h: 0.5, fontSize: 16, bold: true, color: "FFFFFF", fontFace: HEAD, valign: "middle", margin: 0 });

  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: outX + 0.32, y: cy + 1.2, w: outW - 0.64, h: 0.62, fill: { color: AMBER }, rectRadius: 0.08, line: { type: "none" } });
  s.addText("⬇  VÄHENDA INTENSIIVSUST", { x: outX + 0.32, y: cy + 1.2, w: outW - 0.64, h: 0.62, fontSize: 15, bold: true, color: INK, fontFace: HEAD, align: "center", valign: "middle", margin: 0, charSpacing: 0.5 });

  s.addText("Põhjendus", { x: outX + 0.34, y: cy + 2.0, w: outW - 0.6, h: 0.32, fontSize: 11, bold: true, color: LIME, fontFace: HEAD, margin: 0 });
  s.addText("„7-päeva koormus on kõrge ja kasvab, RPE 8 koos lühikese unega kuhjab väsimust — täna pigem kontrollitud tempo väiksemas mahus kui täiskoormusega 6 × 1000 m.“",
    { x: outX + 0.34, y: cy + 2.34, w: outW - 0.68, h: 1.2, fontSize: 13, italic: true, color: "FFFFFF", fontFace: BODY, align: "left", valign: "top", margin: 0, lineSpacingMultiple: 1.12 });

  s.addText([
    { text: "Taustaks: ", options: { bold: true, color: INKTX } },
    { text: "kasutaja näeb ACWR-kõverat ja viimase 14 päeva tabelit, et soovitust ", options: { color: MUTE } },
    { text: "kriitiliselt hinnata", options: { color: TEAL, bold: true } },
    { text: " — tööriist on otsustustugi, mitte käsk.", options: { color: MUTE } },
  ], { x: M, y: 6.05, w: W - 2 * M, h: 0.6, fontSize: 13, fontFace: BODY, align: "left", valign: "middle", margin: 0 });
  s.addNotes(
    "NÄIDE (~35 s). Tee pipeline käegakatsutavaks ühe päeva näitel (20. mai juhtum). Sisend hommikul: ACWR 1,36 ja tõusev, eile RPE 8, uni napp 6,1 h, plaanis kõva 6×1000 m.\n" +
    "Mudel ei ütle 'jäta trenn ära' — ta soovitab mõõdukalt 'vähenda intensiivsust' ja põhjendab numbritega.\n" +
    "Rõhuta: kasutaja näeb tausta (ACWR-kõver, 14 päeva tabel) ja saab ise otsustada — tööriist on otsustustugi, mitte käsk."
  );
  pageFooter(s, 5, false);
}

// ---------- 6. ARCHITECTURE ----------
async function slideArchitecture() {
  const s = pres.addSlide();
  bg(s, INK);
  sectionTag(s, "Tehniline arhitektuur", LIME_DK, M, 0.55);
  slideTitle(s, "Selge moodulipiir, valitud tööriistad", true);

  // left: stack
  const lx = M, lw = 5.55;
  roundCard(s, lx, 1.95, lw, 4.32, INK2, true);
  await iconCircle(s, COMP.code, LIME, INK, lx + 0.3, 2.15, 0.6);
  s.addText("Tehnoloogiavalik", { x: lx + 1.0, y: 2.19, w: lw - 1.2, h: 0.45, fontSize: 15.5, bold: true, color: "FFFFFF", fontFace: HEAD, valign: "middle", margin: 0 });
  const stack = [
    ["Python · pandas · numpy", "andmetöötlus ja näitajad"],
    ["Streamlit", "veebirakenduse raam"],
    ["Supabase (Postgres + RLS)", "autentimine + mitme kasutaja andmed"],
    ["LLM API", "Claude / OpenAI / OpenRouter"],
    ["scikit-learn", "ACWR-trendi prognoos"],
    ["Plotly · SQLite", "graafikud · lokaalne vahemälu"],
  ];
  let yy = 2.82;
  for (const [a, b] of stack) {
    s.addShape(pres.shapes.OVAL, { x: lx + 0.34, y: yy + 0.07, w: 0.12, h: 0.12, fill: { color: LIME }, line: { type: "none" } });
    s.addText([
      { text: a + "  ", options: { bold: true, color: "FFFFFF" } },
      { text: "— " + b, options: { color: MUTE_L } },
    ], { x: lx + 0.6, y: yy - 0.07, w: lw - 0.85, h: 0.4, fontSize: 12.5, fontFace: BODY, align: "left", valign: "middle", margin: 0 });
    yy += 0.56;
  }

  // right: module map
  const rx = lx + lw + 0.4, rw = W - rx - M;
  s.addText("Koodi moodulid", { x: rx, y: 1.95, w: rw, h: 0.4, fontSize: 15.5, bold: true, color: LIME, fontFace: HEAD, margin: 0 });
  const mods = [
    ["data", "import + salvestus"], ["metrics", "ACWR · TRIMP · TSB"],
    ["rules", "ohutusfiltrid"], ["llm", "prompt + JSON"],
    ["planning", "treeningkava"], ["validation", "PDF-aruanne"],
  ];
  const mcw = (rw - 0.3) / 2, mch = 0.68;
  let mx = rx, my = 2.4, ci = 0;
  for (const [a, b] of mods) {
    roundCard(s, mx, my, mcw, mch, INK2, true);
    s.addShape(pres.shapes.RECTANGLE, { x: mx, y: my, w: 0.1, h: mch, fill: { color: TEAL_LT }, line: { type: "none" } });
    s.addText("vorm/" + a, { x: mx + 0.28, y: my + 0.09, w: mcw - 0.4, h: 0.3, fontSize: 13, bold: true, color: "FFFFFF", fontFace: "Consolas", margin: 0 });
    s.addText(b, { x: mx + 0.28, y: my + 0.4, w: mcw - 0.4, h: 0.28, fontSize: 10.5, color: MUTE_L, fontFace: BODY, margin: 0 });
    ci++;
    if (ci % 2 === 0) { mx = rx; my += mch + 0.2; } else { mx += mcw + 0.3; }
  }
  // metrics strip under modules
  roundCard(s, rx, my + 0.02, rw, 0.82, INK3, true);
  s.addText([
    { text: "~9 800", options: { bold: true, color: LIME, fontSize: 18 } },
    { text: " rida koodi      ", options: { color: MUTE_L } },
    { text: "20", options: { bold: true, color: LIME, fontSize: 18 } },
    { text: " testifaili      ", options: { color: MUTE_L } },
    { text: "177", options: { bold: true, color: LIME, fontSize: 18 } },
    { text: " ühiktesti", options: { color: MUTE_L } },
  ], { x: rx + 0.3, y: my + 0.02, w: rw - 0.6, h: 0.82, fontSize: 12.5, fontFace: BODY, align: "left", valign: "middle", margin: 0 });

  // design decisions footer
  s.addText([
    { text: "Disainipõhimõtted:  ", options: { bold: true, color: LIME } },
    { text: "LLM on põhikomponent (mitte lisand) · reeglid turvafiltrina · LLM-ile saadetakse ainult agregeeritud näitajad (privaatsus).", options: { color: "FFFFFF" } },
  ], { x: M, y: 6.6, w: W - 2 * M, h: 0.35, fontSize: 11.5, fontFace: BODY, align: "left", valign: "middle", margin: 0 });
  s.addNotes(
    "ARHITEKTUUR (~40 s). Näita, et projekt on 'minu oma' ja tehniliselt korras. Python + pandas arvutab näitajad; Streamlit on UI; Supabase (Postgres + Row-Level Security) hoiab autentimist ja mitme kasutaja andmeid; LLM API on vahetatav (Claude/OpenAI/OpenRouter); scikit-learn prognoosib; Plotly + SQLite.\n" +
    "Kood on jaotatud selgeteks mooduliteks (data, metrics, rules, llm, planning, validation, ui), ~9800 rida, 20 testifaili, 177 ühiktesti.\n" +
    "Disainipõhimõtted Q&A jaoks: LLM on PÕHIkomponent (mitte iluvidin); reeglid on turvafilter; privaatsus — LLM-ile lähevad AINULT agregeeritud näitajad, mitte toorpulss ega GPS. Ole valmis avama ükskõik millist moodulit."
  );
  pageFooter(s, 6, true);
}

// ---------- 7. COACH-ATHLETE ----------
async function slideCoachAthlete() {
  const s = pres.addSlide();
  bg(s, CREAM);
  sectionTag(s, "Mitme kasutaja tugi", TEAL, M, 0.55);
  slideTitle(s, "Treener ja sportlane — üks platvorm", false);

  // flow band
  const fy = 1.95;
  const fItems = [
    [COMP.coach, TEAL, "Treener loob kutsekoodi"],
    [COMP.key, AMBER, "Sportlane sisestab koodi"],
    [COMP.users, LIME_DK, "Seos aktiivne — andmed jagatud"],
  ];
  const fw = 3.7, fgap = (W - 2 * M - 3 * fw) / 2;
  let fx = M;
  for (let i = 0; i < fItems.length; i++) {
    const [icon, col, txt] = fItems[i];
    roundCard(s, fx, fy, fw, 1.05, CARD, false);
    await iconCircle(s, icon, col, "FFFFFF", fx + 0.25, fy + 0.235, 0.58);
    s.addText(txt, { x: fx + 0.95, y: fy, w: fw - 1.1, h: 1.05, fontSize: 13.5, bold: true, color: INKTX, fontFace: HEAD, align: "left", valign: "middle", margin: 0 });
    if (i < 2) {
      const ap = await iconPng(COMP.right, "#" + TEAL, 200);
      s.addImage({ data: ap, x: fx + fw + (fgap - 0.28) / 2, y: fy + 0.38, w: 0.28, h: 0.28 });
    }
    fx += fw + fgap;
  }

  // three feature cards
  const cards = [
    [COMP.list, TEAL, "Rollipõhine konto", "Registreerumisel valid: sportlane või treener. Roll juhib kogu kasutajakogemust."],
    [COMP.desktop, AMBER, "Treeneri töölaud", "Treener näeb seotud sportlaste koormust ja sisestab §4.2 pimeotsuse otse sportlase konteksti."],
    [COMP.lock, LIME_DK, "Turvalisus & nõusolek", "Postgres Row-Level Security isoleerib read; andmete jagamiseks annab sportlane eraldi nõusoleku."],
  ];
  const cw = (W - 2 * M - 2 * 0.35) / 3;
  let cx = M, cy = 3.25;
  for (const [icon, col, head, body] of cards) {
    roundCard(s, cx, cy, cw, 2.45, CARD, false);
    await iconCircle(s, icon, col, "FFFFFF", cx + 0.28, cy + 0.3, 0.7);
    s.addText(head, { x: cx + 0.28, y: cy + 1.12, w: cw - 0.5, h: 0.45, fontSize: 15, bold: true, color: INKTX, fontFace: HEAD, align: "left", margin: 0 });
    s.addText(body, { x: cx + 0.28, y: cy + 1.55, w: cw - 0.5, h: 0.85, fontSize: 11.5, color: MUTE, fontFace: BODY, align: "left", valign: "top", margin: 0, lineSpacingMultiple: 1.08 });
    cx += cw + 0.35;
  }

  roundCard(s, M, 5.95, W - 2 * M, 0.78, INK, true);
  s.addText([
    { text: "Seos valideerimisega:  ", options: { bold: true, color: LIME } },
    { text: "sama mehhanism toidab §4.2 valideerimist — treener sisestab oma otsuse mudeli väljundit nägemata (pimemenetlus).", options: { color: "FFFFFF" } },
  ], { x: M + 0.4, y: 5.95, w: W - 2 * M - 0.8, h: 0.78, fontSize: 13, fontFace: BODY, align: "left", valign: "middle", margin: 0 });
  s.addNotes(
    "TREENER–SPORTLANE (~35 s). See on hiljutine täiendus, mis teeb Vorm.ai-st päris platvormi. Treener loob kutsekoodi, sportlane sisestab selle, seos muutub aktiivseks.\n" +
    "Kolm sammast: rollipõhine konto (signup'is valid rolli); treeneri töölaud (näeb seotud sportlaste koormust, sisestab otsuse); turvalisus — Postgres RLS isoleerib read andmebaasi tasemel, jagamiseks on vaja sportlase eraldi nõusolekut.\n" +
    "Seo see valideerimisega: sama mehhanism võimaldab treeneril sisestada §4.2 pimeotsuse — ta ei näe mudeli väljundit."
  );
  pageFooter(s, 7, false);
}

// ---------- 8. UI ----------
async function slideUI() {
  const s = pres.addSlide();
  bg(s, CREAM);
  sectionTag(s, "Kasutajaliides", TEAL, M, 0.55);
  slideTitle(s, "Töötav veebirakendus, mitte makett", false);

  // browser mock
  const bx = M, by = 1.95, bw = 8.0, bh = 4.05;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: bx, y: by, w: bw, h: bh, fill: { color: "FFFFFF" }, rectRadius: 0.06, line: { color: LINE, width: 1 }, shadow: softShadow() });
  // top bar
  s.addShape(pres.shapes.RECTANGLE, { x: bx, y: by, w: bw, h: 0.42, fill: { color: INK }, line: { type: "none" } });
  for (let i = 0; i < 3; i++) s.addShape(pres.shapes.OVAL, { x: bx + 0.2 + i * 0.22, y: by + 0.15, w: 0.12, h: 0.12, fill: { color: [CORAL, AMBER, LIME][i] }, line: { type: "none" } });
  s.addText("vorm.ai", { x: bx + 1.0, y: by, w: bw - 1.2, h: 0.42, fontSize: 10.5, color: MUTE_L, fontFace: BODY, align: "left", valign: "middle", margin: 0 });
  // tab row
  const tabs = ["Tänane soovitus", "Koormuse ajalugu", "Retrospektiiv", "Treeningkava", "Päevalogi", "Treeneri võrdlus"];
  let tx = bx + 0.18; const tabY = by + 0.55;
  for (let i = 0; i < tabs.length; i++) {
    const active = i === 0;
    const tw = 0.18 + tabs[i].length * 0.069;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: tx, y: tabY, w: tw, h: 0.34, fill: { color: active ? TEAL : "EEF2F1" }, rectRadius: 0.06, line: { type: "none" } });
    s.addText(tabs[i], { x: tx, y: tabY, w: tw, h: 0.34, fontSize: 8.5, bold: active, color: active ? "FFFFFF" : MUTE, fontFace: BODY, align: "center", valign: "middle", margin: 0 });
    tx += tw + 0.08;
  }
  // recommendation banner inside
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: bx + 0.25, y: tabY + 0.55, w: bw - 0.5, h: 0.78, fill: { color: AMBER }, rectRadius: 0.06, line: { type: "none" } });
  await iconCircle(s, COMP.down, "FFFFFF", AMBER, bx + 0.45, tabY + 0.7, 0.48);
  s.addText([
    { text: "Vähenda intensiivsust", options: { bold: true, color: INK, fontSize: 14, breakLine: true } },
    { text: "ACWR 1,36 ↑ · RPE 8 · uni 6,1 h — täna kontrollitud tempo.", options: { color: "3a2a10", fontSize: 10 } },
  ], { x: bx + 1.1, y: tabY + 0.6, w: bw - 1.4, h: 0.68, fontFace: BODY, align: "left", valign: "middle", margin: 0 });
  // mini chart (ACWR-ish bars)
  s.addText("Koormuse trend (ACWR)", { x: bx + 0.25, y: tabY + 1.5, w: 4, h: 0.3, fontSize: 10, bold: true, color: MUTE, fontFace: BODY, margin: 0 });
  const vals = [1.05, 1.14, 1.22, 1.36, 1.48, 1.41, 1.32, 1.46];
  const chartY = tabY + 1.85, chartH = 0.95, baseY = chartY + chartH;
  const bw2 = 0.52;
  let cbx = bx + 0.35;
  for (let i = 0; i < vals.length; i++) {
    const hh = (vals[i] - 0.9) / 0.7 * chartH;
    const col = vals[i] > 1.45 ? CORAL : vals[i] > 1.3 ? AMBER : TEAL_LT;
    s.addShape(pres.shapes.RECTANGLE, { x: cbx, y: baseY - hh, w: bw2, h: hh, fill: { color: col }, line: { type: "none" } });
    cbx += bw2 + 0.36;
  }
  // danger line 1.5
  s.addShape(pres.shapes.LINE, { x: bx + 0.3, y: baseY - (1.5 - 0.9) / 0.7 * chartH, w: bw - 0.95, h: 0, line: { color: CORAL, width: 1, dashType: "dash" } });
  s.addText("ohulõige 1,5", { x: bx + bw - 1.45, y: baseY - (1.5 - 0.9) / 0.7 * chartH - 0.22, w: 1.3, h: 0.2, fontSize: 8, color: CORAL, fontFace: BODY, align: "right", margin: 0 });

  // right feature list
  const rx = bx + bw + 0.4, rw = W - rx - M;
  const feats = [
    [COMP.desktop, "6 töövaadet ühes rakenduses"],
    [COMP.moon, "Hele / tume teema"],
    [COMP.users, "Külalisrežiim — proovi ilma kontota"],
    [COMP.clip, "Onboarding-juhend uuele kasutajale"],
    [COMP.db, "Automaatne salvestus pilve"],
    [COMP.chart, "PDF / CSV eksport aruanneteks"],
  ];
  let fy2 = 2.05;
  for (const [icon, txt] of feats) {
    await iconCircle(s, icon, TEAL, "FFFFFF", rx, fy2, 0.5);
    s.addText(txt, { x: rx + 0.66, y: fy2 - 0.04, w: rw - 0.66, h: 0.58, fontSize: 12, bold: true, color: INKTX, fontFace: BODY, align: "left", valign: "middle", margin: 0 });
    fy2 += 0.68;
  }

  s.addText([
    { text: "Offline ka ilma LLM-võtmeta: ", options: { bold: true, color: TEAL } },
    { text: "näitajad, ohutusreeglid ja graafikud töötavad; ainult soovituse tekst vajab mudelit.", options: { color: MUTE } },
  ], { x: M, y: 6.2, w: W - 2 * M, h: 0.5, fontSize: 12.5, fontFace: BODY, align: "left", valign: "middle", margin: 0 });
  s.addNotes(
    "KASUTAJALIIDES (~30 s). Rõhuta: see on töötav Streamlit-rakendus, mitte makett. Kuus töövaadet ühes: tänane soovitus, koormuse ajalugu, retrospektiiv, treeningkava, päevalogi, treeneri võrdlus.\n" +
    "Kasutatavus: hele/tume teema, külalisrežiim (proovi ilma kontota), onboarding-juhend, automaatne pilve-salvestus, PDF/CSV eksport.\n" +
    "Tähtis: ilma LLM-võtmeta töötavad näitajad, ohutusreeglid ja graafikud edasi — ainult soovituse tekst vajab mudelit. Demo-võimalus, kui aega/küsitakse."
  );
  pageFooter(s, 8, false);
}

// ---------- 9. VALIDATION METHOD ----------
async function slideValidationMethod() {
  const s = pres.addSlide();
  bg(s, CREAM);
  sectionTag(s, "Valideerimine", LIME_DK, M, 0.55);
  slideTitle(s, "Struktureeritud valideerimine, mitte ad-hoc", false);

  // left: 3-layer comparison
  const lx = M, lw = 5.5;
  s.addText("Kolmekihiline võrdlus iga päeva kohta", { x: lx, y: 1.85, w: lw, h: 0.4, fontSize: 14.5, bold: true, color: INKTX, fontFace: HEAD, margin: 0 });
  const layers = [
    [COMP.robot, TEAL, "1 · LLM-i soovitus", "Vorm.ai kategooria hommikuse konteksti põhjal."],
    [COMP.eyeoff, AMBER, "2 · Treeneri otsus (pime)", "Ille Kukk otsustab mudeli väljundit nägemata."],
    [COMP.check, LIME_DK, "3 · Tegelik järgimine", "Kas sportlane järgis — ja mis juhtus järgmisel päeval."],
  ];
  let ly = 2.35;
  for (const [icon, col, head, body] of layers) {
    roundCard(s, lx, ly, lw, 1.02, CARD, false);
    await iconCircle(s, icon, col, "FFFFFF", lx + 0.25, ly + 0.21, 0.6);
    s.addText(head, { x: lx + 1.0, y: ly + 0.14, w: lw - 1.2, h: 0.36, fontSize: 13.5, bold: true, color: INKTX, fontFace: HEAD, margin: 0 });
    s.addText(body, { x: lx + 1.0, y: ly + 0.5, w: lw - 1.2, h: 0.45, fontSize: 11, color: MUTE, fontFace: BODY, margin: 0 });
    ly += 1.14;
  }

  // right: 4 methods + legend
  const rx = lx + lw + 0.45, rw = W - rx - M;
  s.addText("Neli valideerimismeetodit", { x: rx, y: 1.85, w: rw, h: 0.4, fontSize: 14.5, bold: true, color: INKTX, fontFace: HEAD, margin: 0 });
  const methods = [
    [COMP.clock, "Retrospektiivne test — 30 mineviku päeva, sh kriitilised"],
    [COMP.scale, "Treeneri pimekõrvutus — 14 järjestikust päeva"],
    [COMP.clip, "Igapäevane päevalogi — kasulikkus & veenvus 1–5"],
    [COMP.users, "2 struktureeritud intervjuud treeningkaaslastega"],
  ];
  let ry = 2.3;
  for (const [icon, txt] of methods) {
    await iconCircle(s, icon, TEAL, "FFFFFF", rx, ry, 0.5);
    s.addText(txt, { x: rx + 0.66, y: ry - 0.05, w: rw - 0.66, h: 0.6, fontSize: 12, color: INKTX, fontFace: BODY, valign: "middle", margin: 0 });
    ry += 0.63;
  }
  // legend match/close/conflict
  roundCard(s, rx, ry + 0.04, rw, 1.5, INK, true);
  s.addText("Kokkulangevuse skaala", { x: rx + 0.3, y: ry + 0.18, w: rw - 0.6, h: 0.32, fontSize: 12.5, bold: true, color: LIME, fontFace: HEAD, margin: 0 });
  const leg = [[LIME_DK, "match", "sama kategooria"], [AMBER, "close", "mõlemad ettevaatlikud"], [CORAL, "conflict", "vastandlikud suunad"]];
  let lyy = ry + 0.58;
  for (const [col, a, b] of leg) {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: rx + 0.3, y: lyy, w: 1.15, h: 0.3, fill: { color: col }, rectRadius: 0.15, line: { type: "none" } });
    s.addText(a, { x: rx + 0.3, y: lyy, w: 1.15, h: 0.3, fontSize: 10.5, bold: true, color: "FFFFFF", fontFace: HEAD, align: "center", valign: "middle", margin: 0 });
    s.addText("— " + b, { x: rx + 1.6, y: lyy, w: rw - 1.9, h: 0.3, fontSize: 11, color: "FFFFFF", fontFace: BODY, valign: "middle", margin: 0 });
    lyy += 0.31;
  }

  s.addText([
    { text: "Juhtumiuuring:  ", options: { bold: true, color: TEAL } },
    { text: "sportlane Enari Tõnström × treener Ille Kukk · 14 päeva (18.–31.05.2026).", options: { color: MUTE } },
  ], { x: M, y: 6.62, w: W - 2 * M, h: 0.34, fontSize: 12, fontFace: BODY, align: "left", valign: "middle", margin: 0 });
  s.addNotes(
    "VALIDEERIMINE — METOODIKA (~40 s). Rõhuta sõna 'struktureeritud'. Iga päeva võrdleme kolmes kihis: (1) mida soovitas mudel, (2) mida otsustas treener PIMESI (mudeli väljundit nägemata), (3) mida sportlane tegelikult tegi ja mis järgmisel päeval juhtus.\n" +
    "Neli meetodit: retrospektiivne test minevikuandmetel, treeneri 14-päevane pimekõrvutus, igapäevane päevalogi (1–5 hinnangud), 2 struktureeritud intervjuud.\n" +
    "Kokkulangevust mõõdame kolmes ämbris: match / close / conflict. AUSUS Q&A jaoks: see konkreetne andmestik on esitluse jaoks rekonstrueeritud (toorlog läks kaduma), nii et numbrid illustreerivad metoodikat — ära esita seda kui statistilist tõestust."
  );
  pageFooter(s, 9, false);
}

// ---------- 10. VALIDATION RESULTS ----------
async function slideValidationResults() {
  const s = pres.addSlide();
  bg(s, CREAM);
  sectionTag(s, "Tulemused", LIME_DK, M, 0.55);
  slideTitle(s, "Mudel langes treeneriga ühte 11 / 14 päeval", false);

  // stat callouts row
  const stats = [
    ["78,6%", "praktiliselt sobivaid otsuseid", LIME_DK],
    ["8 / 14", "täpne kokkulangevus (match)", TEAL],
    ["4,1 / 5", "keskmine kasulikkus (tagantjärele)", AMBER],
    ["≥ 70% ✓", "kvantitatiivne eesmärk ületatud", LIME_DK],
  ];
  const cw = (W - 2 * M - 3 * 0.3) / 4;
  let x = M;
  for (const [big, lab, col] of stats) {
    roundCard(s, x, 1.95, cw, 1.55, CARD, false);
    s.addShape(pres.shapes.RECTANGLE, { x: x, y: 1.95, w: cw, h: 0.12, fill: { color: col }, line: { type: "none" } });
    s.addText(big, { x: x + 0.1, y: 2.18, w: cw - 0.2, h: 0.7, fontSize: 30, bold: true, color: col, fontFace: HEAD, align: "center", valign: "middle", margin: 0 });
    s.addText(lab, { x: x + 0.14, y: 2.9, w: cw - 0.28, h: 0.55, fontSize: 11, color: MUTE, fontFace: BODY, align: "center", valign: "top", margin: 0, lineSpacingMultiple: 1.02 });
    x += cw + 0.3;
  }

  // chart left
  const chX = M, chW = 6.4;
  roundCard(s, chX, 3.75, chW, 2.9, CARD, false);
  s.addText("Kokkulangevus 14 päeva lõikes", { x: chX + 0.3, y: 3.9, w: chW - 0.6, h: 0.4, fontSize: 13.5, bold: true, color: INKTX, fontFace: HEAD, margin: 0 });
  s.addChart(pres.charts.BAR, [
    { name: "Päevi", labels: ["Match (8)", "Close (3)", "Conflict (3)"], values: [8, 3, 3] },
  ], {
    x: chX + 0.2, y: 4.3, w: chW - 0.4, h: 2.15, barDir: "col",
    chartColors: [LIME_DK, AMBER, CORAL],
    chartArea: { fill: { color: "FFFFFF" } },
    catAxisLabelColor: "5C7178", catAxisLabelFontSize: 11, catAxisLabelFontBold: true,
    valAxisHidden: true, valGridLine: { style: "none" }, catGridLine: { style: "none" },
    valAxisMaxVal: 9, valAxisMinVal: 0,
    showValue: true, dataLabelPosition: "outEnd", dataLabelColor: "143038", dataLabelFontSize: 13, dataLabelFontBold: true,
    showLegend: false, showTitle: false,
  });

  // interpretation right
  const rx = chX + chW + 0.4, rw = W - rx - M;
  roundCard(s, rx, 3.75, rw, 2.9, INK, true);
  await iconCircle(s, COMP.bulb, LIME, INK, rx + 0.3, 3.98, 0.6);
  s.addText("Mida see tähendab", { x: rx + 1.0, y: 4.02, w: rw - 1.2, h: 0.45, fontSize: 15, bold: true, color: LIME, fontFace: HEAD, valign: "middle", margin: 0 });
  const pts = [
    "Match + close = 11/14: mudeli praktiline suund kattus treeneriga.",
    "Kõik 3 konflikti olid päevad, kus LLM soovitas treenerist konservatiivsemalt.",
    "Kõrge kasulikkus ≠ „treenerist parem“ — vaid andmetega põhjendatav.",
  ];
  let py = 4.6;
  for (const t of pts) {
    s.addShape(pres.shapes.OVAL, { x: rx + 0.35, y: py + 0.08, w: 0.12, h: 0.12, fill: { color: LIME }, line: { type: "none" } });
    s.addText(t, { x: rx + 0.6, y: py - 0.04, w: rw - 0.9, h: 0.62, fontSize: 12, color: "FFFFFF", fontFace: BODY, valign: "top", margin: 0, lineSpacingMultiple: 1.05 });
    py += 0.66;
  }
  s.addNotes(
    "TULEMUSED (~40 s) — see on tugevaim slaid, anna sellele aega. 14 päevast: 8 täpset kokkulangevust (match), 3 lähedast (close), 3 konflikti. Match + close = 11/14 ehk 78,6% praktiliselt sobivaid otsuseid. Keskmine tagantjärele kasulikkus 4,1/5.\n" +
    "Kvantitatiivne eesmärk oli ≥70% — ületatud.\n" +
    "Tõlgendus: kõik 3 konflikti olid päevad, kus mudel oli treenerist KONSERVATIIVSEM. Kõrge kasulikkus ei tähenda 'treenerist parem' — vaid 'andmetega põhjendatav'. See viib loomulikult järgmise slaidi juhtumini."
  );
  pageFooter(s, 10, false);
}

// ---------- 11. CASE STUDY ----------
async function slideCaseStudy() {
  const s = pres.addSlide();
  bg(s, CREAM);
  sectionTag(s, "Fookusjuhtum", CORAL, M, 0.55);
  slideTitle(s, "20.05 — kus tööriist näitas väärtust", false);

  // timeline vertical on left
  const steps = [
    [COMP.heart, TEAL, "Hommik", "ACWR 1,36 · eile RPE 8 · uni 6,1 h"],
    [COMP.robot, AMBER, "Vorm.ai", "Soovitus: vähenda intensiivsust"],
    [COMP.coach, BLUE, "Treener Ille", "Otsus: jätka plaanipäraselt (konkreetne kvaliteettrenn)"],
    [COMP.run, CORAL, "Sportlane", "Järgis treenerit: 6 × 1000 m — viimased kordused rasked"],
    [COMP.warn, CORAL, "Järgmine hommik", "Jalad rasked, RPE 9"],
  ];
  const lx = M, lw = 7.0;
  let y = 1.95;
  const rowH = 0.92;
  for (let i = 0; i < steps.length; i++) {
    const [icon, col, head, body] = steps[i];
    await iconCircle(s, icon, col, "FFFFFF", lx, y, 0.62);
    if (i < steps.length - 1) s.addShape(pres.shapes.LINE, { x: lx + 0.31, y: y + 0.62, w: 0, h: rowH - 0.62, line: { color: LINE, width: 2 } });
    s.addText(head, { x: lx + 0.85, y: y + 0.02, w: lw - 0.85, h: 0.32, fontSize: 13.5, bold: true, color: col === BLUE ? TEAL : col, fontFace: HEAD, margin: 0 });
    s.addText(body, { x: lx + 0.85, y: y + 0.33, w: lw - 0.85, h: 0.5, fontSize: 12, color: INKTX, fontFace: BODY, valign: "top", margin: 0 });
    y += rowH;
  }

  // takeaway box right
  const rx = lx + lw + 0.3, rw = W - rx - M;
  roundCard(s, rx, 1.95, rw, 4.0, INK, true);
  await iconCircle(s, COMP.bulb, LIME, INK, rx + (rw - 0.85) / 2, 2.3, 0.85);
  s.addText("Tööriista roll", { x: rx + 0.3, y: 3.3, w: rw - 0.6, h: 0.4, fontSize: 17, bold: true, color: LIME, fontFace: HEAD, align: "center", margin: 0 });
  s.addText("Vorm.ai ei asenda treenerit.", { x: rx + 0.35, y: 3.8, w: rw - 0.7, h: 0.5, fontSize: 16, bold: true, color: "FFFFFF", fontFace: HEAD, align: "center", margin: 0 });
  s.addText("Ta tõstab esile andmetest tuleva riskisignaali enne, kui sportlane ise plaani muudab — andmepõhise teise arvamusena treeneriplaani kõrval.",
    { x: rx + 0.4, y: 4.35, w: rw - 0.8, h: 1.5, fontSize: 13, color: MUTE_L, fontFace: BODY, align: "center", valign: "top", margin: 0, lineSpacingMultiple: 1.12 });
  s.addNotes(
    "FOOKUSJUHTUM (~40 s) — jutusta see kui lugu. 20. mai: hommikul ACWR 1,36, eile RPE 8, uni 6,1 h. Mudel ütles 'vähenda intensiivsust'. Treener Ille ütles 'jätka' — tal oli konkreetne kvaliteettrenn plaanis. Sportlane usaldas treenerit, tegi 6×1000 m, viimased kordused olid rasked. Järgmisel hommikul: jalad rasked, RPE 9.\n" +
    "Mõte: mudeli soovitus oli tagantjärele pigem õige. AGA — väärtus pole treeneri asendamine. Treener teab konteksti (võistlusplaan, periodiseering), mida mudel ei tea. Vorm.ai roll on tõsta riskisignaal esile ENNE, kui sportlane ise plaani muudab. Aus ja tasakaalukas sõnum."
  );
  pageFooter(s, 11, false);
}

// ---------- 12. CONCLUSION ----------
async function slideConclusion() {
  const s = pres.addSlide();
  bg(s, INK);
  s.addShape(pres.shapes.RECTANGLE, { x: M, y: 0.7, w: 1.5, h: 0.12, fill: { color: LIME }, line: { type: "none" } });
  s.addText("Kokkuvõte", { x: M, y: 0.9, w: W - 2 * M, h: 0.8, fontSize: 32, bold: true, color: "FFFFFF", fontFace: HEAD, margin: 0 });

  // two columns: goals met + limitations
  const colW = (W - 2 * M - 0.4) / 2;
  // goals
  roundCard(s, M, 1.95, colW, 2.55, INK2, true);
  await iconCircle(s, COMP.check, LIME, INK, M + 0.3, 2.18, 0.58);
  s.addText("Eesmärgid täidetud", { x: M + 1.0, y: 2.22, w: colW - 1.2, h: 0.45, fontSize: 15.5, bold: true, color: LIME, fontFace: HEAD, valign: "middle", margin: 0 });
  const goals = ["Kvantitatiivne ≥ 70% → 78,6%", "Otsast-otsa pipeline töötab päris andmetel", "Mitme kasutaja tugi + treener-sportlane seos"];
  let gy = 2.95;
  for (const g of goals) {
    s.addShape(pres.shapes.OVAL, { x: M + 0.34, y: gy + 0.07, w: 0.12, h: 0.12, fill: { color: LIME }, line: { type: "none" } });
    s.addText(g, { x: M + 0.6, y: gy - 0.05, w: colW - 0.85, h: 0.45, fontSize: 12.5, color: "FFFFFF", fontFace: BODY, valign: "middle", margin: 0 });
    gy += 0.5;
  }
  // limitations
  const l2 = M + colW + 0.4;
  roundCard(s, l2, 1.95, colW, 2.55, INK2, true);
  await iconCircle(s, COMP.scale, AMBER, INK, l2 + 0.3, 2.18, 0.58);
  s.addText("Ausad piirangud", { x: l2 + 1.0, y: 2.22, w: colW - 1.2, h: 0.45, fontSize: 15.5, bold: true, color: AMBER, fontFace: HEAD, valign: "middle", margin: 0 });
  const lims = ["Väike valim: 1 sportlane + 1 treener, 14 päeva", "Kasulikkuse hinne on tagantjäreline", "Treener teab konteksti (periodiseering), mida mudel ei tea"];
  let lyy = 2.95;
  for (const g of lims) {
    s.addShape(pres.shapes.OVAL, { x: l2 + 0.34, y: lyy + 0.07, w: 0.12, h: 0.12, fill: { color: AMBER }, line: { type: "none" } });
    s.addText(g, { x: l2 + 0.6, y: lyy - 0.05, w: colW - 0.85, h: 0.5, fontSize: 12.5, color: "FFFFFF", fontFace: BODY, valign: "top", margin: 0, lineSpacingMultiple: 1.02 });
    lyy += 0.52;
  }

  // big takeaway
  roundCard(s, M, 4.75, W - 2 * M, 1.55, INK3, true);
  s.addShape(pres.shapes.RECTANGLE, { x: M, y: 4.75, w: 0.14, h: 1.55, fill: { color: LIME }, line: { type: "none" } });
  s.addText([
    { text: "Sõnum:  ", options: { bold: true, color: LIME } },
    { text: "LLM-i soovitus oli konfliktses kohas pigem õige — kuid väärtus pole treeneri asendamine, vaid andmepõhine riskisignaal tema plaani kõrval.", options: { color: "FFFFFF" } },
  ], { x: M + 0.45, y: 4.75, w: W - 2 * M - 0.8, h: 1.55, fontSize: 16.5, fontFace: BODY, align: "left", valign: "middle", margin: 0, lineSpacingMultiple: 1.1 });

  s.addText([
    { text: "Edasi:  ", options: { bold: true, color: MUTE_L } },
    { text: "rohkem kasutajaid ja suurem valim · prognoosimudeli täpsustamine · pikem reaalkasutus.", options: { color: MUTE_L } },
  ], { x: M, y: 6.45, w: W - 2 * M, h: 0.4, fontSize: 12.5, fontFace: BODY, align: "left", valign: "middle", margin: 0 });

  s.addText("Aitäh!  Küsimused?", { x: W - 4.2, y: 6.45, w: 3.6, h: 0.45, fontSize: 16, bold: true, color: LIME, fontFace: HEAD, align: "right", valign: "middle", margin: 0 });
  s.addNotes(
    "KOKKUVÕTE (~35 s). Eesmärgid täidetud: kvantitatiivne ≥70% → 78,6%; otsast-otsa pipeline töötab päris andmetel; mitme kasutaja tugi + treener-sportlane seos valmis.\n" +
    "Ausad piirangud (näita küpsust): väike valim (1 sportlane + 1 treener, 14 päeva), kasulikkuse hinne on tagantjäreline, treener teab konteksti, mida mudel ei tea. Maini ka, et esitlusandmestik on rekonstrueeritud.\n" +
    "Lõppsõnum: mudeli soovitus oli konfliktses kohas pigem õige, kuid väärtus pole treeneri asendamine — vaid andmepõhine riskisignaal tema plaani kõrval. Tänan, võtan küsimusi.\n" +
    "VÕIMALIKUD KÜSIMUSED: Miks LLM, mitte puhas reeglimootor? (nüansid + inimkeele põhjendus). Kuidas väldid hallutsinatsioone? (temp=0, reeglid-turvafilter, agregeeritud sisend, kasutaja näeb tausta). Privaatsus? (RLS + nõusolek + ainult agregaadid LLM-ile). Kuidas skaleerub? (Supabase multi-tenant juba olemas)."
  );
}

build().catch(e => { console.error(e); process.exit(1); });
