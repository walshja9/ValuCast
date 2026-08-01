# My Players Design

**Date:** 2026-08-01

**Status:** Design approved; written review pending

**Scope:** Display and local browser state only

## Goal

Give returning users a fast, personal reason to open ValuCast without adding
accounts or another primary destination. A user can manually follow players
from any board and see a compact **My Players** section above the current
board, using that board's league settings and current validated data.

## Decisions

- Players enter the list only when the user selects a star control.
- One watchlist is shared across Redraft, Dynasty, and Prospects.
- The section lives above the main board; there is no new full-page route or
  navigation item.
- State is stored only in the browser. No account, server-side user record,
  synchronization, notification, or background job is added.
- The feature cannot affect ranks, values, models, publication gates, Role
  Watch, Buy signals, Movers, or any committed artifact.

## Approaches Considered

### Selected: local state plus a server-rendered partial

Store stable player identities in `localStorage`, then request a small HTML
partial containing current rows for those identities. This follows the
existing Flask, Jinja, and htmx architecture, supports players absent from the
current table, and keeps valuation logic on the server.

### Rejected: client-side row cloning

Cloning visible table rows would require less backend work, but it cannot
reliably represent a followed player who is filtered out, below the rendered
limit, promoted, or absent from the current board.

### Rejected: accounts and database-backed watchlists

Accounts would provide cross-device synchronization, but add authentication,
privacy, migration, and support work before ValuCast has evidence that users
need synchronization. The home-screen app already provides a durable
single-device experience.

## Identity Contract

The stored key is `mlbam_id_role`, where role is `hitter` or `pitcher`. This
matches the repository's existing prospect identity convention and preserves
two-way-player separation. The browser never stores names, ranks, values, or
statuses; all display data is resolved fresh by the server.

Rows without a usable MLBAM ID and role do not show a star control. Invalid,
duplicate, or malformed stored identities are ignored rather than guessed.

## User Interface

### Star control

Eligible player rows on all three board modes receive a native button beside
the existing row actions:

- unselected: `☆`, accessible name `Follow <player>`;
- selected: `★`, accessible name `Unfollow <player>`, with
  `aria-pressed="true"`;
- activation must not open the detail row or toggle Compare.

The same control may be added to an existing expanded player detail only when
it can reuse the identical data attributes and event handler. It is not a
separate implementation requirement for v1.

### My Players section

The section appears above the board after at least one player is followed. It
contains at most 50 watched identities and is sorted by the current board's
rank, followed by unresolved identities in the user's stored order.

Each resolved row shows only fields already available from current validated
stores:

- player name, organization/team, position or role;
- rank and league-adjusted value for the current board;
- current value/rank movement when an existing artifact supplies it;
- existing availability, promotion, Role Watch, Buy, or Mover context when
  applicable.

The section does not invent a composite alert, recommendation, or urgency
score. Missing fields render as a dash or are omitted under the existing
display-honesty rule.

If a followed player is not served on the current board but resolves in
another ValuCast universe, the row remains visible with a direct link to the
appropriate Dynasty or Prospects view. The player is never silently removed
from the watchlist.

The empty state is not rendered. Star buttons are the discovery mechanism;
following the first player reveals the section.

## Data Flow

1. A static browser script reads `vc-watchlist` from `localStorage`.
2. It synchronizes the visible star buttons.
3. If the list is non-empty, it sends one same-origin GET request for the My
   Players partial. The request includes the watched identity keys and the
   current board's existing league/scoring query parameters.
4. Flask validates and deduplicates the identities, caps them at 50, resolves
   rows through existing board stores, and renders a Jinja partial.
5. A star change updates local storage and refreshes only the My Players
   partial. Existing board recalculations continue unchanged.

The endpoint returns HTML only. No new public JSON contract is introduced.

## League Context

The partial uses the same validated request parameters as the active board.
URL parameters remain authoritative. Existing locally saved Dynasty settings
continue to populate the board first; the watchlist request simply serializes
the resulting form state. No second league-settings store is created.

## Limits and Failure Behavior

- Maximum stored/resolved list: 50 identities.
- If `localStorage` is unavailable, star controls remain inert or hidden and
  the normal board is unaffected.
- If the partial request fails, the normal board remains usable and the
  existing htmx failure notice handles the error.
- A stale or missing player row is shown as unavailable in the current board
  when it can be resolved elsewhere; otherwise the stored identity remains
  followed and receives a neutral unavailable label.
- User-supplied identity strings are treated as untrusted input and accepted
  only when they match the numeric-ID plus allowed-role contract.

## Analytics

Use the existing first-party event endpoint for two aggregate events:
`watch_player` and `unwatch_player`. Do not include player identity, name, raw
path, or league settings in the event payload. No new analytics schema or
external service is added.

## Testing

Contract tests must prove:

- eligible board rows expose accessible, non-submitting star buttons;
- the client stores one shared list and restores selected state;
- two-way hitter and pitcher identities remain distinct;
- malformed and duplicate identities are ignored;
- the server caps resolution at 50 identities;
- league and scoring parameters reach the partial unchanged through the
  existing validators;
- a player absent from the active board is retained with an honest alternate
  destination or unavailable state;
- following or unfollowing does not toggle player details or Compare;
- local-storage and endpoint failures do not break the main board;
- ranks, values, artifacts, workflow files, and model outputs are unchanged.

Focused tests should run before the full `python -m pytest -q` suite. Browser
verification covers one mobile-width flow: follow a prospect, switch board
modes, reload, and unfollow.

## Explicit Non-Goals

- Accounts or cross-device synchronization.
- Push, email, or operating-system notifications.
- Automatic follows from searches or recently viewed players.
- Personalized model scores, rankings, Buy signals, or recommendations.
- A dedicated My ValuCast route.
- Roster import, full fantasy-team tracking, ownership percentages, or league
  transactions.
- Native-app-only behavior.

These additions require measured repeat usage or direct user demand; they are
not speculative v1 scaffolding.
