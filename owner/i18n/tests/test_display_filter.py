"""[owner] 展示层翻译过滤器的用例（T1-4）。

覆盖三组性质：

1. **功能**：精确匹配、模板匹配、未命中降级、逐行模式、缓存。
2. **安全**：只做整串匹配（不改子串）、模板静态片段过短时拒绝编译、占位符
   内容原样保留、语言为 en 时恒等、catalog 缺失时不崩。
3. **覆盖不变量**：对 ``locales/en.yaml`` 的每一个键，过滤器作用在英文原文
   上必须得到 ``locales/zh.yaml`` 的译文（歧义项除外）——这条把「过滤器与
   catalog 不同步」变成会失败的断言。

另有一条 AST 断言：官方**检测层**模块不得导入本过滤器。理由见 T1-1——
把展示用译文写进机器可读的返回值、而消费方按英文匹配，会击穿逻辑；
本过滤器的适用边界是展示面，不能渗进判定层。
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from owner.i18n import display_filter as df


@pytest.fixture(autouse=True)
def _clean_cache():
    df.clear_cache()
    yield
    df.clear_cache()


# ---------------------------------------------------------------------------
# 1. 功能
# ---------------------------------------------------------------------------


def test_exact_match_translates_known_string():
    en_catalog = df._load_catalog("en")
    zh_catalog = df._load_catalog("zh")
    if not en_catalog or not zh_catalog:
        pytest.skip("catalog 不可用")
    # 取一条无占位符、无歧义的键
    for key, en_text in en_catalog.items():
        zh_text = zh_catalog.get(key)
        if not zh_text or zh_text == en_text or "{" in en_text:
            continue
        assert df.translate(en_text, "zh") == zh_text, key
        return
    pytest.skip("找不到合适的样例键")


def test_unmatched_string_passes_through_unchanged():
    probe = "A string that is definitely not in any catalog :: 9f3c1a"
    assert df.translate(probe, "zh") == probe


def test_english_language_is_identity():
    en_catalog = df._load_catalog("en")
    if not en_catalog:
        pytest.skip("catalog 不可用")
    for en_text in list(en_catalog.values())[:50]:
        assert df.translate(en_text, "en") == en_text


def test_non_string_and_empty_inputs_are_safe():
    assert df.translate("", "zh") == ""
    assert df.translate(None, "zh") is None  # type: ignore[arg-type]


def _sample_template_keys(limit: int = 40) -> list[tuple[str, str, str]]:
    """取一批「含占位符且骨架足够长」的 (key, en, zh) 样例。"""
    en_catalog = df._load_catalog("en")
    zh_catalog = df._load_catalog("zh")
    out: list[tuple[str, str, str]] = []
    for key, en_text in en_catalog.items():
        zh_text = zh_catalog.get(key)
        if not zh_text or zh_text == en_text or "{" not in en_text:
            continue
        parts = df._template_parts(en_text)
        if not parts or sum(len(v) for k, v in parts if k == "lit") < df._MIN_TEMPLATE_LITERAL:
            continue
        out.append((key, en_text, zh_text))
        if len(out) >= limit:
            break
    return out


def test_template_preserves_captured_content_verbatim():
    """模板匹配只替换静态片段，占位符捕获到的内容必须原样保留。"""
    samples = _sample_template_keys(limit=1)
    if not samples:
        pytest.skip("catalog 不可用")
    _key, en_text, _zh_text = samples[0]

    names = list(dict.fromkeys(v for k, v in df._template_parts(en_text) if k == "field"))
    probes = {name: f"<PROBE-{i}-9f3c>" for i, name in enumerate(names)}
    filled = en_text.format(**probes)

    out = df.translate(filled, "zh")
    for name, probe in probes.items():
        assert probe in out, f"占位符 {name} 的捕获内容被改动了：{out!r}"


def test_translate_lines_translates_embedded_catalog_line():
    en_catalog = df._load_catalog("en")
    zh_catalog = df._load_catalog("zh")
    if not en_catalog or not zh_catalog:
        pytest.skip("catalog 不可用")

    sample_keys = [
        k
        for k, v in en_catalog.items()
        if zh_catalog.get(k) and zh_catalog[k] != v and "{" not in v and "\n" not in v
    ]
    if not sample_keys:
        pytest.skip("找不到合适的样例键")
    key = sample_keys[0]
    en_text, zh_text = en_catalog[key], zh_catalog[key]

    wrapped = f"Header line\n{en_text}\nFooter line"
    out = df.translate_lines(wrapped, "zh")
    assert zh_text in out
    assert "Header line" in out and "Footer line" in out


def test_translate_lines_ignores_very_long_payloads():
    payload = "\n".join(f"line {i}" for i in range(df._MAX_LINES + 10))
    assert df.translate_lines(payload, "zh") == payload


def test_cache_is_reused_and_clearable():
    df.build_map("zh")
    assert df.coverage("zh")["exact"] > 0
    df.clear_cache()
    # 清缓存后重建结果一致（保证无可变全局污染）
    assert df.coverage("zh")["exact"] > 0


# ---------------------------------------------------------------------------
# 2. 安全
# ---------------------------------------------------------------------------


def test_no_substring_replacement():
    """整串匹配：目录条目作为子串出现时不得被替换。

    T1-1 的教训——按子串改文本会改坏消息里嵌着的命令与路径。
    """
    en_catalog = df._load_catalog("en")
    if not en_catalog:
        pytest.skip("catalog 不可用")

    # 造一个「以某条 catalog 原文为子串」的命令串
    candidates = [v for v in en_catalog.values() if len(v) >= 4 and "{" not in v]
    if not candidates:
        pytest.skip("找不到合适的样例键")
    embedded = "sudo " + candidates[0].strip() + " /etc/hosts"

    out = df.translate(embedded, "zh")
    assert candidates[0].strip() in out, "子串被替换了，违反了整串匹配约束"


def test_all_placeholder_templates_are_rejected():
    """几乎全占位符的模板会退化成「匹配任意字符串」，必须拒绝。"""
    assert df._build_template("{a}", "x") is None
    assert df._build_template("{a}:", "x") is None
    assert df._build_template("{a} {b} ab", "x") is not None


def test_template_with_unknown_placeholder_in_translation_is_rejected():
    """译文引入了英文原文没有的占位符 → 无法安全还原。"""
    assert df._build_template("Hello {name}!", "{greeting} 你好") is None


def test_template_matching_does_not_span_lines():
    en_text = "Result: {value}"
    assert df._build_template(en_text, "结果：{value}") is not None
    assert df.translate("Result: a\nb", "zh") == "Result: a\nb"


def test_ambiguous_english_texts_are_not_translated():
    """同一英文原文对应多个中文键时默认不翻，除非显式消解。"""
    unresolved = df.unresolved_texts("zh")
    # 现网 catalog 存在歧义项；数量不做硬编码，但必须可枚举
    assert isinstance(unresolved, tuple)
    for en_text in unresolved:
        assert df.translate(en_text, "zh") == en_text


def test_missing_catalog_degrades_to_identity(monkeypatch):
    monkeypatch.setattr(df, "_load_catalog", lambda lang: {})
    df.clear_cache()
    assert df.translate("anything at all", "zh") == "anything at all"


def test_does_not_translate_machine_markers_in_message_body():
    """消息里嵌着的命令、路径、标识符必须保持原样。"""
    message = "Blocked command: git reset --hard HEAD~1 (rule: destructive-git)"
    out = df.translate(message, "zh")
    assert "git reset --hard HEAD~1" in out
    assert "destructive-git" in out


# ---------------------------------------------------------------------------
# 3. 覆盖不变量：过滤器与 catalog 必须同步
# ---------------------------------------------------------------------------


def test_exact_entries_match_catalog_for_every_key():
    """无占位符的键：过滤器结果必须与该键的中文译文逐字一致。

    这是最强的一条不变量——它把「过滤器与 catalog 不同步」变成会失败的断言。
    含占位符的键不在此列：模板之间存在重叠匹配，逐键严格相等不是成立的
    性质，由下一条按比例校验。
    """
    en_catalog = df._load_catalog("en")
    zh_catalog = df._load_catalog("zh")
    if not en_catalog or not zh_catalog:
        pytest.skip("catalog 不可用")

    unresolved = set(df.unresolved_texts("zh"))
    overrides = df._AMBIGUOUS_OVERRIDES
    mismatched: list[str] = []

    for key, en_text in en_catalog.items():
        zh_text = zh_catalog.get(key)
        if not zh_text or zh_text == en_text or "{" in en_text:
            continue
        if en_text in overrides:
            expected = overrides[en_text]
        elif en_text in unresolved:
            expected = en_text
        else:
            expected = zh_text
        got = df.translate(en_text, "zh")
        if got != expected:
            mismatched.append(f"{key}: expected={expected!r} got={got!r}")

    assert not mismatched, (
        f"{len(mismatched)} 个键的过滤器结果与 catalog 不一致（前 5 条）：\n  "
        + "\n  ".join(mismatched[:5])
    )


def test_template_entries_round_trip_at_high_rate():
    """含占位符的键：填充后翻译必须等于填充后的中文译文。

    允许少量不命中——模板存在重叠匹配，且骨架过短的模板会被安全护栏拒绝
    （现网仅 1 例）。这里把「拒绝/不命中」的比例钉死，防止后续改动把
    覆盖率悄悄拉低。
    """
    en_catalog = df._load_catalog("en")
    zh_catalog = df._load_catalog("zh")
    if not en_catalog or not zh_catalog:
        pytest.skip("catalog 不可用")

    total = 0
    ok = 0
    misses: list[str] = []

    for key, en_text in en_catalog.items():
        zh_text = zh_catalog.get(key)
        if not zh_text or zh_text == en_text or "{" not in en_text:
            continue
        parts = df._template_parts(en_text)
        if not parts:
            continue
        names = list(dict.fromkeys(v for k, v in parts if k == "field"))
        probes = {name: f"SENTINEL{i}X" for i, name in enumerate(names)}
        try:
            filled = en_text.format(**probes)
            expected = zh_text.format(**probes)
        except (KeyError, IndexError, ValueError):
            continue
        total += 1
        if df.translate(filled, "zh") == expected:
            ok += 1
        elif len(misses) < 5:
            misses.append(f"{key}: expected={expected!r} got={df.translate(filled, 'zh')!r}")

    assert total > 0, "找不到含占位符的键"
    assert ok / total >= 0.90, (
        f"模板往返成功率过低：{ok}/{total} = {ok / total:.1%}\n  " + "\n  ".join(misses)
    )


def test_coverage_is_non_trivial():
    stats = df.coverage("zh")
    # en/zh 各 1662 键；扣掉 en==zh（约 37）与歧义项后，精确项应在千级上下，
    # 模板项在数百级
    assert stats["exact"] >= 800, stats
    assert stats["templates"] >= 500, stats
    assert stats["unresolved"] <= 20, stats


def test_only_one_template_is_rejected_by_literal_guard():
    """骨架过短的模板被安全护栏拒绝——现网只应有 1 例（approval.scan_summary）。

    这条同时是护栏的回归保护：护栏被误删会让数量变成 0，误收紧会大幅上升。
    """
    en_catalog = df._load_catalog("en")
    zh_catalog = df._load_catalog("zh")
    if not en_catalog or not zh_catalog:
        pytest.skip("catalog 不可用")

    rejected: list[str] = []
    for key, en_text in en_catalog.items():
        zh_text = zh_catalog.get(key)
        if not zh_text or zh_text == en_text or "{" not in en_text:
            continue
        parts = df._template_parts(en_text)
        if not parts:
            continue
        literal_len = sum(len(v) for k, v in parts if k == "lit")
        if literal_len < df._MIN_TEMPLATE_LITERAL:
            rejected.append(key)

    assert rejected == ["approval.scan_summary"], rejected


# ---------------------------------------------------------------------------
# 4. 边界：不得渗进官方判定层
# ---------------------------------------------------------------------------


_FORBIDDEN_IMPORTERS = (
    "tools/approval.py",
    "owner/semantic_audit/detector.py",
)
"""检测层模块：这些文件按英文字面匹配返回值，绝不能让展示层翻译渗进来。"""


def test_detection_layer_does_not_import_display_filter():
    root = pathlib.Path(__file__).resolve().parents[3]
    offenders: list[str] = []

    for rel in _FORBIDDEN_IMPORTERS:
        path = root / rel
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if "owner.i18n" in alias.name:
                        offenders.append(f"{rel}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if "owner.i18n" in module:
                    offenders.append(f"{rel}: from {module} import …")

    assert not offenders, (
        "展示层翻译被导入到检测层，会重现 T1-1 的失败模式（译文击穿英文匹配）：\n  "
        + "\n  ".join(offenders)
    )
