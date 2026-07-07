"""Feishu media upload size guard + SDK-crash user-visible fallback.

背景
----
飞书 ``im/v1/file/create`` 限制 30 MB，``im/v1/image/create`` 限制 10 MB
（来源：https://open.feishu.cn/document/server-docs/im-v1/file/create）。
当文件接近上限时，飞书服务端在某些路径下不返回错误码 234006，而是返回
**空响应体**（非 JSON），导致 lark SDK ``JSON.unmarshal("")`` 抛
``Expecting value: line 1 column 1 (char 0)``。

之前 ``_send_uploaded_file_message`` / ``send_image_file`` 的 ``except`` 只记
ERROR 日志，返回 ``SendResult(success=False, error=...)``；上层媒体投递链
（``_deliver_media_from_response`` / ``base._send_response_messages``）收到
失败结果后**再降一级**为 ``logger.warning`` —— 用户在飞书 DM 里看不到任何
提示：文件没发出来，也没有错误消息，纯粹的静默失败。

本模块做两件事
--------------
1. **调用 API 前做大小预检查**：超限时**不调** API，直接返回带中文提示的
   ``SendResult``，由上层投递链把提示发出去（参考 ``base.py`` 的
   ``⚠️ Couldn't deliver the ... attachment.`` 模式）。
2. **SDK 崩溃时提供用户可见的提示**：当 ``file.create`` / ``image.create``
   抛异常（``JSONDecodeError`` 等）时，``check_upload_exception`` 把异常翻译
   成对用户友好的中文 ``SendResult``，而不是 ``str(exc)`` 这种原始 traceback
   风格的 error。

注意：本模块**只产提示文本和 SendResult**，不直接向飞书发消息。提示的投递
交给调用方（adapter 的 ``_send_uploaded_file_message`` / ``send_image_file``
返回 ``SendResult``，由上层媒体投递链决定如何降级显示），与现有
``⚠️ Couldn't deliver the ...`` 降级路径保持一致。

所有逻辑放在 owner/；adapter 只做 1 行 ``_owner_import`` 薄胶水委托。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    # [owner] 目标分支飞书适配器已重构为插件（源码为单体 gateway/platforms/feishu.py）。
    from plugins.platforms.feishu.adapter import FeishuAdapter

logger = logging.getLogger(__name__)


# 飞书官方上传限制（字节）。来源：飞书开放平台 im/v1/file/create 与
# im/v1/image/create 文档。用字节比较，避免 MB/MB(1024^2)/MiB 的单位歧义。
FEISHU_FILE_MAX_BYTES = 30 * 1024 * 1024   # 30 MB — im/v1/file/create
FEISHU_IMAGE_MAX_BYTES = 10 * 1024 * 1024  # 10 MB — im/v1/image/create


def _format_size(num_bytes: int) -> str:
    """把字节数格式化成人类可读的中文大小（MB）。

    保留一位小数；不足 1 MB 时显示 ``<1 MB``，避免 ``0.0 MB`` 这种误导。
    """
    mb = num_bytes / (1024 * 1024)
    if mb < 1:
        return "<1 MB"
    return f"{mb:.1f} MB"


def _try_get_size(file_path: str) -> Optional[int]:
    """安全地读取文件大小。文件不存在/不可读时返回 None。"""
    try:
        return os.path.getsize(file_path)
    except OSError:
        return None


def check_file_size(file_path: str, *, display_name: Optional[str] = None) -> Optional["SendResult"]:  # type: ignore[name-defined]
    """预检查待上传文件的体积是否超过飞书 ``file.create`` 的 30 MB 上限。

    返回值语义
    ~~~~~~~~~~
    - ``None`` —— 文件大小在限制内（或无法读取大小），可以继续上传。
    - ``SendResult(success=False, ...)`` —— 超限，**不要**调用 API，直接把
      这个结果返回给上层投递链，让用户看到提示。

    ``display_name`` 用于在提示里展示文件名（调用方已经解析好的用户可见
    文件名），不传则回退到 ``os.path.basename(file_path)``。
    """
    size = _try_get_size(file_path)
    if size is None:
        # 文件不存在或无法读取：交给后续 ``open()`` 抛 ``FileNotFound`` 原路
        # 处理，不要在这里抢着返回错误（避免双重报错 / 误导）。
        return None
    if size <= FEISHU_FILE_MAX_BYTES:
        return None

    name = display_name or os.path.basename(file_path)
    text = (
        f"⚠️ 文件过大，飞书消息文件上限为 30 MB（当前 {_format_size(size)}），"
        f"已跳过上传：{name}"
    )
    logger.warning(
        "[Feishu] media_guard: file %s is %d bytes (> %d limit); skipping file.create",
        file_path, size, FEISHU_FILE_MAX_BYTES,
    )
    return _build_warn_result(text)


def check_image_size(image_path: str) -> Optional["SendResult"]:  # type: ignore[name-defined]
    """预检查待上传图片的体积是否超过飞书 ``image.create`` 的 10 MB 上限。

    语义同 :func:`check_file_size`：``None`` 表示放行，``SendResult`` 表示
    超限应跳过上传并提示用户。
    """
    size = _try_get_size(image_path)
    if size is None:
        return None
    if size <= FEISHU_IMAGE_MAX_BYTES:
        return None

    name = os.path.basename(image_path)
    text = (
        f"⚠️ 图片过大，飞书消息图片上限为 10 MB（当前 {_format_size(size)}），"
        f"已跳过上传：{name}"
    )
    logger.warning(
        "[Feishu] media_guard: image %s is %d bytes (> %d limit); skipping image.create",
        image_path, size, FEISHU_IMAGE_MAX_BYTES,
    )
    return _build_warn_result(text)


def check_upload_exception(exc: BaseException, *, file_path: str, display_name: Optional[str] = None) -> "SendResult":  # type: ignore[name-defined]
    """把上传 API 抛出的异常翻译成用户可见的中文 ``SendResult``。

    覆盖的核心场景：飞书服务端对接近/超过上限的文件返回**空响应体**，
    lark SDK ``JSON.unmarshal("")`` 抛
    ``json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)``。
    这个异常名对用户毫无意义；这里统一替换成「上传失败，可能超过限制」
    的中文提示。

    其他异常也兜底成友好提示（不再把 ``str(exc)`` 原样塞进 ``error``），
    但保留原始异常在日志里方便排查。
    """
    name = display_name or os.path.basename(file_path)
    is_decode_error = _is_empty_body_decode_error(exc)
    if is_decode_error:
        text = (
            f"⚠️ 文件上传失败，可能超过飞书 30 MB 上限或服务端返回异常：{name}"
        )
        logger.error(
            "[Feishu] media_guard: file.create raised %s for %s (likely empty "
            "response body / over-limit); surfacing user-visible hint",
            type(exc).__name__, file_path, exc_info=True,
        )
    else:
        text = f"⚠️ 文件上传失败：{name}"
        logger.error(
            "[Feishu] media_guard: file.create raised %s for %s: %s",
            type(exc).__name__, file_path, exc, exc_info=True,
        )
    return _build_warn_result(text, raw_exc=exc)


def check_image_upload_exception(exc: BaseException, *, image_path: str) -> "SendResult":  # type: ignore[name-defined]
    """图片上传异常的友好翻译。语义同 :func:`check_upload_exception`。"""
    name = os.path.basename(image_path)
    is_decode_error = _is_empty_body_decode_error(exc)
    if is_decode_error:
        text = (
            f"⚠️ 图片上传失败，可能超过飞书 10 MB 上限或服务端返回异常：{name}"
        )
    else:
        text = f"⚠️ 图片上传失败：{name}"
    logger.error(
        "[Feishu] media_guard: image.create raised %s for %s: %s",
        type(exc).__name__, image_path, exc, exc_info=True,
    )
    return _build_warn_result(text, raw_exc=exc)


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------

def _is_empty_body_decode_error(exc: BaseException) -> bool:
    """判断异常是否像「飞书返回空响应体导致 SDK JSON 解析失败」。

    命中两类：
    1. ``json.JSONDecodeError`` —— lark SDK 直接 ``json.loads("")``。
    2. ``ValueError`` 且消息含 ``Expecting value`` —— 某些 SDK 版本把它
       包成 ``ValueError``。
    """
    if isinstance(exc, ValueError):
        msg = str(exc)
        return "Expecting value" in msg or "No JSON object" in msg
    # json.JSONDecodeError 是 ValueError 的子类，上面已覆盖；保留显式判断
    # 以防未来 SDK 自定义异常不继承 ValueError。
    return type(exc).__name__ == "JSONDecodeError"


def _build_warn_result(text: str, *, raw_exc: Any = None) -> "SendResult":  # type: ignore[name-defined]
    """构造一个携带用户可见提示文本的失败 SendResult。

    延迟导入 ``SendResult``：owner/ 模块在 plugin 体系之外可能被静态分析
    工具 import，而 ``gateway.platforms.base`` 依赖较重，延迟到调用时再
    import 避免循环/启动期开销（与 ``auto_card.py`` 同样的处理）。
    """
    from gateway.platforms.base import SendResult

    # 把提示文本放在 error 字段：上层媒体投递链（base.py 的
    # ``send_document``/``send_image_file`` 默认 fallback、以及
    # ``_deliver_media_from_response`` 的 warning 路径）会消费 error。
    # 当上层决定把提示真正发给用户时（见 adapter 薄胶水），就从这里取。
    return SendResult(success=False, error=text, raw_response=raw_exc)
