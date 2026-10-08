"""T2-20 A3 簇 7b-7 —— ``gateway/run_turn_runner.py`` 的进度行组装。

宿主 ``TurnRunner`` 未挂到 ``GatewayRunner`` 的 MRO 上，故直接驱动方法**本体**（规则 ⑪）。

本簇两类：
* **保我方（4 行）**：终端块表头与友好标签都走 **catalog 驱动**的助手
  （`agent.display.terminal_block_header_label()` / `compose_tool_label()`，上游 0 处），
  替代上游的「裸 `tool_name`」与「`get_tool_verb` + `tool_verb_connector` + preview **拼接**」。
  ⇒ 英文逐字不变（`terminal_block_header_label()` 在 en 返回裸 `terminal`），**其它语言才不同**
  （zh 表头 `运行命令`、标签 `正在搜索网页：…`）；且整句模板允许语言重排语序 —— 拼接式不行。
* **等价已落位（7 行）**：`_classify_edit_failure`（宿主 `_owner_action`）、`_last_edit_ts`
  （宿主由调用方统一打点）、clarify 超时停（宿主已完整落位，仅局部变量改名）⇒ 走登记，不在此处断言。

emoji 不属本簇：那是上游 `get_tool_emoji()` 的调用，值来自工具注册表/skin，故期望值按同一入口构造。
"""

from __future__ import annotations

import ast
import pathlib
from types import SimpleNamespace

import pytest

from gateway.run_turn_runner import TurnRunner

EN_HEADER = "terminal"          # en 下 `terminal_block_header_label()` 的原样返回
ZH_HEADER = "运行命令"           # zh 的本地化表头


def _emoji(tool: str) -> str:
    from agent.display import get_tool_emoji

    return get_tool_emoji(tool, default="⚙️")


class _Adapter:
    """`supports_code_blocks=False`：跳过终端块路径，便于单测友好标签。"""

    supports_code_blocks = False

    def format_tool_preview(self, prepared):
        return prepared.text


class _MdAdapter(_Adapter):
    """markdown 平台：终端块路径生效。"""

    supports_code_blocks = True


class _RunnerStub:
    def __init__(self, adapter):
        self._adapter = adapter

    def _delivery_adapter_for(self, source):
        return self._adapter


def _mk(*, consecutive=False, adapter=None):
    ctx = SimpleNamespace(
        last_was_terminal_block=[consecutive],
        source=SimpleNamespace(platform="telegram", chat_id="c1"),
        progress_mode="all",
    )
    return TurnRunner(_RunnerStub(adapter), ctx)


# ------------------------------------------------------------------ 终端块表头
class TestTerminalBlockHeader:

    @pytest.mark.parametrize("lang,header", [("en", EN_HEADER), ("zh", ZH_HEADER)])
    def test_header_uses_catalog_label(self, lang, header, monkeypatch):
        monkeypatch.setenv("HERMES_LANGUAGE", lang)
        full, short = _mk()._progress_terminal_blocks(
            _MdAdapter(), "terminal", {"command": "ls -la"}, "💻")
        assert full == f"💻 {header}\n```\nls -la\n```"
        assert short == f"💻 {header}\n```\nls -la\n```"

    @pytest.mark.parametrize("lang", ["en", "zh"])
    def test_consecutive_calls_drop_the_header(self, lang, monkeypatch):
        monkeypatch.setenv("HERMES_LANGUAGE", lang)
        full, _short = _mk(consecutive=True)._progress_terminal_blocks(
            _MdAdapter(), "terminal", {"command": "ls"}, "💻")
        assert full == "```\nls\n```"

    @pytest.mark.parametrize("lang,header", [("en", EN_HEADER), ("zh", "terminal")])
    def test_friendly_labels_off_falls_back_to_raw_tool_name(self, lang, header, monkeypatch):
        """关掉友好标签后，zh 也回到裸 `terminal`（与上游一致）。"""
        from agent import display as disp

        monkeypatch.setenv("HERMES_LANGUAGE", lang)
        monkeypatch.setattr(disp, "_friendly_tool_labels", False, raising=False)
        full, _short = _mk()._progress_terminal_blocks(
            _MdAdapter(), "terminal", {"command": "ls"}, "💻")
        assert full == f"💻 {header}\n```\nls\n```"

    def test_non_terminal_tool_returns_none(self, monkeypatch):
        monkeypatch.setenv("HERMES_LANGUAGE", "en")
        assert _mk()._progress_terminal_blocks(
            _MdAdapter(), "read_file", {"path": "x"}, "📖") == (None, None)

    def test_missing_command_returns_none(self, monkeypatch):
        monkeypatch.setenv("HERMES_LANGUAGE", "en")
        assert _mk()._progress_terminal_blocks(_MdAdapter(), "terminal", {}, "💻") == (None, None)


# ------------------------------------------------------------------ 友好标签
class TestFriendlyLabel:

    @pytest.mark.parametrize("lang,label", [
        ("en", "Searching the web for cats"),
        ("zh", "正在搜索网页：cats"),
    ])
    def test_curated_tool_uses_whole_sentence_template(self, lang, label, monkeypatch):
        monkeypatch.setenv("HERMES_LANGUAGE", lang)
        out = _mk(adapter=_Adapter())._progress_build_message(
            "web_search", "cats", {"query": "cats"})
        assert out == f"{_emoji('web_search')} {label}"

    def test_language_can_reorder_words(self, monkeypatch):
        """整句模板允许重排语序 —— 这正是不能用「verb+connector+preview」拼接的原因。"""
        monkeypatch.setenv("HERMES_LANGUAGE", "zh")
        zh = _mk(adapter=_Adapter())._progress_build_message(
            "web_search", "cats", {"query": "cats"})
        monkeypatch.setenv("HERMES_LANGUAGE", "en")
        en = _mk(adapter=_Adapter())._progress_build_message(
            "web_search", "cats", {"query": "cats"})
        assert zh != en and "：" in zh and "for" in en

    @pytest.mark.parametrize("lang", ["en", "zh"])
    def test_uncurated_tool_falls_back_to_raw_form(self, lang, monkeypatch):
        monkeypatch.setenv("HERMES_LANGUAGE", lang)
        out = _mk(adapter=_Adapter())._progress_build_message(
            "my_plugin_tool", "cats", {"q": "cats"})
        assert out == f'{_emoji("my_plugin_tool")} my_plugin_tool: "cats"'

    @pytest.mark.parametrize("lang", ["en", "zh"])
    def test_friendly_labels_off_falls_back(self, lang, monkeypatch):
        from agent import display as disp

        monkeypatch.setenv("HERMES_LANGUAGE", lang)
        monkeypatch.setattr(disp, "_friendly_tool_labels", False, raising=False)
        out = _mk(adapter=_Adapter())._progress_build_message(
            "web_search", "cats", {"query": "cats"})
        assert out == f'{_emoji("web_search")} web_search: "cats"'

    def test_no_preview_yields_ellipsis_form(self, monkeypatch):
        monkeypatch.setenv("HERMES_LANGUAGE", "en")
        out = _mk(adapter=_Adapter())._progress_build_message("web_search", None, {})
        assert out == f"{_emoji('web_search')} web_search..."


# ------------------------------------------------------------------ 结构：拼接路径已不再被本文件调用
class TestConnectorPathRetired:

    def test_no_composition_helpers_called(self):
        """**AST 判「调用」，不是字符串判存在** —— 本簇的注释里就会提到这三个名字。"""
        src = pathlib.Path("gateway/run_turn_runner.py").read_text(encoding="utf-8")
        retired = {"get_tool_verb", "tool_verb_connector", "verb_drops_preview"}
        tree = ast.parse(src)
        used = {n.func.id for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        used |= {a.name for n in ast.walk(tree)
                 if isinstance(n, ast.ImportFrom) for a in n.names}
        assert not (retired & used), retired & used

    def test_catalog_helpers_are_used(self):
        src = pathlib.Path("gateway/run_turn_runner.py").read_text(encoding="utf-8")
        assert "terminal_block_header_label()" in src
        assert "compose_tool_label(tool_name, preview)" in src
