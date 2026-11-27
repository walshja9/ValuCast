# Ship Rung 3 — ValuCast Statcast-De-noised Hitting Source (App Integration) — Design

**Date:** 2026-06-02
**Status:** SUPERSEDED by `2026-06-04-valucast-hp-source-ship-design.md` (widened from hitter-only to H+P after the pitching foundation shipped). Kept for history.
**Builds on:** Rung 3 (`2026-06-02-projections-rung3-statcast-inputs-design.md`, verdict: WIN) and the Rung 1 `ProjectionCatalog` seam.

## Goal

Put the proven Rung 3 win in front of users: register a **Statcast-de-noised ValuCast hitting projection** as a selectable, opt-in source in the app, using the locked winning alphas — while Steamer stays the default and current app behavior is preserved exactly. This is a shipping/integration step, not a modeling rung.

## Decisions (locked in brainstorming)

- **Hitter-only source.** ValuCast (Marcel) projects no pitchers; we ship exactly what the harness validated — de-noised hitters — with no borrowed numbers. Under `source=valucast`, pitcher surfaces show a clear "ValuCast doesn't project pitchers yet — switch to Steamer" affordance, never a broken/empty board pretending otherwise. **No in-house pitching is implied anywhere.**
- **It's a pure full-season projection, labeled as such.** Distinct in kind from the default board (2026 actuals + Steamer ROS outlook). UI label: *"ValuCast projection — hitters (full season, Statcast-de-noised)."* It is a "what our model projects" lens, not "where the season is headed."
- **No HR claim.** The shipped win is framed as **measured rate-stat lift (AVG/OBP/SLG/OPS) from Statcast input de-noising**. HR was neutral in Rung 3; we do not claim HR improvement.
- **Established hitters only.** A pure Marcel projection needs prior MLB seasons, so 2026 debutants/rookies are absent (no prospect model yet). Labeled as a known limitation.

## Naming

- Source key: **`valucast`** (the tuned/proprietary model — reserved for exactly this since Rung 1; the bare-Marcel source stays `marcel`).
- Run model id: `valucast_marcel_statcast`; `model_version` bumped from the bare-Marcel run.
- Locked params: `alpha_contact = 0.75`, `alpha_power = 0.5`, `gamma = 0`.

## Architecture

**No runtime network. No runtime model execution.** The ValuCast projection is built **offline** at implementation time and committed as an immutable run; the app only *loads* it.

1. **Build + archive the run (offline, committed):**
   `build_marcel_projections(2026, data_dir, MarcelParams(alpha_contact=0.75, alpha_power=0.5), identities)` → `write_run(..., model="valucast_marcel_statcast", as_of_season=2026, version=N)`. Produces `projections/runs/valucast_marcel_statcast_2026_vN/projections.json` + `run_manifest.json`. Committed (immutable, like the snapshots). Prior seasons 2023–2025 (all Statcast-covered) drive it.

2. **Run manifest metadata** (required, for provenance + honest UI): `source_name=valucast`, `model=valucast_marcel_statcast`, `model_version`, `alpha_contact`, `alpha_power`, `gamma`, `statcast_snapshot_years` (the prior years used, e.g. [2023,2024,2025]), and a short `rung3_verdict` summary (held-out 2020–25 mean MAE ratio 0.979; AVG/OBP/SLG/OPS 4–6% lift; HR neutral).

3. **Catalog wiring in `app.py`:** replace the lone `store = ProjectionStore(...)` with a `ProjectionCatalog` registering `{steamer: data/projections/current.json (default), valucast: <run projections.json>}`. Add `_active_store(source) -> ProjectionStore` returning `catalog.store_for(source or "steamer")`. Routes that currently use the global `store` accept an optional `?source=` query param and resolve via `_active_store`; **absent/unknown → steamer**, so the default board is byte-for-byte unchanged.

4. **Hitter-only behavior:** the `valucast` store contains only hitter rows, so rankings/search/detail naturally surface hitters. When a pitcher view is requested under `source=valucast`, render the "no pitching yet" affordance instead of an empty list.

## Failure modes (fail clearly, never silently)

- Unknown `source` → `ProjectionCatalog.store_for` raises `KeyError` (already implemented); the app surfaces a clear error, does **not** silently fall back in a way that hides the bug.
- Missing/partial run file → `ProjectionStore` load raises on a missing path; a run with zero hitter rows is rejected at startup (guard), so a broken publish can't masquerade as "ValuCast just has no players."
- Steamer path missing → same hard failure as today (no behavior change).

## Success criteria

1. **Default unchanged:** with no `?source=` (or `source=steamer`), every route returns exactly today's output; existing suite stays green.
2. **Selectable:** `source=valucast` loads the committed run through `ProjectionCatalog` and the engine values it end-to-end (a ranked hitter board, finite values).
3. **Hitter-only honesty:** `valucast` board contains only hitters; pitcher request under `valucast` shows the "no pitching yet" affordance, not an empty/error board.
4. **Provenance:** the run manifest carries source name, model version, both alphas, gamma, Statcast snapshot years, and the Rung 3 verdict summary.
5. **Fails clearly:** unknown source raises; missing/empty run file raises at load; tests assert each.

## Non-Goals

- Any pitching projection (the affordance points to Steamer).
- Composite ValuCast-hitters + Steamer-pitchers source (a later step, once a pitching model exists).
- Runtime model execution or Statcast fetching (offline-built, committed run only).
- Prospect/rookie projection (established hitters only).
- Re-tuning alphas or any modeling change — this ships the locked Rung 3 model as-is.
- Making `valucast` the default (Steamer stays default).

## Risks & limitations

- **Projection-vs-outlook confusion:** users could read the ValuCast board as a live outlook. Mitigated by explicit labeling and keeping it opt-in/non-default.
- **Rookie gap:** established hitters only; the default outlook board remains the place to see 2026 debutants.
- **Run staleness:** the committed run is a point-in-time projection; refreshing it is a manual offline rebuild + commit (acceptable — it's a projection, not a live feed).
