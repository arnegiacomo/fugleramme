# The kiosk and the admin

Covers the `web/` package.

- `web/` is the kiosk and the admin: `server.py` is routing and transport only, `admin.py` builds the page from a `modes.Context`, `hostinfo.py` probes the machine. Nothing outside it imports anything but `web.server.serve`.

## The web pages are files (`web/static/`)

- `admin.html` is a `string.Template`; the kiosk page needs no substitution at all.
- `admin.js` is static and cached: it reads its server values from a JSON blob in the page rather than being built per request.
- The Margin field is a range slider. `admin.js` renders its preview on `change` (release, or a keyboard step), never on `input`, so a drag costs one render.
- The preview box takes the page's shape before a render starts: `cfg.panel` turned by the rotation in the *form*, not the one last rendered, so the species list under it holds still and moves only when the page would.
- While the margin is dragged, the `.mat` band over the preview stands in for the render and goes when one starts. It is not shown while the preview is loading: there is no page to shade.
- The admin is used from a remote browser against a headless Pi. Do not design flows around `file://` URLs, opening a browser on the server, or other local-GUI assumptions.
