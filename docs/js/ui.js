// Kleine hulpjes voor het bouwen van schermen.
export const $ = (s, el = document) => el.querySelector(s);

export const h = (tag, props = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k === "html") el.innerHTML = v;            // alleen voor vaste iconen uit deze codebase
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(kid));
  }
  return el;
};

export const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* vol of geblokkeerd */ } },
};

const NBSP = "\u00a0";
const eurFmt = new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR" });
export const eur = (x) => (x == null || Number.isNaN(x) ? "–" : eurFmt.format(x).replace(/\s/g, NBSP));
export const pp = (p) => Math.round(p * 100) + "%";
export const signed = (x, d = 0) => (x == null || Number.isNaN(x) ? "–" :
  (x > 0.0005 ? "+" : x < -0.0005 ? "−" : "") + Math.abs(x * 100).toFixed(d) + "%");
export const signedEur = (x) => (x == null ? "–" : (x >= 0 ? "+" : "−") + eur(Math.abs(x)));
export const days = (n) => `${n} ${n === 1 ? "day" : "days"}`;
const sep4 = (s) => s.replace("Sept", "Sep");   // nieuwere browsers schrijven "Sept"; overal "Sep" houden
export const fmtDate = (iso) => sep4(new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" }));
export const fmtDateTime = (ts) => { const d = new Date(ts); return Number.isNaN(d.getTime()) ? "" : sep4(d.toLocaleDateString("en-GB", { day: "numeric", month: "short" })) + ", " + d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }); };
export const fmtDateLong = (iso) => sep4(new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }));
export const safeImg = (u) => (typeof u === "string" && /^https:\/\//.test(u) ? u : null);
export const num = (x) => (x == null || x === "" ? null : Number(x));
// Accepteert "24,50", "24.50", "1.234,50" en "1,234.50": het laatste scheidingsteken is de decimaal, tenzij er precies 3 cijfers
// achter staan zonder ander scheidingsteken ervoor ("1.234" of "1,234" = duizendtallen).
export const parseMoney = (s) => {
  let t = String(s).replace(/[^\d,.-]/g, "");
  const last = Math.max(t.lastIndexOf(","), t.lastIndexOf("."));
  if (last >= 0) {
    const intPart = t.slice(0, last).replace(/[,.]/g, ""), frac = t.slice(last + 1);
    const sep = t[last], before = t.slice(0, last);
    const thousands = /^\d{3}$/.test(frac) && (before.includes(sep) || (!/[,.]/.test(before) && /[1-9]/.test(intPart)));
    t = thousands ? intPart + frac : intPart + "." + frac;
  }
  const n = parseFloat(t);
  return Number.isFinite(n) ? n : null;
};
export const debounce = (fn, ms = 300) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

const ICON = {
  home: '<path d="M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.5-4.5"/>',
  cards: '<rect x="8" y="3" width="12" height="15" rx="2"/><path d="M4 8v11a2 2 0 0 0 2 2h9"/>',
  camera: '<path d="M4 8h3l2-3h6l2 3h3a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"/><circle cx="12" cy="13.5" r="3.5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>', minus: '<path d="M5 12h14"/>', check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  back: '<path d="M15 5l-7 7 7 7"/>', x: '<path d="M6 6l12 12M18 6L6 18"/>', right: '<path d="M9 5l7 7-7 7"/>',
  bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
  sort: '<path d="M4 7h16M7 12h10M10 17h4"/>', chev: '<path d="M6 9l6 6 6-6"/>',
  star: '<path d="M12 3.5l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17.4l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
  heart: '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8l1.1 1.1L12 21l7.8-7.5 1.1-1.1a5.5 5.5 0 0 0-.1-7.8z"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-9 9"/>',
  folder: '<path d="M4 6a1 1 0 0 1 1-1h4l2 2h8a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1z"/>',
};
export const icon = (name, cls = "") => h("span", { class: "icw", html: `<svg class="ic ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICON[name]}</svg>` });

// ---- kleine meldingen ----
export function toast(msg) {
  let t = $("#toast");
  if (!t) { t = h("div", { id: "toast", role: "status" }); document.body.append(t); }
  t.textContent = msg;
  t.classList.add("on");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("on"), 2600);
}

// ---- onderblad (dialog) ----
export function openSheet(content, { onClose, id = "sheet" } = {}) {
  let d = document.getElementById(id);
  if (!d) { d = h("dialog", { id, class: "dsheet" }); document.body.append(d); }
  d.replaceChildren(content);
  // het close-event komt pas later binnen: is het blad intussen al opnieuw geopend (het ene blad opent het volgende), dan niets wissen
  d.onclose = () => { if (d.open) return; d.replaceChildren(); onClose?.(); };
  d.onclick = (e) => { if (e.target === d) d.close(); };
  if (!d.open) d.showModal();
  return d;
}
export const closeSheet = (id = "sheet") => document.getElementById(id)?.close();

// ---- gesegmenteerde knoppen ----
export function segment(options, current, onPick, cls = "") {
  const el = h("div", { class: "seg " + cls, role: "group" });
  const draw = (cur) => el.replaceChildren(...options.map(([v, label]) =>
    h("button", { type: "button", "aria-pressed": String(v === cur), text: label, onclick: () => { draw(v); onPick(v); } })));
  draw(current);
  return el;
}

// ---- schakelaar ----
export function toggle(on, onChange, label) {
  const b = h("button", { type: "button", class: "tg" + (on ? "" : " off"), role: "switch", "aria-checked": String(on), "aria-label": label || "" });
  b.onclick = () => { on = !on; b.classList.toggle("off", !on); b.setAttribute("aria-checked", String(on)); onChange(on); };
  return b;
}

export const thumb = (url, cls = "ph", box = false, label = "") => {
  // zonder foto: het lege kaartje, met (als de naam bekend is) naam en nummer erop, zodat je altijd ziet welke kaart het is
  const blank = () => (label ? h("span", { class: cls + " txt" + (box ? " box" : ""), role: "img", "aria-label": label }, h("b", { text: label })) : h("span", { class: cls + (box ? " box" : "") }));
  if (!url) return blank();
  const img = h("img", { class: cls + " img", src: url, alt: "", loading: "lazy", decoding: "async" });
  img.addEventListener("error", () => { if (img.parentNode) img.replaceWith(blank()); }, { once: true });   // kapotte link: netjes het lege kaartje, geen gebroken-plaatje-icoon
  return img;
};
