import { configured, isLoggedIn } from "./api.js";
import { go, note } from "./components.js";
import { loadSettings } from "./prefs.js";
import { $, h, icon } from "./ui.js";
import { collectionView } from "./views/collection.js";
import { detailView } from "./views/detail.js";
import { homeView } from "./views/home.js";
import { loginView } from "./views/login.js";
import { searchView } from "./views/search.js";
import { settingsView } from "./views/settings.js";
import { trackView } from "./views/track.js";

const app = $("#app");
const tabsEl = $("#tabs");
const TABS = [["home", "Kansen", "home"], ["search", "Zoeken", "search"], ["collection", "Collectie", "cards"]];

function drawTabs(active) {
  tabsEl.hidden = !active;
  tabsEl.replaceChildren(...TABS.map(([id, label, ic]) => h("a", { class: "tab" + (id === active ? " on" : ""), href: `#/${id}`, "aria-current": id === active ? "page" : null },
    h("span", { class: "pi" }, icon(ic)), h("span", { text: label }))));
}

function parse() {
  const [path, qs] = (location.hash || "#/home").slice(1).split("?");
  return { parts: path.split("/").filter(Boolean).map(decodeURIComponent), q: new URLSearchParams(qs || "") };
}

async function route() {
  const { parts, q } = parse();
  const view = parts[0] || "home";
  window.scrollTo(0, 0);
  if (!configured) {
    drawTabs(null);
    app.replaceChildren(h("div", { class: "page" }, h("div", { class: "head" }, h("h1", { text: "Bijna klaar" })),
      note("Verbinding ontbreekt", "Vul SUPABASE_URL en SUPABASE_KEY in bij docs/config.js. Zie de README, stap 3.")));
    return;
  }
  try {
    switch (view) {
      case "home": drawTabs("home"); await homeView(app); break;
      case "search": drawTabs("search"); await searchView(app); break;
      case "collection":
        drawTabs("collection");
        if (!isLoggedIn()) loginView(app, { reason: "Log in om je collectie te zien en bij te houden.", onDone: route });
        else await collectionView(app);
        break;
      case "detail": drawTabs(null); await detailView(app, parts[1], q.get("c")); break;
      case "settings": drawTabs(null); await settingsView(app); break;
      case "track": drawTabs(null); await trackView(app); break;
      case "login": drawTabs(null); loginView(app, { onDone: () => { const next = q.get("next"); go(next || "#/home"); } }); break;
      default: go("#/home");
    }
  } catch (e) {
    console.error(e);
    app.replaceChildren(h("div", { class: "page" }, note("Er ging iets mis", "Probeer de app opnieuw te openen.")));
  }
}

window.addEventListener("hashchange", route);
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
  navigator.serviceWorker.addEventListener("message", (e) => { if (e.data?.type === "nav" && e.data.url) location.hash = e.data.url.replace(/^.*#/, "#"); });
}
loadSettings().finally(route);
