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

    response = app.test_client().get("/static/app.webmanifest")
    assert response.status_code == 200
    assert response.mimetype == "application/manifest+json"


def test_every_full_page_links_the_install_manifest():
    client = app.test_client()
    for path in ("/", "/methodology", "/trade"):
        response = client.get(path)
        assert response.status_code == 200
        assert b'rel="manifest"' in response.data
        assert b'href="/static/app.webmanifest"' in response.data


def test_install_control_is_accessible_and_hidden_by_default():
    html = app.test_client().get("/").data

    assert b'id="install-app-button"' in html
    assert b'type="button"' in html
    assert b'class="footer-install" hidden' in html
    assert b"Install ValuCast" in html
    assert b'id="install-app-dialog"' in html
    assert b'aria-labelledby="install-app-title"' in html
    assert b"Share" in html
    assert b"Add to Home Screen" in html
    assert b'src="/static/install-app.js"' in html


def test_install_controller_has_all_fail_closed_paths():
    script = (ROOT / "static" / "install-app.js").read_text(encoding="utf-8")

    for marker in (
        "beforeinstallprompt",
        "appinstalled",
        "(display-mode: standalone)",
        "navigator.standalone",
        "maxTouchPoints",
        "showModal",
    ):
        assert marker in script
    assert "serviceWorker" not in script
    assert "caches." not in script


def test_install_styles_preserve_tap_target_and_native_dialog():
    css = app.test_client().get("/static/style.css").data

    assert b".footer-install" in css
    assert b"min-height: 44px" in css
    assert b".install-app-dialog::backdrop" in css
