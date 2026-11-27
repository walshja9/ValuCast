# Data Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pull Steamer and ZiPS projections from FanGraphs, blend them, and output a JSON file that feeds directly into the league_values engine.

**Architecture:** Three modules — `fangraphs.py` (HTTP fetcher), `blend.py` (player matching + stat blending), `refresh.py` (orchestrator). Raw API responses saved to `data/projections/raw/`, blended output to `data/projections/current.json`. No external dependencies beyond stdlib.

**Tech Stack:** Python 3.12+, urllib.request, json, unittest. No external dependencies.

**Test runner:** `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v`

---

### Task 1: FanGraphs Fetcher

**Files:**
- Create: `scraper/__init__.py`
- Create: `scraper/fangraphs.py`
- Test: `tests/test_fangraphs.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fangraphs.py`:

```python
import json
import unittest
from unittest.mock import patch, MagicMock

from scraper.fangraphs import fetch_projections, fetch_all, PROJECTION_URL


class TestFetchProjections(unittest.TestCase):
    def _mock_response(self, data):
        mock = MagicMock()
        mock.read.return_value = json.dumps(data).encode("utf-8")
        mock.__enter__ = lambda s: s
        mock.__exit__ = MagicMock(return_value=False)
        return mock

    @patch("scraper.fangraphs.urlopen")
    def test_fetch_returns_list_of_dicts(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response([
            {"PlayerName": "Test Player", "Team": "NYY", "HR": 30, "playerids": "12345"},
        ])
        result = fetch_projections("steamer", "bat")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["PlayerName"], "Test Player")

    @patch("scraper.fangraphs.urlopen")
    def test_fetch_builds_correct_url(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response([])
        fetch_projections("zips", "pit")
        called_url = mock_urlopen.call_args[0][0].full_url
        self.assertIn("type=zips", called_url)
        self.assertIn("stats=pit", called_url)

    @patch("scraper.fangraphs.urlopen")
    def test_fetch_all_returns_four_keys(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response([])
        result = fetch_all(delay=0)
        self.assertEqual(set(result.keys()), {
            "steamer_hitters", "steamer_pitchers",
            "zips_hitters", "zips_pitchers",
        })

    def test_projection_url_format(self):
        self.assertIn("fangraphs.com/api/projections", PROJECTION_URL)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest tests.test_fangraphs -v`
Expected: ImportError — `scraper.fangraphs` doesn't exist.

- [ ] **Step 3: Create scraper package and fangraphs.py**

Create `scraper/__init__.py` (empty file).

Create `scraper/fangraphs.py`:

```python
"""Fetch Steamer and ZiPS projections from the FanGraphs API."""
from __future__ import annotations

import json
import time
from urllib.request import Request, urlopen

PROJECTION_URL = "https://www.fangraphs.com/api/projections"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def fetch_projections(system: str, stats: str) -> list[dict]:
    """Fetch one projection set.

    Args:
        system: 'steamer' or 'zips'
        stats: 'bat' or 'pit'

    Returns:
        List of player dicts from the API.
    """
    url = f"{PROJECTION_URL}?type={system}&stats={stats}&pos=all&team=0&players=0&lg=all"
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_all(delay: float = 1.0) -> dict[str, list[dict]]:
    """Fetch all 4 projection sets with a delay between requests.

    Returns:
        Dict with keys: steamer_hitters, steamer_pitchers, zips_hitters, zips_pitchers.
    """
    sets = [
        ("steamer_hitters", "steamer", "bat"),
        ("steamer_pitchers", "steamer", "pit"),
        ("zips_hitters", "zips", "bat"),
        ("zips_pitchers", "zips", "pit"),
    ]
    result = {}
    for i, (key, system, stats) in enumerate(sets):
        result[key] = fetch_projections(system, stats)
        if delay > 0 and i < len(sets) - 1:
            time.sleep(delay)
    return result


def save_raw(data: dict[str, list[dict]], output_dir: str) -> None:
    """Save raw API responses to JSON files."""
    import os
    os.makedirs(output_dir, exist_ok=True)
    for key, players in data.items():
        path = os.path.join(output_dir, f"{key}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(players, f, indent=2)
```

- [ ] **Step 4: Run tests**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest tests.test_fangraphs -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scraper/__init__.py scraper/fangraphs.py tests/test_fangraphs.py
git commit -m "feat: add FanGraphs API fetcher — 4 projection sets via HTTP"
```

---

### Task 2: Projection Blender

**Files:**
- Create: `scraper/blend.py`
- Test: `tests/test_blend.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_blend.py`:

```python
import unittest

from scraper.blend import blend_projections, blend_hitters, blend_pitchers


STEAMER_HITTERS = [
    {"playerids": "1", "PlayerName": "Star Hitter", "Team": "NYY",
     "PA": 620, "AB": 560, "H": 168, "HR": 32, "R": 95, "RBI": 90,
     "SB": 15, "SO": 120, "BB": 55, "AVG": 0.300, "OBP": 0.370,
     "SLG": 0.520, "OPS": 0.890},
    {"playerids": "2", "PlayerName": "Bench Guy", "Team": "BOS",
     "PA": 250, "AB": 220, "H": 55, "HR": 8, "R": 30, "RBI": 28,
     "SB": 3, "SO": 60, "BB": 25, "AVG": 0.250, "OBP": 0.320,
     "SLG": 0.400, "OPS": 0.720},
]

ZIPS_HITTERS = [
    {"playerids": "1", "PlayerName": "Star Hitter", "Team": "NYY",
     "PA": 640, "AB": 580, "H": 174, "HR": 36, "R": 100, "RBI": 95,
     "SB": 18, "SO": 130, "BB": 55, "AVG": 0.300, "OBP": 0.365,
     "SLG": 0.540, "OPS": 0.905},
]

STEAMER_PITCHERS = [
    {"playerids": "10", "PlayerName": "Ace Starter", "Team": "LAD",
     "GS": 30, "G": 32, "W": 14, "L": 7, "IP": 190, "SO": 210,
     "BB": 50, "SV": 0, "HLD": 0, "ER": 65, "H": 155, "QS": 18,
     "ERA": 3.08, "WHIP": 1.08, "K/9": 9.95, "BB/9": 2.37, "K/BB": 4.20},
    {"playerids": "11", "PlayerName": "Shutdown Closer", "Team": "CLE",
     "GS": 0, "G": 65, "W": 4, "L": 2, "IP": 65, "SO": 80,
     "SV": 38, "HLD": 0, "ER": 15, "BB": 15, "H": 40, "QS": 0,
     "ERA": 2.08, "WHIP": 0.85, "K/9": 11.08, "BB/9": 2.08, "K/BB": 5.33},
]

ZIPS_PITCHERS = [
    {"playerids": "10", "PlayerName": "Ace Starter", "Team": "LAD",
     "GS": 30, "G": 32, "W": 12, "L": 8, "IP": 185, "SO": 200,
     "BB": 55, "SV": 0, "HLD": 0, "ER": 70, "H": 160, "QS": 16,
     "ERA": 3.41, "WHIP": 1.16, "K/9": 9.73, "BB/9": 2.68, "K/BB": 3.64},
]


class TestBlendHitters(unittest.TestCase):
    def test_matched_hitter_averages_counting_stats(self):
        result = blend_hitters(STEAMER_HITTERS, ZIPS_HITTERS)
        star = next(p for p in result if p["name"] == "Star Hitter")
        # PA: avg of 620 and 640 = 630
        self.assertAlmostEqual(star["stats"]["PA"], 630, places=0)
        # HR: avg of 32 and 36 = 34
        self.assertAlmostEqual(star["stats"]["HR"], 34, places=0)

    def test_unmatched_hitter_uses_single_source(self):
        result = blend_hitters(STEAMER_HITTERS, ZIPS_HITTERS)
        bench = next(p for p in result if p["name"] == "Bench Guy")
        self.assertAlmostEqual(bench["stats"]["PA"], 250, places=0)

    def test_hitter_has_correct_pool(self):
        result = blend_hitters(STEAMER_HITTERS, ZIPS_HITTERS)
        for p in result:
            self.assertEqual(p["pool"], "hitter")

    def test_hitter_has_required_fields(self):
        result = blend_hitters(STEAMER_HITTERS, ZIPS_HITTERS)
        star = next(p for p in result if p["name"] == "Star Hitter")
        self.assertIn("id", star)
        self.assertIn("name", star)
        self.assertIn("pool", star)
        self.assertIn("team", star)
        self.assertIn("stats", star)
        self.assertIn("metadata", star)

    def test_rate_stats_volume_weighted(self):
        result = blend_hitters(STEAMER_HITTERS, ZIPS_HITTERS)
        star = next(p for p in result if p["name"] == "Star Hitter")
        # AVG should be volume-weighted: (0.300*620 + 0.300*640) / (620+640) = 0.300
        self.assertAlmostEqual(star["stats"]["AVG"], 0.300, places=3)
        # OPS: (0.890*620 + 0.905*640) / (620+640) ≈ 0.8976
        self.assertAlmostEqual(star["stats"]["OPS"], 0.898, places=2)


class TestBlendPitchers(unittest.TestCase):
    def test_starter_has_correct_pool(self):
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        ace = next(p for p in result if p["name"] == "Ace Starter")
        self.assertEqual(ace["pool"], "starter")

    def test_closer_has_reliever_pool(self):
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        closer = next(p for p in result if p["name"] == "Shutdown Closer")
        self.assertEqual(closer["pool"], "reliever")

    def test_pitcher_has_derived_stats(self):
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        closer = next(p for p in result if p["name"] == "Shutdown Closer")
        self.assertIn("SV_HLD", closer["stats"])
        self.assertEqual(closer["stats"]["SV_HLD"], 38)
        self.assertIn("K_BB", closer["stats"])

    def test_starter_positions(self):
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        ace = next(p for p in result if p["name"] == "Ace Starter")
        self.assertIn("SP", ace["positions"])

    def test_closer_positions(self):
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        closer = next(p for p in result if p["name"] == "Shutdown Closer")
        self.assertIn("RP", closer["positions"])

    def test_matched_pitcher_averages_counting(self):
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        ace = next(p for p in result if p["name"] == "Ace Starter")
        # IP: avg(190, 185) = 187.5
        self.assertAlmostEqual(ace["stats"]["IP"], 187.5, places=1)
        # K: avg(210, 200) = 205
        self.assertAlmostEqual(ace["stats"]["K"], 205, places=0)


class TestBlendAll(unittest.TestCase):
    def test_blend_projections_returns_all_players(self):
        raw = {
            "steamer_hitters": STEAMER_HITTERS,
            "steamer_pitchers": STEAMER_PITCHERS,
            "zips_hitters": ZIPS_HITTERS,
            "zips_pitchers": ZIPS_PITCHERS,
        }
        result = blend_projections(raw)
        # 2 hitters + 2 pitchers (bench guy only in steamer, closer only in steamer)
        names = {p["name"] for p in result}
        self.assertIn("Star Hitter", names)
        self.assertIn("Bench Guy", names)
        self.assertIn("Ace Starter", names)
        self.assertIn("Shutdown Closer", names)

    def test_blend_output_is_list_of_dicts(self):
        raw = {
            "steamer_hitters": STEAMER_HITTERS,
            "steamer_pitchers": STEAMER_PITCHERS,
            "zips_hitters": ZIPS_HITTERS,
            "zips_pitchers": ZIPS_PITCHERS,
        }
        result = blend_projections(raw)
        self.assertIsInstance(result, list)
        for p in result:
            self.assertIsInstance(p, dict)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest tests.test_blend -v`
Expected: ImportError — `scraper.blend` doesn't exist.

- [ ] **Step 3: Implement blend.py**

Create `scraper/blend.py`:

```python
"""Blend Steamer and ZiPS projections into a single player set."""
from __future__ import annotations


# Stats to average (counting stats)
HITTER_COUNTING = ("PA", "AB", "H", "HR", "R", "RBI", "SB", "SO", "BB",
                    "1B", "2B", "3B", "HBP", "SF", "SH", "GDP", "CS", "IBB", "G")
PITCHER_COUNTING = ("IP", "K", "W", "L", "GS", "G", "SV", "HLD", "ER", "H",
                     "BB", "QS", "SO", "HR", "R", "TBF", "IBB", "HBP", "BS")

# Stats to volume-weight (rate stats)
HITTER_RATE = ("AVG", "OBP", "SLG", "OPS")
PITCHER_RATE = ("ERA", "WHIP")


def _safe_float(val, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _avg(a: float, b: float) -> float:
    return (a + b) / 2


def _weighted_avg(val_a: float, vol_a: float, val_b: float, vol_b: float) -> float:
    total_vol = vol_a + vol_b
    if total_vol == 0:
        return 0.0
    return (val_a * vol_a + val_b * vol_b) / total_vol


def blend_hitters(steamer: list[dict], zips: list[dict]) -> list[dict]:
    """Blend hitter projections from two sources."""
    steamer_by_id = {str(p.get("playerids", "")): p for p in steamer if p.get("playerids")}
    zips_by_id = {str(p.get("playerids", "")): p for p in zips if p.get("playerids")}

    all_ids = set(steamer_by_id) | set(zips_by_id)
    result = []

    for pid in all_ids:
        s = steamer_by_id.get(pid)
        z = zips_by_id.get(pid)

        if s and z:
            player = _blend_hitter(s, z, pid)
        elif s:
            player = _single_hitter(s, pid, "steamer")
        else:
            player = _single_hitter(z, pid, "zips")

        result.append(player)

    return result


def _blend_hitter(s: dict, z: dict, pid: str) -> dict:
    stats = {}
    for stat in HITTER_COUNTING:
        sv = _safe_float(s.get(stat))
        zv = _safe_float(z.get(stat))
        stats[stat] = _avg(sv, zv)

    s_pa = _safe_float(s.get("PA", 0))
    z_pa = _safe_float(z.get("PA", 0))
    for stat in HITTER_RATE:
        sv = _safe_float(s.get(stat))
        zv = _safe_float(z.get(stat))
        stats[stat] = _weighted_avg(sv, s_pa, zv, z_pa)

    # Recompute AVG from blended counting for consistency
    ab = stats.get("AB", 0)
    if ab > 0:
        stats["AVG"] = stats.get("H", 0) / ab

    return {
        "id": pid,
        "name": s.get("PlayerName", ""),
        "pool": "hitter",
        "positions": [],
        "team": s.get("Team", ""),
        "stats": {k: round(v, 3) if isinstance(v, float) else v for k, v in stats.items()},
        "metadata": {
            "fangraphs_id": pid,
            "mlbam_id": str(s.get("xMLBAMID", "") or s.get("MLBAMID", "")),
        },
        "sources": ["steamer", "zips"],
    }


def _single_hitter(p: dict, pid: str, source: str) -> dict:
    stats = {}
    for stat in HITTER_COUNTING:
        stats[stat] = _safe_float(p.get(stat))
    for stat in HITTER_RATE:
        stats[stat] = _safe_float(p.get(stat))

    return {
        "id": pid,
        "name": p.get("PlayerName", ""),
        "pool": "hitter",
        "positions": [],
        "team": p.get("Team", ""),
        "stats": {k: round(v, 3) if isinstance(v, float) else v for k, v in stats.items()},
        "metadata": {
            "fangraphs_id": pid,
            "mlbam_id": str(p.get("xMLBAMID", "") or p.get("MLBAMID", "")),
        },
        "sources": [source],
    }


def blend_pitchers(steamer: list[dict], zips: list[dict]) -> list[dict]:
    """Blend pitcher projections from two sources."""
    steamer_by_id = {str(p.get("playerids", "")): p for p in steamer if p.get("playerids")}
    zips_by_id = {str(p.get("playerids", "")): p for p in zips if p.get("playerids")}

    all_ids = set(steamer_by_id) | set(zips_by_id)
    result = []

    for pid in all_ids:
        s = steamer_by_id.get(pid)
        z = zips_by_id.get(pid)

        if s and z:
            player = _blend_pitcher(s, z, pid)
        elif s:
            player = _single_pitcher(s, pid, "steamer")
        else:
            player = _single_pitcher(z, pid, "zips")

        result.append(player)

    return result


def _detect_pitcher_pool(stats: dict) -> str:
    gs = _safe_float(stats.get("GS", 0))
    sv = _safe_float(stats.get("SV", 0))
    hld = _safe_float(stats.get("HLD", 0))
    if gs > 0:
        return "starter"
    if sv > 0 or hld > 0:
        return "reliever"
    return "starter"


def _detect_pitcher_positions(stats: dict) -> list[str]:
    gs = _safe_float(stats.get("GS", 0))
    sv = _safe_float(stats.get("SV", 0))
    hld = _safe_float(stats.get("HLD", 0))
    positions = []
    if gs > 0:
        positions.append("SP")
    if sv > 0 or hld > 0:
        positions.append("RP")
    if not positions:
        positions.append("SP")
    return positions


def _blend_pitcher(s: dict, z: dict, pid: str) -> dict:
    stats = {}
    for stat in PITCHER_COUNTING:
        sv = _safe_float(s.get(stat))
        zv = _safe_float(z.get(stat))
        stats[stat] = _avg(sv, zv)

    # Use "SO" key for strikeouts (engine expects "K")
    if "SO" in stats and "K" not in stats:
        stats["K"] = stats.pop("SO")
    elif "SO" in stats:
        stats["K"] = stats.pop("SO")

    s_ip = _safe_float(s.get("IP", 0))
    z_ip = _safe_float(z.get("IP", 0))
    for stat in PITCHER_RATE:
        sv = _safe_float(s.get(stat))
        zv = _safe_float(z.get(stat))
        stats[stat] = _weighted_avg(sv, s_ip, zv, z_ip)

    # Derived stats
    stats["SV_HLD"] = _safe_float(stats.get("SV", 0)) + _safe_float(stats.get("HLD", 0))
    bb = _safe_float(stats.get("BB", 0))
    k = _safe_float(stats.get("K", 0))
    stats["K_BB"] = round(k / bb, 2) if bb > 0 else 0.0

    pool = _detect_pitcher_pool(stats)
    positions = _detect_pitcher_positions(stats)

    return {
        "id": pid,
        "name": s.get("PlayerName", ""),
        "pool": pool,
        "positions": positions,
        "team": s.get("Team", ""),
        "stats": {k_: round(v, 3) if isinstance(v, float) else v for k_, v in stats.items()},
        "metadata": {
            "fangraphs_id": pid,
            "mlbam_id": str(s.get("xMLBAMID", "") or s.get("MLBAMID", "")),
        },
        "sources": ["steamer", "zips"],
    }


def _single_pitcher(p: dict, pid: str, source: str) -> dict:
    stats = {}
    for stat in PITCHER_COUNTING:
        stats[stat] = _safe_float(p.get(stat))
    for stat in PITCHER_RATE:
        stats[stat] = _safe_float(p.get(stat))

    if "SO" in stats and "K" not in stats:
        stats["K"] = stats.pop("SO")
    elif "SO" in stats:
        stats["K"] = stats.pop("SO")

    stats["SV_HLD"] = _safe_float(stats.get("SV", 0)) + _safe_float(stats.get("HLD", 0))
    bb = _safe_float(stats.get("BB", 0))
    k = _safe_float(stats.get("K", 0))
    stats["K_BB"] = round(k / bb, 2) if bb > 0 else 0.0

    pool = _detect_pitcher_pool(stats)
    positions = _detect_pitcher_positions(stats)

    return {
        "id": pid,
        "name": p.get("PlayerName", ""),
        "pool": pool,
        "positions": positions,
        "team": p.get("Team", ""),
        "stats": {k_: round(v, 3) if isinstance(v, float) else v for k_, v in stats.items()},
        "metadata": {
            "fangraphs_id": pid,
            "mlbam_id": str(p.get("xMLBAMID", "") or p.get("MLBAMID", "")),
        },
        "sources": [source],
    }


def blend_projections(raw: dict[str, list[dict]]) -> list[dict]:
    """Blend all raw projection data into a single player list.

    Args:
        raw: Dict with keys steamer_hitters, steamer_pitchers, zips_hitters, zips_pitchers.

    Returns:
        List of player dicts ready for value_players().
    """
    hitters = blend_hitters(
        raw.get("steamer_hitters", []),
        raw.get("zips_hitters", []),
    )
    pitchers = blend_pitchers(
        raw.get("steamer_pitchers", []),
        raw.get("zips_pitchers", []),
    )
    return hitters + pitchers
```

- [ ] **Step 4: Run tests**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest tests.test_blend -v`
Expected: 12 tests PASS.

- [ ] **Step 5: Run full suite**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`
Expected: All tests PASS (82 existing + 12 new = 94).

- [ ] **Step 6: Commit**

```bash
git add scraper/blend.py tests/test_blend.py
git commit -m "feat: add projection blender — Steamer/ZiPS matching, stat blending, pool detection"
```

---

### Task 3: Refresh Orchestrator + Data Directories

**Files:**
- Create: `scraper/refresh.py`
- Create: `data/projections/raw/.gitkeep`
- Modify: `.gitignore`
- Test: `tests/test_refresh.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_refresh.py`:

```python
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from scraper.refresh import refresh


class TestRefresh(unittest.TestCase):
    @patch("scraper.refresh.fetch_all")
    def test_refresh_writes_current_json(self, mock_fetch):
        mock_fetch.return_value = {
            "steamer_hitters": [
                {"playerids": "1", "PlayerName": "Test", "Team": "NYY",
                 "PA": 600, "AB": 540, "H": 162, "HR": 30, "R": 90, "RBI": 85,
                 "SB": 10, "SO": 120, "BB": 55, "AVG": 0.300, "OBP": 0.370,
                 "SLG": 0.500, "OPS": 0.870},
            ],
            "steamer_pitchers": [],
            "zips_hitters": [],
            "zips_pitchers": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "current.json")
            raw_dir = os.path.join(tmpdir, "raw")
            refresh(output_path=output, raw_dir=raw_dir, delay=0)

            self.assertTrue(os.path.exists(output))
            with open(output) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["name"], "Test")

    @patch("scraper.refresh.fetch_all")
    def test_refresh_saves_raw_files(self, mock_fetch):
        mock_fetch.return_value = {
            "steamer_hitters": [{"playerids": "1", "PlayerName": "A", "Team": "X"}],
            "steamer_pitchers": [],
            "zips_hitters": [],
            "zips_pitchers": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "current.json")
            raw_dir = os.path.join(tmpdir, "raw")
            refresh(output_path=output, raw_dir=raw_dir, delay=0)

            self.assertTrue(os.path.exists(os.path.join(raw_dir, "steamer_hitters.json")))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest tests.test_refresh -v`
Expected: ImportError — `scraper.refresh` doesn't exist.

- [ ] **Step 3: Implement refresh.py**

Create `scraper/refresh.py`:

```python
"""Orchestrator: fetch projections, blend, write output."""
from __future__ import annotations

import json
import os

from .fangraphs import fetch_all, save_raw
from .blend import blend_projections


DEFAULT_OUTPUT = os.path.join(os.path.dirname(__file__), "..", "data", "projections", "current.json")
DEFAULT_RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "projections", "raw")


def refresh(
    output_path: str = DEFAULT_OUTPUT,
    raw_dir: str = DEFAULT_RAW_DIR,
    delay: float = 1.0,
) -> list[dict]:
    """Full pipeline: fetch all projections, blend, write output.

    Returns:
        Blended player list.
    """
    print("Fetching projections from FanGraphs...")
    raw = fetch_all(delay=delay)

    for key, players in raw.items():
        print(f"  {key}: {len(players)} players")

    print("Saving raw data...")
    save_raw(raw, raw_dir)

    print("Blending projections...")
    blended = blend_projections(raw)
    print(f"  {len(blended)} total players")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(blended, f, indent=2)
    print(f"Written to {output_path}")

    return blended


if __name__ == "__main__":
    refresh()
```

- [ ] **Step 4: Create data directories and update .gitignore**

Create `data/projections/raw/.gitkeep` (empty file).

Add to `.gitignore`:
```
data/projections/raw/*.json
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 5: Run tests**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest tests.test_refresh -v`
Expected: 2 tests PASS.

- [ ] **Step 6: Run full suite**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`
Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add scraper/refresh.py tests/test_refresh.py data/projections/raw/.gitkeep .gitignore
git commit -m "feat: add refresh orchestrator — fetch, blend, write current.json"
```

---

### Task 4: Live Fetch Test + Push

**Files:** None new — this is a manual verification step.

- [ ] **Step 1: Run the actual pipeline against FanGraphs**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m scraper.refresh`

Expected output:
```
Fetching projections from FanGraphs...
  steamer_hitters: ~300 players
  steamer_pitchers: ~400 players
  zips_hitters: ~300 players
  zips_pitchers: ~400 players
Saving raw data...
Blending projections...
  ~800 total players
Written to data/projections/current.json
```

- [ ] **Step 2: Verify current.json is usable by the engine**

```python
import json
from league_values import value_players
from league_values.presets import dd_7x7

with open("data/projections/current.json") as f:
    players = json.load(f)

config = dd_7x7()
results = value_players(players, config)
print(f"Valued {len(results)} players")
for r in results[:10]:
    print(f"  {r.name}: {r.total_value:.2f}")
```

- [ ] **Step 3: Commit current.json and push**

```bash
git add data/projections/current.json
git commit -m "data: initial blended projections from FanGraphs Steamer + ZiPS"
git push origin master
```
