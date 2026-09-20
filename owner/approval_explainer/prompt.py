"""审批命令解说的提示词模板与输出约束。

设计约束 (设计稿 §prompt):
- 输出 2-3 句: ① 这条命令做什么 (点名具体对象) ② 风险特征 (是否删除/
  覆盖/杀进程, 可不可逆, 影响面) ③ 批准前需要注意什么。
- **绝不输出"建议批准/拒绝"类结论** —— approval 的意义在用户决策权,
  解说器只给事实。绝不编造命令里没有的细节。
- ≤3 句; 语言随 display.language; temperature=0。

纯函数模块: 不做网络调用、不持状态。
"""

from __future__ import annotations

from typing import Any, Dict, List

# 支持的 language 码 → 提示词语言指示 (其余一律按英文)。
_LANGUAGES = {
    "zh": "Chinese (Simplified, 简体中文)",
    "zh-cn": "Chinese (Simplified, 简体中文)",
    "zh-tw": "Chinese (Traditional, 繁體中文)",
    "en": "English",
}

_SYSTEM_TEMPLATE = """\
You explain one shell command to a human who must decide whether to approve \
its execution. They may not know what the command does.

Write EXACTLY two or three short sentences, in this order:
1. What this command does, naming the concrete objects it touches (which \
directory, file, service, process, or machine).
2. Its risk profile: does it delete/overwrite data, kill processes, restart \
services, or otherwise change state? Is the change reversible? How wide is \
the blast radius (one file vs a whole directory tree vs a whole host)?
3. If any, what the approver should double-check before allowing it.

Hard constraints (violations are discarded):
- NEVER give a recommendation, verdict, or instruction to approve or deny. \
Your job is facts only; the approval decision belongs to the human.
- NEVER invent details that are not in the command or the reason text below.
- No markdown headings, no bullet lists, no code blocks.
- At most 3 sentences total.
- Write in {language}."""

_USER_TEMPLATE = """\
命令 (已脱敏):
{command}

触发审批的原因 (官方规则说明):
{description}

请按系统提示的要求输出 2-3 句解说, 语言为 {language}。"""


def _norm_language(language: Any) -> str:
    """归一化 language: 未知值回落英文 (fail-open, 不抛)。"""
    key = str(language or "").strip().lower()
    return _LANGUAGES.get(key, _LANGUAGES["en"])


def _clip(text: Any, limit: int) -> str:
    s = str(text or "").replace("\r", " ").strip()
    if limit <= 0:
        return ""
    if len(s) > limit:
        return s[:limit] + "…"
    return s


def build_messages(
    command: str,
    description: str,
    language: str,
    *,
    command_max_chars: int = 2000,
    description_max_chars: int = 500,
) -> List[Dict[str, str]]:
    """构造辅助模型 messages: [system, user] 两条。

    纯函数: 不修改入参, 返回新 list。截断策略集中在此 (prompt 膨胀防线,
    对齐 progress_explainer.digest 的做法)。
    """
    lang = _norm_language(language)
    sys_prompt = _SYSTEM_TEMPLATE.format(language=lang)
    user_prompt = _USER_TEMPLATE.format(
        command=_clip(command, command_max_chars) or "（空）",
        description=_clip(description, description_max_chars) or "（无说明）",
        language=lang,
    )
    return [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]
