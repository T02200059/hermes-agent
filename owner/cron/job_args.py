"""Map stored cron job ``args`` to CLI ``--key value`` flags.

源树（owner 分支）在 ``cron/scheduler._run_job_script`` 内联实现；
v2 按二次开发规范把逻辑放 ``owner/``，官方 ``cron/scheduler_script`` 仅薄胶水。

清单：C23 / §11.2。
"""

from __future__ import annotations

from typing import Any, Mapping


def map_job_args_to_cli(args: Any) -> list[str]:
    """Convert a job ``args`` mapping into argv fragments.

    Rules (byte-compatible with the old owner inline loop):

    * non-mapping / falsy → ``[]``
    * empty key (after ``str().strip()``) → skip
    * ``True`` → ``--key`` alone (boolean flag)
    * ``False`` / ``None`` → skip
    * other values → ``--key`` + ``str(value).strip()``; skip if empty after strip

    Examples::

        {"mode": "pref-card"} → ["--mode", "pref-card"]
        {"BACKUP_QUIET": "1", "timeout_seconds": "1800"}
            → ["--BACKUP_QUIET", "1", "--timeout_seconds", "1800"]
        {"verbose": True, "quiet": False, "x": None, "": "nope"}
            → ["--verbose"]
    """
    if not args or not isinstance(args, Mapping):
        return []
    out: list[str] = []
    for key, value in args.items():
        key_str = str(key).strip()
        if not key_str:
            continue
        if value is True:
            out.append(f"--{key_str}")
        elif value is not None and value is not False:
            value_str = str(value).strip()
            if value_str:
                out.append(f"--{key_str}")
                out.append(value_str)
    return out


def extend_argv_with_job_args(argv: list[str], args: Any) -> list[str]:
    """Append mapped flags onto *argv* (mutates and returns the same list)."""
    argv.extend(map_job_args_to_cli(args))
    return argv
