"""T2-20 A3 簇 7a —— ``gateway/run_turn.py::_format_session_info`` 的 i18n 重放。

宿主 ``GatewayTurnMixin`` 目前**未挂到** ``GatewayRunner`` 的 MRO 上（``run.py`` 单体里还有
一份同名实现继续对外服务），所以这里直接驱动 mixin 的方法体：断言的对象是**行为**
（渲染出来的会话信息块），不是源码文本。

英文侧必须与上游的硬编码英文**逐字相同**；中文侧必须真本地化，且**逐调用**解析语言
（模块级常量会把文案与语言一起冻结在 import 时刻，这正是本簇要防的回归）。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from gateway.run import _GatewayModelContext
from gateway.run_turn import GatewayTurnMixin

CN_MODEL = "anthropic/claude-opus-4.6"


class _Runner(GatewayTurnMixin):
    """最小的 mixin 宿主：``_format_session_info`` 不依赖任何实例状态。"""


def _ctx(
    *,
    model: str = CN_MODEL,
    provider: str = "openrouter",
    base_url: str = "",
    context_length: int = 262_144,
    context_source: str = "config",
) -> _GatewayModelContext:
    return _GatewayModelContext(
        model=model,
        provider=provider,
        base_url=base_url,
        context_length=context_length,
        context_source=context_source,
    )


def _info(ctx: _GatewayModelContext) -> str:
    with patch("gateway.run._resolve_gateway_model_context", return_value=ctx):
        return _Runner()._format_session_info()


def _moa_patches(aggregator: dict | None, preset: str):
    """Patch the two in-body imports the moa branch performs."""
    from hermes_cli import config as cfg_mod
    from hermes_cli import moa_config as moa_mod

    presets = {preset: {"aggregator": aggregator}} if aggregator else {}
    stack = [
        patch.object(cfg_mod, "load_config", return_value={"moa": {}}),
        patch.object(moa_mod, "normalize_moa_config", return_value={"presets": presets}),
    ]
    return stack


class TestEnglishVerbatim:
    """英文渲染必须与上游硬编码英文逐字一致（否则换码就是把英文改了）。"""

    def test_base_block(self, monkeypatch):
        monkeypatch.setenv("HERMES_LANGUAGE", "en")
        assert _info(_ctx()) == (
            f"◆ Model: `{CN_MODEL}`\n"
            "◆ Provider: openrouter\n"
            "◆ Context: 262K tokens (config)"
        )

    def test_provider_falls_back_to_openrouter(self, monkeypatch):
        monkeypatch.setenv("HERMES_LANGUAGE", "en")
        assert "◆ Provider: openrouter" in _info(_ctx(provider=""))

    def test_context_source_default_keeps_full_hint(self, monkeypatch):
        monkeypatch.setenv("HERMES_LANGUAGE", "en")
        out = _info(_ctx(context_source="default"))
        assert (
            "◆ Context: 262K tokens (default — set model.context_length in config to override)"
            in out
        )

    def test_context_source_unknown_renders_detected(self, monkeypatch):
        monkeypatch.setenv("HERMES_LANGUAGE", "en")
        assert "◆ Context: 262K tokens (detected)" in _info(_ctx(context_source="detected-by-probe"))

    def test_million_scale_display(self, monkeypatch):
        monkeypatch.setenv("HERMES_LANGUAGE", "en")
        assert "◆ Context: 1.0M tokens (config)" in _info(_ctx(context_length=1_048_576))

    def test_endpoint_branch(self, monkeypatch):
        monkeypatch.setenv("HERMES_LANGUAGE", "en")
        url = "http://127.0.0.1:8080/v1"
        assert f"◆ Endpoint: {url}" in _info(_ctx(base_url=url, provider="custom"))

    def test_public_endpoint_is_not_shown(self, monkeypatch):
        monkeypatch.setenv("HERMES_LANGUAGE", "en")
        assert "◆ Endpoint" not in _info(_ctx(base_url="https://openrouter.ai/api/v1"))

    def test_moa_acting_model_line(self, monkeypatch):
        monkeypatch.setenv("HERMES_LANGUAGE", "en")
        stack = _moa_patches({"provider": "openai", "model": "gpt-5"}, "mix-a")
        with stack[0], stack[1]:
            out = _info(_ctx(model="mix-a", provider="moa"))
        assert "◆ Acting model (billed for the run): openai:gpt-5" in out


class TestZhLocalization:

    def test_base_block_localized(self, monkeypatch):
        monkeypatch.setenv("HERMES_LANGUAGE", "zh")
        out = _info(_ctx())
        assert out == (
            f"◆ 模型：`{CN_MODEL}`\n"
            "◆ 提供方：openrouter\n"
            "◆ 上下文：262K tokens（配置）"
        )

    def test_chinese_differs_from_english(self, monkeypatch):
        """「没有残留占位符」这类断言在英文串上恒真 —— 必须显式比不等于英文。"""
        monkeypatch.setenv("HERMES_LANGUAGE", "en")
        en = _info(_ctx())
        monkeypatch.setenv("HERMES_LANGUAGE", "zh")
        zh = _info(_ctx())
        assert zh != en
        assert "◆ Model:" not in zh and "◆ Provider:" not in zh and "◆ Context:" not in zh

    def test_language_is_resolved_per_call_not_at_import(self, monkeypatch):
        """模块级常量会把语言冻结在 import 时刻；同一进程内切换必须立刻生效。"""
        monkeypatch.setenv("HERMES_LANGUAGE", "en")
        assert "◆ Model:" in _info(_ctx())
        monkeypatch.setenv("HERMES_LANGUAGE", "zh")
        assert "◆ 模型：" in _info(_ctx())

    def test_context_source_labels_localized(self, monkeypatch):
        monkeypatch.setenv("HERMES_LANGUAGE", "zh")
        assert "（检测）" in _info(_ctx(context_source="probed"))
        assert "（默认 — 在 config 中设置 model.context_length 可覆盖）" in _info(
            _ctx(context_source="default")
        )

    def test_moa_acting_model_line_localized(self, monkeypatch):
        monkeypatch.setenv("HERMES_LANGUAGE", "zh")
        stack = _moa_patches({"provider": "openai", "model": "gpt-5"}, "mix-a")
        with stack[0], stack[1]:
            out = _info(_ctx(model="mix-a", provider="moa"))
        assert "◆ 实际调用模型（本次计费对象）：openai:gpt-5" in out
        assert "Acting model" not in out

    def test_endpoint_line_localized(self, monkeypatch):
        monkeypatch.setenv("HERMES_LANGUAGE", "zh")
        url = "http://127.0.0.1:8080/v1"
        out = _info(_ctx(base_url=url, provider="custom"))
        assert f"◆ 端点：{url}" in out
        assert "◆ Endpoint:" not in out


class TestCatalogHygiene:

    @pytest.mark.parametrize("lang", ["en", "zh"])
    def test_no_unresolved_placeholder_leaks(self, lang, monkeypatch):
        monkeypatch.setenv("HERMES_LANGUAGE", lang)
        stack = _moa_patches({"provider": "openai", "model": "gpt-5"}, "mix-a")
        with stack[0], stack[1]:
            out = _info(_ctx(model="mix-a", provider="moa", base_url="http://localhost:1/v1"))
        assert "{" not in out and "}" not in out

    @pytest.mark.parametrize("lang", ["en", "zh"])
    def test_no_bare_key_path_leaks(self, lang, monkeypatch):
        """``t()`` 在键缺失时返回键路径本身 —— 那是最难看的失败形态。"""
        monkeypatch.setenv("HERMES_LANGUAGE", lang)
        out = _info(_ctx())
        assert "gateway.model." not in out
