# Plan 002: Remove DD as a live valuation fallback and retire the three DD deploy gates

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat c8d8a22..HEAD -- app.py render.yaml scripts/validate_public_data_freshness.py tests/test_app.py tests/test_public_data_refresh.py tests/test_public_surfaces_smoke.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: 001 (its fail-loud validators + the `_stale`-aware route assertion must land first, so this behavioral change cannot silently regress)
- **Category**: tech-debt / architecture
- **Planned at**: commit `c8d8a22`, 2026-06-17

## Why this matters

This is the product decision: **DD must never be the live valuation authority for
ValuCast.** A blank or stale-but-labeled board is a product problem (fixable); a
silent fallback to DD-generated dynasty/prospect values is a trust problem (it
makes the app the exact thing the "fully independent" promise says it isn't).

Today three deploy gates and one serving path keep DD wired as the live safety
net. When the ValuCast public snapshot fails its readiness gate, `app.py` silently
swaps the entire public board back to raw DD `dynasty_value`/`dynasty_rank`, and
the deploy/boot/freshness gates *require* the DD feed to be present and same-day
fresh even when every ValuCast-owned artifact is healthy.

After this plan: if the snapshot is ready, serve it; if it is structurally valid
but not ready (e.g. a governor blocker) and recent, serve it labeled stale; if
there is no servable ValuCast snapshot, refuse to promote the deploy (so the prior
healthy deploy stays live) or render an explicit unavailable state at runtime —
**never DD**. DD remains available as comparison-only/benchmark data (the daily DD
feed sync stays), just not as a public valuation source, and the deploy gates
validate ValuCast snapshot health directly instead of DD readiness.

## Current state

- `app.py:251-345` — store wiring, selection, and the boot guard:
  ```python
  legacy_dd_store = DDFeedStore(DD_FEED_PATH)                     # 251
  public_snapshot_store = PublicSnapshotStore(PUBLIC_SNAPSHOT_PATH) # 252
  valucast_buy_store = ValuCastBuyStore(VALUCAST_BUYS_PATH)        # 253

  def _select_dynasty_store(dd_candidate, snapshot_candidate, use_public_snapshot=None):  # 256
      enabled = (os.environ.get("VALUCAST_USE_PUBLIC_SNAPSHOT", "1") == "1"
                 if use_public_snapshot is None else bool(use_public_snapshot))
      if (enabled and snapshot_candidate.is_available
              and snapshot_candidate.ready_for_live_consumers):
          return snapshot_candidate, "valucast_public_snapshot"
      return dd_candidate, "dd_feed"                              # <-- the silent DD fallback

  def _select_buy_source(dd_candidate, buy_candidate, *, use_valucast_buys=None,
                         public_snapshot_active=None):            # 271
      ...
      if (enabled and snapshot_active and buy_candidate.is_available
              and buy_candidate.ready_for_live_consumers):
          return buy_candidate, "valucast_buys"
      return dd_candidate, "dd_feed"                              # <-- DD buys fallback

  dd_store, dynasty_data_source = _select_dynasty_store(legacy_dd_store, public_snapshot_store)  # 332
  prospect_pool = prospect_percentiles.build_pool(dd_store.get_all()) if dd_store.is_available else {}  # 335

  # boot guard (337-345):
  if os.environ.get("VALUCAST_REQUIRE_DD") == "1" and not legacy_dd_store.is_available:
      raise RuntimeError(f"DD feed required but unavailable: {DD_FEED_PATH}. ...")
  ```
  `PublicSnapshotStore` (web/public_snapshot_store.py:151-227) exposes
  `.is_available`, `.ready_for_live_consumers`, `.generated_at` (ISO date string),
  `.get_all()`, `.get_by_id()`, `.filter(...)`. A `PublicSnapshotStore` pointed at
  a nonexistent path loads nothing: `.is_available` is `False`, `.get_all()` is
  `[]` — i.e. it is already a usable "unavailable" null-object.

- `app.py:3040-3082` — readiness probe. `stores` includes the blocking DD gate:
  ```python
  stores = {
      "steamer": _store_ok("steamer"),
      "valucast": _store_ok("valucast"),
      "dd": legacy_dd_store.is_available,         # 3053  <-- DD blocks readiness
  }
  if ...VALUCAST_USE_PUBLIC_SNAPSHOT...:
      stores["public_snapshot_ready"] = (public_snapshot_store.is_available
                                         and public_snapshot_store.ready_for_live_consumers)
  ...
  ready = all(stores.values())                    # 3066
  ```

- `render.yaml:11-17` — production env:
  ```yaml
  envVars:
    - key: PYTHON_VERSION
      value: "3.12"
    - key: VALUCAST_REQUIRE_DD          # 14-15  <-- to remove
      value: "1"
    - key: VALUCAST_USE_PUBLIC_SNAPSHOT
      value: "1"
  ```
  `startCommand` uses `gunicorn ... --preload`, so a `RuntimeError` at import time
  fails the candidate deploy and Render keeps the prior healthy deploy live.

- `scripts/validate_public_data_freshness.py:11,94` — DD feed in the hard freshness gate:
  ```python
  DD_FEED = ROOT / "data" / "dd" / "dd_dynasty_feed.json"   # 11
  ...
  dated_artifacts = [
      (DD_FEED, "generated_at"),                            # 94  <-- to remove
      (VALUCAST_PROSPECT_INPUTS, "generated_at"),
      ...
  ]
  ```
  Any artifact whose `generated_at` != today fails the build (lines 124-135).

- Routes already degrade gracefully when the dynasty store is unavailable —
  these are the existing "explicit unavailable state" and must keep working:
  `app.py:493` (`if not dd_store.is_available:`), `:2769`, `:3415-3416`
  (`return "...graphic unavailable", 503`), `:3470-3471` (`"...card unavailable", 503`).
  Many routes read `dd_store` (the SELECTED store) — those are unaffected because
  `dd_store` remains a valid store object (snapshot or unavailable null-object).

- `legacy_dd_store` is only consumed at lines 332-333 (passed to `_select_*`), 341
  (boot guard), and 3053 (health). After this plan it must not back any served
  surface. The daily DD feed sync (`scripts/sync_dd_feed.py`, run in
  `.github/workflows/daily-public-data.yml`) STAYS — DD comparison data is allowed.

## Commands you will need

| Purpose | Command (run from repo root) | Expected |
|---------|------------------------------|----------|
| App-level tests | `python -m pytest -q tests/test_app.py` | all pass |
| Smoke tests | `python -m pytest -q tests/test_public_surfaces_smoke.py` | all pass |
| Refresh/workflow tests | `python -m pytest -q tests/test_public_data_refresh.py` | all pass |
| Freshness validator | `python scripts/validate_public_data_freshness.py` | exit 0 |
| Import the app | `python -c "import app; print(app.dynasty_data_source)"` | prints a ValuCast source, not `dd_feed` |
| Lint | `ruff check <changed files>` | exit 0 |
| Full suite (final) | `python -m pytest -q` | all pass |

## Scope

**In scope** (modify only these):
- `app.py` — `_select_dynasty_store`, `_select_buy_source`, the boot guard, `/health/ready`, and a stale-banner context flag (Steps 1-4)
- `render.yaml` — remove `VALUCAST_REQUIRE_DD` (Step 3)
- `scripts/validate_public_data_freshness.py` — drop the DD_FEED freshness row (Step 5)
- A dynasty/prospects template for the stale banner (Step 4 — identify via the route render; likely `templates/index.html` or a partial it includes)
- `tests/test_app.py`, `tests/test_public_data_refresh.py`, `tests/test_public_surfaces_smoke.py` — update to the new behavior

**Out of scope** (do NOT touch):
- `scripts/sync_dd_feed.py` and the DD sync step in `daily-public-data.yml` — DD
  comparison data stays.
- `DDFeedStore` class itself — keep it; it is still used to load the comparison feed.
- `scripts/build_public_dynasty_snapshot.py` / `prospects/rank_v1.py` — no changes
  to what the snapshot emits.
- The external-board panel / `source_ranks` — comparison-only display is kept.
- Anything Plan 001 owns (validators, governor check, ratchet).

## Git workflow

- Branch: `advisor/002-remove-dd-valuation-fallback`
- Order steps so the codebase is never in a "boot guard removed but no stale
  fallback" state: implement the stale/unavailable serving (Steps 1-2) BEFORE
  removing the boot guard (Step 3).
- Commit per step; terse imperative messages matching `git log`.
- Do NOT push or open a PR.

## Steps

### Step 1: Stop selecting DD; add stale-but-valid + unavailable serving

Rewrite `_select_dynasty_store` so it never returns the DD candidate. Add a
module constant `MAX_SNAPSHOT_STALE_DAYS = 7` (taste dial — the daily build means
a snapshot older than a few days signals a broken pipeline) and a `_within_stale_window`
helper that parses `snapshot_candidate.generated_at` (ISO date) and returns True
when it is within `MAX_SNAPSHOT_STALE_DAYS` of today. Target shape:

```python
def _select_dynasty_store(snapshot_candidate, use_public_snapshot=None):
    enabled = (os.environ.get("VALUCAST_USE_PUBLIC_SNAPSHOT", "1") == "1"
               if use_public_snapshot is None else bool(use_public_snapshot))
    if enabled and snapshot_candidate.is_available:
        if snapshot_candidate.ready_for_live_consumers:
            return snapshot_candidate, "valucast_public_snapshot"
        if _within_stale_window(snapshot_candidate.generated_at):
            return snapshot_candidate, "valucast_public_snapshot_stale"
    return _UNAVAILABLE_DYNASTY_STORE, "unavailable"
```

Create the unavailable null-object as a `PublicSnapshotStore` pointed at a path
that does not exist (it loads to `is_available=False`, `get_all()==[]`):
`_UNAVAILABLE_DYNASTY_STORE = PublicSnapshotStore(PUBLIC_SNAPSHOT_PATH.parent / "__never__.json")`
(or any guaranteed-absent path). Update the call site (line 332) to the new
signature: `dd_store, dynasty_data_source = _select_dynasty_store(public_snapshot_store)`.
`legacy_dd_store` is no longer passed here.

**Verify**: `python -c "import app; print(app.dynasty_data_source)"` prints
`valucast_public_snapshot` (or `_stale`), never `dd_feed`/`unavailable` on the
committed snapshot. STOP if it prints `unavailable` — that means the committed
snapshot isn't loading; investigate before continuing.

### Step 2: De-DD the buy-source fallback

In `_select_buy_source`, replace the final `return dd_candidate, "dd_feed"` so it
never serves DD. The buy fallback when ValuCast buys aren't ready should be an
explicit non-DD state. First inspect the call site
(`grep -n "_select_buy_source(" app.py`) to see what `dd_candidate` is bound to
and how the result is consumed (note `app.py:2814-2821`:
`if buy_data_source == "valucast_buys" and buy_store.is_available: ... elif dd_store.is_available: ...`).
Target: return `(_UNAVAILABLE_DYNASTY_STORE, "unavailable")` (or the ValuCast buy
candidate if structurally valid-but-stale, mirroring Step 1) instead of the DD
candidate, and confirm the consuming branch renders a no-buys/unavailable state
rather than DD-derived buys.

**STOP** if the buys consumer genuinely cannot render without DD-derived rows
without a larger change — report it and leave `_select_buy_source` for a follow-up
plan rather than half-removing it.

**Verify**: `python -m pytest -q tests/test_app.py` → all pass (update buy-source
tests to assert the fallback is `"unavailable"`/ValuCast, never `"dd_feed"`).

### Step 3: Replace the DD boot guard with a ValuCast-snapshot health guard; drop the env var

Replace the `VALUCAST_REQUIRE_DD` boot guard (app.py:337-345) with a guard keyed
on ValuCast servability — refuse to start (so `--preload` keeps the prior healthy
deploy) only when there is nothing ValuCast-owned to serve:

```python
# Refuse to promote a deploy with no servable ValuCast snapshot, so the prior
# healthy Render deploy stays live. DD is never a valuation fallback.
if os.environ.get("VALUCAST_USE_PUBLIC_SNAPSHOT", "1") == "1" and dynasty_data_source == "unavailable":
    raise RuntimeError(
        "No servable ValuCast snapshot (not ready and not stale-valid). Refusing to "
        "start so the prior healthy Render deploy stays live."
    )
```

Remove the `VALUCAST_REQUIRE_DD` env block from `render.yaml` (lines 14-15).

**Verify**: `python -c "import app"` succeeds (committed snapshot is servable).
`grep -rn "VALUCAST_REQUIRE_DD" app.py render.yaml tests/` returns only updated/removed
references.

### Step 4: Drop DD from `/health/ready`; surface a stale banner

In `/health/ready`, remove `"dd": legacy_dd_store.is_available` from the `stores`
dict that feeds `ready = all(...)`. Keep a DD diagnostic OUT of the gate — add it
to the response body as informational only, e.g.
`body["dd_comparison_feed"] = {"available": legacy_dd_store.is_available}` so the
object stays purposeful without blocking readiness. Readiness now = steamer +
valucast + public_snapshot_ready (+ valucast_buys_ready when enabled).

Surface the stale state to users: pass a flag into the dynasty/prospects render
context (find the route that renders the board; it already sets
`ctx["dd_available"]` near app.py:1973/2016) such as
`ctx["snapshot_stale"] = (dynasty_data_source == "valucast_public_snapshot_stale")`,
and add one labeled banner line in the template when true, e.g. "Showing the most
recent validated ValuCast snapshot (updated {date}) — today's refresh hasn't
published yet." Match the existing notice/banner styling; keep it to one
conditional block. Do NOT surface DD anywhere.

**Verify**: `python -m pytest -q tests/test_app.py tests/test_public_surfaces_smoke.py`
→ all pass (update the `/health/ready` test: `dd` no longer in the blocking
`stores`; ready is True on the committed fixtures).

### Step 5: Remove the DD feed from the hard freshness gate

In `scripts/validate_public_data_freshness.py`, remove `(DD_FEED, "generated_at")`
from `dated_artifacts` (line 94). If `DD_FEED` (line 11) becomes unused, remove the
constant too (let `ruff` confirm). DD is comparison-only; a stale DD feed must not
fail the ValuCast daily build.

**Verify**: `python scripts/validate_public_data_freshness.py` → exit 0 on
today's data. `ruff check scripts/validate_public_data_freshness.py` → exit 0.
Update `tests/test_public_data_refresh.py` if it asserts DD_FEED is in the
freshness set.

### Step 6: Full-suite gate

**Verify**: `python -m pytest -q` → all pass (2 pre-existing skips OK).
`ruff check` on every changed file → exit 0.

## Test plan

- `tests/test_app.py`:
  - `_select_dynasty_store`: snapshot ready → `valucast_public_snapshot`; snapshot
    available-but-not-ready and recent → `valucast_public_snapshot_stale`; snapshot
    unavailable (or stale beyond window) → returns the unavailable null-object and
    `"unavailable"`; **never** returns `"dd_feed"`.
  - `_select_buy_source`: never returns `"dd_feed"`.
  - `/health/ready`: `dd` is not in the blocking `stores`; `ready` True when
    ValuCast stores are healthy regardless of DD.
- `tests/test_public_surfaces_smoke.py`: the Plan-001 assertion (source in the
  ValuCast allowlist, never `dd_feed`) still passes with the `_stale` value.
- `tests/test_public_data_refresh.py`: freshness no longer requires the DD feed.
- Model new assertions on the existing tests in `tests/test_app.py` (find current
  `_select_dynasty_store`/`health_ready` tests with `grep -n "_select_dynasty_store\|health_ready\|dd_feed" tests/test_app.py`).

## Done criteria

ALL must hold:
- [ ] `python -m pytest -q` exits 0 (pre-existing skips allowed).
- [ ] `grep -n "dd_feed" app.py` shows no code path that RETURNS the DD store as a served source (string may remain only in comments/removed-test references).
- [ ] `grep -rn "VALUCAST_REQUIRE_DD" app.py render.yaml` returns nothing.
- [ ] `/health/ready` `ready` does not depend on `legacy_dd_store.is_available`.
- [ ] `(DD_FEED, "generated_at")` removed from `validate_public_data_freshness.py`.
- [ ] `python -c "import app; assert app.dynasty_data_source != 'dd_feed'"` succeeds.
- [ ] `ruff check` clean on changed files.
- [ ] Only in-scope files modified.
- [ ] `plans/README.md` status row updated.

## STOP conditions

Stop and report (do not improvise) if:
- "Current state" excerpts don't match live code (drift).
- The committed snapshot does not load (`dynasty_data_source == "unavailable"` on
  import) — the stale/unavailable path would mask a real problem; investigate first.
- The buys consumer cannot render without DD rows without a larger refactor
  (Step 2 STOP).
- Removing the DD health gate or boot guard breaks a test whose intent you cannot
  confirm is obsolete — report the test rather than rewriting its contract.
- You discover any OTHER runtime path that serves `legacy_dd_store` data to users
  (beyond the two selection functions) — report it; it must be de-DD'd too.

## Maintenance notes

- `MAX_SNAPSHOT_STALE_DAYS = 7` is a taste dial. If the daily build cadence
  changes, revisit it. Beyond the window the board goes unavailable rather than
  serving very old values.
- The stale banner is the user-visible half of "resilience without surrendering
  independence" — keep its copy honest (it must say ValuCast snapshot, with the
  date; never imply live freshness).
- `legacy_dd_store` now backs only comparison/diagnostics. If a later plan removes
  the DD comparison surfaces entirely, the store and the `/health` diagnostic can
  be deleted then.
- A reviewer should scrutinize: that no served path returns the DD store, that the
  boot guard still protects against promoting an empty deploy, and that the stale
  state is both reachable (test) and clearly labeled.
