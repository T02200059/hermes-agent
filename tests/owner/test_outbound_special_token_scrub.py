"""Tests for owner outbound BOS/EOS scrub."""

from __future__ import annotations

import importlib

import pytest

BOS = "<｜begin▁of▁sentence｜>"
EOS = "<｜end▁of▁sentence｜>"


@pytest.fixture()
def scrub():
    mod = importlib.import_module("owner.outbound_special_token_scrub")
    return mod.scrub_outbound_text


def test_none_and_empty(scrub):
    assert scrub(None) == ""
    assert scrub("") == ""


def test_untouched_normal_prose(scrub):
    text = "构建通过，准备提交。"
    assert scrub(text) == text


def test_pure_bos_becomes_empty(scrub):
    assert scrub(BOS) == ""
    assert scrub(f"  {BOS}\n") == ""


def test_pure_eos_becomes_empty(scrub):
    assert scrub(EOS) == ""


def test_bos_prefix_stripped_rest_kept(scrub):
    assert scrub(f"{BOS}hello") == "hello"
    assert scrub(f"{BOS}X") == "X"


def test_bos_and_eos_both_stripped(scrub):
    assert scrub(f"{BOS}mid{EOS}") == "mid"


def test_non_string_coerced(scrub):
    assert scrub(123) == "123"


def test_sanitize_gateway_strips_bos_on_chat_surface():
    from gateway.run import _sanitize_gateway_final_response

    assert _sanitize_gateway_final_response("feishu", BOS) == ""
    assert _sanitize_gateway_final_response("feishu", f"{BOS}ok") == "ok"
    # local/raw surfaces still pass through existing sanitize early-return
    # before owner scrub — verify chat surface path above is the contract.
