"""[owner] C13 — localize official ``last_activity_desc`` stamps for progress fact_line.

Official code keeps English ``_touch_activity(...)`` literals; this table is the
display-only zh mapping used when ``display.language`` is Chinese. Unknown stamps
fail-open (original English kept). English UI is a no-op.
"""

from __future__ import annotations

import re
from typing import Callable, Match, Optional, Pattern, Sequence

from owner.explainers.common import display_language_is_chinese

# Exact static stamps (production + common durable projections).
_EXACT_ZH: dict[str, str] = {
    "initializing": "正在初始化",
    "starting new turn": "开始新回合",
    "starting new turn (cached)": "开始新回合（缓存）",
    "receiving stream response": "正在接收流式响应",
    "model reading the prompt": "模型正在读取提示",
    "waiting for provider response": "正在等待供应商响应",
    "waiting for provider response (streaming)": "正在等待供应商响应（流式）",
    "waiting for non-streaming API response": "正在等待非流式 API 响应",
    "waiting for first stream event after reconnect": "重连后正在等待首个流事件",
    "local model loading": "正在加载本地模型",
    "⚙ processing prompt": "⚙ 正在处理提示",
    "context compression started": "上下文压缩已开始",
    "context compression in progress": "正在压缩上下文",
    "context compression completed": "上下文压缩已完成",
    "context compression cancelled": "上下文压缩已取消",
    "context compression failed": "上下文压缩失败",
    "context compression rollback failed": "上下文压缩回滚失败",
    "context compression timed out": "上下文压缩超时",
    "compressing context": "正在压缩上下文",
    "session hygiene compression turn-hold": "会话卫生压缩：回合占用中",
    "session hygiene compression timed out": "会话卫生压缩超时",
    "session hygiene compression cancelled at commit fence": "会话卫生压缩在提交栅栏处取消",
    "session hygiene compression aborted": "会话卫生压缩已中止",
    "calling model": "正在调用模型",
    "done": "完成",
    "api_call": "API 调用",
}

_PHASE_ZH: dict[str, str] = {
    "first_event": "等待首事件",
    "reconnect": "重连中",
    "pre_progress": "尚无实质进展",
    "post_event": "事件后静默",
    "first_chunk": "等待首块",
    "post_chunk": "块后静默",
    "no chunks yet": "尚无数据块",
}

_WATCHDOG_LABEL_ZH: dict[str, str] = {
    "wall-clock stale": "墙钟过期",
    "TTFB": "TTFB",
    "first progress": "首次进展",
    "stream idle": "流空闲",
    "stream stale": "流过期",
}

_Fmt = Callable[[Match[str]], str]
_Template = tuple[Pattern[str], _Fmt]


def _phase(raw: str) -> str:
    return _PHASE_ZH.get(raw, raw)


def _watchdog(raw: str) -> str:
    return _WATCHDOG_LABEL_ZH.get(raw, raw)


def friendly_tool_token(name: object) -> str:
    """Map a bare tool id to curated ``display.verb.*`` (via ``get_tool_verb``).

    Same source as tool-progress friendly labels / ``display.friendly_tool_labels``.
    """
    n = str(name or "").strip()
    if not n:
        return n
    try:
        from agent.display import get_tool_verb

        verb = get_tool_verb(n)
    except Exception:
        verb = None
    return verb or n


def friendly_tool_list(names: object) -> str:
    """Comma-separated tool ids → friendly tokens (keeps unknown names)."""
    raw = str(names or "").strip()
    if not raw:
        return raw
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return ", ".join(friendly_tool_token(p) for p in parts)


def format_running_tool(tool_name: object) -> str:
    """Delegate to :func:`agent.display.format_running_tool` (display.verb.*)."""
    from agent.display import format_running_tool as _fmt

    return _fmt(str(tool_name or ""))


def _templates() -> Sequence[_Template]:
    return (
        (
            re.compile(r"^starting API call #(\d+)$"),
            lambda m: f"开始第 {m.group(1)} 次 API 调用",
        ),
        (
            re.compile(r"^API call #(\d+) completed$"),
            lambda m: f"第 {m.group(1)} 次 API 调用已完成",
        ),
        (
            re.compile(r"^tool results posted, continuing iteration #(\d+)$"),
            lambda m: f"工具结果已回写，继续第 {m.group(1)} 轮迭代",
        ),
        (
            # Prefer curated verb phrase (display.verb.*) over "正在执行工具：terminal".
            re.compile(r"^executing tool: (.+)$"),
            lambda m: format_running_tool(m.group(1)),
        ),
        (
            re.compile(r"^tool running: (.+)$"),
            lambda m: format_running_tool(m.group(1)),
        ),
        (
            re.compile(r"^tool completed: (.+) \(([0-9.]+)s\)( \(error\))?$"),
            lambda m: (
                f"工具已完成：{friendly_tool_token(m.group(1))}（{m.group(2)} 秒）"
                + ("（出错）" if m.group(3) else "")
            ),
        ),
        (
            re.compile(r"^sequential tool running \((\d+)s\): (.+)$"),
            lambda m: (
                f"顺序工具运行中（{m.group(1)} 秒）："
                f"{friendly_tool_list(m.group(2))}"
            ),
        ),
        (
            re.compile(r"^executing (\d+) tools concurrently: (.+)$"),
            lambda m: (
                f"正在并发执行 {m.group(1)} 个工具："
                f"{friendly_tool_list(m.group(2))}"
            ),
        ),
        (
            re.compile(
                r"^concurrent tools running \((\d+)s, (\d+) remaining: (.+)\)$"
            ),
            lambda m: (
                f"并发工具运行中（{m.group(1)} 秒，剩余 {m.group(2)} 个："
                f"{friendly_tool_list(m.group(3))}）"
            ),
        ),
        (
            re.compile(r"^waiting for stream response \((\d+)s, (.+)\)$"),
            lambda m: f"正在等待流式响应（{m.group(1)} 秒，{_phase(m.group(2))}）",
        ),
        (
            re.compile(r"^waiting for provider response \((\d+)s, (.+)\)$"),
            lambda m: f"正在等待供应商响应（{m.group(1)} 秒，{_phase(m.group(2))}）",
        ),
        (
            re.compile(r"^stale stream detected after (\d+)s, reconnecting$"),
            lambda m: f"流停滞 {m.group(1)} 秒，正在重连",
        ),
        (
            re.compile(r"^stale non-streaming call killed after (\d+)s$"),
            lambda m: f"非流式调用停滞 {m.group(1)} 秒已终止",
        ),
        (
            re.compile(
                r"^codex stream killed after (\d+)s with no first stream event$"
            ),
            lambda m: f"Codex 流在 {m.group(1)} 秒内无首事件已终止",
        ),
        (
            re.compile(
                r"^codex stream killed after (\d+)s without model progress$"
            ),
            lambda m: f"Codex 流在 {m.group(1)} 秒内无模型进展已终止",
        ),
        (
            re.compile(r"^codex stream killed after (\d+)s with no SSE events$"),
            lambda m: f"Codex 流在 {m.group(1)} 秒内无 SSE 事件已终止",
        ),
        (
            re.compile(r"^stream retry (\d+)/(\d+) after (.+)$"),
            lambda m: f"流重试 {m.group(1)}/{m.group(2)}（因 {m.group(3)}）",
        ),
        (
            re.compile(r"^API error recovery \(attempt (\d+)/(\d+)\)$"),
            lambda m: f"API 错误恢复（第 {m.group(1)}/{m.group(2)} 次）",
        ),
        (
            re.compile(r"^resumed after the computer slept for (\d+)s$"),
            lambda m: f"电脑休眠 {m.group(1)} 秒后已恢复",
        ),
        (
            re.compile(r"^compression blocked \((.+)\)$"),
            lambda m: f"压缩被阻止（{m.group(1)}）",
        ),
        (
            re.compile(r"^error retry backoff \((\d+)/(\d+)\)$"),
            lambda m: f"错误重试退避（{m.group(1)}/{m.group(2)}）",
        ),
        (
            re.compile(r"^auto-recovery wait \((\d+)/(\d+)\)$"),
            lambda m: f"自动恢复等待（{m.group(1)}/{m.group(2)}）",
        ),
        (
            re.compile(r"^empty response retry backoff \((\d+)/(\d+)\)$"),
            lambda m: f"空响应重试退避（{m.group(1)}/{m.group(2)}）",
        ),
        (
            re.compile(r"^retry backoff \((\d+)/(\d+)\)$"),
            lambda m: f"重试退避（{m.group(1)}/{m.group(2)}）",
        ),
        (
            re.compile(r"^⚙ processing prompt — (\d+)%$"),
            lambda m: f"⚙ 正在处理提示 — {m.group(1)}%",
        ),
        (
            re.compile(
                r"^⏳ loading (.+) into memory — (\d+)% "
                r"\(responses start once the model is loaded\)$"
            ),
            lambda m: (
                f"⏳ 正在将 {m.group(1)} 加载到内存 — {m.group(2)}%"
                "（加载完成后开始响应）"
            ),
        ),
        (
            re.compile(
                r"^delegate_task: subagent (.+) \(iteration (\d+)/(\d+)\)$"
            ),
            lambda m: (
                f"委派任务：子代理 {_localize_body(m.group(1))} "
                f"（第 {m.group(2)}/{m.group(3)} 轮迭代）"
            ),
        ),
        (
            re.compile(r"^codex app-server: (.+)$"),
            lambda m: f"Codex app-server：{m.group(1)}",
        ),
        # Operator wait-notice lines (#92550) — may carry phase + watchdog suffix.
        (
            re.compile(
                r"^⏳ (still waiting on|waiting on) (.+) — (.+?)(?: \(auto-reconnect: (.+) watchdog in (\d+)s\))?$"
            ),
            _fmt_wait_notice,
        ),
        # Backoff heartbeats: "<label>, Ns remaining"
        (
            re.compile(r"^(.+), (\d+)s remaining$"),
            lambda m: f"{_localize_body(m.group(1), allow_remaining=False)}，剩余 {m.group(2)} 秒",
        ),
    )


_WAIT_PHASE_TEMPLATES: Sequence[tuple[Pattern[str], _Fmt]] = (
    (
        re.compile(r"^(\d+)s waiting for the first provider event$"),
        lambda m: f"已等待首个供应商事件 {m.group(1)} 秒",
    ),
    (
        re.compile(
            r"^(\d+)s waiting for the first provider event after reconnect$"
        ),
        lambda m: f"重连后已等待首个供应商事件 {m.group(1)} 秒",
    ),
    (
        re.compile(
            r"^provider stream open; (\d+)s without substantive model progress$"
        ),
        lambda m: f"供应商流已打开；{m.group(1)} 秒无实质模型进展",
    ),
    (
        re.compile(r"^provider stream active; (\d+)s without stream events$"),
        lambda m: f"供应商流活跃中；{m.group(1)} 秒无流事件",
    ),
    (
        re.compile(r"^(\d+)s waiting for the first stream chunk$"),
        lambda m: f"已等待首个数据块 {m.group(1)} 秒",
    ),
    (
        re.compile(r"^stream open; (\d+)s without stream output$"),
        lambda m: f"流已打开；{m.group(1)} 秒无流输出",
    ),
)


def _fmt_wait_phase(text: str) -> str:
    for pat, fmt in _WAIT_PHASE_TEMPLATES:
        m = pat.fullmatch(text)
        if m:
            return fmt(m)
    return text


def _fmt_wait_notice(m: Match[str]) -> str:
    lead = "仍在等待" if m.group(1).startswith("still") else "正在等待"
    model = m.group(2)
    phase = _fmt_wait_phase(m.group(3))
    out = f"⏳ {lead} {model} — {phase}"
    if m.group(4) is not None:
        out += (
            f"（自动重连：{_watchdog(m.group(4))} 看门狗将在 "
            f"{m.group(5)} 秒后触发）"
        )
    return out


def _localize_body(desc: str, *, allow_remaining: bool = True) -> str:
    """Translate *desc* assuming Chinese UI (used by nested templates)."""
    s = str(desc or "").strip()
    if not s:
        return s
    hit = _EXACT_ZH.get(s)
    if hit is not None:
        return hit
    for pat, fmt in _templates():
        # Nested call from the remaining-suffix formatter must not re-match it.
        if not allow_remaining and pat.pattern == r"^(.+), (\d+)s remaining$":
            continue
        m = pat.fullmatch(s)
        if m:
            try:
                return fmt(m)
            except Exception:
                return s
    # Bare tool id (e.g. activity summary current_tool mirrored into last_activity_desc)
    # → curated display.verb.* when friendly labels are on.
    token = friendly_tool_token(s)
    return token if token != s else s


def localize_activity_desc(
    desc: object,
    *,
    force_chinese: Optional[bool] = None,
) -> str:
    """Return zh display text for an activity stamp, or the original on miss / en UI.

    ``force_chinese`` overrides ``display.language`` (tests); ``None`` follows
    ``display_language_is_chinese()``.
    """
    if desc is None:
        return ""
    s = str(desc).strip()
    if not s:
        return s
    chinese = (
        display_language_is_chinese()
        if force_chinese is None
        else bool(force_chinese)
    )
    if not chinese:
        # Activity stamp sentences stay English; bare tool ids still take display.verb.*.
        token = friendly_tool_token(s)
        return token if token != s else s
    return _localize_body(s)


def mapped_exact_count() -> int:
    """Number of exact-match entries (for docs / tests)."""
    return len(_EXACT_ZH)


def mapped_template_count() -> int:
    """Number of regex template entries (for docs / tests)."""
    return len(_templates()) + len(_WAIT_PHASE_TEMPLATES)


__all__ = [
    "format_running_tool",
    "friendly_tool_list",
    "friendly_tool_token",
    "localize_activity_desc",
    "mapped_exact_count",
    "mapped_template_count",
]
