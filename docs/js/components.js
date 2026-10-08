// Herbruikbare stukjes: labels, kansbalken en lijstrijen.
import { debounce, eur, h, icon, pp, signed, thumb } from "./ui.js";
import { SET_ALIASES } from "./cardsearch.js";
import { costEach, gradeLabel } from "./model.js";

export const go = (hash) => { location.hash = hash; };
export const detailHash = (pid, cid) => `#/detail/${encodeURIComponent(pid)}${cid ? `?c=${cid}` : ""}`;

export const kindTag = (kind) => h("span", { class: "tag" + (kind === "sealed" ? " s" : ""), text: kind === "sealed" ? "sealed" : "kaart" });
export const pill = (label) => h("span", { class: "pill " + (label.startsWith("koop") ? "koop" : label.startsWith("verkoop") ? "verkoop" : label.startsWith("winst") ? "winst" : ""), text: label });
export const gradeTag = (c) => (gradeLabel(c) ? h("span", { class: "gr", text: gradeLabel(c) }) : null);

/** Cardmarket-adres van een kaart: de exacte pagina als we die kennen (cm_url, via PkmnPrices), anders een zoekopdracht
 * op naam en nummer (die kan meerdere kaarten van dezelfde Pokémon tonen). Alleen echte Cardmarket-adressen. */
export const CM_PREFIX = "https://www.cardmarket.com/";
export const hasExactCm = (p) => typeof p.cm_url === "string" && p.cm_url.startsWith(CM_PREFIX);
export function cardmarketHref(p, { nearMint = false } = {}) {
  // nearMint: Cardmarket kan de aanbiedingen op conditie filteren met minCondition (2 = Near Mint of beter); kent een pagina dat niet, dan wordt het genegeerd
  if (hasExactCm(p)) return nearMint ? p.cm_url + (p.cm_url.includes("?") ? "&" : "?") + "minCondition=2" : p.cm_url;
  const q = [p.name, p.kind === "card" && p.number ? p.number : ""].join(" ").trim();
  return `${CM_PREFIX}en/Pokemon/Products/Search?searchString=${encodeURIComponent(q)}`;
}

/** Mediaan van een lijst getallen (bij een even aantal: het gemiddelde van de twee middelste). */
export const median = (xs) => {
  const s = [...xs].sort((a, b) => a - b), m = s.length >> 1;
  return s.length ? (s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2) : null;
};

const normText = (x) => String(x || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, " ").trim();

/** Zoekt in een lijst: elk woord dat je typt moet ergens voorkomen (naam, set, nummer, enz.). Een setafkorting als '30c' of 'obf' telt
 * ook als de setnaam erbij past, net als bij Zoeken. Leeg = alles. fields: lijst teksten van deze regel; set: de setnaam. */
export function matchQuery(q, fields, set = "") {
  const toks = normText(q).split(/\s+/).filter(Boolean);
  if (!toks.length) return true;
  const hay = normText(fields.filter(Boolean).join(" "));
  const setN = normText(set);
  return toks.every((t) => hay.includes(t) || (SET_ALIASES[t] && setN.includes(normText(SET_ALIASES[t]))));
}

/** Zoekbalk boven een lijst; roept onInput aan terwijl je typt (met een korte pauze). Geeft { box, input } terug. */
export function filterBox(placeholder, onInput, value = "") {
  const input = h("input", { type: "search", placeholder, "aria-label": placeholder, value, autocomplete: "off", autocapitalize: "off", spellcheck: "false" });
  const fire = debounce(() => onInput(input.value), 120);
  input.addEventListener("input", fire);
  return { box: h("label", { class: "sbox fbox" }, icon("search"), input), input };
}

/** Logo + naam, bovenaan elk scherm. */
export const brandmark = () => h("div", { class: "brandmark" },
  h("span", { class: "mark" }, h("img", { src: "icons/icon-192.png?v=2", alt: "" })),
  h("span", { class: "wordmark" }, h("b", { text: "poké" }), h("i", { text: "deals" })));

/** Enkelzijdige balk voor Home: kans op stijging + verwachte stijging na kosten. */
export function upBar(pUp, net) {
  const fill = h("i"); fill.style.width = Math.min(pUp * 100, 100) + "%";
  return h("div", { class: "l3" },
    h("b", { text: pp(pUp) }), h("span", { class: "lbl", text: "kans" }),
    h("div", { class: "bar1", role: "img", "aria-label": `Kans op stijging ${pp(pUp)}` }, fill),
    h("span", { class: "nt" }, h("b", { text: signed(net) }), " ", h("span", { class: "lbl", text: "netto" })));
}

/** Tweezijdige balk: rood = kans op daling, groen = kans op stijging. */
export function chanceBar(pUp, pDown) {
  const scale = (p) => Math.min(p / 0.8, 1) * 100 + "%";
  const l = h("i"); l.style.width = scale(pDown);
  const r = h("i"); r.style.width = scale(pUp);
  return h("div", { class: "chance", role: "img", "aria-label": `Kans op daling ${pp(pDown)}, kans op stijging ${pp(pUp)}` },
    h("span", { class: "d num", text: pp(pDown) }),
    h("div", { class: "track" }, h("div", { class: "l" }, l), h("div", { class: "r" }, r)),
    h("span", { class: "u num", text: pp(pUp) }));
}

export function oppRow(r, net, watch = null) {
  const main = h("button", { class: "row", type: "button", onclick: () => go(detailHash(r.product_id)) },
    thumb(r.image, "ph", r.kind === "sealed", r.kind === "sealed" ? "" : [r.name, r.number ? "#" + r.number : ""].filter(Boolean).join(" ")),
    h("div", { class: "body" },
      h("div", { class: "l1" }, h("span", { class: "name", text: r.name }), h("span", { class: "price num", text: eur(r.price) })),
      h("div", { class: "l2" }, h("span", { class: "set", text: r.set_name || "" }, r.number && r.kind === "card" ? ` #${r.number}` : ""),
        h("span", { class: "tags" }, r.confidence === "laag" ? h("span", { class: "tag grof", title: "Weinig prijsgeschiedenis: grove schatting", text: "grof" }) : null, kindTag(r.kind))),
      upBar(r.p_up, net)));
  return h("li", {}, watch ? h("div", { class: "homeitem" }, main,
    h("button", { class: "heartb" + (watch.on ? " on" : ""), type: "button", "aria-label": watch.on ? "Van volglijst halen" : "Aan volglijst toevoegen", onclick: watch.onclick }, icon("heart", watch.on ? "filled" : ""))) : main);
}

export function collRow(c, { valueEach, alerted, gain: gainOverride }) {
  const total = (valueEach ?? costEach(c)) * c.quantity;
  const gain = gainOverride !== undefined ? gainOverride : valueEach ? valueEach / costEach(c) - 1 : null;
  const cls = gain == null ? "" : gain < 0 ? " neg" : "";
  return h("li", {}, h("button", { class: "rowc", type: "button", onclick: () => go(detailHash(c.product_id, c.id)) },
    thumb(c.image, "ph", c.kind === "sealed", c.kind === "sealed" ? "" : [c.name, c.number ? "#" + c.number : ""].filter(Boolean).join(" ")),
    h("div", { class: "body" },
      h("span", { class: "nm" }, h("span", { class: "name", text: c.name }), gradeTag(c), alerted ? h("span", { class: "mini-bell", role: "img", "aria-label": "Prijsmelding actief" }, icon("bell")) : null),
      h("span", { class: "set", text: (c.set_name || "") + (c.number && c.kind === "card" ? ` #${c.number}` : "") }),
      h("span", { class: "set", text: `${c.quantity > 1 ? c.quantity + "x, " : ""}gekocht voor ${eur(c.purchase_price)}` })),
    h("div", { class: "p" }, h("span", { class: "v num", text: eur(total) }),
      h("span", { class: "pc" + cls, text: gain == null ? "prijs onbekend" : signed(gain) }))));
}

export const emptyNote = (text) => h("li", { class: "empty", text });
export const note = (title, ...body) => h("div", { class: "note" }, title ? h("strong", { text: title }) : null, ...body);

/** Klein label met het advies (Goede koop / Nu verkopen / Bijkopen / Let op); bij Bewaren/Afwachten niets, om de lijsten rustig te houden (tenzij always). */
export const adviceChip = (adv, always = false) =>
  adv && (always || adv.tone !== "hold") ? h("span", { class: "advchip " + adv.tone, text: adv.label }) : null;

/** Blok 'Advies' op de detailpagina: het label en één korte zin; de redenen en hoe vaak dit advies klopte achter 'Waarom?'. */
export function adviceBox(adv, trackLine) {
  const more = h("div", { class: "advmore", hidden: true },
    h("ul", { class: "advwhy" }, ...adv.reasons.filter(Boolean).map((r) => h("li", { text: r }))),
    h("p", { class: "mini", text: trackLine + " Een inschatting, geen garantie en geen financieel advies." }));
  const toggleBtn = h("button", { class: "linkbtn", type: "button", text: "Waarom?", onclick: () => { more.hidden = !more.hidden; toggleBtn.textContent = more.hidden ? "Waarom?" : "Minder"; } });
  return h("div", { class: "sec advbox " + adv.tone },
    h("div", { class: "advhead" }, h("span", { class: "advchip big " + adv.tone, text: adv.label }), toggleBtn),
    h("p", { class: "p14", text: adv.short }),
    more);
}

// ---------------------------------------------------------------- stijgt of daalt, in één oogopslag
const pct0 = (x) => Math.round(Math.abs(x) * 100) + "%";

/** Pijl met percentage: groen ▲ bij stijging, rood ▼ bij daling, grijs bij (bijna) niets. */
export function arrow(x, cls = "") {
  if (x == null || Number.isNaN(x)) return null;
  const dir = x > 0.005 ? "up" : x < -0.005 ? "down" : "flat";
  return h("span", { class: `arw ${dir} ${cls}`.trim(), "aria-label": dir === "flat" ? "gelijk" : `${dir === "up" ? "gestegen" : "gedaald"} ${pct0(x)}` },
    dir === "up" ? "▲ " : dir === "down" ? "▼ " : "", dir === "flat" ? "0%" : pct0(x));
}

/** Kleur voor een kans van 0 tot 1: van rood (weinig kans) via oranje naar groen (veel kans). */
export const chanceColor = (c) => `hsl(${Math.round(Math.max(0, Math.min(1, c)) * 120)} 70% 46%)`;

/** Balkje dat inkleurt tot het bolletje: hoe verder (en groener), hoe groter de kans dat de verwachte beweging echt gebeurt.
 * Erachter de verwachte beweging (▲ 45% of ▼ 20%). o: { move, chance } uit model.outlook. */
export function outlookBar(o) {
  if (!o) return null;
  const col = chanceColor(o.chance);
  const fill = h("i"); fill.style.width = Math.round(o.chance * 100) + "%"; fill.style.background = col;
  const dot = h("b"); dot.style.left = Math.round(o.chance * 100) + "%"; dot.style.borderColor = col;
  return h("span", { class: "olk", role: "img", "aria-label": `Verwacht ${o.move >= 0 ? "stijging" : "daling"} van ${pct0(o.move)}, kans ${Math.round(o.chance * 100)}%` },
    h("span", { class: "cbar" }, fill, dot), arrow(o.move, "sm"));
}

/** Rechterkolom van een lijstregel: bedrag, wat de prijs deed (pijl + %) en het vooruitzicht (balkje). */
export const moveCell = ({ value, change = null, outlook: o = null }) =>
  h("span", { class: "mv" }, value != null ? h("span", { class: "v num", text: value }) : null, arrow(change), outlookBar(o));
