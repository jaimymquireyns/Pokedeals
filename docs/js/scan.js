// Kaart fotograferen en herkennen (tekstherkenning in de browser, gratis).
import { addForm } from "./add.js";
import { SET_ALIASES, searchCards } from "./cardsearch.js";
import { normNum, parseBottom, parseCardText, rankCandidates, scanQueries } from "./ocr.js";
import { closeSheet, debounce, h, icon, openSheet } from "./ui.js";

const TESS = "https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js";
let tessPromise;
export function loadTesseract() {
  if (window.Tesseract) return Promise.resolve(window.Tesseract);
  tessPromise ??= new Promise((res, rej) => {
    const s = h("script", { src: TESS });
    s.onload = () => res(window.Tesseract);
    s.onerror = () => { tessPromise = null; rej(new Error("Tekstherkenning kon niet worden geladen (internet nodig)")); };
    document.head.append(s);
  });
  return tessPromise;
}

/** Kandidaten via dezelfde zoekfunctie als Zoeken (die begrijpt "149/128" en setcodes als "30c"), van precies naar breed.
 * Wat in meerdere zoekopdrachten terugkomt en bij naam, nummer en settotaal past, komt bovenaan. */
async function findCandidates(parsed) {
  const seen = new Map();
  for (const q of scanQueries(parsed)) {
    let rows = [];
    try { rows = await searchCards(q, { kind: "card", limit: 20 }); } catch { continue; }
    rows.forEach((r, i) => { const x = seen.get(r.product_id) || { ...r, hits: 0, best: 99 }; x.hits += 1; x.best = Math.min(x.best, i); seen.set(r.product_id, x); });
    if (seen.size && [...seen.values()].some((x) => parsed.number && normNum(x.number) === normNum(parsed.number) && (!parsed.total || String(x.set_total) === String(Number(parsed.total))))) break;
  }
  const rows = [...seen.values()];
  const ranked = rankCandidates(parsed, rows);
  const rest_ = rows.filter((r) => !ranked.some((x) => x.product_id === r.product_id)).sort((a, b) => b.hits - a.hits || a.best - b.best);
  return [...ranked, ...rest_].slice(0, 6);
}

/** De kaart uit de foto halen: bij de camera het kader in het midden, bij een gekozen foto de hele foto. */
function cardCanvas(source, sw, sh, crop) {
  const cw = crop ? sh * 0.8 * (63 / 88) : sw, ch = crop ? sh * 0.8 : sh;
  const sx = crop ? (sw - cw) / 2 : 0, sy = crop ? (sh - ch) / 2 : 0;
  const c = h("canvas", { width: Math.round(cw), height: Math.round(ch) });
  c.getContext("2d").drawImage(source, sx, sy, cw, ch, 0, 0, c.width, c.height);
  return c;
}

/** Een strook van de kaart, vergroot en in hoog contrast: kleine tekst (het nummer onderaan) wordt zo veel beter gelezen. */
function band(card, x0, y0, x1, y1, width = 1600) {
  const w = card.width * (x1 - x0), hh = card.height * (y1 - y0);
  const scale = width / w;
  const c = h("canvas", { width: Math.round(w * scale), height: Math.round(hh * scale) });
  const ctx = c.getContext("2d");
  ctx.filter = "grayscale(1) contrast(1.6)";
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(card, card.width * x0, card.height * y0, w, hh, 0, 0, c.width, c.height);
  return c;
}

let workerP = null;
async function readText(T, canvas, params) {
  if (T.createWorker) {
    workerP ??= T.createWorker("eng");
    const w = await workerP;
    await w.setParameters({ tessedit_char_whitelist: "", tessedit_pageseg_mode: "6", ...params });
    return (await w.recognize(canvas)).data.text || "";
  }
  return (await T.recognize(canvas, "eng")).data.text || "";   // oudere tesseract.js (en de tests)
}

/** Leest naam (bovenrand), nummer en setcode (onderrand) apart, en de hele kaart als vangnet. */
async function readCard(T, card) {
  const codes = Object.keys(SET_ALIASES);
  const top = await readText(T, band(card, 0.03, 0.02, 0.78, 0.13));
  const bottom = await readText(T, band(card, 0, 0.86, 1, 1, 1800), { tessedit_char_whitelist: "0123456789/ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz " });
  let parsed = { ...parseCardText(top), ...parseBottom(bottom, codes) };
  if (!parsed.name || !parsed.number) {   // vangnet: de hele kaart
    const full = await readText(T, band(card, 0, 0, 1, 1, 1200));
    const all = parseCardText(full), b = parseBottom(full, codes);
    parsed = { ...parsed, name: parsed.name || all.name, number: parsed.number || b.number || all.number, total: parsed.total || b.total || all.total, setCode: parsed.setCode || b.setCode };
  }
  return parsed;
}

export function openScan({ onAdded }) {
  let stream;
  const stop = () => { stream?.getTracks().forEach((t) => t.stop()); stream = null; };
  const video = h("video", { autoplay: true, playsinline: true, muted: true });
  const status = h("div", { class: "vf-hint", text: "Leg de kaart in het kader" });
  const panel = h("div", { class: "scanpanel", hidden: true });
  const file = h("input", { type: "file", accept: "image/*", capture: "environment", hidden: true });
  const shutter = h("button", { class: "shutter", type: "button", "aria-label": "Foto maken" });
  const dlg = h("div", { class: "scan" },
    video,
    h("div", { class: "vf-top" }, h("button", { class: "round", type: "button", "aria-label": "Sluiten", onclick: () => closeSheet("scan") }, icon("x")),
      h("button", { class: "round txt", type: "button", onclick: () => file.click(), text: "Foto kiezen" })),
    status, h("div", { class: "frame" }, h("i", { class: "corner c1" }), h("i", { class: "corner c2" }), h("i", { class: "corner c3" }), h("i", { class: "corner c4" })),
    h("div", { class: "shutterbar" }, shutter), file, panel);

  async function recognise(source, w, h_, crop) {
    stop();
    video.pause?.();
    status.textContent = "Kaart herkennen…";
    shutter.disabled = true;
    try {
      const T = await loadTesseract();
      const parsed = await readCard(T, cardCanvas(source, w, h_, crop));
      const read = [parsed.name, parsed.setCode, parsed.number ? (parsed.total ? `${parsed.number}/${parsed.total}` : parsed.number) : ""].filter(Boolean).join(" ");
      status.textContent = read ? `Gelezen: ${read}` : "Niets gelezen";
      showResults(parsed, read ? await findCandidates(parsed) : []);
    } catch (e) {
      status.textContent = e.message || "Herkennen mislukte";
      showResults({ name: null }, []);
    }
  }

  function showResults(parsed, cands) {
    panel.hidden = false;
    const body = h("div", { class: "sheetin" });
    const pick = (p) => body.replaceChildren(h("div", { class: "handle" }),
      h("div", { class: "okrow" }, h("span", { class: "ok", text: "Herkend" }),
        cands.length > 1 || !p ? h("button", { type: "button", class: "linkbtn", text: "Niet juist?", onclick: () => choose() }) : null),
      addForm(p, { onDone: () => { closeSheet("scan"); onAdded?.(); } }));
    const choose = () => {
      const q = h("input", { type: "search", placeholder: "Zoek op naam, set of nummer (bijv. 149/128)", "aria-label": "Zoek de kaart",
        value: [parsed.name, parsed.number ? (parsed.total ? `${parsed.number}/${parsed.total}` : parsed.number) : ""].filter(Boolean).join(" ") });
      const out = h("ul", { class: "list pick" });
      const run = async () => {
        const term = q.value.trim();
        if (term.length < 2) return;
        const rows = await searchCards(term, { kind: "card", limit: 12 }).catch(() => []);
        out.replaceChildren(...rows.map((r) => h("li", {}, h("button", { type: "button", class: "res", onclick: () => pick(r) },
          h("span", { class: "name", text: r.name }), h("span", { class: "set", text: `${r.set_name} #${r.number}` })))));
      };
      q.oninput = debounce(run, 300);
      body.replaceChildren(h("div", { class: "handle" }), h("h3", { text: "Kies de juiste kaart" }), q, out,
        ...(cands.length ? [h("p", { class: "mini", text: "Suggesties uit de foto:" }), h("ul", { class: "list pick" }, ...cands.map((r) =>
          h("li", {}, h("button", { type: "button", class: "res", onclick: () => pick(r) }, h("span", { class: "name", text: r.name }), h("span", { class: "set", text: `${r.set_name} #${r.number}` })))))] : []));
      run();
    };
    cands.length ? pick(cands[0]) : choose();
    panel.replaceChildren(body);
  }

  shutter.onclick = () => recognise(video, video.videoWidth, video.videoHeight, true);
  file.onchange = () => {
    const f = file.files[0];
    if (!f) return;
    const img = new Image();
    img.onload = () => recognise(img, img.naturalWidth, img.naturalHeight, false);
    img.src = URL.createObjectURL(f);
  };

  openSheet(dlg, { id: "scan", onClose: stop });
  navigator.mediaDevices?.getUserMedia?.({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 } }, audio: false })
    .then((s) => { stream = s; video.srcObject = s; })
    .catch(() => { status.textContent = "Geen cameratoegang. Kies een foto uit je galerij."; shutter.hidden = true; });
}
