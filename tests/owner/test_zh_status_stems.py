"""T2-20 A3 簇 7b-8 —— 两条状态正则里 10 条 zh 词干的「词干 ↔ 真实渲染」对照。

## 为什么要有这个文件

`gateway/run.py` 的两条状态正则（`_TELEGRAM_NOISY_STATUS_RE` /
`_COMPRESSION_PROGRESS_STATUS_RE`）的**英文分支由模板常量派生**，于是
`display.language=zh` 时 emit 站点渲染的中文**匹配不上任何一条英文分支**：
噪声会漏进聊天、用户显式开启的压缩进度会被吞。我方为此追加了 10 条 zh 词干。

词干一旦与 catalog 走散就是**静默失效**（正则不报错，只是不再命中）。本文件把
「每一条词干 → 它本该命中的那条真实渲染」钉死，改词干/改译文任一侧都会红。

## 两类词干（实测区分，勿混）

* **承载类 5 条**：对应的 catalog 键**确有 emit 站点**（已 grep 核实），
  渲染取**真实发射函数**（`get_compaction_status()` 等），不是手写字面量。
* **前向兼容类 5 条**（`_COMPRESSION_PROGRESS_STATUS_RE` 的 zh 列表）：对应的
  `gateway.runtime.{pre_api_compression,preflight_compression,compressed_messages,
  compressed_tokens,context_too_large_compressing}` 目前**全仓零引用** —— 这些
  状态今天一律以**英文模板常量**发射（`agent/conversation_compression.py` 的
  `*_STATUS_TEMPLATE`）。故这 5 条 zh 分支当下不参与匹配，保留是为了上游一旦
  把这些发射点本地化即可生效。测试对它们只做「词干 ↔ catalog 渲染」一致性钉死。
"""

from __future__ import annotations

import re

import pytest

from agent.conversation_compression import (
    COMPACTION_STATUS,
    COMPACTION_STATUS_MARKER,
    get_compaction_status,
)
from agent.i18n import t
from gateway.run import (
    _COMPRESSION_PROGRESS_STATUS_RE,
    _TELEGRAM_NOISY_STATUS_RE,
)

ZH = "zh"


def _zh(key: str, **kwargs) -> str:
    return t(key, lang=ZH, **kwargs)


# ------------------------------------------------------------------ 承载类 5 条
# (词干原文, 真实渲染, 说明) —— 渲染一律走 emit 路径，不抄字面量。
BEARING = [
    (
        r"compacting\s+context\s+[—-]\s+(?:summarizing\s+earlier\s+conversation|正在总结)",
        lambda: get_compaction_status(),
        "gateway.runtime.compaction（en 半边 + zh 半边同处一条分支）",
    ),
    (
        r"会话已压缩\s*\d+\s*次",
        lambda: _zh("gateway.compress.repeated_warning", count=12),
        "gateway.compress.repeated_warning",
    ),
    (
        r"压缩摘要失败",
        lambda: _zh("gateway.compress.summary_marker", error="upstream error"),
        "gateway.compress.summary_marker 首句",
    ),
    (
        r"回退上下文标记",
        lambda: _zh("gateway.compress.summary_marker", error="upstream error"),
        "gateway.compress.summary_marker 尾句（en 分支只覆盖到首句）",
    ),
    (
        r"配置的压缩模型",
        lambda: _zh("gateway.compress.aux_failed", model="small", error="x"),
        "gateway.compress.aux_failed / gateway.aux_model_fallback 共用词头",
    ),
]

# ------------------------------------------------------------------ 前向兼容类 5 条
FORWARD = [
    (r"compacting\s+context\s+[—-]\s+正在总结",
     lambda: _zh("gateway.runtime.compaction", marker=COMPACTION_STATUS_MARKER),
     "gateway.runtime.compaction"),
    (r"预\s*API\s*压缩",
     lambda: _zh("gateway.runtime.pre_api_compression", tokens=123456),
     "gateway.runtime.pre_api_compression"),
    (r"预检压缩",
     lambda: _zh("gateway.runtime.preflight_compression", tokens=120000, threshold=100000),
     "gateway.runtime.preflight_compression"),
    (r"已压缩：",
     lambda: _zh("gateway.runtime.compressed_messages", before=30, after=12),
     "gateway.runtime.compressed_messages / compressed_tokens"),
    (r"上下文过大",
     lambda: _zh("gateway.runtime.context_too_large_compressing", tokens=250000,
                 current=1, total=3),
     "gateway.runtime.context_too_large_compressing"),
]


class TestZhStemsAreWired:
    """用**模块里那两条编译好的正则**去搜真实渲染 —— 证明词干确实接进了正则。

    语言必须显式钉住：`get_compaction_status()` 走的是**活动语言**（env > config），
    不钉的话会渲染英文，用例就变成在测英文分支（实测踩过：摘掉 zh 半边它照样绿）。
    """

    @pytest.fixture(autouse=True)
    def _zh_language(self, monkeypatch):
        monkeypatch.setenv("HERMES_LANGUAGE", ZH)

    @pytest.mark.parametrize("stem,render,what", BEARING, ids=lambda x: None)
    def test_bearing_stem_matches_noisy_regex(self, stem, render, what):
        text = render()
        assert _TELEGRAM_NOISY_STATUS_RE.search(text), f"{what}：{text!r} 未被噪声过滤命中"
        assert re.search(stem, text, re.IGNORECASE), f"{what}：词干单独也不命中"

    @pytest.mark.parametrize("stem,render,what", FORWARD, ids=lambda x: None)
    def test_forward_stem_matches_progress_regex(self, stem, render, what):
        text = render()
        assert _COMPRESSION_PROGRESS_STATUS_RE.search(text), f"{what}：{text!r} 未被进度门放行"
        assert re.search(stem, text, re.IGNORECASE), f"{what}：词干单独也不命中"

    def test_compaction_status_really_renders_chinese(self):
        """活动语言 = zh 时 `get_compaction_status()` 必须真的是中文（否则上面第一条是空测）。"""
        text = get_compaction_status()
        assert "正在总结" in text and "summarizing earlier conversation" not in text

    def test_aux_model_fallback_also_covered(self):
        """`gateway.aux_model_fallback` 是第二个 emit 站点，共用同一词头。"""
        text = _zh("gateway.aux_model_fallback", model="small", error="x")
        assert _TELEGRAM_NOISY_STATUS_RE.search(text)

    def test_compaction_zh_also_passes_the_progress_gate(self):
        """用户显式开启 `compression.progress_notices` 时，zh 压缩进度必须放行。"""
        assert _COMPRESSION_PROGRESS_STATUS_RE.search(get_compaction_status())


class TestEnglishSideUnchanged:
    """zh 词干不得挤掉英文分支：en 渲染仍走原分支。"""

    @pytest.fixture(autouse=True)
    def _en_language(self, monkeypatch):
        monkeypatch.setenv("HERMES_LANGUAGE", "en")

    def test_noisy_regex_still_matches_english(self):
        assert _TELEGRAM_NOISY_STATUS_RE.search(COMPACTION_STATUS)
        assert _TELEGRAM_NOISY_STATUS_RE.search(
            "⚠ Compression summary failed: upstream error. "
            "Inserted a fallback context marker."
        )
        assert _TELEGRAM_NOISY_STATUS_RE.search(
            "⚠️  Session compressed 12 times — accuracy may degrade. "
            "Consider /new to start fresh."
        )

    def test_progress_regex_still_matches_english_templates(self):
        from agent.conversation_compression import (
            PRE_API_COMPRESSION_STATUS_TEMPLATE,
            PREFLIGHT_COMPRESSION_STATUS_TEMPLATE,
        )

        assert _COMPRESSION_PROGRESS_STATUS_RE.search(
            PRE_API_COMPRESSION_STATUS_TEMPLATE.format(tokens=123456))
        assert _COMPRESSION_PROGRESS_STATUS_RE.search(
            PREFLIGHT_COMPRESSION_STATUS_TEMPLATE.format(tokens=120000, threshold=100000))

    def test_manual_compress_feedback_still_exempt(self):
        """手工 `/compress` 回执从不属于噪声（en/zh 两侧都不该被吞）。"""
        for text in ("Compressed: 30 → 12 messages",
                     "Compressed context: 30 → 12 messages"):
            assert not _TELEGRAM_NOISY_STATUS_RE.search(text), text


class TestStemAndCatalogAgree:
    """词干与 catalog 的绑定面：zh 渲染必须真的与 en 不同（否则词干是死的）。"""

    @pytest.mark.parametrize("key,kwargs", [
        ("gateway.runtime.compaction", {"marker": COMPACTION_STATUS_MARKER}),
        ("gateway.compress.repeated_warning", {"count": 3}),
        ("gateway.compress.summary_marker", {"error": "e"}),
        ("gateway.compress.aux_failed", {"model": "m", "error": "e"}),
        ("gateway.aux_model_fallback", {"model": "m", "error": "e"}),
        ("gateway.runtime.pre_api_compression", {"tokens": 1}),
        ("gateway.runtime.preflight_compression", {"tokens": 1, "threshold": 1}),
        ("gateway.runtime.compressed_messages", {"before": 1, "after": 1}),
        ("gateway.runtime.compressed_tokens", {"before_tokens": 1, "after_tokens": 1}),
        ("gateway.runtime.context_too_large_compressing",
         {"tokens": 1, "current": 1, "total": 1}),
    ])
    def test_zh_render_differs_from_en(self, key, kwargs):
        assert t(key, lang=ZH, **kwargs) != t(key, lang="en", **kwargs)
