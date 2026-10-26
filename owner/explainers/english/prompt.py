"""英文解说提示词与投递前缀。

PREFIX 须与飞书 notice 卡规则、patch.yaml notice_titles 字面一致。
"""

from __future__ import annotations

from typing import Any, Dict, List

# 投递时拼在最终文案最前面；飞书 auto_card 按此前缀升为 notice 卡。
PREFIX = "🔤 系统提示："

_SYSTEM = """You translate an AI agent reply that accidentally came out in English into clear Simplified Chinese for a Chinese-speaking user.

Hard constraints:
- Output ONLY the Chinese translation (natural prose).
- Do NOT wrap in quotes or markdown fences.
- Keep technical identifiers (paths, commands, APIs, code identifiers) recognizable; you may keep them in Latin script when that is clearer.
- Do not invent content that is not in the source.
- At most ~8 short sentences unless the source is longer; stay faithful, not verbose."""

_USER = """请把下面这段 agent 英文回复译成简体中文（只输出译文）：

---
{source}
---"""


def build_messages(source: str) -> List[Dict[str, str]]:
    body = str(source or "").strip() or "（空）"
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": _USER.format(source=body)},
    ]


def format_delivery(translation: str) -> str:
    text = str(translation or "").strip()
    if not text:
        return ""
    return f"{PREFIX}{text}"
