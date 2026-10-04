// Overzicht 'Verkocht': elke verkoop als bestelling, met je echte winst, plus export naar CSV.
import { rest, userId } from "../api.js";
import { emptyNote } from "../components.js";
import { allocate, saleProfit } from "../model.js";
import { eur, fmtDateLong, h, signedEur, toast } from "../ui.js";

export async function loadSales() {
  const [sales, items] = await Promise.all([
    rest.get("sales?select=*&order=sale_date.desc,created_at.desc"),
    rest.get("sale_items?select=*"),
  ]);
  const ids = [...new Set(items.map((i) => i.product_id))];
  const products = ids.length ? await rest.get(`products?select=product_id,name,set_name,number,kind&product_id=in.(${ids.map(encodeURIComponent).join(",")})`) : [];
  const prod = new Map(products.map((p) => [p.product_id, p]));
  const bySale = new Map();
  for (const it of items) {
    if (!bySale.has(it.sale_id)) bySale.set(it.sale_id, []);
    bySale.get(it.sale_id).push({ ...it, ...(prod.get(it.product_id) || { name: it.product_id }), price_share: Number(it.price_share), cost_total: Number(it.cost_total) });
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
  const head = ["Bestelnummer", "Datum", "Koper", "Kaart", "Set", "Nummer", "Staat", "Aantal", "Verkoopprijs", "Commissie",
    "Verzending ontvangen", "Verzending betaald", "Overige kosten", "Kostprijs", "Winst"];
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
  const a = h("a", { href: url, download: `pokedeals-verkopen-${new Date().toISOString().slice(0, 10)}.csv` });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast("CSV opgeslagen");
}

/** Verkoop terugdraaien: de kaarten komen terug in 'In bezit' tegen hun kostprijs, en de verkoop verdwijnt. */
async function undoSale(s, onChange) {
  if (!confirm(`Verkoop aan ${s.buyer || "onbekende koper"} van ${fmtDateLong(s.sale_date)} terugdraaien? De kaarten komen terug in je collectie.`)) return;
  try {
    await rest.insert("collection", s.lines.map((l) => ({ user_id: userId(), product_id: l.product_id, quantity: l.quantity,
      condition: l.condition || null, grade_company: l.grade_company || null, grade: l.grade || null,
      purchase_price: Math.round((l.cost_total / l.quantity) * 100) / 100, purchase_date: l.purchase_date || s.sale_date })));
    await rest.del("sales", `id=eq.${s.id}`);
    toast("Verkoop teruggedraaid");
    onChange?.();
  } catch (e) { console.error(e); toast("Terugdraaien mislukte"); }
}

export async function renderSales(box, { onChange } = {}) {
  box.replaceChildren(h("p", { class: "muted pad", text: "Laden…" }));
  let sales;
  try { sales = await loadSales(); } catch (e) { console.error(e); box.replaceChildren(h("p", { class: "err pad", text: "Kon je verkopen niet laden." })); return; }
  if (!sales.length) {
    box.replaceChildren(emptyNote("Nog geen verkopen. Kies bij 'In bezit' de knop Verkopen om er een vast te leggen."));
    return;
  }
  const month = new Date().toISOString().slice(0, 7);
  const total = sales.reduce((t, s) => t + s.profit.total, 0);
  const thisMonth = sales.filter((s) => s.sale_date.startsWith(month)).reduce((t, s) => t + s.profit.total, 0);
  const revenue = sales.reduce((t, s) => t + Number(s.total_price), 0);
  box.replaceChildren(
    h("div", { class: "sum" },
      h("div", {}, h("div", { class: "lbl2", text: "Winst totaal" }), h("div", { class: "big num " + (total < 0 ? "neg" : ""), text: signedEur(total) })),
      h("div", { class: "r" }, h("div", { class: "lbl2", text: "Deze maand" }), h("div", { class: "prof num" + (thisMonth < 0 ? " neg" : ""), text: signedEur(thisMonth) })),
      h("div", { class: "inv", text: `${sales.length} ${sales.length === 1 ? "verkoop" : "verkopen"} · ${eur(revenue)} omzet` })),
    h("div", { class: "more" }, h("button", { type: "button", text: "Exporteer als CSV", onclick: () => downloadCsv(sales) })),
    h("div", { class: "salelist" }, ...sales.map((s) => h("div", { class: "sec salecard" },
      h("div", { class: "salehead" },
        h("div", {}, h("b", { text: s.buyer || "Onbekende koper" }), h("div", { class: "mini", text: fmtDateLong(s.sale_date) })),
        h("b", { class: "num " + (s.profit.total < 0 ? "neg" : "pos"), text: signedEur(s.profit.total) })),
      h("ul", { class: "salelines" }, ...s.lines.map((l, i) => h("li", {},
        h("span", { text: `${l.quantity > 1 ? l.quantity + "x " : ""}${l.name}` }),
        h("span", { class: "num", text: `${eur(l.price_share)} (${signedEur(s.profit.per[i])})` })))),
      h("div", { class: "mini", text: `Ontvangen ${eur(Number(s.total_price) + Number(s.shipping_received))} · commissie ${eur(Number(s.commission))} · verzending ${eur(Number(s.shipping_paid))} · overig ${eur(Number(s.other_costs))}` }),
      h("button", { type: "button", class: "linkbtn", text: "Verkoop terugdraaien", onclick: () => undoSale(s, onChange) })))));
}
