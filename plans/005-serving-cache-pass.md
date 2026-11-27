# Plan 005: Stop recomputing the world per request — generation-keyed caches across the serving layer

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 72e68864..HEAD -- app.py`
> If app.py changed since this plan was written, compare every "Current state"
> excerpt against the live code before proceeding; on a mismatch, treat it as
> a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (touches the hottest routes; mitigated by byte-parity verification)
- **Depends on**: none (but coordinate with 007 — both touch app.py; do 007 first, it's tiny)
- **Category**: perf
- **Planned at**: commit `72e68864`, 2026-07-08

## Why this matters

The app runs on a single GIL-bound gunicorn worker (render.yaml: `--workers 1 --threads 4`, 512MB). The landing route and every filter/search keystroke re-run the FULL valuation engine over ~10,600 players even though the expensive result depends only on (projection source, league config) — not on the filter args. The home page also re-parses a 127KB movers JSON on every render; /map builds its 2,700-row payload twice per view; every dynasty request re-sorts and re-tiers the full universe; and a 10MB prospect model is parsed at import on every worker boot (workers recycle every ~300 requests). All five are the same idea: cache keyed on artifact generation. The repo already has the pattern three times (`_load_artifact` mtime cache, `_DYN_Z_CACHE` generation cache, `lru_cache` on `_custom_dynasty_values`) — this plan makes the rest of app.py use it. Data changes at most daily; none of these caches can go stale within a process, because every key includes the store's generation stamp.

## Current state

All in `app.py` (8,654 lines). Excerpts verified at `72e68864`:

- **A. Redraft board** — `_build_context` (route-args → full board context). At :4079:
  ```python
  all_results = _redraft_value_players(_valuation_players(active_store=active), config)
  all_results.sort(key=lambda r: r.total_value, reverse=True)
  redraft_value_scale = _redraft_value_scale(all_results)
  ...
  metadata_pool = all_results[:200]
  ```
  `active = _active_store(args.get("source", ""))` (~:4042). `config` is built at :4071 from `(mode, cats, pcats, rules_str, pt_params, split_rp, weights)` — all parsed from args above it (weights parse loop at :4060-4068). Pool/position/search filtering happens AFTER, at :4086-4118, and never mutates `all_results` (it rebinds `results` to new filtered lists). Downstream metadata at :4153-4156: `_compute_position_ranks(metadata_pool)`, `_compute_dollar_values(metadata_pool)`, `_compute_tiers(metadata_pool)`, and `overall_ranks` from `all_results` at :4160. The sub-threshold search branch (:4110-4117) runs a small on-demand valuation — leave it uncached.
  Callers: `index()` (:4269 area) and `rankings()` (:4321 area) call `_build_context(request.args)` per request. `_valuation_players` (:487) has no cache.
- **B. Artifact loaders that bypass the mtime cache** — `_load_artifact` (:4480) is a correct mtime-keyed cache over `_ARTIFACT_CACHE`. But:
  - `_load_movers_payload` (:6734) — bare `json.loads(path.read_text())`, returns `{}` on error/non-dict. Called by `_front_door_digest` (:4205), which runs on EVERY branch of `index()` (:4261/4267/4271), and by the movers page.
  - `_load_receipts_payload` (:6907) — same shape.
  - `_load_scorecard_payload` (:6936) — same, returns `None` on error/non-dict, reads `_LEDGER_SCORECARD_PATH`.
  - `_native_prospect_movers_strip` (:530-542) — reads the same movers file uncached AGAIN via its own `json.loads(Path(path).read_text())`.
- **C. /map** — `_value_map_players(rows)` (:6456) loops every dd_store row building dicts; `value_map()` (:6487) calls it just to take `len(players)`; `/api/value-map-players` (:6501) rebuilds it per fetch; the share-card route builds it a third time.
- **D. Dynasty metadata** — `_dynasty_metadata(settings, value_of=None)` (:862-870):
  ```python
  value_of = value_of or (lambda r: r.dynasty_value)
  all_rows = sorted(dd_store.get_all(), key=value_of, reverse=True)
  return (
      _compute_dynasty_dollars(all_rows, settings, value_of=value_of),
      _dynasty_tiers_for(all_rows, settings, value_of=value_of),
  )
  ```
  Called from `_build_dynasty_context` at :3782 with a preset-dependent `value_of` lambda on every dynasty request. NOTE: `value_of` is a closure — it cannot be a cache key directly; the cache key must use whatever preset/rank_by identifier DETERMINED it (read `_build_dynasty_context` upward from :3782 to find that variable).
- **E. Eager 10MB model** — at :583:
  ```python
  _UNIVERSAL_PROSPECT_PROFILES, _UNIVERSAL_PROSPECT_AVAILABLE = (
      _load_universal_prospect_profiles(UNIVERSAL_PROSPECT_MODEL_PATH)
  )
  ```
  Consumers: `_custom_prospect_ranks` (:1187, itself lru_cache'd) does `list(_UNIVERSAL_PROSPECT_PROFILES.values())`; gate at :1351 `if custom_active and _UNIVERSAL_PROSPECT_AVAILABLE:`. Grep for ALL uses of both names before changing.
- **Exemplar to imitate** — `_dynasty_match_maps` (:924-935): module dict cache keyed on `dd_store.generated_at`:
  ```python
  key = dd_store.generated_at
  if _DYN_Z_CACHE.get("key") == key:
      return _DYN_Z_CACHE["map"], _DYN_Z_CACHE["stats"]
  ```

Convention notes: caches in this file are module-level dicts or `functools.lru_cache`; comments explain WHY a key part exists (see the `_PNG_CACHE_PARAMS` comment block for tone). Thread-safety bar: worst case under `--threads 4` must be duplicate computation, never an exception or a torn read (assign the fully-built value in ONE statement, like `_DYN_Z_CACHE` does... note `_DYN_Z_CACHE` itself sets `key` before payload — do NOT copy that ordering; build a tuple/dict fully, then assign a single reference).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| App tests | `python -m pytest -q tests/test_app.py tests/test_app_source.py` | all pass |
| Full suite (final) | `python -m pytest -q` | all pass; then `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json` |
| Byte-parity check | script in Step 6 | identical bytes for repeated + cross-filter requests |

## Scope

**In scope**: `app.py`; `tests/test_app.py` (extend).

**Out of scope** (do NOT touch):
- The PNG byte-cache block (app.py:95-230) — that's plan 007.
- `_build_dynasty_context`'s VALUE computation, `_dynasty_match_maps`, `_custom_dynasty_values` — already cached.
- The sub-threshold search valuation branch (:4110-4117) — per-query by design.
- `prospects/`, `web/`, templates — nothing outside app.py needs to change.
- Response shapes, template context keys — this plan changes WHEN things compute, never WHAT.

## Git workflow

- Work on `master` locally, do NOT push (Render auto-deploys master). Stage files explicitly; never `git add -A`.
- Commit style: `Cache the redraft board bundle per (source, config) generation` — one commit per lettered step is fine.

## Steps

### Step 1: Extract and cache the redraft board bundle (A)

Extract everything in `_build_context` that depends only on `(active store, config)` — `all_results` (sorted), `redraft_value_scale`, `metadata_pool`, `position_ranks`, `dollar_values`, `tiers`, `overall_ranks` — into a helper, and cache it with a small bounded LRU:

```python
_REDRAFT_BUNDLE_CACHE: OrderedDict[tuple, dict] = OrderedDict()
_REDRAFT_BUNDLE_MAX = 16  # weights/pt params are user input -> unbounded key space, must bound

def _redraft_board_bundle(source_name, generation, mode, cats_t, pcats_t, rules_str, pt_t, split_rp, weights_t):
    key = (source_name, generation, mode, cats_t, pcats_t, rules_str, pt_t, split_rp, weights_t)
    hit = _REDRAFT_BUNDLE_CACHE.get(key)
    if hit is not None:
        return hit
    ... build config + everything listed above ...
    bundle = {...}          # fully built first
    _REDRAFT_BUNDLE_CACHE[key] = bundle   # single-reference assign
    while len(_REDRAFT_BUNDLE_CACHE) > _REDRAFT_BUNDLE_MAX:
        try:
            _REDRAFT_BUNDLE_CACHE.popitem(last=False)
        except KeyError:
            break
    return bundle
```

Key parts: `source_name` = the resolved source string (default `"steamer"`), `generation` = the active store's `as_of`. Tuple-ize cats/pcats/pt_params/weights as `tuple(...)` / `tuple(sorted(dict.items()))`. `_build_context` then consumes the bundle and keeps only arg parsing + filtering + display assembly. Treat every cached object as immutable downstream — if you find ANY in-place mutation of `all_results`, `metadata_pool`, or the three metadata dicts after the extraction point, that's a STOP condition.

**Verify**: `python -m pytest -q tests/test_app.py tests/test_app_source.py` → all pass.

### Step 2: Route the four bare loaders through `_load_artifact` (B)

`_load_movers_payload` / `_load_receipts_payload` → `payload = _load_artifact(path); return payload if isinstance(payload, dict) else {}`. `_load_scorecard_payload` → same with `None` fallback. `_native_prospect_movers_strip` → read via `_load_artifact(Path(path))` keeping its current empty-list fallbacks. Note `_load_artifact` takes a `Path` — coerce str args.

**Verify**: `python -m pytest -q tests/test_app.py` → all pass (movers/receipts/gaps page tests included).

### Step 3: Memoize the value-map payload (C)

Module cache keyed on `dd_store.generated_at` (mirror `_DYN_Z_CACHE`, but assign one fully-built tuple). `value_map()`, `/api/value-map-players`, and the map share-card route all read through it. Keep the `dd_store.is_available` guard.

**Verify**: `python -m pytest -q tests/test_app.py -k "map"` → all pass (if no map tests exist, add one: GET /api/value-map-players twice, assert identical JSON and status 200).

### Step 4: Cache `_dynasty_metadata` per (generation, settings, preset) (D)

Find the variable in `_build_dynasty_context` that determines `value_of` (the preset / rank_by identifier). Cache key = `(dd_store.generated_at, settings-signature, that identifier)`. `settings` — find its class; if it has no stable signature, build one from its constructor fields (`settings.summary()` is acceptable if deterministic). Bounded OrderedDict LRU like Step 1 (max ~16). If you cannot find a stable identifier that fully determines `value_of`, STOP and report — do not key on `str(value_of)`.

**Verify**: `python -m pytest -q tests/test_app.py -k "dynasty"` → all pass.

### Step 5: Lazy-load the universal prospect model (E)

Replace the module-level parse with:
```python
@functools.cache
def _universal_prospect_profiles_cached():
    return _load_universal_prospect_profiles(UNIVERSAL_PROSPECT_MODEL_PATH)
```
`_UNIVERSAL_PROSPECT_AVAILABLE` becomes a path-existence check (or a lazy property) so the :1351 gate works without parsing 10MB. Update ALL readers of both names (grep first: `grep -n "_UNIVERSAL_PROSPECT_PROFILES\|_UNIVERSAL_PROSPECT_AVAILABLE" app.py tests/ -r`). Note `functools.cache` is thread-safe for this purpose (worst case duplicate parse).

**Verify**: `python -c "import time; t=time.time(); import app; print(round(time.time()-t,2))"` → import time drops vs. pre-change (record both numbers). `python -m pytest -q tests/test_app.py` → all pass.

### Step 6: Byte-parity + full-suite gate

Byte-parity harness (run it BEFORE your first change to capture goldens, and after):
```python
# scratch script, do not commit
import app
c = app.app.test_client()
urls = ["/", "/?search=judge", "/?pool=pitcher&cats=R,HR", "/rankings?mode=categories",
        "/?mode=dd_dynasty", "/map", "/api/value-map-players", "/movers", "/gaps"]
for u in urls:
    r1 = c.get(u); r2 = c.get(u)
    assert r1.status_code == r2.status_code
    assert r1.data == r2.data, u
print("parity ok")
```
Golden comparison: for each url, the response bytes AFTER your changes must equal the bytes BEFORE (same data files, so any diff = you changed behavior, not just speed). Exception: if a template renders a timestamp of "now" anywhere, exclude that url and say so.

**Verify**: parity script passes pre-vs-post; `python -m pytest -q` all green; restore the pytest byproduct file.

## Test plan

- Extend `tests/test_app.py`: (1) two identical GETs to `/` return identical bytes; (2) a filtered GET (`/?pool=pitcher`) returns the same players as filtering the unfiltered response would (already implicitly covered if existing board tests pass — then skip); (3) `/api/value-map-players` stable across calls.
- Cache-correctness test: monkeypatch the store's `as_of`/`generated_at` to a new value and assert the bundle/map caches MISS (recompute happens). Model after whatever existing test manipulates `dd_store` state.
- Full suite green.

## Done criteria

- [ ] `python -m pytest -q` exits 0.
- [ ] Byte-parity harness passes pre-vs-post on all listed URLs.
- [ ] `grep -c "read_text" app.py` count for the four loader functions is 0 (they go through `_load_artifact`).
- [ ] Import-time measurement recorded in the commit message (Step 5).
- [ ] `git status`: only app.py + tests/test_app.py modified; pytest byproduct restored.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- Any in-scope excerpt doesn't match live code (drift).
- You find downstream code mutating `all_results`/`metadata_pool`/metadata dicts after extraction (cached-object aliasing — needs a design call, not improvisation).
- No stable preset identifier exists for Step 4's `value_of`.
- Byte-parity fails on any URL and you cannot attribute it to a "now" timestamp.

## Maintenance notes

- Every new cache key includes the store generation — if a new projection source or a second daily refresh is ever added, the keys already handle it; what they do NOT handle is mid-day artifact edits with an unchanged `generated_at` (don't do those; the daily build always restamps).
- If a future feature adds a render-affecting query param to the board, it must join the Step 1 cache key — same rule as the `_PNG_CACHE_PARAMS` allowlist comment.
- Reviewer scrutiny: the single-reference assignment discipline in every new cache (no key-before-payload ordering), and the boundedness of both new LRUs.
- Deferred: `_DYN_Z_CACHE`'s own key-before-payload ordering is a pre-existing LOW finding (survivor #30 in the 7/8 audit) — fix it here only if trivial while in the area; do not restructure it.
