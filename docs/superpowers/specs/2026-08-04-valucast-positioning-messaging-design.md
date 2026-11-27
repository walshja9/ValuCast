# ValuCast Positioning and Messaging Design

**Date:** 2026-08-04

**Status:** Approved direction; implementation requires a separate plan and review

**Scope:** Copy and information hierarchy only

## Decision

ValuCast will present one product identity:

> **Independent prospect intelligence, translated for your dynasty league.**

The independent model is the reason to trust ValuCast. The dynasty tools are how users apply it. The public methodology, Ledger, and receipts are how ValuCast proves its work.

This resolves the apparent split between “prospect model” and “fantasy tool” without creating a second brand or product.

## Product hierarchy

Every public description should follow the same order:

1. **Evaluate** — independent prospect and MLB evaluation.
2. **Translate** — league-aware rankings, values, and trades.
3. **Act** — buys, movers, call-ups, and reports.
4. **Prove** — methodology, the Ledger, and receipts.

The homepage should lead with evaluation and translation. Action tools and proof should support that promise, not compete with it.

## Approved copy

### Homepage

Place a compact positioning strip immediately before the existing board navigation. It must not become a splash screen or push the board below a large marketing hero.

**Headline**

> Independent prospect intelligence, translated for your dynasty league.

**Support line**

> ValuCast evaluates players independently, then turns that evidence into league-aware rankings, values, trades, buys, and call-up decisions.

The existing board remains the first interactive content. No new call-to-action is needed.

### Metadata

**Default page title**

> ValuCast | Independent Prospect Intelligence for Dynasty Baseball

**Default description**

> Independent prospect evaluation for league-aware dynasty rankings, values, trades, buys and call-up decisions, with public methodology and receipts.

Use the same positioning for default Open Graph and X metadata. Route-specific metadata remains more specific when it already exists.

### Navigation language

Keep the current routes, order, visibility gates, and flat navigation. Change only unclear labels:

| Current label | New label | Route |
| --- | --- | --- |
| Board | Rankings | `/` |
| The Archives | Archives | `/board` |
| Gaps | Disagreements | `/gaps` |
| Backfields | Farm Systems | `/backfields` |

Keep Movers, Buys, Receipts, Map, and Methodology unchanged. Do not add another navigation layer or rename URLs.

### Board support copy

The prospect-board summary should reinforce the hierarchy without making a superiority claim:

> Independent prospect evaluation, league-aware value, current evidence, and actionable signals.

Redraft and dynasty source disclosures remain unchanged.

### Footer

Lead the footer with one shared explanation:

> ValuCast independently evaluates prospects, translates that evidence into league-specific fantasy decisions, and publishes the methodology and receipts.

Keep the existing route-specific source and freshness disclosures below it. Do not redesign the footer or add new destinations in this pass.

### Share graphics

Use **Independent prospect intelligence** as the short default brand line on prospect and player share graphics.

Keep functional surface names where they identify the graphic, including Prospect Movers, Farm-System Rankings, Call-Up Receipts, Track Record, Forward Ledger, Discipline Leaders, and The Second Opinion. “Ahead of the Curve” remains the editorial name for the Buys product; it is no longer the default company positioning.

### X profile

**Bio**

> Independent prospect intelligence, translated for your dynasty league. Daily rankings, values, trades and receipts. Free at valucast.app.

**Pinned post**

```text
ValuCast independently evaluates prospects, then translates that evidence into your dynasty league.

Evaluate: prospect + MLB models
Translate: league-aware rankings, values + trades
Act: buys, movers + call-ups
Prove: methodology, Ledger + receipts

Free: valucast.app
```

The bio and pinned post are owner-applied copy; implementation must not automate posting or change social credentials.

## UX constraints

- Keep the board immediately accessible on desktop and mobile.
- Preserve current routes, saved league settings, install behavior, holds, and accessibility semantics.
- Do not hide source, freshness, uncertainty, or validation disclosures.
- Keep copy readable without animation or JavaScript.
- Do not mention or compare named competitors.
- Do not claim ValuCast is the most accurate, best, or an industry standard before registered evidence authorizes that claim.

## Non-goals

- No scoring, ranking, value, model, cap, Role Watch, or publication changes.
- No new routes, features, account system, native app, newsletter, or second brand.
- No redesign of boards, cards, navigation mechanics, or share-card layouts.
- No removal of “Ahead of the Curve” or “The Second Opinion” as product names.
- No new analytics events or dependencies.

## Verification

The implementation should leave the smallest runnable proof:

1. Template contract tests for the homepage headline, default metadata, four navigation labels, footer statement, and prospect-board summary.
2. A share-renderer contract test confirming the new default line while preserving explicit surface taglines.
3. Existing route and accessibility tests.
4. Desktop and mobile render smoke checks confirming the positioning strip does not obstruct or materially delay the board.
5. A rank/value artifact comparison showing no data changes.

## Delivery

Ship as one reviewed copy-only pull request. Normal deployment is sufficient; no data refresh, workflow dispatch, model look, or re-baseline is required.
