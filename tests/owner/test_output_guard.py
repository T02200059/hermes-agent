"""Tests for owner output_guard follow-up fixes (P2-2 / P2-3)."""

from __future__ import annotations

import importlib.util
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
