// Herbruikbare stukjes: labels, kansbalken en lijstrijen.
import { eur, h, icon, pp, signed, thumb } from "./ui.js";
import { gradeLabel } from "./model.js";

export const go = (hash) => { location.hash = hash; };
export const detailHash = (pid, cid) => `#/detail/${encodeURIComponent(pid)}${cid ? `?c=${cid}` : ""}`;

export const kindTag = (kind) => h("span", { class: "tag" + (kind === "sealed" ? " s" : ""), text: kind === "sealed" ? "sealed" : "kaart" });
export const pill = (label) => h("span", { class: "pill " + (label.startsWith("koop") ? "koop" : label.startsWith("verkoop") ? "verkoop" : label.startsWith("winst") ? "winst" : ""), text: label });
export const gradeTag = (c) => (gradeLabel(c) ? h("span", { class: "gr", text: gradeLabel(c) }) : null);

/** Enkelzijdige balk voor Home: kans op stijging + verwachte stijging na kosten. */
export function upBar(pUp, net) {
  const fill = h("i"); fill.style.width = Math.min(pUp * 100, 100) + "%";
  return h("div", { class: "l3" },
    h("b", { text: pp(pUp) }), h("span", { class: "lbl", text: "kans" }),
    h("div", { class: "bar1", role: "img", "aria-label": `Kans op stijging ${pp(pUp)}` }, fill),
    h("span", { class: "nt" }, h("b", { text: signed(net) }), " ", h("span", { class: "lbl", text: "netto" })));
}

/** Tweezijdige balk: rood = kans op daling, groen = kans op stijging. */
export function chanceBar(pUp, pDown) {
  const scale = (p) => Math.min(p / 0.8, 1) * 100 + "%";
  const l = h("i"); l.style.width = scale(pDown);
  const r = h("i"); r.style.width = scale(pUp);
  return h("div", { class: "chance", role: "img", "aria-label": `Kans op daling ${pp(pDown)}, kans op stijging ${pp(pUp)}` },
    h("span", { class: "d num", text: pp(pDown) }),
    h("div", { class: "track" }, h("div", { class: "l" }, l), h("div", { class: "r" }, r)),
    h("span", { class: "u num", text: pp(pUp) }));
}

export function oppRow(r, net) {
  return h("li", {}, h("button", { class: "row", type: "button", onclick: () => go(detailHash(r.product_id)) },
    thumb(r.image, "ph", r.kind === "sealed"),
    h("div", { class: "body" },
      h("div", { class: "l1" }, h("span", { class: "name", text: r.name }), h("span", { class: "price num", text: eur(r.price) })),
      h("div", { class: "l2" }, h("span", { class: "set", text: r.set_name || "" }, r.number && r.kind === "card" ? ` #${r.number}` : ""), kindTag(r.kind)),
      upBar(r.p_up, net))));
}

export function collRow(c, { valueEach, alerted, gain: gainOverride }) {
  const total = (valueEach ?? c.purchase_price) * c.quantity;
  const gain = gainOverride !== undefined ? gainOverride : valueEach ? valueEach / c.purchase_price - 1 : null;
  const cls = gain == null ? "" : gain < 0 ? " neg" : "";
  return h("li", {}, h("button", { class: "rowc", type: "button", onclick: () => go(detailHash(c.product_id, c.id)) },
    thumb(c.image, "ph", c.kind === "sealed"),
    h("div", { class: "body" },
      h("span", { class: "nm" }, h("span", { class: "name", text: c.name }), gradeTag(c), alerted ? h("span", { class: "mini-bell", role: "img", "aria-label": "Prijsmelding actief" }, icon("bell")) : null),
      h("span", { class: "set", text: (c.set_name || "") + (c.number && c.kind === "card" ? ` #${c.number}` : "") }),
      h("span", { class: "set", text: `${c.quantity > 1 ? c.quantity + "x, " : ""}gekocht voor ${eur(c.purchase_price)}` })),
    h("div", { class: "p" }, h("span", { class: "v num", text: eur(total) }),
      h("span", { class: "pc" + cls, text: gain == null ? "prijs onbekend" : signed(gain) }))));
}

export const emptyNote = (text) => h("li", { class: "empty", text });
export const note = (title, ...body) => h("div", { class: "note" }, title ? h("strong", { text: title }) : null, ...body);
