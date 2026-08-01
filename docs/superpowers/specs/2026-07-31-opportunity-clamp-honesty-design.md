# Opportunity Clamp Honesty Design

## Goal

Do not present a clamped rest-of-season opportunity value as a real role or
playing-time forecast.

## Root cause

The H+P builder subtracts current actuals from a Marcel full-season baseline.
When actual PA/IP exceeds that baseline, it correctly records
`remaining_opportunity_clamped: true` and clamps the remainder to zero. The
role tracker currently ignores that flag, marks the profile ready, and turns
zero into a bench/depth label.

## Design

- Add `remaining_opportunity_clamped` to the existing role contract and make it
  a blocker in `mlb/playing_time_role.py`.
- Keep the artifact's raw diagnostic role and volume for internal auditability,
  but mark the context blocked.
- At the single public context mapper in `app.py`, render every blocked role
  context as `Not rated`, hide volume, preserve availability/roster context,
  and provide a plain explanation for the clamp.
- Extend the existing validator so a newly built artifact cannot label a
  clamped row ready.
- Cover the contract and public mapping with focused regression tests.

## Boundaries

- No ranking, valuation, scoring, projection, or publication-cap changes.
- No change to H+P subtraction math or the model freeze.
- No new source, dependency, template, renderer, or workflow.
- The same public mapper serves web cards and share-card copy, preserving parity.

## Success criteria

For an active player whose remaining opportunity was clamped, the public card
shows `Projected Role: Not rated`, no `Volume`, the correct active-roster
context, and an honest source-data explanation. Ready, non-clamped profiles
render exactly as before.
