# Policy: "Held" Means Surface-Only; Deploy-Key Audit Before Credential Changes

**Recorded:** 2026-07-27 (owner decisions 5 and 6 on the
`docs/review-2026-07-27-baseline-to-master-commit-audit.md` findings)

## 1. Held-content policy (resolves P1-6)

The repository stays **public**. "Held from publication" is hereby defined as
**held from app surfaces** (pages, cards, share graphics, APIs, CSV export) —
not held from the repository. Consequences:

- Factual data, model artifacts, structured evidence, and shadow observability
  may live in the public repo even when their app-surface publication is
  gated. Repo visibility is not a leak for this class.
- **Genuinely private unpublished prose must not be committed at all.** The
  current instance was `peak_summary` in
  `data/models/valucast_scouting_reports.json`, which the app already stripped
  at render time (`app.py` `_scouting_display_report`). `report_llm` and its
  cache remain because valid text can become the public display report and is
  therefore renderable content.

**Implemented by PR #26 (merge `78d889ae`):** the builder strips
`peak_summary` after its in-process checks, and the validator forbids the key
in committed artifacts. History rewriting remains out of scope.

## 2. Deploy-key audit checklist (gates any credential-architecture change, P1-2)

No change to the refresh credential architecture until this server-side audit
is performed and recorded (none of it is verifiable from inside the repo):

- [x] Exactly **one** deploy key exists on the repository; title matches the
      design doc; write access confirmed
      (`docs/superpowers/specs/2026-07-23-refresh-deploy-key-protection-design.md`
      requires exactly one — the ruleset bypass is deploy-key-*class*).
- [x] `REFRESH_DEPLOY_KEY` Actions secret exists; metadata only, value unread.
- [x] The default-branch ruleset is **active** and requires: pull request,
      `pytest` status from GitHub Actions app ID 15368, branch up-to-date;
      blocks deletion and force pushes.
- [x] The ruleset's only bypass actor type is `DeployKey`.
- [x] Key creation date recorded and a rotation date set (design doc says
      rotation is manual — give it a calendar owner).
- [x] Confirm whether GitHub logs deploy-key pushes distinguishably in the
      repo audit surface (so a stolen-key push would be attributable).

After the audit, evaluate (do not pre-commit to) the mitigations from the
commit-audit report: `persist-credentials: false` with the key scoped to the
push step only, a hash-pinned lockfile for the build environment, and
scheduled key rotation. Any such change gets its own design doc per the
existing workflow-contract test discipline.

### Audit record — 2026-07-27

- [x] Exactly one deploy key exists: `ValuCast scheduled refresh writer`
      (ID `158148733`), verified and write-enabled. It was created by
      `walshja9` on 2026-07-23. The design doc does not prescribe a literal
      title; this observed title is the approved expected title going forward.
- [x] The `REFRESH_DEPLOY_KEY` Actions secret exists; its value was not read.
- [x] Ruleset `Protect default branch` (ID `19627275`) is active on the
      default branch. It requires pull requests, requires the `pytest` status
      from GitHub Actions app ID `15368` with the branch up to date, and blocks
      deletion and non-fast-forward pushes.
- [x] The ruleset's only bypass actor is `DeployKey`.
- [x] Rotation owner: `walshja9`. Next manual rotation due 2026-10-21
      (90 days after key creation).
- [x] Attribution checked. Repository push events identify the account
      (`walshja9`), not the deploy key. Automated data commits identify
      `github-actions[bot]` in commit metadata, but that identity is not proof
      of which credential authenticated the push. Treat an unexpected direct
      automated push as a rotate-and-investigate event; GitHub's repository
      audit surface does not provide key-level attribution here.
