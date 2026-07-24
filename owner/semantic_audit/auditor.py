"""构造 audit payload + call_llm + 解析 verdict。

LLM 调用：call_llm(task="semantic_audit", ...) 同步，timeout 默认 5s。
fail 策略：已标危险(tier1/hardline 已分流)的 call → BLOCK；未标危险 → PASS。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Sequence

from owner.semantic_audit.detector import ClassifiedCall

logger = logging.getLogger(__name__)

_USER_CLIP = 300
_ASSIST_CLIP = 500
_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _msg_content(msg: Any) -> str:
    if isinstance(msg, dict):
        c = msg.get("content")
    else:
        c = getattr(msg, "content", None)
    if c is None:
        return ""
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for p in c:
            if isinstance(p, dict) and p.get("type") == "text":
                parts.append(str(p.get("text") or ""))
            elif isinstance(p, str):
                parts.append(p)
        return "\n".join(parts)
    return str(c)


def extract_user_instructions(
    messages: Sequence[Any],
    agent: Any = None,
    *,
    max_items: int = 3,
) -> List[str]:
    """最近 2-3 条用户指令。

    压缩安全：优先 agent 上的 turn 快照（若存在），否则扫 messages。
    """
    snapshot = getattr(agent, "_semantic_audit_user_snapshot", None) if agent else None
    if isinstance(snapshot, list) and snapshot:
        return [_clip(str(s), _USER_CLIP) for s in snapshot[-max_items:]]

    # turn-start 原文（若 conversation 层挂过）
    if agent is not None:
        for attr in (
            "_semantic_audit_turn_user",
            "_persist_user_message_override",
            "_pending_cli_user_message",
        ):
            val = getattr(agent, attr, None)
            if isinstance(val, str) and val.strip():
                # 仍扫 history 凑满 2-3 条
                break

    users: List[str] = []
    for msg in messages or []:
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
        if role == "user":
            text = _msg_content(msg).strip()
            if text:
                users.append(_clip(text, _USER_CLIP))
    # 优先 turn 快照原文 prepend
    if agent is not None:
        for attr in ("_semantic_audit_turn_user", "_persist_user_message_override"):
            val = getattr(agent, attr, None)
            if isinstance(val, str) and val.strip():
                clipped = _clip(val, _USER_CLIP)
                if not users or users[-1] != clipped:
                    users.append(clipped)
                break
    return users[-max_items:]


def extract_assistant_text(assistant_message: Any) -> str:
    content = getattr(assistant_message, "content", None)
    if content is None and isinstance(assistant_message, dict):
        content = assistant_message.get("content")
    if isinstance(content, list):
        return _clip(_msg_content({"content": content}), _ASSIST_CLIP)
    return _clip(str(content or ""), _ASSIST_CLIP)


def extract_prior_tool_calls(messages: Sequence[Any], *, limit: int = 12) -> List[Dict[str, Any]]:
    """本轮已执行的 tool 结果摘要（从 messages 尾部回看）。"""
    prior: List[Dict[str, Any]] = []
    for msg in messages or []:
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
        if role != "tool":
            continue
        name = ""
        if isinstance(msg, dict):
            name = str(msg.get("name") or msg.get("tool_name") or "")
            tid = str(msg.get("tool_call_id") or "")
            content = str(msg.get("content") or "")[:120]
        else:
            name = str(getattr(msg, "name", "") or "")
            tid = str(getattr(msg, "tool_call_id", "") or "")
            content = str(getattr(msg, "content", "") or "")[:120]
        prior.append({"name": name, "tool_call_id": tid, "preview": content})
    return prior[-limit:]


def build_audit_prompt(
    *,
    user_instructions: List[str],
    assistant_text: str,
    tier1_calls: Sequence[ClassifiedCall],
    prior_tools: Sequence[Dict[str, Any]],
) -> List[Dict[str, str]]:
    calls_payload = []
    for c in tier1_calls:
        # 截断 args 防 prompt 膨胀
        try:
            args_s = json.dumps(c.args, ensure_ascii=False)
        except (TypeError, ValueError):
            args_s = str(c.args)
        if len(args_s) > 400:
            args_s = args_s[:399] + "…"
        calls_payload.append(
            {
                "tool_call_id": c.tool_call_id,
                "name": c.name,
                "args": args_s,
                "detector_reason": c.reason,
            }
        )

    system = (
        "You are a semantic audit gate for an AI agent. "
        "Decide whether each proposed tool call stays within the user's instructions. "
        "PASS = allowed; BLOCK = refuse this call but agent may continue; "
        "HALT = refuse and stop the whole turn (use for clear, aggressive overreach "
        "or irreversible destructive intent). "
        "Respond with ONLY a JSON object of the form:\n"
        '{"verdicts":{"<tool_call_id>":{"verdict":"PASS|BLOCK|HALT","reason":"..."}}}\n'
        "No prose outside JSON."
    )
    user = {
        "user_instructions": user_instructions,
        "assistant_text": assistant_text,
        "proposed_tool_calls": calls_payload,
        "already_executed_tools": list(prior_tools),
    }
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(user, ensure_ascii=False),
        },
    ]


def _call_llm_sync(
    *,
    messages: list,
    timeout: float,
    provider: str = "auto",
    model: str = "auto",
    max_tokens: int = 400,
) -> Any:
    from agent.auxiliary_client import call_llm

    kwargs: Dict[str, Any] = {
        "task": "semantic_audit",
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
        "timeout": timeout,
    }
    # provider/model "auto" 交给 call_llm 自己解析
    if provider and provider != "auto":
        kwargs["provider"] = provider
    if model and model != "auto":
        kwargs["model"] = model
    return call_llm(**kwargs)


def parse_verdicts(content: str, expected_ids: Sequence[str]) -> Dict[str, Dict[str, str]]:
    """Parse LLM JSON into {tool_call_id: {verdict, reason}}."""
    text = (content or "").strip()
    if not text:
        return {}
    # strip markdown fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    data = None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        m = _JSON_OBJ_RE.search(text)
        if m:
            try:
                data = json.loads(m.group(0))
            except (json.JSONDecodeError, ValueError):
                data = None
    if not isinstance(data, dict):
        return {}
    raw = data.get("verdicts", data)
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Dict[str, str]] = {}
    for tid in expected_ids:
        entry = raw.get(tid) or raw.get(str(tid))
        if isinstance(entry, dict):
            v = str(entry.get("verdict") or "PASS").upper()
            if v not in {"PASS", "BLOCK", "HALT"}:
                v = "PASS"
            out[tid] = {"verdict": v, "reason": str(entry.get("reason") or "")}
        elif isinstance(entry, str):
            v = entry.upper()
            if v not in {"PASS", "BLOCK", "HALT"}:
                v = "PASS"
            out[tid] = {"verdict": v, "reason": ""}
    return out


def fail_closed_verdicts(
    tier1_calls: Sequence[ClassifiedCall],
    *,
    reason: str = "audit LLM unavailable",
) -> Dict[str, Dict[str, str]]:
    """危险 call → BLOCK；理论上本函数只收到 tier1。"""
    return {
        c.tool_call_id: {"verdict": "BLOCK", "reason": reason}
        for c in tier1_calls
    }


def audit_tier1_calls(
    *,
    agent: Any,
    messages: Sequence[Any],
    assistant_message: Any,
    tier1_calls: Sequence[ClassifiedCall],
    cfg: Dict[str, Any],
) -> Dict[str, Dict[str, str]]:
    """Run LLM audit; on failure return fail-closed BLOCKs for tier1."""
    if not tier1_calls:
        return {}

    # 压缩安全：首次审计时冻结 user 指令快照
    if agent is not None and not getattr(agent, "_semantic_audit_user_snapshot", None):
        try:
            snap = extract_user_instructions(messages, agent=agent)
            agent._semantic_audit_user_snapshot = list(snap)
        except Exception:
            pass

    user_instructions = extract_user_instructions(messages, agent=agent)
    assistant_text = extract_assistant_text(assistant_message)
    prior = extract_prior_tool_calls(messages)
    prompt = build_audit_prompt(
        user_instructions=user_instructions,
        assistant_text=assistant_text,
        tier1_calls=tier1_calls,
        prior_tools=prior,
    )
    expected = [c.tool_call_id for c in tier1_calls]
    timeout = float(cfg.get("timeout") or 5)

    try:
        response = _call_llm_sync(
            messages=prompt,
            timeout=timeout,
            provider=str(cfg.get("provider") or "auto"),
            model=str(cfg.get("model") or "auto"),
        )
        content = ""
        try:
            content = response.choices[0].message.content or ""
        except Exception:
            content = str(getattr(response, "content", "") or "")
        parsed = parse_verdicts(content, expected)
        if not parsed:
            logger.warning("semantic_audit: empty/unparseable LLM verdicts → fail-closed")
            return fail_closed_verdicts(tier1_calls, reason="audit LLM returned unparseable verdicts")
        # 缺 id 的危险 call fail-closed
        for tid in expected:
            if tid not in parsed:
                parsed[tid] = {
                    "verdict": "BLOCK",
                    "reason": "audit LLM omitted verdict (fail-closed)",
                }
        return parsed
    except Exception as exc:
        logger.warning("semantic_audit LLM failed: %s", exc)
        return fail_closed_verdicts(
            tier1_calls, reason=f"audit LLM error/timeout: {exc}"
        )
