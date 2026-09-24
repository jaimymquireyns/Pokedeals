import { isLoggedIn, rest, userId } from "../api.js";
import { addForm } from "../add.js";
import { lineChart } from "../chart.js";
import { chanceBar, gradeTag, go, kindTag, pill } from "../components.js";
import { PERIODS, SIGNAL_TEXT, breakEven, gradeKey, netGain, ownedSignal, whyBullets } from "../model.js";
import { getSettings } from "../prefs.js";
import { enablePush, pushPermission } from "../push.js";
import { addWatch, isWatched, removeWatch } from "./watchlist.js";
import { closeSheet, debounce, eur, fmtDateLong, h, icon, num, openSheet, parseMoney, pp, segment, signed, signedEur, thumb, toast, toggle } from "../ui.js";

const enc = encodeURIComponent;
const stat = (k, v, s, cls = "") => h("div", { class: "stat" }, h("div", { class: "k", text: k }), h("div", { class: "v num " + cls, text: v }), s ? h("div", { class: "s", text: s }) : null);

export async function detailView(root, pid, cid) {
  root.replaceChildren(h("p", { class: "muted pad", text: "Laden…" }));
  const s = getSettings();
  let p, c = null, fcRows = [], hist = [], al = null, nmRow = null, watchId = null, offerRows = [];
  try {
    const owned = cid ? rest.get(`v_collection?select=*&id=eq.${enc(cid)}`).then((r) => r[0] || null) : Promise.resolve(null);
    [p, c, fcRows] = await Promise.all([
      rest.get(`v_search?select=*&product_id=eq.${enc(pid)}`).then((r) => r[0]), owned,
      rest.get(`forecasts?select=*&product_id=eq.${enc(pid)}`)]);
    if (!p) throw new Error("onbekend product");
    const gk = c ? gradeKey(c) : "raw";
    hist = await rest.get(`prices?select=date,price,source&product_id=eq.${enc(pid)}&grade_key=eq.${enc(gk)}&order=date.asc&limit=1000`);
    if (gk === "raw") nmRow = (await rest.get(`prices?select=date,price&product_id=eq.${enc(pid)}&grade_key=eq.nm&order=date.desc&limit=1`).catch(() => []))[0] || null;
    if (p.kind === "card" && gk === "raw") offerRows = await rest.get(`offers?select=*&product_id=eq.${enc(pid)}&order=rank.asc`).catch(() => []);
    if (isLoggedIn()) {
      al = (await rest.get(`alerts?select=*&product_id=eq.${enc(pid)}&grade_key=eq.${enc(gk)}&limit=1`))[0] || null;
      watchId = await isWatched(pid);
    }
  } catch (e) { root.replaceChildren(h("p", { class: "err pad", text: "Kon dit product niet laden." }), h("button", { class: "linkbtn", text: "Terug", onclick: () => history.back() })); console.error(e); return; }

  const gk = c ? gradeKey(c) : "raw";
  const num2 = (x) => (x == null ? null : Number(x));
  const price = c ? num2(c.value_each) : num2(p.price);
  const graded = gk !== "raw";
  const fcByKey = new Map(fcRows.map((r) => [`${r.horizon_days}-${r.threshold_pct}`, r]));
  const toFx = (r) => r && { ...r, price: Number(r.price), p_up: Number(r.p_up), p_down: Number(r.p_down), exp: Number(r.exp_change), avg7: num2(r.avg7), avg30: num2(r.avg30), mom30: num2(r.mom30), sigma: num2(r.sigma) };
  let period = PERIODS.find((pr) => pr.horizon === s.horizon && pr.pct === s.pct) || PERIODS.find((pr) => pr.key === "30");
  let fx = toFx(fcByKey.get(`${period.horizon}-${period.pct}`));

  // ---- laagste aanbiedingen (Cardmarket, Near Mint, via PkmnPrices) ----
  let offersSec = null;
  if (p.kind === "card" && gk === "raw" && offerRows.length) {
    offersSec = h("div", { class: "sec" }, h("h3", { text: "Laagste aanbiedingen · Near Mint" }),
      ...offerRows.map((o) => h("div", { class: "offrow" },
        h("div", {}, h("div", { class: "offprice num", text: eur(Number(o.price)) }),
          h("div", { class: "offmeta", text: [o.seller, o.quantity > 1 ? `${o.quantity} stuks` : "1 stuk", o.language].filter(Boolean).join(" · ") })))),
      h("a", { class: "linkbtn", target: "_blank", rel: "noopener", text: "Alle aanbiedingen op Cardmarket →",
        href: `https://www.cardmarket.com/en/Pokemon/Products/Search?searchString=${enc([p.name, p.number || ""].join(" ").trim())}` }),
      h("p", { class: "mini", text: `Live aanbod van Cardmarket, alleen Near Mint. Bijgewerkt ${fmtDateLong(offerRows[0].date)}. Alleen beschikbaar voor je collectie en de beste kansen.` }));
  }

  // ---- kop ----
  const head = h("div", { class: "dh" }, thumb(p.image, "ph", p.kind === "sealed"),
    h("div", {}, h("h2", { text: p.name }), h("div", { class: "sub", text: [p.set_name, p.number && p.kind === "card" ? `#${p.number}` : ""].filter(Boolean).join(" · ") }),
      h("div", { class: "tags" }, kindTag(p.kind), c ? gradeTag(c) : null),
      h("div", { class: "big num", text: price ? eur(price) : "Geen prijs" })));

  // ---- identificatie: zeldzaamheid, uitgiftedatum, taal ----
  const idBits = [p.kind === "card" && p.rarity ? ["Zeldzaamheid", p.rarity] : null,
    p.release_date ? ["Uitgiftedatum", fmtDateLong(p.release_date)] : null,
    p.kind === "card" ? ["Taal", "Engels"] : null].filter(Boolean);
  const idgrid = idBits.length ? h("div", { class: "idgrid" }, ...idBits.map(([k, v]) => h("div", { class: "idbox" }, h("div", { class: "k" }, k), h("div", { class: "v" }, v)))) : null;

  // ---- cijfers ----
  let stats;
  if (c) {
    const total = price ? (price - c.purchase_price) * c.quantity : null;
    stats = h("div", { class: "stats" }, stat("Aankoop", eur(Number(c.purchase_price)), `${c.quantity > 1 ? c.quantity + "x, " : ""}${fmtDateLong(c.purchase_date)}`),
      stat("Waarde nu", price ? eur(price * c.quantity) : "–", price ? `${eur(price)} per stuk` : "prijs onbekend"),
      stat("Winst", total == null ? "–" : signedEur(total), price ? signed(price / Number(c.purchase_price) - 1, 1) : "", total != null && total < 0 ? "neg" : "pos"));
  } else {
    stats = h("div", { class: "stats" }, stat("Trendprijs", price ? eur(price) : "–", "Cardmarket-gemiddelde"), stat("Gem. 7 dagen", fx?.avg7 ? eur(fx.avg7) : "–"), stat("Gem. 30 dagen", fx?.avg30 ? eur(fx.avg30) : "–"));
  }

  // ---- winstgrens: welke verkoopprijs is nodig om quitte te spelen, na commissie en verzendkosten ----
  let breakEvenBox = null;
  if (price) {
    const costPrice = c ? Number(c.purchase_price) : price;
    const be = breakEven(costPrice, s.fee_pct);
    const fee = be * (s.fee_pct / 100);
    const ship = be - costPrice - fee > 0 ? be - costPrice - fee : 0;
    const rows = [
      [c ? "Aankoopprijs" : "Huidige prijs (als aankoopprijs)", eur(costPrice)],
      [`Cardmarket-commissie (${s.fee_pct}%)`, `+ ${eur(fee)}`],
      ["Geschatte verzendkosten", `+ ${eur(ship)}`],
    ];
    const diff = price / be - 1;
    breakEvenBox = h("div", { class: "sec" }, h("h3", { text: c ? "Winstgrens (dit exemplaar)" : "Winstgrens (bij aankoop tegen de huidige prijs)" }),
      ...rows.map(([k, v]) => h("div", { class: "berow" }, h("span", { text: k }), h("b", { text: v }))),
      h("div", { class: "beline" }),
      h("div", { class: "betotal" }, h("span", { class: "k", text: "Verkoopprijs om quitte te spelen" }), h("span", { class: "v", text: eur(be) })),
      c
        ? h("div", { class: "bestatus " + (diff >= 0 ? "good" : "bad"), text: diff >= 0
            ? `✓ Nu al ${eur(price - be)} winst (+${(diff * 100).toFixed(0)}% boven de winstgrens)`
            : `Nog ${(Math.abs(diff) * 100).toFixed(0)}% te gaan tot de winstgrens (${eur(be - price)}).` })
        : h("p", { class: "mini", text: `Koop je nu voor ${eur(price)}, dan moet de prijs eerst ${signed(be / price - 1, 1)} stijgen voor je break-even bent.` }));
  }

  // ---- laagste Near Mint-prijs (PkmnPrices) ----
  const nmBox = nmRow && !graded && price ? h("div", { class: "nmbox" },
    h("div", {}, h("div", { class: "k", text: "Near Mint vanaf" }), h("div", { class: "s", text: `Laagste aanbod, ${fmtDateLong(nmRow.date)}` })),
    h("div", { class: "r" }, h("div", { class: "v num", text: eur(Number(nmRow.price)) }), h("div", { class: "s", text: `${signed(Number(nmRow.price) / price - 1)} t.o.v. trend` }))) : null;

  // ---- kans, met een periode-kiezer (los van de standaardperiode in Instellingen) ----
  const periodBar = h("div", { class: "seg periods" });
  const chance = h("div", {});
  const why = h("div", { class: "sec" }, h("h3", { text: "Waarom deze kans?" }));

  function drawPeriods() {
    periodBar.replaceChildren(...PERIODS.map((pr) => h("button", { type: "button", "aria-pressed": String(pr.key === period.key),
      onclick: () => { period = pr; fx = toFx(fcByKey.get(`${pr.horizon}-${pr.pct}`)); drawPeriods(); drawChance(); }, text: pr.label })));
  }

  function drawChance() {
    const pct = period.pct;
    const label = period.horizon <= 30 ? `${period.horizon} dagen` : period.horizon < 365 ? `${Math.round(period.horizon / 30)} maanden` : `${Math.round(period.horizon / 365)} jaar`;
    const box = h("div", { class: "sec" }, h("h3", { text: `Kans binnen ${label}` }));
    if (fx) {
      const expUp = fx.exp_up != null ? Number(fx.exp_up) : fx.exp;
      const expDown = fx.exp_down != null ? Number(fx.exp_down) : -pct / 100;
      const net = netGain(fx.price, expUp, s);
      const sig = c ? ownedSignal(fx, c) : { label: fx.signal, text: SIGNAL_TEXT[fx.signal] };
      box.append(...[chanceBar(fx.p_up, fx.p_down),
        h("p", { class: "p14 dirs" }, h("span", { text: `daling van ${pct}% of meer` }), h("span", { text: `stijging van ${pct}% of meer` })),
        h("p", { class: "p14 outcomes" },
          h("span", { class: "u" }, h("b", { text: pp(fx.p_up) }), " kans op ", h("b", { text: `${signed(expUp, 0)} (${signedEur(fx.price * expUp)})` }), " stijging."),
          h("span", { class: "d" }, h("b", { text: pp(fx.p_down) }), " kans op ", h("b", { text: `${signed(expDown, 0)} (${signedEur(fx.price * expDown)})` }), " daling.")),
        h("p", { class: "p14" }, "Bij stijging, na verkoopkosten: ", h("b", { text: `${signed(net, 1)} (${signedEur(fx.price * net)})` }), "."),
        h("div", { class: "sigrow" }, pill(sig.label), h("span", { text: sig.text })),
        graded ? h("p", { class: "mini", text: `Let op: deze kans is berekend op de prijs van de ongegradeerde kaart. ${gk.replace("-", " ")} beweegt vaak anders.` }) : null,
        fx.basis === "nm" ? h("p", { class: "mini", text: "Gebaseerd op de eigen Near Mint-prijsgeschiedenis van deze kaart, niet op de gemengde Cardmarket-trend." }) : null].filter(Boolean));
    } else {
      box.append(h("p", { class: "p14 muted", text: period.horizon > 60
        ? "Nog niet berekend voor deze periode. Lange periodes (3-24 maanden) worden 1x per week bijgewerkt, op maandag."
        : "Nog geen kansberekening. Dat kan komen doordat er te weinig prijsdata is, of omdat de prijs onder de € 2 ligt." }));
    }
    chance.replaceChildren(box);
    why.replaceChildren(h("h3", { text: "Waarom deze kans?" }), fx ? h("ul", { class: "why" }, ...whyBullets(fx).map((b) => h("li", { class: "whyrow " + (b.tone === "g" ? "good" : b.tone === "r" ? "bad" : b.tone === "n" ? "warn" : "") },
      h("span", { class: "dot " + b.tone, text: b.tone === "g" ? "+" : b.tone === "r" ? "−" : b.tone === "n" ? "~" : "i" }),
      h("div", { class: "txt" }, h("b", { text: b.head }), h("span", { text: b.text })),
      b.val != null ? h("div", { class: "whyvalbox" }, h("div", { class: "whyval " + b.tone, text: b.val }), h("div", { class: "whytag " + b.tone, text: b.label })) : null)))
      : h("p", { class: "p14 muted", text: "Nog geen uitleg beschikbaar voor deze periode." }));
  }
  drawPeriods();
  drawChance();

  // ---- grafiek ----
  const chartSec = h("div", { class: "sec" }, h("h3", { text: c ? "Prijs sinds aankoop" : "Prijsverloop" }));
  const bySrc = {};
  for (const r of hist) (bySrc[r.source] ||= []).push(r);
  const src = (bySrc.tcgdex?.length || 0) >= 5 ? "tcgdex" : (Object.keys(bySrc).sort((a, b) => bySrc[b].length - bySrc[a].length)[0]);
  let rows = (bySrc[src] || []);
  if (c) { const from = c.purchase_date; const after = rows.filter((r) => r.date >= from); if (after.length >= 2) rows = after; }
  if (rows.length >= 2) {
    chartSec.append(lineChart({ series: [{ pts: rows.map((r) => [new Date(r.date + "T00:00:00Z").getTime(), Number(r.price)]), stroke: "var(--up)" }],
      hlines: c ? [{ y: Number(c.purchase_price), label: `Aankoop ${eur(Number(c.purchase_price))}` }] : [], label: "Prijsverloop" }));
    if (src !== "tcgdex" && p.kind === "card") chartSec.append(h("p", { class: "mini", text: "Historie van TCGplayer (omgerekend naar euro). Onze eigen Cardmarket-metingen bouwen zich op." }));
  } else chartSec.append(h("p", { class: "p14 muted", text: "Nog te weinig prijsgeschiedenis voor een grafiek." }));

  // ---- prijsmelding ----
  const alertSec = h("div", { class: "sec" });
  let alertState = al ? { id: al.id, on: al.active, min: num2(al.min_price), max: num2(al.max_price) } : { id: null, on: false, min: null, max: null };
  const saveAlert = debounce(async () => {
    const body = { min_price: alertState.min, max_price: alertState.max, active: alertState.on, armed: true };
    try {
      if (alertState.id) await rest.patch("alerts", `id=eq.${alertState.id}`, body);
      else { const r = await rest.insert("alerts", [{ user_id: userId(), product_id: pid, grade_key: gk, ...body }]); alertState.id = r[0].id; }
      toast(alertState.on ? "Prijsmelding opgeslagen" : "Prijsmelding uit");
    } catch (e) { toast("Opslaan mislukte"); console.error(e); }
  }, 500);
  const drawAlert = () => {
    if (!isLoggedIn()) {
      alertSec.replaceChildren(h("h3", { text: "Prijsmelding" }), h("p", { class: "p14 muted", text: "Log in om meldingen te krijgen als de prijs in jouw bereik komt." }),
        h("button", { class: "btn", type: "button", text: "Inloggen", onclick: () => go("#/login?next=" + enc(location.hash)) }));
      return;
    }
    const money = (key, label, ph) => h("label", { class: "amt" }, h("span", { class: "lbl2", text: label }),
      h("input", { type: "text", inputmode: "decimal", placeholder: ph, "aria-label": label, value: alertState[key] == null ? "" : String(alertState[key]).replace(".", ","),
        oninput: (e) => { alertState[key] = parseMoney(e.target.value); saveAlert(); } }));
    const tg = toggle(alertState.on, async (on) => {
      if (on) {
        if (pushPermission() !== "granted") { try { await enablePush(); } catch (e) { toast(e.message); alertState.on = false; drawAlert(); return; } }
        if (alertState.min == null && alertState.max == null && price) { alertState.min = Math.round(price * 0.8 * 100) / 100; alertState.max = Math.round(price * 0.9 * 100) / 100; }
      }
      alertState.on = on; saveAlert(); drawAlert();
    }, "Prijsmelding aan of uit");
    alertSec.replaceChildren(h("div", { class: "sech" }, h("h3", { text: "Prijsmelding" }), tg),
      alertState.on ? h("div", {}, h("p", { class: "p14", text: "Ik krijg een melding als de prijs binnen dit bereik komt:" }),
        h("div", { class: "two eq" }, money("min", "Van (€)", "bijv. 40"), money("max", "Tot (€)", "bijv. 44")),
        h("p", { class: "mini", text: "Leeg laten mag: dan geldt alleen de andere grens. Na een melding hoef je niets te resetten; hij komt pas weer als de prijs eerst uit het bereik is geweest." }))
        : h("p", { class: "p14 muted", text: "Uit. Zet aan om een melding te krijgen bij een prijs die jij wilt." }));
  };
  drawAlert();

  // ---- knoppen ----
  const btns = h("div", { class: "btns" });
  if (isLoggedIn()) {
    const watchBtn = h("button", { class: "btn" + (watchId ? " watching" : ""), type: "button" },
      icon("star", watchId ? "filled" : ""), h("span", { text: watchId ? "Wordt gevolgd" : "Volgen" }));
    watchBtn.onclick = async () => {
      watchBtn.disabled = true;
      try {
        if (watchId) { await removeWatch(watchId); watchId = null; toast("Van watchlist gehaald"); }
        else { watchId = await addWatch(pid); toast("Toegevoegd aan watchlist"); }
        watchBtn.classList.toggle("watching", Boolean(watchId));
        watchBtn.replaceChildren(icon("star", watchId ? "filled" : ""), h("span", { text: watchId ? "Wordt gevolgd" : "Volgen" }));
      } catch { toast("Aanpassen mislukte"); } finally { watchBtn.disabled = false; }
    };
    btns.append(watchBtn);
  } else {
    btns.append(h("button", { class: "btn", type: "button", text: "Volgen (log in)", onclick: () => go("#/login?next=" + enc(location.hash)) }));
  }
  const reload = () => { closeSheet(); detailView(root, pid, cid); };
  if (c) {
    btns.append(h("button", { class: "btn", type: "button", text: "Bewerken", onclick: () => openSheet(h("div", { class: "sheetin" }, h("div", { class: "handle" }), addForm({ ...p, price: c.value_each }, { editing: c, onDone: reload }))) }));
  } else {
    btns.append(h("button", { class: "btn primary", type: "button", text: "Toevoegen aan collectie", onclick: () => {
      if (!isLoggedIn()) { go("#/login?next=" + enc(location.hash)); return; }
      openSheet(h("div", { class: "sheetin" }, h("div", { class: "handle" }), addForm(p, { onDone: () => { closeSheet(); toast("Toegevoegd aan je collectie"); } })));
    } }));
  }
  btns.append(h("a", { class: "btn", target: "_blank", rel: "noopener", text: "Zoek op Cardmarket",
    href: `https://www.cardmarket.com/en/Pokemon/Products/Search?searchString=${enc([p.name, p.kind === "card" && p.number ? p.number : ""].join(" ").trim())}` }));
  if (c) btns.append(h("button", { class: "btn del", type: "button", text: "Verwijderen uit collectie", onclick: async () => {
    if (!confirm(`${p.name} uit je collectie verwijderen?`)) return;
    try { await rest.del("collection", `id=eq.${enc(cid)}`); toast("Verwijderd"); go("#/collection"); } catch { toast("Verwijderen mislukte"); }
  } }));

  root.replaceChildren(h("div", { class: "page" },
    h("div", { class: "topbar" }, h("button", { class: "back", type: "button", onclick: () => history.back() }, icon("back"), h("span", { text: "Terug" }))),
    head, idgrid, stats, nmBox,
    !c ? h("p", { class: "mini pad2", text: "De trendprijs is Cardmarkets gemiddelde voor alle talen en condities. Het goedkoopste aanbod (Near Mint) kan een stuk lager liggen, zeker bij dure kaarten met weinig verkopen." }) : null,
    graded ? h("p", { class: "mini pad2", text: "Gegradeerde prijzen komen van eBay-verkopen (dollars, omgerekend), omdat Cardmarket daar geen prijzen voor heeft." }) : null,
    periodBar, chance, why, breakEvenBox, chartSec, offersSec, alertSec, btns));
}
