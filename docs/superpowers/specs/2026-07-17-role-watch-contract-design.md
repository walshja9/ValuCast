# Role Watch Contract-First Design

**Date:** 2026-07-17
**Status:** Approved for implementation planning
**Branch:** `codex/role-watch-contract`

## Purpose

Build an honest, non-public Role Watch review surface from ValuCast's existing
playing-time artifact. Before exposing that surface, correct two display-contract
problems:

1. A reliever can currently be labeled a starter from season-paced innings alone.
2. Prospect cards call a four-year non-establishment probability `Bust risk`, which
   reads like a career verdict and overstates what the model predicts.

The work is display and context infrastructure. It does not authorize a new
repertoire model, a pitcher rerank, a value change, a cap change, or a publication
decision.

## Evidence Behind the Scope

- `valucast_playing_time_role_tracker.json` currently labels Tyler Holton a
  `rotation_starter` and Tyler Alexander a `rotation_workhorse` even though both
  source rows are relievers with zero projected starts. Their season-paced innings
  crossed the starter threshold.
- Tyler Wells has starter evidence and projected starts but zero projected innings.
  That contradiction must be held, not explained away.
- The prospect outcome mix uses a fixed four-year horizon. `bust_risk` means no
  season reaching 300 PA for a hitter or 50 IP for a pitcher inside that horizon.
- In the 2026-07-17 public snapshot, `Bust risk` is the modal segment for 2,821 of
  2,833 prospects and 47 of the top 50. The prevalence is partly the underlying
  base rate, but the current label is still semantically too broad.
- The hitter outcome distribution has significant historical improvement over its
  level-age baseline. The pitcher improvement is directional and its confidence
  interval includes zero. Neither result authorizes refitting in this project.

## Goals

- Give every playing-time role field one documented meaning.
- Stop innings-only starter classifications.
- Fail closed on contradictory role evidence.
- Produce a small, explainable Role Watch candidate list from existing projections.
- Suppress injured, inactive, unavailable, and contradictory candidates.
- Correct the prospect-card outcome language without changing its numbers.
- Keep Role Watch dark by default and absent from navigation.
- Leave a testable path to a later registered repertoire challenger.

## Non-Goals

- No repertoire, pitch-mix, Stuff+, or conversion-success model.
- No coefficient fitting, probability recalibration, or model promotion.
- No changes to ranks, dynasty values, buy scores, pitcher caps, or publication vetoes.
- No change to the failed pitcher pedigree-decay flag.
- No change to League Connect.
- No navigation, footer, homepage, share-card, social, or launch work.
- No new dependency and no JavaScript requirement.
- No deployment, workflow dispatch, environment flip, push, or production release.

## Existing Components to Reuse

- `mlb/playing_time_role.py` remains the single role-context builder.
- `scripts/validate_playing_time_role_tracker.py` remains the artifact validator.
- `data/models/valucast_playing_time_role_tracker.json` remains the sole Role Watch
  data source.
- `app.py::_env_flag_held` supplies the fail-closed environment gate.
- Existing Flask/Jinja page, table, card, status-chip, focus, and responsive styles
  are reused. No new component system is introduced.
- `web/prospect_context.py::outcome_mix` remains the outcome partition helper.

## Role Field Contract

The tracker will continue to emit its current fields and add explicit source and
quality fields. All fields are context-only.

| Field | Type | Meaning |
|---|---|---|
| `source_pool` | string | The projection source's role family: `hitter`, `starter`, `reliever`, or generic pitcher. It is not inferred by Role Watch. |
| `starter_probability` | number or null | Existing projection metadata `p_sp`, constrained to `[0, 1]`. Display context only. It is not a conversion probability. |
| `projected_starts_ros` | number | Rest-of-season projected starts from `stats.GS`; never annualized for display. |
| `projected_innings_ros` | number | Rest-of-season projected innings from `stats.IP`; identical to pitcher `projected_volume`. |
| `projected_role` | string | Coarse role label derived by the rules below. |
| `role_basis` | string | Short machine-readable explanation of the evidence used for `projected_role`. |
| `active_mlb_roster` | boolean | Official roster-context join result. |
| `availability_status` | string | Official availability status already joined by MLBAM ID. |
| `active_injury_risk` | boolean | Official transaction-backed injury/rehab risk flag. |
| `role_context_status` | `ready` or `blocked` | Whether the role fields are coherent enough for Role Watch. |
| `role_context_blockers` | list of strings | Exact contradictions or invalid inputs. Empty when ready. |
| `usage` | string | Remains `role_context_not_live_rank_or_value`. |

The artifact-level source policy continues to require `feeds_live_rank: false` and
`feeds_live_value: false`. Role Watch adds no writable path back into any source
artifact.

## Corrected Pitcher Role Rules

The role builder keeps the current full-season pace adjustment for threshold
comparisons while displaying honest rest-of-season volumes.

1. Starter evidence exists when either:
   - `source_pool == "starter"`, or
   - season-paced projected starts are at least 18.
2. With starter evidence:
   - `rotation_workhorse` requires at least 150 season-paced IP or 24
     season-paced starts.
   - otherwise the role is `rotation_starter`.
3. Without starter evidence:
   - a reliever source pool or at least 12 season-paced saves plus holds remains
     relief;
   - at least 22 season-paced saves plus holds is `leverage_reliever`;
   - other relief is `middle_relief`;
   - a generic pitcher with at least 75 season-paced IP is `swingman_or_bulk`;
   - otherwise the role is `depth_arm`.

Season-paced innings alone can no longer turn a source reliever into a starter.

## Contradiction and Availability Rules

A pitcher profile is `blocked` from Role Watch when any of these applies:

- `starter_probability` is present but outside `[0, 1]`.
- projected starts or innings are negative.
- projected starts are at least 0.5 while projected innings are zero.
- a source row without a usable MLBAM identity is omitted before profile creation;
  the validator never accepts an emitted profile without one.

Role Watch additionally excludes, without rewriting the underlying profile:

- `active_mlb_roster != true`;
- `active_injury_risk == true`;
- availability status is `injured`, `rehab`, `inactive`, or `stale_or_inactive`;
- `starter_probability` is missing;
- its required opportunity explanation cannot be produced.

Missing roster or availability evidence therefore fails closed for the surface.

## Role Watch Candidate Screen

Role Watch is an opportunity screen, not a conversion ranking. A row is eligible
only when all of the following are true:

- pitcher `source_pool == "reliever"`;
- `role_context_status == "ready"`;
- active MLB roster and not excluded by availability rules;
- at least 1.0 projected rest-of-season start;
- positive projected rest-of-season innings;
- valid `starter_probability`.

The 1.0-start threshold is an operational display threshold, not a fitted or
validated model parameter. It prevents fractional noise from creating a watch
candidate while retaining pitchers with a concrete projected start.

Rows are ordered by projected rest-of-season starts, then name. The page states
that this is opportunity order, not player quality or conversion likelihood.

Every row carries a deterministic explanation using only its own fields:

> Projected for {GS} starts and {IP} innings the rest of the season while the
> source role remains relief. Starter probability is {p_sp}. Roster status is
> {availability}.

If every clause cannot be supported, the row is omitted.

## Web Surface

### Gate and route

- Add `ROLE_WATCH_HOLD = _env_flag_held("ROLE_WATCH_HOLD")`.
- Add `GET /role-watch`.
- Unset or truthy `ROLE_WATCH_HOLD` returns 404.
- A missing, stale-contract, invalid, or unready artifact returns 404.
- No navigation or footer link is added.
- The route is HTML only; no API, export, share card, or PNG is added.

### Page content

The held review page contains:

- Kicker: `ROLE WATCH · PRIVATE REVIEW`.
- Heading: `Projected opportunity, not a conversion grade`.
- One-sentence methodology note explaining that projected starts, volume, and
  roster context drive inclusion.
- Artifact date and eligible-candidate count.
- Accessible candidate rows with player/team, source role, projected GS/IP,
  starter probability, roster context, and the deterministic explanation.
- An empty state that says no pitchers meet the current evidence gate.
- A footer methodology note stating that Role Watch cannot affect rankings,
  values, caps, or publication decisions.

The design uses semantic headings, a real table or definition-list structure,
visible keyboard focus, existing color tokens, and the existing mobile stack. It
does not rely on color alone and adds no client-side interaction.

## Prospect Outcome-Language Correction

`outcome_mix` keeps the exact same three mutually exclusive percentages and only
changes their public labels:

| Current | Replacement |
|---|---|
| `Star ceiling` | `Impact season` |
| `Everyday role` | `Established MLB role` |
| `Bust risk` | `Not established by Year 4` |

The attribution note becomes:

> Four-year MLB outlook. “Not established” means no applicable 300-PA hitter or
> 50-IP pitcher season within four years—not a career verdict.

This corrects the time horizon and threshold meaning. No probability, score,
ordering, model artifact, or public snapshot value changes.

## Acceptance Matrix

The current real-player review is an acceptance aid, not a production allowlist.
Tests use synthetic equivalents so they do not become stale name-based logic.

| Case | Expected result |
|---|---|
| Tyler Holton | Remains relief because zero projected starts; not a Role Watch candidate. |
| Tyler Alexander | Remains relief because zero projected starts; not a Role Watch candidate. |
| Tyler Wells | Role context blocked because projected starts coexist with zero innings. |
| Evan Sisk / Jakob Junis | Excluded while injured or inactive. |
| Active reliever with at least one projected start and positive IP | Included with a complete deterministic explanation. |
| Stable closer with no projected starts | Remains relief and is excluded. |

## Validation and Tests

### Unit tests

- A high-IP source reliever with zero GS remains relief.
- A generic pitcher with starter-level GS is classified as a starter.
- A source starter can still be a starter when its IP projection is modest.
- GS with zero IP creates a `blocked` profile and named blocker.
- Invalid probability and negative volume create blockers.
- Every profile retains context-only usage and source-policy guards.
- Role Watch includes the eligible active reliever.
- Role Watch excludes injured, inactive, missing-probability, fractional-noise,
  zero-IP, and blocked rows.
- Every included row has a complete opportunity explanation.
- Candidate ordering is projected GS then name.
- Outcome segments still sum to 100 with the replacement labels.
- Rendered prospect cards contain the four-year note and no `Bust risk` label.

### Validator changes

- Validate every profile, not `profiles[:200]`.
- Require the new role-contract fields.
- Reject invalid `starter_probability` values.
- Reject a ready profile that still contains blockers.
- Reject a blocked profile without blockers.
- Preserve the existing rank/value/feed guards.

### Route tests

- Held route returns 404.
- Unheld route with missing or unready artifact returns 404.
- Unheld route renders an eligible candidate and its explanation.
- Suppressed and blocked players do not render.
- No primary navigation or footer link appears.

### Full verification

- Run the focused role-tracker, route, prospect-context, and app tests.
- Run the full automated suite.
- Rebuild and validate the tracker locally without staging the generated daily
  artifact in the feature commit.
- Inspect the generated current-player acceptance matrix.
- Run keyboard, responsive-mobile, empty-state, and normal-state browser checks
  with `ROLE_WATCH_HOLD=0` in staging.
- Confirm normal production configuration still returns 404.

## File Scope

Expected implementation files:

- Modify `mlb/playing_time_role.py`.
- Modify `scripts/validate_playing_time_role_tracker.py`.
- Modify `web/prospect_context.py`.
- Modify `web/public_snapshot_models.py` only if the outcome note needs a model
  property; avoid this change if static template copy is sufficient.
- Modify `app.py`.
- Create `templates/role_watch.html`.
- Modify the smallest existing stylesheet only if current page/table classes do
  not cover the mobile layout.
- Modify focused tests under `tests/`.

Do not commit regenerated daily artifacts unless the implementation proves that
the application cannot fail closed against the previous schema. The held route
must remain safe during the schema transition.

## Launch Gate

Implementation completion is not launch authorization. Publication requires all
of the following after merge:

1. Two clean nightly tracker builds using the new contract.
2. Full automated regression passing on the release commit.
3. Staging browser review at desktop and mobile widths.
4. Current-player acceptance review, including Wells.
5. Confirmation that ranks, values, caps, and pitcher publication outputs are
   byte-for-byte or semantically unchanged as applicable.
6. Explicit approval before setting `ROLE_WATCH_HOLD=0` or deploying.

No workflow should be dispatched near 00:00 UTC. The existing no-push window and
all production-authorization rules remain in force.

## Future Repertoire Challenger

A repertoire-aware model is a separate registered study. It must compare against:

- existing `p_sp`;
- prior-starting-history alone;
- raw pitcher quality or fastball share;
- a combined role-and-opportunity baseline.

It must separately label an attempted conversion, a sustained role, and
fantasy-useful performance. If the registered power gate is inadequate, the
challenger remains display-only and cannot feed Role Watch ordering, ranks,
values, caps, or publication.
