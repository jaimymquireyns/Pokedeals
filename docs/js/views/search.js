import { isLoggedIn, rest } from "../api.js";
import { addForm } from "../add.js";
import { detailHash, emptyNote, go, kindTag } from "../components.js";
import { openScan } from "../scan.js";
import { debounce, eur, h, icon, openSheet, closeSheet, segment, thumb, toast } from "../ui.js";

let state = { q: "", kind: "alles" };
let setsCache = null;   // {set_id, name}[], 1x opgehaald, klein genoeg om in het geheugen te houden

// Bekende community-afkortingen (bron: pkmncards.com/sets/, alle sets sinds 1999). Deze staan nergens in onze
// eigen data, dus zonder deze lijst zou "30c" of "dri" nooit gevonden worden, ook al kent iedereen ze wel.
const SET_ALIASES = {
  "30c": "30th Celebration", "pbl": "Pitch Black", "cri": "Chaos Rising", "por": "Perfect Order",
  "asc": "Ascended Heroes", "pfl": "Phantasmal Flames", "mee": "Mega Evolution Energy", "meg": "Mega Evolution", "mep": "Mega Evolution Promos",
  "wht": "White Flare", "sve": "Scarlet & Violet Energy", "blk": "Black Bolt", "dri": "Destined Rivals", "jtg": "Journey Together",
  "pre": "Prismatic Evolutions", "ssp": "Surging Sparks", "scr": "Stellar Crown", "sfa": "Shrouded Fable", "twm": "Twilight Masquerade",
  "tef": "Temporal Forces", "paf": "Paldean Fates", "par": "Paradox Rift", "mew": "151", "obf": "Obsidian Flames",
  "pal": "Paldea Evolved", "svi": "Scarlet & Violet", "svp": "Scarlet & Violet Promos",
  "crz": "Crown Zenith", "sit": "Silver Tempest", "lor": "Lost Origin", "pgo": "Pokémon GO", "asr": "Astral Radiance",
  "brs": "Brilliant Stars", "fst": "Fusion Strike", "cel": "Celebrations", "evs": "Evolving Skies", "cre": "Chilling Reign",
  "bst": "Battle Styles", "shf": "Shining Fates", "viv": "Vivid Voltage", "cpa": "Champion's Path", "daa": "Darkness Ablaze",
  "rcl": "Rebel Clash", "ssh": "Sword & Shield",
  "cec": "Cosmic Eclipse", "hif": "Hidden Fates", "unm": "Unified Minds", "unb": "Unbroken Bonds", "det": "Detective Pikachu",
  "teu": "Team Up", "lot": "Lost Thunder", "drm": "Dragon Majesty", "ces": "Celestial Storm", "fli": "Forbidden Light",
  "upr": "Ultra Prism", "cin": "Crimson Invasion", "slg": "Shining Legends", "bus": "Burning Shadows", "gri": "Guardians Rising",
  "sum": "Sun & Moon", "smp": "Sun & Moon Promos",
  "evo": "Evolutions", "sts": "Steam Siege", "fco": "Fates Collide", "gen": "Generations", "bkp": "BREAKpoint",
  "bkt": "BREAKthrough", "aor": "Ancient Origins", "ros": "Roaring Skies", "dcr": "Double Crisis", "prc": "Primal Clash",
  "phf": "Phantom Forces", "ffi": "Furious Fists", "flf": "Flashfire", "xyp": "XY Promos",
  "ltr": "Legendary Treasures", "plb": "Plasma Blast", "plf": "Plasma Freeze", "pls": "Plasma Storm", "bcr": "Boundaries Crossed",
  "drv": "Dragon Vault", "drx": "Dragons Exalted", "dex": "Dark Explorers", "nxd": "Next Destinies", "nvi": "Noble Victories",
  "epo": "Emerging Powers", "blw": "Black & White", "bwp": "Black & White Promos",
  "cl": "Call of Legends", "tm": "Triumphant", "ud": "Undaunted", "ul": "Unleashed", "hs": "HeartGold & SoulSilver",
  "ar": "Arceus", "sv": "Supreme Victors", "rr": "Rising Rivals", "pl": "Platinum",
  "sf": "Stormfront", "la": "Legends Awakened", "md": "Majestic Dawn", "ge": "Great Encounters", "sw": "Secret Wonders",
  "mt": "Mysterious Treasures", "dp": "Diamond & Pearl",
  "pk": "Power Keepers", "df": "Dragon Frontiers", "cg": "Crystal Guardians", "hp": "Holon Phantoms", "lm": "Legend Maker",
  "ds": "Delta Species", "uf": "Unseen Forces", "em": "Emerald", "dx": "Deoxys", "tr": "Team Rocket Returns",
  "rg": "FireRed & LeafGreen", "hl": "Hidden Legends", "ma": "Team Magma vs Team Aqua", "dr": "Dragon", "ss": "Sandstorm", "rs": "Ruby & Sapphire",
  "sk": "Skyridge", "aq": "Aquapolis",
  "n4": "Neo Destiny", "n3": "Neo Revelation", "n2": "Neo Discovery", "n1": "Neo Genesis",
  "g2": "Gym Challenge", "g1": "Gym Heroes",
  "ro": "Team Rocket", "b2": "Base Set 2", "fo": "Fossil", "ju": "Jungle", "bs": "Base Set",
  // 'ex' (Expedition) bewust weggelaten: te veel kaartnamen eindigen zelf op 'ex' (bijv. 'Charizard ex'), dat
  // zou anders per ongeluk als setcode worden gelezen. Typ 'expedition' voluit voor die set.
};

const norm = (x) => String(x || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, " ").trim();
const looksLikeNumber = (w) => /\d/.test(w) && /^[a-z]{0,3}\d{1,4}[a-z]{0,2}$/i.test(w);

async function getSets() {
  if (!setsCache) setsCache = await rest.get("sets?select=set_id,name").catch(() => []);
  return setsCache;
}

/** Splitst de zoektekst in: kaartnummer (laatste woord, als het op een nummer lijkt), een setnaam (herkend via
 * de bekende community-afkortingen zoals '30c' of 'dri', óf via een stuk van de echte setnaam of set-id uit onze
 * eigen sets-tabel), en de rest als naam. Zo werkt "charizard 30c 63" net zo goed als "charizard 30th 63" of
 * "charizard celebration 63". Een setcode die nergens voorkomt (verzonnen, of een nieuwe set die nog niet in de
 * lijst staat) wordt gewoon als een naamwoord behandeld. */
function parseQuery(raw, sets) {
  const words = norm(raw).split(/\s+/).filter(Boolean);
  let number = null;
  if (words.length > 1 && looksLikeNumber(words[words.length - 1])) number = words.pop();

  let setMatch = null;
  for (let start = 0; start < words.length && !setMatch; start++) {
    const alias = SET_ALIASES[words[start]];
    if (alias) { setMatch = alias; words.splice(start, 1); break; }
    for (let end = words.length; end > start; end--) {
      const phrase = words.slice(start, end).join(" ");
      if (phrase.length < 3) continue;
      const hit = sets.find((s) => norm(s.set_id) === phrase || norm(s.name) === phrase || norm(s.name).includes(phrase));
      if (hit) { setMatch = hit.name; words.splice(start, end - start); break; }
    }
  }
  return { nameWords: words, number, setName: setMatch };
}

export async function searchView(root) {
  const input = h("input", { type: "search", placeholder: "Zoek naam, set of nummer", value: state.q, "aria-label": "Zoeken", autocomplete: "off" });
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
    if (!state.q.trim()) { list.replaceChildren(emptyNote("Typ een naam, set of nummer. Bijvoorbeeld \"charizard 30th 4\". Of gebruik de camera om een kaart te scannen.")); return; }
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

  const score = (r, q) => {
    const name = norm(r.name), wanted = q.nameWords.join(" ");
    let n = 0;
    if (wanted && name === wanted) n += 120;
    else if (wanted && name.startsWith(wanted)) n += 60;
    if (q.setName && norm(r.set_name) === norm(q.setName)) n += 40;
    if (q.number && norm(r.number) === norm(q.number)) n += 30;
    return n;
  };

  const run = debounce(async () => {
    const kind = state.kind === "alles" ? "" : `&kind=eq.${state.kind}`;
    const raw = state.q.trim();
    if (!raw) { rows = []; draw(); return; }
    const sets = await getSets();
    const q = parseQuery(raw, sets);
    try {
      const ors = [];
      if (q.nameWords.length) ors.push(`name.ilike.*${encodeURIComponent(q.nameWords.join("*"))}*`);
      if (q.setName) ors.push(`set_name.ilike.*${encodeURIComponent(q.setName)}*`);
      if (!ors.length) ors.push(`name.ilike.*${encodeURIComponent(raw)}*`, `set_name.ilike.*${encodeURIComponent(raw)}*`);
      let candidates = await rest.get(`v_search?select=*&or=(${ors.join(",")})${kind}&order=price.desc.nullslast&limit=200`);
      if (q.number) candidates = candidates.filter((r) => norm(r.number) === q.number);
      if (q.setName) candidates = candidates.filter((r) => norm(r.set_name).includes(norm(q.setName)));
      rows = candidates.sort((a, b) => score(b, q) - score(a, q) || Number(b.price || 0) - Number(a.price || 0)).slice(0, 40);
      if (!rows.length && (q.number || q.setName)) {
        // niets gevonden met de gestructureerde uitleg van de zoektekst: val terug op een gewone, brede zoekopdracht
        const pat = encodeURIComponent(norm(raw).split(/\s+/).join("*"));
        rows = await rest.get(`v_search?select=*&or=(name.ilike.*${pat}*,set_name.ilike.*${pat}*)${kind}&order=price.desc.nullslast&limit=40`);
      }
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
