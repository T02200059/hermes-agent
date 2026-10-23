"""Put ``sys.modules`` back the way a test found it, package attributes included.

A few tests wipe part (or all) of the module table so the code under test imports a
fresh agent stack (``run_agent`` / ``agent.*`` / ``tools.*``). Restoring the saved
dict alone is not enough: the re-import rebinds ``pkg.<child>`` attributes on the
parent package to the NEW module objects, so after the table is put back
``from pkg import child`` still yields the fresh object while
``sys.modules["pkg.child"]`` yields the original — two objects for one symbol, and a
later ``monkeypatch.setattr`` lands on whichever one the test happened to hold.

The wipe window itself is also hazardous: while the table is short, any OTHER thread
that imports re-executes module bodies (for ``cli`` that means module-scope
``setup_logging`` runs again and stacks a second file handler on the root logger).
Delete the specific keys a test needs when that is enough; ``restore_sys_modules`` is
for the cases that genuinely replace whole subtrees.
"""

from __future__ import annotations

import sys


def snapshot_sys_modules() -> dict[str, object]:
    """A shallow copy of the current module table."""
    return dict(sys.modules)


def restore_sys_modules(saved: dict[str, object]) -> None:
    """Drop what the test imported, put ``saved`` back, re-point package attributes.

    Deliberately NOT ``sys.modules.clear()`` + ``update(saved)``: that leaves the table
    EMPTY while the copy runs, so any thread that imports in that instant re-executes
    module bodies. Dropping the added names one at a time reaches the same end state
    with a window of one key instead of the whole table.
    """
    for name in [existing for existing in sys.modules if existing not in saved]:
        sys.modules.pop(name, None)
    sys.modules.update(saved)
    for name, module in saved.items():
        parent_name, _, child = name.rpartition(".")
        if not parent_name:
            continue
        parent = saved.get(parent_name)
        if parent is None:
            continue
        try:
            setattr(parent, child, module)
        except Exception:
            # A parent that refuses attribute writes is not something this helper can
            # fix; leaving it alone is still better than aborting the restore.
            pass
