"""Swaps in a staged panel program before main.py runs, and rolls a bad one back.

main.py stages a downloaded update as main.py.new and restarts. On the boot
that follows, this file validates it, keeps the old program as main.py.bak and
lets the new one run. The new program deletes main.py.bak once a wake has
reached the frame without a problem; when this file instead finds main.py.bak
on a later boot, the new program never got that far, so it is rolled back -
and stays rolled back, because main.etag still names the rejected version, so
the frame answers 304 until it serves something else.

A watchdog backs the trial: a program that hangs instead of crashing never
reaches another boot on its own, so this file arms one every boot, generous
enough for a healthy wake; one that outlives it resets the board and takes the
rollback path above.

A staged file can be damaged by a power cut between writing and restarting.
Never let that turn into a boot loop: reject it, keep the installed program,
and let the frame serve the update again.
"""

import os

import machine

# A hung program never reaches the next boot's check on its own.
machine.WDT(timeout=300_000)


def there(name: str) -> bool:
    try:
        os.stat(name)
        return True
    except OSError:
        return False


def discard(name: str) -> None:
    try:
        os.remove(name)
    except OSError:
        pass


if there("main.py.bak") and not there("main.py.new"):
    # The last install was never confirmed: back onto the program that worked.
    os.rename("main.py.bak", "main.py")
elif there("main.py.new"):
    if there("main.py.bak"):
        # A power cut during the last swap left no program. Undo the staging.
        # Drop main.etag so the frame serves the update again.
        print("boot: discarding update staged during an interrupted swap")
        discard("main.py.new")
        discard("main.etag")
        if not there("main.py"):
            os.rename("main.py.bak", "main.py")
    else:
        try:
            with open("main.py.new", "rb") as file:
                source = file.read()
            compile(source, "main.py", "exec")  # never run a program that cannot load
        except Exception as error:
            # A truncated/corrupt staged file must not brick an unattended board.
            print("boot: rejecting staged main.py:", error)
            discard("main.py.new")
        else:
            if there("main.py"):
                os.rename("main.py", "main.py.bak")
            os.rename("main.py.new", "main.py")
