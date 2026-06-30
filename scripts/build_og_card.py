"""Generate static/og-card.png — the 1200x630 social-link preview banner — from the
app's glass brand helpers (anti-aliased curve, glass-V emblem, glossy wordmark) so it
matches the share cards. Re-run when branding changes:
    python scripts/build_og_card.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

import app  # noqa: E402

W, H = 1200, 630


def build_og_card() -> Path:
    palette = app._GRAPHIC_PALETTE
    img = Image.new("RGB", (W, H), palette["bg"])
    app._graphic_fill_background(img)
    draw = ImageDraw.Draw(img)

    # Rising brand swoosh, top-right (anti-aliased via the shared curve helper).
    app._graphic_brand_curve(img, draw, x0=700, y0=250, x1=1150, y1=90)

    # Brand lockup, vertically centered on the left: glass-V emblem + glossy wordmark.
    app._paste_brand_mark(img, 90, 250, size=132)
    app._draw_glass_text(img, draw, (252, 270), "VALUCAST", app._graphic_font(86, bold=True))
    draw.text((258, 382), "Ahead of the Curve", fill=palette["muted"], font=app._graphic_font(30, bold=True))
    draw.text((258, 426), "Independent player values tuned to your league",
              fill=palette["slate"], font=app._graphic_font(24))

    draw.text((90, 556), "valucast.app", fill=palette["teal"], font=app._graphic_font(26, bold=True))

    out = ROOT / "static" / "og-card.png"
    img.save(out, format="PNG", optimize=True)
    return out


if __name__ == "__main__":
    path = build_og_card()
    print(f"wrote {path} ({W}x{H})")
