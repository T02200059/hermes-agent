"""Diff card customization for messaging platforms.

Provides after-the-fact diff display for file-mutating tools:
- Feishu: interactive colored card with compact / expanded / full stages.
- QQ Bot: plain markdown diff message.

Core logic lives under owner/ per the二次开发规范:
- Official source files get only thin glue + # [owner] markers.
- All platform-specific rendering and callbacks are here.
"""

from owner.diff_card.dispatcher import (
    make_tool_start_snapshot_callback,
    maybe_send_diff_cards,
)
from owner.diff_card.feishu import (
    handle_feishu_diff_action,
    send_feishu_diff_card,
)
from owner.diff_card.qqbot import (
    diff_to_qq_markdown,
    send_qqbot_diff_markdown,
)

__all__ = [
    "make_tool_start_snapshot_callback",
    "maybe_send_diff_cards",
    "send_feishu_diff_card",
    "handle_feishu_diff_action",
    "diff_to_qq_markdown",
    "send_qqbot_diff_markdown",
]
