# Consensus Decision Error Audit Design

**Date:** 2026-07-31

**Status:** Approved for evidence-only implementation

**Scope:** The 151 matured, decided calls in the frozen Ahead-of-the-Curve scorecard

## Objective

Explain where ValuCast's matured higher-than-consensus calls have succeeded,
moved away from the field, or been retracted. The audit is diagnostic. It must
not optimize the scorecard, change a rank or value, alter publication, or turn
consensus into a model input.

## Selected approach

Use a fixed-dimension, claim-time cohort audit and map any credible findings to
the challengers that are already registered. This is preferred to either a
descriptive-only memo with no forward path or a direct scoring/filter change
that would game the public accountability metric.

The audit may identify a new research hypothesis. It may not promote one. A
new hypothesis selected after this audit is exploratory and requires a new,
untouched future cohort before confirmation.

## Frozen population and outcomes

The source of truth is
`data/models/valucast_ahead_of_consensus_scorecard.json` at the implementation
commit. A decision belongs in the audit only when:

- `days_tracked >= 14`; and
- status is one of `open_toward`, `closed_caught_up`, `open_away`, or
  `retired_we_backed_off`.

Outcomes remain separate:

- **Win:** `open_toward` or `closed_caught_up`.
- **Moved away:** `open_away`.
- **Retracted:** `retired_we_backed_off`.

The frozen decided rate is reproduced as wins divided by all three outcome
classes. Moved-away calls and retractions are never merged in the diagnostic
tables.

## Claim-time join

Each decision joins by `identity_key` to the dated rank archive named by its
`ahead_since` date. No current-board field may substitute for a missing
claim-time field. The audit fails closed unless every matured decision joins to
exactly one row with the same role.

The output records SHA-256 hashes for the scorecard and the ordered archive
manifest. Source-level board names and ranks are never written to the audit
artifact or report. Only the qualifying external-board count may be retained.

## Predefined dimensions

The following dimensions are fixed before any result is inspected:

| Dimension | Bins |
|---|---|
| Role | hitter; pitcher |
| Level | complex/rookie; A/A+; AA; AAA; other/missing |
| Age | 19 or younger; 20-21; 22-23; 24 or older; missing |
| Confidence | low; medium; high; other/missing |
| Sample reliability | below 25; 25-49.99; 50 or higher; missing |
| Current sample, hitters | below 100 PA; 100-199; 200-399; 400+; missing |
| Current sample, pitchers | below 20 IP; 20-49.99; 50-99.99; 100+; missing |
| Initial gap | 25-49; 50-99; 100-199; 200+ |
| Claim-time consensus rank | 1-50; 51-100; 101-250; 251+ |
| External-board coverage | 2; 3-4; 5+ |
| Availability | available; limited; unavailable; other/missing |
| Score source | exact claim-time value, with uncommon values grouped as other |

Availability is mapped without interpretation: `available` remains available;
thin/current-limited states map to limited; injury, inactive, stale, or absent
states map to unavailable; everything else maps to other/missing.

## Statistics and guardrails

For every segment, report `n`, wins, moved-away calls, retractions, the three
rates, and a two-sided 95% Wilson interval for the win rate.

- Cells below 10 decisions are labelled `insufficient`, not ranked.
- A segment cannot become a candidate signal below 20 decisions.
- No p-values, best-segment selection, or significance claims are permitted.
- This is an exploratory error audit, not a confirmatory feature test.
- Overall matched-control performance is copied only as frozen context; no
  segment-level control comparison is reconstructed post hoc.

## Research disposition

Findings are checked first against the existing registrations:

- development density / injury-adjusted development time;
- position value by youth and level; and
- the post-2026 prospect challenger epoch.

Already-registered hypotheses retain their existing multiplicity and future-
cohort requirements. Athleticism, contact quality, organizational investment,
cross-role normalization, and player-specific patches remain non-actions unless
the audit establishes a distinct cohort-wide hypothesis and a separate future-
only registration is approved.

## Deliverables

1. A deterministic audit builder with pure binning and reconciliation helpers.
2. Tests that cover exact joins, exclusions, bin boundaries, reconciliation,
   small-cell labels, and the no-source-name/no-model-feed boundary.
3. `data/validation/valucast_consensus_decision_error_audit.json`.
4. `docs/audit-2026-07-31-consensus-decision-errors.md` with an answer-first
   assessment and explicit non-actions.

The artifact is internal validation evidence. It is not wired into the app,
daily workflows, scoring, rankings, values, buy signals, caps, Role Watch, or
publication decisions.

## Invariants

- Prospect scoring remains frozen at bucket calibration 0.3.2.
- The failed pitcher decay flag remains disabled.
- Consensus remains display-only and score-inert.
- The pitcher publication veto and every existing hold remain intact.
- No workflow is dispatched and no public claim is authorized by this audit.
