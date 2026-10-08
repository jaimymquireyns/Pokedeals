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
// Onder EUR25 gewone post (rond EUR3), vanaf EUR25 als pakket (duurder). Een schatting; pas aan als de tarieven veranderen.
export const SHIP_TIERS = [[24.99, 3], [50, 7], [150, 10], [Infinity, 15]];
export const shipCost = (price) => SHIP_TIERS.find(([limit]) => price <= limit)[1];
export const MAIN_PRICE_N = 10;   // de hoofdprijs van een kaart: de mediaan van de zoveel goedkoopste aanbiedingen van dezelfde uitvoering
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

/** Verwachte winst op een koopje: je koopt de goedkoopste aanbieding (plus verzending als koper) en verkoopt daarna voor de
 * prijs van de tweede goedkoopste (min commissie en verpakking). Is dat bedrag niet duidelijk positief, dan is het geen koopje. */
export const DEAL_MIN_GAIN = 1;
export const dealGain = (cheapest, second, s) => second * (1 - s.fee_pct / 100) - PACKAGING - (cheapest + shipCost(cheapest));

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
    if (ch >= limit) out.push({ it, kind: "winst", chip: `▲ ${signed(ch, 0)} in 30 days` });
    else if (ch <= -limit) out.push({ it, kind: "daling", chip: `▼ ${signed(ch, 0)} in 30 days` });
  }
  return out.sort((a, b) => Math.abs(b.it.value_each / b.it.value_30d_ago - 1) - Math.abs(a.it.value_each / a.it.value_30d_ago - 1));
}

const LABELS = { g: "Positive", r: "Negative", n: "Moderate" };
const CONF_LABEL = { laag: "Low", middel: "Medium", hoog: "High" };

/** Uitleg bij de kans, opgebouwd uit dezelfde gegevens als het model. Elk punt krijgt ook een kort getal (val) en
 * een kwalitatief label (label), zodat de app dat apart en duidelijk kan tonen naast de volzin. */
export function whyBullets(f) {
  const out = [];
  if (f.mom30 != null && Math.abs(f.mom30) >= 0.03 && f.avg30) {
    out.push(f.mom30 > 0
      ? { tone: "g", head: "Price above average", text: `Now ${signed(f.mom30).replace("+", "")} above the 30-day average (${eur(f.avg30)}), so the price is already rising.`, val: signed(f.mom30, 0), label: LABELS.g }
      : { tone: "r", head: "Price below average", text: `Now ${signed(-f.mom30).replace("+", "")} below the 30-day average (${eur(f.avg30)}), so the price is already falling.`, val: signed(f.mom30, 0), label: LABELS.r });
  }
  if (f.avg7 && f.avg30) {
    const diff = f.avg7 / f.avg30 - 1;
    if (f.avg7 > f.avg30 * 1.01) out.push({ tone: "g", head: "Rise is speeding up", text: "Faster rise in the last 7 days than in the 30 before: the trend is still going.", val: signed(diff, 0), label: LABELS.g });
    else if (f.avg7 < f.avg30 * 0.99) out.push({ tone: "r", head: "Drop is speeding up", text: "Faster drop in the last 7 days than in the 30 before: the trend is still going.", val: signed(diff, 0), label: LABELS.r });
  }
  if (f.sigma && f.mode === "snel") {
    out.push({ tone: "n", head: "Volatility is assumed", text: `Too little price history yet; we assume about ${(f.sigma * 100).toFixed(0)}% per day.`, val: `±${(f.sigma * 100).toFixed(0)}%`, label: LABELS.n });
  } else if (f.sigma) {
    const pct = (f.sigma * 100).toFixed(1);
    out.push(f.sigma >= 0.05
      ? { tone: "r", head: "Price swings a lot", text: "Average daily move, so the outcome is very uncertain.", val: `±${pct}%`, label: "High" }
      : { tone: "n", head: "Price swings", text: "Average daily move, so the outcome stays uncertain.", val: `±${pct}%`, label: "Moderate" });
  }
  out.push({ tone: "i", head: "Reliability", text: f.mode === "snel"
    ? `Estimate from the 30/7/1-day averages, as there is only ${days(f.n)} of price data. More data sharpens it.`
    : `Amount of price data the estimate is based on. More data sharpens it.`, val: days(f.n), label: CONF_LABEL[f.confidence] || f.confidence.charAt(0).toUpperCase() + f.confidence.slice(1) });
  return out;
}

export const SIGNAL_TEXT = {
  koop: "High chance of a rise, low chance of a drop.",
  verkoop: "High chance of a drop, low chance of a rise.",
  afwachten: "No clear lean towards a rise or a drop.",
};

/** Signaal voor een item dat je al bezit (houden / winst nemen / verkopen overwegen). */
export function ownedSignal(f, item) {
  if (!f || f.p_up == null) return { label: "hold", text: "Too little data for advice yet." };
  if (f.p_down >= ATTN.minDown) return { label: "consider selling", text: "High chance of a drop." };
  const gain = item.value_each && item.purchase_price ? item.value_each / costEach(item) - 1 : 0;
  if (gain >= ATTN.profit && f.p_up <= ATTN.maxUp) return { label: "take profit?", text: "You're well in profit and more rise is unlikely." };
  return { label: "hold", text: f.p_up >= 0.4 ? "The outlook is positive, but extra profit isn't certain yet." : "No reason to act now." };
}

export const gradeKey = (c) => (c.grade_company ? `${c.grade_company}-${c.grade}` : "raw");
export const gradeLabel = (c) => (c.grade_company ? `${c.grade_company} ${c.grade}` : null);

// ---------------------------------------------------------------- advies (kopen / verkopen / houden / verdacht)
// De verzamelaar (collector/advice.py) beoordeelt elke dag per product of de prijs ruim boven of onder normaal staat en of echte
// verkopen dat bevestigen. Hier maken we daar per persoon een advies van, met jouw aankoopprijs en kosten erbij.
export const ADVICE = { minBuyPrice: 10, sellProfit: 0.15, buyGain: 0.10 };
export const CONTEXT_TEXT = {
  herdruk: "a new version of this card came out recently",
  "nieuwe set": "the set is still new: prices often keep falling in the first months",
  "set daalt": "the whole set is falling",
  "pokemon daalt": "all cards of this Pokémon are falling",
  "markt daalt": "the whole market is falling",
  "na een piek": "longer history shows an earlier peak and the price is now falling back",
  "set stijgt": "the whole set is rising (hype)",
  "pokemon stijgt": "all cards of this Pokémon are rising (hype)",
};
export const ADVICE_FLAG_TEXT = {
  afwijking: "the asking price is far from what the card really sells for",
  springt: "the price made several big jumps in the last 2 months",
  "weinig verkopers": "only 1 or 2 sellers list it, so the price is easy to steer",
  "aanbod verdwijnt": "listings suddenly halved in the last 2 weeks: possibly bought up",
  "te goedkoop": "the cheapest listing is suspiciously low: maybe another version, bad condition or a lure",
  "niet bevestigd": "the high price doesn't show up in real sales",
  onwaarschijnlijk: "the price would be over 3 times higher or lower than normal: the Cardmarket link is probably wrong",
  "trend wijkt af": "Cardmarket's trend price is far from what the card really costs now (the cheapest Near Mint listings); a few outliers skew it",
};

/** Wat je overhoudt als je nu koopt (met verzending) en verkoopt op de normale prijs (min commissie en verpakking), als deel van wat je betaalde. */
export const recoveryGain = (price, normal, s = DEFAULT_SETTINGS) =>
  (normal * (1 - s.fee_pct / 100) - PACKAGING - (price + shipCost(price))) / (price + shipCost(price));

/** a: rij uit v_advice (of null); owned: collectieregel (of groep) als je de kaart hebt. Geeft { label, tone, short, reasons }.
 * label: "Sell now" | "Good buy" | "Buy more" | "Hold" | "Wait" | "Caution"; tone: sell | buy | hold | warn. */
export function adviceFor(a, { owned = null, s = DEFAULT_SETTINGS } = {}) {
  const hold = owned ? "Hold" : "Wait";
  if (owned && owned.grade_company) return { label: hold, tone: "hold", short: "No advice for graded cards.", reasons: ["Advice uses Cardmarket prices of raw cards; graded cards have too few sales to make it reliable."] };
  if (!a || a.state === "onbekend" || !a.normal || !a.price) {
    return { label: hold, tone: "hold", short: "Too little price data for advice yet.", reasons: ["We need at least a few weeks of prices and a normal price to say anything."] };
  }
  const price = Number(a.price), normal = Number(a.normal), ratio = price / normal - 1;
  const basis = a.basis === "nm" ? "the median of the last 3 months" : "Cardmarket's sales average of the last month";
  const where = `Now ${eur(price)}; normal is ${eur(normal)} (${basis}), so ${ratio >= 0 ? signed(ratio) + " above" : signed(-ratio).replace("+", "") + " below"}.`;
  const sales = a.sales7 ? `Real sales last week: average ${eur(Number(a.sales7))}; sold on ${a.sale_days} of the last 14 days.` : "No sales average known for last week.";
  if (a.state === "verdacht") {
    const why = (a.flags || []).map((f) => ADVICE_FLAG_TEXT[f] || f);
    return { label: "Caution", tone: "warn", short: "The price looks steered or unreliable: no advice.",
      reasons: [where, ...why.map((w) => w.charAt(0).toUpperCase() + w.slice(1) + "."), "So we deliberately give no buy or sell advice here."] };
  }
  // achtergrondcontrole (collector/advice.py): heeft de daling of stijging een aanwijsbare reden?
  const ctx = (a.context || []).map((c) => { const [k, ...rest] = String(c).split(": "); return { k, text: (CONTEXT_TEXT[k] || k) + (rest.length ? ` (${rest.join(": ")})` : "") }; });
  const ctxDrop = a.state === "laag" ? ctx : [];
  const ctxReasons = ctx.map((c) => c.text.charAt(0).toUpperCase() + c.text.slice(1) + ".");
  if (owned) {
    const net = price * (1 - s.fee_pct / 100) - PACKAGING, cost = costEach(owned), profit = cost ? net / cost - 1 : null;
    const pText = profit == null ? "" : `Sell now and you keep about ${eur(net)} each after fees and packaging: ${signed(profit)} on what you paid (${eur(cost)}).`;
    if (a.state === "hoog" && profit != null && profit >= ADVICE.sellProfit) {
      return { label: "Sell now", tone: "sell", short: `Price is well above normal and you make ${signed(profit)} profit.`,
        reasons: [where, sales, pText, ...ctxReasons, "Prices this far above normal usually fall back."] };
    }
    if (a.state === "hoog") return { label: "Hold", tone: "hold", short: "The price is high, but too little is left after costs.", reasons: [where, sales, pText, ...ctxReasons] };
    if (a.state === "laag") {
      const gain = recoveryGain(price, normal, s);
      if (ctxDrop.length) return { label: "Hold", tone: "hold", short: `The price is low, but for a reason: ${ctxDrop[0].text}.`,
        reasons: [where, sales, pText, ...ctxReasons, "So we advise against buying more now: such drops recover less often. Selling locks in a loss."] };
      if (price >= ADVICE.minBuyPrice && gain >= ADVICE.buyGain) return { label: "Buy more", tone: "buy", short: `Temporarily ${signed(-ratio).replace("+", "")} below normal; buying more earns ${signed(gain)} if it recovers.`,
        reasons: [where, sales, pText, `Buy one more now and sell it once the price is back to normal, and you keep about ${signed(gain)} after costs.`, "No clear reason found for the drop (no reprint; the rest of the set and the market are steady). Such drops usually recover, but not always."] };
      return { label: "Hold", tone: "hold", short: "The price is temporarily low: selling now locks in a loss.", reasons: [where, sales, pText, "Prices far below normal usually recover."] };
    }
    if (Math.abs(ratio) > 0.25) return { label: "Hold", tone: "hold", short: "The price swung a lot this week: no clear picture yet.", reasons: [where, sales, pText, "We only give advice once a high or low price holds for a full week."].filter(Boolean) };
    return { label: "Hold", tone: "hold", short: "Nothing special: the price is around normal.", reasons: [where, pText].filter(Boolean) };
  }
  if (a.state === "laag" && ctxDrop.length) {
    return { label: "Wait", tone: "hold", short: `Below normal, but for a reason: ${ctxDrop[0].text}.`,
      reasons: [where, sales, ...ctxReasons, "Such drops recover on their own less often, so no buy advice."] };
  }
  if (a.state === "laag") {
    const gain = recoveryGain(price, normal, s);
    if (price >= ADVICE.minBuyPrice && gain >= ADVICE.buyGain) {
      return { label: "Good buy", tone: "buy", short: `${signed(-ratio).replace("+", "")} below normal; ${signed(gain)} profit if it recovers.`,
        reasons: [where, sales, `Buy now (about ${eur(shipCost(price))} shipping) and sell once the price is back to normal, and you keep about ${signed(gain)} after costs.`, "No clear reason found for the drop (no reprint; the rest of the set and the market are steady). Such drops usually recover, but not always."] };
    }
    return { label: "Wait", tone: "hold", short: price < ADVICE.minBuyPrice ? "Below normal, but too cheap: costs eat the profit." : "Below normal, but too little is left after costs.", reasons: [where, sales] };
  }
  if (a.state === "hoog") return { label: "Wait", tone: "hold", short: "The price is well above normal: not a good time to buy.", reasons: [where, sales] };
  if (Math.abs(ratio) > 0.25) return { label: "Wait", tone: "hold", short: "The price swung a lot this week: no clear picture yet.", reasons: [where, sales, "We only give advice once a high or low price holds for a full week."] };
  return { label: "Wait", tone: "hold", short: "Nothing special: the price is around normal.", reasons: [where] };
}

/** Zin over hoe vaak het advies klopte (advice_stats, bron 'live'), met het toeval (willekeurige gewone kaarten) ernaast. */
export function adviceTrack(stats, state) {
  const get = (k) => (stats || []).find((x) => x.source === "live" && x.state === k);
  const st = get(state), ctrl = get(state === "hoog" ? "controle_daalt" : "controle");
  if (!st || !st.n) return "Advice is checked after 30 days and compared with random cards; first results are on their way.";
  const pct = (x) => Math.round((x.hits / x.n) * 100);
  const base = `This advice was right ${st.hits} of ${st.n} times so far (${pct(st)}%)` + (ctrl && ctrl.n ? `; for random cards it was ${pct(ctrl)}%.` : ", checked after 30 days.");
  // eerlijk zijn: met genoeg uitkomsten en niet beter dan toeval, dan zeggen we dat ook
  if (ctrl && ctrl.n >= 30 && st.n >= 30 && pct(st) <= pct(ctrl)) return base + " That's no better than chance yet: take this advice with a grain of salt.";
  return base;
}

// ---------------------------------------------------------------- vooruitzicht in één oogopslag (balkje rood → groen)
const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));

/** Verwachte beweging en de kans dat die echt gebeurt, voor het balkje in de lijsten. Alleen bij een kaart die al een week
 * ruim onder (laag) of boven (hoog) zijn normale prijs staat: dan verwachten we dat hij terugkeert naar normaal.
 * move: verwachte stijging (+) of daling (−) tot de normale prijs, als fractie. chance: 0..1.
 * Zolang er geen gecontroleerde uitkomsten zijn, telt de kans hoeveel controles de kaart doorstaat (verkopen, aantal
 * verkoopdagen, eigen Near Mint-geschiedenis, geen reden voor de daling, geen waarschuwingen). Vanaf 30 uitkomsten
 * (advice_stats) vertrekt de kans van hoe vaak dit soort advies echt uitkwam, en schuiven de controles hem wat op of neer. */
export function outlook(a, stats = null) {
  if (!a || (a.state !== "laag" && a.state !== "hoog")) return null;
  const price = Number(a.price), normal = Number(a.normal);
  if (!price || !normal) return null;
  const move = normal / price - 1;
  let score = 0.5;
  score += 0.15 * clamp((Number(a.sale_days) || 0) / 14, 0, 1);                       // vaak verkocht: de prijs is echt
  const s7 = Number(a.sales7) || 0;
  if (s7 && Math.abs(s7 / price - 1) <= 0.15) score += 0.1;                             // de verkopen liggen rond de huidige prijs
  if (a.basis === "nm") score += 0.05;                                                  // normaal komt uit 90 dagen eigen geschiedenis
  score -= 0.2 * Math.min((a.context || []).length, 2);                                 // er is een reden voor de beweging
  score -= 0.1 * Math.min((a.flags || []).length, 2);                                   // kleine waarschuwingen
  if (Math.abs(move) > 0.8) score -= 0.1;                                               // heel grote afstand: herstelt zelden helemaal
  const st = (stats || []).find((x) => x.source === "live" && x.state === a.state);
  const chance = st && st.n >= 30 ? st.hits / st.n + (score - 0.5) * 0.6 : score;
  return { move, chance: clamp(chance, 0.05, 0.95) };
}

/** Prijsverandering tussen twee prijzen, als fractie (of null). */
export const change = (now, before) => (now && before ? now / before - 1 : null);
