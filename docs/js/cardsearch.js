// Gedeelde zoekfunctie voor kaarten: gebruikt door Zoeken en door het aankoopformulier (bestellingen).
import { rest } from "./api.js";

let setsCache = null;   // {set_id, name}[], 1x opgehaald, klein genoeg om in het geheugen te houden

// Bekende community-afkortingen (bron: pkmncards.com/sets/, alle sets sinds 1999). Deze staan nergens in onze
// eigen data, dus zonder deze lijst zou "30c" of "dri" nooit gevonden worden, ook al kent iedereen ze wel.
export const SET_ALIASES = {
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
function parseQuery(raw, sets, opts = {}) {
  // Cardmarket-schrijfwijze opvangen: "Blissey Lv.44 (MT 5)", "Blissey Lv. 44 MT5", "Charizard 4/102", "Charizard 30c BS4".
  const cleaned = String(raw).replace(/(\d+)\s*\/\s*\d+/g, "$1");          // 4/102 -> 4 (nummer zonder settotaal)
  const toks = [];
  const all = norm(cleaned).split(/\s+/).filter(Boolean);
  for (let i = 0; i < all.length; i++) {                                     // level weglaten: in onze database heet de kaart gewoon "Blissey"
    if ((all[i] === "lv" || all[i] === "level") && i + 1 < all.length && /^(\d+|x)$/.test(all[i + 1])) { i++; continue; }
    if (/^lv\d+$/.test(all[i]) || all[i] === "lv") continue;
    toks.push(all[i]);
  }

  // Twee manieren om te lezen. Eerst: staat er al een setafkorting of setnaam, dan is een woord als 'BS4' het kaartnummer
  // ("charizard 30c BS4"). Zo niet, dan is 'MT5' een setafkorting met een nummer eraan vast ("blissey MT5").
  const read = (words) => {
    words = [...words];
    let number = null;
    const lastW = words[words.length - 1];
    // een setafkorting met een letter erin ('30c') gaat voor op een nummer: "charizard 30c" zoekt in die set, niet naar kaartnummer 30c
    if (words.length > 1 && looksLikeNumber(lastW) && !(SET_ALIASES[lastW] && /[a-z]/.test(lastW))) number = words.pop();
    let setMatch = null;
    for (let start = 1; start < words.length && !setMatch; start++) {         // het eerste woord is de naam, geen setcode
      if (SET_ALIASES[words[start]]) { setMatch = SET_ALIASES[words[start]]; words.splice(start, 1); break; }
      for (let end = words.length; end > start; end--) {
        const phrase = words.slice(start, end).join(" ");
        if (phrase.length < 3) continue;
        // eerst een set die precies zo heet ('30th-c' = 30th Classic Collection), pas dan een set die er alleen mee begint
        const hit = sets.find((s) => norm(s.set_id) === phrase || norm(s.name) === phrase) || sets.find((s) => norm(s.name).includes(phrase));
        if (hit) { setMatch = hit.name; words.splice(start, end - start); break; }
      }
    }
    // Set eerst, zoals Cardmarket het noemt ("cel wp 24", "obf 125"): alleen als terugvaloptie (opts.setFirst), omdat een afkorting ook een
    // kaartnaam kan zijn ("mew" is zowel de 151-set als de Pokémon). 'cel' = set, 'wp' hoort bij het nummer.
    let prefix = "";
    if (!setMatch && opts.setFirst && words.length >= 1 && SET_ALIASES[words[0]] && (number || words.length === 1) && words.slice(1).every((w) => /^[a-z]{1,4}$/.test(w))) {
      setMatch = SET_ALIASES[words[0]];
      prefix = words.slice(1).join("");
      words = [];
    }
    return { nameWords: words, number, setName: setMatch, prefix, setFirst: Boolean(prefix || (opts.setFirst && setMatch && !words.length)) };
  };

  let q = read(toks);
  if (!q.setName) {
    const glued = [];
    for (const w of toks) {
      const m = w.match(/^([a-z]+)(\d+[a-z]?)$/);                             // setcode en nummer aan elkaar: MT5, OBF125
      if (m && SET_ALIASES[m[1]]) glued.push(m[1], m[2]); else glued.push(w);
    }
    q = read(glued);
  }
  // een nummer met letters ervoor ('bs4', 'sv46', 'swsh020'): ook zonder de letters proberen ('4')
  const letters = q.number && q.number.match(/^[a-z]+(\d+[a-z]?)$/);
  q.numbers = q.number ? [q.number, ...(letters ? [letters[1]] : [])] : [];
  if (q.prefix && q.number) q.numbers.unshift(q.prefix + q.number);   // 'wp' + '24' -> 'wp24' eerst: dat is het nummer zoals Cardmarket het noemt
  // "30c bs 4": 'bs' staat los van '4' maar hoort bij het nummer; als extra mogelijkheid ('bs4') proberen, nooit in plaats van het nummer zelf
  const prev = q.nameWords[q.nameWords.length - 1];
  if (q.number && /^\d/.test(q.number) && q.nameWords.length > 1 && /^[a-z]{1,4}$/.test(prev)) q.numbers.push(prev + q.number);
  return q;
}

/** Zoekt kaarten op naam, set (ook community-afkortingen zoals '30c' of 'dri') en kaartnummer. De database filtert op
 * alles tegelijk, zodat ook goedkopere kaarten van een Pokémon met honderden kaarten gevonden worden (voorheen werden
 * eerst de 200 duurste opgehaald en pas daarna op nummer gefilterd). Niets gevonden? Dan een brede zoekopdracht. */
/** Zoekt rijen voor een gelezen zoekopdracht, van precies naar breed; zodra een poging iets oplevert stoppen we. */
async function findRows(q, kindF) {
  // de nummers zoals getypt (ook zonder de letters ervoor: 'bs4' -> '4'), elk zonder voorloopnullen ('005' -> '5') en met voorloopnullen
  // ('5' -> '05', '005'): sommige sets (bijv. Scarlet & Violet) nummeren hun kaarten gevuld
  const nums = [...new Set((q.numbers || []).flatMap((n) => {
    const bare = n.replace(/^0+(?=\d)/, "");
    return [n, bare, ...(/^\d{1,2}$/.test(bare) ? [bare.padStart(2, "0"), bare.padStart(3, "0")] : [])];
  }))];
  const numF = (n) => (n ? [`number=ilike.${encodeURIComponent(n)}`] : []);
  const nameF = (w) => (w.length ? [`name=ilike.*${encodeURIComponent(w.join("*"))}*`] : []);
  const setF = q.setName ? [`set_name=ilike.*${encodeURIComponent(q.setName)}*`] : [];
  const first = q.nameWords.slice(0, 1);
  // Eerst alles met de set erbij (voor elk nummer), pas daarna zonder set, zodat een kaart uit de bedoelde set nooit achter dezelfde naam
  // uit een andere set verdwijnt.
  const attempts = [];
  for (const n of nums.length ? nums : [null]) attempts.push([...nameF(q.nameWords), ...setF, ...numF(n)]);
  if (q.nameWords.length > 1) for (const n of nums.length ? nums : [null]) attempts.push([...nameF(first), ...setF, ...numF(n)]);
  for (const n of nums.length ? nums : [null]) {
    if (setF.length) attempts.push([...nameF(q.nameWords), ...numF(n)]);
    if (q.nameWords.length > 1) attempts.push([...nameF(first), ...numF(n)]);
  }
  attempts.push([...nameF(q.nameWords), ...setF], [...nameF(q.nameWords)], [...nameF(first)]);
  const tried = new Set();
  for (const f of attempts) {
    const key = f.join("&");
    if (!f.length || tried.has(key)) continue;
    tried.add(key);
    const rows = await rest.get(`v_search?select=*&${key}${kindF}&order=price.desc.nullslast&limit=300`);
    if (rows.length) return rows;
  }
  return [];
}

export async function searchCards(raw, { kind = "alles", limit = 40 } = {}) {
  raw = String(raw || "").trim();
  if (!raw) return [];
  const kindF = kind === "alles" ? "" : `&kind=eq.${kind}`;
  const sets = await getSets();
  let q = parseQuery(raw, sets);
  let rows = await findRows(q, kindF);
  if (!rows.length) {   // niets gevonden: misschien is de set eerst getypt, zoals Cardmarket het noemt ("cel wp 24", "obf 125")
    const alt = parseQuery(raw, sets, { setFirst: true });
    if (alt.setFirst) {
      rows = await findRows(alt, kindF);
      if (rows.length) q = alt;
    }
  }
  if (!rows.length) {
    const pat = encodeURIComponent(norm(raw).split(/\s+/).join("*"));
    rows = await rest.get(`v_search?select=*&or=(name.ilike.*${pat}*,set_name.ilike.*${pat}*)${kindF}&order=price.desc.nullslast&limit=${limit}`);
  }
  const score = (r, q) => {
    const name = norm(r.name), wanted = q.nameWords.join(" ");
    let n = 0;
    if (wanted && name === wanted) n += 120;
    else if (wanted && name.startsWith(wanted)) n += 60;
    if (q.setName && norm(r.set_name) === norm(q.setName)) n += 40;
    if (q.number && norm(r.number) === norm(q.number)) n += 30;
    if (q.numbers && q.numbers.some((x) => norm(r.number) === norm(x))) n += 30;
    return n;
  };
  return rows.sort((a, b) => score(b, q) - score(a, q) || Number(b.price || 0) - Number(a.price || 0)).slice(0, limit);
}
