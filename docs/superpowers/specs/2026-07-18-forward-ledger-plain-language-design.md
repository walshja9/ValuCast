# Forward Ledger Plain-Language Design

**Date:** 2026-07-18
**Status:** Approved in conversation

## Goal

Make the live Forward Ledger understandable before a reader encounters its statistical terminology, while preserving every existing honesty disclosure and technical measure.

## Design

The first screen leads with a dynamic, sign-aware result: `EARLY RESULTS: N DAYS AHEAD`, `N DAYS BEHIND`, or `EVEN WITH THE FIELD`. A one-sentence explanation translates the result using the settled-call count and says plainly that it is too early to declare a win.

The formal name `Anticipation Score`, confidence interval, sample size, provisional state, one-board comparison, registration metadata, and full funnel accounting remain visible below. Metric tiles use reader language: `Moved our way`, `Moved against us`, `Calls we changed`, and `Still waiting`.

## Boundaries

- Change display copy only in `templates/forward_scoreboard.html`.
- Add a render contract to `tests/test_forward_scoreboard_page.py`.
- Do not change scoring, artifacts, ranks, values, cohorts, hold gates, share-card rendering, model flags, Role Watch, or League Connect.
- Preserve the model freeze and `PITCHER_STALE_PEDIGREE_DECAY_ENABLED = False`.

## Verification

The page test must fail on the current technical-first copy, pass after the template change, and continue asserting the confidence interval, provisional warning, registration metadata, and funnel totals. Then run the full pytest suite and a 390x844 browser pass with no overflow, clipped elements, broken images, or console errors.
