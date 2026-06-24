# HANDOFF — ValuCast Phase 2: settings-aware dynasty-peak values (preset precompute)

**Date:** 2026-06-24  **Branch:** master  **Flag:** `VALUCAST_DYNASTY_PRESET_VALUE` (default OFF, per-request, reversible)

Spec: `docs/specs/2026-06-23-valucast-signature-metric-strategy.md` — Phase 2 / "INVESTIGATION 6/24".
Goal: dynasty board $/VALUE/order MOVE with league scoring, via build-time precomputed `value_by_preset`, served by dict lookup. Flag-gated.

## Data flow
`mlb/dynasty.py build_mlb_dynasty_layer` → `data/models/valucast_mlb_dynasty_layer.json` (MLB rows carry `value_by_preset`) → `scripts/build_public_dynasty_snapshot.py _mlb_rows` copies it through → `data/public/public_dynasty_snapshot.json` → `app.py` dd_store (`PublicSnapshotRow`) → `_build_dynasty_context`. Snapshot value unmutated, so `value_by_preset["5x5"] == served value`. Prospect rows have NO value_by_preset (prospect presets blocked) → fall back to single value.

## FINAL 7-preset menu (web/category_registry.py `DYNASTY_VALUE_PRESETS`, registry ids) — reconciled + extended 6/24
| id | hitting | pitching |
|---|---|---|
| 5x5 | R,HR,RBI,SB,AVG | W,SV,K,ERA,WHIP |
| obp | R,HR,RBI,SB,OBP | W,SV,K,ERA,WHIP |
| 6x6 | R,HR,RBI,SB,AVG,OBP | W,QS,SV,K,ERA,WHIP |
| sv_hld | R,HR,RBI,SB,AVG | W,SV_HLD,K,ERA,WHIP |
| 7x7 | R,HR,RBI,SB,AVG,OBP,SO | W,QS,SV,HLD,K,ERA,WHIP |
| 7x7_ops | R,HR,RBI,SB,AVG,OPS,SO | W,QS,SV_HLD,K,ERA,WHIP,K_BB |
| points | POINTS_PRESETS["default"] | — |

`7x7_ops` = Alex-requested 6/24 (OPS + combined SV_HLD + K_BB; ~his DD league w/ W not L). Added alongside the canonical OBP `7x7`; confirm if he wants it to REPLACE rather than sit beside it.

**RECONCILE PENDING:** Round 1 shipped OLD ids `obp_ops` (OBP+OPS, redundant) and `h2h` (OPS/K_BB, missing W) — both non-standard per NFBC/Yahoo/ESPN/CBS/Ottoneu/Razzball research. Rename in DYNASTY_VALUE_PRESETS: `obp_ops`→`obp`, `h2h`→`7x7` (cats above). Propagate ids: test_mlb_dynasty_preset_parity.py PRESET_IDS, Round-3 serving tests, Round-4 button map (relabel UI "H2H Categories" button → 7x7). FREE now — value_by_preset not yet in the live snapshot.

## Status (4 gated Codex rounds; Fable reviews every diff + runs FULL suite)
- **R1 build core — DONE+ACCEPTED.** category_registry (menu + expected_category_count); mlb/dynasty.py (`_scores_for_config` helper, per-preset loop, value_by_preset on rows, value_by_preset_menu, LAYER_VERSION→0.6.0, _ros_lookup optional league, fail-loud category guard); tests/test_mlb_dynasty_preset_parity.py. Full suite 1471 passed. Post-processors stateless (engine reuse safe). Parity structural+exact.
- **R2 snapshot bridge + model — DONE+ACCEPTED.** build_public_dynasty_snapshot.py (_mlb_rows copy-through + _merge_two_way_mlb_rows per-preset combine); public_snapshot_models.py (value_by_preset field + parse + value_for(preset)). public_snapshot_store.py needs NO change. Full suite 1472 passed.
- **R3 serving / app.py — IN PROGRESS (not yet reviewed).** Codex job `b92a0bur9` / agentId `a2f6645389cd4b4a0`. Per-request flag; value_of threaded through _compute_dynasty_dollars/_dynasty_tiers_for/_dynasty_metadata; _build_dynasty_context re-ranks by preset + builds preset_rank_by_id; context keys active_preset/preset_rank_by_id/preset_value_enabled/dynasty_value_presets; serving tests. **NEXT: review diff + full suite.**
- **R4 template/JS — NOT STARTED.** rankings_table_dynasty.html VAL→`row.value_for(active_preset)`, rank→`preset_rank_by_id.get(row.id,row.dynasty_rank)`, $ reuses dynasty_dollars (no change). templates/index.html Category-Fit (~470-636): under flag, 6 buttons fire HTMX `?preset=<id>` instead of client z-rank; flag off unchanged. Map roto→5x5, obp→obp_ops, sixBySix→6x6, svh→sv_hld, points→points, h2h→h2h. dynasty_category_fit.html copy conditional. resetDynastyOrder = reset path.

## Next steps
1. Review R3 app.py diff; `python -m pytest -q` (was 1472 passed / 4 skipped).
2. Dispatch R4 (template/JS).
3. End-to-end smoke: app flag-on + `?preset=sv_hld` → $/VAL/order move; flag-off byte-identical.
4. Rebuild snapshot (`scripts/build_public_dynasty_snapshot.py`, needs rebuilt mlb layer) so value_by_preset reaches the live board; nightly build also regenerates.
5. Commit/push on Alex approval. Flag stays OFF in prod until he flips it.

## Invariants / traps (do not violate)
- POOLED min-max (floor=p05, ceiling=max) recomputed PER preset; never reuse 5x5 floor/ceiling.
- PITCHER_PRODUCTION_ANCHOR 0.92 + 0.95/0.05 blend identical per preset.
- HORIZON_YEAR_WEIGHTS / age / reliability preset-INVARIANT.
- Do NOT port prospect `within_role_percentile_to_pooled_distribution` (makes MLB pitcher tilt worse).
- Flag OFF must be byte-identical to current behavior everywhere.

Resumable Codex agents: R1 aa6a54973c98520f7, R2 a7f21bd365eceb028, R3 a2f6645389cd4b4a0.
