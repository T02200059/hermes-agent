"""Tests for owner output_guard follow-up fixes (P2-2 / P2-3 / T2-10)."""

from __future__ import annotations

import importlib.util
import itertools
import random
import re
import time
from pathlib import Path


def _load_output_guard():
    path = (
        Path(__file__).resolve().parents[2]
        / "owner"
        / "owner-extensions"
        / "output_guard"
        / "__init__.py"
    )
    spec = importlib.util.spec_from_file_location("owner_output_guard", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


og = _load_output_guard()


def test_comp_ratio_uses_byte_denominator_for_chinese():
    text = "复读" * 2000
    sig = og.analyze(text)
    encoded = text.encode("utf-8")
    import zlib

    expected = len(zlib.compress(encoded)) / len(encoded)
    assert abs(sig["comp_ratio"] - expected) < 1e-9


def test_mojibake_keeps_first_paragraph_only():
    first = "正常首段"
    rest = ("\ufffd" * 80) + "\n\n" + ("乱码段落\ufffd\n\n" * 20)
    text = first + "\n\n" + rest
    out = og._on_transform_llm_output(text, session_id="s", model="m")
    assert out is not None
    assert out.startswith(first)
    assert "已保留首段" in out
    assert rest.strip() not in out


def test_single_newline_repeat_is_hard_truncated():
    line = "确认就推。默认不推 upstream。需要就说一声。\n"
    text = line * 8000  # well over 50k, no blank-line paragraph breaks
    assert "\n\n" not in text
    out = og._on_transform_llm_output(text, session_id="s", model="m")
    assert out is not None
    body, _sep, note = out.partition("\n\n---\n")
    assert len(body) <= og._MAX_CHARS
    assert "output-guard" in note


# ---------------------------------------------------------------------------
# T2-10：word_repeat 判据从 O(n²) 正则改为线性扫描
# ---------------------------------------------------------------------------
# 被替换掉的原判据。它只在这里作**等价性 oracle**，模块内已不再使用。
_ORACLE_RE = re.compile(r"(\S+)( \1){5,}")


def _oracle_start(text: str):
    m = _ORACLE_RE.search(text)
    return None if m is None else m.start()


def test_linear_scan_matches_the_regex_oracle():
    """线性实现必须与原正则**逐例等价** —— 命中与否、以及最左匹配起点都相同。

    该判定位于每轮生成收尾的同步阻塞链上（`_persist_session` 之前），换实现是为
    了拿掉二次回溯，**不是为了改判定语义**。故以原正则作 oracle 做差分测试：
    任何语义漂移都会在这里红，而不是等到线上漏判/误判才发现。
    """
    checked = 0

    # 1) 穷举全部短串：覆盖 run 边界（空格 / Tab / 换行）、次数上下限、尾串形态
    for length in range(0, 7):
        for tup in itertools.product("ab \t\n", repeat=length):
            t = "".join(tup)
            assert og._find_word_repeat(t) == _oracle_start(t), repr(t)
            checked += 1

    # 2) 随机语料：含 NBSP 与全角空格等 Unicode 空白
    rng = random.Random(20260928)
    alpha = "ab \t\n\u00a0\u3000xy"
    for _ in range(2000):
        t = "".join(rng.choice(alpha) for _ in range(rng.randint(0, 60)))
        assert og._find_word_repeat(t) == _oracle_start(t), repr(t)
        checked += 1

    # 3) 结构化：token 长度跨过 64（有界量词方案正是在这里丢形态）、各种分隔符与前后缀
    for tlen in (1, 5, 63, 64, 65, 130):
        for reps in (4, 5, 6, 7):
            for sep in (" ", "  ", "\t"):
                for pre in ("", "Z", "Z" + "a" * (tlen // 2)):
                    # post="X" 让**末次出现成为更长 token 的前缀** —— 反向引用是字面串，
                    # 不要求其后也是空白；要求尾随边界是常见的实现错误，专门覆盖。
                    for post in ("", "X", "XX", " tail"):
                        tok = "a" * tlen
                        t = pre + tok + "".join(sep + tok for _ in range(reps - 1)) + post
                        assert og._find_word_repeat(t) == _oracle_start(t), repr(t)
                        checked += 1

    # 4) run 边界是**任意**空白：token 内部的 Tab / 换行 / NBSP 必须切断 run
    #    （只有 token 之间的分隔符才是单空格）。覆盖「拿 find(" ") 当边界」这类实现错误。
    for inner in ("\t", "\n", "\u00a0"):
        for reps in (5, 6, 7):
            tok = "a" + inner + "b"
            for sep in (" ", "  "):
                t = tok + "".join(sep + tok for _ in range(reps - 1))
                assert og._find_word_repeat(t) == _oracle_start(t), repr(t)
                checked += 1

    assert checked > 20000, checked


def test_word_repeat_does_not_block_the_turn_finalizer():
    """时间上界：50 000 字符（= _MAX_CHARS）的无空白长串必须在毫秒级完成。

    同一输入在旧正则上耗时 **30.4 秒**（无空白时 ``(\\S+)`` 的每次回溯都白跑），
    而判定点在 `_persist_session` 之前 ⇒ 落库、微压缩与最终投递全部被拖住。阈值
    取 1s：比线性实现（实测 0.26ms）宽约四个数量级、足以吸收 CI 抖动，同时任何
    退回二次方的改动（≈30s）都必然失败。
    """
    text = "中" * og._MAX_CHARS
    start = time.perf_counter()
    og._find_word_repeat(text)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"word_repeat 在 {og._MAX_CHARS} 字符上耗时 {elapsed:.2f}s"


def test_analyze_stays_fast_on_a_long_detailed_reply():
    """端到端：合法的长中文回复（verdict=ok）不能被护栏本身拖慢。"""
    text = "中" * og._MAX_CHARS
    start = time.perf_counter()
    sig = og.analyze(text)
    elapsed = time.perf_counter() - start
    assert sig["verdict"] == "ok"
    assert elapsed < 1.0, f"analyze 在 {og._MAX_CHARS} 字符上耗时 {elapsed:.2f}s"


def test_long_token_repeat_is_still_detected():
    """>64 字符的重复单元仍须命中。

    收窄到 ``(\\S{1,64})`` 是最省事的提速法，但会在这里漏判（实测 65 / 200 字符
    的 token 双双不命中，且 dirty_run 与 comp_belt 都不会补位）—— 本用例把该形态
    钉住，防止日后为省事又退回有界量词。
    """
    assert og._degenerate_scan(("y" * 200 + " ") * 8)["word_repeat"] == 1
    assert og._degenerate_scan(("y" * 65 + " ") * 8)["word_repeat"] == 1


def test_repeat_may_start_inside_a_token():
    """原正则允许从 token 中间起步（重复单元 = 该 token 的尾串），照旧保留。"""
    text = "Zabcde " + "abcde " * 5
    assert _ORACLE_RE.search(text) is not None  # 先自证 oracle 确实命中此形态
    sig = og._degenerate_scan(text)
    assert sig["word_repeat"] == 1
    assert sig["first_offense"] == 1  # 起点在 token 内部偏移 1 处，与正则 start() 一致


def test_separator_must_be_a_single_literal_space():
    """分隔符是字面单空格（原正则 `` \\1``）：Tab 与双空格均不命中。"""
    assert og._degenerate_scan("\t".join(["word"] * 8))["word_repeat"] == 0
    assert og._degenerate_scan("word  " * 8)["word_repeat"] == 0


def test_repeat_count_threshold_is_unchanged():
    """下限仍是 6 次（原正则的 1 + {5,}）：5 次不判、6 次判。"""
    assert og._degenerate_scan(" ".join(["word"] * 5))["word_repeat"] == 0
    assert og._degenerate_scan(" ".join(["word"] * 6))["word_repeat"] == 1


def test_the_quadratic_implementation_does_not_come_back():
    """无上界正则不回归，且「为什么不用它」留在代码旁（含 oracle 用例的指针）。"""
    assert not hasattr(og, "_WORD_REPEAT"), "无上界正则 `(\\S+)( \\1){5,}` 不得回归"
    assert "O(n²)" in og.__doc__
    assert "test_output_guard" in og.__doc__
