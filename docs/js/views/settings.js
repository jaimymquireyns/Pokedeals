import { getSession, isLoggedIn, signOut, userEmail } from "../api.js";
import { brandmark, go } from "../components.js";
import { SHOW_PREDICTIONS } from "../model.js";
import { getSettings, loadSettings, saveSettings } from "../prefs.js";
import { disablePush, enablePush, hasSubscription, pushPermission, pushSupported } from "../push.js";
import { debounce, h, icon, parseMoney, segment, toast, toggle } from "../ui.js";

export async function settingsView(root) {
  await loadSettings();
  let s = getSettings();
  const flash = debounce(() => toast("Opgeslagen"), 400);
  const set = async (patch) => {
    s = { ...s, ...patch };
    try { await saveSettings(patch); flash(); } catch { toast("Opslaan mislukte"); }
  };
  const money = (key, label, suffix) => h("label", { class: "trow" }, h("span", { class: "t", text: label }),
    h("span", { class: "sfx" }, h("input", { type: "text", inputmode: "decimal", "aria-label": label, value: String(s[key]).replace(".", ","),
      onchange: (e) => { const v = parseMoney(e.target.value); if (v != null && v >= 0) set({ [key]: v }); else e.target.value = String(s[key]).replace(".", ","); } }), suffix));
  const row = (title, sub, ctl) => h("div", { class: "trow" }, h("div", {}, h("div", { class: "t", text: title }), sub ? h("div", { class: "s", text: sub }) : null), ctl);

  const devBtn = h("button", { class: "btn small", type: "button" });
  const drawDevice = async () => {
    if (!isLoggedIn()) { devBtn.replaceChildren("Log in voor meldingen"); devBtn.onclick = () => go("#/login?next=" + encodeURIComponent("#/settings")); return; }
    if (!pushSupported()) { devBtn.replaceChildren("Niet ondersteund op dit toestel"); devBtn.disabled = true; return; }
    const on = pushPermission() === "granted" && (await hasSubscription());
    devBtn.replaceChildren(on ? "Meldingen op dit toestel uitzetten" : "Meldingen op dit toestel aanzetten");
    devBtn.onclick = async () => {
      try { on ? await disablePush() : await enablePush(); toast(on ? "Uitgezet" : "Meldingen staan aan"); } catch (e) { toast(e.message); }
      drawDevice();
    };
  };
  drawDevice();

  root.replaceChildren(h("div", { class: "page" },
    h("div", { class: "topbar" }, h("button", { class: "back", type: "button", onclick: () => history.back() }, icon("back"), h("span", { text: "Terug" }))),
    brandmark(),
    h("div", { class: "head" }, h("h1", { text: "Instellingen" })),
    h("div", { class: "grp" }, h("h3", { text: "Collectie" }),
      h("div", { class: "lbl2", text: "Aandacht nodig vanaf een prijsbeweging van" }),
      segment([[10, "10%"], [15, "15%"], [20, "20%"], [25, "25%"]], Number(s.attn_pct) || 15, (v) => set({ attn_pct: v })),
      h("p", { class: "p14 muted", text: "Over de afgelopen 30 dagen, omhoog of omlaag." })),
    !SHOW_PREDICTIONS ? null : h("div", { class: "grp" }, h("h3", { text: "Kansen" }),
      h("div", { class: "lbl2", text: "Kijk vooruit" }), segment([[14, "14 dagen"], [30, "30 dagen"], [60, "60 dagen"]], s.horizon, (v) => set({ horizon: v })),
      h("div", { class: "lbl2 gap", text: "Bewegingsdrempel" }), segment([[10, "10%"], [20, "20%"]], s.pct, (v) => set({ pct: v })),
      row("Alleen kansen met netto winst", "Na verkoopkosten en verzending", toggle(s.net_only, (v) => set({ net_only: v }), "Alleen netto winst")),
      money("net_min_pct", "Minimale netto winst", "%")),
    h("div", { class: "grp" }, h("h3", { text: "Verkoopkosten" }),
      money("fee_pct", "Kosten per verkoop (Cardmarket-commissie + Trustee Service)", "%"),
      h("p", { class: "p14 muted", text: "De verzending bij het verkopen betaalt de koper. Wat wel telt: de verzending die jij bij het kopen betaalde (vul die in bij je aankoop) en € 0,50 verpakking per verkoop. Voor kaarten die je nog niet hebt, schatten we de verzending bij aankoop op € 1,50 tot € 15, afhankelijk van de prijs." })),
    h("div", { class: "grp" }, h("h3", { text: "Meldingen" }),
      row("Dagelijkse samenvatting", "Elke ochtend rond 08:00 nieuwe kansen en waar je aandacht aan moet geven", toggle(s.digest, (v) => set({ digest: v }), "Dagelijkse samenvatting")),
      row("Prijsmeldingen", "Als een prijs in jouw bereik komt", toggle(s.price_alerts, (v) => set({ price_alerts: v }), "Prijsmeldingen")),
      devBtn),
    !SHOW_PREDICTIONS ? null : h("div", { class: "grp" }, h("button", { class: "trow linkrow", type: "button", onclick: () => go("#/track") }, h("span", { class: "t", text: "Trackrecord bekijken" }), icon("right"))),
    h("div", { class: "grp" }, h("h3", { text: "Account" }),
      h("p", { class: "p14 muted", text: isLoggedIn() ? `Ingelogd als ${userEmail() || getSession()?.user?.email || "?"}` : "Niet ingelogd" }),
      isLoggedIn() ? h("button", { class: "btn", type: "button", text: "Uitloggen", onclick: async () => { await signOut(); go("#/home"); } })
        : h("button", { class: "btn", type: "button", text: "Inloggen", onclick: () => go("#/login?next=" + encodeURIComponent("#/settings")) }))));
}
