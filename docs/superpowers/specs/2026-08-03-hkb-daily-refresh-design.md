# HKB Daily Consensus Refresh

## Decision

Refresh Harry Knows Ball once inside the existing daily public-data build. HKB remains one external, context-only consensus source and never affects ValuCast score, rank, value, or buy logic.

## Data flow

1. After the current prospect universe is built and before the public rank is assembled, the existing HKB fetcher downloads the live calculator payload.
2. It rejects missing, malformed, or fewer-than-400-prospect payloads.
3. It writes the candidate CSV and candidate MLBAM-keyed snapshot to temporary files.
4. Only after both candidates build successfully are they promoted to `data/hkb/hkb_source.csv` and `data/hkb/hkb_consensus_snapshot.json`.
5. The publish workflow commits both files with the rest of the daily artifacts.

The snapshot `generated_at` changes only after a successful live fetch and snapshot build. A network, markup, or tiny-payload failure exits successfully after logging that the committed last-good pair is being retained; it does not re-stamp stale ranks. A local builder failure remains fatal so code or identity-contract defects cannot be hidden as an external outage.

## Scope boundaries

- Reuse the current stdlib fetcher, tiny-refresh guard, HKB builder, daily runner, and workflow.
- Add no workflow, cache, service, dependency, model feature, or public claim.
- Keep STS, Prospects Live, Pipeline, and FanGraphs ingestion unchanged; their supplied data updates are separate data-only work.

## Verification

- A fetch failure leaves both committed files byte-identical and returns success for the daily build.
- A valid payload builds and promotes both files.
- HKB refresh runs after the prospect universe and before `build_prospect_rank_v1.py`.
- The workflow stages both HKB files.
- Existing HKB identity gates and daily-refresh contract tests remain green.
