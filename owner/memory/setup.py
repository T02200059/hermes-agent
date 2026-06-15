"""Runtime setup for the memory proposal approval system.

- Registers ``memory_propose`` as the public memory tool.
- Removes the legacy ``memory`` tool from the registry so models cannot
  bypass the approval gate.
- Patches ``toolsets`` so ``memory`` toolset resolves to ``memory_propose``
  and platform core tool lists no longer advertise the disabled ``memory`` tool.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_patched = False


def _patch_toolsets() -> None:
    """Mutate toolsets at runtime so memory_propose replaces memory.

    Idempotent: runs at most once per process, even if the module is
    re-imported in different contexts (CLI, TUI, gateway).
    """
    global _patched
    if _patched:
        return
    _patched = True
    try:
        import toolsets as _toolsets
        from tools.registry import registry
    except Exception as exc:
        logger.warning("[owner] memory_propose: failed to import toolsets/registry for patch: %s", exc)
        return

    # tools/*.py discovery is alphabetical: memory_propose_tool.py loads before
    # memory_tool.py, so force-register legacy memory here before deregister.
    try:
        import tools.memory_tool  # noqa: F401
    except ImportError as exc:
        logger.debug("[owner] memory_propose: memory_tool unavailable: %s", exc)

    # Deregister legacy memory tool if present.
    try:
        if registry.get_entry("memory") is not None:
            registry.deregister("memory")
            logger.debug("[owner] memory_propose: deregistered legacy memory tool")
    except Exception as exc:
        logger.warning("[owner] memory_propose: failed to deregister memory tool: %s", exc)

    # Replace "memory" with "memory_propose" in the static memory toolset.
    try:
        _memory_ts = _toolsets.TOOLSETS.get("memory")
        if _memory_ts is not None:
            _memory_ts["tools"] = ["memory_propose"]
            _memory_ts["description"] = (
                "Persistent memory across sessions (personal notes + user profile) - requires approval"
            )
    except Exception as exc:
        logger.warning("[owner] memory_propose: failed to patch memory toolset: %s", exc)

    # Remove "memory" from the core tools list so platform toolsets that copy
    # it do not advertise a disabled tool. Platform toolsets that want memory
    # approval should include the "memory" toolset via ``includes``.
    try:
        if "memory" in _toolsets._HERMES_CORE_TOOLS:
            _toolsets._HERMES_CORE_TOOLS.remove("memory")
            logger.debug("[owner] memory_propose: removed memory from _HERMES_CORE_TOOLS")
    except Exception as exc:
        logger.warning("[owner] memory_propose: failed to patch _HERMES_CORE_TOOLS: %s", exc)

    # Ensure key platform toolsets include the memory toolset and do not
    # directly list the disabled legacy "memory" tool.
    _platforms = ("hermes-feishu", "hermes-qqbot")
    for ts_name in _platforms:
        ts = _toolsets.TOOLSETS.get(ts_name)
        if ts is None:
            continue
        tools = ts.get("tools")
        if isinstance(tools, list) and "memory" in tools:
            tools.remove("memory")
        includes = ts.get("includes")
        if includes is None:
            ts["includes"] = ["memory"]
        elif "memory" not in includes:
            includes.append("memory")


_patch_toolsets()
