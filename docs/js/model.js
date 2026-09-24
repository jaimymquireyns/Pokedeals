// Berekeningen aan de kant van de app: netto winst, uitleg bij de kans en 'aandacht nodig'.
import { days, eur, pp, signed } from "./ui.js";

export const DEFAULT_SETTINGS = { fee_pct: 6, net_only: true, net_min_pct: 3, digest: true, price_alerts: true, horizon: 30, pct: 10 };

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
// Verzendkosten lopen op met de verkoopprijs (Cardmarkets eigen tarieven zijn niet automatisch op te halen).
export const SHIP_TIERS = [[5, 1.5], [20, 4], [50, 7], [150, 10], [Infinity, 15]];
export const shipCost = (price) => SHIP_TIERS.find(([limit]) => price <= limit)[1];
export const netGain = (price, exp, s) => {
  const sellPrice = price * (1 + exp);
  return (1 + exp) * (1 - s.fee_pct / 100) - shipCost(sellPrice) / price - 1;
};

export const isOpportunity = (r, s) => !s.net_only || netGain(r.price, r.exp, s) * 100 >= s.net_min_pct;

// Verkoopprijs die nodig is om quitte te spelen op 'costPrice' (aankoopprijs of, als je 'm nog niet hebt, de huidige
// prijs), na commissie en de oplopende verzendtabel. De verzendtrap hangt af van de verkoopprijs zelf, dus een
// paar keer benaderen tot het stabiel is (de tabel heeft maar een paar treden, dit convergeert vrijwel meteen).
export function breakEven(costPrice, feePct) {
  let sell = costPrice;
  for (let i = 0; i < 5; i++) sell = (costPrice + shipCost(sell)) / (1 - feePct / 100);
  return sell;
}

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

const LABELS = { g: "Positief", r: "Negatief", n: "Matig" };

/** Uitleg bij de kans, opgebouwd uit dezelfde gegevens als het model. Elk punt krijgt ook een kort getal (val) en
 * een kwalitatief label (label), zodat de app dat apart en duidelijk kan tonen naast de volzin. */
export function whyBullets(f) {
  const out = [];
  if (f.mom30 != null && Math.abs(f.mom30) >= 0.03 && f.avg30) {
    out.push(f.mom30 > 0
      ? { tone: "g", head: "Prijs ligt boven het gemiddelde", text: `Nu ${signed(f.mom30).replace("+", "")} hoger dan het gemiddelde van de laatste 30 dagen (${eur(f.avg30)}) — de prijs is dus al aan het stijgen.`, val: signed(f.mom30, 0), label: LABELS.g }
      : { tone: "r", head: "Prijs ligt onder het gemiddelde", text: `Nu ${signed(-f.mom30).replace("+", "")} lager dan het gemiddelde van de laatste 30 dagen (${eur(f.avg30)}) — de prijs is dus al aan het dalen.`, val: signed(f.mom30, 0), label: LABELS.r });
  }
  if (f.avg7 && f.avg30) {
    const diff = f.avg7 / f.avg30 - 1;
    if (f.avg7 > f.avg30 * 1.01) out.push({ tone: "g", head: "De stijging versnelt", text: "De laatste 7 dagen ging het sneller omhoog dan de 30 dagen ervoor — de trend zet nog door, is niet alweer aan het afvlakken.", val: signed(diff, 0), label: LABELS.g });
    else if (f.avg7 < f.avg30 * 0.99) out.push({ tone: "r", head: "De daling versnelt", text: "De laatste 7 dagen ging het sneller omlaag dan de 30 dagen ervoor — de trend zet nog door, is niet alweer aan het afvlakken.", val: signed(diff, 0), label: LABELS.r });
  }
  if (f.sigma && f.mode === "snel") {
    out.push({ tone: "n", head: "Schommeling is een aanname", text: `Er is nog te weinig prijsgeschiedenis; we rekenen met ongeveer ${(f.sigma * 100).toFixed(0)}% per dag.`, val: `±${(f.sigma * 100).toFixed(0)}%`, label: LABELS.n });
  } else if (f.sigma) {
    const pct = (f.sigma * 100).toFixed(1).replace(".", ",");
    out.push(f.sigma >= 0.05
      ? { tone: "r", head: "Prijs schommelt sterk", text: "Gemiddelde dagelijkse beweging — de uitkomst is hierdoor erg onzeker.", val: `±${pct}%`, label: "Hoog" }
      : { tone: "n", head: "Prijs schommelt", text: "Gemiddelde dagelijkse beweging — de uitkomst blijft hierdoor onzeker.", val: `±${pct}%`, label: "Matig" });
  }
  out.push({ tone: "i", head: "Betrouwbaarheid", text: f.mode === "snel"
    ? `Schatting uit de 30/7/1-daagse gemiddelden, want er is pas ${days(f.n)} prijsdata. Meer data maakt de schatting scherper.`
    : `Hoeveelheid prijsdata waar de schatting op is gebaseerd. Meer data maakt de schatting scherper.`, val: days(f.n), label: f.confidence.charAt(0).toUpperCase() + f.confidence.slice(1) });
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
