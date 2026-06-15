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

⚠️ 性能约束（hermes-hooks skill 红线）：
  - handler 协程里禁止用阻塞同步 I/O 卡 gateway event loop
  - 但因为本 hook 走 ThreadPoolExecutor + requests（同步），
    且总延迟 < 1s，gateway 短暂停顿可接受（其他飞书会话独立事件循环）
  - 若将来单 hook 延迟变高（>2s），需改为 aiohttp + asyncio.to_thread
"""
# ============================================================
# ⚠️ Per-turn 召回约定（CR-01 2026-06-06 review 结论）
# ============================================================
# 本 hook 返回的 extra_context **只对当次 LLM 调用可见**。
# 它被拼到 message_text 走 _run_agent() 输入，**不会** 写进
# session history（gateway/run.py:9385 只修改 LLM 输入变量，
# 不修改 history 持久化路径）。
#
# 多轮连续召回由每次新的 message:receive 事件重新触发 hook 保证，
# 不依赖上轮结果。两次不同 query 即使引用了同一段历史信息，
# 也不会复用上轮的召回结果——这是 by design，不是 bug。
#
# 如果未来需要 per-session 召回（即"上轮提到的实体在本轮仍可见"），
# 需要在 gateway 侧把 extra_context 写进 session_entry 或 history
# 的 user message——这是更大的设计变更，不在本 hook 范围内。
# ============================================================

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from pathlib import Path
from typing import Any

import requests
import yaml
from dotenv import dotenv_values

# ============== 日志 ==============

def _log_dir() -> Path:
    from hermes_constants import get_hermes_home

    return get_hermes_home() / "logs"


_LOG_DIR = _log_dir()
_LOG_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("qdrant-memory-recall")
if not logger.handlers:
    _h = logging.FileHandler(_LOG_DIR / "qdrant-memory-recall.log", encoding="utf-8")
    _h.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s"
    ))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

# ============== 配置加载 ==============

_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "top_k": 3,
    "score_threshold": 0.5,
    "per_collection_k": 3,
    "body_max_chars": 300,
    "min_query_length": 5,
    "embed_model": "text-embedding-v4",
    "embed_timeout_sec": 3,  # 单次 3s 兜底 dashscope 限流；总预算 10s 内允许 2 次重试
    "embed_max_retries": 2,
    "collections": ["cases", "entities", "events", "patterns", "preferences"],
    "per_collection_timeout_sec": 2,
    "total_timeout_sec": 10,
    "include_score": True,
    "include_source_collection": True,
    "extra_context_header": (
        "# Retrieved Memory (qdrant 语义召回, top-K 按 cosine 相似度排序)\n\n"
        "以下是从知识库中语义检索到的相关条目，score 为相似度（0-1，越高越相关）：\n"
    ),
    "log_on_empty_recall": False,
}


def _load_config() -> dict[str, Any]:
    """
    从 ~/.hermes/patch.yaml 读 owner.hooks.qdrant_memory_recall。
    找不到路径 → 走 defaults（保证 fail-open 始终能跑）。
    """
    try:
        from hermes_constants import get_hermes_home

        patch_path = get_hermes_home() / "patch.yaml"
        if not patch_path.exists():
            return dict(_DEFAULTS)
        with patch_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        cfg = (data.get("owner", {})
                  .get("hooks", {})
                  .get("qdrant_memory_recall", {}))
        merged = dict(_DEFAULTS)
        merged.update(cfg or {})
        return merged
    except Exception as e:  # 任何解析异常都退化到默认
        logger.warning(f"config load failed, using defaults: {e}")
        return dict(_DEFAULTS)


# ============== 客户端（lazy init）==============

_env_cache: dict | None = None
_bot_menu_cache: set[str] | None = None
_bot_menu_cache_time: float = 0.0
_BOT_MENU_CACHE_TTL: float = 60.0  # 60s 刷一次


def _get_env() -> dict:
    """读 ~/.hermes/.env 里的 DAMODEL/QDRANT 配置。"""
    global _env_cache
    if _env_cache is not None:
        return _env_cache
    try:
        from hermes_constants import get_hermes_home

        env = dotenv_values(get_hermes_home() / ".env")
        _env_cache = {
            "DAMODEL_BASE_URL": (env.get("DAMODEL_BASE_URL") or "").rstrip("/"),
            "DAMODEL_API_KEY": env.get("DAMODEL_API_KEY") or "",
            "QDRANT_URL": (env.get("QDRANT_URL") or "").rstrip("/"),
            "QDRANT_KEY": env.get("QDRANT_KEY") or "",
        }
    except Exception as e:
        logger.error(f".env load failed: {e}")
        _env_cache = {"DAMODEL_BASE_URL": "", "DAMODEL_API_KEY": "",
                      "QDRANT_URL": "", "QDRANT_KEY": ""}
    return _env_cache


def _load_bot_menu_commands() -> set[str]:
    """
    从 ~/.hermes/patch.yaml 读 owner.feishu.bot_menu，返回所有 command 值的集合。
    用于 hook 跳过 bot menu 命令（如 "/new"、"/stop"），这些不是真正的用户查询，
    做语义召回无意义且浪费 API 配额。
    缓存 60s，避免每条消息都重新解析 YAML。
    """
    global _bot_menu_cache, _bot_menu_cache_time
    now = time.monotonic()
    if _bot_menu_cache is not None and (now - _bot_menu_cache_time) < _BOT_MENU_CACHE_TTL:
        return _bot_menu_cache
    try:
        from hermes_constants import get_hermes_home

        patch_path = get_hermes_home() / "patch.yaml"
        if not patch_path.exists():
            _bot_menu_cache = set()
            _bot_menu_cache_time = now
            return _bot_menu_cache
        with patch_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        bot_menu = (data.get("owner", {})
                      .get("feishu", {})
                      .get("bot_menu", {}))
        _bot_menu_cache = set(bot_menu.values()) if isinstance(bot_menu, dict) else set()
        _bot_menu_cache_time = now
    except Exception as e:
        logger.warning(f"bot_menu load failed: {e}")
        _bot_menu_cache = set()
        _bot_menu_cache_time = now
    return _bot_menu_cache


# ============== 核心：embed + search ==============

def _embed_sync(text: str, cfg: dict) -> list[float] | None:
    """
    同步 embed（在线程池里跑）。
    失败（含 401/key 失效/超时）→ 返回 None。
    """
    env = _get_env()
    if not env["DAMODEL_BASE_URL"] or not env["DAMODEL_API_KEY"]:
        logger.warning("DAMODEL env missing, skip embed")
        return None

    timeout = cfg["embed_timeout_sec"]
    model = cfg["embed_model"]
    last_err = None
    for attempt in range(cfg["embed_max_retries"] + 1):
        try:
            resp = requests.post(
                f"{env['DAMODEL_BASE_URL']}/embeddings",
                headers={"Authorization": f"Bearer {env['DAMODEL_API_KEY']}"},
                json={"model": model, "input": text},
                timeout=timeout,
            )
            # 401/403: key 失效，立即返，不重试
            if resp.status_code in (401, 403):
                logger.error(f"embed auth failed (HTTP {resp.status_code}): key 可能失效")
                return None
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
        except requests.exceptions.Timeout:
            last_err = f"embed timeout after {timeout}s"
        except requests.exceptions.RequestException as e:
            last_err = f"embed request error: {e}"
        except Exception as e:
            last_err = f"embed unexpected: {e}"

        if attempt < cfg["embed_max_retries"]:
            time.sleep(0.3 * (attempt + 1))  # 短退避

    logger.warning(f"embed failed after retries: {last_err}")
    return None


def _search_collection_sync(collection: str, vector: list[float], cfg: dict) -> list[dict]:
    """
    同步搜单 collection。失败 → 返回空 list（warn 已记），不抛。

    搜索策略：优先 named vector (dense)，返回 0 条时 fallback 回 unnamed vector。
    兼容 events collection (named) 和其他 collection (unnamed)。
    """
    env = _get_env()
    if not env["QDRANT_URL"] or not env["QDRANT_KEY"]:
        return []
    search_url = f"{env['QDRANT_URL']}/collections/{collection}/points/search"
    headers = {"api-key": env["QDRANT_KEY"], "Content-Type": "application/json"}
    base_params = {"limit": cfg["per_collection_k"], "with_payload": True}

    # Step 1: 优先用 named vector 搜索（events collection 用 dense）
    try:
        resp = requests.post(
            search_url,
            headers=headers,
            json={"vector": {"name": "dense", "vector": vector}, **base_params},
            timeout=cfg["per_collection_timeout_sec"],
        )
        if resp.status_code in (400, 404):
            # 400 可能是 "Not existing vector name"，说明是 unnamed collection，走 fallback
            logger.debug(f"collection={collection} named vector search returned {resp.status_code}, trying fallback")
        else:
            resp.raise_for_status()
            hits = resp.json().get("result", []) or []
            if hits:
                # 有结果，直接返回
                for h in hits:
                    h["_collection"] = collection
                return hits
            # 0 条结果，也走 fallback
            logger.debug(f"collection={collection} named vector search returned 0 hits, trying fallback")
    except requests.exceptions.Timeout:
        logger.warning(f"search timeout (named): collection={collection}")
    except Exception as e:
        logger.debug(f"collection={collection} named vector search error: {e}, trying fallback")

    # Step 2: Fallback 回 unnamed vector 搜索
    try:
        resp = requests.post(
            search_url,
            headers=headers,
            json={"vector": vector, **base_params},
            timeout=cfg["per_collection_timeout_sec"],
        )
        if resp.status_code in (400, 404):
            logger.warning(
                f"collection={collection} skipped (HTTP {resp.status_code}): "
                f"{resp.text[:200]}"
            )
            return []
        resp.raise_for_status()
        hits = resp.json().get("result", []) or []
        for h in hits:
            h["_collection"] = collection
        return hits
    except requests.exceptions.Timeout:
        logger.warning(f"search timeout (unnamed): collection={collection}")
        return []
    except Exception as e:
        logger.warning(f"search error (unnamed): {e}")
        return []


def _format_hit(hit: dict, cfg: dict) -> str:
    """把单条 hit 格式化成 LLM 可见的行。"""
    payload = hit.get("payload") or {}
    uri = payload.get("uri") or f"unknown-{hit.get('id')}"
    score = hit.get("score", 0.0)
    coll = hit.get("_collection", "?")

    # 找正文
    body = (payload.get("content") or payload.get("text")
            or payload.get("description"))
    if not body:
        meta = [f"{k}={v}" for k, v in payload.items()
                if k not in ("uri", "name") and v]
        body = " | ".join(meta) if meta else (payload.get("name") or "")

    body = str(body)
    if len(body) > cfg["body_max_chars"]:
        body = body[: cfg["body_max_chars"]] + "..."

    parts = [f"[uri={uri}"]
    if cfg["include_score"]:
        parts.append(f", score={score:.3f}")
    if cfg["include_source_collection"]:
        parts.append(f", src={coll}")
    parts.append("] ")
    parts.append(body)
    return "".join(parts)


# ============== Gateway 内部合成消息前缀 ==============
# 这些前缀匹配 gateway 内部自动注入的合成 MessageEvent，非用户输入。
# 触发源（gateway/run.py）：
#   - _run_process_watcher (L15846): "[IMPORTANT: Background process proc_xxx completed ..."
#   - _format_gateway_process_notification (L1730): "[IMPORTANT: Background process proc_xxx matched watch pattern ..."
#   - _format_gateway_process_notification (L1724): "[IMPORTANT: ..."
#   - _dispatch_handoff_turn (L4848): "[Session was just handed off from CLI ..."
# 对这类消息做语义召回无意义且浪费 API 配额。

_SYNTHETIC_PREFIXES: tuple[str, ...] = (
    "[IMPORTANT:",
    "[Session was just handed off",
    "[Background process",
)


# ============== 飞书卡片构建 ==============

def _build_recall_card_compact(
    hits: list[dict],
    cfg: dict,
    elapsed_ms: float,
    recall_id: str,
) -> dict:
    """构建飞书 2.0 卡片（compact 阶段：只展示元数据，不含内容）"""
    top_score = hits[0].get("score", 0)  # hits 保证非空（调用方已检查）
    collections = sorted(set(h.get("_collection", "?") for h in hits))

    # 摘要行
    summary = (
        f"**{len(hits)} 条匹配** · 最高 **{top_score:.3f}** · "
        f"{len(collections)} collection · {elapsed_ms:.0f}ms"
    )

    # 每条 hit 的元数据（compact 模式：只展示 collection + score + uri）
    hit_lines = []
    for h in hits:
        payload = h.get("payload") or {}
        uri = payload.get("uri") or f"unknown-{h.get('id')}"
        score = h.get("score", 0.0)
        coll = h.get("_collection", "?")
        # 简化 uri 显示：取最后一段
        short_uri = uri.split("/")[-1] if "/" in uri else uri
        # 标题 fallback: name → abstract → content 首行 # 标题 → short_uri
        title = payload.get("name") or payload.get("abstract")
        if not title:
            _body = payload.get("content") or payload.get("text") or ""
            _first_line = str(_body).split("\n", 1)[0].strip()
            if _first_line.startswith("# "):
                title = _first_line[2:].strip()
        title = str(title or short_uri)
        if len(title) > 35:
            title = title[:32] + "..."
        hit_lines.append(f"• `{coll}` **{score:.3f}** {title}")

    hits_md = "\n".join(hit_lines)

    # 展开按钮
    expand_btn = {
        "tag": "button",
        "text": {"tag": "plain_text", "content": "🔍 展开详情"},
        "type": "default",
        "width": "fill",
        "behaviors": [
            {"type": "callback", "value": {"expand_recall": True, "recall_id": recall_id}}
        ],
    }

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "🧠 知识库召回"},
            "template": "blue",
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": summary},
                {"tag": "hr"},
                {"tag": "markdown", "content": hits_md},
                expand_btn,
            ],
        },
    }


def _build_recall_card_expanded(
    hits: list[dict],
    cfg: dict,
    elapsed_ms: float,
    recall_id: str,
) -> dict:
    """构建飞书 2.0 卡片（expanded 阶段：展示完整内容）"""
    top_score = hits[0].get("score", 0)  # hits 保证非空（调用方已检查）
    collections = sorted(set(h.get("_collection", "?") for h in hits))

    # 摘要行
    summary = (
        f"**{len(hits)} 条匹配** · 最高 **{top_score:.3f}** · "
        f"{len(collections)} collection · {elapsed_ms:.0f}ms"
    )

    # 每条 hit 的完整内容
    hit_elements = []
    for i, h in enumerate(hits):
        payload = h.get("payload") or {}
        uri = payload.get("uri") or f"unknown-{h.get('id')}"
        score = h.get("score", 0.0)
        coll = h.get("_collection", "?")

        # 找正文（复用 _format_hit 的逻辑）
        body = (payload.get("content") or payload.get("text")
                or payload.get("description"))
        if not body:
            meta = [f"{k}={v}" for k, v in payload.items()
                    if k not in ("uri", "name") and v]
            body = " | ".join(meta) if meta else (payload.get("name") or "")
        body = str(body)
        if len(body) > cfg["body_max_chars"]:
            body = body[:cfg["body_max_chars"]] + "..."

        # 分割线（除了第一条）
        if i > 0:
            hit_elements.append({"tag": "hr"})

        # 内容（expanded 模式也展示标题）
        short_uri = uri.split("/")[-1] if "/" in uri else uri
        title = (payload.get("name")
                 or payload.get("abstract")
                 or short_uri)
        title = str(title)
        if len(title) > 80:
            title = title[:77] + "..."
        hit_elements.append({
            "tag": "markdown",
            "content": f"**[{coll}] {score:.3f}** {title}\n{body}",
        })

    # 折叠按钮
    collapse_btn = {
        "tag": "button",
        "text": {"tag": "plain_text", "content": "⬆️ 折叠"},
        "type": "default",
        "width": "fill",
        "behaviors": [
            {"type": "callback", "value": {"collapse_recall": True, "recall_id": recall_id}}
        ],
    }

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "🧠 知识库召回"},
            "template": "blue",
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": summary},
                {"tag": "hr"},
                *hit_elements,
                collapse_btn,
            ],
        },
    }


# ============== 入口 ==============

async def handle(event_type: str, context: dict) -> dict | None:
    """
    Gateway lifecycle hook 入口。

    任何异常 → 返回 None（fail-open），不抛、不污染主对话。
    """
    t_start = time.monotonic()

    # 1. 入口配置（每次重新读，便于热更新 patch.yaml 后下次生效）
    cfg = _load_config()
    if not cfg.get("enabled", True):
        return None

    # 2. 取出消息
    message = (context.get("message") or "").strip()
    if len(message) < cfg["min_query_length"]:
        return None  # 短消息短路

    # 2b. 跳过 gateway 内部构造的合成消息（不触发 embed + 搜索）
    if message.startswith(_SYNTHETIC_PREFIXES):
        return None

    # 2c. 跳过飞书 bot menu 命令（exact match，不触发 embed + 搜索）
    bot_menu_cmds = _load_bot_menu_commands()
    if bot_menu_cmds and message in bot_menu_cmds:
        return None

    session_id = context.get("session_id", "")

    # 3. 总超时守护（剩余预算）
    deadline = t_start + cfg["total_timeout_sec"]

    # 4. embed（在线程池里跑）
    try:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = loop.run_in_executor(ex, _embed_sync, message, cfg)
            remaining = max(0.1, deadline - time.monotonic())
            vector = await asyncio.wait_for(fut, timeout=remaining)
    except asyncio.TimeoutError:
        logger.warning(f"embed overall timeout: "
                       f"elapsed={time.monotonic()-t_start:.1f}s, "
                       f"session={session_id}")
        return None
    except Exception as e:
        logger.warning(f"embed runner error: {e}")
        return None

    if vector is None:
        return None  # key 失效 / 网络问题，embed 函数自己已记 warn

    # 5. 5 collection 并行搜（线程池，最多 5 worker）
    try:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=len(cfg["collections"])) as ex:
            futures = {
                ex.submit(_search_collection_sync, c, vector, cfg): c
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
                    logger.warning(f"search timeout: "
                                   f"collection={futures[fut]}")
                except Exception as e:
                    logger.warning(f"search error: {e}")
    except Exception as e:
        logger.warning(f"search runner error: {e}")
        return None

    # 6. 过滤 + 排序 + 截断
    # 2026-06-08 (C 阶段 B 步骤): 过滤 low_quality=true 的点.
    # 5/30 viking→qdrant 迁移遗留的 584 个空壳点已在 C 阶段打 low_quality 标.
    # 它们只有 uri 没有 content, 召回只会让 LLM "基于 URL 编内容", 高风险.
    # 2026-06-08 (用户裁决权扩展): 过滤 disabled=true 的点.
    # qdrant-knowledge-quality 铁律 6: 用户明确说"删/过时/错"时, AI 直接打 disabled=true,
    # hook 必须自动过滤, 否则用户的"删"意图未闭环 (标了但还在召回). 兼容老的 low_quality 过滤.
    n_filtered_lowq = sum(1 for h in all_hits if (h.get("payload") or {}).get("low_quality"))
    threshold = cfg["score_threshold"]
    all_hits = [h for h in all_hits if h.get("score", 0) >= threshold
                and not (h.get("payload") or {}).get("low_quality")
                and not (h.get("payload") or {}).get("disabled")]
    all_hits.sort(key=lambda h: h.get("score", 0), reverse=True)
    all_hits = all_hits[: cfg["top_k"]]

    # 7. 0 hit 短路
    if not all_hits:
        if cfg.get("log_on_empty_recall"):
            logger.info(
                f"no hits | session={session_id} | "
                f"query={message[:60]} | "
                f"elapsed={(time.monotonic()-t_start)*1000:.0f}ms"
            )
        return None

    # 8. 拼 extra_context（给 LLM + 其他平台 fallback，不变）
    body_lines = [cfg["extra_context_header"].rstrip("\n")]
    for h in all_hits:
        body_lines.append(_format_hit(h, cfg))
    extra_context = "\n".join(body_lines)

    # 9. 记成功日志
    elapsed_ms = (time.monotonic() - t_start) * 1000
    try:
        logger.info(
            f"recall ok | session={session_id} | "
            f"hits={len(all_hits)} | filtered_lowq={n_filtered_lowq} | "
            f"top_score={all_hits[0].get('score', 0):.3f} | "
            f"query={message[:60]} | elapsed={elapsed_ms:.0f}ms | "
            f"inject_chars={len(extra_context)}"
        )
    except Exception:
        pass  # 日志失败不阻断

    # 10. 构建飞书卡片（新增，只用于飞书渠道用户侧展示）
    recall_id = secrets.token_hex(6)
    feishu_card = _build_recall_card_compact(all_hits, cfg, elapsed_ms, recall_id)

    return {
        "extra_context": extra_context,  # 给 LLM + 其他平台 fallback
        "feishu_card": feishu_card,       # 飞书专属卡片（compact 阶段）
        "feishu_card_cache": {            # 卡片回调缓存数据
            "recall_id": recall_id,
            "hits": all_hits,
            "cfg": cfg,
            "elapsed_ms": elapsed_ms,
        },
    }
