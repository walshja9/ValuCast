# Trade Player-Only Honesty Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Label every current Trade Analyzer result as a player-only verdict on the page, preview metadata, and PNG.

**Architecture:** Add one application-owned disclosure constant beside the existing trade constants. Pass it through the existing page context and reuse it directly in the current Pillow share-card renderer and preview description; no new component or dependency is needed.

**Tech Stack:** Python 3, Flask/Jinja, Pillow, unittest/pytest, Playwright CLI.

## Global Constraints

- Use this exact public sentence: `Player-only verdict: draft picks, FAAB, roster spots, and league context are not included.`
- Change presentation and shared copy only.
- Do not add pick inputs, pick values, pick curves, roster imports, league sync, accounts, databases, dependencies, or new model features.
- Do not change rankings, values, the fixed trade noise band, pitcher caps, publication decisions, Role Watch, or League Connect.
- Preserve the model freeze and `PITCHER_STALE_PEDIGREE_DECAY_ENABLED = False`.
- Do not push, deploy, merge, or dispatch workflows.

---

### Task 1: Publish the shared player-only verdict contract

**Files:**
- Modify: `app.py:7441-7446,7589-7614,7630-7700,7755-7785`
- Modify: `templates/trade.html:28-39`
- Modify: `templates/partials/_trade_result.html:44-59`
- Test: `tests/test_app.py:1895-2005`

**Interfaces:**
- Consumes: the existing `_build_trade_page_context(args)`, `_trade_share_card_png(give_ids, get_ids, generated_at=None)`, and `trade_share_card()` paths.
- Produces: `_TRADE_SCOPE_NOTE: str` and `trade_scope_note` in the trade template context.

- [ ] **Step 1: Write the failing public-contract tests**

Add these methods to `TestTradeAnalyzer` in `tests/test_app.py`:

```python
def test_trade_scope_note_on_empty_result_and_preview(self):
    from app import dd_store
    scope = (
        "Player-only verdict: draft picks, FAAB, roster spots, and league "
        "context are not included."
    )
    self.assertIn(scope, self.client.get("/trade").data.decode())

    give, get = dd_store.get_all()[:2]
    query = f"give={give.id}&get={get.id}"
    result = self.client.get(f"/trade?{query}").data.decode()
    self.assertGreaterEqual(result.count(scope), 2)
    preview = self.client.get(f"/trade/share-card?{query}").data.decode()
    self.assertIn(scope, preview)

def test_trade_scope_note_is_rendered_into_png(self):
    import app as app_module
    from unittest.mock import patch

    give, get = app_module.dd_store.get_all()[:2]
    with patch.object(
        app_module,
        "_graphic_wrap_text",
        wraps=app_module._graphic_wrap_text,
    ) as wrap:
        png = app_module._trade_share_card_png([give.id], [get.id])

    wrapped_text = [call.args[1] for call in wrap.call_args_list if len(call.args) > 1]
    self.assertIn(app_module._TRADE_SCOPE_NOTE, wrapped_text)
    self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
```

- [ ] **Step 2: Run the two tests and verify RED**

Run:

```powershell
python -m pytest tests/test_app.py::TestTradeAnalyzer::test_trade_scope_note_on_empty_result_and_preview tests/test_app.py::TestTradeAnalyzer::test_trade_scope_note_is_rendered_into_png -q
```

Expected: both tests fail because the sentence and `_TRADE_SCOPE_NOTE` do not exist.

- [ ] **Step 3: Add the smallest shared implementation**

In `app.py`, beside `_TRADE_NOISE_PER_PLAYER`, add:

```python
_TRADE_SCOPE_NOTE = (
    "Player-only verdict: draft picks, FAAB, roster spots, and league context "
    "are not included."
)
```

In `_build_trade_page_context`, add the existing constant to the returned mapping:

```python
"trade_scope_note": _TRADE_SCOPE_NOTE,
```

In `templates/trade.html`, after the existing free-number explanation, render:

```html
<p class="buys-fineprint"><strong>{{ trade_scope_note }}</strong></p>
```

In `templates/partials/_trade_result.html`, immediately after `.trade-verdict-totals`, render:

```html
<p class="trade-note trade-note-even">{{ trade_scope_note }}</p>
```

In `_trade_share_card_png`, seed the existing note list with the same constant and preserve the default note when no conditional caveat applies:

```python
notes = [(muted, _TRADE_SCOPE_NOTE)]
```

Replace `if not notes:` with:

```python
if len(notes) == 1:
```

In `trade_share_card`, change the preview description to:

```python
description=(
    f"{_TRADE_SCOPE_NOTE} The board's verdict on this dynasty trade, from the "
    "same 0-100 values ValuCast serves."
),
```

- [ ] **Step 4: Verify GREEN and the unchanged product boundaries**

Run the focused tests:

```powershell
python -m pytest tests/test_app.py::TestTradeAnalyzer -q
```

Expected: every `TestTradeAnalyzer` test passes.

Run the full suite:

```powershell
python -m pytest -q
```

Expected: the full suite passes with no failures.

Confirm frozen areas are untouched:

```powershell
git diff --name-only 325c9cbb --
git diff --check
```

Expected: only `app.py`, the two trade templates, `tests/test_app.py`, and this plan appear; `git diff --check` prints nothing.

Run the 390x844 browser check:

```powershell
$server = Start-Process python -ArgumentList '-m','flask','--app','app','run','--port','5092' -WorkingDirectory (Get-Location) -WindowStyle Hidden -PassThru
npx --yes --package @playwright/cli playwright-cli -s=trade-honesty open http://127.0.0.1:5092/trade
npx --yes --package @playwright/cli playwright-cli -s=trade-honesty resize 390 844
npx --yes --package @playwright/cli playwright-cli -s=trade-honesty screenshot --filename=trade-honesty-mobile.png
npx --yes --package @playwright/cli playwright-cli -s=trade-honesty console
npx --yes --package @playwright/cli playwright-cli -s=trade-honesty close
Stop-Process -Id $server.Id
```

Expected: the disclosure is visible without horizontal overflow or clipping, and no new console error is present.

- [ ] **Step 5: Commit the implementation**

```powershell
git add -- app.py templates/trade.html templates/partials/_trade_result.html tests/test_app.py
git commit -m "fix: label trade verdicts as player-only"
```
