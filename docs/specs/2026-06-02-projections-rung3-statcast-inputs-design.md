# Projections Rung 3 — Statcast Input De-noising (Hitting) — Design

**Date:** 2026-06-02
**Status:** Approved (design)
**Builds on:** Rung 1 (`...-foundation-hitting-design.md`) and Rung 2 (`...-rung2-reliability-regression-design.md`).

## Goal

Beat **classic Marcel** on held-out 2020–2025 by feeding it *luck-stripped* historical inputs: before Marcel weights each prior season, blend that season's actual hit/power production toward its Statcast expected stats (`xBA`, `xSLG`). The hypothesis (THE BAT X's core finding) is that expected stats predict *future* performance better than actual outcomes, because they strip BABIP/sequencing luck out of the line.

This is the next lever after regression tuning was exhausted: Rung 1 (global knobs) and Rung 2 (per-component reliability) both **tied** classic Marcel on held-out data. The remaining lever is **better inputs, not more tuning.**

## Why de-noise inputs (vs other integrations)

Decided in brainstorming: de-noising the inputs reuses the entire Marcel machine, has a tiny overfit surface (two blend knobs), and directly tests the expected-vs-actual hypothesis. The alternatives (Statcast-informed regression *target*, or output blending) add moving parts or treat Statcast as a parallel black box.

## Data audit (confirmed reachable 2026-06-02)

Baseball Savant public CSV endpoints, **join key `player_id` = MLBAM id** (clean, no name-matching):

| Leaderboard | Fields used | Endpoint |
|---|---|---|
| `expected_statistics` | `est_ba` (xBA), `est_slg` (xSLG) — **the bridge**; `est_woba` stored | `/leaderboard/expected_statistics?type=batter&year=Y&min=1&filterType=bip&csv=true` |
| `statcast` (barrels/EV) | `brl_percent`, `avg_hit_speed`, `ev95percent`, `avg_hit_angle` — **observe-only v1** | `/leaderboard/statcast?type=batter&year=Y&min=1&csv=true` |

- **Coverage: 2015+** (Statcast era). The held-out block (2020–25) and the seasons it projects from (2017+) are fully covered. Pre-2015 seasons have no Statcast → classic fallback.
- **Parsing:** UTF-8 BOM + the name column is one quoted `"last_name, first_name"` field. Use `utf-8-sig`; key off `player_id`, not name.
- **Fragility:** scraping endpoint (can rate-limit / change params). Mitigation: pull once into immutable per-season snapshots, never scrape at projection time (mirrors the MLB historical backbone).
- **`min` pinned to `1`** (`filterType=bip`, ≥1 batted ball). Probed coverage for 2023: `min=1`→651 rows, `min=100`→403, `min=q`→258. `min=1` is the lowest accepted threshold and gives maximum coverage (651 ≫ our ~330-player eval population). Any player-season still missing → classic fallback for that season.
- **Undercoverage guard (fail loud):** record each season's pulled row count in the manifest and **raise** if a season returns fewer than **250 rows** (a hard floor well under the ~600 normal / shortened-2020 levels). A silent empty/partial pull would otherwise masquerade as "classic fallback everywhere" and fake a tie.

## Data layer (`projections/data/statcast.py`)

Mirror `historical.py`: immutable per-season snapshots `projections/data/statcast/hitting_<season>.json`, keyed by `mlbam_id`, storing `{xba, xslg, xwoba, barrel_pct, avg_ev, hardhit_pct, launch_angle}`. Manifest with content hash; re-pull of a finalized season is a no-op (same immutability contract as the MLB backbone). A loader returns `{mlbam_id: statcast_row}` for a season; missing season → empty dict.

## The component bridge (the centerpiece)

Statcast gives slash-level expecteds, not per-component rates, so we de-noise at the two aggregates Statcast supports cleanly, then redistribute into components using the player's **own** extra-base mix (no invented "xHR").

**Applied per historical player-season that has Statcast, before Marcel weights it.** Inputs: actual `1B, 2B, 3B, HR, AB`; `xBA, xSLG`; knobs `α_contact, α_power`.

Let `H = 1B+2B+3B+HR`, `TB = 1B+2·2B+3·3B+4·HR`, `XB = 2B+3B+HR`.

**1. De-noise the two aggregates (blend actual rate toward expected):**
```
H*  = AB · [ (1−α_contact)·(H/AB)  + α_contact·xBA  ]
TB* = AB · [ (1−α_power)·(TB/AB)   + α_power·xSLG   ]
```

**2. Redistribute to components, preserving the player's 2B:3B:HR proportions.**
With `m = (2·2B + 3·3B + 4·HR) / XB` (total bases per extra-base hit, `m ∈ (2,4]`):
```
XB' = (TB* − H*) / (m − 1)        # extra-base hits
1B' = H* − XB'                    # singles
2B',3B',HR' = XB' split by the player's actual (2B:3B:HR) proportions
```
So **`xBA` sets total hits, `xSLG` sets total bases, the player's mix sets the split.** HR moves only as far as the player's power profile + xSLG justify.

**3. Feasibility guards (required — xBA/xSLG can force an impossible line, esp. small samples):**
- Clamp `H*` to `[0, AB]`.
- Enforce `TB* ≥ H*` (can't have fewer total bases than hits); if blending produced `TB* < H*`, set `TB* = H*`.
- Clamp `XB'` to `[0, H*]`. **If the clamp binds, `TB*` cannot be matched exactly — prioritize coherent components over exact xSLG** (recompute `1B' = H* − XB'` and let realized TB follow).
- Clamp every resulting component to `≥ 0`.

**4. Undefined-mix fallback (`XB == 0` or `m ≤ 1`):**
- Use the **league-average XBH mix for that season** (league 2B:3B:HR proportions and league `m`) so a zero-XBH player with high xSLG still gets coherent power de-noising — *not* a zero-HR lock.
- If the league mix is unavailable, fall back to **classic for power** for that player-season (de-noise contact/`H` only; leave components' power split as actual).

**5. Tiny-sample / missing-Statcast guard:**
- No Statcast row for the player-season, or `AB` below a small floor → treat as `α=0` for that season (use actual components unchanged).

**What this de-noises:** `H, 1B, 2B, 3B, HR, TB` (and therefore projected `AVG, SLG, OPS`, and the `HR` category).
**Left fully classic (untouched):** `BB, SO, HBP, SF, SB, CS, R, RBI, PA, AB`, the age curve, and the PA projection.

## Model shape & knobs

- Add `alpha_contact: float = 0.0` and `alpha_power: float = 0.0` to `MarcelParams`. **`α=0` (default) nests classic Marcel exactly** — no de-noising applied.
- **Regression stays classic:** `gamma = 0` (Rung 2's reliability-weighting is *not* combined here — we isolate the Statcast effect). The reliability machinery remains available but inert.
- De-noising is applied to the component counts of the 3 Marcel input seasons inside `build_marcel_projections`, after joining each season's Statcast snapshot; the de-noised seasons then flow through the unchanged `project_hitter`.
- Tuning: reuse `coordinate_descent`, extended to search `(alpha_contact, alpha_power)` (gamma/n_reg held at classic). Leakage-safe: tuning seasons disjoint from scoring seasons.

**Tuning & evaluation blocks (Statcast-aware — do NOT reuse Rung 2's 2014–2019):**
A target season's de-noising only bites if its 3 prior seasons have Statcast. Statcast starts 2015, so all three priors are covered only when `T ≥ 2018` (T−3 ≥ 2015). Therefore:
- **Tuning block: 2018–2019** — both have fully Statcast-covered priors (2018←2015/16/17, 2019←2016/17/18). Avoids tuning on mostly-fallback-classic noise.
- **Scoring block: 2020–2025** (disjoint) — all priors ≥2017, fully covered.
- The harness must **report the Statcast-covered prior-season share per target** (e.g. "2018: 3/3 priors covered") so undercoverage is visible, not silent.
(2017 is available as an optional extra tuning season but its 2014 prior is fallback — include only if more tuning data is needed, with the coverage caveat noted.)

## Success criteria

1. **Data layer:** immutable Savant snapshots 2015–2025 (`min=1`), joined by `mlbam_id`, manifested with row counts; re-pull no-op verified; undercoverage guard raises below the 250-row floor.
2. **Bridge correctness:** unit-tested — `α=0` reproduces classic components exactly; a hand-built case verifies the redistribution hits `H*`/`TB*`; each feasibility guard has a test (H* clamp, TB*≥H*, XB' clamp-binds, XB==0 league-mix fallback, missing-Statcast α=0).
3. **Backward compatibility:** `α=0` build == current classic build exactly; existing 478 tests stay green.
4. **The verdict (honest either way):** tuned on **2018–2019**, scored on disjoint **2020–2025**, `(α_contact, α_power)` either **beats classic** (mean MAE ratio vs classic < 1.0, correlation improvement on a majority, edge **carries** from the tuning block) — or **ties**, recorded plainly. Statcast-covered prior-season share reported per target. Do not expand the grid to chase a scoring-block win (leakage).

## Non-Goals

- Barrel%/EV/launch-angle as model inputs (pulled, stored, observe-only this rung).
- Combining with Rung 2 reliability-weighting (`gamma` stays 0).
- De-noising `BB/SO/SB/CS/R/RBI` (no defensible Statcast bridge).
- Pitching, prospects, any UI/source-toggle exposure.
- xwOBA-direct value modeling (would abandon the component contract the engine consumes).

## Risks & limitations

- **Impossible-line risk** — the reason for the guards; small-sample player-seasons are where xBA/xSLG most often force incoherent components. Guards prioritize coherence over exact xSLG.
- **Coverage** — Savant thresholds + 2015 floor mean some player-seasons lack Statcast; they fall back to classic, diluting the effect (acceptable; the eval era is well-covered).
- **It may tie.** Regression tuning already tied twice; de-noising is a genuinely different lever, but the harness will tell us honestly. A tie still advances the program (rules out the cheap input-blend; points to barrel%-driven power modeling or a full xwOBA reframe).
- **Scraping fragility** — handled by snapshotting, but a Savant schema/param change would break the pull; the loader must fail loud, not silently emit empty Statcast (which would masquerade as "classic everywhere").
