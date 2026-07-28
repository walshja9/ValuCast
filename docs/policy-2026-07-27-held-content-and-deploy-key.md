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
  current instance: raw LLM scouting prose in
  `data/models/valucast_scouting_reports.json` (`peak_summary`, present on
  500/768 rows, plus raw `report_llm` text) and the daily-recommitted
  `valucast_scouting_llm_cache.json`. The app already strips `peak_summary`
  at render time (`app.py` `_scouting_display_report`); the committed
  artifact must stop carrying what the surface refuses to show.

**Follow-up work (scoped, not yet implemented):** change the scouting build
step to strip `peak_summary` (and any other never-rendered prose fields) from
the committed artifact — keeping them only in the ephemeral build workspace —
and add a validator assertion that the committed artifact contains no field
the display layer strips. History scrubbing is explicitly out of scope: the
prose has been public in history; the goal is to stop recommitting it daily,
not to rewrite history.

## 2. Deploy-key audit checklist (gates any credential-architecture change, P1-2)

No change to the refresh credential architecture until this server-side audit
is performed and recorded (none of it is verifiable from inside the repo):

- [ ] Exactly **one** deploy key exists on the repository; title matches the
      design doc; write access confirmed
      (`docs/superpowers/specs/2026-07-23-refresh-deploy-key-protection-design.md`
      requires exactly one — the ruleset bypass is deploy-key-*class*).
- [ ] `REFRESH_DEPLOY_KEY` Actions secret exists; metadata only, value unread.
- [ ] The default-branch ruleset is **active** and requires: pull request,
      `pytest` status from GitHub Actions app ID 15368, branch up-to-date;
      blocks deletion and force pushes.
- [ ] The ruleset's only bypass actor type is `DeployKey`.
- [ ] Key creation date recorded and a rotation date set (design doc says
      rotation is manual — give it a calendar owner).
- [ ] Confirm whether GitHub logs deploy-key pushes distinguishably in the
      repo audit surface (so a stolen-key push would be attributable).

After the audit, evaluate (do not pre-commit to) the mitigations from the
commit-audit report: `persist-credentials: false` with the key scoped to the
push step only, a hash-pinned lockfile for the build environment, and
scheduled key rotation. Any such change gets its own design doc per the
existing workflow-contract test discipline.
