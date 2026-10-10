// Overzicht 'Verkocht': elke verkoop als bestelling, met je echte winst, plus export naar CSV.
import { rest, userId } from "../api.js";
import { lineChart } from "../chart.js";
import { emptyNote, filterBox, go, matchQuery } from "../components.js";
import { openSaleEdit } from "../orders.js";
import { allocate, saleProfit } from "../model.js";
import { closeSheet, eur, fmtDateLong, h, icon, openSheet, segment, signedEur, store, toast } from "../ui.js";

export async function loadSales() {
  const [sales, items] = await Promise.all([
    rest.get("sales?select=*&order=sale_date.desc,created_at.desc"),
    rest.get("sale_items?select=*"),
  ]);
  const ids = [...new Set(items.map((i) => i.product_id).filter(Boolean))];
  const products = ids.length ? await rest.get(`products?select=product_id,name,set_name,number,kind,image&product_id=in.(${ids.map(encodeURIComponent).join(",")})`) : [];
  const prod = new Map(products.map((p) => [p.product_id, p]));
  const bySale = new Map();
  for (const it of items) {
    if (!bySale.has(it.sale_id)) bySale.set(it.sale_id, []);
    // kaart die niet in de database staat (bijv. Japans): naam en taal staan op de regel zelf
    const base = it.product_id ? (prod.get(it.product_id) || { name: it.product_id }) : { name: it.item_name || "Card", set_name: it.item_language || "", kind: "card" };
    bySale.get(it.sale_id).push({ ...it, ...base, price_share: Number(it.price_share), cost_total: Number(it.cost_total) });
  }
  return sales.map((s) => {
    const lines = bySale.get(s.id) || [];
    return { ...s, lines, profit: saleProfit(s, lines) };
  });
}

// ---- CSV: een regel per kaart; gedeelde bedragen van de bestelling verdeeld zoals de prijs ----
const cell = (v) => { const t = v == null ? "" : String(v); return /[";\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t; };
const nl = (n) => (n == null || Number.isNaN(n) ? "" : Number(n).toFixed(2).replace(".", ","));

export function salesCsv(sales) {
  const head = ["Order number", "Date", "Buyer", "Card", "Set", "Number", "Condition", "Quantity", "Sale price", "Commission",
    "Shipping received", "Shipping paid", "Other costs", "Cost", "Profit"];
  const out = [head.map(cell).join(";")];
  for (const s of sales) {
    const w = s.lines.map((l) => l.price_share);
    const parts = ["commission", "shipping_received", "shipping_paid", "other_costs"].map((k) => allocate(Number(s[k] || 0), w));
    s.lines.forEach((l, i) => {
      out.push([s.id.slice(0, 8), s.sale_date, s.buyer || "", l.name, l.set_name || "", l.number || "",
        l.grade_company ? `${l.grade_company} ${l.grade}` : (l.condition || ""), l.quantity,
        nl(l.price_share), nl(parts[0][i]), nl(parts[1][i]), nl(parts[2][i]), nl(parts[3][i]), nl(l.cost_total), nl(s.profit.per[i])].map(cell).join(";"));
    });
  }
  return out.join("\r\n");
}

function downloadCsv(sales) {
  const blob = new Blob(["\ufeff" + salesCsv(sales)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: `pokedeals-sales-${new Date().toISOString().slice(0, 10)}.csv` });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast("CSV saved");
}

/** Verkoop terugdraaien: de kaarten komen terug in 'In bezit' tegen hun kostprijs, en de verkoop verdwijnt. */
async function undoSale(s, onChange) {
  if (!confirm(`Undo sale to ${s.buyer || "unknown buyer"} on ${fmtDateLong(s.sale_date)}? The cards go back to your collection.`)) return;
  try {
    const back = s.lines.filter((l) => l.product_id);   // niet-Engelse kaarten komen niet in de collectie
    if (back.length) await rest.insert("collection", back.map((l) => ({ user_id: userId(), product_id: l.product_id, quantity: l.quantity,
      condition: l.condition || null, grade_company: l.grade_company || null, grade: l.grade || null,
      purchase_price: Math.round((l.cost_total / l.quantity) * 100) / 100, purchase_date: l.purchase_date || s.sale_date,
      purchase_seller: l.purchase_seller || null, purchase_order: l.purchase_order || null })));
    await rest.del("sales", `id=eq.${s.id}`);
    toast("Sale undone");
    onChange?.();
  } catch (e) { console.error(e); toast("Couldn't undo"); }
}

// ---- grafiek: kost en winst van je verkopen ----
const DAY = 86400000;
const ymdMs = (d) => Date.parse(`${d}T00:00:00Z`);
const costOf = (s) => s.lines.reduce((t, l) => t + Number(l.cost_total || 0), 0);

/** Twee lijnen: wat je voor de verkochte kaarten betaalde (paid) en wat je ervoor terugkreeg na alle kosten (received = betaald + winst).
 * Het vlak ertussen is je winst. 'cum' = opgeteld tot en met die dag, als trapje (de lijn springt pas op een verkoopdag);
 * 'month' = per maand. range: '3M' | '1J' | 'MAX'. Geeft { paid, received, sales: [[ms, received]] } of { note }. */
export function salesPoints(sales, mode, range, now = Date.now()) {
  const days = { "3M": 90, "1J": 365, MAX: Infinity }[range] ?? Infinity;
  const cutoff = now - days * DAY;
  const sorted = [...sales].sort((a, b) => a.sale_date.localeCompare(b.sale_date));
  if (!sorted.length) return { note: "No sales yet." };
  const r2 = (x) => Math.round(x * 100) / 100;
  if (mode === "month") {
    const by = new Map();
    for (const s of sorted) {
      const k = s.sale_date.slice(0, 7);
      const m = by.get(k) || { c: 0, p: 0 };
      m.c += costOf(s); m.p += s.profit.total; by.set(k, m);
    }
    const paid = [], received = [];
    for (const [k, m] of by) {
      const x = ymdMs(`${k}-15`);
      if (x + 16 * DAY >= cutoff) { paid.push([x, r2(m.c)]); received.push([x, r2(m.c + m.p)]); }
    }
    if (paid.length < 2) return { note: "Only one month with sales in this period: pick Cumulative or a longer period." };
    return { paid, received, sales: received };
  }
  const byDay = new Map();
  for (const s of sorted) {
    const d = byDay.get(s.sale_date) || { c: 0, p: 0 };
    d.c += costOf(s); d.p += s.profit.total; byDay.set(s.sale_date, d);
  }
  let c = 0, p = 0;
  const all = [[ymdMs(sorted[0].sale_date) - DAY, 0, 0]];   // vanaf nul de dag voor de eerste verkoop
  for (const [d, v] of byDay) { c += v.c; p += v.p; all.push([ymdMs(d), r2(c), r2(c + p)]); }
  all.push([Math.max(now, all[all.length - 1][0]), r2(c), r2(c + p)]);   // vlak doorlopen tot vandaag
  let shown = all.filter((x) => x[0] >= cutoff);
  if (shown.length < all.length) { const prev = all[all.length - shown.length - 1]; shown = [[cutoff, prev[1], prev[2]], ...shown]; }
  if (shown.length < 2) return { note: "Too few sales in this period for a chart." };
  // trapje: tussen twee verkoopdagen blijft de lijn vlak en springt pas op de dag zelf
  const step = (i) => shown.flatMap((x, k) => (k ? [[x[0], shown[k - 1][i]], [x[0], x[i]]] : [[x[0], x[i]]]));
  const saleDays = new Set([...byDay.keys()].map(ymdMs));
  return { paid: step(1), received: step(2), sales: shown.filter((x) => saleDays.has(x[0])).map((x) => [x[0], x[2]]) };
}

const SALE_PERIODS = [["1w", "1W"], ["1m", "1M"], ["3m", "3M"], ["1y", "1Y"], ["2y", "2Y"], ["all", "All"]];
const PERIOD_DAYS = { "1w": 7, "1m": 30, "3m": 91, "1y": 365, "2y": 730 };
const OLD_PERIOD = { month: "1m", year: "1y" };   // oude bewaarde keuzes
const SALE_RESULTS = [["all", "All"], ["win", "Profit"], ["loss", "Loss"]];
const SALE_SORTS = [["new", "Newest first"], ["old", "Oldest first"], ["win", "Biggest profit"], ["loss", "Biggest loss"]];
export const SALE_FILTER_DEFAULT = { period: "all", result: "all", sort: "new" };

/** Periode, uitkomst en volgorde toepassen op de verkopen. now: 'YYYY-MM-DD' (voor de tests). */
export function filterSales(sales, f, now = new Date().toISOString().slice(0, 10)) {
  const day = (d, n) => new Date(Date.parse(`${d}T00:00:00Z`) + n * 86400000).toISOString().slice(0, 10);
  const p = OLD_PERIOD[f.period] || f.period;
  const ok = PERIOD_DAYS[p] ? (s) => s.sale_date > day(now, -PERIOD_DAYS[p]) : () => true;   // de laatste 7 / 30 / 91 / 365 / 730 dagen
  const res = { all: () => true, win: (s) => s.profit.total > 0, loss: (s) => s.profit.total < 0 }[f.result] || (() => true);
  const cmp = {
    new: (a, b) => b.sale_date.localeCompare(a.sale_date),
    old: (a, b) => a.sale_date.localeCompare(b.sale_date),
    win: (a, b) => b.profit.total - a.profit.total,
    loss: (a, b) => a.profit.total - b.profit.total,
  }[f.sort] || (() => 0);
  return sales.filter((s) => ok(s) && res(s)).sort(cmp);
}

export async function renderSales(box, { onChange } = {}) {
  box.replaceChildren(h("p", { class: "muted pad", text: "Loading…" }));
  let sales;
  try { sales = await loadSales(); } catch (e) { console.error(e); box.replaceChildren(h("p", { class: "err pad", text: "Couldn't load your sales." })); return; }
  if (!sales.length) {
    box.replaceChildren(emptyNote("No sales yet. In your collection, tap 'Select' and then 'Sell' to record one."));
    return;
  }
  const ui = { mode: "cum", ...SALE_FILTER_DEFAULT, ...store.get("pd:sales", {}) };
  ui.period = OLD_PERIOD[ui.period] || ui.period;
  const saveUi = () => store.set("pd:sales", ui);
  let query = "";
  let current = sales;   // de verkopen die door de zoekbalk komen: de totalen, de grafiek, de lijst en de CSV gaan daar allemaal over

  const sumBox = h("div");
  const chartBox = h("div", { class: "chartbox" });
  const chartCard = h("div", { class: "chartcard" },
    segment([["cum", "Cumulative"], ["month", "Per month"]], ui.mode, (m) => { ui.mode = m; saveUi(); drawChart(); }, "small"),
    chartBox);
  const csvBox = h("div", { class: "more" });
  const listBox = h("div", { class: "salelist" });
  const countNote = h("p", { class: "mini fcount", hidden: true });
  const search = filterBox("Search buyer, card or set", (v) => { query = v; draw(); });
  const sortBtn = h("button", { class: "sortb", type: "button", onclick: () => {
    const opts = h("div", { class: "opts" }, ...SALE_SORTS.map(([k, label]) => h("button", { type: "button", class: "opt", "aria-pressed": String(ui.sort === k),
      onclick: () => { ui.sort = k; saveUi(); closeSheet(); draw(); } }, h("span", { text: label }), ui.sort === k ? icon("check") : null)));
    openSheet(h("div", { class: "sheetin" }, h("div", { class: "handle" }), h("h3", { text: "Sort" }), opts));
  } });
  const filterBar = h("div", { class: "salefilters" },
    segment(SALE_PERIODS, ui.period, (v) => { ui.period = v; saveUi(); draw(); }, "small"),
    h("div", { class: "filterrow" }, segment(SALE_RESULTS, ui.result, (v) => { ui.result = v; saveUi(); draw(); }, "small"), sortBtn));
  const filtersActive = () => ui.period !== "all" || ui.result !== "all";
  const clearFilters = () => { ui.period = "all"; ui.result = "all"; saveUi(); renderSales(box, { onChange }); };

  function drawChart() {
    const r = salesPoints(current, ui.mode, "MAX");   // de periode-knoppen hierboven filteren de verkopen al
    if (r.note) { chartBox.replaceChildren(h("p", { class: "muted small", text: r.note })); return; }
    const loss = r.received[r.received.length - 1][1] < r.paid[r.paid.length - 1][1];
    chartBox.replaceChildren(
      lineChart({ series: [{ pts: r.paid, stroke: "var(--ink)", width: 2.2, name: "Paid" }, { pts: r.received, stroke: "var(--up)", width: 3, name: "Received" }],
        area: { upper: r.received, lower: r.paid, fill: loss ? "#C23B2F" : "#0E8A5B" }, marks: r.sales.map(([x, y]) => ({ x, y })),
        scrubSeries: [0, 1], scrubDiff: { name: "Profit", a: 1, b: 0 }, label: "What you paid for the cards you sold, and what you got back" }),
      h("div", { class: "legend" }, h("span", { class: "lg cost", text: "Paid" }), h("span", { class: "lg gain", text: "Received" }), h("span", { class: "lg area", text: "Profit" })));
  }

  function draw() {
    const q = query.trim();
    sortBtn.replaceChildren(icon("sort"), h("span", { text: "Sort" }));
    sortBtn.setAttribute("aria-label", "Sort, now: " + SALE_SORTS.find((x) => x[0] === ui.sort)[1]);
    const searched = sales.filter((s) => matchQuery(q, [s.buyer, s.sale_date, ...s.lines.flatMap((l) => [l.name, l.set_name, l.number])], s.lines.map((l) => l.set_name).join(" ")));
    current = filterSales(searched, ui);
    const narrowed = Boolean(q) || filtersActive();
    countNote.hidden = !narrowed;
    countNote.textContent = `${current.length} of ${sales.length} sales`;
    if (!current.length) {
      sumBox.replaceChildren(); chartCard.hidden = true; csvBox.replaceChildren();
      listBox.replaceChildren(h("div", { class: "emptyfilter" }, emptyNote(q ? `Nothing found for "${q}"${filtersActive() ? " within these filters" : ""}.` : "No sales match these filters."),
        filtersActive() ? h("button", { class: "linkbtn", type: "button", text: "Clear filters", onclick: clearFilters }) : null));
      return;
    }
    chartCard.hidden = false;
    const month = new Date().toISOString().slice(0, 7);
    const total = current.reduce((t, s) => t + s.profit.total, 0);
    const thisMonth = current.filter((s) => s.sale_date.startsWith(month)).reduce((t, s) => t + s.profit.total, 0);
    const revenue = current.reduce((t, s) => t + Number(s.total_price), 0);
    sumBox.replaceChildren(h("div", { class: "sum" },
      h("div", {}, h("div", { class: "lbl2", text: narrowed ? "Profit (filtered)" : "Total profit" }), h("div", { class: "big num " + (total < 0 ? "neg" : ""), text: signedEur(total) })),
      h("div", { class: "r" }, h("div", { class: "lbl2", text: "This month" }), h("div", { class: "prof num" + (thisMonth < 0 ? " neg" : ""), text: signedEur(thisMonth) })),
      h("div", { class: "inv", text: `${current.length} ${current.length === 1 ? "sale" : "sales"} · ${eur(revenue)} revenue` })));
    csvBox.replaceChildren(h("button", { type: "button", text: narrowed ? "Export these sales as CSV" : "Export as CSV", onclick: () => downloadCsv(current) }));
    drawChart();
    listBox.replaceChildren(...current.map((s) => h("div", { class: "sec salecard" },
      h("div", { class: "salehead" },
        h("div", {}, h("b", { text: s.buyer || "Unknown buyer" }), h("div", { class: "mini", text: fmtDateLong(s.sale_date) })),
        h("b", { class: "num " + (s.profit.total < 0 ? "neg" : "pos"), text: signedEur(s.profit.total) })),
      h("ul", { class: "salelines" }, ...s.lines.map((l, i) => h("li", {},
        h("span", { text: `${l.quantity > 1 ? l.quantity + "x " : ""}${l.name}${l.product_id ? "" : ` (${l.item_language || "other"})`}` }),
        h("span", { class: "num", text: `${eur(l.price_share)} (${signedEur(s.profit.per[i])})` })))),
      s.note && s.note !== "Cardmarket" ? h("div", { class: "mini", text: s.note }) : null,
      h("div", { class: "mini", text: `Received ${eur(Number(s.total_price) + Number(s.shipping_received))} · commission ${eur(Number(s.commission))} · shipping ${eur(Number(s.shipping_paid))} · other ${eur(Number(s.other_costs))}` }),
      h("div", { class: "saleacts" },
        h("button", { type: "button", class: "btn act", onclick: () => openSaleEdit(s, onChange) }, "Edit"),
        h("button", { type: "button", class: "linkbtn", text: "Undo sale", onclick: () => undoSale(s, onChange) })))));
  }

  box.replaceChildren(h("div", { class: "searchrow" }, search.box), filterBar, countNote, sumBox, chartCard, csvBox, listBox);
  draw();
}

/** Eigen pagina 'Verkocht' (vanuit Collectie): alle verkopen, met aanpassen en terugdraaien. */
export async function salesView(root) {
  const box = h("div", { class: "salesbox" });
  root.replaceChildren(h("div", { class: "page" },
    h("div", { class: "topbar" }, h("button", { class: "back", type: "button", onclick: () => go("#/collection") }, icon("back"), h("span", { text: "Collection" }))),
    h("div", { class: "head" }, h("h1", { text: "Sold" }), h("p", { class: "muted", text: "All your sales. Tap Edit to fix a mistake." })),
    box));
  await renderSales(box, { onChange: () => salesView(root) });
}
