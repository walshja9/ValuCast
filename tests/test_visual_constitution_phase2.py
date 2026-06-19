import re
from pathlib import Path


ROOT = Path(__file__).parent.parent
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
DYNASTY_TEMPLATE = (
    ROOT / "templates" / "partials" / "player_detail_dynasty.html"
).read_text(encoding="utf-8")
SCOUTING_TEMPLATE = (ROOT / "templates" / "scouting.html").read_text(encoding="utf-8")
STATCAST_STORE = (ROOT / "web" / "statcast_store.py").read_text(encoding="utf-8")


def _blocks(selector: str) -> list[str]:
    return re.findall(rf"{re.escape(selector)}\s*\{{([^}}]+)\}}", CSS, flags=re.S)


def _last_block(selector: str) -> str:
    blocks = _blocks(selector)
    assert blocks, f"Missing CSS block for {selector}"
    return blocks[-1]


def _last_block_containing(selector: str, needle: str) -> str:
    blocks = [block for block in _blocks(selector) if needle in block]
    assert blocks, f"Missing CSS block for {selector} containing {needle}"
    return blocks[-1]


def _template_block(source: str, class_name: str) -> str:
    match = re.search(
        rf'<div class="{re.escape(class_name)}">\s*(.*?)\s*</div>',
        source,
        flags=re.S,
    )
    assert match, f"Missing template block for {class_name}"
    return match.group(1)


def test_active_controls_use_mode_tint_not_signal_or_function_blue():
    selectors = [
        ".mode-btn:has(input:checked)",
        ".htab.on",
        ".htab-prospects.on",
        ".seg-opt:has(input:checked) > span",
        ".source-opt:has(input:checked) > span",
        ".pool-btn:has(input:checked)",
        ".preset-btn.active",
        ".mode-btn-prospects:has(input:checked)",
        ".rank-by-toggle input:checked + span",
    ]

    for selector in selectors:
        block = _last_block(selector)
        assert "var(--c-dynasty)" in block, selector
        assert "rgba(167, 139, 250, .14)" in block, selector
        assert "background: var(--c-dynasty)" not in block, selector
        assert "color: #fff" not in block, selector
        assert "var(--c-blue)" not in block, selector
        assert "var(--c-blue-strong)" not in block, selector
        assert "var(--c-prospect)" not in block, selector
        assert "var(--c-signal)" not in block, selector


def test_functional_buttons_are_slate_not_signal_or_filled_blue():
    selectors = [
        ".rank-toolbar .graphic-btn",
        ".rank-toolbar .graphic-btn:hover",
        ".scouting-filters button",
    ]

    for selector in selectors:
        block = _last_block(selector)
        assert "var(--surface-2)" in block or "#23252c" in block, selector
        assert "var(--c-border-strong)" in block, selector
        assert "var(--c-text)" in block, selector
        assert "var(--c-signal)" not in block, selector
        assert "var(--c-prospect)" not in block, selector
        assert "var(--c-blue)" not in block, selector
        assert "var(--c-blue-strong)" not in block, selector
        assert "79, 134, 247" not in block, selector
        assert "110, 161, 255" not in block, selector
        assert "52, 226, 196" not in block, selector


def test_secondary_badges_are_slate_not_signal():
    selectors = [
        ".rank-chip",
        ".confidence-high",
        ".spread-chip.tight",
    ]

    for selector in selectors:
        block = _last_block_containing(selector, "color")
        assert "color: var(--c-muted)" in block, selector
        assert "var(--c-prospect)" not in block, selector
        assert "var(--c-signal)" not in block, selector
        assert "var(--c-positive-muted)" not in block, selector
        assert "52,226,196" not in block.replace(" ", ""), selector


def test_value_and_movement_keep_the_signal_lane():
    assert "var(--c-signal)" in _last_block(".rankings-table td.col-value")
    assert "var(--c-signal)" in _last_block(".value-spark polyline")
    assert "var(--c-signal)" in _last_block(".value-spark circle")
    assert "var(--c-signal)" in _last_block(".mover-chip.up") or "var(--c-pos)" in _last_block(
        ".mover-chip.up"
    )


def test_tier_is_a_left_edge_luminance_tick_not_a_colored_badge():
    # Wave 2C: tier reads as a 3px left-edge luminance ramp, T1 brightest → T5 darkest.
    ladder = {
        ".player-row.tier-1::before": "#e6eaf1",
        ".player-row.tier-2::before": "#b9c0ce",
        ".player-row.tier-3::before": "#8a93a4",
        ".player-row.tier-4::before": "#5e6678",
        ".player-row.tier-5::before": "#3e465a",
    }
    for selector, hex_value in ladder.items():
        assert hex_value in _last_block(selector), selector

    base = _last_block(".player-row::before")
    assert "width: 3px" in base
    assert "left: 0" in base
    # the in-name colored tier chip stays hidden — tier is the tick, not a badge
    assert "display: none" in _last_block(".rankings-table td.col-name > .tier-badge")


def test_name_links_inherit_text_not_functional_blue():
    block = _last_block_containing(".buys-main a", "color")
    assert "var(--c-text)" in block
    assert "var(--c-blue)" not in block


def test_data_bars_use_slate_teal_clay_not_functional_blue():
    # Phase 2: blue is functional-only (links/focus), never painted on data bars or dots.
    for selector in [".pct-rail-fill", ".spread-dot", ".role-probability-track"]:
        block = _last_block(selector)
        assert "var(--c-blue)" not in block, selector
        assert "110, 161, 255" not in block, selector
    # off-token teal retired from the profile skill bars
    assert "#2bcdb2" not in _last_block(".profile-bar-fill.good")


def test_redraft_detail_value_is_the_hero_not_muted():
    # Wave 2E: the redraft card value is the hero metric — keep its val-pos/val-neg
    # teal/clay, not the Phase-2 muted grey it was demoted to.
    block = _last_block(".detail-value")
    assert "var(--c-muted)" not in block


def test_bar_grammar_tokens_are_defined():
    for token in ["--bar-h", "--bar-h-rail", "--bar-radius", "--bar-rail"]:
        assert token in CSS


def test_data_bar_tracks_share_bar_grammar_tokens():
    selectors = [
        ".profile-bar-track",
        ".skill-compare-track",
        ".pct-rail",
        ".pct-track",
        ".role-probability-track",
        ".zbar",
        ".spread-rail",
    ]

    for selector in selectors:
        block = _last_block(selector)
        assert "var(--bar-rail)" in block, selector
        assert "var(--bar-radius)" in block, selector
        assert "999px" not in block, selector
        assert "#24262d" not in block, selector
        assert "rgba(39, 48, 74" not in block, selector


def test_statcast_percentile_ramp_matches_bar_palette_tokens():
    for token_tuple in ["(52, 226, 196)", "(94, 102, 120)", "(204, 138, 102)"]:
        assert token_tuple in STATCAST_STORE

    for retired in ["(52, 211, 153)", "#34d399", "(91, 102, 122)", "#5b667a"]:
        assert retired not in STATCAST_STORE


def test_prospect_profile_badges_only_hold_share_graphic_link():
    block = _template_block(DYNASTY_TEMPLATE, "profile-card-badges")

    assert "player-share-link" in block
    assert "Share graphic" in block
    assert "prospect_rank" not in block
    assert "dynasty_value" not in block
    assert "P#" not in block
    assert "VAL " not in block
    assert "T{{ row.tier" not in block


def test_dynasty_headline_uses_one_context_line_for_secondary_metadata():
    block = _template_block(DYNASTY_TEMPLATE, "dynasty-headline")

    assert 'class="headline-value"' in block
    assert 'class="headline-context"' in block
    assert "headline-range" not in block
    assert "headline-tier" not in block
    assert "confidence-chip" not in block
    assert "row.eta" in block
    assert "  ·  " in block
    assert "–" in block
    assert '<span class="stat-label">ETA</span>' not in DYNASTY_TEMPLATE

    css = _last_block(".headline-context")
    assert "font-family: var(--font-mono)" in css
    assert "color: var(--c-muted)" in css
    assert "font-size: .74rem" in css
    assert "background" not in css
    assert "border:" not in css
    assert "border-radius" not in css


def test_scouting_meta_is_single_muted_mono_line_not_chip_stack():
    block = _template_block(SCOUTING_TEMPLATE, "scouting-meta")

    assert block.count("<span") == 1
    assert 'class="scouting-meta-line"' in block
    for label in [
        "report.status_label",
        "report.sample_label",
        "report.movement_label",
        "report.buy_rank_label",
        "report.card_status_label",
        "report.confidence_label",
    ]:
        assert label in block
    assert "  ·  " in block
    assert "Open board" in block
    assert "Share graphic" in block

    span_css = _last_block(".scouting-meta span")
    assert "font-family: var(--font-mono)" in span_css
    assert "color: var(--c-muted)" in span_css
    assert "background" not in span_css
    assert "border:" not in span_css
    assert "border-radius" not in span_css

    link_css = _last_block(".scouting-meta a")
    assert "var(--c-blue)" in link_css
    assert "text-decoration" in link_css
