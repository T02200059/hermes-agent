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

    # Medium#6: when streaming already delivered the body (already_sent=True),
    # the response has been shown to the user live. force=True below would skip
    # the streaming-disabled guard and re-fire the WHOLE body as a duplicate
    # card. Bail before that.
    if agent_result.get("already_sent"):
        return response, footer_line

    adapter = runner.adapters.get(Platform.FEISHU)
    if adapter is None:
        return response, footer_line

    # [owner] auto-card: 提前抽出并投递 MEDIA: 标签 / 裸本地路径。
    # 否则整段 response（含 ``MEDIA:<path>`` 字面文本）会被 try_auto_card 包进卡片
    # 当作纯文本发出，文件永远不会被上传；而下游 ``_process_message_background`` 在
    # already_sent=True 时又会跳过 ``extract_media``，三道防线全部 miss（详见
    # owner/docs/feishu-autocard-media-delivery.md）。
    #
    # 复用 gateway 的 ``_deliver_media_from_response``：它是权威的 response→附件管线
    # （MEDIA 标签 + 裸路径联合提取、图片/视频/语音/文档分流、安全过滤、
    # [[as_document]] / [[audio_as_voice]] 指令）。该方法内部会再 extract_media 一次，
    # 但标签已被剥光、第二次扫幂等无副作用。
    #
    # 顺序：先投附件，后发卡片。投递失败只 warning 不 raise —— 卡片照发，文本信息不丢。
    # 用 adapter.extract_media 取清理后的文本喂给卡片，避免 MEDIA: 标签泄漏到用户可见
    # 的卡片正文里。
    if hasattr(adapter, "extract_media"):
        try:
            from gateway.platforms.base import BasePlatformAdapter

            _media_files, _cleaned = adapter.extract_media(response)
            _media_files = BasePlatformAdapter.filter_media_delivery_paths(_media_files)
            # Medium#8: extract_media only strips ``MEDIA:`` tags; bare local
            # paths (auto-detected by extract_local_files in the gateway
            # delivery chain) are NOT stripped here, so a bare path would
            # leak into the card body as literal text AND be re-delivered as
            # an attachment. Mirror the gateway's chain order and detect bare
            # paths; when we end up shipping attachments we then strip BOTH
            # MEDIA tags and bare paths from the text fed to the card so
            # nothing appears twice.
            if hasattr(adapter, "extract_images"):
                _, _cleaned_no_img = adapter.extract_images(_cleaned)
            else:
                _cleaned_no_img = _cleaned
            _local_files: list = []
            _cleaned_no_paths = _cleaned_no_img
            if hasattr(adapter, "extract_local_files"):
                _local_files, _cleaned_no_paths = adapter.extract_local_files(_cleaned_no_img)
            has_attachments = bool(_media_files) or bool(_local_files)
            if has_attachments:
                # 把附件投递 + 联合管线（extract_images / extract_local_files）交给 gateway，
                # 我们只用剥光后的 _cleaned_no_paths 去包卡片。
                #
                # Medium#7: _deliver_media_from_response swallows per-item
                # delivery errors as warnings and returns None. If the cleaned
                # body is empty (a MEDIA-only / path-only response) and delivery
                # failed, setting already_sent=True here would seal the plain-
                # text safety net and leave the user with zero output. Track
                # whether delivery even started; if the cleaned body is empty we
                # don't claim success — fall through so the downstream plain-
                # text path can retry delivery and at minimum surface a message.
                deliv_started = True
                try:
                    await runner._deliver_media_from_response(response, event, adapter)
                except Exception as deliv_exc:
                    deliv_started = False
                    logger.warning(
                        "[Feishu] auto-card pre-deliver media raised: %s", deliv_exc
                    )
                # 附件已（尝试）投递；剥光 MEDIA 标签 + 裸路径后的文本喂给卡片，避免重复。
                response = _cleaned_no_paths
                # 边界：response 原本只有 MEDIA 标签 / 裸路径 → 清理后为空。
                if not response:
                    if deliv_started:
                        # 附件投递链至少跑通了；没有正文可包卡片，直接返回 already_sent
                        # 让下游 plain-text 跳过（否则 try_auto_card(force=True) 会发一张空卡片）。
                        agent_result["already_sent"] = True
                        return "", ""
                    # 投递链异常 + 空正文：不设 already_sent，把原始 response 交还下游兜底，
                    # 避免用户零输出。
                    return response, footer_line
        except Exception as exc:
            logger.debug("auto-card pre-deliver media failed: %s", exc)

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
