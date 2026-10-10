import { getSession, rest } from "../api.js";
import { brandmark, detailHash, emptyNote, go, moveCell, note, oppRow } from "../components.js";
import { DEAL_MIN_GAIN, SHOW_PREDICTIONS, adviceFor, adviceTrack, dealGain, isOpportunity, netGain, outlook, recoveryGain, shipCost } from "../model.js";
import { addWatch, isWatched, removeWatch } from "./watchlist.js";
import { getSettings } from "../prefs.js";
import { closeSheet, eur, fmtDate, fmtDateTime, h, icon, openSheet, segment, store, thumb, toast } from "../ui.js";
import { summarize } from "./track.js";

const DEAL_MIN_DISCOUNT = 0.20;   // hoeveel de goedkoopste aanbieding minstens onder het gemiddelde van de andere moet liggen...
const DEAL_MIN_ABS = 25;          // ...óf, als dat percentage niet gehaald wordt, minstens dit bedrag eraf (voor dure kaarten waar 20% een hoge drempel is)

/** Goedkope aanbiedingen: de laagste aanbieding ligt flink onder het gemiddelde van de andere aanbiedingen van
 * dezelfde kaart (min. 20%, of min. EUR25 bij dure kaarten). De database rekent dit zelf uit (view v_deals), zodat
 * de app niet alle aanbiedingen hoeft op te halen. Vergelijkt aanbiedingen onderling, niet met de trendprijs: die
 * kan bij weinig verkopen onbetrouwbaar zijn (zie Electivire). */
async function fetchDeals(limit = 200) {
  const s = getSettings();
  const rows = await rest.get(`v_deals?select=*&order=discount.desc&limit=200`).catch(() => []);
  return rows
    .map((d) => ({ ...d, cheapest: Number(d.cheapest), market: Number(d.market), discount: Number(d.discount) }))
    .map((d) => ({ ...d, gain: dealGain(d.cheapest, d.market, s) }))
    .map((d) => ({ ...d, gainPct: d.gain / (d.cheapest + shipCost(d.cheapest)) }))   // winst als deel van wat je kwijt bent: kaart plus verzending
    .filter((d) => d.gain >= DEAL_MIN_GAIN)   // na verzending als koper, commissie en verpakking moet er echt winst overblijven
    .sort((a, b) => b.gain - a.gain)
    .slice(0, limit);
}

// ---- filters en sortering op Home: één rij knopjes voor Deals én Goedkope aanbiedingen ----
export const HOME_DEFAULT = { kind: "alles", max: 0, sort: "gain" };
const HOME_SORTS = [["gain", "Most profit"], ["dip", "Biggest discount"], ["low", "Lowest price"], ["high", "Highest price"]];
const HOME_MAX = [[0, "Any price"], [25, "Up to €25"], [50, "Up to €50"], [100, "Up to €100"], [250, "Up to €250"]];
const HOME_KIND = [["alles", "All"], ["card", "Cards"], ["sealed", "Sealed"]];
const DEAL_ORDER = {
  gain: (a, b) => b.gainPct - a.gainPct, dip: (a, b) => b.discount - a.discount,
  low: (a, b) => a.cheapest - b.cheapest, high: (a, b) => b.cheapest - a.cheapest,
};

/** Past de filters en de sortering toe op de goedkope aanbiedingen. max 0 = geen grens. */
export function filterDeals(deals, f) {
  return deals
    .filter((d) => (!f.max || d.cheapest <= f.max) && (f.kind === "alles" || d.kind === f.kind))
    .sort(DEAL_ORDER[f.sort] || DEAL_ORDER.gain);
}

/** Zelfde filters op de Deals (kaarten ruim onder hun normale prijs). */
export function filterBuys(picks, f) {
  const cmp = {
    gain: (a, b) => b.gain - a.gain,
    dip: (a, b) => a.price / a.normal - b.price / b.normal,
    low: (a, b) => a.price - b.price,
    high: (a, b) => b.price - a.price,
  }[f.sort] || ((a, b) => b.gain - a.gain);
  return picks.filter((x) => (!f.max || x.price <= f.max) && (f.kind === "alles" || x.r.kind === f.kind)).sort(cmp);
}

/** Kies-lijst onderaan het scherm (sorteren, maximumprijs). */
function pickSheet(title, opts, cur, onPick) {
  openSheet(h("div", { class: "sheetin" }, h("div", { class: "handle" }), h("h3", { text: title }),
    h("div", { class: "opts" }, ...opts.map(([k, label]) => h("button", { type: "button", class: "opt", "aria-pressed": String(cur === k),
      onclick: () => { closeSheet(); onPick(k); } }, h("span", { text: label }), cur === k ? icon("check") : null)))));
}

/** Uitleg achter het i'tje naast een titel: de lijst zelf blijft zo kort. */
const infoBtn = (title, ...body) => h("button", { type: "button", class: "infob", "aria-label": `Info: ${title}`,
  onclick: () => openSheet(h("div", { class: "sheetin" }, h("div", { class: "handle" }), h("h3", { text: title }), ...body.map((t) => (typeof t === "string" ? h("p", { class: "p14", text: t }) : t)))) }, "i");

/** De rij filterknopjes. onChange wordt aangeroepen na elke wijziging. */
function filterBar(f, onChange) {
  const bar = h("div", { class: "fchips homef" });
  const draw = () => bar.replaceChildren(
    ...HOME_KIND.map(([k, label]) => h("button", { type: "button", class: "fchip" + (f.kind === k ? " on" : ""), "aria-pressed": String(f.kind === k), text: label,
      onclick: () => { f.kind = k; done(); } })),
    h("button", { type: "button", class: "fchip" + (f.max ? " on" : ""), "aria-label": "Max price", onclick: () => pickSheet("Max price", HOME_MAX, f.max, (v) => { f.max = v; done(); }) },
      HOME_MAX.find((x) => x[0] === f.max)?.[1] || "Any price", icon("chev")),
    h("button", { type: "button", class: "fchip sortc", "aria-label": "Sort, now: " + HOME_SORTS.find((x) => x[0] === f.sort)[1], onclick: () => pickSheet("Sort", HOME_SORTS, f.sort, (v) => { f.sort = v; done(); }) },
      icon("sort"), HOME_SORTS.find((x) => x[0] === f.sort)[1]));
  const done = () => { store.set("pd:home2", f); draw(); onChange(); };
  draw();
  bar.reset = () => { Object.assign(f, HOME_DEFAULT); done(); };
  return bar;
}

const setLine = (r) => [r.set_name, r.number && r.kind === "card" ? `#${r.number}` : ""].filter(Boolean).join(" · ");

function marketRow(d, watchId, onHeart) {
  return h("li", {}, h("div", { class: "homeitem" },
    h("button", { class: "rowc dealrow", type: "button", onclick: () => go(detailHash(d.product_id)) },
      thumb(d.image, "ph", d.kind === "sealed"),
      h("div", { class: "body" },
        h("span", { class: "nm" }, h("span", { class: "name", text: d.name })),
        h("span", { class: "set", text: setLine(d) }),
        d.variant && d.variant !== "Normal" ? h("span", {}, h("span", { class: "tag", text: d.variant })) : null),
      h("span", { class: "mv" }, h("span", { class: "v num", text: eur(d.cheapest) }),
        h("span", { class: "arw up", "aria-label": `${Math.round(d.discount * 100)}% below the next cheapest` }, `−${Math.round(d.discount * 100)}%`),
        h("span", { class: "gain num", "aria-label": "profit after costs", text: "+" + eur(d.gain) }))),
    h("button", { class: "heartb" + (watchId ? " on" : ""), type: "button", "aria-label": watchId ? "Remove from watchlist" : "Add to watchlist", onclick: onHeart }, icon("heart", watchId ? "filled" : ""))));
}

let state = { kind: "alles", shown: 60 };

async function fetchRows(s) {
  const key = `pd:home:${s.horizon}:${s.pct}`;
  const sel = "product_id,kind,name,set_name,number,image,price,exp_change,p_up,p_down,signal,confidence,n,updated";
  try {
    const rows = await rest.get(`v_forecasts?select=${sel}&horizon_days=eq.${s.horizon}&threshold_pct=eq.${s.pct}&order=p_up.desc&limit=1000`);
    store.set(key, { ts: Date.now(), rows });
    return { rows, cachedAt: null };
  } catch (e) {
    const c = store.get(key, null);
    if (c) return { rows: c.rows, cachedAt: c.ts };
    throw e;
  }
}

/** Deals: kaarten die al een week ruim onder hun normale prijs staan, bevestigd door echte verkopen, zonder tekenen van
 * een gestuurde prijs en zonder aanwijsbare reden voor de daling, en waarbij na kosten genoeg overblijft als ze herstellen
 * (zie collector/advice.py en model.adviceFor). Per kaart: prijs en een balkje met de verwachte stijging en de kans erop. */
function buySection(f, hook, reset) {
  const box = h("div", { class: "sec buysec" });
  (async () => {
    let rows, stats;
    try {
      [rows, stats] = await Promise.all([rest.get("v_advice?select=*&state=eq.laag&price=gte.10&limit=1000"), rest.get("advice_stats?select=*")]);
    } catch { box.remove(); return; }   // adviestabel bestaat nog niet (schema.sql niet opnieuw gedraaid)
    const s = getSettings();
    const all = rows.map((r) => ({ r, a: adviceFor(r, { s }), o: outlook(r, stats), price: Number(r.price), normal: Number(r.normal), gain: recoveryGain(Number(r.price), Number(r.normal), s) }))
      .filter((x) => x.a.tone === "buy");
    const SHOWN = 5;
    let showAll = false;
    const row = ({ r, o }) => h("li", {}, h("button", { type: "button", class: "rowc", onclick: () => go(detailHash(r.product_id)) },
      thumb(r.image, "ph", r.kind === "sealed"),
      h("div", { class: "body" }, h("span", { class: "nm" }, h("span", { class: "name", text: r.name })), h("span", { class: "set", text: setLine(r) })),
      moveCell({ value: eur(Number(r.price)), outlook: o })));
    const list = h("ul", { class: "list advlist" });
    const moreBtn = h("button", { class: "linkbtn", type: "button" });
    const title = h("h3", {});
    function draw() {
      const picks = filterBuys(all, f);
      title.replaceChildren("Deals ", h("span", { class: "cnt", text: String(picks.length) }));
      list.replaceChildren(...(picks.length ? (showAll ? picks : picks.slice(0, SHOWN)).map(row)
        : [all.length ? h("li", { class: "emptyfilter" }, emptyNote("No deals match these filters."), h("button", { class: "linkbtn", type: "button", text: "Clear filters", onclick: reset }))
            : emptyNote("No deals today. Better none than a bad one.")]));
      moreBtn.hidden = showAll || picks.length <= SHOWN;
      moreBtn.textContent = `Show all ${picks.length}`;
    }
    moreBtn.onclick = () => { showAll = true; draw(); };
    box.replaceChildren(h("div", { class: "sech" }, title, infoBtn("Deals",
      "Cards a week well below their normal price, confirmed by real sales.",
      "The bar shows the chance the price returns to normal: the longer and greener, the likelier. The percentage is how much the card would rise.",
      "Cards with signs of price manipulation, or a reason for the drop (reprint, new set, whole set or market falling), are left out.",
      adviceTrack(stats, "laag"),
      "With a big drop, always check Cardmarket yourself before buying. Not financial advice.")),
      list, moreBtn);
    hook.draw = draw;
    draw();
  })();
  return box;
}

/** Wanneer de dagelijkse update voor het laatst klaar was (tabel app_status, geschreven door collector/run.py). */
const lastUpdate = () => rest.get("app_status?select=updated_at&order=updated_at.desc&limit=1").then((r) => r[0]?.updated_at || null).catch(() => null);

async function dealsHome(root) {
  const status = h("p", { class: "muted sub" });
  const list = h("ul", { class: "list dealslist" });
  const watched = new Map();
  const f = { ...HOME_DEFAULT, ...store.get("pd:home2", {}) };
  let deals = [];
  const buyHook = { draw: () => {} };
  const title = h("h3", { text: "Cheap listings" });
  const SHOWN = 5;
  let showAll = false;
  const moreBtn = h("button", { class: "linkbtn", type: "button", hidden: true, onclick: () => { showAll = true; draw(); } });

  const dealSec = h("div", { class: "sec dealsec" },
    h("div", { class: "sech" }, title, infoBtn("Cheap listings",
      "The cheapest Cardmarket listing is well below the next cheapest, within the same variant (Normal, Reverse Holofoil, ...).",
      "Red is how much cheaper; green is what you keep if you buy and resell at the next cheapest price, after shipping, fees and packaging.",
      "Near Mint cards only. A very low price may be a mistake: always check Cardmarket yourself.")),
    list, moreBtn);
  const fbar = filterBar(f, () => { buyHook.draw(); draw(); });
  root.replaceChildren(h("div", { class: "page" },
    brandmark(),
    h("div", { class: "head" }, h("h1", { text: "Home" }), status),
    fbar,
    buySection(f, buyHook, () => fbar.reset()),
    dealSec));

  function draw() {
    const shown = filterDeals(deals, f);
    title.replaceChildren("Cheap listings ", h("span", { class: "cnt", text: String(shown.length) }));
    if (!deals.length) return;
    moreBtn.hidden = showAll || shown.length <= SHOWN;
    moreBtn.textContent = `Show all ${shown.length}`;
    if (!shown.length) { list.replaceChildren(h("li", { class: "emptyfilter" }, emptyNote("No listings match these filters."), h("button", { class: "linkbtn", type: "button", text: "Clear filters", onclick: () => fbar.reset() }))); return; }
    list.replaceChildren(...(showAll ? shown : shown.slice(0, SHOWN)).map((d) => marketRow(d, watched.get(d.product_id), async (e) => {
      e.stopPropagation();
      if (!getSession()) { go("#/login?next=" + encodeURIComponent("#/home")); return; }
      try {
        const wid = watched.get(d.product_id);
        if (wid) { await removeWatch(wid); watched.delete(d.product_id); toast("Removed from watchlist"); }
        else { watched.set(d.product_id, await addWatch(d.product_id)); toast("Added to watchlist"); }
        draw();
      } catch { toast("Couldn't update"); }
    })));
  }

  list.replaceChildren(emptyNote("Loading…"));
  deals = await fetchDeals();
  if (!deals.length) {
    title.textContent = "Cheap listings";
    list.replaceChildren(emptyNote("No cheap listings yet. They update every night."));
    return;
  }
  const newest = deals.reduce((m, d) => (d.date > m ? d.date : m), "");
  status.textContent = newest ? `Updated ${fmtDate(newest)}` : "";
  lastUpdate().then((t) => { if (t) status.textContent = `Updated ${fmtDateTime(t)}`; });
  if (getSession()) await Promise.all(deals.map(async (d) => { try { const id = await isWatched(d.product_id); if (id) watched.set(d.product_id, id); } catch {} }));
  draw();
}

export async function homeView(root) {
  if (!SHOW_PREDICTIONS) return dealsHome(root);
  const s = getSettings();
  const trackLine = h("span", { text: "" });
  const status = h("p", { class: "muted sub" }, h("span", { class: "st", text: "Loading…" }), " ", trackLine);
  const notice = h("div");
  const legend = h("p", { class: "legend", text: `Chance the Cardmarket trend price rises ${s.pct}%+ within ${s.horizon} days. Right: expected rise after selling costs and shipping. The trend price is an average, not the cheapest listing.` });
  const list = h("ul", { class: "list" });
  const more = h("div", { class: "more" }, h("button", { type: "button", text: "Show more", onclick: () => { state.shown += 60; draw(); } }));
  let rows = [];
  const watched = new Map();

  const toggleWatch = async (pid) => {
    if (!getSession()) { go("#/login?next=" + encodeURIComponent("#/home")); return; }
    try {
      const wid = watched.get(pid);
      if (wid) { await removeWatch(wid); watched.delete(pid); toast("Removed from watchlist"); }
      else { watched.set(pid, await addWatch(pid)); toast("Added to watchlist"); }
      draw();
    } catch { toast("Couldn't update"); }
  };

  let draw = () => {
    const vis = rows.filter((r) => (state.kind === "alles" || r.kind === state.kind) && isOpportunity({ price: Number(r.price), exp: Number(r.exp_change) }, s));
    const page = vis.slice(0, state.shown);
    list.replaceChildren(...(page.length ? page.map((r) => oppRow({ ...r, price: Number(r.price), p_up: Number(r.p_up) }, netGain(Number(r.price), Number(r.exp_change), s), { on: watched.has(r.product_id), onclick: (e) => { e.stopPropagation(); toggleWatch(r.product_id); } }))
      : [emptyNote(rows.length ? "No chances with these settings. Adjust them in Settings." : "No chances yet. They appear after the first daily run.")]));
    more.hidden = vis.length <= state.shown;
  };

  const dealsSec = h("div");
  const dealsList = h("ul", { class: "dealslist" });

  root.replaceChildren(h("div", { class: "page" },
    brandmark(),
    h("div", { class: "head" }, h("h1", { text: "Home" }), status),
    h("div", { class: "bar" },
      segment([["alles", "All"], ["card", "Cards"], ["sealed", "Sealed"]], state.kind, (v) => { state.kind = v; state.shown = 60; draw(); }),
      h("button", { class: "gear", type: "button", text: "Settings", onclick: () => go("#/settings") })),
    dealsSec,
    h("div", { class: "sec homechance" }, h("h3", { text: "Chances" }), legend, list, more),
    h("p", { class: "fine muted", text: "Statistical estimate from market prices; not financial advice. Prices ignore condition, language and marketplace fees (unless set in Settings). Always check the real listings." })));

  fetchDeals().then(async (deals) => {
    if (!deals.length) return;
    if (getSession()) await Promise.all(deals.map(async (d) => { try { const id = await isWatched(d.product_id); if (id) watched.set(d.product_id, id); } catch {} }));
    const drawDeals = () => {
      const vis = deals.filter((d) => state.kind === "alles" || d.kind === state.kind);
      dealsList.replaceChildren(...vis.map((d) => marketRow(d, watched.get(d.product_id), async (e) => {
        e.stopPropagation();
        if (!getSession()) { go("#/login?next=" + encodeURIComponent("#/home")); return; }
        try {
          const wid = watched.get(d.product_id);
          if (wid) { await removeWatch(wid); watched.delete(d.product_id); toast("Removed from watchlist"); }
          else { watched.set(d.product_id, await addWatch(d.product_id)); toast("Added to watchlist"); }
          drawDeals();
        } catch { toast("Couldn't update"); }
      })));
    };
    dealsSec.replaceChildren(h("div", { class: "sec dealsec" },
      h("h3", { text: "Cheap listings" }),
      h("p", { class: "p14 muted", text: "The lowest current listing is well below what other sellers ask, apart from the chance below." }), dealsList));
    drawDeals();
    const oldDraw = draw;
    draw = () => { oldDraw(); drawDeals(); };
  }).catch(() => {});

  rest.get("trackrecord_stats?select=*&horizon_days=eq.30&threshold_pct=eq.10").then((st) => {
    const t = summarize(st);
    trackLine.replaceChildren(h("a", { href: "#/track", class: "hl", text: "Trackrecord" }),
      t?.koop?.n ? `: ${t.koop.hits} of ${t.koop.n} buy signals came true${t.source === "backtest" ? " (backtest)" : ""}.` : ": no results yet.");
  }).catch(() => {});

  try {
    const { rows: data, cachedAt } = await fetchRows(s);
    rows = data;
    if (getSession()) await Promise.all(rows.slice(0, 120).map(async (r) => { if (watched.has(r.product_id)) return; try { const id = await isWatched(r.product_id); if (id) watched.set(r.product_id, id); } catch {} }));
    const updated = rows.reduce((m, r) => (r.updated > m ? r.updated : m), "");
    status.querySelector(".st").textContent = rows.length ? `Updated ${fmtDate(updated)}.` : "No data yet.";
    if (cachedAt) notice.append(note("Offline", `Showing saved data from ${new Date(cachedAt).toLocaleDateString("en-GB", { day: "numeric", month: "long" })}.`));
    const low = rows.filter((r) => r.confidence === "laag").length;
    if (rows.length && low / rows.length > 0.5) {
      notice.append(note("Rough estimates", "Little price history yet. Rows marked 'rough' are a first indication and get more reliable every day."));
    }
    draw();
  } catch (e) {
    status.querySelector(".st").textContent = "Couldn't load.";
    notice.append(note("Couldn't fetch data", "Check your connection and the settings in config.js.",
      h("button", { type: "button", text: "Try again", onclick: () => homeView(root) })));
    console.error(e, getSession());
  }
}
