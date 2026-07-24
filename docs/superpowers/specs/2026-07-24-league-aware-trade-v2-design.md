# League-Aware Second Opinion V2 Design

**Date:** 2026-07-24  
**Status:** Approved in conversation

## Goal

Let a user apply manual league context to The Second Opinion without accounts,
league import, invented prospect category values, or a new fitted model.

The feature must make a real numerical adjustment where current ValuCast data
supports one, and must label every setting that remains context-only.

## Current Evidence

The existing application already provides:

- validated manual league-size and roster-depth parsing in
  `web/league_settings.py`;
- a replacement-level dynasty-dollar implementation in `app.py`;
- fixed scoring presets in `web/category_registry.py`;
- preset-specific 0-100 dynasty values for every MLB row in the public
  snapshot; and
- category-specific prospect re-ranking within hitter and pitcher roles.

The July 24 public snapshot has preset-specific values for all 913 MLB rows and
none of its 2,866 prospect rows. Prospect category ranks are not calibrated
onto the shared MLB/prospect 0-100 value scale. Therefore a scoring preset may
change a trade total only when every resolved trade piece is an MLB player.

## Approaches Considered

1. **Selected: phased, fail-closed league context.** League depth changes all
   opted-in trades. Scoring presets change MLB-only trades. Prospect or mixed
   trades use base dynasty values for every player and say why. Competitive
   window and prospect slots remain context-only.
2. **Wait for calibrated prospect preset values.** This would give one uniform
   scoring path, but it blocks useful league-depth support on a future model
   study that is not ready.
3. **Apply the MLB preset while leaving prospects unchanged.** Rejected because
   it silently mixes two value definitions inside one trade.

## Public Controls

Add a compact manual setup form to `/trade` with these query parameters:

| Parameter | Values | Default |
|---|---|---|
| `league` | `1` enables V2 | absent |
| `teams` | integer, clamped to 4–20 | 12 |
| `roster` | integer, clamped to 10–50 | 26 |
| `pslots` | integer, clamped to 0–20 | 5 |
| `preset` | existing `DYNASTY_VALUE_PRESETS` key or blank | blank |
| `window` | `balanced`, `contend`, or `rebuild` | `balanced` |

The form submits with `GET` and preserves the resolved `give` and `get` IDs.
The resulting URL is the durable, shareable state. No local storage, account,
database, or server-side profile is added.

Existing `/trade?give=...&get=...` links without `league=1` retain the current
player-only calculation and copy. This avoids silently changing previously
shared verdicts.

Budget is not a V2 input. V2 compares value points above replacement, not
auction dollars, so budget would only decorate or rescale the same decision.

## Numerical Contract

### Selected value

For an opted-in trade:

1. Resolve and deduplicate the trade exactly as V1 does.
2. If every resolved player on both sides is an MLB player and `preset` is a
   recognized key, use `row.value_for(preset)` for the trade and replacement
   pool.
3. Otherwise use `row.dynasty_value` for every trade player and every row in
   the replacement pool.

When an MLB-only preset is active, prospect rows in the full replacement pool
fall back to their base dynasty value through the existing `value_for`
contract. This matches the shipped dynasty-board behavior.

### Replacement adjustment

Use the complete served dynasty universe and the selected-value rule above:

```text
cutoff = min(teams × roster, number of served rows)
replacement = selected value of the row at cutoff
league-adjusted value = max(0, selected value − replacement)
```

The trade totals and margin are sums of league-adjusted values. This is the
same value-above-replacement concept already used before dynasty auction-dollar
normalization, but it remains on the existing 0-100 point scale.

Because the scale remains 0-100, V1's fixed value band of approximately
plus/minus 9 points per player remains unchanged. Count-mismatch,
cross-universe, duplicate-cancellation, one-sided, and empty-state behavior
also remain unchanged.

`pslots` does not alter this calculation. The existing dynasty contract defines
`teams × roster` as the combined MLB/prospect rostered pool and uses prospect
slots only as prospect-depth context.

## Honesty Contract

Every opted-in result must show the applied league summary:

```text
12 teams · 26 roster spots · 5 prospect slots · 7x7 OPS · Contending
```

The result and share graphic must also carry the applicable statements:

- MLB-only preset applied:
  `Scoring preset applied to every player.`
- Recognized preset requested with any prospect:
  `Scoring preset not applied: prospect preset values are not calibrated on the shared MLB/prospect value scale. Base dynasty values were used for every player.`
- Prospect slots:
  `Prospect slots are roster-depth context only and do not change the totals.`
- Competitive window:
  `Competitive window is context only and does not change the totals.`

The application must never describe prospect/mixed totals as format-adjusted.
Changing only `window` or `pslots` must produce exactly the same numerical
totals and verdict.

V1's unconditional player-only disclosure remains:

> Player-only verdict: draft picks, FAAB, roster spots, and league context are not included.

For opted-in V2 results, replace only the final phrase so the sentence remains
accurate:

> Player-only verdict: draft picks, FAAB, and unlisted roster effects are not included.

The V1 disclosure remains unchanged on legacy links.

## Page and Share-Graphic Parity

The page, share-preview URL, Open Graph image URL, and PNG route must carry the
same canonical query parameters. Add `league` to `_PNG_CACHE_PARAMS`; the
existing cache-key support for `teams`, `roster`, `pslots`, `preset`, and
`window` remains authoritative.

The PNG must display:

- the league summary;
- whether the scoring preset was applied; and
- the prospect-slot and competitive-window context-only disclosures.

The PNG reuses the existing wrapping and note layout. It must not add a new
graphic renderer or dependency.

## Validation and Failure Behavior

- Reuse `parse_league_settings`; malformed values fall back or clamp exactly as
  they do on the dynasty board.
- An unknown preset falls back to base dynasty values and is not described as
  applied.
- An unknown window becomes `balanced`.
- A missing or unavailable public snapshot keeps the existing unavailable
  state.
- A one-sided or empty trade still produces no verdict or PNG.
- A cutoff at or beyond the served universe uses the final row as replacement.
- No request writes data or mutates a served row.

## Testing

Tests must prove:

1. A legacy trade URL produces its existing totals, headline, scope note, and
   share URL.
2. Shallow and deep opted-in leagues can produce different adjusted totals from
   the same trade.
3. A valid scoring preset changes an MLB-only trade and is labeled applied.
4. The same preset on a trade containing a prospect uses base values for every
   piece and renders the fail-closed disclosure.
5. Changing only `window` or `pslots` leaves totals and the verdict byte-for-byte
   equal.
6. Invalid settings clamp or fall back without a 500 or false applied label.
7. Duplicate cancellation, one-sided input, value-band, count-mismatch, and
   cross-universe behavior remain intact.
8. Page, preview metadata, PNG content, and PNG cache keys carry the same V2
   state.
9. The complete daily-public-data validation and full test suite remain green.
10. A 390×844 browser pass has no clipped controls, hidden disclosures, broken
    images, or new console errors.

## Boundaries

- No new model or research look.
- No changes to ranks, base dynasty values, public snapshot artifacts, daily
  workflows, publication gates, pitcher caps, Role Watch, or model flags.
- No prospect preset-value mapping.
- No draft-pick, FAAB, roster-import, league-import, account, payment, or
  persistence work.
- No deployment in this slice.

