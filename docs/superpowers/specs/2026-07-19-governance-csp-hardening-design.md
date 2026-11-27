# Governance and CSP Hardening Design

## Goal

Remove two public-trust defects without changing rankings, values, model inputs, publication gates, or held features.

## Peak governance correction

Peak Projection is display-only context. Its committed calibration artifact says `feeds_live_rank: false`, `feeds_live_value: false`, and `ready_for_review: true`, while the public registry currently marks it as feeding value and public surfaces call it ready or live.

The registry entry will set `feeds_value` to `false`. The registry validator will reject any future entry that claims to feed value when its evidence artifact explicitly sets `source_policy.feeds_live_value` to `false`. Public Intelligence and Scouting status copy will say `Display only`, with supporting copy that it does not move rank or value.

## CSP-safe HTMX trigger

The board form's HTMX trigger filter is compiled with `Function(...)`, which violates the real Content Security Policy. HTMX catches that failure and treats the change trigger as unfiltered, so changing the league-import URL submits an unintended rankings request.

The form will use the ordinary declarative `change` trigger. The league URL input alone will stop its native change event from bubbling to the form. This preserves every existing board control and search trigger without loosening CSP or adding JavaScript infrastructure.

## Verification

- A registry-validator regression rejects a display-only artifact marked as feeding value.
- Public-route regressions require the Peak surfaces to say `Display only` and not show a `feeds value` badge for Peak.
- A Playwright regression loads the real app under its CSP, changes the league URL, and requires zero CSP errors and zero `/rankings` requests.
- Existing targeted tests and the full automated suite must pass.

## Non-goals

- No Peak model, prospect rank, prospect value, share-card, or publication behavior changes.
- No CSP weakening, HTMX replacement, new dependency, or general form refactor.
- No push or production deployment.
