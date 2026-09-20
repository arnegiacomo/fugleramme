# The kiosk and the admin

Covers the `web/` package.

- `web/` is the kiosk and the admin: `server.py` is routing and transport only, `admin.py` builds the page from a `modes.Context`, `hostinfo.py` probes the machine. Nothing outside it imports anything but `web.server.serve`.

## The admin is gated, the kiosk is not (`server.GATED`)

- A login page and a session cookie, never `WWW-Authenticate`. This is BirdNET-Go's shape: its "basic auth" is a password typed into a form in its own UI, and the browser's credential dialog appears nowhere in that product. A frame that popped one would not read as the same appliance.
- Everything that must 401 for a signed-out admin is in `GATED`; add to it when the page learns to fetch something new. The static files are not in it on purpose - `admin.css` is what the login page is styled with. A browser (`Accept: text/html`) is redirected to the login page; anything else gets the 401, so a fetch does not land a login page in a JSON parser.
- The kiosk side stays open whatever is set: the public demo reads `/collage.png` and `/state`, and the container's healthcheck reads `/health`.
- `Settings.admin_locked` is the whole gate: the switch on *and* a password saved. Either half alone is an open frame, so a switch flipped on before a password is typed cannot lock anyone out.
- The cookie is signed with `session_secret` mixed with the password, so changing the password ends every session, and the secret is rotated on sign-out and on a password change - which is real revocation, unlike BirdNET-Go, whose access token outlives its own logout. No `Secure` flag: the frame is plain HTTP on a LAN and the cookie would never be sent.
- `admin.form_changes` drops `session_secret` from every post and treats a password field that still starts with `PASSWORD_SET` as untouched; `admin.js` empties such a field on focus. Typing on the end of the bullets would otherwise save them as the password, a lockout.
- `admin_password` is stored in the clear beside `detector_password` deliberately - `FUGLERAMME_ADMIN_PASSWORD` seeds a container, and a hand edit is how a locked-out Pi gets back in. BirdNET-Go stores its own the same way.
- `SameSite=Lax` keeps the cookie off another site's POST, and `do_POST` refuses a `Sec-Fetch-Site: cross-site` request besides - which is what protects a frame with no password set at all. Comparing `Origin` to `Host` instead would lock out anyone running the frame behind an HTTPS proxy.

## The web pages are files (`web/static/`)

- `admin.html` is a `string.Template`; the kiosk page needs no substitution at all.
- `admin.js` is static and cached: it reads its server values from a JSON blob in the page rather than being built per request.
- The Margin field is a range slider. `admin.js` renders its preview on `change` (release, or a keyboard step), never on `input`, so a drag costs one render.
- The preview box takes the page's shape before a render starts: `cfg.panel` turned by the rotation in the *form*, not the one last rendered, so the species list under it holds still and moves only when the page would.
- While the margin is dragged, the `.mat` band over the preview stands in for the render and goes when one starts. It is not shown while the preview is loading: there is no page to shade.
- The admin is used from a remote browser against a headless Pi. Do not design flows around `file://` URLs, opening a browser on the server, or other local-GUI assumptions.
