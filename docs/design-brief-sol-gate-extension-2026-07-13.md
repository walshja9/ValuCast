# Sol Design Brief #5 — Extend the Gate to the Scoring Layer — 2026-07-13

You are Sol, running a **read-only design review** — not an audit. Your first
four audits found the defects; this brief asks you to design the fix for the
deepest one you found: **the backtest gate cannot see the scoring layer it is
supposed to police.**

## Ground rules (same fence as the audits)

- **Read-only.** No file edits, no commits, no `git add`/`stash`, no writes
  outside your own scratch space. You may RUN existing scripts only if they
  write nothing into the repo; never run pytest (it dirties a committed
  archive file).
- **Every claim about current code needs `file:line`.** Your mechanisms have
  been consistently right and your specifics consistently wrong — counts,
  vintages, configs. Anything you did not directly read in this run, label
  HYPOTHESIS with the exact command that would confirm it. Unlabeled specifics
  will be treated as unverified and cost credibility.
- **A measurement ceiling is a success outcome.** If part of the scoring layer
  CANNOT be validated out-of-sample with data this repo holds, saying so
  precisely — and specifying the best honest standard below that ceiling — is
  exactly what we need. Do not invent a gate that flatters feasibility.

## Context — why this brief exists

Phase 0 (committed 2026-07-13) made the adapter backtest honest at the MODEL
layer: pitcher concordance 0.4692 on n=1127 (was 0.4903 on a QS-truncated
cohort), hitter 0.7791 on n=1091, label windows clipped to
`cohort_year + OUTCOME_HORIZON_YEARS` in `model.py`, `universal.py`, and both
backtests. That ruler now judges what it can see.

What it cannot see: `prospects/adapter_backtest.py` imports neither
`prospects/rank_v1.py` nor `prospects/availability.py`. Plan 028's main levers
— the stale-pedigree cap on the main score path, the pitcher concordance-gap
down-weight, the attrition base-rate discount — all land at the RANK layer,
outside the measurement. 028's current acceptance standard for those levers is
a set of player assertions (named pitchers out of the top 16, consensus arms
in the top 25, governor pitcher-share green). Assertions are not measurement:
they can be satisfied by tuning until the named players move, which is the
in-sample trap with extra steps. We deferred 028's scoring-side execution
rather than ship a public board re-baseline on that standard.

Your job: **design the minimal extension of the honest gate that makes
rank-layer changes measurable — or prove precisely how far that is possible.**

## Target 1 — the replay-feasibility question (answer this first)

The core question everything hangs on: **can `rank_v1`'s scoring path be
replayed for a historical cohort at all?** Trace what `rank_v1.py` and
`availability.py` consume (current rosters, IL status, consensus boards, FV
pedigree, playing-time feeds — whatever you actually find) and classify each
input as:

- (a) reconstructible for past cohorts from data committed in this repo
  (dated archives, season stats, the prospect outcome dataset);
- (b) current-only (exists only as a live snapshot — e.g. today's IL list),
  meaning any "historical replay" through it is silently anachronistic;
- (c) partially reconstructible with stated approximations.

The output of Target 1 is a table: input → class → evidence (`file:line` or
data path). This table IS the measurement ceiling. Be exhaustive here; the
rest of the design inherits its honesty from this step.

## Target 2 — the gate design, under the ceiling

Given Target 1, design the strongest honest gate for rank-layer changes.
Address at minimum:

1. **If full historical replay is feasible** for some subset of the rank path:
   spec a walk-forward rank-layer backtest mirroring the adapter harness
   (cohorts, folds, the concordance metric, fixed 4-year horizon), and state
   which 028 levers it can and cannot reach.
2. **If replay is infeasible** for the availability/pedigree inputs (likely):
   design the fallback standard. Candidates to evaluate honestly, not rubber-
   stamp: ablation gates (score the current universe with the lever on/off and
   bound the blast radius against pre-registered invariants), backtested
   PROXIES (e.g. the attrition discount's base rates are themselves derivable
   from historical cohorts even if the full rank replay is not), and
   distribution-shift guards (rank-order stability vs the consensus median).
   For each: what failure mode of 028's levers would it actually catch, and
   what would slip through?
3. **Pre-registration.** Whatever the gate is, its acceptance thresholds must
   be stated BEFORE 028's levers are tuned — otherwise the gate is tuned along
   with the model and measures nothing. Spec the exact numbers/invariants to
   freeze and where they should live (the 028 plan? a registered spec file?).
4. **Multiple-comparisons discipline.** The pitcher cohort is small and the
   levers are three. If 028 iterates against the gate, how many looks does the
   evidence budget allow before the gate is overfit? Give a concrete rule, not
   a caution.

## Target 3 — attack your own design

Turn adversarial on the thing you just designed. The three named traps, plus
whatever you find:

- **Anachronism leaks:** any replay that touches class-(b) inputs from Target
  1 — show where a designer would accidentally wire one in.
- **Goodhart risk:** for each gate criterion you proposed, how would a
  well-meaning executor satisfy the letter of it while making the board worse?
- **The assertion trap in new clothes:** does any part of your design reduce,
  under pressure, to "tune until the named players move"? If yes, mark it.

## Known context — do not re-derive

- The pitcher axis may be near its irreducible ceiling (~0.47 concordance vs
  0.78 hitters); 028's calibration slice (uncertainty widening, down-weight at
  parity) ships regardless of the feature work and is NOT blocked on this
  design.
- The epoch-bump protocol (one public re-baseline per deliberate re-score) is
  settled — your design constrains WHEN 028 ships, not how it discloses.
- Audits #1-#4 findings are fixed or queued; do not re-report them.
- `data/dd/dd_dynasty_feed.json` untracked in the worktree — expected.

## Deliverable

One report, in this order:

1. **The Target 1 table** (replay feasibility per input — the ceiling).
2. **The recommended gate design** with its pre-registered acceptance criteria
   stated as numbers/invariants ready to freeze.
3. **What the gate still cannot catch** — the residual, stated plainly.
4. **The self-attack findings** from Target 3.
5. **Cleared/checked list** so silence is distinguishable from not-checked.

Every specific (a count, a path, a config) either carries `file:line` evidence
from this run or the HYPOTHESIS label. The design will be adversarially
verified before anything is built from it.
