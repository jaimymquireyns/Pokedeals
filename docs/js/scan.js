// Kaart fotograferen en herkennen (tekstherkenning in de browser, gratis).
import { rest } from "./api.js";
import { addForm } from "./add.js";
import { normNum, parseCardText, rankCandidates, searchTerm } from "./ocr.js";
import { closeSheet, h, icon, openSheet } from "./ui.js";

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

async function findCandidates(parsed) {
  const term = searchTerm(parsed);
  if (!term) return [];
  const rows = await rest.get(`v_search?select=product_id,kind,name,set_name,number,set_total,image,price&kind=eq.card&name=ilike.*${encodeURIComponent(term.replace(/[*,()]/g, ""))}*&limit=80`);
  return rankCandidates(parsed, rows);
}

/** Bijsnijden naar het kaartkader en verkleinen: dat maakt herkennen sneller en beter. */
function frameToCanvas(source, sw, sh, crop) {
  const cw = crop ? sh * 0.8 * (63 / 88) : sw, ch = crop ? sh * 0.8 : sh;
  const sx = crop ? (sw - cw) / 2 : 0, sy = crop ? (sh - ch) / 2 : 0;
  const scale = Math.min(1, 1200 / cw);
  const c = h("canvas", { width: Math.round(cw * scale), height: Math.round(ch * scale) });
  const ctx = c.getContext("2d");
  ctx.filter = "grayscale(1) contrast(1.35)";
  ctx.drawImage(source, sx, sy, cw, ch, 0, 0, c.width, c.height);
  return c;
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
      const canvas = frameToCanvas(source, w, h_, crop);
      const { data } = await T.recognize(canvas, "eng");
      const parsed = parseCardText(data.text);
      status.textContent = parsed.name ? `Gelezen: ${parsed.name}${parsed.number ? ` ${parsed.number}/${parsed.total}` : ""}` : "Naam niet gelezen";
      showResults(parsed, parsed.name ? await findCandidates(parsed) : []);
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
      const q = h("input", { type: "search", placeholder: "Zoek de kaart op naam", "aria-label": "Zoek de kaart", value: parsed.name || "" });
      const out = h("ul", { class: "list pick" });
      const run = async () => {
        const term = q.value.trim().split(" ")[0];
        if (term.length < 2) return;
        const rows = await rest.get(`v_search?select=product_id,kind,name,set_name,number,set_total,image,price&kind=eq.card&name=ilike.*${encodeURIComponent(term.replace(/[*,()]/g, ""))}*&order=price.desc.nullslast&limit=12`);
        out.replaceChildren(...rows.map((r) => h("li", {}, h("button", { type: "button", class: "res", onclick: () => pick(r) },
          h("span", { class: "name", text: r.name }), h("span", { class: "set", text: `${r.set_name} #${r.number}` })))));
      };
      q.oninput = run;
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
