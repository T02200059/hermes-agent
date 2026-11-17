"""Owner display-layer translations for user-visible diagnostic notices.

Official producers keep English literals (some shapes are also noisy-filter /
provider-error match keys). Translate only when rendering to a messaging
surface or a Chinese activity stamp. English UI, unknown strings, and
exceptions fail open to the original text.

Commands such as ``/stop``, ``/retry``, and ``/model`` stay verbatim.
Numeric and name parameters are preserved.
"""

from __future__ import annotations

import re
from typing import Callable, Match, Optional, Pattern, Sequence

from agent.i18n import DEFAULT_LANGUAGE, get_language

_Fmt = Callable[[Match[str]], str]
_Template = tuple[Pattern[str], _Fmt]

# Stop-hint tails from agent.turn_recovery_autorecover._STOP_HINTS / _DEFAULT_STOP_HINT.
_STOP_HINT_ZH: dict[str, str] = {
    "send /stop to cancel": "发送 /stop 可取消",
    "press Esc to stop": "按 Esc 可停止",
    "cancel the request to stop": "取消请求即可停止",
}


def _hint_zh(hint: str) -> str:
    return _STOP_HINT_ZH.get(hint, hint)


def _lang_is_chinese(force_chinese: Optional[bool]) -> bool:
    if force_chinese is not None:
        return bool(force_chinese)
    try:
        return str(get_language() or "").strip().lower().startswith("zh")
    except Exception:
        return False


def _templates() -> Sequence[_Template]:
    return (
        (
            # Durable auto-recovery ladder (feishu / messaging status bubble).
            re.compile(
                r"^⏳ Provider temporarily unavailable — "
                r"retrying automatically in (\d+)s \(cycle (\d+)/(\d+)\)"
                r"(?:; (.+))?$"
            ),
            lambda m: (
                f"⏳ 供应商暂时不可用 — 将在 {m.group(1)} 秒后自动重试"
                f"（第 {m.group(2)}/{m.group(3)} 轮）"
                + (f"；{_hint_zh(m.group(4))}" if m.group(4) else "")
            ),
        ),
        (
            re.compile(
                r"^⏳ Automatic recovery gave up after (\d+) cycles — "
                r"the provider is still unavailable\.$"
            ),
            lambda m: f"⏳ 自动恢复已在 {m.group(1)} 轮后放弃 — 供应商仍不可用。",
        ),
        (
            re.compile(
                r"^❌ The model provider didn't answer after all retries\. "
                r"Send /retry, or switch models with /model\.$"
            ),
            lambda m: (
                "❌ 所有重试后供应商仍未返回结果。"
                "请发送 /retry，或用 /model 切换模型。"
            ),
        ),
        (
            re.compile(
                r"^❌ Model returned no content after all retries and fallback attempts\.$"
            ),
            lambda m: "❌ 所有重试和回退尝试后，模型仍未返回内容。",
        ),
        (
            re.compile(
                r"^❌ Model returned no content after all retries\. "
                r"No fallback providers configured\.$"
            ),
            lambda m: "❌ 所有重试后模型仍未返回内容。未配置回退供应商。",
        ),
        (
            re.compile(
                r"^⚠️ Model produced reasoning but no visible response after all retries\. "
                r"Returning empty\.$"
            ),
            lambda m: "⚠️ 所有重试后，模型只产生了推理、没有可见回复。将返回空内容。",
        ),
        (
            re.compile(
                r"^↻ Stream interrupted — using delivered content as final response$"
            ),
            lambda m: "↻ 流被中断 — 将已送达的内容作为最终回复",
        ),
        (
            re.compile(
                r"^↻ Empty response after tool calls — using earlier content as final answer$"
            ),
            lambda m: "↻ 工具调用后得到空回复 — 将沿用先前内容作为最终答案",
        ),
        (
            re.compile(
                r"^↻ Model signaled a tool call but sent none — re-prompting \((\d+)/3\)$"
            ),
            lambda m: f"↻ 模型发出了工具调用信号但未附带调用 — 正在重新提示（{m.group(1)}/3）",
        ),
        (
            re.compile(
                r"^⚠️ Iteration budget exhausted \((\d+)/(\d+)\) — asking model to summarise$"
            ),
            lambda m: f"⚠️ 迭代预算已用尽（{m.group(1)}/{m.group(2)}）— 正在请模型做总结",
        ),
        (
            re.compile(
                r"^❌ Ollama runtime context is too small for Hermes tool use$"
            ),
            lambda m: "❌ Ollama 运行时上下文过小，无法供 Hermes 使用工具",
        ),
        (
            re.compile(
                r"^✅ Primary model restored: (.+) via (.+); "
                r"fallback (.+) via (.+) is no longer active\.$"
            ),
            lambda m: (
                f"✅ 主模型已恢复：{m.group(1)}（{m.group(2)}）；"
                f"回退模型 {m.group(3)}（{m.group(4)}）已停用。"
            ),
        ),
        (
            re.compile(
                r"^⚠️ The model declined to respond to this request \(safety refusal\)\.$"
            ),
            lambda m: "⚠️ 模型拒绝回应此请求（安全拒答）。",
        ),
        (
            re.compile(r"^⚠️ Tool guardrail halted (.+): (.+)$"),
            lambda m: f"⚠️ 工具护栏已中止 {m.group(1)}：{m.group(2)}",
        ),
        (
            re.compile(
                r"^❌ Billing or credits exhausted — (.+)$"
            ),
            lambda m: f"❌ 额度或账单已耗尽 — {m.group(1)}",
        ),
        (
            re.compile(
                r"^❌ Provider reported usage/credit exhaustion "
                r"\(unverified — may be a content-filter rejection\) — (.+)$"
            ),
            lambda m: (
                "❌ 供应商报告额度耗尽（未经核实 — 也可能是内容过滤拒绝）"
                f" — {m.group(1)}"
            ),
        ),
        # Live wait-line variants (activity / thinking), not always a status bubble.
        (
            re.compile(
                r"^⚠ no output from provider for (\d+)s — reconnecting\.\.\.$"
            ),
            lambda m: f"⚠ 供应商已 {m.group(1)} 秒无输出 — 正在重连…",
        ),
        (
            re.compile(
                r"^⚠ no response from provider in (\d+)s — reconnecting\.\.\.$"
            ),
            lambda m: f"⚠ 已等待供应商 {m.group(1)} 秒无响应 — 正在重连…",
        ),
        (
            re.compile(
                r"^↻ model stuck on internal reasoning — switching to fallback provider$"
            ),
            lambda m: "↻ 模型卡在内部推理 — 正在切换到回退供应商",
        ),
        (
            re.compile(
                r"^↻ model returned reasoning with no final answer — "
                r"asking it to continue \((\d+)/3\)$"
            ),
            lambda m: f"↻ 模型只返回了推理、没有最终答案 — 正在请它继续（{m.group(1)}/3）",
        ),
    )


def translate_diagnostic_notice(
    text: str | None,
    *,
    force_chinese: Optional[bool] = None,
) -> str:
    """Return a Simplified Chinese display string, or the original on miss / English UI."""
    if text is None:
        return ""
    s = str(text).strip()
    if not s:
        return s
    if not _lang_is_chinese(force_chinese):
        return s
    try:
        lang = get_language() if force_chinese is None else None
        if force_chinese is None and lang == DEFAULT_LANGUAGE:
            return s
    except Exception:
        if force_chinese is None:
            return s
    for pat, fmt in _templates():
        m = pat.fullmatch(s)
        if not m:
            continue
        try:
            return fmt(m)
        except Exception:
            return s
    return s


__all__ = ["translate_diagnostic_notice"]
