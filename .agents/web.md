# The kiosk and the admin

Covers the `web/` package.

- Nothing outside `web/` imports anything but `web.server.serve`. `server.py` is routing and transport only, `admin.py` works out what each tab shows from a `modes.Context`, `hostinfo.py` probes the machine.

## The admin is gated, the kiosk is not (`server.GATED`)

- A login page and a session cookie, never `WWW-Authenticate`. This is BirdNET-Go's shape: its "basic auth" is a password typed into a form in its own UI, and the browser's credential dialog appears nowhere in that product. A frame that popped one would not read as the same appliance.
- Everything that must 401 for a signed-out admin is in `GATED`; add to it when the page learns to fetch something new. The static files are not in it on purpose - `admin.css` is what the login page is styled with. A browser (`Accept: text/html`) is redirected to the login page; anything else gets the 401, so a fetch does not land a login page in a JSON parser.
- The kiosk side stays open whatever is set: the public demo reads `/collage.png` and `/state`, the container's healthcheck reads `/health`, and an external panel's board reads `/frame.e6` or `/frame.png`.
- `/press` is the one thing a locked frame gates outside the admin, since a press changes settings. A headless client cannot hold a browser session, and a sign-out anywhere would rotate the secret and silently end it, so it posts the admin password with each press instead, in the form body as the login page does (`_press_refused`). A wrong one counts against the sign-in's limit, or `/press` would be an unthrottled way to guess the password; a missing one does not, so an unconfigured client cannot lock the owner out.
- `Settings.admin_locked` is the whole gate: the switch on *and* a password saved. Either half alone is an open frame, so a switch flipped on before a password is typed cannot lock anyone out.
- The cookie is signed with `session_secret` mixed with the password, so changing the password ends every session, and the secret is rotated on sign-out and on a password change - which is real revocation, unlike BirdNET-Go, whose access token outlives its own logout. No `Secure` flag: the frame is plain HTTP on a LAN and the cookie would never be sent.
- `admin.form_changes` drops `session_secret` from every post and treats a password field that still starts with `PASSWORD_SET` as untouched; `forms.js` empties such a field on focus. Typing on the end of the bullets would otherwise save them as the password, a lockout.
- `admin_password` is stored in the clear beside `detector_password` deliberately - `FUGLERAMME_ADMIN_PASSWORD` seeds a container, and a hand edit is how a locked-out Pi gets back in. BirdNET-Go stores its own the same way.
- `SameSite=Lax` keeps the cookie off another site's POST, and `do_POST` refuses a `Sec-Fetch-Site: cross-site` request besides - which is what protects a frame with no password set at all. Comparing `Origin` to `Host` instead would lock out anyone running the frame behind an HTTPS proxy.

## The Detector tab (`templates/detector.html`, `admin.refused`)

- Each type keeps its own fields. The other type's are `hidden` and `disabled`, so a save posts nothing for them and their stored values stand for a switch back; `detector.js` swaps them before the form's dirty check reads it. Both are text inputs: a url input would refuse a bare station ID and a BirdNET-Go typed without a scheme.
- An address typed into the wrong type's field is refused and nothing is saved, since settings would otherwise drop the station or save it as a BirdNET-Go. A refused save carries the stations across the redirect, so the note names the one it was refused for.
- BirdWeather's stations are a row each, all posting `detector_station`, which `admin.form_changes` joins with commas the way settings hold them. `detector.js` adds and removes rows and fires `input`, since the dirty check would not see a removed row otherwise.
- **Find stations…** is a `dialog` that only fills the rows. Its field has no `name`, so nothing of it posts. The places are Photon's, since Nominatim's usage policy forbids search-as-you-type.
- Each station's line in the Detector row carries its own logo, so Test connection's answer brings logos `detector.js` has to load (`common.showLogos`).
- The detectors' favicons are loaded by the browser at runtime (`LOGOS` in `common.js`): they are other projects' brand marks, so the repo holds no copy.

## The web pages are files (`web/templates/`, `web/static/`)

- A Jinja template per tab, each rendered by its own `admin.*_tab` function, so a test renders one tab without the rest. They autoescape and render under `StrictUndefined`: a value a template names and nobody passed fails the render rather than leaving a blank.
- `rows.html` holds the rows the server also sends on their own, the species list (`/species`) and a test's Detector row (`/detector`), so the page and the answer render from one macro.
- The script is ES modules under `static/admin/`, one per section, static and cached with no build step: it reads its server values from a JSON blob in the page rather than being built per request. Each sets itself up on import; `main.js` runs what has to wait for all of them, such as the forms' dirty snapshot, which must come after `settings.js` has dimmed the fields the form's state leaves out.
- The Wi-Fi portal stays out of the templates on purpose: it is stdlib only (`.agents/wifi.md`).
- The Margin field is a range slider. `settings.js` renders its preview on `change` (release, or a keyboard step), never on `input`, so a drag costs one render.
- A change to any `margin*` field also posts the form to `/mat-test` (debounced 500 ms), which starts the margin test the render breadcrumb describes. There is no button: the black band is the feedback.
- The preview box takes the page's shape before a render starts: the Inky's while one is detected, else the external panel's while its box is ticked, turned by the rotation in the *form*, not the one last rendered (with no panel, the form's aspect and portrait), so the species list under it holds still and moves only when the page would.
- `syncPanel` and `syncMargin` follow the same answer: Rotation, Lock to panel, Uniform and the edges are offered while the form has a panel. All are always rendered with their declarations, and disabled - declaration included - without a panel, so a save then leaves the stored values alone.
- Display and Frame are two tabs over one form, so one preview serves both; `#settings` is shown for either.
- One save bar serves every tab (`forms.js`). Save posts each changed form to `/admin` in turn, as it would have posted on its own, then reloads once: a reload after one form's save would drop the others' edits. The access form goes last, since a new admin password ends the session and nothing after it would be let in. A refused detector save lands on its `?refused=` page, which is where the reload goes. Enter in a field is a Save of everything, and a tab with unsaved changes carries a dot.
- The margin's edge sliders are named for the glass (`margin_top` is the top at rotation 0), and `settings.js` relabels and reorders them by the rotation in the form, so they always read as the frame hangs.
- While the margin is dragged, the `.mat` band over the preview stands in for the render and goes when one starts. It is not shown while the preview is loading: there is no page to shade.
- The admin is used from a remote browser against a headless Pi. Do not design flows around `file://` URLs, opening a browser on the server, or other local-GUI assumptions.
