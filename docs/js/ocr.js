// Tekst van een kaartfoto omzetten naar naam en nummer, en die koppelen aan onze kaarten. Puur rekenwerk, goed testbaar.

export const normNum = (n) => String(n ?? "").split("/")[0].replace(/^0+(?=\d)/, "").toLowerCase();
const norm = (s) => String(s ?? "").toLowerCase().replace(/[^a-z0-9]/g, "");

const SKIP = /^(basic|stage\s*\d|pok[eé]mon|trainer|item|supporter|stadium|energy|illus|ability|attack|weakness|resistance|retreat)\b/i;

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

export function rankCandidates(parsed, rows) {
  const first = norm(searchTerm(parsed) || "");
  const full = norm(parsed.name);
  return rows.map((r) => {
    const n = norm(r.name);
    let s = 0;
    if (full && n === full) s += 3; else if (first && n.startsWith(first)) s += 2; else if (first && n.includes(first)) s += 1;
    if (parsed.number && normNum(r.number) === normNum(parsed.number)) s += 3;
    if (parsed.total && r.set_total != null && String(Number(r.set_total)) === String(Number(parsed.total))) s += 2;
    return { ...r, score: s };
  }).filter((r) => r.score > 0).sort((a, b) => b.score - a.score).slice(0, 6);
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
