"""Feishu interactive cards for skill_approval gate.

Self-contained card + callback system for skill_manage write approval on
sub-profile Feishu sessions.  Mirrors the established owner card pattern
(see ``owner/feishu/memory_approval.py``):

* Card construction and button-click handling live **here** in ``owner/``.
* The Feishu adapter dispatches ``hermes_action == "skill_approval_gate"``
  clicks to ``handle_card_click`` (4 lines of thin glue).
* Sending uses ``owner.feishu.card_sender.send_card_via_rest`` so no new
  method is added to the adapter.

Card layout:
  ┌─────────────────────────────────────────┐
  │ 🔍 技能审批: create 'xy-damodel'        │  header (orange)
  ├─────────────────────────────────────────┤
  │ 📋 改动概要                              │  markdown
  │   操作 / 技能名 / 文件 / 触发者          │
  ├─────────────────────────────────────────┤
  │ 🔍 初步评估                              │  markdown
  │   风险标记 / 工具列表 / 文件大小          │
  ├─────────────────────────────────────────┤
  │ 📝 审查 Prompt (复制后粘贴到AI对话)      │  markdown
  │ ┌─────────────────────────────────┐     │
  │ │ 请审查以下 Hermes 技能变更...    │     │  code block
  │ └─────────────────────────────────┘     │
  ├─────────────────────────────────────────┤
  │ [✅ 批准]  [⛔ 拒绝]                     │  buttons
  └─────────────────────────────────────────┘

Click flow:
  user clicks ✅ / ⛔ on the card
  └─ adapter._dispatch_card_action
     └─ hermes_action == "skill_approval_gate" branch
        └─ handle_card_click(adapter, ...)
           ├─ approve -> resolve_gateway_approval(session_key, "once")
           ├─ deny    -> resolve_gateway_approval(session_key, "deny")
           └─ CallBackCard inline-update (green/red, buttons removed)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Action key (lives in button value)
# ---------------------------------------------------------------------------

ACTION_KEY = "skill_approval_gate"
_APPROVE_VALUE = "approve"
_DENY_VALUE = "deny"

# Content truncation for card display
_CONTENT_PREVIEW_LIMIT = 2000
_SUMMARY_LIMIT = 600


# ---------------------------------------------------------------------------
# Card builders
# ---------------------------------------------------------------------------

def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "…[truncated]"


def _resolve_skill_path(args: Dict[str, Any]) -> str:
    """Best-effort resolve the on-disk skill path from skill_manage args."""
    name = str(args.get("name") or "").strip()
    if not name:
        return "(unknown)"
    file_path = args.get("file_path")
    if file_path:
        return str(file_path)
    category = args.get("category")
    # Match the skill directory layout used by skill_manage
    if category:
        return f"~/.hermes/skills/{category}/{name}/SKILL.md"
    return f"~/.hermes/skills/{name}/SKILL.md"


def _extract_content(args: Dict[str, Any]) -> str:
    """Extract skill content from args based on action type."""
    action = str(args.get("action") or "").strip()
    if action in ("create", "edit"):
        return str(args.get("content") or "")
    elif action == "patch":
        old = str(args.get("old_string") or "")
        new = str(args.get("new_string") or "")
        if old and new:
            return f"--- old ---\n{old}\n--- new ---\n{new}"
        return new or old
    elif action == "write_file":
        return str(args.get("file_content") or "")
    elif action == "remove_file":
        return f"(removing file: {args.get('file_path', '?')})"
    elif action == "delete":
        return "(deleting skill)"
    return ""


def _build_summary_section(
    *,
    action: str,
    name: str,
    args: Dict[str, Any],
    profile: str,
    origin_chat_id: str,
) -> str:
    """Build the 📋 改动概要 markdown section."""
    skill_path = _resolve_skill_path(args)
    category = args.get("category") or "(default)"
    lines = [
        "**📋 改动概要**",
        f"- **操作**: `{action}`",
        f"- **技能名**: `{name}`",
        f"- **类别**: `{category}`",
        f"- **文件路径**: `{skill_path}`",
        f"- **触发者**: `{profile}`",
    ]
    if origin_chat_id:
        lines.append(f"- **来源会话**: `{origin_chat_id}`")
    return "\n".join(lines)


def _build_assessment_section(
    *,
    action: str,
    name: str,
    args: Dict[str, Any],
) -> str:
    """Build the 🔍 初步评估 markdown section (template-based, no LLM)."""
    content = _extract_content(args)
    content_size = len(content) if content else 0

    # Detect risk patterns
    risk_flags = []
    dangerous_patterns = [
        ("rm -rf", "⚠️ 包含 `rm -rf` 模式"),
        ("sudo ", "⚠️ 包含 `sudo` 调用"),
        ("chmod 777", "⚠️ 包含 `chmod 777`"),
        ("> /dev/sd", "⚠️ 可能直接写磁盘设备"),
        ("mkfs", "⚠️ 包含格式化命令"),
        (":(){:|:&};:", "⚠️ 包含 fork bomb"),
        ("DROP TABLE", "⚠️ 包含 DROP TABLE"),
        ("DELETE FROM", "⚠️ 包含 DELETE FROM"),
        ("TRUNCATE", "⚠️ 包含 TRUNCATE"),
        ("eval(", "⚠️ 包含 eval() 调用"),
        ("exec(", "⚠️ 包含 exec() 调用"),
        ("os.system", "⚠️ 包含 os.system 调用"),
        ("subprocess.call", "⚠️ 包含 subprocess 调用"),
    ]
    content_lower = content.lower() if content else ""
    for pattern, flag in dangerous_patterns:
        if pattern.lower() in content_lower:
            risk_flags.append(flag)

    # Detect tool references
    tool_refs = []
    tool_patterns = [
        ("terminal", "terminal"),
        ("execute_code", "execute_code"),
        ("delegate_task", "delegate_task"),
        ("ssh", "ssh"),
        ("web_search", "web_search"),
        ("browser_", "browser"),
        ("kubectl", "kubectl"),
        ("docker", "docker"),
        ("systemctl", "systemctl"),
    ]
    for pattern, label in tool_patterns:
        if pattern in content_lower:
            tool_refs.append(label)

    lines = ["**🔍 初步评估**"]
    if risk_flags:
        lines.extend(risk_flags)
    else:
        lines.append("- ✅ 未检测到高风险模式")

    if tool_refs:
        lines.append(f"- **触及工具**: {', '.join(tool_refs)}")
    else:
        lines.append("- **触及工具**: (未检测到特定工具引用)")

    lines.append(f"- **内容大小**: {content_size} 字符")

    if action == "create":
        lines.append("- **类型**: 新建技能")
    elif action == "edit":
        lines.append("- **类型**: 编辑技能")
    elif action == "patch":
        lines.append("- **类型**: 补丁修改")
    elif action == "delete":
        lines.append("- **类型**: ⚠️ 删除技能")
    elif action == "write_file":
        lines.append("- **类型**: 写入文件")
    elif action == "remove_file":
        lines.append("- **类型**: ⚠️ 删除文件")

    return "\n".join(lines)


def _build_review_prompt(
    *,
    action: str,
    name: str,
    args: Dict[str, Any],
    profile: str,
    origin_chat_id: str,
) -> str:
    """Build a copy-pasteable review prompt for the user's AI chat."""
    skill_path = _resolve_skill_path(args)
    category = args.get("category") or "(default)"
    content = _extract_content(args)
    content_preview = _truncate(content, _CONTENT_PREVIEW_LIMIT)

    lines = [
        "请审查以下 Hermes 技能变更：",
        "",
        f"操作: {action}",
        f"技能名: {name}",
        f"文件路径: {skill_path}",
        f"类别: {category}",
        f"触发者: {profile}",
    ]
    if origin_chat_id:
        lines.append(f"来源会话: {origin_chat_id}")

    lines.extend([
        "",
        "--- SKILL.md 内容 ---",
        content_preview if content_preview else "(内容为空或不可用)",
        "",
        "--- 审查要点 ---",
        "1. 安全性: 是否有命令注入、路径遍历、凭据泄露风险",
        "2. 正确性: 工具调用参数是否正确，路径是否合理",
        "3. 规范性: YAML frontmatter 是否完整，markdown 格式是否标准",
        "4. 依赖: 是否引用了不存在的 skill 或工具",
    ])
    return "\n".join(lines)


def build_skill_approval_card(
    *,
    action: str,
    name: str,
    args: Dict[str, Any],
    profile: str,
    origin_chat_id: str = "",
    session_key: str = "",
    chat_id: str = "",
) -> Dict[str, Any]:
    """Build the interactive skill approval card JSON.

    Each button ``value`` carries ``session_key`` and ``chat_id`` so the
    click handler can resolve the approval via
    ``resolve_gateway_approval``.  The ``review_prompt`` is embedded in
    the button value so the resolved card can still display it.
    """
    summary_md = _build_summary_section(
        action=action, name=name, args=args,
        profile=profile, origin_chat_id=origin_chat_id,
    )
    assessment_md = _build_assessment_section(action=action, name=name, args=args)
    review_prompt = _build_review_prompt(
        action=action, name=name, args=args,
        profile=profile, origin_chat_id=origin_chat_id,
    )

    # The review prompt is shown in a collapsible code block so users can
    # easily copy it.  Feishu markdown doesn't support ``` copy buttons,
    # but a plain code block is the closest we get.
    review_md = (
        "**📝 审查 Prompt (复制后粘贴到 AI 对话)**\n\n"
        "```\n" + review_prompt + "\n```"
    )

    def _btn(label: str, choice: str, btn_type: str) -> Dict[str, Any]:
        return {
            "tag": "button",
            "text": {"tag": "plain_text", "content": label},
            "type": btn_type,
            "value": {
                "hermes_action": ACTION_KEY,
                "choice": choice,
                "session_key": session_key,
                "chat_id": chat_id,
                "action": action,
                "skill_name": name,
                "review_prompt": review_prompt,
            },
        }

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "content": f"🔍 技能审批: {action} '{name}'",
                "tag": "plain_text",
            },
            "template": "orange",
        },
        "elements": [
            {"tag": "markdown", "content": summary_md},
            {"tag": "hr"},
            {"tag": "markdown", "content": assessment_md},
            {"tag": "hr"},
            {"tag": "markdown", "content": review_md},
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    _btn("✅ 批准", _APPROVE_VALUE, "primary"),
                    _btn("⛔ 拒绝", _DENY_VALUE, "danger"),
                ],
            },
        ],
    }


def build_resolved_card(
    *,
    choice: str,
    action: str = "",
    skill_name: str = "",
    review_prompt: str = "",
) -> Dict[str, Any]:
    """Build the raw card data for CallBackCard inline-update after click.

    Switches header to green (approve) or red (deny), changes title,
    keeps the review prompt visible so the user can still read what was
    approved/denied.  Buttons are removed - the card is frozen.
    """
    if choice == _APPROVE_VALUE:
        icon, label, template = "✅", "已批准", "green"
    else:
        icon, label, template = "🟥", "已拒绝", "red"

    title = f"{icon} {label}"
    if action and skill_name:
        title = f"{icon} {label}: {action} '{skill_name}'"

    elements: list[dict] = []
    if review_prompt:
        elements.append({
            "tag": "markdown",
            "content": "**📝 审查 Prompt**\n\n```\n" + review_prompt + "\n```",
        })
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": title, "tag": "plain_text"},
            "template": template,
        },
        "elements": elements,
    }


# ---------------------------------------------------------------------------
# Card sending - send-side glue invoked by skill_manage_gate
# ---------------------------------------------------------------------------

async def send_skill_approval_card(
    adapter: Any,
    *,
    chat_id: str,
    action: str,
    name: str,
    args: Dict[str, Any],
    profile: str,
    origin_chat_id: str = "",
    session_key: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> Any:
    """Send a Feishu skill approval card via REST API.

    Returns the ``SendResult`` from the REST call.
    """
    try:
        from owner.feishu.card_sender import send_card_via_rest

        card = build_skill_approval_card(
            action=action,
            name=name,
            args=args,
            profile=profile,
            origin_chat_id=origin_chat_id,
            session_key=session_key,
            chat_id=chat_id,
        )
        # Annotate metadata for downstream click correlation.
        meta = dict(metadata) if metadata else {}
        meta["session_id"] = session_key
        meta["chat_id"] = chat_id
        result = await send_card_via_rest(adapter, chat_id, card, meta)
        if getattr(result, "success", False):
            logger.info(
                "[Feishu card] skill_approval sent OK action=%s name=%s chat_id=%s",
                action, name, chat_id,
            )
        else:
            logger.warning(
                "[Feishu card] skill_approval send failed action=%s name=%s error=%s",
                action, name, getattr(result, "error", None),
            )
        return result
    except Exception as exc:
        logger.warning(
            "[Feishu] skill_approval send_card failed (action=%s name=%s): %s",
            action, name, exc,
        )
        return None


# ---------------------------------------------------------------------------
# Click handling - invoked by the adapter dispatch branch
# ---------------------------------------------------------------------------

def handle_card_click(
    *,
    adapter: Any,
    event: Any,
    action_value: Dict[str, Any],
    loop: Any,
) -> Any:
    """Resolve a skill_approval button click and inline-update the card.

    Dispatches on ``choice`` in ``action_value``:

    * ``approve`` -> ``resolve_gateway_approval(session_key, "once")``
    * ``deny``    -> ``resolve_gateway_approval(session_key, "deny")``

    Then returns a ``P2CardActionTriggerResponse`` whose ``CallBackCard``
    updates the original card inline - switches header to green / red,
    removes the buttons, keeps the review prompt visible.
    """
    if not isinstance(action_value, dict):
        return None
    if action_value.get("hermes_action") != ACTION_KEY:
        return None

    choice = action_value.get("choice", "")
    session_key = str(action_value.get("session_key", "") or "")
    chat_id = str(action_value.get("chat_id", "") or "")
    action = str(action_value.get("action", "") or "")
    skill_name = str(action_value.get("skill_name", "") or "")
    review_prompt = str(action_value.get("review_prompt", "") or "")

    if choice not in {_APPROVE_VALUE, _DENY_VALUE} or not session_key:
        return _empty_response()

    # Resolve the gateway approval - this unblocks the waiting agent thread.
    try:
        from tools.approval import resolve_gateway_approval

        count = resolve_gateway_approval(session_key, choice)
        logger.info(
            "[Feishu card] skill_approval action session=%s choice=%s "
            "resolved=%d action=%s name=%s",
            session_key, choice, count, action, skill_name,
        )
    except Exception as exc:
        logger.error(
            "[Feishu] skill_approval resolve failed for session %s: %s",
            session_key, exc,
        )

    # Build the resolved card for inline update.
    try:
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            CallBackCard,
            P2CardActionTriggerResponse,
        )
    except ImportError:
        CallBackCard = None  # type: ignore[assignment]
        P2CardActionTriggerResponse = None  # type: ignore[assignment]

    if P2CardActionTriggerResponse is None:
        return None

    response = P2CardActionTriggerResponse()
    if CallBackCard is not None:
        card = CallBackCard()
        card.type = "raw"
        card.data = build_resolved_card(
            choice=choice, action=action,
            skill_name=skill_name, review_prompt=review_prompt,
        )
        response.card = card
    return response


def _empty_response() -> Any:
    try:
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            P2CardActionTriggerResponse,
        )
        return P2CardActionTriggerResponse()
    except ImportError:
        return None
