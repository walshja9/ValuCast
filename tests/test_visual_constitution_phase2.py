import re
from pathlib import Path


CSS = (Path(__file__).parent.parent / "static" / "style.css").read_text()


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
