# Frame

How the frame shows the page, and how to change it. Open the admin page at
`http://<host>.local:8080/admin` and use the **Frame** tab.

## Settings

### Panel output

Enable or disable the different outputs that are generated. The Inky Impression is automatically detected as soon as it is connected, and its image data is generated internally. The raw image data for an external e-ink panel is served via the web interface and can be enabled or disabled. The web view is always enabled.

### Panel size

The size of the external e-ink panel: **4.0" (600×400)**, **7.3" (800×480)** or **13.3" (1600×1200)**. Default is **13.3"**. With an Inky Impression connected, its own size is shown and used for every output, the external panel's included, and the option is disabled.

### Rotation

How the frame hangs: 0° or 180° for landscape, 90° or 270° for portrait. Default is **0°**. Applies to the Inky Impression, the external e-ink panel and a web view locked to the panel. Without a panel there is nothing to turn, and therefore the option is disabled.

### Panel refresh

The shortest time the panel holds a render before newly heard birds may change it. Default is **As soon as it changes**. This is a floor and not a timer, and affects all modes. If you have a busy station, you can use this to avoid constant redraws.

### Resolution (web only)

The resolution of the web renders. Default is **1080p**. Independent from the e-ink panel's own size (the connected Inky's, else **Panel size**).

### Lock to panel (web only)

Lock the web view to the e-ink panel's shape and rotation. Default is **on** if you have an Inky Impression connected or the external e-ink panel enabled. Turn it off and pick an **Aspect** and **Portrait** to fit a TV or a desktop as well - see [Screens](screens.md). 

Without a panel there is nothing to lock to, and therefore the option is disabled.

### Margin

How much space between whats rendered and the edges, as a percentage of the short side. Default is **4%**. Raise it if your frame's passepartout covers the edges of the panel, so the birds don't end up underneath - see
[cutting the passepartout](hardware.md#cutting-the-passepartout-mostly-relevant-for-full-build).

The single-bird modes have a wide border, so only 8% or above affects them.

### Uniform (panel only)

One margin to rule them all, or one per edge. Default is **on**. Turn it off if the passepartout's window is not centred on the panel (Inky impressions are not fully centered in an A4 picture frame). Without a panel there are no edges to set, and therefore the option is disabled.
