"""[owner] "currently doing …" phrase for a bare running tool id.

Shared by busy ack (gateway/run_busy.py), long-run heartbeat
(gateway/run_turn.py) and the C13 progress fact-line
(owner/explainers/progress/activity_i18n.py). Body migrated verbatim from
``agent/display.py`` (commit a6e7e672) so the official module keeps only a
thin delegate (二次开发规范 §2.1/§2.2).

Import direction: only ``agent.i18n`` at module top (leaf official module,
same as the other owner/i18n/ helpers); ``agent.display.get_tool_verb`` is
imported lazily at call time so display ↔ owner stays acyclic at load.
"""

from __future__ import annotations

from agent.i18n import get_language, t


def format_running_tool(tool_name: str | None) -> str:
    """User-facing 'currently doing …' phrase for a bare tool id (busy ack / heartbeat / progress).

    Reuses ``display.verb.<tool>`` via :func:`agent.display.get_tool_verb` (honours
    ``display.friendly_tool_labels``). Chinese → ``正在{verb}`` (terminal → 正在运行命令);
    English → the verb as-is (already progressive). Unknown / labels off →
    ``gateway.busy.running_tool``.
    """
    n = str(tool_name or "").strip()
    if not n:
        return ""
    try:
        from agent.display import get_tool_verb  # lazy: keep display ↔ owner acyclic

        verb = get_tool_verb(n)
    except Exception:
        verb = None
    if not verb:
        return t("gateway.busy.running_tool", tool=n)
    lang = ""
    try:
        lang = str(get_language() or "")
    except Exception:
        lang = ""
    if lang.lower().startswith("zh"):
        return f"正在{verb}"
    return verb


__all__ = ["format_running_tool"]
