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
    # Day 20 (matured: headline counts only 14d+ calls): field moved toward us
    # (median 55). catch_up = 85 - 55 = 30 — well past the noise floor
    # (max(10, 15% of 75) = 11.25) -> open_toward.
    _board(tmp_path, "2026-06-20", [_row(1, 10, {"pipeline": 50, "hkb": 60})])

    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-06-20T00:00:00+00:00")

    call = payload["calls"][0]
    assert call["ahead_since"] == "2026-06-01"     # earliest guarded date, not day 20
    assert call["consensus_then"] == 85
    assert call["consensus_now"] == 55
    assert call["consensus_catch_up"] == 30
    assert call["status"] == "open_toward"
    assert payload["funnel"]["open_toward"] == 1
    assert payload["summary"]["wins"] == 1
    # 19-day horizon is below the publish gate -> number stays withheld.
    assert payload["gate"]["publishable"] is False
    # Independence firewall.
    assert payload["source_policy"]["feeds_model_score"] is False


def test_field_moving_away_is_not_a_win(tmp_path):
    _board(tmp_path, "2026-06-01", [_row(1, 10, {"pipeline": 60, "hkb": 70})])   # median 65
    _board(tmp_path, "2026-06-20", [_row(1, 10, {"pipeline": 90, "hkb": 100})])  # median 95 -> AWAY
    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-06-20T00:00:00+00:00")
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
    _board(tmp_path, "2026-06-20", [_row(1, 70, {"pipeline": 78, "hkb": 88})])   # gap 13 < guard
    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-06-20T00:00:00+00:00")
    call = payload["calls"][0]
    assert call["status"] == "retired_we_backed_off"
    assert payload["funnel"]["retired_we_backed_off"] == 1
    assert payload["summary"]["decided_count"] == 1
    assert payload["summary"]["decided_rate"] == 0.0


def test_full_catch_up_that_closes_the_gap_is_a_terminal_win(tmp_path):
    # Field comes all the way to VC (median 85 -> 18) while VC holds: the call
    # leaves the guarded set as closed_caught_up — a WIN the v1 metric dropped.
    _board(tmp_path, "2026-06-01", [_row(1, 10, {"pipeline": 80, "hkb": 90})])
    _board(tmp_path, "2026-06-20", [_row(1, 10, {"pipeline": 16, "hkb": 20})])
    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-06-20T00:00:00+00:00")
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
    _board(tmp_path, "2026-06-20", day2)
    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-06-20T00:00:00+00:00")
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


def test_headline_counts_only_matured_calls(tmp_path):
    # Registered maturity rule (7/12 compliance fix): the headline decided-rate
    # counts only calls >= 14 days old. Two retreats — one matured (19d), one
    # young (2d): the young one sits in the funnel and immature_decided, NOT in
    # the headline denominator.
    _board(tmp_path, "2026-06-01", [_row(1, 10, {"pipeline": 80, "hkb": 90})])
    _board(tmp_path, "2026-06-18", [
        _row(1, 10, {"pipeline": 80, "hkb": 90}),
        _row(2, 10, {"pipeline": 80, "hkb": 90}),
    ])
    _board(tmp_path, "2026-06-20", [
        _row(1, 70, {"pipeline": 78, "hkb": 88}),   # matured retreat (gap 13 < guard)
        _row(2, 70, {"pipeline": 78, "hkb": 88}),   # 2-day-old retreat
    ])
    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-06-20T00:00:00+00:00")
    assert payload["funnel"]["retired_we_backed_off"] == 2   # full account keeps both
    assert payload["summary"]["decided_count"] == 1          # headline: matured only
    assert payload["summary"]["wins"] == 0
    assert payload["summary"]["decided_rate"] == 0.0
    assert payload["summary"]["immature_decided"] == 1       # excluded, never hidden


def test_control_lift_compares_matured_with_matured(tmp_path):
    # 7/12 compliance fix regression lock: lift = matured open calls vs matured
    # controls. A young open call must NOT dilute the numerator (the old
    # all-calls lift here would read 0.5; the registered matured lift is 1.0).
    _board(tmp_path, "2026-06-01", [
        _row(1, 10, {"pipeline": 80, "hkb": 90}),   # the matured call, consensus 85
        _row(2, 84, {"pipeline": 78, "hkb": 92}),   # never-flagged control, consensus 85
    ])
    _board(tmp_path, "2026-06-18", [_row(3, 10, {"pipeline": 80, "hkb": 90})])  # young call
    _board(tmp_path, "2026-06-20", [
        _row(1, 10, {"pipeline": 50, "hkb": 60}),   # call: field came +30 -> toward
        _row(2, 84, {"pipeline": 48, "hkb": 62}),   # control: field came +30 -> toward
        _row(3, 10, {"pipeline": 80, "hkb": 90}),   # young call: flat
    ])
    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-06-20T00:00:00+00:00")
    assert payload["summary"]["matured_open_rates"]["toward_rate"] == 1.0
    assert payload["summary"]["open_rates"]["toward_rate"] == 0.5   # diluted by the young flat
    assert payload["summary"]["control_lift"] == 1.0                # matured / matured


def test_as_of_date_filters_the_archive(tmp_path):
    # Replay support for the stabilized window: as_of_date must make the build
    # see only archives on or before that date (so a past build reproduces).
    from scripts.build_ahead_of_consensus_scorecard import build_scorecard
    _board(tmp_path, "2026-06-01", [_row(1, 10, {"pipeline": 80, "hkb": 90})])
    _board(tmp_path, "2026-06-20", [_row(1, 10, {"pipeline": 50, "hkb": 60})])
    early = build_scorecard(archive_dir=tmp_path,
                            generated_at="2026-06-01T00:00:00+00:00", as_of_date="2026-06-01")
    late = build_scorecard(archive_dir=tmp_path,
                           generated_at="2026-06-20T00:00:00+00:00", as_of_date="2026-06-20")
    assert early["summary"]["horizon_days"] == 0     # only 6-01 visible
    assert late["summary"]["horizon_days"] == 19      # both boards visible


def test_stabilized_window_is_additive_summary_of_daily(tmp_path):
    # The stabilized read replays the SAME daily metric over a trailing window
    # and aggregates it. Assert the mechanics + invariants (mean inside min/max,
    # never claims more readings than the window), not exact values.
    import datetime as _dt
    from scripts.build_ahead_of_consensus_scorecard import (
        _stabilized_window, STABILIZED_WINDOW_DAYS, STABILIZED_MIN_READINGS,
    )
    # 20 consecutive boards; the field steadily creeps toward VC #10, with a
    # matched control in the same band.
    for i in range(20):
        d = (_dt.date(2026, 6, 1) + _dt.timedelta(days=i)).isoformat()
        cons = max(20, 90 - i * 3)
        _board(tmp_path, d, [
            _row(1, 10, {"pipeline": cons - 5, "hkb": cons + 5}),
            _row(2, cons, {"pipeline": cons - 5, "hkb": cons + 5}),
        ])
    stab = _stabilized_window(archive_dir=tmp_path)
    assert stab["window_days"] == STABILIZED_WINDOW_DAYS
    assert len(stab["readings"]) == STABILIZED_WINDOW_DAYS      # last 14 of 20
    for key in ("decided_rate", "control_lift"):
        agg = stab[key]
        if agg is not None:
            assert agg["min"] <= agg["mean"] <= agg["max"]
            assert 0 < agg["n"] <= STABILIZED_WINDOW_DAYS
    # publishable iff enough valid decided-rate readings accumulated
    dr = stab["decided_rate"]
    assert stab["publishable"] == (bool(dr) and dr["n"] >= STABILIZED_MIN_READINGS)


def test_run_scorecard_writes_stabilized_into_artifact(tmp_path):
    # The written artifact must carry summary.stabilized (additive) without the
    # daily headline changing.
    from scripts.build_ahead_of_consensus_scorecard import build_scorecard, run_scorecard
    _board(tmp_path, "2026-06-01", [_row(1, 10, {"pipeline": 80, "hkb": 90})])
    _board(tmp_path, "2026-06-20", [_row(1, 10, {"pipeline": 50, "hkb": 60})])
    art = tmp_path / "sc.json"
    daily = build_scorecard(archive_dir=tmp_path)
    run_scorecard(archive_dir=tmp_path, artifact_path=art)
    written = json.loads(art.read_text(encoding="utf-8"))
    assert "stabilized" in written["summary"]
    # daily headline untouched by the additive summary
    assert written["summary"]["decided_rate"] == daily["summary"]["decided_rate"]
    assert written["summary"]["control_lift"] == daily["summary"]["control_lift"]


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

    assert "TRACK RECORD" in html
    assert "We backed off" in html                      # misses are on the page
    assert "Our retreats" in html                       # ...and in the funnel tiles
    assert "/aotc-scorecard.json" in html               # raw artifact still linked

    # 7/9 claims-register gap (c): the leading tile must NOT sum provisional
    # open_toward into a bare green "Wins" number. It splits final vs trending
    # so the headline stops implying 31 final wins when 23 are still provisional.
    # (Assert on the TILE label span, not a bare ">Wins<" -- the outcome filter
    # pill legitimately still says "Wins".)
    assert '<span class="ledger-tile-label">Leading</span>' in html
    assert '<span class="ledger-tile-label">Wins</span>' not in html
    assert "caught up" in html and "trending our way" in html  # both counts distinct
    # 7/12 audit F6: the ledger must disclose the field-consensus vintage — the
    # scorecard restamps daily while source boards age on their own schedules.
    assert "Field-consensus vintage" in html
    # 7/12 audit: statuses recompute every build and can reopen — the page must
    # never promise a finality the code cannot deliver (King/Bitonti flapped
    # closed->open in the real archive while the copy said "final").
    assert "are final" not in html
    assert '"final"' not in html and "5 final" not in html
    assert "nothing is hand-frozen" in html
    assert "no call ever leaves this page silently" in html.lower()
    assert 'data-ledger-filter="retreat"' in html       # outcome filter pills
    assert 'data-ledger-filter="resolved"' in html      # resolved != undecided
    assert "conviction, not evidence" in html           # worked-example explainer
    # The decided-rate and matched-control lift use different populations. The
    # public sentence must not make the lift look derived from wins/decided.
    assert "matured decided calls" in html
    assert "Separately, among still-open matured calls" in html
    assert "matched controls" in html
    # 7/3 retention-cohort disclosure: policy-change entries are labeled,
    # never silent — and never curated out (scoring fields stay frozen).
    assert "Board policy change 2026-07-02" in html
    assert "ledger-chip-mlb" in html

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
    _board(tmp_path, "2026-06-20", [_row(1, 70, {"pipeline": 80})])
    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-06-20T00:00:00+00:00")
    call = payload["calls"][0]
    assert call["status"] == "retired_we_backed_off"
    assert payload["summary"]["decided_count"] == 1


def test_active_mlb_first_appearance_never_enrolls(tmp_path):
    # Rookie-retention rows are stamped active_mlb_roster in the archive from
    # 7/4 on. A player whose FIRST guarded appearance is stamped (Guzman case:
    # in the majors, boards delisting him faked the gap) must never open a call.
    row = _row(1, 15, {"pipeline": 250, "hkb": 280, "sts": 290})
    row["active_mlb_roster"] = True
    _board(tmp_path, "2026-07-04", [row])
    _board(tmp_path, "2026-07-05", [row])
    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-07-05T00:00:00+00:00")
    assert payload["calls"] == []
    assert all(count == 0 for count in payload["funnel"].values())


def test_call_opened_in_minors_survives_later_debut(tmp_path):
    # Enrollment is the ONLY place the stamp is consulted: a call opened while
    # the player was in the minors keeps its lifecycle after he debuts -- the
    # debut is the receipt, not a reason to erase the call.
    _board(tmp_path, "2026-07-04", [_row(1, 10, {"pipeline": 80, "hkb": 90})])
    stamped = _row(1, 10, {"pipeline": 50, "hkb": 60})
    stamped["active_mlb_roster"] = True
    _board(tmp_path, "2026-07-08", [stamped])
    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-07-08T00:00:00+00:00")
    call = payload["calls"][0]
    assert call["ahead_since"] == "2026-07-04"
    assert call["status"] == "open_toward"
    assert payload["funnel"]["open_toward"] == 1


def test_option_down_opens_a_fresh_dated_call(tmp_path):
    # A call-up optioned back to the minors is a genuine minor-league
    # divergence again: the first UNSTAMPED guarded day opens a new call dated
    # from the option-down, never backdated into his MLB stint.
    stamped = _row(1, 15, {"pipeline": 250, "hkb": 280, "sts": 290})
    stamped["active_mlb_roster"] = True
    _board(tmp_path, "2026-07-04", [stamped])
    _board(tmp_path, "2026-07-10", [_row(1, 15, {"pipeline": 250, "hkb": 280, "sts": 290})])
    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-07-10T00:00:00+00:00")
    call = payload["calls"][0]
    assert call["ahead_since"] == "2026-07-10"
    assert call["status"].startswith("open_")


def test_active_mlb_rows_never_serve_as_controls(tmp_path):
    # Symmetry with enrollment: boards delisting a retained call-up drags his
    # "catch-up" negative, so letting him be a matched CONTROL would inflate
    # control_lift in ValuCast's favor. Stamped rows are excluded from the pool.
    call_row = _row(1, 10, {"pipeline": 80, "hkb": 90})                      # the call, consensus 85
    ctrl_clean = _row(2, 200, {"pipeline": 78, "hkb": 88})                   # clean control, consensus 83
    ctrl_mlb = _row(3, 201, {"pipeline": 79, "hkb": 89})                     # in-MLB by day 2
    _board(tmp_path, "2026-07-04", [call_row, ctrl_clean, ctrl_mlb])
    day2_mlb = _row(3, 201, {"pipeline": 300, "hkb": 320})                   # delisting artifact
    day2_mlb["active_mlb_roster"] = True
    _board(
        tmp_path,
        "2026-07-08",
        [_row(1, 10, {"pipeline": 50, "hkb": 60}), ctrl_clean, day2_mlb],
    )
    payload = build_scorecard(archive_dir=tmp_path, generated_at="2026-07-08T00:00:00+00:00")
    assert payload["summary"]["control_rates"]["n"] == 1  # only the clean control


def test_track_record_context_composes_existing_artifacts_and_rates(monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "SCOREBOARD_HOLD", False)
    monkeypatch.setattr(app_module, "RECEIPTS_HOLD", False)
    monkeypatch.setattr(app_module, "_load_scorecard_payload", lambda: {"artifact": "consensus"})
    monkeypatch.setattr(app_module, "_load_forward_scoreboard_payload", lambda: {
        "anticipation_score": {"pool_size": 70, "provisional": True},
        "funnel": {
            "wins": 39,
            "losses": 31,
            "open": 102,
            "total_claims": 258,
            "excluded_from_pool": 188,
            "unscored_or_unclassified": 0,
            "buckets": {"clean_retraction": 86},
            "self_retraction_rate": {"retracted": 117, "total": 258, "rate": 117 / 258},
        },
        "cohorts": {"cohort_count": 4},
    })
    monkeypatch.setattr(app_module, "_load_receipts_payload", lambda: {
        "generated_at": "2026-07-21T00:00:00+00:00",
        "receipts": [{"name": str(i)} for i in range(7)],
        "misses": [],
        "no_claim_rows": [{"name": str(i)} for i in range(33)],
        "summary": {
            "no_claim_call_up_count": 33,
            "maturation": {"pending": 7, "confirmed": 0, "decayed": 0},
        },
    })

    context = app_module._track_record_context()

    assert context["sc"] == {"artifact": "consensus"}
    assert context["forward_sc"]["wins"] == 39
    assert context["forward_sc"]["losses"] == 31
    assert context["forward_sc"]["win_rate_pct"] == 56
    assert context["forward_sc"]["clean_retractions"] == 86
    assert context["receipt_count"] == 7
    assert context["miss_count"] == 0
    assert context["no_claim_call_up_count"] == 33


def test_track_record_context_respects_both_hold_gates(monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "SCOREBOARD_HOLD", True)
    monkeypatch.setattr(app_module, "RECEIPTS_HOLD", True)
    monkeypatch.setattr(app_module, "_load_scorecard_payload", lambda: {"artifact": "consensus"})
    monkeypatch.setattr(
        app_module,
        "_load_forward_scoreboard_payload",
        lambda: (_ for _ in ()).throw(AssertionError("held scoreboard was loaded")),
    )

    context = app_module._track_record_context()

    assert context["forward_sc"] is None
    assert context["receipts_available"] is False
    assert context["receipt_count"] == 0
    assert context["miss_count"] == 0
    assert context["no_claim_call_up_count"] == 0


def test_track_record_explains_three_evidence_lanes_with_denominators(monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "SCOREBOARD_HOLD", False)
    monkeypatch.setattr(app_module, "RECEIPTS_HOLD", False)
    monkeypatch.setattr(app_module, "_load_forward_scoreboard_payload", lambda: {
        "anticipation_score": {"pool_size": 70, "provisional": True},
        "funnel": {
            "wins": 39,
            "losses": 31,
            "open": 102,
            "total_claims": 258,
            "excluded_from_pool": 188,
            "unscored_or_unclassified": 0,
            "buckets": {"clean_retraction": 86},
            "self_retraction_rate": {"retracted": 117, "total": 258, "rate": 117 / 258},
        },
        "cohorts": {"cohort_count": 4},
    })
    monkeypatch.setattr(app_module, "_load_receipts_payload", lambda: {
        "receipts": [{"name": str(i)} for i in range(7)],
        "misses": [],
        "no_claim_rows": [{"name": str(i)} for i in range(33)],
        "summary": {"no_claim_call_up_count": 33, "maturation": {"pending": 7}},
    })

    html = app_module.app.test_client().get("/ledger").data.decode("utf-8")

    assert "TRACK RECORD" in html
    assert "Forward Calls" in html
    assert "39–31 across 70 scored calls (56%)" in html
    assert "86 clean retractions" in html and "102 open" in html
    assert "Consensus Movement" in html
    assert "mature decisions" in html and "matched controls" in html
    assert "Call-Up Timing" in html
    assert "7 clearly ahead" in html and "0 clearly behind" in html
    assert "33 without a large enough ranking gap to score" in html


def test_track_record_discloses_exact_call_up_thresholds():
    from app import app
    from prospects.ahead_of_consensus import MAX_VALUCAST_RANK, MIN_BOARDS, MIN_DIVERGENCE
    from prospects.call_up_receipts import FIELD_UNRANKED_MAX_VALUCAST_RANK

    html = app.test_client().get("/ledger").data.decode("utf-8")

    assert f"at least {MIN_BOARDS} public boards" in html
    assert "inside the top 600" in html
    assert f"top {MAX_VALUCAST_RANK}" in html
    assert f"{MIN_DIVERGENCE} places" in html
    assert f"top-{FIELD_UNRANKED_MAX_VALUCAST_RANK}" in html
    assert "no scoreable ranking gap" in html
    assert "eligible prior call" not in html

