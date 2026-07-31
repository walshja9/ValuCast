# Ahead-of-Consensus Decision Error Audit

**As of:** 2026-07-31

**Verdict:** Remediate through existing registered research; register no new
model challenger from this audit.

## Bottom line

The public 27.8% decided rate is accurate for the frozen higher-than-consensus
track: 42 wins, 34 cases where consensus moved away, and 75 matured
retractions across 151 decisions. Its 95% Wilson interval is 21.3%-35.4%.
Matched controls moved toward ValuCast's prior position 31.5% of the time, so
the current 0.89x lift does not show an edge.

The dominant failure mode is not the field aggressively rejecting ValuCast.
It is ValuCast backing off its own early call: retractions are 49.7% of all
decisions and 75 of the 109 non-wins. That makes claim stability the central
problem to solve honestly.

The weakness is not isolated to hitters, pitchers, confidence labels, sample
reliability, or thin board coverage. The strongest descriptive concentration
is level: AA calls won 7 of 48 (14.6%) and were retracted 31 times (64.6%),
while AAA calls won 19 of 42 (45.2%). That is a real audit signal, but not a
causal result and not permission to suppress AA calls after seeing them lose.

## Frozen evidence

| Slice | N | Wins | Moved away | Retracted | Win rate | 95% Wilson interval |
|---|---:|---:|---:|---:|---:|---:|
| All matured decisions | 151 | 42 | 34 | 75 | 27.8% | 21.3%-35.4% |
| Hitters | 85 | 23 | 15 | 47 | 27.1% | 18.8%-37.3% |
| Pitchers | 66 | 19 | 19 | 28 | 28.8% | 19.3%-40.6% |
| A/A+ | 61 | 16 | 14 | 31 | 26.2% | 16.8%-38.4% |
| AA | 48 | 7 | 10 | 31 | 14.6% | 7.2%-27.2% |
| AAA | 42 | 19 | 10 | 13 | 45.2% | 31.2%-60.1% |

### What did not explain the result

- **Role:** hitters and pitchers were nearly identical at 27.1% and 28.8%.
- **Confidence:** high-confidence calls won 29.6% (n=54); medium-confidence
  calls won 27.8% (n=90). The labels did not separate outcomes.
- **Sample reliability:** 25-49.99 won 31.5% (n=54); 50+ won 26.3% (n=95).
  More reliability did not produce a better catch-up rate in this sample.
- **Board coverage:** 131 decisions had exactly two qualifying boards and won
  28.2%. The 3-4-board cell won 26.3% but has only 19 decisions; the 5+ cell
  has one. Thin coverage dominates the population, but it does not explain the
  observed miss rate.
- **Availability:** 143 decisions were marked available at claim time. Injury
  or limited-status cells are too small to interpret.

### What deserves continued observation

- **Level:** AA is the clearest concentration of retractions and low win rate;
  AAA is the strongest sufficiently sized level cohort.
- **Initial disagreement size:** the frozen bins rise monotonically from 18.6%
  at a 25-49-place gap to 38.7% at 200+. This is descriptive and selected on
  the current evidence. Retrospectively raising the threshold would make the
  scorecard prettier without proving a better model, so no threshold change is
  authorized.
- **Role-specific sample:** pitchers at 20-49.99 IP won 40.7% (n=27), while
  hitters at 200-399 PA won 24.1% (n=54). These are not adjusted comparisons
  and do not establish a feature effect.

## Research disposition

### Existing work remains the right path

1. **Development density (C1)** remains the most relevant registered
   challenger to the stability problem. It can test whether playing-time
   density adds durable development information beyond a single current line.
   This audit does not count as confirmation.
2. **Position value by youth and level (C2)** remains registered on its prior
   out-of-fold evidence. The present age margins do not independently
   strengthen or weaken it.
3. **Plan 034** already contains the future-only families capable of testing
   level-related calibration—especially train/serve shrinkage alignment and
   target scaling—inside nested walk-forward selection. It cannot execute
   before its registered 2027 trigger, and this audit does not add a family or
   authorize a look.

### No new challenger is registered

The audit identifies a cohort where the current live calls have struggled, but
not a causal, historically reconstructable feature that is distinct from the
existing registrations. Creating an AA penalty or a larger-gap-only public
track now would be a post-outcome filter chosen to improve this scorecard. That
is rejected.

Athleticism, contact quality, organizational investment, cross-role
normalization, and player-specific patches remain explicit non-actions. Any
new hypothesis derived from this report requires a new untouched future cohort
and a pre-results registration; it cannot reuse these 151 decisions as its
confirmation sample.

## Data quality and boundaries

- All 151 matured decisions joined exactly once to the dated rank archive from
  their `ahead_since` date; no current-board substitute was permitted.
- Wins, moves away, and retractions reconcile exactly with the frozen
  scorecard.
- Each audit dimension reconciles to all 151 decisions.
- The committed JSON contains aggregate board coverage only—no board names or
  source-level ranks.
- Cells below 10 are marked insufficient; cells from 10-19 are descriptive
  only. No p-values or best-segment claims were produced.
- Segment-level matched controls were not reconstructed post hoc. The 0.89x
  control lift is copied only as frozen overall context.
- The audit is internal validation evidence. It feeds no score, rank, value,
  cap, buy signal, Role Watch output, pitcher decision, workflow, or public
  surface.

## Recommendation

Keep the scorecard and its thresholds unchanged. Let future calls improve the
number rather than editing the denominator. Use the existing C1/C2 confirmation
protocols and Plan 034 to test cohort-wide stability and level calibration when
their registered gates permit; do not ship an AA-specific patch or a
high-gap-only claim filter.

The actionable product lesson today is narrower: when discussing the 27.8%,
say that nearly half of matured decisions were ValuCast retractions. That is
the honest weakness the next validated model improvement must reduce.

## Reproduction

```powershell
python scripts/audit_consensus_decisions.py
python -m pytest tests/test_consensus_decision_error_audit.py -q
```

Machine-readable evidence:
`data/validation/valucast_consensus_decision_error_audit.json`.
