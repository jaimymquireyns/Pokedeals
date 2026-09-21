// Instellingen (kosten, meldingen, kijkhorizon). Lokaal bewaard en, als je bent ingelogd, ook in Supabase.
import { isLoggedIn, rest, userId } from "./api.js";
import { DEFAULT_SETTINGS } from "./model.js";
import { store } from "./ui.js";

let cache = { ...DEFAULT_SETTINGS, ...store.get("pd:settings", {}) };
export const getSettings = () => cache;

export async function loadSettings() {
  if (!isLoggedIn()) return cache;
  try {
    const rows = await rest.get("user_settings?select=*&limit=1");
    if (rows[0]) {
      const { user_id, ...s } = rows[0];
      cache = { ...DEFAULT_SETTINGS, ...s };
      store.set("pd:settings", cache);
    }
  } catch { /* offline: lokale versie blijft */ }
  return cache;
}

export async function saveSettings(patch) {
  cache = { ...cache, ...patch };
  store.set("pd:settings", cache);
  if (isLoggedIn()) {
    await rest.upsert("user_settings", [{ user_id: userId(), ...cache }], "user_id");
  }
  return cache;
}
