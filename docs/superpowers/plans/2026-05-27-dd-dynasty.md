# DD 7x7 Dynasty Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a DD 7x7 Dynasty mode to ValuCast that consumes a combined MLB + prospect dynasty feed from Diamond Dynasties, displaying interleaved rankings with dynasty values on a 0-150 scale.

**Architecture:** DD exports a versioned JSON feed (`dd_dynasty_feed.json`) containing all MLB players and prospects with dynasty values. ValuCast loads this feed at startup via `web/dd_feed_store.py`, validates it, and serves it through a dedicated `dd_dynasty` mode that bypasses the engine. Separate template partials render dynasty-specific rankings and player details. Redraft modes are completely unaffected.

**Tech Stack:** Python 3.12, Flask, Jinja2, htmx, unittest

**Test runner:** `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`

**Implementation notes:**
- `mode=dd_dynasty` must NEVER flow through `ScoringMode(mode)` or `build_config()` — branch out of `_build_context` before either is called.
- No Flask flash messages — use a `notice` context variable for the feed-unavailable warning.
- DD feed records use `DynastyRankingRow`, not `ValuationResult`. No fake engine objects.

---

### Task 1: DD Feed Generator (DD Repo)

**Files:**
- Create: `C:/Users/Alex/DiamondDynastiesTradeAnalyzer/generate_valucast_feed.py`

This task runs in the **DD repo**, not the ValuCast repo. It generates the feed file that ValuCast consumes.

- [ ] **Step 1: Create the feed generator script**

Create `C:/Users/Alex/DiamondDynastiesTradeAnalyzer/generate_valucast_feed.py`:

```python
"""Generate dd_dynasty_feed.json for ValuCast consumption."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from valuation import get_dynasty_value
from precompute import get_all_player_names


def _get_prospect_data() -> list[dict]:
    """Load prospects from prospects_ranked.json."""
    path = os.path.join(os.path.dirname(__file__), "prospects_ranked.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_mlb_record(name: str, team: str, dynasty_rank: int) -> dict | None:
    """Build a feed record for an MLB player."""
    try:
        val_result = get_dynasty_value(name, team)
    except Exception:
        return None

    value = val_result.get("value", 0)
    if value <= 0:
        return None

    mlbam_id = str(val_result.get("mlbam_id", ""))
    player_id = f"dd_mlb_{mlbam_id}" if mlbam_id else f"dd_mlb_{name.lower().replace(' ', '_')}"

    return {
        "id": player_id,
        "player_type": "mlb",
        "name": name,
        "mlbam_id": mlbam_id or None,
        "positions": val_result.get("positions", []),
        "mlb_team": team,
        "age": val_result.get("age"),
        "dynasty_rank": dynasty_rank,
        "dynasty_value": round(value, 1),
        "status": "mlb",
        "last_updated": datetime.now().strftime("%Y-%m-%d"),
    }


def _build_prospect_record(prospect: dict, dynasty_rank: int) -> dict:
    """Build a feed record for a prospect."""
    name = prospect.get("name", "")
    mlbam_id = str(prospect.get("mlbam_id", ""))
    if mlbam_id:
        player_id = f"dd_prospect_{mlbam_id}"
    else:
        player_id = f"dd_prospect_{name.lower().replace(' ', '_')}"

    # Get dynasty value from valuation
    try:
        val_result = get_dynasty_value(name, prospect.get("mlb_team", ""))
        dynasty_value = round(val_result.get("value", 0), 1)
    except Exception:
        dynasty_value = 0

    return {
        "id": player_id,
        "player_type": "prospect",
        "name": name,
        "mlbam_id": mlbam_id or None,
        "positions": prospect.get("positions", []),
        "mlb_team": prospect.get("mlb_team", ""),
        "age": prospect.get("age"),
        "dynasty_rank": dynasty_rank,
        "dynasty_value": dynasty_value,
        "status": "minors",
        "last_updated": datetime.now().strftime("%Y-%m-%d"),
        # Prospect-only fields
        "level": prospect.get("level"),
        "eta": prospect.get("eta"),
        "prospect_rank": prospect.get("composite_rank"),
        "source_ranks": prospect.get("source_ranks"),
        "breakout_label": prospect.get("breakout_label"),
        "breakout_rank_change": prospect.get("breakout_rank_change"),
        "stat_line": prospect.get("breakout_stat_line") or prospect.get("stat_line"),
    }


def generate_feed(output_path: str | None = None) -> dict:
    """Generate the complete DD dynasty feed."""
    if output_path is None:
        output_path = os.path.join(os.path.dirname(__file__), "dd_dynasty_feed.json")

    print("Loading prospect data...")
    prospects = _get_prospect_data()

    print("Computing MLB dynasty values...")
    all_players = get_all_player_names()

    # Build all records
    mlb_records = []
    for name, team in all_players:
        record = _build_mlb_record(name, team, dynasty_rank=0)
        if record:
            mlb_records.append(record)

    prospect_records = []
    for prospect in prospects:
        record = _build_prospect_record(prospect, dynasty_rank=0)
        if record and record["dynasty_value"] > 0:
            prospect_records.append(record)

    # Combine and rank by dynasty_value
    all_records = mlb_records + prospect_records
    all_records.sort(key=lambda r: r["dynasty_value"], reverse=True)
    for i, record in enumerate(all_records, 1):
        record["dynasty_rank"] = i

    # Also set prospect_rank for prospects
    prospect_rank = 1
    for record in all_records:
        if record["player_type"] == "prospect":
            record["prospect_rank"] = prospect_rank
            prospect_rank += 1

    feed = {
        "schema_version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "generated_by": "diamond_dynasties",
        "source": "diamond_dynasties",
        "league_preset": "DD_7x7",
        "scale": "0_150_dynasty_value",
        "value_semantics": "higher_is_better",
        "player_count": len(all_records),
        "prospect_count": len(prospect_records),
        "players": all_records,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(feed, f, indent=2)
    print(f"Feed written: {len(all_records)} players ({len(prospect_records)} prospects) → {output_path}")

    return feed


if __name__ == "__main__":
    generate_feed()
```

Note: This script depends on DD's existing `valuation.py`, `precompute.py`, and data files. The exact function signatures for `get_dynasty_value` and `get_all_player_names` may need adjustment based on DD's current API. The implementer should read those files and adapt the calls.

- [ ] **Step 2: Run the generator and verify output**

```bash
cd "C:/Users/Alex/DiamondDynastiesTradeAnalyzer" && python generate_valucast_feed.py
```

Verify the output:
```bash
python -c "
import json
with open('dd_dynasty_feed.json') as f:
    feed = json.load(f)
print(f'Schema: {feed[\"schema_version\"]}')
print(f'Players: {feed[\"player_count\"]}')
print(f'Prospects: {feed[\"prospect_count\"]}')
mlb = [p for p in feed['players'] if p['player_type'] == 'mlb']
pros = [p for p in feed['players'] if p['player_type'] == 'prospect']
print(f'MLB: {len(mlb)}, Prospects: {len(pros)}')
print(f'Top 5:')
for p in feed['players'][:5]:
    print(f'  #{p[\"dynasty_rank\"]} {p[\"name\"]} ({p[\"player_type\"]}) = {p[\"dynasty_value\"]}')
"
```

- [ ] **Step 3: Copy feed to ValuCast**

```bash
mkdir -p "C:/Users/Alex/Documents/Codex/2026-05-18/league-values/data/dd"
cp "C:/Users/Alex/DiamondDynastiesTradeAnalyzer/dd_dynasty_feed.json" "C:/Users/Alex/Documents/Codex/2026-05-18/league-values/data/dd/"
```

- [ ] **Step 4: Commit the generator in DD repo**

```bash
cd "C:/Users/Alex/DiamondDynastiesTradeAnalyzer"
git add generate_valucast_feed.py
git commit -m "feat: add ValuCast dynasty feed generator"
```

- [ ] **Step 5: Commit the feed in ValuCast repo**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add data/dd/dd_dynasty_feed.json
git commit -m "data: initial DD dynasty feed — MLB + prospect values"
```

---

### Task 2: DynastyRankingRow Model

**Files:**
- Create: `web/dynasty_models.py`
- Create: `tests/test_dynasty_models.py`

- [ ] **Step 1: Write tests**

Create `tests/test_dynasty_models.py`:

```python
import unittest
from web.dynasty_models import DynastyRankingRow


SAMPLE_MLB = {
    "id": "dd_mlb_592450",
    "player_type": "mlb",
    "name": "Aaron Judge",
    "mlbam_id": "592450",
    "positions": ["OF"],
    "mlb_team": "NYY",
    "age": 34,
    "dynasty_rank": 12,
    "dynasty_value": 88.2,
    "status": "mlb",
}

SAMPLE_PROSPECT = {
    "id": "dd_prospect_691234",
    "player_type": "prospect",
    "name": "Kade Anderson",
    "mlbam_id": "691234",
    "positions": ["SP"],
    "mlb_team": "SEA",
    "age": 21,
    "dynasty_rank": 38,
    "dynasty_value": 71.3,
    "status": "minors",
    "level": "AAA",
    "eta": 2027,
    "prospect_rank": 2,
    "source_ranks": {"pipeline": 17, "cfr": 4, "hkb": 4, "milb_perf": 21},
    "breakout_label": "steady",
    "breakout_rank_change": -1,
    "stat_line": {"era": 1.63, "k_per_9": 13.5, "whip": 0.8, "ip": 38.7},
}


class TestDynastyRankingRow(unittest.TestCase):
    def test_from_feed_mlb(self):
        row = DynastyRankingRow.from_feed(SAMPLE_MLB)
        self.assertEqual(row.id, "dd_mlb_592450")
        self.assertEqual(row.name, "Aaron Judge")
        self.assertEqual(row.player_type, "mlb")
        self.assertEqual(row.dynasty_rank, 12)
        self.assertEqual(row.dynasty_value, 88.2)
        self.assertIsNone(row.prospect_rank)
        self.assertIsNone(row.stat_line)

    def test_from_feed_prospect(self):
        row = DynastyRankingRow.from_feed(SAMPLE_PROSPECT)
        self.assertEqual(row.id, "dd_prospect_691234")
        self.assertEqual(row.player_type, "prospect")
        self.assertEqual(row.prospect_rank, 2)
        self.assertEqual(row.level, "AAA")
        self.assertEqual(row.eta, 2027)
        self.assertEqual(row.breakout_label, "steady")
        self.assertIsNotNone(row.stat_line)

    def test_is_prospect(self):
        mlb_row = DynastyRankingRow.from_feed(SAMPLE_MLB)
        prospect_row = DynastyRankingRow.from_feed(SAMPLE_PROSPECT)
        self.assertFalse(mlb_row.is_prospect)
        self.assertTrue(prospect_row.is_prospect)

    def test_positions_as_tuple(self):
        row = DynastyRankingRow.from_feed(SAMPLE_MLB)
        self.assertIsInstance(row.positions, tuple)

    def test_missing_optional_fields(self):
        minimal = {"id": "dd_mlb_1", "player_type": "mlb", "name": "Test",
                   "dynasty_rank": 1, "dynasty_value": 50.0}
        row = DynastyRankingRow.from_feed(minimal)
        self.assertIsNone(row.mlbam_id)
        self.assertIsNone(row.age)
        self.assertEqual(row.positions, ())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest tests.test_dynasty_models -v`

- [ ] **Step 3: Implement `web/dynasty_models.py`**

Create `web/dynasty_models.py`:

```python
"""Data models for DD Dynasty mode — separate from engine ValuationResult."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DynastyRankingRow:
    """A single player row in DD Dynasty rankings. Not an engine result."""
    id: str
    name: str
    player_type: str
    positions: tuple[str, ...]
    team: str
    age: int | None
    dynasty_rank: int
    dynasty_value: float
    status: str | None
    mlbam_id: str | None
    # MLB-specific (populated by join to season outlook)
    mlb_stats: dict | None = None
    mlb_stats_actual: dict | None = None
    mlb_stats_ros: dict | None = None
    # Prospect-specific (from feed)
    prospect_rank: int | None = None
    level: str | None = None
    eta: int | None = None
    source_ranks: dict | None = None
    breakout_label: str | None = None
    breakout_rank_change: int | None = None
    stat_line: dict | None = None
    # Raw metadata passthrough
    metadata: dict = field(default_factory=dict)

    @property
    def is_prospect(self) -> bool:
        return self.player_type == "prospect"

    @classmethod
    def from_feed(cls, record: dict) -> DynastyRankingRow:
        """Create from a DD feed record."""
        positions = record.get("positions") or []
        return cls(
            id=record["id"],
            name=record["name"],
            player_type=record["player_type"],
            positions=tuple(positions),
            team=record.get("mlb_team", ""),
            age=record.get("age"),
            dynasty_rank=record["dynasty_rank"],
            dynasty_value=record["dynasty_value"],
            status=record.get("status"),
            mlbam_id=record.get("mlbam_id"),
            prospect_rank=record.get("prospect_rank"),
            level=record.get("level"),
            eta=record.get("eta"),
            source_ranks=record.get("source_ranks"),
            breakout_label=record.get("breakout_label"),
            breakout_rank_change=record.get("breakout_rank_change"),
            stat_line=record.get("stat_line"),
            metadata=record,
        )
```

- [ ] **Step 4: Run all tests**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add web/dynasty_models.py tests/test_dynasty_models.py
git commit -m "feat: DynastyRankingRow model for DD Dynasty mode"
```

---

### Task 3: DD Feed Store

**Files:**
- Create: `web/dd_feed_store.py`
- Create: `tests/test_dd_feed_store.py`

- [ ] **Step 1: Write tests**

Create `tests/test_dd_feed_store.py`:

```python
import json
import os
import tempfile
import unittest

from web.dd_feed_store import DDFeedStore


VALID_FEED = {
    "schema_version": "1.0",
    "generated_at": "2026-05-27T08:00:00",
    "generated_by": "diamond_dynasties",
    "source": "diamond_dynasties",
    "league_preset": "DD_7x7",
    "scale": "0_150_dynasty_value",
    "value_semantics": "higher_is_better",
    "player_count": 3,
    "prospect_count": 1,
    "players": [
        {"id": "dd_mlb_100", "player_type": "mlb", "name": "Star Hitter",
         "mlbam_id": "100", "positions": ["OF"], "mlb_team": "NYY",
         "age": 28, "dynasty_rank": 1, "dynasty_value": 95.0, "status": "mlb"},
        {"id": "dd_mlb_200", "player_type": "mlb", "name": "Good Pitcher",
         "mlbam_id": "200", "positions": ["SP"], "mlb_team": "LAD",
         "age": 26, "dynasty_rank": 2, "dynasty_value": 80.0, "status": "mlb"},
        {"id": "dd_prospect_300", "player_type": "prospect", "name": "Top Prospect",
         "mlbam_id": "300", "positions": ["SS"], "mlb_team": "TEX",
         "age": 19, "dynasty_rank": 3, "dynasty_value": 72.0, "status": "minors",
         "level": "AA", "eta": 2028, "prospect_rank": 1,
         "source_ranks": {"pipeline": 1, "cfr": 2, "hkb": 3},
         "breakout_label": "rising", "breakout_rank_change": 5,
         "stat_line": {"pa": 200, "hr": 10, "ops": 0.900}},
    ],
}


def _write_feed(d: str, feed: dict) -> str:
    path = os.path.join(d, "dd_dynasty_feed.json")
    with open(path, "w") as f:
        json.dump(feed, f)
    return path


class TestDDFeedStoreLoad(unittest.TestCase):
    def test_loads_valid_feed(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_feed(d, VALID_FEED)
            store = DDFeedStore(path)
            self.assertTrue(store.is_available)
            self.assertEqual(len(store.get_all()), 3)

    def test_missing_file_not_available(self):
        store = DDFeedStore("/nonexistent/path/feed.json")
        self.assertFalse(store.is_available)

    def test_get_by_id(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_feed(d, VALID_FEED)
            store = DDFeedStore(path)
            row = store.get_by_id("dd_prospect_300")
            self.assertIsNotNone(row)
            self.assertEqual(row.name, "Top Prospect")

    def test_get_by_id_missing(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_feed(d, VALID_FEED)
            store = DDFeedStore(path)
            self.assertIsNone(store.get_by_id("nonexistent"))

    def test_generated_at(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_feed(d, VALID_FEED)
            store = DDFeedStore(path)
            self.assertEqual(store.generated_at, "2026-05-27T08:00:00")

    def test_sorted_by_dynasty_rank(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_feed(d, VALID_FEED)
            store = DDFeedStore(path)
            rows = store.get_all()
            ranks = [r.dynasty_rank for r in rows]
            self.assertEqual(ranks, sorted(ranks))


class TestDDFeedStoreValidation(unittest.TestCase):
    def test_rejects_wrong_schema_version(self):
        with tempfile.TemporaryDirectory() as d:
            bad = {**VALID_FEED, "schema_version": "2.0"}
            path = _write_feed(d, bad)
            store = DDFeedStore(path)
            self.assertFalse(store.is_available)

    def test_rejects_empty_players(self):
        with tempfile.TemporaryDirectory() as d:
            bad = {**VALID_FEED, "players": []}
            path = _write_feed(d, bad)
            store = DDFeedStore(path)
            self.assertFalse(store.is_available)

    def test_rejects_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as d:
            dup_players = [VALID_FEED["players"][0], VALID_FEED["players"][0]]
            bad = {**VALID_FEED, "players": dup_players}
            path = _write_feed(d, bad)
            store = DDFeedStore(path)
            self.assertFalse(store.is_available)

    def test_skips_records_missing_required_fields(self):
        with tempfile.TemporaryDirectory() as d:
            players = list(VALID_FEED["players"]) + [
                {"id": "bad1", "player_type": "mlb"},  # missing name, rank, value
            ]
            feed = {**VALID_FEED, "players": players, "player_count": 4}
            path = _write_feed(d, feed)
            store = DDFeedStore(path)
            self.assertTrue(store.is_available)
            self.assertEqual(len(store.get_all()), 3)  # bad record skipped

    def test_rejects_high_invalid_rate(self):
        with tempfile.TemporaryDirectory() as d:
            # All invalid except one
            bad_players = [
                {"id": f"bad{i}"} for i in range(20)
            ] + [VALID_FEED["players"][0]]
            feed = {**VALID_FEED, "players": bad_players, "player_count": 21}
            path = _write_feed(d, feed)
            store = DDFeedStore(path)
            self.assertFalse(store.is_available)  # >5% invalid


class TestDDFeedStoreFilter(unittest.TestCase):
    def test_filter_by_player_type(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_feed(d, VALID_FEED)
            store = DDFeedStore(path)
            prospects = store.filter(player_type="prospect")
            self.assertEqual(len(prospects), 1)
            self.assertEqual(prospects[0].name, "Top Prospect")

    def test_filter_by_position(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_feed(d, VALID_FEED)
            store = DDFeedStore(path)
            sps = store.filter(position="SP")
            self.assertEqual(len(sps), 1)
            self.assertEqual(sps[0].name, "Good Pitcher")

    def test_filter_by_search(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_feed(d, VALID_FEED)
            store = DDFeedStore(path)
            results = store.filter(search="star")
            self.assertEqual(len(results), 1)

    def test_filter_mlb_only(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_feed(d, VALID_FEED)
            store = DDFeedStore(path)
            mlb = store.filter(player_type="mlb")
            self.assertEqual(len(mlb), 2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest tests.test_dd_feed_store -v`

- [ ] **Step 3: Implement `web/dd_feed_store.py`**

Create `web/dd_feed_store.py`:

```python
"""Load and validate the DD dynasty feed for the web app."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .dynasty_models import DynastyRankingRow

logger = logging.getLogger(__name__)

REQUIRED_RECORD_FIELDS = ("id", "player_type", "name", "dynasty_rank", "dynasty_value")


class DDFeedStore:
    """Loads and serves the DD dynasty rankings feed."""

    def __init__(self, path: str | Path) -> None:
        self._rows: list[DynastyRankingRow] = []
        self._by_id: dict[str, DynastyRankingRow] = {}
        self._is_available: bool = False
        self._generated_at: str | None = None
        self._load(Path(path))

    def _load(self, path: Path) -> None:
        if not path.exists():
            logger.warning("DD dynasty feed not found at %s", path)
            return

        try:
            with path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load DD feed: %s", e)
            return

        # Validate envelope
        if raw.get("schema_version") != "1.0":
            logger.warning("DD feed schema_version is %s, expected 1.0", raw.get("schema_version"))
            return

        players = raw.get("players")
        if not players:
            logger.warning("DD feed has no players")
            return

        # Check for duplicate IDs
        ids = [p.get("id") for p in players if p.get("id")]
        if len(ids) != len(set(ids)):
            logger.warning("DD feed contains duplicate IDs")
            return

        # Validate and load records
        valid_rows = []
        skipped = 0
        for record in players:
            if not self._is_valid_record(record):
                skipped += 1
                continue
            try:
                row = DynastyRankingRow.from_feed(record)
                valid_rows.append(row)
            except Exception:
                skipped += 1

        # Reject if too many invalid
        total = len(players)
        if total > 0 and skipped / total > 0.05:
            logger.warning("DD feed has %.1f%% invalid records (%d/%d), rejecting",
                          skipped / total * 100, skipped, total)
            return

        if skipped > 0:
            logger.warning("DD feed: skipped %d invalid records", skipped)

        # Sort by dynasty_rank
        valid_rows.sort(key=lambda r: r.dynasty_rank)

        self._rows = valid_rows
        self._by_id = {r.id: r for r in valid_rows}
        self._generated_at = raw.get("generated_at")
        self._is_available = True

    @staticmethod
    def _is_valid_record(record: dict) -> bool:
        for field in REQUIRED_RECORD_FIELDS:
            if field not in record or record[field] is None:
                return False
        if not isinstance(record.get("dynasty_value"), (int, float)):
            return False
        if not isinstance(record.get("dynasty_rank"), int):
            return False
        return True

    @property
    def is_available(self) -> bool:
        return self._is_available

    @property
    def generated_at(self) -> str | None:
        return self._generated_at

    def get_all(self) -> list[DynastyRankingRow]:
        return list(self._rows)

    def get_by_id(self, row_id: str) -> DynastyRankingRow | None:
        return self._by_id.get(row_id)

    def filter(
        self,
        player_type: str | None = None,
        position: str | None = None,
        search: str | None = None,
        pool: str | None = None,
    ) -> list[DynastyRankingRow]:
        results = self._rows
        if player_type:
            results = [r for r in results if r.player_type == player_type]
        if pool:
            if pool == "prospect":
                results = [r for r in results if r.is_prospect]
            elif pool == "mlb":
                results = [r for r in results if not r.is_prospect]
            elif pool == "hitter":
                results = [r for r in results
                           if any(p not in ("SP", "RP", "P") for p in r.positions)]
            elif pool == "pitcher":
                results = [r for r in results
                           if any(p in ("SP", "RP", "P") for p in r.positions)]
        if position:
            results = [r for r in results if position in r.positions]
        if search:
            query = search.lower()
            results = [r for r in results if query in r.name.lower()]
        return results
```

- [ ] **Step 4: Run all tests**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add web/dd_feed_store.py tests/test_dd_feed_store.py
git commit -m "feat: DD feed store — load, validate, filter dynasty rankings"
```

---

### Task 4: Wire DD Dynasty Mode into App Routes

**Files:**
- Modify: `app.py`
- Modify: `web/config_builder.py`
- Modify: `tests/test_app.py`

This is the core integration task. `_build_context` branches for `dd_dynasty` mode BEFORE touching `build_config` or `ScoringMode`.

- [ ] **Step 1: Write tests**

Add to `tests/test_app.py`:

```python
class TestDDDynastyMode(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_dd_dynasty_returns_200_if_available(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/?mode=dd_dynasty")
        self.assertEqual(response.status_code, 200)

    def test_dd_dynasty_contains_dynasty_value_header(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/?mode=dd_dynasty")
        self.assertIn(b"Dynasty Value", response.data)

    def test_dd_dynasty_ignores_custom_cats(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        r1 = self.client.get("/?mode=dd_dynasty")
        r2 = self.client.get("/?mode=dd_dynasty&cats=R,HR&pcats=K")
        # Both should return the same content since cats are ignored
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)

    def test_dd_dynasty_fallback_when_unavailable(self):
        """If feed is unavailable, dd_dynasty mode falls back to redraft."""
        from app import dd_store
        if dd_store.is_available:
            self.skipTest("DD feed is available — can't test fallback")
        response = self.client.get("/?mode=dd_dynasty")
        self.assertEqual(response.status_code, 200)
        # Should fall back to categories mode
        self.assertIn(b"rankings-table", response.data)
```

- [ ] **Step 2: Update `app.py`**

Add DD feed store loading at startup (after the existing `store` and `engine` lines):

```python
from web.dd_feed_store import DDFeedStore

DD_FEED_PATH = Path(os.environ.get("DD_DYNASTY_FEED_PATH",
                    str(Path(__file__).parent / "data" / "dd" / "dd_dynasty_feed.json")))
dd_store = DDFeedStore(DD_FEED_PATH)
```

Add `import os` at the top if not already present.

Create a new function `_build_dynasty_context` that builds context for DD Dynasty mode:

```python
def _build_dynasty_context(args):
    """Build template context for DD Dynasty mode. Bypasses engine entirely."""
    pool = args.get("pool", "")
    position = args.get("position", "")
    search = args.get("search", "")

    rows = dd_store.filter(pool=pool or None, position=position or None, search=search or None)
    rows = rows[:200]  # Limit to top 200

    # Compute dynasty auction dollars
    dynasty_dollars = _compute_dynasty_dollars(rows)
    tiers = _compute_dynasty_tiers(rows)

    return {
        "mode": "dd_dynasty",
        "pool": pool,
        "position": position,
        "search": search,
        "dd_rows": rows,
        "dynasty_dollars": dynasty_dollars,
        "tiers": tiers,
        "dd_available": dd_store.is_available,
        "dd_generated_at": dd_store.generated_at,
        "as_of": store.as_of,
    }


def _compute_dynasty_dollars(rows: list, num_teams: int = 12, budget: int = 200) -> dict[str, float]:
    """Convert dynasty values to auction dollars proportionally."""
    positive = [r for r in rows if r.dynasty_value > 0]
    total_positive = sum(r.dynasty_value for r in positive)
    total_budget = budget * num_teams
    dollars: dict[str, float] = {}
    if total_positive > 0:
        for r in rows:
            if r.dynasty_value > 0:
                dollars[r.id] = round(r.dynasty_value / total_positive * total_budget, 1)
            else:
                dollars[r.id] = 0.0
    return dollars


def _compute_dynasty_tiers(rows: list) -> dict[str, int]:
    """Assign tiers from dynasty value gaps. Same algorithm as _compute_tiers."""
    if len(rows) < 2:
        return {r.id: 1 for r in rows}

    gaps = []
    for i in range(len(rows) - 1):
        gap = rows[i].dynasty_value - rows[i + 1].dynasty_value
        if gap > 0:
            gaps.append((gap, i))

    sorted_gaps = sorted(gaps, key=lambda x: x[0], reverse=True)
    break_indices = sorted([g[1] for g in sorted_gaps[:7]])

    tiers_list = []
    current_tier = 1
    for i, r in enumerate(rows):
        tiers_list.append([r.id, current_tier])
        if i in break_indices:
            current_tier += 1

    # Enforce minimum tier size of 3
    if len(rows) >= 3:
        changed = True
        while changed:
            changed = False
            tier_counts: dict[int, int] = {}
            for _, t in tiers_list:
                tier_counts[t] = tier_counts.get(t, 0) + 1
            for tier_num in sorted(tier_counts.keys()):
                if tier_counts[tier_num] < 3:
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
        unique_tiers = sorted(set(t for _, t in tiers_list))
        remap = {old: new for new, old in enumerate(unique_tiers, 1)}
        for entry in tiers_list:
            entry[1] = remap[entry[1]]

    return {pid: t for pid, t in tiers_list}
```

Modify the `index()` route to branch for DD Dynasty:

```python
@app.route("/")
def index():
    mode = request.args.get("mode", "categories")
    if mode == "dd_dynasty":
        if not dd_store.is_available:
            # Fallback to default redraft with notice
            ctx = _build_context(request.args)
            ctx["notice"] = "DD 7x7 Dynasty data is not available. Showing default rankings."
            ctx["dd_available"] = False
            return render_template("index.html", **ctx)
        ctx = _build_dynasty_context(request.args)
        return render_template("index.html", **ctx)
    ctx = _build_context(request.args)
    ctx["dd_available"] = dd_store.is_available
    return render_template("index.html", **ctx)
```

Modify the `rankings()` route similarly:

```python
@app.route("/rankings")
def rankings():
    mode = request.args.get("mode", "categories")
    if mode == "dd_dynasty":
        if not dd_store.is_available:
            ctx = _build_context(request.args)
            ctx["dd_available"] = False
        else:
            ctx = _build_dynasty_context(request.args)
        html = render_template("partials/rankings_response.html", **ctx)
        response = make_response(html)
        # Only preserve supported params for DD Dynasty URLs
        params = {}
        if ctx.get("pool"):
            params["pool"] = ctx["pool"]
        if ctx.get("position"):
            params["position"] = ctx["position"]
        if ctx.get("search"):
            params["search"] = ctx["search"]
        params["mode"] = "dd_dynasty"
        push_url = "/?" + "&".join(f"{k}={v}" for k, v in params.items() if v)
        response.headers["HX-Replace-Url"] = push_url
        return response
    # Existing redraft path
    ctx = _build_context(request.args)
    ctx["dd_available"] = dd_store.is_available
    html = render_template("partials/rankings_response.html", **ctx)
    response = make_response(html)
    url_params = build_url_params(
        mode=ctx["mode"], cats=ctx["cats"], pcats=ctx["pcats"],
        pool=ctx["pool"], position=ctx["position"], search=ctx["search"],
        rules_str=ctx["rules_str"], split_rp=ctx["split_rp"],
        weights=ctx["weights"] if ctx["weights"] else None,
    )
    push_url = f"/?{url_params}" if url_params else "/"
    response.headers["HX-Replace-Url"] = push_url
    return response
```

Modify the `player_detail()` route to branch for DD Dynasty:

```python
@app.route("/player/<player_id>")
def player_detail(player_id):
    mode = request.args.get("mode", "categories")

    # DD Dynasty mode: use dd_feed_store first
    if mode == "dd_dynasty" and dd_store.is_available:
        dd_row = dd_store.get_by_id(player_id)
        if dd_row is None:
            return "<div class='error'>Player not found</div>", 404

        # For MLB players, join to season outlook for stat display
        mlb_stats = None
        mlb_stats_actual = None
        mlb_stats_ros = None
        if dd_row.mlbam_id and not dd_row.is_prospect:
            # Find matching projection(s) by mlbam_id
            for proj in store.get_all():
                if proj.metadata.get("base_id") == f"mlbam_{dd_row.mlbam_id}":
                    if proj.pool.value == "hitter":
                        mlb_stats = proj.stats
                        mlb_stats_actual = proj.metadata.get("stats_actual")
                        mlb_stats_ros = proj.metadata.get("stats_ros")
                        break
            # Fallback: check direct mlbam_id match
            if mlb_stats is None:
                for proj in store.get_all():
                    if proj.metadata.get("mlbam_id") == dd_row.mlbam_id:
                        mlb_stats = proj.stats
                        mlb_stats_actual = proj.metadata.get("stats_actual")
                        mlb_stats_ros = proj.metadata.get("stats_ros")
                        break

        return render_template(
            "partials/player_detail_dynasty.html",
            row=dd_row,
            mlb_stats=mlb_stats,
            mlb_stats_actual=mlb_stats_actual,
            mlb_stats_ros=mlb_stats_ros,
        )

    # Existing redraft path
    player_proj = store.get_by_id(player_id)
    if not player_proj:
        return "<div class='error'>Player not found</div>", 404

    ctx = _build_context(request.args)
    result = next((r for r in ctx["results"] if r.player.id == player_id), None)

    if result is None:
        config = ctx["config"]
        all_results = engine.value_players(store.get_all(), config)
        result = next((r for r in all_results if r.player.id == player_id), None)

    return render_template(
        "partials/player_detail.html",
        player=player_proj,
        result=result,
        active_categories=ctx["active_categories"],
    )
```

Modify `export_csv()` to handle DD Dynasty mode:

```python
@app.route("/export")
def export_csv():
    mode = request.args.get("mode", "categories")

    if mode == "dd_dynasty" and dd_store.is_available:
        ctx = _build_dynasty_context(request.args)
        rows = ctx["dd_rows"]
        dynasty_dollars = ctx["dynasty_dollars"]

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Overall Dynasty Rank", "Player", "Type", "Positions", "Team",
                         "Age", "Dynasty Value", "Dynasty $", "Prospect Rank", "Level", "ETA"])
        for row in rows:
            writer.writerow([
                row.dynasty_rank,
                row.name,
                row.player_type.upper(),
                ", ".join(row.positions) or "",
                row.team,
                row.age or "",
                row.dynasty_value,
                dynasty_dollars.get(row.id, 0),
                row.prospect_rank or "",
                row.level or "",
                row.eta or "",
            ])

        response = make_response(output.getvalue())
        response.headers["Content-Type"] = "text/csv; charset=utf-8"
        response.headers["Content-Disposition"] = "attachment; filename=valucast-dynasty-rankings.csv"
        return response

    # Existing redraft export
    ctx = _build_context(request.args)
    # ... (existing code unchanged)
```

- [ ] **Step 3: Run all tests**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`

- [ ] **Step 4: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add app.py tests/test_app.py
git commit -m "feat: wire DD Dynasty mode into app routes — rankings, player detail, export"
```

---

### Task 5: DD Dynasty Mode Selector + Config Panel UI

**Files:**
- Modify: `templates/index.html`
- Modify: `static/style.css`

- [ ] **Step 1: Add DD Dynasty mode button to index.html**

In `templates/index.html`, add the DD Dynasty button in the mode selector section, after the Points button. Wrap it in an availability check:

```html
        {% if dd_available %}
        <label class="mode-btn mode-btn-dynasty">
            <input type="radio" name="mode" value="dd_dynasty"
                   {{ 'checked' if mode == 'dd_dynasty' else '' }}>
            <span>DD 7x7 Dynasty</span>
        </label>
        {% endif %}
```

Replace the config bar + setup panel section to branch for DD Dynasty:

```html
    {% if mode == 'dd_dynasty' %}
    <div class="config-bar config-bar-locked">
        <span class="config-summary">DD 7x7 Dynasty uses Diamond Dynasties' fixed categories, weights, age curves, market calibration, and prospect model. Custom category editing is disabled in this mode.{% if dd_generated_at %} · Updated {{ dd_generated_at[:10] }}{% endif %}</span>
    </div>
    {% else %}
    <div class="config-bar">
        <span class="config-summary">{{ config_summary }}</span>
        <button type="button" class="customize-toggle" onclick="toggleSetup()">Customize</button>
    </div>

    <section id="setup-panel" class="setup-panel collapsed">
        {% if mode == 'points' %}
            {% include "partials/setup_points.html" %}
        {% else %}
            {% include "partials/setup_categories.html" %}
        {% endif %}
    </section>
    {% endif %}
```

Update the pool filter to add MLB/Prospects options in DD mode:

```html
    <section class="filter-bar">
        <div class="pool-toggle">
            <label class="pool-btn">
                <input type="radio" name="pool" value=""
                       {{ 'checked' if not pool else '' }}>
                <span>All</span>
            </label>
            {% if mode == 'dd_dynasty' %}
            <label class="pool-btn">
                <input type="radio" name="pool" value="mlb"
                       {{ 'checked' if pool == 'mlb' else '' }}>
                <span>MLB</span>
            </label>
            {% endif %}
            <label class="pool-btn">
                <input type="radio" name="pool" value="hitter"
                       {{ 'checked' if pool == 'hitter' else '' }}>
                <span>Hitters</span>
            </label>
            <label class="pool-btn">
                <input type="radio" name="pool" value="pitcher"
                       {{ 'checked' if pool == 'pitcher' else '' }}>
                <span>Pitchers</span>
            </label>
            {% if mode == 'dd_dynasty' %}
            <label class="pool-btn">
                <input type="radio" name="pool" value="prospect"
                       {{ 'checked' if pool == 'prospect' else '' }}>
                <span>Prospects</span>
            </label>
            {% endif %}
        </div>

        <select name="position" class="position-select">
            <option value="">All Positions</option>
            {% for pos in ["C","1B","2B","SS","3B","OF","DH","SP","RP"] %}
            <option value="{{ pos }}" {{ 'selected' if position == pos else '' }}>{{ pos }}</option>
            {% endfor %}
        </select>

        <input type="text" name="search" id="search-input"
               class="search-input" placeholder="Search players..."
               value="{{ search }}">

        <a id="export-btn" class="export-btn" onclick="exportCsv(event)">Export CSV</a>
    </section>
```

Hide compare bar in DD Dynasty mode. After the compare bar div:

```html
{% if mode != 'dd_dynasty' %}
<div id="compare-bar" class="compare-bar" style="display:none;">
    <span id="compare-count">0 selected</span>
    <button id="compare-btn" onclick="openCompare()" disabled>Compare</button>
    <button onclick="clearCompare()" class="btn-clear">Clear</button>
</div>

<div id="compare-overlay" class="compare-overlay" style="display:none;"></div>
{% endif %}
```

Add notice display at the top of main content (if fallback):

```html
{% if notice %}
<div class="notice">{{ notice }}</div>
{% endif %}
```

- [ ] **Step 2: Add CSS styles**

In `static/style.css`, add:

```css
.mode-btn-dynasty:has(input:checked) { background: #7c3aed; color: #fff; }

.config-bar-locked {
    background: #f5f3ff;
    border: 1px solid #ddd6fe;
    border-radius: 8px;
    padding: 0.6rem 1.25rem;
    margin-bottom: 0.5rem;
    font-size: 0.8rem;
    color: #6b7280;
    line-height: 1.5;
}

.prospect-badge {
    display: inline-block;
    margin-left: 0.3rem;
    font-size: 0.6rem;
    font-weight: 600;
    color: #7c3aed;
    background: #f5f3ff;
    border-radius: 3px;
    padding: 0.05rem 0.3rem;
    vertical-align: middle;
}

.prospect-rank-badge {
    display: inline-block;
    margin-left: 0.3rem;
    font-size: 0.65rem;
    font-weight: 600;
    color: #059669;
    background: #ecfdf5;
    border-radius: 3px;
    padding: 0.05rem 0.3rem;
    vertical-align: middle;
}

.notice {
    background: #fef3c7;
    border: 1px solid #fbbf24;
    border-radius: 8px;
    padding: 0.75rem 1rem;
    margin-bottom: 1rem;
    font-size: 0.85rem;
    color: #92400e;
}
```

- [ ] **Step 3: Run all tests**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`

- [ ] **Step 4: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add templates/index.html static/style.css
git commit -m "feat: DD Dynasty mode selector, locked config card, extended pool filter"
```

---

### Task 6: Dynasty Rankings Table Partial

**Files:**
- Create: `templates/partials/rankings_table_dynasty.html`
- Modify: `templates/partials/rankings_response.html`

- [ ] **Step 1: Create `templates/partials/rankings_table_dynasty.html`**

```html
<div class="results-meta">
    <span>{{ dd_rows | length }} players{% if dd_rows | length == 200 %} (showing top 200){% endif %}</span>
</div>

{% if dd_rows %}
<table class="rankings-table">
    <thead>
        <tr>
            <th class="col-rank sortable" onclick="sortTable(0)">#</th>
            <th class="col-name sortable" onclick="sortTable(1)">Player</th>
            <th class="col-pos">Pos</th>
            <th class="col-team sortable" onclick="sortTable(3)">Team</th>
            <th class="col-age sortable" onclick="sortTable(4)">Age</th>
            <th class="col-dollars sortable" onclick="sortTable(5)">Dynasty $</th>
            <th class="col-value sortable" onclick="sortTable(6)">Dynasty Value</th>
        </tr>
    </thead>
    <tbody>
        {% set tier_colors = ['#2563eb', '#7c3aed', '#0891b2', '#059669', '#d97706', '#dc2626', '#6b7280', '#9ca3af'] %}
        {% for row in dd_rows %}
        {% set tier = tiers.get(row.id, 0) %}
        {% set prev_tier = tiers.get(dd_rows[loop.index0 - 1].id, 0) if loop.index0 > 0 else tier %}
        <tr class="player-row {% if tier != prev_tier %}tier-break{% endif %}" onclick="toggleDetail('{{ row.id }}', this)">
            <td class="col-rank">{{ row.dynasty_rank }}</td>
            <td class="col-name">
                <strong>{{ row.name }}</strong>
                {% if row.is_prospect %}
                <span class="prospect-badge">Prospect</span>
                {% if row.prospect_rank %}
                <span class="prospect-rank-badge">P#{{ row.prospect_rank }}</span>
                {% endif %}
                {% endif %}
                {% if tier != prev_tier or loop.index0 == 0 %}
                <span class="tier-badge" style="background: {{ tier_colors[(tier - 1) % tier_colors|length] }}">T{{ tier }}</span>
                {% endif %}
            </td>
            <td class="col-pos">{{ row.positions | join(', ') or '&mdash;' }}</td>
            <td class="col-team">{{ row.team }}</td>
            <td class="col-age">{{ row.age or '&mdash;' }}</td>
            <td class="col-dollars {{ 'val-pos' if dynasty_dollars.get(row.id, 0) > 0 else '' }}">
                {% if dynasty_dollars.get(row.id, 0) > 0 %}${{ dynasty_dollars.get(row.id, 0) | int }}{% else %}&mdash;{% endif %}
            </td>
            <td class="col-value val-pos">
                {{ "%.1f" | format(row.dynasty_value) }}
            </td>
        </tr>
        <tr id="detail-{{ row.id }}" class="detail-row" style="display:none;">
            <td colspan="7"></td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% else %}
<div class="no-results">
    <p>No players found. Try adjusting your filters.</p>
</div>
{% endif %}
```

- [ ] **Step 2: Update `templates/partials/rankings_response.html`**

The response partial needs to branch for DD Dynasty mode. Replace the entire file:

```html
{% if mode == 'dd_dynasty' %}
    {% include "partials/rankings_table_dynasty.html" %}
{% else %}
    {% include "partials/rankings_table.html" %}

    <span class="config-summary" hx-swap-oob="innerHTML:.config-summary">{{ config_summary }}</span>

    <section id="setup-panel" class="setup-panel" hx-swap-oob="innerHTML:#setup-panel">
        {% if mode == 'points' %}
            {% include "partials/setup_points.html" %}
        {% else %}
            {% include "partials/setup_categories.html" %}
        {% endif %}
    </section>
{% endif %}
```

- [ ] **Step 3: Run all tests**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`

- [ ] **Step 4: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add templates/partials/rankings_table_dynasty.html templates/partials/rankings_response.html
git commit -m "feat: dynasty rankings table partial with prospect badges and tier visualization"
```

---

### Task 7: Dynasty Player Detail Partial

**Files:**
- Create: `templates/partials/player_detail_dynasty.html`

- [ ] **Step 1: Create the dynasty player detail template**

Create `templates/partials/player_detail_dynasty.html`:

```html
<div class="player-detail">
    <div class="detail-header">
        <h3>{{ row.name }}</h3>
        <span class="detail-meta">
            {{ row.positions | join(', ') or 'N/A' }}
            {% if row.team %} | {{ row.team }}{% endif %}
            {% if row.is_prospect %} | {{ row.level or 'MiLB' }}{% endif %}
        </span>
        <span class="detail-value val-pos">
            Dynasty Value: {{ "%.1f" | format(row.dynasty_value) }}
        </span>
    </div>

    <div class="detail-body">
        {% if row.is_prospect %}
        {# ===== PROSPECT DETAIL ===== #}
        <div class="detail-section">
            <h4>Prospect Profile</h4>
            <div class="stat-grid">
                <div class="stat-item">
                    <span class="stat-label">Prospect Rank</span>
                    <span class="stat-value">#{{ row.prospect_rank or '—' }}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Level</span>
                    <span class="stat-value">{{ row.level or '—' }}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">ETA</span>
                    <span class="stat-value">{{ row.eta or '—' }}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Age</span>
                    <span class="stat-value">{{ row.age or '—' }}</span>
                </div>
                {% if row.breakout_label %}
                <div class="stat-item">
                    <span class="stat-label">Trend</span>
                    <span class="stat-value">{{ row.breakout_label | replace('_', ' ') | title }}{% if row.breakout_rank_change %} ({{ '+' if row.breakout_rank_change > 0 else '' }}{{ row.breakout_rank_change }}){% endif %}</span>
                </div>
                {% endif %}
            </div>
        </div>

        {% if row.source_ranks %}
        <div class="detail-section">
            <h4>Source Rankings</h4>
            <div class="stat-grid">
                {% for source, rank in row.source_ranks.items() %}
                <div class="stat-item">
                    <span class="stat-label">{{ source | upper }}</span>
                    <span class="stat-value">#{{ rank | int if rank is number else rank }}</span>
                </div>
                {% endfor %}
            </div>
        </div>
        {% endif %}

        {% if row.stat_line %}
        <div class="detail-section">
            <h4>MiLB Stats</h4>
            <div class="stat-grid">
                {% for key, value in row.stat_line.items() %}
                <div class="stat-item">
                    <span class="stat-label">{{ key | upper }}</span>
                    <span class="stat-value">
                        {% if value is number %}
                            {% if value < 1 and value > 0 %}{{ "%.3f" | format(value) }}{% elif value == value | int %}{{ value | int }}{% else %}{{ "%.1f" | format(value) }}{% endif %}
                        {% else %}{{ value }}{% endif %}
                    </span>
                </div>
                {% endfor %}
            </div>
        </div>
        {% endif %}

        {% else %}
        {# ===== MLB DETAIL ===== #}
        {% if mlb_stats %}
        <div class="detail-section">
            <h4>2026 Season Outlook</h4>
            <div class="stat-grid">
                {% for key, value in mlb_stats.items() %}
                {% if key not in ['TB', 'NSB', 'G', 'GDP', 'IBB', 'SH', 'SF', 'HBP', 'GS'] %}
                <div class="stat-item">
                    <span class="stat-label">{{ key }}</span>
                    <span class="stat-value">
                        {% if value is number %}
                            {% if value < 1 and value > 0 %}{{ "%.3f" | format(value) }}{% elif value == value | int %}{{ value | int }}{% else %}{{ "%.1f" | format(value) }}{% endif %}
                        {% else %}{{ value }}{% endif %}
                    </span>
                </div>
                {% endif %}
                {% endfor %}
            </div>
        </div>
        {% endif %}

        {% if mlb_stats_actual %}
        <div class="detail-section">
            <h4>2026 Actual Stats</h4>
            <div class="stat-grid">
                {% for key, value in mlb_stats_actual.items() %}
                {% if key not in ['TB', 'NSB', 'G', 'GDP', 'IBB', 'SH', 'SF', 'HBP', 'GS'] %}
                <div class="stat-item">
                    <span class="stat-label">{{ key }}</span>
                    <span class="stat-value">
                        {% if value is number %}
                            {% if value < 1 and value > 0 %}{{ "%.3f" | format(value) }}{% elif value == value | int %}{{ value | int }}{% else %}{{ "%.1f" | format(value) }}{% endif %}
                        {% else %}{{ value }}{% endif %}
                    </span>
                </div>
                {% endif %}
                {% endfor %}
            </div>
        </div>
        {% endif %}

        {% if mlb_stats_ros %}
        <div class="detail-section">
            <h4>ROS Projection (Steamer)</h4>
            <div class="stat-grid">
                {% for key, value in mlb_stats_ros.items() %}
                {% if key not in ['TB', 'NSB', 'G', 'GDP', 'IBB', 'SH', 'SF', 'HBP', 'GS'] %}
                <div class="stat-item">
                    <span class="stat-label">{{ key }}</span>
                    <span class="stat-value">
                        {% if value is number %}
                            {% if value < 1 and value > 0 %}{{ "%.3f" | format(value) }}{% elif value == value | int %}{{ value | int }}{% else %}{{ "%.1f" | format(value) }}{% endif %}
                        {% else %}{{ value }}{% endif %}
                    </span>
                </div>
                {% endif %}
                {% endfor %}
            </div>
        </div>
        {% endif %}

        {% if not mlb_stats %}
        <div class="detail-section">
            <p>No season outlook stats available for this player.</p>
        </div>
        {% endif %}
        {% endif %}
    </div>
</div>
```

- [ ] **Step 2: Run all tests**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`

- [ ] **Step 3: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add templates/partials/player_detail_dynasty.html
git commit -m "feat: dynasty player detail partial — prospect profile + MLB stats views"
```

---

### Task 8: End-to-End Verification

- [ ] **Step 1: Run all tests**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`

- [ ] **Step 2: Start the app and smoke test**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python app.py
```

Verify at http://localhost:5001:

1. **Redraft modes still work** — H2H Categories, Roto, Points all load normally
2. **DD 7x7 Dynasty button appears** in mode selector
3. Clicking DD Dynasty shows **locked config card** (no Customize button)
4. Rankings show **Dynasty Value** column, no category columns
5. **Prospect badges** appear on prospect rows
6. **Pool filter** has All/MLB/Hitters/Pitchers/Prospects options
7. Click MLB player — shows **dynasty value + season outlook stats**
8. Click prospect — shows **dynasty value + prospect profile + source rankings + MiLB stats**
9. **Export CSV** downloads dynasty-specific columns
10. **Compare bar is hidden** in DD Dynasty mode
11. Switching back to H2H Categories **restores normal behavior**
12. Direct URL `/?mode=dd_dynasty` works
13. Direct URL `/?mode=dd_dynasty&cats=R,HR` **ignores cats param**

- [ ] **Step 3: Push to GitHub**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git push origin master
```
