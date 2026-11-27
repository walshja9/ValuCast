# Fable Review Corrections Design

## Goal

Correct the six reproduced defects from the post-merge review without changing model weights, frozen prospect scoring, pitcher caps, or publication thresholds.

## Design

- Apply dynasty horizon multipliers on the same pool-floor-shifted scale already used by the post-processors. The horizon builder will receive the pool baseline and use one shared scalar helper, so negative values cannot improve when age or reliability declines.
- Rebuild AVG, SLG, and ISO from counting components. Rebuild OBP only when HBP is actually present; otherwise preserve the supplied OBP and combine it with rebuilt SLG for OPS. Missing data is never silently treated as zero.
- Keep the exact sign test, but centralize its public verdict. A leading claim requires both a significant positive sign result and a positive median; ties are labeled even, and significant negative results are labeled behind. The validator will recompute every count, direction, p-value, significance flag, basis, and label.
- Make the registration pin test fail closed and give CI full history. Update the factual-current-context contract to match the fields actually emitted.

## Alternatives rejected

- Clamping dynasty values at zero would destroy the signed scale.
- Estimating missing HBP would invent data.
- Letting the page reinterpret scoreboard fields would preserve the current split-brain behavior.
- Adding new statistical libraries or schemas is unnecessary.

## Verification

Each defect gets a failing regression test before its implementation change. Run the focused suites, the broader affected suite, `git diff --check`, and the full pytest suite before handoff.
