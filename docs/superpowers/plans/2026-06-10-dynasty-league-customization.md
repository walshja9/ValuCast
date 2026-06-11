# Dynasty League Customization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users tune the Dynasty board to their league (teams, budget, roster slots, prospect slots) with manual knobs plus a Fantrax/ESPN league-URL settings import, all stateless via form params + localStorage.

**Architecture:** A new `web/league_settings.py` parses/clamps the four params into a `LeagueSettings` dataclass. `app.py` dollar/tier/metadata functions become settings-parameterized with replacement-adjusted auction math. The dynasty toolbar gains the existing redraft `Customize` pattern with a new `setup_dynasty.html` partial; a `/league-import` endpoint pre-fills the same knobs from Fantrax (`fxea` API) or ESPN public (`lm-api-reads` mSettings). Spec: `docs/superpowers/specs/2026-06-10-dynasty-league-customization-design.md`.

**Tech Stack:** Flask + Jinja + htmx (existing), `requests` for import fetchers, `unittest` (existing test style), fixture JSON for import parsers (no network in CI).

**Repo:** `C:\Users\Alex\Documents\Codex\2026-05-18\league-values` (run all commands from repo root). Run tests with `python -m pytest <file> -v`.

**Spec deviations locked in during planning (consistent with approved design):**
- The dynasty table gains a `$` column — dollars are currently CSV-only, and the budget knob must be visible to mean anything. Dynasty horizon only; prospects board unchanged.
- Rows below the roster cutoff are lumped into the LAST tier (not tier 0) so the existing `tiers.get(id, 0)` badge logic never renders "T0".
- Default settings (12 teams × 26 roster = 312 slots) put the cutoff past the 200-row display, so the divider only appears for shallower leagues. That is correct behavior, not a bug.

---

### Task 1: `LeagueSettings` — parse, clamp, summarize

**Files:**
- Create: `web/league_settings.py`
- Test: `tests/test_league_settings.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_league_settings.py
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from web.league_settings import LeagueSettings, parse_league_settings


class FakeArgs(dict):
    """Mimics request.args.get for the keys we read."""
    def get(self, key, default=None):
        return dict.get(self, key, default)


class TestParseLeagueSettings(unittest.TestCase):
    def test_defaults_when_absent(self):
        s = parse_league_settings(FakeArgs())
        self.assertEqual((s.teams, s.budget, s.roster, s.pslots), (12, 200, 26, 5))

    def test_parses_valid_values(self):
        s = parse_league_settings(FakeArgs(teams="16", budget="400", roster="30", pslots="10"))
        self.assertEqual((s.teams, s.budget, s.roster, s.pslots), (16, 400, 30, 10))

    def test_clamps_out_of_range(self):
        s = parse_league_settings(FakeArgs(teams="99", budget="5", roster="2", pslots="999"))
        self.assertEqual(s.teams, 20)    # max 20
        self.assertEqual(s.budget, 100)  # min 100
        self.assertEqual(s.roster, 10)   # min 10
        self.assertEqual(s.pslots, 20)   # max 20

    def test_garbage_falls_back_to_defaults(self):
        s = parse_league_settings(FakeArgs(teams="abc", budget="", roster="12.5x", pslots=None))
        self.assertEqual((s.teams, s.budget, s.roster, s.pslots), (12, 200, 26, 5))

    def test_roster_cutoff(self):
        s = parse_league_settings(FakeArgs(teams="10", roster="20"))
        self.assertEqual(s.roster_cutoff, 200)

    def test_prospect_cutoff(self):
        s = parse_league_settings(FakeArgs(teams="10", pslots="4"))
        self.assertEqual(s.prospect_cutoff, 40)

    def test_summary(self):
        s = LeagueSettings(teams=12, budget=200, roster=26, pslots=5)
        self.assertEqual(s.summary(), "12 teams · $200 · 26 roster · 5 prospect slots")

    def test_is_default(self):
        self.assertTrue(LeagueSettings(12, 200, 26, 5).is_default)
        self.assertFalse(LeagueSettings(10, 200, 26, 5).is_default)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_league_settings.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'web.league_settings'`

- [ ] **Step 3: Write the implementation**

```python
# web/league_settings.py
"""League settings for dynasty customization — parse, clamp, summarize.

Stateless by design: settings ride the URL as plain form params (teams, budget,
roster, pslots) exactly like every other board option. Invalid or absent values
fall back to defaults so a mangled URL can never 500 the board.
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_TEAMS = 12
DEFAULT_BUDGET = 200
DEFAULT_ROSTER = 26
DEFAULT_PSLOTS = 5

# (min, max) clamps per spec.
_BOUNDS = {
    "teams": (4, 20),
    "budget": (100, 1000),
    "roster": (10, 50),
    "pslots": (0, 20),
}


@dataclass(frozen=True)
class LeagueSettings:
    teams: int = DEFAULT_TEAMS
    budget: int = DEFAULT_BUDGET
    roster: int = DEFAULT_ROSTER
    pslots: int = DEFAULT_PSLOTS

    @property
    def roster_cutoff(self) -> int:
        """Total rostered players league-wide = the replacement-level rank."""
        return self.teams * self.roster

    @property
    def prospect_cutoff(self) -> int:
        """Total prospect slots league-wide (prospects-board divider only)."""
        return self.teams * self.pslots

    @property
    def total_budget(self) -> int:
        return self.teams * self.budget

    @property
    def is_default(self) -> bool:
        return (self.teams, self.budget, self.roster, self.pslots) == (
            DEFAULT_TEAMS, DEFAULT_BUDGET, DEFAULT_ROSTER, DEFAULT_PSLOTS)

    def summary(self) -> str:
        return (f"{self.teams} teams · ${self.budget} · "
                f"{self.roster} roster · {self.pslots} prospect slots")


def _clamp_int(raw, field: str, default: int) -> int:
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        return default
    lo, hi = _BOUNDS[field]
    return max(lo, min(hi, value))


def parse_league_settings(args) -> LeagueSettings:
    """Parse request args into LeagueSettings. Garbage -> defaults, extremes -> clamped."""
    return LeagueSettings(
        teams=_clamp_int(args.get("teams"), "teams", DEFAULT_TEAMS),
        budget=_clamp_int(args.get("budget"), "budget", DEFAULT_BUDGET),
        roster=_clamp_int(args.get("roster"), "roster", DEFAULT_ROSTER),
        pslots=_clamp_int(args.get("pslots"), "pslots", DEFAULT_PSLOTS),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_league_settings.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add web/league_settings.py tests/test_league_settings.py
git commit -m "feat: LeagueSettings parse/clamp for dynasty customization"
```

---

### Task 2: Replacement-adjusted dollar math + settings-aware tiers

**Files:**
- Modify: `app.py` — `_compute_dynasty_dollars` (lines ~161-173), `_dynasty_metadata` (~242-247)
- Test: `tests/test_dynasty_customization.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_dynasty_customization.py
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from app import _compute_dynasty_dollars, _compute_dynasty_tiers
from web.dynasty_models import DynastyRankingRow
from web.league_settings import LeagueSettings


def _row(i, value):
    return DynastyRankingRow(
        id=f"p{i}", name=f"Player {i}", player_type="mlb", positions=("OF",),
        team="NYY", age=27, dynasty_rank=i, dynasty_value=value,
        status="mlb", mlbam_id=None,
    )


class TestDynastyDollars(unittest.TestCase):
    def setUp(self):
        # 10 players, values 100, 90, ..., 10
        self.rows = [_row(i + 1, 100 - 10 * i) for i in range(10)]

    def test_budget_conserved(self):
        # 2 teams x 3 roster = 6 rostered; total budget 2 x 100 = 200
        s = LeagueSettings(teams=2, budget=100, roster=3, pslots=0)
        dollars = _compute_dynasty_dollars(self.rows, s)
        rostered = [dollars[f"p{i}"] for i in range(1, 7)]
        self.assertAlmostEqual(sum(rostered), 200.0, delta=0.5)

    def test_below_cutoff_is_zero(self):
        s = LeagueSettings(teams=2, budget=100, roster=3, pslots=0)
        dollars = _compute_dynasty_dollars(self.rows, s)
        for i in range(7, 11):
            self.assertEqual(dollars[f"p{i}"], 0.0)

    def test_rostered_minimum_one_dollar(self):
        s = LeagueSettings(teams=2, budget=100, roster=3, pslots=0)
        dollars = _compute_dynasty_dollars(self.rows, s)
        # p6 (value 50) sits AT the cutoff: value - replacement = 0, floor kicks in
        self.assertEqual(dollars["p6"], 1.0)

    def test_hand_computed_top_player(self):
        # replacement value = value at rank 6 = 50.
        # surplus: p1..p5 = 50,40,30,20,10 (sum 150). Budget above the $1 floors
        # = 200 - 6 = 194. p1 = 1 + 50/150 * 194 = 65.67
        s = LeagueSettings(teams=2, budget=100, roster=3, pslots=0)
        dollars = _compute_dynasty_dollars(self.rows, s)
        self.assertAlmostEqual(dollars["p1"], 65.7, delta=0.1)

    def test_league_size_moves_dollars(self):
        small = _compute_dynasty_dollars(self.rows, LeagueSettings(2, 100, 3, 0))
        deep = _compute_dynasty_dollars(self.rows, LeagueSettings(2, 100, 5, 0))
        # Deeper league -> lower replacement -> top player worth MORE surplus share
        self.assertNotAlmostEqual(small["p1"], deep["p1"], delta=0.5)

    def test_cutoff_beyond_pool_all_rostered(self):
        s = LeagueSettings(teams=12, budget=200, roster=26, pslots=0)  # cutoff 312 > 10 rows
        dollars = _compute_dynasty_dollars(self.rows, s)
        self.assertTrue(all(dollars[f"p{i}"] >= 1.0 for i in range(1, 11)))
        self.assertAlmostEqual(sum(dollars.values()), 12 * 200, delta=1.0)

    def test_unsorted_input_handled(self):
        s = LeagueSettings(teams=2, budget=100, roster=3, pslots=0)
        expected = _compute_dynasty_dollars(self.rows, s)
        shuffled = list(reversed(self.rows))
        self.assertEqual(_compute_dynasty_dollars(shuffled, s), expected)


class TestTierPool(unittest.TestCase):
    def test_below_cutoff_rows_get_last_tier_not_zero(self):
        rows = [_row(i + 1, 150 - i) for i in range(30)]
        s = LeagueSettings(teams=2, budget=100, roster=10, pslots=0)  # cutoff 20
        from app import _dynasty_tiers_for
        tiers = _dynasty_tiers_for(rows, s)
        max_tier = max(tiers.values())
        for i in range(21, 31):
            self.assertEqual(tiers[f"p{i}"], max_tier)
        self.assertNotIn(0, tiers.values())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dynasty_customization.py -v`
Expected: FAIL — `_compute_dynasty_dollars` takes `num_teams=`/`budget=` kwargs, not a settings object; `_dynasty_tiers_for` doesn't exist.

- [ ] **Step 3: Replace the dollar function and add the tier wrapper in `app.py`**

Replace `_compute_dynasty_dollars` (currently lines 161-173) with:

```python
def _compute_dynasty_dollars(rows, settings):
    """Replacement-adjusted auction dollars for a league shaped by `settings`.

    Rostered pool = top (teams x roster) by dynasty value. Replacement value =
    the value at the cutoff rank. Every rostered player gets a $1 floor; the
    remaining budget is split proportionally to value ABOVE replacement.
    Below the cutoff = $0. Total payout == teams x budget (the league's cash).
    """
    ordered = sorted(rows, key=lambda r: r.dynasty_value, reverse=True)
    cutoff = min(settings.roster_cutoff, len(ordered))
    rostered, bench = ordered[:cutoff], ordered[cutoff:]
    dollars = {r.id: 0.0 for r in bench}
    if not rostered:
        return dollars
    replacement = rostered[-1].dynasty_value
    surplus = {r.id: max(0.0, r.dynasty_value - replacement) for r in rostered}
    total_surplus = sum(surplus.values())
    spendable = settings.total_budget - len(rostered)  # $1 floor reserved each
    for r in rostered:
        share = (surplus[r.id] / total_surplus * spendable) if total_surplus > 0 else 0.0
        dollars[r.id] = round(1.0 + max(0.0, share), 1)
    return dollars
```

Immediately after `_gap_tiers` (after line ~239), add:

```python
def _dynasty_tiers_for(rows, settings):
    """Tiers over the rostered pool; below-cutoff rows are lumped into the LAST
    tier (never 0 — the template renders tier badges and 'T0' is nonsense)."""
    ordered = sorted(rows, key=lambda r: r.dynasty_value, reverse=True)
    cutoff = min(settings.roster_cutoff, len(ordered))
    pool, bench = ordered[:cutoff], ordered[cutoff:]
    tiers = _compute_dynasty_tiers(pool)
    last = max(tiers.values()) if tiers else 1
    for r in bench:
        tiers[r.id] = last
    return tiers
```

Replace `_dynasty_metadata` (currently lines 242-247) with:

```python
def _dynasty_metadata(settings):
    """Dynasty $ and tiers computed on the FULL DD universe shaped by league
    settings, so they don't change when the displayed rows are filtered."""
    all_rows = sorted(dd_store.get_all(), key=lambda r: r.dynasty_value, reverse=True)
    return _compute_dynasty_dollars(all_rows, settings), _dynasty_tiers_for(all_rows, settings)
```

Add the import near the other `web.` imports at the top of `app.py`:

```python
from web.league_settings import parse_league_settings
```

NOTE: this breaks the three existing `_dynasty_metadata()` call sites (index ~641, rankings ~674, export ~880, and `_build_dynasty_context` ~266) until Task 3 wires settings through. Fix them in THIS task minimally so the suite stays green: change each bare call to `_dynasty_metadata(parse_league_settings(request.args))`, and in `_build_dynasty_context` to `_dynasty_metadata(parse_league_settings(args))`.

- [ ] **Step 4: Run new tests + the full app test file**

Run: `python -m pytest tests/test_dynasty_customization.py tests/test_app.py -v`
Expected: all pass. If any existing test asserted old proportional dollar values in CSV export, update its expectation to the replacement-adjusted output (check `tests/test_app.py` export tests).

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_dynasty_customization.py tests/test_app.py
git commit -m "feat: replacement-adjusted dynasty dollars + settings-aware tiers"
```

---

### Task 3: Wire settings through routes + context

**Files:**
- Modify: `app.py` — `_build_dynasty_context` (~259-281), index route prospects branch (~633-645), rankings route (~655-691), export dynasty branch (~870-906)
- Test: extend `tests/test_dynasty_customization.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_dynasty_customization.py`)

```python
from app import app as flask_app


class TestDynastyRoutes(unittest.TestCase):
    def setUp(self):
        self.client = flask_app.test_client()
        flask_app.config["TESTING"] = True

    def test_dynasty_config_summary_reflects_params(self):
        r = self.client.get("/?mode=dd_dynasty&teams=10&budget=300&roster=20&pslots=4")
        self.assertEqual(r.status_code, 200)
        self.assertIn("10 teams · $300 · 20 roster · 4 prospect slots",
                      r.data.decode("utf-8"))

    def test_dynasty_default_summary(self):
        r = self.client.get("/?mode=dd_dynasty")
        self.assertIn("12 teams · $200 · 26 roster · 5 prospect slots",
                      r.data.decode("utf-8"))

    def test_dynasty_no_longer_promises_customization(self):
        r = self.client.get("/?mode=dd_dynasty")
        self.assertNotIn(b"League customization is coming", r.data)

    def test_rankings_partial_carries_settings(self):
        r = self.client.get("/rankings?mode=dd_dynasty&teams=8&budget=260&roster=25&pslots=3")
        self.assertEqual(r.status_code, 200)

    def test_export_carries_settings(self):
        r = self.client.get("/export?mode=dd_dynasty&teams=8&budget=100&roster=12")
        self.assertEqual(r.status_code, 200)
        # shallow league -> below-cutoff players export $0; header row intact
        self.assertIn(b"valucast-dynasty-rankings.csv",
                      r.headers["Content-Disposition"].encode())

    def test_cutoff_divider_renders_when_visible(self):
        # 4x10=40 slots: divider must appear inside the top-200 board
        r = self.client.get("/?mode=dd_dynasty&teams=4&roster=10")
        self.assertIn(b"cutoff-row", r.data)

    def test_cutoff_divider_absent_when_beyond_display(self):
        r = self.client.get("/?mode=dd_dynasty")  # 312 > 200 shown
        self.assertNotIn(b"cutoff-row", r.data)
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `python -m pytest tests/test_dynasty_customization.py -v`
Expected: the `TestDynastyRoutes` tests FAIL (summary/divider not implemented); earlier classes still pass.

- [ ] **Step 3: Update `_build_dynasty_context`**

Replace the body so settings are parsed once and exposed to templates:

```python
def _build_dynasty_context(args):
    """Build template context for DD Dynasty mode. Bypasses engine entirely."""
    pool = args.get("pool", "")
    position = args.get("position", "")
    search = args.get("search", "")
    settings = parse_league_settings(args)
    rows = dd_store.filter(pool=pool or None, position=position or None, search=search or None)
    rows = rows[:200]
    dynasty_dollars, tiers = _dynasty_metadata(settings)
    risk_assessments = {row.id: risk_model.evaluate_dynasty(row) for row in rows}
    return {
        "mode": "dd_dynasty",
        "pool": pool,
        "position": position,
        "search": search,
        "dd_rows": rows,
        "dynasty_dollars": dynasty_dollars,
        "tiers": tiers,
        "risk_assessments": risk_assessments,
        "dd_available": dd_store.is_available,
        "dd_generated_at": dd_store.generated_at,
        "as_of": store.as_of,
        "horizon": "dynasty",
        "league_settings": settings,
        "config_summary": settings.summary(),
        "cutoff_rank": settings.roster_cutoff,
    }
```

- [ ] **Step 4: Update the prospects branches and export**

In BOTH the index route prospects branch (~line 633) and the rankings route prospects branch (~line 666), after `ctx["dd_rows"] = rows` the existing line `ctx["dynasty_dollars"], _ = _dynasty_metadata(...)` already passes settings from Task 2's minimal fix — now also set the prospects cutoff:

```python
            settings = parse_league_settings(request.args)
            ctx["dynasty_dollars"], _ = _dynasty_metadata(settings)
            ctx["tiers"] = _prospect_tiers()
            ctx["cutoff_rank"] = settings.prospect_cutoff
```

In the export dynasty branch (~line 870), the Task 2 minimal fix already parses settings; no further change needed beyond confirming the dollars dict comes from `_dynasty_metadata(parse_league_settings(request.args))`.

- [ ] **Step 5: Add the divider + $ column to `templates/partials/rankings_table_dynasty.html`**

Add a `$` header after the Dynasty Value column (dynasty mode only) — after line 14:

```html
            {% if mode == 'dd_dynasty' %}
            <th class="col-dollar sortable" aria-sort="none"><button type="button" class="sort-btn" onclick="sortTable(6)">$</button></th>
            {% endif %}
```

CAREFUL: adding a column shifts the Risk/Range `sortTable()` indices and the detail-row `colspan`. In dynasty mode Risk becomes index 7; make the indices conditional:

```html
            <th class="col-risk sortable" aria-sort="none"><button type="button" class="sort-btn" onclick="sortTable({{ 7 if mode == 'dd_dynasty' else 6 }})">Risk</button></th>
```

and change the detail row to `colspan="{{ 9 if mode == 'dd_dynasty' else 8 }}"`.

Add the $ cell after the `col-value` td (line ~49):

```html
            {% if mode == 'dd_dynasty' %}
            <td class="col-dollar">{% set d = dynasty_dollars.get(row.id, 0) %}{% if d and d > 0 %}${{ "%.0f" | format(d) }}{% else %}$0{% endif %}</td>
            {% endif %}
```

Add the divider inside the row loop, immediately before `<tr class="player-row ...`:

```html
        {% set this_rank = row.prospect_rank if mode == 'prospects' else row.dynasty_rank %}
        {% set prev_rank = (dd_rows[loop.index0 - 1].prospect_rank if mode == 'prospects' else dd_rows[loop.index0 - 1].dynasty_rank) if loop.index0 > 0 else 0 %}
        {% if cutoff_rank and this_rank and prev_rank and prev_rank <= cutoff_rank < this_rank %}
        <tr class="cutoff-row"><td colspan="{{ 9 if mode == 'dd_dynasty' else 8 }}">&asymp; replacement level in your league ({{ cutoff_rank }} rostered)</td></tr>
        {% endif %}
```

(`prev_rank and` guards the first row — no divider above rank 1.)

- [ ] **Step 6: Replace the dynasty toolbar summary in `templates/index.html`**

Change line 94 from the hardcoded "League customization is coming." sentence to:

```html
        <span class="config-summary">{{ config_summary }}{% if dd_generated_at %} · Updated {{ dd_generated_at[:10] }}{% endif %}</span>
```

- [ ] **Step 7: Add minimal CSS for the new elements** (append to `static/style.css`)

```css
/* Dynasty league customization */
.cutoff-row td {
    text-align: center;
    font-size: 0.8rem;
    color: var(--text-muted, #6b7280);
    border-top: 2px dashed #9ca3af;
    border-bottom: 2px dashed #9ca3af;
    padding: 0.35rem;
    background: rgba(156, 163, 175, 0.08);
}
```

Check how the mobile card layout handles `col-risk`/`col-value` (search `style.css` for `col-risk` inside the mobile `@media` block) and give `col-dollar` the SAME treatment — the 6/10 mobile-card regression came from `col-*` rules losing specificity battles; mirror an existing column's selectors exactly rather than inventing new ones.

- [ ] **Step 8: Run tests, then grep the smoke check**

Run: `python -m pytest tests/test_dynasty_customization.py tests/test_app.py -v`
Expected: all pass.

Run: `grep -n "customization" scripts/smoke_check.py`
Expected: no hits (the smoke check must not assert the old "coming" sentence). If it does, update it.

- [ ] **Step 9: Commit**

```bash
git add app.py templates/partials/rankings_table_dynasty.html templates/index.html static/style.css tests/test_dynasty_customization.py
git commit -m "feat: dynasty board responds to league settings ($ column, cutoff divider, live summary)"
```

---

### Task 4: Dynasty Customize panel (UI)

**Files:**
- Create: `templates/partials/setup_dynasty.html`
- Modify: `templates/index.html` (dynasty toolbar, ~lines 92-110), `templates/partials/rankings_response.html`
- Test: extend `tests/test_dynasty_customization.py`

- [ ] **Step 1: Write the failing tests** (append to `TestDynastyRoutes`)

```python
    def test_dynasty_has_customize_button_and_panel(self):
        r = self.client.get("/?mode=dd_dynasty")
        self.assertIn(b"customize-toggle", r.data)
        self.assertIn(b"setup-panel collapsed", r.data)
        for name in (b'name="teams"', b'name="budget"', b'name="roster"', b'name="pslots"'):
            self.assertIn(name, r.data)

    def test_dynasty_panel_inputs_carry_current_values(self):
        r = self.client.get("/?mode=dd_dynasty&teams=14&budget=500")
        self.assertIn(b'name="teams"', r.data)
        self.assertIn(b'value="14"', r.data)
        self.assertIn(b'value="500"', r.data)

    def test_dynasty_hidden_mode_input_still_present(self):
        # Guard against the 6/10 P0: form requests MUST carry mode on non-redraft
        r = self.client.get("/?mode=dd_dynasty")
        self.assertIn(b'<input type="hidden" name="mode" value="dd_dynasty">', r.data)

    def test_rankings_oob_swaps_dynasty_panel(self):
        r = self.client.get("/rankings?mode=dd_dynasty&teams=10")
        self.assertIn(b'hx-swap-oob="innerHTML:#setup-panel"', r.data)
        self.assertIn(b'hx-swap-oob="innerHTML:.config-summary"', r.data)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_dynasty_customization.py -v`
Expected: the four new tests FAIL.

- [ ] **Step 3: Create `templates/partials/setup_dynasty.html`**

```html
<div class="league-knobs">
    <label class="knob">
        <span>Teams</span>
        <input type="number" name="teams" value="{{ league_settings.teams }}" min="4" max="20" step="1">
    </label>
    <label class="knob">
        <span>Budget ($)</span>
        <input type="number" name="budget" value="{{ league_settings.budget }}" min="100" max="1000" step="10">
    </label>
    <label class="knob">
        <span>Roster slots</span>
        <input type="number" name="roster" value="{{ league_settings.roster }}" min="10" max="50" step="1">
    </label>
    <label class="knob">
        <span>Prospect slots</span>
        <input type="number" name="pslots" value="{{ league_settings.pslots }}" min="0" max="20" step="1">
    </label>
</div>

<div class="league-import">
    <input type="url" name="league_url" id="league-url-input" class="league-url-input"
           placeholder="Paste your Fantrax or ESPN league URL to import settings"
           value="" hx-trigger="none">
    <button type="button" class="import-btn"
            hx-get="/league-import"
            hx-include="closest form"
            hx-target="#setup-panel"
            hx-swap="innerHTML">Import settings</button>
    {% if import_notice %}
    <p class="import-notice">{{ import_notice }}</p>
    {% endif %}
</div>
```

(Notes: the URL input lives inside the main form, so typing in it fires a debounced `/rankings` request that simply ignores `league_url` — harmless, accepted in design. The Import button is `type="button"` so it never submits the form.)

- [ ] **Step 4: Add the toolbar button + panel to the dynasty branch of `templates/index.html`**

In the dynasty toolbar (after the Export CSV link, line ~109), add:

```html
        <button type="button" class="customize-toggle" onclick="toggleSetup()">Customize</button>
```

Remove `rank-toolbar-locked` from the dynasty toolbar div class (it is no longer locked); KEEP it on the prospects toolbar.

Immediately after the dynasty toolbar's closing `</div>` add:

```html
    <section id="setup-panel" class="setup-panel collapsed">
        {% include "partials/setup_dynasty.html" %}
    </section>
```

- [ ] **Step 5: OOB-swap the dynasty panel + summary in `templates/partials/rankings_response.html`**

The dynasty/prospects branch (lines 3-4) currently swaps only the table. Change the file's dynasty branch to:

```html
{% if mode == 'dd_dynasty' or mode == 'prospects' %}
{% include "partials/rankings_table_dynasty.html" %}
{% if mode == 'dd_dynasty' %}
<span class="config-summary" hx-swap-oob="innerHTML:.config-summary">{{ config_summary }}{% if dd_generated_at %} · Updated {{ dd_generated_at[:10] }}{% endif %}</span>
<section id="setup-panel" class="setup-panel" hx-swap-oob="innerHTML:#setup-panel">
    {% include "partials/setup_dynasty.html" %}
</section>
{% endif %}
{% else %}
```

(Prospects keeps its static summary and has no panel — the OOB targets wouldn't exist on that page.)

- [ ] **Step 6: Panel CSS** (append to `static/style.css`)

```css
.league-knobs {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem 1.25rem;
    margin-bottom: 0.75rem;
}
.league-knobs .knob {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    font-size: 0.8rem;
}
.league-knobs .knob input {
    width: 6rem;
    padding: 0.3rem 0.4rem;
}
.league-import {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: center;
}
.league-url-input {
    flex: 1 1 16rem;
    min-width: 0;
    padding: 0.35rem 0.5rem;
}
.import-notice {
    flex-basis: 100%;
    font-size: 0.8rem;
    margin: 0.25rem 0 0;
}
```

- [ ] **Step 7: Run tests + visual check both viewports**

Run: `python -m pytest tests/test_dynasty_customization.py tests/test_app.py -v`
Expected: all pass.

Then boot the app (`python app.py`, port 5000) and verify by hand at desktop width AND 420px (mobile is the #1 recurring pain point): panel opens/closes, knob changes re-render the board (watch the summary + $ column change), cutoff divider appears with `teams=4&roster=10`.

- [ ] **Step 8: Commit**

```bash
git add templates/partials/setup_dynasty.html templates/index.html templates/partials/rankings_response.html static/style.css tests/test_dynasty_customization.py
git commit -m "feat: dynasty Customize panel with league knobs"
```

---

### Task 5: League import module (Fantrax + ESPN parsers, no network)

**Files:**
- Create: `web/league_import.py`
- Create: `tests/fixtures/fantrax_league_info.json`, `tests/fixtures/espn_msettings.json`
- Test: `tests/test_league_import.py`

- [ ] **Step 1: Create the fixtures** (these DEFINE the parser contract; shaped after the real APIs)

`tests/fixtures/fantrax_league_info.json`:

```json
{
    "leagueName": "Test Dynasty League",
    "sport": "MLB",
    "teamInfo": {
        "t1": {"name": "Team A"}, "t2": {"name": "Team B"},
        "t3": {"name": "Team C"}, "t4": {"name": "Team D"},
        "t5": {"name": "Team E"}, "t6": {"name": "Team F"},
        "t7": {"name": "Team G"}, "t8": {"name": "Team H"},
        "t9": {"name": "Team I"}, "t10": {"name": "Team J"}
    },
    "rosterInfo": {
        "maxTotalPlayers": 30,
        "positionConstraints": {}
    }
}
```

`tests/fixtures/espn_msettings.json`:

```json
{
    "id": 12345,
    "settings": {
        "name": "Test ESPN League",
        "size": 14,
        "rosterSettings": {
            "lineupSlotCounts": {"0": 1, "1": 1, "2": 1, "3": 1, "4": 1,
                                  "5": 3, "12": 1, "13": 7, "16": 3, "17": 2}
        },
        "draftSettings": {"auctionBudget": 260}
    }
}
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_league_import.py
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from web.league_import import (
    detect_platform, parse_fantrax, parse_espn, ImportError_, import_league,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestDetectPlatform(unittest.TestCase):
    def test_fantrax_league_url(self):
        url = "https://www.fantrax.com/fantasy/league/abc123xyz/standings"
        self.assertEqual(detect_platform(url), ("fantrax", "abc123xyz"))

    def test_fantrax_no_trailing_path(self):
        url = "https://www.fantrax.com/fantasy/league/abc123xyz"
        self.assertEqual(detect_platform(url), ("fantrax", "abc123xyz"))

    def test_espn_url(self):
        url = "https://fantasy.espn.com/baseball/league?leagueId=12345"
        self.assertEqual(detect_platform(url), ("espn", "12345"))

    def test_espn_url_with_extra_params(self):
        url = "https://fantasy.espn.com/baseball/team?leagueId=12345&teamId=3&seasonId=2026"
        self.assertEqual(detect_platform(url), ("espn", "12345"))

    def test_garbage_returns_none(self):
        for url in ("not a url", "https://football.fantasysports.yahoo.com/f1/123",
                    "https://www.fantrax.com/home", ""):
            self.assertIsNone(detect_platform(url), url)


class TestParsers(unittest.TestCase):
    def test_parse_fantrax(self):
        data = json.loads((FIXTURES / "fantrax_league_info.json").read_text())
        result = parse_fantrax(data)
        self.assertEqual(result["teams"], 10)
        self.assertEqual(result["roster"], 30)
        self.assertNotIn("budget", result)   # fxea doesn't expose it -> keep default

    def test_parse_espn(self):
        data = json.loads((FIXTURES / "espn_msettings.json").read_text())
        result = parse_espn(data)
        self.assertEqual(result["teams"], 14)
        self.assertEqual(result["roster"], 21)   # sum of lineupSlotCounts
        self.assertEqual(result["budget"], 260)

    def test_parse_fantrax_missing_fields(self):
        result = parse_fantrax({"leagueName": "x"})
        self.assertEqual(result, {})   # nothing readable -> empty partial

    def test_parse_espn_zero_budget_omitted(self):
        data = json.loads((FIXTURES / "espn_msettings.json").read_text())
        data["settings"]["draftSettings"]["auctionBudget"] = 0
        self.assertNotIn("budget", parse_espn(data))


class TestImportLeague(unittest.TestCase):
    def test_unsupported_url_raises(self):
        with self.assertRaises(ImportError_):
            import_league("https://example.com/nope")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run to verify failure**

Run: `python -m pytest tests/test_league_import.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 4: Write `web/league_import.py`**

```python
"""League settings import from Fantrax / ESPN public leagues.

Self-contained seam by design: this module + the /league-import route are the
ONLY import surface, so a future paid gate wraps one route. Nothing fetched is
stored server-side. Hard 5s timeout per request — Render's 30s ceiling must
never be near.

Parsers are tolerant: any field we can't read is simply omitted from the
returned partial dict and the caller keeps its current/default value.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import requests

FETCH_TIMEOUT = 5  # seconds

_FANTRAX_RE = re.compile(r"fantrax\.com/fantasy/league/([A-Za-z0-9]+)")
_FANTRAX_API = "https://www.fantrax.com/fxea/general/getLeagueInfo"
_ESPN_API = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/"
             "seasons/2026/segments/0/leagues/{league_id}?view=mSettings")


class ImportError_(Exception):
    """User-facing import failure; .args[0] is the inline notice text."""


def detect_platform(url: str) -> tuple[str, str] | None:
    """Return (platform, league_id) or None if the URL isn't recognized."""
    if not url:
        return None
    m = _FANTRAX_RE.search(url)
    if m:
        return ("fantrax", m.group(1))
    parsed = urlparse(url)
    if "espn.com" in parsed.netloc and "/baseball/" in parsed.path:
        league_id = parse_qs(parsed.query).get("leagueId", [None])[0]
        if league_id and league_id.isdigit():
            return ("espn", league_id)
    return None


def parse_fantrax(data: dict) -> dict:
    """Extract a settings partial from a fxea getLeagueInfo response."""
    partial = {}
    team_info = data.get("teamInfo")
    if isinstance(team_info, dict) and team_info:
        partial["teams"] = len(team_info)
    roster_info = data.get("rosterInfo") or {}
    max_players = roster_info.get("maxTotalPlayers")
    if isinstance(max_players, int) and max_players > 0:
        partial["roster"] = max_players
    return partial


def parse_espn(data: dict) -> dict:
    """Extract a settings partial from an ESPN mSettings response."""
    partial = {}
    settings = data.get("settings") or {}
    size = settings.get("size")
    if isinstance(size, int) and size > 0:
        partial["teams"] = size
    slot_counts = (settings.get("rosterSettings") or {}).get("lineupSlotCounts") or {}
    total_slots = sum(v for v in slot_counts.values() if isinstance(v, int) and v > 0)
    if total_slots > 0:
        partial["roster"] = total_slots
    budget = (settings.get("draftSettings") or {}).get("auctionBudget")
    if isinstance(budget, int) and budget > 0:
        partial["budget"] = budget
    return partial


def _fetch_json(url: str, params: dict | None = None) -> dict:
    try:
        resp = requests.get(url, params=params, timeout=FETCH_TIMEOUT,
                            headers={"User-Agent": "ValuCast/1.0 league-import"})
    except requests.RequestException:
        raise ImportError_("Couldn't reach the league host — try again, or enter settings manually.")
    if resp.status_code in (401, 403):
        raise ImportError_("This league is private — enter settings manually.")
    if resp.status_code != 200:
        raise ImportError_(f"League lookup failed (HTTP {resp.status_code}) — enter settings manually.")
    try:
        return resp.json()
    except ValueError:
        raise ImportError_("Unexpected response from the league host — enter settings manually.")


def import_league(url: str) -> tuple[dict, str]:
    """Detect + fetch + parse. Returns (settings_partial, notice).

    Raises ImportError_ with a user-facing message on any failure.
    """
    detected = detect_platform(url)
    if detected is None:
        raise ImportError_("Unsupported URL — paste a Fantrax league URL or an "
                           "ESPN baseball league URL (Yahoo isn't supported yet).")
    platform, league_id = detected
    if platform == "fantrax":
        data = _fetch_json(_FANTRAX_API, params={"leagueId": league_id})
        partial = parse_fantrax(data)
    else:
        data = _fetch_json(_ESPN_API.format(league_id=league_id))
        partial = parse_espn(data)
    if not partial:
        raise ImportError_("Found the league but couldn't read its settings — enter them manually.")
    imported = ", ".join(sorted(partial))
    missing = sorted({"teams", "budget", "roster", "pslots"} - set(partial))
    notice = f"Imported {imported} from {platform.title()}."
    if missing:
        notice += f" Couldn't read {', '.join(missing)} — kept your current values."
    return partial, notice
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_league_import.py -v`
Expected: all pass (no network is touched — only `detect_platform`/parsers/`import_league`-with-bad-URL are exercised).

Confirm `requests` is already a dependency: `grep -i requests requirements.txt` — expected present (the scraper uses it). If absent, add `requests` to `requirements.txt` in this commit.

- [ ] **Step 6: Commit**

```bash
git add web/league_import.py tests/test_league_import.py tests/fixtures/fantrax_league_info.json tests/fixtures/espn_msettings.json
git commit -m "feat: Fantrax/ESPN league settings import module (fixture-tested, no network in CI)"
```

---

### Task 6: `/league-import` route

**Files:**
- Modify: `app.py` (add route after the `/rankings` route), `templates/partials/setup_dynasty.html` (refresh script)
- Test: extend `tests/test_dynasty_customization.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_dynasty_customization.py`)

```python
from unittest.mock import patch


class TestLeagueImportRoute(unittest.TestCase):
    def setUp(self):
        self.client = flask_app.test_client()
        flask_app.config["TESTING"] = True

    def test_import_success_fills_knobs(self):
        with patch("app.import_league", return_value=({"teams": 10, "roster": 30},
                                                      "Imported roster, teams from Fantrax.")):
            r = self.client.get("/league-import?league_url=https://www.fantrax.com/fantasy/league/abc/home&teams=12&budget=350&roster=26&pslots=5")
        self.assertEqual(r.status_code, 200)
        body = r.data.decode("utf-8")
        self.assertIn('name="teams"', body)
        self.assertIn('value="10"', body)      # imported
        self.assertIn('value="30"', body)      # imported
        self.assertIn('value="350"', body)     # NOT imported -> user's current value kept
        self.assertIn("Imported roster, teams", body)
        self.assertIn("league-setup-refresh", body)  # triggers board re-render

    def test_import_failure_keeps_knobs_and_notices(self):
        from web.league_import import ImportError_
        with patch("app.import_league", side_effect=ImportError_("This league is private — enter settings manually.")):
            r = self.client.get("/league-import?league_url=https://fantasy.espn.com/baseball/league?leagueId=1&teams=14")
        self.assertEqual(r.status_code, 200)
        body = r.data.decode("utf-8")
        self.assertIn('value="14"', body)      # untouched
        self.assertIn("league is private", body)
        self.assertNotIn("league-setup-refresh", body)  # no refresh on failure

    def test_import_empty_url(self):
        r = self.client.get("/league-import?teams=12")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Unsupported URL", r.data)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_dynasty_customization.py::TestLeagueImportRoute -v`
Expected: FAIL — 404 (route doesn't exist).

- [ ] **Step 3: Add the route to `app.py`** (after the `/rankings` route; add `from web.league_import import import_league, ImportError_` to the imports)

```python
@app.route("/league-import")
def league_import():
    """Fill the dynasty setup knobs from a league URL. Self-contained seam —
    a future paid gate wraps exactly this route. Always returns the panel
    fragment (200): failures become an inline notice, knobs untouched."""
    current = parse_league_settings(request.args)
    url = (request.args.get("league_url") or "").strip()
    try:
        partial, notice = import_league(url)
        merged = {
            "teams": partial.get("teams", current.teams),
            "budget": partial.get("budget", current.budget),
            "roster": partial.get("roster", current.roster),
            "pslots": partial.get("pslots", current.pslots),
        }
        settings = parse_league_settings(merged)  # clamp imported values too
        refresh = True
    except ImportError_ as exc:
        settings, notice, refresh = current, str(exc), False
    return render_template(
        "partials/setup_dynasty.html",
        league_settings=settings, import_notice=notice, import_refresh=refresh,
    )
```

(`parse_league_settings(merged)` works because `merged` is a plain dict and the
parser only calls `.get()` — same duck type as request args.)

- [ ] **Step 4: Add the refresh script to `templates/partials/setup_dynasty.html`** (at the end of the file)

```html
{% if import_refresh %}
<script class="league-setup-refresh">
/* htmx executes scripts in swapped fragments. Programmatic input swaps don't
   fire 'change', so kick the form once to re-render the board with the
   imported settings. */
document.getElementById('league-setup').dispatchEvent(new Event('change', { bubbles: true }));
</script>
{% endif %}
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_dynasty_customization.py tests/test_app.py -v`
Expected: all pass.

- [ ] **Step 6: One manual live-fire check (not in CI)**

Boot the app and paste a real public ESPN league URL and a real Fantrax league URL into the panel; confirm knobs fill and the board re-renders. If a real-world response shape differs from the fixture, update the FIXTURE to match reality first, then the parser, keeping tests green.

- [ ] **Step 7: Commit**

```bash
git add app.py templates/partials/setup_dynasty.html tests/test_dynasty_customization.py
git commit -m "feat: /league-import endpoint fills dynasty knobs from Fantrax/ESPN"
```

---

### Task 7: localStorage persistence

**Files:**
- Modify: `templates/index.html` (script block, after `toggleSetup`, ~line 163)
- Test: extend `tests/test_dynasty_customization.py` (server-side render check only — JS behavior is verified manually)

- [ ] **Step 1: Add the persistence script to `templates/index.html`** (inside the existing `<script>` block, after `toggleSetup`)

```javascript
// Dynasty league settings persistence: save on change, reapply on bare landings.
// URL params always win — only a landing with NO settings params reads storage.
(function () {
    var KEYS = ['teams', 'budget', 'roster', 'pslots'];
    var form = document.getElementById('league-setup');
    var isDynasty = {{ 'true' if horizon == 'dynasty' else 'false' }};
    if (!form || !isDynasty || !window.localStorage) return;

    var urlHasSettings = KEYS.some(function (k) {
        return new URLSearchParams(window.location.search).has(k);
    });

    if (!urlHasSettings) {
        var saved = null;
        try { saved = JSON.parse(localStorage.getItem('vc-league-settings')); } catch (e) {}
        if (saved) {
            var applied = false;
            KEYS.forEach(function (k) {
                var input = form.querySelector('[name="' + k + '"]');
                if (input && saved[k] != null && String(saved[k]) !== input.value) {
                    input.value = saved[k];
                    applied = true;
                }
            });
            if (applied) form.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }

    form.addEventListener('change', function () {
        var out = {};
        KEYS.forEach(function (k) {
            var input = form.querySelector('[name="' + k + '"]');
            if (input) out[k] = input.value;
        });
        try { localStorage.setItem('vc-league-settings', JSON.stringify(out)); } catch (e) {}
    });
})();
```

- [ ] **Step 2: Add a render test** (append to `TestDynastyRoutes`)

```python
    def test_persistence_script_renders_on_dynasty_only(self):
        dyn = self.client.get("/?mode=dd_dynasty")
        red = self.client.get("/")
        self.assertIn(b"vc-league-settings", dyn.data)
        # Script ships on all pages but self-disables off-dynasty via isDynasty flag
        self.assertIn(b"var isDynasty = false", red.data)
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_dynasty_customization.py -v`
Expected: all pass.

- [ ] **Step 4: Manual verification**

Boot the app: set `teams=8` on Dynasty, navigate away to Redraft, return to bare `/?mode=dd_dynasty` — knobs should restore to 8 and the board re-render. Confirm a URL WITH `teams=14` beats storage. Confirm redraft is untouched.

- [ ] **Step 5: Commit**

```bash
git add templates/index.html tests/test_dynasty_customization.py
git commit -m "feat: dynasty league settings persist via localStorage"
```

---

### Task 8: Full verification sweep

**Files:** none new — verification only.

- [ ] **Step 1: Full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: 675 pre-existing tests + all new ones green, zero failures.

- [ ] **Step 2: Hidden-mode regression check (the 6/10 P0)**

Run: `python -m pytest tests/test_dynasty_customization.py -k "hidden_mode" -v` and manually click a dynasty player row with the panel open — the detail card must render (not 404/redraft swap).

- [ ] **Step 3: Mobile pass at 420px**

Panel knobs wrap cleanly, import input doesn't overflow, $ column renders in the card layout (or is cleanly hidden if the card treats it like other col-* extras), cutoff divider readable. Mobile is the #1 recurring UI pain point — do not skip.

- [ ] **Step 4: Smoke check still passes locally**

Run: `python scripts/smoke_check.py http://127.0.0.1:5000 $(git rev-parse HEAD)` against a locally running app (adjust invocation to match the script's usage if it differs — read its `--help`/docstring first).

- [ ] **Step 5: Final commit if any fixups, then report**

Stage explicit paths only (parallel-session discipline). Do NOT push — Alex pushes ValuCast deploys deliberately (production auto-deploys from master and launch is Friday 6/12).
```

---

## Execution notes

- **Do not push to origin without Alex's explicit go-ahead** — pushing master deploys to valucast.app and launch is Friday 6/12.
- `_qa/`, `_shots*.py`, `HANDOFF.md` are untracked local tooling — never stage them.
- If any existing test asserts old proportional dollar CSV values, update expectations in Task 2 (the math change is the approved spec).
