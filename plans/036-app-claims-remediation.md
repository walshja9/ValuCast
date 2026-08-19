# Plan 036 — App Claims Remediation (canonical audit record, 2026-08-19)

**Status: PARTIALLY IMPLEMENTED — R3 implemented and pending merge
(PR #60, Sol review); all other items remain plan-only. Every item that
changes a served output requires explicit owner authorization, item by
item, before implementation.**

**Baseline:** GitHub master `64d95e6` (2026-08-19), the sole app-audit
baseline by agreement. Findings below are the consensus canonical audit
record reconciled 2026-08-19 between two independent auditors (branch-scope
and path-scope errors on each side identified, corrected, and quarantined).
All v2.2 cross-role experiment findings live in a separated experimental
appendix belonging to an unpushed local branch and are OUT of this plan.

**Frame:** the audit's core diagnosis — the app conflates *independently
produced*, *publishable*, *scientifically validated*, and *comparable on
one value scale*. This plan makes the product honor the distinctions the
registry already draws.

## Consensus findings (verified on master unless noted)

1. MLB and prospect values are globally ranked, dollared, and
   trade-summed while the snapshot itself records
   `unit_mapping_applied: false`, `value_units_calibrated: false`
   (`scripts/build_public_dynasty_snapshot.py`, `_assign_global_ranks`).
2. Points mode: hitter walks and pitcher walks collide on one form key —
   `templates/partials/setup_points.html` emits `name="pt_BB"` in BOTH
   role tables (the pitching loop's stat id is `BB` though the defaults
   vocabulary has a distinct `BB_P` key, whose −0.5 default is therefore
   unreachable from the form). One submitted value silently prices both
   roles' walks.
3. The daily build can produce two governor verdicts: the snapshot builds
   (stage ~109) before the card-data/recent-signal audits (~113–114) and
   evaluates a governor internally, while the standalone governor builds
   later (~133); missing audit inputs read as passing.
4. Registry shows a value-feeding component (`universal_prospect_model_pitchers`)
   as REJECTED without separating the rejected *claim* (beyond-neighbors
   ordering) from *component* status — scientifically honest,
   product-confusing.
5. Pitcher draft pedigree enters both the prospect model's features and
   rank v1's separate investment component — repeat-counting exposure
   (structural; exact causal size unmeasured).
6. Rank v1's cross-role transform (`role_quantile_to_pooled_v0_1`) is
   composition-shaped, not outcome-calibrated; the MLB side carries a
   manual `PITCHER_PRODUCTION_ANCHOR = 0.92`. Both are disclosed policy,
   not validated equivalence.
7. Preset value drift across surfaces and Now-$ ignoring roster size /
   replacement level: credible (cited source files confirmed identical on
   master); numerical magnitudes need one fresh reproduction on the
   current snapshot before fixes are scoped.
8. Prospect slots: proven context-only behavior, currently intentional —
   copy clarity issue only.

## Remediation items (ordered by claim-risk; per-item authorization)

### R1 — Fail closed on mixed-universe false precision  [SERVED OUTPUT — needs owner authorization]

Suppress ONLY the unsupported mixed-universe outputs: exact global ranks
spanning MLB+prospects, dollar values derived from unmapped cross-universe
scores, and declared winners on mixed MLB/prospect trades (components
still shown; the winner headline and total are withheld with a one-line
reason). **Both populations stay fully visible** — the MLB board, the
prospect board, and combined *views* remain; only the false-precision
artifacts (cross-universe rank numbers, dollars, winner verdicts) are
suppressed until a real unit mapping is registered and validated.
Tests: snapshot flags drive rendering; mixed trade → no winner; single-
universe trades unaffected. Rollback: single flag revert.

### R2 — pt_BB role split  [SERVED OUTPUT — needs owner authorization]

Template: the pitching walks row emits `pt_BB_P`. Parsing: role-aware —
`pt_BB_P` becomes a PointRule for stat `BB` scoped to the PITCHER pool;
`pt_BB` prices hitter walks only. The parse vocabulary admits `BB_P`; the
previously unreachable −0.5 default becomes live. Back-compat note
documented: legacy links carrying only `pt_BB` change meaning for
pitchers (they stop inheriting the hitter value and fall to the pitcher
default) — this is the bug's removal, stated plainly in the changelog.
Tests: emitted form keys unique per role; +1 hitter BB / −0.5 pitcher BB
round-trips distinctly; legacy-link behavior pinned.

### R3 — One authoritative governor  [pipeline; no score change] — IMPLEMENTED (PR #60, in Sol review)

As-designed correction: "build every audit before the snapshot" is
impossible — the card-data audit reads the finished snapshot AND feeds
the governor. The implemented architecture is **inject-after**: the
snapshot builds with a pending placeholder verdict (all surfaces held
not-ready); the recent-signal report (no snapshot dependency) builds
BEFORE the snapshot; the snapshot-reading audits build after it; the
governor then evaluates exactly once with every input present and
injects its exact artifact into the snapshot via a pure, idempotent
merge. The validator fails the refresh on a pending placeholder, an
embedded/validation-copy mismatch, or an embedded verdict that does not
hash-match the committed artifact. Missing audit inputs fail closed on
the prospects surface only — the three audit/report inputs are
context-only for Buys/Movers (buy-exclusion set), so a missing context
report can never brick the hard refresh gate. Full graduated-prospect
id list persists in validation (the 12-row display sample silently
shrank the graduated set on high-graduation days). First CI run on the
PR empirically confirmed the two-verdicts divergence on committed data
via the new hash check; both artifacts regenerated through the
single-verdict path with identical surface readiness.

### R4 — Registry v2: separate claim rows from component rows  [registry design — needs owner sign-off]

Components (feeds_value, operational status) and claims (validated /
rejected hypotheses, non-feeding audit rows) become distinct row kinds.
The pitcher beyond-neighbors REJECTED claim moves to its own claim row;
the component row states what the pitcher model IS validated for
(prior-beating, MAE gate) and what it is not. Complies with
resolved-not-reworded: this is a schema separation carrying the same
resolved verdicts, not a rewording of any verdict. Validator + lock tests
updated; /models renders the two kinds distinctly.

### R5 — Preset resolution + Now-$ replacement math  [SERVED OUTPUT — needs owner authorization; reproduce first]

Step 1 (read-only): reproduce preset cross-surface drift and Now-$
roster-size invariance on the current snapshot; record fresh counts.
Step 2: centralize preset value resolution so board, detail, comparison,
CSV, and history read one resolved value; Now-$ reuses the
replacement-aware allocator (roster size and replacement level bind).
Tests: cross-surface equality property test; Now-$ sensitivity test.

### R6 — Pedigree repeat-count remediation  [registered challenger process]

Residualize rank v1's investment component against the model's pedigree
features out-of-fold, or remove the separate term for modeled players —
decided by a registered study, not a hotfix. Add a contribution-
concentration monitor (top-driver mass by feature group), replacing the
source-label-only pedigree count in the calibration monitor.

### R7 — Copy clarity (no behavior change)

Prospect-slots setting labeled as the board divider it is; methodology
"ballpark" language linked wherever combined views render.

## Cross-role scale policy (standing, from the audit)

- Rank v1's pooled-percentile board remains published as the **disclosed
  v1 ranking policy** — an independent ValuCast ranking, never described
  as validated cross-role value.
- No new cross-role model version ships or is even evaluated for release
  without: one common fantasy-economic target; identical
  candidate/comparator training identities; training-only references;
  outcome-independent scale transformation; no role-count fitting; no
  duplicate pedigree; one untouched confirmation cohort.
- **Any v2.x release requires a master-merged registration BEFORE a fresh
  untouched confirmation look.** An unpushed branch is not inherently
  ungoverned, but it is unpublished and independently unverifiable —
  registration on master is what makes a look auditable.

## Sequencing

R3 is implemented (PR #60, held for Sol's pre-merge review). R5's
read-only reproduction is complete (both defects confirmed on master:
preset drift 776–824 of 915 MLB rows per preset, max mismatch 29.97;
Now-$ invariant to roster size on all 915 rows; the replacement-aware
allocator exists at `_compute_dynasty_dollars`). R7 is safe after
normal review. R1 and R2 await owner authorization (product-claim
changes); R5's fix likewise. R4 is a design sign-off then a PR. R6
enters the registered-study queue behind the pitcher-pass program's
Phase C window. Each item lands as its own PR with tests and a one-line
rollback; every R-item PR holds for Sol's independent review before
merge (process locked 2026-08-19: Fable implements, Sol reviews).

## Boundaries

Scoring freeze intact: nothing here changes model scores, ranks, values,
thresholds, or publication state without explicit owner authorization on
the specific item. The pitcher-pass program (within-role ordering
challenger) is unaffected by, and does not gate, any item above.
