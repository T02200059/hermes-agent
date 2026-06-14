"""Thinking-mode reasoning_content detectors for xfyun/damodel/GLM providers.

Extracted from run_agent.py per 二次开发规范 §2.1: thin glue in official code,
core logic in owner/.
"""

from __future__ import annotations

from typing import Optional

from utils import base_url_host_matches


def needs_xfyun_damodel_tool_reasoning(provider: Optional[str], model: Optional[str]) -> bool:
    """Return True for xfyun/damodel Coding-Plan thinking-mode models.

    xfyun and damodel front three thinking-mode model families that all
    require ``reasoning_content`` to be echoed back on every assistant
    tool-call turn:

    - ``astron-code-latest`` (xfyun-native Spark code model)
    - GLM family — ``glm-*`` and the ``xopglm*`` aliases (e.g. xopglm51,
      xopglm5) routing to GLM-5.1 / GLM-5
    - Kimi family — ``xopkimik26`` (and any future ``xopkimi*`` /
      ``kimi-*`` aliases) routing to Kimi-K2.6
    """
    if provider not in {"xfyun", "damodel"}:
        return False
    m = (model or "").lower()
    if not m:
        return False
    return (
        m == "astron-code-latest"
        or "glm" in m
        or "kimi" in m
    )


def needs_glm_tool_reasoning(base_url: Optional[str]) -> bool:
    """Return True when the active provider is a GLM thinking endpoint.

    GLMs on the Coding Plan endpoint (genai.damodel.com, open.bigmodel.cn,
    api.z.ai) have thinking enabled by default and require reasoning_content
    to be echoed back on every assistant turn — including tool-call turns
    where the model returned empty reasoning.  Without the echo the API
    rejects the replay with HTTP 400.

    Detection is host-driven so that aggregators re-exporting GLM models
    under their own base_url are not affected.
    """
    return (
        base_url_host_matches(base_url, "genai.damodel.com")
        or base_url_host_matches(base_url, "open.bigmodel.cn")
        or base_url_host_matches(base_url, "api.z.ai")
    )


def needs_owner_reasoning_detection(
    provider: Optional[str],
    model: Optional[str],
    base_url: Optional[str],
) -> bool:
    """Aggregate all owner-specific reasoning_content detection checks."""
    return (
        needs_glm_tool_reasoning(base_url)
        or needs_xfyun_damodel_tool_reasoning(provider, model)
    )
