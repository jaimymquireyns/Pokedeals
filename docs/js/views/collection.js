import { isLoggedIn, rest } from "../api.js";
import { lineChart, stepPoints } from "../chart.js";
import { brandmark, collRow, detailHash, emptyNote, go, gradeTag } from "../components.js";
import { attention, costEach, gradeKey } from "../model.js";
import { getSettings } from "../prefs.js";
import { openPurchaseOrder, openSaleOrder } from "../orders.js";
import { renderSales } from "./sales.js";
import { closeSheet, eur, h, icon, openSheet, segment, signed, signedEur, store, thumb } from "../ui.js";

let ui = { tab: "bezit", kind: "alles", sort: "up", measure: "buy", range: "1M", attentionOpen: false, expanded: {}, ...store.get("pd:coll", {}) };
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
    purchase_price: Number(c.purchase_price), purchase_shipping: Number(c.purchase_shipping || 0), purchase_costs: Number(c.purchase_costs || 0), p_up: c.p_up == null ? null : Number(c.p_up), p_down: c.p_down == null ? null : Number(c.p_down) }));

  const val = (c) => (c.value_each ?? costEach(c)) * c.quantity;
  const gain = (c) => (ui.measure === "30d" ? (c.value_each && c.value_30d_ago ? c.value_each / c.value_30d_ago - 1 : null) : (c.value_each ? c.value_each / costEach(c) - 1 : null));
  const cmp = {
    az: (a, b) => a.name.localeCompare(b.name, "nl"),
    set: (a, b) => (a.set_name || "").localeCompare(b.set_name || "", "nl") || numCmp(a.number, b.number),
    low: (a, b) => val(a) - val(b), high: (a, b) => val(b) - val(a),
    up: (a, b) => (gain(b) ?? -9) - (gain(a) ?? -9), down: (a, b) => (gain(a) ?? 9) - (gain(b) ?? 9),
  };

  const value = items.reduce((s, c) => s + val(c), 0);
  const invested = items.reduce((s, c) => s + costEach(c) * c.quantity, 0);
  const profit = value - invested;
  const attn = attention(items, getSettings());
  const groupKey = (c) => `${c.product_id}|${gradeKey(c)}`;
  const groups = () => {
    const m = new Map();
    for (const c of items) { const k = groupKey(c); if (!m.has(k)) m.set(k, []); m.get(k).push(c); }
    return [...m.entries()].map(([key, copies]) => {
      const first = copies[0], quantity = copies.reduce((n, c) => n + Number(c.quantity || 0), 0);
      const investedTotal = copies.reduce((n, c) => n + costEach(c) * c.quantity, 0);
      const currentTotal = copies.reduce((n, c) => n + (c.value_each ?? costEach(c)) * c.quantity, 0);
      const purchase_price = quantity ? investedTotal / quantity : first.purchase_price;
      const value_each = quantity ? currentTotal / quantity : first.value_each;
      return { key, copies, ...first, quantity, purchase_price, purchase_shipping: 0, value_each, _invested: investedTotal, _value: currentTotal };
    });
  };
  const chartBox = h("div", { class: "chartbox" });
  const list = h("ul", { class: "list" });
  const sortBtn = h("button", { class: "sortb", type: "button" });

  const drawList = () => {
    sortBtn.replaceChildren(icon("sort"), h("span", { text: "Sorteren" }));
    sortBtn.setAttribute("aria-label", "Sorteren, nu: " + SORTS.find((s) => s[0] === ui.sort)[1]);
    const vis = groups().filter((c) => ui.kind === "alles" || c.kind === ui.kind).sort(cmp[ui.sort]);
    const groupRow = (g) => {
      const multi = g.copies.length > 1;
      const ggain = ui.measure === "30d"
        ? (g.value_each && g.value_30d_ago ? g.value_each / g.value_30d_ago - 1 : null)
        : (g._invested ? g._value / g._invested - 1 : null);
      const cls = ggain == null ? "" : ggain < 0 ? " neg" : "";
      const head = h("button", { class: "rowc grouphead", type: "button", onclick: () => {
        if (!multi) { go(detailHash(g.product_id, g.id)); return; }
        ui.expanded[g.key] = !ui.expanded[g.key]; saveUi(); drawList();
      } },
        h("span", { class: "gthumb" }, thumb(g.image, "ph", g.kind === "sealed")),
        h("div", { class: "body" },
          h("span", { class: "nm" }, h("span", { class: "name", text: g.name }), gradeTag(g)),
          h("span", { class: "set", text: (g.set_name || "") + (g.number && g.kind === "card" ? ` #${g.number}` : "") }),
          h("span", { class: "set", text: multi ? `${g.copies.length} aankopen · ${g.quantity} stuks` : `${g.quantity > 1 ? g.quantity + "x, " : ""}gekocht voor ${eur(g.purchase_price)}` })),
        h("div", { class: "p" },
          h("span", { class: "v num", text: eur(g._value) }),
          h("span", { class: "pc" + cls, text: ggain == null ? "prijs onbekend" : signed(ggain) }),
          multi ? icon("chev", ui.expanded[g.key] ? "flip" : "") : null));
      if (!multi || !ui.expanded[g.key]) return h("li", {}, head);
      const copyRows = g.copies.map((c, i) => h("button", { class: "copyrow", type: "button", onclick: () => go(detailHash(c.product_id, c.id)) },
        h("span", {}, h("b", { text: `Aankoop ${i + 1}` }), h("small", { text: `${c.quantity > 1 ? c.quantity + " stuks · " : ""}${c.purchase_date || ""}` })),
        h("span", { class: "num", text: eur(costEach(c)) })));
      return h("li", { class: "collgroup" }, head, h("div", { class: "copies" }, ...copyRows));
    };
    list.replaceChildren(...(vis.length ? vis.map(groupRow) : [emptyNote(items.length ? "Niets in deze selectie." : "Je collectie is leeg. Voeg kaarten toe via Zoeken of de camera.")]));
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

  const owned = ui.tab !== "verkocht";
  const salesBox = h("div", { class: "salesbox" });
  const reload = () => collectionView(root);
  root.replaceChildren(h("div", { class: "page" },
    brandmark(),
    h("div", { class: "head" }, h("h1", { text: "Collectie" })),
    h("div", { class: "colltop" },
      segment([["bezit", "In bezit"], ["verkocht", "Verkocht"]], owned ? "bezit" : "verkocht", (t) => { ui.tab = t; saveUi(); reload(); }),
      h("div", { class: "collacts" },
        h("button", { type: "button", class: "btn act", onclick: () => openPurchaseOrder({ onDone: reload }) }, icon("plus"), " Aankoop"),
        h("button", { type: "button", class: "btn act", disabled: !items.length, onclick: () => openSaleOrder(items, { onDone: () => { ui.tab = "verkocht"; saveUi(); reload(); } }) }, "Verkopen"))),
    owned ? null : salesBox,
    h("div", { class: "ownedbox", hidden: !owned },
    h("div", { class: "sum" },
      h("div", {}, h("div", { class: "lbl2", text: "Waarde nu" }), h("div", { class: "big num", text: eur(value) })),
      h("div", { class: "r" }, h("div", { class: "lbl2", text: "Winst" }), h("div", { class: "prof num" + (profit < 0 ? " neg" : ""), text: `${signedEur(profit)} · ${invested ? signed(profit / invested, 1) : "–"}` })),
      h("div", { class: "inv", text: `Geïnvesteerd ${eur(invested)} · ${items.reduce((s, c) => s + c.quantity, 0)} stuks` })),
    attn.length ? (() => {
      const am = new Map();
      for (const a of attn) { const k = groupKey(a.it); if (!am.has(k)) am.set(k, []); am.get(k).push(a); }
      const body = h("div", { class: "attnbody" });
      if (!ui.attentionOpen) body.hidden = true;
      const drawAttn = () => {
        body.hidden = !ui.attentionOpen;
        body.replaceChildren(...[...am.entries()].map(([k, arr]) => {
          const a = arr[0], multi = arr.length > 1, open = Boolean(ui.expanded[`attn:${k}`]);
          const wrap = h("div", { class: "attngroup" },
            h("button", { type: "button", class: "ar", onclick: () => {
                if (!multi) { go(detailHash(a.it.product_id, a.it.id)); return; }
                ui.expanded[`attn:${k}`] = !open; saveUi(); drawAttn();
              } },
              h("span", { class: "nm", text: a.it.name }),
              h("span", { class: "attnright" },
                h("span", { class: "chip " + a.kind, text: a.chip }),
                multi ? icon("chev", open ? "flip" : "") : null)));
          if (multi && open) {
            const copyRows = arr.map(({ it }, i) => h("button", { class: "copyrow", type: "button", onclick: () => go(detailHash(it.product_id, it.id)) },
              h("span", {}, h("b", { text: `Aankoop ${i + 1}` })),
              h("span", { class: "num", text: eur(costEach(it)) })));
            wrap.append(h("div", { class: "copies" }, ...copyRows));
          }
          return wrap;
        }));
      };
      const box = h("div", { class: "attn" }, h("button", { class: "attnhead", type: "button", onclick: () => { ui.attentionOpen = !ui.attentionOpen; saveUi(); drawAttn(); } }, h("h3", { text: `Aandacht nodig (${attn.length})` }), icon("chev", ui.attentionOpen ? "flip" : "")), body);
      drawAttn(); return box;
    })() : null,
    h("div", { class: "chartcard" }, segment(RANGES, ui.range, (r) => { ui.range = r; saveUi(); drawChart(); }, "small"), chartBox),
    h("div", { class: "stick" }, segment([["alles", "Alles"], ["card", "Kaarten"], ["sealed", "Sealed"]], ui.kind, (k) => { ui.kind = k; saveUi(); drawList(); }), sortBtn),
    list)));
  if (!owned) renderSales(salesBox, { onChange: reload });
  drawList();
  if (items.length) drawChart(); else chartBox.parentElement.hidden = true;
}
