# Daily Refresh Atomic Reliability Design

## Context

The August 5 daily refresh completed its expensive build but failed final validation on a prospect availability transition. That defect was fixed by PR #48. Recovery attempts on August 6 then lost work when one run was cancelled during LLM scouting and another could not acquire a GitHub-hosted runner. No invalid or partial data reached `master`, but no same-day daily snapshot was published either.

## Goal

Preserve the existing all-or-nothing publication contract while making interrupted work reusable and giving transient GitHub runner failures additional same-day recovery opportunities.

Success means:

- every required build and validator succeeds before any refresh commit or deploy;
- a cancelled scouting build retains completed LLM generations for the next attempt;
- runner congestion or one failed attempt is followed by later automatic attempts that stop once the daily marker commit exists;
- the workflow still has only one writer at a time and never publishes partial artifacts.

## Non-goals

- No validator becomes fail-open.
- No artifact is published before the full validation stage succeeds.
- No new dependency, external scheduler, or self-hosted runner is introduced.
- This cannot make GitHub Actions available during a platform-wide outage; it makes the repository recover automatically when capacity returns during the configured same-day window.

## Design

### Atomic publication remains unchanged

The refresh continues to build in the runner workspace, validate every required artifact, stage the existing allowlist, create one dated refresh commit, push once, and only then trigger deployment. Build or validation failure leaves `master` and production unchanged.

The existing workflow-level `daily-public-data-refresh` concurrency group remains the single-writer lock. Manual dispatches continue to run regardless of the daily marker. Scheduled attempts continue to use the preflight marker check and skip once `data: daily public refresh YYYY-MM-DD` exists.

### Persist completed LLM scouting work

`scouting.repository._attach_llm_reports` will atomically save the LLM cache immediately after each successful new generation. Existing cached reads do not cause redundant writes. If the process is cancelled during a later generation, every earlier completed generation is already present on disk.

The workflow will restore `data/models/valucast_scouting_llm_cache.json` from a dedicated Actions cache before the public snapshot build and save it with `if: always()` after that build. Its key prefix is separate from plate-discipline and AAA-Statcast caches. A failed or cancelled attempt therefore hands its completed generations to the next attempt without placing unvalidated data on `master`.

The committed cache remains in the final git allowlist. Actions cache is recovery state only; the validated daily commit remains the durable source of truth.

### Extend same-day scheduled recovery

Replace the three morning cron entries with an hourly daylight-time recovery window from 11:30 through 19:30 UTC (7:30 AM through 3:30 PM ET during daylight time). GitHub concurrency retains at most one running and one pending attempt; newer scheduled attempts may replace an older pending attempt, but they do not cancel the active build because `cancel-in-progress` remains `false`.

After a successful publication, the next pending scheduled attempt reaches preflight, observes the same-day marker, and skips the expensive refresh. If a runner cannot be acquired or a transient run fails, a later scheduled event supplies another attempt without human dispatch.

The existing 120-minute job timeout remains unchanged. The bounded 300-generation, 10-second-per-call scouting configuration fits the observed successful-run envelope, while increasing the timeout back toward the prior 180-minute setting would recreate the documented queue pileup.

## Failure behavior

- **Build or validator defect:** fail before commit; later attempts retry atomically, and GitHub reports the failing step.
- **LLM API error:** existing per-call handling and generation budget remain unchanged; the repository validator still decides whether the final artifact is publishable.
- **Cancellation during LLM generation:** completed generations are already written and the `always()` cache-save step preserves them for the next attempt.
- **Hosted-runner acquisition failure:** the next hourly scheduled attempt retries when capacity is available.
- **Push race:** existing fail-loud single push remains unchanged; the next attempt syncs current `origin/master` and rebuilds.
- **GitHub-wide outage beyond the recovery window:** no repository-only mechanism can run; manual dispatch remains the recovery path after service returns.

## Files

- `scouting/repository.py`: checkpoint successful new LLM generations.
- `.github/workflows/daily-public-data.yml`: restore/save the dedicated scouting cache and extend scheduled fallbacks.
- `tests/test_scouting_repository.py`: prove a completed generation survives interruption before the full repository build returns.
- `tests/test_public_data_refresh.py`: enforce the hourly recovery window, cache isolation, and restore/build/save ordering.

## Verification

Use strict RED-GREEN cycles:

1. Add an interruption regression test that generates one report, raises `KeyboardInterrupt` on the next call, and asserts the first report exists in the on-disk cache. It must fail before the production change and pass afterward.
2. Add workflow contract assertions for the hourly cron, dedicated cache key/path, `if: always()`, and restore-before-build/save-after-build ordering. They must fail before the YAML change and pass afterward.
3. Run the focused scouting and workflow test files.
4. Run the complete test suite used by the repository's PR workflow.
5. Inspect the final diff and verify only the four implementation/test files plus this design and its implementation plan changed.
