# Prospect Player-Card / Share-Graphic Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing prospect player PNG carry every decision-relevant field from the prospect HTML card while preserving one shared data context and the corrected four-year outcome wording.

**Architecture:** Route both prospect detail renderings through `_build_dynasty_player_detail_context`, then normalize only the decision-relevant PNG fields in one pure helper. Extend the existing Pillow renderer with conditional, measured-height sections for outcome explanation, AAA evidence, rank movement, Peak Outlook, and source/confidence context; existing sections and readers remain intact.

**Tech Stack:** Python 3.10+, Flask, Jinja, Pillow, pytest, existing ValuCast stores and graphic helpers. No new dependency, CSS, JavaScript, model, or data artifact.

**Spec:** `docs/superpowers/specs/2026-07-18-prospect-player-share-parity-design.md`

## Global Constraints

- The prospect HTML card is the source of truth; the PNG is another rendering of the same context.
- Public wording is `Impact season`, `Established MLB role`, and `Not established by Year 4`; never render `Bust risk` publicly.
- Preserve every probability, model artifact, rank, value, cap, and pitcher publication decision.
- Preserve the model freeze, failed pitcher pedigree-decay flag, Role Watch hold, and paused League Connect state.
- Omit unavailable optional sections; never render empty shells or fabricate context.
- Keep the existing 1080-pixel vertical format, QR, palette, typography, provenance, and non-color labels.
- Do not add a second card component, dependency, CSS, JavaScript, or generated daily artifact.
- Do not deploy, dispatch a workflow, flip a hold, merge, or push during implementation.
- Retain the no-push window and do not dispatch workflows near 00:00 UTC.

---

## File Structure

- **Modify** `app.py` — pass the shared detail context into the existing PNG renderer, normalize decision fields, and draw the missing conditional sections.
- **Modify** `tests/test_app.py` — pin route/context parity, normalized wording, optional-section behavior, valid PNG output, and dynamic height.

No template or stylesheet change is planned. If implementation appears to need either, stop and re-check whether the PNG is incorrectly re-deriving a meaning already available in the detail context.

---

### Task 1: Make the PNG consume the shared player-detail context

**Files:**
- Modify: `tests/test_app.py:655-900`
- Modify: `app.py:3049-3091`
- Modify: `app.py:10113-10127`

**Interfaces:**
- Produces: `_prospect_player_card_png(row, detail_context=None) -> bytes`.
- Produces: `_prospect_share_decision_context(row, detail_context) -> dict`.
- Production invariant: `prospect_player_card_png` passes the result of `_build_dynasty_player_detail_context` to the renderer.

- [ ] **Step 1: Write the failing route/context test**

Add to `TestPlayerDetail` in `tests/test_app.py`:

```python
    def test_prospect_player_png_uses_shared_detail_context(self):
        if not app_module.dd_store.is_available:
            self.skipTest("DD feed not available")
        row = next((r for r in app_module.dd_store.get_all() if r.is_prospect), None)
        if row is None:
            self.skipTest("No prospect row available")

        fake_png = b"\x89PNG\r\n\x1a\n"
        with patch.object(
            app_module, "_prospect_player_card_png", return_value=fake_png
        ) as render:
            response = self.client.get(f"/prospects/player-card/{row.id}.png")

        self.assertEqual(response.status_code, 200)
        rendered_row = render.call_args.args[0]
        detail_context = render.call_args.kwargs["detail_context"]
        self.assertIs(rendered_row, detail_context["row"])
        self.assertIn("stat_percentiles", detail_context)
        self.assertIn("vc_rank_trend", detail_context)
        self.assertIn("aaa_pitch_shape", detail_context)
        self.assertIn("aaa_contact_quality", detail_context)
        self.assertIn("format_ranks", detail_context)
```

- [ ] **Step 2: Run the route test and verify RED**

```powershell
python -m pytest tests/test_app.py::TestPlayerDetail::test_prospect_player_png_uses_shared_detail_context -q
```

Expected: FAIL because the route passes only `row` and the renderer has no `detail_context` parameter.

- [ ] **Step 3: Change the production route to reuse the existing builder**

Replace `prospect_player_card_png` with this shape, preserving the current filename and response headers below the shown block:

```python
@app.route("/prospects/player-card/<player_id>.png")
def prospect_player_card_png(player_id):
    if not dd_store.is_available:
        return "", 503
    detail_context = _build_dynasty_player_detail_context(player_id, request.args)
    if detail_context is None:
        return "", 404
    row = detail_context["row"]
    if not row.is_prospect:
        return "", 404

    png = _prospect_player_card_png(row, detail_context=detail_context)
    filename_slug = "-".join(
        piece for piece in "".join(
            ch.lower() if ch.isalnum() else "-" for ch in row.name
        ).split("-") if piece
    )
    response = make_response(png)
    response.headers["Content-Type"] = "image/png"
    response.headers["Content-Disposition"] = (
        f'inline; filename="valucast-{filename_slug or "prospect"}-card.png"'
    )
    return response
```

Change the renderer signature only:

```python
def _prospect_player_card_png(row, detail_context=None):
    """Render the prospect share card from the shared player-detail context."""
    detail_context = detail_context or {}
```

Then prefer existing prepared values without changing the direct-call fallback:

```python
    stat_percentiles = detail_context.get("stat_percentiles")
    if stat_percentiles is None:
        stat_percentiles = prospect_percentiles.card_percentiles(prospect_pool, row)
    profile_bars = detail_context.get("profile_bars")
    if profile_bars is None:
        profile_bars = prospect_percentiles.profile_bars(row, stat_percentiles)
    skill_grades = detail_context.get("skill_grades")
    if skill_grades is None:
        skill_grades = prospect_percentiles.skill_grades(row, stat_percentiles)
    skill_shape = detail_context.get("skill_shape")
    if skill_shape is None:
        skill_shape = prospect_percentiles.skill_shape_compare(
            skill_grades, getattr(row, "peak_shape_items", ()) or ()
        )
    fg_scouting = detail_context.get("fangraphs")
    if fg_scouting is None:
        fg_scouting = fg_fv.get(getattr(row, "mlbam_id", None))
```

For the existing readers, use the prepared context first and retain the current fallback:

```python
    discipline_groups = detail_context.get("plate_discipline")
    if discipline_groups is None:
        discipline_groups = pitch_discipline_store.groups_for(
            getattr(row, "mlbam_id", None)
        )
    discipline_rows = _prospect_discipline_card_rows(discipline_groups)

    artifact_context = detail_context or _artifact_context_for_row(row)
    scouting_report = artifact_context.get("scouting_report")
    comp_source = detail_context.get("shape_comps")
```

When `comp_source` is present, call `_share_card_comp_lines(comp_source)`; otherwise preserve the current artifact lookup.

- [ ] **Step 4: Run the focused route and existing PNG tests**

```powershell
python -m pytest tests/test_app.py::TestPlayerDetail::test_prospect_player_png_uses_shared_detail_context tests/test_app.py::TestPlayerDetail::test_prospect_player_card_preview_and_png tests/test_app.py::TestPlayerDetail::test_player_card_png_fail_soft_without_qr_lib -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit Task 1**

```powershell
git add app.py tests/test_app.py
git commit -m "refactor: share prospect card detail context"
```

---

### Task 2: Normalize the exact decision fields and pin the public wording

**Files:**
- Modify: `tests/test_app.py`
- Modify: `app.py` immediately before `_prospect_player_card_png`

**Interfaces:**
- Consumes: `DynastyRankingRow` public properties and the shared detail context from Task 1.
- Produces: one fail-soft dictionary used directly by the Pillow renderer.

- [ ] **Step 1: Write the failing normalized-context test**

Add to `tests/test_app.py`:

```python
class TestProspectShareDecisionContext(unittest.TestCase):
    def test_context_matches_public_row_fields_and_has_no_bust_label(self):
        if not app_module.dd_store.is_available:
            self.skipTest("DD feed not available")
        row = next(
            (
                r for r in app_module.dd_store.get_all()
                if r.is_prospect and r.outcome_mix and r.has_peak_projection
            ),
            None,
        )
        if row is None:
            self.skipTest("No prospect with outcome and peak context")
        detail = app_module._build_dynasty_player_detail_context(row.id, {})

        decision = app_module._prospect_share_decision_context(row, detail)

        self.assertEqual(decision["outcomes"], tuple(row.outcome_mix))
        self.assertEqual(decision["why_rank"], tuple(row.why_rank_chips[:4]))
        self.assertEqual(decision["attribution"], tuple(row.attribution_components))
        self.assertEqual(decision["rank_trend"], detail["vc_rank_trend"])
        self.assertEqual(decision["peak"]["score"], row.peak_score_label)
        self.assertEqual(decision["peak"]["probabilities"], tuple(row.peak_role_probability_items))
        labels = [item["label"] for item in decision["outcomes"]]
        self.assertEqual(
            labels,
            ["Impact season", "Established MLB role", "Not established by Year 4"],
        )
        self.assertNotIn("Bust risk", " ".join(labels))

    def test_context_omits_missing_optional_sections(self):
        from types import SimpleNamespace

        row = SimpleNamespace(
            outcome_mix=(), why_rank_chips=(), attribution_components=(),
            uncertainty_label=None, uncertainty_note=None,
            uncertainty_driver_items=(), has_peak_projection=False,
            public_source_ranks={}, public_source_consensus=None,
            milb_performance_rank=None, availability_status_label=None,
            availability_risk_discount=None, current_level_sample_label=None,
            bucket_calibration_label=None, peak_score_label=None,
            peak_delta_label=None, peak_role_label=None, peak_risk_label=None,
            peak_confidence_label=None, peak_eta_label=None,
            peak_trajectory_label=None, peak_role_probability_items=(),
            peak_projection_card_copy=None,
        )
        decision = app_module._prospect_share_decision_context(row, {})
        self.assertEqual(decision["outcomes"], ())
        self.assertEqual(decision["rank_trend"], {})
        self.assertEqual(decision["aaa_pitch_shape"], {})
        self.assertEqual(decision["aaa_contact_quality"], {})
        self.assertEqual(decision["context_rows"], ())
        self.assertIsNone(decision["source"])
```

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest tests/test_app.py::TestProspectShareDecisionContext -q
```

Expected: FAIL because `_prospect_share_decision_context` does not exist.

- [ ] **Step 3: Add the minimal pure normalizer**

Add before `_prospect_player_card_png` in `app.py`:

```python
def _prospect_share_decision_context(row, detail_context):
    detail_context = detail_context or {}
    context_rows = []
    for label, value in (
        ("Availability", getattr(row, "availability_status_label", None)),
        ("Current Level", getattr(row, "current_level_sample_label", None)),
        ("Uncertainty", getattr(row, "uncertainty_label", None)),
        ("Confidence adjustment", getattr(row, "bucket_calibration_label", None)),
        ("Strike%", detail_context.get("pitcher_strike_pct")),
    ):
        if value:
            context_rows.append((label, str(value)))
    risk_discount = getattr(row, "availability_risk_discount", None)
    if isinstance(risk_discount, (int, float)) and risk_discount:
        context_rows.append(("Risk Adjustment", f"-{risk_discount * 100:.1f}%"))

    aotc = detail_context.get("ahead_of_consensus")
    public_ranks = getattr(row, "public_source_ranks", {}) or {}
    consensus = (
        aotc.get("consensus_rank")
        if isinstance(aotc, dict) else None
    )
    if consensus is None:
        consensus = getattr(row, "public_source_consensus", None)
    board_count = (
        aotc.get("board_count")
        if isinstance(aotc, dict) else None
    )
    if board_count is None:
        board_count = len(public_ranks)
    source = None
    if consensus is not None or public_ranks:
        source = {
            "consensus_rank": consensus,
            "board_count": board_count,
            "receipt": aotc if isinstance(aotc, dict) else None,
            "milb_performance_rank": getattr(row, "milb_performance_rank", None),
        }

    peak = None
    if getattr(row, "has_peak_projection", False):
        peak = {
            "score": getattr(row, "peak_score_label", None),
            "upside": getattr(row, "peak_delta_label", None),
            "role": getattr(row, "peak_role_label", None),
            "risk": getattr(row, "peak_risk_label", None),
            "confidence": getattr(row, "peak_confidence_label", None),
            "window": getattr(row, "peak_eta_label", None),
            "trajectory": getattr(row, "peak_trajectory_label", None),
            "probabilities": tuple(
                getattr(row, "peak_role_probability_items", ()) or ()
            ),
            "copy": getattr(row, "peak_projection_card_copy", None),
        }

    confidence = getattr(row, "confidence", {}) or {}
    if not isinstance(confidence, dict):
        confidence = {}
    value_range = confidence.get("range") or {}
    headline = []
    if getattr(row, "tier", None) is not None:
        headline.append(f"Tier {row.tier}")
    if getattr(row, "eta_display", None):
        headline.append(f"ETA {row.eta_display}")
    if confidence.get("level"):
        headline.append(
            str(confidence["level"]).replace("_", " ").title() + " confidence"
        )
    if value_range.get("low") is not None and value_range.get("high") is not None:
        headline.append(
            f"Range {float(value_range['low']):.0f}-{float(value_range['high']):.0f}"
        )

    return {
        "headline": tuple(headline),
        "outcomes": tuple(getattr(row, "outcome_mix", ()) or ()),
        "why_rank": tuple((getattr(row, "why_rank_chips", ()) or ())[:4]),
        "attribution": tuple(getattr(row, "attribution_components", ()) or ()),
        "uncertainty_note": getattr(row, "uncertainty_note", None),
        "uncertainty_drivers": tuple(
            getattr(row, "uncertainty_driver_items", ()) or ()
        ),
        "rank_trend": detail_context.get("vc_rank_trend") or {},
        "peak": peak,
        "aaa_pitch_shape": detail_context.get("aaa_pitch_shape") or {},
        "aaa_contact_quality": detail_context.get("aaa_contact_quality") or {},
        "context_rows": tuple(context_rows),
        "source": source,
        "forward_ledger": detail_context.get("forward_ledger"),
        "role_profile": detail_context.get("role_profile") or {},
        "recent_form": detail_context.get("recent_form") or {},
        "recent_signal": detail_context.get("recent_signal") or {},
        "call_up": detail_context.get("call_up"),
    }
```

At the start of `_prospect_player_card_png`, after the shared/fallback context is resolved, add:

```python
    decision = _prospect_share_decision_context(row, detail_context)
```

- [ ] **Step 4: Run normalized-context and existing outcome tests**

```powershell
python -m pytest tests/test_app.py::TestProspectShareDecisionContext tests/test_app.py::TestOutcomeMixHelper tests/test_app.py::TestAttributionPanel -q
```

Expected: all selected tests pass; `Bust risk` remains absent from public labels.

- [ ] **Step 5: Commit Task 2**

```powershell
git add app.py tests/test_app.py
git commit -m "test: define prospect share-card parity fields"
```

---

### Task 3: Draw the outcome explanation above current evidence

**Files:**
- Modify: `tests/test_app.py`
- Modify: `app.py:3211-3619`

**Interfaces:**
- Consumes: `decision["outcomes"]`, `why_rank`, `attribution`, and uncertainty fields from Task 2.
- Produces: a conditional outcome panel and `outcome_extra` vertical offset.

- [ ] **Step 1: Write a failing dynamic-height test**

Add to `TestProspectShareDecisionContext`:

```python
    def test_outcome_context_adds_height_and_sparse_context_does_not(self):
        import struct

        if not app_module.dd_store.is_available:
            self.skipTest("DD feed not available")
        row = next((r for r in app_module.dd_store.get_all() if r.is_prospect), None)
        if row is None:
            self.skipTest("No prospect row available")
        detail = app_module._build_dynasty_player_detail_context(row.id, {})
        full = app_module._prospect_share_decision_context(row, detail)
        full["outcomes"] = (
            {"label": "Impact season", "pct": 8, "tone": "signal"},
            {"label": "Established MLB role", "pct": 28, "tone": "slate"},
            {"label": "Not established by Year 4", "pct": 64, "tone": "clay"},
        )
        sparse = dict(full, outcomes=(), why_rank=(), attribution=(),
                      uncertainty_note=None, uncertainty_drivers=())

        with patch.object(app_module, "_prospect_share_decision_context", return_value=sparse):
            base_png = app_module._prospect_player_card_png(row, detail_context=detail)
        with patch.object(app_module, "_prospect_share_decision_context", return_value=full):
            outcome_png = app_module._prospect_player_card_png(row, detail_context=detail)

        base_h = struct.unpack(">I", base_png[20:24])[0]
        outcome_h = struct.unpack(">I", outcome_png[20:24])[0]
        self.assertGreater(outcome_h, base_h)
```

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest tests/test_app.py::TestProspectShareDecisionContext::test_outcome_context_adds_height_and_sparse_context_does_not -q
```

Expected: FAIL because the renderer does not consume the outcome fields and both images have equal height.

- [ ] **Step 3: Measure the conditional outcome block**

Before `content_height` is calculated in `_prospect_player_card_png`, add:

```python
    outcome_lines = []
    if decision["why_rank"]:
        outcome_lines.append(
            "WHY THIS GRADE  " + "  |  ".join(
                str(item.get("label") or "") for item in decision["why_rank"]
                if item.get("label")
            )
        )
    for item in decision["attribution"]:
        label = str(item.get("label") or "").strip()
        effect = str(item.get("effect") or "").strip()
        note = str(item.get("note") or "").strip()
        if label:
            suffix = effect or note
            if item.get("context_only"):
                suffix = (suffix + " - " if suffix else "") + "context, not a score input"
            outcome_lines.append(f"{label}: {suffix}" if suffix else label)
    if decision["uncertainty_note"]:
        outcome_lines.append(str(decision["uncertainty_note"]))
    for item in decision["uncertainty_drivers"]:
        label = str(item.get("label") or "").strip()
        value = str(item.get("value") or "").strip()
        if label and value:
            outcome_lines.append(f"{label}: {value}")

    outcome_h = 0
    if decision["outcomes"]:
        outcome_h = 176 + 28 * len(outcome_lines)
    outcome_extra = outcome_h + 8 if outcome_h else 0
```

Add `outcome_extra` to `content_height`:

```python
    content_height = (
        1350 + STATS_BLOCK_H + read_extra + comps_extra
        + discipline_extra + outcome_extra
    )
```

- [ ] **Step 4: Draw the exact four-year panel and shift existing evidence**

Immediately before the current skill-bars panel, draw:

```python
    outcome_top = 438
    if outcome_h:
        _graphic_glass_panel(
            img, draw, (48, outcome_top, 1032, outcome_top + outcome_h), radius=12
        )
        draw.text(
            (74, outcome_top + 22), "HOW VALUCAST GRADED HIM",
            fill=muted, font=_graphic_font(20, bold=True),
        )
        bar_x0, bar_x1, bar_y = 74, 1006, outcome_top + 58
        cursor = bar_x0
        tones = {
            "signal": green,
            "slate": _GRAPHIC_PALETTE["slate"],
            "clay": _GRAPHIC_PALETTE["clay"],
        }
        for segment in decision["outcomes"]:
            width_px = round((bar_x1 - bar_x0) * int(segment["pct"]) / 100)
            draw.rectangle(
                (cursor, bar_y, min(bar_x1, cursor + width_px), bar_y + 16),
                fill=tones.get(segment.get("tone"), muted),
            )
            cursor += width_px
        legend_y = bar_y + 30
        legend_font = _graphic_font(15, bold=True)
        slot_w = (bar_x1 - bar_x0) // max(1, len(decision["outcomes"]))
        for index, segment in enumerate(decision["outcomes"]):
            label = f"{segment['label']}  {segment['pct']}%"
            draw.text(
                (bar_x0 + index * slot_w, legend_y),
                _graphic_fit_text(draw, label, legend_font, slot_w - 12),
                fill=text, font=legend_font,
            )
        note = (
            "Four-year MLB outlook. Not established means no applicable 300-PA "
            "hitter or 50-IP pitcher season within four years - not a career verdict."
        )
        draw.text(
            (74, legend_y + 28),
            _graphic_fit_text(draw, note, _graphic_font(14), 932),
            fill=muted, font=_graphic_font(14),
        )
        line_y = legend_y + 56
        for line in outcome_lines:
            draw.text(
                (74, line_y),
                _graphic_fit_text(draw, line, _graphic_font(15), 932),
                fill=text, font=_graphic_font(15),
            )
            line_y += 28
```

In the identity panel, replace the standalone `pool_label` line at y=350 with
the pool label plus the normalized headline fields, fitted to the same 600-pixel
slot:

```python
    headline_context = "  |  ".join((pool_label, *decision["headline"]))
    draw.text(
        (76, 350),
        _graphic_fit_text(draw, headline_context, _graphic_font(18, mono=True), 600),
        fill=muted,
        font=_graphic_font(18, mono=True),
    )
```

Define `evidence_shift = outcome_extra` and replace the existing fixed evidence anchors as follows:

| Existing anchor | Replacement |
|---|---|
| skill panel/bar y values `438`, `468`, `500`, `542`, `560` | add `evidence_shift` |
| discipline `pd_top = 820` | `pd_top = 820 + evidence_shift` |
| season `stats_top = 820 + discipline_extra` | `stats_top = 820 + evidence_shift + discipline_extra` |
| read panel top `1050 + discipline_extra` | `1050 + evidence_shift + discipline_extra` |
| read label/text y values `1080`, `1120`, `proj_y0` | add `evidence_shift + discipline_extra` where discipline is not already included |
| `body_shift = read_extra + discipline_extra` | `body_shift = read_extra + discipline_extra + evidence_shift` |

Leave the identity/header positions unchanged so outcome explanation begins immediately after the current decision header.

Replace the existing `shape_items = peak_shape or skill_grades` assignment with
`shape_items = skill_shape`, and set the title from the actual paired data:

```python
    shape_title = (
        "SKILL SHAPE - CURRENT -> PROJECTED PEAK"
        if any(item.get("peak") is not None for item in shape_items)
        else "CURRENT SKILL SHAPE"
    )
```

In the existing four shape boxes, draw
`skill["current"]` as the first number and append ` -> {skill['peak']}` only when
`peak` is not `None`. This matches the HTML card's current-to-peak comparison
without adding a second shape section:

```python
        current = skill.get("current")
        peak_grade = skill.get("peak")
        grade_text = str(current) if peak_grade is None else f"{current} -> {peak_grade}"
        color_grade = peak_grade if peak_grade is not None else current
        color = bar_elite if color_grade >= 60 else bar_low if color_grade <= 40 else text
        draw.text((x + 138, 1285 + body_shift), grade_text, fill=color,
                  font=_graphic_font(21, bold=True))
```

- [ ] **Step 5: Run focused PNG tests**

```powershell
python -m pytest tests/test_app.py::TestProspectShareDecisionContext tests/test_app.py::TestPlayerDetail::test_prospect_player_card_preview_and_png -q
```

Expected: all selected tests pass and the outcome-enabled image is taller.

- [ ] **Step 6: Commit Task 3**

```powershell
git add app.py tests/test_app.py
git commit -m "feat: carry prospect outcome context onto share cards"
```

---

### Task 4: Add AAA evidence, rank movement, Peak Outlook, and source context

**Files:**
- Modify: `tests/test_app.py`
- Modify: `app.py:3392-3619`

**Interfaces:**
- Consumes: the remaining normalized fields from Task 2.
- Produces: conditional evidence and decision panels whose measured heights feed the existing footer/QR layout.

- [ ] **Step 1: Add failing optional-section height tests**

Add to `TestProspectShareDecisionContext`:

```python
    def test_rank_peak_aaa_and_source_sections_each_grow_the_png(self):
        import struct

        if not app_module.dd_store.is_available:
            self.skipTest("DD feed not available")
        row = next((r for r in app_module.dd_store.get_all() if r.is_prospect), None)
        if row is None:
            self.skipTest("No prospect row available")
        detail = app_module._build_dynasty_player_detail_context(row.id, {})
        empty = app_module._prospect_share_decision_context(row, detail)
        empty.update({
            "outcomes": (), "why_rank": (), "attribution": (),
            "uncertainty_note": None, "uncertainty_drivers": (),
            "rank_trend": {}, "peak": None, "aaa_pitch_shape": {},
            "aaa_contact_quality": {}, "context_rows": (), "source": None,
            "forward_ledger": None,
        })
        variants = [
            dict(empty, rank_trend={
                "points": "0.0,6.0 240.0,54.0", "dot_x": 240.0, "dot_y": 54.0,
                "view_w": 240.0, "view_h": 60.0, "caption": "Best #1 (Jun 24) - now #7",
            }),
            dict(empty, peak={
                "score": "76.1", "upside": "+7.6", "role": "Mid-Rotation Starter Or Better",
                "risk": "Low", "confidence": "Medium", "window": "One To Two Years",
                "trajectory": "More upside than today's value",
                "probabilities": ({"label": "Starter/late inning", "pct": 70, "value": "70%"},),
                "copy": "Projection: mid-rotation starter or better.",
            }),
            dict(empty, aaa_contact_quality={
                "as_of": "2026-07-14", "n_pitches": 700, "n_bip": 120,
                "rows": ({"label": "Avg Exit Velo", "value": "90.4 mph"},),
            }),
            dict(empty, context_rows=(("Current Level", "AA - 72.7 IP"),),
                 source={"consensus_rank": 45, "board_count": 4,
                         "receipt": None, "milb_performance_rank": 17}),
        ]

        def height(decision):
            with patch.object(
                app_module, "_prospect_share_decision_context", return_value=decision
            ):
                png = app_module._prospect_player_card_png(row, detail_context=detail)
            return struct.unpack(">I", png[20:24])[0]

        base_h = height(empty)
        for variant in variants:
            self.assertGreater(height(variant), base_h)
```

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest tests/test_app.py::TestProspectShareDecisionContext::test_rank_peak_aaa_and_source_sections_each_grow_the_png -q
```

Expected: FAIL because the remaining fields do not affect PNG height.

- [ ] **Step 3: Flatten AAA evidence into honest share rows**

Add before the renderer:

```python
def _prospect_share_aaa_rows(pitch_shape, contact_quality):
    rows = []
    if pitch_shape:
        for pitch in pitch_shape.get("pitch_types") or ():
            values = "  |  ".join(
                f"{item['label']} {item['value']}" for item in pitch.get("rows") or ()
            )
            usage = f" {pitch['usage']}" if pitch.get("usage") else ""
            rows.append((f"{pitch.get('label', 'Pitch')}{usage}", values))
        outcomes = "  |  ".join(
            f"{item['label']} {item['value']}"
            for item in pitch_shape.get("outcomes") or ()
        )
        if outcomes:
            rows.append(("Outcomes", outcomes))
    elif contact_quality:
        rows.extend(
            (str(item["label"]), str(item["value"]))
            for item in contact_quality.get("rows") or ()
        )
    return tuple(rows)
```

Add a small local height function inside `_prospect_player_card_png`:

```python
    aaa_rows = _prospect_share_aaa_rows(
        decision["aaa_pitch_shape"], decision["aaa_contact_quality"]
    )
    aaa_h = 58 + 30 * len(aaa_rows) if aaa_rows else 0
    aaa_extra = aaa_h + 8 if aaa_h else 0
```

Insert the AAA panel between plate discipline and the 2026 season table. Use the same prepared values and this disclosure exactly:

```python
    if aaa_h:
        aaa_top = 820 + evidence_shift + discipline_extra
        _graphic_glass_panel(img, draw, (48, aaa_top, 1032, aaa_top + aaa_h), radius=12)
        draw.text((74, aaa_top + 16), "AAA STATCAST", fill=muted,
                  font=_graphic_font(20, bold=True))
        draw.text((300, aaa_top + 19),
                  "measured AAA only - display context, not a model input",
                  fill=muted, font=_graphic_font(13, bold=True))
        row_y = aaa_top + 48
        for label, value in aaa_rows:
            draw.text((74, row_y), _graphic_fit_text(draw, label,
                      _graphic_font(15, bold=True), 210), fill=text,
                      font=_graphic_font(15, bold=True))
            draw.text((300, row_y), _graphic_fit_text(draw, value,
                      _graphic_font(15), 706), fill=text, font=_graphic_font(15))
            row_y += 30
```

Add `aaa_extra` to `content_height`, move `stats_top` down by `aaa_extra`, and include `aaa_extra` in `body_shift`.

- [ ] **Step 4: Measure and draw post-shape decision panels**

Before `content_height`, compute:

```python
    trend_h = 130 if decision["rank_trend"].get("points") else 0
    peak = decision["peak"]
    peak_h = 0
    if peak:
        peak_h = 132 + 34 * len(peak["probabilities"])
        if peak.get("copy"):
            peak_h += 30
    source_rows = list(decision["context_rows"])
    role_profile = decision["role_profile"]
    if role_profile.get("projected_role_label"):
        source_rows.append(("Projected Role", str(role_profile["projected_role_label"])))
    if role_profile.get("projected_volume") is not None and role_profile.get("projected_volume_unit"):
        source_rows.append((
            "Projected Volume",
            f"{float(role_profile['projected_volume']):.0f} {role_profile['projected_volume_unit']}",
        ))
    recent_form = decision["recent_form"]
    if recent_form.get("momentum_label"):
        source_rows.append((
            "Recent Form",
            f"{recent_form['momentum_label']} - last {recent_form.get('window_days') or 30}d vs season",
        ))
    recent_signal = decision["recent_signal"]
    if recent_signal.get("buy_rank"):
        buy_value = f"#{recent_signal['buy_rank']}"
        if recent_signal.get("buy_reason"):
            buy_value += f" - {recent_signal['buy_reason']}"
        source_rows.append(("Buy Board", buy_value))
    call_up = decision["call_up"]
    if call_up:
        call_up_value = "Called up"
        if call_up.get("mlb_team"):
            call_up_value += f" - {call_up['mlb_team']}"
        source_rows.append(("Roster Move", call_up_value))
    if decision["source"]:
        source = decision["source"]
        if source.get("consensus_rank") is not None:
            source_rows.append((
                "Public Consensus",
                f"~P#{source['consensus_rank']} - {source['board_count']} boards",
            ))
        if source.get("milb_performance_rank") is not None:
            source_rows.append((
                "MiLB Performance", f"#{source['milb_performance_rank']}"
            ))
    if decision["forward_ledger"]:
        source_rows.append(("Forward Ledger", "Registered public claim"))
    source_h = 78 + 30 * len(source_rows) if source_rows else 0
    post_shape_extra = sum(
        height + 8 for height in (trend_h, peak_h, source_h) if height
    )
```

After the current projected-shape boxes and before shape comps, initialize:

```python
    next_panel_y = 1356 + body_shift
```

Draw rank trend using the store's prepared geometry:

```python
    if trend_h:
        trend = decision["rank_trend"]
        _graphic_glass_panel(img, draw, (48, next_panel_y, 1032, next_panel_y + trend_h), radius=12)
        draw.text((74, next_panel_y + 16), "VALUCAST RANK TREND", fill=muted,
                  font=_graphic_font(20, bold=True))
        draw.text((74, next_panel_y + 44), str(trend.get("caption") or ""),
                  fill=text, font=_graphic_font(16, bold=True))
        coords = [
            tuple(float(value) for value in pair.split(","))
            for pair in str(trend["points"]).split()
        ]
        chart_x, chart_y, chart_w, chart_h = 74, next_panel_y + 72, 932, 40
        scaled = [
            (
                chart_x + x / float(trend["view_w"]) * chart_w,
                chart_y + y / float(trend["view_h"]) * chart_h,
            )
            for x, y in coords
        ]
        if len(scaled) >= 2:
            draw.line(scaled, fill=green, width=4, joint="curve")
        if scaled:
            x, y = scaled[-1]
            draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=green)
        next_panel_y += trend_h + 8
```

Draw Peak Outlook:

```python
    if peak_h:
        _graphic_glass_panel(img, draw, (48, next_panel_y, 1032, next_panel_y + peak_h), radius=12)
        draw.text((74, next_panel_y + 16), "PEAK OUTLOOK", fill=muted,
                  font=_graphic_font(20, bold=True))
        summary = [
            ("PEAK", peak.get("score")), ("UPSIDE", peak.get("upside")),
            ("ROLE", peak.get("role")), ("RISK", peak.get("risk")),
            ("CONFIDENCE", peak.get("confidence")), ("WINDOW", peak.get("window")),
        ]
        summary = [(label, value) for label, value in summary if value]
        slot_w = 932 // max(1, len(summary))
        for index, (label, value) in enumerate(summary):
            x = 74 + index * slot_w
            draw.text((x, next_panel_y + 48), label, fill=muted,
                      font=_graphic_font(12, bold=True))
            draw.text((x, next_panel_y + 68),
                      _graphic_fit_text(draw, str(value), _graphic_font(15, bold=True), slot_w - 10),
                      fill=text, font=_graphic_font(15, bold=True))
        row_y = next_panel_y + 96
        for item in peak["probabilities"]:
            draw.text((74, row_y), str(item["label"]), fill=text,
                      font=_graphic_font(15, bold=True))
            draw.rounded_rectangle((330, row_y + 3, 900, row_y + 15), radius=4,
                                   fill=(30, 32, 40))
            draw.rounded_rectangle(
                (330, row_y + 3, 330 + round(570 * int(item["pct"]) / 100), row_y + 15),
                radius=4, fill=green,
            )
            draw.text((920, row_y - 2), str(item["value"]), fill=text,
                      font=_graphic_font(15, bold=True))
            row_y += 34
        if peak.get("copy"):
            draw.text((74, row_y), _graphic_fit_text(draw, str(peak["copy"]),
                      _graphic_font(14), 932), fill=muted, font=_graphic_font(14))
        next_panel_y += peak_h + 8
```

Draw confidence/source rows with the same generic label/value treatment:

```python
    if source_h:
        _graphic_glass_panel(img, draw, (48, next_panel_y, 1032, next_panel_y + source_h), radius=12)
        draw.text((74, next_panel_y + 16), "CONFIDENCE AND SOURCE CONTEXT",
                  fill=muted, font=_graphic_font(20, bold=True))
        row_y = next_panel_y + 48
        for label, value in source_rows:
            draw.text((74, row_y), _graphic_fit_text(draw, label,
                      _graphic_font(14, bold=True), 220), fill=muted,
                      font=_graphic_font(14, bold=True))
            draw.text((310, row_y), _graphic_fit_text(draw, value,
                      _graphic_font(15, bold=True), 696), fill=text,
                      font=_graphic_font(15, bold=True))
            row_y += 30
        draw.text((74, next_panel_y + source_h - 22),
                  "External boards and scouting grades are context only - never rank or value inputs.",
                  fill=muted, font=_graphic_font(13))
        next_panel_y += source_h + 8
```

Use `next_panel_y` as the new shape-comps top. Add `post_shape_extra` to `content_height`, and add it to the FanGraphs/footer offsets. Existing comps and FanGraphs drawing remain unchanged.

Extend the footer's right-side note with
`" Model verdicts: valucast.app/models."` after the existing provenance sentence.
The QR remains the navigation mechanism; do not draw a fake button or clickable
link into the PNG.

- [ ] **Step 5: Run optional-section and all prospect-card focused tests**

```powershell
python -m pytest tests/test_app.py::TestProspectShareDecisionContext tests/test_app.py::TestPlayerDetail tests/test_aaa_statcast_store.py tests/test_rank_history_store.py tests/test_prospect_comps.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 4**

```powershell
git add app.py tests/test_app.py
git commit -m "feat: complete prospect player share-card context"
```

---

### Task 5: Run full regression and visual acceptance without launching

**Files:**
- No planned source changes.
- Do not stage PNGs, screenshots, caches, or generated artifacts.

**Interfaces:**
- Verifies the complete written spec against automated output and five representative player cards.

- [ ] **Step 1: Run formatting and focused regression**

```powershell
git diff --check origin/master...HEAD
python -m pytest tests/test_app.py tests/test_card_intelligence.py tests/test_aaa_statcast_store.py tests/test_rank_history_store.py tests/test_prospect_comps.py tests/test_ahead_of_curve_card_stamp.py -q
```

Expected: no whitespace errors and all selected tests pass.

- [ ] **Step 2: Run the complete automated suite**

```powershell
python -m pytest -q
```

Expected: zero failures.

- [ ] **Step 3: Verify protected outputs and holds**

```powershell
git diff --exit-code origin/master -- prospects/model.py prospects/rank_v1.py data/models/valucast_prospect_rank_v1.json data/public/public_dynasty_snapshot.json
git diff --name-only 947776e1..HEAD
```

Expected: the protected-output command exits zero. The changed-file list contains only `app.py`, `tests/test_app.py`, the approved spec, and this plan.

- [ ] **Step 4: Render five current-data acceptance cards to a temporary directory**

```powershell
$reviewRoot = Join-Path $env:TEMP 'valucast-prospect-share-review'
New-Item -ItemType Directory -Force $reviewRoot | Out-Null
$env:VALUCAST_SHARE_REVIEW = $reviewRoot
@'
import os
from pathlib import Path
import app

rows = [row for row in app.dd_store.get_all() if row.is_prospect]

def pick(label, predicate):
    row = next((candidate for candidate in rows if predicate(candidate)), None)
    assert row is not None, f"no current-data {label} acceptance case"
    return row

cases = [
    pick("Kade Anderson", lambda row: row.name == "Kade Anderson"),
    pick("hitter", lambda row: row.role == "hitter" and row.outcome_mix),
    pick("AAA Statcast", lambda row:
         app.aaa_statcast_store.pitch_shape_for(row.mlbam_id)
         or app.aaa_statcast_store.contact_quality_for(row.mlbam_id)),
    pick("availability", lambda row: row.availability_status_label
         and row.availability_status_label != "Available"),
    pick("sparse", lambda row: not row.outcome_mix and not row.has_peak_projection),
]

out = Path(os.environ["VALUCAST_SHARE_REVIEW"])
for row in {case.id: case for case in cases}.values():
    detail = app._build_dynasty_player_detail_context(row.id, {})
    png = app._prospect_player_card_png(row, detail_context=detail)
    target = out / f"{row.id}.png"
    target.write_bytes(png)
    print(target)
'@ | python -
```

Expected: five valid PNG paths under `%TEMP%`; if a current-data class has no representative row, report that absence rather than weakening the selection rule.

- [ ] **Step 5: Inspect native and phone-width previews**

For each generated PNG:

- inspect at native resolution;
- inspect scaled to a 390-pixel phone viewport;
- confirm every available decision section is present;
- confirm no overlap, clipping, tiny provenance copy, or empty panel;
- confirm outcome labels and four-year note are readable;
- confirm Kade Anderson does not show `Bust risk`;
- confirm AAA-only, estimated, external-context, and model-input disclosures remain attached to their data;
- confirm QR/footer remain below content.

Expected: all five cases pass. Fix only the shared renderer or normalizer if a case fails; do not add name-based handling.

- [ ] **Step 6: Final repository audit**

```powershell
git diff --check origin/master...HEAD
git status --short --branch
git log --oneline --decorate 947776e1..HEAD
```

Expected: no whitespace errors, no uncommitted production changes, and only the planned commits. Stop before push, merge, deployment, workflow dispatch, or hold changes.

---

## Review Checkpoints

1. After Task 1: verify the PNG route and HTML detail use the same context builder.
2. After Task 2: verify normalized labels and values match the public row properties exactly.
3. After Task 3: inspect one outcome-enabled card before adding more sections.
4. After Task 4: inspect Kade Anderson and one AAA card at native resolution.
5. After Task 5: stop for explicit integration and production authorization.
