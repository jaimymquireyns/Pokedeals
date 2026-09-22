// Berekeningen aan de kant van de app: netto winst, uitleg bij de kans en 'aandacht nodig'.
import { days, eur, pp, signed } from "./ui.js";

export const DEFAULT_SETTINGS = { fee_pct: 5, ship_eur: 1.5, net_only: true, net_min_pct: 3, digest: true, price_alerts: true, horizon: 30, pct: 10 };

// Periodes op de kaartdetailpagina, los van de Instellingen-standaard. Bij lange periodes ligt de drempel hoger,
// anders is bijna alles "kans op stijging én kans op daling" tegelijk (over 2 jaar beweegt bijna elke prijs 10%).
export const PERIODS = [
  { key: "7", label: "7d", horizon: 7, pct: 5 },
  { key: "14", label: "14d", horizon: 14, pct: 7 },
  { key: "30", label: "30d", horizon: 30, pct: 10 },
  { key: "3m", label: "3m", horizon: 90, pct: 20 },
  { key: "6m", label: "6m", horizon: 180, pct: 35 },
  { key: "12m", label: "12m", horizon: 365, pct: 60 },
  { key: "24m", label: "24m", horizon: 730, pct: 100 },
];

/** Verwachte winst na verkoopkosten en verzending, als fractie van de huidige prijs. */
export const netGain = (price, exp, s) => ((1 + exp) * (1 - s.fee_pct / 100) - s.ship_eur / price) - 1;

export const isOpportunity = (r, s) => !s.net_only || netGain(r.price, r.exp, s) * 100 >= s.net_min_pct;

export const ATTN = { minDown: 0.35, profit: 0.30, maxUp: 0.25 };

export function attention(items) {
  const out = [];
  for (const it of items) {
    const value = it.value_each ?? null, buy = it.purchase_price;
    if (it.p_down != null && it.p_down >= ATTN.minDown) out.push({ it, kind: "daling", chip: `${pp(it.p_down)} kans op daling` });
    else if (value && buy && value / buy - 1 >= ATTN.profit && it.p_up != null && it.p_up <= ATTN.maxUp) out.push({ it, kind: "winst", chip: "Winst nemen?" });
  }
  return out;
}

/** Uitleg bij de kans, opgebouwd uit dezelfde gegevens als het model. */
export function whyBullets(f) {
  const out = [];
  if (f.mom30 != null && Math.abs(f.mom30) >= 0.03 && f.avg30) {
    out.push(f.mom30 > 0
      ? { tone: "g", head: "Opwaartse trend.", text: `De prijs staat ${signed(f.mom30).replace("+", "")} boven het 30-daags gemiddelde (${eur(f.avg30)}).` }
      : { tone: "r", head: "Neerwaartse trend.", text: `De prijs staat ${signed(-f.mom30).replace("+", "")} onder het 30-daags gemiddelde (${eur(f.avg30)}).` });
  }
  if (f.avg7 && f.avg30) {
    if (f.avg7 > f.avg30 * 1.01) out.push({ tone: "g", head: "De stijging is recent.", text: `Het 7-daags gemiddelde (${eur(f.avg7)}) ligt boven het 30-daagse.` });
    else if (f.avg7 < f.avg30 * 0.99) out.push({ tone: "r", head: "De daling is recent.", text: `Het 7-daags gemiddelde (${eur(f.avg7)}) ligt onder het 30-daagse.` });
  }
  if (f.sigma && f.mode === "snel") {
    out.push({ tone: "n", head: "Schommeling is een aanname.", text: `Er is nog te weinig prijsgeschiedenis; we rekenen met ongeveer ${(f.sigma * 100).toFixed(0)}% per dag.` });
  } else if (f.sigma) {
    const pct = (f.sigma * 100).toFixed(1).replace(".", ",");
    out.push(f.sigma >= 0.05
      ? { tone: "r", head: "Prijs schommelt sterk.", text: `Gemiddeld ongeveer ${pct}% per dag, dus de uitkomst is erg onzeker.` }
      : { tone: "n", head: "Prijs schommelt.", text: `Gemiddeld ongeveer ${pct}% per dag, dus de uitkomst blijft onzeker.` });
  }
  out.push({ tone: "i", head: `Betrouwbaarheid ${f.confidence}.`, text: f.mode === "snel"
    ? `Schatting uit de 30/7/1-daagse gemiddelden, want er is pas ${days(f.n)} prijsdata. Meer data maakt de schatting scherper.`
    : `Gebaseerd op ${days(f.n)} prijsdata; meer data maakt de schatting scherper.` });
  return out;
}

export const SIGNAL_TEXT = {
  koop: "Hoge kans op stijging en lage kans op daling.",
  verkoop: "Hoge kans op daling en lage kans op stijging.",
  afwachten: "Geen duidelijk overwicht van stijging of daling.",
};

/** Signaal voor een item dat je al bezit (houden / winst nemen / verkopen overwegen). */
export function ownedSignal(f, item) {
  if (!f || f.p_up == null) return { label: "houden", text: "Nog te weinig gegevens voor een advies." };
  if (f.p_down >= ATTN.minDown) return { label: "verkopen overwegen", text: "De kans op daling is groot." };
  const gain = item.value_each && item.purchase_price ? item.value_each / item.purchase_price - 1 : 0;
  if (gain >= ATTN.profit && f.p_up <= ATTN.maxUp) return { label: "winst nemen?", text: "Je zit goed in de winst en de kans op meer stijging is klein." };
  return { label: "houden", text: f.p_up >= 0.4 ? "De verwachting is positief, maar de extra winst is nog niet zeker." : "Geen reden om nu iets te doen." };
}

export const gradeKey = (c) => (c.grade_company ? `${c.grade_company}-${c.grade}` : "raw");
export const gradeLabel = (c) => (c.grade_company ? `${c.grade_company} ${c.grade}` : null);
