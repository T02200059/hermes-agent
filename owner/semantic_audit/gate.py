"""maybe_audit_batch 编排入口。

副作用全在 owner 内部：
- HALT：为 batch 内每个 tool_call_id 产 synthetic tool result + agent.interrupt()
- BLOCK：gate 自己执行 remaining calls，按原始 tool_calls 顺序拼合全部 results
  （blocked 位置放 synthetic，其余放真实结果），返回 True 跳过下游 dispatch
- 同批有 HALT 级 call 时整批停

协议约束：不改 assistant_message.tool_calls；每个 tool_call_id 有且仅有一条
tool result，顺序与 assistant.tool_calls 一致。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Sequence

from owner.semantic_audit import auditor, detector, notify, policy
from owner.semantic_audit.config import get_semantic_audit_cfg

logger = logging.getLogger(__name__)


def _make_tool_result(name: str, content: str, tool_call_id: str) -> dict:
    try:
        from agent.tool_dispatch_helpers import make_tool_result_message

        return make_tool_result_message(
            name,
            content,
            tool_call_id,
            effect_disposition="none",
        )
    except Exception:
        return {
            "role": "tool",
            "name": name,
            "tool_name": name,
            "content": content,
            "tool_call_id": tool_call_id,
            "effect_disposition": "none",
        }


def _inject_results(messages: list, results: Sequence[dict]) -> None:
    for r in results:
        messages.append(r)


def _invoke_remaining(
    agent: Any,
    call: detector.ClassifiedCall,
    task_id: Optional[str],
    messages: list,
) -> dict:
    """Execute a non-blocked call via agent._invoke_tool; return tool result msg."""
    name = call.name or call.original_name or "unknown"
    args = call.args if isinstance(call.args, dict) else {}
    content: str
    invoke = getattr(agent, "_invoke_tool", None)
    if not callable(invoke):
        content = json.dumps(
            {
                "error": "semantic_audit_dispatch_unavailable",
                "message": (
                    "Blocked sibling filtered; remaining tool could not be "
                    "executed because agent._invoke_tool is missing."
                ),
            },
            ensure_ascii=False,
        )
    else:
        try:
            raw = invoke(
                name,
                args,
                task_id or "default",
                tool_call_id=call.tool_call_id,
                messages=messages,
            )
            if raw is None:
                content = ""
            elif isinstance(raw, str):
                content = raw
            else:
                content = json.dumps(raw, ensure_ascii=False, default=str)
        except Exception as exc:
            logger.exception(
                "semantic_audit: remaining call %s failed during gate dispatch",
                call.tool_call_id,
            )
            content = json.dumps(
                {
                    "error": "semantic_audit_remaining_dispatch_failed",
                    "message": str(exc),
                },
                ensure_ascii=False,
            )
    return _make_tool_result(name, content, call.tool_call_id)


def _notify_halt_user(agent: Any, tool_name: str, reason: str) -> None:
    """Surface HALT to CLI / gateway users (best-effort, never raises)."""
    notice = (
        f"⛔ 语义审计中断\n"
        f"模型尝试执行：{tool_name}\n"
        f"判定原因：{reason}\n"
        f"本轮已终止。"
    )
    try:
        safe_print = getattr(agent, "_safe_print", None)
        if callable(safe_print):
            safe_print(notice)
    except Exception:
        pass
    try:
        cb = getattr(agent, "background_review_callback", None)
        if callable(cb):
            cb(notice)
    except Exception:
        pass


def _notify_block_user(
    agent: Any, blocked_count: int, strikes: int, max_strikes: int
) -> None:
    """Surface BLOCK to CLI / gateway users (lightweight, best-effort)."""
    notice = (
        f"🛡️ 语义审计拦截：{blocked_count} 个越权操作已阻止"
        f"（strike {strikes}/{max_strikes}）"
    )
    try:
        safe_print = getattr(agent, "_safe_print", None)
        if callable(safe_print):
            safe_print(notice)
    except Exception:
        pass
    try:
        cb = getattr(agent, "background_review_callback", None)
        if callable(cb):
            cb(notice)
    except Exception:
        pass


def maybe_audit_batch(
    agent: Any,
    assistant_message: Any,
    messages: list,
    task_id: Optional[str] = None,
) -> bool:
    """Semantic audit gate.

    Returns:
        True  — 跳过后续 tool dispatch（HALT / 全 BLOCK / 混合 BLOCK 已在 gate 内处理完）
        False — 继续 dispatch（无审计动作，tool_calls 原样）
    """
    try:
        return _maybe_audit_batch_impl(agent, assistant_message, messages, task_id)
    except Exception:
        logger.exception("semantic_audit: unexpected error — fail-open")
        return False


def _maybe_audit_batch_impl(
    agent: Any,
    assistant_message: Any,
    messages: list,
    task_id: Optional[str],
) -> bool:
    cfg = get_semantic_audit_cfg()
    if not cfg.get("enabled", False):
        return False

    # cron 默认 enforce；若 cron_enforce=False 可跳过 cron session
    if policy.is_cron_session(agent) and not cfg.get("cron_enforce", True):
        return False

    # yolo 正交：默认 respect_yolo=False → 不关闭审计
    if policy.should_skip_for_yolo(cfg):
        return False

    tool_calls = list(getattr(assistant_message, "tool_calls", None) or [])
    if not tool_calls:
        return False

    classified = detector.classify_batch(tool_calls)

    hardline = [c for c in classified if c.tier == "hardline"]
    tier1 = [c for c in classified if c.tier == "tier1"]

    max_strikes = int(cfg.get("max_strikes") or 2)
    final: Dict[str, Dict[str, Any]] = {}

    # ── Tier 0：直接 HALT ────────────────────────────────────────────
    if hardline:
        for c in classified:
            if c.tier == "hardline":
                final[c.tool_call_id] = {
                    "verdict": "HALT",
                    "reason": c.reason,
                    "hardline": True,
                    "name": c.name,
                }
            else:
                final[c.tool_call_id] = {
                    "verdict": "HALT",
                    "reason": "batch halted by hardline sibling",
                    "hardline": False,
                    "name": c.name,
                    "sibling": True,
                }
        return _apply_halt(agent, messages, classified, final, max_strikes)

    if not tier1:
        return False

    # ── Tier 1：LLM 审计 ─────────────────────────────────────────────
    llm_verdicts = auditor.audit_tier1_calls(
        agent=agent,
        messages=messages,
        assistant_message=assistant_message,
        tier1_calls=tier1,
        cfg=cfg,
    )

    # 先收集原始 verdict；strike 按 batch 计一次，避免同批多 call 连跳
    any_block = False
    any_halt = False
    for c in classified:
        if c.tier == "skip":
            final[c.tool_call_id] = {
                "verdict": "PASS",
                "reason": c.reason,
                "name": c.name,
            }
            continue
        raw = llm_verdicts.get(c.tool_call_id) or {
            "verdict": "BLOCK",
            "reason": "missing audit verdict",
        }
        v = str(raw.get("verdict") or "PASS").upper()
        if v not in {"PASS", "BLOCK", "HALT"}:
            v = "PASS"
        if v == "BLOCK":
            any_block = True
        if v == "HALT":
            any_halt = True
        final[c.tool_call_id] = {
            "verdict": v,
            "reason": raw.get("reason") or c.reason,
            "name": c.name,
        }

    strikes_now = policy.get_strikes(agent)
    if any_block and not any_halt:
        strikes_now = policy.record_block(agent)
        if strikes_now >= max_strikes:
            # 第 N 次 BLOCK 升级整批为 HALT
            any_halt = True
            for tid, info in final.items():
                if info["verdict"] in {"BLOCK", "HALT"}:
                    info["verdict"] = "HALT"
                    info["strikes"] = strikes_now
    elif any_halt:
        strikes_now = policy.get_strikes(agent)

    for info in final.values():
        info["strikes"] = strikes_now

    batch = policy.merge_batch_decision(
        {tid: info["verdict"] for tid, info in final.items()}
    )

    if batch == "HALT":
        # 同批有 HALT：整批停；非 HALT 的 sibling 也注入 skipped
        for tid, info in final.items():
            if info["verdict"] != "HALT":
                info["verdict"] = "HALT"
                info["sibling"] = True
                if not info.get("reason"):
                    info["reason"] = "batch halted by sibling verdict"
        return _apply_halt(agent, messages, classified, final, max_strikes)

    if batch == "BLOCK":
        return _apply_block(
            agent,
            assistant_message,
            messages,
            classified,
            final,
            max_strikes,
            task_id=task_id,
        )

    return False


def _apply_halt(
    agent: Any,
    messages: list,
    classified: Sequence[detector.ClassifiedCall],
    final: Dict[str, Dict[str, Any]],
    max_strikes: int,
) -> bool:
    results = []
    halt_reason = "semantic audit HALT"
    halt_tool = "unknown"
    for c in classified:
        info = final.get(c.tool_call_id) or {}
        hardline = bool(info.get("hardline"))
        sibling = bool(info.get("sibling"))
        reason = str(info.get("reason") or halt_reason)
        if sibling and not hardline:
            content = notify.skipped_sibling_message(c.name)
        else:
            content = notify.halt_message(
                c.name,
                reason,
                strikes=info.get("strikes"),
                hardline=hardline,
            )
            halt_reason = reason
            halt_tool = c.name or c.original_name or halt_tool
        results.append(_make_tool_result(c.name or c.original_name, content, c.tool_call_id))

    _inject_results(messages, results)

    try:
        agent.interrupt(f"[semantic_audit] {halt_reason}")
    except Exception:
        logger.debug("semantic_audit: interrupt failed", exc_info=True)
        # 仍尽量置位
        try:
            agent._interrupt_requested = True
        except Exception:
            pass

    _notify_halt_user(agent, halt_tool, halt_reason)

    logger.warning(
        "semantic_audit HALT session=%s reason=%s calls=%d",
        policy.session_key(agent),
        halt_reason,
        len(classified),
    )
    return True


def _apply_block(
    agent: Any,
    assistant_message: Any,
    messages: list,
    classified: Sequence[detector.ClassifiedCall],
    final: Dict[str, Dict[str, Any]],
    max_strikes: int,
    *,
    task_id: Optional[str] = None,
) -> bool:
    """Handle mixed/all BLOCK without violating OpenAI tool-result protocol.

    Does **not** mutate ``assistant_message.tool_calls``. Executes remaining
    (PASS / skip) calls inside the gate, then extends ``messages`` with one
    tool result per original tool_call_id, in original order.
    Always returns True so downstream dispatch is skipped.
    """
    del assistant_message  # keep signature parity; must not mutate tool_calls
    strikes = policy.get_strikes(agent)
    ordered_results: List[dict] = []
    blocked_count = 0
    remaining_count = 0

    for c in classified:
        info = final.get(c.tool_call_id) or {}
        verdict = (info.get("verdict") or "PASS").upper()
        if verdict == "BLOCK":
            blocked_count += 1
            content = notify.block_message(
                c.name,
                str(info.get("reason") or "out of scope"),
                strikes=int(info.get("strikes") or strikes or 1),
                max_strikes=max_strikes,
            )
            ordered_results.append(
                _make_tool_result(c.name or c.original_name, content, c.tool_call_id)
            )
        else:
            remaining_count += 1
            ordered_results.append(
                _invoke_remaining(agent, c, task_id, messages)
            )

    _inject_results(messages, ordered_results)

    logger.info(
        "semantic_audit BLOCK session=%s blocked=%d remaining=%d strikes=%s",
        policy.session_key(agent),
        blocked_count,
        remaining_count,
        strikes,
    )

    # 用户可见通知（轻量，不打断对话流）
    _notify_block_user(agent, blocked_count, strikes, max_strikes)

    return True
