"""[owner] 展示层翻译过滤器（T1-4）。

背景
----
官方仓库自带 i18n 机制：``agent/i18n.py`` 提供 ``t(key)``，译文放在
``locales/<lang>.yaml``。上游按「thin slice」原则只覆盖少量静态消息
（审批提示、少数 gateway 斜杠命令回复、重启排空通知）——上游 main 上共
276 处 ``t()``（12 个文件）。

owner 侧把该机制扩展到了约 894 处（49 个官方文件），其中 601 处用的键
是上游没有的。代价不在译文（译文放在 ``locales/zh.yaml``，属官方认可位置，
追加式写入、几乎不产生冲突），而在**调用点**：``t()`` 嵌在官方函数体内，
每次 sync 都会与上游改动产生冲突块——这也是 433 个冲突块里约 70% 的来源。

本模块提供另一条路径：官方代码保持英文原文（与上游逐字节一致 → 零冲突块），
中文只在**最终展示边界**转换一次。

安全约束（源自 T1-1 的教训）
--------------------------
T1-1 的根因是「把展示用译文写进了机器可读的返回值，消费方按英文正则匹配
该值」——同一个字符串既被展示又被逻辑匹配时，翻译会击穿逻辑。

因此本过滤器有明确的适用边界：

1. **只在真正的展示边界调用**（把消息发出去之前），不得用于任何返回值、
   状态字段、或被逻辑匹配的字符串。模块本身做精确匹配、绝不猜测语义，
   调用方的责任是「只喂展示面」。
2. **只做整串匹配**，不做子串/正则替换——避免改坏消息里嵌着的命令、路径、
   标识符（例如审批提示里的具体命令文本）。
3. 未命中一律**原样返回**（优雅降级，不漏字不串码）。
4. 含 ``{placeholder}`` 的模板走模板匹配：静态片段必须完整匹配，占位符
   捕获到的内容**原样保留**，只替换静态片段的中文。
5. 同一英文原文对应多个不同中文键时（现网 6 例），**默认不翻译**并把该原文
   记入 :func:`unresolved_texts`，避免任取其一造成前后不一致；确需消解时在
   ``_AMBIGUOUS_OVERRIDES`` 里显式指定。
6. 目标语言为 ``en``（或无 catalog）时是恒等函数，零开销短路。

与上游机制的关系
----------------
``t()`` 仍是**首选**：上游已经用 ``t()`` 覆盖的串，owner 只需在
``locales/zh.yaml`` 补键（零冲突）。本过滤器面向的是「上游未覆盖、而 owner
需要在展示层中文化」的那部分串。
"""

from __future__ import annotations

import logging
import re
import string
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 对官方**私有**符号的依赖（``agent.i18n._locales_dir`` / ``._load_catalog``）
# 必须可降级且**可观测**：降级本身已有自解析兜底，但静默的兜底会让
# 「上游改了名字、我们一直在用次优路径」这件事永远不显形。
_private_dep_notices: set = set()


def _warn_once(key: str, message: str, *args: Any) -> None:
    """Log ``message`` once per process per ``key``."""
    if key in _private_dep_notices:
        return
    _private_dep_notices.add(key)
    logger.warning(message, *args)


# 语言为英文时无需翻译（上游 DEFAULT_LANGUAGE）；显式短路避免加载 catalog
_BASELINE_LANGUAGE = "en"

# 同一英文原文对应多个不同中文键时的显式消解。
#
# 现网 catalog 有 6 例这样的原文。任取其一会导致同一句话在不同界面用词
# 不一致，故默认不翻译；这里的条目是**刻意的**选择，取值风格与
# locales/zh.yaml 中该英文原文出现次数最多的译法保持一致。
_AMBIGUOUS_OVERRIDES: Dict[str, str] = {
    # 审批卡标题：两处译法（命令审批请求 / 命令需要审批），取更短的动作式表达
    "\u26a0\ufe0f Command Approval Required": "\u26a0\ufe0f \u547d\u4ee4\u5ba1\u6279\u8bf7\u6c42",
    # 审批按钮：允许 / 批准，与 approval.allowed_* 系列（✓ 允许）用词统一
    "\u2705 Approve": "\u2705 \u5141\u8bb8",
}


@dataclass
class _LangMap:
    """某一语言的 (英文原文 → 译文) 查找表。"""

    lang: str
    exact: Dict[str, str] = field(default_factory=dict)
    # (编译好的正则, 渲染计划, 静态骨架长度)——计划是
    # ("lit", 文本) / ("val", 捕获组名) 的序列；列表按骨架长度降序，
    # 保证重叠匹配时最具体的模板优先命中
    templates: List[Tuple[re.Pattern, Tuple[Tuple[str, str], ...], int]] = field(
        default_factory=list
    )
    # 因歧义而放弃翻译的英文原文（可读性用）
    unresolved: Tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.exact or self.templates)


_lock = threading.Lock()
_cache: Dict[str, _LangMap] = {}


# ---------------------------------------------------------------------------
# catalog 读取
# ---------------------------------------------------------------------------


def _locales_dir() -> Optional[Path]:
    """locales/ 目录（仓库根）。

    优先复用上游 ``agent.i18n`` 的解析，保证与 ``t()`` 用同一份 catalog；
    该私有符号不存在时退回自解析。
    """
    try:
        from agent.i18n import _locales_dir as _upstream_locales_dir

        path = Path(_upstream_locales_dir())
        if path.is_dir():
            return path
    except Exception as exc:
        _warn_once(
            "display_filter.upstream_locales_dir",
            "owner.i18n.display_filter fell back to its own locales/ resolution: "
            "cannot reach agent.i18n._locales_dir (%s). If the catalog diverges "
            "from t()'s, re-point this import; see owner/docs/owner改动清单.md "
            "§16.13.",
            exc,
        )

    candidate = Path(__file__).resolve().parents[2] / "locales"
    return candidate if candidate.is_dir() else None


def _flatten(node: Any, prefix: str, out: Dict[str, str]) -> None:
    """把嵌套 catalog 压成点分键 → 字符串。"""
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        dotted = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            _flatten(value, dotted, out)
        elif isinstance(value, str):
            out[dotted] = value


def _load_catalog(lang: str) -> Dict[str, str]:
    """读取某语言的扁平 catalog；失败返回空表（调用方保持英文）。"""
    try:
        from agent.i18n import _load_catalog as _upstream_load

        catalog = _upstream_load(lang)
        if isinstance(catalog, dict):
            return {str(k): str(v) for k, v in catalog.items()}
    except Exception as exc:
        _warn_once(
            "display_filter.upstream_load_catalog",
            "owner.i18n.display_filter fell back to parsing locales/%s.yaml "
            "directly: cannot reach agent.i18n._load_catalog (%s). Re-point this "
            "import; see owner/docs/owner改动清单.md §16.13.",
            lang,
            exc,
        )

    directory = _locales_dir()
    if directory is None:
        return {}
    path = directory / f"{lang}.yaml"
    if not path.is_file():
        return {}
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        logger.debug("display_filter: 读取 catalog 失败 lang=%s", lang, exc_info=True)
        return {}
    out: Dict[str, str] = {}
    _flatten(data, "", out)
    return out


# ---------------------------------------------------------------------------
# 模板编译
# ---------------------------------------------------------------------------


def _template_parts(text: str) -> Optional[List[Tuple[str, str]]]:
    """拆解 ``str.format`` 模板为 [("lit", 文本) | ("field", 名)]。

    解析失败（如模板里出现裸花括号）返回 ``None``，调用方跳过该条。
    """
    parts: List[Tuple[str, str]] = []
    try:
        for literal, field_name, _spec, _conv in string.Formatter().parse(text):
            if literal:
                parts.append(("lit", literal))
            if field_name is None:
                continue
            # 仅支持简单 ``{name}``（``{0}`` 位置参数与 ``{a.b}`` 属性访问跳过）
            if not field_name.isidentifier():
                return None
            parts.append(("field", field_name))
    except (ValueError, IndexError):
        return None
    return parts


# 含占位符的模板，其静态片段总长下限（见 _build_template 的说明）
_MIN_TEMPLATE_LITERAL = 3


def _build_template(
    en_text: str, localized: str
) -> Optional[Tuple[re.Pattern, Tuple[Tuple[str, str], ...], int]]:
    """为一条含占位符的译文构建 (匹配正则, 渲染计划, 静态骨架长度)。

    第三个返回值用于排序：模板之间存在重叠匹配（例如同一句话的
    「带工具名」与「不带工具名」两种变体），必须让**静态片段更长**的模板
    优先命中，否则会出现「用 A 句的译文去渲染 B 句」。
    """
    en_parts = _template_parts(en_text)
    loc_parts = _template_parts(localized)
    if not en_parts or not loc_parts:
        return None

    en_fields = [name for kind, name in en_parts if kind == "field"]
    loc_fields = [name for kind, name in loc_parts if kind == "field"]
    # 译文引入了原文没有的占位符 → 无法安全还原，放弃
    if not set(loc_fields) <= set(en_fields):
        return None

    # 安全护栏：静态片段必须有实质量。若模板几乎全是占位符（如 "{a}"），
    # 正则会退化成「匹配任意字符串」，把不该翻译的展示串一并改掉。
    literal_len = sum(len(v) for k, v in en_parts if k == "lit")
    if literal_len < _MIN_TEMPLATE_LITERAL:
        logger.debug(
            "display_filter: 模板静态片段过短（%d<%d），跳过 %r",
            literal_len,
            _MIN_TEMPLATE_LITERAL,
            en_text,
        )
        return None

    # 用命名捕获组重建正则：静态片段 re.escape，占位符非贪婪捕获。
    # 不开 DOTALL：``.`` 不跨行，避免模板吞掉整段多行输出。
    pattern_chunks: List[str] = []
    group_of: Dict[str, str] = {}
    for index, (kind, value) in enumerate(en_parts):
        if kind == "lit":
            pattern_chunks.append(re.escape(value))
        else:
            group = f"p{index}"
            group_of[value] = group
            pattern_chunks.append(f"(?P<{group}>.*?)")

    try:
        pattern = re.compile("^" + "".join(pattern_chunks) + "$")
    except re.error:
        logger.debug("display_filter: 正则编译失败，跳过模板 %r", en_text)
        return None

    # 渲染计划：按译文自身的片段顺序重建，占位符用捕获到的值替换
    plan: List[Tuple[str, str]] = []
    for kind, value in loc_parts:
        if kind == "lit":
            plan.append(("lit", value))
        else:
            plan.append(("val", group_of[value]))
    return pattern, tuple(plan), literal_len


# ---------------------------------------------------------------------------
# 查找表构建
# ---------------------------------------------------------------------------


def build_map(lang: str) -> _LangMap:
    """构建某语言的查找表（带进程内缓存）。"""
    normalized = (lang or "").strip().lower()
    with _lock:
        cached = _cache.get(normalized)
    if cached is not None:
        return cached

    mapping = _LangMap(lang=normalized)
    if normalized and normalized != _BASELINE_LANGUAGE:
        en_catalog = _load_catalog(_BASELINE_LANGUAGE)
        localized = _load_catalog(normalized)
        if en_catalog and localized:
            _populate(mapping, en_catalog, localized)

    with _lock:
        _cache[normalized] = mapping
    return mapping


def _populate(mapping: _LangMap, en_catalog: Dict[str, str], localized: Dict[str, str]) -> None:
    exact: Dict[str, str] = {}
    conflicted: Dict[str, str] = {}

    for key, en_text in en_catalog.items():
        loc_text = localized.get(key)
        if loc_text is None or loc_text == en_text:
            # 无译文或译文与英文相同 → 无需翻译
            continue

        has_placeholders = any(kind == "field" for kind, _ in (_template_parts(en_text) or []))

        if has_placeholders:
            built = _build_template(en_text, loc_text)
            if built is not None:
                mapping.templates.append(built)
            continue

        previous = exact.get(en_text)
        if previous is not None and previous != loc_text:
            # 同一英文原文 → 多个中文；不任取其一
            conflicted[en_text] = previous
            exact.pop(en_text, None)
            continue
        if en_text in conflicted:
            continue
        exact[en_text] = loc_text

    # 歧义原文若有显式消解，按消解值放回
    for en_text, chosen in _AMBIGUOUS_OVERRIDES.items():
        if en_text in conflicted:
            exact[en_text] = chosen
            conflicted.pop(en_text, None)

    # 静态骨架长的模板更具体，排前面（见 _build_template 的说明）
    mapping.templates.sort(key=lambda item: item[2], reverse=True)
    mapping.exact = exact
    mapping.unresolved = tuple(sorted(conflicted))


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def _resolve_language(lang: Optional[str]) -> str:
    if lang and lang.strip():
        return lang.strip().lower()
    try:
        from agent.i18n import get_language

        return (get_language() or _BASELINE_LANGUAGE).strip().lower()
    except Exception:
        import os

        return (os.environ.get("HERMES_LANGUAGE") or _BASELINE_LANGUAGE).strip().lower()


def translate(text: str, lang: Optional[str] = None) -> str:
    """把一条英文展示串翻成目标语言；未命中原样返回。

    仅用于**展示边界**。不要用它处理返回值、状态字段或会被逻辑匹配的字符串。
    """
    if not isinstance(text, str) or not text:
        return text

    target = _resolve_language(lang)
    if target == _BASELINE_LANGUAGE:
        return text

    mapping = build_map(target)
    if not mapping:
        return text

    hit = mapping.exact.get(text)
    if hit is not None:
        return hit

    for pattern, plan, _literal_len in mapping.templates:
        match = pattern.match(text)
        if match is None:
            continue
        rendered: List[str] = []
        for kind, value in plan:
            rendered.append(value if kind == "lit" else match.group(value))
        return "".join(rendered)

    return text


def translate_lines(text: str, lang: Optional[str] = None) -> str:
    """逐行翻译多行消息。

    整串未命中时按行再试一次——消息常在展示前被拼接（前缀/后缀），整串
    匹配不到但其中的行是 catalog 原串。行数超过 ``_MAX_LINES`` 时直接返回
    原文，避免对长输出做无意义的逐行扫描。
    """
    if not isinstance(text, str) or "\n" not in text:
        return translate(text, lang)

    whole = translate(text, lang)
    if whole != text:
        return whole

    lines = text.split("\n")
    if len(lines) > _MAX_LINES:
        return text

    changed = False
    out: List[str] = []
    for line in lines:
        converted = translate(line, lang)
        if converted != line:
            changed = True
        out.append(converted)
    return "\n".join(out) if changed else text


_MAX_LINES = 200


def unresolved_texts(lang: str = "zh") -> Tuple[str, ...]:
    """返回因歧义而放弃翻译的英文原文（供人工消解）。"""
    return build_map(lang).unresolved


def coverage(lang: str = "zh") -> Dict[str, int]:
    """返回当前查找表的规模统计（可观测性 / 测试用）。"""
    mapping = build_map(lang)
    return {
        "exact": len(mapping.exact),
        "templates": len(mapping.templates),
        "unresolved": len(mapping.unresolved),
    }


def clear_cache() -> None:
    """清空查找表缓存（测试与运行时改配置后使用）。"""
    with _lock:
        _cache.clear()


__all__ = [
    "translate",
    "translate_lines",
    "unresolved_texts",
    "coverage",
    "clear_cache",
    "build_map",
]
