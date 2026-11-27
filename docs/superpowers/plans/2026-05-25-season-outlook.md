# Season Outlook + Correctness Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Combine 2026 actual YTD stats (MLB Stats API) with Steamer ROS projections (FanGraphs) into season outlook rankings, and fix three correctness bugs (tiers, AgeCurve, H_ALLOWED).

**Architecture:** MLB actuals adapter normalizes stats to engine schema, FanGraphs fetcher switches to ROS endpoints, combiner joins by (mlbam_id, pool_family) and adds counting stats / recalculates rate stats. Output is a plain JSON array consumed by the existing web app unchanged. Three independent bug fixes are committed separately.

**Tech Stack:** Python 3.12, Flask, unittest, MLB Stats API, FanGraphs API

**Test runner:** `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`

---

### Task 1: Fix Tier Minimum Size

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`

- [ ] **Step 1: Write failing tests**

Add a new test class to `tests/test_app.py`:

```python
class TestComputeTiers(unittest.TestCase):
    def test_single_player_tier_merges_down(self):
        """If tier 1 has only 1 player, merge it into tier 2."""
        from app import _compute_tiers
        from league_values.models import PlayerProjection, ValuationResult

        # Create results with a big gap after player 1
        players = []
        values = [20.0, 10.0, 9.5, 9.0, 8.5, 8.0, 7.5, 7.0, 6.5, 6.0]
        for i, v in enumerate(values):
            proj = {"id": str(i), "name": f"P{i}", "pool": "hitter", "stats": {"HR": 10}}
            r = ValuationResult(
                player=PlayerProjection.from_dict(proj),
                total_value=v, raw_values={}, z_scores={}, category_values={},
            )
            players.append(r)

        tiers = _compute_tiers(players)
        # Player 0 (value=20) should NOT be alone in tier 1
        tier_counts = {}
        for pid, t in tiers.items():
            tier_counts[t] = tier_counts.get(t, 0) + 1
        for tier_num, count in tier_counts.items():
            self.assertGreaterEqual(count, 3, f"Tier {tier_num} has only {count} players")

    def test_all_same_value_single_tier(self):
        """If all players have the same value, one tier."""
        from app import _compute_tiers
        from league_values.models import PlayerProjection, ValuationResult

        players = []
        for i in range(10):
            proj = {"id": str(i), "name": f"P{i}", "pool": "hitter", "stats": {"HR": 10}}
            r = ValuationResult(
                player=PlayerProjection.from_dict(proj),
                total_value=5.0, raw_values={}, z_scores={}, category_values={},
            )
            players.append(r)

        tiers = _compute_tiers(players)
        unique_tiers = set(tiers.values())
        self.assertEqual(len(unique_tiers), 1)

    def test_fewer_than_three_players_ok(self):
        """With < 3 players, tiers are assigned without enforcement."""
        from app import _compute_tiers
        from league_values.models import PlayerProjection, ValuationResult

        players = []
        for i, v in enumerate([10.0, 5.0]):
            proj = {"id": str(i), "name": f"P{i}", "pool": "hitter", "stats": {"HR": 10}}
            r = ValuationResult(
                player=PlayerProjection.from_dict(proj),
                total_value=v, raw_values={}, z_scores={}, category_values={},
            )
            players.append(r)

        tiers = _compute_tiers(players)
        self.assertEqual(len(tiers), 2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest tests.test_app.TestComputeTiers -v`

- [ ] **Step 3: Update `_compute_tiers` in `app.py`**

Replace the existing `_compute_tiers` function (around line 132) with:

```python
def _compute_tiers(results: list[ValuationResult], num_tiers: int = 8) -> dict[str, int]:
    """Assign tier numbers (1 = best) based on value gaps between consecutive players.

    Finds the largest gaps in the value sequence and uses them as tier boundaries.
    Enforces invariant: no tier has fewer than 3 players (unless total < 3).
    """
    if len(results) < 2:
        return {r.player.id: 1 for r in results}

    # Compute gaps between consecutive players
    gaps = []
    for i in range(len(results) - 1):
        gap = results[i].total_value - results[i + 1].total_value
        gaps.append((gap, i))

    # Find the largest gaps to use as tier boundaries
    sorted_gaps = sorted(gaps, key=lambda x: x[0], reverse=True)
    break_indices = sorted([g[1] for g in sorted_gaps[:num_tiers - 1]])

    # Assign initial tier numbers
    tiers_list = []  # list of (player_id, tier_number)
    current_tier = 1
    for i, r in enumerate(results):
        tiers_list.append([r.player.id, current_tier])
        if i in break_indices:
            current_tier += 1

    # Enforce minimum tier size of 3 (iterative merge)
    if len(results) >= 3:
        changed = True
        while changed:
            changed = False
            # Count players per tier
            tier_counts: dict[int, int] = {}
            for _, t in tiers_list:
                tier_counts[t] = tier_counts.get(t, 0) + 1

            # Find first undersized tier
            for tier_num in sorted(tier_counts.keys()):
                if tier_counts[tier_num] < 3:
                    # Merge: tier 1 merges down (absorb tier 2), others merge up
                    if tier_num == min(tier_counts.keys()):
                        merge_target = tier_num + 1 if tier_num + 1 in tier_counts else tier_num
                    else:
                        merge_target = tier_num - 1
                    if merge_target != tier_num:
                        for entry in tiers_list:
                            if entry[1] == tier_num:
                                entry[1] = merge_target
                        changed = True
                        break

        # Renumber tiers to be contiguous starting from 1
        unique_tiers = sorted(set(t for _, t in tiers_list))
        remap = {old: new for new, old in enumerate(unique_tiers, 1)}
        for entry in tiers_list:
            entry[1] = remap[entry[1]]

    return {pid: t for pid, t in tiers_list}
```

- [ ] **Step 4: Run all tests**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add app.py tests/test_app.py
git commit -m "fix: enforce minimum tier size of 3 players"
```

---

### Task 2: Fix AgeCurve Pitcher Pool

**Files:**
- Modify: `src/league_values/post_processors.py`
- Modify: `tests/test_post_processors.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_post_processors.py`:

```python
class TestAgeCurvePitcherPool(unittest.TestCase):
    def test_starter_uses_pitcher_curve(self):
        """STARTER pool players should use pitcher curve, not hitter curve."""
        hitter_curve = {25: 1.1, 30: 1.0, 35: 0.8}
        pitcher_curve = {25: 1.05, 30: 1.0, 35: 0.7}
        ac = AgeCurve(hitter_curve, pitcher_curve)

        league = LeagueConfig(
            name="T", scoring_mode=ScoringMode.CATEGORIES,
            categories=(CategorySpec(id="K", label="K", pool=PlayerPool.PITCHER, stat="K"),),
        )
        proj = {"id": "sp1", "name": "Young SP", "pool": "starter",
                "stats": {"K": 200}, "metadata": {"age": 35}}
        results = ValuationEngine().value_players([proj], league)
        adjusted = ac.process(results, league)

        # With pitcher curve at age 35: 0.7 multiplier
        self.assertAlmostEqual(adjusted[0].total_value, results[0].total_value * 0.7, places=3)

    def test_reliever_uses_pitcher_curve(self):
        """RELIEVER pool players should use pitcher curve, not hitter curve."""
        hitter_curve = {25: 1.1, 30: 1.0, 35: 0.8}
        pitcher_curve = {25: 1.05, 30: 1.0, 35: 0.7}
        ac = AgeCurve(hitter_curve, pitcher_curve)

        league = LeagueConfig(
            name="T", scoring_mode=ScoringMode.CATEGORIES,
            categories=(CategorySpec(id="SV", label="SV", pool=PlayerPool.PITCHER, stat="SV"),),
        )
        proj = {"id": "rp1", "name": "Old RP", "pool": "reliever",
                "stats": {"SV": 30}, "metadata": {"age": 35}}
        results = ValuationEngine().value_players([proj], league)
        adjusted = ac.process(results, league)

        self.assertAlmostEqual(adjusted[0].total_value, results[0].total_value * 0.7, places=3)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest tests.test_post_processors.TestAgeCurvePitcherPool -v`
Expected: FAIL — starters and relievers get hitter curve (0.8) instead of pitcher curve (0.7)

- [ ] **Step 3: Fix AgeCurve in `src/league_values/post_processors.py`**

In `AgeCurve.process()`, change line 134 from:

```python
            curve = self.pitcher_curve if r.player.pool is PlayerPool.PITCHER else self.hitter_curve
```

To:

```python
            curve = self.pitcher_curve if r.player.pool in (PlayerPool.PITCHER, PlayerPool.STARTER, PlayerPool.RELIEVER) else self.hitter_curve
```

- [ ] **Step 4: Run all tests**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add src/league_values/post_processors.py tests/test_post_processors.py
git commit -m "fix: AgeCurve now applies pitcher curve to STARTER and RELIEVER pools"
```

---

### Task 3: Fix Pitcher H_ALLOWED Normalization in Blender

**Files:**
- Modify: `scraper/blend.py`
- Modify: `tests/test_blend.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_blend.py`:

```python
class TestPitcherHAllowed(unittest.TestCase):
    def test_pitcher_stats_have_h_allowed_not_h(self):
        """Pitcher stats should rename H to H_ALLOWED for WHIP calculation."""
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        for p in result:
            self.assertIn("H_ALLOWED", p["stats"], f"{p['name']} missing H_ALLOWED")
            self.assertNotIn("H", p["stats"], f"{p['name']} still has H (should be H_ALLOWED)")

    def test_h_allowed_value_correct(self):
        """H_ALLOWED value should match the original H value."""
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        closer = next(p for p in result if p["name"] == "Shutdown Closer")
        # Closer is single-source (Steamer only), H=40
        self.assertAlmostEqual(closer["stats"]["H_ALLOWED"], 40, places=0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest tests.test_blend.TestPitcherHAllowed -v`
Expected: FAIL — stats have `H` not `H_ALLOWED`

- [ ] **Step 3: Add H_ALLOWED rename in `scraper/blend.py`**

In `_finalize_pitcher_stats()` (around line 121), add the `H` → `H_ALLOWED` rename right after the existing `SO` → `K` rename:

```python
def _finalize_pitcher_stats(stats: dict) -> dict:
    """Rename SO→K, H→H_ALLOWED and add derived stats."""
    if "SO" in stats:
        stats["K"] = stats.pop("SO")
    if "H" in stats:
        stats["H_ALLOWED"] = stats.pop("H")
    stats["SV_HLD"] = _safe_float(stats.get("SV", 0)) + _safe_float(stats.get("HLD", 0))
    bb = _safe_float(stats.get("BB", 0))
    k = _safe_float(stats.get("K", 0))
    stats["K_BB"] = round(k / bb, 2) if bb > 0 else 0.0
    return stats
```

- [ ] **Step 4: Run all tests**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`

Note: This change may break tests that reference pitcher `H` stat. The existing test data in `tests/test_projection_store.py` already uses `H_ALLOWED` for pitchers, so those should pass. Check that `test_blend.py` tests still pass — the matched pitcher test checks `IP` and `K`, not `H`, so it should be fine.

- [ ] **Step 5: Regenerate `data/projections/current.json`**

The existing `current.json` has pitcher stats with `H` instead of `H_ALLOWED`. Run the refresh to regenerate with the fix:

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -c "from scraper.refresh import refresh; refresh(delay=1.0)"
```

Verify the output has `H_ALLOWED` for pitchers:

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && python -c "
import json
with open('data/projections/current.json') as f:
    data = json.load(f)
pitchers = [p for p in data if p['pool'] in ('starter', 'reliever')]
p = pitchers[0]
print(f'{p[\"name\"]}: H_ALLOWED={p[\"stats\"].get(\"H_ALLOWED\", \"MISSING\")}, H={p[\"stats\"].get(\"H\", \"GONE\")}')"
```

- [ ] **Step 6: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add scraper/blend.py tests/test_blend.py data/projections/current.json
git commit -m "fix: rename pitcher H to H_ALLOWED for correct WHIP calculation"
```

---

### Task 4: Switch FanGraphs to ROS Endpoints

**Files:**
- Modify: `scraper/fangraphs.py`
- Modify: `tests/test_fangraphs.py`

- [ ] **Step 1: Update `scraper/fangraphs.py`**

Replace `fetch_all()` to use Steamer ROS only (remove ZiPS, use `steamerr`):

```python
def fetch_all(delay: float = 1.0) -> dict[str, list[dict]]:
    sets = [
        ("steamer_hitters", "steamerr", "bat"),
        ("steamer_pitchers", "steamerr", "pit"),
    ]
    result = {}
    for i, (key, system, stats) in enumerate(sets):
        result[key] = fetch_projections(system, stats)
        if delay > 0 and i < len(sets) - 1:
            time.sleep(delay)
    return result
```

- [ ] **Step 2: Update `scraper/blend.py` to handle single-source gracefully**

The `blend_projections()` function currently passes `raw.get("zips_hitters", [])` etc. With ZiPS removed, the blend functions already handle empty second source (they pass through single-source players). No code change needed — just verify.

- [ ] **Step 3: Update tests**

In `tests/test_fangraphs.py`, if there are tests that reference ZiPS keys, update them. Read the file to check.

- [ ] **Step 4: Run all tests**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add scraper/fangraphs.py
git commit -m "feat: switch FanGraphs to Steamer ROS (steamerr) endpoints"
```

---

### Task 5: MLB Stats API Actuals Adapter

**Files:**
- Create: `scraper/mlb_actuals.py`
- Create: `tests/test_mlb_actuals.py`

- [ ] **Step 1: Write tests for the adapter**

Create `tests/test_mlb_actuals.py`:

```python
import unittest
from scraper.mlb_actuals import normalize_ip, normalize_hitter, normalize_pitcher, derive_qs_from_games


class TestNormalizeIP(unittest.TestCase):
    def test_whole_innings(self):
        self.assertAlmostEqual(normalize_ip(6.0), 6.0, places=4)

    def test_one_out(self):
        self.assertAlmostEqual(normalize_ip(4.1), 4.3333, places=3)

    def test_two_outs(self):
        self.assertAlmostEqual(normalize_ip(4.2), 4.6667, places=3)

    def test_zero(self):
        self.assertAlmostEqual(normalize_ip(0.0), 0.0, places=4)

    def test_string_input(self):
        self.assertAlmostEqual(normalize_ip(float("13.1")), 13.3333, places=3)


SAMPLE_MLB_HITTER = {
    "player": {"id": 592450, "fullName": "Aaron Judge"},
    "stat": {
        "plateAppearances": 241, "atBats": 198, "hits": 50,
        "homeRuns": 17, "runs": 41, "rbi": 32,
        "stolenBases": 5, "caughtStealing": 1,
        "baseOnBalls": 39, "strikeOuts": 68,
        "hitByPitch": 2, "sacFlies": 0,
        "doubles": 9, "triples": 0,
        "gamesPlayed": 55, "intentionalWalks": 3,
    },
    "team": {"abbreviation": "NYY"},
}


class TestNormalizeHitter(unittest.TestCase):
    def test_basic_fields(self):
        result = normalize_hitter(SAMPLE_MLB_HITTER, "2026-05-25")
        self.assertEqual(result["name"], "Aaron Judge")
        self.assertEqual(result["pool"], "hitter")
        self.assertEqual(result["metadata"]["mlbam_id"], "592450")
        self.assertEqual(result["stats"]["PA"], 241)
        self.assertEqual(result["stats"]["HR"], 17)

    def test_singles_derived(self):
        result = normalize_hitter(SAMPLE_MLB_HITTER, "2026-05-25")
        # 1B = H - 2B - 3B - HR = 50 - 9 - 0 - 17 = 24
        self.assertEqual(result["stats"]["1B"], 24)

    def test_tb_derived(self):
        result = normalize_hitter(SAMPLE_MLB_HITTER, "2026-05-25")
        # TB = 24 + 2*9 + 3*0 + 4*17 = 24 + 18 + 0 + 68 = 110
        self.assertEqual(result["stats"]["TB"], 110)

    def test_nsb_derived(self):
        result = normalize_hitter(SAMPLE_MLB_HITTER, "2026-05-25")
        self.assertEqual(result["stats"]["NSB"], 4)  # 5 - 1

    def test_has_base_id(self):
        result = normalize_hitter(SAMPLE_MLB_HITTER, "2026-05-25")
        self.assertEqual(result["metadata"]["base_id"], "mlbam_592450")


SAMPLE_MLB_PITCHER = {
    "player": {"id": 669373, "fullName": "Tarik Skubal"},
    "stat": {
        "inningsPitched": "43.1", "earnedRuns": 13,
        "baseOnBalls": 8, "hits": 30, "strikeOuts": 45,
        "wins": 4, "losses": 1, "saves": 0, "holds": 0,
        "gamesStarted": 7, "gamesPitched": 7,
    },
    "team": {"abbreviation": "DET"},
}


class TestNormalizePitcher(unittest.TestCase):
    def test_basic_fields(self):
        result = normalize_pitcher(SAMPLE_MLB_PITCHER, qs=5, as_of="2026-05-25")
        self.assertEqual(result["name"], "Tarik Skubal")
        self.assertEqual(result["pool"], "starter")
        self.assertEqual(result["metadata"]["mlbam_id"], "669373")

    def test_ip_normalized(self):
        result = normalize_pitcher(SAMPLE_MLB_PITCHER, qs=5, as_of="2026-05-25")
        # 43.1 baseball = 43 + 1/3 = 43.333
        self.assertAlmostEqual(result["stats"]["IP"], 43.3333, places=3)

    def test_h_allowed_not_h(self):
        result = normalize_pitcher(SAMPLE_MLB_PITCHER, qs=5, as_of="2026-05-25")
        self.assertIn("H_ALLOWED", result["stats"])
        self.assertNotIn("H", result["stats"])
        self.assertEqual(result["stats"]["H_ALLOWED"], 30)

    def test_k_not_strikeouts(self):
        result = normalize_pitcher(SAMPLE_MLB_PITCHER, qs=5, as_of="2026-05-25")
        self.assertIn("K", result["stats"])
        self.assertEqual(result["stats"]["K"], 45)

    def test_qs_included(self):
        result = normalize_pitcher(SAMPLE_MLB_PITCHER, qs=5, as_of="2026-05-25")
        self.assertEqual(result["stats"]["QS"], 5)

    def test_sv_hld_derived(self):
        result = normalize_pitcher(SAMPLE_MLB_PITCHER, qs=5, as_of="2026-05-25")
        self.assertEqual(result["stats"]["SV_HLD"], 0)

    def test_reliever_pool_detection(self):
        rp_data = dict(SAMPLE_MLB_PITCHER)
        rp_data["stat"] = dict(SAMPLE_MLB_PITCHER["stat"])
        rp_data["stat"]["gamesStarted"] = 0
        rp_data["stat"]["saves"] = 20
        result = normalize_pitcher(rp_data, qs=0, as_of="2026-05-25")
        self.assertEqual(result["pool"], "reliever")


class TestDeriveQS(unittest.TestCase):
    def test_qs_count(self):
        games = [
            {"stat": {"gamesStarted": 1, "inningsPitched": "6.0", "earnedRuns": 2}},
            {"stat": {"gamesStarted": 1, "inningsPitched": "5.2", "earnedRuns": 1}},
            {"stat": {"gamesStarted": 1, "inningsPitched": "7.0", "earnedRuns": 4}},
            {"stat": {"gamesStarted": 0, "inningsPitched": "1.0", "earnedRuns": 0}},
        ]
        # Game 1: 6.0 IP, 2 ER → QS
        # Game 2: 5.2 = 5⅔ IP < 6.0 → not QS
        # Game 3: 7.0 IP, 4 ER > 3 → not QS
        # Game 4: relief appearance → skip
        self.assertEqual(derive_qs_from_games(games), 1)

    def test_empty_games(self):
        self.assertEqual(derive_qs_from_games([]), 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest tests.test_mlb_actuals -v`

- [ ] **Step 3: Implement `scraper/mlb_actuals.py`**

Create `scraper/mlb_actuals.py`:

```python
"""Fetch 2026 YTD actuals from MLB Stats API and normalize to engine schema."""
from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"
USER_AGENT = "Mozilla/5.0"


def normalize_ip(ip_baseball: float) -> float:
    """Convert baseball IP notation (4.2 = 4 and 2/3) to true decimal (4.667)."""
    whole = int(ip_baseball)
    outs = round((ip_baseball - whole) * 10)
    return whole + outs / 3


def normalize_hitter(entry: dict, as_of: str) -> dict:
    """Convert an MLB Stats API hitter record to engine schema."""
    player = entry["player"]
    s = entry["stat"]
    team = entry.get("team", {}).get("abbreviation", "")
    mlbam_id = str(player["id"])

    doubles = int(s.get("doubles", 0))
    triples = int(s.get("triples", 0))
    hr = int(s.get("homeRuns", 0))
    h = int(s.get("hits", 0))
    singles = h - doubles - triples - hr
    tb = singles + 2 * doubles + 3 * triples + 4 * hr
    sb = int(s.get("stolenBases", 0))
    cs = int(s.get("caughtStealing", 0))

    stats = {
        "PA": int(s.get("plateAppearances", 0)),
        "AB": int(s.get("atBats", 0)),
        "H": h, "HR": hr, "R": int(s.get("runs", 0)),
        "RBI": int(s.get("rbi", 0)),
        "SB": sb, "CS": cs,
        "BB": int(s.get("baseOnBalls", 0)),
        "SO": int(s.get("strikeOuts", 0)),
        "HBP": int(s.get("hitByPitch", 0)),
        "SF": int(s.get("sacFlies", 0)),
        "1B": singles, "2B": doubles, "3B": triples,
        "G": int(s.get("gamesPlayed", 0)),
        "TB": tb, "NSB": sb - cs,
    }

    # Rate stats from actuals
    ab = stats["AB"]
    pa_denom = stats["AB"] + stats["BB"] + stats["HBP"] + stats["SF"]
    stats["AVG"] = round(h / ab, 3) if ab > 0 else 0.0
    obp_num = h + stats["BB"] + stats["HBP"]
    stats["OBP"] = round(obp_num / pa_denom, 3) if pa_denom > 0 else 0.0
    stats["SLG"] = round(tb / ab, 3) if ab > 0 else 0.0
    stats["OPS"] = round(stats["OBP"] + stats["SLG"], 3)

    return {
        "id": f"mlbam_{mlbam_id}_H",
        "name": player["fullName"],
        "pool": "hitter",
        "positions": [],  # MLB API doesn't provide positions in stats endpoint
        "team": team,
        "stats": stats,
        "metadata": {
            "mlbam_id": mlbam_id,
            "base_id": f"mlbam_{mlbam_id}",
            "source": "mlb_stats_api",
            "as_of": as_of,
        },
    }


def normalize_pitcher(entry: dict, qs: int, as_of: str) -> dict:
    """Convert an MLB Stats API pitcher record to engine schema."""
    player = entry["player"]
    s = entry["stat"]
    team = entry.get("team", {}).get("abbreviation", "")
    mlbam_id = str(player["id"])

    ip = normalize_ip(float(s.get("inningsPitched", "0")))
    gs = int(s.get("gamesStarted", 0))
    sv = int(s.get("saves", 0))
    hld = int(s.get("holds", 0))
    k = int(s.get("strikeOuts", 0))
    bb = int(s.get("baseOnBalls", 0))
    er = int(s.get("earnedRuns", 0))
    h_allowed = int(s.get("hits", 0))

    pool = "starter" if gs > 0 else "reliever"
    positions = []
    if gs > 0:
        positions.append("SP")
    if sv > 0 or hld > 0 or gs == 0:
        positions.append("RP")
    if not positions:
        positions.append("SP")

    stats = {
        "IP": round(ip, 4), "ER": er, "BB": bb, "H_ALLOWED": h_allowed,
        "K": k, "W": int(s.get("wins", 0)), "L": int(s.get("losses", 0)),
        "SV": sv, "HLD": hld, "GS": gs,
        "G": int(s.get("gamesPitched", 0)),
        "QS": qs, "SV_HLD": sv + hld,
    }

    # Rate stats from actuals
    stats["ERA"] = round(9 * er / ip, 2) if ip > 0 else 0.0
    stats["WHIP"] = round((bb + h_allowed) / ip, 2) if ip > 0 else 0.0
    stats["K_BB"] = round(k / bb, 2) if bb > 0 else 0.0
    stats["K_9"] = round(9 * k / ip, 2) if ip > 0 else 0.0
    stats["BB_9"] = round(9 * bb / ip, 2) if ip > 0 else 0.0

    return {
        "id": f"mlbam_{mlbam_id}_P",
        "name": player["fullName"],
        "pool": pool,
        "positions": positions,
        "team": team,
        "stats": stats,
        "metadata": {
            "mlbam_id": mlbam_id,
            "base_id": f"mlbam_{mlbam_id}",
            "source": "mlb_stats_api",
            "as_of": as_of,
        },
    }


def derive_qs_from_games(games: list[dict]) -> int:
    """Count quality starts from game log entries."""
    qs = 0
    for game in games:
        s = game["stat"]
        if int(s.get("gamesStarted", 0)) == 0:
            continue
        ip = normalize_ip(float(s.get("inningsPitched", "0")))
        er = int(s.get("earnedRuns", 0))
        if ip >= 6.0 and er <= 3:
            qs += 1
    return qs


def _fetch_json(url: str) -> dict:
    """Fetch JSON from a URL."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_actuals(season: int = 2026) -> dict[str, list[dict]]:
    """Fetch 2026 YTD hitter and pitcher actuals from MLB Stats API.

    Returns {"hitters": [...], "pitchers": [...]} with raw API records.
    Raises on any fetch failure.
    """
    base = f"{MLB_API_BASE}/stats?stats=season&season={season}&sportId=1&limit=5000&playerPool=ALL"
    hitters = _fetch_json(f"{base}&group=hitting")["stats"][0]["splits"]
    pitchers = _fetch_json(f"{base}&group=pitching")["stats"][0]["splits"]
    return {"hitters": hitters, "pitchers": pitchers}


def fetch_qs(pitchers: list[dict], season: int = 2026) -> dict[str, int]:
    """Derive QS from game logs for all pitchers with starts.

    Returns {mlbam_id_str: qs_count}. Raises on any game log fetch failure.
    """
    qs_map: dict[str, int] = {}
    for p in pitchers:
        gs = int(p["stat"].get("gamesStarted", 0))
        mlbam_id = str(p["player"]["id"])
        if gs == 0:
            qs_map[mlbam_id] = 0
            continue
        url = f"{MLB_API_BASE}/people/{mlbam_id}/stats?stats=gameLog&group=pitching&season={season}&gameType=R"
        gl_data = _fetch_json(url)
        games = gl_data["stats"][0]["splits"]
        qs_map[mlbam_id] = derive_qs_from_games(games)
    return qs_map


def build_actuals(season: int = 2026, as_of: str = "") -> list[dict]:
    """Full pipeline: fetch actuals + QS, normalize, return player list."""
    if not as_of:
        from datetime import date
        as_of = date.today().isoformat()

    raw = fetch_actuals(season)
    qs_map = fetch_qs(raw["pitchers"], season)

    players = []
    for entry in raw["hitters"]:
        players.append(normalize_hitter(entry, as_of))
    for entry in raw["pitchers"]:
        mlbam_id = str(entry["player"]["id"])
        qs = qs_map.get(mlbam_id, 0)
        players.append(normalize_pitcher(entry, qs=qs, as_of=as_of))

    return players
```

- [ ] **Step 4: Run tests**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add scraper/mlb_actuals.py tests/test_mlb_actuals.py
git commit -m "feat: MLB Stats API actuals adapter with IP normalization and QS derivation"
```

---

### Task 6: Season Outlook Combiner

**Files:**
- Create: `scraper/combine.py`
- Create: `tests/test_combine.py`

- [ ] **Step 1: Write tests**

Create `tests/test_combine.py`:

```python
import unittest
from scraper.combine import combine_outlook, _pool_family


class TestPoolFamily(unittest.TestCase):
    def test_hitter(self):
        self.assertEqual(_pool_family("hitter"), "hitter")

    def test_starter(self):
        self.assertEqual(_pool_family("starter"), "pitcher")

    def test_reliever(self):
        self.assertEqual(_pool_family("reliever"), "pitcher")

    def test_pitcher(self):
        self.assertEqual(_pool_family("pitcher"), "pitcher")


ROS_HITTER = {
    "id": "15640", "name": "Aaron Judge", "pool": "hitter",
    "positions": ["RF", "DH"], "team": "NYY",
    "stats": {"PA": 450, "AB": 380, "H": 110, "HR": 28, "R": 75,
              "RBI": 80, "SB": 4, "CS": 1, "BB": 60, "SO": 100,
              "HBP": 3, "SF": 4, "1B": 60, "2B": 18, "3B": 0, "G": 100,
              "AVG": 0.289, "OBP": 0.400, "SLG": 0.570, "OPS": 0.970,
              "TB": 217, "NSB": 3},
    "metadata": {"fangraphs_id": "15640", "mlbam_id": "592450"},
}

ACTUAL_HITTER = {
    "id": "mlbam_592450_H", "name": "Aaron Judge", "pool": "hitter",
    "positions": [], "team": "NYY",
    "stats": {"PA": 241, "AB": 198, "H": 50, "HR": 17, "R": 41,
              "RBI": 32, "SB": 5, "CS": 1, "BB": 39, "SO": 68,
              "HBP": 2, "SF": 0, "1B": 24, "2B": 9, "3B": 0, "G": 55,
              "AVG": 0.253, "OBP": 0.381, "SLG": 0.556, "OPS": 0.937,
              "TB": 110, "NSB": 4},
    "metadata": {"mlbam_id": "592450", "base_id": "mlbam_592450",
                 "source": "mlb_stats_api", "as_of": "2026-05-25"},
}

ROS_PITCHER = {
    "id": "22267", "name": "Tarik Skubal", "pool": "starter",
    "positions": ["SP"], "team": "DET",
    "stats": {"IP": 97.29, "ER": 30, "BB": 20, "H_ALLOWED": 78, "K": 116,
              "W": 7, "L": 4, "SV": 0, "HLD": 0, "GS": 15, "G": 15,
              "QS": 10, "SV_HLD": 0,
              "ERA": 2.78, "WHIP": 1.01, "K_BB": 5.8, "K_9": 10.74, "BB_9": 1.85},
    "metadata": {"fangraphs_id": "22267", "mlbam_id": "669373"},
}

ACTUAL_PITCHER = {
    "id": "mlbam_669373_P", "name": "Tarik Skubal", "pool": "starter",
    "positions": ["SP"], "team": "DET",
    "stats": {"IP": 43.3333, "ER": 13, "BB": 8, "H_ALLOWED": 30, "K": 45,
              "W": 4, "L": 1, "SV": 0, "HLD": 0, "GS": 7, "G": 7,
              "QS": 5, "SV_HLD": 0,
              "ERA": 2.70, "WHIP": 0.88, "K_BB": 5.63, "K_9": 9.35, "BB_9": 1.66},
    "metadata": {"mlbam_id": "669373", "base_id": "mlbam_669373",
                 "source": "mlb_stats_api", "as_of": "2026-05-25"},
}


class TestCombineOutlook(unittest.TestCase):
    def test_hitter_counting_stats_add(self):
        result = combine_outlook([ROS_HITTER], [ACTUAL_HITTER])
        judge = next(p for p in result if p["name"] == "Aaron Judge")
        self.assertEqual(judge["stats"]["PA"], 241 + 450)
        self.assertEqual(judge["stats"]["HR"], 17 + 28)

    def test_hitter_rate_stats_recalculated(self):
        result = combine_outlook([ROS_HITTER], [ACTUAL_HITTER])
        judge = next(p for p in result if p["name"] == "Aaron Judge")
        total_h = 50 + 110
        total_ab = 198 + 380
        expected_avg = total_h / total_ab
        self.assertAlmostEqual(judge["stats"]["AVG"], expected_avg, places=3)

    def test_preserves_ros_id(self):
        result = combine_outlook([ROS_HITTER], [ACTUAL_HITTER])
        judge = next(p for p in result if p["name"] == "Aaron Judge")
        self.assertEqual(judge["id"], "15640")  # FanGraphs ID preserved

    def test_has_base_id(self):
        result = combine_outlook([ROS_HITTER], [ACTUAL_HITTER])
        judge = next(p for p in result if p["name"] == "Aaron Judge")
        self.assertEqual(judge["metadata"]["base_id"], "mlbam_592450")

    def test_pitcher_ip_adds(self):
        result = combine_outlook([ROS_PITCHER], [ACTUAL_PITCHER])
        skubal = next(p for p in result if p["name"] == "Tarik Skubal")
        self.assertAlmostEqual(skubal["stats"]["IP"], 43.3333 + 97.29, places=2)

    def test_pitcher_era_recalculated(self):
        result = combine_outlook([ROS_PITCHER], [ACTUAL_PITCHER])
        skubal = next(p for p in result if p["name"] == "Tarik Skubal")
        total_er = 13 + 30
        total_ip = 43.3333 + 97.29
        expected_era = 9 * total_er / total_ip
        self.assertAlmostEqual(skubal["stats"]["ERA"], expected_era, places=2)

    def test_ros_only_player_passes_through(self):
        ros_only = dict(ROS_HITTER)
        ros_only["id"] = "99999"
        ros_only["name"] = "ROS Only"
        ros_only["metadata"] = dict(ROS_HITTER["metadata"])
        ros_only["metadata"]["mlbam_id"] = "999999"
        result = combine_outlook([ROS_HITTER, ros_only], [ACTUAL_HITTER])
        names = [p["name"] for p in result]
        self.assertIn("ROS Only", names)

    def test_actuals_only_player_included(self):
        actuals_only = dict(ACTUAL_HITTER)
        actuals_only["id"] = "mlbam_111111_H"
        actuals_only["name"] = "Call Up"
        actuals_only["metadata"] = dict(ACTUAL_HITTER["metadata"])
        actuals_only["metadata"]["mlbam_id"] = "111111"
        actuals_only["metadata"]["base_id"] = "mlbam_111111"
        result = combine_outlook([ROS_HITTER], [ACTUAL_HITTER, actuals_only])
        callup = next(p for p in result if p["name"] == "Call Up")
        self.assertEqual(callup["metadata"]["has_ros"], False)

    def test_actuals_only_keeps_namespaced_id(self):
        actuals_only = dict(ACTUAL_HITTER)
        actuals_only["id"] = "mlbam_111111_H"
        actuals_only["name"] = "Call Up"
        actuals_only["metadata"] = dict(ACTUAL_HITTER["metadata"])
        actuals_only["metadata"]["mlbam_id"] = "111111"
        actuals_only["metadata"]["base_id"] = "mlbam_111111"
        result = combine_outlook([ROS_HITTER], [ACTUAL_HITTER, actuals_only])
        callup = next(p for p in result if p["name"] == "Call Up")
        self.assertEqual(callup["id"], "mlbam_111111_H")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest tests.test_combine -v`

- [ ] **Step 3: Implement `scraper/combine.py`**

Create `scraper/combine.py`:

```python
"""Combine YTD actuals with ROS projections into season outlook."""
from __future__ import annotations


HITTER_COUNTING = ("PA", "AB", "H", "HR", "R", "RBI", "SB", "CS", "BB", "SO",
                   "HBP", "SF", "1B", "2B", "3B", "G")
PITCHER_COUNTING = ("IP", "ER", "BB", "H_ALLOWED", "K", "W", "L", "SV", "HLD",
                    "GS", "G", "QS")


def _pool_family(pool: str) -> str:
    """Map pool string to 'hitter' or 'pitcher'."""
    if pool == "hitter":
        return "hitter"
    return "pitcher"


def _safe(stats: dict, key: str) -> float:
    return float(stats.get(key, 0) or 0)


def _combine_hitter(ros: dict, actual: dict) -> dict:
    """Combine a hitter's actuals + ROS into season outlook."""
    combined_stats = {}
    for stat in HITTER_COUNTING:
        combined_stats[stat] = _safe(actual["stats"], stat) + _safe(ros["stats"], stat)

    # TB and NSB derived
    combined_stats["TB"] = (combined_stats["1B"] + 2 * combined_stats["2B"]
                            + 3 * combined_stats["3B"] + 4 * combined_stats["HR"])
    combined_stats["NSB"] = combined_stats["SB"] - combined_stats["CS"]

    # Rate stats recalculated from components
    ab = combined_stats["AB"]
    h = combined_stats["H"]
    bb = combined_stats["BB"]
    hbp = combined_stats["HBP"]
    sf = combined_stats["SF"]
    tb = combined_stats["TB"]
    pa_denom = ab + bb + hbp + sf

    combined_stats["AVG"] = round(h / ab, 3) if ab > 0 else 0.0
    obp_num = h + bb + hbp
    combined_stats["OBP"] = round(obp_num / pa_denom, 3) if pa_denom > 0 else 0.0
    combined_stats["SLG"] = round(tb / ab, 3) if ab > 0 else 0.0
    combined_stats["OPS"] = round(combined_stats["OBP"] + combined_stats["SLG"], 3)

    # Use ROS record as base (has FanGraphs ID, positions, etc.)
    meta = dict(ros.get("metadata", {}))
    meta["base_id"] = f"mlbam_{meta.get('mlbam_id', '')}"
    meta["has_ros"] = True

    return {
        "id": ros["id"],
        "name": ros["name"],
        "pool": ros["pool"],
        "positions": ros.get("positions", []),
        "team": ros.get("team", ""),
        "stats": {k: round(v, 4) if isinstance(v, float) else int(v)
                  for k, v in combined_stats.items()},
        "metadata": meta,
    }


def _combine_pitcher(ros: dict, actual: dict) -> dict:
    """Combine a pitcher's actuals + ROS into season outlook."""
    combined_stats = {}
    for stat in PITCHER_COUNTING:
        combined_stats[stat] = _safe(actual["stats"], stat) + _safe(ros["stats"], stat)

    combined_stats["SV_HLD"] = combined_stats["SV"] + combined_stats["HLD"]

    # Rate stats recalculated from components
    ip = combined_stats["IP"]
    er = combined_stats["ER"]
    bb = combined_stats["BB"]
    h_allowed = combined_stats["H_ALLOWED"]
    k = combined_stats["K"]

    combined_stats["ERA"] = round(9 * er / ip, 2) if ip > 0 else 0.0
    combined_stats["WHIP"] = round((bb + h_allowed) / ip, 2) if ip > 0 else 0.0
    combined_stats["K_BB"] = round(k / bb, 2) if bb > 0 else 0.0
    combined_stats["K_9"] = round(9 * k / ip, 2) if ip > 0 else 0.0
    combined_stats["BB_9"] = round(9 * bb / ip, 2) if ip > 0 else 0.0

    meta = dict(ros.get("metadata", {}))
    meta["base_id"] = f"mlbam_{meta.get('mlbam_id', '')}"
    meta["has_ros"] = True

    return {
        "id": ros["id"],
        "name": ros["name"],
        "pool": ros["pool"],
        "positions": ros.get("positions", []),
        "team": ros.get("team", ""),
        "stats": {k_: round(v, 4) if isinstance(v, float) else int(v)
                  for k_, v in combined_stats.items()},
        "metadata": meta,
    }


def combine_outlook(ros_players: list[dict], actual_players: list[dict]) -> list[dict]:
    """Join actuals to ROS projections and produce season outlook.

    Join key: (mlbam_id, pool_family). Matched records combine stats.
    ROS-only records pass through. Actuals-only records included with has_ros=False.
    """
    # Index actuals by (mlbam_id, pool_family)
    actuals_by_key: dict[tuple[str, str], dict] = {}
    for p in actual_players:
        mlbam_id = p.get("metadata", {}).get("mlbam_id", "")
        if mlbam_id:
            key = (mlbam_id, _pool_family(p["pool"]))
            actuals_by_key[key] = p

    matched_actual_keys: set[tuple[str, str]] = set()
    outlook: list[dict] = []

    # Process each ROS player
    for ros in ros_players:
        mlbam_id = ros.get("metadata", {}).get("mlbam_id", "")
        if not mlbam_id:
            # No MLBAM ID — pass through ROS as-is
            meta = dict(ros.get("metadata", {}))
            meta["has_ros"] = True
            ros_copy = dict(ros)
            ros_copy["metadata"] = meta
            outlook.append(ros_copy)
            continue

        key = (mlbam_id, _pool_family(ros["pool"]))
        actual = actuals_by_key.get(key)

        if actual:
            matched_actual_keys.add(key)
            if _pool_family(ros["pool"]) == "hitter":
                outlook.append(_combine_hitter(ros, actual))
            else:
                outlook.append(_combine_pitcher(ros, actual))
        else:
            # ROS only — no actuals yet
            meta = dict(ros.get("metadata", {}))
            meta["base_id"] = f"mlbam_{mlbam_id}"
            meta["has_ros"] = True
            ros_copy = dict(ros)
            ros_copy["metadata"] = meta
            outlook.append(ros_copy)

    # Add actuals-only players (no ROS match)
    for key, actual in actuals_by_key.items():
        if key not in matched_actual_keys:
            meta = dict(actual.get("metadata", {}))
            meta["has_ros"] = False
            actual_copy = dict(actual)
            actual_copy["metadata"] = meta
            outlook.append(actual_copy)

    return outlook
```

- [ ] **Step 4: Run all tests**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add scraper/combine.py tests/test_combine.py
git commit -m "feat: season outlook combiner — joins actuals to ROS by (mlbam_id, pool_family)"
```

---

### Task 7: Update Refresh Pipeline

**Files:**
- Modify: `scraper/refresh.py`
- Modify: `tests/test_refresh.py`

- [ ] **Step 1: Read current `tests/test_refresh.py`**

Read the file to understand existing test patterns before modifying.

- [ ] **Step 2: Update `scraper/refresh.py`**

Replace the entire file:

```python
"""Orchestrator: fetch ROS projections + actuals, combine, write output."""
from __future__ import annotations

import json
import os
from datetime import date

from .fangraphs import fetch_all, save_raw
from .blend import blend_projections
from .mlb_actuals import build_actuals
from .combine import combine_outlook

_BASE = os.path.join(os.path.dirname(__file__), "..")
DEFAULT_OUTPUT = os.path.join(_BASE, "data", "projections", "current.json")
DEFAULT_ROS_OUTPUT = os.path.join(_BASE, "data", "projections", "ros.json")
DEFAULT_ACTUALS_OUTPUT = os.path.join(_BASE, "data", "actuals", "current.json")
DEFAULT_METADATA = os.path.join(_BASE, "data", "projections", "metadata.json")
DEFAULT_RAW_DIR = os.path.join(_BASE, "data", "projections", "raw")


def _write_json(data, path: str) -> None:
    """Write JSON via .tmp + os.replace for safer publish."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)


def refresh(
    output_path: str = DEFAULT_OUTPUT,
    ros_output_path: str = DEFAULT_ROS_OUTPUT,
    actuals_output_path: str = DEFAULT_ACTUALS_OUTPUT,
    metadata_path: str = DEFAULT_METADATA,
    raw_dir: str = DEFAULT_RAW_DIR,
    delay: float = 1.0,
    season: int = 2026,
) -> list[dict]:
    as_of = date.today().isoformat()

    # Step 1: Fetch and blend ROS projections
    print("Fetching ROS projections from FanGraphs...")
    raw = fetch_all(delay=delay)
    for key, players in raw.items():
        print(f"  {key}: {len(players)} players")
    save_raw(raw, raw_dir)

    print("Blending ROS projections...")
    ros_players = blend_projections(raw)
    print(f"  {len(ros_players)} ROS players")
    _write_json(ros_players, ros_output_path)

    # Step 2: Fetch actuals from MLB Stats API
    print("Fetching 2026 actuals from MLB Stats API...")
    actual_players = build_actuals(season=season, as_of=as_of)
    actual_hitters = sum(1 for p in actual_players if p["pool"] == "hitter")
    actual_pitchers = len(actual_players) - actual_hitters
    print(f"  {actual_hitters} hitters, {actual_pitchers} pitchers")
    _write_json(actual_players, actuals_output_path)

    # Step 3: Combine into season outlook
    print("Combining actuals + ROS into season outlook...")
    outlook = combine_outlook(ros_players, actual_players)
    ros_count_h = sum(1 for p in ros_players if p["pool"] == "hitter")
    ros_count_p = len(ros_players) - ros_count_h
    no_ros = sum(1 for p in outlook if not p.get("metadata", {}).get("has_ros", True))
    print(f"  {len(outlook)} outlook players ({no_ros} without ROS)")

    # Step 4: Staged publish — current.json first (load-bearing), metadata second
    _write_json(outlook, output_path)
    print(f"Written to {output_path}")

    metadata = {
        "as_of": as_of,
        "actuals_source": "mlb_stats_api",
        "ros_source": "fangraphs_steamer_ros",
        "actuals_hitters": actual_hitters,
        "actuals_pitchers": actual_pitchers,
        "ros_hitters": ros_count_h,
        "ros_pitchers": ros_count_p,
        "outlook_players": len(outlook),
        "players_without_ros": no_ros,
    }
    _write_json(metadata, metadata_path)
    print(f"Metadata written to {metadata_path}")

    return outlook


if __name__ == "__main__":
    refresh()
```

- [ ] **Step 3: Update tests if needed**

Check `tests/test_refresh.py` — if tests mock `fetch_all`, they may need to be updated for the new function signature and behavior.

- [ ] **Step 4: Run all tests**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add scraper/refresh.py
git commit -m "feat: refresh pipeline — ROS + actuals + combine with staged publish"
```

---

### Task 8: ProjectionStore Metadata + Web App Integration

**Files:**
- Modify: `web/projection_store.py`
- Modify: `templates/base.html`
- Modify: `templates/partials/rankings_table.html`
- Modify: `app.py`
- Modify: `tests/test_projection_store.py`
- Modify: `tests/test_app.py`

- [ ] **Step 1: Write tests for ProjectionStore metadata**

Add to `tests/test_projection_store.py`:

```python
class TestProjectionStoreMetadata(unittest.TestCase):
    def test_as_of_none_when_no_sidecar(self):
        """as_of should be None when metadata.json doesn't exist."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "current.json")
            with open(path, "w") as f:
                json.dump(SAMPLE_PLAYERS, f)
            store = ProjectionStore(path)
            self.assertIsNone(store.as_of)

    def test_as_of_loaded_from_sidecar(self):
        """as_of should load from metadata.json when present."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "current.json")
            meta_path = os.path.join(d, "metadata.json")
            with open(path, "w") as f:
                json.dump(SAMPLE_PLAYERS, f)
            with open(meta_path, "w") as f:
                json.dump({"as_of": "2026-05-25"}, f)
            store = ProjectionStore(path)
            self.assertEqual(store.as_of, "2026-05-25")
```

- [ ] **Step 2: Write test for no-ROS indicator in web app**

Add to `tests/test_app.py`:

```python
class TestNoRosIndicator(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_no_ros_badge_class_exists_in_css(self):
        """The no-ros-badge CSS class should exist for actuals-only players."""
        import os
        css_path = os.path.join(os.path.dirname(__file__), "..", "static", "style.css")
        with open(css_path) as f:
            css = f.read()
        self.assertIn("no-ros-badge", css)
```

- [ ] **Step 3: Update `web/projection_store.py`**

Add metadata loading to the `__init__` and `_load` methods:

```python
class ProjectionStore:
    """Loads and caches player projections from a JSON file."""

    def __init__(self, path: str | Path) -> None:
        self._players: list[PlayerProjection] = []
        self._by_id: dict[str, PlayerProjection] = {}
        self._as_of: str | None = None
        self._load(Path(path))

    def _load(self, path: Path) -> None:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)

        # Load sidecar metadata if present
        meta_path = path.parent / "metadata.json"
        if meta_path.exists():
            with meta_path.open("r", encoding="utf-8") as f:
                meta = json.load(f)
            self._as_of = meta.get("as_of")

        # ... rest of _load unchanged ...
```

Add the `as_of` property:

```python
    @property
    def as_of(self) -> str | None:
        return self._as_of
```

- [ ] **Step 4: Update `app.py` to pass `as_of` and `has_ros` to templates**

In `_build_context`, add `as_of` to the return dict:

```python
"as_of": store.as_of,
```

- [ ] **Step 5: Update `templates/base.html` footer**

Change the footer to show the as_of date:

```html
    <footer class="site-footer">
        <p>Data: FanGraphs Steamer + ZiPS projections{% if as_of %} · Updated {{ as_of }}{% endif %}</p>
    </footer>
```

- [ ] **Step 6: Update `templates/partials/rankings_table.html` for no-ROS badge**

In the player name cell, after the tier badge, add:

```html
                {% if result.player.metadata.get('has_ros') == false %}
                <span class="no-ros-badge">No projection</span>
                {% endif %}
```

- [ ] **Step 7: Add CSS for no-ros-badge**

In `static/style.css`, add:

```css
.no-ros-badge {
    display: inline-block;
    margin-left: 0.3rem;
    font-size: 0.6rem;
    font-weight: 600;
    color: #d97706;
    background: #fef3c7;
    border-radius: 3px;
    padding: 0.05rem 0.3rem;
    vertical-align: middle;
}
```

- [ ] **Step 8: Run all tests**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`

- [ ] **Step 9: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add web/projection_store.py templates/base.html templates/partials/rankings_table.html app.py static/style.css tests/test_projection_store.py tests/test_app.py
git commit -m "feat: metadata sidecar, as_of footer, no-ROS badge for actuals-only players"
```

---

### Task 9: Run Full Refresh and Verify

- [ ] **Step 1: Run the refresh pipeline**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -c "from scraper.refresh import refresh; refresh(delay=1.0)"
```

Expected output includes:
- ROS projections fetched from `steamerr` endpoints
- Actuals fetched from MLB Stats API
- QS derived from game logs
- Season outlook combined
- Files written to `data/projections/current.json`, `data/projections/metadata.json`, `data/actuals/current.json`

- [ ] **Step 2: Verify output data**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && python -c "
import json
with open('data/projections/current.json') as f:
    data = json.load(f)
with open('data/projections/metadata.json') as f:
    meta = json.load(f)
print(f'Outlook players: {len(data)}')
print(f'Metadata: {json.dumps(meta, indent=2)}')
# Check Judge
judge = [p for p in data if 'judge' in p.get('name', '').lower()]
if judge:
    j = judge[0]
    print(f'Judge: PA={j[\"stats\"][\"PA\"]}, HR={j[\"stats\"][\"HR\"]}, has_ros={j[\"metadata\"].get(\"has_ros\", \"?\")}')
    print(f'  base_id={j[\"metadata\"].get(\"base_id\", \"MISSING\")}')
# Check Skubal
skubal = [p for p in data if 'skubal' in p.get('name', '').lower()]
if skubal:
    s = skubal[0]
    print(f'Skubal: IP={s[\"stats\"][\"IP\"]}, QS={s[\"stats\"][\"QS\"]}, H_ALLOWED={s[\"stats\"].get(\"H_ALLOWED\", \"MISSING\")}')
# Check actuals-only count
no_ros = sum(1 for p in data if not p.get('metadata', {}).get('has_ros', True))
print(f'Players without ROS: {no_ros}')
"
```

- [ ] **Step 3: Run all tests**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`

- [ ] **Step 4: Start app and smoke test**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python app.py
```

Verify at http://localhost:5001:
1. Rankings load with season outlook data
2. Footer shows "Updated 2026-05-25" (or today's date)
3. Skubal and other SPs show non-zero QS in category values
4. WHIP values look reasonable (H_ALLOWED fix working)
5. No single-player tiers (tier fix working)

- [ ] **Step 5: Commit data files**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add data/
git commit -m "data: season outlook — 2026 actuals + Steamer ROS projections"
```

- [ ] **Step 6: Push to GitHub**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git push origin master
```
