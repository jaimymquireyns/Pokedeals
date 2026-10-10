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
const money = (label, value = "", attrs = {}) => h("input", { type: "text", inputmode: "decimal", "aria-label": label, placeholder: "0.00", value, ...attrs });
const field = (label, input) => h("div", {}, h("div", { class: "lbl2", text: label }), input);
const fmtIn = (n) => (n ? String(Math.round(n * 100) / 100) : "");

function stepper(get, set, max = Infinity, onChange = () => {}) {
  const out = h("span", { class: "n num", text: String(get()) });
  const bump = (d) => { set(Math.min(Math.max(1, get() + d), max)); out.textContent = String(get()); onChange(); };
  return h("div", { class: "qty" },
    h("button", { type: "button", class: "m", "aria-label": "Less", onclick: () => bump(-1) }, icon("minus")), out,
    h("button", { type: "button", class: "m", "aria-label": "More", onclick: () => bump(1) }, icon("plus")));
}

// ---------------------------------------------------------------- aankoop
/** Een aankoop met een of meer kaarten van dezelfde verkoper. Verzending en overige kosten worden verdeeld naar
 * verhouding van prijs x aantal. Gegradeerde kaarten voeg je (voorlopig) los toe via de +-knop bij Zoeken. */
export function openPurchaseOrder({ onDone } = {}) {
  const lines = [];
  const seller = h("input", { type: "text", "aria-label": "Seller name", placeholder: "Name or Cardmarket user" });
  const date = h("input", { type: "date", "aria-label": "Purchase date", value: today(), max: today() });
  const ship = money("Shipping");
  const costs = money("Trustee fee");
  const linesBox = h("div", { class: "olines" });
  const summary = h("div", { class: "osum" });
  const err = h("p", { class: "err", role: "alert" });
  const results = h("ul", { class: "opick" });
  const q = h("input", { type: "search", placeholder: "Search a card to add", "aria-label": "Search card", autocomplete: "off" });

  // Kaarten vergeten? Kies hier een eerdere aankoop: de nieuwe kaarten komen erbij, en verzending en trustee fee worden opnieuw over alle kaarten van die aankoop verdeeld.
  let existing = null;                       // regels van de aankoop waaraan we toevoegen
  const title = h("h3", { text: "New purchase" });
  const pickOrder = h("select", { "aria-label": "Add to purchase" }, h("option", { value: "", text: "New purchase" }));
  const orderNote = h("p", { class: "mini", text: "Shipping and trustee fee are split across the cards by price. Enter a price per card." });
  const pickBox = h("div", { class: "orderpick", hidden: true }, h("div", { class: "lbl2", text: "New purchase, or add to one" }), pickOrder);
  const orderMap = new Map();
  const sumOf = (rs, k) => rs.reduce((n, r) => n + Number(r[k] || 0), 0);
  (async () => {
    try {
      const rows = await rest.get("collection?select=id,quantity,purchase_price,purchase_shipping,purchase_costs,purchase_seller,purchase_order,purchase_date,created_at&purchase_order=not.is.null&order=created_at.desc&limit=300");
      for (const r of rows) { if (!orderMap.has(r.purchase_order)) orderMap.set(r.purchase_order, []); orderMap.get(r.purchase_order).push(r); }
      for (const [id, rs] of [...orderMap.entries()].slice(0, 12)) {
        const worth = rs.reduce((n, r) => n + Number(r.purchase_price) * Number(r.quantity), 0);
        pickOrder.append(h("option", { value: id, text: `${rs[0].purchase_seller || "unknown seller"} · ${rs[0].purchase_date || ""} · ${sumOf(rs, "quantity")} cards · ${eur(worth)}` }));
      }
      pickBox.hidden = orderMap.size === 0;
    } catch { /* zonder eerdere aankopen blijft het gewoon een nieuwe aankoop */ }
  })();
  pickOrder.onchange = () => {
    existing = pickOrder.value ? orderMap.get(pickOrder.value) : null;
    title.textContent = existing ? "Add to purchase" : "New purchase";
    orderNote.textContent = existing
      ? "You're adding to an existing purchase. Shipping and trustee fee cover the whole purchase (prefilled with what was there) and are re-split across all its cards."
      : "Shipping and trustee fee are split across the cards by price. Enter a price per card.";
    if (existing) { seller.value = existing[0].purchase_seller || ""; date.value = existing[0].purchase_date || today(); ship.value = fmtIn(sumOf(existing, "purchase_shipping")); costs.value = fmtIn(sumOf(existing, "purchase_costs")); }
    else { ship.value = ""; costs.value = ""; }
    drawSum();
  };

  const total = () => lines.reduce((s, l) => s + (parseMoney(l.price.value) || 0) * l.qty, 0);
  const draw = () => {
    linesBox.replaceChildren(...(lines.length ? lines.map((l, i) => h("div", { class: "oline" },
      thumb(l.p.image, "ph", l.p.kind === "sealed"),
      h("div", { class: "body" },
        h("div", { class: "name", text: l.p.name }),
        h("div", { class: "set", text: [l.p.set_name, l.p.number ? `#${l.p.number}` : ""].filter(Boolean).join(" · ") }),
        h("div", { class: "orow" }, h("span", { class: "mini", text: "Price" }), l.price, stepper(() => l.qty, (v) => { l.qty = v; }, Infinity, drawSum),
          l.p.kind === "card" ? segment([["NM", "NM"], ["LP", "LP"], ["MP", "MP"], ["HP", "HP"]], l.condition, (v) => { l.condition = v; }, "small") : null)),
      h("button", { type: "button", class: "ox", "aria-label": `Remove ${l.p.name}`, onclick: () => { lines.splice(i, 1); draw(); } }, icon("x"))))
      : [h("p", { class: "p14 muted", text: "No cards yet. Search for a card above and tap it." })]));
    drawSum();
  };
  const drawSum = () => {
    const extra = (parseMoney(ship.value) || 0) + (parseMoney(costs.value) || 0);
    summary.textContent = lines.length ? `${lines.reduce((s, l) => s + l.qty, 0)} cards · ${eur(total())} + ${eur(extra)} shipping and trustee fee = ${eur(total() + extra)}` : "";
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
      if (!rows.length) { results.replaceChildren(h("li", { class: "p14 muted", text: "Nothing found. Try name + set code + number, e.g. 'charizard obf 125'." })); return; }
      results.replaceChildren(...rows.map((p) => h("li", {}, h("button", { type: "button", class: "opickrow", onclick: () => {
        const price = money("Price each", fmtIn(Number(p.price) || 0));
        price.oninput = drawSum;
        lines.push({ p, price, qty: 1, condition: "NM" });
        q.value = ""; results.replaceChildren(); draw();
      } }, thumb(p.image, "ph", p.kind === "sealed"),
        h("span", {}, h("b", { text: p.name }), h("small", { text: ` ${p.set_name || ""}${p.number ? " #" + p.number : ""}` })),
        h("span", { class: "num", text: p.price ? eur(Number(p.price)) : "" })))));
    } catch { results.replaceChildren(h("li", { class: "p14 muted", text: "Search failed." })); }
  }, 250);
  q.oninput = () => {   // oude resultaten meteen weg, zodat je nooit per ongeluk een kaart van de vorige zoekopdracht aantikt
    results.replaceChildren(q.value.trim().length >= 2 ? h("li", { class: "p14 muted", text: "Searching…" }) : "");
    search();
  };

  const save = h("button", { class: "cta", type: "button", text: "Save purchase", onclick: async () => {
    err.textContent = "";
    if (!lines.length) { err.textContent = "Add at least one card."; return; }
    if (lines.some((l) => !(parseMoney(l.price.value) > 0))) { err.textContent = "Enter a price for each card."; return; }
    const oldRows = existing || [];
    const weights = [...oldRows.map((r) => Number(r.purchase_price) * Number(r.quantity)), ...lines.map((l) => parseMoney(l.price.value) * l.qty)];
    const shipAll = allocate(parseMoney(ship.value) || 0, weights), costAll = allocate(parseMoney(costs.value) || 0, weights);
    const shipShares = shipAll.slice(oldRows.length), costShares = costAll.slice(oldRows.length);
    const oldShip = shipAll.slice(0, oldRows.length), oldCosts = costAll.slice(0, oldRows.length);
    const order = oldRows.length ? oldRows[0].purchase_order : uid();
    const rows = lines.map((l, i) => ({
      user_id: userId(), product_id: l.p.product_id, quantity: l.qty, condition: l.p.kind === "card" ? l.condition : null,
      grade_company: null, grade: null, purchase_price: parseMoney(l.price.value), purchase_date: date.value || today(),
      purchase_shipping: shipShares[i], purchase_costs: costShares[i], purchase_seller: seller.value.trim() || null, purchase_order: order,
    }));
    save.disabled = true;
    try {
      await rest.insert("collection", rows);
      for (let i = 0; i < oldRows.length; i++) await rest.patch("collection", `id=eq.${oldRows[i].id}`, { purchase_shipping: oldShip[i], purchase_costs: oldCosts[i] });
      toast(`${rows.length} ${rows.length === 1 ? "card" : "cards"} ${oldRows.length ? "added to the purchase" : "added"}`);
      closeSheet(); onDone?.();
    } catch (e) { console.error(e); err.textContent = "Couldn't save. Please try again."; save.disabled = false; }
  } });

  openSheet(h("div", { class: "sheetin orderform" }, h("div", { class: "handle" }),
    title, pickBox,
    h("div", { class: "two eq" }, field("Seller name", seller), field("Purchase date", date)),
    h("div", { class: "two eq" }, field("Shipping", ship), field("Trustee fee", costs)),
    orderNote,
    h("div", { class: "lbl2", text: "Cards" }),
    h("label", { class: "sbox" }, icon("search"), q), results,
    linesBox, summary, err, save));
  draw();
}

// ---------------------------------------------------------------- verkoop
/** De kaarten kies je in de collectielijst zelf (knop "Selecteren"); dit is het ene scherm waar de rest van de verkoop ingevuld wordt.
 * chosen = [{c: collectieregel, qty}]. Bij meer dan één stuk kun je hier het aantal nog aanpassen. */
export function openSaleDetails(chosen, onDone) {
  const s = getSettings();
  const buyer = h("input", { type: "text", "aria-label": "Buyer", placeholder: "Name or Cardmarket user" });
  const date = h("input", { type: "date", "aria-label": "Date", value: today(), max: today() });
  const marketTotal = () => chosen.reduce((t, x) => t + (x.c.value_each || costEach(x.c)) * x.qty, 0);
  const total = money("Total price", fmtIn(marketTotal()));
  let totalTouched = false;
  const shipIn = money("Shipping received");
  const shipOut = money("Shipping paid");
  const commission = money("Commission");
  const other = money("Other costs", "0.50");
  let commissionTouched = false, sharesTouched = false;
  const shareInputs = chosen.map(() => money("Share of price"));
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
  // De kaartregels worden alleen opnieuw opgebouwd als het aantal verandert; bij typen passen we enkel de getallen aan,
  // anders verdwijnt op een gsm bij elke toets het toetsenbord (het invulveld wordt dan vervangen).
  const profitEls = chosen.map(() => h("span", { class: "num" }));
  const renderLines = () => linesBox.replaceChildren(...chosen.map((x, i) => h("div", { class: "oline" },
    thumb(x.c.image, "ph", x.c.kind === "sealed", x.c.kind === "sealed" ? "" : [x.c.name, x.c.number ? "#" + x.c.number : ""].filter(Boolean).join(" ")),
    h("div", { class: "body" },
      h("div", { class: "name", text: `${x.qty > 1 ? x.qty + "x " : ""}${x.c.name}` }),
      h("div", { class: "set", text: `cost you ${eur(costOf(x))}` }),
      x.c.quantity > 1 ? h("div", { class: "orow" }, stepper(() => x.qty, (v) => { x.qty = v; }, x.c.quantity, qtyChanged), h("span", { class: "mini", text: `of ${x.c.quantity}` })) : null,
      h("div", { class: "orow" }, shareInputs[i], profitEls[i])))));
  const recalc = () => {
    if (!commissionTouched) commission.value = fmtIn(Math.round((parseMoney(total.value) || 0) * s.fee_pct) / 100);
    if (!sharesTouched) fillShares();
    const lines = chosen.map((x, i) => ({ price_share: parseMoney(shareInputs[i].value) || 0, cost_total: costOf(x) }));
    const pr = saleProfit(sale(), lines);
    const sumShares = Math.round(lines.reduce((t, l) => t + l.price_share, 0) * 100) / 100;
    const off = Math.round(((parseMoney(total.value) || 0) - sumShares) * 100) / 100;
    profitEls.forEach((el, i) => { el.className = "num " + (pr.per[i] < 0 ? "neg" : "pos"); el.textContent = signedEur(pr.per[i]); });
    result.replaceChildren(
      h("div", { class: "bigline" }, h("span", { text: "Profit on this sale" }), h("b", { class: "num " + (pr.total < 0 ? "neg" : "pos"), text: signedEur(pr.total) })),
      off ? h("p", { class: "err", text: `The shares add up to ${eur(sumShares)}, ${eur(Math.abs(off))} ${off > 0 ? "less" : "more"} than the total price.` }) : null);
    return { lines, off };
  };
  total.oninput = () => { totalTouched = true; sharesTouched = false; recalc(); };
  const qtyChanged = () => { if (!totalTouched) total.value = fmtIn(marketTotal()); sharesTouched = false; renderLines(); recalc(); };
  commission.oninput = () => { commissionTouched = true; recalc(); };
  [shipIn, shipOut, other].forEach((el) => { el.oninput = recalc; });
  // prijs per kaart aangepast: het totaal volgt (de som van de kaarten), en daarmee ook de commissie
  shareInputs.forEach((inp) => { inp.oninput = () => {
    sharesTouched = true; totalTouched = true;
    total.value = fmtIn(Math.round(shareInputs.reduce((t, x) => t + (parseMoney(x.value) || 0), 0) * 100) / 100);
    recalc();
  }; });

  const save = h("button", { class: "cta", type: "button", text: "Save sale", onclick: async () => {
    err.textContent = "";
    const tp = parseMoney(total.value);
    if (!(tp > 0)) { err.textContent = "Enter the total price."; return; }
    const { lines, off } = recalc();
    if (off) { err.textContent = "Make the shares add up to the total price."; return; }
    const id = uid();
    save.disabled = true;
    try {
      await rest.insert("sales", [{ id, user_id: userId(), sale_date: date.value || today(), buyer: buyer.value.trim() || null, total_price: tp, ...sale() }]);
      const items = chosen.map((x, i) => ({
        sale_id: id, user_id: userId(), product_id: x.c.product_id, quantity: x.qty, condition: x.c.condition || null,
        grade_company: x.c.grade_company || null, grade: x.c.grade || null, price_share: lines[i].price_share, cost_total: lines[i].cost_total,
        purchase_date: x.c.purchase_date || null, purchase_seller: x.c.purchase_seller || null, purchase_order: x.c.purchase_order || null }));
      await insertSaleItems(items);
      for (const x of chosen) {   // de verkochte stuks uit 'In bezit' halen; bij een deel blijven de kosten naar verhouding staan
        if (x.qty >= x.c.quantity) await rest.del("collection", `id=eq.${x.c.id}`);
        else {
          const keep = (x.c.quantity - x.qty) / x.c.quantity;
          await rest.patch("collection", `id=eq.${x.c.id}`, { quantity: x.c.quantity - x.qty,
            purchase_shipping: Math.round(Number(x.c.purchase_shipping || 0) * keep * 100) / 100,
            purchase_costs: Math.round(Number(x.c.purchase_costs || 0) * keep * 100) / 100 });
        }
      }
      toast("Sale saved");
      closeSheet(); onDone?.();
    } catch (e) { console.error(e); err.textContent = "Couldn't save. Please try again."; save.disabled = false; }
  } });

  openSheet(h("div", { class: "sheetin orderform" }, h("div", { class: "handle" }),
    h("h3", { text: "Sale" }),
    h("div", { class: "two eq" }, field("Buyer", buyer), field("Date", date)),
    h("div", { class: "two eq" }, field("Total card price", total), field("Commission", commission)),
    h("div", { class: "two eq" }, field("Shipping received", shipIn), field("Shipping paid", shipOut)),
    field("Other costs (packaging)", other),
    h("p", { class: "mini", text: `Commission is set to ${s.fee_pct}% of the total price; feel free to enter the exact amount from Cardmarket. The price is split by the cards' current value; you can adjust it per card.` }),
    linesBox, result, err, save));
  renderLines();
  recalc();
}

// ---------------------------------------------------------------- hulp: oudere databases
/** Verkochte kaarten bewaren nu ook van wie je ze kocht (purchase_seller/purchase_order). Is supabase/schema.sql nog niet opnieuw
 * gedraaid, dan bestaan die kolommen nog niet: dan slaan we de verkoop gewoon zonder die twee velden op. */
const missingColumn = (e) => /purchase_(seller|order)/.test(String(e?.message || "")) && /column|schema cache/i.test(String(e?.message || ""));
const withoutPurchaseInfo = (rows) => rows.map(({ purchase_seller, purchase_order, ...r }) => r);   // eslint-disable-line no-unused-vars
export async function insertSaleItems(items) {
  try { return await rest.insert("sale_items", items); } catch (e) {
    if (!missingColumn(e)) throw e;
    return rest.insert("sale_items", withoutPurchaseInfo(items));
  }
}

// ---------------------------------------------------------------- aankoop aanpassen
/** Een bestaande aankoop corrigeren: verkoper, datum, verzending en trustee fee (opnieuw verdeeld), en per kaart prijs, aantal en
 * staat. Een kaart weghalen of de hele aankoop verwijderen kan ook. Alleen kaarten die je nog hebt; verkochte kaarten pas je aan
 * bij de verkoop (daar staat hun kostprijs). rows = collectieregels van deze aankoop (uit v_collection). */
export function openPurchaseEdit(rows, onDone) {
  const lines = rows.map((r) => ({ r, price: money("Price each", fmtIn(Number(r.purchase_price))), qty: Number(r.quantity) || 1,
    condition: r.condition || "NM", removed: false }));
  const sum = (k) => rows.reduce((n, r) => n + Number(r[k] || 0), 0);
  const seller = h("input", { type: "text", "aria-label": "Seller name", placeholder: "Name or Cardmarket user", value: rows[0].purchase_seller || "" });
  const date = h("input", { type: "date", "aria-label": "Purchase date", value: rows[0].purchase_date || today(), max: today() });
  const ship = money("Shipping", fmtIn(sum("purchase_shipping")));
  const costs = money("Trustee fee", fmtIn(sum("purchase_costs")));
  const linesBox = h("div", { class: "olines" });
  const summary = h("div", { class: "osum" });
  const err = h("p", { class: "err", role: "alert" });
  const live = () => lines.filter((l) => !l.removed);
  const drawSum = () => {
    const ls = live(), cards = ls.reduce((s, l) => s + (parseMoney(l.price.value) || 0) * l.qty, 0);
    const extra = (parseMoney(ship.value) || 0) + (parseMoney(costs.value) || 0);
    summary.textContent = ls.length ? `${ls.reduce((s, l) => s + l.qty, 0)} pcs · ${eur(cards)} + ${eur(extra)} shipping and trustee fee = ${eur(cards + extra)}` : "All cards removed: saving deletes this purchase.";
  };
  const draw = () => {
    linesBox.replaceChildren(...lines.map((l) => l.removed
      ? h("div", { class: "oline gone" }, thumb(l.r.image, "ph", l.r.kind === "sealed"),
          h("div", { class: "body" }, h("div", { class: "name", text: l.r.name }), h("div", { class: "set", text: "will be removed" })),
          h("button", { type: "button", class: "linkbtn", text: "Restore", onclick: () => { l.removed = false; draw(); } }))
      : h("div", { class: "oline" }, thumb(l.r.image, "ph", l.r.kind === "sealed"),
          h("div", { class: "body" },
            h("div", { class: "name", text: l.r.name }),
            h("div", { class: "set", text: [l.r.set_name, l.r.number && l.r.kind === "card" ? `#${l.r.number}` : ""].filter(Boolean).join(" · ") }),
            h("div", { class: "orow" }, h("span", { class: "mini", text: "Price" }), l.price, stepper(() => l.qty, (v) => { l.qty = v; }, Infinity, drawSum),
              l.r.kind === "card" && !l.r.grade_company ? segment([["NM", "NM"], ["LP", "LP"], ["MP", "MP"], ["HP", "HP"]], l.condition, (v) => { l.condition = v; }, "small") : null)),
          h("button", { type: "button", class: "ox", "aria-label": `Remove ${l.r.name} from this purchase`, onclick: () => { l.removed = true; draw(); } }, icon("x")))));
    drawSum();
  };
  lines.forEach((l) => { l.price.oninput = drawSum; });
  ship.oninput = drawSum; costs.oninput = drawSum;

  const removeAll = async () => {
    if (!confirm(`Delete this whole purchase (${rows.length} ${rows.length === 1 ? "line" : "lines"}) from your collection? This can't be undone.`)) return;
    try {
      for (const r of rows) await rest.del("collection", `id=eq.${r.id}`);
      toast("Purchase deleted"); closeSheet(); onDone?.();
    } catch (e) { console.error(e); err.textContent = "Couldn't delete. Please try again."; }
  };
  const save = h("button", { class: "cta", type: "button", text: "Save changes", onclick: async () => {
    err.textContent = "";
    const ls = live();
    if (!ls.length) { await removeAll(); return; }
    if (ls.some((l) => !(parseMoney(l.price.value) > 0))) { err.textContent = "Enter a price for each card."; return; }
    const weights = ls.map((l) => parseMoney(l.price.value) * l.qty);
    const shipShares = allocate(parseMoney(ship.value) || 0, weights), costShares = allocate(parseMoney(costs.value) || 0, weights);
    // meerdere kaarten zonder bestelnummer (oude aankoop): nu één bestelling van maken, zodat ze voortaan bij elkaar blijven
    const order = rows.find((r) => r.purchase_order)?.purchase_order || (ls.length > 1 ? uid() : null);
    save.disabled = true;
    try {
      for (const l of lines.filter((x) => x.removed)) await rest.del("collection", `id=eq.${l.r.id}`);
      for (let i = 0; i < ls.length; i++) {
        const l = ls[i];
        await rest.patch("collection", `id=eq.${l.r.id}`, {
          purchase_price: parseMoney(l.price.value), quantity: l.qty,
          condition: l.r.kind === "card" && !l.r.grade_company ? l.condition : l.r.condition || null,
          purchase_seller: seller.value.trim() || null, purchase_date: date.value || today(),
          purchase_shipping: shipShares[i], purchase_costs: costShares[i], purchase_order: order });
      }
      toast("Purchase updated"); closeSheet(); onDone?.();
    } catch (e) { console.error(e); err.textContent = "Couldn't save. Please try again."; save.disabled = false; }
  } });

  openSheet(h("div", { class: "sheetin orderform" }, h("div", { class: "handle" }),
    h("h3", { text: "Edit purchase" }),
    h("div", { class: "two eq" }, field("Seller name", seller), field("Purchase date", date)),
    h("div", { class: "two eq" }, field("Shipping", ship), field("Trustee fee", costs)),
    h("p", { class: "mini", text: "Shipping and trustee fee cover the cards below and are re-split by price." }),
    h("div", { class: "lbl2", text: "Cards" }),
    linesBox, summary, err, save,
    h("button", { type: "button", class: "linkbtn danger", text: "Delete whole purchase", onclick: removeAll })));
  draw();
}

// ---------------------------------------------------------------- verkoop aanpassen
/** Een bestaande verkoop corrigeren: koper, datum, bedragen en per kaart het deel van de prijs en de kostprijs.
 * s = verkoop uit loadSales() (met s.lines). Kaarten terug in je collectie zetten gaat via "Verkoop terugdraaien". */
export function openSaleEdit(s, onDone) {
  const buyer = h("input", { type: "text", "aria-label": "Buyer", placeholder: "Name or Cardmarket user", value: s.buyer || "" });
  const date = h("input", { type: "date", "aria-label": "Date", value: s.sale_date || today(), max: today() });
  const total = money("Total price", fmtIn(Number(s.total_price)));
  const commission = money("Commission", fmtIn(Number(s.commission)));
  const shipIn = money("Shipping received", fmtIn(Number(s.shipping_received)));
  const shipOut = money("Shipping paid", fmtIn(Number(s.shipping_paid)));
  const other = money("Other costs", fmtIn(Number(s.other_costs)));
  const shareIn = s.lines.map((l) => money("Share of price", fmtIn(Number(l.price_share))));
  const costIn = s.lines.map((l) => money("Cost", fmtIn(Number(l.cost_total))));
  const linesBox = h("div", { class: "olines" });
  const result = h("div", { class: "osum" });
  const err = h("p", { class: "err", role: "alert" });
  const sale = () => ({ shipping_received: parseMoney(shipIn.value) || 0, shipping_paid: parseMoney(shipOut.value) || 0,
    commission: parseMoney(commission.value) || 0, other_costs: parseMoney(other.value) || 0 });
  const recalc = () => {
    const lines = s.lines.map((l, i) => ({ price_share: parseMoney(shareIn[i].value) || 0, cost_total: parseMoney(costIn[i].value) || 0 }));
    const pr = saleProfit(sale(), lines);
    const sumShares = Math.round(lines.reduce((t, l) => t + l.price_share, 0) * 100) / 100;
    const off = Math.round(((parseMoney(total.value) || 0) - sumShares) * 100) / 100;
    result.replaceChildren(
      h("div", { class: "bigline" }, h("span", { text: "Profit on this sale" }), h("b", { class: "num " + (pr.total < 0 ? "neg" : "pos"), text: signedEur(pr.total) })),
      off ? h("p", { class: "err", text: `The shares add up to ${eur(sumShares)}, ${eur(Math.abs(off))} ${off > 0 ? "less" : "more"} than the total price.` }) : null);
    return { lines, off };
  };
  linesBox.replaceChildren(...s.lines.map((l, i) => h("div", { class: "oline" },
    thumb(l.image, "ph", l.kind === "sealed"),
    h("div", { class: "body" },
      h("div", { class: "name", text: `${l.quantity > 1 ? l.quantity + "x " : ""}${l.name}` }),
      h("div", { class: "set", text: [l.set_name, l.number && l.kind === "card" ? `#${l.number}` : ""].filter(Boolean).join(" · ") }),
      h("div", { class: "orow" }, h("span", { class: "mini", text: "Sold for" }), shareIn[i]),
      h("div", { class: "orow" }, h("span", { class: "mini", text: "Cost you" }), costIn[i])))));
  [total, commission, shipIn, shipOut, other, ...shareIn, ...costIn].forEach((el) => { el.oninput = recalc; });
  // de totaalprijs aangepast en er is maar één kaart: dan is zijn deel gewoon de totaalprijs
  total.addEventListener("input", () => { if (shareIn.length === 1) shareIn[0].value = total.value; recalc(); });

  const save = h("button", { class: "cta", type: "button", text: "Save changes", onclick: async () => {
    err.textContent = "";
    const tp = parseMoney(total.value);
    if (!(tp > 0)) { err.textContent = "Enter the total price."; return; }
    const { lines, off } = recalc();
    if (off) { err.textContent = "Make the shares add up to the total price."; return; }
    save.disabled = true;
    try {
      await rest.patch("sales", `id=eq.${s.id}`, { buyer: buyer.value.trim() || null, sale_date: date.value || today(), total_price: tp, ...sale() });
      for (let i = 0; i < s.lines.length; i++) {
        await rest.patch("sale_items", `id=eq.${s.lines[i].id}`, { price_share: lines[i].price_share, cost_total: lines[i].cost_total });
      }
      toast("Sale updated"); closeSheet(); onDone?.();
    } catch (e) { console.error(e); err.textContent = "Couldn't save. Please try again."; save.disabled = false; }
  } });

  openSheet(h("div", { class: "sheetin orderform" }, h("div", { class: "handle" }),
    h("h3", { text: "Edit sale" }),
    h("div", { class: "two eq" }, field("Buyer", buyer), field("Date", date)),
    h("div", { class: "two eq" }, field("Total card price", total), field("Commission", commission)),
    h("div", { class: "two eq" }, field("Shipping received", shipIn), field("Shipping paid", shipOut)),
    field("Other costs (packaging)", other),
    h("p", { class: "mini", text: "Per card: what you sold it for (together the total price) and what it cost you. To return cards to your collection, use 'Undo sale'." }),
    linesBox, result, err, save));
  recalc();
}
