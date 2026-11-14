# Giving it as a gift

A frame can go in the box with a picture on it: the birds the recipient may hear where they live, in the month it arrives, with your note at the bottom. E-ink keeps the picture without power, so it is there when the box is opened.

![The gift splash: "Birds you may hear", a Steller's Jay large in the middle with other birds around it, and a note along the bottom](assets/gift-splash.jpg)

Wrapping also gets the frame ready for its new home. It forgets the birds heard at your place, sets the recipient's location in BirdNET-Go and can save their Wi-Fi, so it starts listening as soon as it is plugged in.

It needs a frame with an Inky panel and the BirdNET-Go that the [install](install.md) sets up beside it.

## Wrapping it

Do this last, once the frame works: install it, check the panel and the microphone, and let it hear a few birds.

The birds heard at your place are deleted when it is wrapped. To keep them, back up BirdNET-Go first.

Then, over SSH on the Pi:

```bash
cd ~/fugleramme
uv run fugleramme-gift
```

While it runs the frame is yours to draw on: its own page and the admin pause, and they start again when you quit. `sudo` may ask for your password to pause and start it.

It starts by listing the admin settings the picture is drawn with: the names and their languages, the label font, the artwork, the rotation and the margins. The picture looks like the frame's own page. To change any of them, quit, change them in the admin, and run it again.

It asks one question at a time. An answer it cannot use gets a red ✗ with what is wrong, and the question again with your answer still there to fix.

| Question | What to put |
| --- | --- |
| Where is it going? | A town or an address, or `latitude, longitude`. It shows the place it found, so check it is the right Columbus |
| When does it arrive? | The day, as `YYYY-MM-DD`. The birds are the ones likely there that month |
| Birds that must be on it? | Separated by commas, the first drawn large in the middle. Tab completes a name, and a misspelt one is offered back corrected: press Enter to take it |
| A note | Up to three lines for the bottom of the picture, one at a time. A line too long for this frame's panel says by how many characters. An empty line finishes |
| Wi-Fi | Optional. The recipient's network and its password, so the frame joins it by itself. The password shows as you type, to catch a typo here rather than at their house |
| Admin password | Asked only when the admin page has one. Clearing it is the default, or the new owner could never change a setting |

Then it draws the picture on the frame, which takes up to 30 seconds, and lists your answers by number. Type a number to change one: the picture is drawn again with it. `w` wraps it, `q` quits without changing anything. Ctrl-C quits at any point before the wrap.

Wrapping asks once more, and says what goes for good: how many detections and clips. Its answer is No unless you type `y`. Then it stops BirdNET-Go, writes the new location into its settings, saves the Wi-Fi and clears the password if you asked, and deletes the birds heard at your place last. It ends:

```text
Wrapped.

Unplug it now and box it. The picture stays without
power. The next time it is plugged in, wherever that is,
it wakes as a normal frame and starts listening for the
birds around Columbus.
```

If the connection drops before then, nothing is wrapped: reboot the frame to get its birds back.

## Changed your mind

Before you unplug it, this puts back the location, the Wi-Fi and the admin password, and starts the frame again. The birds heard at your place stay deleted.

```bash
uv run fugleramme-gift unwrap
```

It also puts back what a wrap that stopped part way had changed. Once the frame has been unplugged and plugged in again there is nothing to undo.

## When it is plugged in

The next time the frame starts, it is an ordinary frame again. BirdNET-Go starts listening at the new place, and within a minute the picture gives way to a bare branch until the first birds it hears there. It may be worth telling them, or putting a note in the box.

If it has no Wi-Fi it knows, it opens its own [Wi-Fi setup](wifi.md) as any frame does.

> [!NOTE]
> Plugging it in again at home, even for a quick test, ends gift mode: the picture goes and it starts listening at your place with the recipient's location. To wrap it again, run `uv run fugleramme-gift` again.

## When it isn't available

- A frame reading another BirdNET-Go, or BirdWeather stations, cannot be wrapped: the birds and the location are not its own to change.
- A frame without an Inky panel has nothing to hold the picture without power. The command says so.
