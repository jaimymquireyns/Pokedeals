"""Testbank voor de kaartherkenning (scan.js), op GitHub Actions (daar is internet): echte kaartfoto's van de database worden
'gsm-foto's' gemaakt (scheef, met achtergrond, wazig, ander licht) en door de echte app gehaald, met de echte tekstherkenning
en de echte database. Meet hoeveel kaarten juist herkend worden.

    python tests/scan_bench.py --n 80 --out reports/scan_bench.md
"""
import argparse
import io
import json
import math
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PORT = 8140
WORK = Path("/tmp/scanbench"); WORK.mkdir(exist_ok=True)


def config():
    txt = (ROOT / "docs" / "config.js").read_text()
    url = re.search(r'SUPABASE_URL:\s*"([^"]+)"', txt).group(1)
    key = re.search(r'SUPABASE_KEY:\s*"([^"]+)"', txt).group(1)
    return url, key


def pick_cards(n, seed):
    url, key = config()
    h = {"apikey": key, "Authorization": f"Bearer {key}"} if key.startswith("eyJ") else {"apikey": key}
    def get(q):
        r = requests.get(f"{url}/rest/v1/{q}", headers=h, timeout=60); r.raise_for_status(); return r.json()
    rows = get("v_search?select=product_id,name,set_name,number,set_total,image,release_date,kind&kind=eq.card&image=not.is.null&price=gte.3&limit=5000")
    rows = [r for r in rows if r.get("image") and r.get("number")]
    rnd = random.Random(seed)
    recent = [r for r in rows if (r.get("release_date") or "") >= "2023-01-01"]
    older = [r for r in rows if (r.get("release_date") or "") < "2023-01-01"]
    pick = rnd.sample(recent, min(len(recent), n * 2 // 3)) + rnd.sample(older, min(len(older), n - n * 2 // 3))
    special = get("v_search?select=product_id,name,set_name,number,set_total,image,release_date,kind&kind=eq.card&name=ilike.*Ethan*&image=not.is.null&limit=5")
    seen = {r["product_id"] for r in pick}
    return pick + [r for r in special if r["product_id"] not in seen]


def hires(u):
    if "assets.tcgdex.net" in u:
        u = re.sub(r"/(low|high)\.(png|webp|jpg)$", "", u)
        return u + "/high.png"
    if "images.pokemontcg.io" in u and not u.endswith("_hires.png"):
        return u.replace(".png", "_hires.png")
    return u


def download(card):
    for u in (hires(card["image"]), card["image"]):
        try:
            r = requests.get(u, timeout=30)
            if r.ok and len(r.content) > 5000:
                return Image.open(io.BytesIO(r.content)).convert("RGBA")
        except Exception:
            pass
    return None


def background(w, h, rnd):
    kind = rnd.choice(["wood", "plain", "cloth", "dark"])
    base = {"wood": (150, 105, 65), "plain": (225, 222, 215), "cloth": (60, 90, 140), "dark": (35, 35, 38)}[kind]
    im = Image.new("RGB", (w, h), base)
    d = ImageDraw.Draw(im)
    for _ in range(400 if kind != "plain" else 60):
        x, y = rnd.randrange(w), rnd.randrange(h)
        c = tuple(max(0, min(255, v + rnd.randint(-25, 25))) for v in base)
        if kind == "wood":
            d.line([(0, y), (w, y + rnd.randint(-20, 20))], fill=c, width=rnd.randint(1, 4))
        else:
            d.ellipse([x, y, x + rnd.randint(2, 30), y + rnd.randint(2, 30)], fill=c)
    return im.filter(ImageFilter.GaussianBlur(1.2))


def photo(card_img, level, rnd):
    """level 'easy': recht, vult het beeld. 'hard': scheef, kleiner, achtergrond, wazig, ander licht, jpeg."""
    W, H = 1200, 1600
    if level == "easy":
        fill, angle, blur, light, q = 0.92, rnd.uniform(-1.5, 1.5), 0.0, 1.0, 88
    else:
        fill, angle, blur, light, q = rnd.uniform(0.55, 0.78), rnd.uniform(-9, 9), rnd.uniform(0.6, 1.6), rnd.uniform(0.7, 1.25), 62
    bg = background(W, H, rnd)
    ch = int(H * fill); cw = int(ch * 63 / 88)
    card = card_img.resize((cw, ch), Image.LANCZOS).rotate(angle, expand=True, resample=Image.BICUBIC)
    x = (W - card.width) // 2 + rnd.randint(-int(W * (1 - fill) / 4), int(W * (1 - fill) / 4) + 1)
    y = (H - card.height) // 2 + rnd.randint(-int(H * (1 - fill) / 4), int(H * (1 - fill) / 4) + 1)
    bg.paste(card, (x, y), card)
    im = bg
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    im = ImageEnhance.Brightness(im).enhance(light)
    buf = io.BytesIO(); im.convert("RGB").save(buf, "JPEG", quality=q)
    return buf.getvalue()


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=80)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="reports/scan_bench.md")
    args = ap.parse_args()
    cards = pick_cards(args.n, args.seed)
    print(f"{len(cards)} kaarten gekozen")
    rnd = random.Random(args.seed)
    cases = []
    for c in cards:
        img = download(c)
        if img is None:
            continue
        for level in ("easy", "hard"):
            p = WORK / f"{norm(c['product_id'])}-{level}.jpg"
            p.write_bytes(photo(img, level, rnd))
            cases.append((c, level, p))
    print(f"{len(cases)} foto's gemaakt")
    srv = subprocess.Popen([sys.executable, "-m", "http.server", str(PORT), "--directory", str(ROOT / "docs")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    results = []
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            ctx = b.new_context(viewport={"width": 390, "height": 844}, service_workers="block")
            ctx.add_init_script("navigator.mediaDevices && (navigator.mediaDevices.getUserMedia = () => Promise.reject(new Error('geen camera in de test')));")
            page = ctx.new_page()
            page.goto(f"http://localhost:{PORT}/#/search")
            page.wait_for_timeout(1500)
            for i, (c, level, p) in enumerate(cases):
                t0 = time.time()
                page.evaluate("async () => { const m = await import('./js/scan.js'); m.openScan({}); }")
                page.wait_for_selector(".scan input[type=file]:not([capture])", state="attached")
                page.locator(".scan input[type=file]:not([capture])").set_input_files(str(p))
                try:
                    page.wait_for_selector(".scanpanel .found, .scanpanel h3", timeout=90000)
                except Exception:
                    pass
                status = page.inner_text(".vf-hint") if page.locator(".vf-hint").count() else ""
                found = page.inner_text(".scanpanel .found") if page.locator(".scanpanel .found").count() else ""
                want_name, want_num = c["name"], str(c["number"])
                ok_name = norm(want_name) and norm(want_name) in norm(found)
                ok_num = re.search(rf"#0*{re.escape(want_num.lstrip('0') or '0')}\b", found.replace("\n", " ")) is not None
                results.append({"card": f"{want_name} ({c['set_name']} #{want_num})", "level": level, "ok": bool(ok_name and ok_num), "name_ok": bool(ok_name),
                                "read": status.replace("Read: ", ""), "found": " ".join(found.split())[:80], "secs": round(time.time() - t0, 1)})
                print(f"[{i + 1}/{len(cases)}] {'OK ' if results[-1]['ok'] else 'FOUT'} {level:4} {results[-1]['card']} | gelezen: {results[-1]['read']} | gevonden: {results[-1]['found']}")
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
                page.evaluate("() => { const d = document.getElementById('scan'); if (d && d.open) d.close(); }")
            b.close()
    finally:
        srv.terminate()
    lines = ["# Testbank kaartherkenning", ""]
    for level in ("easy", "hard"):
        rs = [r for r in results if r["level"] == level]
        if rs:
            lines.append(f"- {level}: {sum(r['ok'] for r in rs)}/{len(rs)} juist ({sum(r['ok'] for r in rs) / len(rs):.0%}), naam juist {sum(r['name_ok'] for r in rs)}/{len(rs)}, gemiddeld {sum(r['secs'] for r in rs) / len(rs):.1f} s")
    lines += ["", "## Fouten", "", "| foto | kaart | gelezen | gevonden |", "|---|---|---|---|"]
    for r in results:
        if not r["ok"]:
            lines.append(f"| {r['level']} | {r['card']} | {r['read']} | {r['found']} |")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(lines) + "\n")
    Path(args.out).with_suffix(".json").write_text(json.dumps(results, indent=1))
    print("\n".join(lines[:4]))


if __name__ == "__main__":
    main()
