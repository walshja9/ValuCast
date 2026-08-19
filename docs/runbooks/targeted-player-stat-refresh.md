# Targeted Player Stat Refresh

Use this when a prospect card needs current visible MiLB stats before the next
daily public-data run, usually because a call-up card is being shared.

The normal ValuCast public-data workflow runs once daily from GitHub Actions at
`13:30 UTC`:

- `9:30 AM ET` during daylight time
- `8:30 AM ET` during standard time

The targeted refresh path updates one player's current MiLB stat row and then
rebuilds the public artifacts that display it. It does not claim the entire
daily dataset was refreshed.

## Command

```powershell
cd C:\Users\Alex\Documents\Codex\2026-05-18\league-values
python scripts\refresh_milb_player_stats.py --mlbam-id 806198 --role hitter --season 2026 --fetched-date 2026-06-15
```

Replace:

- `806198` with the player's MLBAM ID.
- `hitter` with the player's role. The current script supports hitters.
- `2026-06-15` with the date of the targeted refresh.

## Rebuild

After the targeted row updates, rebuild the dependent public artifacts:

```powershell
python scripts\build_valucast_prospect_inputs.py
python scripts\build_prospect_availability.py
python scripts\build_prospect_rank_v1.py
python scripts\build_prospect_model_v07.py
python scripts\build_prospect_coverage_audit.py
python scripts\build_prospect_calibration_report.py
python scripts\build_prospect_peak_projection.py
python scripts\build_valucast_buys.py --with-review
python scripts\build_prospect_forward_validation.py
python scripts\build_valucast_buys_monitor.py
python scripts\build_prospect_outcome_backtest.py
python scripts\build_front_office_failures.py
python scripts\build_raw_data_independence_audit.py
python scripts\build_recent_signal_report.py
python scripts\build_public_dynasty_snapshot.py
python scripts\build_milb_stat_freshness_audit.py
python scripts\build_prospect_card_data_audit.py
python scripts\build_valucast_quality_governor.py
python scripts\build_pipeline_observability.py
python scripts\build_front_office_report.py
```

## Verify The Player

```powershell
@'
import json
from pathlib import Path

snapshot = json.loads(Path("data/public/public_dynasty_snapshot.json").read_text(encoding="utf-8"))
row = next(r for r in snapshot["players"] if r.get("mlbam_id") == 806198)
print(row["name"])
print(row["rank"], row.get("prospect_rank"), row["value"])
print(row["stat_line"])
print((row.get("components") or {}).get("availability", {}).get("sample_fetched_date"))
'@ | python -
```

Expected result for a successful targeted refresh:

- `stat_line` reflects the current official MiLB page.
- `sample_fetched_date` equals the targeted refresh date.
- The player rank/value should only move if the stat correction legitimately
  changes model inputs.

## Validate

```powershell
python scripts\validate_valucast_prospect_inputs.py
python scripts\validate_prospect_peak_projection.py
python scripts\validate_milb_stat_freshness_audit.py
python scripts\validate_valucast_quality_governor.py
python scripts\validate_pipeline_observability.py
python scripts\validate_front_office_report.py
python scripts\validate_public_dynasty_snapshot.py
python scripts\validate_public_data_freshness.py --date 2026-06-14
python -m pytest tests\test_refresh_milb_player_stats.py tests\test_milb_stat_freshness.py tests\test_pipeline_observability.py tests\test_public_dynasty_snapshot.py tests\test_valucast_quality_governor.py -q
```

Use the daily artifact date for `validate_public_data_freshness.py --date`.
For example, a single player row can be refreshed on `2026-06-15` while the
daily public dataset remains correctly stamped `2026-06-14`.

## Commit Scope

The intended diff should be narrow:

- `data/prospects/raw/milb_season_stats.json`
- `data/prospects/prospect_model_inputs.json`
- regenerated model/public artifacts affected by that player row
- optional runbook or script changes

Do not commit large formatting rewrites of raw caches. If
`data/prospects/raw/milb_card_history.json` rewrites wholesale, revert that file
and use the normal daily pipeline for historical-card cache updates.
