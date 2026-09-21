import { getSession, rest } from "../api.js";
import { emptyNote, go, note, oppRow } from "../components.js";
import { isOpportunity, netGain } from "../model.js";
import { getSettings } from "../prefs.js";
import { fmtDate, h, segment, store } from "../ui.js";
import { summarize } from "./track.js";

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
  const legend = h("p", { class: "legend", text: `Kans dat de prijs binnen ${s.horizon} dagen minstens ${s.pct}% stijgt. Rechts de verwachte stijging na verkoopkosten en verzending.` });
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

  root.replaceChildren(h("div", { class: "page" },
    h("div", { class: "head" }, h("h1", { text: "Kansen" }), status),
    h("div", { class: "bar" },
      segment([["alles", "Alles"], ["card", "Kaarten"], ["sealed", "Sealed"]], state.kind, (v) => { state.kind = v; state.shown = 60; draw(); }),
      h("button", { class: "gear", type: "button", text: "Instellingen", onclick: () => go("#/settings") })),
    notice, legend, list, more,
    h("p", { class: "fine muted", text: "Statistische schatting op basis van marktprijzen; geen financieel advies. Prijzen houden geen rekening met conditie, taal of marktplaatskosten (tenzij je die bij Instellingen invult). Controleer altijd de echte aanbiedingen." })));

  rest.get("trackrecord_stats?select=*").then((st) => {
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
    draw();
  } catch (e) {
    status.querySelector(".st").textContent = "Laden mislukt.";
    notice.append(note("Kon de gegevens niet ophalen", "Controleer je internetverbinding en de gegevens in config.js.",
      h("button", { type: "button", text: "Opnieuw proberen", onclick: () => homeView(root) })));
    console.error(e, getSession());
  }
}
