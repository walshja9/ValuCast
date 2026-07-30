# ValuCast Home-Screen Installation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ValuCast installable from supported browsers as a standalone home-screen web app with a visible, accessible installation path.

**Architecture:** Add a static web app manifest and link it from the shared base template. A dependency-free external controller reveals one footer button only when the browser can install ValuCast or when an iPhone/iPad needs Add to Home Screen instructions; no service worker or application-data cache is introduced.

**Tech Stack:** Flask/Jinja templates, static JSON, vanilla JavaScript, CSS, pytest, Pillow.

## Global Constraints

- Reuse `static/brand/valucast-mark-192.png` and `static/brand/valucast-mark-512.png`.
- Use `#12131f` for manifest background and theme colors.
- Launch `/` with manifest `id`, `start_url`, and `scope` all rooted at `/`.
- Use `display: standalone`.
- Add no dependency, service worker, offline cache, notification, badge, background sync, app shortcut, native wrapper, model change, data artifact change, workflow change, or CSP change.
- The install control must be hidden when installed or unsupported.
- Dynamic boards, cards, and trade pages remain network-only.

---

### Task 1: Installability manifest and shared-page contract

**Files:**
- Create: `static/app.webmanifest`
- Create: `tests/test_home_screen_install.py`
- Modify: `templates/base.html:4-25`

**Interfaces:**
- Consumes: Existing 192px and 512px PNG files under `static/brand/`.
- Produces: A root-scoped manifest linked from every page through `templates/base.html`.

- [ ] **Step 1: Run the relevant baseline**

Run:

```powershell
python -m pytest tests/test_ui_a11y.py tests/test_public_surfaces_smoke.py -q
```

Expected: all selected tests pass before feature changes.

- [ ] **Step 2: Write the failing manifest contract**

Create `tests/test_home_screen_install.py`:

```python
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
        assert Image.open(path).size == expected


def test_every_full_page_links_the_install_manifest():
    client = app.test_client()
    for path in ("/", "/methodology", "/trade"):
        response = client.get(path)
        assert response.status_code == 200
        assert b'rel="manifest"' in response.data
        assert b'href="/static/app.webmanifest"' in response.data
```

- [ ] **Step 3: Run the test and verify RED**

Run:

```powershell
python -m pytest tests/test_home_screen_install.py -q
```

Expected: FAIL because `static/app.webmanifest` does not exist.

- [ ] **Step 4: Add the manifest**

Create `static/app.webmanifest`:

```json
{
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
      "purpose": "any"
    },
    {
      "src": "/static/brand/valucast-mark-512.png",
      "sizes": "512x512",
      "type": "image/png",
      "purpose": "any"
    }
  ]
}
```

- [ ] **Step 5: Link the manifest from the shared base**

In `templates/base.html`, immediately after the theme-color meta tag, add:

```html
    <link rel="manifest" href="{{ url_for('static', filename='app.webmanifest') }}">
```

- [ ] **Step 6: Run the test and verify GREEN**

Run:

```powershell
python -m pytest tests/test_home_screen_install.py -q
```

Expected: 2 passed.

- [ ] **Step 7: Commit the manifest slice**

```powershell
git add static/app.webmanifest templates/base.html tests/test_home_screen_install.py
git commit -m "feat: add ValuCast install manifest"
```

---

### Task 2: Accessible install control and browser controller

**Files:**
- Create: `static/install-app.js`
- Modify: `templates/base.html:20-95`
- Modify: `static/style.css:1080-1110`
- Modify: `tests/test_home_screen_install.py`

**Interfaces:**
- Consumes: `#install-app-button` and `#install-app-dialog` from the base template; browser `beforeinstallprompt`, `appinstalled`, `matchMedia`, and navigator properties.
- Produces: A hidden-by-default install button that either opens the native prompt or iPhone/iPad instructions.

- [ ] **Step 1: Write the failing UI/controller contracts**

Append to `tests/test_home_screen_install.py`:

```python
def test_install_control_is_accessible_and_hidden_by_default():
    html = app.test_client().get("/").data

    assert b'id="install-app-button"' in html
    assert b'type="button"' in html
    assert b'Install ValuCast' in html
    assert b'id="install-app-dialog"' in html
    assert b'aria-labelledby="install-app-title"' in html
    assert b'Share' in html
    assert b'Add to Home Screen' in html
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
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
python -m pytest tests/test_home_screen_install.py -q
```

Expected: three new failures because the button, dialog, controller, and styles do not exist.

- [ ] **Step 3: Add the hidden button and instruction dialog**

In `templates/base.html`, inside `.site-footer` after `#footer-provenance`, add:

```html
        <button type="button" id="install-app-button" class="footer-install" hidden>Install ValuCast</button>
```

After the closing `</footer>`, add:

```html
    <dialog id="install-app-dialog" class="install-app-dialog" aria-labelledby="install-app-title">
        <form method="dialog">
            <h2 id="install-app-title">Install ValuCast</h2>
            <p>Open the Share menu, then choose <strong>Add to Home Screen</strong>.</p>
            <div class="install-app-dialog-actions">
                <button type="submit">Close</button>
            </div>
        </form>
    </dialog>
```

In the document head after `htmx.min.js`, add:

```html
    <script src="{{ url_for('static', filename='install-app.js') }}" defer></script>
```

- [ ] **Step 4: Add the minimal install controller**

Create `static/install-app.js`:

```javascript
(function () {
    "use strict";

    const button = document.getElementById("install-app-button");
    const dialog = document.getElementById("install-app-dialog");
    if (!button) return;

    const installed =
        window.matchMedia("(display-mode: standalone)").matches ||
        window.navigator.standalone === true;
    if (installed) return;

    const navigator = window.navigator;
    const isiPhoneOrIPad =
        /iphone|ipad|ipod/i.test(navigator.userAgent) ||
        (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    let installPrompt = null;

    if (isiPhoneOrIPad && dialog && typeof dialog.showModal === "function") {
        button.hidden = false;
    }

    window.addEventListener("beforeinstallprompt", function (event) {
        event.preventDefault();
        installPrompt = event;
        button.hidden = false;
    });

    button.addEventListener("click", async function () {
        if (installPrompt) {
            const prompt = installPrompt;
            installPrompt = null;
            button.hidden = true;
            await prompt.prompt();
            return;
        }
        if (isiPhoneOrIPad && dialog && typeof dialog.showModal === "function") {
            dialog.showModal();
        }
    });

    window.addEventListener("appinstalled", function () {
        installPrompt = null;
        button.hidden = true;
        if (dialog && dialog.open) dialog.close();
    });
}());
```

- [ ] **Step 5: Add focused footer/dialog styles**

After the existing `.site-footer` block in `static/style.css`, add:

```css
.footer-install {
    min-height: 44px;
    margin-top: .55rem;
    padding: .45rem .8rem;
    border: 1px solid var(--c-border-strong);
    border-radius: var(--radius-sm);
    background: var(--surface-2);
    color: var(--c-text);
    cursor: pointer;
    font: inherit;
    font-weight: 700;
}
.footer-install:hover { border-color: var(--c-signal); }
.footer-install:focus-visible {
    outline: 2px solid var(--c-blue-strong);
    outline-offset: 2px;
}
.install-app-dialog {
    width: min(420px, calc(100vw - 32px));
    padding: 1.1rem;
    border: 1px solid var(--c-border-strong);
    border-radius: var(--radius-lg);
    background: var(--surface);
    color: var(--c-text);
    box-shadow: var(--shadow-soft);
}
.install-app-dialog::backdrop { background: rgba(0, 0, 0, .72); }
.install-app-dialog h2 { margin: 0 0 .55rem; font-size: 1.15rem; }
.install-app-dialog p { margin: 0; color: var(--c-muted); line-height: 1.55; }
.install-app-dialog-actions { margin-top: 1rem; text-align: right; }
.install-app-dialog-actions button {
    min-height: 44px;
    padding: .45rem .8rem;
    border: 1px solid var(--c-border-strong);
    border-radius: var(--radius-sm);
    background: var(--surface-2);
    color: var(--c-text);
    cursor: pointer;
    font: inherit;
    font-weight: 700;
}
.install-app-dialog-actions button:focus-visible {
    outline: 2px solid var(--c-blue-strong);
    outline-offset: 2px;
}
```

- [ ] **Step 6: Run focused tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_home_screen_install.py tests/test_ui_a11y.py tests/test_public_surfaces_smoke.py -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit the install experience**

```powershell
git add static/install-app.js static/style.css templates/base.html tests/test_home_screen_install.py
git commit -m "feat: add home-screen install control"
```

---

### Task 3: Browser and regression verification

**Files:**
- Verify only; no production file changes expected.

**Interfaces:**
- Consumes: Completed manifest and install controller from Tasks 1 and 2.
- Produces: Evidence that the feature is safe to submit for review.

- [ ] **Step 1: Run the complete automated suite**

Run:

```powershell
python -m pytest -q
```

Expected: the full suite passes with only the repository's previously documented skips.

- [ ] **Step 2: Run source-integrity checks**

Run:

```powershell
git diff --check origin/master...HEAD
git status --short
```

Expected: no whitespace errors and a clean worktree.

- [ ] **Step 3: Verify locally in a browser**

Start the application, then open `http://127.0.0.1:5010/`:

```powershell
$env:FLASK_APP='app.py'
python -m flask run --port 5010
```

Verify:

1. Desktop Chromium exposes **Install ValuCast** only after
   `beforeinstallprompt`.
2. The manifest reports ValuCast, `/`, standalone display, and both icons.
3. Installed-mode emulation hides the install control.
4. iPhone/iPad emulation shows the Share > Add to Home Screen dialog.
5. Board filtering, player-card navigation, `/trade`, and share actions still
   use live network responses.
6. DevTools shows no service worker registration and no Cache Storage entries
   created by ValuCast.

Expected: all six checks pass.

- [ ] **Step 4: Record final verification in the PR body**

Include:

```text
Home-screen install verification
- Manifest and icons: PASS
- Desktop native prompt path: PASS
- iPhone/iPad instruction path: PASS
- Installed/unsupported suppression: PASS
- No service worker or application-data cache: PASS
- Full pytest suite: PASS
```
