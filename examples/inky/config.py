# The Fugleramme frame whose page this panel shows. Enable "External e-ink
# panel" under Frame on its admin page.
FRAME_URL = "http://fugleramme.local:8080"

# Seconds between checks for a new page. An unchanged page costs a 304 and
# nothing else; the frame's Panel refresh decides how often the glass changes.
POLL_SECONDS = 5
