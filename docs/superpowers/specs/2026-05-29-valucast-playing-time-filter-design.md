# ValuCast Playing-Time Filter — Design

**Date:** 2026-05-29
**Status:** Approved

## Problem

The valuation engine values every projection in `data/projections/current.json`, but
the data is ~87% filler:

- 9,953 total players (4,386 hitters, 5,091 starters, 476 relievers)
- Median hitter = **1.0 PA**; 3,885 of 4,386 hitters have < 50 PA
- Median pitcher = **1.0 IP**; 4,960 of 5,567 pitchers have < 20 IP
- PA/IP are present for every player (0 missing) — reliable keys to filter on

The engine computes category means/stddevs (categories mode), SGP denominators
(roto mode), and ratio baselines from the **whole eligible pool**. With that pool
dominated by ~1-PA/1-IP filler, every real player's z-score is distorted. The
existing `VolumeMultiplier` post-processor only *discounts* low-volume players
(floor 0.20) after valuation — it never removes them, and it cannot un-contaminate
a baseline that was already computed from the polluted pool.

## Approach

Drop sub-threshold players **before** valuation (pre-engine), so the baselines are
computed from real players only. Provide an ID-based bypass (`always_keep`) so
specific players can still be valued and inspected against the clean baseline —
this is what keeps the ranking, player-detail, and compare views numerically
consistent.

## Components

### 1. `src/league_values/playing_time.py` (new)

A single pure function, unit-testable in isolation:

```python
def filter_by_playing_time(
    players,
    *,
    hitter_pa: float,
    sp_ip: float,
    rp_ip: float,
    always_keep: frozenset[str] = frozenset(),
) -> list[PlayerProjection]:
    ...
```

Rules:

- **Hitter** (`pool == hitter`): keep if `PA` (fallback `AB`) ≥ `hitter_pa`
- **Starter** (`pool == starter`): keep if `IP` ≥ `sp_ip`
- **Reliever** (`pool == reliever`): keep if `IP` ≥ `rp_ip`
- **Generic pitcher** (`pool == pitcher`, none in current data): use `rp_ip` (the
  lower bar) to avoid wrongly dropping an ambiguous pitcher
- Comparison is inclusive (`≥`); missing or zero volume → dropped
- **`always_keep` bypass (two-way tolerant):** a player is retained regardless of
  threshold if either of the following holds:
  - `player.id` ∈ `always_keep`, or
  - `base(player)` ∈ `{ strip_suffix(k) for k in always_keep }`

  where `base(player) = player.metadata.get("base_id") or strip_suffix(player.id)`
  and `strip_suffix` removes a trailing `_P` or `_H` (the suffixes
  `ProjectionStore` adds when deduplicating two-way players). This guarantees that
  passing either side of a two-way player (e.g. `19755` or `19755_P`) keeps both
  the hitter and pitcher entries. `strip_suffix` only strips the exact `_P`/`_H`
  suffixes; current IDs are numeric so there is no collision risk.

The function reads only `PlayerProjection` fields (`pool`, `stats`, `id`,
`metadata`) — no dependency on the store, so it stays pure and easy to test.

### 2. App threshold constants (`app.py`)

```python
MIN_HITTER_PA = 100
MIN_SP_IP = 40
MIN_RP_IP = 20
```

Single place to tune. Defaults keep ~440 hitters / ~235 SP / ~333 RP — genuinely
rosterable depth for a dynasty league, while removing the ~9,000 filler entries.

### 3. Shared valuation-input helper (`app.py`)

```python
def _valuation_players(always_keep: set[str] | None = None):
    return filter_by_playing_time(
        store.get_all(),
        hitter_pa=MIN_HITTER_PA,
        sp_ip=MIN_SP_IP,
        rp_ip=MIN_RP_IP,
        always_keep=always_keep or frozenset(),
    )
```

Every engine call routes through this helper:

- **Ranking (`_build_context`):** `always_keep` = the set of IDs whose name matches
  the active search query, gathered from the raw `store.get_all()`. Searched
  players are valued (against the clean baseline) so they appear; the existing
  post-valuation display filter still narrows the table to the search as normal.

  ```python
  search_keep = {p.id for p in store.get_all() if search and search.lower() in p.name.lower()}
  results = engine.value_players(_valuation_players(search_keep), config)
  ```

- **Player detail:** compute the detail player's valuation directly with
  `engine.value_players(_valuation_players({player_id}), config)` and find the
  player in that result — do **not** read the value out of the ranking results.
  This makes the detail value identical to the ranking value whether or not the
  player cleared the threshold, and removes the old "re-run on full pool" fallback
  branch.

- **Compare:** `engine.value_players(_valuation_players({p1_id, p2_id}), config)`.

### Relationship to `VolumeMultiplier`

Complementary and unchanged. The filter removes baseline-wrecking filler; the
`VolumeMultiplier` post-processor still discounts the legitimate part-timers that
survive the filter (e.g. a 250-PA platoon bat gets discounted, not dropped).

### Side benefit

Engine input drops from ~9,953 to ~1,000 players per request → every valuation is
faster. This reduces (though does not eliminate) the motivation for the separate
engine-result-caching backlog item.

## Testing

Unit tests for `filter_by_playing_time`:

- Hitter kept at exactly `hitter_pa`, dropped at `hitter_pa - 1`
- Hitter with no `PA` but qualifying `AB` is kept (fallback)
- Starter / reliever kept and dropped at their respective IP thresholds
- Generic `pitcher` pool uses the `rp_ip` bar
- Missing PA/IP entirely → dropped
- `always_keep` retains a sub-threshold player by exact `id`
- Two-way preservation: passing the base id keeps both `id` and `id_P`/`id_H`
  entries; passing a suffixed id keeps the sibling too

Integration test (`tests/test_app.py` style):

- A known ~1-PA player is absent from default rankings
- The same player appears when searched by name (bypass path)
- A two-way player (Ohtani) survives with both hitter and pitcher sides intact

## Out of Scope

- DD dynasty / prospects modes — they read from the separate `dd_store` feed, not
  this engine, and are unaffected.
- UI-configurable thresholds — fixed constants only for now.
- Engine result caching — tracked separately; this change reduces its urgency.
