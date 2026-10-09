// Tekst van een kaartfoto omzetten naar naam en nummer, en die koppelen aan onze kaarten. Puur rekenwerk, goed testbaar.

export const normNum = (n) => String(n ?? "").split("/")[0].replace(/^0+(?=\d)/, "").toLowerCase();
const norm = (s) => String(s ?? "").toLowerCase().replace(/[^a-z0-9]/g, "");

const SKIP = /^(basic|stage\s*\d|pok[eé]mon|trainer|item|supporter|stadium|energy|illus|ability|attack|weakness|resistance|retreat|evolves)\b/i;

export function parseCardText(text) {
  const raw = String(text || "");
  const lines = raw.split(/\r?\n/).map((l) => l.replace(/[|_—–~=]+/g, " ").trim()).filter(Boolean);
  let number = null, total = null;
  const m = raw.match(/\b(\d{1,3})\s*\/\s*(\d{2,3})\b/);
  if (m) { number = m[1]; total = m[2]; }
  let name = null;
  for (const l of lines.slice(0, 8)) {
    const t = l.replace(/\bHP\s*\d+\b/i, "").replace(/\b\d+\s*HP\b/i, "").replace(/^(basic|stage\s*\d|mega|break)\b\s*/i, "")
      .replace(/[^A-Za-z\u00C0-\u017F'’.\- ]/g, " ").replace(/\s+/g, " ").trim();
    const letters = (t.match(/[A-Za-z]/g) || []).length;
    const lineLetters = (l.match(/[A-Za-z]/g) || []).length;
    if (letters >= 3 && lineLetters / l.length >= 0.5 && !SKIP.test(t)) {
      // losse ruis van 1-2 letters rond de naam ('dq Charizard', 'EC Mewtwo ow') weghalen; ex, V, GX e.d. horen er wel bij
      const words = t.split(" ").filter((w) => w.length > 2 || /^(ex|EX|V|GX|LV|δ|&)$/.test(w));
      if (words.join("").length >= 3) { name = words.join(" "); break; }
    }
  }
  return { name, number, total, lines };
}

/** Zoekterm voor de database: het eerste woord van de naam dat lang genoeg is. */
export const searchTerm = (parsed) => {
  // het langste woord, afgekapt waar ruis aan de naam vastgeplakt is ('UmbreonWaaxa' -> 'Umbreon')
  const words = (parsed.name || "").split(" ").map((w) => w.replace(/^([A-Z]?[a-z\u00C0-\u017F'’.\-]{2,})[A-Z].*$/, "$1")).filter((w) => w.replace(/[^A-Za-z]/g, "").length >= 3);
  return words.sort((a, b) => b.length - a.length)[0] || null;
};

// ---- naam met een tikfout herkennen: 'Ehandelune' is Chandelure, 'gneasel' is Sneasel ----
/** Afstand tussen twee woorden: hoeveel letters je moet veranderen, toevoegen of weghalen. */
export function lev(a, b) {
  a = String(a); b = String(b);
  if (!a.length) return b.length; if (!b.length) return a.length;
  let prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    for (let j = 1; j <= b.length; j++) cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    prev = cur;
  }
  return prev[b.length];
}

/** Hoe goed past een gelezen woord in een woord van de kaartnaam (0..1)? Ook als er ruis aan vastplakt ('dMabosstiff'). */
export function wordSim(read, word) {
  read = norm(read); word = norm(word);
  if (!read || !word || word.length < 3) return 0;
  if (read === word) return 1;
  let best = 1 - lev(read, word) / Math.max(read.length, word.length);
  // het gelezen woord is langer (ruis ervoor of erna): vergelijk met elk stuk van dezelfde lengte, met een kleine aftrek
  if (read.length > word.length) {
    for (let i = 0; i + word.length <= read.length; i++) {
      for (const L of [word.length - 1, word.length, word.length + 1]) {
        if (L < 3 || i + L > read.length) continue;
        best = Math.max(best, 1 - lev(read.slice(i, i + L), word) / Math.max(L, word.length) - 0.05);
      }
    }
  }
  return Math.max(0, best);
}

const NAME_STOP = /^(basic|stage|pokemon|trainer|item|supporter|stadium|energy|illus|ability|attack|weakness|resistance|retreat|tool|evolves|from|rule|when|your|this|the|and)$/i;

/** De bruikbare woorden uit wat er bovenaan de kaart gelezen werd (namen van minstens 4 letters, zonder 'Basic', 'Stage' e.d.). */
export function nameTokens(text) {
  const out = [];
  const clean = String(text || "").split(/\r?\n/).filter((l) => !/evolves|from|put .* on/i.test(l)).join(" ");
  for (const w of clean.split(/[^A-Za-z\u00C0-\u017F'’]+/)) {
    const t = w.replace(/['’]s?$/, "");
    if (norm(t).length >= 4 && !NAME_STOP.test(norm(t)) && !/^(.)\1+$/.test(norm(t))) out.push(t);
  }
  return [...new Set(out)].slice(0, 8);
}

/** Stukjes van 4 letters om in de database op te zoeken: zo vind je 'Chandelure' ook via 'Ehandelune' (via 'ndel'). */
export function nameGrams(tokens, max = 14) {
  const grams = [];
  for (const t of tokens) {
    const n = norm(t).replace(/[0-9]/g, "");
    for (let i = 0; i + 4 <= n.length; i += 2) grams.push(n.slice(i, i + 4));
  }
  return [...new Set(grams)].slice(0, max);
}

/** Beste overeenkomst tussen de gelezen woorden en de naam van een kaart (0..1); bij namen van 2 woorden telt het belangrijkste woord. */
export function nameSim(tokens, cardName) {
  const words = String(cardName || "").split(/[^A-Za-z\u00C0-\u017F]+/).filter((w) => w.length >= 3 && !/^(ex|gx|vmax|vstar|mega|team|dark|light)$/i.test(w));
  let best = 0;
  for (const t of tokens) for (const w of words) best = Math.max(best, wordSim(t, w));
  return best;
}

export function rankCandidates(parsed, rows) {
  const first = norm(searchTerm(parsed) || "");
  const full = norm(parsed.name);
  const tokens = parsed.tokens && parsed.tokens.length ? parsed.tokens : nameTokens(parsed.name || "");
  const code = String(parsed.setName || "").toLowerCase();
  return rows.map((r) => {
    const n = norm(r.name);
    let s = 0;
    // de naam weegt het zwaarst: een verkeerd gelezen cijfer komt vaker voor dan een kaart met een heel andere naam
    const sim = nameSim(tokens, r.name);
    if (full && n === full) s += 5;
    else if (sim >= 0.8) s += 4 + (sim - 0.8) * 5;
    else if (first && n.startsWith(first)) s += 3;
    else if (sim >= 0.65) s += 2;
    else if (first || tokens.length) s -= 2;
    const pn = normNum(parsed.number), rn = normNum(r.number);
    const digits = (x) => x.replace(/^[a-z]+/, "").replace(/^0+(?=\d)/, "");
    const numOk = parsed.number && (rn === pn || (digits(rn) === digits(pn) && /promo|black star/i.test(r.set_name || "")));   // 'SVP101' = promo nr. 101
    if (numOk) s += 3;
    else if (parsed.number && pn.length >= 2 && rn.length === pn.length && lev(rn, pn) === 1) s += 1.5;   // één cijfer verkeerd gelezen ('709' voor 109)
    if (parsed.total && r.set_total != null && String(Number(r.set_total)) === String(Number(parsed.total))) s += 2;
    if (code && String(r.set_name || "").toLowerCase().includes(code)) s += 2;
    return { ...r, score: s, sim };
  }).filter((r) => r.score > 0).sort((a, b) => b.score - a.score).slice(0, 6);   // (bij score 0 of lager: niets dat bij de foto past)
}

/** De onderrand van een kaart: nummer ("149/128", "TG05/TG30", "SWSH074") en setcode ("30C", "OBF", "PAF"). OCR haalt de streep
 * of een cijfer soms door elkaar (l/I/| voor 1, O voor 0); dat vangen we hier op. knownCodes: lijst bekende setcodes (kleine letters). */
export function parseBottom(text, knownCodes = []) {
  const t = String(text || "").replace(/[|]/g, "1");
  const fix = (x) => x.replace(/[oO]/g, "0").replace(/[lI]/g, "1");
  let number = null, total = null, setCode = null;
  const m = t.match(/\b([A-Za-z]{0,3}[0-9OlI]{1,3})\s*[\/7]\s*([A-Za-z]{0,3}[0-9OlI]{2,3})\b/);
  if (m) {
    // letters ervoor die eigenlijk cijfers zijn ('l49' = 149, 'O5' = 05) horen bij het nummer, echte letters ('TG05') niet
    // alleen echte voorvoegsels (TG05, GG12, SV045, RC5, H31...) blijven staan; andere letters zijn leesfouten en vallen weg
    const split = (x) => {
      const r = x.match(/^([A-Za-z]{0,3})(.*)$/);
      if (/^[lIoO]+$/.test(r[1])) return ["", r[1] + r[2]];
      return /^(TG|GG|SV|RC|SH|SL|H|BW|XY|SM)$/i.test(r[1]) || !r[1] ? [r[1], r[2]] : ["", r[2]];
    };
    const a = [null, ...split(m[1])], b = [null, ...split(m[2])];
    number = (a[1] + fix(a[2])).toUpperCase();
    total = (b[1] + fix(b[2])).toUpperCase();
    if (!/^\d+$/.test(total)) total = null;     // 'TG30': geen settotaal om op te zoeken
  } else {
    const promo = t.match(/\b(SWSH|SVP|SV|SM|XY|BW|TG|GG|SL)\s?-?(\d{2,3})\b/i);
    if (promo) number = (promo[1] + promo[2]).toUpperCase();
  }
  const codes = new Set(knownCodes);
  // de setcode staat op dezelfde regel als het nummer; elders in de tekst (aanvallen, regels) is een losse 'LA' of 'CEL' toeval
  const line = m ? (t.split(/\r?\n/).find((l) => l.includes(m[0])) || "") : "";
  for (const w of line.split(/[^A-Za-z0-9]+/)) {
    const k = w.toLowerCase();
    if (k.length >= 2 && k.length <= 4 && /[a-z]/.test(k) && codes.has(k)) { setCode = w.toUpperCase(); break; }
  }
  return { number, total, setCode };
}

/** Zoekopdrachten voor een gelezen kaart, van precies naar breed. Zoeken (cardsearch.js) begrijpt "149/128" en setcodes als "30c". */
export function scanQueries(p) {
  const name = (p.name || "").trim(), nr = p.number ? (p.total ? `${p.number}/${p.total}` : p.number) : "", code = p.setCode || "";
  const qs = [[name, code, nr], [name, nr], [code, nr], [nr], [name, code], [name]].map((x) => x.filter(Boolean).join(" ").trim());
  return [...new Set(qs.filter((q) => q.length >= 2 && !(q === nr && !p.total && !code)))];   // een los nummer zonder settotaal is te vaag
}
