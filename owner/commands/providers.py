"""/providers command handler for gateway — interactive card on Feishu, plain text elsewhere.

Thin-glue caller in gateway/run.py:
  ``from owner.commands.providers import handle_providers_command``
  ``return await handle_providers_command(adapters=self.adapters, event=event)``

可移除性：删除此文件后 gateway/run.py 中 ImportError fallback 返回
"providers 命令不可用" 字符串，不会崩溃。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def handle_providers_command(
    *,
    adapters: Any,
    event: Any,
) -> Optional[str]:
    """Handle /providers command.

    Args:
        adapters: Dict-like mapping Platform → adapter instance.
        event: MessageEvent or similar with ``.source`` attribute.

    Returns:
        str for plain-text response; None when a Feishu card was sent
        (suppresses default text reply from gateway runner).
    """
    # Lazy imports — keep gateway dependency minimal.
    from gateway.config import Platform

    source = getattr(event, "source", None)
    chat_id = getattr(source, "chat_id", "") or ""

    # Feishu: interactive card
    if source and source.platform == Platform.FEISHU:
        adapter = adapters.get(Platform.FEISHU)
        if adapter and hasattr(adapter, "send_model_picker_card") and chat_id:
            try:
                rows = _load_provider_rows()
                if rows:
                    await adapter.send_model_picker_card(
                        chat_id=chat_id, providers=rows, source=source,
                    )
                    return None
            except Exception as exc:
                logger.warning(
                    "[/providers] Feishu card failed, falling back to text: %s", exc
                )

    # Fallback: plain text
    try:
        rows = _load_provider_rows()
    except Exception as exc:
        logger.warning("[/providers] Failed to load provider inventory: %s", exc)
        return _TEXT["load_failed"]

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
    """Load provider inventory rows from hermes_cli.inventory."""
    from hermes_cli.inventory import build_models_payload, load_picker_context

    ctx = load_picker_context()
    payload = build_models_payload(ctx, max_models=50)
    return payload.get("providers") or []


_TEXT = {
    "header": "已配置 provider（共 {count} 个）：",
    "no_providers": "当前没有已配置的 provider（未设置任何 API Key）",
    "load_failed": "⚠️ 无法读取 provider 列表",
    "more_models": "共 {total} 个模型",
}
