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
const eurFmt = new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR" });
export const eur = (x) => (x == null || Number.isNaN(x) ? "–" : eurFmt.format(x).replace(/\s/g, NBSP));
export const pp = (p) => Math.round(p * 100) + "%";
export const signed = (x, d = 0) => (x == null || Number.isNaN(x) ? "–" :
  (x > 0.0005 ? "+" : x < -0.0005 ? "−" : "") + Math.abs(x * 100).toFixed(d).replace(".", ",") + "%");
export const signedEur = (x) => (x == null ? "–" : (x >= 0 ? "+" : "−") + NBSP + eur(Math.abs(x)));
export const days = (n) => `${n} ${n === 1 ? "dag" : "dagen"}`;
export const fmtDate = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("nl-NL", { day: "numeric", month: "short" });
export const fmtDateLong = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("nl-NL", { day: "numeric", month: "short", year: "numeric" });
export const safeImg = (u) => (typeof u === "string" && /^https:\/\//.test(u) ? u : null);
export const num = (x) => (x == null || x === "" ? null : Number(x));
export const parseMoney = (s) => { const n = parseFloat(String(s).replace(/[^\d,.-]/g, "").replace(/\.(?=\d{3}\b)/g, "").replace(",", ".")); return Number.isFinite(n) ? n : null; };
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
  d.onclose = () => { d.replaceChildren(); onClose?.(); };
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

export const thumb = (url, cls = "ph", box = false) =>
  url ? h("img", { class: cls + " img", src: url, alt: "", loading: "lazy", decoding: "async" }) : h("span", { class: cls + (box ? " box" : "") });
