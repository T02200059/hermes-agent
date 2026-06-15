"""launchd gateway restart strategy (kickstart -k).

Extracted from hermes_cli/gateway.py per owner migration规范 — official file
keeps a one-line delegate; tests patch gateway_cli.launchd_restart and
gateway_cli.subprocess.run via injected subprocess_run.
"""

from __future__ import annotations

import subprocess
from typing import Any, Callable, Optional


def run_launchd_restart(
    *,
    get_launchd_label: Callable[[], str],
    launchd_domain: Callable[[], str],
    get_running_pid: Callable[[], Optional[int]],
    request_self_restart: Callable[[int], bool],
    launchd_error_indicates_unloaded: Callable[[subprocess.CalledProcessError], bool],
    launchctl_domain_unsupported: Callable[[int], bool],
    get_plist_path: Callable[[], Any],
    fallback_to_detached: Callable[[str], None],
    subprocess_run: Callable[..., Any] = subprocess.run,
) -> None:
    """Restart the gateway via launchctl kickstart -k (atomic lifecycle)."""
    label = get_launchd_label()
    target = f"{launchd_domain()}/{label}"

    try:
        pid = get_running_pid()
        # When called from within the gateway itself (agent-triggered restart),
        # request a graceful drain via SIGUSR1 — launchd auto-restarts on exit 75
        # because KeepAlive.SuccessfulExit=false only suppresses restart on exit 0.
        if pid is not None and request_self_restart(pid):
            print("✓ Service restart requested")
            return

        # External restart (CLI, cron, etc.): let launchd handle the full
        # lifecycle atomically.  kickstart -k sends SIGTERM, waits for
        # the exit_timeout (default 20s), force-SIGKILLs if needed, then
        # starts a fresh instance — no manual drain/wait that can block
        # indefinitely when the old process is stuck in a long API call.
        subprocess_run(
            ["launchctl", "kickstart", "-k", target],
            check=True,
            timeout=120,
        )
        print("✓ Service restarted")
    except subprocess.CalledProcessError as e:
        if not launchd_error_indicates_unloaded(e):
            if launchctl_domain_unsupported(e.returncode):
                fallback_to_detached(f"launchctl kickstart exit {e.returncode}")
                return
            raise
        print("↻ launchd job was unloaded; reloading")
        plist_path = get_plist_path()
        try:
            subprocess_run(
                ["launchctl", "bootstrap", launchd_domain(), str(plist_path)],
                check=True,
                timeout=30,
            )
            subprocess_run(
                ["launchctl", "kickstart", target],
                check=True,
                timeout=60,
            )
        except subprocess.CalledProcessError as e2:
            if not launchctl_domain_unsupported(e2.returncode):
                raise
            fallback_to_detached(f"launchctl exit {e2.returncode}")
            return
        print("✓ Service restarted")