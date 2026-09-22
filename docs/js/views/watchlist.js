// Watchlist: kaarten en sealed producten die je volgt, met eigen mappen (een kaart mag in meerdere mappen staan).
import { isLoggedIn, rest, userId } from "../api.js";
import { chanceBar, detailHash, emptyNote, go, kindTag } from "../components.js";
import { closeSheet, debounce, eur, h, icon, num, openSheet, pp, segment, signed, store, thumb, toast } from "../ui.js";

let ui = { folder: "alles", sort: "az", ...store.get("pd:watch", {}) };
const saveUi = () => store.set("pd:watch", ui);
const SORTS = [["az", "A–Z"], ["set", "Set en nummer"], ["low", "Laagste prijs"], ["high", "Hoogste prijs"], ["up", "Grootste kans op stijging"], ["down", "Grootste kans op daling"]];
const numCmp = (a, b) => String(a ?? "").localeCompare(String(b ?? ""), "nl", { numeric: true });

export async function watchlistView(root) {
  if (!isLoggedIn()) {
    const { loginView } = await import("./login.js");
    loginView(root, { reason: "Log in om kaarten te volgen.", onDone: () => watchlistView(root) });
    return;
  }
  root.replaceChildren(h("div", { class: "page" }, h("div", { class: "head" }, h("h1", { text: "Watchlist" }), h("p", { class: "muted", text: "Laden…" }))));
  let items, folders, links;
  try {
    [items, folders, links] = await Promise.all([
      rest.get("v_watchlist?select=*&order=created_at.desc"),
      rest.get("watch_folders?select=*&order=name.asc"),
      rest.get("watch_folder_items?select=folder_id,item_id"),
    ]);
  } catch (e) { root.replaceChildren(h("p", { class: "err pad", text: "Kon je watchlist niet laden. Controleer je verbinding." })); console.error(e); return; }
  items = items.map((r) => ({ ...r, value_each: r.value_each == null ? null : Number(r.value_each), p_up: r.p_up == null ? null : Number(r.p_up), p_down: r.p_down == null ? null : Number(r.p_down) }));
  const byFolder = new Map(); // folder_id -> Set(item_id)
  for (const l of links) { if (!byFolder.has(l.folder_id)) byFolder.set(l.folder_id, new Set()); byFolder.get(l.folder_id).add(l.item_id); }
  const itemFolders = (itemId) => folders.filter((f) => byFolder.get(f.id)?.has(itemId));

  const cmp = {
    az: (a, b) => a.name.localeCompare(b.name, "nl"),
    set: (a, b) => (a.set_name || "").localeCompare(b.set_name || "", "nl") || numCmp(a.number, b.number),
    low: (a, b) => (a.value_each ?? Infinity) - (b.value_each ?? Infinity), high: (a, b) => (b.value_each ?? -1) - (a.value_each ?? -1),
    up: (a, b) => (b.p_up ?? -1) - (a.p_up ?? -1), down: (a, b) => (b.p_down ?? -1) - (a.p_down ?? -1),
  };

  const chips = h("div", { class: "fchips" });
  const list = h("ul", { class: "list" });
  const sortBtn = h("button", { class: "sortb", type: "button" });

  const drawChips = () => {
    const opts = [["alles", "Alles"], ...folders.map((f) => [f.id, f.name])];
    chips.replaceChildren(...opts.map(([id, label]) => h("button", { type: "button", class: "fchip" + (ui.folder === id ? " on" : ""),
      onclick: () => { ui.folder = id; saveUi(); drawList(); drawChips(); } }, label)),
      h("button", { type: "button", class: "fchip add", onclick: newFolder }, icon("plus"), " Map"));
  };

  const drawList = () => {
    sortBtn.replaceChildren(icon("sort"), h("span", { text: "Sorteren" }));
    const vis = items.filter((r) => ui.folder === "alles" || byFolder.get(ui.folder)?.has(r.id)).sort(cmp[ui.sort]);
    list.replaceChildren(...(vis.length ? vis.map((r) => row(r)) : [emptyNote(items.length ? "Niets in deze map." : "Nog niets gevolgd. Voeg kaarten toe via Zoeken of een kaartdetail.")]));
  };

  function row(r) {
    const fchips = itemFolders(r.id);
    return h("li", {}, h("div", { class: "wrow" },
      h("button", { class: "row", type: "button", onclick: () => go(detailHash(r.product_id)) },
        thumb(r.image, "ph", r.kind === "sealed"),
        h("div", { class: "body" },
          h("div", { class: "l1" }, h("span", { class: "name", text: r.name }), h("span", { class: "price num", text: r.value_each ? eur(r.value_each) : "–" })),
          h("div", { class: "l2" }, h("span", { class: "set", text: (r.set_name || "") + (r.number && r.kind === "card" ? ` #${r.number}` : "") }), kindTag(r.kind)),
          r.p_up != null ? h("div", { class: "l3" }, h("b", { text: pp(r.p_up) }), h("span", { class: "lbl", text: "kans" }),
            h("div", { class: "bar1" }, h("i", { style: `width:${Math.min(r.p_up * 100, 100)}%` })),
            fchips.length ? h("span", { class: "fmini", text: fchips.map((f) => f.name).join(", ") }) : null) : null)),
      h("button", { class: "morebtn", type: "button", "aria-label": "Mappen en verwijderen", onclick: () => manage(r, fchips) }, icon("folder"))));
  }

  function manage(r, current) {
    const checks = folders.map((f) => {
      const on0 = current.some((c) => c.id === f.id);
      const cb = h("input", { type: "checkbox", checked: on0 || null });
      cb.onchange = async () => {
        try {
          if (cb.checked) { await rest.insert("watch_folder_items", [{ folder_id: f.id, item_id: r.id }]); (byFolder.get(f.id) || byFolder.set(f.id, new Set()).get(f.id)).add(r.id); }
          else { await rest.del("watch_folder_items", `folder_id=eq.${f.id}&item_id=eq.${r.id}`); byFolder.get(f.id)?.delete(r.id); }
          drawList();
        } catch { toast("Aanpassen mislukte"); cb.checked = !cb.checked; }
      };
      return h("label", { class: "chkrow" }, cb, h("span", { text: f.name }));
    });
    openSheet(h("div", { class: "sheetin" }, h("div", { class: "handle" }), h("h3", { text: r.name }),
      folders.length ? h("div", {}, h("p", { class: "lbl2", text: "In mappen" }), ...checks) : h("p", { class: "p14 muted", text: "Je hebt nog geen mappen. Maak er een via 'Map' boven de lijst." }),
      h("button", { type: "button", class: "btn del", text: "Verwijderen uit watchlist", onclick: async () => {
        closeSheet();
        try { await rest.del("watch_items", `id=eq.${r.id}`); items = items.filter((x) => x.id !== r.id); toast("Verwijderd"); drawList(); }
        catch { toast("Verwijderen mislukte"); }
      } })));
  }

  function newFolder() {
    const input = h("input", { type: "text", placeholder: "Naam van de map", "aria-label": "Naam van de map", maxlength: 40 });
    const err = h("p", { class: "err" });
    const save = h("button", { type: "button", class: "cta", text: "Map maken" });
    save.onclick = async () => {
      const name = input.value.trim();
      if (!name) { err.textContent = "Vul een naam in."; return; }
      save.disabled = true;
      try {
        const [f] = await rest.insert("watch_folders", [{ user_id: userId(), name }]);
        folders.push(f); folders.sort((a, b) => a.name.localeCompare(b.name, "nl"));
        closeSheet(); drawChips();
      } catch (e) { err.textContent = String(e.message).includes("409") || String(e.message).includes("23505") ? "Die naam heb je al." : "Aanmaken mislukte."; save.disabled = false; }
    };
    openSheet(h("div", { class: "sheetin" }, h("div", { class: "handle" }), h("h3", { text: "Nieuwe map" }), input, err, save));
    input.focus();
  }

  root.replaceChildren(h("div", { class: "page" },
    h("div", { class: "head" }, h("h1", { text: "Watchlist" })),
    chips,
    h("div", { class: "bar" }, h("span", { class: "muted", text: `${items.length} ${items.length === 1 ? "kaart" : "kaarten"}` }), sortBtn),
    list));
  drawChips(); drawList();

  sortBtn.onclick = () => {
    const opts = h("div", { class: "opts" }, ...SORTS.map(([k, label]) => h("button", { type: "button", class: "opt", "aria-pressed": String(ui.sort === k),
      onclick: () => { ui.sort = k; saveUi(); closeSheet(); drawList(); } }, h("span", { text: label }), ui.sort === k ? icon("check") : null)));
    openSheet(h("div", { class: "sheetin" }, h("div", { class: "handle" }), h("h3", { text: "Sorteren" }), opts));
  };
}

/** Voor de knop op de kaartdetailpagina: is dit product al gevolgd, en zet aan/uit. */
export async function isWatched(productId) {
  const r = await rest.get(`watch_items?select=id&product_id=eq.${encodeURIComponent(productId)}&limit=1`);
  return r[0]?.id || null;
}
export async function addWatch(productId) {
  const [row] = await rest.insert("watch_items", [{ user_id: userId(), product_id: productId }]);
  return row.id;
}
export async function removeWatch(watchId) {
  await rest.del("watch_items", `id=eq.${watchId}`);
}
