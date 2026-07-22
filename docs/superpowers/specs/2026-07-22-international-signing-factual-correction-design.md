# International Signing Factual Correction

**Date:** 2026-07-22
**Status:** Approved preview; implementation and publication pending external and final review

## Decision

Use the 13 source-backed international signing bonuses in
`data/prospects/raw/international_signing_facts.json` only in Prospect Rank
v1's existing `factual_investment_context` component.

Do not pass these bonuses into the v0.6 prospect model or the universal
prospect model. Do not change any weight, formula, availability adjustment,
quality governor, pitcher control, hold, or publication rule.

## Why

The current rank input treats each verified player as having missing
investment evidence and substitutes the existing score of 25. Replacing that
missing value with the verified bonus removes a factual coverage gap.

The universal model was trained primarily on Rule 4 signing data. Applying its
learned bonus effect to international signees would be an unvalidated model
change, so that path stays frozen for a later registered challenger study.

## Data Flow

1. Validate the committed evidence artifact: unique MLBAM IDs, positive
   bonuses, supported acquisition type, source URL, and verification date.
2. At Prospect Rank v1 build time, overlay the verified bonus only onto a
   rank-local copy of matching current hitter inputs whose bonus is missing.
3. Build the rank with the existing factual-investment formula and weights.
4. Leave the canonical model input contract unchanged, ensuring the v0.6 and
   universal model builders cannot consume the overlay.
5. Record the evidence artifact in rank provenance and report the corrected
   rows in the coverage audit.

Invalid, duplicate, unmatched, or conflicting evidence must fail closed rather
than silently alter the board. An already-populated identical bonus is an
idempotent no-op; an already-populated different bonus is a conflict.

## Approved Preview

The preview reproduces the committed 2,851-row board exactly before applying
the correction. After applying only the factual correction:

- all 13 corrected players gain value and none lose value;
- no unrelated player's value changes;
- 43 rows change rank because of ordinary displacement;
- top-25 composition remains 15 hitters and 10 pitchers;
- top-50 membership and composition remain unchanged; and
- the v0.6 and universal model artifacts remain frozen.

The largest rank changes are Leo De Vries from 36 to 22, Lazaro Montes from 50
to 38, Nelson Rada from 38 to 27, Leo Bernal from 48 to 40, and Angel Genao
from 28 to 21.

The exact preview artifact is generated locally at
`tmp_investment_counterfactual/2026-07-22-direct-only.json` and remains ignored
by Git.

## Verification Gates

Before publication:

1. A regression test must fail before the overlay exists and pass after it is
   implemented.
2. The unchanged baseline must reproduce current identity, rank, score, and
   component fields exactly.
3. The corrected build must match the approved 13-player preview exactly.
4. The v0.6 and universal model artifacts must remain byte-identical.
5. No unrelated player value may change.
6. Full automated tests and the existing rank validators must pass.
7. The implementation diff and preview receive an independent Claude review.
8. Codex performs a final diff, governance, data, and regression review.
9. Publication requires a separate explicit user approval after both reviews.

## Challenger Follow-up

The later universal-model study needs historical international signing facts
and future outcomes. It must compare the incumbent, a no-bonus baseline, and an
acquisition-aware challenger under the registered post-2026 process. These 13
current players alone are not a training dataset and authorize no model change.

## Non-goals

- Retraining or promoting either prospect model.
- Changing the core 76% v0.6 contribution.
- Changing the universal-model contribution.
- Reweighting investment context.
- Changing pitcher ranks, caps, or publication decisions.
- Publishing before the review sequence is complete.
