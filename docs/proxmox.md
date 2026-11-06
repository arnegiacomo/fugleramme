# Proxmox

Fugleramme as an LXC on a [Proxmox VE](https://www.proxmox.com/en/proxmox-virtual-environment) host,
next to a BirdNET-Go you already run, or a public
[BirdWeather station](operations.md#using-birdweather-instead-of-birdnet-go).
The installer follows the [Proxmox VE community scripts](https://community-scripts.org/) and is
maintained separately, in [proxmox-fugleramme](https://github.com/dmellok/proxmox-fugleramme).

> [!NOTE]
> Like the [container](container.md), it is web only. BirdNET-Go and the mic are not part of it.

## Install

On the Proxmox host's shell (not inside a container):

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/dmellok/proxmox-fugleramme/main/ct/fugleramme.sh)"
```

Take the defaults or pick your own CPU, memory, disk and network. It creates a Debian container,
installs the latest Fugleramme release in it and starts the frame as a service. When it is done,
it prints the container's address.

The kiosk is on `:8080` and the admin on `:8080/admin`. Set BirdNET-Go's address on the admin
page's Detector tab, the way you open its own dashboard, e.g. `http://192.168.1.20:8080`.

## Updates

The System tab will still notify if there's a new update, but there is no Install button, and the
`docker compose` command it shows is for the [container](container.md). On Proxmox, open the
container's console and run:

```bash
update
```

It installs the latest release and keeps your settings.

## Problems

Problems with the installer itself go to
[proxmox-fugleramme](https://github.com/dmellok/proxmox-fugleramme/issues). If the frame
misbehaves the same way in the [container](container.md), it is a Fugleramme bug - see
[Troubleshooting](troubleshooting.md).
