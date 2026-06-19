"""Shared HTML wrappers for static share-card PNG routes."""

from __future__ import annotations

from html import escape


def build_share_preview_html(
    *,
    title: str,
    subtitle: str,
    png_url: str,
    filename: str,
    public_png_url: str,
    public_page_url: str,
    description: str,
    image_alt: str,
    back_url: str,
    back_label: str,
) -> str:
    """Return the small branded preview/download shell for a share PNG."""
    safe_title = escape(title)
    safe_subtitle = escape(subtitle)
    safe_png_url = escape(png_url)
    safe_public_png_url = escape(public_png_url)
    safe_public_page_url = escape(public_page_url)
    safe_description = escape(description)
    safe_filename = escape(filename)
    safe_alt = escape(image_alt)
    safe_back_url = escape(back_url)
    safe_back_label = escape(back_label)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title} | ValuCast</title>
  <meta name="description" content="{safe_description}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="ValuCast">
  <meta property="og:title" content="{safe_title} | ValuCast">
  <meta property="og:description" content="{safe_description}">
  <meta property="og:url" content="{safe_public_page_url}">
  <meta property="og:image" content="{safe_public_png_url}">
  <meta property="og:image:width" content="1080">
  <meta property="og:image:height" content="1350">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{safe_title} | ValuCast">
  <meta name="twitter:description" content="{safe_description}">
  <meta name="twitter:image" content="{safe_public_png_url}">
  <style>
    body {{ margin: 0; background: #0b0c0f; color: #e8e9ee; font-family: "Space Grotesk", system-ui, "Segoe UI", Helvetica, Arial, sans-serif; }}
    main {{ min-height: 100vh; display: grid; place-items: center; gap: 16px; padding: 24px; }}
    .meta, .actions, .card-wrap {{ width: min(1080px, 100%); }}
    h1 {{ margin: 0 0 4px; color: #f4f5f8; font-size: 22px; font-weight: 600; }}
    p {{ margin: 0; color: #9197a6; font-weight: 500; }}
    img {{ width: 100%; height: auto; display: block; border-radius: 16px; box-shadow: 0 24px 80px rgba(0,0,0,.5); }}
    .actions {{ display: flex; justify-content: flex-end; gap: 12px; align-items: center; }}
    .download {{ color: #06231e; background: #34e2c4; border-radius: 8px; padding: 10px 16px; text-decoration: none; font-weight: 700; }}
    .back {{ color: #9197a6; text-decoration: none; font-weight: 600; }}
  </style>
</head>
<body>
  <main>
    <div class="meta">
      <h1>{safe_title}</h1>
      <p>{safe_subtitle}</p>
    </div>
    <div class="card-wrap"><img src="{safe_png_url}" alt="{safe_alt}"></div>
    <div class="actions">
      <a class="back" href="{safe_back_url}">{safe_back_label}</a>
      <a class="download" href="{safe_png_url}" download="{safe_filename}">Download PNG</a>
    </div>
  </main>
</body>
</html>"""
