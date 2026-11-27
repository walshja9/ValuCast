# ValuCast Render Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. NOTE: this is a deployment plan — Tasks 1–3 and 5 are automatable; Tasks 4 and 6 are **interactive** (Alex performs dashboard/registrar actions, the agent provides exact steps and verifies).

**Goal:** Deploy ValuCast as an always-on Render Starter web service from `render.yaml`, serving the committed data snapshot, then attach `valucast.app` (Cloudflare) as a no-redeploy follow-up.

**Architecture:** Render Blueprint reads a hardened `render.yaml` (Starter plan, gunicorn bound to `0.0.0.0:$PORT`). A local production dry-run in WSL (Linux, like Render) proves the exact build + start commands serve all endpoints before any dashboard step. Custom domain is attached via Cloudflare DNS-only records after launch.

**Tech Stack:** Flask, gunicorn, Render (Blueprint + managed TLS), Cloudflare Registrar/DNS, WSL Ubuntu (dry-run only).

**Spec:** `docs/superpowers/specs/2026-06-09-render-deployment-design.md`

---

## File Structure

- `render.yaml` — the only repo change. Hardens plan + gunicorn bind/tuning + health check.
- (dry-run is a throwaway WSL venv + ad-hoc curls; nothing committed.)

No application code changes. No test files (the verification is the live-process dry-run, not unit tests — the app's 584-test suite already passed and is unchanged).

---

### Task 1: Harden `render.yaml`

**Files:**
- Modify: `render.yaml` (full rewrite — 6 lines change)

- [ ] **Step 1: Rewrite `render.yaml`**

Replace the entire file contents with:

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

- [ ] **Step 2: Verify it is valid YAML and has the deploy-critical fields**

Run:
```bash
python -c "import yaml,sys; d=yaml.safe_load(open('render.yaml')); s=d['services'][0]; assert s['plan']=='starter', s.get('plan'); assert '0.0.0.0:$PORT' in s['startCommand'], s['startCommand']; assert s['healthCheckPath']=='/'; print('render.yaml OK:', s['name'], s['plan'])"
```
Expected: `render.yaml OK: valucast starter`
(If PyYAML is missing: `pip install pyyaml` first. PyYAML is only a local lint dep, not added to `requirements.txt`.)

- [ ] **Step 3: Commit (do NOT push yet — push happens in Task 3 after the dry-run passes)**

```bash
git add render.yaml
git commit -m "chore: harden render.yaml for deploy (starter plan, bind \$PORT, preload)"
```

---

### Task 2: Local production dry-run in WSL

Reproduce Render's Linux build + start commands in a clean venv and prove all five endpoints serve. This is the gate before pushing.

**Files:** none (throwaway WSL venv at `~/vc-dryrun`, removed at the end).

**Known caveat:** WSL has Python 3.14; Render pins 3.12. For this pure-Python Flask app the dry-run validates build/import/serve, which is interpreter-version-robust. A dependency that fails to install *only* on 3.14 is a WSL artifact, not a Render blocker — note it and rely on Render's own 3.12 build as the final word.

- [ ] **Step 1: Create a clean venv and run the exact `buildCommand`**

Run (single WSL invocation; `REPO` points at the Windows checkout via `/mnt`):
```bash
wsl bash -lc 'set -e; REPO=/mnt/c/Users/Alex/Documents/Codex/2026-05-18/league-values; rm -rf ~/vc-dryrun && python3 -m venv ~/vc-dryrun && ~/vc-dryrun/bin/pip install -q --upgrade pip && ~/vc-dryrun/bin/pip install -q -r "$REPO/requirements.txt" && ~/vc-dryrun/bin/pip install -q -e "$REPO" && echo BUILD_OK'
```
Expected: ends with `BUILD_OK`. (If a package fails to build only on 3.14, record it and proceed to Render's 3.12 build as the real check.)

- [ ] **Step 2: Boot gunicorn with the exact `startCommand` and curl all five endpoints**

Run (boots gunicorn on port 10000 from the repo dir so `import web`/`projections` resolve, waits for liveness, curls, then kills it):
```bash
wsl bash -lc 'set -e; REPO=/mnt/c/Users/Alex/Documents/Codex/2026-05-18/league-values; cd "$REPO"; PORT=10000 ~/vc-dryrun/bin/gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 60 --preload --pid /tmp/vc.pid --daemon --access-logfile /tmp/vc.log --error-logfile /tmp/vc.err; for i in $(seq 1 30); do curl -sf -o /dev/null http://127.0.0.1:10000/ && break || sleep 1; done; echo "--- status codes ---"; for p in "/" "/rankings" "/rankings?source=valucast" "/methodology" "/export?source=valucast"; do code=$(curl -s -o /tmp/body -w "%{http_code}" "http://127.0.0.1:10000$p"); echo "$code  $p"; done; echo "--- content probes ---"; curl -s "http://127.0.0.1:10000/rankings?source=valucast" | grep -q "pitching model is fully in-house" && echo "caption OK" || echo "caption MISSING"; curl -s "http://127.0.0.1:10000/methodology" | grep -q "ValuCast H+P v1" && echo "methodology OK" || echo "methodology MISSING"; curl -s "http://127.0.0.1:10000/" | grep -q "player-row" && echo "board OK" || echo "board MISSING"; kill $(cat /tmp/vc.pid) 2>/dev/null; echo DRYRUN_DONE'
```
Expected: five `200` lines, then `caption OK`, `methodology OK`, `board OK`, then `DRYRUN_DONE`.

- [ ] **Step 3: If any endpoint is non-200, inspect the gunicorn error log and fix before proceeding**

Run:
```bash
wsl bash -lc 'echo "=== error log ==="; tail -40 /tmp/vc.err; echo "=== access log ==="; tail -20 /tmp/vc.log'
```
Diagnose from the traceback. Most likely causes and fixes:
- `ModuleNotFoundError: league_values` → the `pip install -e .` step did not run / failed; re-run Step 1.
- `ModuleNotFoundError: web`/`projections` → gunicorn was not started from the repo root; ensure the `cd "$REPO"` is present.
- `FileNotFoundError` on a data path → a boot data file is not tracked; `git ls-files` it and `git add` it.
Re-run Step 2 until all green. Do not advance to Task 3 with any failure.

- [ ] **Step 4: Tear down the dry-run venv**

```bash
wsl bash -lc 'rm -rf ~/vc-dryrun /tmp/vc.pid /tmp/vc.log /tmp/vc.err /tmp/body; echo CLEANED'
```
Expected: `CLEANED`.

---

### Task 3: Push the hardened blueprint

**Files:** none (push only).

- [ ] **Step 1: Confirm the dry-run passed, then push `main`**

```bash
git push origin main
```
Expected: push succeeds; the `render.yaml` commit is now on GitHub for Render's Blueprint to read.

---

### Task 4: Blueprint deploy (INTERACTIVE — Alex in the Render dashboard)

The agent provides the exact click path; Alex executes and pastes back the live URL or any build-log error. No repo action.

- [ ] **Step 1: Create the Blueprint service**

1. Go to **https://dashboard.render.com** and sign in (GitHub auth).
2. Click **New +** (top right) → **Blueprint**.
3. **Connect a repository** → authorize Render for GitHub if prompted → select **`walshja9/league-values`**.
4. Branch: **`main`**. Render reads `render.yaml` and shows a service to create: **`valucast`** (type web, runtime Python, plan **Starter**).
5. Give the Blueprint a name if asked (e.g. `valucast`) and click **Apply** / **Create Services**.

- [ ] **Step 2: Watch the first build**

The build runs `pip install -r requirements.txt && pip install -e .` (~2–4 min), then starts gunicorn. A healthy deploy ends with the log line showing `Booting worker` and the service status flipping to **Live**.

- [ ] **Step 3: Report back**

Paste to the agent either:
- the live URL (`https://valucast.onrender.com` or the assigned `*.onrender.com`), **or**
- the last ~30 lines of the build/deploy log if it failed.

(If the build fails: the agent diagnoses from the log. The dry-run in Task 2 should have caught build/serve issues; a Render-only failure is most likely a `PYTHON_VERSION`/dependency resolution difference, which the agent will address by adjusting `requirements.txt`/`render.yaml` and you re-deploy.)

---

### Task 5: Post-deploy production verification (agent)

**Files:** none.

- [ ] **Step 1: Curl the live URL's full surface**

Once Alex provides `LIVE_URL` (the `*.onrender.com` address), run (substitute the real URL):
```bash
LIVE=https://valucast.onrender.com; echo "--- status codes ---"; for p in "/" "/rankings" "/rankings?source=valucast" "/methodology" "/export?source=valucast"; do code=$(curl -s -o /tmp/lbody -w "%{http_code}" "$LIVE$p"); echo "$code  $p"; done; echo "--- content ---"; curl -s "$LIVE/rankings?source=valucast" | grep -q "pitching model is fully in-house" && echo "caption OK" || echo "caption MISSING"; curl -s "$LIVE/methodology" | grep -q "ValuCast H+P v1" && echo "methodology OK" || echo "methodology MISSING"; curl -s "$LIVE/" | grep -q "player-row" && echo "board OK" || echo "board MISSING"
```
Expected: five `200` lines, then `caption OK`, `methodology OK`, `board OK`.

- [ ] **Step 2: Confirm always-on (no spin-down)**

Render Starter does not spin down. Confirm responsiveness on a second hit after a brief idle:
```bash
LIVE=https://valucast.onrender.com; sleep 20; curl -s -o /dev/null -w "second-hit latency: %{time_total}s  status: %{http_code}\n" "$LIVE/"
```
Expected: status `200` with a low latency (sub-second after warm; Starter never cold-starts). Report results to Alex.

---

### Task 6: Attach `valucast.app` via Cloudflare (INTERACTIVE — deferred, no redeploy)

Run when Alex has registered the domain. The agent verifies steps 4 and 6 against production. Full rationale is in the spec §5; the runnable checklist:

- [ ] **Step 1: Register the domain**

At **Cloudflare Registrar**, register **`valucast.app`** (creates the DNS zone in your Cloudflare account). Decline add-ons; WHOIS privacy is included free.

- [ ] **Step 2: Add the custom domain in Render**

Render → **`valucast` service → Settings → Custom Domains → Add Custom Domain** → enter `valucast.app` (and optionally `www.valucast.app`). Render displays the verification target (`valucast.onrender.com`).

- [ ] **Step 3: Create the Cloudflare DNS records**

Cloudflare → `valucast.app` zone → **DNS → Records**:
- `CNAME  @  →  valucast.onrender.com`  — **Proxy status: DNS only (grey cloud).**
- (Optional) `CNAME  www  →  valucast.onrender.com`  — **DNS only (grey cloud).**

**Grey cloud is mandatory** — if proxied (orange), Cloudflare terminates TLS and Render cannot complete its HTTP-01 challenge to issue the certificate. Cloudflare's CNAME-flattening serves the apex `CNAME @` correctly.

- [ ] **Step 4: Wait for Render to verify + issue TLS**

In Render's Custom Domains panel, wait for **Verified** and **Certificate Issued** (minutes up to ~1 hour). `.app` is HSTS-preloaded (HTTPS-only); Render's managed Let's Encrypt cert satisfies it. (Agent verifies this status with Alex.)

- [ ] **Step 5: (Optional) Set the canonical redirect**

In Render, choose the canonical host (apex ↔ www) so the non-canonical one 301s to it.

- [ ] **Step 6: Verify the live domain**

```bash
for p in "/" "/rankings?source=valucast" "/methodology"; do curl -s -o /dev/null -w "%{http_code}  %{url_effective}\n" "https://valucast.app$p"; done
```
Expected: `200` on each over TLS. Report to Alex; deployment complete.

---

## Self-Review

**Spec coverage:**
- Spec §1 render.yaml hardening → Task 1.
- Spec §2 local production dry-run (5 endpoints, clean env) → Task 2 (run in WSL for real gunicorn/Linux; spec said "fresh venv + exact build/start command" — WSL satisfies this more faithfully than Windows, where gunicorn can't run).
- Spec §3 Blueprint deploy → Tasks 3 (push) + 4 (dashboard).
- Spec §4 post-deploy verification → Task 5.
- Spec §5 custom domain (Cloudflare, valucast.app) → Task 6.
- Success criteria 1→Task1, 2→Task2, 3→Task5, 4→Task5 Step2 + Render auto-deploy (push in Task 3), 5→Task6.

**Placeholder scan:** No TBD/TODO. Every command is literal and runnable. The one substitution (`LIVE_URL`/`valucast.app`) is unavoidable real-world input, with the placeholder default `https://valucast.onrender.com` shown.

**Consistency:** Service name `valucast`, repo `walshja9/league-values`, branch `main`, port 10000 for the dry-run, the same five-endpoint set and three content probes ("pitching model is fully in-house", "ValuCast H+P v1", "player-row") used identically in Task 2 (local) and Task 5 (prod). gunicorn flags identical between `render.yaml` and the Task 2 boot command.

**Deviation noted:** This plan is operational, not TDD — the verification gate is the live-process dry-run (Task 2) and prod curl (Task 5), since the deliverable is a deployment, not new code. The existing 584-test suite is unchanged and already green.
