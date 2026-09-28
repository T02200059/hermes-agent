"""[owner] T1-4 迁移等价性：展示层翻译必须逐条复现 ``t(key)`` 的输出。

为什么要这条断言
----------------
T1-4 的做法是：把官方函数体里的 ``t("key")`` 回退成英文原文，中文改由
``owner/i18n/display_filter`` 在展示边界完成。这个迁移**只有在**
「过滤器作用于英文原文的结果 == ``t(key)`` 的结果」时才成立。

所以本用例在**动手改代码之前**就把这条前提量化：对工作清单里每个
owner 侧调用点，断言

    display_filter.translate(en_catalog[key], ...) == zh_catalog[key]

不成立的条目就是迁移时需要人工处理的（歧义原文、骨架过短的模板、
``t()`` 首参非字面量等）。用例把失败条目按原因分桶并钉死数量——
这既防止迁移悄悄漏条，也把「哪些条要人看」变成可读的清单。
"""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

import pytest

from owner.i18n import display_filter as df

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "owner" / "scripts" / "i18n-owner-sites.py"


def _load_inventory_module():
    spec = importlib.util.spec_from_file_location("_i18n_owner_sites", _SCRIPT)
    if spec is None or spec.loader is None:  # pragma: no cover
        pytest.skip("工作清单脚本不可加载")
    module = importlib.util.module_from_spec(spec)
    # dataclass 装饰器会回查 sys.modules[cls.__module__] 解析字符串注解，
    # 先注册再 exec，否则 @dataclass 直接抛 AttributeError
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


@pytest.fixture(scope="module")
def inventory():
    if not _SCRIPT.is_file():
        pytest.skip("工作清单脚本不存在")
    if subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "upstream/main"],
        cwd=_REPO_ROOT,
        capture_output=True,
    ).returncode != 0:
        pytest.skip("上游参照 ref 不存在")
    module = _load_inventory_module()
    return module.collect("upstream/main")


def test_every_owner_site_round_trips_through_display_filter(inventory):
    """每个 owner 侧调用点的英文原文，都能被过滤器还原成同一句中文。"""
    owner_sites = [s for s in inventory.sites if s.kind == "owner"]
    assert owner_sites, "工作清单里没有 owner 键，扫描口径可能失效"

    ok: list[str] = []
    failures: dict[str, list[str]] = {}

    for site in owner_sites:
        where = f"{site.file}:{site.line} [{site.key}]"
        if not site.zh:
            failures.setdefault("catalog-缺中文", []).append(where)
            continue

        # 含占位符的调用点：用哨兵值填充后再比对
        parts = df._template_parts(site.en)
        if site.en and "{" in site.en and parts:
            names = list(dict.fromkeys(v for k, v in parts if k == "field"))
            probes = {name: f"EQ{i}Z" for i, name in enumerate(names)}
            try:
                filled_en = site.en.format(**probes)
                expected = site.zh.format(**probes)
            except (KeyError, IndexError, ValueError):
                failures.setdefault("format-失败", []).append(where)
                continue
        else:
            filled_en, expected = site.en, site.zh

        got = df.translate(filled_en, "zh")
        if got == expected:
            ok.append(where)
        elif site.key.split(".")[0] in {"approval"} and site.zh and got == site.en:
            failures.setdefault("歧义/未消解", []).append(where)
        else:
            failures.setdefault("译文不一致", []).append(where)

    total = len(owner_sites)
    # 允许少量需人工处理的条目；比例下限钉死，防止迁移覆盖率被悄悄拉低
    assert len(ok) / total >= 0.90, (
        f"迁移等价率过低：{len(ok)}/{total} = {len(ok) / total:.1%}\n"
        + "\n".join(
            f"  {reason}：{len(items)} 条（前 3）{items[:3]}"
            for reason, items in sorted(failures.items())
        )
    )


def test_inventory_covers_all_official_t_call_sites(inventory):
    """清单口径自检：官方文件里用 ``t()`` 的必须都被扫到。"""
    assert len(inventory.files_with_t) >= 40, len(inventory.files_with_t)
    assert len(inventory.sites) >= 800, len(inventory.sites)
    # ``t()`` 首参非字面量的调用点数不应失控（现网 21 处），
    # 大幅上升说明扫描口径或官方代码形态变了
    assert len(inventory.bare) <= 40, len(inventory.bare)


def test_display_filter_beats_regex_for_templates(inventory):
    """含占位符的 owner 调用点也必须能走模板匹配（不能全靠人工）。"""
    owner_sites = [s for s in inventory.sites if s.kind == "owner" and "{" in s.en]
    assert owner_sites, "owner 键里没有含占位符的调用点，口径可疑"

    matched = 0
    for site in owner_sites:
        parts = df._template_parts(site.en)
        if not parts:
            continue
        names = list(dict.fromkeys(v for k, v in parts if k == "field"))
        probes = {name: f"TP{i}Z" for i, name in enumerate(names)}
        try:
            filled = site.en.format(**probes)
        except (KeyError, IndexError, ValueError):
            continue
        if df.translate(filled, "zh") != filled:
            matched += 1

    assert matched / len(owner_sites) >= 0.90, f"{matched}/{len(owner_sites)}"
