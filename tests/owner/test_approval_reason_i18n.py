"""审批卡「标记原因」展示层中文：英文键不改，仅渲染时翻译。"""

from __future__ import annotations

from typing import Any, Iterator

import pytest

from agent import i18n
from gateway.platforms.base import BasePlatformAdapter
from owner.i18n.approval_reasons import (
    REASON_ZH,
    collect_static_detector_descriptions,
    translate_reason,
)


@pytest.fixture
def use_language(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    def _set(lang: str) -> None:
        monkeypatch.setenv("HERMES_LANGUAGE", lang)
        i18n.reset_language_cache()
        assert i18n.get_language() == lang

    yield _set
    i18n.reset_language_cache()


def _bare(cls):
    return object.__new__(cls)


class _DefaultAdapter(BasePlatformAdapter):
    async def connect(self):  # pragma: no cover
        pass

    async def disconnect(self):  # pragma: no cover
        pass

    async def get_chat_info(self, chat_id):  # pragma: no cover
        return {}

    async def send(self, *a, **k):  # pragma: no cover
        raise NotImplementedError


USER_EXAMPLES = {
    "shell execution via heredoc": "通过 heredoc 执行 shell",
    "script execution via heredoc": "通过 heredoc 执行脚本",
    "script execution via -e/-c flag": "通过 -e/-c 参数执行脚本",
    "shell command via -c/-lc flag": "通过 -c/-lc 参数执行 shell 命令",
    "pipe decoded content to shell (possible command obfuscation)": (
        "将解码内容管道传给 shell（可能是命令混淆）"
    ),
    "execute remote content via command substitution": "通过命令替换执行远程内容",
}


def test_user_examples_zh(use_language):
    use_language("zh")
    for en, zh in USER_EXAMPLES.items():
        assert translate_reason(en) == zh
        # terms preserved
        if "heredoc" in en:
            assert "heredoc" in zh
        if "shell" in en and "shell" in zh.lower() or "shell" in en:
            # Chinese sentence still contains the term shell where present in source intent
            if "shell" in en:
                assert "shell" in zh
        if "-e/-c" in en:
            assert "-e/-c" in zh
        if "-c/-lc" in en:
            assert "-c/-lc" in zh


def test_en_passthrough_even_when_table_has_entry(use_language):
    use_language("en")
    for en in USER_EXAMPLES:
        assert translate_reason(en) == en


def test_unknown_falls_back(use_language):
    use_language("zh")
    unknown = "totally unknown reason xyz"
    assert translate_reason(unknown) == unknown


def test_dynamic_arbitrary_program(use_language):
    use_language("zh")
    assert translate_reason("arbitrary program execution via rg --pre") == (
        "通过 rg --pre 执行任意程序"
    )
    assert translate_reason("arbitrary program execution via ag --pager") == (
        "通过 ag --pager 执行任意程序"
    )


def test_none_and_empty(use_language):
    use_language("zh")
    assert translate_reason(None) is None
    assert translate_reason("") == ""


def test_drift_static_descriptions_covered():
    static = collect_static_detector_descriptions()
    missing = static - set(REASON_ZH)
    assert not missing, (
        "上游新增未译的静态 description，请补 owner/i18n/approval_reasons.py::REASON_ZH:\n"
        + "\n".join(sorted(missing))
    )


def test_format_exec_approval_zh_reason(use_language, monkeypatch):
    use_language("zh")
    monkeypatch.setattr("gateway.platforms.base.approval_timeout_seconds", lambda: 90)
    text = _bare(_DefaultAdapter)._format_exec_approval(
        "cat <<EOF\necho hi\nEOF", "shell execution via heredoc"
    )
    assert "通过 heredoc 执行 shell" in text
    # reason_label still present (localized separately)
    from gateway.platforms.base_exec_approval import ea_reason_label_text

    label = ea_reason_label_text()
    assert label in text or f"{label}:" in text or "标记原因" in text


def test_format_exec_approval_en_unchanged(use_language, monkeypatch):
    use_language("en")
    monkeypatch.setattr("gateway.platforms.base.approval_timeout_seconds", lambda: 90)
    text = _bare(_DefaultAdapter)._format_exec_approval(
        "rm -rf /tmp/x", "shell execution via heredoc"
    )
    assert "shell execution via heredoc" in text
    assert "通过 heredoc" not in text


def test_fallback_formatter_glue_present():
    """Avoid importing gateway.run (home_io_guard); assert thin glue is wired."""
    from pathlib import Path

    src = Path("gateway/run.py").read_text(encoding="utf-8")
    assert "translate_reason" in src
    assert "_format_exec_approval_fallback" in src
    assert "owner/i18n/approval_reasons.py" in src or "owner.i18n.approval_reasons" in src


def test_prompt_description_field_stays_english_on_send(use_language):
    """ExecApprovalPrompt.description stays English; card text is translated."""
    import asyncio
    from typing import Any

    from gateway.config import Platform, PlatformConfig
    from gateway.platforms.base import ExecApprovalPrompt, SendResult

    use_language("zh")

    class _Capture(BasePlatformAdapter):
        def __init__(self):
            super().__init__(PlatformConfig(enabled=True), Platform.TELEGRAM)
            self.prompt = None

        async def connect(self, *, is_reconnect: bool = False) -> bool:
            return True

        async def disconnect(self) -> None:
            pass

        async def send(self, *a: Any, **k: Any) -> SendResult:
            return SendResult(success=True)

        async def get_chat_info(self, chat_id: str) -> dict[str, Any]:
            return {}

        async def _send_exec_approval_prompt(self, prompt: ExecApprovalPrompt) -> SendResult:
            self.prompt = prompt
            return SendResult(success=True, message_id="m1")

    adapter = _Capture()
    asyncio.run(
        adapter.send_exec_approval(
            "chat",
            "bash <<EOF\ntrue\nEOF",
            "sess",
            description="shell execution via heredoc",
        )
    )
    assert adapter.prompt is not None
    assert adapter.prompt.description == "shell execution via heredoc"
    assert "通过 heredoc 执行 shell" in adapter.prompt.text
