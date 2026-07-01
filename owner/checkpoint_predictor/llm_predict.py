"""LLM 兜底预测 —— 静态解析失败时, 问 auxiliary LLM 命令会改哪些文件。

复用 agent.auxiliary_client.call_llm(task="approval"), 即和 smart approval
同一条侧路、同一个模型 (默认=主聊天模型)。零新配置面。

同步阻塞调用, 超时即返回空列表 (触发 predictor 不拍快照 + 报错)。
会话内 LRU 缓存 (command, cwd), 避免重复命令重复调模型。
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections import OrderedDict
from typing import List

logger = logging.getLogger(__name__)

# 会话内 LRU 缓存, 键 (command, cwd)
_cache: OrderedDict = OrderedDict()
_cache_lock = threading.Lock()
_CACHE_MAX = 32


def _cache_clear() -> None:
    """清空缓存 (测试用)。"""
    with _cache_lock:
        _cache.clear()


def _cache_get(key: tuple):
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
        return None


def _cache_set(key: tuple, value, max_size: int) -> None:
    with _cache_lock:
        _cache[key] = value
        _cache.move_to_end(key)
        while len(_cache) > max_size:
            _cache.popitem(last=False)


def _build_prompt(command: str, cwd: str) -> str:
    """构造 LLM prompt。"""
    return f"""You are a file-mutation predictor. Given a shell command and its working directory, list the file paths (relative to cwd, or absolute) that this command will create, modify, or delete. Respond with ONLY a JSON array of strings, no prose. If you cannot determine any files, respond with [].

Working directory: {cwd}
Command: {command}

Examples:
  Command: sed -i \'s/a/b/\' foo.py
  Response: ["foo.py"]
  Command: python -c "open(\'out.txt\',\'w\').write(\'x\')"
  Response: ["out.txt"]
  Command: npm run build
  Response: ["dist/"]
  Command: ls -la
  Response: []"""


def _call_llm_sync(
    *,
    messages: list,
    timeout: float,
    max_tokens: int = 200,
) -> object:
    """实际调 auxiliary_client.call_llm (便于测试 mock)。"""
    from agent.auxiliary_client import call_llm

    return call_llm(
        task="approval",
        messages=messages,
        temperature=0,
        max_tokens=max_tokens,
        timeout=timeout,
    )


_JSON_ARRAY_RE = re.compile(r"\[.*?\]", re.DOTALL)


def llm_predict(command: str, cwd: str, timeout_ms: int) -> List[str]:
    """问 LLM 命令会改哪些文件。返回路径列表, 失败返回空列表。"""
    global _CACHE_MAX

    cache_key = (command, cwd)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        response = _call_llm_sync(
            messages=[{"role": "user", "content": _build_prompt(command, cwd)}],
            timeout=timeout_ms / 1000.0,
        )
        content = response.choices[0].message.content or ""
    except Exception as exc:
        logger.debug("checkpoint llm_predict failed: %s", exc)
        _cache_set(cache_key, [], _CACHE_MAX)
        return []

    m = _JSON_ARRAY_RE.search(content)
    if not m:
        _cache_set(cache_key, [], _CACHE_MAX)
        return []

    try:
        parsed = json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        _cache_set(cache_key, [], _CACHE_MAX)
        return []

    if not isinstance(parsed, list):
        _cache_set(cache_key, [], _CACHE_MAX)
        return []

    result = [str(p) for p in parsed if isinstance(p, str) and p.strip()]
    _cache_set(cache_key, result, _CACHE_MAX)
    return result
