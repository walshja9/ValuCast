# International Bonus Universal-Model Feasibility

**Date:** 2026-07-22
**Decision:** Blocked on historical international signing facts; do not change the universal model yet.

## Intended use and grain

The question is whether international signing bonuses can enter the universal
prospect model as predictive features. The relevant historical grain is one
prospect cohort, MLBAM ID, and role at the cohort-season cutoff, joined to later
MLB outcomes.

## Data checks

The current historical contract contains 6,756 cohort-role rows:

| Role | Rows | Positive signing bonus | Coverage |
|---|---:|---:|---:|
| Hitter | 3,307 | 794 | 24.0% |
| Pitcher | 3,449 | 837 | 24.3% |

Every historical row with a signing bonus also has a Rule 4 draft pick:

- hitter bonus rows without a draft pick: 0;
- pitcher bonus rows without a draft pick: 0; and
- rows with an `acquisition_type` field: 0.

The 13 newly verified international signees match zero historical hitter rows.
They are current prospects, not mature training examples with later MLB
outcomes.

Historical bonus rows by cohort are:

| Cohort | Hitters | Pitchers |
|---:|---:|---:|
| 2017 | 2 | 1 |
| 2018 | 162 | 160 |
| 2019 | 209 | 238 |
| 2021 | 219 | 204 |
| 2022 | 202 | 234 |

## Model-path check

`prospects/universal.py` currently encodes `draft_record_known`,
`rule4_drafted`, draft-pick score, log signing bonus, signing-bonus presence,
and school type in one feature vector. It has no acquisition-type field or
international-bonus interaction.

Consequently, supplying the 13 current international bonuses would ask a model
trained entirely on Rule 4 bonus rows to extrapolate that relationship into a
different signing market. The private counterfactual showed that this path can
change predicted outcomes, including a small decrease for Nelson Rada despite
his positive investment fact. That is evidence of model sensitivity, not
evidence of improved accuracy.

## Findings

### High: no historical international training population

There are zero labeled international bonus rows. The intended subgroup effect
cannot be estimated, validated, or calibrated. Any immediate universal-model
change would be unsupported domain transfer.

### High: acquisition type is not reconstructable from the contract

The schema omits acquisition type. Treating “bonus with no draft pick” as an
international signing is not viable because the historical store contains zero
such bonus rows and missing draft facts can also mean missing data.

### Medium: the current 13-player evidence is suitable for rank context only

The records are complete, source-backed, uniquely MLBAM-keyed, and useful for
the direct factual-investment component. They have no mature future outcomes,
so they cannot train or validate the universal model.

## Minimum remediation

1. Build an MLBAM-keyed historical international signing-facts table covering
   eligible hitter cohorts, including signing year, bonus, acquisition type,
   source, and source-check date.
2. Add acquisition type to the historical factual contract without inferring it
   from missing draft fields.
3. Run coverage, uniqueness, source, temporal-cutoff, and outcome-maturity gates
   before fitting anything.
4. Within the registered post-2026 challenger process, compare the incumbent,
   a no-bonus baseline, and an acquisition-aware bonus challenger using
   training-fold-only selection and untouched outer cohorts.
5. Promote nothing automatically; a successful study earns a separate review.

## Conclusion

The code can support an acquisition-aware challenger, but the current data
cannot. The correct status is
`blocked_on_historical_international_signing_facts`. The direct rank correction
may proceed through review independently; the universal model remains frozen.
