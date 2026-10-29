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

# The battery voltage below which the panel shows "Battery low" once and sleeps
# at least LOW_BATTERY_SLEEP_MINUTES between wakes. The divider on the EE02
# reads the raw cell, so a one-cell LiPo is full around 4.2 V and a
# USB-powered board sits near 4.0 V: lower the threshold if your cell never
# crosses 3.5 V, or the panel will warn at a healthy charge.
LOW_BATTERY = 3.5
# The sleep floor (in minutes) once the battery is below LOW_BATTERY.
LOW_BATTERY_SLEEP_MINUTES = 60

WIDTH, HEIGHT = 1200, 1600
