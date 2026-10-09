// Kaart fotograferen en herkennen (tekstherkenning in de browser, gratis).
import { addForm } from "./add.js";
import { rest } from "./api.js";
import { SET_ALIASES, searchCards } from "./cardsearch.js";
import { nameGrams, nameTokens, normNum, parseBottom, parseCardText, rankCandidates, scanQueries, searchTerm } from "./ocr.js";
import { closeSheet, debounce, h, icon, openSheet } from "./ui.js";

const TESS = "https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js";
let tessPromise;
export function loadTesseract() {
  if (window.Tesseract) return Promise.resolve(window.Tesseract);
  tessPromise ??= new Promise((res, rej) => {
    const s = h("script", { src: TESS });
    s.onload = () => res(window.Tesseract);
    s.onerror = () => { tessPromise = null; rej(new Error("Couldn't load text recognition (needs internet)")); };
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
  // nummer verkeerd gelezen, maar naam en settotaal wel ('159/128' i.p.v. 149/128): alle kaarten met die naam uit sets van die grootte
  const best = rankCandidates(parsed, [...seen.values()])[0];
  const term = (searchTerm(parsed) || "").toLowerCase();
  if (parsed.name && parsed.total && term && !(best && normNum(best.number) === normNum(parsed.number) && String(best.name).toLowerCase().includes(term))) {
    const word = searchTerm(parsed) || "";
    try {
      const extra = await rest.get(`v_search?select=*&kind=eq.card&name=ilike.*${encodeURIComponent(word.replace(/[*,()]/g, ""))}*&set_total=eq.${Number(parsed.total)}&limit=40`);
      extra.forEach((r) => { if (!seen.has(r.product_id)) seen.set(r.product_id, { ...r, hits: 1, best: 50 }); });
    } catch { /* zonder deze extra poging verder */ }
  }
  // naam met leesfouten ('Ehandelune'): kaarten zoeken die stukjes van 4 letters gemeen hebben, en die op gelijkenis laten scoren
  const grams = nameGrams(parsed.tokens || []);
  if (grams.length) {
    try {
      const or = grams.map((g) => `name.ilike.*${g}*`).join(",");
      const extra = await rest.get(`v_search?select=*&kind=eq.card&or=(${encodeURIComponent(or)})&limit=400`);
      extra.forEach((r) => { if (!seen.has(r.product_id)) seen.set(r.product_id, { ...r, hits: 0, best: 60 }); });
    } catch { /* zonder deze extra poging verder */ }
  }
  const rows = [...seen.values()];
  const ranked = rankCandidates(parsed, rows);
  const rest_ = rows.filter((r) => !ranked.some((x) => x.product_id === r.product_id)).sort((a, b) => b.hits - a.hits || a.best - b.best);
  return [...ranked, ...rest_].slice(0, 6);
}

/** Zoekt de kaart in een foto: alles wat duidelijk anders is dan de rand van de foto (de achtergrond), het grootste aaneengesloten
 * stuk daarvan, en hoe scheef dat ligt. Geeft { cx, cy, w, h, angle } in de maat van de foto, of null als er niets duidelijks is. */
export function locateCard(source, sw, sh) {
  const scale = 320 / Math.max(sw, sh);
  const w = Math.max(8, Math.round(sw * scale)), hh = Math.max(8, Math.round(sh * scale));
  const c = h("canvas", { width: w, height: hh });
  const ctx = c.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(source, 0, 0, w, hh);
  const px = ctx.getImageData(0, 0, w, hh).data;
  // achtergrondkleur: de mediaan van een smalle rand rond de foto
  const rs = [], gs = [], bs = [], m = Math.max(2, Math.round(Math.min(w, hh) * 0.03));
  for (let y = 0; y < hh; y++) for (let x = 0; x < w; x++) {
    if (x >= m && x < w - m && y >= m && y < hh - m) continue;
    const i = (y * w + x) * 4; rs.push(px[i]); gs.push(px[i + 1]); bs.push(px[i + 2]);
  }
  const med = (a) => a.sort((p, q) => p - q)[a.length >> 1];
  const br = med(rs), bg = med(gs), bb = med(bs);
  // spreiding van de achtergrond: bij een drukke achtergrond (hout) moet het verschil groter zijn
  let spread = 0; for (let k = 0; k < rs.length; k++) spread += Math.abs(rs[k] - br) + Math.abs(gs[k] - bg) + Math.abs(bs[k] - bb);
  const T = Math.max(60, (spread / rs.length) * 2.2);
  const mask = new Uint8Array(w * hh);
  for (let k = 0, i = 0; k < w * hh; k++, i += 4) mask[k] = Math.abs(px[i] - br) + Math.abs(px[i + 1] - bg) + Math.abs(px[i + 2] - bb) > T ? 1 : 0;
  // grootste aaneengesloten stuk
  const lab = new Int32Array(w * hh); let best = null, id = 0;
  for (let k = 0; k < w * hh; k++) {
    if (!mask[k] || lab[k]) continue;
    id++; const stack = [k]; lab[k] = id; const pts = [];
    while (stack.length) {
      const q = stack.pop(); pts.push(q);
      const x = q % w, y = (q - x) / w;
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const nx = x + dx, ny = y + dy;
        if (nx < 0 || ny < 0 || nx >= w || ny >= hh) continue;
        const n = ny * w + nx;
        if (mask[n] && !lab[n]) { lab[n] = id; stack.push(n); }
      }
    }
    if (!best || pts.length > best.length) best = pts;
  }
  if (!best || best.length < w * hh * 0.12) return null;
  // ligging: hoofdas van het stuk (een kaart staat rechtop, de lange kant is de hoogte)
  let sx = 0, sy = 0; for (const q of best) { sx += q % w; sy += (q - (q % w)) / w; }
  const mx = sx / best.length, my = sy / best.length;
  let cxx = 0, cyy = 0, cxy = 0;
  for (const q of best) { const x = (q % w) - mx, y = (q - (q % w)) / w - my; cxx += x * x; cyy += y * y; cxy += x * y; }
  const theta = 0.5 * Math.atan2(2 * cxy, cxx - cyy);                 // hoek van de lange as t.o.v. de x-as
  let angle = theta - Math.PI / 2; while (angle > Math.PI / 4) angle -= Math.PI / 2; while (angle < -Math.PI / 4) angle += Math.PI / 2;
  if (Math.abs(angle) > 0.35) return null;                              // meer dan 20° scheef: liever niet gokken
  const ca = Math.cos(angle), sa = Math.sin(angle);
  let u0 = Infinity, u1 = -Infinity, v0 = Infinity, v1 = -Infinity;
  for (const q of best) {
    const x = (q % w) - mx, y = (q - (q % w)) / w - my;
    const u = x * ca + y * sa, v = -x * sa + y * ca;                    // u langs de breedte, v langs de hoogte (rechtgezet)
    if (u < u0) u0 = u; if (u > u1) u1 = u; if (v < v0) v0 = v; if (v > v1) v1 = v;
  }
  const bw = u1 - u0, bh = v1 - v0;
  if (bw < 10 || bh < 10 || bh / bw < 1.05 || bh / bw > 1.8) return null;   // geen kaartvorm
  const ucx = (u0 + u1) / 2, vcy = (v0 + v1) / 2;
  const cx = mx + ucx * ca - vcy * sa, cy = my + ucx * sa + vcy * ca;
  return { cx: cx / scale, cy: cy / scale, w: bw / scale, h: bh / scale, angle };
}

/** De gevonden kaart rechtgezet en uitgeknipt. */
export function cardFromBox(source, box) {
  const c = h("canvas", { width: Math.round(box.w), height: Math.round(box.h) });
  const ctx = c.getContext("2d");
  ctx.translate(c.width / 2, c.height / 2);
  ctx.rotate(-box.angle);
  ctx.drawImage(source, -box.cx, -box.cy);
  return c;
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
  let parsed = { ...parseCardText(top), ...parseBottom(bottom, codes), tokens: nameTokens(top) };
  if (!parsed.name || !parsed.number) {   // vangnet: de hele kaart
    const full = await readText(T, band(card, 0, 0, 1, 1, 1200));
    const all = parseCardText(full), b = parseBottom(full, codes);
    parsed = { ...parsed, name: parsed.name || all.name, number: parsed.number || b.number || all.number, total: parsed.total || b.total || all.total, setCode: parsed.setCode || b.setCode,
      tokens: parsed.tokens.length ? parsed.tokens : nameTokens(full.split(/\r?\n/).slice(0, 4).join(" ")) };
  }
  if (parsed.setCode && SET_ALIASES[parsed.setCode.toLowerCase()]) parsed.setName = SET_ALIASES[parsed.setCode.toLowerCase()];
  return parsed;
}

export function openScan({ onAdded }) {
  let stream;
  const stop = () => { stream?.getTracks().forEach((t) => t.stop()); stream = null; };
  const video = h("video", { autoplay: true, playsinline: true, muted: true });
  const status = h("div", { class: "vf-hint", text: "Place the card in the frame" });
  const panel = h("div", { class: "scanpanel", hidden: true });
  // twee bestandskiezers: zonder 'capture' opent de galerij, met 'capture' de camera-app van de telefoon (werkt ook als de camera
  // in de app zelf niet start, bijvoorbeeld zonder toestemming of in sommige browsers)
  const file = h("input", { type: "file", accept: "image/*", hidden: true });
  const camFile = h("input", { type: "file", accept: "image/*", capture: "environment", hidden: true });
  const shutter = h("button", { class: "shutter", type: "button", "aria-label": "Take photo" });
  const dlg = h("div", { class: "scan" },
    video,
    h("div", { class: "vf-top" }, h("button", { class: "round", type: "button", "aria-label": "Close", onclick: () => closeSheet("scan") }, icon("x")),
      h("button", { class: "round txt", type: "button", onclick: () => file.click() }, icon("image"), " Gallery")),
    status, h("div", { class: "frame" }, h("i", { class: "corner c1" }), h("i", { class: "corner c2" }), h("i", { class: "corner c3" }), h("i", { class: "corner c4" })),
    h("div", { class: "shutterbar" }, shutter), file, camFile, panel);

  async function recognise(source, w, h_, crop) {
    stop();
    video.pause?.();
    status.textContent = "Recognising card…";
    shutter.disabled = true;
    try {
      const T = await loadTesseract();
      // pogingen, van best naar ruimst: de kaart zoals gevonden in de foto, het kader (camera) of de hele foto, en het midden
      const box = locateCard(source, w, h_);
      const tries = [box ? cardFromBox(source, box) : null, cardCanvas(source, w, h_, crop), crop ? null : cardCanvas(source, w, h_, true)].filter(Boolean);
      let parsed = null, cands = [], bestScore = -99;
      for (const card of tries) {
        const p = await readCard(T, card);
        const cs = (p.name || p.number || p.tokens?.length) ? await findCandidates(p) : [];
        const sc = cs[0]?.score ?? -1;
        if (sc > bestScore) { parsed = p; cands = cs; bestScore = sc; }
        if (sc >= 8) break;                                             // naam én nummer kloppen: klaar
      }
      const read = [parsed.name, parsed.setCode, parsed.number ? (parsed.total ? `${parsed.number}/${parsed.total}` : parsed.number) : ""].filter(Boolean).join(" ");
      status.textContent = read ? `Read: ${read}` : "Nothing read";
      showResults(parsed, cands);
    } catch (e) {
      status.textContent = e.message || "Couldn't recognise";
      showResults({ name: null }, []);
    }
  }

  function showResults(parsed, cands) {
    panel.hidden = false;
    const body = h("div", { class: "sheetin" });
    const pick = (p) => body.replaceChildren(h("div", { class: "handle" }),
      h("div", { class: "okrow" }, h("span", { class: "ok", text: "Recognised" }),
        cands.length > 1 || !p ? h("button", { type: "button", class: "linkbtn", text: "Not right?", onclick: () => choose() }) : null),
      addForm(p, { onDone: () => { closeSheet("scan"); onAdded?.(); } }));
    const choose = () => {
      const q = h("input", { type: "search", placeholder: "Search name, set or number (e.g. 149/128)", "aria-label": "Find the card",
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
      body.replaceChildren(h("div", { class: "handle" }), h("h3", { text: "Pick the right card" }), q, out,
        ...(cands.length ? [h("p", { class: "mini", text: "Suggestions from the photo:" }), h("ul", { class: "list pick" }, ...cands.map((r) =>
          h("li", {}, h("button", { type: "button", class: "res", onclick: () => pick(r) }, h("span", { class: "name", text: r.name }), h("span", { class: "set", text: `${r.set_name} #${r.number}` })))))] : []));
      run();
    };
    cands.length ? pick(cands[0]) : choose();
    panel.replaceChildren(body);
  }

  shutter.onclick = () => recognise(video, video.videoWidth, video.videoHeight, true);
  const fromFile = (input) => () => {
    const f = input.files[0];
    if (!f) return;
    const img = new Image();
    img.onload = () => recognise(img, img.naturalWidth, img.naturalHeight, false);
    img.onerror = () => { status.textContent = "Couldn't open this photo. Try another one."; };
    img.src = URL.createObjectURL(f);
  };
  file.onchange = fromFile(file);
  camFile.onchange = fromFile(camFile);
  // geen camera in de app: twee grote knoppen in plaats van de sluiter
  const noCamera = () => {
    status.textContent = "Take a photo of the card, or pick one from your gallery";
    dlg.querySelector(".shutterbar").replaceChildren(h("div", { class: "pickbtns" },
      h("button", { type: "button", class: "cta", onclick: () => camFile.click() }, icon("camera"), " Take photo"),
      h("button", { type: "button", class: "btn", onclick: () => file.click() }, icon("image"), " From gallery")));
  };

  openSheet(dlg, { id: "scan", onClose: stop });
  navigator.mediaDevices?.getUserMedia?.({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 } }, audio: false })
    .then((s) => { stream = s; video.srcObject = s; video.play?.().catch(() => {}); })
    .catch(noCamera);
  if (!navigator.mediaDevices?.getUserMedia) noCamera();
}
