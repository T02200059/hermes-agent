"""Feishu interactive cards for write-approval gated memory writes.

Mirrors the established owner card pattern (see
``owner/feishu/model_picker.py`` / ``owner/feishu/clarify_card.py`` / 
``owner/feishu/resume_card.py``):

* Card construction and button-click handling live **here** in ``owner/``.
* The Feishu adapter (``plugins/platforms/feishu/adapter.py``) keeps only a
  few lines of thin-glue dispatch — matching the existing pattern used by
  ``_handle_model_picker_action`` / ``_handle_clarify_card_action`` /
  ``_handle_resume_card_action``.
* Sending uses ``owner.feishu.card_sender.send_card_via_rest`` so no new
  method is added to the adapter (zero upstream surface for the *send* path).

Trigger flow (writer → card)::

    memory tool handler (tools/memory_tool.py)
      └─ write_approval.evaluate_gate(MEMORY) ─→ stage=True
         └─ tools/write_approval.py: stage_write(MEMORY, payload)
         └─ memory tool returns JSON {"staged": True, "pending_id": "..."}
      └─ plugin post_tool_call hook sees staged result
         └─ plugin.send_approval_card(adapter, chat_id, pending_id, ...)
         └─ owner/feishu/card_sender.send_card_via_rest(...)

Click flow (user → card → command)::

    user clicks ✅ / 🟥 on the card
    └─ Feishu SDK on_card_action_trigger
       └─ adapter._dispatch_card_action (plugins/platforms/feishu/adapter.py)
      └─ hermes_action == "memory_approval_gate" branch (~4 lines added)
         └─ owner.feishu.memory_approval.handle_card_click(adapter, ...)
            ├─ approve → emit synthetic "/memory approve <pending_id>"
            │           via adapter._submit_on_loop(_handle_message_with_guards)
            ├─ deny    → emit synthetic "/memory reject <pending_id>"
            └─ CallBackCard with green/red template + frozen proposal md
               (matches owner-v17 build_resolved_memory_proposal_card shape)

The synthetic ``/memory approve <id>`` / ``/memory reject <id>`` commands are
already handled by ``gateway/slash_commands.py:_handle_memory_command`` so we
reuse the existing infrastructure rather than re-implementing the write.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Action key (lives in button value)
# ---------------------------------------------------------------------------

ACTION_KEY = "memory_approval_gate"
_APPROVE_VALUE = "approve"
_DENY_VALUE = "deny"

# Preview truncation. Memory entries are small (~200 chars by convention), but
# batch ops may have several; cap each preview line so the card stays small.
_CONTENT_PREVIEW_LIMIT = 600  # preview of the staged content / batch ops


# ---------------------------------------------------------------------------
# Session-id parsing — extract chat_id from gateway session keys
# ---------------------------------------------------------------------------

def extract_feishu_chat_id(session_id: str) -> str:
    """Best-effort parse a Feishu ``chat_id`` out of a gateway ``session_id``.

    Gateway session keys are colon-delimited (see
    ``gateway/session.py:build_session_key``)::

        agent:main:<platform>:dm:<chat_id>[:<thread_id>]
        agent:main:<platform>:<chat_type>:<chat_id>[:<thread_id>[:...]]

    For Feishu, ``platform`` segment == ``"feishu"``. We pull out ``chat_id``
    at segment index 4 — the DM ``dm`` chat_type sits at index 3 and chat_id
    follows, exactly the layout used by both group and DM shapes. Returns
    ``""`` when the format does not match (caller treats that as a no-op).

    Intentionally strict: returns ``""`` for unknown segment counts /
    non-feishu, so the post_tool_call hook degrades to a no-op rather than
    sending a card to the wrong chat.
    """
    if not session_id:
        return ""
    parts = session_id.split(":")
    if len(parts) < 5:
        return ""
    if parts[2] != "feishu":
        return ""
    return parts[4]


# ---------------------------------------------------------------------------
# Card builders
# ---------------------------------------------------------------------------

def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _format_proposal_md(*, summary: str, content_preview: str,
                       pending_id: str) -> str:
    """Build the markdown shown above the buttons.

    Mirrors owner-v17 ``_build_batch_proposal_md`` shape (target line +
    summary header + preview block) but adapted for the stock memory_tool
    payload shape (single add/replace/remove op or batch).
    """
    from agent.i18n import t as _t
    summary_line = (summary or "").strip() or _t("memory_proposal.summary_add", target="memory")
    preview = _truncate(content_preview, _CONTENT_PREVIEW_LIMIT)
    return (
        f"**{_t('memory_proposal.pending_id_label')}**: {pending_id}\n"
        f"**{_t('memory_proposal.card_summary_label')}**: {summary_line}\n\n"
        f"```\n{preview}\n```"
    )


def build_approval_card(
    *,
    pending_id: str,
    summary: str,
    content_preview: str,
    chat_id: str,
    session_id: str = "",
) -> Dict[str, Any]:
    """Build the interactive approval card JSON (purple, two buttons).

    Each button ``value`` carries the ``pending_id`` so the click handler can
    re-route the correct ``/memory approve <id>`` / ``/memory reject <id>``
    command without consulting an external state store. This matches
    owner-v17's ``memory_proposal`` card, which embeds ``proposal_md`` in the
    button value to preserve content across the click round-trip.
    """
    from agent.i18n import t as _t

    proposal_md = _format_proposal_md(
        summary=summary, content_preview=content_preview, pending_id=pending_id,
    )
    title = _t("memory_proposal.card_title")

    def _btn(label: str, choice: str, btn_type: str) -> Dict[str, Any]:
        return {
            "tag": "button",
            "text": {"tag": "plain_text", "content": label},
            "type": btn_type,
            "value": {
                "hermes_action": ACTION_KEY,
                "pending_id": pending_id,
                "choice": choice,
                "session_id": session_id,
                "chat_id": chat_id,
                "proposal_md": proposal_md,
            },
        }

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": title, "tag": "plain_text"},
            "template": "purple",
        },
        "elements": [
            {"tag": "markdown", "content": proposal_md},
            {
                "tag": "action",
                "actions": [
                    _btn(_t("memory_proposal.btn_approve"), _APPROVE_VALUE, "primary"),
                    _btn(_t("memory_proposal.btn_deny"), _DENY_VALUE, "danger"),
                ],
            },
        ],
    }


def build_resolved_card(*, choice: str, proposal_md: str = "") -> Dict[str, Any]:
    """Build the raw card data for ``CallBackCard`` inline-update after click.

    Mirrors owner-v17 ``build_resolved_memory_proposal_card``: change header
    colour (green/red), change title, keep the original ``proposal_md`` so the
    user can still read what was approved/denied. The buttons are removed —
    the card is frozen in its resolved state.
    """
    from agent.i18n import t as _t

    if choice == _APPROVE_VALUE:
        icon, label, template = "✅", _t("memory_proposal.approved"), "green"
    else:
        icon, label, template = "🟥", _t("memory_proposal.denied"), "red"

    elements: list[dict] = []
    if proposal_md:
        elements.append({"tag": "markdown", "content": proposal_md})
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": f"{icon} {label}", "tag": "plain_text"},
            "template": template,
        },
        "elements": elements,
    }


# ---------------------------------------------------------------------------
# Card sending — send-side glue invoked by the post_tool_call hook
# ---------------------------------------------------------------------------

async def send_approval_card(
    adapter: Any,
    *,
    chat_id: str,
    pending_id: str,
    summary: str,
    content_preview: str,
    session_id: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> Any:
    """Send a Feishu approval card for a staged memory write.

    Uses ``owner.feishu.card_sender.send_card_via_rest`` so we don't need a
    new method on the adapter — keep the upstream-side surface zero.

    Returns the ``SendResult`` from the REST call (best-effort; failures are
    logged and swallowed because the staged write is already on disk and can
    still be reviewed via ``/memory pending``).
    """
    try:
        from owner.feishu.card_sender import send_card_via_rest

        card = build_approval_card(
            pending_id=pending_id,
            summary=summary,
            content_preview=content_preview,
            chat_id=chat_id,
            session_id=session_id,
        )
        # Annotate metadata for downstream click correlation (matches
        # model_picker / clarify card patterns).
        meta = dict(metadata) if metadata else {}
        meta["session_id"] = session_id
        meta["chat_id"] = chat_id
        result = await send_card_via_rest(adapter, chat_id, card, meta)
        if getattr(result, "success", False):
            logger.info(
                "[Feishu card] memory_approval sent OK pending_id=%s chat_id=%s message_id=%s",
                pending_id,
                chat_id,
                getattr(result, "message_id", None) or "(none)",
            )
        else:
            logger.warning(
                "[Feishu card] memory_approval send failed pending_id=%s chat_id=%s error=%s",
                pending_id,
                chat_id,
                getattr(result, "error", None),
            )
        return result
    except Exception as exc:
        logger.warning(
            "[Feishu] memory_approval send_approval_card failed (pending=%s): %s",
            pending_id, exc,
        )
        return None


# ---------------------------------------------------------------------------
# Click handling — invoked by the adapter dispatch branch
# ---------------------------------------------------------------------------

def _build_source_from_event(event: Any, chat_id: str) -> Any:
    """Reconstruct a minimal ``SessionSource`` for the synthetic command.

    The original source that triggered the card was lost between the
    post_tool_call hook and now. The lark_oapi click event still carries
    ``context.open_chat_id`` and ``operator.open_id`` which is enough for
    the gateway to derive a session key and route the synthetic
    ``/memory approve|reject`` command to its own handler.

    Mirrors owner-v17 ``memory_proposal._session_key_from_action_value``'s
    fallback path which reads ``event.context.open_chat_id`` when the button
    value lacks a session_key.
    """
    try:
        from gateway.config import Platform
        from gateway.session import SessionSource
    except Exception as exc:
        logger.warning("[Feishu] memory_approval source deps missing: %s", exc)
        return None

    context = getattr(event, "context", None)
    event_chat_id = str(getattr(context, "open_chat_id", "") or "") if context else ""
    resolved_chat_id = event_chat_id or chat_id or ""
    if not resolved_chat_id:
        return None

    # Extract operator open_id so the synthetic command passes auth checks.
    operator = getattr(event, "operator", None)
    open_id = str(getattr(operator, "open_id", "") or "") if operator else ""

    return SessionSource(
        platform=Platform.FEISHU,
        chat_id=resolved_chat_id,
        chat_type="dm",  # default; /memory approve|reject is id-keyed so chat
                          # type doesn't gate the pending store action.
        user_id=open_id,
        user_id_alt="",
        thread_id="",
    )


def _route_command(adapter: Any, loop: Any, *, command: str, chat_id: str,
                   event: Any) -> None:
    """Submit a synthetic ``/memory approve <id>`` or ``/memory reject <id>``.

    Pattern lifted from ``owner/feishu/model_picker.py``'s
    ``_route_picker_command``: build a MessageEvent with
    ``message_type=COMMAND`` and feed it back through the adapter's
    ``_handle_message_with_guards`` via ``adapter._submit_on_loop``. The
    gateway ``_handle_memory_command`` (in ``gateway/slash_commands.py``)
    already understands ``/memory approve|reject <id>``, so we don't
    re-implement it.
    """
    try:
        from gateway.platforms.base import MessageEvent, MessageType
    except Exception as exc:
        logger.warning("[Feishu] memory_approval routing deps missing: %s", exc)
        return

    if not chat_id:
        return
    if loop is None or getattr(loop, "is_closed", lambda: False)():
        logger.warning("[Feishu] memory_approval routing skipped: loop unavailable")
        return

    source = _build_source_from_event(event, chat_id)
    if source is None:
        logger.warning(
            "[Feishu] memory_approval routing skipped: no source reconstructed "
            "for chat_id=%s", chat_id,
        )
        return

    async def _dispatch() -> None:
        try:
            synthetic_event = MessageEvent(
                text=command,
                message_type=MessageType.COMMAND,
                source=source,
                raw_message=None,
                message_id="",  # no reply_to — synthetic, not a real Feishu message
                timestamp=datetime.now(),
            )
            await adapter._handle_message_with_guards(synthetic_event)
        except Exception as exc:
            logger.warning(
                "[Feishu] memory_approval synthetic command '%s' route failed: %s",
                command, exc,
            )

    adapter._submit_on_loop(loop, _dispatch())


def handle_card_click(
    *,
    adapter: Any,
    event: Any,
    action_value: Dict[str, Any],
    loop: Any,
) -> Any:
    """Resolve an approval-card button click and inline-update the card.

    Dispatches on ``choice`` in ``action_value``:

    * ``approve`` → synthetic ``/memory approve <pending_id>``.
    * ``deny``    → synthetic ``/memory reject <pending_id>``.

    Then returns a ``P2CardActionTriggerResponse`` whose ``CallBackCard``
    updates the original card inline — switches header to green / red,
    changes the title, removes the buttons, keeps the proposal markdown
    visible (matches owner-v17 ``build_resolved_memory_proposal_card``).

    Returns ``None`` when the click was not for us / lark_oapi isn't importable.
    """
    if not isinstance(action_value, dict):
        return None
    if action_value.get("hermes_action") != ACTION_KEY:
        return None

    choice = action_value.get("choice", "")
    pending_id = str(action_value.get("pending_id", "") or "")
    chat_id = str(action_value.get("chat_id", "") or "")

    if choice not in {_APPROVE_VALUE, _DENY_VALUE} or not pending_id:
        return _empty_response()

    # Build & route the synthetic slash command for the chosen option.
    if choice == _APPROVE_VALUE:
        command = f"/memory approve {pending_id}"
    else:
        command = f"/memory reject {pending_id}"

    _route_command(adapter, loop, command=command, chat_id=chat_id, event=event)
    logger.info(
        "[Feishu card] memory_approval action pending_id=%s choice=%s chat_id=%s command=%s",
        pending_id,
        choice,
        chat_id,
        command,
    )

    # Resolve the original card inline (freeze + colour + title change).
    proposal_md = str(action_value.get("proposal_md", "") or "")
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
        card.data = build_resolved_card(choice=choice, proposal_md=proposal_md)
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


# ---------------------------------------------------------------------------
# Preview extraction — extracted here so tests can import without the plugin
# ---------------------------------------------------------------------------

def build_preview(args: Dict[str, Any]) -> tuple[str, str]:
    """Build a (summary, content_preview) tuple from memory tool args.

    Mirrors the summary/detail construction inside
    ``tools/memory_tool.py:_apply_write_gate`` so the card shows roughly what
    the inline CLI prompt would have shown. Falls back to ``("", "")`` on
    unknown action shapes so the caller can still decide to skip / show a
    generic card.
    """
    from agent.i18n import t as _t

    if not isinstance(args, dict):
        return ("", "")
    action = str(args.get("action", "") or "").strip()
    target = str(args.get("target", "") or "").strip()
    content = str(args.get("content", "") or "")
    old_text = str(args.get("old_text", "") or "")
    operations = args.get("operations") or []

    label = _t("memory_proposal.card_target").lower() if target == "user" else "memory"

    if action == "batch" and isinstance(operations, list) and operations:
        n = len(operations)
        op_lines: list[str] = []
        for op in operations[:6]:
            op = op or {}
            act = str(op.get("action", "?"))
            if act == "remove":
                ot = str(op.get("old_text", ""))[:60]
                op_lines.append(f"- remove: {ot}")
            elif act == "replace":
                ot = str(op.get("old_text", ""))[:40]
                nc = str(op.get("content", ""))[:60]
                op_lines.append(f"- replace: {ot} -> {nc}")
            else:
                c = str(op.get("content", ""))[:60]
                op_lines.append(f"- {act}: {c}")
        if len(operations) > 6:
            op_lines.append(f"... {len(operations) - 6} more")
        return (
            _t("memory_proposal.summary_batch", count=n, target=label),
            "\n".join(op_lines),
        )

    if action == "add":
        return (_t("memory_proposal.summary_add", target=label), content)
    if action == "replace":
        return (
            _t("memory_proposal.summary_replace", target=label),
            f"old:\n{old_text}\n---\nnew:\n{content}",
        )
    if action == "remove":
        return (_t("memory_proposal.summary_remove", target=label), old_text or "(empty)")
    if action:
        return (_t("memory_proposal.summary_action", action=action, target=label), content or old_text or "(empty)")
    return ("", "")