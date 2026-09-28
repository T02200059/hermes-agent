"""T2-12 回归守卫：护栏文案的英文原文必须留在代码里，en 输出由代码驱动。

背景（2026-09-28 月度审查 T2-12，P1）：
    一次 i18n 改造把 ``tools/file_tools.py`` 两处写入护栏的文案整体搬进了
    ``locales/{en,zh}.yaml`` —— 4 个模板 + 8 个 why 片段，共 12 个目录键 ——
    代码里只剩 ``t("<key>")``。后果是**上游护栏文案改进永不传导**：上游改词
    会在代码里形成冲突并被人工解决，但运行时输出始终取自目录，冲突即使解决
    正确也换不来新文案；更糟的是模板里那句安全指令
    （``Do NOT retry it … via another path``）只存在于目录，上游删改它不会有
    任何代码痕迹。

现方案（T2-12）：英文原文逐字回归代码当唯一真源，经 ``_localized(key,
en_text, **kw)`` 渲染——活跃语言为 en 直接返回代码原文（上游改词自动传导），
非 en 走目录、缺键回落代码原文。

本文件守住七件事：
    1. 12 个目录键的英文条目与代码常量逐字一致（漂移守卫，纯本地比对，
       不需要上游 ref —— CI 只克隆单分支时也能跑）；
    2. 代码里出现的每个 ``_localized`` / ``_blocked`` 键都在代码常量表里，
       且表里没有无人引用的键（否则守卫可以被绕过）；
    3. 受守卫的键不得再以 ``t("<key>")`` 的形式直接取值（那样会绕过代码真源）；
    4. en 输出**不查目录**：把目录值换成哨兵，en 输出必须不变；
    5. 非 en 输出**取自目录**：同样的哨兵必须出现在输出里；
    6. 目录全缺时回落代码原文，且不抛异常；
    7. 两个护栏端到端文案在 en / zh 下与改造前逐字一致，且键↔常量配对正确。
"""

from __future__ import annotations

import ast
import json
import pathlib
from typing import Any, Iterator

import pytest

import agent.i18n as i18n
import tools.file_tools as ft

# 受守卫的 12 个键 = 4 个模板 + 8 个 why 片段。
_TEMPLATE_KEYS = (
    "approval.protected_file_request",
    "approval.protected_file_blocked",
    "approval.ssh_config_request",
    "approval.ssh_config_blocked",
)
_WHY_KEYS = tuple(
    k for k in ft._GUARD_EN_TEXTS if k.startswith("approval.gate_why_")
)
_GUARDED_KEYS = _TEMPLATE_KEYS + _WHY_KEYS

# 以这些前缀开头的键只允许经由 _localized / _blocked 取值。
_GUARDED_PREFIXES = (
    "approval.protected_file_",
    "approval.ssh_config_",
    "approval.gate_why_",
)

_SENTINEL = "SENTINEL-MUST-NOT-REACH-THE-USER"


@pytest.fixture
def use_language(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Switch the active language and clear the resolution/catalog caches."""

    def _set(lang: str) -> None:
        monkeypatch.setenv("HERMES_LANGUAGE", lang)
        i18n.reset_language_cache()
        assert i18n.get_language() == lang

    yield _set
    i18n.reset_language_cache()


def _poison_catalogs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace every guarded catalog entry with a sentinel value."""
    real = i18n._load_catalog

    def poisoned(lang: str) -> dict[str, str]:
        catalog = dict(real(lang))
        for key in _GUARDED_KEYS:
            catalog[key] = _SENTINEL
        return catalog

    monkeypatch.setattr(i18n, "_load_catalog", poisoned)


def _source() -> str:
    return pathlib.Path(ft.__file__).read_text(encoding="utf-8")


def _localized_keys_in_source() -> set[str]:
    """Guard keys passed as a literal first positional arg in the source."""
    keys: set[str] = set()
    for node in ast.walk(ast.parse(_source())):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name not in {"_localized", "_blocked"}:
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            keys.add(arg.value)
    return keys


def _t_style_keys_in_source() -> set[str]:
    """Guarded keys still read straight from the catalog via ``t(...)``."""
    keys: set[str] = set()
    for node in ast.walk(ast.parse(_source())):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name != "t":
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            if arg.value.startswith(_GUARDED_PREFIXES):
                keys.add(arg.value)
    return keys


# --------------------------------------------------------------- 1. 漂移守卫


def test_english_catalog_matches_the_code_originals() -> None:
    """en 目录必须与代码常量逐字一致，否则非 en 的回落路径会与 en 输出分叉。"""
    catalog = i18n._load_catalog("en")
    drifted = {
        key: {"catalog": catalog.get(key), "code": en_text}
        for key, en_text in ft._GUARD_EN_TEXTS.items()
        if catalog.get(key) != en_text
    }
    assert drifted == {}, (
        "locales/en.yaml 与 tools/file_tools.py 的英文原文已经分叉；"
        f"两边必须同改：{json.dumps(drifted, ensure_ascii=False, indent=2)}"
    )


def test_chinese_catalog_covers_every_guarded_key() -> None:
    """中文是主要使用语言：缺键会让用户看到英文原文。"""
    catalog = i18n._load_catalog("zh")
    missing = [key for key in _GUARDED_KEYS if key not in catalog]
    assert missing == [], f"locales/zh.yaml 缺少 {len(missing)} 个护栏键: {missing}"


# ------------------------------------------------- 2/3. 守卫不可绕过的结构断言


def test_code_table_and_call_sites_agree_exactly() -> None:
    used = _localized_keys_in_source()
    declared = set(ft._GUARD_EN_TEXTS)
    assert used == declared, (
        f"调用点出现但表里没有: {sorted(used - declared)}; "
        f"表里有但没人引用: {sorted(declared - used)}"
    )
    assert len(used) == 12, f"受守卫的键应为 12 个，实为 {len(used)}"


def test_guarded_keys_are_not_read_straight_from_the_catalog() -> None:
    straight = _t_style_keys_in_source()
    assert straight == set(), (
        "这些键又被 t(...) 直接取值了，会绕过代码里的英文真源："
        f"{sorted(straight)}"
    )


def test_call_sites_pair_each_key_with_its_table_constant() -> None:
    """每个调用点必须把键和**表中那个**常量配在一起。

    en 分支不查目录，所以「同一个常量配错键」在英文输出里完全看不出来
    （只有非 en 用户会中招）。这里按对象身份把常量表反查成「键 → 常量名」，
    再从源码 AST 逐调用点核对，属于纯机械检查、不依赖任何目录内容。
    """
    by_id = {
        id(value): name
        for name, value in vars(ft).items()
        if isinstance(value, str) and not name.startswith("__")
    }
    expected = {
        key: by_id.get(id(text), "") for key, text in ft._GUARD_EN_TEXTS.items()
    }
    unnamed = [k for k, name in expected.items() if not name]
    assert unnamed == [], (
        f"这些键在常量表里不是具名模块常量，无法核对配对：{unnamed}"
    )

    pairs: list[tuple[str, str]] = []
    for node in ast.walk(ast.parse(_source())):
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name not in {"_localized", "_blocked"}:
            continue
        key_arg, const_arg = node.args[0], node.args[1]
        if not (
            isinstance(key_arg, ast.Constant)
            and isinstance(key_arg.value, str)
            and isinstance(const_arg, ast.Name)
        ):
            continue
        pairs.append((key_arg.value, const_arg.id))

    assert len(pairs) == 16, f"应扫到 16 个 (键, 常量) 调用对，实为 {len(pairs)}"
    wrong = [(k, got, expected.get(k)) for k, got in pairs
             if expected.get(k) != got]
    assert wrong == [], f"调用点把键和常量配错了 (键, 实际, 应为): {wrong}"


# ----------------------------------------------------------- 4/5/6. 渲染路径


def test_english_rendering_ignores_the_catalog(
    monkeypatch: pytest.MonkeyPatch, use_language: Any
) -> None:
    """哨兵法：目录被污染后 en 输出必须不变 ⇒ 英文真源确实在代码里。"""
    use_language("en")
    _poison_catalogs(monkeypatch)
    for key, en_text in ft._GUARD_EN_TEXTS.items():
        assert ft._localized(key, en_text) == en_text, key
    for key in _TEMPLATE_KEYS:
        got = ft._localized(
            key, ft._GUARD_EN_TEXTS[key], targets="AGENTS.md", why="W"
        )
        assert got == ft._GUARD_EN_TEXTS[key].format(
            targets="AGENTS.md", why="W"
        ), key
        assert _SENTINEL not in got, key


def test_non_english_rendering_comes_from_the_catalog(
    monkeypatch: pytest.MonkeyPatch, use_language: Any
) -> None:
    use_language("zh")
    for key, en_text in ft._GUARD_EN_TEXTS.items():
        assert ft._localized(key, en_text) == i18n._load_catalog("zh")[key], key
    # 反向哨兵：证据表明非 en 路径**确实**查目录，而不是顺手也返回了原文。
    _poison_catalogs(monkeypatch)
    for key, en_text in ft._GUARD_EN_TEXTS.items():
        assert ft._localized(key, en_text) == _SENTINEL, key


def test_missing_catalog_falls_back_to_the_code_original(
    monkeypatch: pytest.MonkeyPatch, use_language: Any
) -> None:
    use_language("zh")
    monkeypatch.setattr(i18n, "_load_catalog", lambda lang: {})
    for key, en_text in ft._GUARD_EN_TEXTS.items():
        assert ft._localized(key, en_text) == en_text, key


# ------------------------------------------------------- 7. 两个护栏的端到端文案


def _run_ssh_gate(monkeypatch: pytest.MonkeyPatch, target: str) -> tuple[
    dict[str, Any], str | None
]:
    """Drive ``_check_approval_required_write`` and capture the gate kwargs."""
    import agent.file_safety as file_safety
    import tools.approval as approval

    seen: dict[str, Any] = {}

    def fake_gate(**kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return {"approved": False, "message": ""}

    monkeypatch.setattr(file_safety, "is_write_approval_required", lambda p: True)
    monkeypatch.setattr(approval, "_run_approval_gate", fake_gate)
    return seen, ft._check_approval_required_write([target])


def test_ssh_gate_text_is_unchanged_and_correctly_paired(
    monkeypatch: pytest.MonkeyPatch, use_language: Any
) -> None:
    target = "~/.ssh/config"
    use_language("en")
    seen, returned = _run_ssh_gate(monkeypatch, target)

    # 键↔常量配对：每个分支必须用自己那个 why 常量，不能混用。
    assert seen["description"] == ft._SSH_CONFIG_REQUEST.format(targets=target)
    assert seen["display_target"] == f"<write to {target}>"
    assert seen["cron_deny_message"] == ft._SSH_CONFIG_BLOCKED.format(
        targets=target, why=ft._WHY_CRON_DENIED
    )
    assert seen["single_query_deny_message"] == ft._SSH_CONFIG_BLOCKED.format(
        targets=target, why=ft._WHY_SINGLE_QUERY_DENIED
    )
    assert seen["no_human_block_message"] == ft._SSH_CONFIG_BLOCKED.format(
        targets=target, why=ft._WHY_NO_HUMAN
    )
    assert returned == ft._SSH_CONFIG_BLOCKED.format(
        targets=target, why=ft._WHY_DENIED
    )

    # 非 en 分支：不用目录重新推导期望值（那会变成同义反复 —— mutation 实测
    # 得不出结论）。改为断言「与目录无关、改坏就会挂」的语言一致性：
    # 三段文案必须互不相同（why 键配对正确且各自被本地化），且英文原文
    # （代码常量）一个字都不许漏进中文输出。
    use_language("zh")
    seen_zh, returned_zh = _run_ssh_gate(monkeypatch, target)
    assert seen_zh["description"] != ft._SSH_CONFIG_REQUEST.format(targets=target)
    for field, why_const in (
        ("cron_deny_message", ft._WHY_CRON_DENIED),
        ("single_query_deny_message", ft._WHY_SINGLE_QUERY_DENIED),
        ("no_human_block_message", ft._WHY_NO_HUMAN),
    ):
        value = seen_zh[field]
        assert why_const not in value, f"{field}: 英文 why 片段漏进了中文输出"
        assert value != ft._SSH_CONFIG_BLOCKED.format(
            targets=target, why=why_const
        ), f"{field}: 中文分支用了代码里的英文模板"
    assert len({
        seen_zh["cron_deny_message"],
        seen_zh["single_query_deny_message"],
        seen_zh["no_human_block_message"],
    }) == 3, "三个分支的文案塌成了同一条 —— why 键配对错了"
    assert ft._WHY_DENIED not in returned_zh


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_protected_gate_text_is_unchanged_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, use_language: Any, lang: str
) -> None:
    """无任何人工通道时走 fail-closed 分支：文案必须与改造前逐字一致。"""
    from tools.terminal_tool import set_approval_callback

    use_language(lang)
    monkeypatch.setattr(ft, "_protected_instruction_config", lambda: (True, []))
    set_approval_callback(None)
    try:
        res = json.loads(
            ft.write_file_tool(str(tmp_path / "AGENTS.md"), "injected")
        )
    finally:
        set_approval_callback(None)

    error = res.get("error")
    assert isinstance(error, str) and error, res
    expected = ft._PROTECTED_FILE_BLOCKED.format(
        targets="AGENTS.md", why=ft._WHY_NO_HUMAN
    )
    if lang == "en":
        # en 期望值完全由代码常量拼出：改常量、改配对、丢本地化都会挂。
        assert error == expected
    else:
        # 非 en 分支断言语言一致性（不用目录重推期望值，避免同义反复）。
        assert error != expected, "非 en 分支用了代码里的英文模板"
        assert ft._WHY_NO_HUMAN not in error, "英文 why 片段漏进了中文输出"
        assert "BLOCKED" not in error
    assert not (tmp_path / "AGENTS.md").exists()
