"""提示词模板与输出约束（设计稿 §11）。

三段式输出要求：① 现在在做什么 ② 依据（读了什么/跑了什么）
③ 接下来打算做什么 + 粗估（允许"不确定"，禁止硬承诺）。

硬约束（写进 system，模型必须遵守）：
- 只输出自然语言概述，绝不引用思考原文（防 CoT 泄漏进群聊）；
- 不带 markdown 标题 / 代码块；
- ≤3 句；
- 语言随 display.language。

纯函数模块：不做网络调用、不持状态。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# 投递时由 dispatcher 拼在最终文案最前面的固定前缀，标明不是模型在说话。
PREFIX = "🧭 系统提示："

# 支持的 language 码 → 提示词语言指示（其余一律按英文）。
_LANGUAGES = {
    "zh": "Chinese (Simplified, 简体中文)",
    "zh-cn": "Chinese (Simplified, 简体中文)",
    "zh-tw": "Chinese (Traditional, 繁體中文)",
    "en": "English",
}

_SYSTEM_TEMPLATE = """You are a silent progress narrator inside a running AI agent session. \
The user has seen nothing readable for a while (only tool breadcrumbs or nothing), \
and you must tell them, in a few words of natural language, what is happening right now.

Write EXACTLY three parts, in this order:
1. What the agent is doing right now.
2. The evidence for that (which tool ran / what was read / what the stream counters show).
3. What the agent plans to do next, with a rough estimate. Saying "how much longer is unclear" is fine; NEVER make hard promises about timing or success.

Hard constraints (violations are discarded):
- Natural-language prose only. NEVER quote or paraphrase the raw reasoning excerpt verbatim; use it only to understand what is being pondered (no chain-of-thought leakage).
- No markdown headings, no bullet lists, no code blocks.
- At most 3 sentences total.
- Write in {language}.
- Do not invent facts that are not in the evidence below."""

_USER_TEMPLATE = """用户本次请求:
{user_message}

当前运行证据:
{digest}

硬事实（权威数据，引用时以此为准）:
{hard_facts}

请按系统提示的三段式要求输出，最多 3 句，语言为 {language}。"""


def _norm_language(language: Any) -> str:
    """归一化 language：未知值回落英文（fail-open，不抛）。"""
    key = str(language or "").strip().lower()
    return _LANGUAGES.get(key, _LANGUAGES["en"])


def _format_hard_facts(hard_facts: Dict[str, Any]) -> str:
    """硬事实 dict → 单行文本（纯展示，模型无权改写）。"""
    if not hard_facts:
        return "（暂无）"
    parts: List[str] = []
    it = hard_facts.get("iteration")
    max_it = hard_facts.get("max_iterations")
    if isinstance(it, int) and isinstance(max_it, int):
        parts.append(f"迭代 {it}/{max_it}")
    elif isinstance(it, int):
        parts.append(f"迭代 {it}")
    elapsed = hard_facts.get("elapsed_s")
    if isinstance(elapsed, (int, float)):
        parts.append(f"已耗时 {elapsed:.0f}s" if isinstance(elapsed, float) else f"已耗时 {elapsed}s")
    current_tool = hard_facts.get("current_tool")
    if current_tool:
        parts.append(f"当前工具: {current_tool}")
    silence = hard_facts.get("silence_s")
    if isinstance(silence, (int, float)):
        parts.append(f"静默 {silence:.0f}s" if isinstance(silence, float) else f"静默 {silence}s")
    if not parts:
        return "（暂无）"
    return "；".join(parts)


def build_messages(
    user_message: str,
    digest: str,
    hard_facts: dict,
    language: str,
) -> List[Dict[str, str]]:
    """构造辅助模型 messages：[system, user] 两条。

    纯函数：不修改入参（hard_facts 内部仅读取），返回新 list。
    """
    lang = _norm_language(language)
    sys_prompt = _SYSTEM_TEMPLATE.format(language=lang)
    user_prompt = _USER_TEMPLATE.format(
        user_message=str(user_message or "").strip() or "（无，本 turn 由系统自动触发）",
        digest=str(digest or "").strip() or "（暂无证据）",
        hard_facts=_format_hard_facts(hard_facts if isinstance(hard_facts, dict) else {}),
        language=lang,
    )
    return [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]
