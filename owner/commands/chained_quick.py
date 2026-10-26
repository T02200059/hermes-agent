"""Chained quick-command helpers (``;;`` split + alias expand).

[owner] C19 — shared by CLI / gateway / TUI thin glue. Official surfaces
dispatch the resulting list themselves (sync vs async).
"""

from __future__ import annotations


def parse_chained_commands(text: str, sep: str = ";;") -> list[str]:
    """Split ``text`` on *sep* and return non-empty stripped fragments.

    ``"/model x ;; /reasoning low"`` → ``["/model x", "/reasoning low"]``

    If *sep* is absent the original text is returned as a single-element list.
    """
    if not text or sep not in text:
        return [text] if text else []
    return [cmd.strip() for cmd in text.split(sep) if cmd.strip()]


def expand_chained_quick_alias(target: str, user_args: str = "") -> list[str]:
    """Build chain text from alias target + user args and split on ``;;``.

    Central helper so CLI / gateway / TUI agree on where a chain breaks.
    """
    chain_text = f"{target} {user_args}".strip()
    return parse_chained_commands(chain_text)


def strip_leading_slash(cmd: str) -> str:
    """Normalize a fragment for TUI ``type: chain`` payloads (handler adds ``/``)."""
    return cmd[1:] if cmd.startswith("/") else cmd


def ensure_leading_slash(cmd: str) -> str:
    """Normalize a fragment for CLI / gateway re-dispatch."""
    return cmd if cmd.startswith("/") else f"/{cmd}"
