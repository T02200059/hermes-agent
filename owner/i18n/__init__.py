"""Owner i18n 展示层翻译 —— 可移除包。

把「中文只在展示边界转换一次」这条路径与官方源码解耦：官方文件保持英文
原文（与上游逐字节一致 → 零冲突块），中文由本包在输出侧完成。

入口：``owner.i18n.display_filter.translate(text, lang=None) -> str``

删除此包后，官方文件里的英文原文不再被中文化（界面回退为英文），但不会
导致崩溃——:func:`translate` 的所有调用点都必须容忍「原样返回」。
"""

from __future__ import annotations

from owner.i18n.display_filter import (
    clear_cache,
    coverage,
    translate,
    translate_lines,
    unresolved_texts,
)

__all__ = [
    "translate",
    "translate_lines",
    "unresolved_texts",
    "coverage",
    "clear_cache",
]
