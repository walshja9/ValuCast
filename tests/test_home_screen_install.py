import json
from pathlib import Path

from PIL import Image

from app import app


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "static" / "app.webmanifest"


def test_install_manifest_contract_and_icons():
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert payload == {
        "id": "/",
        "name": "ValuCast",
        "short_name": "ValuCast",
        "description": "Fantasy baseball values, prospect intelligence, and league-aware decisions.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#12131f",
        "theme_color": "#12131f",
        "icons": [
            {
                "src": "/static/brand/valucast-mark-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": "/static/brand/valucast-mark-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any",
            },
        ],
    }

    for icon in payload["icons"]:
        path = ROOT / icon["src"].lstrip("/")
        assert path.exists()
        expected = tuple(int(part) for part in icon["sizes"].split("x"))
        with Image.open(path) as image:
            assert image.size == expected


def test_every_full_page_links_the_install_manifest():
    client = app.test_client()
    for path in ("/", "/methodology", "/trade"):
        response = client.get(path)
        assert response.status_code == 200
        assert b'rel="manifest"' in response.data
        assert b'href="/static/app.webmanifest"' in response.data
