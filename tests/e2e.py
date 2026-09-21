"""Browsertest van de hele app tegen een nep-Supabase. Draaien: python tests/e2e.py (vanuit de projectmap)."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(__file__))
from mock_supabase import Mock  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SHOTS = Path(os.environ.get("SHOTS", "/tmp/shots")); SHOTS.mkdir(exist_ok=True)
PORT = 8123
CONFIG = 'window.POKEDEALS={SUPABASE_URL:"http://mock.supabase.test",SUPABASE_KEY:"eyJtest",VAPID_PUBLIC_KEY:"BFWnzYpMSYNu1DKn9DONA5wou1TwuMMVLEQFfymBKkP9526Y_v15YOKl6XIYuS0o4tA2akxOUJmrlCjFo3ePynM"};'
INIT = """
Object.defineProperty(Notification, 'permission', {get: () => window.__perm || 'default', configurable: true});
Notification.requestPermission = async () => { window.__perm = 'granted'; return 'granted'; };
PushManager.prototype.getSubscription = async function () { return window.__sub || null; };
PushManager.prototype.subscribe = async function () {
  window.__sub = { endpoint: 'https://push.test/abc', toJSON: () => ({ endpoint: 'https://push.test/abc', keys: { p256dh: 'pk', auth: 'ak' } }), unsubscribe: async () => { window.__sub = null; return true; } };
  return window.__sub; };
Object.defineProperty(navigator.serviceWorker, 'ready', { get: () => Promise.resolve({ pushManager: PushManager.prototype }), configurable: true });
window.Tesseract = { recognize: async () => ({ data: { text: 'Basic\\nCharizard ex 330 HP\\nsome text\\n125/197 OBF R' } }) };
"""
fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def main():
    srv = subprocess.Popen([sys.executable, "-m", "http.server", str(PORT), "--directory", str(ROOT / "docs")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    mock = Mock()
    errors = []
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
            ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, permissions=["camera"], locale="nl-NL", service_workers="block")
            ctx.add_init_script(INIT)
            ctx.route("**/config.js", lambda r: r.fulfill(status=200, content_type="text/javascript", body=CONFIG))
            ctx.route("http://mock.supabase.test/**", mock.handle)
            page = ctx.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "favicon" not in m.text else None)
            base = f"http://localhost:{PORT}/"

            print("Home")
            page.goto(base)
            page.wait_for_selector(".row")
            names = page.locator(".row .name").all_inner_texts()
            check(names[:3] == ["Charizard ex", "Pikachu ex", "Surging Sparks Booster Box"], f"sorteert op kans: {names}")
            check("Umbreon VMAX" not in names, "verkoop-kaart (negatieve verwachting) valt af door netto-filter")
            check("Trackrecord: 27 van 46" in page.inner_text(".sub"), "trackrecord-regel: " + page.inner_text(".sub"))
            page.screenshot(path=str(SHOTS / "home.png"))
            page.get_by_role("button", name="Sealed", exact=True).click()
            check(page.locator(".row").count() == 1 and "Booster Box" in page.inner_text(".row"), "filter Sealed")
            page.get_by_role("button", name="Alles", exact=True).click()

            print("Instellingen wijzigen kosten")
            page.get_by_role("button", name="Instellingen", exact=True).click()
            page.wait_for_selector("text=Verkoopkosten")
            page.screenshot(path=str(SHOTS / "settings.png"), full_page=True)
            page.locator("input[aria-label^='Kosten per verkoop']").fill("40"); page.locator("input[aria-label^='Kosten per verkoop']").blur()
            page.get_by_role("button", name="Terug", exact=True).click()
            page.wait_for_selector(".list .empty")
            check("Geen kansen" in page.inner_text(".list"), "met 40% kosten blijven er geen netto-kansen over")
            page.get_by_role("button", name="Instellingen", exact=True).click()
            page.locator("input[aria-label^='Kosten per verkoop']").fill("5"); page.locator("input[aria-label^='Kosten per verkoop']").blur()
            page.get_by_role("button", name="Terug", exact=True).click()
            page.wait_for_selector(".row")

            print("Detail (niet in bezit)")
            page.locator(".row").first.click()
            page.wait_for_selector(".chance")
            check("72%" in page.inner_text(".chance") and "6%" in page.inner_text(".chance"), "kansbalk toont 72% en 6%")
            check(page.locator(".why li").count() >= 3, "waarom-punten aanwezig")
            check(page.locator("svg.chart").count() == 1, "grafiek aanwezig")
            page.screenshot(path=str(SHOTS / "detail.png"), full_page=True)

            print("Zoeken zonder login: + leidt naar login")
            page.get_by_role("link", name="Zoeken").click() if page.locator("#tabs").is_visible() else page.goto(base + "#/search")
            page.goto(base + "#/search")
            page.get_by_placeholder("Zoek kaart, sealed of set").fill("charizard")
            page.wait_for_selector(".resrow")
            check(page.locator(".resrow").count() == 2, "2 Charizard-resultaten")
            page.screenshot(path=str(SHOTS / "search.png"))
            page.locator(".addb").first.click()
            page.wait_for_selector(".login")
            check("Inloggen" in page.inner_text(".login h1"), "login-scherm")
            page.locator("input[type=email]").fill("ik@example.nl")
            page.get_by_role("button", name="Stuur code").click()
            page.wait_for_selector("input[autocomplete=one-time-code]")
            page.locator("input[autocomplete=one-time-code]").fill("000000")
            page.get_by_role("button", name="Inloggen", exact=True).click()
            page.wait_for_selector(".err:not(:empty)")
            check("klopt niet" in page.inner_text(".err"), "foute code geeft melding")
            page.locator("input[autocomplete=one-time-code]").fill("123456")
            page.get_by_role("button", name="Inloggen", exact=True).click()
            page.wait_for_selector("#tabs .tab.on")
            check(mock.logged_in, "ingelogd")

            print("Toevoegen aan collectie")
            page.goto(base + "#/search")
            page.get_by_placeholder("Zoek kaart, sealed of set").fill("charizard ex")
            page.wait_for_selector(".resrow")
            page.locator(".addb").first.click()
            page.wait_for_selector(".addform")
            page.screenshot(path=str(SHOTS / "add.png"))
            page.locator(".addform input[type=text]").fill("30,00")
            page.locator(".cta").click()
            page.wait_for_selector(".addb.done")
            check(len(mock.db["collection"]) == 1 and mock.db["collection"][0]["purchase_price"] == 30, "rij opgeslagen met prijs 30")
            # gegradeerd item
            page.locator(".addb").first.click()
            page.wait_for_selector(".addform")
            page.get_by_role("button", name="Gegradeerd", exact=True).click()
            page.wait_for_selector("select")
            page.locator(".addform input[type=text]").fill("120")
            page.locator(".cta").click()
            page.wait_for_selector(".addb.done")
            check(mock.db["collection"][1]["grade_company"] == "PSA" and mock.db["collection"][1]["grade"] == "10", "PSA 10 opgeslagen")

            print("Scan-flow")
            page.locator(".camb").click()
            page.wait_for_selector(".scan video")
            page.wait_for_timeout(600)
            page.locator(".shutter").click()
            page.wait_for_selector(".scanpanel .addform")
            check("Charizard ex" in page.inner_text(".scanpanel .found"), "herkend als Charizard ex: " + page.inner_text(".scanpanel .found").replace("\n", " "))
            check("Obsidian Flames" in page.inner_text(".scanpanel .found"), "juiste set via nummer 125/197")
            page.screenshot(path=str(SHOTS / "scan.png"))
            page.locator(".scanpanel .addform input[type=text]").fill("25")
            page.locator(".scanpanel .cta").click()
            page.wait_for_selector("dialog#scan:not([open])", state="attached")
            check(len(mock.db["collection"]) == 3, "gescande kaart toegevoegd")

            print("Collectie")
            for c in mock.db["collection"]:
                c["purchase_date"] = "2026-08-01"      # zodat er al een grafiek te tekenen valt
            page.goto(base + "#/collection")
            page.wait_for_selector(".rowc")
            check(page.locator(".rowc").count() == 3, "3 regels")
            check("PSA 10" in page.inner_text(".list"), "PSA 10-label zichtbaar")
            check("Waarde nu" in page.inner_text(".sum"), "samenvatting")
            page.wait_for_selector(".chartbox svg")
            page.screenshot(path=str(SHOTS / "collection.png"), full_page=True)
            page.get_by_role("button", name="Sorteren").or_(page.locator(".sortb")).first.click()
            page.get_by_role("button", name="Laagste waarde").click()
            vals = page.locator(".rowc .v").all_inner_texts()
            nums = [float(v.replace("€", "").replace("\u00a0", "").replace(".", "").replace(",", ".")) for v in vals]
            check(nums == sorted(nums), f"sorteren op laagste waarde: {vals}")
            page.get_by_role("button", name="Sealed", exact=True).click()
            check("Niets in deze selectie" in page.inner_text(".list"), "filter Sealed leeg")
            page.get_by_role("button", name="Alles", exact=True).click()
            page.get_by_role("button", name="3M").click(); page.wait_for_selector(".chartbox svg")

            print("Detail in bezit + prijsmelding")
            page.locator(".rowc").first.click()
            page.wait_for_selector(".stats")
            check("Aankoop" in page.inner_text(".stats"), "aankoopblok bij bezit")
            page.screenshot(path=str(SHOTS / "detail-owned.png"), full_page=True)
            page.locator(".tg").click()
            page.wait_for_selector(".amt input")
            check(len(mock.db["push_subscriptions"]) == 1, "push-abonnement opgeslagen")
            page.wait_for_timeout(900)
            check(len(mock.db["alerts"]) == 1 and mock.db["alerts"][0]["active"] is True, "prijsmelding opgeslagen")
            page.locator(".amt input").first.fill("20"); page.wait_for_timeout(900)
            check(mock.db["alerts"][0]["min_price"] == 20, "grens bijgewerkt")

            print("Trackrecord")
            page.goto(base + "#/track")
            page.wait_for_selector(".tr-big")
            check("27 van 46" in page.inner_text(".tr-big"), "27 van 46")
            page.screenshot(path=str(SHOTS / "track.png"), full_page=True)

            print("Verwijderen")
            page.goto(base + "#/collection"); page.wait_for_selector(".rowc")
            page.locator(".rowc").first.click(); page.wait_for_selector(".btns")
            page.once("dialog", lambda d: d.accept())
            page.get_by_role("button", name="Verwijderen uit collectie").click()
            page.wait_for_selector(".rowc")
            check(len(mock.db["collection"]) == 2, "item verwijderd")
            b.close()
    finally:
        srv.terminate()
    real = [e for e in errors if "Failed to load resource" not in e]
    check(not real, f"geen console/pagina-fouten: {real[:3]}")
    print("\nMISLUKT:" if fails else "\nalle browsertests geslaagd", fails or "")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
