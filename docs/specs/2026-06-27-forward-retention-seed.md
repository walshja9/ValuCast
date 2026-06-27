# Forward-retention seed — finding (no in-repo retention edit exists)

**Status: the brief's literal target is not in this repo. By-level lines are already
retained going forward; the gap is a cohort-keyed join, not a discard. No served
value, live board, or 3-fold backtest is touched (zero code changed).**

Observe-only. All numbers on committed, network-free data. Companion to
`w21-mle-backtest-gate.md`.

## The brief vs the repo
The brief: change "the universal prospect dataset builder" to stop discarding
by-level lines (add `by_level_lines`, or a parallel store), without touching the
collapsed selection that live scoring and the 3-fold backtest consume.

What the repo actually contains:
1. **The universal dataset builder is upstream/external.** Its selection metadata
   (`season_selection = "earliest credible season, highest level within season"`,
   `player_grouped`, `outcomes_fail_closed`) appears in **no `.py` file**, and the
   dataset is **not produced by the daily build** (`run_daily_public_build.py` has no
   step that writes it). `valucast_universal_prospect_dataset.json` is a committed
   input generated outside this repo. There is no in-repo selection step to make additive.
2. **The only in-repo collapse is `universal.py::_base_historical_rows` (L497-528)** —
   sort by `-LEVEL_CODE[level]`, `by_player.setdefault(...)` keeps one highest-level row
   per player-cohort. The brief explicitly says to **leave this untouched** (live + the
   3-fold backtest consume it). So the one in-repo collapse is the one we must not change.
3. **By-level lines are not being discarded going forward.** `milb_card_history.json`
   is a committed raw artifact that already retains by-level lines per player per season,
   growing every year — within-season multi-level players: 2022 = 221, 2023 = 315,
   2024 = 420, 2025 = 531, 2026 = 282 (partial). Retention already happens; nothing
   in-repo throws these away.

**Conclusion: there is no in-repo "stop discarding" edit to make.** A retention change
to the external builder would have to be made in the upstream tool, which isn't here.

## What is actually missing: a cohort-keyed join (and it's thin / not yet forward)
Card history is name-keyed; its lines carry `mlbam_id` + `season` but **no `cohort_year`**.
The only place cohort lives is the universal dataset. So a pooled-vs-single input requires
joining card history to the universal cohort map on `mlbam_id` — exactly the W2.1 join.

Buildability of that join on committed data (card_history ⋈ universal cohort map):

| cohort | within-season poolable | across-season multi-level (post-cohort progression) |
|-------:|-----------------------:|----------------------------------------------------:|
| 2014–2021 |                  0 |                                          8–96 each |
| 2022   |                     75 |                                                 141 |

- **Within-season poolable** (the unit a single-cohort pooled input is built from) is
  **0 for every pre-2022 cohort** — card history starts 2022, so the cohort season of a
  2014–2021 player predates coverage. Only 2022 has any (75 — reproduces W2.1 exactly).
- The non-zero **across-season** column is post-cohort level progression (a 2017 player's
  2023 AA / 2024 AAA lines). Real by-level history, but **not** the cohort-season pooling
  input the MLE backtest consumes.
- These are **backward survivorship joins** — only players still tracked in card history's
  2022-26 window appear — so even the 75 is skewed toward persisters.
- **Forward cohorts can't be measured yet:** the committed universal dataset stops at the
  **2022 cohort** (8 cohorts, 2014–2022, 2020 absent). 2023+ cohorts aren't present, so
  their already-retained card-history by-level lines have nothing to cohort-join against
  until the upstream dataset adds them.

## What forward-retention actually requires (none of it an in-repo retention edit)
1. **Upstream:** the universal dataset gains 2023+ cohorts (external builder).
2. **Outcome maturity:** `OUTCOME_COMPLETE_THROUGH` manually bumped as seasons complete
   (hardcoded 2025 today; see gate memo).
3. **A join, not a retention change:** card-history season-lines ⋈ universal cohort map on
   `mlbam_id`. This can live in the backtest at run time, or be materialized as a parallel
   observe-only artifact. Either way it is **additive** and leaves the universal dataset,
   live board, and 3-fold backtest **byte-identical** (their inputs are untouched).

## Recommendation (owner decision — not landed unilaterally)
- **Do not write a retention edit.** Nothing in-repo discards the by-level lines; the
  premise doesn't hold against the code.
- **Re-aim the seed as a join-index**, if wanted: a new `(mlbam_id, cohort_year) -> by_level_lines`
  artifact built from committed `milb_card_history.json` + `milb_season_stats.json` (hitter
  iso/ops) ⋈ the universal cohort map. Buildable today (proof above). But it is a **new
  daily-build artifact with its own ownership**, not a one-line selection change — so it is
  an explicit scope decision, deferred to the owner per lock-before-build.
- **Net:** forward by-level retention is already occurring in card history; the MLE unblock
  is gated on (1) upstream adding forward cohorts and (2) outcomes maturing — not on any
  retention code this repo can change.

## Live-path safety
Zero code changed in this finding. The live board and the current 3-fold backtest are
byte-unchanged by construction (no input or selection they consume was touched), so no
shadow-diff is owed for this item.
