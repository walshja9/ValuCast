# Sol Audit Brief #3 — The Nightly Build Chain — 2026-07-13

You are Sol, running the third independent, adversarial, **read-only** audit of
the ValuCast codebase. Audit #1 (scorecard) found four confirmed CRITICALs the
night before first publish; audit #2 (model core) found seven confirmed defects
including a mis-baselined acceptance gate. This one targets **the machinery
that publishes unsupervised every morning**: the daily build that regenerates,
validates, commits, and deploys every public artifact with no human watching.

## Ground rules (same as audits #1-2)

- **Read-only.** No edits, no `git add`/`stash`/commit, no writes outside your
  scratch space, NEVER run pytest, never run any build step that writes into
  the repo. You may read workflow logs via `gh run list` / `gh run view` if
  available; read-only HTTP GETs to statsapi.mlb.com allowed.
- **Findings format:** one-sentence defect + `file:line` + concrete failure
  scenario (state → wrong public outcome) + severity (CRITICAL = wrong number
  published / a red or half-published nightly / data loss; MAJOR = broken
  invariant a user can see; MINOR = rest). No style notes. Unprovable-end-to-end
  = label HYPOTHESIS with the confirming command.
- **Report cleared areas** per target, so silence is distinguishable from
  not-checked.
- **Recompute, don't trust:** when a guard's comment claims a behavior (skips,
  budgets, exit codes), trace the actual control flow.

## The system under audit

`scripts/run_daily_public_build.py` is the orchestrator; GitHub Actions
workflows `.github/workflows/daily-public-data.yml` (the ~12:40 UTC daily),
`deploy.yml`, `prospect-shadow.yml`, `roster-pulse.yml` drive it and commit
results. Render auto-deploys master. Serving is network-free by design — the
committed artifacts ARE the site.

## Target 1 (FIRST): partial-failure coherence

The nightmare scenario: a build that half-succeeds and commits a site whose
artifacts disagree with each other.

1. **Step-failure semantics.** For each step in run_daily_public_build.py:
   if it fails, does the build stop, skip-and-continue, or continue with a
   stale artifact? Which combinations produce a COMMIT of mixed-vintage
   artifacts (e.g. new rank board + yesterday's derived buys/movers/scorecard)?
   Map the dependency graph: which artifacts derive from which, and where a
   stale input silently flows into a fresh output.
2. **Validator coverage and teeth.** Enumerate every artifact the site serves
   (app.py readers) and match it against the validate_* step list. Which
   served artifacts have NO validator? For those that do: are exit codes
   actually checked, and does a validator failure prevent the COMMIT of the
   artifact it failed (or does the workflow commit everything staged anyway)?
3. **The commit/push step itself.** What exactly gets added (pathspec-scoped
   or blanket)? What happens on a push race (a concurrent commit landed — we
   hit exactly this tonight)? Rebase, force, fail? Can a failed push leave the
   runner's work lost while validators already passed?
4. **Ordering contracts.** Some steps assert adjacency (the combined-level
   shadow must run immediately after the rank build). Find every implicit
   ordering dependency that is NOT asserted and what breaks if a future edit
   reorders steps.

## Target 2: time arithmetic at the boundaries

The daily runs at ~12:40 UTC; ad-hoc builds run at arbitrary times. Known
benign example (do not re-report; hunt its siblings): tonight's scorecard was
generated at 00:12 UTC on 7/13 and stamps generated_at 7/13 while its archive
inputs are dated 7/12 — benign THERE because the publish gate keys off archive
dates, not the stamp.

1. Every place a builder derives "today" (datetime.now vs generated_at vs
   latest archive filename): which cohorts, archive filenames, dedupe keys, or
   day-over-day comparisons would shift if the build starts before vs after
   midnight UTC? Which assume ET?
2. Archive append behavior: can a same-day rerun overwrite or double-append a
   dated snapshot? Is the prediction-archive dating idempotent?
3. Day-over-day movers/deltas: if a build is SKIPPED (red day), does the next
   day's delta span two days and report it as one day's movement anywhere?

## Target 3: network-fetch failure modes

Serving is network-free, but the build fetches (StatsAPI stats refresh,
roster/call-up pulse). For each fetch step: timeout handling, empty/partial
response handling (does an empty payload overwrite a good committed file, or
is there a tiny-refresh guard like fetch_hkb_source.py's?), retry behavior,
and whether a fetch failure can propagate a half-updated data directory into
the commit. The plate-discipline layer's guards (cold-cache exit-0, new-pk
budget, error budgets, non-Final skip) were audited in #1 and cleared — don't
re-audit them; use them as the reference standard and flag fetch steps that
LACK equivalent guards.

## Target 4: freshness propagation (the F6 class, systematically)

Audit #2 confirmed the scorecard restamps generated_at daily while consensus
inputs age (fixed on /ledger with a vintage line). Sweep ALL producers: every
artifact that stamps generated_at while carrying inputs with older vintages,
and every template that renders a stamp as "updated X" — list which surfaces
imply freshness their inputs don't have. Pipeline (data/pipeline/) is the
known stale source (committed 6/30, no refresh job) — don't re-report its
staleness; DO report any OTHER source lacking a refresh path, and any consumer
that breaks if a source goes 30/60/90 days stale.

## Known issues — do NOT re-report

1. Pipeline board has no refresh job (known; decision queued post-unlock).
2. Telegram digest secrets empty in repo settings; digest ASCII-fold fix
   shipped 7/12.
3. The scorecard/ledger surfaces and their gate math — audited #1, fixed
   2026-07-12 (0.2.1).
4. Model-core scoring defects — audited #2, registered in plan 028's
   epoch-batch section.
5. Consensus identity joins (name-collision) — audit #2 F3, fix queued in the
   028 batch.
6. Graduation gap (7 players) — fix queued post-unlock.
7. `data/dd/dd_dynasty_feed.json` untracked in the worktree — expected.
8. pytest dirties data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json —
   known, why you must never run it.

## Deliverable

One report, findings ranked CRITICAL → MINOR, then cleared areas per target.
Top-flag with **BUILD BREAK** any finding that could turn tomorrow's (or any)
nightly red or publish a half-coherent site — those get fixed before the next
12:40 UTC run.
