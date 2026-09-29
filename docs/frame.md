# Frame

How the frame shows the page, and how to change it. Open the admin page at
`http://<host>.local:8080/admin` and use the **Frame** tab.

## Settings

### Panel refresh

The shortest time the panel holds a render before newly heard birds may change it. Default is **As soon as it changes**. This is a floor and not a timer, and affects all modes. If you have a busy station, you can use this to avoid constant redraws.

### Resolution (web only)

The resolution of the web renders. Default is **1080p**. Independent from the e-ink panel's own size (automatically identified).

### Lock to panel (web only)

Lock the web view to the e-ink panel's shape and rotation. Default is **on** if you have an Inky Impression connected. Turn it off and pick an **Aspect** and **Portrait** to fit a TV or a desktop as well - see [Screens](screens.md). 

Without a panel there is nothing to lock to, and therefore the option is disabled.

### Margin

How much space between whats rendered and the edges, as a percentage of the short side. Default is **4%**. Raise it if your frame's passepartout covers the edges of the panel, so the birds don't end up underneath - see
[cutting the passepartout](hardware.md#cutting-the-passepartout-mostly-relevant-for-full-build).

The single-bird modes have a wide border, so only 8% or above affects them.

### Uniform (panel only)

One margin to rule them all, or one per edge. Default is **on**. Turn it off if the passepartout's window is not centred on the panel (Inky impressions are not fully centered in an A4 picture frame).
