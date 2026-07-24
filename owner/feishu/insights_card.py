"""Feishu interactive card for the /insights command.

Builds a v2-schema card with markdown tables for Models, Platforms, Tools,
and Skills sections — much more readable than the plain-text list format.

Design follows the resume_card.py pattern:
- owner/ feishu/ holds all card-building logic
- gateway/ slash_commands.py does a thin platform check + call
- Fallback to plain text on any card build/send failure

All user-facing strings are i18n-ready via agent.i18n.t().
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from gateway.platforms.feishu import FeishuAdapter

from agent.i18n import t
from gateway.platforms.base import SendResult

logger = logging.getLogger(__name__)

# ── Day-name mapping (insights.py emits English abbreviations) ──
_DAY_I18N_KEYS: dict[str, str] = {
    "Mon": "gateway.insights.card.day_mon",
    "Tue": "gateway.insights.card.day_tue",
    "Wed": "gateway.insights.card.day_wed",
    "Thu": "gateway.insights.card.day_thu",
    "Fri": "gateway.insights.card.day_fri",
    "Sat": "gateway.insights.card.day_sat",
    "Sun": "gateway.insights.card.day_sun",
}


def _format_tokens(n: int) -> str:
    """Human-friendly token count: 1,004,104,661 → '1.0B' / 568,985,244 → '569.0M' / 147,087,026 → '147.1M'."""
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _format_duration_compact(seconds: float) -> str:
    """Compact duration: 3600 → '1h', 86400 → '1d', 300 → '5m'."""
    from agent.usage_pricing import format_duration_compact as _fmt
    return _fmt(seconds)


def _t(key: str, **kwargs: Any) -> str:
    """Shorthand for gateway.insights.card.* translations."""
    return t(f"gateway.insights.card.{key}", **kwargs)


def build_insights_card(report: Dict[str, Any]) -> Dict[str, Any]:
    """Build a v2-schema Feishu card with markdown tables for /insights.

    Args:
        report: The dict returned by InsightsEngine.generate().

    Returns:
        Feishu v2-schema card dict ready for send_card_via_rest.
    """
    days = report.get("days", 30)
    o = report["overview"]

    # ── Header summary ──
    total_hours = o.get("total_hours", 0)
    avg_session = o.get("avg_session_duration", 0)
    summary_lines = [
        f"**{_t('sessions')}:** {o['total_sessions']:,}  |  "
        f"**{_t('messages')}:** {o['total_messages']:,}  |  "
        f"**{_t('tool_calls')}:** {o['total_tool_calls']:,}",
        f"**{_t('tokens')}:** {_format_tokens(o['total_tokens'])} "
        f"({_t('token_in')}: {_format_tokens(o['total_input_tokens'])} / "
        f"{_t('token_out')}: {_format_tokens(o['total_output_tokens'])})",
    ]
    if total_hours > 0:
        summary_lines.append(
            f"**{_t('active_time')}:** ~{_format_duration_compact(total_hours * 3600)}  |  "
            f"**{_t('avg_session')}:** ~{_format_duration_compact(avg_session)}"
        )
    summary_md = "\n".join(summary_lines)

    elements: list[Dict[str, Any]] = [
        {"tag": "markdown", "content": summary_md},
        {"tag": "hr"},
    ]

    # ── Models table ──
    models = report.get("models", [])
    if models:
        rows = []
        for m in models[:5]:
            rows.append(
                f"| {m['model'][:25]} "
                f"| {m['sessions']:,} "
                f"| {_format_tokens(m['total_tokens'])} |"
            )
        table_md = (
            f"**{_t('models_header')}**\n\n"
            f"| {_t('model')} | {_t('sessions')} | {_t('tokens')} |\n"
            f"| --- | ---: | ---: |\n"
            + "\n".join(rows)
        )
        elements.append({"tag": "markdown", "content": table_md})

    # ── Platforms table ──
    platforms = report.get("platforms", [])
    if len(platforms) > 1:
        rows = []
        for p in platforms:
            rows.append(f"| {p['platform']} | {p['sessions']:,} | {p['messages']:,} |")
        table_md = (
            f"**{_t('platforms_header')}**\n\n"
            f"| {_t('platform')} | {_t('sessions')} | {_t('messages')} |\n"
            f"| --- | ---: | ---: |\n"
            + "\n".join(rows)
        )
        elements.append({"tag": "markdown", "content": table_md})

    # ── Tools table ──
    tools = report.get("tools", [])
    if tools:
        rows = []
        for tool_item in tools[:8]:
            rows.append(
                f"| {tool_item['tool']} "
                f"| {tool_item['count']:,} "
                f"| {tool_item['percentage']:.1f}% |"
            )
        table_md = (
            f"**{_t('tools_header')}**\n\n"
            f"| {_t('tool')} | {_t('calls')} | {_t('pct')} |\n"
            f"| --- | ---: | ---: |\n"
            + "\n".join(rows)
        )
        elements.append({"tag": "markdown", "content": table_md})

    # ── Skills table ──
    skills_data = report.get("skills", {})
    top_skills = skills_data.get("top_skills", [])
    if top_skills:
        rows = []
        for s in top_skills[:5]:
            last_used = ""
            if s.get("last_used_at"):
                last_used = datetime.fromtimestamp(s["last_used_at"]).strftime("%b %d")
            rows.append(
                f"| {s['skill']} "
                f"| {s['view_count']:,} "
                f"| {s['manage_count']:,} "
                f"| {last_used} |"
            )
        table_md = (
            f"**{_t('skills_header')}**\n\n"
            f"| {_t('skill')} | {_t('loads')} | {_t('edits')} | {_t('last_used')} |\n"
            f"| --- | ---: | ---: | --- |\n"
            + "\n".join(rows)
        )
        elements.append({"tag": "markdown", "content": table_md})

    # ── Activity summary ──
    act = report.get("activity", {})
    if act.get("busiest_day") and act.get("busiest_hour"):
        hr = act["busiest_hour"]["hour"]
        ampm = "AM" if hr < 12 else "PM"
        display_hr = hr % 12 or 12
        day_abbr = act["busiest_day"]["day"]
        day_label = t(_DAY_I18N_KEYS.get(day_abbr, ""), default=day_abbr + "s")
        activity_lines = [
            f"**{_t('activity_header')}:** {day_label} "
            f"({act['busiest_day']['count']} {_t('sessions').lower()}), "
            f"{display_hr}{ampm} ({act['busiest_hour']['count']} {_t('sessions').lower()})",
        ]
        if act.get("active_days"):
            activity_lines.append(f"**{_t('active_days')}:** {act['active_days']}")
        if act.get("max_streak", 0) > 1:
            activity_lines.append(
                f"**{_t('best_streak')}:** "
                + _t("streak_days", count=act["max_streak"])
            )
        elements.append({"tag": "hr"})
        elements.append({"tag": "markdown", "content": "\n".join(activity_lines)})

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "content": _t("title", days=days),
                "tag": "plain_text",
            },
            "template": "blue",
        },
        "body": {"elements": elements},
    }


async def try_send_insights_card(
    adapter: Any,
    *,
    source: Any,
    event: Any,
    report: Dict[str, Any],
) -> str:
    """Feishu-specific path for /insights: send a card with markdown tables.

    Returns an empty string when the card path delivered, indicating the
    caller should stop rendering the plain-text version. Raises on
    unexpected failure so the caller can fall back to plain text.
    """
    if not adapter or not hasattr(adapter, "_client"):
        raise RuntimeError("Feishu adapter not available")

    from owner.feishu.card_sender import send_card_via_rest

    event_meta = getattr(event, "metadata", None)
    metadata = dict(event_meta) if event_meta is not None else {}
    metadata["chat_type"] = source.chat_type
    if source.user_id:
        metadata["open_id"] = source.user_id
    elif source.user_id_alt:
        metadata["open_id"] = source.user_id_alt

    try:
        card = build_insights_card(report)
        result = await send_card_via_rest(adapter, source.chat_id, card, metadata)
        if result.success:
            logger.info(
                "[Feishu card] insights sent OK chat_id=%s message_id=%s",
                source.chat_id,
                result.message_id or "(none)",
            )
            return ""
        logger.info(
            "[Feishu card] insights send failed (%s); falling back to plain text",
            result.error,
        )
        raise RuntimeError(f"Card send failed: {result.error}")
    except Exception as exc:
        logger.warning(
            "[Feishu] /insights card build/send failed: %s; falling back to plain text",
            exc,
        )
        raise
