import { isLoggedIn, rest } from "../api.js";
import { SET_ALIASES, searchCards } from "../cardsearch.js";
import { addForm } from "../add.js";
import { brandmark, detailHash, emptyNote, go, kindTag } from "../components.js";
import { openScan } from "../scan.js";
import { debounce, eur, h, icon, openSheet, closeSheet, segment, thumb, toast } from "../ui.js";

let state = { q: "", kind: "alles" };
let allSets = null;
const normq = (x) => String(x || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, " ").trim();

/** Sets die bij de zoektekst passen: een bekende afkorting ('pre', '151', 'obf') of een stuk van de setnaam. Nieuwste eerst. */
export function matchSets(q, sets, aliases = SET_ALIASES) {
  const nq = normq(q);
  if (nq.length < 2) return [];
  const alias = aliases[nq] ? normq(aliases[nq]) : null;
  const hits = sets.filter((s) => {
    const n = normq(s.name), id = normq(s.set_id);
    return (alias && n.includes(alias)) || n === nq || id === nq || (nq.length >= 3 && !/^\d+$/.test(nq) && n.includes(nq));
  });
  return hits.sort((a, b) => String(b.release_date || "").localeCompare(String(a.release_date || ""))).slice(0, 4);
}

export async function searchView(root) {
  const input = h("input", { type: "search", placeholder: "Search name, set or number", value: state.q, "aria-label": "Search", autocomplete: "off" });
  const list = h("ul", { class: "list" });
  const owned = new Map();

  const need = () => {
    if (isLoggedIn()) return true;
    toast("Log in first to use your collection");
    go("#/login?next=" + encodeURIComponent("#/search"));
    return false;
  };
  const addSheet = (row) => {
    if (!need()) return;
    openSheet(h("div", { class: "sheetin" }, h("div", { class: "handle" }), addForm(row, { onDone: () => { closeSheet(); owned.set(row.product_id, (owned.get(row.product_id) || 0) + 1); draw(); } })));
  };

  let rows = [], setHits = [];
  const setRow = (st) => h("li", {}, h("button", { class: "row setrow", type: "button", onclick: () => go(`#/set/${encodeURIComponent(st.set_id)}`) },
    h("span", { class: "ph setph", text: "SET" }),
    h("div", { class: "body" },
      h("div", { class: "l1" }, h("span", { class: "name", text: st.name }), h("span", { class: "price", text: "›" })),
      h("div", { class: "l2" }, h("span", { class: "set", text: [st.release_date ? String(st.release_date).slice(0, 4) : "", "Singles, ETBs, bundles, boxes"].filter(Boolean).join(" · ") })))));
  const draw = () => {
    if (!state.q.trim()) { list.replaceChildren(emptyNote("Type a name, set or number, e.g. \"charizard 30th 4\", or a set like \"prismatic\" to see all its singles and sealed. Or scan a card with the camera.")); return; }
    list.replaceChildren(...setHits.map(setRow), ...(rows.length ? rows.map((r) => {
      const n = owned.get(r.product_id);
      return h("li", {}, h("div", { class: "resrow" },
        h("button", { class: "row", type: "button", onclick: () => go(detailHash(r.product_id)) },
          thumb(r.image, "ph", r.kind === "sealed"),
          h("div", { class: "body" },
            h("div", { class: "l1" }, h("span", { class: "name", text: r.name }), h("span", { class: "price num", text: r.price ? eur(Number(r.price)) : "–" })),
            h("div", { class: "l2" }, h("span", { class: "set", text: (r.set_name || "") + (r.number && r.kind === "card" ? ` #${r.number}` : "") }), kindTag(r.kind)),
            r.cm_name && r.kind === "card" && /\(.+\)/.test(r.cm_name) && r.cm_name.toLowerCase() !== String(r.name).toLowerCase() ? h("div", { class: "set cmn", text: `Cardmarket: ${r.cm_name}` }) : null)),
        h("button", { class: "addb" + (n ? " done" : ""), type: "button", "aria-label": n ? "Add another" : "Add to collection", onclick: () => addSheet(r) }, icon(n ? "check" : "plus"))));
    }) : (setHits.length ? [] : [emptyNote("Nothing found.")])));
    const d = rows.debug;
    if (d && state.q.trim()) {   // hoe de zoekopdracht gelezen is: zo zie je meteen of het lezen of de data het probleem is
      list.append(h("li", { class: "readas" }, `Read as: name "${d.name}"${d.set ? ` · set "${d.set}"` : ""}${d.numbers.length ? ` · number ${d.numbers.join(" / ")}` : ""}. Found via: ${d.via || "–"} (${d.found} rows).`));
    }
  };



  const run = debounce(async () => {
    const kind = state.kind === "alles" ? "" : `&kind=eq.${state.kind}`;
    const raw = state.q.trim();
    if (!raw) { rows = []; draw(); return; }
    try {
      if (!allSets) allSets = await rest.get("sets?select=set_id,name,release_date").catch(() => []);
      setHits = matchSets(raw, allSets);
      rows = await searchCards(raw, { kind: state.kind });
    } catch { rows = []; list.replaceChildren(emptyNote("Search failed. Check your connection.")); return; }
    draw();
  }, 250);

  input.oninput = () => { state.q = input.value; run(); };
  root.replaceChildren(h("div", { class: "page" },
    brandmark(),
    h("div", { class: "head" }, h("h1", { text: "Search" })),
    h("div", { class: "searchrow" }, h("label", { class: "sbox" }, icon("search"), input),
      h("button", { class: "camb", type: "button", "aria-label": "Scan card with camera", onclick: () => { if (need()) openScan({ onAdded: () => run() }); } }, icon("camera"))),
    h("div", { class: "bar" }, segment([["alles", "All"], ["card", "Cards"], ["sealed", "Sealed"]], state.kind, (v) => { state.kind = v; run(); })),
    list));
  draw();
  if (state.q) run();
  if (isLoggedIn()) {
    try { for (const r of await rest.get("collection?select=product_id,quantity")) owned.set(r.product_id, (owned.get(r.product_id) || 0) + r.quantity); draw(); } catch { /* geen collectie-info */ }
  }
}
