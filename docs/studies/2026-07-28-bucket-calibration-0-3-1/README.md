# Study Package: Bucket Calibration 0.3.1 vs 0.3.0

Registered study raw materials (owner ship-gate #6). Registration:
`docs/registration-2026-07-28-bucket-calibration-0-3-1-evaluation.md`
(commit `3688f83`, pushed before any result was computed). Results and
verdict: `docs/audit-2026-07-29-bucket-calibration-0-3-1-evaluation.md`.

## Contents

- `per_player_deltas.csv` — the definitive raw table: every affected row-day
  (|Δscore| ≥ 0.01, unrounded) across the six input days: scores/ranks under
  both arms, delta, intended/unintended class, `continuity_floor_applied`,
  arm-B bucket membership. 1,947 rows (87 intended), matching the results doc.
- `analyze.py` — the study's Q1/Q2/subgroup computation script.
- `analyze_output.txt` — its full output: per-day and pooled tables as
  reported in the results doc.
- `determinism_check.py` — the double-build decision-field diff used for the
  determinism spot check.
- `q3/` — per-arm-day headline-statistic extracts from the calibration
  builders (Q3), with logs omitted for size.

## Reproducing the boards (not committed: ~274 MB for 12 builds)

Arms: worktree A at `20e2511` (0.3.0), worktree B at `3c847df` (0.3.1).
For each input day sha in {`5e8959d`, `1d63585`, `d4ae26f`, `b8cd8a9`,
`d83a9a7`, `3e044b1`}: `git -C <worktree> checkout <sha> -- data`, then run
`scripts/build_prospect_rank_v1.py` in that worktree (offline; reads only
committed `data/`). Prior board for the first day pair:
`git show 20e2511:data/models/valucast_prospect_rank_v1.json`. Exclude
`generated_at` and `context_only.source_ranks` from any comparison (the
latter is the known nondeterministic context leaf). The arm-B 07-23 rebuild
must byte-match the served `5e8959d` artifact under those exclusions.
