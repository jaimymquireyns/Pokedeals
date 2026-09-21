import { isLoggedIn, rest } from "../api.js";
import { addForm } from "../add.js";
import { detailHash, emptyNote, go, kindTag } from "../components.js";
import { openScan } from "../scan.js";
import { debounce, eur, h, icon, openSheet, closeSheet, segment, thumb, toast } from "../ui.js";

let state = { q: "", kind: "alles" };

export async function searchView(root) {
  const input = h("input", { type: "search", placeholder: "Zoek kaart, sealed of set", value: state.q, "aria-label": "Zoeken", autocomplete: "off" });
  const list = h("ul", { class: "list" });
  const owned = new Map();

  const need = () => {
    if (isLoggedIn()) return true;
    toast("Log eerst in om je collectie te gebruiken");
    go("#/login?next=" + encodeURIComponent("#/search"));
    return false;
  };
  const addSheet = (row) => {
    if (!need()) return;
    openSheet(h("div", { class: "sheetin" }, h("div", { class: "handle" }), addForm(row, { onDone: () => { closeSheet(); owned.set(row.product_id, (owned.get(row.product_id) || 0) + 1); draw(); } })));
  };

  let rows = [];
  const draw = () => {
    if (!state.q.trim()) { list.replaceChildren(emptyNote("Typ een naam of set. Of gebruik de camera om een kaart te scannen.")); return; }
    list.replaceChildren(...(rows.length ? rows.map((r) => {
      const n = owned.get(r.product_id);
      return h("li", {}, h("div", { class: "resrow" },
        h("button", { class: "row", type: "button", onclick: () => go(detailHash(r.product_id)) },
          thumb(r.image, "ph", r.kind === "sealed"),
          h("div", { class: "body" },
            h("div", { class: "l1" }, h("span", { class: "name", text: r.name }), h("span", { class: "price num", text: r.price ? eur(Number(r.price)) : "–" })),
            h("div", { class: "l2" }, h("span", { class: "set", text: (r.set_name || "") + (r.number && r.kind === "card" ? ` #${r.number}` : "") }), kindTag(r.kind)))),
        h("button", { class: "addb" + (n ? " done" : ""), type: "button", "aria-label": n ? "Nog een toevoegen" : "Toevoegen aan collectie", onclick: () => addSheet(r) }, icon(n ? "check" : "plus"))));
    }) : [emptyNote("Niets gevonden.")]));
  };

  const run = debounce(async () => {
    const words = state.q.replace(/[*,()%]/g, " ").trim().split(/\s+/).filter(Boolean);
    if (!words.length) { rows = []; draw(); return; }
    const pat = encodeURIComponent(words.join("*"));
    const kind = state.kind === "alles" ? "" : `&kind=eq.${state.kind}`;
    try {
      rows = await rest.get(`v_search?select=*&or=(name.ilike.*${pat}*,set_name.ilike.*${pat}*)${kind}&order=price.desc.nullslast&limit=40`);
    } catch { rows = []; list.replaceChildren(emptyNote("Zoeken lukte niet. Controleer je verbinding.")); return; }
    draw();
  }, 250);

  input.oninput = () => { state.q = input.value; run(); };
  root.replaceChildren(h("div", { class: "page" },
    h("div", { class: "head" }, h("h1", { text: "Zoeken" })),
    h("div", { class: "searchrow" }, h("label", { class: "sbox" }, icon("search"), input),
      h("button", { class: "camb", type: "button", "aria-label": "Kaart scannen met de camera", onclick: () => { if (need()) openScan({ onAdded: () => run() }); } }, icon("camera"))),
    h("div", { class: "bar" }, segment([["alles", "Alles"], ["card", "Kaarten"], ["sealed", "Sealed"]], state.kind, (v) => { state.kind = v; run(); })),
    list));
  draw();
  if (state.q) run();
  if (isLoggedIn()) {
    try { for (const r of await rest.get("collection?select=product_id,quantity")) owned.set(r.product_id, (owned.get(r.product_id) || 0) + r.quantity); draw(); } catch { /* geen collectie-info */ }
  }
}
