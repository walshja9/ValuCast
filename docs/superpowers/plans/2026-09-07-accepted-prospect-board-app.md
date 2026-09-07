# Accepted combined prospect board in ValuCast

> **For agentic workers:** Use subagent-driven-development to implement and independently review this scoped app change. Work only in this isolated public-app checkout.

**Goal:** The existing Prospects route displays the entire accepted v2.6.6 board, with matching search, role filters, detail and exact download.

**Architecture:** Read the already exported CSV and metadata as a small immutable app dataset. Select it through deployment configuration only after real board acceptance. Keep the protected experiment, replay and exporter outside HTTP requests.

**Tech Stack:** Existing Flask/Jinja/HTMX/CSS, Python standard library and pytest. No dependency additions.

## Constraints and implementation choices

- Base is c315ee3100c355edbd92561e3f289f2d7bad48e0 in the independent public clone. This work does not change the running R5 checkout or the refresh-recovery PR.
- This is authorized local app implementation. Synthetic tests are engineering evidence only. No real accepted files, approval hash, production configuration, scientific execution or deployment is created here.
- Reuse the existing shell, CSS, native GET forms, HTMX behavior and `web.search_fold.fold`. A dedicated internal data representation is required because surplus is incompatible with dynasty value, dollars and public-v1 probabilities.
- Configuration: `VALUCAST_PROSPECT_BOARD_DIR` plus `VALUCAST_PROSPECT_BOARD_METADATA_SHA256`. Neither set preserves the current source; either set selects the new source and both must then validate. Invalid selected data produces an explicit unavailable response, never a v1 fallback under the v266 identity.
- Load and verify at startup, retaining the verified CSV bytes in memory for downloads. A deployment changes the accepted artifact/configuration; HTTP requests never observe a half-replaced pair.
- Exact exporter header: `Rank,MLBAM ID,Player,Role,Y12 Surplus,Y24 Surplus,Evidence Confidence`. UTF-8 BOM, CSV CRLF. Render supplied escaped names safely without stripping a legitimate apostrophe.
- Metadata has the exporter's exact 12 keys, schema `valucast_prospect_v2_6_6_board_export_v1`, model `v2.6.6`, decision date `2026-08-26T12:00:00Z`, terminal/registration/reproduction/prediction/public-snapshot bindings, CSV SHA/bytes/count/role counts. The separately pinned metadata hash is the acceptance binding; self-consistency alone is not acceptance.
- Verify canonical metadata bytes, exact key/type sets and SHA formats; CSV digest/size/header/row widths; positive unique numeric MLBAM IDs; finite surplus; contiguous full ranks; roles/confidence; name presence; counts and order `(-Y24,-Y12,MLBAM)`. Do not import the protected exporter/builder merely to parse this public contract.
- Full board is the default, with no 200-row cap. Filtering keeps original sealed ranks. Hitter/pitcher filters each include a two-way asset once; two-way has its own filter.
- Board and detail show the same surplus values and confidence. No dollar conversions, custom-league reranking, extra pitcher adjustment, old probability/interval/tier, or old rank history appears in this view.
- Display the fixed forecast date prominently. Daily factual snapshot date is separate if shown. Do not use the shared old stale banner or footer's dynasty/daily-commit claims as v266 provenance.
- Download serves the exact accepted full CSV, clearly labeled full-board download even after filtering. Do not regenerate a filtered file and present it as the accepted artifact.
- Existing redraft/dynasty/trade and factual-context products retain their own source. Direct prospect detail/compare and old prospect graphic URLs must not silently answer with v1 rankings after selecting v266. Use the new data for supported routes; explicitly mark unsupported old graphic routes unavailable with a board link, without exposing them as active controls.
- Health reports selected prospect source, availability and fixed decision date, and fails readiness if the selected board is unavailable. It must not borrow public-v1 quality/freshness flags as scientific acceptance.

## Task 1: Integrity-checked public dataset

**Files:** Create `web/accepted_prospect_board.py` and `tests/test_accepted_prospect_board.py`.

- [ ] Write failing tests using a small synthetic BOM/CRLF export with hitter, pitcher and two-way rows, equal-score identity tie-breaking, accented and HTML-sensitive names. Pin its canonical metadata hash explicitly in the test.
- [ ] Implement a small immutable row/dataset representation and `load_board(directory, expected_metadata_sha256)` using stdlib only. Store the exact verified CSV bytes and source bindings. Raise a single clear dataset-validation error for unavailable/invalid input, retaining useful internal cause for logging.
- [ ] Add meaningful rejection cases for wrong pin, tampered CSV, duplicate IDs, nonfinite values, incorrect count/order/role, malformed/duplicate-key metadata and missing half of the configured pair. No real acceptance record is written.
- [ ] Run `python -B -m pytest -q tests/test_accepted_prospect_board.py`; preserve witnessed RED and GREEN output in ignored private evidence.

## Task 2: One board through the existing routes

**Files:** Modify `app.py`, shared navigation/footer only where needed; add one board template, its table partial and one reusable detail presentation. Add route checks to the same focused test file. Keep helpers in the new module if this avoids expanding the large app file.

- [ ] Trace all existing callers of prospect context, export, detail, compare and graphic routes before wiring selection.
- [ ] Add startup selection and a small request context built from the immutable dataset. Reuse `fold` for search and standard query encoding for HX history.
- [ ] Route `/?mode=prospects`, `/rankings?mode=prospects`, `/player/<id>?mode=prospects`, `/compare?mode=prospects` and `/export?mode=prospects` to the selected dataset. Preserve direct navigation and HTMX error handling. IDs are explicit MLBAM-based v266 IDs; never guess or fall back to unrelated redraft IDs.
- [ ] Render accessible labeled search/role controls and a submit button, so the page works without JavaScript. Add HTMX enhancement with `hx-history="false"`. Native links provide direct detail and exact download; reuse existing responsive table classes.
- [ ] Correct shared provenance for this selected view, and selected-source health. Guard unsupported legacy prospect graphics from returning a contradictory board.
- [ ] Test full population beyond 200, filtering/rank holes/two-way membership, direct and HX detail, export-byte parity, missing/tampered selected data, health, and no invocation of legacy value/reranking paths. Confirm legacy behavior when configuration is absent.
- [ ] Run the focused file plus existing public board, app, smoke and customization checks; run scoped Ruff, compile and diff hygiene. Do not claim scientific/model acceptance from these tests.

## Task 3: Review and real delivery

- [ ] Independently review changed source and complete route coverage.
- [ ] Use a visibly synthetic test fixture in a separate loopback preview only for browser QA; inspect desktop/mobile search, role filters, detail, full count, download and error behavior. Never display it as a real qualified prospect board.
- [ ] After real E/T/reproduction/board acceptance exists, bind exact accepted files/configuration and repeat real-data parity and browser checks. That later action remains pending; do not invent a hash now.
- [ ] Keep the fixed-vintage model distinct from daily public factual refresh. A future daily model inference contract is separate work, not a relabeling of August 26 predictions.
