# Ship ValuCast H+P — Combined In-House Source (App Integration) — Design

**Date:** 2026-06-04
**Status:** Draft / pending review
**Supersedes:** `2026-06-02-valucast-hitting-source-ship-design.md` (the hitter-only version, parked when pitching was deferred — now widened to H+P since the pitching foundation shipped).
**Builds on:** Rung 3 (hitting de-noise, WIN), the pitching foundation (role-routed Marcel, WIN), and the Rung 1 `ProjectionCatalog` seam.

## Goal

Put both proven in-house models in front of users: register **ValuCast H+P** — our Statcast-de-noised hitters + role-routed pitchers — as a single selectable, opt-in projection source, while Steamer stays the default and current app behavior is preserved exactly. A shipping/integration step, not a modeling rung.

## Decisions (locked)

- **Combined H+P source.** One `valucast` source = ValuCast hitters + ValuCast pitchers, so the board is complete (matches the app's identity: hitters, pitchers, prospects). No more "no pitching yet" affordance.
- **Honest provenance, per segment:**
  - **Hitters:** Statcast-de-noised Marcel (Rung 3, locked α). The de-noising blends toward **Savant's** xBA/xSLG — we **do NOT claim our own xBA** (the own-xBA grid was a SHORTFALL; Savant remains the better input today). Framed as *measured rate-stat lift (AVG/OBP/SLG/OPS) from Statcast input de-noising*; **no HR claim** (HR was neutral).
  - **Pitchers:** role-routed Marcel — **fully in-house**, beat persistence on skill cats (ERA/WHIP/K/K9/BB9). W/SV/QS noted as usage/context.
  - **Steamer:** stays the external benchmark and the default.
- **Pure full-season projection lens.** ValuCast is a from-prior-years projection, distinct in kind from the default board (2026 actuals + Steamer ROS outlook). Labeled as "what our models project," not "where the season is headed." **Established players only** — no 2026 debutants/rookies (no prospect model yet).

## Naming

- Source key: **`valucast`**.
- Run model ids: hitters `valucast_marcel_statcast` (α_contact=0.75, α_power=0.5, γ=0); pitchers `valucast_pitching_marcel`. Combined run id `valucast_hp_2026_v1`.

## Architecture

**No runtime network. No runtime model execution.** Both projections are built **offline** at implementation time and committed as an immutable combined run; the app only *loads* it.

1. **Build + archive (offline, committed):**
   - Hitters: `build_marcel_projections(2026, data_dir, MarcelParams(alpha_contact=0.75, alpha_power=0.5), identities)`.
   - Pitchers: `build_pitcher_projections(2026, data_dir, PitcherMarcelParams())`.
   - Concatenate the two row lists and `write_run(combined_rows, runs_dir, model="valucast_hp", as_of_season=2026, version=1)` → `projections/runs/valucast_hp_2026_v1/projections.json` + `run_manifest.json`. Committed (immutable; `write_run` already enforces this). Prior seasons 2023–2025 drive both.

2. **Combined run manifest** (provenance + honest UI): `source_name=valucast`; a `components` block with, per leg, `model`, `model_version`, params (hitter α/γ; pitcher n_reg), `prior_seasons`, an `inputs` note (hitters: "consumes Savant xBA/xSLG — not our own"; pitchers: "fully in-house, no Statcast"), and a one-line `verdict` (hitting: held-out 2020–25 mean MAE ratio 0.979, AVG/OBP/SLG/OPS 4–6% lift, HR neutral; pitching: held-out 2020–25 skill mean MAE ratio 0.821 vs persistence). Hitter/pitcher row counts.

3. **Catalog wiring in `app.py`:** replace the lone `store = ProjectionStore(...)` with a `ProjectionCatalog` registering `{steamer: data/projections/current.json (default), valucast: <combined run projections.json>}`. Add `_active_store(source) -> ProjectionStore` returning `catalog.store_for(source or "steamer")`. The ~8 routes that use the global `store` accept an optional `?source=` query param and resolve via `_active_store`; **absent/unknown → steamer**, so the default board is byte-for-byte unchanged.

4. **Combined board:** the `valucast` store contains both hitter (`mlbam_*_H`) and pitcher (`mlbam_*_P`) rows; the engine already values STARTER/RELIEVER/HITTER pools, so rankings/search/detail surface a full board under `source=valucast` with zero engine changes.

## Failure modes (fail clearly, never silently)

- Unknown `source` → `ProjectionCatalog.store_for` raises `KeyError`; the app surfaces a clear error, never a silent fallback that hides the bug.
- Missing/partial combined run file → `ProjectionStore` load raises on a missing path; a run with **zero hitter rows OR zero pitcher rows** is rejected (guard at load/wiring), so a broken half-publish can't masquerade as "ValuCast just has no pitchers."
- Steamer path missing → same hard failure as today (no behavior change).

## Success criteria

1. **Default unchanged:** no `?source=` (or `source=steamer`) → every route returns exactly today's output; existing suite stays green.
2. **Selectable + combined:** `source=valucast` loads the committed combined run via `ProjectionCatalog`; the engine values it end-to-end producing a ranked board with **both** hitters and pitchers (finite values, both pools present).
3. **Provenance:** the combined manifest carries per-leg model, params, inputs note (hitters consume Savant; pitchers in-house), and verdict summaries; **no claim our xBA replaces Savant**.
4. **Fails clearly:** unknown source raises; missing/empty (or single-pool) combined run raises at load; tests assert each.
5. **Honest labels:** the source label distinguishes ValuCast (our projection) from Steamer (external benchmark/default) and notes the hitter/pitcher provenance split.

## Non-Goals

- Replacing Steamer as default (stays default).
- Any runtime model execution or network (offline-built, committed run only).
- Prospect/rookie projection (established players only).
- Re-tuning either model or any modeling change — ships the locked, proven runs as-is.
- Claiming our own xBA (the own-xBA grid SHORTFALL stands; hitters consume Savant's xBA/xSLG).
- A full source-toggle UI redesign — minimal `?source=` seam; richer UI is a later step.

## Risks & limitations

- **Projection-vs-outlook confusion** — mitigated by explicit labeling + opt-in/non-default.
- **Rookie gap** — established players only; the default outlook board remains the place for 2026 debutants.
- **Run staleness** — the committed run is point-in-time; refreshing is a manual offline rebuild + commit (acceptable — it's a projection, not a live feed).
- **Two-way players (Ohtani)** — `ProjectionStore` already dedups two-way by `_H`/`_P` suffix; the combined source carries both his hitter and pitcher rows, valued in their correct pools.
