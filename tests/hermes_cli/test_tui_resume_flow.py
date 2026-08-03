from argparse import Namespace
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import types

import pytest


def _args(**overrides):
    base = {
        "continue_last": None,
        "model": None,
        "provider": None,
        "resume": None,
        "toolsets": None,
        "tui": True,
        "tui_dev": False,
    }
    base.update(overrides)
    return Namespace(**base)


def _raise_exit(rc):
    raise SystemExit(rc)


@pytest.fixture
def main_mod(monkeypatch):
    import hermes_cli.main as mod

    monkeypatch.setattr(mod, "_has_any_provider_configured", lambda: True)
    # Reset the idempotency guard so each test starts fresh.
    monkeypatch.setattr(mod, "_oneshot_cleanup_done", False)
    return mod
















def test_termux_skips_bundled_skill_sync_when_stamp_fresh(monkeypatch, tmp_path, main_mod):
    calls = []

    monkeypatch.setenv("TERMUX_VERSION", "1")
    monkeypatch.setattr(main_mod, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(main_mod, "_termux_bundled_skills_fingerprint", lambda: "fp1")
    main_mod._mark_termux_bundled_skills_synced()
    monkeypatch.setitem(
        sys.modules,
        "tools.skills_sync",
        types.SimpleNamespace(sync_skills=lambda quiet: calls.append(quiet)),
    )

    assert main_mod._sync_bundled_skills_for_startup() is False
    assert calls == []






def test_exit_after_oneshot_flushes_stdio_and_calls_os_exit(
    monkeypatch, main_mod
):
    flushed = []
    exits = []

    class FakeStream:
        def __init__(self, name):
            self.name = name

        def flush(self):
            flushed.append(self.name)

    def fake_exit(rc):
        exits.append(rc)
        raise SystemExit(rc)

    monkeypatch.setattr(main_mod.sys, "stdout", FakeStream("stdout"))
    monkeypatch.setattr(main_mod.sys, "stderr", FakeStream("stderr"))
    monkeypatch.setattr(main_mod.os, "_exit", fake_exit)
    monkeypatch.setattr("logging.shutdown", lambda: None)

    with pytest.raises(SystemExit) as exc:
        main_mod._exit_after_oneshot(17)

    assert exc.value.code == 17
    assert exits == [17]
    assert flushed == ["stdout", "stderr"]






def test_oneshot_subprocess_exits_without_teardown_abort():
    program = textwrap.dedent(
        """
        import hermes_cli.oneshot as oneshot
        from hermes_cli.main import _exit_after_oneshot

        oneshot._run_agent = lambda *args, **kwargs: ("ok", {"final_response": "ok"})
        _exit_after_oneshot(oneshot.run_oneshot("hello"))
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == b"ok\n"
    # Don't demand byte-empty stderr — an import-time warning from the heavy
    # CLI import chain shouldn't fail this. What matters is no crash traceback.
    assert b"Traceback" not in result.stderr








def _stub_plugin_discovery(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "hermes_cli.plugins",
        types.SimpleNamespace(discover_plugins=lambda: None),
    )




def test_oneshot_wires_session_db_for_recall(monkeypatch):
    """hermes -z bypasses HermesCLI, but recall still needs SessionDB."""
    from hermes_cli.oneshot import _run_agent

    captured = {}
    sentinel_db = object()

    class FakeAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.suppress_status_output = False
            self.stream_delta_callback = object()
            self.tool_gen_callback = object()

        def run_conversation(self, prompt, **_kwargs):
            captured["prompt"] = prompt
            return {"final_response": "ok", "failed": False, "partial": False}

    class FakeSessionDB:
        def __new__(cls):
            return sentinel_db

    def mod(name, **attrs):
        module = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(module, key, value)
        return module

    monkeypatch.setitem(sys.modules, "run_agent", mod("run_agent", AIAgent=FakeAgent))
    monkeypatch.setitem(sys.modules, "hermes_state", mod("hermes_state", SessionDB=FakeSessionDB))
    monkeypatch.setitem(
        sys.modules,
        "hermes_cli.config",
        mod("hermes_cli.config", load_config=lambda: {"model": {"default": "m"}}),
    )
    monkeypatch.setitem(
        sys.modules,
        "hermes_cli.models",
        mod("hermes_cli.models", detect_provider_for_model=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "hermes_cli.runtime_provider",
        mod(
            "hermes_cli.runtime_provider",
            resolve_runtime_provider=lambda **_kwargs: {
                "api_key": "k",
                "base_url": "u",
                "provider": "p",
                "api_mode": "chat_completions",
                "credential_pool": None,
            },
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "hermes_cli.tools_config",
        mod("hermes_cli.tools_config", _get_platform_tools=lambda *_args, **_kwargs: {"session_search"}),
    )

    text, result = _run_agent("recall this")
    assert text == "ok"
    assert not result.get("failed")
    assert captured["session_db"] is sentinel_db
    assert captured["enabled_toolsets"] == ["session_search"]
    assert captured["prompt"] == "recall this"


def test_launch_tui_exports_model_provider_and_toolsets(monkeypatch, main_mod):
    captured = {}
    active_path_during_call = None

    monkeypatch.setattr(
        main_mod,
        "_make_tui_argv",
        lambda tui_dir, tui_dev: (["node", "dist/entry.js"], Path(".")),
    )

    def fake_call(argv, cwd=None, env=None):
        nonlocal active_path_during_call
        captured.update({"argv": argv, "cwd": cwd, "env": env})
        active_path_during_call = Path(env["HERMES_TUI_ACTIVE_SESSION_FILE"])
        assert active_path_during_call.exists()
        return 1

    monkeypatch.setattr(main_mod.subprocess, "call", fake_call)

    with pytest.raises(SystemExit):
        main_mod._launch_tui(
            model="nous/hermes-test", provider="nous", toolsets="web, terminal"
        )

    env = captured["env"]
    assert env["HERMES_MODEL"] == "nous/hermes-test"
    assert env["HERMES_INFERENCE_MODEL"] == "nous/hermes-test"
    assert env["HERMES_TUI_PROVIDER"] == "nous"
    assert env["HERMES_INFERENCE_PROVIDER"] == "nous"
    assert env["HERMES_TUI_TOOLSETS"] == "web,terminal"
    active_path = Path(env["HERMES_TUI_ACTIVE_SESSION_FILE"])
    assert active_path.name.startswith("hermes-tui-active-session-")
    assert active_path.suffix == ".json"
    assert active_path_during_call == active_path
    assert not active_path.exists()
    assert env["NODE_ENV"] == "production"


def test_call_tui_process_absorbs_parent_sigint_until_child_exits(monkeypatch, main_mod):
    import signal

    observed = {}
    original = signal.getsignal(signal.SIGINT)

    def fake_call(argv, cwd=None, env=None):
        installed = signal.getsignal(signal.SIGINT)
        observed["installed"] = installed
        # Simulate the launcher's copy of the foreground-process-group SIGINT.
        # It must not raise KeyboardInterrupt or return before the child does.
        installed(signal.SIGINT, None)
        observed["continued"] = True
        return 0

    monkeypatch.setattr(main_mod.subprocess, "call", fake_call)

    assert main_mod._call_tui_process(
        ["node", "dist/entry.js"], cwd=".", env={}
    ) == 0
    assert observed["continued"] is True
    assert callable(observed["installed"])
    assert signal.getsignal(signal.SIGINT) is original


def test_launch_tui_worktree_validates_relative_python_against_final_cwd(
    monkeypatch, main_mod, tmp_path
):
    import cli as cli_mod

    parent_cwd = tmp_path / "parent"
    parent_cwd.mkdir()
    worktree = tmp_path / "worktree"
    relative_python = Path(".review-venv") / "bin" / Path(sys.executable).name
    python_path = worktree / relative_python
    python_path.parent.mkdir(parents=True)
    # copy2, not os.link: tmp_path may sit on a different filesystem than
    # the venv (tmpfs /tmp vs disk home) where hard links raise EXDEV.
    import shutil

    shutil.copy2(sys.executable, python_path)
    captured = {}

    monkeypatch.setenv("HERMES_CWD", str(parent_cwd))
    monkeypatch.setenv("HERMES_PYTHON", str(relative_python))
    monkeypatch.setattr(cli_mod, "_git_repo_root", lambda: None)
    monkeypatch.setattr(cli_mod, "_prune_stale_worktrees", lambda _repo: None)
    monkeypatch.setattr(cli_mod, "_setup_worktree", lambda: {"path": str(worktree)})
    monkeypatch.setattr(cli_mod, "_cleanup_worktree", lambda _info: None)
    monkeypatch.setattr(
        main_mod,
        "_make_tui_argv",
        lambda tui_dir, tui_dev: (["node", "dist/entry.js"], Path(".")),
    )
    monkeypatch.setattr(
        main_mod.subprocess,
        "call",
        lambda argv, cwd=None, env=None: captured.update({"env": env}) or 1,
    )

    with pytest.raises(SystemExit):
        main_mod._launch_tui(worktree=True)

    assert captured["env"]["HERMES_CWD"] == str(worktree)
    assert captured["env"]["HERMES_PYTHON"] == str(relative_python)


def test_launch_tui_applies_terminal_backend_config(
    monkeypatch, main_mod, _isolate_hermes_home
):
    captured = {}
    config_path = Path(os.environ["HERMES_HOME"]) / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "terminal:",
                "  backend: docker",
                "  docker_image: example/hermes-tools:latest",
                "  docker_extra_args:",
                "    - --network=host",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("TERMINAL_ENV", raising=False)
    monkeypatch.delenv("TERMINAL_DOCKER_IMAGE", raising=False)
    monkeypatch.delenv("TERMINAL_DOCKER_EXTRA_ARGS", raising=False)

    monkeypatch.setattr(
        main_mod,
        "_make_tui_argv",
        lambda tui_dir, tui_dev: (["node", "dist/entry.js"], Path(".")),
    )
    monkeypatch.setattr(
        main_mod.subprocess,
        "call",
        lambda argv, cwd=None, env=None: captured.update({"env": env}) or 1,
    )

    with pytest.raises(SystemExit):
        main_mod._launch_tui()

    assert captured["env"]["TERMINAL_ENV"] == "docker"
    assert captured["env"]["TERMINAL_DOCKER_IMAGE"] == "example/hermes-tools:latest"
    assert captured["env"]["TERMINAL_DOCKER_EXTRA_ARGS"] == '["--network=host"]'


def test_launch_tui_exit_code_42_relaunches_update(monkeypatch, main_mod):
    from unittest.mock import patch

    monkeypatch.setattr(
        main_mod,
        "_make_tui_argv",
        lambda tui_dir, tui_dev: (["node", "dist/entry.js"], Path(".")),
    )
    monkeypatch.setattr(main_mod.subprocess, "call", lambda *args, **kwargs: 42)

    with patch("hermes_cli.relaunch.relaunch") as mock_relaunch:
        with pytest.raises(SystemExit) as exc:
            main_mod._launch_tui()

    assert exc.value.code == 42
    mock_relaunch.assert_called_once_with(["update"], preserve_inherited=False)


def test_launch_tui_drops_stale_resume_env_without_resume_arg(monkeypatch, main_mod):
    captured = {}

    monkeypatch.setenv("HERMES_TUI_RESUME", "stale-missing-session")
    monkeypatch.setattr(
        main_mod,
        "_make_tui_argv",
        lambda tui_dir, tui_dev: (["node", "dist/entry.js"], Path(".")),
    )
    monkeypatch.setattr(
        main_mod.subprocess,
        "call",
        lambda argv, cwd=None, env=None: captured.update({"env": env}) or 1,
    )

    with pytest.raises(SystemExit):
        main_mod._launch_tui()

    assert "HERMES_TUI_RESUME" not in captured["env"]


def test_launch_tui_sets_resume_env_from_resume_arg(monkeypatch, main_mod):
    captured = {}

    monkeypatch.setenv("HERMES_TUI_RESUME", "stale-missing-session")
    monkeypatch.setattr(
        main_mod,
        "_make_tui_argv",
        lambda tui_dir, tui_dev: (["node", "dist/entry.js"], Path(".")),
    )
    monkeypatch.setattr(
        main_mod.subprocess,
        "call",
        lambda argv, cwd=None, env=None: captured.update({"env": env}) or 1,
    )

    with pytest.raises(SystemExit):
        main_mod._launch_tui(resume_session_id="20260518_000000_goodid")

    assert captured["env"]["HERMES_TUI_RESUME"] == "20260518_000000_goodid"


def test_make_tui_argv_dev_prebuilds_hermes_ink(monkeypatch, main_mod, tmp_path):
    tui_dir = tmp_path / "ui-tui"
    tsx = tui_dir / "node_modules" / ".bin" / "tsx"
    ink_dir = tui_dir / "packages" / "hermes-ink"
    tsx.parent.mkdir(parents=True)
    ink_dir.mkdir(parents=True)
    tsx.write_text("#!/usr/bin/env node\n", encoding="utf-8")

    monkeypatch.setattr(main_mod, "_ensure_tui_node", lambda: None)
    monkeypatch.setattr(main_mod, "_tui_need_npm_install", lambda _tui_dir: False)
    monkeypatch.delenv("HERMES_TUI_DIR", raising=False)
    monkeypatch.setattr(main_mod.shutil, "which", lambda bin_name: f"/usr/bin/{bin_name}")

    calls = []

    def fake_run(cmd, cwd=None, **_kwargs):
        calls.append((cmd, cwd))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(main_mod.subprocess, "run", fake_run)

    argv, cwd = main_mod._make_tui_argv(tui_dir, tui_dev=True)

    assert argv == [str(tsx), "src/entry.tsx"]
    assert cwd == tui_dir
    assert calls == [(["/usr/bin/npm", "run", "build"], str(ink_dir))]




