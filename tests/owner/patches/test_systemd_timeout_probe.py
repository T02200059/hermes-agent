"""owner/patches/systemd_timeout_probe：LoadState=loaded + scope 顺序。"""

from __future__ import annotations

import subprocess
from typing import Optional, Sequence

from owner.patches.systemd_timeout_probe import (
    preferred_systemctl_flags,
    systemd_timeout_stop_us,
)


def _cp(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def _parse_duration(raw: str) -> Optional[int]:
    # 测试注入：仅覆盖本测用到的字面量，避免依赖 gateway 解析器。
    mapping = {
        "1min 30s": 90 * 1_000_000,
        "330s": 330 * 1_000_000,
        "5min 30s": 330 * 1_000_000,
    }
    return mapping.get(raw)


class TestPreferredFlags:
    def test_system_prefers_bare_first(self):
        assert preferred_systemctl_flags("system") == [[], ["--user"]]

    def test_user_or_none_prefers_user_first(self):
        assert preferred_systemctl_flags("user") == [["--user"], []]
        assert preferred_systemctl_flags(None) == [["--user"], []]


class TestSystemdTimeoutStopUs:
    def test_user_not_found_default_then_system_loaded_330(self):
        """--user not-found 默认 90s 不得采纳；system loaded 330s 才返回。"""
        calls: list[Sequence[str]] = []

        def fake_run(argv, **_kwargs):
            calls.append(tuple(argv))
            if "--user" in argv:
                return _cp("LoadState=not-found\nTimeoutStopUSec=1min 30s\n")
            return _cp("LoadState=loaded\nTimeoutStopUSec=330000000\n")

        got = systemd_timeout_stop_us(
            "hermes-gateway.service",
            prefer_scope=None,  # hermes 默认先 --user
            run=fake_run,
            parse_duration=_parse_duration,
        )
        assert got == 330_000_000
        assert any("--user" in c for c in calls)
        assert any("--user" not in c and "show" in c for c in calls)

    def test_prefer_scope_system_probes_system_first(self):
        order: list[str] = []

        def fake_run(argv, **_kwargs):
            order.append("user" if "--user" in argv else "system")
            if "--user" in argv:
                return _cp("LoadState=not-found\nTimeoutStopUSec=1min 30s\n")
            return _cp("LoadState=loaded\nTimeoutStopUSec=330000000\n")

        got = systemd_timeout_stop_us(
            "hub.service",
            prefer_scope="system",
            run=fake_run,
            parse_duration=_parse_duration,
        )
        assert got == 330_000_000
        assert order[0] == "system"

    def test_both_not_found_returns_none(self):
        def fake_run(argv, **_kwargs):
            return _cp("LoadState=not-found\nTimeoutStopUSec=1min 30s\n")

        assert (
            systemd_timeout_stop_us(
                "missing.service",
                prefer_scope="system",
                run=fake_run,
                parse_duration=_parse_duration,
            )
            is None
        )

    def test_only_user_loaded_takes_user(self):
        def fake_run(argv, **_kwargs):
            if "--user" in argv:
                return _cp("LoadState=loaded\nTimeoutStopUSec=1min 30s\n")
            return _cp("LoadState=not-found\nTimeoutStopUSec=1min 30s\n")

        got = systemd_timeout_stop_us(
            "hermes-gateway.service",
            prefer_scope=None,
            run=fake_run,
            parse_duration=_parse_duration,
        )
        assert got == 90_000_000
