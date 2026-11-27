# Sol Audit Brief #4 — Public Attack Surface — 2026-07-13

You are Sol, running the fourth independent, adversarial, **read-only** audit of
the ValuCast codebase. This one is different in kind: not "is the math right"
but **"what can a stranger do to us."** valucast.app is a public, unauthenticated
Flask app with growing social attention and a premium waitlist forming. Nobody —
internal review or external audit — has ever run a hostile-input/abuse/load pass
over it. You are auditing OUR OWN app, defensively, with the owner's authorization.

## Ground rules

- **Read-only on the repo.** No edits, no `git add`/`stash`/commit, no writes
  outside your scratch space, NEVER run pytest, never run build scripts that
  write artifacts.
- **Local verification only.** You MAY exercise hostile inputs against a LOCAL
  Flask test client (`app.test_client()`, TESTING=True) — single requests to
  demonstrate behavior. You MUST NOT send any traffic to valucast.app
  production, no load tests anywhere, no sustained request loops even locally.
  For cost findings, reason from code + one timed local request; never
  demonstrate amplification by actually amplifying.
- **Findings format:** one-sentence defect + `file:line` + a concrete abuse
  scenario (request(s) → bad outcome) + severity. CRITICAL = an unauthenticated
  stranger can corrupt served data, read something private, or knock the site
  over with trivial effort. MAJOR = meaningful cost amplification, cache
  corruption, or injection with visible effect. MINOR = hardening gaps.
  Unproven = HYPOTHESIS + the exact local check that would confirm.
- **Report cleared areas** per target.

## Target 1: hostile input on every route

Enumerate every `@app.route` in app.py (and any blueprints). For each, attack
the parameters a stranger controls:

1. **Type/shape confusion:** ids that aren't ids, list params with thousands of
   entries, negative/NaN/1e308 numerics in league-settings bounds
   (`web/league_settings.py` `_BOUNDS`), repeated params, null bytes, huge
   strings. Which route 500s, hangs, or returns another player's data?
2. **Injection into non-HTML sinks.** Jinja autoescapes templates, so hunt the
   OTHER sinks: user input reaching PNG text rendering (share cards echo
   player/trade params), `build_share_preview_html`, response HEADERS
   (Content-Disposition filenames, HX-Replace-Url built from user params —
   header injection/CRLF), og: meta URLs built with urlencode, and any place a
   search string is echoed into an attribute or inline script context.
3. **Path-shaped inputs:** any param that reaches a filesystem read
   (player_id → file? export formats?). The Sleeper sibling repo had a
   path-traversal class; check this one has none.
4. **The /league-import route** (line ~4656): it accepts external league
   identifiers — what does it fetch, store, or echo, and can a hostile league
   payload reach other users' views?

## Target 2: cost amplification (the "viral tweet" problem)

Render runs this with ~2 workers and a ~30s request ceiling. One popular post
can send thousands of strangers at any URL. Rank the damage:

1. **Per-request compute map.** Which public GETs run the full valuation
   engine or Pillow image generation per request, and which are cached?
   Produce a top-5 "most expensive uncached GET" list with the code path.
2. **Cache-key cardinality.** Every `@lru_cache`/manual cache keyed on
   user-controlled values (e.g. `_custom_dynasty_values(cats, pcats, teams,
   budget)`, maxsize=16; the PNG caches; rankings context caches): can a
   stranger iterating parameter permutations evict the whole cache
   continuously (thrash = every real user gets cold-path latency) or grow
   memory unboundedly? For each cache: keyspace cardinality under URL control,
   maxsize, and cost of one miss.
3. **Image endpoints as CPU bombs.** share-card.png/svg routes: per-request
   Pillow cost, whether results are cached, whether cache keys include ALL
   output-affecting params, and the worst-case param that maximizes render
   cost (6v6 trade with maximal notes? longest names?).
4. **No-limit surfaces:** anything that reflects unbounded output size
   (export rows, compare lists, search results) — response-size ceilings?

## Target 3: cache correctness under adversarial keys

The known pattern (plan 007/022, do not re-report): PNG cache keys must
include `give`/`get` — a key that omits an output-affecting param lets one
user's render poison another's. Generalize: for EVERY cached response
(HTML fragments, PNGs, JSON payloads), diff the cache key's params against the
set of params that change the output. Any gap = one stranger's crafted request
poisons what the next visitor sees. Also check cache keys are canonicalized
(param order, case, duplicate params) so equivalent requests share entries and
non-equivalent ones never do.

## Target 4: CI/CD and secrets hygiene

1. `.github/workflows/*.yml` (daily-public-data, deploy, prospect-shadow,
   roster-pulse): `permissions:` blocks (or the default token scope), triggers
   (any `pull_request_target` or workflow_run risk), whether a FORKED PR can
   execute anything with write perms or secret access, and whether any step
   can print a secret into logs (set -x, curl -v, echo of env).
2. Secrets inventory: what the workflows/app expect (Telegram vars are known
   empty — don't re-report), what happens when each is absent, and whether any
   committed file carries a live credential (sweep data/ and scripts/ for
   token-shaped strings — report a HYPOTHESIS with the file, never print the
   value itself).
3. Flask session/secret usage: is there a session/secret at all; if
   FLASK_SECRET is unset does anything signed (cookies, CSRF) silently run
   with a default?
4. Debug/dev leftovers: any route or config that enables debug, exposes
   /console, or reflects stack traces to strangers in production mode.

## Known issues — do NOT re-report

1. `_PNG_CACHE_PARAMS` give/get coverage on the trade card — tested, shipped
   (plan 022 + 7/12 batch). Generalizing the CLASS to other caches (Target 3)
   is in scope; the trade card instance is not.
2. CSP/gzip/HX-request guards shipped 7/1 (F-batch). Verify coverage gaps if
   you find them, but the headers existing is known.
3. Telegram secrets empty in repo settings.
4. Named per-source ranks on the player card — open product ruling.
5. Trade tool one-sided/duplicate input handling — fixed 7/12.
6. All math/scoring/build-chain findings from audits #1-#3.
7. `data/dd/dd_dynasty_feed.json` untracked in the worktree — expected.

## Deliverable

One report, findings ranked CRITICAL → MINOR, cleared areas per target.
Top-flags: **EXPLOITABLE** for anything an unauthenticated stranger can do
RIGHT NOW that corrupts served data or reads something private, and
**COST BOMB** for the cheapest request-to-damage amplification you find.
For every EXPLOITABLE finding include the one-line local repro (test client
call) so verification is immediate.
