import { SHOW_PREDICTIONS } from "../model.js";
// Volglijst (watchlist): kaarten en sealed producten die je volgt, met eigen mappen (een kaart mag in meerdere mappen staan).
import { isLoggedIn, rest, userId } from "../api.js";
import { brandmark, detailHash, emptyNote, go, moveCell } from "../components.js";
import { change, outlook } from "../model.js";
import { closeSheet, debounce, eur, h, icon, num, openSheet, pp, segment, signed, store, thumb, toast } from "../ui.js";

let ui = { folder: "alles", sort: "az", ...store.get("pd:watch", {}) };
const saveUi = () => store.set("pd:watch", ui);
const SORTS = [["az", "A–Z"], ["set", "Set and number"], ["low", "Lowest price"], ["high", "Highest price"],
  ...(SHOW_PREDICTIONS ? [["up", "Likeliest to rise"], ["down", "Likeliest to drop"]] : [])];
const numCmp = (a, b) => String(a ?? "").localeCompare(String(b ?? ""), "nl", { numeric: true });

export async function watchlistView(root) {
  if (!isLoggedIn()) {
    const { loginView } = await import("./login.js");
    loginView(root, { reason: "Log in to watch cards.", onDone: () => watchlistView(root) });
    return;
  }
  root.replaceChildren(h("div", { class: "page" }, h("div", { class: "head" }, h("h1", { text: "Watchlist" }), h("p", { class: "muted", text: "Loading…" }))));
  let items, folders, links;
  try {
    [items, folders, links] = await Promise.all([
      rest.get("v_watchlist?select=*&order=created_at.desc"),
      rest.get("watch_folders?select=*&order=name.asc"),
      rest.get("watch_folder_items?select=folder_id,item_id"),
    ]);
  } catch (e) { root.replaceChildren(h("p", { class: "err pad", text: "Couldn't load your watchlist. Check your connection." })); console.error(e); return; }
  items = items.map((r) => ({ ...r, value_each: r.value_each == null ? null : Number(r.value_each), p_up: r.p_up == null ? null : Number(r.p_up), p_down: r.p_down == null ? null : Number(r.p_down) }));
  // wat de prijs de laatste 30 dagen deed, en het vooruitzicht (balkje); lukt dat niet, dan gewoon zonder
  const before = new Map(), adv = new Map();
  let stats = [];
  const ids = [...new Set(items.map((r) => r.product_id))];
  const iso = (d) => new Date(Date.now() - d * 864e5).toISOString().slice(0, 10);
  await Promise.all([
    rest.get("advice_stats?select=*").then((x) => { stats = x; }).catch(() => {}),
    ...Array.from({ length: Math.ceil(ids.length / 80) }, (_, i) => ids.slice(i * 80, i * 80 + 80)).map(async (chunk) => {
      const inList = chunk.map(encodeURIComponent).join(",");
      try { for (const a of await rest.get(`v_advice?select=*&product_id=in.(${inList})`)) adv.set(a.product_id, a); } catch {}
      try {
        const rows = await rest.get(`prices?select=product_id,date,price&grade_key=eq.raw&product_id=in.(${inList})&date=lte.${iso(30)}&date=gte.${iso(45)}&order=date.desc`);
        for (const x of rows) if (!before.has(x.product_id)) before.set(x.product_id, Number(x.price));
      } catch {}
    })]);
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
    const opts = [["alles", "All"], ...folders.map((f) => [f.id, f.name])];
    chips.replaceChildren(...opts.map(([id, label]) => h("button", { type: "button", class: "fchip" + (ui.folder === id ? " on" : ""),
      onclick: () => { ui.folder = id; saveUi(); drawList(); drawChips(); } }, label)),
      h("button", { type: "button", class: "fchip add", onclick: newFolder }, icon("plus"), " Folder"));
  };

  const drawList = () => {
    sortBtn.replaceChildren(icon("sort"), h("span", { text: "Sort" }));
    const vis = items.filter((r) => ui.folder === "alles" || byFolder.get(ui.folder)?.has(r.id)).sort(cmp[ui.sort]);
    list.replaceChildren(...(vis.length ? vis.map((r) => row(r)) : [emptyNote(items.length ? "Nothing in this folder." : "Not watching anything yet. Add cards via Search or a card page.")]));
  };

  function row(r) {
    const fchips = itemFolders(r.id);
    return h("li", {}, h("div", { class: "wrow" },
      h("button", { class: "rowc", type: "button", onclick: () => go(detailHash(r.product_id)) },
        thumb(r.image, "ph", r.kind === "sealed"),
        h("div", { class: "body" },
          h("span", { class: "nm" }, h("span", { class: "name", text: r.name })),
          h("span", { class: "set", text: (r.set_name || "") + (r.number && r.kind === "card" ? ` #${r.number}` : "") }),
          fchips.length ? h("span", { class: "set fmini", text: fchips.map((f) => f.name).join(", ") }) : null),
        moveCell({ value: r.value_each ? eur(r.value_each) : "–", change: change(r.value_each, before.get(r.product_id)), outlook: outlook(adv.get(r.product_id), stats) })),
      h("button", { class: "morebtn", type: "button", "aria-label": "Folders and remove", onclick: () => manage(r, fchips) }, icon("folder"))));
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
        } catch { toast("Couldn't update"); cb.checked = !cb.checked; }
      };
      return h("label", { class: "chkrow" }, cb, h("span", { text: f.name }));
    });
    openSheet(h("div", { class: "sheetin" }, h("div", { class: "handle" }), h("h3", { text: r.name }),
      folders.length ? h("div", {}, h("p", { class: "lbl2", text: "In folders" }), ...checks) : h("p", { class: "p14 muted", text: "No folders yet. Create one via 'Folder' above the list." }),
      h("button", { type: "button", class: "btn del", text: "Remove from watchlist", onclick: async () => {
        closeSheet();
        try { await rest.del("watch_items", `id=eq.${r.id}`); items = items.filter((x) => x.id !== r.id); toast("Removed"); drawList(); }
        catch { toast("Couldn't remove"); }
      } })));
  }

  function newFolder() {
    const input = h("input", { type: "text", placeholder: "Folder name", "aria-label": "Folder name", maxlength: 40 });
    const err = h("p", { class: "err" });
    const save = h("button", { type: "button", class: "cta", text: "Create folder" });
    save.onclick = async () => {
      const name = input.value.trim();
      if (!name) { err.textContent = "Enter a name."; return; }
      save.disabled = true;
      try {
        const [f] = await rest.insert("watch_folders", [{ user_id: userId(), name }]);
        folders.push(f); folders.sort((a, b) => a.name.localeCompare(b.name, "nl"));
        closeSheet(); drawChips();
      } catch (e) { err.textContent = String(e.message).includes("409") || String(e.message).includes("23505") ? "You already have that name." : "Couldn't create."; save.disabled = false; }
    };
    openSheet(h("div", { class: "sheetin" }, h("div", { class: "handle" }), h("h3", { text: "New folder" }), input, err, save));
    input.focus();
  }

  root.replaceChildren(h("div", { class: "page" },
    brandmark(),
    h("div", { class: "head" }, h("h1", { text: "Watchlist" })),
    chips,
    h("div", { class: "bar" }, h("span", { class: "muted", text: `${items.length} ${items.length === 1 ? "card" : "cards"}` }), sortBtn),
    list));
  drawChips(); drawList();

  sortBtn.onclick = () => {
    const opts = h("div", { class: "opts" }, ...SORTS.map(([k, label]) => h("button", { type: "button", class: "opt", "aria-pressed": String(ui.sort === k),
      onclick: () => { ui.sort = k; saveUi(); closeSheet(); drawList(); } }, h("span", { text: label }), ui.sort === k ? icon("check") : null)));
    openSheet(h("div", { class: "sheetin" }, h("div", { class: "handle" }), h("h3", { text: "Sort" }), opts));
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
