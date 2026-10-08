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

// ---------------------------------------------------------------- advies (kopen / verkopen / houden / verdacht)
// De verzamelaar (collector/advice.py) beoordeelt elke dag per product of de prijs ruim boven of onder normaal staat en of echte
// verkopen dat bevestigen. Hier maken we daar per persoon een advies van, met jouw aankoopprijs en kosten erbij.
export const ADVICE = { minBuyPrice: 10, sellProfit: 0.15, buyGain: 0.10 };
export const CONTEXT_TEXT = {
  herdruk: "er kwam onlangs een nieuwe versie van deze kaart uit",
  "nieuwe set": "de set is nog nieuw: prijzen zakken de eerste maanden vaak verder",
  "set daalt": "de hele set daalt",
  "pokemon daalt": "alle kaarten van deze Pokémon dalen",
  "markt daalt": "de hele markt daalt",
  "na een piek": "de langere geschiedenis laat zien dat de prijs eerder een piek had en nu terugzakt",
  "set stijgt": "de hele set stijgt (hype)",
  "pokemon stijgt": "alle kaarten van deze Pokémon stijgen (hype)",
};
export const ADVICE_FLAG_TEXT = {
  afwijking: "de vraagprijs wijkt sterk af van waarvoor de kaart echt verkocht wordt",
  springt: "de prijs maakte de laatste 2 maanden meerdere grote sprongen",
  "weinig verkopers": "maar 1 of 2 verkopers bieden hem aan, dus de prijs is makkelijk te sturen",
  "aanbod verdwijnt": "het aanbod is de laatste 2 weken plots gehalveerd: mogelijk opgekocht",
  "te goedkoop": "de goedkoopste aanbieding is verdacht laag: mogelijk een andere versie, slechte staat of een lokvogel",
  "niet bevestigd": "de hoge prijs komt niet terug in de echte verkopen",
  onwaarschijnlijk: "de prijs zou meer dan 3 keer zo hoog of laag zijn als normaal: waarschijnlijk klopt de koppeling met Cardmarket niet",
  "trend wijkt af": "Cardmarkets trendprijs ligt ver van wat de kaart nu echt kost (de goedkoopste Near Mint-aanbiedingen); een paar uitschieters trekken hem scheef",
};

/** Wat je overhoudt als je nu koopt (met verzending) en verkoopt op de normale prijs (min commissie en verpakking), als deel van wat je betaalde. */
export const recoveryGain = (price, normal, s = DEFAULT_SETTINGS) =>
  (normal * (1 - s.fee_pct / 100) - PACKAGING - (price + shipCost(price))) / (price + shipCost(price));

/** a: rij uit v_advice (of null); owned: collectieregel (of groep) als je de kaart hebt. Geeft { label, tone, short, reasons }.
 * label: "Nu verkopen" | "Goede koop" | "Bijkopen" | "Bewaren" | "Afwachten" | "Let op"; tone: sell | buy | hold | warn. */
export function adviceFor(a, { owned = null, s = DEFAULT_SETTINGS } = {}) {
  const hold = owned ? "Bewaren" : "Afwachten";
  if (owned && owned.grade_company) return { label: hold, tone: "hold", short: "Geen advies voor gegradeerde kaarten.", reasons: ["Het advies kijkt naar Cardmarket-prijzen van gewone kaarten; voor gegradeerde kaarten zijn er te weinig verkopen om het betrouwbaar te maken."] };
  if (!a || a.state === "onbekend" || !a.normal || !a.price) {
    return { label: hold, tone: "hold", short: "Nog te weinig prijsgegevens voor een advies.", reasons: ["We hebben minstens een paar weken prijzen en een normale prijs nodig om iets te zeggen."] };
  }
  const price = Number(a.price), normal = Number(a.normal), ratio = price / normal - 1;
  const basis = a.basis === "nm" ? "de mediaan van de laatste 3 maanden" : "Cardmarkets verkoopgemiddelde van de afgelopen maand";
  const where = `Nu ${eur(price)}; normaal is ${eur(normal)} (${basis}), dus ${ratio >= 0 ? signed(ratio) + " erboven" : signed(-ratio).replace("+", "") + " eronder"}.`;
  const sales = a.sales7 ? `Echte verkopen de laatste week: gemiddeld ${eur(Number(a.sales7))}; op ${a.sale_days} van de laatste 14 dagen verkocht.` : "De laatste week geen verkoopgemiddelde bekend.";
  if (a.state === "verdacht") {
    const why = (a.flags || []).map((f) => ADVICE_FLAG_TEXT[f] || f);
    return { label: "Let op", tone: "warn", short: "De prijs lijkt gestuurd of onbetrouwbaar: geen advies.",
      reasons: [where, ...why.map((w) => w.charAt(0).toUpperCase() + w.slice(1) + "."), "Daarom geven we hier bewust geen kopen- of verkopenadvies."] };
  }
  // achtergrondcontrole (collector/advice.py): heeft de daling of stijging een aanwijsbare reden?
  const ctx = (a.context || []).map((c) => { const [k, ...rest] = String(c).split(": "); return { k, text: (CONTEXT_TEXT[k] || k) + (rest.length ? ` (${rest.join(": ")})` : "") }; });
  const ctxDrop = a.state === "laag" ? ctx : [];
  const ctxReasons = ctx.map((c) => c.text.charAt(0).toUpperCase() + c.text.slice(1) + ".");
  if (owned) {
    const net = price * (1 - s.fee_pct / 100) - PACKAGING, cost = costEach(owned), profit = cost ? net / cost - 1 : null;
    const pText = profit == null ? "" : `Verkoop je nu, dan hou je na commissie en verpakking ongeveer ${eur(net)} per stuk over: ${signed(profit)} op wat je betaalde (${eur(cost)}).`;
    if (a.state === "hoog" && profit != null && profit >= ADVICE.sellProfit) {
      return { label: "Nu verkopen", tone: "sell", short: `Prijs staat ruim boven normaal en je maakt ${signed(profit)} winst.`,
        reasons: [where, sales, pText, ...ctxReasons, "Prijzen die zo ver boven normaal staan, zakken meestal weer terug."] };
    }
    if (a.state === "hoog") return { label: "Bewaren", tone: "hold", short: "De prijs is hoog, maar na kosten hou je nog te weinig over.", reasons: [where, sales, pText, ...ctxReasons] };
    if (a.state === "laag") {
      const gain = recoveryGain(price, normal, s);
      if (ctxDrop.length) return { label: "Bewaren", tone: "hold", short: `De prijs staat laag, maar daar is een reden voor: ${ctxDrop[0].text}.`,
        reasons: [where, sales, pText, ...ctxReasons, "Daarom raden we bijkopen nu af: zo'n daling herstelt minder vaak vanzelf. Verkopen zet wel verlies vast."] };
      if (price >= ADVICE.minBuyPrice && gain >= ADVICE.buyGain) return { label: "Bijkopen", tone: "buy", short: `Tijdelijk ${signed(-ratio).replace("+", "")} onder normaal; bijkopen levert ${signed(gain)} op als hij herstelt.`,
        reasons: [where, sales, pText, `Koop je er nu één bij en verkoop je die als de prijs terug op normaal staat, dan hou je na kosten ongeveer ${signed(gain)} over.`, "Geen aanwijsbare reden voor de daling gevonden (geen herdruk, de rest van de set en de markt staan gewoon). Zulke dalingen herstellen meestal, maar niet altijd."] };
      return { label: "Bewaren", tone: "hold", short: "De prijs staat tijdelijk laag: nu verkopen zet verlies vast.", reasons: [where, sales, pText, "Prijzen die ver onder normaal staan, herstellen meestal."] };
    }
    if (Math.abs(ratio) > 0.25) return { label: "Bewaren", tone: "hold", short: "De prijs schommelt sterk de laatste week: nog geen duidelijk beeld.", reasons: [where, sales, pText, "We geven pas een advies als een hoge of lage prijs een hele week aanhoudt."].filter(Boolean) };
    return { label: "Bewaren", tone: "hold", short: "Niets bijzonders: de prijs staat rond normaal.", reasons: [where, pText].filter(Boolean) };
  }
  if (a.state === "laag" && ctxDrop.length) {
    return { label: "Afwachten", tone: "hold", short: `Onder normaal, maar met een reden: ${ctxDrop[0].text}.`,
      reasons: [where, sales, ...ctxReasons, "Zo'n daling herstelt minder vaak vanzelf, dus geen koopadvies."] };
  }
  if (a.state === "laag") {
    const gain = recoveryGain(price, normal, s);
    if (price >= ADVICE.minBuyPrice && gain >= ADVICE.buyGain) {
      return { label: "Goede koop", tone: "buy", short: `${signed(-ratio).replace("+", "")} onder normaal; ${signed(gain)} winst als hij herstelt.`,
        reasons: [where, sales, `Koop je nu (met ongeveer ${eur(shipCost(price))} verzending) en verkoop je als de prijs terug op normaal staat, dan hou je na kosten ongeveer ${signed(gain)} over.`, "Geen aanwijsbare reden voor de daling gevonden (geen herdruk, de rest van de set en de markt staan gewoon). Zulke dalingen herstellen meestal, maar niet altijd."] };
    }
    return { label: "Afwachten", tone: "hold", short: price < ADVICE.minBuyPrice ? "Onder normaal, maar te goedkoop: de kosten eten de winst op." : "Onder normaal, maar na kosten blijft er te weinig over.", reasons: [where, sales] };
  }
  if (a.state === "hoog") return { label: "Afwachten", tone: "hold", short: "De prijs staat nu ruim boven normaal: geen goed moment om te kopen.", reasons: [where, sales] };
  if (Math.abs(ratio) > 0.25) return { label: "Afwachten", tone: "hold", short: "De prijs schommelt sterk de laatste week: nog geen duidelijk beeld.", reasons: [where, sales, "We geven pas een advies als een hoge of lage prijs een hele week aanhoudt."] };
  return { label: "Afwachten", tone: "hold", short: "Niets bijzonders: de prijs staat rond normaal.", reasons: [where] };
}

/** Zin over hoe vaak het advies klopte (advice_stats, bron 'live'), met het toeval (willekeurige gewone kaarten) ernaast. */
export function adviceTrack(stats, state) {
  const get = (k) => (stats || []).find((x) => x.source === "live" && x.state === k);
  const st = get(state), ctrl = get(state === "hoog" ? "controle_daalt" : "controle");
  if (!st || !st.n) return "Elk advies wordt na 30 dagen gecontroleerd en vergeleken met willekeurige kaarten; de eerste uitkomsten komen er nog aan.";
  const pct = (x) => Math.round((x.hits / x.n) * 100);
  const base = `Dit advies klopte tot nu toe ${st.hits} van ${st.n} keer (${pct(st)}%)` + (ctrl && ctrl.n ? `; bij willekeurige kaarten was dat ${pct(ctrl)}%.` : ", gecontroleerd na 30 dagen.");
  // eerlijk zijn: met genoeg uitkomsten en niet beter dan toeval, dan zeggen we dat ook
  if (ctrl && ctrl.n >= 30 && st.n >= 30 && pct(st) <= pct(ctrl)) return base + " Dat is nog niet beter dan toeval: neem dit advies met een korrel zout.";
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
