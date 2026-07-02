"""Ahead-of-the-Curve scorecard v2: exit-accounted funnel, noise floor,
matched controls, decided-rate, pre-registered targets, gate."""
import json

from scripts.build_ahead_of_consensus_scorecard import build_scorecard


def _board(archive_dir, date_str, rows):
    (archive_dir / f"{date_str}.json").write_text(
        json.dumps({"board": rows}), encoding="utf-8"
    )


def _row(mlbam, vc_rank, source_ranks, name=None, role="hitter"):
    return {
        "mlbam_id": mlbam,
        "role": role,
        "name": name or f"Player {mlbam}",
        "rank": vc_rank,
        "context_only": {"source_ranks": source_ranks},
    }


def test_catch_up_and_earliest_date(tmp_path):
    # Day 1: field has him ~#85 (median of 80/90), VC #10 -> divergence 75, guarded.
    _board(tmp_path, "2026-06-01", [_row(1, 10, {"pipeline": 80, "hkb": 90})])
    # Day 3: field moved toward us (median 55). catch_up = 85 - 55 = 30 — well past
    # the noise floor (max(10, 15% of 75) = 11.25) -> open_toward.
    _board(tmp_path, "2026-06-03", [_row(1, 10, {"pipeline": 50, "hkb": 60})])

    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-06-03T00:00:00+00:00")

    call = payload["calls"][0]
    assert call["ahead_since"] == "2026-06-01"     # earliest guarded date, not day 3
    assert call["consensus_then"] == 85
    assert call["consensus_now"] == 55
    assert call["consensus_catch_up"] == 30
    assert call["status"] == "open_toward"
    assert payload["funnel"]["open_toward"] == 1
    assert payload["summary"]["wins"] == 1
    # 2-day horizon is far below the publish gate -> number stays withheld.
    assert payload["gate"]["publishable"] is False
    # Independence firewall.
    assert payload["source_policy"]["feeds_model_score"] is False


def test_field_moving_away_is_not_a_win(tmp_path):
    _board(tmp_path, "2026-06-01", [_row(1, 10, {"pipeline": 60, "hkb": 70})])   # median 65
    _board(tmp_path, "2026-06-05", [_row(1, 10, {"pipeline": 90, "hkb": 100})])  # median 95 -> AWAY
    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-06-05T00:00:00+00:00")
    call = payload["calls"][0]
    assert call["consensus_catch_up"] == -30
    assert call["status"] == "open_away"
    assert payload["summary"]["wins"] == 0
    assert payload["summary"]["decided_count"] == 1
    assert payload["summary"]["decided_rate"] == 0.0


def test_noise_floor_keeps_small_wiggles_flat(tmp_path):
    # divergence 55 -> floor = max(10, 8.25) = 10; a +6 move must stay flat.
    _board(tmp_path, "2026-06-01", [_row(1, 10, {"pipeline": 60, "hkb": 70})])   # median 65
    _board(tmp_path, "2026-06-05", [_row(1, 10, {"pipeline": 55, "hkb": 63})])   # median 59: +6
    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-06-05T00:00:00+00:00")
    call = payload["calls"][0]
    assert call["consensus_catch_up"] == 6
    assert call["status"] == "open_flat"
    # Flats are undecided, never wins and never hidden.
    assert payload["summary"]["decided_count"] == 0
    assert payload["funnel"]["open_flat"] == 1


def test_retreat_attribution_counts_against_valucast(tmp_path):
    # Divergence closes because VC came DOWN (10 -> 70) while the field barely
    # moved: retired_we_backed_off, in the decided denominator as a loss.
    _board(tmp_path, "2026-06-01", [_row(1, 10, {"pipeline": 80, "hkb": 90})])   # gap 75
    _board(tmp_path, "2026-06-05", [_row(1, 70, {"pipeline": 78, "hkb": 88})])   # gap 13 < guard
    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-06-05T00:00:00+00:00")
    call = payload["calls"][0]
    assert call["status"] == "retired_we_backed_off"
    assert payload["funnel"]["retired_we_backed_off"] == 1
    assert payload["summary"]["decided_count"] == 1
    assert payload["summary"]["decided_rate"] == 0.0


def test_full_catch_up_that_closes_the_gap_is_a_terminal_win(tmp_path):
    # Field comes all the way to VC (median 85 -> 18) while VC holds: the call
    # leaves the guarded set as closed_caught_up — a WIN the v1 metric dropped.
    _board(tmp_path, "2026-06-01", [_row(1, 10, {"pipeline": 80, "hkb": 90})])
    _board(tmp_path, "2026-06-05", [_row(1, 10, {"pipeline": 16, "hkb": 20})])
    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-06-05T00:00:00+00:00")
    call = payload["calls"][0]
    assert call["status"] == "closed_caught_up"
    assert payload["summary"]["wins"] == 1
    assert payload["summary"]["decided_rate"] == 1.0


def test_matched_controls_and_lift(tmp_path):
    # One call (VC #10 vs field 85) + one never-flagged control at a similar field
    # rank whose consensus never moves -> lift is wins-rate / control-rate.
    day1 = [
        _row(1, 10, {"pipeline": 80, "hkb": 90}),           # the call
        _row(2, 84, {"pipeline": 78, "hkb": 92}),           # control: median 85, no divergence
    ]
    day2 = [
        _row(1, 10, {"pipeline": 50, "hkb": 60}),           # call: field came to 55 (+30)
        _row(2, 84, {"pipeline": 78, "hkb": 92}),           # control: unmoved
    ]
    _board(tmp_path, "2026-06-01", day1)
    _board(tmp_path, "2026-06-05", day2)
    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-06-05T00:00:00+00:00")
    controls = payload["summary"]["control_rates"]
    assert controls["n"] == 1
    assert controls["toward"] == 0
    assert payload["summary"]["open_rates"]["toward_rate"] == 1.0
    # control toward_rate is 0 -> lift is None (division guard), never inf.
    assert payload["summary"]["control_lift"] is None


def test_funnel_sums_to_ever_flagged_and_targets_present(tmp_path):
    _board(tmp_path, "2026-06-01", [_row(1, 10, {"pipeline": 80, "hkb": 90})])
    _board(tmp_path, "2026-06-05", [_row(1, 10, {"pipeline": 50, "hkb": 60})])
    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-06-05T00:00:00+00:00")
    assert sum(payload["funnel"].values()) == payload["summary"]["ever_flagged"]
    assert payload["targets"]["decided_rate"] == 0.50
    assert payload["targets"]["control_lift"] == 1.5
    assert "frozen" in payload["definitions"]


def test_empty_archive_is_safe(tmp_path):
    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-06-05T00:00:00+00:00")
    assert payload["status"] == "blocked"
    assert payload["calls"] == []
    assert payload["gate"]["publishable"] is False


def test_ledger_page_renders_full_ledger():
    """/ledger is the human-readable ledger — funnel tiles, every call with an
    honest status chip — while the headline still honors the publish gate."""
    from app import app

    app.config["TESTING"] = True
    client = app.test_client()
    html = client.get("/ledger").data.decode("utf-8")

    assert "THE LEDGER" in html
    assert "We backed off" in html                      # misses are on the page
    assert "Our retreats" in html                       # ...and in the funnel tiles
    assert "/aotc-scorecard.json" in html               # raw artifact still linked
    assert "no call ever leaves this page silently" in html.lower()
    assert 'data-ledger-filter="retreat"' in html       # outcome filter pills
    assert 'data-ledger-filter="resolved"' in html      # resolved != undecided
    assert "conviction, not evidence" in html           # worked-example explainer

    # Legacy route redirects permanently.
    r = client.get("/track-record")
    assert r.status_code == 301
    assert r.headers["Location"].endswith("/ledger")

def test_streak_anchor_resets_after_a_lapse(tmp_path):
    # Day 1 guarded (gap 75), day 2 the gap collapses below the 25-spot guard
    # (still on the board), day 3 guarded again. Scoring stays pinned to the
    # earliest date, but the DISPLAY streak must restart at day 3 -- "since
    # day 1" on a lapsed call is falsifiable from our own archive.
    _board(tmp_path, "2026-06-01", [_row(1, 10, {"pipeline": 80, "hkb": 90})])
    _board(tmp_path, "2026-06-02", [_row(1, 10, {"pipeline": 20, "hkb": 30})])
    _board(tmp_path, "2026-06-03", [_row(1, 10, {"pipeline": 80, "hkb": 90})])
    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-06-03T00:00:00+00:00")
    call = payload["calls"][0]
    assert call["ahead_since"] == "2026-06-01"      # scoring anchor unchanged
    assert call["days_tracked"] == 2
    assert call["streak_since"] == "2026-06-03"     # display anchor restarts
    assert call["streak_days"] == 0


def test_unbroken_run_streak_matches_ahead_since(tmp_path):
    _board(tmp_path, "2026-06-01", [_row(1, 10, {"pipeline": 80, "hkb": 90})])
    _board(tmp_path, "2026-06-05", [_row(1, 10, {"pipeline": 80, "hkb": 90})])
    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-06-05T00:00:00+00:00")
    call = payload["calls"][0]
    assert call["streak_since"] == call["ahead_since"] == "2026-06-01"
    assert call["streak_days"] == call["days_tracked"] == 4


def test_coverage_loss_without_our_retreat_is_not_a_retreat(tmp_path):
    # Day 2: one public board drops him -> consensus uncomputable (MIN_BOARDS=2)
    # while OUR rank never moved. Neither side's retreat is measurable, so this
    # must exit-account as left_universe, NOT "we backed off" (whose row would
    # contradict its own numbers).
    _board(tmp_path, "2026-06-01", [_row(1, 10, {"pipeline": 80, "hkb": 90})])
    _board(tmp_path, "2026-06-05", [_row(1, 10, {"pipeline": 80})])
    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-06-05T00:00:00+00:00")
    call = payload["calls"][0]
    assert call["status"] == "left_universe"
    assert payload["funnel"]["left_universe"] == 1
    assert payload["funnel"]["retired_we_backed_off"] == 0
    assert payload["summary"]["decided_count"] == 0


def test_coverage_loss_with_our_retreat_still_counts_against_us(tmp_path):
    # Same coverage loss, but WE also dropped him 10 -> 70: our side of the
    # retreat is measurable from our own board, so it stays a retreat.
    _board(tmp_path, "2026-06-01", [_row(1, 10, {"pipeline": 80, "hkb": 90})])
    _board(tmp_path, "2026-06-05", [_row(1, 70, {"pipeline": 80})])
    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-06-05T00:00:00+00:00")
    call = payload["calls"][0]
    assert call["status"] == "retired_we_backed_off"
    assert payload["summary"]["decided_count"] == 1

