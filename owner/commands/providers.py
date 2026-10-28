"""/providers — list configured providers (text; Feishu card when adapter supports it).

Registered via ``owner/owner-extensions`` plugin. Gateway plugin dispatch only
passes ``source`` / session kwargs — not ``adapters`` — so we resolve the live
Feishu adapter via ``gateway.run._gateway_runner_ref`` when needed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _resolve_adapters(adapters: Any) -> Any:
    """Use an explicit adapters map, else the in-process GatewayRunner's."""
    if adapters:
        return adapters
    try:
        from gateway.run import _gateway_runner_ref

        runner = _gateway_runner_ref()
    except Exception:
        return None
    if runner is None:
        return None
    return getattr(runner, "adapters", None) or None


async def handle_providers_command(
    raw_args: str = "",
    *,
    source: Any = None,
    adapters: Any = None,
    event: Any = None,
    **_kwargs: Any,
) -> Optional[str]:
    """Handle /providers.

    Returns plain-text for most surfaces. Returns ``None`` when a Feishu
    model-picker card was sent (suppresses the default text reply).
    """
    if source is None and event is not None:
        source = getattr(event, "source", None)

    try:
        rows = await asyncio.to_thread(_load_provider_rows)
    except Exception as exc:
        logger.warning("[/providers] Failed to load provider inventory: %s", exc)
        return _TEXT["load_failed"]

    # Feishu interactive card — when adapter exposes send_model_picker_card
    # (C26-feishu-picker). Text path remains the always-on fallback.
    try:
        from gateway.config import Platform

        platform = getattr(source, "platform", None)
        chat_id = getattr(source, "chat_id", "") or ""
        adapters = _resolve_adapters(adapters)
        if (
            platform == Platform.FEISHU
            and adapters
            and chat_id
            and rows
        ):
            adapter = adapters.get(Platform.FEISHU) if hasattr(adapters, "get") else None
            if adapter is not None and hasattr(adapter, "send_model_picker_card"):
                await adapter.send_model_picker_card(
                    chat_id=chat_id, providers=rows, source=source,
                )
                return None
    except Exception as exc:
        logger.warning("[/providers] Feishu card failed, falling back to text: %s", exc)

    if not rows:
        return _TEXT["no_providers"]

    lines = [_TEXT["header"].format(count=len(rows)), ""]
    for row in rows:
        slug = row.get("slug", "")
        name = row.get("name", "")
        models = row.get("models") or []
        total = row.get("total_models", len(models))
        label = f"{slug}（{name}）" if name and name != slug else slug
        lines.append(f"▸ {label}")
        for m in models:
            lines.append(f"  • {m}")
        if total > len(models):
            lines.append(f"  … {_TEXT['more_models'].format(total=total)}")
        lines.append("")

    return "\n".join(lines).rstrip()


def _load_provider_rows() -> list:
    """Load inventory rows with picker-friendly probe knobs (non-blocking catalogs)."""
    from hermes_cli.inventory import build_models_payload, load_picker_context

    ctx = load_picker_context()
    payload = build_models_payload(
        ctx,
        max_models=50,
        for_picker=True,
        probe_custom_providers=False,
        probe_current_custom_provider=True,
    )
    return payload.get("providers") or []


_TEXT = {
    "header": "已配置 provider（共 {count} 个）：",
    "no_providers": "当前没有已配置的 provider（未设置任何 API Key）",
    "load_failed": "💡 无法读取 provider 列表",
    "more_models": "共 {total} 个模型",
}
