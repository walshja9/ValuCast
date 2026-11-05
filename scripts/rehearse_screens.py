"""Screenshot the redraft and dynasty rows and cards for named players. Throwaway branch only.

Usage: rehearse_screens.py OUT LABEL NAME [NAME...]
A name starting with "dynasty:" has no redraft row, so only its dynasty row and card are taken.
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
DISCOUNT = "This dynasty value includes an injury discount"
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
IN_VIEW = """el => {
  const box = el.getBoundingClientRect();
  return box.width > 0 && box.left >= 0 && box.top >= 0 && box.right <= innerWidth && box.bottom <= innerHeight;
}"""
# Moves the page only, so a table that scrolls sideways stays where a visitor first sees it.
PAGE_TO = "el => window.scrollBy(0, el.getBoundingClientRect().top - innerHeight / 2)"
CENTER = "el => el.scrollIntoView({block: 'center'})"

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


def shoot_note(page, card, path):
    """A viewport shot of the note as a visitor sees it. None when the card has no note."""
    note = card.locator(".sample-context-note", has_text=NOTE)
    if not note.count():
        return None
    note.first.evaluate(CENTER)
    page.wait_for_timeout(500)  # The site may scroll smoothly.
    seen = note.first.evaluate(IN_VIEW)
    page.screenshot(path=str(path))
    return seen


with sync_playwright() as play:
    browser = play.chromium.launch()
    for width, height in ((1280, 1000), (390, 844)):
        page = browser.new_page(viewport={"width": width, "height": height})
        for entry in names:
            dynasty_only = entry.startswith("dynasty:")
            name = entry.removeprefix("dynasty:")
            slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
            row_result = dict(label=label, name=name, width=width, dynasty_only=dynasty_only)
            if not dynasty_only:
                try:
                    row = open_row(page, "categories", name)
                    badge = row.locator(".no-ros-badge", has_text="Injury hold")
                    row_result.update(
                        found=True,
                        rank=row.locator(".col-rank").inner_text().strip(),
                        value=row.locator(".col-value").inner_text().strip(),
                        badge=badge.count() > 0,
                        row_overflow=page.evaluate(OVERFLOW),
                    )
                    page.evaluate(MASK)
                    row.evaluate(PAGE_TO)
                    page.wait_for_timeout(500)
                    row_result["rank_in_view"] = row.locator(".col-rank").evaluate(IN_VIEW)
                    if badge.count():
                        row_result["badge_in_view"] = badge.first.evaluate(IN_VIEW)
                    page.screenshot(path=str(out / f"{label}_{slug}_redraft_row_{width}.png"))
                    card = open_card(page, row)
                    text = card.inner_text()
                    row_result.update(note=NOTE in text, no_discount_line=NO_DISCOUNT in text,
                                      card_overflow=page.evaluate(OVERFLOW))
                    page.evaluate(MASK)
                    card.screenshot(path=str(out / f"{label}_{slug}_redraft_card_{width}.png"))
                    row_result["redraft_note_in_view"] = shoot_note(
                        page, card, out / f"{label}_{slug}_redraft_note_{width}.png")
                except Exception as error:  # noqa: BLE001
                    row_result.update(found=row_result.get("found", False), error=f"{type(error).__name__}: {error}"[:300])
            try:
                row = open_row(page, "dd_dynasty", name)
                dynasty_badge = row.locator(".no-ros-badge", has_text="Injury hold")
                page.evaluate(MASK)
                row.evaluate(PAGE_TO)
                page.wait_for_timeout(500)
                row_result["dynasty_badge"] = dynasty_badge.count() > 0
                if dynasty_badge.count():
                    row_result["dynasty_badge_in_view"] = dynasty_badge.first.evaluate(IN_VIEW)
                page.screenshot(path=str(out / f"{label}_{slug}_dynasty_row_{width}.png"))
                card = open_card(page, row)
                text = card.inner_text()
                row_result.update(dynasty_note=NOTE in text, dynasty_discount=DISCOUNT in text,
                                  risk_adjustment_shown="Risk Adjustment" in text,
                                  dynasty_overflow=page.evaluate(OVERFLOW))
                page.evaluate(MASK)
                card.screenshot(path=str(out / f"{label}_{slug}_dynasty_card_{width}.png"))
                row_result["dynasty_note_in_view"] = shoot_note(
                    page, card, out / f"{label}_{slug}_dynasty_note_{width}.png")
            except Exception as error:  # noqa: BLE001
                row_result.update(dynasty_error=f"{type(error).__name__}: {error}"[:300])
            results.append(row_result)
            print(row_result, flush=True)
        page.close()
(out / f"{label}_results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
