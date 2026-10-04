// Berekeningen aan de kant van de app: netto winst, uitleg bij de kans en 'aandacht nodig'.
import { days, eur, pp, signed } from "./ui.js";

export const DEFAULT_SETTINGS = { fee_pct: 6, net_only: true, net_min_pct: 3, digest: true, price_alerts: true, horizon: 30, pct: 10, attn_pct: 15 };

// De kansberekening klopt nog niet goed genoeg (zie de backtest): verborgen in de app tot ze beter is. Op de achtergrond
// blijft ze gewoon draaien. Op true zetten om alles weer te tonen.
export const SHOW_PREDICTIONS = false;

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

// Verzending bij een Cardmarket-aankoop, geschat op de prijs van de kaart (de koper betaalt de verzending; de verkoper
// koopt daar de postzegel van). Alleen nodig voor kaarten die je nog niet hebt: bij je eigen aankopen vul je de echte
// verzending in. Cardmarkets eigen tarieven zijn niet automatisch op te halen.
export const SHIP_TIERS = [[5, 1.5], [20, 4], [50, 7], [150, 10], [Infinity, 15]];
export const shipCost = (price) => SHIP_TIERS.find(([limit]) => price <= limit)[1];
export const PACKAGING = 0.5;   // hoesje, toploader en envelop per verkoop

/** Echte kostprijs per stuk: aankoopprijs plus jouw deel van de verzending en overige kosten bij het kopen. */
export const costEach = (c) => Number(c.purchase_price) + (Number(c.purchase_shipping || 0) + Number(c.purchase_costs || 0)) / Math.max(Number(c.quantity) || 1, 1);

/** Verdeelt een bedrag over regels naar verhouding van hun gewicht, afgerond op centen; het afrondingsverschil gaat
 * naar de laatste regel, zodat de delen altijd precies optellen tot het totaal. Geen gewicht: gelijk verdelen. */
export function allocate(total, weights) {
  const n = weights.length;
  if (!n) return [];
  const sum = weights.reduce((s, w) => s + Math.max(Number(w) || 0, 0), 0);
  const raw = weights.map((w) => (sum > 0 ? (Math.max(Number(w) || 0, 0) / sum) * total : total / n));
  const out = raw.map((x) => Math.round(x * 100) / 100);
  out[n - 1] = Math.round((total - out.slice(0, -1).reduce((s, x) => s + x, 0)) * 100) / 100;
  return out;
}

/** Winst van een verkoopbestelling, in totaal en per regel. lines: [{price_share, cost_total}]. */
export function saleProfit(sale, lines) {
  const extra = Number(sale.shipping_received || 0) - Number(sale.shipping_paid || 0) - Number(sale.commission || 0) - Number(sale.other_costs || 0);
  const extraShares = allocate(extra, lines.map((l) => l.price_share));
  const per = lines.map((l, i) => Math.round((Number(l.price_share) + extraShares[i] - Number(l.cost_total)) * 100) / 100);
  return { total: Math.round(per.reduce((s, x) => s + x, 0) * 100) / 100, per, extraShares };
}

/** Verwachte winst als fractie van wat je betaalt, als je nu koopt (prijs + geschatte verzending) en na de
 * verwachte stijging verkoopt (min commissie en verpakking; de verzending bij verkopen betaalt de koper). */
export const netGain = (price, exp, s) => {
  const cost = price + shipCost(price);
  const net = price * (1 + exp) * (1 - s.fee_pct / 100) - PACKAGING;
  return net / cost - 1;
};

export const isOpportunity = (r, s) => !s.net_only || netGain(r.price, r.exp, s) * 100 >= s.net_min_pct;

// Verkoopprijs die nodig is om quitte te spelen: alles wat je betaalde (kaart + verzending bij aankoop) plus
// verpakking, gedeeld door wat je na commissie overhoudt.
export function breakEven(costPrice, feePct, buyShipping = 0) {
  return (costPrice + buyShipping + PACKAGING) / (1 - feePct / 100);
}

export const ATTN = { minDown: 0.35, profit: 0.30, maxUp: 0.25 };

/** 'Aandacht nodig': kaarten die de laatste 30 dagen sterk in waarde zijn gestegen of gedaald (vanaf s.attn_pct).
 * Gebaseerd op wat er echt gebeurde, niet op de (nog verborgen) voorspellingen. */
export function attention(items, s = DEFAULT_SETTINGS) {
  const limit = (Number(s.attn_pct) || DEFAULT_SETTINGS.attn_pct) / 100;
  const out = [];
  for (const it of items) {
    const now = it.value_each ?? null, before = it.value_30d_ago ?? null;
    if (!now || !before) continue;
    const ch = now / before - 1;
    if (ch >= limit) out.push({ it, kind: "winst", chip: `▲ ${signed(ch, 0)} in 30 dagen` });
    else if (ch <= -limit) out.push({ it, kind: "daling", chip: `▼ ${signed(ch, 0)} in 30 dagen` });
  }
  return out.sort((a, b) => Math.abs(b.it.value_each / b.it.value_30d_ago - 1) - Math.abs(a.it.value_each / a.it.value_30d_ago - 1));
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
  const gain = item.value_each && item.purchase_price ? item.value_each / costEach(item) - 1 : 0;
  if (gain >= ATTN.profit && f.p_up <= ATTN.maxUp) return { label: "winst nemen?", text: "Je zit goed in de winst en de kans op meer stijging is klein." };
  return { label: "houden", text: f.p_up >= 0.4 ? "De verwachting is positief, maar de extra winst is nog niet zeker." : "Geen reden om nu iets te doen." };
}

export const gradeKey = (c) => (c.grade_company ? `${c.grade_company}-${c.grade}` : "raw");
export const gradeLabel = (c) => (c.grade_company ? `${c.grade_company} ${c.grade}` : null);
