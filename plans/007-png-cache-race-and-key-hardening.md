# Plan 007: PNG share-card cache — eliminate the thread race and close the unbounded-key bypass

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 72e68864..HEAD -- app.py web/category_registry.py`
> On drift in the app.py:95-230 region, re-read it before proceeding; on a
> mismatch with the excerpts, STOP.

## Status

- **Priority**: P1 (tiny effort, production 500s + a DoS-shaped hole)
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (do this BEFORE plan 005 — both touch app.py; this one is minutes)
- **Category**: bug + security
- **Planned at**: commit `72e68864`, 2026-07-08

## Why this matters

Share-card PNGs are ValuCast's growth surface (social unfurls). Two verified defects in the 7/2 PNG cache: (1) a thread race — the write path does `_PNG_CACHE[key] = ...` then `move_to_end(key)` as two statements under gunicorn `--threads 4`; a concurrent request can pop the key between them and `move_to_end` raises `KeyError` inside an `after_request` handler → a 500 for a request that had already rendered a valid PNG. Concurrent same-key fetches are exactly what unfurl bots do. (2) The cache key includes EVERY query param starting `w_`/`pt_` without validating the suffix, so `?w_junk1=1&w_junk2=1...` mints unlimited distinct keys → guaranteed cache miss → full ~1080×1350 Pillow render per request on the single 512MB worker, while evicting all 32 real entries. That's an unauthenticated CPU hammer, the exact thing the 7/2 fix was built to stop.

## Current state

All in `app.py` (region 95–230), verified at `72e68864`:

- `:101-102` — `_PNG_CACHE_MAX = 32`; `_PNG_CACHE: OrderedDict[tuple, tuple[bytes, dict[str, str]]] = OrderedDict()`. No `threading` import, no lock anywhere in app.py.
- `:136-143` — the allowlist + prefixes:
  ```python
  _PNG_CACHE_PARAMS = frozenset({
      "n", "limit", "pool", "position", "search", "callups",
      "mode", "source", "cats", "pcats", "rules", "split_rp", "display",
      "fit_cats", "preset", "rank_by",
      "teams", "budget", "roster", "pslots",
  })
  _PNG_CACHE_PARAM_PREFIXES = ("w_", "pt_")
  ```
- `:145-155` — `_png_cache_key()` folds in every arg where `k in _PNG_CACHE_PARAMS or k.startswith(_PNG_CACHE_PARAM_PREFIXES)`.
- `:160-172` — `_serve_cached_png` (before_request): `cached = _PNG_CACHE.pop(key, None)` then on hit `_PNG_CACHE[key] = cached` (the read side was already hardened; comment on :165 says so).
- `:176-196` — `_maybe_cache_png` (runs inside the `_security_headers` after_request at :227):
  ```python
  _PNG_CACHE[key] = (body, headers)
  _PNG_CACHE.move_to_end(key)
  while len(_PNG_CACHE) > _PNG_CACHE_MAX:
      _PNG_CACHE.popitem(last=False)
  ```
  `OrderedDict.move_to_end` on an absent key raises `KeyError`; `popitem` on a concurrently-emptied dict likewise.
- Valid `w_` suffixes come from the category registry: `web/category_registry.py` defines `HITTING_CATEGORIES` (:10) and `PITCHING_CATEGORIES` (:42), tuples of `CategorySpec(id=...)`. Valid `pt_` suffixes are the point-rule stat ids — find them in the same file (`POINTS_PRESETS` at :184 and/or wherever `pt_params` are parsed in `_build_context`, app.py ~:4046). The weights parse in `_build_context` (:4060-4068) does `weights[key[2:]] = w` — read how `build_config` (web/config_builder.py:30) consumes `weights` and `pt_params` to confirm the exact suffix vocabulary, INCLUDING any split-RP variants (e.g. a `w_K_SP`-style id) if they exist.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| App tests | `python -m pytest -q tests/test_app.py tests/test_positional_share_card.py` | all pass |
| Full suite (final) | `python -m pytest -q` | all pass; then `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json` |

## Scope

**In scope**: `app.py` (the :95-230 cache block + a `threading` import), `tests/test_app.py` (extend).

**Out of scope**: every PNG RENDERER (nothing about how cards draw changes); `_maybe_gzip`; the `_PNG_CACHE_PARAMS` allowlist membership for NON-prefix params (its comment documents an adversarial review — leave it); plan 005's caches.

## Git workflow

- Work on `master` locally, do NOT push. Stage explicitly. Commit style: `Fix PNG cache thread race; validate w_/pt_ cache-key suffixes`.

## Steps

### Step 1: Make cache mutation race-free

Add `import threading` and `_PNG_CACHE_LOCK = threading.Lock()` next to the cache. In `_maybe_cache_png`, wrap the store+evict block in the lock and drop the two-statement pattern:
```python
with _PNG_CACHE_LOCK:
    _PNG_CACHE.pop(key, None)
    _PNG_CACHE[key] = (body, headers)   # fresh insert is always last: LRU preserved, no absent-key call
    while len(_PNG_CACHE) > _PNG_CACHE_MAX:
        _PNG_CACHE.popitem(last=False)
```
In `_serve_cached_png`, wrap the pop + re-insert hit path in the same lock (keep the existing pop-or-None shape). The lock covers only dict ops on already-built bytes — no render work ever happens under it.

**Verify**: `python -m pytest -q tests/test_app.py -k "png or cache"` → all pass.

### Step 2: Validate prefix-param suffixes in the cache key

Build a module-level frozenset of legitimate prefixed keys from the registry, e.g.:
```python
from web.category_registry import HITTING_CATEGORIES, PITCHING_CATEGORIES
_PNG_CACHE_PREFIXED_KEYS = frozenset(
    {f"w_{c.id}" for c in (*HITTING_CATEGORIES, *PITCHING_CATEGORIES)}
    | {f"pt_{<stat id>}" for <stat id> in <the point-rule stat vocabulary>}
)
```
— fill the `pt_` half from what `build_config` actually accepts (Step 0 of your work: read `web/config_builder.py:30` and the `pt_params` collection at app.py:4046; if split-RP weight ids exist, include them). Then in `_png_cache_key`, replace `k.startswith(_PNG_CACHE_PARAM_PREFIXES)` with `k in _PNG_CACHE_PREFIXED_KEYS`. Unknown `w_junk` params now collapse to the canonical key — same behavior unknown non-prefix params already get. Update the comment block above `_PNG_CACHE_PARAMS` (it narrates this exact threat model — extend it, don't contradict it).

CRITICAL correctness constraint (from that comment): the derived set must cover ALL render-affecting prefix params, or two legitimately different cards collapse to one key and users get the WRONG image. If the renderer reads any `w_`/`pt_` param whose suffix is NOT derivable from the registry, STOP and report.

**Verify**: `python -m pytest -q tests/test_app.py` → all pass, plus your new tests below.

## Test plan

Extend `tests/test_app.py` (find the existing PNG-cache tests from the 7/2 fix and model after them):
1. Junk-prefix collapse: with `TESTING` disabled for the cache path (mirror how existing cache tests arrange this), request the same .png with and without `?w_zzz=1&w_zzz2=3` → same cache key (assert via `_png_cache_key()` in a request context) — 2 requests, second is a HIT.
2. Legit weight changes the key: `?w_HR=2` vs `?w_HR=3` → different keys.
3. Race regression: concurrency in a unit test is flaky — instead assert the new invariant directly: `_maybe_cache_png` path never calls `move_to_end` (grep-level assertion is fine in Done criteria) and eviction under a pre-emptied dict doesn't raise (call the store block with `_PNG_CACHE` cleared by the test between operations if the existing test structure allows; otherwise skip and rely on the lock + shape).

## Done criteria

- [ ] `python -m pytest -q` exits 0 (byproduct file restored after).
- [ ] `grep -n "move_to_end" app.py` → no hits in the PNG cache block.
- [ ] `grep -n "_PNG_CACHE_LOCK" app.py` → lock defined and used in BOTH handlers.
- [ ] `grep -n "_PNG_CACHE_PARAM_PREFIXES" app.py` → no longer used in `_png_cache_key` (constant may be deleted if nothing else reads it).
- [ ] New tests from the test plan exist and pass.
- [ ] `git status`: only app.py + tests/test_app.py.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- The renderer reads a `w_`/`pt_` param whose suffix isn't in the registry-derived vocabulary (key-collapse would serve wrong images).
- The :95-230 block doesn't match the excerpts (plan 005 or other work landed first — re-read, reconcile, and if the race was already fixed differently, report instead of re-fixing).

## Maintenance notes

- If a new league-config category id is ever added to `web/category_registry.py`, `_PNG_CACHE_PREFIXED_KEYS` picks it up automatically (it derives from the registry) — that's the point of deriving instead of hand-listing.
- Reviewer scrutiny: confirm no code path renders a PNG while holding `_PNG_CACHE_LOCK`.
