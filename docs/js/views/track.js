import { rest } from "../api.js";
import { go } from "../components.js";
import { fmtDate, h, icon, pp, signed } from "../ui.js";

/** Kiest live-uitkomsten als er genoeg zijn, anders de backtest. */
export function summarize(rows) {
  const by = { live: {}, backtest: {} };
  for (const r of rows) if (by[r.source]) by[r.source][r.bucket] = { n: r.n, hits: r.hits, sum_p: Number(r.sum_p) };
  const pick = by.live.all?.n >= 30 ? "live" : by.backtest.all?.n ? "backtest" : by.live.all?.n ? "live" : null;
  return pick ? { source: pick, ...by[pick] } : null;
}

export async function trackView(root) {
  root.replaceChildren(h("p", { class: "muted pad", text: "Laden…" }));
  let stats = [], signals = [];
  try {
    [stats, signals] = await Promise.all([rest.get("trackrecord_stats?select=*&horizon_days=eq.30&threshold_pct=eq.10"),
      rest.get("trackrecord_signals?select=*&horizon_days=eq.30&threshold_pct=eq.10&order=resolved_on.desc,id.desc&limit=6")]);
  } catch { root.replaceChildren(h("p", { class: "err pad", text: "Kon het trackrecord niet laden." })); return; }
  const s = summarize(stats);

  const page = h("div", { class: "page" },
    h("div", { class: "topbar" }, h("button", { class: "back", type: "button", onclick: () => history.back() }, icon("back"), h("span", { text: "Terug" }))),
    h("div", { class: "head" }, h("h1", { text: "Trackrecord" }),
      h("p", { class: "muted", text: "Zo vaak kwamen eerdere koop-signalen uit. Alleen voorspellingen van meer dan 30 dagen geleden tellen mee." })));

  if (!s) {
    page.append(h("div", { class: "grp" }, h("p", { class: "p14", text: "Nog geen uitkomsten. De eerste voorspellingen worden na 30 dagen beoordeeld. Zodra er historische prijzen zijn opgehaald kan een backtest hier al cijfers laten zien." })));
    root.replaceChildren(page); return;
  }
  const koop = s.koop || { n: 0, hits: 0 }, all = s.all;
  page.append(h("div", { class: "grp" },
    s.source === "backtest" ? h("p", { class: "chipn a", text: "Backtest op historische prijzen" }) : null,
    h("div", { class: "tr-big", text: `${koop.hits} van ${koop.n}` }),
    h("p", { class: "p14" }, "koop-signalen stegen binnen 30 dagen met minstens 10% (", h("b", { text: koop.n ? pp(koop.hits / koop.n) : "–" }),
      "). Bij alle kaarten en sealed samen lukte dat ", h("b", { text: all.n ? pp(all.hits / all.n) : "–" }), ".")));

  const cmp = (label, b) => {
    const st = s[b]; if (!st || !st.n) return null;
    const pred = h("i", { class: "p" }), act = h("i", { class: "a" });
    pred.style.width = Math.round((st.sum_p / st.n) * 100) + "%"; act.style.width = Math.round((st.hits / st.n) * 100) + "%";
    return h("div", { class: "cmp" }, h("span", { text: label }), h("div", { class: "b" }, pred, act), h("b", { text: pp(st.hits / st.n) }));
  };
  page.append(h("div", { class: "grp" }, h("h3", { text: "Voorspeld tegenover werkelijk" }),
    cmp("Kans 20–40%", "20-40"), cmp("Kans 40–60%", "40-60"), cmp("Kans 60–80%", "60-80"), cmp("Kans 80%+", "80-100"),
    h("p", { class: "mini", text: "Grijs: de voorspelde kans. Groen: hoe vaak het echt gebeurde." })));

  if (signals.length) {
    page.append(h("div", { class: "grp" }, h("h3", { text: "Recente signalen" }),
      ...signals.map((r) => h("div", { class: "res2" },
        h("span", {}, h("b", { text: r.name || r.product_id }), h("small", { text: `Signaal ${fmtDate(r.signal_date)}, kans ${pp(Number(r.p_up))}` })),
        h("span", { class: r.hit ? "ok2" : "no2", text: `${signed(Number(r.change))} ${r.hit ? "✓" : "✗"}` })))));
  }
  root.replaceChildren(page);
}
