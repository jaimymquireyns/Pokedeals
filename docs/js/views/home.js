import { getSession, rest } from "../api.js";
import { brandmark, detailHash, emptyNote, go, kindTag, note, oppRow } from "../components.js";
import { SHOW_PREDICTIONS, isOpportunity, netGain } from "../model.js";
import { addWatch, isWatched, removeWatch } from "./watchlist.js";
import { getSettings } from "../prefs.js";
import { eur, fmtDate, h, icon, segment, store, thumb, toast } from "../ui.js";
import { summarize } from "./track.js";

const DEAL_MIN_DISCOUNT = 0.20;   // hoeveel de goedkoopste aanbieding minstens onder het gemiddelde van de andere moet liggen...
const DEAL_MIN_ABS = 25;          // ...óf, als dat percentage niet gehaald wordt, minstens dit bedrag eraf (voor dure kaarten waar 20% een hoge drempel is)

/** Goedkope aanbiedingen: de laagste aanbieding ligt flink onder het gemiddelde van de andere aanbiedingen van
 * dezelfde kaart (min. 20%, of min. EUR25 bij dure kaarten). De database rekent dit zelf uit (view v_deals), zodat
 * de app niet alle aanbiedingen hoeft op te halen. Vergelijkt aanbiedingen onderling, niet met de trendprijs: die
 * kan bij weinig verkopen onbetrouwbaar zijn (zie Electivire). */
async function fetchDeals(limit = 60) {
  const rows = await rest.get(`v_deals?select=*&order=discount.desc&limit=${limit}`).catch(() => []);
  return rows.map((d) => ({ ...d, cheapest: Number(d.cheapest), market: Number(d.market), discount: Number(d.discount) }));
}

function marketRow(d, watchId, onHeart) {
  return h("li", {}, h("div", { class: "homeitem" },
    h("button", { class: "dealrow", type: "button", onclick: () => go(detailHash(d.product_id)) },
      thumb(d.image, "ph", d.kind === "sealed"),
      h("div", { class: "body" },
        h("div", { class: "l1" }, h("span", { class: "name", text: d.name }), h("span", { class: "price num", text: eur(d.cheapest) })),
        h("div", { class: "l2" }, h("span", { class: "set", text: (d.set_name || "") + (d.number && d.kind === "card" ? ` #${d.number}` : "") }), kindTag(d.kind)),
        d.variant && d.variant !== "Normal" ? h("div", { class: "l2" }, h("span", { class: "tag", text: d.variant })) : null,
        h("div", { class: "l3 dealinfo" }, h("b", { class: "dealpct", text: `-${Math.round(d.discount * 100)}%` }), h("span", { class: "lbl", text: `t.o.v. ${eur(d.market)} (nr. 2)` })))),
    h("button", { class: "heartb" + (watchId ? " on" : ""), type: "button", "aria-label": watchId ? "Van watchlist halen" : "Aan watchlist toevoegen", onclick: onHeart }, icon("heart", watchId ? "filled" : ""))));
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

/** Home zolang de kansberekening verborgen is: alleen de goedkope aanbiedingen. */
async function dealsHome(root) {
  const status = h("p", { class: "muted sub", text: "Laden…" });
  const list = h("ul", { class: "dealslist" });
  const watched = new Map();
  root.replaceChildren(h("div", { class: "page" },
    brandmark(),
    h("div", { class: "head" }, h("h1", { text: "Home" }), status),
    h("div", { class: "bar" }, h("span"), h("button", { class: "gear", type: "button", text: "Instellingen", onclick: () => go("#/settings") })),
    h("div", { class: "sec dealsec" },
      h("h3", { text: "Goedkope aanbiedingen" }),
      h("p", { class: "p14 muted", text: "Kaarten waarvan de goedkoopste aanbieding op Cardmarket flink onder de tweede goedkoopste ligt, binnen dezelfde uitvoering (Normal, Reverse Holofoil, ...). Alleen gewone Near Mint-kaarten. Vergelijk altijd zelf op Cardmarket: een opvallend lage prijs kan ook een vergissing zijn." }),
      list),
    h("p", { class: "fine muted", text: "De kansberekening (welke kaarten gaan stijgen) is tijdelijk verborgen tot ze betrouwbaar genoeg is. Geen financieel advies." })));
  const deals = await fetchDeals();
  if (!deals.length) {
    status.textContent = "";
    list.replaceChildren(emptyNote("Nog geen goedkope aanbiedingen gevonden. Ze worden elke nacht bijgewerkt; elke kaart om de 3 dagen."));
    return;
  }
  const newest = deals.reduce((m, d) => (d.date > m ? d.date : m), "");
  status.textContent = `${deals.length} aanbiedingen · laatst gecontroleerd ${fmtDate(newest)}`;
  if (getSession()) await Promise.all(deals.map(async (d) => { try { const id = await isWatched(d.product_id); if (id) watched.set(d.product_id, id); } catch {} }));
  const draw = () => list.replaceChildren(...deals.map((d) => marketRow(d, watched.get(d.product_id), async (e) => {
    e.stopPropagation();
    if (!getSession()) { go("#/login?next=" + encodeURIComponent("#/home")); return; }
    try {
      const wid = watched.get(d.product_id);
      if (wid) { await removeWatch(wid); watched.delete(d.product_id); toast("Van watchlist gehaald"); }
      else { watched.set(d.product_id, await addWatch(d.product_id)); toast("Toegevoegd aan watchlist"); }
      draw();
    } catch { toast("Aanpassen mislukte"); }
  })));
  draw();
}

export async function homeView(root) {
  if (!SHOW_PREDICTIONS) return dealsHome(root);
  const s = getSettings();
  const trackLine = h("span", { text: "" });
  const status = h("p", { class: "muted sub" }, h("span", { class: "st", text: "Laden…" }), " ", trackLine);
  const notice = h("div");
  const legend = h("p", { class: "legend", text: `Kans dat de Cardmarket-trendprijs binnen ${s.horizon} dagen minstens ${s.pct}% stijgt. Rechts de verwachte stijging na verkoopkosten en verzending. De trendprijs is een gemiddelde, niet het goedkoopste aanbod.` });
  const list = h("ul", { class: "list" });
  const more = h("div", { class: "more" }, h("button", { type: "button", text: "Toon meer", onclick: () => { state.shown += 60; draw(); } }));
  let rows = [];
  const watched = new Map();

  const toggleWatch = async (pid) => {
    if (!getSession()) { go("#/login?next=" + encodeURIComponent("#/home")); return; }
    try {
      const wid = watched.get(pid);
      if (wid) { await removeWatch(wid); watched.delete(pid); toast("Van watchlist gehaald"); }
      else { watched.set(pid, await addWatch(pid)); toast("Toegevoegd aan watchlist"); }
      draw();
    } catch { toast("Aanpassen mislukte"); }
  };

  let draw = () => {
    const vis = rows.filter((r) => (state.kind === "alles" || r.kind === state.kind) && isOpportunity({ price: Number(r.price), exp: Number(r.exp_change) }, s));
    const page = vis.slice(0, state.shown);
    list.replaceChildren(...(page.length ? page.map((r) => oppRow({ ...r, price: Number(r.price), p_up: Number(r.p_up) }, netGain(Number(r.price), Number(r.exp_change), s), { on: watched.has(r.product_id), onclick: (e) => { e.stopPropagation(); toggleWatch(r.product_id); } }))
      : [emptyNote(rows.length ? "Geen kansen met deze instellingen. Pas filters of kosten aan in Instellingen." : "Nog geen kansen. Na de eerste dagelijkse run verschijnen ze hier.")]));
    more.hidden = vis.length <= state.shown;
  };

  const dealsSec = h("div");
  const dealsList = h("ul", { class: "dealslist" });

  root.replaceChildren(h("div", { class: "page" },
    brandmark(),
    h("div", { class: "head" }, h("h1", { text: "Home" }), status),
    h("div", { class: "bar" },
      segment([["alles", "Alles"], ["card", "Kaarten"], ["sealed", "Sealed"]], state.kind, (v) => { state.kind = v; state.shown = 60; draw(); }),
      h("button", { class: "gear", type: "button", text: "Instellingen", onclick: () => go("#/settings") })),
    dealsSec,
    h("div", { class: "sec homechance" }, h("h3", { text: "Kansen" }), legend, list, more),
    h("p", { class: "fine muted", text: "Statistische schatting op basis van marktprijzen; geen financieel advies. Prijzen houden geen rekening met conditie, taal of marktplaatskosten (tenzij je die bij Instellingen invult). Controleer altijd de echte aanbiedingen." })));

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
          if (wid) { await removeWatch(wid); watched.delete(d.product_id); toast("Van watchlist gehaald"); }
          else { watched.set(d.product_id, await addWatch(d.product_id)); toast("Toegevoegd aan watchlist"); }
          drawDeals();
        } catch { toast("Aanpassen mislukte"); }
      })));
    };
    dealsSec.replaceChildren(h("div", { class: "sec dealsec" },
      h("h3", { text: "Goedkope aanbiedingen" }),
      h("p", { class: "p14 muted", text: "De laagste actuele aanbieding ligt hier flink onder wat de andere verkopers vragen, los van de kans hieronder." }), dealsList));
    drawDeals();
    const oldDraw = draw;
    draw = () => { oldDraw(); drawDeals(); };
  }).catch(() => {});

  rest.get("trackrecord_stats?select=*&horizon_days=eq.30&threshold_pct=eq.10").then((st) => {
    const t = summarize(st);
    trackLine.replaceChildren(h("a", { href: "#/track", class: "hl", text: "Trackrecord" }),
      t?.koop?.n ? `: ${t.koop.hits} van ${t.koop.n} koop-signalen kwamen uit${t.source === "backtest" ? " (backtest)" : ""}.` : ": nog geen uitkomsten.");
  }).catch(() => {});

  try {
    const { rows: data, cachedAt } = await fetchRows(s);
    rows = data;
    if (getSession()) await Promise.all(rows.slice(0, 120).map(async (r) => { if (watched.has(r.product_id)) return; try { const id = await isWatched(r.product_id); if (id) watched.set(r.product_id, id); } catch {} }));
    const updated = rows.reduce((m, r) => (r.updated > m ? r.updated : m), "");
    status.querySelector(".st").textContent = rows.length ? `Bijgewerkt ${fmtDate(updated)}.` : "Nog geen data.";
    if (cachedAt) notice.append(note("Geen verbinding", `Je ziet de laatst opgeslagen stand van ${new Date(cachedAt).toLocaleDateString("nl-NL", { day: "numeric", month: "long" })}.`));
    const low = rows.filter((r) => r.confidence === "laag").length;
    if (rows.length && low / rows.length > 0.5) {
      notice.append(note("Nog grove schattingen", "Er is nog weinig prijsgeschiedenis. Rijen met het label 'grof' zijn een eerste indicatie en worden elke dag betrouwbaarder."));
    }
    draw();
  } catch (e) {
    status.querySelector(".st").textContent = "Laden mislukt.";
    notice.append(note("Kon de gegevens niet ophalen", "Controleer je internetverbinding en de gegevens in config.js.",
      h("button", { type: "button", text: "Opnieuw proberen", onclick: () => homeView(root) })));
    console.error(e, getSession());
  }
}
