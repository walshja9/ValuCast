# ValuCast Render Deployment — Design

**Date:** 2026-06-09
**Status:** Approved (pending spec review)
**Goal:** Take ValuCast from local-only to a live, always-on public site on Render
(Starter plan), deployed reproducibly from `render.yaml`, serving the committed data
snapshot. Custom domain `valucast.app` (registered via Cloudflare) attached as a
no-redeploy follow-up.

## Context (verified)

- The app boots from **git-tracked** data: `data/projections/current.json` (Steamer,
  8.7M), `data/projections/ros.json` (7.1M), `projections/runs/valucast_hp_2026_v1/`
  (ValuCast, 2M + manifest), `data/actuals/current.json`, `data/dd/dd_dynasty_feed.json`.
  Runtime loaders are network-free, so a Render build from GitHub has everything to serve
  both boards. (~19MB JSON on disk; ~60–100MB resident per worker.)
- `app.py` imports `from league_values…`, so the build **must** run `pip install -e .`
  (already in `render.yaml`).
- Production runs via `gunicorn app:app`; the `if __name__ == "__main__"` block (which
  sets `debug=True`) is never executed under gunicorn, so debug stays off in prod.
- `render.yaml` already exists but has two deploy-blockers: `plan: free` (we want
  always-on) and `gunicorn app:app` with no bind (defaults to `127.0.0.1:8000`, which
  Render's health check cannot reach → boot would hang).

## Approach

**Render Blueprint** (driven by `render.yaml`, config-as-code) over a hand-built dashboard
service, so the service definition stays version-controlled and reproducible. **Local
production dry-run first** — reproduce Render's exact build + start commands locally and
curl the real endpoints — so build/runtime breakage is caught before any dashboard step.
**Subdomain now, custom domain later** — ship on `valucast.onrender.com`, attach
`valucast.app` as an additive, no-redeploy step once registered.

Division of labor: I harden the repo, prove the build locally, write exact dashboard
steps, and verify the live URL. Alex does the Render dashboard auth/create, the Cloudflare
registration, and the DNS records (I can't click in dashboards or buy domains).

## 1. Repo hardening (`render.yaml`)

The only code change. New `render.yaml`:

```yaml
services:
  - type: web
    name: valucast
    runtime: python
    plan: starter
    buildCommand: pip install -r requirements.txt && pip install -e .
    startCommand: gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 60 --preload
    healthCheckPath: /
    envVars:
      - key: PYTHON_VERSION
        value: "3.12"
```

Rationale: `--bind 0.0.0.0:$PORT` (Render injects `$PORT`; the health check probes it);
`--workers 2` fits 512MB with the in-memory data; `--timeout 60` is generous slack over
sub-second valuations; `--preload` parses the ~19MB data once in the master then forks
(faster boot, and fails fast if a data file is missing); `healthCheckPath: /` gives Render
a real liveness signal.

## 2. Local production dry-run (the test, before any dashboard step)

Reproduce Render's environment exactly and prove it serves:

- Fresh virtualenv (so deps resolve from `requirements.txt` alone, like Render's clean
  build — catches any missing dependency the dev environment happened to have).
- Run the literal `buildCommand`.
- Run the literal `startCommand` with `PORT=10000` (`$PORT` substituted).
- Curl and assert HTTP 200 + expected content on the full surface:
  - `/` (default Steamer board renders player rows)
  - `/rankings` (Steamer partial)
  - `/rankings?source=valucast` (ValuCast board + provenance caption present)
  - `/methodology` (page renders, "ValuCast H+P v1")
  - `/export?source=valucast` (CSV downloads)

Pass criterion: build succeeds in a clean venv and all five endpoints return 200 with the
right content. Failure here would mean failure on Render — fix locally first. Captured as
a throwaway script, deleted after the run (not committed).

## 3. Blueprint deploy (Alex's dashboard steps, exact walkthrough)

1. I push the hardened `render.yaml` to `main`.
2. Render dashboard → **New +** → **Blueprint**.
3. Connect/authorize GitHub → select **`walshja9/league-values`** → branch `main`.
4. Render parses `render.yaml` and shows one service: **`valucast`** (web, Starter, Python).
   Confirm plan = **Starter**.
5. **Apply** → first build runs ~2–4 min (pip install + `pip install -e .`).
6. Build log should end with the service "Live" and the gunicorn start line; the URL is
   `https://valucast.onrender.com`.

I provide the literal click path and what each screen should show; Alex executes and pastes
back the live URL (and any build-log errors).

## 4. Post-deploy verification (me)

Once the live URL is up, I curl the same five endpoints against **production** and confirm
both boards, the source toggle (segmented control), the provenance caption + OOB footer,
`/methodology`, and CSV export all work live. Also confirm always-on behavior (no
spin-down) by a second request after a short idle.

## 5. Custom domain — `valucast.app` via Cloudflare (documented follow-up, non-blocking)

Run this checklist once the domain is registered; it requires **no redeploy**.

1. **Register** `valucast.app` at **Cloudflare Registrar** (creates the DNS zone in your
   Cloudflare account automatically). Decline add-ons; WHOIS privacy is included.
2. **Render** → `valucast` service → **Settings → Custom Domains → Add Custom Domain** →
   enter `valucast.app` (and optionally `www.valucast.app`). Render shows the verification
   target (`valucast.onrender.com`) and the expected record.
3. **Cloudflare** → `valucast.app` zone → **DNS → Records**:
   - Apex: `CNAME  @  →  valucast.onrender.com`, **Proxy status: DNS only (grey cloud)**.
     Cloudflare's CNAME-flattening serves this correctly at the apex.
   - (Optional) `CNAME  www  →  valucast.onrender.com`, **DNS only (grey cloud)**.
   - **Grey cloud is required** — if proxied (orange), Cloudflare terminates TLS and Render
     can't complete its HTTP-01 challenge to issue the cert.
4. Back in **Render**, wait for **Verified** + **Certificate Issued** (minutes up to ~1 h;
   Let's Encrypt via Render). `.app` is HSTS-preloaded (HTTPS-only); Render's managed TLS
   satisfies it.
5. (Optional) In Render, set the canonical redirect (apex ↔ www) to whichever you prefer.
6. Verify: `https://valucast.app` serves the site over TLS; both boards work.

I'll be present to verify steps 4 and 6 against production when you do this.

## Non-Goals

- Automated data refresh (snapshot-only; a refresh pipeline is a separate project).
- CI/CD beyond Render's built-in auto-deploy on push to `main`.
- Buying the domain now (deploy is not gated on it).
- Any app-feature or data changes.
- Using Cloudflare's proxy/CDN/WAF (DNS-only; Render serves directly).

## Success criteria

1. `render.yaml` sets `plan: starter` and `startCommand` binds `0.0.0.0:$PORT`.
2. Local dry-run: the exact Render build + start command serve all five endpoints with
   200s and correct content from a clean venv.
3. Live: `valucast.onrender.com` serves both boards, source toggle, caption, footer, and
   export — verified by me against production.
4. Always-on confirmed (no spin-down on Starter); a push to `main` triggers auto-redeploy.
5. Custom-domain attachment for `valucast.app` via Cloudflare is documented as a runnable
   checklist (executed when the domain is registered).
