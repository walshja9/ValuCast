# Sol Audit Brief — 2026-07-12

You are Sol, running an independent, adversarial, **read-only** audit of the
ValuCast codebase (this repo). You are a different model family from the one
that wrote and reviewed most of this code — your job is to find what
correlated reviewers missed. The recent precedent: five review agents and
1,900 passing tests missed that the prospect board carried a player who
debuted in May (internally consistent data, frozen assumption). Hunt for that
class: things that are consistent, tested, and wrong.

## Ground rules

- **Read-only.** No file edits, no commits, no `git add`/`stash`, no writes
  outside your own scratch space. Read-only HTTP GETs to `statsapi.mlb.com`
  are allowed for verifying data shapes; nothing else.
- **Findings format (non-negotiable):** every finding = one-sentence defect +
  `file:line` + a **concrete failure scenario** (inputs/state → wrong output a
  user or the public would see) + severity. No style notes, no "consider
  refactoring," no speculative maybes. If you can't trace the failure end to
  end, label it HYPOTHESIS and say what would confirm it.
- **Severity:** CRITICAL = a wrong number published on a public surface, data
  loss, or a crash on a served path. MAJOR = wrong behavior a user can see or
  a broken invariant. MINOR = everything else worth fixing.
- **Also report what you cleared:** for each target area, list what you
  examined and found clean. Silence must be distinguishable from "not
  checked."
- Rank all findings CRITICAL → MINOR in your final answer.

## What is at stake tomorrow (context, and why Target 1 is first)

The site's Ahead-of-the-Curve scorecard is pre-registered: targets (50%
decided rate, 1.5x matched-control lift) were frozen before data existed, and
a 30-day publish gate matures on **tomorrow morning's build (~12:40 UTC)** —
at which point `/ledger` automatically publishes the aggregate self-grade,
which currently reads as a MISS on the targets. We intend to publish that
miss. The one unacceptable outcome is publishing a **wrong** self-grade — a
bug in the scorecard math would be the worst possible failure for a brand
whose entire premise is honest self-measurement. The scoring files are frozen
until the unlock, so your audit is perfectly timed: findings land exactly
when fixes become possible.

## Target 1 (FIRST, highest stakes): the scorecard math

Files: `scripts/build_ahead_of_consensus_scorecard.py`,
`prospects/ahead_of_consensus.py` (both frozen — READ ONLY),
`data/models/valucast_ahead_of_consensus_scorecard.json` (current artifact),
`templates/track_record.html` (what publishes), and the archive readers they
use (`data/prediction_archive/valucast_prospect_rank_v1/*.json`).

Attack, at minimum:

1. **The decided-rate denominator.** Definition in the artifact:
   `wins (open_toward + closed_caught_up) / (wins + open_away +
   retired_we_backed_off)`. Verify the implementation matches the definition,
   and that the definition itself can't double-count or drop a row (a call
   that is both retired AND moved toward us; a call that flips
   toward→away→toward).
2. **Retreat classification.** 65 of 118 decided outcomes are
   `retired_we_backed_off`. Verify what triggers "we backed off" — if daily
   model-score jitter (documented: a 7/7 retrain moved 185 pitchers ≥2 pts in
   one night) can retire a call without a real conviction change, quantify
   how; if a retired call's player later graduates as a hit, verify it isn't
   still counted against us.
3. **Matched-control construction.** How are controls matched (level, role,
   rank band, date)? Attack for selection bias in either direction: could the
   control pool systematically contain players the boards were about to move
   on anyway, or players who can't move (unranked everywhere)?
4. **Lift computation.** `control_lift` = which cohorts, matured or all? The
   artifact carries both `control_rates` (n=213) and `control_matured_rates`
   (n=147) plus `open_rates`/`matured_open_rates` — verify the published
   lift compares like with like (matured vs matured), and that the template
   prints the same number the artifact computes.
5. **Date/maturity arithmetic.** `horizon_days` (29 today, gate needs 30),
   `maturity_days` = 14, first_call_date 2026-06-13. Attack the boundaries:
   timezone of "day," off-by-one on the horizon (does the gate open on day 30
   or day 31?), calls made mid-window aging correctly, the maturity cut
   actually filtering what it claims.
6. **The `left_universe: 0` and `resolved_called_up_or_graduated: 0` lanes.**
   Both funnel lanes have never fired. Known context: the prospect universe
   has a graduation gap (7 players past rookie thresholds still listed — see
   "known issues"). Verify whether these lanes are dead code, blocked by the
   graduation gap, or genuinely zero — and what happens to open calls on
   players who SHOULD have left the universe.
7. **Template honesty.** `templates/track_record.html:55-100` — when
   `publishable` flips True tomorrow, verify every number printed traces to
   the artifact field it claims (decided_rate rounding, lift, the toward-rate
   comparison line), and that the funnel tiles sum to `ever_flagged`.

## Target 2: the newest public surfaces (least soak time)

- **Trade tool** (`app.py` — search `_trade_verdict`, `_trade_piece`,
  `_parse_trade_ids`, `_build_trade_page_context`, `_trade_share_card_png`,
  routes `/trade`, `/trade/share-card.png`): verdict math (noise band =
  ±9/player scaled by side size), consolidation and cross-universe notes
  firing correctly, id parsing against hostile input, PNG cache keys
  (`_PNG_CACHE_PARAMS` must contain `give`,`get` — regression class from plan
  007/022), content-fit height math (canvas growth for 6v6 + all notes).
  Known context: values come from a universe where 7 players are stale
  (graduation gap) — do NOT re-report that; attack the tool's own logic.
- **Plate-discipline layer** (`prospects/pitch_discipline.py`,
  `scripts/build_pitch_discipline.py`, `web/pitch_discipline_store.py`, card
  section in `templates/partials/player_detail_dynasty.html`, PNG strip in
  `app.py` `_prospect_player_card_png`): counting definitions (swing/whiff
  taxonomy vs MLB description strings — hunt for descriptions we misclassify),
  calibration (train/held split integrity, per-pair strike zones, the 85%
  gate), per-bucket `zone_estimated` flags (AAA measured vs lower-level
  estimated), the 300-pitch floor (394 sub-floor buckets carry populated
  rates — verify nothing serves them ranked), fail-soft reader guarantees,
  incremental-mode CI guards (cold cache exit-0, new-pk budget, error
  budgets, non-Final skip).

## Target 3: design critique of the pending model surgery

Read `docs/governor-review-2026-07-13-pitcher-lean-memo.md` then
`plans/028-pitcher-lean-model-fix.md`. You are not executing it — attack the
DESIGN: does pedigree decay create new artifacts at the boundaries (a
2025 draftee crossing the "adequate sample" line mid-season)? Does the
attrition discount double-count anything `prospects/availability.py` already
prices? Is the acceptance gate (backtest concordance + three named arms
surviving top-25) gameable or under-specified? Is the epoch-bump requirement
sufficient to keep movers/buys from reporting the re-score as player
movement?

## Known issues — do NOT re-report these

1. Graduation gap: 7 players past rookie AB/IP thresholds still on the
   prospect board (Bolte #21, Emerson #41, Eldridge, Ewing, Mack, Avila,
   Lee). Fix queued post-unlock. (But DO report anything this breaks that we
   haven't listed — e.g. Target 1 item 6.)
2. Buys momentum reacts to nightly re-baselines (movers masks them, buys
   doesn't). Fix queued post-unlock.
3. Player card shows named per-source board ranks (`player_detail_dynasty.html:579`)
   — open product ruling, known.
4. The pitcher-lean itself (11 P in top-25) — documented in the memo.
5. Telegram digest secrets are empty; digest ASCII-fold fix just shipped.
6. `data/dd/dd_dynasty_feed.json` untracked in the worktree — expected.

## Deliverable

One report, findings ranked CRITICAL → MINOR in the format above, then the
cleared-areas list per target. If Target 1 yields ANY finding rated MAJOR or
CRITICAL, flag it at the very top with the words SCORECARD FINDING so it is
impossible to miss before tomorrow's build.
