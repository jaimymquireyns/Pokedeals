import { isLoggedIn, rest } from "../api.js";
import { lineChart, stepPoints } from "../chart.js";
import { collRow, detailHash, emptyNote, go } from "../components.js";
import { attention, gradeKey } from "../model.js";
import { closeSheet, eur, h, icon, openSheet, segment, signed, signedEur, store } from "../ui.js";

let ui = { kind: "alles", sort: "up", measure: "buy", range: "1M", ...store.get("pd:coll", {}) };
const saveUi = () => store.set("pd:coll", ui);

const SORTS = [["az", "A–Z"], ["set", "Set en nummer"], ["low", "Laagste waarde"], ["high", "Hoogste waarde"], ["up", "Grootste stijging"], ["down", "Grootste daling"]];
const RANGES = [["1M", "1M"], ["3M", "3M"], ["1J", "1J"], ["MAX", "Max"]];
const numCmp = (a, b) => String(a ?? "").localeCompare(String(b ?? ""), "nl", { numeric: true });

export async function collectionView(root) {
  root.replaceChildren(h("div", { class: "page" }, h("div", { class: "head" }, h("h1", { text: "Collectie" }), h("p", { class: "muted", text: "Laden…" }))));
  let items, alertSet;
  try {
    [items, alertSet] = await Promise.all([
      rest.get("v_collection?select=*"),
      rest.get("alerts?select=product_id,grade_key,active&active=eq.true").then((a) => new Set(a.map((x) => `${x.product_id}|${x.grade_key}`))),
    ]);
  } catch (e) { root.replaceChildren(h("p", { class: "err pad", text: "Kon je collectie niet laden. Controleer je verbinding." })); console.error(e); return; }
  items = items.map((c) => ({ ...c, value_each: c.value_each == null ? null : Number(c.value_each), value_30d_ago: c.value_30d_ago == null ? null : Number(c.value_30d_ago),
    purchase_price: Number(c.purchase_price), p_up: c.p_up == null ? null : Number(c.p_up), p_down: c.p_down == null ? null : Number(c.p_down) }));

  const val = (c) => (c.value_each ?? c.purchase_price) * c.quantity;
  const gain = (c) => (ui.measure === "30d" ? (c.value_each && c.value_30d_ago ? c.value_each / c.value_30d_ago - 1 : null) : (c.value_each ? c.value_each / c.purchase_price - 1 : null));
  const cmp = {
    az: (a, b) => a.name.localeCompare(b.name, "nl"),
    set: (a, b) => (a.set_name || "").localeCompare(b.set_name || "", "nl") || numCmp(a.number, b.number),
    low: (a, b) => val(a) - val(b), high: (a, b) => val(b) - val(a),
    up: (a, b) => (gain(b) ?? -9) - (gain(a) ?? -9), down: (a, b) => (gain(a) ?? 9) - (gain(b) ?? 9),
  };

  const value = items.reduce((s, c) => s + val(c), 0);
  const invested = items.reduce((s, c) => s + c.purchase_price * c.quantity, 0);
  const profit = value - invested;
  const attn = attention(items);
  const chartBox = h("div", { class: "chartbox" });
  const list = h("ul", { class: "list" });
  const sortBtn = h("button", { class: "sortb", type: "button" });

  const drawList = () => {
    sortBtn.replaceChildren(icon("sort"), h("span", { text: "Sorteren" }));
    sortBtn.setAttribute("aria-label", "Sorteren, nu: " + SORTS.find((s) => s[0] === ui.sort)[1]);
    const vis = items.filter((c) => ui.kind === "alles" || c.kind === ui.kind).sort(cmp[ui.sort]);
    list.replaceChildren(...(vis.length ? vis.map((c) => collRow(c, { valueEach: c.value_each, gain: gain(c), alerted: alertSet.has(`${c.product_id}|${gradeKey(c)}`) }))
      : [emptyNote(items.length ? "Niets in deze selectie." : "Je collectie is leeg. Voeg kaarten toe via Zoeken of de camera.")]));
  };

  async function drawChart() {
    const first = items.reduce((m, c) => (c.purchase_date < m ? c.purchase_date : m), "9999");
    const daysSince = Math.max(30, Math.ceil((Date.now() - new Date(first + "T00:00:00")) / 864e5) + 1);
    const nDays = { "1M": 30, "3M": 90, "1J": 365, MAX: Math.min(daysSince, 1500) }[ui.range];
    chartBox.replaceChildren(h("p", { class: "muted", text: "Grafiek laden…" }));
    try {
      const rows = await rest.rpc("portfolio_series", { p_days: nDays });
      const ts = (d) => new Date(d + "T00:00:00Z").getTime();
      const pts = rows.filter((r) => Number(r.invested) > 0);
      if (pts.length < 2) { chartBox.replaceChildren(h("p", { class: "muted small", text: "Nog te weinig data voor een grafiek." })); return; }
      const v = pts.map((r) => [ts(r.day), Number(r.value)]);
      const inv = stepPoints(pts.map((r) => [ts(r.day), Number(r.invested)]));
      chartBox.replaceChildren(lineChart({ series: [{ pts: v, stroke: "var(--up)" }, { pts: inv, stroke: "var(--ink)", width: 2, dash: "5 4" }],
        area: { upper: v, lower: inv, fill: profit >= 0 ? "#0E8A5B" : "#C23B2F" }, label: "Waarde tegenover investering" }),
        h("div", { class: "legend2" }, h("span", { class: "sw solid" }), " Waarde ", h("span", { class: "sw dash" }), " Geïnvesteerd"));
    } catch { chartBox.replaceChildren(h("p", { class: "muted small", text: "Grafiek niet beschikbaar." })); }
  }

  sortBtn.onclick = () => {
    const opts = h("div", { class: "opts" }, ...SORTS.map(([k, label]) => h("button", { type: "button", class: "opt", "aria-pressed": String(ui.sort === k),
      onclick: () => { ui.sort = k; saveUi(); closeSheet(); drawList(); } }, h("span", { text: label }), ui.sort === k ? icon("check") : null)));
    openSheet(h("div", { class: "sheetin" }, h("div", { class: "handle" }), h("h3", { text: "Sorteren" }), opts,
      h("div", { class: "lbl2", text: "Winst of verlies meten" }),
      segment([["buy", "Sinds aankoop"], ["30d", "Afgelopen 30 dagen"]], ui.measure, (m) => { ui.measure = m; saveUi(); drawList(); })));
  };

  root.replaceChildren(h("div", { class: "page" },
    h("div", { class: "head" }, h("h1", { text: "Collectie" })),
    h("div", { class: "sum" },
      h("div", {}, h("div", { class: "lbl2", text: "Waarde nu" }), h("div", { class: "big num", text: eur(value) })),
      h("div", { class: "r" }, h("div", { class: "lbl2", text: "Winst" }), h("div", { class: "prof num" + (profit < 0 ? " neg" : ""), text: `${signedEur(profit)} · ${invested ? signed(profit / invested, 1) : "–"}` })),
      h("div", { class: "inv", text: `Geïnvesteerd ${eur(invested)} · ${items.reduce((s, c) => s + c.quantity, 0)} stuks` })),
    attn.length ? h("div", { class: "attn" }, h("h3", { text: `Aandacht nodig (${attn.length})` }),
      ...attn.map(({ it, chip, kind }) => h("button", { type: "button", class: "ar", onclick: () => go(detailHash(it.product_id, it.id)) },
        h("span", { class: "nm", text: it.name }), h("span", { class: "chip " + kind, text: chip })))) : null,
    h("div", { class: "chartcard" }, segment(RANGES, ui.range, (r) => { ui.range = r; saveUi(); drawChart(); }, "small"), chartBox),
    h("div", { class: "stick" }, segment([["alles", "Alles"], ["card", "Kaarten"], ["sealed", "Sealed"]], ui.kind, (k) => { ui.kind = k; saveUi(); drawList(); }), sortBtn),
    list));
  drawList();
  if (items.length) drawChart(); else chartBox.parentElement.hidden = true;
}
