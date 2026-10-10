import { isLoggedIn, rest, userId } from "../api.js";
import { addForm } from "../add.js";
import { lineChart } from "../chart.js";
import { adviceBox, arrow, cardmarketHref, chanceBar, extraTags, go, gradeTag, hasExactCm, kindTag, median, outlookBar, pill } from "../components.js";
import { PACKAGING, PERIODS, SHOW_PREDICTIONS, SIGNAL_TEXT, adviceFacts, adviceFor, adviceTrack, breakEven, change, outlook, costEach, gradeKey, marketValue, netGain, ownedSignal, shipCost, whyBullets } from "../model.js";
import { getSettings } from "../prefs.js";
import { enablePush, pushPermission } from "../push.js";
import { addWatch, isWatched, removeWatch } from "./watchlist.js";
import { closeSheet, debounce, eur, fmtDateLong, h, icon, num, openSheet, parseMoney, pp, segment, signed, signedEur, thumb, toast, toggle } from "../ui.js";

const enc = encodeURIComponent;
const stat = (k, v, s, cls = "") => h("div", { class: "stat" }, h("div", { class: "k", text: k }), h("div", { class: "v num " + cls, text: v }), s ? h("div", { class: "s", text: s }) : null);

export async function detailView(root, pid, cid) {
  root.replaceChildren(h("p", { class: "muted pad", text: "Loading…" }));
  const s = getSettings();
  let p, c = null, fcRows = [], hist = [], nmHist = [], al = null, nmRow = null, watchId = null, offerRows = [];
  // advies: los opgehaald; ontbreekt de tabel nog (schema.sql niet opnieuw gedraaid), dan gewoon zonder
  const advP = Promise.all([
    rest.get(`v_advice?select=*&product_id=eq.${enc(pid)}`).then((r) => r[0] || null),
    rest.get("advice_stats?select=*"),
  ]).catch(() => null);
  try {
    const owned = cid ? rest.get(`v_collection?select=*&id=eq.${enc(cid)}`).then((r) => r[0] || null) : Promise.resolve(null);
    [p, c, fcRows] = await Promise.all([
      rest.get(`v_search?select=*&product_id=eq.${enc(pid)}`).then((r) => r[0]), owned,
      rest.get(`forecasts?select=*&product_id=eq.${enc(pid)}`)]);
    if (!p) throw new Error("onbekend product");
    const gk = c ? gradeKey(c) : "raw";
    hist = await rest.get(`prices?select=date,price,source&product_id=eq.${enc(pid)}&grade_key=eq.${enc(gk)}&order=date.asc&limit=1000`);
    if (gk === "raw") {
      nmRow = (await rest.get(`prices?select=date,price&product_id=eq.${enc(pid)}&grade_key=eq.nm&order=date.desc&limit=1`).catch(() => []))[0] || null;
      nmHist = await rest.get(`prices?select=date,price,source&product_id=eq.${enc(pid)}&grade_key=eq.nm&order=date.asc&limit=1000`).catch(() => []);
    }
    if (p.kind === "card" && gk === "raw") offerRows = await rest.get(`offers?select=*&product_id=eq.${enc(pid)}&order=rank.asc`).catch(() => []);
    if (isLoggedIn()) {
      al = (await rest.get(`alerts?select=*&product_id=eq.${enc(pid)}&grade_key=eq.${enc(gk)}&limit=1`))[0] || null;
      watchId = await isWatched(pid);
    }
  } catch (e) { root.replaceChildren(h("p", { class: "err pad", text: "Couldn't load this product." }), h("button", { class: "linkbtn", text: "Back", onclick: () => history.back() })); console.error(e); return; }

  const gk = c ? gradeKey(c) : "raw";
  const num2 = (x) => (x == null ? null : Number(x));
  const trendPrice = c ? num2(c.value_trend ?? c.value_each) : num2(p.price);
  // Waarde ("Value now", winst en winstgrens): het gemiddelde van de 10 goedkoopste Engelse aanbiedingen van dezelfde uitvoering,
  // elke verkoper één keer en zonder je eigen aanbiedingen (model.marketValue, zelfde regel als v_market). De trendprijs schiet
  // soms weken omhoog door een paar dure verkopen; wat een kaart echt opbrengt zie je beter aan de aanbiedingen.
  const mv = c && (c.language || c.grade_company) ? null : marketValue(offerRows, s.cm_name);
  const refVariant = mv ? mv.variant : null;
  const refOffers = mv ? mv.ref : [];
  const offerAvg = mv ? mv.value : null;
  const enOffers = offerRows.filter((o) => (o.language || "EN") === "EN").sort((a, b) => Number(a.price) - Number(b.price));
  const lowestOffer = enOffers.length ? Number(enOffers[0].price) : null;
  const price = offerAvg ?? trendPrice;
  const graded = gk !== "raw";
  const fcByKey = new Map(fcRows.map((r) => [`${r.horizon_days}-${r.threshold_pct}`, r]));
  const toFx = (r) => r && { ...r, price: Number(r.price), p_up: Number(r.p_up), p_down: Number(r.p_down), exp: Number(r.exp_change), avg7: num2(r.avg7), avg30: num2(r.avg30), mom30: num2(r.mom30), sigma: num2(r.sigma) };
  let period = PERIODS.find((pr) => pr.horizon === s.horizon && pr.pct === s.pct) || PERIODS.find((pr) => pr.key === "30");
  let fx = toFx(fcByKey.get(`${period.horizon}-${period.pct}`));

  // ---- laagste aanbiedingen (Cardmarket, Near Mint, via PkmnPrices) ----
  let offersSec = null;
  if (p.kind === "card" && gk === "raw" && offerRows.length) {
    const offRow = (o) => h("div", { class: "offrow" },
        h("div", {}, h("div", { class: "offprice num", text: eur(Number(o.price)) }),
          h("div", { class: "offmeta", text: [o.seller, o.quantity > 1 ? `${o.quantity} pcs` : "1 pc", o.language, o.variant && o.variant !== "Normal" ? o.variant : null].filter(Boolean).join(" · ") })));
    const OFF_SHOWN = 8;
    const more = h("div", { hidden: true }, ...offerRows.slice(OFF_SHOWN).map(offRow));
    offersSec = h("div", { class: "sec" }, h("h3", { text: "Lowest listings · Near Mint" }),
      ...offerRows.slice(0, OFF_SHOWN).map(offRow), more,
      offerRows.length > OFF_SHOWN ? h("button", { class: "linkbtn", type: "button", text: `Show all ${offerRows.length} listings`, onclick: (e) => { more.hidden = !more.hidden; e.target.textContent = more.hidden ? `Show all ${offerRows.length} listings` : "Show less"; } }) : null,
      h("a", { class: "linkbtn", target: "_blank", rel: "noopener", text: hasExactCm(p) ? "All listings on Cardmarket →" : "Search on Cardmarket →", href: cardmarketHref(p) }),
      h("p", { class: "mini", text: `Updated ${fmtDateLong(offerRows[0].date)}.` }));
  }

  // ---- wat de prijs de laatste 30 dagen deed (pijl) en het vooruitzicht (balkje), naast de prijs ----
  const mainSeries = () => {
    if (nmHist.length >= 10) return { rows: nmHist, nm: true };
    const bySrc = {};
    for (const r of hist) (bySrc[r.source] ||= []).push(r);
    const src = (bySrc.tcgdex?.length || 0) >= 5 ? "tcgdex" : (Object.keys(bySrc).sort((a, b) => bySrc[b].length - bySrc[a].length)[0]);
    return { rows: bySrc[src] || [], nm: false, src };
  };
  const ch30 = (() => {
    if (c && c.value_30d_ago != null && c.value_trend != null) return change(Number(c.value_trend), Number(c.value_30d_ago));   // zelfde pijl als in je collectie
    const { rows } = mainSeries();
    if (rows.length < 2) return null;
    const last = rows[rows.length - 1], cut = new Date(new Date(last.date + "T00:00:00Z").getTime() - 30 * 864e5).toISOString().slice(0, 10);
    const old = [...rows].reverse().find((x) => x.date <= cut);
    return old ? change(Number(last.price), Number(old.price)) : null;
  })();
  const moveSlot = h("span", { class: "mvd" }, ch30 != null ? h("span", { class: "mvl" }, arrow(ch30), h("small", { text: "30d" })) : null);

  // ---- kop ----
  const head = h("div", { class: "dh" }, thumb(p.image, "ph", p.kind === "sealed", p.kind === "sealed" ? "" : [p.name, p.number ? "#" + p.number : ""].filter(Boolean).join(" ")),
    h("div", {}, h("h2", { text: p.name }), h("div", { class: "sub", text: [p.set_name, p.number && p.kind === "card" ? `#${p.number}` : ""].filter(Boolean).join(" · ") }),
      h("div", { class: "tags" }, kindTag(p.kind), c ? gradeTag(c) : null, c ? extraTags(c) : null),
      h("div", { class: "bigrow" }, h("span", { class: "big num", text: price ? eur(price) : "No price" }), moveSlot),
      lowestOffer != null ? h("p", { class: "mini", text: `For sale from ${eur(lowestOffer)}${refVariant && refVariant !== "Normal" ? ` (${refVariant})` : ""} · trend price ${eur(trendPrice)}` }) : null,
      lowestOffer != null && offerAvg == null ? h("p", { class: "mini warn", text: `Only ${enOffers.length} ${enOffers.length === 1 ? "listing" : "listings"}: too few for a reliable value, so this is the trend price.` }) : null));

  // ---- identificatie: zeldzaamheid, uitgiftedatum, taal ----
  const idBits = [p.kind === "card" && p.rarity ? ["Rarity", p.rarity] : null,
    p.release_date ? ["Release date", fmtDateLong(p.release_date)] : null,
    p.kind === "card" ? ["Language", "English"] : null].filter(Boolean);
  const idgrid = idBits.length ? h("div", { class: "idgrid" }, ...idBits.map(([k, v]) => h("div", { class: "idbox" }, h("div", { class: "k" }, k), h("div", { class: "v" }, v)))) : null;

  // ---- cijfers ----
  let stats;
  if (c) {
    const cost = costEach(c);
    const total = price ? (price - cost) * c.quantity : null;
    const extraEach = (Number(c.purchase_shipping || 0) + Number(c.purchase_costs || 0)) / c.quantity;
    const shipNote = extraEach > 0 ? `incl. ${eur(extraEach)} shipping/costs, ` : "";
    stats = h("div", { class: "stats" }, stat("Purchase", eur(cost), `${shipNote}${c.quantity > 1 ? c.quantity + "x, " : ""}${fmtDateLong(c.purchase_date)}`),
      stat("Value now", price ? eur(price * c.quantity) : "–", price ? `${eur(price)} each` : "price unknown"),
      stat("Profit", total == null ? "–" : signedEur(total), price ? signed(price / cost - 1, 1) : "", total != null && total < 0 ? "neg" : "pos"));
  } else {
    stats = h("div", { class: "stats" }, stat("Trend price", trendPrice ? eur(trendPrice) : "–", "Cardmarket average"), stat("7-day avg", fx?.avg7 ? eur(fx.avg7) : "–"), stat("30-day avg", fx?.avg30 ? eur(fx.avg30) : "–"));
  }

  // ---- winstgrens: welke verkoopprijs is nodig om quitte te spelen ----
  // De verzending bij verkopen betaalt de koper; wat telt is de verzending die jij bij het kopen betaalde.
  let breakEvenBox = null;
  if (price) {
    const cardPrice = c ? Number(c.purchase_price) : price;
    const buyShip = c ? (Number(c.purchase_shipping || 0) + Number(c.purchase_costs || 0)) / Math.max(c.quantity, 1) : shipCost(price);
    const be = breakEven(cardPrice, s.fee_pct, buyShip);
    const fee = be * (s.fee_pct / 100);
    const rows = [
      [c ? "Purchase price" : "Current price (as purchase)", eur(cardPrice)],
      [c ? "Shipping and costs at purchase" : "Est. shipping at purchase", `+ ${eur(buyShip)}`],
      [`Cardmarket fee (${s.fee_pct}%)`, `+ ${eur(fee)}`],
      ["Packaging", `+ ${eur(PACKAGING)}`],
    ];
    const diff = price / be - 1;
    breakEvenBox = h("div", { class: "sec" }, h("h3", { text: c ? "Break-even (this copy)" : "Break-even (buying at current price)" }),
      ...rows.map(([k, v]) => h("div", { class: "berow" }, h("span", { text: k }), h("b", { text: v }))),
      h("div", { class: "beline" }),
      h("div", { class: "betotal" }, h("span", { class: "k", text: "Sale price to break even" }), h("span", { class: "v", text: eur(be) })),
      h("p", { class: "mini", text: "On Cardmarket the buyer pays shipping when you sell, so it's not included." }),
      c
        ? h("div", { class: "bestatus " + (diff >= 0 ? "good" : "bad"), text: diff >= 0
            ? `✓ Already ${eur(price - be)} profit (+${(diff * 100).toFixed(0)}% above break-even)`
            : `${(Math.abs(diff) * 100).toFixed(0)}% to go to break-even (${eur(be - price)}).` })
        : h("p", { class: "mini", text: `Buying now at ${eur(price)}, the price must rise ${signed(be / price - 1, 1)} to break even.` }));
  }

  // ---- laagste Near Mint-prijs (PkmnPrices) ----
  const nmBox = nmRow && !graded && price ? h("a", { class: "nmbox", target: "_blank", rel: "noopener", href: cardmarketHref(p, { nearMint: true }), "aria-label": "View Near Mint listings on Cardmarket" },
    h("div", {}, h("div", { class: "k", text: "Near Mint from" }), h("div", { class: "s", text: `Lowest listing, ${fmtDateLong(nmRow.date)} · tap for Cardmarket` })),
    h("div", { class: "r" }, h("div", { class: "v num", text: eur(Number(nmRow.price)) }), h("div", { class: "s", text: `${signed(Number(nmRow.price) / price - 1)} vs. trend` }))) : null;

  // ---- kans, met een periode-kiezer (los van de standaardperiode in Instellingen) ----
  const periodBar = h("div", { class: "seg periods" });
  const chance = h("div", { class: "chancesec" });
  const why = h("div", { class: "sec" }, h("h3", { text: "Why this chance?" }));

  function drawPeriods() {
    periodBar.replaceChildren(...PERIODS.map((pr) => h("button", { type: "button", "aria-pressed": String(pr.key === period.key),
      onclick: () => { period = pr; fx = toFx(fcByKey.get(`${pr.horizon}-${pr.pct}`)); drawPeriods(); drawChart(); drawChance(); }, text: pr.label })));
  }

  function drawChance() {
    const pct = period.pct;
    const label = period.horizon <= 30 ? `${period.horizon} days` : period.horizon < 365 ? `${Math.round(period.horizon / 30)} months` : `${Math.round(period.horizon / 365)} years`;
    const box = h("div", { class: "sec" }, h("h3", { text: `Chance within ${label}` }));
    if (fx) {
      const expUp = fx.exp_up != null ? Number(fx.exp_up) : fx.exp;
      const expDown = fx.exp_down != null ? Number(fx.exp_down) : -pct / 100;
      const net = netGain(fx.price, expUp, s);
      const sig = c ? ownedSignal(fx, c) : { label: fx.signal, text: SIGNAL_TEXT[fx.signal] };
      box.append(...[chanceBar(fx.p_up, fx.p_down),
        h("p", { class: "p14 dirs" }, h("span", { text: `drop of ${pct}%+` }), h("span", { text: `rise of ${pct}%+` })),
        h("p", { class: "p14 outcomes" },
          h("span", { class: "u" }, h("b", { text: pp(fx.p_up) }), " chance of ", h("b", { text: `${signed(expUp, 0)} (${signedEur(fx.price * expUp)})` }), " rise."),
          h("span", { class: "d" }, h("b", { text: pp(fx.p_down) }), " chance of ", h("b", { text: `${signed(expDown, 0)} (${signedEur(fx.price * expDown)})` }), " drop.")),
        h("p", { class: "p14" }, "If it rises, after selling costs: ", h("b", { text: `${signed(net, 1)} (${signedEur(fx.price * net)})` }), "."),
        h("div", { class: "sigrow" }, pill(sig.label), h("span", { text: sig.text })),
        graded ? h("p", { class: "mini", text: `Note: this chance is based on the ungraded card. ${gk.replace("-", " ")} often moves differently.` }) : null,
        fx.basis === "nm" ? h("p", { class: "mini", text: "Based on this card's own Near Mint price history, not the mixed Cardmarket trend." }) : null].filter(Boolean));
    } else {
      box.append(h("p", { class: "p14 muted", text: period.horizon > 60
        ? "Not calculated for this period yet. Long periods (3-24 months) update weekly, on Mondays."
        : "No chance estimate yet: too little price data, or the price is under €2." }));
    }
    chance.replaceChildren(box);
    why.replaceChildren(h("h3", { text: "Why this chance?" }), fx ? h("ul", { class: "why" }, ...whyBullets(fx).map((b) => h("li", { class: "whyrow " + (b.tone === "g" ? "good" : b.tone === "r" ? "bad" : b.tone === "n" ? "warn" : "") },
      h("span", { class: "dot " + b.tone, text: b.tone === "g" ? "+" : b.tone === "r" ? "−" : b.tone === "n" ? "~" : "i" }),
      h("div", { class: "txt" }, h("b", { text: b.head }), h("span", { text: b.text })),
      b.val != null ? h("div", { class: "whyvalbox" }, h("div", { class: "whyval " + b.tone, text: b.val }), h("div", { class: "whytag " + b.tone, text: b.label })) : null)))
      : h("p", { class: "p14 muted", text: "No explanation for this period yet." }));
  }
  drawPeriods();
  drawChance();

  // ---- grafiek; volgt dezelfde periode als de periodeknoppen hierboven ----
  let usual = null;   // { y, nm }: gezet zodra het advies binnen is
  const chartSec = h("div", { class: "sec" }, h("h3", { text: "Price history" }));
  function drawChart() {
    chartSec.replaceChildren(h("h3", { text: "Price history" }));
    const ms = mainSeries(), useNm = ms.nm, allRows = ms.rows, src = ms.nm ? "pkmnprices" : ms.src;
    let rows = allRows;
    if (allRows.length) {
      const last = new Date(allRows[allRows.length - 1].date + "T00:00:00Z").getTime();
      const cutoff = last - period.horizon * 864e5;
      rows = allRows.filter((r) => new Date(r.date + "T00:00:00Z").getTime() >= cutoff);
    }
    if (rows.length >= 2) {
      chartSec.append(lineChart({ series: [{ pts: rows.map((r) => [new Date(r.date + "T00:00:00Z").getTime(), Number(r.price)]), stroke: "var(--up)" }],
        hlines: [...(c ? [{ y: Number(c.purchase_price), label: `Purchase ${eur(Number(c.purchase_price))}` }] : []),
          // 'Usually': de normale prijs uit het advies, alleen als hij over dezelfde reeks gaat als de grafiek (Near Mint of trend)
          ...(usual && usual.nm === useNm ? [{ y: usual.y, label: `Usually ${eur(usual.y)}`, color: "var(--amber)", dash: "2 4", side: "left" }] : [])],
        label: "Price history" }));
      if (!useNm && src !== "tcgdex" && p.kind === "card") chartSec.append(h("p", { class: "mini", text: "TCGplayer prices, converted to euro." }));
    } else chartSec.append(h("p", { class: "p14 muted", text: "Not enough price history for a chart in this period." }));
  }
  drawChart();

  // ---- prijsmelding ----
  const alertSec = h("div", { class: "sec" });
  let alertState = al ? { id: al.id, on: al.active, min: num2(al.min_price), max: num2(al.max_price) } : { id: null, on: false, min: null, max: null };
  const saveAlert = debounce(async () => {
    const body = { min_price: alertState.min, max_price: alertState.max, active: alertState.on, armed: true };
    try {
      if (alertState.id) await rest.patch("alerts", `id=eq.${alertState.id}`, body);
      else { const r = await rest.insert("alerts", [{ user_id: userId(), product_id: pid, grade_key: gk, ...body }]); alertState.id = r[0].id; }
      toast(alertState.on ? "Price alert saved" : "Price alert off");
    } catch (e) { toast("Couldn't save"); console.error(e); }
  }, 500);
  const drawAlert = () => {
    if (!isLoggedIn()) {
      alertSec.replaceChildren(h("h3", { text: "Price alert" }), h("p", { class: "p14 muted", text: "Log in to get alerts when the price hits your range." }),
        h("button", { class: "btn", type: "button", text: "Log in", onclick: () => go("#/login?next=" + enc(location.hash)) }));
      return;
    }
    const money = (key, label, ph) => h("label", { class: "amt" }, h("span", { class: "lbl2", text: label }),
      h("input", { type: "text", inputmode: "decimal", placeholder: ph, "aria-label": label, value: alertState[key] == null ? "" : String(alertState[key]),
        oninput: (e) => { alertState[key] = parseMoney(e.target.value); saveAlert(); } }));
    const tg = toggle(alertState.on, async (on) => {
      if (on) {
        if (pushPermission() !== "granted") { try { await enablePush(); } catch (e) { toast(e.message); alertState.on = false; drawAlert(); return; } }
        if (alertState.min == null && alertState.max == null && price) { alertState.min = Math.round(price * 0.8 * 100) / 100; alertState.max = Math.round(price * 0.9 * 100) / 100; }
      }
      alertState.on = on; saveAlert(); drawAlert();
    }, "Price alert on or off");
    alertSec.replaceChildren(h("div", { class: "sech" }, h("h3", { text: "Price alert" }), tg),
      alertState.on ? h("div", {}, h("p", { class: "p14", text: "Alert me when the price is in this range:" }),
        h("div", { class: "two eq" }, money("min", "From (€)", "e.g. 40"), money("max", "To (€)", "e.g. 44")),
        h("p", { class: "mini", text: "Leave one empty to use only the other limit. No reset needed: after an alert, the next comes once the price has left the range." }))
        : h("p", { class: "p14 muted", text: "Off. Turn on to get alerted at a price you want." }));
  };
  drawAlert();

  // ---- advies ----
  const advRes = await advP;
  const adv = advRes ? adviceFor(advRes[0], { owned: c, s }) : null;
  const olk = advRes && !graded ? outlook(advRes[0], advRes[1]) : null;
  if (advRes?.[0]?.normal && !graded && advRes[0].state !== "onbekend") { usual = { y: Number(advRes[0].normal), nm: advRes[0].basis === "nm" }; drawChart(); }
  if (olk) moveSlot.append(outlookBar(olk));
  const advSec = adv ? adviceBox(adv, adviceTrack(advRes[1], advRes[0]?.state === "hoog" ? "hoog" : "laag"), graded ? [] : adviceFacts(advRes[0], { owned: c, s })) : null;

  // ---- knoppen ----
  const btns = h("div", { class: "btns" });
  if (isLoggedIn()) {
    const watchBtn = h("button", { class: "btn" + (watchId ? " watching" : ""), type: "button" },
      icon("star", watchId ? "filled" : ""), h("span", { text: watchId ? "Watching" : "Watch" }));
    watchBtn.onclick = async () => {
      watchBtn.disabled = true;
      try {
        if (watchId) { await removeWatch(watchId); watchId = null; toast("Removed from watchlist"); }
        else { watchId = await addWatch(pid); toast("Added to watchlist"); }
        watchBtn.classList.toggle("watching", Boolean(watchId));
        watchBtn.replaceChildren(icon("star", watchId ? "filled" : ""), h("span", { text: watchId ? "Watching" : "Watch" }));
      } catch { toast("Couldn't update"); } finally { watchBtn.disabled = false; }
    };
    btns.append(watchBtn);
  } else {
    btns.append(h("button", { class: "btn", type: "button", text: "Watch (log in)", onclick: () => go("#/login?next=" + enc(location.hash)) }));
  }
  const reload = () => { closeSheet(); detailView(root, pid, cid); };
  if (c) {
    btns.append(h("button", { class: "btn", type: "button", text: "Edit", onclick: () => openSheet(h("div", { class: "sheetin" }, h("div", { class: "handle" }), addForm({ ...p, price: c.value_each }, { editing: c, onDone: reload }))) }));
  } else {
    btns.append(h("button", { class: "btn primary", type: "button", text: "Add to collection", onclick: () => {
      if (!isLoggedIn()) { go("#/login?next=" + enc(location.hash)); return; }
      openSheet(h("div", { class: "sheetin" }, h("div", { class: "handle" }), addForm(p, { onDone: () => { closeSheet(); toast("Added to collection"); } })));
    } }));
  }
  btns.append(h("a", { class: "btn", target: "_blank", rel: "noopener", text: hasExactCm(p) ? "Open on Cardmarket" : "Search on Cardmarket", href: cardmarketHref(p) }));
  if (c) btns.append(h("button", { class: "btn del", type: "button", text: "Remove from collection", onclick: async () => {
    if (!confirm(`Remove ${p.name} from your collection?`)) return;
    try { await rest.del("collection", `id=eq.${enc(cid)}`); toast("Removed"); go("#/collection"); } catch { toast("Couldn't remove"); }
  } }));

  root.replaceChildren(h("div", { class: "page" },
    h("div", { class: "topbar" }, h("button", { class: "back", type: "button", onclick: () => history.back() }, icon("back"), h("span", { text: "Back" }))),
    head, advSec, idgrid, stats, nmBox,
    graded ? h("p", { class: "mini pad2", text: "eBay sale prices, converted to euro." }) : null,
    periodBar, chartSec, SHOW_PREDICTIONS ? chance : null, SHOW_PREDICTIONS ? why : null, breakEvenBox, offersSec, alertSec, btns));
}
