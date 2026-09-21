// Formulier om een kaart of sealed product aan je collectie toe te voegen (of te bewerken).
import { rest, userId } from "./api.js";
import { eur, h, icon, parseMoney, segment, thumb, toast, num } from "./ui.js";

const GRADES = ["10", "9.5", "9", "8.5", "8", "7", "6", "5", "4", "3", "2", "1"];
const today = () => new Date().toISOString().slice(0, 10);

/** product: {product_id, name, set_name, number, image, price, kind}. editing: bestaande collectieregel. */
export function addForm(product, { onDone, editing } = {}) {
  const e = editing || {};
  const st = {
    graded: Boolean(e.grade_company), company: e.grade_company || "PSA", grade: e.grade || "10",
    condition: e.condition || "NM", qty: e.quantity || 1,
  };
  const price = h("input", { type: "text", inputmode: "decimal", "aria-label": "Aankoopprijs per stuk", value: (e.purchase_price ?? product.price ?? "") === "" ? "" : String(e.purchase_price ?? product.price).replace(".", ",") });
  const date = h("input", { type: "date", "aria-label": "Gekocht op", value: e.purchase_date || today(), max: today() });
  const qty = h("span", { class: "qv", text: String(st.qty) });
  const hint = h("div", { class: "mini" });
  const err = h("p", { class: "err", role: "alert" });
  const typeBox = h("div"), gradeBox = h("div"), condBox = h("div");

  const gradeKey = () => `${st.company}-${st.grade}`;
  async function drawHint() {
    if (!st.graded) { hint.textContent = product.price ? `Marktwaarde nu ${eur(Number(product.price))}` : ""; return; }
    hint.textContent = "Marktwaarde opzoeken…";
    try {
      const r = await rest.get(`prices?select=price,date&product_id=eq.${encodeURIComponent(product.product_id)}&grade_key=eq.${gradeKey()}&order=date.desc&limit=1`);
      hint.textContent = r[0] ? `Marktwaarde ${st.company} ${st.grade} nu ${eur(Number(r[0].price))}` : `Nog geen prijs voor ${st.company} ${st.grade}. We volgen hem vanaf nu.`;
    } catch { hint.textContent = ""; }
  }

  const draw = () => {
    typeBox.replaceChildren(product.kind === "card" ? segment([["raw", "Ongegradeerd"], ["graded", "Gegradeerd"]], st.graded ? "graded" : "raw", (v) => { st.graded = v === "graded"; draw(); }) : "");
    gradeBox.replaceChildren();
    condBox.replaceChildren();
    if (st.graded) {
      const sel = h("select", { "aria-label": "Cijfer", onchange: (ev) => { st.grade = ev.target.value; drawHint(); } },
        ...GRADES.filter((g) => st.company !== "PSA" || !g.includes(".")).map((g) => h("option", { value: g, text: g, selected: g === st.grade })));
      if (st.company === "PSA" && st.grade.includes(".")) st.grade = "10";
      gradeBox.append(h("div", { class: "two eq" },
        h("div", {}, h("div", { class: "lbl2", text: "Bedrijf" }), segment([["PSA", "PSA"], ["BGS", "BGS"], ["CGC", "CGC"]], st.company, (v) => { st.company = v; draw(); })),
        h("div", {}, h("div", { class: "lbl2", text: "Cijfer" }), h("div", { class: "selw" }, sel, icon("chev")))));
    } else if (product.kind === "card") {
      condBox.append(h("div", { class: "lbl2", text: "Conditie" }), segment([["NM", "NM"], ["LP", "LP"], ["MP", "MP"], ["HP", "HP"]], st.condition, (v) => { st.condition = v; }));
    }
    drawHint();
  };

  const save = h("button", { type: "button", class: "cta", text: editing ? "Opslaan" : "Toevoegen aan collectie" });
  save.onclick = async () => {
    const p = parseMoney(price.value);
    if (!p || p <= 0) { err.textContent = "Vul de aankoopprijs in, bijvoorbeeld 28,00."; return; }
    err.textContent = ""; save.disabled = true;
    const row = { product_id: product.product_id, quantity: st.qty, purchase_price: p, purchase_date: date.value || today(),
      condition: st.graded ? null : (product.kind === "card" ? st.condition : null),
      grade_company: st.graded ? st.company : null, grade: st.graded ? st.grade : null };
    try {
      if (editing) await rest.patch("collection", `id=eq.${editing.id}`, row);
      else await rest.insert("collection", [{ user_id: userId(), ...row }]);
      toast(editing ? "Opgeslagen" : "Toegevoegd aan je collectie");
      onDone?.(row);
    } catch (ex) { err.textContent = "Opslaan mislukte. Probeer het opnieuw."; console.error(ex); save.disabled = false; }
  };

  const stepper = h("div", { class: "inp step" },
    h("button", { type: "button", class: "m", "aria-label": "Minder", onclick: () => { st.qty = Math.max(1, st.qty - 1); qty.textContent = st.qty; } }, icon("minus")),
    qty,
    h("button", { type: "button", class: "m", "aria-label": "Meer", onclick: () => { st.qty += 1; qty.textContent = st.qty; } }, icon("plus")));

  draw();
  return h("div", { class: "addform" },
    h("div", { class: "found" }, thumb(product.image, "ph", product.kind === "sealed"),
      h("div", {}, h("h2", { id: "sheet-title", text: product.name }), h("div", { class: "set", text: [product.set_name, product.number ? `nr ${product.number}` : ""].filter(Boolean).join(", ") }))),
    typeBox, gradeBox, condBox,
    h("div", { class: "three" },
      h("div", {}, h("div", { class: "lbl2", text: "Aantal" }), stepper),
      h("div", {}, h("div", { class: "lbl2", text: "Aankoopprijs" }), price),
      h("div", {}, h("div", { class: "lbl2", text: "Gekocht op" }), date)),
    hint, err, save);
}
