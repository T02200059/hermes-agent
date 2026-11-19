"""Remote-ssh exemption for the supervised-gateway lifecycle guards.

Restarting a gateway on another host over ssh cannot SIGTERM this process, so
those invocations must not trip the local guards — neither the terminal tool's
command scan nor execute_code's source-text scan. Everything that still
executes locally keeps the fail-closed behaviour.
"""

import json

import pytest

from tools.terminal_tool_guards import gateway_lifecycle_block


@pytest.fixture
def supervised(monkeypatch):
    from tools import process_registry

    monkeypatch.setattr(process_registry, "_is_supervised_gateway_process", lambda: True)


def _run(command, tmp_path):
    return gateway_lifecycle_block(
        command=command, env=None, env_type="local", cwd=str(tmp_path), workdir=None,
        session_key="remote-ssh-exemption-test",
    )


def _blocked(command, tmp_path):
    result = _run(command, tmp_path)
    assert result is not None
    return json.loads(result)


def test_remote_ssh_restart_passes(supervised, tmp_path):
    assert _run("ssh node010 'systemctl restart hermes-gateway.service'", tmp_path) is None
    assert _run('ssh -p 2202 yangtb@node010 "systemctl restart hermes-gateway"', tmp_path) is None


def test_remote_ssh_with_trailing_local_noop_passes(supervised, tmp_path):
    command = "ssh node010 'systemctl restart hermes-gateway.service' && echo RESTART_ISSUED"
    assert _run(command, tmp_path) is None


def test_local_restart_still_blocked(supervised, tmp_path):
    blocked = _blocked("systemctl restart hermes-gateway.service", tmp_path)
    assert blocked["exit_code"] == 1
    assert "cannot restart" in blocked["error"]


def test_mixed_remote_and_local_restart_still_blocked(supervised, tmp_path):
    command = (
        "ssh node010 'systemctl restart hermes-gateway.service' "
        "&& systemctl restart hermes-gateway.service"
    )
    assert _blocked(command, tmp_path)["exit_code"] == 1


def test_ssh_to_localhost_still_blocked(supervised, tmp_path):
    for target in ("localhost", "127.0.0.1", "[::1]"):
        blocked = _blocked(f"ssh {target} 'systemctl restart hermes-gateway'", tmp_path)
        assert blocked["exit_code"] == 1, target


def test_ssh_local_command_options_still_blocked(supervised, tmp_path):
    for option in (
        "-o ProxyCommand='systemctl restart hermes-gateway'",
        "-o LocalCommand='systemctl restart hermes-gateway'",
    ):
        assert _blocked(f"ssh {option} node010 'true'", tmp_path)["exit_code"] == 1, option


def test_remote_output_piped_to_local_shell_still_blocked(supervised, tmp_path):
    command = "ssh node010 'echo systemctl restart hermes-gateway' | bash"
    assert _blocked(command, tmp_path)["exit_code"] == 1


# ── execute_code: the same exemption applied to Python source text ──


def _scanned(code):
    from cron.lifecycle_guard import contains_gateway_lifecycle_command
    from tools.terminal_tool_guards import code_without_remote_ssh_calls

    return contains_gateway_lifecycle_command(code_without_remote_ssh_calls(code))


def test_execute_code_argv_remote_ssh_exempt():
    from cron.lifecycle_guard import contains_gateway_lifecycle_command

    code = (
        "import subprocess\n"
        "subprocess.run(['ssh', 'node010', 'systemctl restart hermes-gateway.service'])\n"
    )
    assert contains_gateway_lifecycle_command(code)
    assert not _scanned(code)


def test_execute_code_shell_string_remote_ssh_exempt():
    code = (
        "import os\n"
        "os.system(\"ssh -p 2202 yangtb@node010 'systemctl restart hermes-gateway'\")\n"
    )
    assert not _scanned(code)


def test_execute_code_local_lifecycle_still_flagged():
    assert _scanned("import os\nos.system('systemctl restart hermes-gateway.service')\n")


def test_execute_code_ssh_localhost_still_flagged():
    code = "import os\nos.system(\"ssh localhost 'systemctl restart hermes-gateway'\")\n"
    assert _scanned(code)


def test_execute_code_local_call_beside_remote_ssh_still_flagged():
    code = (
        "import os\n"
        "os.system(\"ssh node010 'systemctl restart hermes-gateway.service'\")\n"
        "os.system('systemctl restart hermes-gateway.service')\n"
    )
    assert _scanned(code)


def test_execute_code_non_literal_argv_stays_fail_closed():
    code = (
        "import subprocess\n"
        "host = 'node010'\n"
        "subprocess.run(['ssh', host, 'systemctl restart hermes-gateway'])\n"
    )
    assert _scanned(code)
