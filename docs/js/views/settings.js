import { getSession, isLoggedIn, signOut, userEmail } from "../api.js";
import { brandmark, go } from "../components.js";
import { SHOW_PREDICTIONS } from "../model.js";
import { getSettings, loadSettings, saveSettings } from "../prefs.js";
import { disablePush, enablePush, hasSubscription, pushPermission, pushSupported } from "../push.js";
import { debounce, h, icon, parseMoney, segment, toast, toggle } from "../ui.js";

export async function settingsView(root) {
  await loadSettings();
  let s = getSettings();
  const flash = debounce(() => toast("Saved"), 400);
  const set = async (patch) => {
    s = { ...s, ...patch };
    try { await saveSettings(patch); flash(); } catch { toast("Couldn't save"); }
  };
  const money = (key, label, suffix) => h("label", { class: "trow" }, h("span", { class: "t", text: label }),
    h("span", { class: "sfx" }, h("input", { type: "text", inputmode: "decimal", "aria-label": label, value: String(s[key]),
      onchange: (e) => { const v = parseMoney(e.target.value); if (v != null && v >= 0) set({ [key]: v }); else e.target.value = String(s[key]); } }), suffix));
  const row = (title, sub, ctl) => h("div", { class: "trow" }, h("div", {}, h("div", { class: "t", text: title }), sub ? h("div", { class: "s", text: sub }) : null), ctl);

  const devBtn = h("button", { class: "btn small", type: "button" });
  const drawDevice = async () => {
    if (!isLoggedIn()) { devBtn.replaceChildren("Log in for notifications"); devBtn.onclick = () => go("#/login?next=" + encodeURIComponent("#/settings")); return; }
    if (!pushSupported()) { devBtn.replaceChildren("Not supported on this device"); devBtn.disabled = true; return; }
    const on = pushPermission() === "granted" && (await hasSubscription());
    devBtn.replaceChildren(on ? "Turn off notifications on this device" : "Turn on notifications on this device");
    devBtn.onclick = async () => {
      try { on ? await disablePush() : await enablePush(); toast(on ? "Turned off" : "Notifications on"); } catch (e) { toast(e.message); }
      drawDevice();
    };
  };
  drawDevice();

  root.replaceChildren(h("div", { class: "page" },
    brandmark(),
    h("div", { class: "head" }, h("h1", { text: "Settings" })),
    h("div", { class: "grp" }, h("h3", { text: "Collection" }),
      h("div", { class: "lbl2", text: "Needs attention from a price move of" }),
      segment([[10, "10%"], [15, "15%"], [20, "20%"], [25, "25%"]], Number(s.attn_pct) || 15, (v) => set({ attn_pct: v })),
      h("p", { class: "p14 muted", text: "Over the last 30 days, up or down." })),
    !SHOW_PREDICTIONS ? null : h("div", { class: "grp" }, h("h3", { text: "Chances" }),
      h("div", { class: "lbl2", text: "Look ahead" }), segment([[14, "14 days"], [30, "30 days"], [60, "60 days"]], s.horizon, (v) => set({ horizon: v })),
      h("div", { class: "lbl2 gap", text: "Move threshold" }), segment([[10, "10%"], [20, "20%"]], s.pct, (v) => set({ pct: v })),
      row("Only chances with net profit", "After selling costs and shipping", toggle(s.net_only, (v) => set({ net_only: v }), "Only net profit")),
      money("net_min_pct", "Minimum net profit", "%")),
    h("div", { class: "grp" }, h("h3", { text: "Selling costs" }),
      money("fee_pct", "Cost per sale (Cardmarket fee + Trustee Service)", "%"),
      h("p", { class: "p14 muted", text: "The buyer pays shipping when you sell. What counts: the shipping you paid when buying (enter it with your purchase) and €0.50 packaging per sale. For cards you don't own yet, we estimate purchase shipping at €1.50 to €15, depending on price." })),
    h("div", { class: "grp" }, h("h3", { text: "Notifications" }),
      row("Daily summary", "Every morning around 08:00, with new deals and what needs attention", toggle(s.digest, (v) => set({ digest: v }), "Daily summary")),
      row("Price alerts", "When a price hits your range", toggle(s.price_alerts, (v) => set({ price_alerts: v }), "Price alerts")),
      devBtn),
    !SHOW_PREDICTIONS ? null : h("div", { class: "grp" }, h("button", { class: "trow linkrow", type: "button", onclick: () => go("#/track") }, h("span", { class: "t", text: "View track record" }), icon("right"))),
    h("div", { class: "grp" }, h("h3", { text: "Account" }),
      h("p", { class: "p14 muted", text: isLoggedIn() ? `Logged in as ${userEmail() || getSession()?.user?.email || "?"}` : "Not logged in" }),
      isLoggedIn() ? h("button", { class: "btn", type: "button", text: "Log out", onclick: async () => { await signOut(); go("#/home"); } })
        : h("button", { class: "btn", type: "button", text: "Log in", onclick: () => go("#/login?next=" + encodeURIComponent("#/settings")) }))));
}
