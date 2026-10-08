import { rest } from "../api.js";
import { brandmark, go } from "../components.js";
import { fmtDate, h, icon, pp, signed } from "../ui.js";

/** Kiest live-uitkomsten als er genoeg zijn, anders de backtest. */
export function summarize(rows) {
  const by = { live: {}, backtest: {} };
  for (const r of rows) if (by[r.source]) by[r.source][r.bucket] = { n: r.n, hits: r.hits, sum_p: Number(r.sum_p) };
  const pick = by.live.all?.n >= 30 ? "live" : by.backtest.all?.n ? "backtest" : by.live.all?.n ? "live" : null;
  return pick ? { source: pick, ...by[pick] } : null;
}

export async function trackView(root) {
  root.replaceChildren(h("p", { class: "muted pad", text: "Loading…" }));
  let stats = [], signals = [];
  try {
    [stats, signals] = await Promise.all([rest.get("trackrecord_stats?select=*&horizon_days=eq.30&threshold_pct=eq.10"),
      rest.get("trackrecord_signals?select=*&horizon_days=eq.30&threshold_pct=eq.10&order=resolved_on.desc,id.desc&limit=6")]);
  } catch { root.replaceChildren(h("p", { class: "err pad", text: "Couldn't load the track record." })); return; }
  const s = summarize(stats);

  const page = h("div", { class: "page" },
    h("div", { class: "topbar" }, h("button", { class: "back", type: "button", onclick: () => history.back() }, icon("back"), h("span", { text: "Back" }))),
    brandmark(),
    h("div", { class: "head" }, h("h1", { text: "Track record" }),
      h("p", { class: "muted", text: "How often past buy signals came true. Only predictions older than 30 days count." })));

  if (!s) {
    page.append(h("div", { class: "grp" }, h("p", { class: "p14", text: "No results yet. Predictions are judged after 30 days. Once historical prices are fetched, a backtest can show numbers here." })));
    root.replaceChildren(page); return;
  }
  const koop = s.koop || { n: 0, hits: 0 }, all = s.all;
  page.append(h("div", { class: "grp" },
    s.source === "backtest" ? h("p", { class: "chipn a", text: "Backtest on historical prices" }) : null,
    h("div", { class: "tr-big", text: `${koop.hits} of ${koop.n}` }),
    h("p", { class: "p14" }, "buy signals rose 10%+ within 30 days (", h("b", { text: koop.n ? pp(koop.hits / koop.n) : "–" }),
      "). For all cards and sealed together: ", h("b", { text: all.n ? pp(all.hits / all.n) : "–" }), ".")));

  const cmp = (label, b) => {
    const st = s[b]; if (!st || !st.n) return null;
    const pred = h("i", { class: "p" }), act = h("i", { class: "a" });
    pred.style.width = Math.round((st.sum_p / st.n) * 100) + "%"; act.style.width = Math.round((st.hits / st.n) * 100) + "%";
    return h("div", { class: "cmp" }, h("span", { text: label }), h("div", { class: "b" }, pred, act), h("b", { text: pp(st.hits / st.n) }));
  };
  page.append(h("div", { class: "grp" }, h("h3", { text: "Predicted vs. actual" }),
    cmp("Chance 20–40%", "20-40"), cmp("Chance 40–60%", "40-60"), cmp("Chance 60–80%", "60-80"), cmp("Chance 80%+", "80-100"),
    h("p", { class: "mini", text: "Grey: predicted chance. Green: how often it happened." })));

  if (signals.length) {
    page.append(h("div", { class: "grp" }, h("h3", { text: "Recent signals" }),
      ...signals.map((r) => h("div", { class: "res2" },
        h("span", {}, h("b", { text: r.name || r.product_id }), h("small", { text: `Signal ${fmtDate(r.signal_date)}, chance ${pp(Number(r.p_up))}` })),
        h("span", { class: r.hit ? "ok2" : "no2", text: `${signed(Number(r.change))} ${r.hit ? "✓" : "✗"}` })))));
  }
  root.replaceChildren(page);
}
