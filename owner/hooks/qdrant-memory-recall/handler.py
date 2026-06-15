"""
qdrant-memory-recall — Gateway Lifecycle Hook

触发点：message:receive
作用：在每条飞书消息到达 LLM 之前，从 Qdrant 5 个 collection 召回
      语义相关条目，拼成 extra_context 注入到 user message。

⚠️ 容错铁律（所有路径都必须遵守）：
  1. 任何异常 → 返回 None，绝不抛给 caller
  2. 单 collection 失败 → warn 跳过，不阻断其他
  3. 总耗时硬上限 total_timeout_sec（默认 10s），接近即返
  4. 0 hit 时不注入（返回 None），绝不返回空字符串
  5. 日志失败不影响主流程（log → try/except 隔离）

模块拆分：recall_config / recall_embedder / recall_searcher / recall_card
"""
# ============================================================
# ⚠️ Per-turn 召回约定（CR-01 2026-06-06 review 结论）
# ============================================================
# 本 hook 返回的 extra_context **只对当次 LLM 调用可见**。
# 它被拼到 message_text 走 _run_agent() 输入，**不会** 写进
# session history（gateway/run.py 只修改 LLM 输入变量，
# 不修改 history 持久化路径）。
# ============================================================

from __future__ import annotations

import asyncio
import secrets
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from pathlib import Path

# Sibling modules (recall_*.py) are loaded via importlib file location.
_hook_dir = str(Path(__file__).resolve().parent)
if _hook_dir not in sys.path:
    sys.path.insert(0, _hook_dir)

from recall_card import build_recall_card_compact  # noqa: E402
from recall_config import load_bot_menu_commands, load_config, logger  # noqa: E402
from recall_embedder import embed_sync  # noqa: E402
from recall_searcher import SYNTHETIC_PREFIXES, format_hit, search_collection_sync  # noqa: E402


async def handle(event_type: str, context: dict) -> dict | None:
    """Gateway lifecycle hook entry. Any exception → None (fail-open)."""
    t_start = time.monotonic()

    cfg = load_config()
    if not cfg.get("enabled", True):
        return None

    message = (context.get("message") or "").strip()
    if len(message) < cfg["min_query_length"]:
        return None

    if message.startswith(SYNTHETIC_PREFIXES):
        return None

    bot_menu_cmds = load_bot_menu_commands()
    if bot_menu_cmds and message in bot_menu_cmds:
        return None

    session_id = context.get("session_id", "")
    deadline = t_start + cfg["total_timeout_sec"]

    try:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = loop.run_in_executor(ex, embed_sync, message, cfg)
            remaining = max(0.1, deadline - time.monotonic())
            vector = await asyncio.wait_for(fut, timeout=remaining)
    except asyncio.TimeoutError:
        logger.warning(
            f"embed overall timeout: elapsed={time.monotonic()-t_start:.1f}s, "
            f"session={session_id}"
        )
        return None
    except Exception as e:
        logger.warning(f"embed runner error: {e}")
        return None

    if vector is None:
        return None

    try:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=len(cfg["collections"])) as ex:
            futures = {
                ex.submit(search_collection_sync, c, vector, cfg): c
                for c in cfg["collections"]
            }
            all_hits: list[dict] = []
            remaining = max(0.1, deadline - time.monotonic())
            done_deadline = time.monotonic() + remaining
            for fut in futures:
                try:
                    time_left = max(0.1, done_deadline - time.monotonic())
                    hits = fut.result(timeout=time_left)
                    all_hits.extend(hits)
                except FutTimeout:
                    logger.warning(f"search timeout: collection={futures[fut]}")
                except Exception as e:
                    logger.warning(f"search error: {e}")
    except Exception as e:
        logger.warning(f"search runner error: {e}")
        return None

    n_filtered_lowq = sum(
        1 for h in all_hits if (h.get("payload") or {}).get("low_quality")
    )
    threshold = cfg["score_threshold"]
    all_hits = [
        h
        for h in all_hits
        if h.get("score", 0) >= threshold
        and not (h.get("payload") or {}).get("low_quality")
        and not (h.get("payload") or {}).get("disabled")
    ]
    all_hits.sort(key=lambda h: h.get("score", 0), reverse=True)
    all_hits = all_hits[: cfg["top_k"]]

    if not all_hits:
        if cfg.get("log_on_empty_recall"):
            logger.info(
                f"no hits | session={session_id} | query={message[:60]} | "
                f"elapsed={(time.monotonic()-t_start)*1000:.0f}ms"
            )
        return None

    body_lines = [cfg["extra_context_header"].rstrip("\n")]
    for h in all_hits:
        body_lines.append(format_hit(h, cfg))
    extra_context = "\n".join(body_lines)

    elapsed_ms = (time.monotonic() - t_start) * 1000
    try:
        logger.info(
            f"recall ok | session={session_id} | hits={len(all_hits)} | "
            f"filtered_lowq={n_filtered_lowq} | "
            f"top_score={all_hits[0].get('score', 0):.3f} | "
            f"query={message[:60]} | elapsed={elapsed_ms:.0f}ms | "
            f"inject_chars={len(extra_context)}"
        )
    except Exception:
        pass

    recall_id = secrets.token_hex(6)
    feishu_card = build_recall_card_compact(all_hits, cfg, elapsed_ms, recall_id)

    return {
        "extra_context": extra_context,
        "feishu_card": feishu_card,
        "feishu_card_cache": {
            "recall_id": recall_id,
            "hits": all_hits,
            "cfg": cfg,
            "elapsed_ms": elapsed_ms,
        },
    }