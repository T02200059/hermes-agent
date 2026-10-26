"""[owner] C13 recap — prompts + notice delivery prefix.

PREFIX 须与飞书 notice 卡规则、patch.yaml notice_titles 字面一致。
"""

from __future__ import annotations

from typing import Dict, List

# 投递前缀：飞书 auto_card 按此前缀升为 notice 卡；不入主会话模型历史。
PREFIX = "📋 系统提示："

_SYSTEM = """You write a short recap of a conversation between a human (User) and an AI coding agent (Agent).

Hard constraints:
- Output ONE short paragraph in Simplified Chinese (or match the user's language if the dialogue is clearly not Chinese).
- Use subject voice as if speaking to the user: 「你问了…」「我们改了/做了…」.
- Cover the main ask and what landed (or where things stalled). Do not invent facts.
- No bullet list, no markdown fences, no title line, no quotes around the whole answer.
- Keep technical identifiers (paths, commands, APIs) recognizable.
- Prefer ~2–5 sentences; stay under ~120 Chinese characters when the dialogue is short, longer only when needed."""

_USER = """请根据下面压平后的对话写一句/一小段回顾（只输出正文）：

---
{dialogue}
---"""


def build_messages(dialogue: str) -> List[Dict[str, str]]:
    body = str(dialogue or "").strip() or "（空对话）"
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": _USER.format(dialogue=body)},
    ]


def format_delivery(recap_text: str) -> str:
    text = str(recap_text or "").strip()
    if not text:
        return ""
    return f"{PREFIX}{text}"
