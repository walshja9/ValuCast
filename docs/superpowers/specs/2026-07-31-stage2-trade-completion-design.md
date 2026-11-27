# League-Aware Trade and Stage 2 Completion Design

**Date:** 2026-07-31
**Status:** Approved in conversation; implementation pending spec review

## Goal

Close the remaining product and evidence gaps without changing a live score,
rank, value, model flag, pitcher publication decision, or public claim.

This is completion work, not a new model program:

1. verify the already-shipped League-Aware Second Opinion V2 against its
   approved contract; and
2. preserve the missing dated Stage 2 format evidence needed by the already
   registered post-2026 validation program.

## Current state

League-Aware Second Opinion V2 is already on `master`. It:

- adjusts trade values for `teams x roster` replacement depth;
- applies a recognized scoring preset when every trade piece is an MLB player;
- fails closed to base values for prospect or mixed trades because prospect
  format scores are not calibrated onto the shared MLB/prospect value scale;
- labels prospect slots and competitive window as context-only; and
- carries the same state and disclosures on the page, preview, PNG, and cache
  key.

Stage 2 already has complete retrospective category evidence. The committed
readiness artifact reports all hitter and pitcher 7x7 categories ready after
the official quality-starts join. It correctly remains blocked because:

- the incumbent impact target is not direct 7x7; and
- exact historical decision-time replay cannot be reconstructed.

Plan 034 already registers the next direct realized-value look, forbids its
execution before 2027-01-01, and reserves the cross-universe trade mapping as a
separate forward decision track. This work must not create a competing look.

## Approaches considered

1. **Selected: verify the product and complete forward evidence capture.**
   Reuse the existing trade tests and renderer. Add only the missing dated
   archive of the existing research-only prospect league adapters. This keeps
   the future registered evaluation reconstructable without running it early.
2. **Run a new retrospective direct-7x7 evaluator now.** Rejected because it
   conflicts with Plan 034's frozen timing, folds, endpoints, and multiplicity
   controls.
3. **Apply current prospect adapter scores directly in mixed trades.** Rejected
   because within-role adapter scores are not calibrated onto the shared
   MLB/prospect 0-100 value scale.

## Product completion contract

No new trade math or controls are added.

Completion means the current implementation passes:

- legacy URL parity;
- shallow-versus-deep replacement behavior;
- MLB-only preset application;
- prospect/mixed preset fail-closed behavior;
- inert `pslots` and `window` totals;
- invalid-setting fallbacks;
- duplicate, one-sided, count-mismatch, and cross-universe guards;
- page, preview, PNG, and cache-key parity; and
- a 390x844 browser pass.

If a failure appears, fix the shared root cause with the smallest tested diff.
If all checks pass, no trade code changes merely to create activity.

## Stage 2 forward-evidence contract

The dated Prospect Rank v1 archive already preserves exact daily rank, score,
role, availability context, score source, and component output from 2026-06-13
forward. The missing format-specific input is the daily prospect league-adapter
artifact.

Extend the existing adapter writer rather than add a new framework:

```text
data/models/valucast_prospect_league_adapters.json
  -> data/prediction_archive/valucast_prospect_league_adapters/YYYY-MM-DD.json
```

The dated artifact is the exact adapter payload already built that day. It
retains:

- `generated_at` and the universal model name/version;
- adapter and projection-contract versions;
- scoring and authority disclosures;
- each preset's configured and supported categories;
- identity, role, projected volume, category projections, adapter score, and
  adapter rank; and
- the existing `research_only`, `feeds_live_value: false`, and
  `is_dynasty_value: false` boundaries.

Write atomically. A byte-identical same-date rerun is a no-op. A changed
same-date rerun replaces only that date, matching the existing rank-archive
behavior. Do not copy outcomes, public ranks, external consensus, or trade
results into this archive.

The daily workflow needs one explicit git-add allow-list entry for the new
archive directory. This is the only `.github` change and is authorized solely
to preserve the already-built research artifact; it does not dispatch,
publish, or alter the build order.

## Validation status

The existing Stage 2 readiness artifact remains immutable and retains:

```text
retrospective_direct_7x7_evidence_ready = true
incumbent_direct_7x7_target_ready = false
exact_prospective_replay_ready = false
realized_value_regret_ready = false
status = blocked
```

The new archive changes no readiness flag. It makes future prospective replay
possible from the archive date forward. The eventual Plan 034 result, not this
change, decides whether format-specific prospect values or mixed-trade
adjustments are eligible for promotion.

## Tests

Tests must prove:

1. `run_adapters` still writes the serving artifact byte-for-byte as before.
2. It writes a deterministic dated copy using the payload date.
3. A byte-identical rerun reports no archive change.
4. A changed same-date payload updates only that date atomically.
5. The archive retains the explicit research-only/non-value contract.
6. The daily build still invokes the existing adapter builder once.
7. The workflow allow-list includes only the new archive directory.
8. Existing Stage 2 readiness artifacts and frozen live files remain unchanged.
9. Existing trade tests, public-data validation, and the full suite pass.

## Boundaries

- No new fitted model or registered look.
- No direct-7x7 result before Plan 034's trigger.
- No prospect preset value or cross-universe mapping.
- No live rank, value, trade verdict, pitcher cap, Role Watch, or publication
  change.
- No change to the model freeze, failed-decay flag, or pitcher veto.
- No workflow dispatch or deployment.
- No new dependency, database, account, or persistence service.

## Success condition

The work is complete when the shipped league-aware analyzer passes its entire
approved acceptance contract and every future daily build preserves the exact
prospect format opinion needed to join with the existing dated Rank v1 output.
Stage 2 then has honest prospective evidence collection in place while its
performance verdict remains sealed until the registered maturity gate.
