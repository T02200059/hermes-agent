"""Remote-ssh exemption for the supervised-gateway lifecycle guard.

Restarting a gateway on another host over ssh cannot SIGTERM this process, so
those segments must not trip the local guard. Everything that still executes
locally keeps the fail-closed behaviour.
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
