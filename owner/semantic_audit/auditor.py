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
_ARGS_CLIP = 400
_SIBLING_ARGS_CLIP = 300
_PRIOR_PREVIEW_CLIP = 120
_PRIOR_SKILL_CLIP = 2500  # skill_view 结果给审计看更长，贴近主 AI 读到的 SOP
_SKILL_CONTENT_CLIP = 3000
_MAX_SKILL_CONTEXTS = 3
_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)

# 读 skill 类工具：审计侧需要内容，避免把 SOP 步骤误判为越权
_SKILL_READ_TOOLS = frozenset({"skill_view"})


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

    users: List[str] = []
    for msg in messages or []:
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
        if role == "user":
            text = _msg_content(msg).strip()
            if text:
                users.append(_clip(text, _USER_CLIP))
    # 优先 turn 快照原文 append（再取尾部 max_items）
    if agent is not None:
        for attr in (
            "_semantic_audit_turn_user",
            "_persist_user_message_override",
            "_pending_cli_user_message",
        ):
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


def _json_args_clip(args: Any, limit: int = _ARGS_CLIP) -> str:
    try:
        args_s = json.dumps(args if args is not None else {}, ensure_ascii=False)
    except (TypeError, ValueError):
        args_s = str(args)
    if len(args_s) > limit:
        return args_s[: limit - 1] + "…"
    return args_s


def extract_prior_tool_calls(messages: Sequence[Any], *, limit: int = 12) -> List[Dict[str, Any]]:
    """已执行 tool 结果摘要（从 messages 尾部回看）。

    skill_view 结果用更长截断，便于审计对照 SOP。
    """
    prior: List[Dict[str, Any]] = []
    for msg in messages or []:
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
        if role != "tool":
            continue
        if isinstance(msg, dict):
            name = str(msg.get("name") or msg.get("tool_name") or "")
            tid = str(msg.get("tool_call_id") or "")
            raw = str(msg.get("content") or "")
        else:
            name = str(getattr(msg, "name", "") or "")
            tid = str(getattr(msg, "tool_call_id", "") or "")
            raw = str(getattr(msg, "content", "") or "")
        clip = _PRIOR_SKILL_CLIP if name in _SKILL_READ_TOOLS else _PRIOR_PREVIEW_CLIP
        prior.append(
            {
                "name": name,
                "tool_call_id": tid,
                "preview": _clip(raw, clip),
            }
        )
    return prior[-limit:]


def classified_to_sibling_payload(call: ClassifiedCall) -> Dict[str, Any]:
    """本批任意 tool_call 的轻量摘要（含 skip），供审计看完整计划。"""
    return {
        "tool_call_id": call.tool_call_id,
        "name": call.name,
        "original_name": call.original_name,
        "tier": call.tier,
        "args": _json_args_clip(call.args, _SIBLING_ARGS_CLIP),
        "detector_reason": call.reason,
    }


def _skill_key(name: str, file_path: Optional[str] = None) -> str:
    fp = (file_path or "").strip()
    return f"{name.strip()}::{fp}" if fp else name.strip()


def _load_skill_content(
    name: str,
    file_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """复用主 agent 同源 skill_view，让审计看到与主 AI 相同的 skill 正文。"""
    skill_name = (name or "").strip()
    if not skill_name:
        return None
    try:
        from tools.skills_tool import skill_view

        raw = skill_view(
            skill_name,
            file_path=file_path or None,
            preprocess=True,
        )
        data = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(data, dict) or not data.get("success"):
            return None
        content = str(data.get("content") or "")
        return {
            "skill": str(data.get("name") or skill_name),
            "file_path": (file_path or "SKILL.md"),
            "description": _clip(str(data.get("description") or ""), 200),
            "content": _clip(content, _SKILL_CONTENT_CLIP),
            "source": "skill_view",
        }
    except Exception as exc:
        logger.debug(
            "semantic_audit: skill_view load failed name=%s err=%s",
            skill_name,
            exc,
        )
        return None


def _skill_from_tool_result_content(content: str) -> Optional[Dict[str, Any]]:
    """从已执行的 skill_view JSON 结果里抽正文（无需再 IO）。"""
    text = (content or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("success"):
        return None
    skill = str(data.get("name") or "").strip()
    body = str(data.get("content") or "")
    if not skill and not body:
        return None
    return {
        "skill": skill or "(unknown)",
        "file_path": str(data.get("file") or data.get("file_path") or "SKILL.md"),
        "description": _clip(str(data.get("description") or ""), 200),
        "content": _clip(body, _SKILL_CONTENT_CLIP),
        "source": "prior_tool_result",
    }


def collect_skill_context(
    batch_calls: Sequence[ClassifiedCall],
    messages: Sequence[Any],
    *,
    max_skills: int = _MAX_SKILL_CONTEXTS,
) -> List[Dict[str, Any]]:
    """收集本批 / 近期 skill_view 对应的 skill 正文，供审计对照 SOP。

    优先级：
    1. 本批 skill_view（含尚未执行的 sibling）→ 直接 skill_view 重读
    2. messages 里已执行的 skill_view 结果 JSON
    """
    out: List[Dict[str, Any]] = []
    seen: set = set()

    def _add(entry: Optional[Dict[str, Any]]) -> bool:
        if not entry:
            return False
        key = _skill_key(str(entry.get("skill") or ""), str(entry.get("file_path") or ""))
        if not key or key in seen:
            return False
        seen.add(key)
        out.append(entry)
        return len(out) >= max_skills

    # 1) 本批 skill_view（同批未执行也能让审计看到 SOP）
    for c in batch_calls or []:
        if c.name not in _SKILL_READ_TOOLS:
            continue
        sname = str(c.args.get("name") or "").strip()
        if not sname:
            continue
        fp = c.args.get("file_path")
        fp_s = str(fp).strip() if fp else None
        if _add(_load_skill_content(sname, fp_s)):
            return out

    # 2) 历史 skill_view tool 结果
    for msg in messages or []:
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
        if role != "tool":
            continue
        if isinstance(msg, dict):
            name = str(msg.get("name") or msg.get("tool_name") or "")
            content = str(msg.get("content") or "")
        else:
            name = str(getattr(msg, "name", "") or "")
            content = str(getattr(msg, "content", "") or "")
        if name not in _SKILL_READ_TOOLS:
            continue
        if _add(_skill_from_tool_result_content(content)):
            return out

    return out


def build_audit_prompt(
    *,
    user_instructions: List[str],
    assistant_text: str,
    tier1_calls: Sequence[ClassifiedCall],
    prior_tools: Sequence[Dict[str, Any]],
    batch_siblings: Optional[Sequence[Dict[str, Any]]] = None,
    skill_context: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, str]]:
    calls_payload = []
    for c in tier1_calls:
        calls_payload.append(
            {
                "tool_call_id": c.tool_call_id,
                "name": c.name,
                "args": _json_args_clip(c.args, _ARGS_CLIP),
                "detector_reason": c.reason,
            }
        )

    system = (
        "You are a semantic audit gate for an AI agent. "
        "Decide whether each proposed tool call stays within the user's instructions. "
        "PASS = allowed; BLOCK = refuse this call but agent may continue; "
        "HALT = refuse and stop the whole turn (use for clear, aggressive overreach "
        "or irreversible destructive intent). "
        "Only emit verdicts for ids listed in proposed_tool_calls "
        "(batch_siblings are context only — do not invent extra verdict ids). "
        "batch_siblings shows the full concurrent tool-call plan in this assistant turn "
        "(including read-only skill_view / read_file / etc.). "
        "skill_context contains skill/SOP documents the main agent loaded or is loading "
        "via skill_view — treat them as procedure the agent may legitimately follow. "
        "If a proposed call matches steps described in skill_context and is consistent "
        "with user_instructions, prefer PASS over BLOCK. "
        "Still HALT clear irreversible destructive overreach even if a skill mentions it. "
        "Respond with ONLY a JSON object of the form:\n"
        '{"verdicts":{"<tool_call_id>":{"verdict":"PASS|BLOCK|HALT","reason":"..."}}}\n'
        "No prose outside JSON."
    )
    user: Dict[str, Any] = {
        "user_instructions": user_instructions,
        "assistant_text": assistant_text,
        "proposed_tool_calls": calls_payload,
        "batch_siblings": list(batch_siblings or []),
        "skill_context": list(skill_context or []),
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
    batch_calls: Optional[Sequence[ClassifiedCall]] = None,
) -> Dict[str, Dict[str, str]]:
    """Run LLM audit; on failure return fail-closed BLOCKs for tier1.

    ``batch_calls``：本批全部分类结果（含 skip），用于 batch_siblings + skill 加载。
    """
    if not tier1_calls:
        return {}

    batch = list(batch_calls) if batch_calls is not None else list(tier1_calls)

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
    siblings = [classified_to_sibling_payload(c) for c in batch]
    skills = collect_skill_context(batch, messages)
    prompt = build_audit_prompt(
        user_instructions=user_instructions,
        assistant_text=assistant_text,
        tier1_calls=tier1_calls,
        prior_tools=prior,
        batch_siblings=siblings,
        skill_context=skills,
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
