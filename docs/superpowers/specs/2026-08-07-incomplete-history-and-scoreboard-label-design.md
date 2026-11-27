# Incomplete Prospect History and Scoreboard Label Design

## Problem

ValuCast currently treats missing outcome-model inputs as factual zeros. This is unsafe for historical fallback rows: all 111 selected `latest_milb_history` rows in the August 7 input contract omit at least one model feature, including Blake Walston's hits, walks, home runs, batters faced, and games played. The resulting zero-derived rates can inflate a stale model score.

The forward scoreboard also renders `cohorts.cohort_count` as a number of boards. The current value `1` means one registered cohort, while the frozen consensus comparisons require at least two public boards per player.

## Design

1. When a player has a newer current-season line, an older historical fallback is eligible for the prospect outcome model only when every factual input used by its outcome feature vector is present. An incomplete old season cannot override newer evidence; the player instead uses the existing pedigree, universal, or identity fallback until the current sample qualifies. History-only players keep their existing prior evidence because removing it causes unrelated, unsupported multi-thousand-place drops.
2. Do not impute missing statistics and do not add player-specific exclusions.
3. Render the scoreboard cohort count as `registered cohort(s)`, and disclose that each player consensus requires at least two public boards. This changes display copy only; the forward-scoreboard calculations and artifact remain unchanged.

## Verification

- A regression test must fail while an incomplete history row can override a newer current line and pass after the shared selector guard.
- A complete historical row must remain eligible.
- A history-only player must retain the existing fallback behavior.
- A scoreboard regression must fail while one cohort is labeled `1 board` and pass when it is labeled `1 registered cohort`.
- Run the focused model and scoreboard suites, then the broader affected test suites.
