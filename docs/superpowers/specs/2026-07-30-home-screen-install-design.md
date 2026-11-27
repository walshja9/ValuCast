# ValuCast Home-Screen Installation Design

**Date:** 2026-07-30
**Status:** Approved design; implementation not started
**Branch:** `codex/home-screen-install`

## Outcome

Make ValuCast installable from a supported browser as a standalone home-screen
web app. The installed experience uses the existing live site and existing brand
assets; it does not create a native application or a second product surface.

## Scope

### Included

- A root-scoped web app manifest linked from every HTML page.
- Existing 192px and 512px ValuCast marks as install icons.
- Standalone display using the current ValuCast background and theme colors.
- A discoverable, accessible **Install ValuCast** control in the site footer.
- The native browser install prompt on browsers that expose it.
- Brief Share → Add to Home Screen instructions on iPhone and iPad.
- Automatic suppression of the install control when ValuCast is already running
  in standalone mode.

### Excluded

- Service workers, offline caching, cached HTML, or cached board data.
- Push notifications, badges, background synchronization, or app shortcuts.
- Apple App Store or Google Play packaging.
- Native wrappers or platform-specific application code.
- Changes to models, rankings, values, artifacts, workflows, or daily refresh.
- A dependency on the pending first-party analytics work. Installation events
  can be added after that endpoint exists.

## User Experience

The footer contains an **Install ValuCast** button that is hidden by default.
External JavaScript reveals it only when installation is actionable:

1. On Android or desktop browsers that emit `beforeinstallprompt`, selecting the
   button opens the browser's native installation prompt.
2. On iPhone or iPad outside standalone mode, selecting the button opens a small
   native HTML dialog explaining: open Share, then select **Add to Home Screen**.
3. In standalone mode, the button remains hidden.
4. On unsupported browsers with no applicable installation path, the button
   remains hidden rather than presenting a dead action.

The installed app launches `/` in a standalone window. All board, player-card,
trade, methodology, and share routes continue to load from the network exactly
as they do in the browser.

## Components

### Web app manifest

Add `static/app.webmanifest` with:

- `id` and `start_url`: `/`
- `scope`: `/`
- `name` and `short_name`: `ValuCast`
- `display`: `standalone`
- existing `#12131f` background and theme colors
- existing `/static/brand/valucast-mark-192.png` and
  `/static/brand/valucast-mark-512.png` icons with purpose `any`

The manifest is linked from `templates/base.html`, which already supplies the
theme color and Apple touch icon.

### Installation controller

Add one dependency-free external file, `static/install-app.js`. It owns:

- standalone-mode detection;
- capture and one-time use of `beforeinstallprompt`;
- iPhone/iPad install-instruction detection;
- button visibility and click handling;
- hiding the control after `appinstalled`.

No inline installation script is added, and no CSP change is required.

### Footer markup

Add a hidden button and a native `<dialog>` to `templates/base.html` beside the
shared footer. The button has an explicit accessible label. The dialog includes
a heading, concise instructions, and a close button; native Escape behavior and
focus handling remain intact.

## Freshness and Failure Behavior

The feature intentionally has no service worker. Every installed navigation
continues to use the live network response, so installation cannot introduce a
second cache capable of serving stale rankings or cards.

If the manifest, JavaScript, or browser installation API is unavailable, the
normal website continues to work and the install control stays hidden.

## Verification

Automated checks will cover:

- manifest validity and required fields;
- referenced icon files and dimensions;
- manifest and controller links on the shared base page;
- hidden-by-default, accessible install markup;
- controller behavior for native prompt, iPhone/iPad instructions, unsupported
  browsers, installed mode, and `appinstalled`.

Manual staging checks will cover:

- Android Chrome installation and standalone launch;
- iPhone Safari Share → Add to Home Screen and standalone launch;
- desktop Chrome/Edge installation when offered;
- normal navigation, player cards, trade analyzer, and share actions inside the
  standalone window;
- no offline or stale-data claims.

## Release Boundary

This ships as a small, independent product PR. It does not wait for analytics
instrumentation and does not change the public-data pipeline. Store packaging is
a later project after the installed web experience is stable and, for Apple,
after ValuCast has app-specific utility beyond a repackaged website.
