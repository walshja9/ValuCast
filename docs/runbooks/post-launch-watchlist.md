# ValuCast Post-Launch Watchlist

Last updated: 2026-06-15

This tracks the remaining operational, model, and product-polish items after ValuCast became the canonical publisher for Dynasty, Prospects, and Buys.

## Operating Rule

Treat the model and pipeline as shipped unless a validator, freshness gate, production check, or repeatable calibration report says otherwise. Do not retune by individual player names.

## Active Watch Items

### 1. Watch the next daily pipeline run

Status: active watch

Why it matters: the daily workflow is now responsible for refreshing inputs, building the canonical snapshot, generating Buys, running forward validation, running the quality governor, and publishing the public artifacts.

Evidence to check after the next run:

```bash
python scripts/validate_milb_stat_freshness_audit.py
python scripts/validate_pipeline_observability.py
python scripts/validate_valucast_quality_governor.py
python scripts/validate_front_office_report.py
python scripts/validate_public_data_freshness.py --date YYYY-MM-DD
```

Done when: the scheduled workflow finishes cleanly, generated artifacts are same-day fresh, and production is serving the new snapshot.

### 2. Post-deploy production check

Status: active watch

Check these live surfaces after deploy:

- `/health/ready`
- `/`
- `/?mode=prospects`
- `/?mode=prospects&search=Cooper%20Pratt`
- `/buys`
- `/prospects/share-card?limit=20`
- `/front-office`

Done when: all pages load, the ready endpoint is green, Cooper Pratt and other targeted refresh examples show current stat context, and public "Updated" labels reflect the generated data date.

### 3. Let forward validation mature

Status: time-based watch

Why it matters: forward validation currently tracks movement and retention, not realized MLB outcome accuracy. It is useful, but it needs more days of archived ValuCast ranks before it can support stronger calibration decisions.

Done when: the report has enough dated archives to support bucket-level decisions without leaning on manual player-name reactions.

### 4. Add pitcher targeted refresh support

Status: backlog

Why it matters: hitter call-up cards can now be surgically refreshed without waiting for the next full pipeline. Pitchers need the same workflow for call-ups, injury returns, and stale MiLB lines.

Smallest useful scope:

- Extend `scripts/refresh_milb_player_stats.py` with `--role pitcher`.
- Fetch MLBAM-keyed current MiLB pitching rows.
- Preserve row-level `sample_fetched_date`.
- Validate IP, ERA, WHIP, K, BB, K-BB%, and sample size fields.
- Add pitcher fixtures/tests.
- Update the targeted-refresh runbook.

Done when: a named pitcher can be refreshed by MLBAM ID and the public card reflects the updated current-season line after the snapshot rebuild.

### 5. Review DD audit results

Status: external watch

Why it matters: ValuCast is canonical on its side, but DD can still be an upstream factual-input producer. DD must prove its factual contract is actually factual, not just labeled that way.

Done when: DD findings are either implemented, dismissed with evidence, or converted into a scoped follow-up brief.

### 6. Decide whether to move cron earlier

Status: wait for evidence

Why it matters: moving the schedule earlier only helps if upstream MiLB/Fantrax/public data is already available. If the upstream sources are not ready, an earlier cron only publishes stale or partial data sooner.

Decision rule: use the freshness and pipeline observability artifacts for several runs before changing the schedule.

Done when: evidence shows the upstream data is reliably available earlier than the current run time, or the current schedule is confirmed as the better reliability point.

## Product Polish Queue

These are worth doing, but they are polish and trust work rather than launch blockers.

### A. Player detail card cleanup

Goal: make player cards easier to read and easier to trust on mobile.

Recommended scope:

- Put the current stat strip higher on the card.
- Show the stat season and sample date when available.
- Keep source/freshness language short.
- Reduce repeated label weight so the card feels less dense.
- Keep expanded methodology below the first screen.

### B. Prospect card cleanup

Goal: explain why a prospect is ranked without turning every card into a model essay.

Recommended scope:

- Surface current sample, availability, and source type in one compact row.
- Make history fallback vs current sample obvious.
- Keep category fit separate from universal rank.
- Avoid public-consensus language in the core rank/value area.
- Use detail expansion for uncertainty, not the card header.

### C. Share graphic refinement

Goal: make the public graphics clean enough to share without extra explanation.

Recommended scope:

- Add one short methodology line, such as: `ValuCast ranks combine model projection, current sample, age/level context, availability, and calibration gates.`
- Add a concise freshness/source footer.
- Fix truncation on top-card names where possible.
- Keep Top 20 prospects and Top 40 buys visually consistent.
- Verify mobile screenshot crop and safe area.

### D. Front-office page refinement

Goal: make the readiness grade useful to a non-technical reader.

Recommended scope:

- Lead with grade, release status, and blockers.
- Collapse raw evidence behind sections.
- Show the next evidence target instead of long validator detail.
- Keep the page factual and audit-friendly.

## Not Now

- Do not tune the board by individual names.
- Do not move the daily workflow earlier without observability evidence.
- Do not reintroduce external rankings into ValuCast score generation.
- Do not let DD become the canonical authority for ValuCast public values again.
- Do not make UI polish a reason to reopen the scoring contract unless validators or calibration reports point there.
