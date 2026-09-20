"""调辅助 LLM 生成审批命令解说 (永不抛)。

侧路: agent.auxiliary_client.call_llm(task="approval_explainer", ...):
- provider/model 未配置 (None, None) → auxiliary auto 链:
  config.yaml ``auxiliary.approval_explainer`` 段有配置则按任务段生效,
  否则回落主聊天模型 —— 承接 hermes 自己的配置体系 (2026-09-20 定稿)。
- 显式 provider/model → 直连最高优先。
temperature=0、max_tokens≈250、硬超时 (默认 30s, 与 progress_explainer
对齐)。任何异常 / 超时 → None, 静默丢弃, 卡片照发 (fail-open — 审批是
安全关键路径, 解说只是增强)。

同命令短 TTL LRU 缓存: once 审批后同命令再来 → 缓存命中零延迟。
参考 owner/progress_explainer/explain.py 的永不抛风格。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from typing import Optional

from owner.approval_explainer import prompt as prompt_mod
from owner.approval_explainer.config import load_config, resolve_model

logger = logging.getLogger(__name__)

# 输出上限: max_tokens≈250 生成的中文通常 ≤500 字符; 防御性截断更宽。
_MAX_OUTPUT_CHARS = 700
_DEFAULT_TIMEOUT_MS = 30000
_MAX_TOKENS = 250

# 同命令缓存 (模块级, 锁不需要 —— 只在事件循环线程读写; 保守起见
# approval 场景本就单飞)。TTL 默认 600s, 上限 128 条。
_CACHE: "OrderedDict[str, tuple[float, str]]" = OrderedDict()


def _extract_content(response: object) -> Optional[str]:
    """兼容 OpenAI 风格响应 / 裸字符串, 取正文文本。失败返回 None。"""
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
    """基础清理: 去首尾空白、掐掉包裹性引号、去空行、超长截断。"""
    s = (text or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("\"", "'", "“", "‘", "`"):
        s = s[1:-1].strip()
    s = "\n".join(line.strip() for line in s.splitlines() if line.strip())
    if not s:
        return None
    if len(s) > _MAX_OUTPUT_CHARS:
        s = s[:_MAX_OUTPUT_CHARS].rstrip() + "…"
    return s


def _cache_key(command: str, description: str, language: str) -> str:
    raw = f"{command}\x00{description}\x00{language}"
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()


def _cache_get(key: str, ttl: int) -> Optional[str]:
    entry = _CACHE.get(key)
    if entry is None:
        return None
    ts, val = entry
    if ttl > 0 and (time.time() - ts) > ttl:
        _CACHE.pop(key, None)
        return None
    _CACHE.move_to_end(key)
    return val


def _cache_put(key: str, val: str, max_entries: int) -> None:
    _CACHE[key] = (time.time(), val)
    _CACHE.move_to_end(key)
    if max_entries > 0:
        while len(_CACHE) > max_entries:
            _CACHE.popitem(last=False)


def clear_cache() -> None:
    """测试 / 配置切换后清缓存。"""
    _CACHE.clear()


async def explain_command(
    command: str,
    description: str,
    language: str,
    *,
    platform: str = "",
    chat_id: "object | None" = None,
) -> Optional[str]:
    """生成一条审批命令解说文案 (永不抛, 失败/超时/未启用 → None)。

    入参只读; 缓存命中直接返回, 不调 LLM。
    """
    try:
        from owner.approval_explainer.config import resolve_enabled

        if not resolve_enabled(platform, chat_id):
            return None

        cfg = load_config()
        timeout_ms = int(cfg.get("timeout_ms", _DEFAULT_TIMEOUT_MS) or 0)
        if timeout_ms <= 0:
            timeout_ms = _DEFAULT_TIMEOUT_MS
        timeout_s = max(0.5, timeout_ms / 1000.0)

        key = _cache_key(command, description, language)
        cached = _cache_get(key, int(cfg.get("cache_ttl_seconds", 600) or 0))
        if cached is not None:
            return cached

        messages = prompt_mod.build_messages(
            command,
            description,
            language,
            description_max_chars=int(cfg.get("description_max_chars", 500) or 0),
        )
        provider, model = resolve_model(cfg)

        def _call() -> object:
            from agent.auxiliary_client import call_llm  # 延迟导入, 避免 import 期副作用

            return call_llm(
                task="approval_explainer",
                messages=messages,
                temperature=0,
                max_tokens=_MAX_TOKENS,
                timeout=timeout_s,
                provider=provider,  # type: ignore[arg-type]
                model=model,  # type: ignore[arg-type]
            )

        response = await asyncio.wait_for(
            asyncio.to_thread(_call), timeout=timeout_s
        )
        content = _extract_content(response)
        if not content:
            return None
        text = _clean_output(content)
        if text:
            _cache_put(key, text, int(cfg.get("cache_max_entries", 128) or 0))
        return text
    except Exception as exc:  # noqa: BLE001 —— fail-open: 解说缺席不挡审批卡
        logger.debug("approval_explainer explain failed: %s", exc)
        return None
