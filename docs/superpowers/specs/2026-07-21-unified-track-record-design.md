# Unified Track Record Design

**Date:** 2026-07-21
**Status:** Approved for planning

## Goal

Give readers one plain-English place to understand ValuCast's public evidence without learning three overlapping product names or mixing incompatible denominators.

## Product shape

Reuse the existing `/ledger` page as the public **Track Record** hub. Do not add a fourth evidence system or a new scoring artifact. The hub reads the three existing committed artifacts and links to the existing detailed views.

The overview contains three sections:

1. **Forward Calls — Did our published calls prove right?**
   - Show wins, losses, clean retractions, and open calls.
   - Show the win rate only as `wins / (wins + losses)` and print the denominator beside it: `39–31 across 70 scored calls (56%)`.
   - State that the scorecard remains provisional while its registered expiry window has not matured.

2. **Consensus Movement — Did the market later move toward our different view?**
   - Show `46 of 147 mature decisions (31%)`.
   - Describe this as market movement toward ValuCast, not player-outcome accuracy and not proof that ValuCast beat consensus.
   - Keep the matched-control comparison visible wherever the movement rate is shown.

3. **Call-Up Timing — Did we identify prospects before their MLB promotions?**
   - Show `7 clearly ahead · 0 clearly behind · 33 without a large enough ranking gap to score`.
   - Describe these as arrival receipts, not career-value wins.
   - Keep maturation separate: pending, confirmed, or decayed according to the existing registered workload rules.

Rates from these sections must never be blended. Each percentage prints its numerator and denominator.

## Call-up scoring disclosure

The Call-Up Timing summary always includes one visible sentence:

> Call-ups are scored only when our archived pre-promotion ranking differed clearly from the public field.

An adjacent **How scoring works** disclosure contains the exact rules:

- Consensus requires at least two public boards, using ranks inside the top 600.
- ValuCast scores ahead when its rank is inside the top 300 and at least 25 places better than consensus.
- ValuCast scores behind when consensus is inside the top 300 and ValuCast is at least 25 places worse.
- With fewer than two qualifying boards, only exceptional top-25 cases score: a ValuCast top-25 ranking can score ahead; the mirrored behind case requires one public top-25 ranking and ValuCast at least 25 places lower.
- Every other post-launch promotion is shown as having no scoreable ranking gap. It is not called a miss and is not described as lacking an “eligible prior call.”

## Copy rules

- Use **Track Record** as the umbrella label.
- Use **Forward Calls**, **Consensus Movement**, and **Call-Up Timing** as evidence types, not competing product brands.
- Keep `/scoreboard` and `/receipts` as detailed drilldowns. Existing URLs remain valid.
- Replace “called up N days before the field did” with the provable statement: “Ranked for N consecutive archived days before the MLB call-up; field median #X at promotion.”
- Never use `56%` without `39–31 across 70 scored calls` nearby.
- Never describe `31%` as a win rate.
- Never describe a no-score call-up as unranked unless the archived row actually has no ValuCast rank.

## Data and gates

The hub composes, without recalculation:

- `data/models/valucast_forward_scoreboard.json`
- `data/models/valucast_ahead_of_consensus_scorecard.json`
- `data/models/valucast_call_up_receipts.json`

All existing publication and hold gates continue to apply. If a section is held or its artifact is unavailable, omit its metrics and show the existing neutral held/unavailable explanation. A missing section must not cause the rest of the Track Record to fail.

No model, rank, value, cap, Role Watch, publication decision, or artifact-builder logic changes are in scope.

## Verification

Add focused render tests that prove:

- every percentage is paired with its numerator and denominator;
- the three evidence populations remain separate;
- the Call-Up Timing disclosure contains the 2-board, 25-place, top-300, and low-coverage top-25 rules;
- no-score call-ups use “no scoreable ranking gap” language;
- the receipts hold suppresses receipt metrics on the hub;
- the lead-time sentence describes archived ValuCast duration, not time “before the field”;
- existing `/scoreboard`, `/ledger`, and `/receipts` URLs still render.

Run focused template tests, the existing scorecard and receipt validators, and a mobile browser pass before release.
