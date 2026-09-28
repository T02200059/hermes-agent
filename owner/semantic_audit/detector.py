"""Tier 0/1 检测：判断 batch 中哪些 tool_call 需要语义审计。

- Tier 0 Hardline（reboot / rm -rf / mkfs / dd / DROP…）→ 直接 HALT
- Tier 1 Pattern（dangerous command + 敏感路径写）→ 进 LLM 审计
- 其余（read_file / web_search / search_files…）→ 跳过

分类准入规则（T1-2，2026-09-28 修订）
    1. 只有「无论参数如何都无副作用」的工具才能进 ``_SAFE_TOOLS``；
    2. 带 action / 子命令 / 可变语义参数的工具一律走
       :func:`_classify_action_split_tool` 按 action 分流；
    3. 未枚举 action 取 fail-closed（tier1），不假设安全；
    4. 完全未分类的工具名同样取 fail-closed（tier1）——理由见
       ``classify_tool_call`` 兜底分支处的注释。

Tool Search 桥：审计前 unwrap 真实工具名；unwrap 失败按 tier1 处理。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# 明确安全、不需要审计的工具（只读 / 查询 / UI）
#
# ⚠️ 准入规则（T1-2，2026-09-28）：**只有「无论参数如何都无副作用」的工具
# 才能进本表**。任何带 action / 子命令 / 可变语义参数的工具必须走
# ``_classify_action_split_tool`` 按 action 分流——否则一个危险 action
# 会被整段当 safe tool 跳过，形成「门看起来生效、实际放过」的盲区。
# 已被移出的先例：``process``（上一轮）、``skill_manage`` / ``close_terminal``
# / ``memory``（本轮）。
_SAFE_TOOLS = frozenset(
    {
        "read_file",
        "search_files",
        "web_search",
        "web_extract",
        "session_search",
        "todo",  # 只写 agent 自身任务清单，无外部副作用；见 docs 决策记录
        "skills_list",
        "skill_view",
        "clarify",
        "vision_analyze",
        "tts",
        "stt",
        "image_gen",
        "browser_snapshot",
        "browser_get_content",
        "read_terminal",
        # process 不在此列：list/poll/log/wait 在 classify 中 early-skip，
        # kill/write/submit/close 等副作用 action 走 tier1。
        # skill_manage 不在此列：其 6 个 action（create/edit/patch/delete/
        #   write_file/remove_file）全是写操作，无只读 action。
        # close_terminal 不在此列：与已判 tier1 的 process action=close 是
        #   同一操作的两个工具名，必须同等对待。
        # memory 不在此列：add/replace/remove/batch 全部写持久记忆，
        #   是 prompt 注入的跨会话持久化面。
        "tool_search",
        "tool_describe",
    }
)

# ── action 分流表 ─────────────────────────────────────────────────
#
# skill_manage 的写 action 唯一真源是 owner/approval/skill_manage_gate。
# 这里复用而不复制，避免两处表漂移（skill_manager_tool 与 gate 的表是同一份）。
_FALLBACK_SKILL_WRITE_ACTIONS = frozenset(
    {"create", "edit", "patch", "delete", "write_file", "remove_file"}
)

# 不可逆写删 → 直接 hardline（无恢复路径，与 rm -rf 同类）
_SKILL_MANAGE_HARDLINE_ACTIONS = frozenset({"delete", "remove_file"})

# memory 的全部 action 都会写持久记忆；batch 内嵌 operations 亦然
_MEMORY_WRITE_ACTIONS = frozenset({"add", "replace", "remove", "batch"})

# Tool Search 桥的调用名（与 tools/tool_search.TOOL_CALL_NAME 一致；
# 用字面量副本以便桥模块不可导入时仍能识别）
_TOOL_CALL_BRIDGE_NAME = "tool_call"


def _skill_manage_write_actions() -> frozenset:
    """skill_manage 写 action 集合（唯一真源：owner/approval/skill_manage_gate）。"""
    try:
        from owner.approval.skill_manage_gate import WRITE_ACTIONS

        return frozenset(WRITE_ACTIONS)
    except Exception:
        # 该模块缺失时退化为内置表，宁可多审计不可漏审计
        return _FALLBACK_SKILL_WRITE_ACTIONS


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
    resolved, uargs, _err = unwrap_tool_call_ex(name, args)
    return resolved, uargs


def unwrap_tool_call_ex(
    name: str, args: Dict[str, Any]
) -> Tuple[str, Dict[str, Any], Optional[str]]:
    """同 :func:`unwrap_tool_call`，但显式回传失败原因。

    桥解析失败时必须让调用方看见（→ tier1），而不是静默保留 ``tool_call``
    这个工具名然后被当成未分类跳过——那正是「门看起来生效、实际放过」的
    典型形态（T2-2 / T3-5 同族）。
    """
    # 先用字面量判断，保证桥模块不可导入时也能识别出桥调用
    if name != _TOOL_CALL_BRIDGE_NAME:
        return name, args, None
    try:
        from tools.tool_search import TOOL_CALL_NAME, resolve_underlying_call

        assert TOOL_CALL_NAME == _TOOL_CALL_BRIDGE_NAME
        underlying, uargs, err = resolve_underlying_call(args)
        if err:
            return name, args, str(err)
        if not underlying:
            return name, args, "tool_call 未解析出底层工具名"
        return underlying, uargs if isinstance(uargs, dict) else {}, None
    except Exception as exc:  # 桥模块缺失或解析异常
        return name, args, f"Tool Search 桥不可用：{type(exc).__name__}: {exc}"


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


def _classify_action_split_tool(
    name: str,
    args: Dict[str, Any],
    tid: str,
    original_name: str,
    tc: Any,
) -> Optional["ClassifiedCall"]:
    """按 action 分流「白名单会整段跳过」的性质可变工具。

    返回 ``None`` 表示本函数不负责该工具名，交回主流程。

    存在的理由：这些工具名本身可变语义（同一工具名下既有只读 action 也有
    不可逆写删 action）。任何「白名单准入」都会把危险 action 一并跳过，
    使审计门看起来生效、实际放过。故一律按 action 分流，且 **未知 action
    取 fail-closed**（tier1），而不是回落到跳过。
    """

    def _mk(tier: str, reason: str) -> "ClassifiedCall":
        return ClassifiedCall(
            tool_call_id=tid,
            original_name=original_name,
            name=name,
            args=args,
            tier=tier,
            reason=reason,
            raw_tc=tc,
        )

    if name == "skill_manage":
        # 6 个 action 全是写；delete / remove_file 无恢复路径 → hardline
        action = str(args.get("action") or "").strip().lower()
        if action in _SKILL_MANAGE_HARDLINE_ACTIONS:
            return _mk("hardline", f"skill_manage {action}（不可逆写删）")
        if action in _skill_manage_write_actions():
            return _mk("tier1", f"skill_manage {action}")
        # 未枚举的 action：不假设它安全
        return _mk("tier1", f"skill_manage 未知 action: {action or '<空>'}")

    if name == "close_terminal":
        # 与已判 tier1 的 process action=close 是同一操作的两个工具名，
        # 实现同为 process_registry.request_close_terminal(pid)。
        return _mk("tier1", "close_terminal（等同 process close）")

    if name == "memory":
        action = str(args.get("action") or "").strip().lower()
        if action in _MEMORY_WRITE_ACTIONS:
            return _mk("tier1", f"memory {action}（写持久记忆）")
        # memory 目前没有只读 action；未枚举者不假设安全
        return _mk("tier1", f"memory 未知 action: {action or '<空>'}")

    return None


def classify_tool_call(tc: Any) -> ClassifiedCall:
    """Classify a single tool_call into skip / tier1 / hardline."""
    tid, original_name, raw_args = _tc_fields(tc)
    args = _parse_args(raw_args)
    name, args, unwrap_error = unwrap_tool_call_ex(original_name, args)

    # Tool Search 桥解析失败 → 底层工具未知，不能当「未分类」放过
    if unwrap_error:
        return ClassifiedCall(
            tool_call_id=tid,
            original_name=original_name,
            name=name,
            args=args,
            tier="tier1",
            reason=f"Tool Search 桥 unwrap 失败：{unwrap_error}",
            raw_tc=tc,
        )

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

    # 性质可变的工具（skill_manage / close_terminal / memory）按 action 分流。
    # 这些工具名绝不能进 _SAFE_TOOLS —— 那会把危险 action 一并跳过。
    _split = _classify_action_split_tool(name, args, tid, original_name, tc)
    if _split is not None:
        return _split

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

    # 已知的副作用工具：显式列出（reason 更可读）
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

    # 兜底（未分类工具）：tier1，fail-closed。
    #
    # 这里是本模块唯一一处方向性选择。历史上此处为 ``skip``（fail-open），
    # 注释却写着「fail-closed 倾向」——实现与注释相反，且后果不轻：
    # 上游 / MCP 新增的工具（computer_use / browser_exec / kanban_* 等）
    # 会全部静默跳过审计。审计门一旦开启，用户要的是防护而不是「看起来
    # 已防护」——后者比门不存在更危险，因为它剥夺了警觉。
    # 该方向的代价是审计量的增加，这是有意接受的取舍。
    return ClassifiedCall(
        tool_call_id=tid,
        original_name=original_name,
        name=name,
        args=args,
        tier="tier1",
        reason=f"unclassified tool（fail-closed）: {name}",
        raw_tc=tc,
    )


def classify_batch(tool_calls: Sequence[Any]) -> List[ClassifiedCall]:
    return [classify_tool_call(tc) for tc in tool_calls]


# ---------------------------------------------------------------------------
# 分类覆盖对账（启动期告警）
# ---------------------------------------------------------------------------

# 走 action 分流的工具名（不属 _SAFE_TOOLS / _SIDE_EFFECT_TOOLS，但已显式分类）
_ACTION_SPLIT_TOOL_NAMES = frozenset(
    {"process", "skill_manage", "close_terminal", "memory"}
)

# 兜底已改为 fail-closed tier1，所以「未分类」不再是漏检，但它意味着该工具
# 以「未知工具」身份进入 LLM 审计、语义上下文不足。本对账用于量化分类表
# 相对工具注册表的漂移：仓库注册 80+ 工具，两张显式表只覆盖其中一小部分，
# 上游 / MCP 每新增一个工具，这个差距只会增大。
_coverage_warned = False


def classified_tool_names() -> frozenset:
    """两张显式表 + action 分流表覆盖的全部工具名。"""
    return frozenset(_SAFE_TOOLS) | frozenset(_SIDE_EFFECT_TOOLS) | _ACTION_SPLIT_TOOL_NAMES


def unreconciled_tool_names() -> List[str]:
    """返回「已注册但未被任何分类表显式覆盖」的工具名（升序）。

    工具注册表不可用时返回空列表——对账是辅助信号，不能让审计门因此失败。
    """
    try:
        from tools.registry import registry

        names = registry.get_all_tool_names()
    except Exception:
        return []
    known = classified_tool_names()
    return sorted(n for n in names if n not in known)


def warn_unreconciled_tools() -> List[str]:
    """对账并告警（每进程一次）。返回未覆盖的工具名列表。

    调用点：审计门首次真正生效时（见 gate._maybe_audit_batch_impl）。
    仅在门开启时告警，避免关闭态刷日志。
    """
    global _coverage_warned
    unknown = unreconciled_tool_names()
    if unknown and not _coverage_warned:
        _coverage_warned = True
        logger.warning(
            "semantic_audit: %d 个已注册工具未被分类表显式覆盖，将按 fail-closed "
            "tier1 处理（语义上下文不足，建议补分类）：%s",
            len(unknown),
            ", ".join(unknown[:20]) + (" …" if len(unknown) > 20 else ""),
        )
    return unknown
