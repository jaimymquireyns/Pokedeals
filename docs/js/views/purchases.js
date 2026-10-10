// Pagina 'Gekocht': al je aankopen als bestelling (verkoper, datum, kaarten, wat je betaalde), ook van kaarten die je al verkocht hebt.
// Kaarten die je nog hebt, kun je hier aanpassen of verwijderen; verkochte kaarten pas je aan bij hun verkoop.
import { rest } from "../api.js";
import { emptyNote, extras, filterBox, go, gradeTag, matchQuery } from "../components.js";
import { costEach } from "../model.js";
import { openPurchaseEdit, openPurchaseOrder } from "../orders.js";
import { loadSales } from "./sales.js";
import { closeSheet, eur, fmtDateLong, h, icon, openSheet, store, thumb } from "../ui.js";

const SORTS = [["new", "Newest first"], ["old", "Oldest first"], ["high", "Highest amount"], ["low", "Lowest amount"]];

/** Zet collectieregels (nog in bezit) en verkochte regels om in aankopen. Zelfde purchase_order = zelfde aankoop; zonder
 * bestelnummer is elke regel een eigen aankoop. Geëxporteerd voor de tests. */
export function groupPurchases(owned, sold) {
  const m = new Map();
  const add = (key, base) => { if (!m.has(key)) m.set(key, { key, seller: base.seller, date: base.date, created: base.created || "", owned: [], sold: [] }); return m.get(key); };
  for (const r of owned) {
    const g = add(r.purchase_order ? `o:${r.purchase_order}` : `c:${r.id}`, { seller: r.purchase_seller, date: r.purchase_date, created: r.created_at });
    g.owned.push(r);
    if (!g.seller && r.purchase_seller) g.seller = r.purchase_seller;
    if (String(r.created_at || "") > g.created) g.created = String(r.created_at || "");
  }
  for (const l of sold) {
    const g = add(l.purchase_order ? `o:${l.purchase_order}` : `s:${l.id}`, { seller: l.purchase_seller, date: l.purchase_date || l.sale_date, created: "" });
    g.sold.push(l);
    if (!g.seller && l.purchase_seller) g.seller = l.purchase_seller;
  }
  return [...m.values()].map((g) => ({
    ...g,
    total: Math.round((g.owned.reduce((t, r) => t + costEach(r) * Number(r.quantity), 0) + g.sold.reduce((t, l) => t + Number(l.cost_total || 0), 0)) * 100) / 100,
    pieces: g.owned.reduce((t, r) => t + Number(r.quantity), 0) + g.sold.reduce((t, l) => t + Number(l.quantity), 0),
  }));
}

export async function purchasesView(root) {
  root.replaceChildren(h("div", { class: "page" }, h("div", { class: "head" }, h("h1", { text: "Bought" }), h("p", { class: "muted", text: "Loading…" }))));
  let owned, sales;
  try {
    [owned, sales] = await Promise.all([
      rest.get("v_collection?select=id,product_id,quantity,condition,grade_company,grade,language,variant,purchase_price,purchase_shipping,purchase_costs,purchase_seller,purchase_order,purchase_date,created_at,name,set_name,number,image,kind"),
      loadSales(),
    ]);
  } catch (e) { console.error(e); root.replaceChildren(h("p", { class: "err pad", text: "Couldn't load your purchases. Check your connection." })); return; }
  const sold = sales.flatMap((s) => s.lines.map((l) => ({ ...l, sale_date: s.sale_date, buyer: s.buyer })));
  const all = groupPurchases(owned, sold);
  const reload = () => purchasesView(root);

  const ui = { sort: "new", ...store.get("pd:buys", {}) };
  const saveUi = () => store.set("pd:buys", ui);
  let query = "";
  const sumBox = h("div");
  const list = h("ul", { class: "list buylist" });
  const countNote = h("p", { class: "mini fcount", hidden: true });
  const search = filterBox("Search seller, card or set", (v) => { query = v; draw(); });
  const sortBtn = h("button", { class: "sortb", type: "button", onclick: () => {
    const opts = h("div", { class: "opts" }, ...SORTS.map(([k, label]) => h("button", { type: "button", class: "opt", "aria-pressed": String(ui.sort === k),
      onclick: () => { ui.sort = k; saveUi(); closeSheet(); draw(); } }, h("span", { text: label }), ui.sort === k ? icon("check") : null)));
    openSheet(h("div", { class: "sheetin" }, h("div", { class: "handle" }), h("h3", { text: "Sort" }), opts));
  } });
  const cmp = {
    new: (a, b) => String(b.date || "").localeCompare(String(a.date || "")) || b.created.localeCompare(a.created),
    old: (a, b) => String(a.date || "").localeCompare(String(b.date || "")) || a.created.localeCompare(b.created),
    high: (a, b) => b.total - a.total, low: (a, b) => a.total - b.total,
  };

  const lineRow = (name, sub, right, extra = null) => h("li", {},
    h("span", { class: "bl" }, h("b", { text: name }), extra, sub ? h("small", { text: sub }) : null), h("span", { class: "num", text: right }));
  const card = (g) => {
    const shipping = g.owned.reduce((t, r) => t + Number(r.purchase_shipping || 0) + Number(r.purchase_costs || 0), 0);
    return h("li", { class: "sec salecard buycard" },
      h("div", { class: "salehead" },
        h("div", {}, h("b", { text: g.seller || "Unknown seller" }), h("div", { class: "mini", text: [g.date ? fmtDateLong(g.date) : "", `${g.pieces} ${g.pieces === 1 ? "pc" : "pcs"}`].filter(Boolean).join(" · ") })),
        h("b", { class: "num", text: eur(g.total) })),
      h("ul", { class: "salelines buylines" },
        ...g.owned.map((r) => h("li", {},
          h("button", { type: "button", class: "buyline", onclick: () => go(`#/detail/${encodeURIComponent(r.product_id)}?c=${r.id}`) },
            thumb(r.image, "ph", r.kind === "sealed"),
            h("span", { class: "bl" }, h("b", { text: `${r.quantity > 1 ? r.quantity + "x " : ""}${r.name}` }), gradeTag(r),
              h("small", { text: [r.set_name, r.number && r.kind === "card" ? `#${r.number}` : "", r.kind === "card" && !r.grade_company ? r.condition : "", ...extras(r)].filter(Boolean).join(" · ") })),
            h("span", { class: "num", text: eur(Number(r.purchase_price) * Number(r.quantity)) })))),
        ...g.sold.map((l) => h("li", {},
          h("div", { class: "buyline" },
            thumb(l.image, "ph", l.kind === "sealed"),
            h("span", { class: "bl" }, h("b", { text: `${l.quantity > 1 ? l.quantity + "x " : ""}${l.name}` }), h("span", { class: "soldtag", text: "sold" }),
              h("small", { text: [l.set_name, l.buyer ? `to ${l.buyer}` : "", l.sale_date ? fmtDateLong(l.sale_date) : ""].filter(Boolean).join(" · ") })),
            h("span", { class: "num", text: eur(Number(l.cost_total)) }))))),
      shipping ? h("div", { class: "mini", text: `Incl. shipping and trustee fee ${eur(shipping)}` }) : null,
      g.owned.length
        ? h("div", { class: "saleacts" }, h("button", { type: "button", class: "btn act", onclick: () => openPurchaseEdit(g.owned, reload) }, "Edit"),
            g.sold.length ? h("span", { class: "mini", text: "Edit sold cards under Sold." }) : null)
        : h("div", { class: "saleacts" }, h("button", { type: "button", class: "linkbtn", text: "Edit under Sold", onclick: () => go("#/verkocht") })));
  };

  function draw() {
    sortBtn.replaceChildren(icon("sort"), h("span", { text: "Sort" }));
    sortBtn.setAttribute("aria-label", "Sort, now: " + SORTS.find((x) => x[0] === ui.sort)[1]);
    const q = query.trim();
    const vis = all.filter((g) => matchQuery(q, [g.seller, g.date, ...g.owned.flatMap((r) => [r.name, r.set_name, r.number]), ...g.sold.flatMap((l) => [l.name, l.set_name, l.number])],
      [...g.owned, ...g.sold].map((x) => x.set_name).join(" "))).sort(cmp[ui.sort] || cmp.new);
    countNote.hidden = !q;
    countNote.textContent = `${vis.length} of ${all.length} purchases`;
    const spent = vis.reduce((t, g) => t + g.total, 0);
    sumBox.replaceChildren(all.length ? h("div", { class: "sum" },
      h("div", {}, h("div", { class: "lbl2", text: q ? "Spent (filtered)" : "Total spent" }), h("div", { class: "big num", text: eur(spent) })),
      h("div", { class: "r" }, h("div", { class: "lbl2", text: "Purchases" }), h("div", { class: "prof num", text: String(vis.length) })),
      h("div", { class: "inv", text: `${vis.reduce((t, g) => t + g.pieces, 0)} pcs, including what you've sold` })) : "");
    list.replaceChildren(...(vis.length ? vis.map(card) : [emptyNote(q ? `Nothing found for "${q}".` : "No purchases yet. Add one with the Purchase button.")]));
  }

  root.replaceChildren(h("div", { class: "page" },
    h("div", { class: "topbar" }, h("button", { class: "back", type: "button", onclick: () => go("#/collection") }, icon("back"), h("span", { text: "Collection" }))),
    h("div", { class: "head headrow" }, h("div", {}, h("h1", { text: "Bought" }), h("p", { class: "muted", text: "All your purchases. Tap Edit to fix a mistake." })),
      h("button", { type: "button", class: "btn act", onclick: () => openPurchaseOrder({ onDone: reload }) }, icon("plus"), " Purchase")),
    sumBox,
    h("div", { class: "searchrow" }, search.box),
    h("div", { class: "bar barend" }, sortBtn),
    countNote, list));
  draw();
}
