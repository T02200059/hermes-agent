"""T1-1 回归守卫：检测层返回契约必须是「机器可读的英文原文」。

背景（2026-09-28 月度审查 T1-1，P0）：
    一次 i18n 改造把 ``_translate_pattern_description()`` 塞进了
    ``detect_dangerous_command()`` / ``detect_hardline_command()``，
    使返回元组的第 3 元由英文变成中文。而消费方
    ``hermes_cli.approvals_suggest.is_unsafe_class()`` 用**英文正则**匹配该值，
    于是「破坏类永不建议」排除表被击穿：

        dangerous 类：78 条可排除 → 44 条失去排除资格
        hardline  类：12 条可排除 → 10 条失去排除资格

    后果链路（端到端已跑通）：被击穿的破坏类会生成宽 glob 建议
    （``sed *`` / ``git reset *`` / ``git clean *`` / ``mv app.py *``），
    经 ``apply_proposals`` **永久**写入 ``~/.hermes/config.yaml`` 的
    ``command_allowlist``，此后该类破坏命令免审批自动执行。

本文件守住四件事：
    1. 检测函数体内不得出现任何本地化调用（结构级断言，防重新引入）；
    2. 真实破坏命令在 zh / en 两种语言下的排除判定必须一致且为「排除」；
    3. 本地化只允许发生在展示层，且未命中时必须原样返回（优雅降级）；
    4. 把「若在检测层本地化会丢多少条」这一数量钉死，避免回归悄无声息。
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import agent.i18n as i18n
import tools.approval as approval
from hermes_cli.approvals_suggest import is_unsafe_class

REPO_ROOT = Path(__file__).resolve().parents[2]

# 报告 PoC 中的破坏命令 + 各类代表样本。每条都应命中 DANGEROUS_PATTERNS
# 且其类别必须被排除表拒绝。
_DESTRUCTIVE_COMMANDS = (
    "sed -i 's/x/y/' /etc/hosts",
    "git reset --hard HEAD~1",
    "git clean -fdx",
    "git branch -D feature",
    "mv app.py /etc/app.py",
    "rm -rf /",
    "chmod 777 /etc/passwd",
    "shutdown -h now",
    "dd if=/dev/zero of=/dev/sda",
)


def _set_language(monkeypatch: pytest.MonkeyPatch, lang: str) -> None:
    monkeypatch.setenv("HERMES_LANGUAGE", lang)
    i18n.reset_language_cache()
    assert i18n.get_language() == lang


def _detection_calls(func) -> list[str]:
    """返回 ``func`` 函数体内被调用的所有函数名（不含嵌套函数的内部调用）。"""
    tree = ast.parse(inspect.getsource(func).lstrip())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name):
                names.append(target.id)
            elif isinstance(target, ast.Attribute):
                names.append(target.attr)
    return names


# --------------------------------------------------------------------------
# 1. 结构级：检测层不得本地化
# --------------------------------------------------------------------------

_FORBIDDEN_IN_DETECTION = {
    "_translate_pattern_description",   # 直接本地化
    "_pattern_description_to_key",      # 本地化用的键推导
    "t",                                # i18n 查询入口
}


@pytest.mark.parametrize(
    "func_name",
    ["detect_dangerous_command", "detect_hardline_command", "_execution_flag_findings"],
)
def test_detection_layer_never_localizes(func_name: str) -> None:
    """检测函数体内不得出现本地化调用（AST 级，不受注释/docstring 干扰）。

    这是最廉价的防回归断言：只要有人在检测层重新引入本地化，本用例立刻失败，
    不必等到排除表被击穿 26 天后才被发现。
    """
    func = getattr(approval, func_name)
    called = set(_detection_calls(func))
    hit = called & _FORBIDDEN_IN_DETECTION
    assert not hit, (
        f"{func_name} 调用了 {sorted(hit)} —— 检测层返回的必须是机器可读的英文原文，"
        "本地化只允许发生在展示层（见 T1-1）。"
    )


# --------------------------------------------------------------------------
# 2. 行为级：真实破坏命令在 zh / en 下判定一致，且必须被排除
# --------------------------------------------------------------------------

def _fired_descriptions(command: str) -> list[str]:
    """返回该命令在 hardline / dangerous 两层检测上命中的全部描述。"""
    fired: list[str] = []
    is_hardline, hardline_desc = approval.detect_hardline_command(command)
    if is_hardline:
        fired.append(hardline_desc)
    is_dangerous, pattern_key, description = approval.detect_dangerous_command(command)
    if is_dangerous:
        assert pattern_key == description, (
            f"{command!r} 返回契约被破坏：pattern_key={pattern_key!r} "
            f"description={description!r}（第 2、3 元都必须是原始英文描述）"
        )
        fired.append(description)
    return fired


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("command", _DESTRUCTIVE_COMMANDS)
def test_destructive_classes_stay_excluded(command: str, lang: str, monkeypatch) -> None:
    _set_language(monkeypatch, lang)
    fired = _fired_descriptions(command)
    assert fired, f"{command!r} 未命中任何危险/硬线模式（{lang}）"
    for description in fired:
        assert is_unsafe_class(description), (
            f"{command!r}（{lang}）的类别 {description!r} 未进入"
            "「破坏类永不建议」排除表"
        )


def test_exclusion_verdict_is_locale_independent(monkeypatch) -> None:
    """对全部 DANGEROUS_PATTERNS 描述逐个比对 en / zh 判定，必须完全一致。"""
    verdicts: dict[str, list[bool]] = {}
    for lang in ("en", "zh"):
        _set_language(monkeypatch, lang)
        verdicts[lang] = [
            is_unsafe_class(desc) for _, desc in approval.DANGEROUS_PATTERNS
        ]
    assert verdicts["en"] == verdicts["zh"], (
        "英文/中文两种语言下排除表判定不一致 —— 说明有环节按语言改写了被匹配的值"
    )
    # 排除表本身要真的排掉东西（防止把断言写成恒真）
    assert sum(verdicts["en"]) > 0


def test_detection_output_equals_raw_pattern_string(monkeypatch) -> None:
    """检测输出的描述必须能在原始模式表里逐字命中（英文原文，非译文）。"""
    _set_language(monkeypatch, "zh")
    raw_dangerous = {desc for _, desc in approval.DANGEROUS_PATTERNS}
    raw_hardline = {desc for desc in (hp[1] for hp in approval.HARDLINE_PATTERNS)}
    for command in _DESTRUCTIVE_COMMANDS:
        for description in _fired_descriptions(command):
            assert description in raw_dangerous or description in raw_hardline, (
                f"{command!r} 返回了非原始模式串的描述：{description!r}"
            )


# --------------------------------------------------------------------------
# 3. 展示层：本地化只在这里发生，且未命中时原样返回
# --------------------------------------------------------------------------

def test_translation_is_display_only_and_falls_back(monkeypatch) -> None:
    _set_language(monkeypatch, "zh")
    zh = approval._translate_pattern_description("delete in root path")
    assert zh != "delete in root path", "已知键应能查到中文译文"

    # 未命中的键必须优雅降级为英文原文，不能漏字、不能串码、不能返回裸键路径
    unknown = "this pattern has no catalog entry at all"
    assert approval._translate_pattern_description(unknown) == unknown

    # 空描述不炸
    assert approval._translate_pattern_description("") == ""


def test_catalog_coverage_does_not_collapse(monkeypatch) -> None:
    """译文目录不能被清空——否则展示层静默退回英文，中文用户看不到任何翻译。"""
    _set_language(monkeypatch, "zh")
    total = len(approval.DANGEROUS_PATTERNS)
    covered = sum(
        1
        for _, desc in approval.DANGEROUS_PATTERNS
        if approval._translate_pattern_description(desc) != desc
    )
    # 当前覆盖率约 2/3（99 条中 66 条有译文）；设 60% 下限防目录塌陷。
    assert covered >= int(total * 0.6), f"危险模式译文覆盖率塌陷：{covered}/{total}"


# --------------------------------------------------------------------------
# 4. 把根因影响面钉死：若在检测层本地化，会丢多少条排除资格
# --------------------------------------------------------------------------

def test_localizing_detection_would_lose_exclusions(monkeypatch) -> None:
    """反事实断言：量化「检测层本地化」的破坏面。

    本用例的作用不是验证实现，而是**锁定根因规模**——一旦将来有人把本地化
    挪回检测层，上面第 2 节的用例会失败，而本用例给出失败的量级解释。
    若某天译文覆盖变化导致数字漂移，本用例会提示需要重新评估影响面。
    """
    _set_language(monkeypatch, "zh")

    dangerous_total = sum(1 for _, d in approval.DANGEROUS_PATTERNS if is_unsafe_class(d))
    hardline_total = sum(
        1 for d in (hp[1] for hp in approval.HARDLINE_PATTERNS) if is_unsafe_class(d)
    )
    assert dangerous_total == 78, f"dangerous 可排除基数变化：{dangerous_total}"
    assert hardline_total == 12, f"hardline 可排除基数变化：{hardline_total}"

    dangerous_lost = [
        d
        for _, d in approval.DANGEROUS_PATTERNS
        if is_unsafe_class(d) and not is_unsafe_class(approval._translate_pattern_description(d))
    ]
    hardline_lost = [
        d
        for d in (hp[1] for hp in approval.HARDLINE_PATTERNS)
        if is_unsafe_class(d)
        and not is_unsafe_class(approval._translate_pattern_description(d, kind="hardline"))
    ]

    assert len(dangerous_lost) == 44, f"dangerous 破坏面变化：{len(dangerous_lost)}"
    assert len(hardline_lost) == 10, f"hardline 破坏面变化：{len(hardline_lost)}"

    # 破坏面必须真实存在——否则说明译文缺失，第 3 节的降级测试失去意义
    assert dangerous_lost and hardline_lost
