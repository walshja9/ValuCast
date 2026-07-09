# Plan 008: Self-host the web fonts — faster first paint, no Google IP leak, tighter CSP

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 72e68864..HEAD -- templates/base.html static/style.css app.py`
> On a mismatch with the excerpts below, STOP.

## Status

- **Priority**: P2
- **Effort**: S-M
- **Risk**: LOW (worst case is a font falling back to the system stack)
- **Depends on**: none
- **Category**: perf + privacy
- **Planned at**: commit `72e68864`, 2026-07-08

## Why this matters

Every page load blocks first text paint on two extra origins (fonts.googleapis.com CSS, then fonts.gstatic.com files) and leaks each visitor's IP to Google — on a site that deliberately self-hosts every other asset (htmx, html2canvas) and has no accounts or tracking. Two of the three font families are ALREADY committed to the repo as variable TTFs (used by the Pillow share-card renderers). Self-hosting removes the render-blocking cross-origin fetch, the FOUT/layout-shift on cold loads, the GDPR exposure, and lets the CSP drop both Google hosts.

## Current state

- `templates/base.html:23-25`:
  ```html
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700&family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap">
  ```
  `base.html` is the ONLY template pulling fonts (verify: `grep -rn "fonts.googleapis" templates/` → 1 file).
- `static/fonts/` already contains `SpaceGrotesk[wght].ttf` (136KB, variable) and `JetBrainsMono[wght].ttf` (187KB, variable) — committed for the Pillow renderers (`app.py:2150-2154` `_GRAPHIC_BRAND_FONTS`). Archivo is NOT in the repo.
- `static/style.css:40-43` — the font stacks (system fallbacks already present):
  ```css
  --font-display: "Space Grotesk", -apple-system, ...;
  --font-body: "Archivo", -apple-system, ..., Roboto, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, ...;
  ```
  No `@font-face` rules exist anywhere in style.css (verify with grep).
- `app.py:95-97` CSP (inside `_CSP_POLICY`): `style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com data:;`
- Gzip note: `_GZIP_MIMETYPES` (app.py:79) does NOT include font types, and woff2 is already brotli-compressed — do not add font mimetypes to gzip.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Fetch woff2 (needs network) | `curl -A "Mozilla/5.0 ... Chrome/120" -s "https://fonts.googleapis.com/css2?family=Archivo:wght@400..700&display=swap"` | CSS containing `.woff2` URLs (a Chrome UA is required to be served woff2) |
| App tests | `python -m pytest -q tests/test_app.py` | all pass |
| Header check | `python - <<'PY'` snippet asserting CSP (Step 3 verify) | passes |

## Scope

**In scope**:
- `templates/base.html` (the three font lines)
- `static/style.css` (add `@font-face` rules at the top)
- `static/fonts/` (add woff2 files)
- `app.py` (the `_CSP_POLICY` string only)
- `tests/test_app.py` (extend the existing CSP test)

**Out of scope**:
- `_GRAPHIC_BRAND_FONTS` / Pillow rendering — the TTFs stay exactly where they are; server-side rendering is untouched.
- Any other CSP directive (`script-src 'unsafe-inline'` is a separate, larger finding — do not attempt it here).
- Font choices/weights — same three families, same weights as the current Google CSS.

## Git workflow

- Work on `master` locally, do NOT push. Stage explicitly (the new font binaries individually — never `git add -A`). Commit style: `Self-host web fonts; drop Google Fonts origins from CSP`.

## Steps

### Step 1: Acquire woff2 files

Primary path (network): request the Google Fonts css2 URL from Current state with a Chrome desktop User-Agent — the response is `@font-face` CSS with `https://fonts.gstatic.com/...woff2` URLs. For EACH family, download the `latin` subset variable file (css2 with a wght range like `Archivo:wght@400..700` returns one variable woff2 per subset; if only static per-weight files come back, take 400/500/600/700 for Archivo + Space Grotesk and 400/500 for JetBrains Mono, latin subset only). Save as `static/fonts/Archivo[wght].woff2`, `static/fonts/SpaceGrotesk[wght].woff2`, `static/fonts/JetBrainsMono[wght].woff2` (or `-400.woff2` style names for static files).

Fallback path (no network available): write `@font-face` rules pointing at the two COMMITTED TTFs (`SpaceGrotesk[wght].ttf`, `JetBrainsMono[wght].ttf`) with `font-weight: 400 700` / `400 500`, and leave `--font-body` falling back to the system stack by removing only the Google link (Archivo temporarily unavailable). Report in your summary that Archivo needs a follow-up download; do NOT ship a broken external link.

**Verify**: `ls -la static/fonts/` shows the new files; each woff2 is > 10KB and < 150KB (a tiny file means an error page was saved — inspect with `file static/fonts/*.woff2` → "Web Open Font Format 2").

### Step 2: `@font-face` + preload, remove the Google link

At the very top of `static/style.css` add one `@font-face` per family (variable form shown):
```css
@font-face {
  font-family: "Archivo";
  src: url("fonts/Archivo[wght].woff2") format("woff2");
  font-weight: 400 700;
  font-display: swap;
}
```
(matching blocks for Space Grotesk `400 700` and JetBrains Mono `400 500`; note style.css lives in static/, so the relative `fonts/` URL resolves to /static/fonts/). In `templates/base.html`, delete the two preconnects + the Google stylesheet link, and add ONE preload for the body face before the stylesheet link:
```html
<link rel="preload" href="{{ url_for('static', filename='fonts/Archivo[wght].woff2') }}" as="font" type="font/woff2" crossorigin>
```

**Verify**: `grep -rn "fonts.googleapis\|fonts.gstatic" templates/ static/style.css` → no hits.

### Step 3: Tighten the CSP

In `app.py` `_CSP_POLICY`: `style-src 'self' 'unsafe-inline'` (drop googleapis) and `font-src 'self' data:` (drop gstatic).

**Verify**: update the existing CSP test in `tests/test_app.py` (grep `Content-Security-Policy` there) to assert both Google hosts are ABSENT and the directives still present; `python -m pytest -q tests/test_app.py` → all pass.

### Step 4: Visual smoke (reviewer/Alex gate)

Run the app (`python app.py`, port 5001) and load `/` in a browser with devtools Network open: three font files load from /static/fonts with 200s, zero requests to any Google host, headings render in Space Grotesk (distinctly geometric — compare against production if unsure), body in Archivo, table numbers in JetBrains Mono. This step is a human check — flag for the reviewer rather than asserting yourself if you cannot run a browser.

## Test plan

- Extend the existing CSP assertion test (Step 3).
- Add one test: GET `/static/fonts/<the archivo file>` → 200 and `Content-Type` contains `font` (Flask serves woff2 as `font/woff2` on py3.11+; if it comes back `application/octet-stream`, register the mimetype via `mimetypes.add_type("font/woff2", ".woff2")` at app startup and note it).
- `python -m pytest -q` full suite green; restore `data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json` after.

## Done criteria

- [ ] No reference to fonts.googleapis.com / fonts.gstatic.com anywhere in the repo (`grep -rn "gstatic\|googleapis" templates/ static/ app.py` → only the CSP test asserting absence, if worded that way).
- [ ] Three families load from /static/fonts (or documented Archivo-pending fallback).
- [ ] CSP no longer lists Google hosts; tests assert it.
- [ ] `python -m pytest -q` exits 0.
- [ ] `git status`: only in-scope files (+ new font binaries).
- [ ] `plans/README.md` status row updated.

## STOP conditions

- Downloaded files fail the `file` check (not real woff2).
- The css2 endpoint won't serve woff2 to your UA and no fallback UA works — use the committed-TTF fallback path and report.
- Any template other than base.html turns out to reference Google Fonts (grep first — the OG/share templates must keep working).

## Maintenance notes

- License note for the repo: all three families are OFL-licensed (Google Fonts); include the OFL notice if a fonts/LICENSE file convention exists, otherwise mention licensing in the commit message.
- If a fourth font family is ever added, it follows this pattern — never re-add a fonts CDN, the CSP will (correctly) block it.
- Follow-up (deliberately out of scope): `script-src 'unsafe-inline'` removal is audit finding "CSP is decorative" — a larger inline-handler migration; do not bundle it here.
