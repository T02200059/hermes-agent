"""[owner] Scope-aware systemd TimeoutStopUSec probe.

根因：Hub 等进程跑在系统级 unit（cgroup 在 ``system.slice``，``TimeoutStopSec=330``）时，
``systemctl --user show`` 对未加载的同名 unit 仍常返回默认 ``TimeoutStopUSec=1min 30s``
且 ``LoadState=not-found``。旧逻辑只看 TimeoutStopUSec、且固定先 ``--user``，
会把对齐检查误报成 90s < expected。

为何不长期关掉检查：启动时比对 TimeoutStopSec 与 drain 预算仍能抓到真正过期的
unit 文件（升级未 ``hermes setup``）。正确做法是只采纳 ``LoadState=loaded`` 的属性，
并按 cgroup scope 优先探测 system / user。
"""

from __future__ import annotations

import subprocess
from typing import Callable, Optional


def preferred_systemctl_flags(prefer_scope: Optional[str]) -> list[list[str]]:
    """Return ``systemctl`` flag lists in probe order.

    ``system`` → bare (system bus) first, then ``--user``.
    ``user`` or ``None`` → ``--user`` first (hermes 常见默认), then bare.
    """
    if prefer_scope == "system":
        return [[], ["--user"]]
    return [["--user"], []]


def systemd_timeout_stop_us(
    unit_name: str,
    *,
    prefer_scope: Optional[str] = None,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    parse_duration: Optional[Callable[[str], Optional[int]]] = None,
) -> Optional[int]:
    """Return ``TimeoutStopUSec`` in microseconds for a *loaded* unit, else ``None``.

    Probes systemctl scopes in :func:`preferred_systemctl_flags` order. Requests both
    ``LoadState`` and ``TimeoutStopUSec``; only parses the timeout when
    ``LoadState=loaded``. Digits are taken as microseconds; otherwise ``parse_duration``
    (default: lazy import of ``gateway.shutdown_forensics.parse_systemd_duration_to_us``).
    """
    if parse_duration is None:
        from gateway.shutdown_forensics import parse_systemd_duration_to_us as parse_duration

    for flag in preferred_systemctl_flags(prefer_scope):
        try:
            result = run(
                ["systemctl", *flag, "show", unit_name,
                 "--property=LoadState,TimeoutStopUSec"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=2.0,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            continue
        if result.returncode != 0:
            continue
        load_state, timeout_raw = _parse_show_properties(result.stdout)
        if load_state != "loaded" or not timeout_raw:
            continue
        if timeout_raw.isdigit():
            return int(timeout_raw)
        parsed = parse_duration(timeout_raw)
        if parsed is not None:
            return parsed
    return None


def _parse_show_properties(stdout: str) -> tuple[Optional[str], Optional[str]]:
    load_state: Optional[str] = None
    timeout_raw: Optional[str] = None
    for line in stdout.splitlines():
        if line.startswith("LoadState="):
            load_state = line.split("=", 1)[1].strip()
        elif line.startswith("TimeoutStopUSec="):
            timeout_raw = line.split("=", 1)[1].strip()
    return load_state, timeout_raw
