import { isLoggedIn, rest } from "../api.js";
import { lineChart, stepPoints } from "../chart.js";
import { adviceChip, brandmark, detailHash, emptyNote, extras, filterBox, go, gradeTag, matchQuery, moveCell } from "../components.js";
import { adviceFor, attention, costEach, gradeKey, outlook } from "../model.js";
import { getSettings } from "../prefs.js";
import { openPurchaseOrder, openSaleDetails } from "../orders.js";
import { closeSheet, eur, h, icon, openSheet, segment, signed, signedEur, store, thumb } from "../ui.js";

let ui = { tab: "bezit", adviceOpen: true, kind: "alles", sort: "up", measure: "buy", range: "1M", attentionOpen: false, expanded: {}, ...store.get("pd:coll", {}) };
const saveUi = () => store.set("pd:coll", ui);

const SORTS = [["az", "A–Z"], ["za", "Z–A"], ["new", "Newest (last added)"], ["set", "Set and number"], ["low", "Lowest value"], ["high", "Highest value"], ["up", "Biggest rise"], ["down", "Biggest drop"]];
const RANGES = [["1M", "1M"], ["3M", "3M"], ["1J", "1Y"], ["MAX", "Max"]];
const numCmp = (a, b) => String(a ?? "").localeCompare(String(b ?? ""), "nl", { numeric: true });


export async function collectionView(root) {
  root.replaceChildren(h("div", { class: "page" }, h("div", { class: "head" }, h("h1", { text: "Collection" }), h("p", { class: "muted", text: "Loading…" }))));
  let items, alertSet;
  try {
    [items, alertSet] = await Promise.all([
      rest.get("v_collection?select=*"),
      rest.get("alerts?select=product_id,grade_key,active&active=eq.true").then((a) => new Set(a.map((x) => `${x.product_id}|${x.grade_key}`))),
    ]);
  } catch (e) { root.replaceChildren(h("p", { class: "err pad", text: "Couldn't load your collection. Check your connection." })); console.error(e); return; }
  items = items.map((c) => ({ ...c, value_each: c.value_each == null ? null : Number(c.value_each), value_30d_ago: c.value_30d_ago == null ? null : Number(c.value_30d_ago), value_trend: c.value_trend == null ? null : Number(c.value_trend),
    purchase_price: Number(c.purchase_price), purchase_shipping: Number(c.purchase_shipping || 0), purchase_costs: Number(c.purchase_costs || 0), p_up: c.p_up == null ? null : Number(c.p_up), p_down: c.p_down == null ? null : Number(c.p_down) }));

  // advies per kaart (Verkopen / Houden / Verdacht); zonder adviestabel gewoon zonder
  const advRows = new Map();
  const advStats = await rest.get("advice_stats?select=*").catch(() => []);
  const ids = [...new Set(items.map((c) => c.product_id))];
  for (let i = 0; i < ids.length; i += 100) {
    try {
      for (const r of await rest.get(`v_advice?select=*&product_id=in.(${ids.slice(i, i + 100).map(encodeURIComponent).join(",")})`)) advRows.set(r.product_id, r);
    } catch { break; }
  }
  const settings = getSettings();
  const adviceOf = (g) => adviceFor(advRows.get(g.product_id), { owned: g, s: settings });
  const outlookOf = (g) => (g.grade_company ? null : outlook(advRows.get(g.product_id), advStats));

  const val = (c) => (c.value_each ?? costEach(c)) * c.quantity;
  const gain = (c) => (ui.measure === "30d" ? ((c.value_trend ?? c.value_each) && c.value_30d_ago ? (c.value_trend ?? c.value_each) / c.value_30d_ago - 1 : null) : (c.value_each ? c.value_each / costEach(c) - 1 : null));
  // Het moment van toevoegen (created_at); zonder dat veld (de weergave is nog niet bijgewerkt) vallen we terug op de aankoopdatum.
  // Een kaart met meerdere aankopen telt mee met zijn laatst toegevoegde aankoop.
  const addedAt = (c) => String((c.copies ? c.copies.reduce((m, x) => (String(x.created_at || x.purchase_date || "") > m ? String(x.created_at || x.purchase_date || "") : m), "") : (c.created_at || c.purchase_date)) || "");
  const cmp = {
    az: (a, b) => a.name.localeCompare(b.name, "nl"),
    za: (a, b) => b.name.localeCompare(a.name, "nl"),
    new: (a, b) => addedAt(b).localeCompare(addedAt(a)) || a.name.localeCompare(b.name, "nl"),   // wanneer het aan de collectie is toegevoegd, niet de aankoopdatum
    set: (a, b) => (a.set_name || "").localeCompare(b.set_name || "", "nl") || numCmp(a.number, b.number),
    low: (a, b) => val(a) - val(b), high: (a, b) => val(b) - val(a),
    up: (a, b) => (gain(b) ?? -9) - (gain(a) ?? -9), down: (a, b) => (gain(a) ?? 9) - (gain(b) ?? 9),
  };

  const value = items.reduce((s, c) => s + val(c), 0);
  const invested = items.reduce((s, c) => s + costEach(c) * c.quantity, 0);
  const profit = value - invested;
  const attn = attention(items, getSettings());
  const groupKey = (c) => `${c.product_id}|${gradeKey(c)}|${c.language || ""}|${c.variant || ""}`;
  const groups = () => {
    const m = new Map();
    for (const c of items) { const k = groupKey(c); if (!m.has(k)) m.set(k, []); m.get(k).push(c); }
    return [...m.entries()].map(([key, copies]) => {
      const first = copies[0], quantity = copies.reduce((n, c) => n + Number(c.quantity || 0), 0);
      const investedTotal = copies.reduce((n, c) => n + costEach(c) * c.quantity, 0);
      const currentTotal = copies.reduce((n, c) => n + (c.value_each ?? costEach(c)) * c.quantity, 0);
      const purchase_price = quantity ? investedTotal / quantity : first.purchase_price;
      const value_each = quantity ? currentTotal / quantity : first.value_each;
      return { key, copies, ...first, quantity, purchase_price, purchase_shipping: 0, purchase_costs: 0, value_each, _invested: investedTotal, _value: currentTotal };
    });
  };
  const chartBox = h("div", { class: "chartbox" });
  const list = h("ul", { class: "list" });
  const sortBtn = h("button", { class: "sortb", type: "button" });

  let selecting = false;           // "Selecteren" om kaarten te verkopen
  const picked = new Set();        // groepssleutels van aangevinkte kaarten
  const selBar = h("div", { class: "selbar", hidden: true });
  const fab = h("button", { type: "button", class: "fab", "aria-label": "Add" }, icon("plus"));
  const drawSel = () => {
    fab.hidden = selecting;
    const gs = groups().filter((g) => picked.has(g.key));
    const n = gs.reduce((t, g) => t + g.quantity, 0);
    const worth = gs.reduce((t, g) => t + g._value, 0);
    selBar.hidden = !selecting;
    list.style.paddingBottom = "84px";   // de + en de balk onderaan mogen de laatste kaart niet bedekken
    selBar.replaceChildren(
      h("button", { type: "button", class: "selx", "aria-label": "Cancel", onclick: () => { selecting = false; picked.clear(); drawSel(); drawList(); } }, icon("x")),
      h("span", { class: "selinfo" }, h("b", { text: gs.length ? `${n} selected` : "Tap the cards you sold" }), gs.length ? h("small", { class: "num", text: `value ${eur(worth)}` }) : null),
      h("button", { type: "button", class: "cta", onclick: () => {
        const chosen = gs.flatMap((g) => g.copies.map((c) => ({ c, qty: Number(c.quantity) })));
        openSaleDetails(chosen, () => { selecting = false; picked.clear(); go("#/verkocht"); });
      } }, gs.length ? `Sell (${gs.length})` : "Sell"));
  };
  // + rechtsonder: een aankoop toevoegen of een verkoop vastleggen (dan tik je de verkochte kaarten aan)
  fab.onclick = () => openSheet(h("div", { class: "sheetin" }, h("div", { class: "handle" }),
    h("div", { class: "opts" },
      h("button", { type: "button", class: "opt", onclick: () => { closeSheet(); openPurchaseOrder({ onDone: reload }); } }, icon("plus"), h("span", { text: "Add purchase" })),
      items.length ? h("button", { type: "button", class: "opt", onclick: () => { closeSheet(); selecting = true; picked.clear(); drawSel(); drawList(); } }, icon("check"), h("span", { text: "Record sale" })) : null)));

  let query = "";   // zoekbalk: wordt gewist zodra je van scherm wisselt
  const countNote = h("p", { class: "mini fcount", hidden: true });
  const searchBar = filterBox("Search name, set or number", (v) => { query = v; drawList(); });
  const drawList = () => {
    sortBtn.replaceChildren(icon("sort"), h("span", { text: "Sort" }));
    sortBtn.setAttribute("aria-label", "Sort, now: " + SORTS.find((s) => s[0] === ui.sort)[1]);
    const ofKind = groups().filter((c) => ui.kind === "alles" || c.kind === ui.kind);
    const vis = ofKind.filter((c) => matchQuery(query, [c.name, c.cm_name, c.set_name, c.number, c.condition, c.language, c.variant, c.grade_company ? `${c.grade_company} ${c.grade}` : ""], c.set_name)).sort(selecting ? cmp.az : cmp[ui.sort]);   // bij het selecteren altijd A–Z
    countNote.hidden = !query.trim();
    countNote.textContent = `${vis.length} of ${ofKind.length} found`;
    const groupRow = (g) => {
      const multi = g.copies.length > 1;
      const ggain = ui.measure === "30d"
        ? ((g.value_trend ?? g.value_each) && g.value_30d_ago ? (g.value_trend ?? g.value_each) / g.value_30d_ago - 1 : null)
        : (g._invested ? g._value / g._invested - 1 : null);
      const head = h("button", { class: "rowc grouphead", type: "button", onclick: () => {
        if (selecting) { if (picked.has(g.key)) picked.delete(g.key); else picked.add(g.key); drawSel(); drawList(); return; }
        if (!multi) { go(detailHash(g.product_id, g.id)); return; }
        ui.expanded[g.key] = !ui.expanded[g.key]; saveUi(); drawList();
      } },
        h("span", { class: "gthumb" }, thumb(g.image, "ph", g.kind === "sealed", g.kind === "sealed" ? "" : [g.name, g.number ? "#" + g.number : ""].filter(Boolean).join(" "))),
        h("div", { class: "body" },
          h("span", { class: "nm" }, h("span", { class: "name", text: g.name }), gradeTag(g)),
          h("span", { class: "set", text: (g.set_name || "") + (g.number && g.kind === "card" ? ` #${g.number}` : "") }),
          multi || g.quantity > 1 || adviceChip(adviceOf(g)) || extras(g).length ? h("span", { class: "meta" }, adviceChip(adviceOf(g)),
            extras(g).length ? h("span", { class: "set", text: extras(g).join(" · ") }) : null,
            multi ? h("span", { class: "set", text: `${g.copies.length} purchases` }) : g.quantity > 1 ? h("span", { class: "set", text: `${g.quantity}x` }) : null,
            multi ? icon("chev", ui.expanded[g.key] ? "flip" : "") : null) : null),
        moveCell({ value: eur(g._value), change: ggain, outlook: outlookOf(g) }));
      if (selecting) {
        const box = h("input", { type: "checkbox", class: "selbox", "aria-label": `Select ${g.name}`, checked: picked.has(g.key) ? "checked" : null,
          onchange: (e) => { if (e.target.checked) picked.add(g.key); else picked.delete(g.key); drawSel(); drawList(); } });
        return h("li", { class: "selrow" + (picked.has(g.key) ? " on" : "") }, box, head);
      }
      if (!multi || !ui.expanded[g.key]) return h("li", {}, head);
      const copyRows = g.copies.map((c, i) => h("button", { class: "copyrow", type: "button", onclick: () => go(detailHash(c.product_id, c.id)) },
        h("span", {}, h("b", { text: `Purchase ${i + 1}` }), h("small", { text: `${c.quantity > 1 ? c.quantity + " pcs · " : ""}${c.purchase_date || ""}` })),
        h("span", { class: "num", text: eur(costEach(c)) })));
      return h("li", { class: "collgroup" }, head, h("div", { class: "copies" }, ...copyRows));
    };
    list.replaceChildren(...(vis.length ? vis.map(groupRow) : [emptyNote(query.trim() ? `Nothing found for "${query.trim()}".` : items.length ? "Nothing in this selection." : "Your collection is empty. Add cards via Search or the camera.")]));
  };

  async function drawChart() {
    const first = items.reduce((m, c) => (c.purchase_date < m ? c.purchase_date : m), "9999");
    const daysSince = Math.max(30, Math.ceil((Date.now() - new Date(first + "T00:00:00")) / 864e5) + 1);
    const nDays = { "1M": 30, "3M": 90, "1J": 365, MAX: Math.min(daysSince, 1500) }[ui.range];
    chartBox.replaceChildren(h("p", { class: "muted", text: "Loading chart…" }));
    try {
      const rows = await rest.rpc("portfolio_series", { p_days: nDays });
      const ts = (d) => new Date(d + "T00:00:00Z").getTime();
      const pts = rows.filter((r) => Number(r.invested) > 0);
      if (pts.length < 2) { chartBox.replaceChildren(h("p", { class: "muted small", text: "Not enough data for a chart yet." })); return; }
      const v = pts.map((r) => [ts(r.day), Number(r.value)]);
      const inv = stepPoints(pts.map((r) => [ts(r.day), Number(r.invested)]));
      chartBox.replaceChildren(lineChart({ series: [{ pts: v, stroke: "var(--up)" }, { pts: inv, stroke: "var(--ink)", width: 2, dash: "5 4" }],
        area: { upper: v, lower: inv, fill: profit >= 0 ? "#0E8A5B" : "#C23B2F" }, label: "Value vs. invested" }),
        h("div", { class: "legend2" }, h("span", { class: "sw solid" }), " Value ", h("span", { class: "sw dash" }), " Invested"));
    } catch { chartBox.replaceChildren(h("p", { class: "muted small", text: "Chart unavailable." })); }
  }

  sortBtn.onclick = () => {
    const opts = h("div", { class: "opts" }, ...SORTS.map(([k, label]) => h("button", { type: "button", class: "opt", "aria-pressed": String(ui.sort === k),
      onclick: () => { ui.sort = k; saveUi(); closeSheet(); drawList(); } }, h("span", { text: label }), ui.sort === k ? icon("check") : null)));
    openSheet(h("div", { class: "sheetin" }, h("div", { class: "handle" }), h("h3", { text: "Sort" }), opts,
      h("div", { class: "lbl2", text: "Measure profit or loss" }),
      segment([["buy", "Since purchase"], ["30d", "Last 30 days"]], ui.measure, (m) => { ui.measure = m; saveUi(); drawList(); })));
  };

  const reload = () => collectionView(root);
  root.replaceChildren(h("div", { class: "page" },
    brandmark(),
    h("div", { class: "head" }, h("h1", { text: "Collection" })),
    // "In bezit" is deze pagina zelf; Gekocht en Verkocht zijn eigen pagina's met de hele geschiedenis
    h("nav", { class: "collnav", "aria-label": "Collection" },
      h("span", { class: "on", "aria-current": "page", text: "Owned" }),
      h("a", { href: "#/gekocht", text: "Bought" }),
      h("a", { href: "#/verkocht", text: "Sold" })),
    h("div", { class: "ownedbox" },
    h("div", { class: "sum" },
      h("div", {}, h("div", { class: "lbl2", text: "Value now" }), h("div", { class: "big num", text: eur(value) })),
      h("div", { class: "r" }, h("div", { class: "lbl2", text: "Profit" }), h("div", { class: "prof num" + (profit < 0 ? " neg" : ""), text: `${signedEur(profit)} · ${invested ? signed(profit / invested, 1) : "–"}` })),
      h("div", { class: "inv", text: `Invested ${eur(invested)} · ${items.reduce((s, c) => s + c.quantity, 0)} pcs` })),
    (() => {   // Advies: kaarten om te verkopen of die verdacht zijn, bovenaan, met de korte reden
      const list = groups().map((g) => ({ g, a: adviceOf(g) })).filter((x) => x.a.tone !== "hold")
        .sort((x, y) => ({ sell: 0, buy: 1, warn: 2 }[x.a.tone] - { sell: 0, buy: 1, warn: 2 }[y.a.tone]) || y.g._value - x.g._value);
      if (!list.length) return null;
      const body = h("ul", { class: "advlist", hidden: !ui.adviceOpen }, ...list.map(({ g, a }) => h("li", {},
        h("button", { type: "button", class: "advrow", onclick: () => go(detailHash(g.product_id, g.copies[0].id)) },
          thumb(g.image, "ph", g.kind === "sealed"),
          h("span", { class: "bl" }, h("b", { text: g.name }), h("span", {}, adviceChip(a))),
          moveCell({ value: eur(g._value), outlook: outlookOf(g) })))));
      const sell = list.filter((x) => x.a.tone === "sell").length, buy = list.filter((x) => x.a.tone === "buy").length, warn = list.length - sell - buy;
      return h("div", { class: "attn" },
        h("button", { class: "attnhead", type: "button", onclick: (e) => { ui.adviceOpen = !ui.adviceOpen; saveUi(); body.hidden = !ui.adviceOpen; e.currentTarget.querySelector(".icw").replaceWith(icon("chev", ui.adviceOpen ? "flip" : "")); } },
          h("h3", { text: `Advice: ${[sell ? `${sell}× sell now` : "", buy ? `${buy}× buy more` : "", warn ? `${warn}× caution` : ""].filter(Boolean).join(", ")}` }), icon("chev", ui.adviceOpen ? "flip" : "")),
        body);
    })(),
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
              h("span", {}, h("b", { text: `Purchase ${i + 1}` })),
              h("span", { class: "num", text: eur(costEach(it)) })));
            wrap.append(h("div", { class: "copies" }, ...copyRows));
          }
          return wrap;
        }));
      };
      const box = h("div", { class: "attn" }, h("button", { class: "attnhead", type: "button", onclick: () => { ui.attentionOpen = !ui.attentionOpen; saveUi(); drawAttn(); } }, h("h3", { text: `Needs attention (${attn.length})` }), icon("chev", ui.attentionOpen ? "flip" : "")), body);
      drawAttn(); return box;
    })() : null,
    h("div", { class: "chartcard" }, segment(RANGES, ui.range, (r) => { ui.range = r; saveUi(); drawChart(); }, "small"), chartBox),
    h("div", { class: "searchrow" }, searchBar.box),
    h("div", { class: "stick" }, segment([["alles", "All"], ["card", "Cards"], ["sealed", "Sealed"]], ui.kind, (k) => { ui.kind = k; saveUi(); drawList(); }), sortBtn),
    countNote,
    list),
    selBar, fab));
  drawList();
  drawSel();
  if (items.length) drawChart(); else chartBox.parentElement.hidden = true;
}
