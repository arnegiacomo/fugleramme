# Wi-Fi networks to join, in the order they should be tried: the first one
# that connects wins. Add one by appending an (ssid, password) pair.
WIFI_NETWORKS = (("your-network", "your-password"),)
# The network that connected last time, tried first on the next wake.
WIFI_HINT = "wifi"

# Change to your Fugleramme setup
FRAME_HOST = "fugleramme.local"
FRAME_PORT = 8080
# The frame is served over TLS on 443; set True for HTTPS on another port.
# Note: we don't enable host validation, just encryption to avoid having to store a certificate store
FRAME_TLS = FRAME_PORT == 443

# The panel's program comes from the frame itself: a full URL, since it may be
# served by another host than the frame's page - for example through a reverse
# proxy whose auth the token in the path skips, which would otherwise answer
# the board's HTTP client with a 302 it cannot use. A bare path is served by
# the frame's own host. Checked every OTA_EVERY_N_RUNS wakes in main.py, or at
# once when button 2 wakes the board.
FIRMWARE = "http://fugleramme.local/FIRMWARE-TOKEN/admin.py"

# The minimum sleep duration between two polls
MIN_SLEEP_MINUTES = 5

# Failed wakes in a row before an unreachable frame is worth a refresh.
NOTICE_AFTER = 3

WIDTH, HEIGHT = 1200, 1600
