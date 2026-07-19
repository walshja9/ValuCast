# Trade Player-Only Honesty Design

**Date:** 2026-07-19
**Status:** Approved in conversation

## Goal

Make The Second Opinion honest about what it can evaluate today: listed players
only. A reader must not mistake its verdict for a complete evaluation of a deal
that also contains draft picks, FAAB, roster-slot effects, or league context.

## Approaches Considered

1. **Recommended: one shared player-only disclosure everywhere.** Render the
   same sentence on the empty trade page, every completed verdict, the share
   preview metadata, and the PNG itself.
2. **Page-only disclosure.** This is smaller, but a downloaded or unfurled card
   would lose the limitation and become misleading when separated from the page.
3. **Add draft-pick values now.** Rejected because the current repository has no
   validated FYPD pick-value curve. A guessed curve would replace an obvious
   omission with false precision.

The first approach is the smallest complete correction.

## Public Contract

Use one application-owned sentence as the source of truth:

> Player-only verdict: draft picks, FAAB, roster spots, and league context are not included.

- Show it beside the trade-input explanation before a user adds players.
- Show it with every rendered verdict, including inside-band, count-mismatch,
  and mixed-universe results.
- Carry the same sentence into every trade share PNG and share-preview
  description so the limitation survives reposting.
- Keep the current player values, sums, noise band, consolidation note, and
  mixed-universe note unchanged.
- Do not imply that ValuCast can detect whether the real-world deal contains an
  omitted asset. All current verdicts are labeled player-only unconditionally.

## Boundaries

- Change presentation and shared copy only.
- Do not add pick inputs, pick values, pick curves, roster imports, league sync,
  accounts, databases, dependencies, or new model features.
- Do not change rankings, values, the fixed trade noise band, pitcher caps,
  publication decisions, Role Watch, or League Connect.
- Preserve the model freeze and `PITCHER_STALE_PEDIGREE_DECAY_ENABLED = False`.
- Do not push, deploy, merge, or dispatch workflows in this slice.

## Testing

- A route test must fail before implementation because the exact disclosure is
  absent, then pass after it appears on both the empty page and a real verdict.
- A PNG renderer test must prove the same application-owned sentence is passed
  to the existing text-wrapping/render path; the existing PNG signature test
  continues to prove the image renders.
- The share-preview description must identify the result as player-only.
- Run focused trade tests, then the full automated suite and a 390x844 browser
  pass with no overflow, clipping, broken images, or new console errors.

## Deferred Pick-Valuation Study

Draft-pick support is a separate registered challenger study. It must define
league size, exact slot versus range, draft class, time horizon, replacement
level, historical cohorts, uncertainty, and strong public baselines before any
pick value can affect a trade verdict. Until that evidence exists, ValuCast says
what it does not know instead of inventing a number.
