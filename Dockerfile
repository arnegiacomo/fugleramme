# The headless kiosk as an image. No panel - SPI, I2C and the buttons are the Pi's.
#
# config.REPO_ROOT is derived from the package's own file, and the artwork, the
# fonts, the labels and bird_sizes.csv all hang off it, so the checkout's layout
# has to survive into the image: /app/src/fugleramme beside /app/assets.

FROM python:3.12-slim-bookworm AS build

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON=/usr/local/bin/python \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Deps in their own layer, so a source change re-runs only the install below.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

COPY README.md LICENSE ./
COPY src ./src
RUN uv sync --locked --no-dev  # no panel extra: inky and gpiod are Pi hardware


FROM python:3.12-slim-bookworm

# python:slim carries no zone data, and the frame's day is the local one.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 fugleramme \
    && useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin fugleramme \
    && install -d -o 1000 -g 1000 /data

WORKDIR /app

COPY --from=build /app/.venv ./.venv

COPY assets/ATTRIBUTION.md assets/bird_sizes.csv assets/birdnet_aliases.json assets/birdnet_labels_v2.4.txt ./assets/
COPY assets/fonts ./assets/fonts
COPY assets/artwork/custom ./assets/artwork/custom
COPY assets/artwork/classic/ATTRIBUTION.md assets/artwork/classic/manifest.json ./assets/artwork/classic/
COPY assets/artwork/classic/perches ./assets/artwork/classic/perches

# The plates are 165 MB, so they ship as a layer per letter: the registry serves
# blobs by digest, and the ranges a release did not touch are already on disk.
#
# The ranges must leave no letter out. Nothing starts with k, q, w or y today, so
# a range skipping them would drop tomorrow's species from the image and nowhere
# else; a range matching nothing fails the build. tests/test_container.py checks both.
COPY assets/artwork/classic/birds/[a]* ./assets/artwork/classic/birds/
COPY assets/artwork/classic/birds/[b]* ./assets/artwork/classic/birds/
COPY assets/artwork/classic/birds/[c]* ./assets/artwork/classic/birds/
COPY assets/artwork/classic/birds/[d-e]* ./assets/artwork/classic/birds/
COPY assets/artwork/classic/birds/[f-g]* ./assets/artwork/classic/birds/
COPY assets/artwork/classic/birds/[h-k]* ./assets/artwork/classic/birds/
COPY assets/artwork/classic/birds/[l]* ./assets/artwork/classic/birds/
COPY assets/artwork/classic/birds/[m]* ./assets/artwork/classic/birds/
COPY assets/artwork/classic/birds/[n-o]* ./assets/artwork/classic/birds/
COPY assets/artwork/classic/birds/[p-q]* ./assets/artwork/classic/birds/
COPY assets/artwork/classic/birds/[r]* ./assets/artwork/classic/birds/
COPY assets/artwork/classic/birds/[s]* ./assets/artwork/classic/birds/
COPY assets/artwork/classic/birds/[t]* ./assets/artwork/classic/birds/
COPY assets/artwork/classic/birds/[u-z]* ./assets/artwork/classic/birds/

# Last, so an app-only release re-pulls a few hundred kilobytes.
COPY src ./src

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    TZ=UTC \
    FUGLERAMME_CONTAINER=1

# Fail the build, not the first render, if the package lands anywhere else.
RUN python -c "from fugleramme.config import REPO_ROOT; assert str(REPO_ROOT) == '/app', REPO_ROOT"

USER fugleramme
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"

# Everything the frame writes derives from --config's parent, so one volume at
# /data holds all of it. A fresh /data names no detector: FUGLERAMME_DETECTOR_URL,
# or --detector appended as `command:`.
ENTRYPOINT ["fugleramme-frame", "--config", "/data/settings.json", "--output", "/data/frame.png"]
