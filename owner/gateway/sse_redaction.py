"""SSE 出站脱敏：工具参数 / 工具结果的秘密遮蔽与帧归属绑定。

原位于 `gateway/platforms/api_server.py`（约 213 行内联函数）。这些函数在**上游
完全不存在**（`git show upstream/main:gateway/platforms/api_server.py` 里
`_clip*` / `_redact*` 一个都没有），是纯 owner 新增 —— 按 §2.1「最小侵入源码」，
它们本就不该占着官方文件的 213 行，每次上游在同一文件动手都要为这块解冲。

## 为什么需要两层防护

`hermes.tool.progress` / Responses 通道会把工具参数与结果送上 wire。这些是进程内
最宽的自由文本通道 —— 命令行、文件内容、命令输出都在里面。只靠"SSE 只发给请求方"
不够：`api_server` 支撑按会话扇出的第三方消费方，一个会话里的秘密会随进度事件
流到别人那里。所以：

1. **隔离**：每个 tool 生命周期帧绑定发起请求的 token（`bind_tool_frame`），
   别人的帧降级为 name+status（`stripped_tool_frame`），绝不携带参数与输出。
2. **脱敏**：在边界处遮蔽可识别的凭据（`redact_for_sse`），复用 `agent.redact`
   的模式集而非另造一套。

两层都要，因为泄漏面有两个：错误的接收方，和正确的接收方但载荷含密。

## 三个容易写错的地方

- **脱敏必须在截断之前**（`clip_jsonable_value` / `clip_tool_output_for_sse`）。
  先截断会在切口留下凭据残片（`…ghp_abc`），而截断后的残片太短、模式集认不出来，
  dict 级兜底也救不回。整体秘密两处都丢，差别只在残片。
- **失败必须 fail-closed**：`agent.redact` 加载不到时返回占位符而不是原文。
  这是出站边界，"无法验证"不得静默退化成"原样发出"。
- **常量由调用方传入**（`max_chars` / `value_max` / `primary_keys` 等）。
  wire budget 是上游定义的，若在这里写死副本，上游调整预算时本模块会静默不同步；
  传参让官方文件始终是唯一真源。

## 可移除性

删除本文件后，官方文件的薄委托会 ImportError。调用点均已在 `try` 之外，因此
表现为该端点报错，而不是静默发原文 —— 宁可不可用，不可泄漏。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# 脱敏器不可用时的占位符。出现在 wire 上说明这条帧的秘密状态未知，
# 消费方应视为"无内容"而不是"内容为空"。
SSE_REDACT_PLACEHOLDER = "«redaction unavailable»"

# 只在首次失败时记一次 error：出站路径每帧都调，逐帧刷屏会淹没根因。
_redaction_failed = False


def reset_redaction_state() -> None:
    """测试用：复位"已报告过失败"标志（生产路径不需要）。"""
    global _redaction_failed
    _redaction_failed = False


def redact_for_sse(text: str) -> str:
    """遮蔽 SSE 自由文本中的可识别秘密。

    复用日志脱敏器并强制 ``force=True`` —— ``agent.redact`` 把一个显式 flag
    定义为"无论用户全局 `security.redact_secrets` 偏好如何都不得返回原文"的边界，
    出站 stream 正属于这种边界。

    脱敏器加载失败时返回占位符而非输入。
    """
    global _redaction_failed
    try:
        from agent.redact import redact_sensitive_text

        return redact_sensitive_text(text, force=True)
    except Exception as exc:  # noqa: BLE001 - 边界 fail-closed，不静默放行
        if not _redaction_failed:
            _redaction_failed = True
            logger.error(
                "[API] SSE secret redaction unavailable (%s); suppressing "
                "tool args/results on hermes.tool.progress",
                exc,
            )
        return SSE_REDACT_PLACEHOLDER


def redact_args_for_sse(args: dict) -> dict:
    """递归遮蔽工具参数字典里的字符串叶子。

    ``clip_jsonable_value`` 走的是"JSON 编码后整体脱敏"，Responses 通道则是手工
    拼 payload —— 这条路径没有那个保护。递归穿透 dict/list/tuple，确保嵌一层的
    凭据不会原样带走。
    """
    out: Dict[str, Any] = {}
    for key, value in args.items():
        out[key] = redact_nested_for_sse(value)
    return out


def redact_nested_for_sse(value: Any) -> Any:
    """遮蔽 JSON 形态值里任意深度的字符串。"""
    if isinstance(value, str):
        return redact_for_sse(value)
    if isinstance(value, bytes):
        return redact_for_sse(value.decode("utf-8", "replace"))
    if isinstance(value, dict):
        return redact_args_for_sse(value)
    if isinstance(value, (list, tuple)):
        return type(value)(redact_nested_for_sse(item) for item in value)
    return value


def redact_result_for_sse(result: Any) -> Any:
    """为 Responses 通道遮蔽原始工具结果。

    与 :func:`clip_tool_output_for_sse` 不同，这里**保持载荷形状** —— 该通道把
    item 当 JSON 回显、自有长度预算，所以只遮蔽字符串叶子。
    """
    return redact_nested_for_sse(result)


def bind_tool_frame(tag: str, payload: dict, frame_token: str) -> tuple:
    """把发起请求标记盖到 tool 生命周期帧上。

    token 放在 ``queue`` 元组里，**不进 ``payload``**：payload 会直接序列化上 wire，
    而隔离断言是内部契约，消费方既不需要也不应该去解析它。
    """
    return (tag, frame_token, payload)


def tool_frame_is_ours(item: Any, frame_token: str) -> bool:
    """这一帧是否属于*本*流的请求？

    未绑定（2 元组，早于绑定机制的写入方产生）或绑定了别的 token 都不算。
    调用方必须把这类帧**降级为 name+status 而不是丢弃** —— 丢弃会让用户看不到
    工具在执行；降级则保证泄漏的帧仍然带不走参数与输出。
    """
    return (
        isinstance(item, tuple)
        and len(item) == 3
        and bool(frame_token)
        and item[1] == frame_token
    )


def stripped_tool_frame(payload: Any) -> dict:
    """name+status 形式 —— 未绑定帧降级后的样子。"""
    if not isinstance(payload, dict):
        return {}
    return {
        k: v
        for k, v in payload.items()
        if k in ("tool", "name", "toolCallId", "tool_call_id", "status")
    }


def clip_jsonable_value(value: Any, max_chars: int) -> Any:
    """把工具参数压成 JSON 安全的标量/对象，截断并脱敏。

    **脱敏先于截断**，理由见模块 docstring。
    """
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        value = redact_for_sse(value)
        return value if len(value) <= max_chars else value[: max_chars - 1] + "…"
    if isinstance(value, bytes):
        text = redact_for_sse(value.decode("utf-8", "replace"))
        return text if len(text) <= max_chars else text[: max_chars - 1] + "…"
    try:
        encoded = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        encoded = str(value)
    encoded = redact_for_sse(encoded)
    if len(encoded) <= max_chars:
        try:
            return json.loads(encoded)
        except Exception:
            return encoded
    return encoded[: max_chars - 1] + "…"


def clip_tool_args_for_sse(
    args: Any,
    *,
    max_chars: int,
    value_max: int,
    primary_keys: Sequence[str],
) -> dict:
    """给 ``hermes.tool.progress`` 的可脱敏参数；保证 JSON 可序列化。

    脱敏在 :func:`clip_jsonable_value` 内按值做一遍，这里再做一遍 dict 级兜底，
    确保没有代码路径能把原始字符串交给 wire。

    ``max_chars`` / ``value_max`` / ``primary_keys`` 由调用方传入：wire budget
    是上游定义的真源，本模块不持有副本（见模块 docstring）。
    """
    if not isinstance(args, dict):
        return {}
    out: Dict[str, Any] = {}
    for key, value in args.items():
        if not isinstance(key, str):
            continue
        out[key[:64]] = clip_jsonable_value(value, value_max)
        if len(out) >= 24:
            break
    try:
        encoded = json.dumps(out, ensure_ascii=False, default=str)
    except Exception:
        encoded = ""
    if len(encoded) <= max_chars:
        return redact_args_for_sse(out)
    # 精简兜底必须遵守**同一份** wire 预算（T3-11）。旧实现把每个主键裁到 4000
    # 且不设总量上限，11 个键编码成约 44 KB —— 是声明预算的 7 倍。改为按优先级
    # 逐个加入、每个裁到"剩余预算 - 64"（留给键名与 JSON 标点），满了就停，
    # 结果可证不超过 max_chars。
    slim: Dict[str, Any] = {}
    for key in primary_keys:
        if key not in args:
            continue
        used = len(json.dumps(slim, ensure_ascii=False, default=str))
        remaining = max_chars - used
        if remaining <= 64:
            break
        slim[key] = clip_jsonable_value(args[key], remaining - 64)
    return redact_args_for_sse(slim)


def clip_tool_output_for_sse(result: Any, *, output_max: int) -> str:
    """completed 进度事件的工具结果预览：短、JSON 安全、已脱敏。

    这个 helper 曾经是**纯截断** —— 命令输出、``stdout``、文件正文原样上 wire。
    现在脱敏先于长度裁剪，理由同参数侧：被裁过的秘密仍是秘密。
    """
    if result is None:
        return ""
    if isinstance(result, bytes):
        result = result.decode("utf-8", "replace")
    if isinstance(result, str):
        text = result
    elif isinstance(result, dict):
        text = ""
        for key in ("output", "content", "stdout", "text", "result"):
            val = result.get(key)
            if isinstance(val, str) and val.strip():
                text = val
                break
        if not text:
            try:
                text = json.dumps(result, ensure_ascii=False, default=str)
            except Exception:
                text = str(result)
    else:
        text = str(result)
    text = redact_for_sse(text.replace("\x00", ""))
    if len(text) > output_max:
        return text[: output_max - 1] + "…"
    return text
