# Rankings Correctness Trio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make per-player display metadata (auction $, position rank, tier) filter-invariant, make category presets/column order serialization-independent, and show projected stats by default with a `Projections | Category value` toggle.

**Architecture:** Compute all display metadata on a fixed **top-200-by-value pool of the full valued universe** (search/pool/position-independent), then apply display filters only — so the default board is byte-identical and filtered views show the *same* numbers. Normalize category id lists to canonical registry order at parse time, and compare presets order-insensitively. Add a `display` request param (default `projections`) driving a stat-vs-value column render, an accessible toggle, and export.

**Tech Stack:** Flask, Jinja2, htmx, Python `unittest` (run via pytest).

**Spec:** `docs/superpowers/specs/2026-06-09-rankings-correctness-design.md`

**Test command:** `python -m pytest tests -q -p no:cacheprovider` (subsets shown per task).

---

## File Structure

- `app.py` — `_build_context` (redraft metadata-on-full-universe + canonical cats + `display`), `_build_dynasty_context` + the prospect branches in `index()`/`rankings()` (dynasty metadata-on-full-universe), `_config_summary` (order-insensitive), `export_csv` (`display`-aware), a `format_stat` Jinja filter, and `_canonical_cats` helper.
- `web/category_registry.py` — `CANONICAL_CAT_ORDER` / `canonicalize_cats()` helper.
- `templates/partials/rankings_table.html` — projections-vs-value cell + header render.
- `templates/index.html` — `Projections | Category value` toggle in the filter bar.
- `static/style.css` — reuse `.source-seg`/`.source-opt`; no new control styles needed.
- `tests/test_filter_stable_metadata.py`, `tests/test_category_ordering.py`, `tests/test_display_toggle.py` — new.

---

### Task 1: Filter-stable redraft metadata (auction $, position rank, tier)

**Bug:** `_build_context` filters + truncates to top-200 *before* `_compute_position_ranks`/`_compute_dollar_values`/`_compute_tiers` (`app.py:424-454`), so searching one player hands him the whole budget. Fix: compute metadata on a fixed top-200 pool of the full valued universe; filter for display only.

**Files:**
- Modify: `app.py:416-483` (`_build_context`)
- Test: `tests/test_filter_stable_metadata.py`

- [ ] **Step 1: Write the failing invariant tests**

Create `tests/test_filter_stable_metadata.py`:

```python
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from app import app


def _ohtani_dollars(html):
    # Find the row containing "Ohtani" and pull its $ cell (col-dollars).
    m = re.search(r'Ohtani.*?col-dollars[^>]*>\s*\$?(\d+)', html, re.S)
    return int(m.group(1)) if m and m.group(1) else None


class TestFilterStableMetadata(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_search_does_not_inflate_dollars(self):
        # The classic bug: searching one player handed him the whole $2400 budget.
        full = self.client.get("/rankings").data.decode("utf-8")
        searched = self.client.get("/rankings?search=ohtani").data.decode("utf-8")
        d_full = _ohtani_dollars(full)
        d_search = _ohtani_dollars(searched)
        self.assertIsNotNone(d_full)
        self.assertIsNotNone(d_search)
        self.assertEqual(d_full, d_search, "auction $ changed under search")
        self.assertLess(d_search, 500, "single-player search still shows budget artifact")

    def test_pool_filter_preserves_dollars(self):
        full = self.client.get("/rankings").data.decode("utf-8")
        hitters = self.client.get("/rankings?pool=hitter").data.decode("utf-8")
        self.assertEqual(_ohtani_dollars(full), _ohtani_dollars(hitters))
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_filter_stable_metadata.py -q -p no:cacheprovider`
Expected: FAIL — searched/pool dollars differ from full (and the search value is huge).

- [ ] **Step 3: Refactor `_build_context` to compute metadata on the full universe**

In `app.py`, replace the block from `search_keep = (` through the three `_compute_*` assignments (the current lines 416-454 region computing results, filtering, top-200, then ranks/dollars/tiers) so that valuation→metadata happens on the canonical universe and filtering happens after. Replace:

```python
    search_keep = (
        {p.id for p in active.get_all() if search.lower() in p.name.lower()}
        if search
        else frozenset()
    )
    results = engine.value_players(_valuation_players(search_keep, active_store=active), config)
    results = _merge_two_way_players(results)

    # Filter results for display
    if pool:
        if pool == "pitcher":
            results = [
                r for r in results
                if r.player.pool in (PlayerPool.PITCHER, PlayerPool.STARTER, PlayerPool.RELIEVER)
            ]
        else:
            results = [r for r in results if r.player.pool == PlayerPool(pool)]
    if position:
        results = [r for r in results if position in r.player.positions]
    if search:
        query = search.lower()
        results = [r for r in results if query in r.player.name.lower()]

    # Limit to top 200
    results = results[:200]
```

with:

```python
    # Value the canonical universe (search/filter-independent) so display metadata is
    # stable. A search may surface sub-threshold players for DISPLAY only; it must not
    # change the pool the metadata is computed on.
    all_results = _merge_two_way_players(
        engine.value_players(_valuation_players(active_store=active), config)
    )
    all_results.sort(key=lambda r: r.total_value, reverse=True)

    # Metadata pool = the fixed top-200-by-value of the full universe (the same set the
    # default unfiltered board shows). Computing $/ranks/tiers here keeps the default
    # board byte-identical AND makes filtered views show the SAME numbers.
    metadata_pool = all_results[:200]

    # Display set: filter the full universe, then surface sub-threshold search matches.
    results = all_results
    if pool:
        if pool == "pitcher":
            results = [
                r for r in results
                if r.player.pool in (PlayerPool.PITCHER, PlayerPool.STARTER, PlayerPool.RELIEVER)
            ]
        else:
            results = [r for r in results if r.player.pool == PlayerPool(pool)]
    if position:
        results = [r for r in results if position in r.player.positions]
    if search:
        query = search.lower()
        results = [r for r in results if query in r.player.name.lower()]
        if not results:
            # Sub-threshold name match: value it on demand for display (no metadata).
            search_keep = {p.id for p in active.get_all() if query in p.name.lower()}
            if search_keep:
                extra = _merge_two_way_players(
                    engine.value_players(
                        _valuation_players(search_keep, active_store=active), config
                    )
                )
                results = [r for r in extra if query in r.player.name.lower()]

    # Limit to top 200 for display
    results = results[:200]
```

- [ ] **Step 4: Point the metadata computations at the fixed pool**

Still in `_build_context`, change the three computations (currently `_compute_position_ranks(results)` etc. near `app.py:452`) from `results` to `metadata_pool`:

```python
    position_ranks = _compute_position_ranks(metadata_pool)
    dollar_values = _compute_dollar_values(metadata_pool)
    tiers = _compute_tiers(metadata_pool)
```

(The template/export already look these up by id with a default, so display rows outside the top-200 pool render `—`/blank — correct, since they are below the valued board.)

- [ ] **Step 5: Run to verify pass**

Run: `python -m pytest tests/test_filter_stable_metadata.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Run the broader suite (default board must be unchanged)**

Run: `python -m pytest tests/test_app.py tests/test_app_source.py -q -p no:cacheprovider`
Expected: PASS (no regressions; the unfiltered board uses the same top-200 denominator as before).

- [ ] **Step 7: Commit**

```bash
git add app.py tests/test_filter_stable_metadata.py
git commit -m "fix: filter-stable redraft metadata (compute on full-universe top-200, filter for display)"
```

---

### Task 2: Filter-stable dynasty + prospects metadata

**Bug:** `_build_dynasty_context` (`app.py:194-197`) and the prospect branches in `index()` (`app.py:502-510`) and `rankings()` (`app.py:533-543`) filter `dd_store` then truncate to 200 *before* computing dynasty dollars/tiers — same artifact. Fix: a single helper computes both on a fixed top-200-by-value pool of the full DD universe.

**Files:**
- Modify: `app.py` — add `_dynasty_metadata()` helper; use it in `_build_dynasty_context` + both prospect branches.
- Test: `tests/test_filter_stable_metadata.py` (extend)

- [ ] **Step 1: Write the failing dynasty invariant test**

Append to `tests/test_filter_stable_metadata.py`:

```python
    def _first_player_dynasty_dollars(self, html):
        m = re.search(r'data-rank="1".*?col-dollars[^>]*>\s*\$?([\d.]+)', html, re.S)
        return float(m.group(1)) if m and m.group(1) else None

    def test_dynasty_dollars_stable_under_position_filter(self):
        # If DD feed is unavailable in this env, skip (fail-closed hides tabs).
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed unavailable")
        full = self.client.get("/rankings?mode=dd_dynasty").data.decode("utf-8")
        ss = self.client.get("/rankings?mode=dd_dynasty&position=SS").data.decode("utf-8")
        # The top SS player's dynasty $ must match its value on the unfiltered board.
        # Pull a known id-stable check: the same player's $ token appears identically.
        m_full = re.findall(r'col-dollars[^>]*>\s*\$?([\d.]+)', full)
        m_ss = re.findall(r'col-dollars[^>]*>\s*\$?([\d.]+)', ss)
        self.assertTrue(m_full and m_ss)
        # Max dynasty $ on a filtered view must not exceed the unfiltered max
        # (filtering used to re-concentrate the budget onto fewer players).
        self.assertLessEqual(max(float(x) for x in m_ss),
                             max(float(x) for x in m_full) + 0.01)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_filter_stable_metadata.py -k dynasty -q -p no:cacheprovider`
Expected: FAIL — filtered view's max $ exceeds unfiltered (budget re-concentrated). (If it errors as skipped, the feed is missing — restore it first.)

- [ ] **Step 3: Add the `_dynasty_metadata` helper**

In `app.py`, immediately after `_compute_dynasty_tiers` (ends ~line 187), add:

```python
def _dynasty_metadata():
    """Dynasty $ and tiers computed on a fixed top-200-by-value pool of the FULL DD
    universe, so they don't change when the displayed rows are filtered."""
    all_rows = sorted(dd_store.get_all(), key=lambda r: r.dynasty_value, reverse=True)
    pool = all_rows[:200]
    return _compute_dynasty_dollars(pool), _compute_dynasty_tiers(pool)
```

- [ ] **Step 4: Use it in `_build_dynasty_context`**

Replace (`app.py:194-198`):

```python
    rows = dd_store.filter(pool=pool or None, position=position or None, search=search or None)
    rows = rows[:200]
    dynasty_dollars = _compute_dynasty_dollars(rows)
    tiers = _compute_dynasty_tiers(rows)
    risk_assessments = {row.id: risk_model.evaluate_dynasty(row) for row in rows}
```

with:

```python
    rows = dd_store.filter(pool=pool or None, position=position or None, search=search or None)
    rows = rows[:200]
    dynasty_dollars, tiers = _dynasty_metadata()
    risk_assessments = {row.id: risk_model.evaluate_dynasty(row) for row in rows}
```

- [ ] **Step 5: Use it in the prospect branches of `index()` and `rankings()`**

In `index()` (the `if mode == "prospects":` block, `app.py:509-510`) replace:

```python
            ctx["dynasty_dollars"] = _compute_dynasty_dollars(rows)
            ctx["tiers"] = _compute_dynasty_tiers(rows)
```

with:

```python
            ctx["dynasty_dollars"], ctx["tiers"] = _dynasty_metadata()
```

Make the identical replacement in `rankings()` (the prospect block, `app.py:541-542`).

- [ ] **Step 6: Run to verify pass + no regressions**

Run: `python -m pytest tests/test_filter_stable_metadata.py tests/test_dd_feed_integrity.py tests/test_dynasty_tiers.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app.py tests/test_filter_stable_metadata.py
git commit -m "fix: filter-stable dynasty/prospects metadata (top-200 universe pool)"
```

---

### Task 3: Canonical category ordering + order-insensitive preset summary

**Bug:** category checkboxes serialize in DOM order; `_config_summary` compares to presets order-sensitively (`app.py:371`), so a reordered-but-identical set flips "Standard 5x5" → "Custom 10 categories" and reorders columns.

**Files:**
- Modify: `web/category_registry.py` — add `canonicalize_cats`.
- Modify: `app.py` — normalize `cats`/`pcats` at parse time; set-based preset match.
- Test: `tests/test_category_ordering.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_category_ordering.py`:

```python
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from app import app
from web.category_registry import canonicalize_cats


class TestCategoryOrdering(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_canonicalize_sorts_to_registry_order(self):
        # Shuffled 5x5 hitting cats normalize to registry order R,HR,RBI,SB,AVG.
        out = canonicalize_cats(["AVG", "SB", "R", "RBI", "HR"], pool="hitter")
        self.assertEqual(out, ["R", "HR", "RBI", "SB", "AVG"])

    def test_shuffled_preset_still_reads_standard(self):
        # Identical 5x5 set in a different order must still say "Standard 5x5".
        qs = "cats=AVG&cats=R&cats=HR&cats=RBI&cats=SB&pcats=WHIP&pcats=W&pcats=SV&pcats=K&pcats=ERA"
        r = self.client.get("/rankings?" + qs)
        self.assertIn(b"Standard 5x5", r.data)
        self.assertNotIn(b"Custom", r.data)

    def test_column_order_is_canonical_regardless_of_input(self):
        # First hitting column header is always R (registry order), not the input's first.
        qs = "cats=AVG&cats=R&cats=HR&cats=RBI&cats=SB&pcats=W&pcats=SV&pcats=K&pcats=ERA&pcats=WHIP"
        r = self.client.get("/rankings?" + qs).data.decode("utf-8")
        # The R header cell must appear before the AVG header cell.
        self.assertLess(r.index('title="Runs"'), r.index('title="Batting Average"'))
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_category_ordering.py -q -p no:cacheprovider`
Expected: FAIL — `canonicalize_cats` missing; shuffled preset reads "Custom".

- [ ] **Step 3: Add `canonicalize_cats` to the registry**

In `web/category_registry.py`, after `_ALL_CATEGORIES` (line 79), add:

```python
# Canonical ordering = registry declaration order (hitting then pitching).
_CANONICAL_ORDER: dict[str, int] = {c.id: i for i, c in enumerate(
    HITTING_CATEGORIES + PITCHING_CATEGORIES
)}


def canonicalize_cats(ids: list[str], pool: str | None = None) -> list[str]:
    """Return the given category ids sorted into canonical registry order,
    dropping unknowns and duplicates (first occurrence wins)."""
    seen = set()
    deduped = []
    for cid in ids:
        if cid in _CANONICAL_ORDER and cid not in seen:
            seen.add(cid)
            deduped.append(cid)
    return sorted(deduped, key=lambda c: _CANONICAL_ORDER[c])
```

(The `pool` arg is accepted for call-site clarity but ordering is global; unknown ids are dropped regardless of pool.)

- [ ] **Step 4: Normalize at parse time in `_build_context`**

In `app.py`, change the `cats`/`pcats` parse lines (`app.py:383-384`):

```python
    cats = parse_list(args.getlist("cats")) or DEFAULT_CATS
    pcats = parse_list(args.getlist("pcats")) or DEFAULT_PCATS
```

to:

```python
    from web.category_registry import canonicalize_cats
    cats = canonicalize_cats(parse_list(args.getlist("cats"))) or list(DEFAULT_CATS)
    pcats = canonicalize_cats(parse_list(args.getlist("pcats"))) or list(DEFAULT_PCATS)
```

- [ ] **Step 5: Make the preset comparison order-insensitive**

In `_config_summary` (`app.py:371`), change:

```python
        if cats == preset["cats"] and pcats == preset["pcats"]:
```

to:

```python
        if set(cats) == set(preset["cats"]) and set(pcats) == set(preset["pcats"]):
```

- [ ] **Step 6: Run to verify pass + no regressions**

Run: `python -m pytest tests/test_category_ordering.py tests/test_app.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web/category_registry.py app.py tests/test_category_ordering.py
git commit -m "fix: canonical category ordering + order-insensitive preset summary"
```

---

### Task 4: Projections columns by default + `Projections | Category value` toggle

Show projected stats (already in `result.raw_values`) by default; a sticky accessible toggle switches to the z-contribution view with explicit `… value` headers + tooltips. Export defaults to projected stats; both honor `display`.

**Files:**
- Modify: `app.py` — `display` param in `_build_context`; `format_stat` Jinja filter; HX-Replace-Url; export.
- Modify: `templates/partials/rankings_table.html` — cell + header render by `display`.
- Modify: `templates/index.html` — toggle in filter bar.
- Test: `tests/test_display_toggle.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_display_toggle.py`:

```python
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from app import app


class TestDisplayToggle(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_default_shows_projected_stats(self):
        # Default (no display param) shows a projected AVG like .2xx / .3xx, not a z-value.
        html = self.client.get("/rankings").data.decode("utf-8")
        # An AVG cell formatted as a leading-dot rate stat must appear somewhere.
        self.assertRegex(html, r'col-cat[^>]*>\s*\.\d{3}\s*<')

    def test_value_view_uses_value_headers(self):
        html = self.client.get("/rankings?display=values").data.decode("utf-8")
        self.assertIn("HR value", html)

    def test_default_header_has_no_value_suffix(self):
        html = self.client.get("/rankings").data.decode("utf-8")
        self.assertNotIn("HR value", html)

    def test_toggle_is_accessible_and_present(self):
        html = self.client.get("/").data.decode("utf-8")
        self.assertIn('name="display"', html)
        self.assertIn('aria-label="Column display"', html)

    def test_display_sticky_in_replace_url(self):
        r = self.client.get("/rankings?display=values")
        self.assertIn("display=values", r.headers.get("HX-Replace-Url", ""))

    def test_default_display_not_in_url(self):
        r = self.client.get("/rankings")
        self.assertNotIn("display=", r.headers.get("HX-Replace-Url", ""))

    def test_export_default_has_projected_stats(self):
        csv = self.client.get("/export").data.decode("utf-8")
        # A rate stat column value with a leading dot indicates projected stats, not z.
        self.assertRegex(csv, r'(^|,)\.\d{3}(,|\r|\n)')
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_display_toggle.py -q -p no:cacheprovider`
Expected: FAIL — columns still show z-values; no `display` param/headers/filter.

- [ ] **Step 3: Add the `format_stat` filter and `_RATE_*` sets to `app.py`**

In `app.py`, just after the Flask `app = Flask(...)` creation (search for `app = Flask`), add:

```python
# Per-category projected-stat formatting for the rankings columns.
_RATE_3DP = {"AVG", "OBP", "SLG", "OPS"}            # .280
_RATE_2DP = {"ERA", "WHIP", "K_BB", "K_9", "BB_9"}  # 3.24
_DECIMAL_1 = {"IP"}                                  # 182.1


@app.template_filter("format_stat")
def format_stat(value, cat_id):
    """Format a projected stat for display, keyed by category id."""
    if value is None:
        return "—"  # em dash
    if cat_id in _RATE_3DP:
        s = f"{value:.3f}"
        return s.replace("0.", ".", 1) if s.startswith(("0.", "-0.")) else s
    if cat_id in _RATE_2DP:
        return f"{value:.2f}"
    if cat_id in _DECIMAL_1:
        return f"{value:.1f}"
    return f"{value:.0f}"
```

- [ ] **Step 4: Parse + expose `display` in `_build_context`**

In `_build_context`, after the `split_rp = ...` line (`app.py:389`) add:

```python
    display = args.get("display", "projections")
    if display not in ("projections", "values"):
        display = "projections"
```

And in the returned context dict (after `"source": ...`, `app.py:481`) add:

```python
        "display": display,
```

- [ ] **Step 5: Render cells + headers by `display` in the table template**

In `templates/partials/rankings_table.html`, replace the header loop (lines 16-18):

```html
            {% for col in display_columns %}
            <th class="col-cat sortable" onclick="sortTable({{ loop.index0 + 7 }})" title="{{ col.label }}">{{ col.id }}</th>
            {% endfor %}
```

with:

```html
            {% for col in display_columns %}
            {% if display == 'values' %}
            <th class="col-cat sortable" onclick="sortTable({{ loop.index0 + 7 }})"
                title="Category value: z-score contribution to total value (not a projection)">{{ col.id }} value</th>
            {% else %}
            <th class="col-cat sortable" onclick="sortTable({{ loop.index0 + 7 }})" title="{{ col.label }}">{{ col.id }}</th>
            {% endif %}
            {% endfor %}
```

Then replace the cell render (lines 60-62):

```html
            <td class="col-cat {{ 'na' if raw is none else '' }}{{ 'val-pos' if raw is not none and val > 0 else '' }}{{ 'val-neg' if raw is not none and val < 0 else '' }}">
                {% if raw is none %}&mdash;{% else %}{{ "%.1f" | format(val) }}{% endif %}
            </td>
```

with:

```html
            <td class="col-cat {{ 'na' if raw is none else '' }}{{ 'val-pos' if display == 'values' and raw is not none and val > 0 else '' }}{{ 'val-neg' if display == 'values' and raw is not none and val < 0 else '' }}">
                {% if raw is none %}&mdash;{% elif display == 'values' %}{{ "%.1f" | format(val) }}{% else %}{{ raw | format_stat(col.id) }}{% endif %}
            </td>
```

- [ ] **Step 6: Add the toggle to the filter bar**

In `templates/index.html`, inside the non-prospects `<section class="filter-bar">` (the first one, after the `pool-toggle` `</div>` at line 106, before the `<select name="position"`), insert:

```html
        <fieldset class="source-seg" aria-label="Column display">
            <label class="source-opt">
                <input type="radio" name="display" value="projections" {% if (display or 'projections') != 'values' %}checked{% endif %}>
                <span>Projections</span>
            </label>
            <label class="source-opt">
                <input type="radio" name="display" value="values" {% if display == 'values' %}checked{% endif %}>
                <span>Category value</span>
            </label>
        </fieldset>
```

- [ ] **Step 7: Make `display` sticky in HX-Replace-Url**

In `rankings()` (the non-dynasty source-append block, `app.py:568-571`), replace:

```python
    push_url = f"/?{url_params}" if url_params else "/"
    if ctx.get("source") and ctx["source"] != "steamer":
        sep = "&" if url_params else ""
        push_url = f"/?{url_params}{sep}source={ctx['source']}"
```

with a query-builder that appends both optional params cleanly:

```python
    extra = []
    if ctx.get("source") and ctx["source"] != "steamer":
        extra.append(f"source={ctx['source']}")
    if ctx.get("display") and ctx["display"] != "projections":
        extra.append(f"display={ctx['display']}")
    all_params = "&".join([p for p in [url_params] + extra if p])
    push_url = f"/?{all_params}" if all_params else "/"
```

- [ ] **Step 8: Make export `display`-aware (default projected stats)**

In `export_csv` (the non-dynasty path, `app.py:760-769`), replace the per-column loop:

```python
        for col in display_columns:
            if col.get("split"):
                sp_raw = result.raw_values.get(col["sp_id"])
                rp_raw = result.raw_values.get(col["rp_id"])
                val = result.category_values.get(col["sp_id"], 0) + result.category_values.get(col["rp_id"], 0)
                row.append(round(val, 1) if sp_raw is not None or rp_raw is not None else "")
            else:
                raw = result.raw_values.get(col["id"])
                val = result.category_values.get(col["id"], 0)
                row.append(round(val, 1) if raw is not None else "")
```

with a `display`-aware version (reads the request's `display`, default projections):

```python
        for col in display_columns:
            if col.get("split"):
                sp_raw = result.raw_values.get(col["sp_id"])
                rp_raw = result.raw_values.get(col["rp_id"])
                raw = sp_raw if sp_raw is not None else rp_raw
                val = result.category_values.get(col["sp_id"], 0) + result.category_values.get(col["rp_id"], 0)
            else:
                raw = result.raw_values.get(col["id"])
                val = result.category_values.get(col["id"], 0)
            if raw is None:
                row.append("")
            elif export_display == "values":
                row.append(round(val, 1))
            else:
                row.append(format_stat(raw, col["id"]))
```

And define `export_display` once near the top of the non-dynasty export path (after `ctx = _build_context(request.args)`, `app.py:726`):

```python
    export_display = ctx.get("display", "projections")
```

- [ ] **Step 9: Run to verify pass**

Run: `python -m pytest tests/test_display_toggle.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 10: Full suite + commit**

Run: `python -m pytest tests -q -p no:cacheprovider`
Expected: PASS (no regressions).

```bash
git add app.py templates/partials/rankings_table.html templates/index.html tests/test_display_toggle.py
git commit -m "feat: projected stats by default + Projections|Category value toggle (sticky, accessible, export-aware)"
```

---

## Self-Review

**Spec coverage:**
- §1 filter-stable values/ranks/dollars/tiers → Tasks 1 (redraft) + 2 (dynasty/prospects). Refinement vs spec: metadata computed on the **fixed top-200 pool of the full universe**, so the default board is byte-identical (the spec's "slight shift" is avoided; only filtered views change to match). Invariant + no-budget-artifact tests included.
- §2 order-insensitive presets + canonical column order → Task 3.
- §3 projections default + `Projections | Category value` toggle, explicit `… value` headers + tooltip, sticky (form + HX-Replace-Url), accessible (reuses focusable `.source-seg`), export default projected stats → Task 4.
- Success criteria 1→Task1/2 tests, 2→Task1 `test_search_does_not_inflate_dollars`, 3→Task3, 4→Task4.

**Placeholder scan:** No TBD/TODO; every step has literal code + commands.

**Consistency:** `display` values `projections`/`values`, `name="display"`, `aria-label="Column display"`, `format_stat` filter, `_dynasty_metadata`, `canonicalize_cats`, `metadata_pool` used identically across app.py, templates, export, and tests. `format_stat` is reused by both the template (Jinja filter) and the export route (direct call).

