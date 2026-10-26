"""C10 / T2-12：护栏文案英文留在代码，en 输出由代码驱动。

英文原文经 ``_localized(key, en_text)`` 渲染——活跃语言为 en 直接返回代码原文；
非 en 走目录、缺键回落代码原文。本文件守住漂移 / 键表一致 / 不绕过真源 / en|zh 行为。
"""

from __future__ import annotations

import ast
import pathlib
from typing import Any, Iterator

import pytest

import agent.i18n as i18n
import tools.file_tools_write_guards as ft

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
_GUARDED_PREFIXES = (
    "approval.protected_file_",
    "approval.ssh_config_",
    "approval.gate_why_",
)
_SENTINEL = "SENTINEL-MUST-NOT-REACH-THE-USER"


@pytest.fixture
def use_language(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    def _set(lang: str) -> None:
        monkeypatch.setenv("HERMES_LANGUAGE", lang)
        i18n.reset_language_cache()
        assert i18n.get_language() == lang

    yield _set
    i18n.reset_language_cache()


def _poison_catalogs(monkeypatch: pytest.MonkeyPatch) -> None:
    real = i18n._load_catalog

    def poisoned(lang: str, home: str | None = None) -> dict[str, str]:
        catalog = dict(real(lang, home))
        for key in _GUARDED_KEYS:
            catalog[key] = _SENTINEL
        return catalog

    monkeypatch.setattr(i18n, "_load_catalog", poisoned)


def _source() -> str:
    return pathlib.Path(ft.__file__).read_text(encoding="utf-8")


def _localized_keys_in_source() -> set[str]:
    keys: set[str] = set()
    for node in ast.walk(ast.parse(_source())):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name not in {"_localized", "_blocked"}:
            continue
        arg0 = node.args[0]
        if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
            keys.add(arg0.value)
    return keys


def test_en_catalog_matches_code_constants():
    catalog = i18n._load_catalog("en")
    for key, en_text in ft._GUARD_EN_TEXTS.items():
        assert key in catalog, f"locales/en.yaml 缺键 {key}"
        assert catalog[key] == en_text, f"en 目录与代码常量漂移: {key}"


def test_guard_en_texts_covers_localized_calls():
    used = {k for k in _localized_keys_in_source() if any(k.startswith(p) for p in _GUARDED_PREFIXES)}
    table = set(ft._GUARD_EN_TEXTS)
    missing = used - table
    unused = {k for k in table if any(k.startswith(p) for p in _GUARDED_PREFIXES)} - used
    # _blocked passes template_key + why_key as literals via helper — why keys appear via _blocked
    # Also template keys appear in _localized and _blocked. unused why keys still OK if via _blocked.
    assert not missing, f"_localized 用了常量表没有的键: {missing}"


def test_no_direct_t_for_guarded_keys():
    src = _source()
    tree = ast.parse(src)
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name != "t":
            continue
        if not node.args:
            continue
        arg0 = node.args[0]
        if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
            if any(arg0.value.startswith(p) for p in _GUARDED_PREFIXES):
                bad.append(arg0.value)
    assert not bad, f"护栏键不得直接 t(): {bad}"


def test_en_ignores_poisoned_catalog(use_language, monkeypatch):
    use_language("en")
    _poison_catalogs(monkeypatch)
    for key, en_text in ft._GUARD_EN_TEXTS.items():
        assert ft._localized(key, en_text) == en_text, key
        if "{targets}" in en_text and "{why}" in en_text:
            got = ft._localized(key, en_text, targets="SOUL.md", why="WHY")
            assert _SENTINEL not in got
            assert "SOUL.md" in got and "WHY" in got


def test_zh_uses_catalog(use_language, monkeypatch):
    use_language("zh")
    for key, en_text in ft._GUARD_EN_TEXTS.items():
        assert ft._localized(key, en_text) == i18n._load_catalog("zh")[key], key


def test_zh_missing_key_falls_back_to_en(use_language, monkeypatch):
    use_language("zh")
    real = i18n._load_catalog

    def missing(lang: str, home: str | None = None) -> dict[str, str]:
        catalog = dict(real(lang, home))
        for key in _GUARDED_KEYS:
            catalog.pop(key, None)
        return catalog

    monkeypatch.setattr(i18n, "_load_catalog", missing)
    for key, en_text in ft._GUARD_EN_TEXTS.items():
        assert ft._localized(key, en_text) == en_text, key


def test_end_to_end_protected_and_ssh_copy(use_language):
    use_language("en")
    en_pf = ft._blocked(
        "approval.protected_file_blocked", ft._PROTECTED_FILE_BLOCKED,
        targets="SOUL.md",
        why_key="approval.gate_why_denied_by_user",
        why_en=ft._WHY_DENIED_BY_USER,
    )
    assert "BLOCKED: write to protected" in en_pf
    assert "SOUL.md" in en_pf
    assert "was denied by the user." in en_pf

    use_language("zh")
    zh_pf = ft._blocked(
        "approval.protected_file_blocked", ft._PROTECTED_FILE_BLOCKED,
        targets="SOUL.md",
        why_key="approval.gate_why_denied_by_user",
        why_en=ft._WHY_DENIED_BY_USER,
    )
    assert "已拦截" in zh_pf
    assert "SOUL.md" in zh_pf
    assert "已被用户拒绝" in zh_pf
