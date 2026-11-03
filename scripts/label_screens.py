"""Screenshot public pages and share images with the Preliminary labels. Throwaway branch only."""

import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5000"
out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
PAGES = ["/", "/?mode=dd_dynasty", "/?mode=prospects", "/?mode=categories", "/buys", "/movers", "/backfields", "/farms",
         "/map", "/trade", "/board", "/scouting", "/gaps", "/receipts", "/ledger", "/scoreboard", "/discipline-leaders",
         "/front-office", "/intelligence", "/cards", "/prospects/share-card", "/dynasty/share-card"]
IMAGES = ["/prospects/share-card.png", "/prospects/share-card.svg", "/dynasty/share-card.png", "/farms/share-card.png",
          "/buys/share-card.png", "/movers/share-card.png", "/map/share-card.png", "/receipts/share-card.png",
          "/ledger/share-card.png", "/share/prospects/P.png"]
MEASURE = """() => ({
  scroll: document.documentElement.scrollWidth,
  inner: window.innerWidth,
  notices: document.querySelectorAll('.prospect-publication-notice').length,
  tags: document.querySelectorAll('.preliminary-tag').length,
})"""
HIDE = "() => document.querySelectorAll('.preliminary-tag').forEach(e => e.style.display = 'none')"


def name(path, width):
    return re.sub(r"[^a-z0-9]+", "_", path.lower()).strip("_") + f"_{width}"


results = []
with sync_playwright() as play:
    browser = play.chromium.launch()
    for width, height in ((1280, 1000), (390, 844)):
        page = browser.new_page(viewport={"width": width, "height": height})
        for path in PAGES:
            try:
                response = page.goto(BASE + path, wait_until="domcontentloaded", timeout=120000)
                page.wait_for_timeout(800)
                row = dict(path=path, width=width, status=response.status, **page.evaluate(MEASURE))
                page.screenshot(path=str(out / f"{name(path, width) or 'home'}_{width}.png"))
                page.evaluate(HIDE)
                row["scroll_without_tags"] = page.evaluate("() => document.documentElement.scrollWidth")
            except Exception as error:  # noqa: BLE001
                row = dict(path=path, width=width, error=type(error).__name__)
            results.append(row)
            print(row, flush=True)
    page = browser.new_page(viewport={"width": 1280, "height": 1000})
    html = page.goto(BASE + "/?mode=prospects", timeout=120000).text()
    found = re.search(r"/prospects/player-card/([^\"'?.\s]+)", html) or re.search(r'data-(?:player-)?id="([^"]+)"', html)
    images = list(IMAGES)
    if found:
        images += [f"/prospects/player-card/{quote(found.group(1))}", f"/prospects/player-card/{quote(found.group(1))}.png",
                   f"/dynasty/player-card/{quote(found.group(1))}.png"]
    for path in images:
        response = page.request.get(BASE + path, timeout=120000)
        row = dict(path=path, status=response.status, type=response.headers.get("content-type"))
        suffix = {"image/png": ".png", "image/svg+xml": ".svg"}.get((row["type"] or "").split(";")[0])
        if suffix and response.ok:
            (out / ("image_" + name(path, "x") + suffix)).write_bytes(response.body())
        results.append(row)
        print(row, flush=True)
(out / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
