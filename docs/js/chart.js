// Eenvoudige SVG-lijngrafieken (geen bibliotheek).
import { eur, fmtDate } from "./ui.js";

const NS = "http://www.w3.org/2000/svg";
const el = (name, attrs = {}, text) => {
  const n = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text != null) n.textContent = text;
  return n;
};

export const stepPoints = (pts) => {
  const out = [];
  pts.forEach((p, i) => { if (i) out.push([p[0], pts[i - 1][1]]); out.push(p); });
  return out;
};

function niceTicks(lo, hi, n = 3) {
  const span = hi - lo || 1;
  const raw = span / n;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || raw;
  const ticks = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(v);
  return ticks;
}

/**
 * series: [{ pts: [[ms, y], ...], stroke, width, dash }]  hlines: [{ y, label, dash }]
 * area:   { upper: pts, lower: pts, fill }  (vlak tussen twee lijnen)
 */
export function lineChart({ series, area, hlines = [], width = 358, height = 170, label = "Grafiek" }) {
  const L = 50, R = 6, T = 10, B = 24;
  const all = [...series.flatMap((s) => s.pts), ...(area ? [...area.upper, ...area.lower] : [])];
  const xs = all.map((p) => p[0]);
  const ys = [...all.map((p) => p[1]), ...hlines.map((h) => h.y)];
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let lo = Math.min(...ys), hi = Math.max(...ys);
  if (hi - lo < 1e-9) { lo *= 0.95; hi *= 1.05; }
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const X = (x) => L + ((x - x0) / Math.max(x1 - x0, 1)) * (width - L - R);
  const Y = (y) => T + (1 - (y - lo) / (hi - lo)) * (height - T - B);
  const path = (pts) => pts.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)} ${Y(p[1]).toFixed(1)}`).join("");

  const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, class: "chart", role: "img", "aria-label": label });
  for (const t of niceTicks(lo, hi)) {
    svg.append(el("line", { class: "grid", x1: L, x2: width - R, y1: Y(t), y2: Y(t) }));
    svg.append(el("text", { x: L - 6, y: Y(t) + 4, "text-anchor": "end" }, eur(t).replace(/,00$/, "")));
  }
  if (area) {
    const poly = [...area.upper, ...[...area.lower].reverse()].map((p) => `${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(" ");
    svg.append(el("polygon", { points: poly, fill: area.fill || "#0E8A5B", opacity: ".14" }));
  }
  for (const h of hlines) {
    svg.append(el("line", { x1: L, x2: width - R, y1: Y(h.y), y2: Y(h.y), stroke: "var(--ink)", "stroke-width": 1.6, "stroke-dasharray": "5 4" }));
    if (h.label) svg.append(el("text", { x: width - R, y: Y(h.y) + 14, "text-anchor": "end", style: "fill:var(--ink);font-weight:700" }, h.label));
  }
  for (const s of series) {
    svg.append(el("path", { d: path(s.pts), fill: "none", stroke: s.stroke, "stroke-width": s.width || 3,
      "stroke-linejoin": "round", "stroke-linecap": "round", ...(s.dash ? { "stroke-dasharray": s.dash } : {}) }));
  }
  const iso = (ms) => new Date(ms).toISOString().slice(0, 10);
  svg.append(el("text", { x: L, y: height - 6 }, fmtDate(iso(x0))));
  svg.append(el("text", { x: width - R, y: height - 6, "text-anchor": "end" }, fmtDate(iso(x1))));
  return svg;
}
