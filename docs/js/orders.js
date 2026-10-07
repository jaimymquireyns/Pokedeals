// Kopen en verkopen als bestelling: meerdere kaarten, één verkoper of koper. Kopen en verkopen werken bewust hetzelfde:
// je kiest de kaarten, vult de gegevens van de bestelling in, en de app verdeelt gedeelde bedragen (verzending,
// kosten, of bij verkopen de totaalprijs) over de kaarten.
import { rest, userId } from "./api.js";
import { searchCards } from "./cardsearch.js";
import { allocate, costEach, saleProfit } from "./model.js";
import { getSettings } from "./prefs.js";
import { closeSheet, debounce, eur, h, icon, openSheet, parseMoney, segment, signedEur, thumb, toast } from "./ui.js";

const today = () => new Date().toISOString().slice(0, 10);
const uid = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`);
const money = (label, value = "", attrs = {}) => h("input", { type: "text", inputmode: "decimal", "aria-label": label, placeholder: "0,00", value, ...attrs });
const field = (label, input) => h("div", {}, h("div", { class: "lbl2", text: label }), input);
const fmtIn = (n) => (n ? String(Math.round(n * 100) / 100).replace(".", ",") : "");

function stepper(get, set, max = Infinity, onChange = () => {}) {
  const out = h("span", { class: "n num", text: String(get()) });
  const bump = (d) => { set(Math.min(Math.max(1, get() + d), max)); out.textContent = String(get()); onChange(); };
  return h("div", { class: "qty" },
    h("button", { type: "button", class: "m", "aria-label": "Minder", onclick: () => bump(-1) }, icon("minus")), out,
    h("button", { type: "button", class: "m", "aria-label": "Meer", onclick: () => bump(1) }, icon("plus")));
}

// ---------------------------------------------------------------- aankoop
/** Een aankoop met een of meer kaarten van dezelfde verkoper. Verzending en overige kosten worden verdeeld naar
 * verhouding van prijs x aantal. Gegradeerde kaarten voeg je (voorlopig) los toe via de +-knop bij Zoeken. */
export function openPurchaseOrder({ onDone } = {}) {
  const lines = [];
  const seller = h("input", { type: "text", "aria-label": "Naam verkoper", placeholder: "Naam of Cardmarket-gebruiker" });
  const date = h("input", { type: "date", "aria-label": "Datum aankoop", value: today(), max: today() });
  const ship = money("Verzendkosten");
  const costs = money("Trustee fee");
  const linesBox = h("div", { class: "olines" });
  const summary = h("div", { class: "osum" });
  const err = h("p", { class: "err", role: "alert" });
  const results = h("ul", { class: "opick" });
  const q = h("input", { type: "search", placeholder: "Zoek een kaart om toe te voegen", "aria-label": "Kaart zoeken", autocomplete: "off" });

  const total = () => lines.reduce((s, l) => s + (parseMoney(l.price.value) || 0) * l.qty, 0);
  const draw = () => {
    linesBox.replaceChildren(...(lines.length ? lines.map((l, i) => h("div", { class: "oline" },
      thumb(l.p.image, "ph", l.p.kind === "sealed"),
      h("div", { class: "body" },
        h("div", { class: "name", text: l.p.name }),
        h("div", { class: "set", text: [l.p.set_name, l.p.number ? `#${l.p.number}` : ""].filter(Boolean).join(" · ") }),
        h("div", { class: "orow" }, h("span", { class: "mini", text: "Prijs" }), l.price, stepper(() => l.qty, (v) => { l.qty = v; }, Infinity, drawSum),
          l.p.kind === "card" ? segment([["NM", "NM"], ["LP", "LP"], ["MP", "MP"], ["HP", "HP"]], l.condition, (v) => { l.condition = v; }, "small") : null)),
      h("button", { type: "button", class: "ox", "aria-label": `${l.p.name} verwijderen`, onclick: () => { lines.splice(i, 1); draw(); } }, icon("x"))))
      : [h("p", { class: "p14 muted", text: "Nog geen kaarten. Zoek hierboven een kaart en tik erop." })]));
    drawSum();
  };
  const drawSum = () => {
    const extra = (parseMoney(ship.value) || 0) + (parseMoney(costs.value) || 0);
    summary.textContent = lines.length ? `${lines.reduce((s, l) => s + l.qty, 0)} kaarten · ${eur(total())} + ${eur(extra)} verzending en trustee fee = ${eur(total() + extra)}` : "";
  };
  ship.oninput = drawSum; costs.oninput = drawSum;

  let seq = 0;   // alleen het antwoord op de laatste zoekopdracht tonen
  const search = debounce(async () => {
    const term = q.value.trim();
    if (term.length < 2) { results.replaceChildren(); return; }
    const mine = ++seq;
    try {
      const rows = await searchCards(term, { limit: 30 });
      if (mine !== seq) return;
      if (!rows.length) { results.replaceChildren(h("li", { class: "p14 muted", text: "Niets gevonden. Probeer naam + setafkorting + nummer, bijv. 'charizard obf 125'." })); return; }
      results.replaceChildren(...rows.map((p) => h("li", {}, h("button", { type: "button", class: "opickrow", onclick: () => {
        const price = money("Prijs per stuk", fmtIn(Number(p.price) || 0));
        price.oninput = drawSum;
        lines.push({ p, price, qty: 1, condition: "NM" });
        q.value = ""; results.replaceChildren(); draw();
      } }, thumb(p.image, "ph", p.kind === "sealed"),
        h("span", {}, h("b", { text: p.name }), h("small", { text: ` ${p.set_name || ""}${p.number ? " #" + p.number : ""}` })),
        h("span", { class: "num", text: p.price ? eur(Number(p.price)) : "" })))));
    } catch { results.replaceChildren(h("li", { class: "p14 muted", text: "Zoeken lukte niet." })); }
  }, 250);
  q.oninput = () => {   // oude resultaten meteen weg, zodat je nooit per ongeluk een kaart van de vorige zoekopdracht aantikt
    results.replaceChildren(q.value.trim().length >= 2 ? h("li", { class: "p14 muted", text: "Zoeken…" }) : "");
    search();
  };

  const save = h("button", { class: "cta", type: "button", text: "Aankoop opslaan", onclick: async () => {
    err.textContent = "";
    if (!lines.length) { err.textContent = "Voeg minstens één kaart toe."; return; }
    if (lines.some((l) => !(parseMoney(l.price.value) > 0))) { err.textContent = "Vul bij elke kaart een prijs in."; return; }
    const weights = lines.map((l) => parseMoney(l.price.value) * l.qty);
    const shipShares = allocate(parseMoney(ship.value) || 0, weights);
    const costShares = allocate(parseMoney(costs.value) || 0, weights);
    const order = uid();
    const rows = lines.map((l, i) => ({
      user_id: userId(), product_id: l.p.product_id, quantity: l.qty, condition: l.p.kind === "card" ? l.condition : null,
      grade_company: null, grade: null, purchase_price: parseMoney(l.price.value), purchase_date: date.value || today(),
      purchase_shipping: shipShares[i], purchase_costs: costShares[i], purchase_seller: seller.value.trim() || null, purchase_order: order,
    }));
    save.disabled = true;
    try {
      await rest.insert("collection", rows);
      toast(`${rows.length} ${rows.length === 1 ? "kaart" : "kaarten"} toegevoegd`);
      closeSheet(); onDone?.();
    } catch (e) { console.error(e); err.textContent = "Opslaan mislukte. Probeer het opnieuw."; save.disabled = false; }
  } });

  openSheet(h("div", { class: "sheetin orderform" }, h("div", { class: "handle" }),
    h("h3", { text: "Nieuwe aankoop" }),
    h("div", { class: "two eq" }, field("Naam verkoper", seller), field("Datum aankoop", date)),
    h("div", { class: "two eq" }, field("Verzendkosten", ship), field("Trustee fee", costs)),
    h("p", { class: "mini", text: "Verzendkosten en trustee fee worden verdeeld over de kaarten, naar verhouding van hun prijs. De prijs vul je per kaart in." }),
    h("div", { class: "lbl2", text: "Kaarten" }),
    h("label", { class: "sbox" }, icon("search"), q), results,
    linesBox, summary, err, save));
  draw();
}

// ---------------------------------------------------------------- verkoop
/** Stap 1: kaarten uit je collectie aanvinken (met aantal). Stap 2: de bestelling invullen. */
export function openSaleOrder(rawItems, { onDone } = {}) {
  // A–Z op naam, dan op set en nummer: zo vind je een kaart snel terug in een lange lijst
  const items = [...rawItems].sort((a, b) => String(a.name).localeCompare(String(b.name), "nl") || String(a.set_name || "").localeCompare(String(b.set_name || ""), "nl")
    || String(a.number || "").localeCompare(String(b.number || ""), "nl", { numeric: true }));
  const pick = new Map();   // collection id -> aantal
  const list = h("div", { class: "olines" });
  const next = h("button", { class: "cta", type: "button", text: "Verder", onclick: () => {
    const chosen = items.filter((c) => pick.has(c.id)).map((c) => ({ c, qty: pick.get(c.id) }));
    if (!chosen.length) { toast("Vink minstens één kaart aan"); return; }
    saleDetails(chosen, onDone);
  } });
  const draw = () => {
    list.replaceChildren(...items.map((c) => {
      const on = pick.has(c.id);
      return h("div", { class: "oline" + (on ? " on" : "") },
        h("input", { type: "checkbox", "aria-label": `${c.name} verkopen`, checked: on ? "checked" : null, onchange: (e) => { if (e.target.checked) pick.set(c.id, c.quantity); else pick.delete(c.id); draw(); } }),
        thumb(c.image, "ph", c.kind === "sealed"),
        h("div", { class: "body" },
          h("div", { class: "name", text: c.name }),
          h("div", { class: "set", text: [c.set_name, c.number ? `#${c.number}` : "", c.grade_company ? `${c.grade_company} ${c.grade}` : c.condition].filter(Boolean).join(" · ") }),
          on && c.quantity > 1 ? h("div", { class: "orow" }, stepper(() => pick.get(c.id), (v) => pick.set(c.id, v), c.quantity), h("span", { class: "mini", text: `van ${c.quantity}` })) : null),
        h("span", { class: "num", text: c.value_each ? eur(c.value_each) : "" }));
    }));
  };
  draw();
  openSheet(h("div", { class: "sheetin orderform" }, h("div", { class: "handle" }),
    h("h3", { text: "Verkopen" }),
    h("p", { class: "p14 muted", text: "Vink de kaarten aan die naar dezelfde koper gaan." }),
    list, next));
}

function saleDetails(chosen, onDone) {
  const s = getSettings();
  const buyer = h("input", { type: "text", "aria-label": "Koper", placeholder: "Naam of Cardmarket-gebruiker" });
  const date = h("input", { type: "date", "aria-label": "Datum", value: today(), max: today() });
  const marketTotal = chosen.reduce((t, x) => t + (x.c.value_each || costEach(x.c)) * x.qty, 0);
  const total = money("Totaalprijs", fmtIn(marketTotal));
  const shipIn = money("Verzending ontvangen");
  const shipOut = money("Verzending betaald");
  const commission = money("Commissie");
  const other = money("Overige kosten", "0,50");
  let commissionTouched = false, sharesTouched = false;
  const shareInputs = chosen.map(() => money("Deel van de prijs"));
  const linesBox = h("div", { class: "olines" });
  const result = h("div", { class: "osum" });
  const err = h("p", { class: "err", role: "alert" });

  const costOf = (x) => Math.round(costEach(x.c) * x.qty * 100) / 100;
  const fillShares = () => {
    const shares = allocate(parseMoney(total.value) || 0, chosen.map((x) => (x.c.value_each || costEach(x.c)) * x.qty));
    shareInputs.forEach((inp, i) => { inp.value = fmtIn(shares[i]); });
  };
  const sale = () => ({ shipping_received: parseMoney(shipIn.value) || 0, shipping_paid: parseMoney(shipOut.value) || 0,
    commission: parseMoney(commission.value) || 0, other_costs: parseMoney(other.value) || 0 });
  const recalc = () => {
    if (!commissionTouched) commission.value = fmtIn(Math.round((parseMoney(total.value) || 0) * s.fee_pct) / 100);
    if (!sharesTouched) fillShares();
    const lines = chosen.map((x, i) => ({ price_share: parseMoney(shareInputs[i].value) || 0, cost_total: costOf(x) }));
    const pr = saleProfit(sale(), lines);
    const sumShares = Math.round(lines.reduce((t, l) => t + l.price_share, 0) * 100) / 100;
    const off = Math.round(((parseMoney(total.value) || 0) - sumShares) * 100) / 100;
    linesBox.replaceChildren(...chosen.map((x, i) => h("div", { class: "oline" },
      thumb(x.c.image, "ph", x.c.kind === "sealed"),
      h("div", { class: "body" },
        h("div", { class: "name", text: `${x.qty > 1 ? x.qty + "x " : ""}${x.c.name}` }),
        h("div", { class: "set", text: `kostte je ${eur(costOf(x))}` }),
        h("div", { class: "orow" }, shareInputs[i], h("span", { class: "num " + (pr.per[i] < 0 ? "neg" : "pos"), text: signedEur(pr.per[i]) }))))));
    result.replaceChildren(
      h("div", { class: "bigline" }, h("span", { text: "Winst op deze verkoop" }), h("b", { class: "num " + (pr.total < 0 ? "neg" : "pos"), text: signedEur(pr.total) })),
      off ? h("p", { class: "err", text: `De delen tellen op tot ${eur(sumShares)}, ${eur(Math.abs(off))} ${off > 0 ? "minder" : "meer"} dan de totaalprijs.` }) : null);
    return { lines, off };
  };
  total.oninput = () => { sharesTouched = false; recalc(); };
  commission.oninput = () => { commissionTouched = true; recalc(); };
  [shipIn, shipOut, other].forEach((el) => { el.oninput = recalc; });
  shareInputs.forEach((inp) => { inp.oninput = () => { sharesTouched = true; recalc(); }; });

  const save = h("button", { class: "cta", type: "button", text: "Verkoop opslaan", onclick: async () => {
    err.textContent = "";
    const tp = parseMoney(total.value);
    if (!(tp > 0)) { err.textContent = "Vul de totaalprijs in."; return; }
    const { lines, off } = recalc();
    if (off) { err.textContent = "Zorg dat de delen optellen tot de totaalprijs."; return; }
    const id = uid();
    save.disabled = true;
    try {
      await rest.insert("sales", [{ id, user_id: userId(), sale_date: date.value || today(), buyer: buyer.value.trim() || null, total_price: tp, ...sale() }]);
      await rest.insert("sale_items", chosen.map((x, i) => ({
        sale_id: id, user_id: userId(), product_id: x.c.product_id, quantity: x.qty, condition: x.c.condition || null,
        grade_company: x.c.grade_company || null, grade: x.c.grade || null, price_share: lines[i].price_share, cost_total: lines[i].cost_total,
        purchase_date: x.c.purchase_date || null })));
      for (const x of chosen) {   // de verkochte stuks uit 'In bezit' halen; bij een deel blijven de kosten naar verhouding staan
        if (x.qty >= x.c.quantity) await rest.del("collection", `id=eq.${x.c.id}`);
        else {
          const keep = (x.c.quantity - x.qty) / x.c.quantity;
          await rest.patch("collection", `id=eq.${x.c.id}`, { quantity: x.c.quantity - x.qty,
            purchase_shipping: Math.round(Number(x.c.purchase_shipping || 0) * keep * 100) / 100,
            purchase_costs: Math.round(Number(x.c.purchase_costs || 0) * keep * 100) / 100 });
        }
      }
      toast("Verkoop opgeslagen");
      closeSheet(); onDone?.();
    } catch (e) { console.error(e); err.textContent = "Opslaan mislukte. Probeer het opnieuw."; save.disabled = false; }
  } });

  openSheet(h("div", { class: "sheetin orderform" }, h("div", { class: "handle" }),
    h("h3", { text: "Verkoop" }),
    h("div", { class: "two eq" }, field("Koper", buyer), field("Datum", date)),
    h("div", { class: "two eq" }, field("Totaalprijs kaarten", total), field("Commissie", commission)),
    h("div", { class: "two eq" }, field("Verzending ontvangen", shipIn), field("Verzending betaald", shipOut)),
    field("Overige kosten (verpakking)", other),
    h("p", { class: "mini", text: `De commissie staat op ${s.fee_pct}% van de totaalprijs; vul gerust het exacte bedrag van je Cardmarket-overzicht in. De prijs wordt verdeeld naar de huidige waarde van de kaarten; per kaart aan te passen.` }),
    linesBox, result, err, save));
  recalc();
}
