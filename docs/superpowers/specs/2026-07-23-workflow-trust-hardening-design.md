# Workflow Trust Hardening Design

## Goal

Make pull-request CI reject invalid committed artifacts and prevent upstream
GitHub Actions tags from changing the code executed by ValuCast workflows.

## Current state

The daily refresh already runs the canonical committed-artifact gate:

```text
python scripts/run_daily_public_build.py --only validate
```

Pull-request CI runs the full pytest suite but does not run that gate. Four
workflows reference `actions/checkout@v5` or `actions/setup-python@v6` through
mutable major-version tags.

## Design

Reuse the existing validation command in `.github/workflows/tests.yml`.
Run it after dependency installation and before the full pytest suite. Any
validator failure must fail the job; no fallback or warning-only path is added.

Replace every `actions/checkout@v5` and `actions/setup-python@v6` reference in
`.github/workflows/` with the full 40-character commit SHA currently resolved
by that official major-version tag. Retain the human-readable major version in
an inline comment. Verify the SHAs directly against the official Actions
repositories immediately before editing.

Extend `tests/test_daily_workflow_wiring.py` with one contract test that:

- requires `tests.yml` to run the canonical artifact-validation command before
  the full pytest command; and
- rejects mutable `actions/checkout` and `actions/setup-python` references in
  every repository workflow.

The test uses only Python's standard library and reads the workflow files as
text, matching the existing workflow-wiring tests.

## Verification

Follow RED-GREEN:

1. Add and run the workflow contract test; it must fail because validation is
   absent from `tests.yml` and mutable action tags remain.
2. Make the minimum workflow edits.
3. Run the focused contract test.
4. Run the complete pytest suite.
5. Inspect the diff to confirm that only the design/plan, workflow YAML, and
   the existing workflow contract-test file changed.

## Non-goals

- No new scripts or dependencies.
- No branch protection or repository-ruleset changes.
- No dependency-locking project.
- No data rebuild, workflow dispatch, deployment, or production change.
- No model, ranking, value, cap, Role Watch, or publication change.
