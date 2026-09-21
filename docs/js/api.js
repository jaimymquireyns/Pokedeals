// Verbinding met Supabase: inloggen met e-mailcode en REST-verzoeken. Geen externe bibliotheken.
const cfg = window.POKEDEALS || {};
export const configured = Boolean(cfg.SUPABASE_URL && cfg.SUPABASE_KEY);
const base = (cfg.SUPABASE_URL || "").replace(/\/$/, "");

const load = (k) => { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } };
const save = (k, v) => { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, JSON.stringify(v)); } catch { /* geblokkeerd */ } };

let session = load("pd:session");
export const getSession = () => session;
export const isLoggedIn = () => Boolean(session?.access_token);
export const userId = () => session?.user?.id;
export const userEmail = () => session?.user?.email;

function authHeaders() {
  const h = { apikey: cfg.SUPABASE_KEY };
  if (session?.access_token) h.Authorization = "Bearer " + session.access_token;
  else if ((cfg.SUPABASE_KEY || "").startsWith("eyJ")) h.Authorization = "Bearer " + cfg.SUPABASE_KEY;
  return h;
}

function setSession(s) {
  if (s && !s.expires_at && s.expires_in) s.expires_at = Math.floor(Date.now() / 1000) + s.expires_in;
  session = s;
  save("pd:session", s);
}

async function refresh() {
  if (!session?.refresh_token) return false;
  const r = await fetch(`${base}/auth/v1/token?grant_type=refresh_token`, {
    method: "POST", headers: { apikey: cfg.SUPABASE_KEY, "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: session.refresh_token }),
  });
  if (!r.ok) { setSession(null); return false; }
  setSession(await r.json());
  return true;
}

export async function request(method, path, { body, headers, retry = true } = {}) {
  if (session?.expires_at && session.expires_at - Date.now() / 1000 < 60) await refresh();
  const r = await fetch(base + path, {
    method, headers: { ...authHeaders(), "Content-Type": "application/json", ...headers },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (r.status === 401 && retry && session && (await refresh())) return request(method, path, { body, headers, retry: false });
  const text = await r.text();
  if (!r.ok) {
    const e = new Error(`${method} ${path.split("?")[0]}: ${r.status} ${text.slice(0, 160)}`);
    e.status = r.status;
    throw e;
  }
  return text ? JSON.parse(text) : null;
}

export const rest = {
  get: (path) => request("GET", "/rest/v1/" + path),
  insert: (table, rows) => request("POST", `/rest/v1/${table}`, { body: rows, headers: { Prefer: "return=representation" } }),
  upsert: (table, rows, conflict) => request("POST", `/rest/v1/${table}?on_conflict=${conflict}`,
    { body: rows, headers: { Prefer: "resolution=merge-duplicates,return=representation" } }),
  patch: (table, filter, data) => request("PATCH", `/rest/v1/${table}?${filter}`, { body: data, headers: { Prefer: "return=representation" } }),
  del: (table, filter) => request("DELETE", `/rest/v1/${table}?${filter}`),
  rpc: (fn, args) => request("POST", `/rest/v1/rpc/${fn}`, { body: args }),
};

// ---- account: e-mailadres en wachtwoord ----
/** Maakt een account. Geeft true als je meteen bent ingelogd (dat gebeurt als e-mailbevestiging bij Supabase uit staat). */
export async function signUp(email, password) {
  const s = await request("POST", "/auth/v1/signup", { body: { email, password }, retry: false });
  if (s?.access_token) { setSession(s); return true; }
  return false;
}

export async function signIn(email, password) {
  setSession(await request("POST", "/auth/v1/token?grant_type=password", { body: { email, password }, retry: false }));
}

export async function signOut() {
  try { await request("POST", "/auth/v1/logout", { retry: false }); } catch { /* al uitgelogd */ }
  setSession(null);
}
