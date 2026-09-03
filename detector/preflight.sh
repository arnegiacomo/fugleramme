#!/usr/bin/env bash
# BirdNET-Go only logs and retries on a missing mic; report it before startup.
set -euo pipefail

if ! command -v arecord >/dev/null 2>&1; then
  echo "preflight: arecord not found - install alsa-utils" >&2
  exit 1
fi

if ! arecord -l 2>/dev/null | grep -q '^card '; then
  echo "preflight: no ALSA capture device found - is the USB mic plugged in?" >&2
  exit 1
fi

echo "preflight: capture device(s) present:"
arecord -l | grep '^card '
