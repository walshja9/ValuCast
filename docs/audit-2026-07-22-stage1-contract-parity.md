# Stage 1 Contract Parity Audit

Date: 2026-07-22
Status: Stage 1 migration decision parity verified; pre-existing served-artifact context reproducibility exception documented

## Locked served board

- Board rows: 2,851
- Canonical board SHA-256: `e2626fee0e993d3e7e52e371e917a162bb561130d21bae2b372ca154a0de7d46`
- Locked served baseline changed: false

## Matching-input migration parity

- Stage 1 contract version: 1.0.0
- Served state: incumbent
- Exact pre/post Stage 1 regenerated board parity: true
- Regenerated board rows: 2,851
- Diagnostic regenerated-board SHA-256: `8fb4e5d6310534ccce5a81b2c2ebd7d9242cd8486b74e688b5c55fbafcedff45`
- Diagnostic hash is the served baseline: false

## Served-artifact reproducibility exception

- Served artifact vs matching-input rebuild exact parity: false
- Differing rows: 1
- Pre-existing differing leaf: `context_only.source_ranks`
- Player: Christian Gonzalez (MLBAM 822619)
- Locked served value: `null`
- Matching-input rebuild value: `{"sts": 1217}`
- Decision parity for identity, role, name, score, rank, ordering, and every non-context field: true

## Contract and publication invariants

- Research/shadow challenger states accepted by Rank v1: false
- Rejected contract overwrites prior artifact: false
- Model freeze preserved: true
- Failed stale-pedigree-decay flag preserved: true
- Live score/rank/value/cap/Role Watch/publication change: false

## Post-refresh rebase verification

Revalidated on 2026-07-23 after rebasing onto refreshed master
`5e8959d9`. Fresh Rank v1 builds from master and the Stage 1 branch used the
same July 23 inputs.

- Board rows: 2,856
- Exact matching-input board parity: true
- Exact active-MLB-board parity: true
- Matching-input board SHA-256: `981e609354bf8a30365cfdb5371a3ae53fb4b909276c732e6c0e237448bd5d3a`
- Rank validation blockers on both builds: none
- Score, rank, identity, role, and ordering differences: zero
- Refreshed served artifact vs matching-input rebuild: four
  `context_only.source_ranks` leaves differ; no decision field differs
