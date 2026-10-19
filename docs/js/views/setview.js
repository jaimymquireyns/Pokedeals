// Setpagina: alles uit één set, zoals op Cardmarket, verdeeld in Singles, ETB's, Bundles, Booster boxes, Box sets en Other.
// Elke categorie is apart te sorteren. Bereikbaar via Zoeken (een set intypen) of #/set/<set_id>.
import { rest } from "../api.js";
import { brandmark, detailHash, emptyNote, go } from "../components.js";
import { eur, fmtDate, h, segment, store, thumb } from "../ui.js";

/** Soort sealed product uit de productnaam (en de categorie van Cardmarket als die er is). */
export function sealedGroup(name, productType = "") {
  const t = `${name || ""} ${productType || ""}`.toLowerCase();
  if (/elite trainer box|\betb\b/.test(t)) return "etb";
  if (/booster bundle|\bbundle\b/.test(t)) return "bundle";
  if (/booster box|\bdisplay\b|booster display/.test(t)) return "boosterbox";
  if (/collection|premium|box set|\bbox\b|\btin\b|blister|build & battle|build and battle/.test(t)) return "boxset";
  return "other";
}

export const GROUPS = [["singles", "Singles"], ["etb", "ETBs"], ["bundle", "Bundles"], ["boosterbox", "Booster boxes"], ["boxset", "Box sets"], ["other", "Other"]];
const SORTS = {
  singles: [["number", "Number"], ["high", "Price ↓"], ["low", "Price ↑"], ["name", "Name"]],
  sealed: [["high", "Price ↓"], ["low", "Price ↑"], ["name", "Name"]],
};
const num = (x) => { const m = String(x || "").match(/\d+/); return m ? Number(m[0]) : 1e9; };
export const ORDER = {
  number: (a, b) => num(a.number) - num(b.number) || String(a.number).localeCompare(String(b.number)),
  high: (a, b) => (Number(b.price) || 0) - (Number(a.price) || 0),
  low: (a, b) => (Number(a.price) || Infinity) - (Number(b.price) || Infinity),
  name: (a, b) => String(a.name).localeCompare(String(b.name)),
};

/** Verdeelt de producten van een set over de groepen. */
export function groupRows(rows, types = {}) {
  const out = Object.fromEntries(GROUPS.map(([k]) => [k, []]));
  for (const r of rows) out[r.kind === "sealed" ? sealedGroup(r.name, types[r.product_id]) : "singles"].push(r);
  return out;
}

export async function setView(root, setId) {
  const page = h("div", { class: "page" }, brandmark(), h("p", { class: "muted pad", text: "Loading…" }));
  root.replaceChildren(page);
  const sets = await rest.get(`sets?select=set_id,name,release_date,card_total&set_id=eq.${encodeURIComponent(setId)}`).catch(() => []);
  const set = sets[0] || { set_id: setId, name: setId };
  const enc = encodeURIComponent;
  // kaarten op set_id; sealed hangt soms alleen op de setnaam (Cardmarket-producten), dus beide
  const [byId, byName] = await Promise.all([
    rest.get(`products?select=product_id,kind,name,number,image,product_type&set_id=eq.${enc(setId)}&limit=2000`).catch(() => []),
    set.name ? rest.get(`products?select=product_id,kind,name,number,image,product_type&set_name=eq.${enc(set.name)}&kind=eq.sealed&limit=500`).catch(() => []) : [],
  ]);
  const prods = new Map([...byId, ...byName].map((p) => [p.product_id, p]));
  const ids = [...prods.keys()];
  const price = new Map();
  for (let i = 0; i < ids.length; i += 80) {
    const list = ids.slice(i, i + 80).map((x) => `"${x}"`).join(",");
    for (const r of await rest.get(`v_search?select=product_id,price&product_id=in.(${enc(list)})`).catch(() => [])) price.set(r.product_id, r.price);
  }
  const rows = [...prods.values()].map((p) => ({ ...p, set_name: set.name, price: price.get(p.product_id) }));
  const types = Object.fromEntries(rows.map((r) => [r.product_id, r.product_type]));
  const groups = groupRows(rows, types);
  const present = GROUPS.filter(([k]) => groups[k].length);
  const saved = store.get("pd:setview", {});
  let tab = present.some(([k]) => k === saved.tab) ? saved.tab : (present[0] || ["singles"])[0];
  const sorts = { ...{ singles: "number" }, ...(saved.sorts || {}) };
  const list = h("ul", { class: "list setlist" });
  const sortBox = h("div", { class: "bar" });
  const tabs = h("div", { class: "hometabs settabs", role: "tablist" });

  const row = (r) => h("li", {}, h("button", { class: "row", type: "button", onclick: () => go(detailHash(r.product_id)) },
    thumb(r.image, "ph", r.kind === "sealed"),
    h("div", { class: "body" },
      h("div", { class: "l1" }, h("span", { class: "name", text: r.name }), h("span", { class: "price num", text: r.price ? eur(Number(r.price)) : "–" })),
      h("div", { class: "l2" }, h("span", { class: "set", text: r.kind === "card" && r.number ? `#${r.number}` : (GROUPS.find(([k]) => k === sealedGroup(r.name, r.product_type)) || [, ""])[1] })))));

  function draw() {
    store.set("pd:setview", { tab, sorts });
    tabs.replaceChildren(...present.map(([k, label]) => h("button", { type: "button", role: "tab", class: "hometab", "aria-selected": String(k === tab),
      onclick: () => { tab = k; draw(); } }, h("span", { class: "lbl", text: label }), h("span", { class: "cnt", text: String(groups[k].length) }))));
    const opts = tab === "singles" ? SORTS.singles : SORTS.sealed;
    const cur = opts.some(([v]) => v === sorts[tab]) ? sorts[tab] : opts[0][0];
    sortBox.replaceChildren(segment(opts, cur, (v) => { sorts[tab] = v; draw(); }, "small"));
    const items = [...(groups[tab] || [])].sort(ORDER[cur]);
    list.replaceChildren(...(items.length ? items.map(row) : [emptyNote("Nothing in this category.")]));
  }

  page.replaceChildren(brandmark(),
    h("div", { class: "head" }, h("button", { class: "linkbtn back", type: "button", text: "‹ Back", onclick: () => history.back() }), h("h1", { text: set.name || setId })),
    h("p", { class: "homesum", text: [set.release_date ? `Released ${fmtDate(set.release_date)}` : "", `${groups.singles.length} singles`, `${rows.length - groups.singles.length} sealed`].filter(Boolean).join(" · ") }),
    present.length ? tabs : null, present.length ? sortBox : null, present.length ? list : emptyNote("Nothing found for this set."));
  if (present.length) draw();
}
