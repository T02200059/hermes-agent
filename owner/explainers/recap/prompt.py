"""[owner] C13 recap — prompts + notice delivery prefix.

PREFIX 须与飞书 notice 卡规则、overlay.yaml notice_titles 字面一致。
"""

from __future__ import annotations

from typing import Optional

# 投递前缀：飞书 auto_card 按此前缀升为 notice 卡；不入主会话模型历史。
PREFIX = "📋 系统提示："

_SYSTEM = """You write a short progress-style recap of a conversation between a human (User) and an AI coding agent (Agent).

Hard constraints:
- Output ONE short paragraph in Simplified Chinese (or match the user's language if the dialogue is clearly not Chinese).
- Use subject voice as if speaking to the user: 「你…」「我们…」.
- Write it like a status note, not a changelog: where things stand / what is done / what is left or blocked / next step if already clear in the dialogue.
- Prefer progress and completion over implementation detail. Do NOT list filenames, paths, table_ids, test counts, API method names, or commit hashes unless one identifier is truly necessary to judge completion.
- No bullet list, no markdown fences, no title line, no quotes around the whole answer.
- Do not invent facts. If the next step is unclear, omit it rather than guessing.
- Keep it brief: about 2–4 short sentences; aim ≤220 Chinese characters so the hard ~350-char display cap does not cut mid-sentence.
- If a prior recap is provided, treat it as background for the omitted earlier turns. Prefer the recent dialogue when the two conflict."""

_USER = """请根据下面压平后的对话写一小段进度回顾（只输出正文）：
侧重做到哪了、完成度、还差什么/下一步；不要罗列文件名或实现细节清单。

---
{dialogue}
---"""

_USER_HYBRID = """请根据下面两段材料写一小段进度回顾（只输出正文）：
1. 「先前回顾」是被省略的对话前半段的说明，请当作已发生的背景，不要当成当前原文。
2. 「近期对话」是截断后保留的尾部原文，以这段为准更新进度；若与先前回顾冲突，以近期对话为准。
侧重做到哪了、完成度、还差什么/下一步；不要罗列文件名或实现细节清单。

---
【先前回顾】
{prior_recap}

【近期对话】
{dialogue}
---"""


def build_messages(dialogue: str, prior_recap: Optional[str] = None) -> list[dict[str, str]]:
    body = str(dialogue or "").strip() or "（空对话）"
    prior = str(prior_recap or "").strip()
    if prior:
        user = _USER_HYBRID.format(prior_recap=prior, dialogue=body)
    else:
        user = _USER.format(dialogue=body)
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]


def format_delivery(recap_text: str) -> str:
    text = str(recap_text or "").strip()
    if not text:
        return ""
    return f"{PREFIX}{text}"
