"""模型选择护栏文案的 owner i18n（cost / data_policy / context_cache 三类）。

英文原文留在 ``hermes_cli/model_*_guard*.py`` 里并由代码驱动（en 输出不受目录影响）；
其他语言由 ``owner.i18n.localized`` 取 ``locales/<lang>.yaml`` 的
``gateway.model.guard.*``。本文件守住三件事：中文真的出来了、参数没被翻掉、
英文仍是上游原文。
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest

from agent import i18n
from hermes_cli import model_data_policy_guard as dp
from hermes_cli.model_selection_guards import SelectionContext, _context_cache_guard

_ZH_CONTEXT_TOKENS = 177_722
_ZH_CONTEXT_HEADER = "!!! 大上下文模型切换 !!!"
_EN_CONTEXT_HEADER = "!!! LARGE CONTEXT MODEL SWITCH !!!"


@pytest.fixture
def use_language(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    def _set(lang: str) -> None:
        monkeypatch.setenv("HERMES_LANGUAGE", lang)
        i18n.reset_language_cache()
        assert i18n.get_language() == lang

    yield _set
    i18n.reset_language_cache()


def _context_warning(target: str = "glm-5.3"):
    return _context_cache_guard(
        target, "zhipu", None, None, None,
        SelectionContext(context_tokens=_ZH_CONTEXT_TOKENS, current_model="deepseek-flash"))


class TestGuardCopyFollowsLanguage:
    def test_zh_context_guard_is_chinese_and_keeps_its_parameters(self, use_language):
        use_language("zh")
        warning = _context_warning("glm-5.3")
        assert warning is not None
        assert warning.title == "大上下文切换警告"
        assert warning.message.startswith(_ZH_CONTEXT_HEADER)
        assert "177,722" in warning.message and "glm-5.3" in warning.message
        assert "100,000" in warning.message
        assert "LARGE CONTEXT" not in warning.message

    def test_zh_data_policy_notice_is_chinese(self, use_language):
        use_language("zh")
        warning = dp.data_training_warning("llama-3.1-405b-contributor", provider="meta")
        assert warning is not None
        assert warning.message.startswith("!!! contributor 层级")
        assert "TRAINS ON YOUR DATA" not in warning.message

    def test_english_output_stays_the_upstream_wording(self, use_language):
        use_language("en")
        warning = _context_warning("glm-5.3")
        assert warning is not None
        assert warning.title == "Large Context Switch Warning"
        assert warning.message.startswith(_EN_CONTEXT_HEADER)
        assert f"~{_ZH_CONTEXT_TOKENS:,} tokens of context" in warning.message
        assert "Threshold: model.switch_context_confirm_tokens (currently 100,000; 0 disables" in (
            warning.message)


class TestGuardCatalog:
    def test_every_guard_key_in_english_carries_a_chinese_translation(self):
        en = i18n._load_catalog("en")
        zh = i18n._load_catalog("zh")
        keys = {k for k in en if k.startswith("gateway.model.guard.")}
        assert keys, "guard copy must live in the catalog"
        missing = sorted(k for k in keys if k not in zh)
        untranslated = sorted(k for k in keys if zh.get(k) == en[k])
        assert not missing, f"zh.yaml missing guard keys: {missing}"
        assert not untranslated, f"zh.yaml still English for: {untranslated}"
