"""T2-15 guard: a locale catalog must not define the same key twice.

背景
----
`merge-conflict` 报告 T2-15 说 `locales/{zh,en}.yaml` 的 owner 新增键「分散成
两簇、插在上游活跃区间内」（引 `zh.yaml:36-69` 与 `:560-606`），修法是「把新增键
统一追加到 `approval:` 块末尾 + 界标注释（~120 行移动）」。逐条复核后该修法两个
方面都不成立（取证与结论见 `owner/docs/owner改动清单.md` §16.12）。

但在复核过程中，用 `yaml.compose()` 逐节点核对时发现了一个**真缺陷**：

    approval.hardline_blocked   在 en.yaml 定义于第 44 行与第 65 行
                                在 zh.yaml 定义于第 34 行与第 55 行

两处值逐字相同，所以 PyYAML 的「后定义者生效」把问题完全遮住了 —— 运行期读到的
是对的，编辑**第一处**却没有任何效果。它是本仓两个 owner i18n commit 各自往不同
小节添加同一个键造成的（`e93f3148e7` / `92e0787ea6`）。已删除第一处，保留
「拦截结果消息 / Block-result messages」小节里的那一处 —— 键的消费方是
`tools/approval.py::_hardline_block_result`（返回工具结果 dict），与同段的
`hardline_recovery_saved` / `hardline_recovery_manual` 同组。

为什么既有 parity 测试抓不到
----------------------------
`tests/agent/test_i18n.py::test_catalog_keys_match_english` 走的是
`yaml.safe_load` + `_flatten`：

  * `safe_load` 对重复键**不报错**（后定义者胜出，先定义的静默丢失）；
  * `_flatten` 把结果折进一个 `dict`，重复键在此之前就已经被合并掉；
  * 于是 `en_keys - lang_keys` 与 `lang_keys - en_keys` 两边都看不出异常 ——
    两本 catalog 的两处重复都被同等地抹平了。

所以「en/zh 键集一致」这条不变量与「单本 catalog 内部无重复」是**两条独立**的
不变量，前者永远无法发现后者。本文件的第一个用例补齐后者；第二个用例钉住修复的
对象本身（防止「两处一起删掉」也能通过）；第三个用例钉住**仪器选择**是承重的。

注：非 en/zh 的 15 本 catalog 不是本仓维护目标（见 `tests/agent/test_i18n.py`
的 `_MAINTAINED_LOCALES`），但它们同样在扫描范围内 —— 本缺陷的形态与语言无关。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

LOCALES_DIR = Path(__file__).resolve().parents[2] / "locales"

ALL_LOCALE_FILES = sorted(LOCALES_DIR.glob("*.yaml"))
MAINTAINED_LOCALES = ("en", "zh")

# The heading of the section the surviving approval.hardline_blocked belongs to.
_SECTION_HEADINGS = {
    "en": "Block-result messages",
    "zh": "拦截结果消息",
}


def _mappings(node):
    """Yield every mapping node in the document (nested ones included)."""
    if isinstance(node, yaml.MappingNode):
        yield node
        for _key_node, value_node in node.value:
            yield from _mappings(value_node)


def _duplicate_keys(text: str) -> dict[str, list[int]]:
    """Sibling key -> every 1-based line it is defined on, when >1.

    Uses ``compose`` rather than ``safe_load``: only the node tree still has the
    dropped occurrence, and ``KeyNode.start_mark.line`` gives its position.
    """
    found: dict[str, list[int]] = {}
    for node in _mappings(yaml.compose(text)):
        seen: dict[str, list[int]] = {}
        for key_node, _value_node in node.value:
            seen.setdefault(key_node.value, []).append(key_node.start_mark.line + 1)
        for key, lines in seen.items():
            if len(lines) > 1:
                found[key] = lines
    return found


def _key_line(text: str, top: str, key: str) -> int:
    """1-based line where ``top.key`` is defined."""
    root = yaml.compose(text)
    for top_node, value_node in root.value:
        if top_node.value == top and isinstance(value_node, yaml.MappingNode):
            for key_node, _value_node in value_node.value:
                if key_node.value == key:
                    return key_node.start_mark.line + 1
    raise AssertionError(f"{top}.{key} not found")


@pytest.mark.parametrize("path", ALL_LOCALE_FILES, ids=lambda p: p.name)
def test_no_locale_defines_the_same_key_twice(path: Path):
    """A repeated sibling key is silently dropped by the loader.

    The failure mode is not a crash: the catalog keeps working with whichever
    definition comes last, so editing the earlier one looks like a no-op. That
    is why this asserts on the issue map instead of on "the file still loads".
    """
    duplicates = _duplicate_keys(path.read_text(encoding="utf-8"))

    assert duplicates == {}, (
        f"{path.name} defines the same key more than once "
        f"(only the last definition survives): {duplicates}"
    )


@pytest.mark.parametrize("lang", MAINTAINED_LOCALES)
def test_the_maintained_locales_still_define_hardline_blocked_once(lang: str):
    """Pin the object of the de-duplication, not just its absence.

    `test_no_locale_defines_the_same_key_twice` is equally satisfied by deleting
    *both* copies — and then `t("approval.hardline_blocked")` silently falls back
    to the bare key. So the key is pinned here in both maintained catalogs, and
    so is *which* copy was the right one to keep: the consumer is
    `tools/approval.py::_hardline_block_result`, which returns a tool-result
    dict, so the definition must sit in the block-*result* section (the one whose
    heading names it), below the block-message section where the dropped copy
    was.
    """
    text = (LOCALES_DIR / f"{lang}.yaml").read_text(encoding="utf-8")

    assert text.count("hardline_blocked:") == 1, f"{lang}.yaml must define it exactly once"
    assert yaml.safe_load(text)["approval"]["hardline_blocked"]

    heading = _SECTION_HEADINGS[lang]
    # Anchor to a heading line, not to any mention: the note we left in the
    # block-message section names the block-result section on purpose, so a bare
    # substring search matches twice.
    heading_re = re.compile(r"^#\s*" + re.escape(heading))
    heading_lines = [
        i for i, line in enumerate(text.splitlines(), 1) if heading_re.match(line.strip())
    ]
    assert len(heading_lines) == 1, f"{lang}.yaml: section heading {heading!r} not unique"
    assert _key_line(text, "approval", "hardline_blocked") > heading_lines[0], (
        f"{lang}.yaml: approval.hardline_blocked must stay in the block-result section"
    )


def test_safe_load_would_not_notice_a_duplicate():
    """The instrument is load-bearing: `safe_load` erases the evidence.

    A future reader may be tempted to rewrite the duplicate check on top of
    `safe_load` + a flatten helper (the shape `tests/agent/test_i18n.py` uses).
    That rewrite would be vacuously green, so the difference is pinned here: on
    the same input, `compose` sees two definitions and `safe_load` sees one.
    """
    duplicated = 'root:\n  k: "first"\n  k: "second"\n'

    loaded = yaml.safe_load(duplicated)
    assert loaded == {"root": {"k": "second"}}  # first definition is gone
    assert list(_mappings(yaml.compose(duplicated)))  # nodes are intact
    assert _duplicate_keys(duplicated) == {"k": [2, 3]}
