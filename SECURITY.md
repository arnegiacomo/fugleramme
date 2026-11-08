# Security policy

## Reporting a vulnerability

Please don't open a public issue. Use **[Report a vulnerability](https://github.com/arnegiacomo/fugleramme/security/advisories/new)** on the Security tab, or email arnegiacomo+fugleramme@gmail.com.

This is a one-person project, so replies are best effort. The fix ships as a new release, which frames with auto-update pick up on their own, and the advisory would be published after that.

## Supported versions

Only the latest release. There are no backports.

## Scope

The frame's own code, the install scripts and the self-update.

The frame serves plain HTTP on the local network by design. If it's reachable from anywhere less trusted, serve it over HTTPS [behind a reverse proxy](docs/operations.md#behind-a-reverse-proxy).
