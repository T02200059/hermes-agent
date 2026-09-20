"""调辅助 LLM 生成进度旁白（永不抛）。

侧路：agent.auxiliary_client.call_llm(task="progress_explainer")，
与设计稿 §2.4 / §7 一致：temperature=0、max_tokens≈200、硬超时。
任何异常 / 超时 → 返回 None，静默丢弃，不发半成品。
参考 owner/checkpoint_predictor/llm_predict.py 的永不抛风格。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from owner.progress_explainer import prompt as prompt_mod

logger = logging.getLogger(__name__)

# 输出上限：max_tokens≈200 生成的中文通常 ≤400 字符；防御性截断更宽。
_MAX_OUTPUT_CHARS = 600
# [owner] 2026-09-20 定稿: 默认 30s (原 15s), 与 approval_explainer 对齐。
_DEFAULT_TIMEOUT_MS = 30000


def _extract_content(response: object) -> Optional[str]:
    """兼容 OpenAI 风格响应 / 裸字符串，取正文文本。失败返回 None。"""
    if isinstance(response, str):
        return response or None
    if response is None:
        return None
    content: object = None
    try:
        choices = getattr(response, "choices", None)
        if choices:
            content = getattr(getattr(choices[0], "message", None), "content", None)
    except Exception:  # noqa: BLE001 —— 结构不符一律视为无输出
        content = None
    if not content or not isinstance(content, str):
        return None
    return content


def _clean_output(text: str) -> Optional[str]:
    """基础清理：去首尾空白、掐掉包裹性引号、去空行、超长截断。"""
    s = (text or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("\"", "'", "“", "‘", "`"):
        s = s[1:-1].strip()
    s = "\n".join(line.strip() for line in s.splitlines() if line.strip())
    if not s:
        return None
    if len(s) > _MAX_OUTPUT_CHARS:
        s = s[:_MAX_OUTPUT_CHARS].rstrip() + "…"
    return s


async def explain(state: dict, cfg: dict, user_message: str, language: str) -> Optional[str]:
    """生成一条进度旁白文案（不带 PREFIX，前缀由投递层拼）。

    永不抛：任何异常 / 超时 / 空输出 → None。
    state/cfg 入参只读；本函数自身无状态。
    """
    try:
        if not isinstance(state, dict) or not isinstance(cfg, dict):
            return None

        timeout_ms = _DEFAULT_TIMEOUT_MS
        try:
            timeout_ms = int(cfg.get("explainer_timeout_ms", _DEFAULT_TIMEOUT_MS))
        except (TypeError, ValueError):
            pass
        if timeout_ms <= 0:
            timeout_ms = _DEFAULT_TIMEOUT_MS
        timeout_s = max(0.5, timeout_ms / 1000.0)

        digest = str(state.get("digest") or "")
        raw_hard = state.get("hard_facts")
        hard_facts = raw_hard if isinstance(raw_hard, dict) else {}
        messages = prompt_mod.build_messages(user_message, digest, hard_facts, language)

        # [owner] 模型解析 (2026-09-20 定稿, 与 approval_explainer 同语义):
        # patch.yaml owner.progress_explainer.provider/model 空 (或 "auto")
        # → 两个都传 None → call_llm(task=...) 走 auxiliary auto 链 ——
        # config.yaml auxiliary.progress_explainer 任务段有配置则按其生效,
        # 否则回落主聊天模型 (承接 hermes 自己的配置体系)。
        # 显式 provider/model → 直连最高优先。
        _provider = str(cfg.get("provider", "") or "").strip() or None
        _model = str(cfg.get("model", "") or "").strip() or None
        if _model and _model.lower() == "auto":
            _model = None

        def _call() -> object:
            from agent.auxiliary_client import call_llm  # 延迟导入，避免 import 期副作用

            return call_llm(
                task="progress_explainer",
                messages=messages,
                temperature=0,
                max_tokens=200,
                timeout=timeout_s,
                provider=_provider,
                model=_model,
            )

        response = await asyncio.wait_for(asyncio.to_thread(_call), timeout=timeout_s)
        content = _extract_content(response)
        if not content:
            return None
        return _clean_output(content)
    except Exception as exc:  # noqa: BLE001 —— 设计稿 §9：静默丢弃，不发半成品
        logger.debug("progress_explainer explain failed: %s", exc)
        return None
