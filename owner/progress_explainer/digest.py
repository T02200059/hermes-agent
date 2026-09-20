"""证据 → 有界 prompt 输入（截断策略集中在此，防 prompt 膨胀）。

纯函数模块：不碰网络、不读配置、不持锁、不读 agent.messages。
输入 tracker_state（由 tracker.py 在锁保护下产出的浅快照 dict）+ cfg
（patch.yaml owner.progress_explainer 段，含默认值回填），输出一段
可直接拼进辅助模型 prompt 的文本。

截断策略（全部集中在本模块）：
- 用户原始请求        ≤ 300 字符
- 工具事件           最近 events_in_digest 条（默认 8），每条 ≤ chars_per_event
- reasoning 尾摘录     ≤ reasoning_tail_chars（默认 1500）
- 流统计 / 硬事实      纯数字，无截断问题
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# 与设计稿 §7 默认值一致；cfg 缺 key / 非法值时回落到这里。
_DEFAULT_EVENTS_IN_DIGEST = 8
_DEFAULT_CHARS_PER_EVENT = 200
_DEFAULT_REASONING_TAIL_CHARS = 1500
_USER_MESSAGE_MAX_CHARS = 300

# cfg 数值键 → 默认值（非法值统一回落）
_CFG_INT_KEYS = {
    "events_in_digest": _DEFAULT_EVENTS_IN_DIGEST,
    "chars_per_event": _DEFAULT_CHARS_PER_EVENT,
    "reasoning_tail_chars": _DEFAULT_REASONING_TAIL_CHARS,
}


def _cfg_int(cfg: Dict[str, Any], key: str) -> int:
    """读 cfg 数值键，非法（非 int / 负数）回落默认。"""
    try:
        val = int(cfg.get(key, _CFG_INT_KEYS[key]))
    except (TypeError, ValueError):
        val = _CFG_INT_KEYS[key]
    if val < 0:
        val = _CFG_INT_KEYS[key]
    return val


def _clip(text: Any, limit: int) -> str:
    """把任意值转成单行字符串并截断到 limit 字符。None → 空串。"""
    if text is None:
        return ""
    s = str(text).replace("\r", " ").replace("\n", " ").strip()
    if limit <= 0:
        return ""
    if len(s) > limit:
        return s[:limit] + "…"
    return s


def _format_events(events: List[Dict[str, Any]], max_events: int, chars_per_event: int) -> List[str]:
    """最近 N 条工具事件 → 每条一行的摘要（started / completed 两种）。"""
    lines: List[str] = []
    for ev in events[-max_events:] if max_events else []:
        if not isinstance(ev, dict):
            continue
        kind = ev.get("kind") or "tool"
        name = _clip(ev.get("name") or ev.get("tool") or "?", 80)
        if kind == "started":
            args = _clip(ev.get("args") or ev.get("args_preview"), chars_per_event)
            line = f"- {name} 开始执行，参数: {args}" if args else f"- {name} 开始执行"
        elif kind == "tool_gen":
            # E4：工具参数生成中（尚未执行），如 45KB write_file
            args = _clip(ev.get("args") or ev.get("args_preview"), chars_per_event)
            line = f"- 正在生成 {name} 的调用参数（尚未执行），预览: {args}" if args else f"- 正在生成 {name} 的调用参数（尚未执行）"
        else:  # completed / 其他
            dur = ev.get("duration_s")
            dur_part = f"，耗时 {dur}s" if isinstance(dur, (int, float)) else ""
            if ev.get("is_error"):
                result = _clip(ev.get("result") or ev.get("result_summary"), chars_per_event)
                line = f"- {name} 执行出错{dur_part}，结果: {result}"
            else:
                result = _clip(ev.get("result") or ev.get("result_summary"), chars_per_event)
                line = f"- {name} 完成{dur_part}，结果摘要: {result}"
        lines.append(line)
    return lines


def build_digest(tracker_state: dict, cfg: dict) -> str:
    """把 tracker 快照 + 配置压成有界的 prompt 证据段。

    纯函数：只读入参，返回 str；任何字段缺失/类型不符都安全跳过。
    """
    if not isinstance(tracker_state, dict):
        tracker_state = {}
    if not isinstance(cfg, dict):
        cfg = {}

    max_events = _cfg_int(cfg, "events_in_digest")
    chars_per_event = _cfg_int(cfg, "chars_per_event")
    tail_chars = _cfg_int(cfg, "reasoning_tail_chars")

    sections: List[str] = []

    # --- 硬事实（不由模型生成）---
    hard = tracker_state.get("hard_facts")
    if isinstance(hard, dict) and hard:
        parts = []
        it = hard.get("iteration")
        max_it = hard.get("max_iterations")
        if isinstance(it, int) and isinstance(max_it, int):
            parts.append(f"迭代 {it}/{max_it}")
        elif isinstance(it, int):
            parts.append(f"迭代 {it}")
        elapsed = hard.get("elapsed_s")
        if isinstance(elapsed, (int, float)):
            parts.append(f"本轮已耗时 {elapsed:.0f} 秒" if isinstance(elapsed, float) else f"本轮已耗时 {elapsed} 秒")
        current_tool = hard.get("current_tool")
        if current_tool:
            parts.append(f"当前正在执行的工具: {_clip(current_tool, 80)}")
        if parts:
            sections.append("硬事实: " + "；".join(parts) + "。")

    # --- 用户原始请求 ---
    user_message = tracker_state.get("user_message")
    user_part = _clip(user_message, _USER_MESSAGE_MAX_CHARS)
    if user_part:
        sections.append(f"用户原始请求: {user_part}")

    # --- 最近工具事件 ---
    events = tracker_state.get("events")
    if isinstance(events, list) and events:
        lines = _format_events(events, max_events, chars_per_event)
        if lines:
            sections.append("最近的工具事件（新→旧为正序，仅列最近 %d 条）:\n" % len(lines) + "\n".join(lines))

    # --- 流统计 ---
    streams = tracker_state.get("stream_stats")
    if isinstance(streams, dict) and streams:
        parts = []
        text_chars = streams.get("text_chars")
        if isinstance(text_chars, (int, float)) and text_chars > 0:
            rate = streams.get("text_chars_per_s")
            rate_part = ""
            if isinstance(rate, (int, float)) and rate > 0:
                rate_part = f"（约 {rate:.0f} 字符/秒）"
            parts.append(f"正文已流式输出 {int(text_chars)} 字符{rate_part}")
        reasoning_chars = streams.get("reasoning_chars")
        if isinstance(reasoning_chars, (int, float)) and reasoning_chars > 0:
            parts.append(f"思考流已生成 {int(reasoning_chars)} 字符（本 turn 有推理流）")
        elif streams.get("has_reasoning_stream"):
            parts.append("本 turn 有推理流")
        if parts:
            sections.append("流统计: " + "；".join(parts) + "。")

    # --- reasoning 尾部摘录（只做截断，输出仍受 prompt 约束禁止引用原文）---
    reasoning_tail = tracker_state.get("reasoning_tail")
    tail_part = _clip(reasoning_tail, tail_chars)
    if tail_part:
        sections.append("思考流最新内容的尾部摘录（仅供判断在推敲什么，输出中禁止引用原文）:\n" + tail_part)

    if not sections:
        return "（暂无可读证据：尚无工具事件、流输出或思考摘录。）"
    return "\n\n".join(sections)
