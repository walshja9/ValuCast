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


def test_track_record_page_renders_full_ledger():
    """/track-record is the human-readable ledger — funnel, every call, honest
    statuses — while the aggregate headline still honors the publish gate."""
    from app import app

    app.config["TESTING"] = True
    html = app.test_client().get("/track-record").data.decode("utf-8")

    assert "Ahead of the Curve — Track Record" in html
    assert "We backed off" in html                      # misses are on the page
    assert "/aotc-scorecard.json" in html               # raw artifact still linked
    assert "no call ever leaves this ledger silently" in html.lower()

