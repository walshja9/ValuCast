# Authorization Record: International Signing Factual Correction — Publication Ratified

**Recorded:** 2026-07-27
**Applies to:** the 13-player international signing-bonus overlay
(`data/prospects/raw/international_signing_facts.json`, as_of 2026-07-22),
applied to Prospect Rank v1's factual-investment component
(`input_artifacts.investment_evidence_applied_count: 13`), live in the public
board since the 2026-07-23 daily build.

## Record

The owner ratified publication of the reviewed 13-player corrected board on
2026-07-27, confirming that the review-and-approve sequence completed on
2026-07-22 (Claude review, final Codex review, and the owner's explicit
approval and instruction to commit and merge PR #13) was intended to authorize
publication. The published rank/value effects match the "Exact Candidate
Result" table in
`docs/review-2026-07-22-international-signing-factual-correction.md` and were
re-verified against the served board during the 2026-07-27 commit audit.

The governance failure was that this authorization was never recorded in-repo
before the overlay went live — not that publication lacked the owner's
approval. This document closes that gap retroactively. Finding P0-2 of
`docs/review-2026-07-27-baseline-to-master-commit-audit.md` is resolved as
**ratified**.

## Standing rule going forward

"Approved but held" artifacts must not live on a default-loading production
path: the hold in the 07-22 packet was structurally unenforceable because
`prospects/rank_v1.py` loads the evidence file unconditionally, so the first
scheduled build after merge published it. Any future held factual overlay must
either stay off `master` until publication is authorized, or sit behind an
explicit activation flag whose flip is itself the recorded authorization.
