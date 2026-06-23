"""Feishu auto-card dispatch at agent:end.

Extracted from gateway/run.py per二次开发规范 P1:
  run.py 只做 import + 委托, 全部逻辑放在 owner/.

Returns (response, footer_line) — the possibly-cleared values.
When the card is sent, both are returned as "" so the downstream
plain-text path produces no visible duplicate.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from gateway.run import GatewayRunner
    from gateway.session import SessionSource

logger = logging.getLogger(__name__)


async def try_auto_card_on_end(
    runner: GatewayRunner,
    source: SessionSource,
    event: Any,
    agent_result: Dict[str, Any],
    response: str,
    footer_line: str,
) -> Tuple[str, str]:
    """Send the final feishu response as a card if applicable.

    Called after the agent:end hook but before the plain-text send.
    When the card succeeds, ``agent_result["already_sent"]`` is set
    and the returned strings are empty, suppressing the downstream
    plain-text path.

    Returns ``(response, footer_line)`` — assign back to the locals
    in the caller.
    """
    from gateway.config import Platform

    if source.platform != Platform.FEISHU or not response:
        return response, footer_line

    adapter = runner.adapters.get(Platform.FEISHU)
    if adapter is None:
        return response, footer_line

    try:
        from owner.feishu.auto_card import try_auto_card

        meta = runner._thread_metadata_for_source(
            source, runner._reply_anchor_for_event(event)
        )
        # [owner] auto-card: split footer from response so it can be rendered after hr divider
        body_text = response
        footer_text = ""
        if footer_line and response.endswith(footer_line):
            body_text = response[: -len(footer_line)].rstrip("\n")
            footer_text = footer_line

        result = await try_auto_card(
            adapter, body_text, meta,  # type: ignore[arg-type]  # runtime is FeishuAdapter
            chat_id=source.chat_id, force=True,
            footer=footer_text,
        )
    except Exception as exc:
        logger.debug("agent:end auto_card failed: %s", exc)
        return response, footer_line

    if result is not None:
        agent_result["already_sent"] = True
        return "", ""
    return response, footer_line
