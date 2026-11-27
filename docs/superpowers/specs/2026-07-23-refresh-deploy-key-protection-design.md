# Refresh Deploy-Key Protection Design

## Goal

Protect `master` with pull requests and the existing `pytest` check without
breaking the three scheduled workflows that intentionally publish generated
artifacts directly to `master`.

This is repository-security work only. It does not change models, rankings,
values, data construction, refresh schedules, or production deployment.

## Current State

- `daily-public-data.yml`, `prospect-shadow.yml`, and `roster-pulse.yml` each
  push generated artifacts directly to `master`.
- `tests.yml` supplies the successful `pytest` check from GitHub Actions app
  ID `15368`.
- The repository has no deploy keys and no branch ruleset.
- GitHub will not accept the built-in GitHub Actions app as a bypass actor for
  this personal repository.

## Chosen Design

Use one repository-scoped SSH deploy key as the sole write credential for the
three publishing workflows.

1. Add `ssh-key: ${{ secrets.REFRESH_DEPLOY_KEY }}` to the pinned
   `actions/checkout` step in the three workflows that push `master`.
2. Reduce those workflows' built-in `GITHUB_TOKEN` permission from
   `contents: write` to `contents: read`.
3. Keep `tests.yml` keyless.
4. Store the private key only in the repository Actions secret
   `REFRESH_DEPLOY_KEY`.
5. Add the public key as the repository's only write-enabled deploy key.
6. Activate one default-branch ruleset that:
   - requires changes to go through a pull request;
   - requires the `pytest` status from GitHub Actions app ID `15368`;
   - requires the branch to be current before merge;
   - blocks deletion and force pushes; and
   - allows deploy-key authentication to bypass the rules for scheduled
     artifact publication.

GitHub's ruleset API represents deploy-key bypass with `actor_id: null`, so it
applies to repository deploy keys as a class rather than naming one key. The
repository must therefore retain exactly one deploy key unless this design is
reviewed again.

## Rejected Alternatives

### Personal access token or machine user

This can identify a named user as the bypass actor, but it adds an account or
broader credential lifecycle for one repository. It is unnecessary here.

### Keep direct GitHub Actions writes without protection

This preserves the current refresh path but does not enforce pull requests or
CI for human changes.

### Convert every refresh into a pull request

This removes the bypass but would require routine human merges or additional
auto-merge machinery. It is a larger operational change than this hardening
slice needs.

## Credential Lifecycle

- Generate a new Ed25519 key pair in a temporary directory.
- Never print or commit the private key.
- Add the public key through GitHub's deploy-key API with write access.
- Send the private key to `gh secret set REFRESH_DEPLOY_KEY` through standard
  input.
- Verify only secret metadata and deploy-key metadata.
- Delete the temporary key files after both remote writes succeed.
- If the code change is abandoned, remove the unused secret and deploy key.
- Rotation is manual: replace the deploy key and secret together, then remove
  the old key.

## Workflow Contract

One test will inspect all workflow files and enforce:

- the three workflows containing `git push origin master` use
  `secrets.REFRESH_DEPLOY_KEY`;
- those three workflows request only `contents: read`;
- no other workflow references the deploy-key secret; and
- `tests.yml` remains keyless.

The test extends the existing workflow contract suite and uses only the Python
standard library.

## Rollout Order

1. Land the workflow contract and workflow changes through a pull request while
   `master` is still unprotected.
2. Provision the deploy key and Actions secret before merging that pull request.
3. Merge only after local verification and GitHub `pytest` pass.
4. Create the active ruleset after the key-aware workflows are on `master`.
5. Read the ruleset, deploy-key metadata, secret list, and workflow files back
   from GitHub to verify the final state.
6. Let the next scheduled artifact-producing run provide the first real push
   proof. Do not manufacture a data change or re-run the sealed same-day MiLB
   archive merely to exercise authentication.

This order avoids any interval where branch protection is active but scheduled
writers still authenticate with the blocked built-in token.

## Failure Handling

- A missing or invalid deploy-key secret makes checkout or push fail loud; it
  cannot silently fall back to the read-only token for publication.
- A non-fast-forward push keeps the existing fail-loud behavior.
- If scheduled publishing fails after activation, disable the ruleset before
  changing credentials or workflow code. Do not weaken the model validators.
- Rollback consists of disabling/removing the ruleset, reverting the three
  workflow inputs, and deleting the deploy key and secret.

## Verification

Before merge:

- capture a RED failure from the new contract test;
- make the minimal workflow edits;
- run the focused workflow tests;
- run the committed-artifact validator; and
- run the full local test suite.

After merge:

- confirm the only deploy key has the expected title and write access;
- confirm `REFRESH_DEPLOY_KEY` exists without reading its value;
- confirm the ruleset is active on the default branch;
- confirm its required check is `pytest` from integration ID `15368`;
- confirm its only bypass actor type is `DeployKey`; and
- confirm local `master` matches `origin/master`.

## Non-Goals

- No new scripts, dependencies, GitHub Apps, accounts, or branch rules.
- No refresh dispatch solely for testing.
- No change to refresh schedules, generated-artifact allowlists, model gates,
  pitcher publication policy, production deployment, or Stage 2.
