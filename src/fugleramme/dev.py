"""Dev-only entrypoint: run the frame service with auto-restart on code change.

Wraps the normal CLI in watchfiles' run_process, which restarts the whole
process - render loop, panel push, and HTTP server - whenever a source file under
src/fugleramme changes. Dev convenience only; production runs fugleramme-frame
directly under systemd. All CLI flags are forwarded, so e.g.

    fugleramme-dev --preview out.png

behaves like fugleramme-frame with reload.
"""

from __future__ import annotations

import sys

from watchfiles import run_process

from .cli import main as service_main
from .config import REPO_ROOT


def main() -> None:
    watch_dir = REPO_ROOT / "src" / "fugleramme"
    run_process(watch_dir, target=service_main, args=(sys.argv[1:],))


if __name__ == "__main__":
    main()
