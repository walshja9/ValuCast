# Share Graphic QR Removal Design

## Decision

Remove QR codes and their captions from every ValuCast share graphic. Keep the existing visible `valucast.app` footer as the destination cue.

## Scope

- Remove QR rendering from prospect board, prospect player-card, farm-ranking, and Forward Ledger graphics.
- Reclaim the 128-pixel QR-only strip on prospect player cards.
- Delete the QR helper, optional import, dependency, and QR-specific tests.
- Add one contract test preventing QR rendering from returning to share graphics.

## Non-goals

- No redesign of share graphics.
- No change to card data, model output, rankings, values, routes, downloads, or workflows.

## Acceptance

All affected PNG routes still render valid images, player cards no longer reserve QR-only space, and the repository no longer depends on `qrcode`.
