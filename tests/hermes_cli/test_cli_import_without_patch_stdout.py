"""``cli`` must import even when ``prompt_toolkit.patch_stdout`` is missing (#96075).

The top-level ``from prompt_toolkit.patch_stdout import patch_stdout`` was unguarded,
so a partial/broken prompt_toolkit install (e.g. a stale venv that has the package but
not every submodule) crashed the import chain — including ``tui_gateway.slash_worker``,
which imports ``cli`` in every gateway session. The only use site is a
``with patch_stdout():`` block, so a ``nullcontext`` fallback preserves behaviour.

Modeled on tests/tui_gateway/test_slash_worker_sys_path.py's subprocess pattern.

Isolation note: ``import cli`` runs ``cli.py``'s MODULE-SCOPE
``_init_logging_and_display_from_config()``, which calls ``hermes_logging.setup_logging()``
-> ``mkdir_under_hermes_home(get_hermes_home() / "logs")`` and attaches rotating file
handlers to ``agent.log``/``errors.log``. A child started with a bare
``HOME=Path.home()`` and no ``HERMES_HOME`` therefore creates — or rotates — the
operator's REAL ``~/.hermes/logs``, which on a developer box is the log the live
gateway is writing. ``tests/home_io_guard.py`` patches this process's Python file
calls only, so subprocess I/O is invisible to it: the child env is the only defence.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Import blocker: a sys.meta_path finder that raises ImportError only for
# prompt_toolkit.patch_stdout — the "package present, submodule broken" case.
_BLOCKER = """
import sys

class _BlockPatchStdout:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "prompt_toolkit.patch_stdout":
            raise ImportError("simulated broken prompt_toolkit.patch_stdout")
        return None

sys.meta_path.insert(0, _BlockPatchStdout())
"""


def _sandboxed_child_env(tmp_path: Path) -> dict[str, str]:
    """A child env that cannot resolve the operator's real Hermes home or logs.

    Every entry is load-bearing:

    * ``HOME``/``USERPROFILE`` — ``Path.home()`` and ``os.path.expanduser("~")`` read
      these (POSIX/Windows respectively); pointing them at the tmpdir re-homes every
      path the child derives from ``~`` (``~/.config``, ``~/.cache``, ``~/.local/state``
      and ``~/.hermes`` alike), not just the Hermes root.
    * ``HERMES_HOME`` — explicit, so the answer never depends on ``HOME`` resolution.
    * ``HERMES_TEST_ISOLATION`` — the marker ``hermes_state_guard`` uses to know the
      process tree is a test run. It inherits by default; a child env that drops it
      silently disarms the live-DB guard for that child.
    * ``PYTHONDONTWRITEBYTECODE`` — the child runs with ``cwd`` in the checkout, so
      without this every import drops ``__pycache__`` into the working tree.
    """
    home = tmp_path / "home"
    hermes_home = tmp_path / "hermes-home"
    home.mkdir(exist_ok=True)
    hermes_home.mkdir(exist_ok=True)
    return {
        "PYTHONPATH": str(PROJECT_ROOT),
        "PATH": "",
        "HOME": str(home),
        "USERPROFILE": str(home),
        "HERMES_HOME": str(hermes_home),
        "HERMES_TEST_ISOLATION": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _run_cli_child(code: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(PROJECT_ROOT),
        check=False,
    )


@pytest.fixture
def child_env(tmp_path) -> dict[str, str]:
    return _sandboxed_child_env(tmp_path)


def test_cli_imports_without_patch_stdout(child_env):
    proc = _run_cli_child(_BLOCKER + "import cli\n", child_env)
    assert proc.returncode == 0, proc.stderr


def test_cli_patch_stdout_falls_back_to_nullcontext(child_env):
    code = _BLOCKER + (
        "import cli, contextlib\n"
        "assert cli.patch_stdout is contextlib.nullcontext, cli.patch_stdout\n"
        "assert callable(cli.HermesCLI)\n"
    )
    proc = _run_cli_child(code, child_env)
    assert proc.returncode == 0, proc.stderr


def test_child_resolves_the_sandbox_home_not_the_operator_home(child_env):
    """The guard for this file's premise: the child must resolve the sandbox root.

    ``setup_logging`` derives ``logs/`` from exactly this value, so as long as the
    child answers with the tmpdir, importing ``cli`` cannot touch the operator's
    ``~/.hermes/logs``. Asserting the resolved root (not merely the env vars we
    passed in) is what catches a future edit that drops ``HERMES_HOME`` or reverts
    ``HOME`` to ``Path.home()``.
    """
    proc = _run_cli_child(
        "import hermes_constants; print(hermes_constants.get_hermes_home())\n", child_env
    )
    assert proc.returncode == 0, proc.stderr
    stdout = [line for line in proc.stdout.strip().splitlines() if line.strip()]
    assert stdout, f"child printed nothing (stderr={proc.stderr!r})"
    assert Path(stdout[-1]).resolve() == Path(child_env["HERMES_HOME"]).resolve()
