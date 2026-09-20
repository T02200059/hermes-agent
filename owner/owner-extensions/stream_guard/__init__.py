"""[owner] stream_guard — 生成中退化闸门（thinking / 输出阶段边界循环）。

背景
----
2026-09-17 16:20:58 → 16:25:14，会话 `20260917_122148_57701e`（cli / xy-max）
单轮生成 30,742 字符不收敛，形态是**思考→输出阶段边界循环**：反复宣告
"思考结束、现在输出"而永不输出，尾部 8% 全是 `END OF THINKING` /
`WRITING RESPONSE` / `(stop)(stop)(stop)`。本轮最终由人工 Ctrl-C 结束
（`agent.log`: `Turn ended: reason=interrupted_during_api_call`）。
取证、根因与设计见 owner/docs/degenerate-stream-guard-design.md。

为什么既有防线都没拦住
----------------------
- `output_guard`（transform_llm_output）只在**整轮生成结束之后**判定；
- `TurnLivenessWatchdog` 是**空闲**看门狗：流式每个 chunk 都
  `_touch_activity("receiving stream response")`，活动时钟永远新鲜 → 永不触发；
- 缺的是 **progress（质量）看门狗**：动静很大、但零进展。本模块就是它。

工作方式
--------
消费 `on_stream_delta` 观察钩子，在每个流式窗口上做三信号 2/3 投票，
命中则（按配置）中止本轮并主动告知用户：

- **S1 阶段终止语密度**（命中次数 / KB）：`END OF THINKING`、
  `WRITING RESPONSE`、`思考结束`、`(stop)` 这类"宣布即将输出"的元话语。
  它出现得越密，说明模型正在把「终止条件」当内容生成 —— 今日事故的本体形态。
- **S2 风格签名密度**（相对基线倍数）：画像风格 token（如 `ฅ`）的密度 / KB
  除以配置基线。实测正常长回复 0.5–1.0/KB，事故 29.6/KB（≈30×）。
  只用"密度异常"，不做二值判定 —— 签名本身是风格特征，正常回复也带它。
- **S3 零进展窗口**：窗口文本被 `agent.repetition_guard.is_repetition_dominated`
  判为复读主导。对今日「词汇多样、语义空转」的形态判别力中等（事故样本
  本身 S3=0），但对**纯复读**形态是硬信号 —— 在 324 条真实长回复上命中 6 条、
  逐条核对全部是真复读事故（精度 100%），故 S3 命中即触发（`s3_solo`）。

误伤控制（沿用 output_guard v1/v2 的多信号哲学）
----------------------------------------------
- `min_stream_chars`：短回复根本不判；
- `grace_seconds`：首个 delta 之后 N 秒内不判，给正常长思考留余地；
- `vote_threshold`（默认 2/3）：S1/S2 单信号不动作，必须互证；
- `s3_solo`：S3 是唯一例外 —— 它复用官方既有守卫，且实测零误报；
- `max_actions_per_turn`：每轮最多动作一次（思考窗口与正文窗口共用 latch）；
- `action: warn_only` 灰度：只告警不中断，用来收集真实误伤率。

落地顺序：先 `warn_only` 跑一周 → 看 `agent.log` 里 `stream_guard trip` 行的
signals 分布与误伤 → 再切 `interrupt`。

契约
----
- `on_stream_delta` 在**独立线程**回调（`agent/plugin_stream_hooks.py` 的
  per-consumer worker），本模块状态全部加锁，O(1)/delta，评估每
  `eval_interval_chars` 才做一次；
- 任何异常都吞掉：观察者绝不影响 token 路径；
- 中止复用载荷里的 `request_stop` 回调（`run_agent.py::_request_stream_stop`），
  它自带"轮次一致 + 每轮一次"的重入保护；
- 用户通知复用 `agent._emit_warning()`，agent 句柄经
  `request_stop.__self__` 取回（观察钩子载荷不含 agent，这是 route B 的唯一回溯）。

配置：`~/.hermes/patch.yaml` → `owner.stream_guard`（见 owner/config/patch.yaml）
设计文档：owner/docs/degenerate-stream-guard-design.md
自检：`python owner/owner-extensions/stream_guard/selfcheck.py`
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 默认配置 —— owner/patch.yaml 的 owner.stream_guard 段可逐项覆盖
# ---------------------------------------------------------------------------
DEFAULTS: dict = {
    "enabled": True,
    # warn_only：只告警不中止（灰度用）；interrupt：真正中止本轮
    "action": "warn_only",
    # 低于此累计字符数不做任何判定
    "min_stream_chars": 1200,
    # 首个 delta 之后这么多秒内不判定（正常长思考的缓冲）
    "grace_seconds": 20.0,
    # 信号评估窗口（尾部 N 字符）
    "window_chars": 4096,
    # 每积累这么多新字符才做一次窗口评估（摊销成本）
    "eval_interval_chars": 512,
    # 三信号中命中几个即触发
    "vote_threshold": 2,
    # S3 单独即可触发。is_repetition_dominated 是官方既有守卫，精度实测 100%
    # （见下方 S3 注释），复读型失控若也要求投票会整体漏掉。
    "s3_solo": True,
    # S1：窗口内阶段终止语命中次数 / KB 的下限
    # 标定依据（2026-09-17，324 条真实长回复 + 事故样本）：
    #   事故 4.15/KB；负样本峰值 2.41/KB（恰好是一条讨论本次事故、引用
    #   了 END OF THINKING 等字样的回复）→ 取 3.0 两侧余量最平衡。
    "marker_rate_per_kb": 3.0,
    # S2：窗口内签名密度相对基线的倍数下限
    "signature_rate_multiple": 8.0,
    # S2 基线：正常回复的签名密度（/KB）。实测长回复 0.5–1.0，取 1.0。
    "signature_baseline_per_kb": 1.0,
    # S2 签名 token（按 profile 配置；空列表 = 关闭 S2）
    "signature_tokens": ["ฅ"],
    # 每轮最多动作次数
    "max_actions_per_turn": 1,
}

# S1：宣布"即将进入输出阶段"的元话语。命中密度异常 = 模型在拿终止条件当内容。
_MARKER_RE = re.compile(
    r"END\s+OF\s+(?:THE\s+)?THINKING"
    r"|DONE\s+THINKING"
    r"|STOP(?:PED)?\s+THINKING"
    r"|FINISH(?:ED)?\s+THINKING"
    r"|THINKING\s+(?:HAS\s+)?(?:ENDED|IS\s+DONE|DONE|FINISHED)"
    r"|WRIT(?:E|ING)\s+(?:THE\s+|MY\s+|A\s+)?RESPONSE"
    r"|NOW\s+OUTPUTTING"
    r"|RESPONSE\s+FOLLOWS"
    r"|OUTPUT(?:TING)?\s+THE\s+RESPONSE"
    r"|思考(?:已经|已)?(?:结束|完成)"
    r"|停止思考"
    r"|结束思考"
    r"|以下(?:是|为)(?:我的)?(?:最终)?(?:回答|回复|答案)"
    r"|(?:开始|现在)(?:正式)?(?:输出|回答)"
    r"|\((?:stop|done|end)\)",
    re.IGNORECASE,
)

# 窗口/动作表的存活与容量上限（长驻进程防累积）
_WINDOW_TTL_SECONDS = 900.0
_MAX_WINDOWS = 64
# 配置读取的本地缓存（patch.yaml 本身另有 mtime + 60s TTL 缓存）
_CFG_TTL_SECONDS = 5.0


@dataclass
class _Window:
    """单个 (session, turn, channel, iteration) 的流式滑窗。"""

    session_id: str
    turn_id: str
    kind: str
    iteration: int
    started_at: float
    total_chars: int = 0
    evaluated_at: int = 0
    buf: str = ""
    signals: dict = field(default_factory=dict)
    tripped: bool = False


_STATE: dict = {}
_ACTIONS: dict = {}
_LOCK = threading.Lock()
_CFG_CACHE: dict = {"data": None, "loaded_at": 0.0}
# S3 失能只告警一次（见 evaluate_window 内注释）
_S3_DEGRADED_WARNED = False


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
def _load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        from owner.patch_config import load_patch_config

        patch = (load_patch_config() or {}).get("stream_guard")
        if isinstance(patch, dict):
            for key, value in patch.items():
                if key in cfg:
                    cfg[key] = value
    except Exception:
        logger.debug("stream_guard: patch.yaml load failed", exc_info=True)
    tokens = cfg.get("signature_tokens")
    if isinstance(tokens, str):
        tokens = [tokens]
    cfg["signature_tokens"] = tuple(
        t for t in (tokens or ()) if isinstance(t, str) and t
    )
    return cfg


def config() -> dict:
    """带 TTL 缓存的配置读取（每个 delta 都会调用，需廉价且 fail-open）。"""
    now = time.time()
    cached = _CFG_CACHE.get("data")
    if cached is not None and now - _CFG_CACHE.get("loaded_at", 0.0) < _CFG_TTL_SECONDS:
        return cached
    try:
        fresh = _load_config()
    except Exception:
        logger.debug("stream_guard: config load failed", exc_info=True)
        fresh = dict(DEFAULTS)
    _CFG_CACHE["data"] = fresh
    _CFG_CACHE["loaded_at"] = now
    return fresh


# ---------------------------------------------------------------------------
# 信号
# ---------------------------------------------------------------------------
def evaluate_window(buf: str, cfg: dict) -> dict:
    """对窗口文本做三信号判定。纯函数，便于离线回放与自检。"""
    kb = len(buf) / 1000.0
    out = {
        "window_chars": len(buf),
        "kb": round(kb, 3),
        "s1_marker_rate": 0.0,
        "s2_signature_multiple": 0.0,
        "s3_no_progress": 0,
        "votes": 0,
        "trip": False,
    }
    if kb <= 0:
        return out

    votes = 0

    # S1 —— 阶段终止语密度
    s1 = len(_MARKER_RE.findall(buf)) / kb
    out["s1_marker_rate"] = round(s1, 3)
    try:
        if s1 >= float(cfg.get("marker_rate_per_kb", DEFAULTS["marker_rate_per_kb"])):
            votes += 1
    except Exception:
        pass

    # S2 —— 风格签名密度（相对基线倍数）
    tokens = cfg.get("signature_tokens") or ()
    if tokens:
        try:
            baseline = float(cfg.get("signature_baseline_per_kb") or 0.0) or 1.0
            hits = sum(buf.count(t) for t in tokens)
            s2 = (hits / kb) / baseline
            out["s2_signature_multiple"] = round(s2, 3)
            if s2 >= float(
                cfg.get("signature_rate_multiple", DEFAULTS["signature_rate_multiple"])
            ):
                votes += 1
        except Exception:
            pass

    # S3 —— 零进展（复用官方 repetition_guard，不重写）
    try:
        from agent.repetition_guard import is_repetition_dominated

        if is_repetition_dominated(buf):
            out["s3_no_progress"] = 1
            votes += 1
    except Exception as exc:
        # 单次告警而非逐窗口 debug：S3 不可用是**永久性**失能（上游改名/移动模块），
        # 且它承载的是本仓历史事故里最常见的一类（纯复读，实测精度 100%）。
        # 静默 fail-open 会让这一整类失去唯一防线且毫无信号，故必须留痕一次。
        global _S3_DEGRADED_WARNED
        if not _S3_DEGRADED_WARNED:
            _S3_DEGRADED_WARNED = True
            logger.warning(
                "stream_guard: S3 (repetition guard) UNAVAILABLE — 纯复读型失控"
                " 本轮起无防线，仅剩 S1/S2 投票：%s", exc,
            )

    out["votes"] = votes
    try:
        # S3 单独成立：`is_repetition_dominated` 是官方既有守卫（60+ 字符窗口
        # 重复 ≥5 次且覆盖 ≥50% 才判），`conversation_loop` 本就把它当硬护栏。
        # 2026-09-17 标定：全库 324 条真实长回复里 S3 命中 6 条，逐条核对
        # **全部是真正的复读事故**（265,518 / 262,157 / 12,180×3 / 7,819），
        # 精度 100%。而 S1/S2 对"纯复读"形态不敏感（事故 S1=0、S2=0），
        # 若坚持 2/3 投票就会把这一类整片漏掉 —— 它恰恰是本仓历史事故里
        # 最常见的一类。故 S3 命中即触发。
        if out["s3_no_progress"] and bool(cfg.get("s3_solo", DEFAULTS["s3_solo"])):
            out["trip"] = True
            return out
        out["trip"] = votes >= int(cfg.get("vote_threshold", DEFAULTS["vote_threshold"]))
    except Exception:
        out["trip"] = False
    return out


# ---------------------------------------------------------------------------
# 动作
# ---------------------------------------------------------------------------
def _resolve_agent(request_stop):
    """经绑定方法回溯 agent 句柄 —— 观察钩子载荷里没有 agent。

    只有确认拿到的是本仓 `RunAgent._request_stream_stop` 才返回，
    避免把任意 callable 的 `__self__` 当 agent 用。
    """
    fn = getattr(request_stop, "__func__", None)
    if fn is None or getattr(fn, "__name__", "") != "_request_stream_stop":
        return None
    return getattr(request_stop, "__self__", None)


def _notify(agent, message: str) -> None:
    """复用既有告警通道：CLI 立即可见 + 网关转平台消息。"""
    try:
        emit = getattr(agent, "_emit_warning", None)
        if callable(emit):
            emit(message)
    except Exception:
        logger.debug("stream_guard: _emit_warning failed", exc_info=True)


def _build_message(sig: dict, cfg: dict, *, kind: str, model: str, interrupted: bool,
                   stopped: bool, action: str) -> str:
    verdict = "已中止本轮生成。" if (action == "interrupt" and stopped) else (
        "灰度观察模式，本轮未中止。" if action != "interrupt"
        else "中止请求未被采纳（轮次可能已结束，或已有其它中断）。"
    )
    return (
        f"⚠️ [stream-guard] 检测到生成退化（思考/输出阶段边界循环），{verdict}\n"
        f"   判定：阶段终止语 {sig['s1_marker_rate']:.1f}/KB、"
        f"风格签名 ×{sig['s2_signature_multiple']:.1f}"
        f"（基线 {cfg.get('signature_baseline_per_kb', 1.0)}/KB）、"
        f"零进展 {sig['s3_no_progress']}；"
        f"命中 {sig['votes']} 项信号（阈值 {cfg.get('vote_threshold', 2)}）\n"
        f"   窗口 {sig['window_chars']} 字符；通道 {kind}；模型 {model or '-'}"
        + ("；本轮生成已被中断。" if interrupted else "")
    )


def _act(*, cfg: dict, sig: dict, session_id: str, turn_id: str, kind: str,
         model: str, request_stop, streaming_chars: int) -> None:
    """执行一次动作（告警 / 中止）。调用方已释放锁。"""
    action = str(cfg.get("action") or DEFAULTS["action"]).lower()
    interrupt = action == "interrupt"
    agent = _resolve_agent(request_stop)
    if agent is None and request_stop is not None:
        logger.debug(
            "stream_guard: no agent handle recovered from request_stop; "
            "abort still attempted, user notification skipped"
        )

    stopped = False
    if interrupt and callable(request_stop):
        try:
            stopped = bool(
                request_stop(
                    reason=(
                        f"degenerate stream: {sig['votes']} signals "
                        f"(s1={sig['s1_marker_rate']}/KB, "
                        f"s2=x{sig['s2_signature_multiple']}, "
                        f"s3={sig['s3_no_progress']}) chars={streaming_chars}"
                    ),
                    turn_id=turn_id if turn_id != "-" else "",
                )
            )
        except Exception:
            logger.debug("stream_guard: request_stop failed", exc_info=True)
            stopped = False

    logger.warning(
        "stream_guard trip session=%s turn=%s kind=%s action=%s stopped=%s "
        "streaming_chars=%s signals=%s",
        session_id, turn_id, kind, action, stopped, streaming_chars, sig,
    )

    if agent is not None:
        _notify(
            agent,
            _build_message(
                sig, cfg, kind=kind, model=model,
                interrupted=interrupt, stopped=stopped, action=action,
            ),
        )


# ---------------------------------------------------------------------------
# 观察钩子
# ---------------------------------------------------------------------------
def _prune(now: float) -> None:
    """丢弃过期窗口与动作计数（调用方持锁）。"""
    cutoff = now - _WINDOW_TTL_SECONDS
    for key in [k for k, w in _STATE.items() if w.started_at < cutoff]:
        _STATE.pop(key, None)
    if len(_STATE) > _MAX_WINDOWS:
        excess = len(_STATE) - _MAX_WINDOWS
        oldest = sorted(_STATE.items(), key=lambda kv: kv[1].started_at)[:excess]
        for key, _ in oldest:
            _STATE.pop(key, None)
    for key in [k for k, v in _ACTIONS.items() if v[1] < cutoff]:
        _ACTIONS.pop(key, None)


def _observe_impl(*, delta, kind, session_id, turn_id, iteration, model,
                  provider, surface, request_stop) -> None:
    if not delta or not isinstance(delta, str):
        return
    cfg = config()
    if not bool(cfg.get("enabled", True)):
        return

    now = time.time()
    sid = session_id or "-"
    tid = turn_id or "-"
    chan = kind or "text"
    skey = (sid, tid, chan, int(iteration or 0))
    akey = (sid, tid)

    action_payload = None
    try:
        win_chars_cfg = int(cfg.get("window_chars") or DEFAULTS["window_chars"])
    except Exception:
        win_chars_cfg = DEFAULTS["window_chars"]

    with _LOCK:
        _prune(now)
        win = _STATE.get(skey)
        if win is None:
            win = _Window(
                session_id=sid, turn_id=tid, kind=chan,
                iteration=int(iteration or 0), started_at=now,
            )
            _STATE[skey] = win
        win.total_chars += len(delta)
        win.buf = (win.buf + delta)[-win_chars_cfg:] if win_chars_cfg > 0 else win.buf + delta

        if not win.tripped:
            try:
                grace = float(cfg.get("grace_seconds", DEFAULTS["grace_seconds"]))
                min_chars = int(cfg.get("min_stream_chars", DEFAULTS["min_stream_chars"]))
                interval = int(cfg.get("eval_interval_chars", DEFAULTS["eval_interval_chars"]))
                max_actions = int(cfg.get("max_actions_per_turn", DEFAULTS["max_actions_per_turn"]))
            except Exception:
                grace, min_chars, interval, max_actions = 20.0, 1200, 512, 1

            if now - win.started_at >= grace and win.total_chars >= min_chars \
                    and win.total_chars - win.evaluated_at >= interval:
                win.evaluated_at = win.total_chars
                sig = evaluate_window(win.buf, cfg)
                win.signals = sig
                if sig["trip"]:
                    win.tripped = True
                    acted, _ = _ACTIONS.get(akey, (0, now))
                    if acted < max_actions:
                        _ACTIONS[akey] = (acted + 1, now)
                        action_payload = (sig, win.total_chars)

    if action_payload is None:
        return
    sig, streaming_chars = action_payload
    _act(
        cfg=cfg, sig=sig, session_id=sid, turn_id=tid, kind=chan,
        model=model, request_stop=request_stop, streaming_chars=streaming_chars,
    )


def observe(
    delta: str = "",
    *,
    kind: str = "text",
    session_id: str = "",
    turn_id: str = "",
    iteration: int = 0,
    model: str = "",
    provider: str = "",
    surface: str = "",
    request_stop=None,
    **kwargs,
) -> None:
    """`on_stream_delta` 回调体。

    在 dispatcher 线程上运行；任何异常都吞掉 —— 观察者绝不影响 token 路径。
    """
    try:
        _observe_impl(
            delta=delta, kind=kind, session_id=session_id, turn_id=turn_id,
            iteration=iteration, model=model, provider=provider,
            surface=surface, request_stop=request_stop,
        )
    except Exception:
        logger.debug("stream_guard observe failed", exc_info=True)


def register_hooks(ctx) -> None:
    """由 owner-extensions 聚合调用。"""
    ctx.register_hook("on_stream_delta", observe)
    logger.debug("stream_guard: on_stream_delta hook registered")


def snapshot(session_id: str = "", turn_id: str = "") -> dict:
    """公开只读快照（progress_explainer 让位判定用，设计稿 §8）。

    返回 ``{"total_chars": int, "tripped": bool, "signals": dict|None,
    "kinds": {kind: chars}}``。session/turn 为空时聚合所有窗口。
    只读 ``_STATE``，不加动作、不触发评估；任何异常 → 空 dict。
    """
    try:
        sid = session_id or "-"
        tid = turn_id or "-"
        total = 0
        tripped = False
        signals = None
        kinds: dict = {}
        with _LOCK:
            for win in _STATE.values():
                if win.session_id != sid or win.turn_id != tid:
                    continue
                total += win.total_chars
                kinds[win.kind] = kinds.get(win.kind, 0) + win.total_chars
                if win.tripped:
                    tripped = True
                    if signals is None:
                        signals = dict(win.signals) if win.signals else {}
        return {
            "total_chars": total,
            "tripped": tripped,
            "signals": signals or {},
            "kinds": kinds,
        }
    except Exception:
        return {}


def reset_state() -> None:
    """清空窗口/动作表（自检与测试用）。"""
    with _LOCK:
        _STATE.clear()
        _ACTIONS.clear()
    _CFG_CACHE["data"] = None
    _CFG_CACHE["loaded_at"] = 0.0
