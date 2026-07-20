# Competitive Distribution and Comps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship discoverable farm graphics, deeper organization reports, transparent hitter component comps, and role-separated pitcher shape comps without affecting any ValuCast decision output.

**Architecture:** Extend the existing offline `prospects.comps` artifact rather than create a second runtime system. Extend the existing team-board context rather than build a farm dashboard service. All public routes read committed artifacts and existing contexts; only one-time history fetchers use the network.

**Tech Stack:** Python 3.11, Flask/Jinja, Pillow, stdlib JSON/urllib, pytest.

## Global Constraints

- Display-only: no comp or farm-summary field may feed rank, value, caps, Role Watch, or publication decisions.
- No similarity percentages or pitcher outcome probabilities.
- Pitcher history covers MLB seasons 2000–2025 and is committed for offline runtime use.
- Pitcher matches are starter-to-starter or reliever-to-reliever; ambiguous current roles are suppressed.
- No new dependency and no deployment.
- Preserve the model freeze and failed decay flag.

---

### Task 1: Hitter component matches

**Files:**
- Modify: `prospects/comps.py`
- Test: `tests/test_prospect_comps.py`

**Interfaces:**
- Consumes: existing `CompPool`, `SHAPE_KEYS`, and translated `{k_pct, bb_pct, iso}`.
- Produces: `player["components"]` keyed by `power`, `contact`, and `approach`.

- [ ] **Step 1: Write the failing component test**

```python
def test_hitter_components_use_single_transparent_axes_and_distance():
    pool = CompPool(_filler_pool(2025))
    comp = comp_for_target(pool, {"k_pct": 20.0, "bb_pct": 9.0, "iso": 0.180})
    assert comp["components"]["power"]["metric"] == "ISO"
    assert comp["components"]["contact"]["metric"] == "K%"
    assert comp["components"]["approach"]["metric"] == "BB%"
    assert all("distance" in item for item in comp["components"].values())
    assert all("match_pct" not in item for item in comp["components"].values())
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/test_prospect_comps.py::test_hitter_components_use_single_transparent_axes_and_distance`

Expected: `KeyError: 'components'`.

- [ ] **Step 3: Add the minimal component matcher**

```python
COMPONENT_AXES = {
    "power": ("Power", "iso", "ISO"),
    "contact": ("Contact", "k_pct", "K%"),
    "approach": ("Approach", "bb_pct", "BB%"),
}

def _component_matches(pool: CompPool, target: tuple, translated: dict) -> dict:
    matches = {}
    for slug, (label, key, metric) in COMPONENT_AXES.items():
        index = SHAPE_KEYS.index(key)
        row = min(pool.match_rows, key=lambda item: abs(target[index] - item["z"][index]))
        matches[slug] = {
            "label": label,
            "metric": metric,
            "target": round(float(translated[key]), 3 if key == "iso" else 1),
            "match": row["name"],
            "season": row["season"],
            "value": round(row["rates"][key], 3 if key == "iso" else 1),
            "distance": round(abs(target[index] - row["z"][index]), 3),
        }
    return matches
```

Add `"components": _component_matches(pool, target, translated)` to `comp_for_target()`.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest -q tests/test_prospect_comps.py`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add prospects/comps.py tests/test_prospect_comps.py
git commit -m "Add transparent hitter component comps"
```

---

### Task 2: Offline pitcher history and role-separated matching

**Files:**
- Create: `scripts/fetch_mlb_history_pitching_seasons.py`
- Create: `data/mlb/mlb_history_pitching_seasons.json`
- Modify: `prospects/comps.py`
- Modify: `scripts/build_prospect_comps.py`
- Test: `tests/test_prospect_comps.py`

**Interfaces:**
- Consumes: MLB StatsAPI only in the one-time fetch script; snapshot translated pitcher rates and `components.factual_current_context` in the offline builder.
- Produces: a separate top-level `pitchers` map in `valucast_prospect_comps.json` with `role_pool`, `target`, and `twins`; the existing hitter `players` map remains backward-compatible and two-way players cannot overwrite either role.

- [ ] **Step 1: Write failing role and coverage tests**

```python
def test_pitcher_role_classification_suppresses_mixed_usage():
    assert pitcher_target_role({"starter_role": True, "games_started": 5, "sample": 50}) == "starter"
    assert pitcher_target_role({"starter_role": False, "games_started": 0, "sample": 30}) == "reliever"
    assert pitcher_target_role({"starter_role": True, "games_started": 3, "sample": 45}) is None
    assert pitcher_target_role({"starter_role": False, "games_started": 2, "sample": 40}) is None

def test_pitcher_matches_never_cross_role_or_publish_probabilities():
    rows = []
    for season in range(2000, 2026):
        for index in range(4):
            rows.extend([
                {"id": season * 100 + index, "name": f"Starter {season}-{index}",
                 "season": season, "age": 24, "ip": 100 + index, "g": 20,
                 "gs": 20, "bf": 420, "k": 100 + index * 5, "bb": 30 + index},
                {"id": season * 100 + 50 + index, "name": f"Reliever {season}-{index}",
                 "season": season, "age": 24, "ip": 50 + index, "g": 50,
                 "gs": 0, "bf": 220, "k": 60 + index * 5, "bb": 18 + index},
            ])
    pool = PitcherCompPool(rows)
    comp = pitcher_comp_for_target(pool, "starter", {"k_bb_pct": 20.0, "k_per_9": 10.5, "bb_per_9": 2.7})
    assert comp["role_pool"] == "starter"
    assert {row["role"] for row in comp["twins"]} == {"starter"}
    assert "cohort" not in comp
    assert "probability" not in json.dumps(comp).lower()
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/test_prospect_comps.py -k pitcher`

Expected: import failures for `PitcherCompPool`, `pitcher_comp_for_target`, and `pitcher_target_role`.

- [ ] **Step 3: Add the one-time fetcher**

Implement a stdlib `urllib.request` script parallel to `fetch_mlb_history_seasons.py`. For each season in `range(2000, 2026)`, request:

```python
url = (
    f"{BASE}/stats?stats=season&group=pitching&season={season}"
    "&sportId=1&playerPool=All&limit=5000"
)
```

Persist compact rows containing `id`, `name`, `season`, `age`, `ip`, `g`, `gs`, `bf`, `k`, and `bb`. Write atomically to `data/mlb/mlb_history_pitching_seasons.json` with `seasons: [2000, 2025]`.

- [ ] **Step 4: Add the offline pitcher pool**

In `prospects/comps.py`, add:

```python
PITCHER_HISTORY_PATH = ROOT / "data" / "mlb" / "mlb_history_pitching_seasons.json"
PITCHER_SHAPE_KEYS = ("k_bb_pct", "k_per_9", "bb_per_9")

def pitcher_target_role(context: dict) -> str | None:
    starts = context.get("games_started")
    sample = context.get("sample")
    if context.get("starter_role") is True and starts is not None and starts >= 5:
        return "starter"
    if context.get("starter_role") is False and starts == 0 and sample is not None and sample >= 30:
        return "reliever"
    return None
```

`PitcherCompPool` must classify historical starter seasons at `GS/G >= .50` with `IP >= 50`, reliever seasons at `GS/G <= .10` with `IP >= 30`, exclude the middle, z-score the three rates within `(season, role)`, and expose `coverage_ready` only when every season 2000–2025 is present and both match pools contain at least 100 young-player seasons.

`pitcher_comp_for_target()` returns the three nearest unique-player seasons within the requested role, including raw metrics and Euclidean z-distance. It returns `None` when `coverage_ready` is false.

- [ ] **Step 5: Extend builder eligibility**

Require `player_type == "prospect"`, translated `role == "pitcher"`, `confidence == "high"`, `low_sample == false`, all three translated metrics, and a non-ambiguous `pitcher_target_role()` result. Pass the optional pitcher-history payload into `build_prospect_comps()` and write eligible results to a new top-level `pitchers` map while leaving the existing hitter `players` schema unchanged.

- [ ] **Step 6: Verify GREEN with fixtures**

Run: `python -m pytest -q tests/test_prospect_comps.py`

Expected: all tests pass without network access.

- [ ] **Step 7: Fetch and validate the committed history**

Run:

```powershell
python scripts/fetch_mlb_history_pitching_seasons.py
python scripts/build_prospect_comps.py
python -m pytest -q tests/test_prospect_comps.py
```

Expected: history reports seasons `2000–2025`; builder reports nonzero pitcher coverage or an explicit suppressed count by gate; tests pass.

- [ ] **Step 8: Commit**

```powershell
git add scripts/fetch_mlb_history_pitching_seasons.py data/mlb/mlb_history_pitching_seasons.json prospects/comps.py scripts/build_prospect_comps.py tests/test_prospect_comps.py data/models/valucast_prospect_comps.json
git commit -m "Build role-separated pitcher shape comps"
```

---

### Task 3: Player-card and share-card comp parity

**Files:**
- Modify: `templates/partials/player_detail_dynasty.html`
- Modify: `app.py`
- Modify: `templates/methodology.html`
- Test: `tests/test_prospect_comps.py`
- Test: `tests/test_player_card_display_additions.py`

**Interfaces:**
- Consumes: hitter or pitcher entry from `valucast_prospect_comps.json`.
- Produces: honest page and PNG sections with the same matches and distances.

- [ ] **Step 1: Write failing display tests**

```python
assert "Power — ISO" in hitter_html
assert "Contact — K%" in hitter_html
assert "Approach — BB%" in hitter_html
assert "measured distance" in hitter_html
assert "match percentage" not in hitter_html.lower()
assert "Pitcher Shape Comps" in pitcher_html
assert "starter pool" in pitcher_html
assert "success probability" not in pitcher_html.lower()
assert "The forecast is the model's role probabilities" not in hitter_html
assert "Peak Outlook is a separate qualitative scenario layer" in hitter_html
```

Add a PNG parity assertion by monkeypatching `_share_card_comp_lines()` input and checking that each component or pitcher twin name appears in its returned lines.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/test_prospect_comps.py tests/test_player_card_display_additions.py -k 'component or pitcher_shape or disclosure'`

Expected: missing component/pitcher copy assertions fail.

- [ ] **Step 3: Render the two explicit variants**

In the Jinja comp block, branch on `shape_comps.player_type`. Hitter mode retains overall twins/outcomes and adds three component rows. Pitcher mode shows `Pitcher Shape Comps`, the current-usage role pool, translated metrics, three matched seasons, and measured distances; it renders no outcome bars.

Change the stale hitter disclosure to:

```html
Peak Outlook is a separate qualitative scenario layer. Shape matches are descriptive, not a forecast, and do not feed ValuCast Value or rank.
```

Extend `_share_card_comp_lines()` to return a list of compact strings and size the existing comp panel from the list length. Reuse `_graphic_fit_text`; do not create another renderer.

- [ ] **Step 4: Update methodology**

Document the three hitter component axes, pitcher role filters, pitcher axes, measured distance, coverage suppression, and display-only policy.

- [ ] **Step 5: Verify GREEN**

Run: `python -m pytest -q tests/test_prospect_comps.py tests/test_player_card_display_additions.py tests/test_card_intelligence.py`

Expected: all tests and subtests pass.

- [ ] **Step 6: Commit**

```powershell
git add templates/partials/player_detail_dynasty.html templates/methodology.html app.py tests/test_prospect_comps.py tests/test_player_card_display_additions.py
git commit -m "Show transparent hitter and pitcher comps"
```

---

### Task 4: Organization intelligence summaries

**Files:**
- Modify: `app.py`
- Modify: `templates/backfields.html`
- Modify: `static/style.css`
- Test: `tests/test_backfields_page.py`

**Interfaces:**
- Consumes: `_team_board_prospect_rows()`, `_team_board_movements()`, and committed `valucast_prospect_buys.json`.
- Produces: `team_boards.summary`, `team_boards.risers`, and `team_boards.buys`.

- [ ] **Step 1: Write failing summary tests**

```python
rows = [_row(f"Player {index}", "MIL", prospect_rank=index, value=index) for index in range(1, 21)]
for index, row in enumerate(rows):
    row.level = ("R", "A", "A+", "AA", "AAA")[index % 5]
    row.positions = ("P",) if index % 4 == 0 else ("SS",)
    row.position = row.positions[0]
summary, risers = _team_board_system_summary(rows, {})
assert summary["top5_concentration_pct"] == round(100 * sum(range(1, 6)) / sum(range(1, 21)), 1)
assert sum(summary["levels"].values()) == 20
assert summary["top20_hitters"] + summary["top20_pitchers"] == 20
assert risers == []
```

Add a missing-artifact test that monkeypatches `_load_artifact` to return `None` for buys and asserts the team page remains 200 with `buys == []`.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/test_backfields_page.py -k 'summary or risers or buys'`

Expected: missing `summary`, `risers`, or `buys` keys.

- [ ] **Step 3: Add one shared summary helper**

Add `_team_board_system_summary(org_rows, movements)` returning the documented concentration, normalized level counts, top-20 hitter/pitcher counts, and top three positive movers. Determine pitcher rows from `row.role == "pitcher"` or pitcher-only positions; count every other row as hitter. Use zero concentration when top-20 value is zero.

Load the existing buy artifact once inside `_build_team_board_context()`, filter its `board` by canonical `team`, sort by integer `rank`, and shape at most three rows with player URLs. Missing or malformed data returns an empty list.

- [ ] **Step 4: Render the report**

Add a compact `System snapshot` above the organization table. Use native HTML lists/bars and existing Backfields classes where possible. Show `No current ValuCast buy` or `No positive mover in the current window` when the corresponding list is empty.

- [ ] **Step 5: Verify GREEN**

Run: `python -m pytest -q tests/test_backfields_page.py tests/test_public_surfaces_smoke.py`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add app.py templates/backfields.html static/style.css tests/test_backfields_page.py
git commit -m "Deepen organization farm reports"
```

---

### Task 5: Farm-system and organization share distribution

**Files:**
- Modify: `app.py`
- Modify: `templates/farms.html`
- Modify: `tests/test_backfields_page.py`
- Modify: `tests/test_public_surfaces_smoke.py`

**Interfaces:**
- Consumes: `_build_farm_rankings_context()` and the enriched `_build_team_board_context()`.
- Produces: `/farms/share-card`, `/farms/share-card.png`, expanded organization PNGs, and complete default entries on `/cards`.

- [ ] **Step 1: Write failing route and gallery tests**

```python
png = client.get("/farms/share-card.png")
assert png.status_code == 200
assert png.mimetype == "image/png"
assert Image.open(io.BytesIO(png.data)).size == (1080, 1350)
assert client.get("/farms/share-card").status_code == 200
assert b'href="/farms/share-card"' in client.get("/farms").data
cards = client.get("/cards").data
for title in (b"Farm-System Rankings", b"Dynasty Rankings", b"Redraft Rankings"):
    assert title in cards
```

Add an explicit hold test for Forward Ledger and a 503 test when farm systems are unavailable.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/test_backfields_page.py tests/test_public_surfaces_smoke.py -k 'farm_share or cards_gallery or forward_ledger'`

Expected: `/farms/share-card.png` is 404 and gallery titles are missing.

- [ ] **Step 3: Add the farm renderer and routes**

Render all systems in two columns using existing brand, font, glass-panel, editorial-date, and QR helpers. Rows use the context order and show only rank, organization, top-20 value, and top-100 count. Return 503 for an empty context. Build the preview route with `build_share_preview_html()`.

- [ ] **Step 4: Enrich the existing organization PNG**

Use `board["summary"]`, `board["risers"]`, and `board["buys"]` from the shared context. Keep the existing top-10/top-20 query behavior and fit the summary into the existing card rather than create a second team graphic.

- [ ] **Step 5: Complete `/cards` default coverage**

Add static entries for Farm-System Rankings, Dynasty Rankings, and Redraft Rankings. Add Forward Ledger only when `SCOREBOARD_HOLD` is false. Dynamic player, trade, and per-team cards remain discoverable from their own pages and are not duplicated in the gallery.

- [ ] **Step 6: Verify GREEN**

Run: `python -m pytest -q tests/test_backfields_page.py tests/test_public_surfaces_smoke.py tests/test_app.py -k 'share or cards or farm or backfields'`

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

```powershell
git add app.py templates/farms.html tests/test_backfields_page.py tests/test_public_surfaces_smoke.py
git commit -m "Complete farm share distribution"
```

---

### Task 6: Full verification

**Files:**
- Verify only

- [ ] **Step 1: Check scope and whitespace**

Run:

```powershell
git diff --check master...HEAD
git status -sb
```

Expected: no whitespace errors; only planned files and committed generated artifacts differ.

- [ ] **Step 2: Run the complete suite**

Run: `python -m pytest -q`

Expected: zero failures.

- [ ] **Step 3: Render smoke images**

Use the Flask test client to save one hitter card, one eligible pitcher card, `/farms/share-card.png`, and one organization top-20 PNG. Inspect all four images for clipping, unreadable type, incorrect labels, and page/share mismatch.

- [ ] **Step 4: Confirm model isolation**

Run:

```powershell
git diff --name-only master...HEAD | rg 'rank_v1|model|value|projection|role_tracker|quality_governor'
```

Expected: only the generated display artifact `data/models/valucast_prospect_comps.json` may match; no model or ranking implementation changed.
