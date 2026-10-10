// Formulier om een kaart of sealed product aan je collectie toe te voegen (of te bewerken).
import { rest, userId } from "./api.js";
import { eur, h, icon, parseMoney, segment, thumb, toast, num } from "./ui.js";

const LANGS = ["English", "German", "French", "Italian", "Spanish", "Dutch", "Portuguese", "Japanese", "Korean", "Chinese"];
const VARIANTS = ["Normal", "Reverse holo", "1st edition", "Stamped"];
const GRADES = ["10", "9.5", "9", "8.5", "8", "7", "6", "5", "4", "3", "2", "1"];
const today = () => new Date().toISOString().slice(0, 10);

/** Hoeveel stuks van precies dit product, in dezelfde staat (zelfde graad, of bij ongegradeerd dezelfde conditie), staan al in je collectie. */
async function ownedCount(productId, row) {
  const rows = await rest.get(`collection?select=quantity,condition,grade_company,grade&product_id=eq.${encodeURIComponent(productId)}`);
  return rows
    .filter((r) => (r.grade_company || null) === row.grade_company && (r.grade || null) === row.grade && (r.grade_company ? true : (r.condition || null) === row.condition))
    .reduce((s, r) => s + Number(r.quantity || 0), 0);
}

/** product: {product_id, name, set_name, number, image, price, kind}. editing: bestaande collectieregel. */
export function addForm(product, { onDone, editing } = {}) {
  const e = editing || {};
  const st = {
    graded: Boolean(e.grade_company), company: e.grade_company || "PSA", grade: e.grade || "10",
    condition: e.condition || "NM", qty: e.quantity || 1,
  };
  const pick = (label, opts, cur) => h("div", { class: "selw" }, h("select", { "aria-label": label }, ...opts.map((o) => h("option", { value: o, text: o, selected: o === cur }))), icon("chev"));
  const langSel = pick("Language", LANGS, e.language || "English");
  const varSel = pick("Variant", VARIANTS, e.variant || "Normal");
  const price = h("input", { type: "text", inputmode: "decimal", "aria-label": "Purchase price each", value: (e.purchase_price ?? product.price ?? "") === "" ? "" : String(e.purchase_price ?? product.price) });
  const date = h("input", { type: "date", "aria-label": "Bought on", value: e.purchase_date || today(), max: today() });
  // verzending die je als koper betaalde, eventueel voor meerdere kaarten uit dezelfde bestelling
  const ship = h("input", { type: "text", inputmode: "decimal", "aria-label": "Shipping", placeholder: "0.00",
    value: Number(e.purchase_shipping) > 0 ? String(e.purchase_shipping) : "" });
  const orderCards = h("input", { type: "number", min: "1", inputmode: "numeric", "aria-label": "Cards in that order", value: String(e.quantity || 1) });
  const seller = h("input", { type: "text", "aria-label": "Seller name", placeholder: "Name or Cardmarket user", value: e.purchase_seller || "" });
  const costs = h("input", { type: "text", inputmode: "decimal", "aria-label": "Trustee fee", placeholder: "0.00",
    value: Number(e.purchase_costs) > 0 ? String(e.purchase_costs) : "" });
  const shipHint = h("div", { class: "mini" });
  const shipShare = () => {
    const total = parseMoney(ship.value) || 0;
    const n = Math.max(parseInt(orderCards.value, 10) || 1, 1);
    return Math.round((total / n) * st.qty * 100) / 100;
  };
  const drawShip = () => {
    const share = shipShare();
    shipHint.textContent = share > 0 ? `${eur(share)} shipping counts towards the cost of ${st.qty > 1 ? "these " + st.qty + " cards" : "this card"}.` : "";
  };
  ship.oninput = drawShip; orderCards.oninput = drawShip;
  const qty = h("span", { class: "qv", text: String(st.qty) });
  const hint = h("div", { class: "mini" });
  const err = h("p", { class: "err", role: "alert" });
  const typeBox = h("div"), gradeBox = h("div"), condBox = h("div");

  const gradeKey = () => `${st.company}-${st.grade}`;
  async function drawHint() {
    if (!st.graded) { hint.textContent = product.price ? `Market value now ${eur(Number(product.price))}` : ""; return; }
    hint.textContent = "Looking up market value…";
    try {
      const r = await rest.get(`prices?select=price,date&product_id=eq.${encodeURIComponent(product.product_id)}&grade_key=eq.${gradeKey()}&order=date.desc&limit=1`);
      hint.textContent = r[0] ? `Market value ${st.company} ${st.grade} now ${eur(Number(r[0].price))}` : `No price yet for ${st.company} ${st.grade}. We'll track it from now on.`;
    } catch { hint.textContent = ""; }
  }

  const draw = () => {
    typeBox.replaceChildren(product.kind === "card" ? segment([["raw", "Raw"], ["graded", "Graded"]], st.graded ? "graded" : "raw", (v) => { st.graded = v === "graded"; draw(); }) : "");
    gradeBox.replaceChildren();
    condBox.replaceChildren();
    if (st.graded) {
      const sel = h("select", { "aria-label": "Grade", onchange: (ev) => { st.grade = ev.target.value; drawHint(); } },
        ...GRADES.filter((g) => st.company !== "PSA" || !g.includes(".")).map((g) => h("option", { value: g, text: g, selected: g === st.grade })));
      if (st.company === "PSA" && st.grade.includes(".")) st.grade = "10";
      gradeBox.append(h("div", { class: "two eq" },
        h("div", {}, h("div", { class: "lbl2", text: "Company" }), segment([["PSA", "PSA"], ["BGS", "BGS"], ["CGC", "CGC"]], st.company, (v) => { st.company = v; draw(); })),
        h("div", {}, h("div", { class: "lbl2", text: "Grade" }), h("div", { class: "selw" }, sel, icon("chev")))));
    } else if (product.kind === "card") {
      condBox.append(h("div", { class: "lbl2", text: "Condition" }), segment([["NM", "NM"], ["LP", "LP"], ["MP", "MP"], ["HP", "HP"]], st.condition, (v) => { st.condition = v; }));
    }
    drawHint();
  };

  const save = h("button", { type: "button", class: "cta", text: editing ? "Save" : "Add to collection" });
  save.onclick = async () => {
    const p = parseMoney(price.value);
    if (!p || p <= 0) { err.textContent = "Enter the purchase price, e.g. 28.00."; return; }
    err.textContent = ""; save.disabled = true;
    const row = { product_id: product.product_id, quantity: st.qty, purchase_price: p, purchase_shipping: shipShare(), purchase_costs: parseMoney(costs.value) || 0, purchase_seller: seller.value.trim() || null, purchase_date: date.value || today(),
      condition: st.graded ? null : (product.kind === "card" ? st.condition : null),
      grade_company: st.graded ? st.company : null, grade: st.graded ? st.grade : null };
    if (product.kind === "card") {
      const lang = langSel.querySelector("select").value, variant = varSel.querySelector("select").value;
      row.language = lang === "English" ? null : lang;
      row.variant = variant === "Normal" ? null : variant;
    }
    try {
      if (editing) await rest.patch("collection", `id=eq.${editing.id}`, row);
      else {
        // waarschuwing als je exact dezelfde kaart in dezelfde staat al hebt (voorkomt per ongeluk dubbel invoeren)
        const have = await ownedCount(product.product_id, row).catch(() => 0);
        if (have > 0 && !confirm(`You already have ${have} of these in your collection (same condition). Add another anyway?`)) {
          save.disabled = false;
          return;
        }
        await rest.insert("collection", [{ user_id: userId(), ...row }]);
      }
      toast(editing ? "Saved" : "Added to your collection");
      onDone?.(row);
    } catch (ex) { err.textContent = "Couldn't save. Please try again."; console.error(ex); save.disabled = false; }
  };

  const stepper = h("div", { class: "inp step" },
    h("button", { type: "button", class: "m", "aria-label": "Fewer", onclick: () => { st.qty = Math.max(1, st.qty - 1); qty.textContent = st.qty; drawShip(); } }, icon("minus")),
    qty,
    h("button", { type: "button", class: "m", "aria-label": "More", onclick: () => { st.qty += 1; qty.textContent = st.qty; if ((parseInt(orderCards.value, 10) || 1) < st.qty) orderCards.value = String(st.qty); drawShip(); } }, icon("plus")));

  draw();
  drawShip();
  return h("div", { class: "addform" },
    h("div", { class: "found" }, thumb(product.image, "ph", product.kind === "sealed", product.kind === "sealed" ? "" : [product.name, product.number ? "#" + product.number : ""].filter(Boolean).join(" ")),
      h("div", {}, h("h2", { id: "sheet-title", text: product.name }), h("div", { class: "set", text: [product.set_name, product.number ? `no. ${product.number}` : ""].filter(Boolean).join(", ") }))),
    typeBox, gradeBox, condBox,
    product.kind === "card" ? h("div", { class: "two eq" },
      h("div", {}, h("div", { class: "lbl2", text: "Language" }), langSel),
      h("div", {}, h("div", { class: "lbl2", text: "Variant" }), varSel)) : null,
    h("div", { class: "three" },
      h("div", {}, h("div", { class: "lbl2", text: "Quantity" }), stepper),
      h("div", {}, h("div", { class: "lbl2", text: "Purchase price" }), price),
      h("div", {}, h("div", { class: "lbl2", text: "Bought on" }), date)),
    h("div", { class: "two eq" },
      h("div", {}, h("div", { class: "lbl2", text: "Shipping" }), ship),
      h("div", {}, h("div", { class: "lbl2", text: "Cards in that order" }), orderCards)),
    shipHint,
    h("div", { class: "two eq" },
      h("div", {}, h("div", { class: "lbl2", text: "Seller name" }), seller),
      h("div", {}, h("div", { class: "lbl2", text: "Trustee fee" }), costs)),
    hint, err, save);
}
