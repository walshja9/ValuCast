# Share Graphic QR Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove QR codes from all ValuCast share graphics without changing their data or routes.

**Architecture:** Delete the shared QR renderer and every call site. Preserve the existing footer URL and validate the deletion with one source contract plus existing PNG route tests.

**Tech Stack:** Python, Flask, Pillow, pytest

## Global Constraints

- No model, rank, value, data, route, or workflow changes.
- Do not replace the QR with another element.
- Keep `valucast.app` visible in existing footers.

---

### Task 1: Remove the QR layer

**Files:**
- Modify: `app.py`
- Modify: `pyproject.toml`
- Modify: `requirements.txt`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: existing PNG renderers and footer helper.
- Produces: the same PNG routes without embedded QR panels.

- [x] **Step 1: Write the failing contract test**

Add `test_share_graphics_do_not_embed_qr_codes` to `tests/test_app.py`; assert that `app.py` contains no `_graphic_qr`, `_graphic_place_qr`, `qr_url`, or `_qrcode`, and that `pyproject.toml` contains no `qrcode` dependency.

- [x] **Step 2: Run the contract test and confirm it fails**

Run: `python -m pytest tests/test_app.py -k "share_graphics_do_not_embed_qr_codes" -q`

Expected: FAIL because the QR renderer and dependency still exist.

- [x] **Step 3: Delete the QR implementation**

Remove the optional QR import, the two QR helpers, all four renderer call sites, the prospect-board `qr_url` parameter, the player-card `qr_extra` canvas extension, and the three obsolete QR tests. Remove `qrcode>=7.4,<9.0` from `pyproject.toml`.

- [x] **Step 4: Run focused verification**

Run: `python -m pytest tests/test_app.py -q`

Expected: PASS.

- [x] **Step 5: Render representative graphics**

Render the prospect board, player card, farm rankings, and Forward Ledger PNGs through their existing tests or Flask test client; verify each response is HTTP 200 and starts with the PNG signature.

- [x] **Step 6: Commit**

Run: `git add app.py pyproject.toml tests/test_app.py docs/superpowers/specs/2026-08-03-share-qr-removal-design.md docs/superpowers/plans/2026-08-03-share-qr-removal.md && git commit -m "fix: remove QR codes from share graphics"`
