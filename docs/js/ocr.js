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
    if (letters >= 3 && lineLetters / l.length >= 0.5 && !SKIP.test(t)) { name = t; break; }
  }
  return { name, number, total, lines };
}

/** Zoekterm voor de database: het eerste woord van de naam dat lang genoeg is. */
export const searchTerm = (parsed) => (parsed.name || "").split(" ").find((w) => w.replace(/[^A-Za-z]/g, "").length >= 3) || null;

export function rankCandidates(parsed, rows) {
  const first = norm(searchTerm(parsed) || "");
  const full = norm(parsed.name);
  return rows.map((r) => {
    const n = norm(r.name);
    let s = 0;
    if (full && n === full) s += 3; else if (first && n.startsWith(first)) s += 2; else if (first && n.includes(first)) s += 1;
    if (parsed.number && normNum(r.number) === normNum(parsed.number)) s += 3;
    if (parsed.total && r.set_total != null && String(r.set_total) === String(parsed.total)) s += 2;
    return { ...r, score: s };
  }).filter((r) => r.score > 0).sort((a, b) => b.score - a.score).slice(0, 6);
}
