import { isLoggedIn, rest, userId } from "../api.js";
import { addForm } from "../add.js";
import { lineChart } from "../chart.js";
import { chanceBar, gradeTag, go, kindTag, pill } from "../components.js";
import { SIGNAL_TEXT, gradeKey, netGain, ownedSignal, whyBullets } from "../model.js";
import { getSettings } from "../prefs.js";
import { enablePush, pushPermission } from "../push.js";
import { closeSheet, debounce, eur, fmtDateLong, h, icon, num, openSheet, parseMoney, pp, signed, signedEur, thumb, toast, toggle } from "../ui.js";

const enc = encodeURIComponent;
const stat = (k, v, s, cls = "") => h("div", { class: "stat" }, h("div", { class: "k", text: k }), h("div", { class: "v num " + cls, text: v }), s ? h("div", { class: "s", text: s }) : null);

export async function detailView(root, pid, cid) {
  root.replaceChildren(h("p", { class: "muted pad", text: "Laden…" }));
  const s = getSettings();
  let p, c = null, f = null, hist = [], al = null;
  try {
    const owned = cid ? rest.get(`v_collection?select=*&id=eq.${enc(cid)}`).then((r) => r[0] || null) : Promise.resolve(null);
    [p, c, f] = await Promise.all([
      rest.get(`v_search?select=*&product_id=eq.${enc(pid)}`).then((r) => r[0]), owned,
      rest.get(`forecasts?select=*&product_id=eq.${enc(pid)}&horizon_days=eq.${s.horizon}&threshold_pct=eq.${s.pct}`).then((r) => r[0] || null)]);
    if (!p) throw new Error("onbekend product");
    const gk = c ? gradeKey(c) : "raw";
    hist = await rest.get(`prices?select=date,price,source&product_id=eq.${enc(pid)}&grade_key=eq.${enc(gk)}&order=date.asc&limit=1000`);
    if (isLoggedIn()) al = (await rest.get(`alerts?select=*&product_id=eq.${enc(pid)}&grade_key=eq.${enc(gk)}&limit=1`))[0] || null;
  } catch (e) { root.replaceChildren(h("p", { class: "err pad", text: "Kon dit product niet laden." }), h("button", { class: "linkbtn", text: "Terug", onclick: () => history.back() })); console.error(e); return; }

  const gk = c ? gradeKey(c) : "raw";
  const num2 = (x) => (x == null ? null : Number(x));
  const price = c ? num2(c.value_each) : num2(p.price);
  const fx = f && { ...f, price: Number(f.price), p_up: Number(f.p_up), p_down: Number(f.p_down), exp: Number(f.exp_change), avg7: num2(f.avg7), avg30: num2(f.avg30), mom30: num2(f.mom30), sigma: num2(f.sigma) };
  const graded = gk !== "raw";

  // ---- kop ----
  const head = h("div", { class: "dh" }, thumb(p.image, "ph", p.kind === "sealed"),
    h("div", {}, h("h2", { text: p.name }), h("div", { class: "sub", text: [p.set_name, p.number && p.kind === "card" ? `#${p.number}` : ""].filter(Boolean).join(" · ") }),
      h("div", { class: "tags" }, kindTag(p.kind), c ? gradeTag(c) : null),
      h("div", { class: "big num", text: price ? eur(price) : "Geen prijs" })));

  // ---- cijfers ----
  let stats;
  if (c) {
    const total = price ? (price - c.purchase_price) * c.quantity : null;
    stats = h("div", { class: "stats" }, stat("Aankoop", eur(Number(c.purchase_price)), `${c.quantity > 1 ? c.quantity + "x, " : ""}${fmtDateLong(c.purchase_date)}`),
      stat("Waarde nu", price ? eur(price * c.quantity) : "–", price ? `${eur(price)} per stuk` : "prijs onbekend"),
      stat("Winst", total == null ? "–" : signedEur(total), price ? signed(price / Number(c.purchase_price) - 1, 1) : "", total != null && total < 0 ? "neg" : "pos"));
  } else {
    stats = h("div", { class: "stats" }, stat("Prijs nu", price ? eur(price) : "–"), stat("Gem. 7 dagen", fx?.avg7 ? eur(fx.avg7) : "–"), stat("Gem. 30 dagen", fx?.avg30 ? eur(fx.avg30) : "–"));
  }

  // ---- kans ----
  const chance = h("div", { class: "sec" }, h("h3", { text: `Kans binnen ${s.horizon} dagen` }));
  if (fx) {
    const net = netGain(fx.price, fx.exp, s);
    const sig = c ? ownedSignal(fx, c) : { label: fx.signal, text: SIGNAL_TEXT[fx.signal] };
    chance.append(...[chanceBar(fx.p_up, fx.p_down),
      h("p", { class: "p14 dirs" }, h("span", { text: `daling van ${s.pct}% of meer` }), h("span", { text: `stijging van ${s.pct}% of meer` })),
      h("p", { class: "p14" }, "Verwachte stijging ", h("b", { text: signed(fx.exp, 1) }), " · na verkoopkosten ", h("b", { text: signed(net, 1) }), "."),
      h("div", { class: "sigrow" }, pill(sig.label), h("span", { text: sig.text })),
      graded ? h("p", { class: "mini", text: `Let op: deze kans is berekend op de prijs van de ongegradeerde kaart. ${gk.replace("-", " ")} beweegt vaak anders.` }) : null].filter(Boolean));
  } else chance.append(h("p", { class: "p14 muted", text: "Nog geen kansberekening. Dat kan komen doordat er te weinig prijsdata is, of omdat de prijs onder de € 2 ligt." }));

  const why = fx ? h("div", { class: "sec" }, h("h3", { text: "Waarom deze kans?" }),
    h("ul", { class: "why" }, ...whyBullets(fx).map((b) => h("li", {}, h("span", { class: "dot " + b.tone, text: b.tone === "g" ? "+" : b.tone === "r" ? "−" : b.tone === "n" ? "~" : "i" }),
      h("span", {}, h("b", { text: b.head }), " " + b.text))))) : null;

  // ---- grafiek ----
  const chartSec = h("div", { class: "sec" }, h("h3", { text: c ? "Prijs sinds aankoop" : "Prijsverloop" }));
  const bySrc = {};
  for (const r of hist) (bySrc[r.source] ||= []).push(r);
  const src = (bySrc.tcgdex?.length || 0) >= 5 ? "tcgdex" : (Object.keys(bySrc).sort((a, b) => bySrc[b].length - bySrc[a].length)[0]);
  let rows = (bySrc[src] || []);
  if (c) { const from = c.purchase_date; const after = rows.filter((r) => r.date >= from); if (after.length >= 2) rows = after; }
  if (rows.length >= 2) {
    chartSec.append(lineChart({ series: [{ pts: rows.map((r) => [new Date(r.date + "T00:00:00Z").getTime(), Number(r.price)]), stroke: "var(--up)" }],
      hlines: c ? [{ y: Number(c.purchase_price), label: `Aankoop ${eur(Number(c.purchase_price))}` }] : [], label: "Prijsverloop" }));
    if (src !== "tcgdex" && p.kind === "card") chartSec.append(h("p", { class: "mini", text: "Historie van TCGplayer (omgerekend naar euro). Onze eigen Cardmarket-metingen bouwen zich op." }));
  } else chartSec.append(h("p", { class: "p14 muted", text: "Nog te weinig prijsgeschiedenis voor een grafiek." }));

  // ---- prijsmelding ----
  const alertSec = h("div", { class: "sec" });
  let alertState = al ? { id: al.id, on: al.active, min: num2(al.min_price), max: num2(al.max_price) } : { id: null, on: false, min: null, max: null };
  const saveAlert = debounce(async () => {
    const body = { min_price: alertState.min, max_price: alertState.max, active: alertState.on, armed: true };
    try {
      if (alertState.id) await rest.patch("alerts", `id=eq.${alertState.id}`, body);
      else { const r = await rest.insert("alerts", [{ user_id: userId(), product_id: pid, grade_key: gk, ...body }]); alertState.id = r[0].id; }
      toast(alertState.on ? "Prijsmelding opgeslagen" : "Prijsmelding uit");
    } catch (e) { toast("Opslaan mislukte"); console.error(e); }
  }, 500);
  const drawAlert = () => {
    if (!isLoggedIn()) {
      alertSec.replaceChildren(h("h3", { text: "Prijsmelding" }), h("p", { class: "p14 muted", text: "Log in om meldingen te krijgen als de prijs in jouw bereik komt." }),
        h("button", { class: "btn", type: "button", text: "Inloggen", onclick: () => go("#/login?next=" + enc(location.hash)) }));
      return;
    }
    const money = (key, label, ph) => h("label", { class: "amt" }, h("span", { class: "lbl2", text: label }),
      h("input", { type: "text", inputmode: "decimal", placeholder: ph, "aria-label": label, value: alertState[key] == null ? "" : String(alertState[key]).replace(".", ","),
        oninput: (e) => { alertState[key] = parseMoney(e.target.value); saveAlert(); } }));
    const tg = toggle(alertState.on, async (on) => {
      if (on) {
        if (pushPermission() !== "granted") { try { await enablePush(); } catch (e) { toast(e.message); alertState.on = false; drawAlert(); return; } }
        if (alertState.min == null && alertState.max == null && price) { alertState.min = Math.round(price * 0.8 * 100) / 100; alertState.max = Math.round(price * 0.9 * 100) / 100; }
      }
      alertState.on = on; saveAlert(); drawAlert();
    }, "Prijsmelding aan of uit");
    alertSec.replaceChildren(h("div", { class: "sech" }, h("h3", { text: "Prijsmelding" }), tg),
      alertState.on ? h("div", {}, h("p", { class: "p14", text: "Ik krijg een melding als de prijs binnen dit bereik komt:" }),
        h("div", { class: "two eq" }, money("min", "Van (€)", "bijv. 40"), money("max", "Tot (€)", "bijv. 44")),
        h("p", { class: "mini", text: "Leeg laten mag: dan geldt alleen de andere grens. Na een melding hoef je niets te resetten; hij komt pas weer als de prijs eerst uit het bereik is geweest." }))
        : h("p", { class: "p14 muted", text: "Uit. Zet aan om een melding te krijgen bij een prijs die jij wilt." }));
  };
  drawAlert();

  // ---- knoppen ----
  const btns = h("div", { class: "btns" });
  const reload = () => { closeSheet(); detailView(root, pid, cid); };
  if (c) {
    btns.append(h("button", { class: "btn", type: "button", text: "Bewerken", onclick: () => openSheet(h("div", { class: "sheetin" }, h("div", { class: "handle" }), addForm({ ...p, price: c.value_each }, { editing: c, onDone: reload }))) }));
  } else {
    btns.append(h("button", { class: "btn primary", type: "button", text: "Toevoegen aan collectie", onclick: () => {
      if (!isLoggedIn()) { go("#/login?next=" + enc(location.hash)); return; }
      openSheet(h("div", { class: "sheetin" }, h("div", { class: "handle" }), addForm(p, { onDone: () => { closeSheet(); toast("Toegevoegd aan je collectie"); } })));
    } }));
  }
  btns.append(h("a", { class: "btn", target: "_blank", rel: "noopener", text: "Zoek op Cardmarket",
    href: `https://www.cardmarket.com/en/Pokemon/Products/Search?searchString=${enc([p.name, p.kind === "card" && p.number ? p.number : ""].join(" ").trim())}` }));
  if (c) btns.append(h("button", { class: "btn del", type: "button", text: "Verwijderen uit collectie", onclick: async () => {
    if (!confirm(`${p.name} uit je collectie verwijderen?`)) return;
    try { await rest.del("collection", `id=eq.${enc(cid)}`); toast("Verwijderd"); go("#/collection"); } catch { toast("Verwijderen mislukte"); }
  } }));

  root.replaceChildren(h("div", { class: "page" },
    h("div", { class: "topbar" }, h("button", { class: "back", type: "button", onclick: () => history.back() }, icon("back"), h("span", { text: "Terug" }))),
    head, stats, chance, why, chartSec, alertSec, btns));
}
