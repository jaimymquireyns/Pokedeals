import { getSession, rest } from "../api.js";
import { detailHash, emptyNote, go, kindTag, note, oppRow } from "../components.js";
import { isOpportunity, netGain } from "../model.js";
import { getSettings } from "../prefs.js";
import { eur, fmtDate, h, segment, store, thumb } from "../ui.js";
import { summarize } from "./track.js";

const DEAL_MIN_DISCOUNT = 0.25;   // hoeveel de goedkoopste aanbieding minstens onder het gemiddelde van de andere moet liggen

/** Kaarten waar de laagste actuele aanbieding opvallend afwijkt van de rest — een toevallig lage prijs vinden,
 * los van de (soms onbetrouwbare) trend-gebaseerde kans hierboven. Alleen mogelijk voor kaarten waar we al
 * aanbiedingen van hebben (collectie + beste kansen), dus dit dekt nooit de hele catalogus. */
async function fetchDeals() {
  const offers = await rest.get("offers?select=*&order=product_id.asc,rank.asc").catch(() => []);
  const byPid = new Map();
  for (const o of offers) { if (!byPid.has(o.product_id)) byPid.set(o.product_id, []); byPid.get(o.product_id).push(o); }
  const deals = [];
  for (const [pid, rows] of byPid) {
    if (rows.length < 2) continue;
    const cheapest = Number(rows[0].price);
    const refAvg = rows.slice(1).reduce((s, r) => s + Number(r.price), 0) / (rows.length - 1);
    const discount = 1 - cheapest / refAvg;
    if (discount >= DEAL_MIN_DISCOUNT) deals.push({ product_id: pid, cheapest, refAvg, discount, seller: rows[0].seller });
  }
  if (!deals.length) return [];
  deals.sort((a, b) => b.discount - a.discount);
  const ids = deals.map((d) => d.product_id);
  const products = await rest.get(`products?select=product_id,name,image,set_name,number,kind&product_id=in.(${ids.join(",")})`).catch(() => []);
  const byProduct = new Map(products.map((p) => [p.product_id, p]));
  return deals.map((d) => ({ ...d, ...byProduct.get(d.product_id) })).filter((d) => d.name).slice(0, 20);
}

function dealCard(d) {
  return h("li", {},
    h("button", { class: "dealrow", type: "button", onclick: () => go(detailHash(d.product_id)) },
      thumb(d.image, "ph", d.kind === "sealed"),
      h("div", { class: "body" },
        h("div", { class: "l1" }, h("span", { class: "name", text: d.name }), h("span", { class: "dealpct", text: `-${Math.round(d.discount * 100)}%` })),
        h("div", { class: "l2" }, h("span", { class: "set", text: [d.set_name, d.number && d.kind === "card" ? `#${d.number}` : ""].filter(Boolean).join(" · ") }), kindTag(d.kind)),
        h("div", { class: "l3" }, h("b", { class: "num", text: eur(d.cheapest) }), h("span", { class: "lbl", text: `i.p.v. ~${eur(d.refAvg)}` })))));
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

export async function homeView(root) {
  const s = getSettings();
  const trackLine = h("span", { text: "" });
  const status = h("p", { class: "muted sub" }, h("span", { class: "st", text: "Laden…" }), " ", trackLine);
  const notice = h("div");
  const legend = h("p", { class: "legend", text: `Kans dat de Cardmarket-trendprijs binnen ${s.horizon} dagen minstens ${s.pct}% stijgt. Rechts de verwachte stijging na verkoopkosten en verzending. De trendprijs is een gemiddelde, niet het goedkoopste aanbod.` });
  const list = h("ul", { class: "list" });
  const more = h("div", { class: "more" }, h("button", { type: "button", text: "Toon meer", onclick: () => { state.shown += 60; draw(); } }));
  let rows = [];

  const draw = () => {
    const vis = rows.filter((r) => (state.kind === "alles" || r.kind === state.kind) && isOpportunity({ price: Number(r.price), exp: Number(r.exp_change) }, s));
    const page = vis.slice(0, state.shown);
    list.replaceChildren(...(page.length ? page.map((r) => oppRow({ ...r, price: Number(r.price), p_up: Number(r.p_up) }, netGain(Number(r.price), Number(r.exp_change), s)))
      : [emptyNote(rows.length ? "Geen kansen met deze instellingen. Pas filters of kosten aan in Instellingen." : "Nog geen kansen. Na de eerste dagelijkse run verschijnen ze hier.")]));
    more.hidden = vis.length <= state.shown;
  };

  const dealsSec = h("div");
  const dealsList = h("ul", { class: "dealslist" });

  root.replaceChildren(h("div", { class: "page" },
    h("div", { class: "head" }, h("h1", { text: "Kansen" }), status),
    dealsSec,
    h("div", { class: "bar" },
      segment([["alles", "Alles"], ["card", "Kaarten"], ["sealed", "Sealed"]], state.kind, (v) => { state.kind = v; state.shown = 60; draw(); }),
      h("button", { class: "gear", type: "button", text: "Instellingen", onclick: () => go("#/settings") })),
    notice, legend, list, more,
    h("p", { class: "fine muted", text: "Statistische schatting op basis van marktprijzen; geen financieel advies. Prijzen houden geen rekening met conditie, taal of marktplaatskosten (tenzij je die bij Instellingen invult). Controleer altijd de echte aanbiedingen." })));

  fetchDeals().then((deals) => {
    if (!deals.length) return;
    dealsList.replaceChildren(...deals.map(dealCard));
    dealsSec.replaceChildren(h("div", { class: "sec dealsec" },
      h("h3", { text: "Goedkope aanbiedingen" }),
      h("p", { class: "p14 muted", text: "De laagste actuele aanbieding ligt hier flink onder wat de andere verkopers vragen, los van de kans hieronder." }),
      dealsList));
  }).catch(() => {});

  rest.get("trackrecord_stats?select=*&horizon_days=eq.30&threshold_pct=eq.10").then((st) => {
    const t = summarize(st);
    trackLine.replaceChildren(h("a", { href: "#/track", class: "hl", text: "Trackrecord" }),
      t?.koop?.n ? `: ${t.koop.hits} van ${t.koop.n} koop-signalen kwamen uit${t.source === "backtest" ? " (backtest)" : ""}.` : ": nog geen uitkomsten.");
  }).catch(() => {});

  try {
    const { rows: data, cachedAt } = await fetchRows(s);
    rows = data;
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
