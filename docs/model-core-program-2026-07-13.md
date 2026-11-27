# Model-Core & Plumbing Program — "make it the most accurate"

Locked 2026-07-13. The thesis: **accuracy isn't added, it's measured into
existence.** No new signal enters the model until the gate can tell us whether
it helped. Phases run in the order below; the archive (Phase 3) starts in
parallel because it's the only clock we can't compress.

## Hard timing gates (these shape everything)

- **7/13 ~12:40 UTC — scorecard unlock.** NOTHING perturbs the frozen scorecard
  inputs (`prospects/ahead_of_consensus.py`, the scoring files) before this.
- **Post-unlock — the 028 epoch bump.** Phase 0 (gate) and every score-moving
  fix ride that single board re-baseline. One re-score, one disclosure, not
  several. Do not land score-moving changes outside it.
- **Operational:** no human push to master ~12:20–13:15 UTC any day (nightly
  build window; F1/F2).

Owners: **Codex executes** from a Fable brief; **Fable reviews the diff and
runs the gate.** The honest backtest is the gate — nothing ships that can't
pass it.

## Phase 0 — Fix the gate (the keystone). Rides the 028 epoch bump.

Everything downstream is judged by this harness, so it must be honest first.
Verified defects to fix (audit #2):

1. **F5 — QS-cohort truncation.** `prospects/adapter_backtest.py` drops any
   established pitcher whose representative season lacks `QS` (58 real seasons,
   1069 obs instead of 1127). Impute `QS=0` (or score the QS-free subset) and
   re-emit the artifact. **Restate the acceptance baseline: 0.4903 → ~0.4692 on
   n=1127.** 028's gate must target the corrected number; beating 0.4903 on the
   truncated cohort proves nothing.
2. **F4 — label leakage.** `model.py` `_impact_target` has no upper-season clip,
   so walk-forward folds train on post-fold outcomes and the "4.15% OOS"
   gate-reason is in-sample. Clip at `cohort_year + OUTCOME_HORIZON_YEARS`
   (mirrors dynasty/adapter). The retrain 028 already schedules reopens this
   function — land it there.
3. **Lead to assess here:** `prospects/universal.py` `_future_seasons` also
   uses an unbounded window, and universal IS the served model. Confirm/fix in
   the same pass.
4. **Regression locks:** add fold-leakage and cohort-cardinality self-checks to
   the harness so both defect classes fail the build if they recur.

Exit criterion: the harness passes its own leakage/cohort self-checks, and its
reported numbers are ones we'd stake the brand on.

## Phase 1 — Plumbing floor-sweep. Cheap, this-week, post-unlock.

One disease, many faces: silent partial data. Uniform cure — every fetcher gets
a prior-day floor, every validator a population floor, freshness a real date.
Verified items (audit #3), ranked cheapest-highest-value:

1. **F8 statcast** — floor `< 300` not `not batters` (normal 544/585). One line,
   widest blast radius (nearly every card).
2. **F7 roster** — per-team floor `< 15` not `not rows` (a truncated team
   currently overwrites a good one under the global 300 check).
3. **F4 availability** — transaction-count floor in the validator (normal 7863)
   + a prior-day-ratio guard before overwrite.
4. **F5 redraft ROS** — per-pool floor (normal 4693 hitter / 5883 pitcher).
5. **F6 MiLB** — make `validate_milb_stat_freshness_audit` FAIL on
   `status=blocked AND top50_history_fallback_count>0`; the detector already
   exists, the validator just accepts `blocked` as a valid shape.
6. **Coherence over freshness** — the nightly must be atomic: all artifacts from
   one run or none. F2 push gets a retry-with-rebase; a half-succeeded build
   should fail loud and serve yesterday, never commit a mixed-vintage site.
7. **F9 vintage** — replace `_board_source_date`'s mtime fallback with a
   git-content-date (or committed sidecar) and add FG; restores a true "last
   refreshed" to /gaps and /ledger (both currently qualitative/optimistic).
8. **F10 stale sources** — decide the STS/PL/FG refresh strategy (automate a
   fetch, or discount stale boards in the corroboration vote). A "live" vote
   from a 3-week-old board is a lie the gate is telling.
9. **Tripwires** — turn each of these findings into a permanent CI guard
   (population-drop, score-move-too-large, source-staleness) so regressions
   announce themselves instead of waiting for the next audit.

Attack-surface hardening (audit #4) folds in here: image-endpoint concurrency
semaphore, raw-query canonicalization, league-import streaming cap. (Cloudflare
in front of valucast.app is Alex's dashboard action — the durable cost-bomb fix.)

## Phase 2 — Attack the pitcher axis. Only through the honest ruler.

Pitcher concordance is ~0.49 (coin flip) vs ~0.78 hitters — that's where
accuracy bleeds. Two responses, in order:

1. **Calibration first (ships regardless):** widen the pitcher uncertainty band
   so the model stops over-claiming where it's weak. A model that owns its own
   confidence beats a slightly sharper overconfident one — and it's where a
   small shop out-executes a big one.
2. **Feature work (only if it beats the gate):** mine the pitch-level
   plate-discipline PBP we already own for stuff/command signals the field lacks
   at the MiLB level. The 028 pitcher-lean fixes (cap, concordance-gap
   down-weight, attrition discount) validate against the CORRECTED gate, never
   a day's count.

No pitcher feature enters the model until Phase 0's gate can measure it.

## Phase 3 — Start the projection archive NOW (parallel, uncompressible clock).

We cannot yet prove we beat Steamer/ZiPS — the forward gate is currently losing,
and we lack matched archived projections for a fair historical backtest. The
only fix is time: **archive dated projections from every source (ValuCast H+P,
Steamer, ZiPS where available) into a committed dated store, starting this
week,** so next season we finally have the apples-to-apples benchmark. Additive,
touches neither serving nor the model. Wire into the nightly post-unlock. The
urgency is measured in seasons, not days — which is exactly why it can't slip.

## The discipline (governs every phase)

No new signal enters the model until the gate can tell us whether it helped.
Feature ideas queue behind the honest ruler. This is the same discipline the
ledger already runs on — pointed at the model core instead of the public calls.
