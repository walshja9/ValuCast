# Prospect Evidence Honesty Design

**Date:** 2026-07-19
**Status:** Approved and implemented on the feature branch; not released
**Supersedes:** The outcome-mix and Peak Outlook probability requirements in the
2026-07-18 share-parity design and the preservation requirement for those fields
in the 2026-07-19 player-card hierarchy design.

## Goal

Keep useful prospect context on the public player card without presenting
shadow-only or heuristic display layers as calibrated player probabilities.
This is a presentation correction only. It does not change any model, rank,
value, cap, role decision, or publication gate.

## Approaches Considered

1. **Recommended: remove false precision and retain qualitative scenarios.**
   Hide the shadow outcome distribution and the heuristic Peak percentages,
   while keeping plainly labeled ceiling, floor, evidence strength, and window.
2. **Relabel the existing percentages with stronger caveats.** This preserves
   information density but still gives uncalibrated point estimates undue
   authority and does not resolve the mixed-neighbor-cohort problem.
3. **Remove both panels completely.** This is safest but unnecessarily discards
   useful qualitative peak and attribution context.

The first approach provides the shortest honest correction.

## Public Card Behavior

### How ValuCast graded him

- Do not render `row.outcome_mix` or any four-year percentage distribution.
- Keep only fields that genuinely explain the live grade: rank/value drivers,
  applied score effects, sample context, and the existing uncertainty range.
- Do not add replacement probability wording or a historical-neighbor count.
  Those belong in research surfaces until the dynasty layer's live-consumer gate
  is active.

### Peak Outlook

Keep the existing card container but reduce it to qualitative scenario context:

- **Ceiling scenario:** existing peak-role label.
- **Floor scenario:** existing floor-role label.
- **Evidence strength:** existing Peak confidence label, explicitly scoped to the
  evidence behind the scenario.
- **Window:** existing ETA window when present.

Do not render:

- numeric Peak score;
- numeric upside/delta;
- generic `Risk` label;
- heuristic role-probability bars;
- copy describing those percentages as a forecast or model probabilities.

The labels are scenarios, not promised outcomes. Missing fields remain omitted.

### ValuCast Read

- Do not let generated prospect prose restate heuristic role percentages or
  use projection language, generic risk bands, likely outcomes, or settled role
  forecasts. MLB-equivalent prospect rates use `translates to` wording instead.
- At display time, fall back to the deterministic performance read when a
  cached generated read contains that language. Legacy deterministic templates
  that say `likely outcome` or `profiles as` are reframed as explicit
  current-performance ceiling scenarios.
- Future generated reads receive only qualitative ceiling, floor, evidence
  strength, and window context; role probabilities, numeric risk, trajectory,
  and projected skill grades are excluded from their grounding.
- MLB rate projections are unaffected by this prospect-only guard.
- The player card, scouting page, team board, and share-card context all use the
  same public display boundary.

## Share Graphics

The share-parity contract follows the corrected public card:

- do not add outcome-mix percentages;
- do not add Peak score, delta, generic risk, or role-probability bars;
- qualitative ceiling, floor, evidence strength, and window may be added only
  when the share-card implementation reaches that section;
- the existing PNG need not be redesigned for this correction.

## Model and Release Boundaries

- Preserve the model freeze and failed pitcher-decay flag.
- Do not change universal, dynasty, Peak, rank, value, Role Watch, pitcher cap,
  League Connect, or publication logic.
- Do not dispatch workflows, deploy, merge, or push as part of this correction.
- Leave shadow artifacts intact for research and forward validation.

## Testing

Focused render tests must prove that prospect HTML:

- does not expose outcome-mix percentages or `Not established by Year 4`;
- does not expose Peak score, upside, generic risk, or role-probability bars;
- still exposes qualitative ceiling, floor, evidence strength, and window when
  provided;
- still exposes actual attribution effects and uncertainty context;
- never renders `Bust risk`.
- falls back from generated prospect prose containing heuristic outcome claims,
  while leaving supported MLB projection-rate prose unchanged.

Update share-parity contract tests or documentation assertions so they no longer
require the removed fields. Then run focused card tests, the full automated suite,
and phone/desktop browser checks. Verify model and generated data artifacts are
unchanged.

## Deferred Evidence Work

A public outcome distribution requires a registered, jointly coherent outcome
model with one documented cohort definition, neighbor-count sensitivity,
out-of-fold reliability, uncertainty intervals, and forward evidence. A public
Peak probability forecast requires realized-role calibration against simple
baselines. Both remain display-only research until their existing gates pass.
