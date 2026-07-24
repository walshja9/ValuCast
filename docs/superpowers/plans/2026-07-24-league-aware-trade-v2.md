# League-Aware Second Opinion V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in, manual league-context mode to The Second Opinion that adjusts every trade for league depth, applies scoring presets only where the served data supports them, and keeps legacy trade links unchanged.

**Architecture:** Keep the feature inside the existing `/trade` request, Jinja, and Pillow paths. Add one pure league-context calculation beside `_trade_verdict`, pass its selected values into the existing verdict and display helpers, and serialize one canonical set of query parameters across the page, preview, Open Graph image, and PNG. Reuse `parse_league_settings`, `DYNASTY_VALUE_PRESETS`, `PublicSnapshotRow.value_for`, the existing public snapshot, and the existing responsive/style system; add no model, artifact, workflow, storage, account, or dependency.

**Tech Stack:** Python 3.14, Flask, Jinja, Pillow, standard-library `urllib.parse`, `unittest`/pytest, existing browser test tooling.

## Global Constraints

- Work only on `codex/league-aware-trade-v2` in the isolated worktree.
- Preserve exact V1 behavior whenever `league=1` is absent.
- Do not change ranks, base values, public artifacts, daily workflows, model code, pitcher publication rules, the model freeze, or the failed-decay flag.
- Use the complete served dynasty universe for replacement level; never calculate replacement from only the players in the trade.
- If a recognized scoring preset is requested and any trade piece is a prospect, use base dynasty values for every player and the entire replacement pool.
- `pslots` and `window` are display-only. Tests must prove they cannot change values or verdicts.
- Keep the existing approximately ±9-per-player decision band.
- Add no new source module, script, dependency, database, or persistence layer.
- Do not deploy in this plan.

---

## Task 1: Add the Pure League-Context Calculation

**Files:**

- Modify: `tests/test_app.py` (`TestTradeAnalyzer`)
- Modify: `app.py:7707-7899`

- [ ] **Step 1: Add failing tests for V1 compatibility and V2 numerical behavior**

Add these tests to `TestTradeAnalyzer`:

```python
def test_trade_league_mode_adjusts_values_above_replacement(self):
    from werkzeug.datastructures import MultiDict
    from app import _build_trade_page_context, dd_store

    give, get = [
        row for row in dd_store.get_all()
        if not row.is_prospect and row.dynasty_value
    ][:2]
    legacy = _build_trade_page_context(
        MultiDict([("give", give.id), ("get", get.id)])
    )
    tuned = _build_trade_page_context(MultiDict([
        ("league", "1"),
        ("teams", "4"),
        ("roster", "10"),
        ("give", give.id),
        ("get", get.id),
    ]))

    self.assertFalse(legacy["league_context"]["enabled"])
    self.assertTrue(tuned["league_context"]["enabled"])
    self.assertNotEqual(
        [legacy["give_pieces"][0]["value"], legacy["get_pieces"][0]["value"]],
        [tuned["give_pieces"][0]["value"], tuned["get_pieces"][0]["value"]],
    )

def test_trade_league_depth_can_change_same_trade_totals(self):
    # Same players; only teams/roster differ.
    from werkzeug.datastructures import MultiDict
    from app import _build_trade_page_context, dd_store

    mlb = sorted(
        (
            row for row in dd_store.get_all()
            if not row.is_prospect and row.dynasty_value
        ),
        key=lambda row: row.dynasty_value,
        reverse=True,
    )
    common = [("league", "1"), ("give", mlb[0].id), ("get", mlb[1].id)]
    shallow = _build_trade_page_context(
        MultiDict(common + [("teams", "4"), ("roster", "10")])
    )
    deep = _build_trade_page_context(
        MultiDict(common + [("teams", "20"), ("roster", "50")])
    )
    self.assertNotEqual(
        shallow["league_context"]["replacement_value"],
        deep["league_context"]["replacement_value"],
    )
    self.assertNotEqual(shallow["verdict"], deep["verdict"])

def test_trade_mlb_preset_uses_value_for_every_piece(self):
    # Choose an MLB pair whose 5x5 and 7x7_ops values differ.
    from werkzeug.datastructures import MultiDict
    from app import _build_trade_page_context, dd_store

    candidates = [
        row for row in dd_store.get_all()
        if not row.is_prospect
        and row.value_for("7x7_ops") != row.dynasty_value
    ]
    give, get = candidates[:2]
    ctx = _build_trade_page_context(MultiDict([
        ("league", "1"),
        ("teams", "12"),
        ("roster", "26"),
        ("preset", "7x7_ops"),
        ("give", give.id),
        ("get", get.id),
    ]))
    replacement = ctx["league_context"]["replacement_value"]
    self.assertTrue(ctx["league_context"]["preset_applied"])
    self.assertEqual(
        ctx["give_pieces"][0]["value"],
        round(max(0.0, give.value_for("7x7_ops") - replacement), 1),
    )
    self.assertEqual(
        ctx["get_pieces"][0]["value"],
        round(max(0.0, get.value_for("7x7_ops") - replacement), 1),
    )

def test_trade_mixed_preset_falls_back_to_base_for_every_piece(self):
    # One MLB row plus one prospect; compare preset request with base V2.
    from werkzeug.datastructures import MultiDict
    from app import _build_trade_page_context, dd_store

    rows = dd_store.get_all()
    mlb = next(
        row for row in rows
        if not row.is_prospect
        and row.value_for("7x7_ops") != row.dynasty_value
    )
    prospect = next(row for row in rows if row.is_prospect)
    common = [
        ("league", "1"),
        ("teams", "12"),
        ("roster", "26"),
        ("give", mlb.id),
        ("get", prospect.id),
    ]
    base = _build_trade_page_context(MultiDict(common))
    requested = _build_trade_page_context(
        MultiDict(common + [("preset", "7x7_ops")])
    )
    self.assertFalse(requested["league_context"]["preset_applied"])
    self.assertTrue(requested["league_context"]["preset_fell_back"])
    self.assertEqual(requested["give_pieces"], base["give_pieces"])
    self.assertEqual(requested["get_pieces"], base["get_pieces"])
    self.assertEqual(requested["verdict"], base["verdict"])

def test_trade_window_and_prospect_slots_are_numerically_inert(self):
    # Assert verdict dict and piece values are exactly equal.
    from werkzeug.datastructures import MultiDict
    from app import _build_trade_page_context, dd_store

    give, get = dd_store.get_all()[:2]
    common = [
        ("league", "1"),
        ("teams", "12"),
        ("roster", "26"),
        ("give", give.id),
        ("get", get.id),
    ]
    balanced = _build_trade_page_context(
        MultiDict(common + [("pslots", "5"), ("window", "balanced")])
    )
    changed = _build_trade_page_context(
        MultiDict(common + [("pslots", "20"), ("window", "rebuild")])
    )
    self.assertEqual(balanced["give_pieces"], changed["give_pieces"])
    self.assertEqual(balanced["get_pieces"], changed["get_pieces"])
    self.assertEqual(balanced["verdict"], changed["verdict"])

def test_trade_invalid_settings_fail_closed(self):
    # Unknown preset -> base values/not applied; unknown window -> balanced;
    # malformed/extreme numeric fields use parse_league_settings defaults/clamps.
    from werkzeug.datastructures import MultiDict
    from app import _build_trade_page_context, dd_store

    give, get = dd_store.get_all()[:2]
    ctx = _build_trade_page_context(MultiDict([
        ("league", "1"),
        ("teams", "abc"),
        ("roster", "999"),
        ("pslots", "-3"),
        ("preset", "invented"),
        ("window", "tomorrow"),
        ("give", give.id),
        ("get", get.id),
    ]))
    league = ctx["league_context"]
    self.assertEqual(league["teams"], 12)
    self.assertEqual(league["roster"], 50)
    self.assertEqual(league["pslots"], 0)
    self.assertIsNone(league["preset"])
    self.assertFalse(league["preset_applied"])
    self.assertEqual(league["window"], "balanced")
```

Also extend the existing pure verdict tests with an injected value function:

```python
def test_verdict_can_sum_supplied_values_without_changing_default(self):
    from app import _trade_verdict
    give = self._row(80)
    get = self._row(95)
    self.assertEqual(_trade_verdict([give], [get])["margin"], 15.0)
    custom = {id(give): 10.0, id(get): 30.0}
    self.assertEqual(
        _trade_verdict([give], [get], value_of=lambda row: custom[id(row)])["margin"],
        20.0,
    )
```

Use real snapshot rows in integration-style helper tests so the test exercises `value_for`, the complete replacement pool, and the actual prospect/MLB data contract. Select rows by properties rather than hardcoded player IDs.

- [ ] **Step 2: Run the new tests and confirm the expected failures**

Run:

```powershell
python -m pytest -q tests/test_app.py -k "trade and (league or supplied_values)"
```

Expected: failures because `_trade_verdict` has no `value_of` argument and the context has no `league_context`.

- [ ] **Step 3: Generalize the existing verdict and piece helpers minimally**

In `app.py`:

1. Change `_trade_verdict(give_rows, get_rows)` to
   `_trade_verdict(give_rows, get_rows, value_of=None)`.
2. Default `value_of` to the current `dynasty_value` getter so every V1 caller is unchanged.
3. Change `_trade_piece(row)` to `_trade_piece(row, value=None)`.
4. When `value` is `None`, keep the current `row.dynasty_value`; otherwise render the supplied adjusted value.

Do not change the honesty flags, noise calculation, headline, rounding, or favored-side behavior.

- [ ] **Step 4: Add one deterministic league-context helper**

Add constants beside the V1 trade constants:

```python
_TRADE_LEAGUE_SCOPE_NOTE = (
    "Player-only verdict: draft picks, FAAB, and unlisted roster effects "
    "are not included."
)
_TRADE_WINDOW_LABELS = {
    "balanced": "Balanced",
    "contend": "Contending",
    "rebuild": "Rebuilding",
}
_TRADE_PRESET_LABELS = {
    "5x5": "5x5",
    "obp": "OBP",
    "6x6": "6x6",
    "sv_hld": "SV+HLD",
    "7x7": "7x7",
    "7x7_ops": "7x7 OPS",
    "points": "Points",
}
```

Add a single helper with this contract:

```python
def _trade_league_context(args, trade_rows):
    """Return (canonical V2 state, value getter); never mutate rows."""
```

The helper must:

1. Enable V2 only when `args.get("league") == "1"`.
2. Parse teams, roster, and prospect slots with `parse_league_settings(args)`.
3. Accept a preset only when it is a key in `DYNASTY_VALUE_PRESETS`.
4. Canonicalize an unknown window to `balanced`.
5. Set `preset_applied` only when V2 is enabled, a recognized preset was requested, the trade has resolved rows, and every trade row is MLB.
6. Choose `row.value_for(preset)` only when `preset_applied`; otherwise choose `row.dynasty_value`.
7. For V2, sort `dd_store.get_all()` by the selected value, use `min(settings.roster_cutoff, len(rows))`, take the final rostered row as replacement, and return `max(0.0, selected - replacement)` for each row.
8. For V1, return the unadjusted base-value getter and the exact legacy scope note.
9. Return canonical params only for enabled V2:

```python
[
    ("league", "1"),
    ("teams", str(settings.teams)),
    ("roster", str(settings.roster)),
    ("pslots", str(settings.pslots)),
    ("preset", preset or ""),
    ("window", window),
]
```

10. Return `(context, value_of)`, where `context` is a template-safe dictionary
    containing at least:

```python
{
    "enabled": bool,
    "teams": int,
    "roster": int,
    "pslots": int,
    "preset": str | None,
    "preset_label": str,
    "preset_applied": bool,
    "preset_fell_back": bool,
    "window": str,
    "window_label": str,
    "replacement_value": float | None,
    "summary": str,
    "disclosures": list[str],
    "params": list[tuple[str, str]],
    "scope_note": str,
}
```

The V2 summary must be exactly:

```text
12 teams · 26 roster spots · 5 prospect slots · 7x7 OPS · Contending
```

Use `Base dynasty values` as the scoring label when no recognized preset is applied or requested. The disclosure list must use the exact approved wording from the design spec. Do not include the parser's budget field in the calculation or summary.

- [ ] **Step 5: Route all page calculations through the helper**

In `_build_trade_page_context(args)`:

1. Preserve the existing ID parsing, resolution, cross-side duplicate cancellation, and one-sided behavior.
2. Build `trade_rows = give_rows + get_rows`.
3. Call `_trade_league_context(args, trade_rows)`.
4. Pass its value getter to `_trade_verdict`.
5. Pass adjusted values to `_trade_piece`.
6. Add `league_context` and the selected scope note to the returned context.
7. Keep V1 `give_param`, `get_param`, verdict, and pieces byte-for-byte compatible.

Avoid caching per-request league values or mutating `PublicSnapshotRow`.

- [ ] **Step 6: Run all trade tests**

Run:

```powershell
python -m pytest -q tests/test_app.py -k trade
```

Expected: all trade tests pass.

- [ ] **Step 7: Commit the calculation slice**

```powershell
git add app.py tests/test_app.py
git commit -m "feat: add league-adjusted trade calculations"
```

---

## Task 2: Add the Manual Form, Canonical URLs, and Honest Page Copy

**Files:**

- Modify: `tests/test_app.py` (`TestTradeAnalyzer`)
- Modify: `app.py:7860-7900`
- Modify: `templates/trade.html`
- Modify: `templates/partials/_trade_result.html`
- Modify: `static/style.css:2513-2573`

- [ ] **Step 1: Add failing route and template tests**

Add tests proving:

```python
def test_trade_legacy_url_keeps_v1_scope_and_share_query(self):
    from app import _TRADE_SCOPE_NOTE, dd_store

    give, get = dd_store.get_all()[:2]
    body = self.client.get(
        f"/trade?give={give.id}&get={get.id}"
    ).data.decode()
    self.assertIn(_TRADE_SCOPE_NOTE, body)
    self.assertNotIn("league=1", body)
    self.assertIn(
        f"/trade/share-card.png?give={give.id}&amp;get={get.id}",
        body,
    )

def test_trade_v2_form_renders_canonical_clamped_state(self):
    body = self.client.get(
        "/trade?league=1&teams=99&roster=2&pslots=999"
        "&preset=invented&window=tomorrow"
    ).data.decode()
    self.assertIn('name="league" value="1"', body)
    self.assertIn('name="teams" value="20"', body)
    self.assertIn('name="roster" value="10"', body)
    self.assertIn('name="pslots" value="20"', body)
    self.assertIn('value="balanced" selected', body)
    self.assertNotIn('value="invented" selected', body)

def test_trade_v2_result_shows_summary_and_disclosures(self):
    from app import dd_store

    rows = dd_store.get_all()
    mlb = next(row for row in rows if not row.is_prospect)
    prospect = next(row for row in rows if row.is_prospect)
    body = self.client.get(
        f"/trade?league=1&teams=12&roster=26&pslots=5"
        f"&preset=7x7_ops&window=contend&give={mlb.id}&get={prospect.id}"
    ).data.decode()
    self.assertIn(
        "12 teams · 26 roster spots · 5 prospect slots · "
        "7x7 OPS · Contending",
        body,
    )
    self.assertIn("Scoring preset not applied:", body)
    self.assertIn(
        "Prospect slots are roster-depth context only and do not change the totals.",
        body,
    )
    self.assertIn(
        "Competitive window is context only and does not change the totals.",
        body,
    )

def test_trade_v2_share_links_preserve_every_canonical_setting(self):
    import html
    import re
    from urllib.parse import parse_qs, urlparse
    from app import dd_store

    give, get = dd_store.get_all()[:2]
    body = self.client.get(
        f"/trade?league=1&teams=12&roster=26&pslots=5"
        f"&preset=7x7_ops&window=contend&give={give.id}&get={get.id}"
    ).data.decode()
    href = html.unescape(re.search(
        r'href="([^"]*/trade/share-card\.png\?[^"]+)"',
        body,
    ).group(1))
    self.assertEqual(
        parse_qs(urlparse(href).query, keep_blank_values=True),
        {
            "league": ["1"],
            "teams": ["12"],
            "roster": ["26"],
            "pslots": ["5"],
            "preset": ["7x7_ops"],
            "window": ["contend"],
            "give": [give.id],
            "get": [get.id],
        },
    )

def test_trade_v2_js_preserves_context_when_players_change(self):
    body = self.client.get(
        "/trade?league=1&teams=16&roster=30&pslots=8"
        "&preset=5x5&window=rebuild"
    ).data.decode()
    self.assertIn("var tradeParams =", body)
    self.assertIn('"league": "1"', body)
    self.assertIn('"teams": "16"', body)
    self.assertIn("new URLSearchParams(tradeParams)", body)
```

Assertions must cover:

- `/trade?give=...&get=...` still shows `_TRADE_SCOPE_NOTE`, not the V2 note.
- V2 form controls are populated from canonical values, including clamped inputs.
- MLB-only preset mode prints `Scoring preset applied to every player.`
- Mixed/prospect mode prints the exact fail-closed preset disclosure.
- The result prints both context-only disclosures.
- Page, PNG, and preview links include `league`, `teams`, `roster`, `pslots`, `preset`, `window`, `give`, and `get`.
- Invalid or unknown inputs do not survive in canonical links.
- Legacy links do not gain `league=1`.
- Player add/remove JavaScript starts with server-provided canonical context rather than rebuilding a `give`/`get`-only URL.

- [ ] **Step 2: Run the route tests and confirm failure**

Run:

```powershell
python -m pytest -q tests/test_app.py -k "trade and (legacy_url or v2_form or v2_result or v2_share_links or v2_js)"
```

Expected: failures because the form, V2 copy, and canonical URL state are not rendered yet.

- [ ] **Step 3: Centralize the canonical query in the page context**

In `_build_trade_page_context`, combine the context helper's canonical V2 pairs with the resolved `give` and `get` pairs. Return:

```python
"trade_query_pairs": query_pairs,
"trade_query_params": dict(query_pairs),
```

The list is authoritative for Python `urlencode`; the dictionary is serialized to JavaScript. Include `give` and `get` only when non-empty. In `trade()`, build the Open Graph, PNG, and preview URLs from `trade_query_pairs`.

V1 must still produce only `give` and `get`.

- [ ] **Step 4: Replace the “coming” copy with a compact GET form**

In `templates/trade.html`:

1. Keep the existing heading and free-product language.
2. Remove the “league-aware version is coming” sentence.
3. Add a form with:
   - hidden `league=1`;
   - hidden resolved `give` and `get`;
   - number inputs for `teams`, `roster`, and `pslots`;
   - a blank/base option plus every existing dynasty-value preset;
   - `balanced`, `contend`, and `rebuild` window options;
   - `Apply league context` submit button;
   - a `Use standard board` link that preserves only resolved `give`/`get`.
4. Use the canonical values returned by the server; do not duplicate clamping in JavaScript.
5. Keep all controls labeled and keyboard accessible.

In the existing `currentUrl()` JavaScript function, initialize `URLSearchParams` from `trade_query_params`, then replace only `give` and `get`. Delete an empty side instead of serializing an empty value. This preserves canonical league context whenever a player is added or removed.

- [ ] **Step 5: Render V2 summary and disclosures beside the verdict**

In `templates/partials/_trade_result.html`, when `league_context.enabled`:

1. Print the league summary before the scope note.
2. Print every string in `league_context.disclosures`.
3. Continue printing the existing noise, count-mismatch, and cross-universe notes.

Do not show V2 disclosures on legacy links. Do not describe a mixed/prospect result as preset-adjusted.

- [ ] **Step 6: Add minimal responsive styles**

Add only the styles needed for a compact settings grid, labels, inputs/selects, actions, and mobile stacking. Reuse existing colors, borders, radii, `.glass`, `.position-select`, `.export-btn`, and spacing variables where practical.

At `max-width: 640px`, controls must become one column and buttons/links must remain at least 44px tall. Do not create a new design system or JavaScript component.

- [ ] **Step 7: Run targeted page tests**

Run:

```powershell
python -m pytest -q tests/test_app.py -k trade
```

Expected: all trade tests pass.

- [ ] **Step 8: Commit the page slice**

```powershell
git add app.py templates/trade.html templates/partials/_trade_result.html static/style.css tests/test_app.py
git commit -m "feat: add manual league context to Second Opinion"
```

---

## Task 3: Keep the PNG, Preview, Metadata, and Cache Key in Parity

**Files:**

- Modify: `tests/test_app.py` (`TestTradeAnalyzer`)
- Modify: `app.py:193-205`
- Modify: `app.py:7901-8075`

- [ ] **Step 1: Add failing share-surface tests**

Add tests:

```python
def test_trade_v2_png_cache_key_distinguishes_league_mode(self):
    from app import _png_cache_key

    with app.test_request_context("/trade/share-card.png?give=a&get=b"):
        legacy = _png_cache_key()
    with app.test_request_context(
        "/trade/share-card.png?league=1&teams=12&roster=26"
        "&pslots=5&preset=5x5&window=balanced&give=a&get=b"
    ):
        tuned = _png_cache_key()
    self.assertNotEqual(legacy, tuned)

def test_trade_v2_png_receives_summary_and_all_disclosures(self):
    import app as app_module
    from unittest.mock import patch
    from werkzeug.datastructures import MultiDict

    rows = app_module.dd_store.get_all()
    mlb = next(row for row in rows if not row.is_prospect)
    prospect = next(row for row in rows if row.is_prospect)
    args = MultiDict([
        ("league", "1"),
        ("teams", "12"),
        ("roster", "26"),
        ("pslots", "5"),
        ("preset", "7x7_ops"),
        ("window", "contend"),
    ])
    with patch.object(
        app_module,
        "_graphic_wrap_text",
        wraps=app_module._graphic_wrap_text,
    ) as wrap:
        png = app_module._trade_share_card_png(
            [mlb.id],
            [prospect.id],
            league_args=args,
        )
    wrapped = [call.args[1] for call in wrap.call_args_list]
    self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
    self.assertTrue(any("12 teams" in text for text in wrapped))
    self.assertTrue(any("Scoring preset not applied:" in text for text in wrapped))
    self.assertTrue(any("Prospect slots are roster-depth context" in text for text in wrapped))
    self.assertTrue(any("Competitive window is context only" in text for text in wrapped))

def test_trade_v2_preview_metadata_preserves_canonical_state(self):
    from app import dd_store

    give, get = dd_store.get_all()[:2]
    query = (
        f"league=1&teams=12&roster=26&pslots=5&preset=5x5"
        f"&window=balanced&give={give.id}&get={get.id}"
    )
    body = self.client.get(f"/trade/share-card?{query}").data.decode()
    for token in (
        "league=1", "teams=12", "roster=26", "pslots=5",
        "preset=5x5", "window=balanced", f"give={give.id}", f"get={get.id}",
    ):
        self.assertIn(token.replace("&", "&amp;"), body)

def test_trade_v2_page_png_and_preview_use_same_query(self):
    import html
    import re
    from urllib.parse import parse_qs, urlparse
    from app import dd_store

    give, get = dd_store.get_all()[:2]
    query = (
        f"league=1&teams=12&roster=26&pslots=5&preset="
        f"&window=rebuild&give={give.id}&get={get.id}"
    )
    body = self.client.get(f"/trade?{query}").data.decode()
    urls = [
        html.unescape(match)
        for match in re.findall(
            r'(?:href|content)="([^"]*/trade/share-card(?:\.png)?\?[^"]+)"',
            body,
        )
    ]
    parsed = [
        parse_qs(urlparse(url).query, keep_blank_values=True)
        for url in urls
    ]
    self.assertGreaterEqual(len(parsed), 2)
    self.assertTrue(all(item == parsed[0] for item in parsed[1:]))

def test_trade_legacy_png_still_uses_legacy_scope_note(self):
    import app as app_module
    from unittest.mock import patch

    give, get = app_module.dd_store.get_all()[:2]
    with patch.object(
        app_module,
        "_graphic_wrap_text",
        wraps=app_module._graphic_wrap_text,
    ) as wrap:
        app_module._trade_share_card_png([give.id], [get.id])
    wrapped = [call.args[1] for call in wrap.call_args_list]
    self.assertIn(app_module._TRADE_SCOPE_NOTE, wrapped)
    self.assertNotIn(app_module._TRADE_LEAGUE_SCOPE_NOTE, wrapped)
```

For PNG copy, patch `_graphic_wrap_text` as the current scope-note test does and assert that the exact summary and applicable disclosures reach the renderer. For URL parity, parse links with `urllib.parse` and compare query dictionaries instead of relying on parameter order.

- [ ] **Step 2: Run the share tests and confirm failure**

Run:

```powershell
python -m pytest -q tests/test_app.py -k "trade and (png or preview or same_query)"
```

Expected: V2-specific assertions fail because the renderer and preview currently parse only `give`/`get`.

- [ ] **Step 3: Add `league` to the bounded PNG cache vocabulary**

Add `"league"` to `_PNG_CACHE_PARAMS`. Do not add any open-ended key. Existing bounded keys already cover `teams`, `roster`, `pslots`, `preset`, `window`, `give`, and `get`.

The test must prove otherwise-identical V1 and V2 PNG URLs produce different cache keys.

- [ ] **Step 4: Feed the canonical V2 state to the existing renderer**

Extend `_trade_share_card_png` with one optional request-state argument while preserving existing direct callers:

```python
def _trade_share_card_png(
    give_ids,
    get_ids,
    *,
    generated_at=None,
    league_args=None,
):
```

Inside the renderer:

1. Keep existing row resolution and duplicate cancellation.
2. Call `_trade_league_context(league_args or {}, give_rows + get_rows)`.
3. Pass the selected value getter to `_trade_verdict`.
4. Pass adjusted values into `_trade_piece` for each displayed row.
5. Use the selected V1/V2 scope note.
6. Add the V2 summary and disclosures to the existing wrapped-note list.
7. Keep the dynamic content-fit canvas; do not add a second renderer or hardcode a new height.
8. Keep all Pillow text ASCII-safe where the renderer requires it. Convert display separators to `" - "` on the PNG while preserving the approved words.

The route `trade_share_card_png()` must pass the request args through to the renderer.

- [ ] **Step 5: Canonicalize the preview route**

In `trade_share_card()`:

1. Build the same trade page context from `request.args`.
2. Return 404 or the existing invalid state when no two-sided verdict resolves.
3. Build PNG, page, and back URLs from `trade_query_pairs`.
4. Include the V2 summary and scope note in the preview description when V2 is enabled.
5. Keep the legacy description unchanged for V1.

Do not let unknown query parameters enter generated URLs or cache keys.

- [ ] **Step 6: Run all trade tests**

Run:

```powershell
python -m pytest -q tests/test_app.py -k trade
```

Expected: all legacy and V2 trade tests pass.

- [ ] **Step 7: Commit the share-parity slice**

```powershell
git add app.py tests/test_app.py
git commit -m "feat: keep league-aware trade graphics in parity"
```

---

## Task 4: Adversarial Verification and Handoff

**Files:**

- Verify only unless a test exposes a defect.

- [ ] **Step 1: Run focused trade regression**

```powershell
python -m pytest -q tests/test_app.py -k trade
```

Expected: all trade tests pass.

- [ ] **Step 2: Run the committed-artifact/daily-public validation**

Use the repository's current validation entry point:

```powershell
python scripts/run_daily_public_build.py --only validate
```

If the command has changed on master, inspect `--help` and use the existing validation-only command. Do not run a publication or refresh workflow from this feature branch.

Expected: validation passes without changing tracked data.

- [ ] **Step 3: Run the full automated suite**

```powershell
python -m pytest -q
```

Expected: full suite passes.

- [ ] **Step 4: Run static hygiene checks**

```powershell
git diff --check origin/master...HEAD
git status --short
git diff --name-only origin/master...HEAD
```

Expected:

- no whitespace errors;
- only the approved trade code, templates, styles, tests, spec, and plan changed;
- no model, data artifact, workflow, or dependency file changed.

- [ ] **Step 5: Run a 390×844 browser pass**

Start the app with the repository's normal local command, then inspect:

1. bare `/trade`;
2. a legacy MLB/prospect trade;
3. a shallow V2 MLB-only preset trade;
4. a mixed V2 preset request that must fall back;
5. the V2 preview and PNG.

At 390×844 verify:

- every input and action is visible and usable;
- no horizontal clipping;
- all disclosures are readable;
- add/remove keeps league settings in the URL;
- `Use standard board` removes league context without removing players;
- preview and PNG load;
- no new browser-console errors.

- [ ] **Step 6: Re-run focused tests after browser QA**

```powershell
python -m pytest -q tests/test_app.py -k trade
```

Expected: all trade tests still pass.

- [ ] **Step 7: Review the final diff against the approved design**

Confirm each item in `docs/superpowers/specs/2026-07-24-league-aware-trade-v2-design.md` is either implemented and tested or explicitly out of scope. In particular, recheck:

- legacy URL parity;
- replacement pool scope;
- preset fail-closed behavior;
- numerical inertness of `pslots` and `window`;
- page/PNG/cache-key parity;
- no model or daily-refresh changes.

- [ ] **Step 8: Prepare the branch for independent review**

Do not merge, deploy, or publish automatically. Report:

- commit list;
- exact test commands and results;
- any browser screenshots;
- changed-file list;
- explicit confirmation that model/data/workflow files are untouched.
