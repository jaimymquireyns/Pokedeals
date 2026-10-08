// Meldingen op je toestel (web push).
import { rest, userId } from "./api.js";

const vapid = () => (window.POKEDEALS || {}).VAPID_PUBLIC_KEY;
export const pushSupported = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
export const pushPermission = () => (pushSupported() ? Notification.permission : "unsupported");

const b64ToBytes = (s) => {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  const raw = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
};

// 'ready' blijft eeuwig hangen als de service worker niet kan starten; dan liever een duidelijke foutmelding.
const swReady = () => Promise.race([navigator.serviceWorker.ready,
  new Promise((_, rej) => setTimeout(() => rej(new Error("The app isn't ready for notifications yet. Close it, reopen it and try again.")), 6000))]);

export async function hasSubscription() {
  if (!pushSupported()) return false;
  const reg = await swReady().catch(() => null);
  if (!reg) return false;
  return Boolean(await reg.pushManager.getSubscription());
}

export async function enablePush() {
  if (!pushSupported()) throw new Error("Notifications aren't supported on this device. On iPhone: add the app to your home screen first.");
  if (!vapid()) throw new Error("VAPID_PUBLIC_KEY is missing in config.js.");
  const perm = await Notification.requestPermission();
  if (perm !== "granted") throw new Error("You didn't allow notifications. Change that in your device settings.");
  const reg = await swReady();
  const sub = (await reg.pushManager.getSubscription()) ||
    (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(vapid()) }));
  const j = sub.toJSON();
  await rest.upsert("push_subscriptions", [{ user_id: userId(), endpoint: j.endpoint, p256dh: j.keys.p256dh, auth: j.keys.auth }], "endpoint");
}

export async function disablePush() {
  const reg = await swReady();
  const sub = await reg.pushManager.getSubscription();
  if (!sub) return;
  await rest.del("push_subscriptions", `endpoint=eq.${encodeURIComponent(sub.endpoint)}`);
  await sub.unsubscribe();
}
