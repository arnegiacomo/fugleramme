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

# Set FIRMWARE to a URL serving the panel's latest program to enable OTA
# updates. The URL must return the file directly, with no authentication or
# redirect, for example the raw main.py from the main branch on GitHub:
# https://raw.githubusercontent.com/arnegiacomo/fugleramme/main/examples/ee02/main.py
# None disables OTA.
FIRMWARE = None

# The minimum sleep duration between two polls
MIN_SLEEP_MINUTES = 5

# Failed wakes in a row before an unreachable frame is worth a refresh.
NOTICE_AFTER = 3

# Battery volts, for a 4.2 V Li-ion or LiPo cell at rest. Below BATTERY_EMPTY
# (about 5%) the panel says so and stops fetching until a charge lifts it above
# BATTERY_CHARGED, with the days and wakes since the cell last read
# BATTERY_FULL. BATTERY_SCALE is the board's divider (2.0); adjust it if the
# printed "battery:" reading differs from a multimeter's.
# Shows the empty notice.
BATTERY_EMPTY = 3.61
# Clears the notice; the gap keeps a recovering cell from flipping it back.
BATTERY_CHARGED = 3.80
# Restarts the stats; only a charge reaches it.
BATTERY_FULL = 4.10
BATTERY_SCALE = 2.0

WIDTH, HEIGHT = 1200, 1600
