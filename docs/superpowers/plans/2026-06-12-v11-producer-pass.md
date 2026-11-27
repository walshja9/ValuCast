# ValuCast v1.1 Producer Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **For Codex:** implement Tasks 1–10 and return the complete diff. Do NOT commit, do NOT regenerate the feed, do NOT run network calls — Fable gates, regenerates, and ships (Task 11).

**Goal:** The deferred v1.1 producer bucket: per-player dynasty-value line charts (30-day history), real MLB stat lines on call-up prospect cards, level-adjusted (MLB-equivalent) peripherals, mlbam_id fill for prospects, and defensive optional-field coercion — across the DD producer and the ValuCast consumer.

**Architecture:** DD's `generate_valucast_feed.py` is enriched with four new optional fields (`value_history`, `mlb_stat_line`, `stat_line_translated`, populated `mlbam_id`) reusing DD's existing epoch-hygiene, twin-guard, and translation machinery — no new models. ValuCast's `DynastyRankingRow` gains coerced optional fields, and three new card surfaces render them server-side (no JS): an SVG sparkline partial, a 2026-MLB stat grid for call-ups, and an MLB-equivalent peripherals block.

**Tech Stack:** Python 3.11, Flask/Jinja2 (ValuCast), plain dataclasses, unittest (VC) / pytest (DD). No new dependencies.

**Two repos:**
- DD = `C:/Users/Alex/DiamondDynastiesTradeAnalyzer`
- VC = `C:/Users/Alex/Documents/Codex/2026-05-18/league-values`

**Hard constraints (same as the launch-polish pass):**
1. VC web app NEVER fetches network at runtime — committed feed artifact only.
2. Honesty: never invent values. Translated peripherals are displayed as values with MLB-average anchors, NOT percentiles (regression shrinkage compresses small samples toward the mean — percentiling shrunk values misleads). The raw percentile pool keeps its level-blind math but gains an "(all levels)" caveat label.
3. Mobile 390px must work for every new surface.
4. Sparkline history must be the epoch-masked series (`player_trends._mask_rebaseline_steps`) over anomaly-filtered snapshots — administrative re-baselines are NOT player movement. Reuse DD's functions; do not reimplement masking.
5. All joins DD-side use the twin-guarded APIs (`get_milb_stat_history(name, role=, age=)`, `get_player_season_stats(name, type, team=)` with team passed). Never bare-name joins.
6. ASCII-safe source: NO unicode middots/em-dashes in NEW Python/JS strings (templates may use `·` ONLY inside existing HTML text conventions). Known executor failure mode: cp1252-mojibake bytes — write plain ASCII separators in code.
7. New feed fields are OPTIONAL — DDFeedStore/from_feed must accept their absence (back-compat with the committed 1.0 feed until regen).
8. Tests mandatory for every task; VC suite must stay green (798 + new).

---

## File Map

| Repo | File | Change |
|---|---|---|
| DD | `generate_valucast_feed.py` | + `attach_value_histories`, `_mlb_stat_line`, prospect mlbam/translation enrichment, schema 1.1, compact JSON, validation |
| DD | `milb_translation.py` | + `"mlb_avg"` in each `stats[]` entry (one line) |
| DD | `tests/test_valucast_feed_v11.py` | NEW — producer unit tests |
| VC | `web/dynasty_models.py` | + 3 fields, + coercion helpers in `from_feed` |
| VC | `web/value_spark.py` | NEW — pure sparkline geometry |
| VC | `templates/partials/_value_spark.html` | NEW — SVG partial |
| VC | `templates/partials/player_detail_dynasty.html` | + spark include (both branches), + MLB stat grid (prospect branch), + translated block, + "(all levels)" label |
| VC | `app.py` | + `build_spark` wiring into dynasty/prospect card context |
| VC | `static/style.css` | + spark/translated-block styles |
| VC | `tests/test_v11_feed.py` | NEW — coercion, spark, card integration |

---

### Task 1 (DD): Producer — attach epoch-masked value history

**Files:**
- Modify: `C:/Users/Alex/DiamondDynastiesTradeAnalyzer/generate_valucast_feed.py`
- Test: `C:/Users/Alex/DiamondDynastiesTradeAnalyzer/tests/test_valucast_feed_v11.py` (NEW)

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the v1.1 feed enrichments in generate_valucast_feed."""
import json

import pytest

import generate_valucast_feed as gvf


def _write_snap(dir_, date_str, players):
    (dir_ / f"{date_str}.json").write_text(
        json.dumps({"date": date_str, "players": players}), encoding="utf-8")


def test_attach_value_histories_masks_and_pairs(tmp_path, monkeypatch):
    # Synthetic snapshot dir routed through player_trends (April dates avoid
    # the real REBASELINE_DATES so values pass through unmasked).
    import player_trends
    monkeypatch.setattr(player_trends, "SNAPSHOTS_DIR", tmp_path)
    _write_snap(tmp_path, "2026-04-01", {"Test Hitter": {"v": 50.0, "t": "B"}})
    _write_snap(tmp_path, "2026-04-02", {"Test Hitter": {"v": 52.0, "t": "B"}})
    _write_snap(tmp_path, "2026-04-03", {"Test Hitter": {"v": 51.5, "t": "B"},
                                         "Solo Point": {"v": 10.0, "t": "D"}})

    records = [
        {"name": "Test Hitter", "mlb_team": "NYY"},
        {"name": "Solo Point", "mlb_team": "BOS"},   # 1 point -> no history
        {"name": "Missing Guy", "mlb_team": "TOR"},  # 0 points -> no history
    ]
    gvf.attach_value_histories(records, days=10)

    assert records[0]["value_history"] == [
        ["2026-04-01", 50.0], ["2026-04-02", 52.0], ["2026-04-03", 51.5]]
    assert "value_history" not in records[1]
    assert "value_history" not in records[2]
```

- [ ] **Step 2: Run test to verify it fails**

Run (Git Bash, DD repo): `python -m pytest tests/test_valucast_feed_v11.py -q`
Expected: FAIL — `AttributeError: module 'generate_valucast_feed' has no attribute 'attach_value_histories'`

- [ ] **Step 3: Implement `attach_value_histories`**

Add after `load_prospect_players` in `generate_valucast_feed.py`:

```python
# ---------------------------------------------------------------------------
# Step 2.5: dynasty-value history from daily snapshots (v1.1)
# ---------------------------------------------------------------------------
SPARK_DAYS = 30


def attach_value_histories(records: list, days: int = SPARK_DAYS) -> None:
    """Attach per-player dynasty-value history from DD's daily snapshots.

    Reuses DD's epoch hygiene wholesale: _get_snapshot_dates filters the
    anomalous-snapshot denylist, find_snapshot_entry resolves team-qualified
    same-name keys, _mask_rebaseline_steps re-expresses pre-re-baseline
    history in the current epoch's frame (administrative model steps are not
    player movement). Emits compact [[date, value], ...] pairs, oldest first,
    only when 2+ points survive masking.
    """
    sys.path.insert(0, BASE_DIR)
    from player_trends import (  # noqa: PLC0415
        _get_snapshot_dates,
        _load_snapshot,
        _mask_rebaseline_steps,
    )
    from value_snapshots import find_snapshot_entry  # noqa: PLC0415

    dates = list(reversed(_get_snapshot_dates(limit=days)))  # chronological
    snaps = [(d, _load_snapshot(d).get("players", {})) for d in dates]
    attached = 0
    for rec in records:
        history = []
        for date_str, players in snaps:
            # Fast path: plain-name key covers the no-collision majority;
            # find_snapshot_entry handles "Name|TEAM" qualified keys.
            entry = players.get(rec["name"]) or find_snapshot_entry(
                players, rec["name"], rec.get("mlb_team"))
            if isinstance(entry, dict) and entry.get("v") is not None:
                history.append({"date": date_str, "value": float(entry["v"])})
        history = _mask_rebaseline_steps(history)
        if len(history) >= 2:
            rec["value_history"] = [
                [h["date"], round(h["value"], 1)] for h in history]
            attached += 1
    print(f"  Attached value_history to {attached}/{len(records)} records "
          f"({len(snaps)} snapshot days).")
```

In `build_feed()`, call it right after the `prospect_rank` assignment loop:

```python
    print("Attaching value histories from snapshots ...")
    attach_value_histories(all_records)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_valucast_feed_v11.py -q`
Expected: 1 passed

---

### Task 2 (DD): Producer — mlbam_id + translated peripherals for prospects

**Files:**
- Modify: `C:/Users/Alex/DiamondDynastiesTradeAnalyzer/generate_valucast_feed.py` (inside `load_prospect_players`)
- Modify: `C:/Users/Alex/DiamondDynastiesTradeAnalyzer/milb_translation.py:113-116`
- Test: `C:/Users/Alex/DiamondDynastiesTradeAnalyzer/tests/test_valucast_feed_v11.py`

- [ ] **Step 1: Add `mlb_avg` to translation output (milb_translation.py)**

In `translate_peripherals`, the `out_stats.append({...})` at lines 113-116 gains one key — the spec's MLB mean, so consumers can anchor the displayed value without duplicating model constants:

```python
        out_stats.append({
            "key": key, "label": label, "fmt": fmt,
            "milb": round(milb_raw, dp), "mlb": round(mlb_equiv, dp),
            "mlb_avg": mean,
        })
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_valucast_feed_v11.py`:

```python
def test_prospect_enrichment_uses_twin_guarded_history(monkeypatch):
    calls = {}

    def fake_history(name, role=None, age=None):
        calls["args"] = (name, role, age)
        return [{"season": 2026, "level": "AA", "mlbam_id": "806954",
                 "role": "hitter", "plate_appearances": 200,
                 "k_pct": 27.2, "bb_pct": 9.1, "iso": 0.214}]

    monkeypatch.setattr(gvf, "_prospect_history_rows", fake_history)
    rows = gvf._prospect_history_rows("Colt Emerson", role="hitter", age=20)
    mlbam, translated = gvf._prospect_milb_extras(rows, "hitter")

    assert calls["args"] == ("Colt Emerson", "hitter", 20)
    assert mlbam == "806954"
    assert translated["role"] == "hitter"
    assert {s["key"] for s in translated["stats"]} == {"k_pct", "bb_pct", "iso"}
    assert all("mlb_avg" in s for s in translated["stats"])
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_valucast_feed_v11.py -q`
Expected: FAIL — no attribute `_prospect_history_rows`

- [ ] **Step 4: Implement the enrichment helpers + wire into the prospect loop**

Add module-level helpers in `generate_valucast_feed.py` (above `load_prospect_players`):

```python
def _prospect_history_rows(name: str, role: str | None = None,
                           age: int | None = None) -> list:
    """Twin-guarded MiLB history rows (newest first). Thin seam for tests."""
    sys.path.insert(0, BASE_DIR)
    from milb_stat_history import get_milb_stat_history  # noqa: PLC0415
    return get_milb_stat_history(name, role=role, age=age)


def _prospect_milb_extras(rows: list, role: str) -> tuple:
    """(mlbam_id, stat_line_translated) from already-fetched history rows."""
    sys.path.insert(0, BASE_DIR)
    from milb_translation import translate_peripherals  # noqa: PLC0415
    mlbam = next((r.get("mlbam_id") for r in rows if r.get("mlbam_id")), None)
    translated = translate_peripherals(rows, role) if rows else None
    return mlbam, translated
```

Inside `load_prospect_players`, in the per-prospect loop right before `records.append(...)`:

```python
        role = ("pitcher" if any(pos in ("SP", "RP", "P")
                                 for pos in (p.get("positions") or []))
                else "hitter")
        history_rows = _prospect_history_rows(p["name"], role=role,
                                              age=p.get("age"))
        mlbam_id, translated = _prospect_milb_extras(history_rows, role)
```

And in the appended record dict, replace `"mlbam_id": None,` with `"mlbam_id": mlbam_id,` and add after `"stat_line": stat_line,`:

```python
                **({"stat_line_translated": translated} if translated else {}),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_valucast_feed_v11.py -q`
Expected: 2 passed

---

### Task 3 (DD): Producer — 2026 MLB stat line for call-up prospects

**Files:**
- Modify: `C:/Users/Alex/DiamondDynastiesTradeAnalyzer/generate_valucast_feed.py`
- Test: `C:/Users/Alex/DiamondDynastiesTradeAnalyzer/tests/test_valucast_feed_v11.py`

- [ ] **Step 1: Write the failing test**

```python
def test_mlb_stat_line_maps_fantrax_keys(monkeypatch):
    def fake_stats(name, player_type=None, team=None):
        assert team == "SEA"  # team MUST be passed (same-name guard)
        if player_type == "hitter":
            return {"PA": 81, "AB": 75, "AVG": 0.296, "OPS": 0.753, "HR": 1.0,
                    "RBI": 9.0, "R": 12.0, "SB": 4.0, "G": 22}
        return None

    monkeypatch.setattr(gvf, "_season_stats", fake_stats)
    line = gvf._mlb_stat_line("Colt Emerson", "SEA", "hitter")
    assert line == {"pa": 81, "avg": 0.296, "ops": 0.753, "hr": 1,
                    "rbi": 9, "r": 12, "sb": 4}
    assert gvf._mlb_stat_line("Nobody", "SEA", "hitter") is None
```

(The second call returns None because `fake_stats` returns None for pitcher
lookups and the test monkeypatches both calls through `_season_stats` — for
"Nobody" the hitter branch asserts team then returns the dict; adjust:
make `fake_stats` return None unless `name == "Colt Emerson"`.)

Use this exact final version:

```python
def test_mlb_stat_line_maps_fantrax_keys(monkeypatch):
    def fake_stats(name, player_type=None, team=None):
        assert team == "SEA"  # team MUST be passed (same-name guard)
        if name == "Colt Emerson" and player_type == "hitter":
            return {"PA": 81, "AB": 75, "AVG": 0.296, "OPS": 0.753, "HR": 1.0,
                    "RBI": 9.0, "R": 12.0, "SB": 4.0, "G": 22}
        return None

    monkeypatch.setattr(gvf, "_season_stats", fake_stats)
    assert gvf._mlb_stat_line("Colt Emerson", "SEA", "hitter") == {
        "pa": 81, "avg": 0.296, "ops": 0.753, "hr": 1, "rbi": 9, "r": 12, "sb": 4}
    assert gvf._mlb_stat_line("Nobody", "SEA", "hitter") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_valucast_feed_v11.py -q`
Expected: FAIL — no attribute `_season_stats`

- [ ] **Step 3: Implement**

```python
# Fantrax stats key -> feed key. Rates keep 3dp, ip 1dp, counters int.
_HITTER_LINE = (("pa", "PA"), ("avg", "AVG"), ("ops", "OPS"), ("hr", "HR"),
                ("rbi", "RBI"), ("r", "R"), ("sb", "SB"))
_PITCHER_LINE = (("ip", "IP"), ("era", "ERA"), ("whip", "WHIP"), ("k", "K"),
                 ("qs", "QS"), ("sv", "SV"), ("gs", "GS"))
_RATE_KEYS = {"avg", "ops", "era", "whip"}


def _season_stats(name: str, player_type=None, team=None):
    """Thin seam over stats_loader for tests."""
    sys.path.insert(0, BASE_DIR)
    from stats_loader import get_player_season_stats  # noqa: PLC0415
    return get_player_season_stats(name, player_type, team)


def _mlb_stat_line(name: str, team, role: str):
    """Current-season MLB line from Fantrax exports; None when absent."""
    stats = _season_stats(name, role, team)
    if not stats:
        return None
    spec = _PITCHER_LINE if role == "pitcher" else _HITTER_LINE
    line = {}
    for out_key, src_key in spec:
        v = stats.get(src_key)
        if v is None:
            continue
        if out_key in _RATE_KEYS:
            line[out_key] = round(float(v), 3)
        elif out_key == "ip":
            line[out_key] = round(float(v), 1)
        else:
            line[out_key] = int(float(v))
    return line or None
```

Wire into the prospect loop (after the Task 2 enrichment lines, before `records.append`):

```python
        mlb_line = _mlb_stat_line(p["name"], p.get("mlb_team"), role) \
            if level == "MLB" else None
```

and in the record dict, after the `stat_line_translated` spread:

```python
                **({"mlb_stat_line": mlb_line} if mlb_line else {}),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_valucast_feed_v11.py -q`
Expected: 3 passed

---

### Task 4 (DD): Schema 1.1, compact JSON, validation

**Files:**
- Modify: `C:/Users/Alex/DiamondDynastiesTradeAnalyzer/generate_valucast_feed.py`

- [ ] **Step 1: Bump schema + compact output**

In `build_feed()`: `"schema_version": "1.0",` becomes `"schema_version": "1.1",`.
The write becomes compact (the artifact is generated, ~1.5k records x 30 history pairs — pretty-printing triples the size for no reader):

```python
    with open(OUTPUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(feed, fh, separators=(",", ":"))
```

- [ ] **Step 2: Extend `_validate_feed`**

Add before the final print in `_validate_feed`:

```python
    for p in players:
        vh = p.get("value_history")
        if vh is not None:
            if (not isinstance(vh, list) or len(vh) < 2
                    or not all(isinstance(pair, list) and len(pair) == 2
                               and isinstance(pair[0], str)
                               and isinstance(pair[1], (int, float))
                               for pair in vh)):
                raise ValueError(
                    f"Refusing to publish: malformed value_history on {p['id']}")
        if p.get("mlb_stat_line") is not None and p.get("level") != "MLB":
            raise ValueError(
                f"Refusing to publish: mlb_stat_line on non-MLB-level {p['id']}")
```

- [ ] **Step 3: Add a validation test**

```python
def test_validate_feed_rejects_malformed_history():
    feed = {"players": [
        {"id": "a", "player_type": "mlb", "dynasty_rank": 1,
         "value_history": [["2026-04-01", 50.0], ["bad"]]},
    ], "player_count": 1, "prospect_count": 0}
    with pytest.raises(ValueError, match="malformed value_history"):
        gvf._validate_feed(feed)
```

- [ ] **Step 4: Run DD test file**

Run: `python -m pytest tests/test_valucast_feed_v11.py -q`
Expected: 4 passed

---

### Task 5 (DD): Full DD test sanity

- [ ] **Step 1:** Run: `python -m pytest tests/test_milb_zone_model.py tests/test_milb_stat_history.py tests/test_valucast_source.py tests/test_valucast_feed_v11.py -q`
Expected: all pass (the `mlb_avg` addition is additive; `test_milb_zone_model`/`milb_translation` consumers ignore extra keys — if any DD test asserts the exact `out_stats` dict shape, update that assertion to include `mlb_avg`).

---

### Task 6 (VC): DynastyRankingRow — new fields + optional-field coercion

**Files:**
- Modify: `C:/Users/Alex/Documents/Codex/2026-05-18/league-values/web/dynasty_models.py`
- Test: `C:/Users/Alex/Documents/Codex/2026-05-18/league-values/tests/test_v11_feed.py` (NEW)

- [ ] **Step 1: Write the failing tests**

```python
"""v1.1 feed fields: coercion, sparkline geometry, card surfaces."""
import unittest

from web.dynasty_models import DynastyRankingRow


def _record(**over):
    base = {
        "id": "dd_prospect_test", "player_type": "prospect", "name": "Test Guy",
        "positions": ["SS"], "mlb_team": "SEA", "age": 20,
        "dynasty_rank": 5, "dynasty_value": 70.0, "status": "minors",
        "mlbam_id": "806954", "level": "MLB", "eta": 2026,
    }
    base.update(over)
    return base


class TestOptionalFieldCoercion(unittest.TestCase):
    def test_new_fields_default_safely_when_absent(self):
        row = DynastyRankingRow.from_feed(_record())
        self.assertEqual(row.value_history, ())
        self.assertIsNone(row.mlb_stat_line)
        self.assertIsNone(row.stat_line_translated)

    def test_value_history_coerces_pairs_and_drops_garbage(self):
        row = DynastyRankingRow.from_feed(_record(value_history=[
            ["2026-05-14", 55.2], ["2026-05-15", "56.1"],
            ["bad-pair"], [None, 1.0], ["2026-05-16", None],
        ]))
        self.assertEqual(row.value_history,
                         (("2026-05-14", 55.2), ("2026-05-15", 56.1)))

    def test_stringly_numbers_coerce(self):
        row = DynastyRankingRow.from_feed(_record(
            eta="2027", age="20", breakout_rank_change="-6"))
        self.assertEqual(row.eta, 2027)
        self.assertEqual(row.age, 20)
        self.assertEqual(row.breakout_rank_change, -6)

    def test_dict_fields_reject_non_dicts(self):
        row = DynastyRankingRow.from_feed(_record(
            mlb_stat_line=["not", "a", "dict"], stat_line_translated="nope"))
        self.assertIsNone(row.mlb_stat_line)
        self.assertIsNone(row.stat_line_translated)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run (PowerShell, VC repo): `$env:PYTHONDONTWRITEBYTECODE="1"; $env:PYTHONPATH="src;."; python -m unittest tests.test_v11_feed -v`
Expected: FAIL — unexpected keyword / missing attribute `value_history`

- [ ] **Step 3: Implement**

Dataclass additions (after `stat_line: dict | None = None`):

```python
    value_history: tuple = ()              # ((date, value), ...) chronological
    mlb_stat_line: dict | None = None      # call-ups: current-season MLB line
    stat_line_translated: dict | None = None  # MLB-equivalent peripherals
```

Coercion helpers (after `_normalize_positions`):

```python
    @staticmethod
    def _coerce_value_history(raw) -> tuple:
        """((date, value), ...) — drop malformed pairs, never reject the row."""
        out = []
        for item in raw or ():
            try:
                d, v = item[0], float(item[1])
            except (TypeError, ValueError, IndexError):
                continue
            if isinstance(d, str) and d:
                out.append((d, v))
        return tuple(out)

    @staticmethod
    def _coerce_int(raw):
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_dict(raw):
        return raw if isinstance(raw, dict) and raw else None
```

`from_feed` changes — these exact lines:

```python
            age=cls._coerce_int(record.get("age")),
            ...
            eta=cls._coerce_int(record.get("eta")),
            ...
            breakout_rank_change=cls._coerce_int(record.get("breakout_rank_change")),
            stat_line=cls._coerce_dict(record.get("stat_line")),
            value_history=cls._coerce_value_history(record.get("value_history")),
            mlb_stat_line=cls._coerce_dict(record.get("mlb_stat_line")),
            stat_line_translated=cls._coerce_dict(record.get("stat_line_translated")),
            metadata=record,
```

(`prospect_rank`/`dynasty_rank` stay as-is — required ints validated by DDFeedStore.)

- [ ] **Step 4: Run tests**

Run: `$env:PYTHONDONTWRITEBYTECODE="1"; $env:PYTHONPATH="src;."; python -m unittest tests.test_v11_feed -v`
Expected: 4 passed

---

### Task 7 (VC): Sparkline — geometry module + partial + wiring + CSS

**Files:**
- Create: `C:/Users/Alex/Documents/Codex/2026-05-18/league-values/web/value_spark.py`
- Create: `C:/Users/Alex/Documents/Codex/2026-05-18/league-values/templates/partials/_value_spark.html`
- Modify: `C:/Users/Alex/Documents/Codex/2026-05-18/league-values/app.py` (dynasty card context — the function that renders `player_detail_dynasty.html`, around lines 1086-1132)
- Modify: `C:/Users/Alex/Documents/Codex/2026-05-18/league-values/templates/partials/player_detail_dynasty.html`
- Modify: `C:/Users/Alex/Documents/Codex/2026-05-18/league-values/static/style.css`
- Test: `tests/test_v11_feed.py`

- [ ] **Step 1: Write the failing tests**

```python
from web.value_spark import build_spark


class TestBuildSpark(unittest.TestCase):
    def test_geometry_and_delta(self):
        spark = build_spark((("2026-05-14", 50.0), ("2026-05-21", 55.0),
                             ("2026-05-28", 52.5)))
        self.assertEqual(spark["direction"], "up")
        self.assertEqual(spark["delta"], 2.5)
        self.assertEqual(spark["min"], 50.0)
        self.assertEqual(spark["max"], 55.0)
        self.assertEqual(len(spark["points"].split()), 3)
        self.assertEqual(spark["first_date"], "2026-05-14")
        self.assertEqual(spark["last_date"], "2026-05-28")

    def test_flat_series_does_not_divide_by_zero(self):
        spark = build_spark((("2026-05-14", 50.0), ("2026-05-15", 50.0)))
        self.assertEqual(spark["direction"], "flat")

    def test_fewer_than_two_points_is_none(self):
        self.assertIsNone(build_spark(()))
        self.assertIsNone(build_spark((("2026-05-14", 50.0),)))
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError: web.value_spark`

- [ ] **Step 3: Create `web/value_spark.py`**

```python
"""Server-rendered sparkline geometry for dynasty value history.

Pure function: feed pairs in, SVG polyline geometry out. Rendering lives in
partials/_value_spark.html — no JS, so it works inside htmx-swapped card
partials and in non-JS contexts.
"""
from __future__ import annotations

W, H, PAD = 280, 56, 4


def build_spark(value_history, width: int = W, height: int = H):
    """value_history: ((date, value), ...) chronological. None when < 2 pts."""
    pts = [(d, float(v)) for d, v in (value_history or ()) if d]
    if len(pts) < 2:
        return None
    values = [v for _, v in pts]
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    step = (width - 2 * PAD) / (len(pts) - 1)
    coords = [
        (round(PAD + i * step, 1),
         round(height - PAD - ((v - lo) / span) * (height - 2 * PAD), 1))
        for i, (_, v) in enumerate(pts)
    ]
    delta = round(values[-1] - values[0], 1)
    return {
        "points": " ".join(f"{x},{y}" for x, y in coords),
        "last_x": coords[-1][0], "last_y": coords[-1][1],
        "width": width, "height": height,
        "first_date": pts[0][0], "last_date": pts[-1][0],
        "min": round(lo, 1), "max": round(hi, 1),
        "delta": delta,
        "direction": "up" if delta > 0 else ("down" if delta < 0 else "flat"),
    }
```

- [ ] **Step 4: Create `templates/partials/_value_spark.html`**

```html
{# Dynasty value sparkline. Context: spark (build_spark output or None). #}
{% if spark %}
<div class="detail-section value-spark-section">
    <h4>Dynasty Value Trend
        <span class="statcast-asof">{{ spark.first_date }} → {{ spark.last_date }} · model re-baselines smoothed</span>
        <span class="spark-delta {{ spark.direction }}">{{ "%+.1f" | format(spark.delta) }}</span>
    </h4>
    <svg class="value-spark" viewBox="0 0 {{ spark.width }} {{ spark.height }}"
         preserveAspectRatio="none" role="img"
         aria-label="Dynasty value {{ spark.first_date }} to {{ spark.last_date }}: range {{ spark.min }} to {{ spark.max }}, change {{ spark.delta }}">
        <polyline points="{{ spark.points }}" fill="none" vector-effect="non-scaling-stroke" />
        <circle cx="{{ spark.last_x }}" cy="{{ spark.last_y }}" r="2.5" />
    </svg>
</div>
{% endif %}
```

- [ ] **Step 5: Wire into app.py card context**

Import near the other web imports: `from web.value_spark import build_spark`.
In the dynasty-card render path (the same function that already builds `mlb_stats`/`statcast_groups` around app.py:1086-1132) add to BOTH the MLB branch's and the prospect branch's `render_template(...)` calls:

```python
            spark=build_spark(row.value_history),
```

(If both branches funnel through one `render_template`, one kwarg suffices — match the existing structure.)

- [ ] **Step 6: Template include**

In `player_detail_dynasty.html`, render the spark directly AFTER the existing identity/value header section and BEFORE the statcast/outlook sections, in the shared region both MLB and prospect cards flow through (if the template splits by branch, include in both):

```html
{% include "partials/_value_spark.html" %}
```

- [ ] **Step 7: CSS (append to style.css near the statcast styles)**

```css
/* Dynasty value sparkline */
.value-spark-section h4 { display: flex; align-items: baseline; gap: .5rem; flex-wrap: wrap; }
.value-spark { width: 100%; max-width: 420px; height: 56px; display: block; margin-top: .35rem; }
.value-spark polyline { stroke: var(--c-dynasty); stroke-width: 2; }
.value-spark circle { fill: var(--c-dynasty); }
.spark-delta { font-size: .72rem; font-weight: 700; border-radius: 999px; padding: .12rem .5rem; }
.spark-delta.up { color: var(--c-pos); background: rgba(45, 212, 160, .14); }
.spark-delta.down { color: var(--c-neg); background: rgba(255, 107, 107, .14); }
.spark-delta.flat { color: var(--c-muted); background: rgba(154, 161, 192, .14); }
```

- [ ] **Step 8: Integration test (append to tests/test_v11_feed.py)**

```python
import json
from pathlib import Path

import app as app_module

HX = {"HX-Request": "true"}


class TestSparkOnCards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_module.app.config["TESTING"] = True
        cls.client = app_module.app.test_client()

    def test_dynasty_card_renders_spark_when_history_present(self):
        row = next((r for r in app_module.dd_store.get_all()
                    if len(r.value_history) >= 2), None)
        if row is None:
            self.skipTest("committed feed predates value_history")
        resp = self.client.get(f"/player/{row.id}?mode=dd_dynasty", headers=HX)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"value-spark", resp.data)
```

(Skip-not-fail when the committed feed is still 1.0 — the regen in Task 11 flips it live. After regen this asserts for real.)

- [ ] **Step 9: Run the new tests** — same unittest command, expected all pass.

---

### Task 8 (VC): 2026 MLB stat grid on call-up prospect cards

**Files:**
- Modify: `C:/Users/Alex/Documents/Codex/2026-05-18/league-values/templates/partials/player_detail_dynasty.html` (prospect branch, directly BEFORE the `{% if row.stat_line %}` MiLB Stats section at line ~144)
- Test: `tests/test_v11_feed.py`

- [ ] **Step 1: Template block**

```html
{% if row.level == 'MLB' and row.mlb_stat_line %}
<div class="detail-section">
    <h4>2026 MLB Stats
        <span class="statcast-asof">current season · via Fantrax</span>
        {% if row.mlb_stat_line.get('pa') is not none and row.mlb_stat_line.get('pa') < 100 %}<span class="small-sample">small sample · {{ row.mlb_stat_line.get('pa') | int }} PA</span>
        {% elif row.mlb_stat_line.get('ip') is not none and row.mlb_stat_line.get('ip') < 30 %}<span class="small-sample">small sample · {{ row.mlb_stat_line.get('ip') }} IP</span>{% endif %}
    </h4>
    <div class="stat-grid">
        {% for key in ['pa', 'avg', 'ops', 'hr', 'rbi', 'r', 'sb', 'ip', 'era', 'whip', 'k', 'qs', 'sv'] %}{% if row.mlb_stat_line.get(key) is not none %}
        <div class="stat-item"><span class="stat-label">{{ key | upper }}</span><span class="stat-value">{{ stat_value(row.mlb_stat_line.get(key), key) }}</span></div>
        {% endif %}{% endfor %}
    </div>
</div>
{% endif %}
```

Check the existing `stat_value` template helper handles keys `pa/hr/rbi/r/sb/k/qs/sv` (integers pass through) and `avg/ops/era/whip` (existing rate formatting — these keys already appear in MiLB stat_line rendering). If an int key formats wrong, extend `stat_value` minimally rather than inventing a new helper.

- [ ] **Step 2: Test (append)**

```python
class TestCallUpMlbLine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_module.app.config["TESTING"] = True
        cls.client = app_module.app.test_client()

    def test_mlb_line_renders_for_callup_with_line(self):
        row = next((r for r in app_module.dd_store.get_all()
                    if r.is_prospect and r.level == "MLB" and r.mlb_stat_line),
                   None)
        if row is None:
            self.skipTest("committed feed predates mlb_stat_line")
        resp = self.client.get(f"/player/{row.id}?mode=dd_dynasty", headers=HX)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"2026 MLB Stats", resp.data)

    def test_mlb_line_absent_for_pure_minors(self):
        row = next(r for r in app_module.dd_store.get_all()
                   if r.is_prospect and r.level not in (None, "MLB"))
        resp = self.client.get(f"/player/{row.id}?mode=dd_dynasty", headers=HX)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(b"2026 MLB Stats", resp.data)
```

- [ ] **Step 3: Run tests** — pass (first may skip until regen).

---

### Task 9 (VC): MLB-equivalent peripherals block + "(all levels)" pool caveat

**Files:**
- Modify: `C:/Users/Alex/Documents/Codex/2026-05-18/league-values/templates/partials/player_detail_dynasty.html` (prospect branch, directly AFTER the MiLB Stats section's closing tag, BEFORE the `prospect-statcast` block at line ~218)
- Modify: same file — find the existing percentile-pool label text `vs ValuCast prospect pool` and append ` (all levels)` inside that span.
- Modify: `static/style.css`
- Test: `tests/test_v11_feed.py`

- [ ] **Step 1: Template block**

```html
{% if row.stat_line_translated and row.stat_line_translated.get('stats') %}
{% set tr = row.stat_line_translated %}
<div class="detail-section translated-section">
    <h4>MLB-Equivalent Rates
        <span class="statcast-asof">level-adjusted from {{ tr.get('level_label') or tr.get('level') }} · sticky peripherals only · {{ tr.get('sample') }} {{ tr.get('sample_unit') }}</span>
        {% if tr.get('confidence') %}<span class="pct-chip {% if tr.get('confidence') == 'low' %}low{% endif %}">{{ tr.get('confidence') }} confidence</span>{% endif %}
    </h4>
    <div class="stat-grid">
        {% for s in tr.get('stats') %}
        <div class="stat-item">
            <span class="stat-label">{{ s.label }}</span>
            <span class="stat-value">{{ s.mlb }}{% if s.fmt == 'pct' %}%{% endif %}</span>
            <span class="translated-from">{{ tr.get('level_label') or tr.get('level') }}: {{ s.milb }}{% if s.fmt == 'pct' %}%{% endif %} · MLB avg {{ s.mlb_avg }}{% if s.fmt == 'pct' %}%{% endif %}</span>
        </div>
        {% endfor %}
    </div>
    <p class="stat-caption">Only K%, BB%, ISO (hitters) and K/9, BB/9, K-BB% (pitchers) survive the minors-to-MLB jump reliably; other stats are deliberately not translated. Small samples are regressed toward MLB average.</p>
</div>
{% endif %}
```

- [ ] **Step 2: CSS**

```css
/* MLB-equivalent peripherals */
.translated-from { display: block; font-size: .68rem; color: var(--c-muted); margin-top: .15rem; }
```

- [ ] **Step 3: Pool caveat label**

In the same template, the prospect percentile heading contains the literal text `vs ValuCast prospect pool` — append ` (all levels)` so it reads `vs ValuCast prospect pool (all levels)`.

- [ ] **Step 4: Test (append)**

```python
class TestTranslatedBlock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_module.app.config["TESTING"] = True
        cls.client = app_module.app.test_client()

    def test_translated_block_renders_when_present(self):
        row = next((r for r in app_module.dd_store.get_all()
                    if r.is_prospect and (r.stat_line_translated or {}).get("stats")),
                   None)
        if row is None:
            self.skipTest("committed feed predates stat_line_translated")
        resp = self.client.get(f"/player/{row.id}?mode=dd_dynasty", headers=HX)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"MLB-Equivalent Rates", resp.data)

    def test_pool_label_carries_all_levels_caveat(self):
        row = next(r for r in app_module.dd_store.get_all()
                   if r.is_prospect and r.stat_line)
        resp = self.client.get(f"/player/{row.id}?mode=dd_dynasty", headers=HX)
        if b"prospect pool" in resp.data:
            self.assertIn(b"prospect pool (all levels)", resp.data)
```

- [ ] **Step 5: Run tests** — pass/skip as above.

---

### Task 10 (VC): Full suite

- [ ] Run (Git Bash, VC repo): `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests 2>&1 | grep -E "^(OK|FAILED|Ran )"`
Expected: `Ran 80x tests` / `OK` (798 + new, minus none).

---

### Task 11 (Fable-side — NOT Codex): regen, gate, ship

- [ ] Review the full Codex diff (contract adherence, mojibake byte-sweep `c3 82 c2 b7` / `c3 a2 e2 82 ac e2 80 9d`, no network in VC runtime).
- [ ] DD: run `python -m pytest tests/test_valucast_feed_v11.py -q` + targeted DD tests.
- [ ] DD: `python generate_valucast_feed.py` — verify console: value_history attach count (expect 1200+/1534), levels summary unchanged, validation passes; spot-check JSON: Emerson has mlbam_id + mlb_stat_line + stat_line_translated; Ohtani has 30-day value_history; schema 1.1.
- [ ] VC: full suite green; local card shots (Ohtani spark, Emerson MLB line + translated block, pure-minors prospect unchanged); mobile 390px.
- [ ] DD commit (explicit paths: generate_valucast_feed.py, milb_translation.py, tests/test_valucast_feed_v11.py) + push.
- [ ] VC commit (explicit paths incl. data/dd/dd_dynasty_feed.json) + push; deploy watcher on /health/ready; live shots → Alex.

---

## Self-Review Notes
- Spec coverage: sparklines (T1+T7), MLB lines (T3+T8), level-adjusted (T2+T9), mlbam_id (T2), coercion (T6), schema/validation (T4), tests (T5/T10), ship (T11). Confidence/range surfaces from the original bucket are OUT (needs own design; not in Alex's ask).
- Producer emits `value_history` as JSON lists `[[date, value], ...]`; VC coerces to tuples — consistent at the boundary.
- `stat_line_translated` is the `translate_peripherals` dict passed through verbatim (plus `mlb_avg` per stat) — VC reads only documented keys, all via `.get`.
- `mlb_stat_line` keys are lowercase; template whitelist matches producer spec exactly (hitter + pitcher unions).
