"""Screenshot the redraft row, redraft card and dynasty card for named players. Throwaway branch only.

Usage: rehearse_screens.py OUT LABEL NAME [NAME...]
Every digit outside rank, value and the note is masked first, so no projected stat line reaches a public artifact.
"""
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5000"
WAIT = 300000
NOTE = "End-of-season injury status held"
NO_DISCOUNT = "no injury discount to this redraft value"
MASK = r"""() => {
  const keep = '.col-rank, .col-value, .col-dollars, .col-dollar, .detail-value, .no-ros-badge';
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const node of nodes) {
    const parent = node.parentElement;
    if (!parent || parent.closest(keep) || parent.closest('script, style')) continue;
    if (node.nodeValue.includes('End-of-season injury status held')) continue;
    if (/\d/.test(node.nodeValue)) node.nodeValue = node.nodeValue.replace(/\d/g, '•');
  }
}"""
OVERFLOW = "() => document.documentElement.scrollWidth > window.innerWidth"

out, label, names = Path(sys.argv[1]), sys.argv[2], sys.argv[3:]
out.mkdir(parents=True, exist_ok=True)
results = []


def open_row(page, mode, name):
    page.goto(f"{BASE}/?{urlencode({'mode': mode, 'search': name})}", wait_until="domcontentloaded", timeout=WAIT)
    page.wait_for_selector("tr.player-row", timeout=WAIT)
    row = page.locator("tr.player-row", has_text=name).first
    row.wait_for(timeout=30000)
    return row


def open_card(page, row):
    toggle = row.locator(".detail-toggle").first
    if toggle.is_visible():
        toggle.click()
    else:
        row.click(position={"x": 4, "y": 4})
    page.wait_for_selector(".player-detail", timeout=WAIT)
    return page.locator(".player-detail").first


with sync_playwright() as play:
    browser = play.chromium.launch()
    for width, height in ((1280, 1000), (390, 844)):
        page = browser.new_page(viewport={"width": width, "height": height})
        for name in names:
            slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
            row_result = dict(label=label, name=name, width=width)
            try:
                row = open_row(page, "categories", name)
                row_result.update(
                    found=True,
                    rank=row.locator(".col-rank").inner_text().strip(),
                    value=row.locator(".col-value").inner_text().strip(),
                    badge=row.locator(".no-ros-badge", has_text="Injury hold").count() > 0,
                    row_overflow=page.evaluate(OVERFLOW),
                )
                page.evaluate(MASK)
                page.screenshot(path=str(out / f"{label}_{slug}_redraft_row_{width}.png"))
                card = open_card(page, row)
                text = card.inner_text()
                row_result.update(note=NOTE in text, no_discount_line=NO_DISCOUNT in text,
                                  card_overflow=page.evaluate(OVERFLOW))
                page.evaluate(MASK)
                card.screenshot(path=str(out / f"{label}_{slug}_redraft_card_{width}.png"))
            except Exception as error:  # noqa: BLE001
                row_result.update(found=row_result.get("found", False), error=f"{type(error).__name__}: {error}"[:300])
            try:
                row = open_row(page, "dd_dynasty", name)
                card = open_card(page, row)
                row_result.update(dynasty_note=NOTE in card.inner_text(), dynasty_overflow=page.evaluate(OVERFLOW))
                page.evaluate(MASK)
                card.screenshot(path=str(out / f"{label}_{slug}_dynasty_card_{width}.png"))
            except Exception as error:  # noqa: BLE001
                row_result.update(dynasty_error=f"{type(error).__name__}: {error}"[:300])
            results.append(row_result)
            print(row_result, flush=True)
        page.close()
(out / f"{label}_results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
