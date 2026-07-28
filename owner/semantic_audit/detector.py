"""Tier 0/1 检测：判断 batch 中哪些 tool_call 需要语义审计。

- Tier 0 Hardline（reboot / rm -rf / mkfs / dd / DROP…）→ 直接 HALT
- Tier 1 Pattern（dangerous command + 敏感路径写）→ 进 LLM 审计
- 其余（read_file / web_search / search_files…）→ 跳过

Tool Search 桥：审计前 unwrap 真实工具名。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

# 明确安全、不需要审计的工具（只读 / 查询 / UI）
_SAFE_TOOLS = frozenset(
    {
        "read_file",
        "search_files",
        "web_search",
        "web_extract",
        "session_search",
        "todo",
        "memory",
        "skills_list",
        "skill_view",
        "skill_manage",
        "clarify",
        "vision_analyze",
        "tts",
        "stt",
        "image_gen",
        "browser_snapshot",
        "browser_get_content",
        "read_terminal",
        "close_terminal",
        # process 不在此列：list/poll/log/wait 在 classify 中 early-skip，
        # kill/write/submit/close 等副作用 action 走 tier1。
        "tool_search",
        "tool_describe",
    }
)

# process 只读 / 无副作用 action（与 tools/process_registry 对齐）
_PROCESS_READ_ACTIONS = frozenset({"list", "poll", "log", "wait", "status", ""})
# process 有副作用的 action（终止会话、stdin 注入、EOF）
_PROCESS_SIDE_EFFECT_ACTIONS = frozenset(
    {"kill", "write", "submit", "close", "signal"}
)

# 明确需要检查的副作用工具
_SIDE_EFFECT_TOOLS = frozenset(
    {
        "terminal",
        "write_file",
        "patch",
        "execute_code",
        "browser_navigate",
        "browser_click",
        "browser_type",
        "delegate_task",
        "cronjob",
        "send_message",
    }
)

# write_file / patch 敏感路径 → Tier 1（或 hardline 若匹配极危险）
_SENSITIVE_PATH_RES = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"(^|/)\.?ssh(/|$)",
        r"authorized_keys",
        r"(^|/)etc(/|$)",
        r"systemd",
        r"crontab",
        r"cron\.d",
        r"/boot(/|$)",
        r"sudoers",
        r"passwd$",
        r"shadow$",
        r"\.bashrc$",
        r"\.zshrc$",
        r"\.profile$",
    )
]

# 额外 hardline：SQL DROP / 裸机破坏（approval 未覆盖的语义层补充）
_EXTRA_HARDLINE_RES = [
    re.compile(p, re.IGNORECASE | re.DOTALL)
    for p in (
        r"\bDROP\s+(TABLE|DATABASE|SCHEMA)\b",
        r"\bTRUNCATE\s+TABLE\b",
        r"\bmkfs\b",
        r"\bdd\b[^\n]*\bof=/dev/",
    )
]


@dataclass
class ClassifiedCall:
    """单条 tool_call 的分类结果。"""

    tool_call_id: str
    original_name: str
    name: str  # unwrap 后
    args: Dict[str, Any]
    tier: str  # "skip" | "tier1" | "hardline"
    reason: str = ""
    raw_tc: Any = field(default=None, repr=False)


def _parse_args(raw: Any) -> Dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, ValueError, TypeError):
            return {"_raw": text}
    return {}


def _tc_fields(tc: Any) -> Tuple[str, str, Any]:
    """Extract (id, name, arguments) from OpenAI-style or dict tool_call."""
    if isinstance(tc, dict):
        tid = str(tc.get("id") or "")
        fn = tc.get("function") or {}
        if isinstance(fn, dict):
            return tid, str(fn.get("name") or ""), fn.get("arguments")
        return tid, "", None
    tid = str(getattr(tc, "id", "") or "")
    fn = getattr(tc, "function", None)
    name = str(getattr(fn, "name", "") or "") if fn is not None else ""
    arguments = getattr(fn, "arguments", None) if fn is not None else None
    return tid, name, arguments


def unwrap_tool_call(name: str, args: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Unwrap Tool Search bridge ``tool_call`` to underlying name+args."""
    try:
        from tools.tool_search import TOOL_CALL_NAME, resolve_underlying_call

        if name == TOOL_CALL_NAME:
            underlying, uargs, err = resolve_underlying_call(args)
            if not err and underlying:
                return underlying, uargs if isinstance(uargs, dict) else {}
    except Exception:
        pass
    return name, args


def _command_from_args(name: str, args: Dict[str, Any]) -> str:
    if name == "terminal":
        return str(args.get("command") or args.get("cmd") or "")
    if name == "execute_code":
        return str(args.get("code") or args.get("source") or "")
    if name == "process":
        # only side-effect actions (session_id is the real process tool key)
        action = str(args.get("action") or "").lower()
        if action in _PROCESS_SIDE_EFFECT_ACTIONS:
            sid = args.get("session_id") or args.get("pid") or ""
            return f"process {action} {sid} {args.get('data', '')}"
    return ""


def _path_from_args(name: str, args: Dict[str, Any]) -> str:
    if name in {"write_file", "patch", "read_file"}:
        return str(args.get("path") or args.get("file") or args.get("file_path") or "")
    return ""


def _is_sensitive_path(path: str) -> bool:
    if not path:
        return False
    for cre in _SENSITIVE_PATH_RES:
        if cre.search(path):
            return True
    return False


def _extra_hardline(text: str) -> Optional[str]:
    if not text:
        return None
    for cre in _EXTRA_HARDLINE_RES:
        if cre.search(text):
            return f"extra hardline: {cre.pattern}"
    return None


def classify_tool_call(tc: Any) -> ClassifiedCall:
    """Classify a single tool_call into skip / tier1 / hardline."""
    tid, original_name, raw_args = _tc_fields(tc)
    args = _parse_args(raw_args)
    name, args = unwrap_tool_call(original_name, args)

    # process：list/poll/log/wait 跳过；kill/write/submit/close 等进 tier1
    # （不得落入 _SAFE_TOOLS，否则副作用 action 会被当 safe tool 整段跳过）
    if name == "process":
        action = str(args.get("action") or "list").lower()
        if action in _PROCESS_READ_ACTIONS:
            return ClassifiedCall(
                tool_call_id=tid,
                original_name=original_name,
                name=name,
                args=args,
                tier="skip",
                reason="process read-only action",
                raw_tc=tc,
            )
        return ClassifiedCall(
            tool_call_id=tid,
            original_name=original_name,
            name=name,
            args=args,
            tier="tier1",
            reason=f"process {action}",
            raw_tc=tc,
        )

    cmd = _command_from_args(name, args)
    path = _path_from_args(name, args)

    # ── Tier 0 Hardline ──────────────────────────────────────────────
    if name == "terminal" and cmd:
        try:
            from tools.approval import detect_hardline_command

            is_hl, desc = detect_hardline_command(cmd)
            if is_hl:
                return ClassifiedCall(
                    tool_call_id=tid,
                    original_name=original_name,
                    name=name,
                    args=args,
                    tier="hardline",
                    reason=desc or "hardline command",
                    raw_tc=tc,
                )
        except Exception:
            pass

    extra = _extra_hardline(cmd) or _extra_hardline(
        f"{name} {json.dumps(args, ensure_ascii=False)[:500]}"
    )
    if extra and name in _SIDE_EFFECT_TOOLS | {"terminal", "execute_code"}:
        return ClassifiedCall(
            tool_call_id=tid,
            original_name=original_name,
            name=name,
            args=args,
            tier="hardline",
            reason=extra,
            raw_tc=tc,
        )

    # ── Tier 1 ───────────────────────────────────────────────────────
    if name == "terminal" and cmd:
        try:
            from tools.approval import detect_dangerous_command

            is_dang, _key, desc = detect_dangerous_command(cmd)
            if is_dang:
                return ClassifiedCall(
                    tool_call_id=tid,
                    original_name=original_name,
                    name=name,
                    args=args,
                    tier="tier1",
                    reason=desc or "dangerous command",
                    raw_tc=tc,
                )
        except Exception:
            # 检测失败时对 terminal 保守进审计
            return ClassifiedCall(
                tool_call_id=tid,
                original_name=original_name,
                name=name,
                args=args,
                tier="tier1",
                reason="terminal (detector unavailable)",
                raw_tc=tc,
            )
        # 未匹配 dangerous 的 terminal 默认 skip（避免对 ls/cat 等廉价调用）
        return ClassifiedCall(
            tool_call_id=tid,
            original_name=original_name,
            name=name,
            args=args,
            tier="skip",
            reason="terminal not dangerous",
            raw_tc=tc,
        )

    if name in {"write_file", "patch"} and _is_sensitive_path(path):
        return ClassifiedCall(
            tool_call_id=tid,
            original_name=original_name,
            name=name,
            args=args,
            tier="tier1",
            reason=f"sensitive path write: {path}",
            raw_tc=tc,
        )

    if name == "execute_code" and cmd:
        # 代码执行默认进审计（模型可能内嵌 shell）
        if _extra_hardline(cmd):
            return ClassifiedCall(
                tool_call_id=tid,
                original_name=original_name,
                name=name,
                args=args,
                tier="hardline",
                reason=_extra_hardline(cmd) or "execute_code hardline",
                raw_tc=tc,
            )
        return ClassifiedCall(
            tool_call_id=tid,
            original_name=original_name,
            name=name,
            args=args,
            tier="tier1",
            reason="execute_code",
            raw_tc=tc,
        )

    if name in _SAFE_TOOLS:
        return ClassifiedCall(
            tool_call_id=tid,
            original_name=original_name,
            name=name,
            args=args,
            tier="skip",
            reason="safe tool",
            raw_tc=tc,
        )

    # 未知副作用工具：进 tier1（fail-closed 倾向）
    if name in _SIDE_EFFECT_TOOLS:
        return ClassifiedCall(
            tool_call_id=tid,
            original_name=original_name,
            name=name,
            args=args,
            tier="tier1",
            reason=f"side-effect tool: {name}",
            raw_tc=tc,
        )

    return ClassifiedCall(
        tool_call_id=tid,
        original_name=original_name,
        name=name,
        args=args,
        tier="skip",
        reason="unclassified skip",
        raw_tc=tc,
    )


def classify_batch(tool_calls: Sequence[Any]) -> List[ClassifiedCall]:
    return [classify_tool_call(tc) for tc in tool_calls]
