"""T2-1 回归守卫：审批历史挖掘必须按**结构**判定「未被自由执行」。

背景（2026-09-28 月度审查 T2-1，P1）
=====================================
``hermes approvals suggest`` 把「危险命令 + 结果不是拦截标记」当作「用户
批准过」，据此生成 ``command_allowlist`` 建议。但审批消息自 ``5d85ec89ac``
（owner i18n 改造）起搬进 ``locales/*.yaml``，``t()`` 在中文环境返回译文
（``已拦截：…``）。于是：

* ``_BLOCK_MARKERS`` 的 11 条**英文**字面量全部失配；
* SQL 预过滤 ``content LIKE '%BLOCKED%' OR content LIKE '%approval%'``
  在中文文案下也大多失配。

**双重漏检**的后果不是「少一条建议」，而是反向的：**被用户拒绝过的危险
命令被当成「执行过且隐含批准」**，达到 ``min_count`` 后进入建议列表，
经 ``--apply`` 永久写入 ``command_allowlist`` —— 此后该类命令免审批自动
执行。``git push --force`` 这类命令恰好是「破坏类排除表」之外的可建议
类别，因此这条链路是真实可达的。

本文件守住五件事
================
1. 端到端：拒绝过的命令**不得**变成建议（中/英两种语言下都必须成立）；
2. 结构优先：``status`` 字段（语言无关）足以判定拦截，不依赖任何文案；
3. 预过滤是判定的超集：任何标记都能通过 SQL 粗筛，否则形成同源漏检；
4. catalog 驱动：标记覆盖**当前语言**的译文，而非只有英文；
5. 不误伤：命令真的执行成功时（即便输出里出现 ``BLOCKED`` 字样）不得
   被判成拦截 —— 这条守住「宁缺毋滥」的另一侧。
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import agent.i18n as i18n
import tools.approval as approval
from hermes_cli import approvals_suggest as suggest
from owner.approval import approval_history_policy as policy

# 一个「会被建议」的危险命令：它命中 danger 分类，但**不**属于「破坏类
# 永不建议」的排除集，所以只要被误判为「已批准」就会真的进建议列表 ——
# 这正是 T2-1 的端到端可复现路径。
_SUGGESTIBLE_DANGEROUS = "git push --force origin main"
_EXPECTED_GLOB = "git push *"


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

def _make_db(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            tool_call_id TEXT,
            tool_calls TEXT,
            timestamp REAL NOT NULL
        );
        """
    )
    con.commit()
    return con


def _add_terminal_call(con, command: str, result: str, ts: float | None = None) -> str:
    """插入一条 assistant ``terminal`` 调用 + 配对的 ``role='tool'`` 结果。"""
    call_id = "call_%d" % (id(result) % 10_000_000) + str(int((ts or time.time()) * 1e6))
    ts = ts if ts is not None else time.time()
    tool_calls = json.dumps(
        [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": "terminal",
                    "arguments": json.dumps({"command": command}),
                },
            }
        ]
    )
    con.execute(
        "INSERT INTO messages (session_id, role, content, tool_calls, timestamp) "
        "VALUES ('s1', 'assistant', '', ?, ?)",
        (tool_calls, ts),
    )
    con.execute(
        "INSERT INTO messages (session_id, role, content, tool_call_id, timestamp) "
        "VALUES ('s1', 'tool', ?, ?, ?)",
        (result, call_id, ts + 1),
    )
    con.commit()
    return call_id


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "state.db"
    con = _make_db(path)
    yield path, con
    con.close()


@pytest.fixture
def isolated_allowlist(monkeypatch):
    store = {"patterns": set(), "saves": 0}

    monkeypatch.setattr(
        approval, "load_permanent_allowlist", lambda: set(store["patterns"])
    )

    def _save(patterns):
        store["patterns"] = set(patterns)
        store["saves"] += 1

    monkeypatch.setattr(approval, "save_permanent_allowlist", _save)
    saved = approval._permanent_approved.copy()
    approval._permanent_approved.clear()
    yield store
    approval._permanent_approved.clear()
    approval._permanent_approved.update(saved)


def _set_language(monkeypatch, lang: str) -> None:
    monkeypatch.setenv("HERMES_LANGUAGE", lang)
    i18n.reset_language_cache()
    policy.clear_cache()


@pytest.fixture(autouse=True)
def _reset_policy_cache():
    policy.clear_cache()
    yield
    policy.clear_cache()


def _localized(key: str) -> str:
    """取 ``approval`` 段某个键在**当前语言**下的真实文案。"""
    return approval.t(key)


def _blocked_result_zh() -> str:
    """terminal 在中文环境下的典型拦截结果（结构 + 中文文案）。"""
    return json.dumps(
        {
            "output": "",
            "exit_code": -1,
            "error": _localized("approval.cli_denied"),
            "status": "blocked",
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# 1. 端到端：拒绝过的命令不得变成建议
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lang", ["zh", "en"])
def test_denied_commands_never_become_proposals(db_path, isolated_allowlist, monkeypatch, lang):
    """清单要求的端到端用例：反复被拒绝的命令不得进建议列表。

    这是 T2-1 的**唯一可观测危害**：拒绝 → 被读成批准 → 写进永久
    allowlist。修复前本用例在 ``zh`` 下失败（漏检），在 ``en`` 下通过。
    """
    _set_language(monkeypatch, lang)
    path, con = db_path

    for _ in range(4):
        _add_terminal_call(con, _SUGGESTIBLE_DANGEROUS, _blocked_result_zh())

    records = suggest.scan_approval_history(path, days=0)
    assert records == [], (
        "被用户拒绝的命令被读成了「隐含批准」——审批结果判定漏检（T2-1）"
    )

    proposals = suggest.build_proposals(records, min_count=2)
    assert proposals == [], "拒绝过的命令进了建议列表"
    assert isolated_allowlist["saves"] == 0


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_approved_commands_still_become_proposals(db_path, isolated_allowlist, monkeypatch, lang):
    """对照组：真正执行成功的同类命令**仍要**产出建议（别修过头）。"""
    _set_language(monkeypatch, lang)
    path, con = db_path

    ok = json.dumps(
        {"output": "forced update", "exit_code": 0, "status": "success"},
        ensure_ascii=False,
    )
    for _ in range(4):
        _add_terminal_call(con, _SUGGESTIBLE_DANGEROUS, ok)

    proposals = suggest.build_proposals(
        suggest.scan_approval_history(path, days=0), min_count=2
    )
    assert [p.pattern for p in proposals] == [_EXPECTED_GLOB]


def test_mixed_history_keeps_only_approved(db_path, isolated_allowlist, monkeypatch):
    """拒绝与批准混在一起时，只保留批准的计数。"""
    _set_language(monkeypatch, "zh")
    path, con = db_path

    ok = json.dumps({"output": "ok", "exit_code": 0, "status": "success"}, ensure_ascii=False)
    for _ in range(3):
        _add_terminal_call(con, _SUGGESTIBLE_DANGEROUS, ok)
    for _ in range(5):
        _add_terminal_call(con, _SUGGESTIBLE_DANGEROUS, _blocked_result_zh())

    proposals = suggest.build_proposals(
        suggest.scan_approval_history(path, days=0), min_count=1
    )
    assert len(proposals) == 1
    assert proposals[0].pattern == _EXPECTED_GLOB
    assert proposals[0].count == 3, "被拒绝的 5 次混进了计数"


# ---------------------------------------------------------------------------
# 2. 结构优先：status 字段（语言无关）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "status",
    ["blocked", "pending_approval", "approval_required", "denied", "rejected"],
)
def test_status_field_alone_proves_non_execution(status):
    """只给结构化状态、不给任何可读文案，也必须判定为「未执行」。"""
    payload = json.dumps({"status": status, "error": "", "output": ""})
    assert policy.result_blocks_execution(payload) is True


def test_approval_pending_flag_proves_non_execution():
    payload = json.dumps({"status": None, "approval_pending": True, "output": ""})
    assert policy.result_blocks_execution(payload) is True


def test_owner_marker_outcome_and_consent_fields():
    """approval 层原始返回 dict 上的 outcome / user_consent 也算结构标记。"""
    assert policy.result_blocks_execution(json.dumps({"outcome": "denied"})) is True
    assert policy.result_blocks_execution(json.dumps({"outcome": "timeout"})) is True
    assert policy.result_blocks_execution(json.dumps({"outcome": "transport_failed"})) is True
    assert policy.result_blocks_execution(json.dumps({"user_consent": False})) is True


def test_command_timeout_status_is_not_treated_as_denial():
    """``status='timeout'`` 是「命令执行超时」（命令跑过了），不是审批超时。

    审批超时由文案层识别（``BLOCKED: Command timed out without user
    response``），不能靠 status 一刀切 —— 否则会丢掉真实的批准。
    """
    payload = json.dumps(
        {"status": "timeout", "error": "Command timed out after 120s", "output": "partial"}
    )
    assert policy.result_blocks_execution(payload) is False


# ---------------------------------------------------------------------------
# 3. 不误伤：执行成功的结果即便提及 BLOCKED 也不算拦截
# ---------------------------------------------------------------------------

def test_successful_result_mentioning_blocked_is_not_a_denial():
    """用户 `cat` 一个含 ``BLOCKED:`` 字样的文件，不是「命令被拦截」。"""
    payload = json.dumps(
        {
            "output": "diff --git a/locales/zh.yaml\n+  cli_denied: 'BLOCKED: User denied this command'\n",
            "exit_code": 0,
            "status": "success",
        },
        ensure_ascii=False,
    )
    assert policy.result_blocks_execution(payload) is False


def test_output_field_is_deliberately_ignored():
    """判定只看 error/message，不看 output —— 后者是命令的真实输出。"""
    payload = json.dumps(
        {"output": _localized("approval.cli_denied"), "exit_code": 0, "status": "success"}
    )
    assert policy.result_blocks_execution(payload) is False

    # 反过来，同样的文案落在 error 字段就必须命中
    payload_err = json.dumps({"error": _localized("approval.cli_denied"), "status": "error"})
    assert policy.result_blocks_execution(payload_err) is True


# ---------------------------------------------------------------------------
# 4. 修复的量：旧表对本地化文案命中 = 0，新策略命中 = 1
# ---------------------------------------------------------------------------

def test_legacy_english_markers_miss_localized_denials(monkeypatch):
    """量化对比：这正是 26 天后才被发现的漏检面。"""
    _set_language(monkeypatch, "zh")

    localized = _localized("approval.cli_denied")
    assert localized and localized != "approval.cli_denied", (
        "未取到 approval.cli_denied 的文案：%r" % localized[:80]
    )
    legacy_hit = any(marker in localized for marker in suggest._BLOCK_MARKERS)
    assert legacy_hit is False, (
        "旧英文标记表居然命中了中文译文 —— 若上游已改走本地化，本断言需要复核"
    )

    payload = json.dumps({"status": "error", "error": localized}, ensure_ascii=False)
    assert policy.result_blocks_execution(payload) is True, "新策略未能命中中文拒绝文案"


def test_legacy_markers_still_available_as_fallback():
    """旧表降级为兜底后仍在文件里，且覆盖英文原文（上游行为不退化）。"""
    en = "BLOCKED: User denied this command. The user has NOT consented to this action."
    assert any(marker in en for marker in suggest._BLOCK_MARKERS)


def test_owner_delegate_is_wired():
    """薄委托必须真的生效（不是静默退回旧表）。"""
    assert suggest._owner_result_blocks_execution is policy.result_blocks_execution
    assert suggest._owner_sql_like_anchors is policy.sql_like_anchors


# ---------------------------------------------------------------------------
# 5. 预过滤是判定的超集（防两处判据漂移）
# ---------------------------------------------------------------------------

def test_every_marker_passes_the_sql_prefilter():
    """任何标记都必须能被 SQL 锚点放行。

    原缺陷的第二个根源就是预过滤与判定表各写一份、互相漂移：判定表认得
    中文，预过滤只认英文，于是中文行根本到不了判定。本断言把这条缝焊死。
    """
    markers = policy.load_markers()
    assert markers, "标记集合为空 —— catalog 与兜底都没有生效"

    uncovered = [m for m in sorted(markers) if not policy.anchor_covers(m)]
    assert not uncovered, (
        "以下标记无法通过 SQL 粗筛，会形成静默漏检；"
        "请在 SQL_LIKE_ANCHORS 中补充锚点：\n  " + "\n  ".join(repr(m) for m in uncovered)
    )


def test_anchor_coverage_is_case_insensitive_like_sql():
    """``anchor_covers`` 必须按 SQL LIKE 语义比较（ASCII 大小写不敏感）。"""
    assert policy.anchor_covers("BLOCKED: whatever") is True
    assert policy.anchor_covers("已拦截：随便什么") is True


def test_prefilter_and_verdict_agree_on_real_shapes():
    """粗筛放行的行里，判定必须真的给出结论（抽样一致性）。"""
    samples = [
        _blocked_result_zh(),
        json.dumps({"status": "pending_approval", "approval_pending": True}),
        json.dumps({"status": "error", "error": _localized("approval.execute_code_user_denied")}),
    ]
    for sample in samples:
        assert any(
            anchor.lower() in sample.lower() for anchor in policy.sql_like_anchors()
        ), "样本未被粗筛放行"
        assert policy.result_blocks_execution(sample) is True


# ---------------------------------------------------------------------------
# 6. catalog 驱动：覆盖当前语言，且不是只认英文
# ---------------------------------------------------------------------------

def test_markers_cover_both_english_and_localized_denials(monkeypatch):
    _set_language(monkeypatch, "zh")
    markers = policy.load_markers()

    def _covered(text: str) -> bool:
        return any(m in text for m in markers)

    assert _covered(_localized("approval.cli_denied")), "标记表未覆盖中文拒绝文案"
    assert _covered(_localized("approval.hardline_blocked").replace("{description}", "x")), (
        "标记表未覆盖中文硬拦截文案"
    )
    assert _covered("BLOCKED: User denied this command."), "标记表未覆盖英文原文"


def test_message_keys_are_real_catalog_keys():
    """白名单里的键必须真实存在于 catalog —— 防止拼写漂移悄悄缩小覆盖面。"""
    import yaml

    en = yaml.safe_load((REPO_ROOT / "locales" / "en.yaml").read_text(encoding="utf-8"))
    segment = en.get("approval") or {}
    missing = [key for key in policy.MESSAGE_KEYS if key not in segment]
    assert not missing, "以下审批键在 locales/en.yaml 的 approval 段中不存在：%s" % missing


def test_fallback_markers_exist_for_catalog_failure():
    """catalog 不可用时仍有兜底标记（fail-safe，而非静默退化为只看 status）。"""
    assert policy.FALLBACK_MARKERS
    assert any("已拦截" in m for m in policy.FALLBACK_MARKERS)
    assert any("BLOCKED" in m for m in policy.FALLBACK_MARKERS)


def test_markers_are_cached_and_resettable():
    first = policy.load_markers()
    assert policy.load_markers() is first, "未命中缓存 —— 每次调用都重读 catalog"
    policy.clear_cache()
    second = policy.load_markers()
    assert second == first
    assert second is not first


# ---------------------------------------------------------------------------
# 7. 覆盖面对比：新策略识别的键比旧表多
# ---------------------------------------------------------------------------

def test_policy_covers_more_keys_than_legacy_table():
    """``MESSAGE_KEYS`` 的规模是旧硬编码表的数倍（旧表 11 条，且多为漂移项）。"""
    assert len(policy.MESSAGE_KEYS) > len(suggest._BLOCK_MARKERS) * 3


def test_legacy_table_had_drifted_from_upstream():
    """记录旧表的漂移：其中若干条在上游 catalog 里已不存在该字面量。"""
    import yaml

    en = yaml.safe_load((REPO_ROOT / "locales" / "en.yaml").read_text(encoding="utf-8"))
    values = [v for v in (en.get("approval") or {}).values() if isinstance(v, str)]
    drifted = [
        marker
        for marker in suggest._BLOCK_MARKERS
        if not any(marker in value for value in values)
    ]
    assert drifted, "旧表仍与上游完全一致 —— 本断言的前提已失效，需复核"
