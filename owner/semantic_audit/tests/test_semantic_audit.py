"""Semantic Audit Gate 测试。

覆盖：
- HALT 配对完整性（每个 tool_call_id 都有 synthetic result）
- strike 2 次升级 HALT
- hardline 直接 HALT（yolo 下也 HALT）
- 并发两 session strike 不串线
- 无 owner 包时 import 失败 fail-open
- mock LLM 超时的分级 fail 行为
- BLOCK 后 PASS 的 call 由 gate 内执行，消息协议 1:1
- 同批 HALT + PASS 时整批停
- HALT 后 _safe_print 用户可见通知
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace
import pytest


# ── helpers ────────────────────────────────────────────────────────────


def _tc(tid: str, name: str, arguments: str | dict):
    if isinstance(arguments, dict):
        import json as _json

        arguments = _json.dumps(arguments)
    return SimpleNamespace(
        id=tid,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _agent(session_id: str = "sess-a", platform: str = "cli"):
    a = SimpleNamespace(
        session_id=session_id,
        platform=platform,
        _interrupt_requested=False,
        _interrupt_message=None,
        _current_turn_id="turn-1",
        _user_turn_count=1,
        _safe_print_calls=[],
        background_review_callback=None,
        _invoked=[],
    )

    def interrupt(message=None):
        a._interrupt_requested = True
        a._interrupt_message = message

    def _safe_print(*args, **kwargs):
        a._safe_print_calls.append((args, kwargs))

    def _invoke_tool(function_name, function_args, effective_task_id,
                     tool_call_id=None, messages=None, **kwargs):
        a._invoked.append(
            {
                "name": function_name,
                "args": function_args,
                "tool_call_id": tool_call_id,
                "task_id": effective_task_id,
            }
        )
        return json.dumps(
            {"ok": True, "tool": function_name, "tool_call_id": tool_call_id}
        )

    a.interrupt = interrupt
    a._safe_print = _safe_print
    a._invoke_tool = _invoke_tool
    return a


@pytest.fixture(autouse=True)
def _clean_strikes():
    from owner.semantic_audit import policy

    policy.clear_all()
    yield
    policy.clear_all()


@pytest.fixture
def enabled_cfg(monkeypatch):
    cfg = {
        "enabled": True,
        "max_strikes": 2,
        "cron_enforce": True,
        "respect_yolo": False,
        "provider": "auto",
        "model": "auto",
        "timeout": 5.0,
    }
    monkeypatch.setattr(
        "owner.semantic_audit.config.get_semantic_audit_cfg",
        lambda: dict(cfg),
    )
    monkeypatch.setattr(
        "owner.semantic_audit.gate.get_semantic_audit_cfg",
        lambda: dict(cfg),
    )
    return cfg


# ── pairing / HALT ─────────────────────────────────────────────────────


def test_halt_pairs_every_tool_call_id(enabled_cfg, monkeypatch):
    """HALT 时 batch 内每个 tool_call_id 都有 synthetic tool result。"""
    from owner.semantic_audit.gate import maybe_audit_batch

    agent = _agent()
    tcs = [
        _tc("c1", "terminal", {"command": "reboot"}),
        _tc("c2", "read_file", {"path": "/tmp/x"}),
        _tc("c3", "web_search", {"query": "hi"}),
    ]
    assistant = SimpleNamespace(tool_calls=tcs, content="rebooting")
    messages: list = []

    halted = maybe_audit_batch(agent, assistant, messages, "task-1")
    assert halted is True
    assert agent._interrupt_requested is True

    result_ids = {
        m.get("tool_call_id") for m in messages if m.get("role") == "tool"
    }
    assert result_ids == {"c1", "c2", "c3"}
    assert all(m.get("content") for m in messages if m.get("role") == "tool")


def test_hardline_halts_under_yolo(enabled_cfg, monkeypatch):
    """Hardline 在 yolo 下仍 HALT。"""
    from owner.semantic_audit.gate import maybe_audit_batch

    # 模拟 yolo 开着
    monkeypatch.setattr(
        "owner.semantic_audit.policy.should_skip_for_yolo",
        lambda cfg: False,  # respect_yolo=False → never skip
    )
    agent = _agent()
    tcs = [_tc("h1", "terminal", {"command": "rm -rf /"})]
    assistant = SimpleNamespace(tool_calls=tcs, content="")
    messages: list = []

    assert maybe_audit_batch(agent, assistant, messages, "t") is True
    assert agent._interrupt_requested is True
    assert "HALT" in (messages[0].get("content") or "") or "hardline" in (
        messages[0].get("content") or ""
    ).lower() or "semantic_audit" in (messages[0].get("content") or "")


def test_strike_two_blocks_escalate_to_halt(enabled_cfg, monkeypatch):
    """第 2 次 BLOCK 升级为 HALT。"""
    from owner.semantic_audit.gate import maybe_audit_batch

    def _llm_block(*, agent, messages, assistant_message, tier1_calls, cfg, **_kw):
        return {
            c.tool_call_id: {
                "verdict": "BLOCK",
                "reason": "scope overreach: restart not requested",
            }
            for c in tier1_calls
        }

    monkeypatch.setattr(
        "owner.semantic_audit.auditor.audit_tier1_calls",
        _llm_block,
    )
    # systemctl restart 是 dangerous → tier1
    agent = _agent()
    cmd = {"command": "systemctl restart nginx"}

    # 第 1 次 BLOCK
    tcs1 = [_tc("b1", "terminal", cmd)]
    asst1 = SimpleNamespace(tool_calls=tcs1, content="")
    msgs1: list = []
    r1 = maybe_audit_batch(agent, asst1, msgs1, "t")
    # 全部 block → return True（无剩余 dispatch），但不 interrupt
    assert r1 is True
    assert agent._interrupt_requested is False
    assert "BLOCK" in (msgs1[0].get("content") or "")

    # 第 2 次 → HALT
    tcs2 = [_tc("b2", "terminal", cmd)]
    asst2 = SimpleNamespace(tool_calls=tcs2, content="")
    msgs2: list = []
    r2 = maybe_audit_batch(agent, asst2, msgs2, "t")
    assert r2 is True
    assert agent._interrupt_requested is True
    assert any("HALT" in (m.get("content") or "") for m in msgs2)


def test_concurrent_sessions_strikes_isolated(enabled_cfg, monkeypatch):
    """两 session 并发 strike 不串线。"""
    from owner.semantic_audit import policy

    a1 = _agent("session-1")
    a2 = _agent("session-2")
    errors: list = []

    def worker(agent, n):
        try:
            for _ in range(n):
                policy.record_block(agent)
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=worker, args=(a1, 3))
    t2 = threading.Thread(target=worker, args=(a2, 1))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert not errors
    assert policy.get_strikes(a1) == 3
    assert policy.get_strikes(a2) == 1


def test_fail_open_without_owner_package():
    """无 owner 包时 import 失败 → glue 静默跳过（模拟）。"""
    # 直接验证 maybe_audit_batch 自身异常也 fail-open
    from owner.semantic_audit.gate import maybe_audit_batch

    class Boom:
        @property
        def tool_calls(self):
            raise RuntimeError("boom")

    agent = _agent()
    messages: list = []
    # 不应抛
    assert maybe_audit_batch(agent, Boom(), messages, "t") is False


def test_llm_timeout_fail_closed_for_tier1(enabled_cfg, monkeypatch):
    """LLM 超时：tier1 危险 call → BLOCK（fail-closed）。"""
    from owner.semantic_audit.gate import maybe_audit_batch

    def _timeout(*a, **k):
        raise TimeoutError("audit timed out")

    monkeypatch.setattr(
        "owner.semantic_audit.auditor._call_llm_sync",
        _timeout,
    )
    agent = _agent()
    tcs = [_tc("d1", "terminal", {"command": "systemctl restart nginx"})]
    asst = SimpleNamespace(tool_calls=list(tcs), content="")
    messages: list = []

    result = maybe_audit_batch(agent, asst, messages, "t")
    # 全部 block → True
    assert result is True
    assert agent._interrupt_requested is False
    assert len(messages) == 1
    assert "BLOCK" in (messages[0].get("content") or "") or "audit" in (
        messages[0].get("content") or ""
    ).lower()


def test_block_keeps_pass_calls_for_dispatch(enabled_cfg, monkeypatch):
    """BLOCK 后 PASS 的 call 由 gate 内执行；不改 tool_calls，返回 True。"""
    from owner.semantic_audit.gate import maybe_audit_batch

    def _mixed(*, agent, messages, assistant_message, tier1_calls, cfg, **_kw):
        out = {}
        for c in tier1_calls:
            if "restart" in str(c.args):
                out[c.tool_call_id] = {
                    "verdict": "BLOCK",
                    "reason": "restart not requested",
                }
            else:
                out[c.tool_call_id] = {"verdict": "PASS", "reason": "ok"}
        return out

    monkeypatch.setattr(
        "owner.semantic_audit.auditor.audit_tier1_calls",
        _mixed,
    )
    agent = _agent()
    t_block = _tc("x1", "terminal", {"command": "systemctl restart nginx"})
    t_pass = _tc("x2", "write_file", {"path": "/etc/hosts", "content": "x"})
    t_read = _tc("x3", "read_file", {"path": "/tmp/a"})

    tool_calls = [t_block, t_pass, t_read]
    asst = SimpleNamespace(tool_calls=tool_calls, content="")
    messages: list = []

    cont = maybe_audit_batch(agent, asst, messages, "t")
    # gate 自己处理完整个 batch → 跳过下游 dispatch
    assert cont is True
    # 不改 assistant.tool_calls（协议要求与 results 1:1）
    assert [tc.id for tc in asst.tool_calls] == ["x1", "x2", "x3"]
    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    assert [m.get("tool_call_id") for m in tool_msgs] == ["x1", "x2", "x3"]
    assert "BLOCK" in (tool_msgs[0].get("content") or "")
    # remaining 经 _invoke_tool 执行
    invoked_ids = {inv["tool_call_id"] for inv in agent._invoked}
    assert invoked_ids == {"x2", "x3"}


def test_block_tool_result_protocol_1to1(enabled_cfg, monkeypatch):
    """BLOCK 混合 batch：每个 tool_call_id 有且仅有一条 result，顺序一致。"""
    from owner.semantic_audit.gate import maybe_audit_batch

    def _mixed(*, agent, messages, assistant_message, tier1_calls, cfg, **_kw):
        out = {}
        for c in tier1_calls:
            if "restart" in str(c.args):
                out[c.tool_call_id] = {
                    "verdict": "BLOCK",
                    "reason": "restart not requested",
                }
            else:
                out[c.tool_call_id] = {"verdict": "PASS", "reason": "ok"}
        return out

    monkeypatch.setattr(
        "owner.semantic_audit.auditor.audit_tier1_calls",
        _mixed,
    )
    agent = _agent()
    # 顺序：PASS, BLOCK, PASS — 验证 blocked 夹在中间时顺序仍对
    tcs = [
        _tc("a", "write_file", {"path": "/etc/hosts", "content": "x"}),
        _tc("b", "terminal", {"command": "systemctl restart nginx"}),
        _tc("c", "read_file", {"path": "/tmp/ok"}),
    ]
    original_ids = [tc.id for tc in tcs]
    asst = SimpleNamespace(tool_calls=list(tcs), content="")
    messages: list = []

    assert maybe_audit_batch(agent, asst, messages, "task-proto") is True
    assert [tc.id for tc in asst.tool_calls] == original_ids

    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    result_ids = [m.get("tool_call_id") for m in tool_msgs]
    assert result_ids == original_ids
    # 唯一性
    assert len(result_ids) == len(set(result_ids)) == len(original_ids)
    assert "BLOCK" in (tool_msgs[1].get("content") or "")
    assert "ok" in (tool_msgs[0].get("content") or "").lower() or tool_msgs[0].get(
        "content"
    )
    assert {inv["tool_call_id"] for inv in agent._invoked} == {"a", "c"}


def test_halt_notifies_via_safe_print(enabled_cfg, monkeypatch):
    """HALT 后 agent._safe_print 被调用，gateway callback 同步推送。"""
    from owner.semantic_audit.gate import maybe_audit_batch

    agent = _agent()
    cb_msgs: list = []
    agent.background_review_callback = lambda msg: cb_msgs.append(msg)

    tcs = [_tc("h1", "terminal", {"command": "rm -rf /"})]
    asst = SimpleNamespace(tool_calls=tcs, content="")
    messages: list = []

    assert maybe_audit_batch(agent, asst, messages, "t") is True
    assert agent._interrupt_requested is True
    assert agent._safe_print_calls, "_safe_print should be called on HALT"
    printed = "\n".join(
        str(args[0]) if args else "" for args, _kwargs in agent._safe_print_calls
    )
    assert "语义审计中断" in printed
    assert "模型尝试执行" in printed
    assert "本轮已终止" in printed
    assert cb_msgs
    assert "语义审计中断" in cb_msgs[0]
    assert "模型尝试执行" in cb_msgs[0]


def test_halt_plus_pass_stops_whole_batch(enabled_cfg, monkeypatch):
    """同批 HALT + PASS 时整批停，PASS 也不执行。"""
    from owner.semantic_audit.gate import maybe_audit_batch

    def _halt_one(*, agent, messages, assistant_message, tier1_calls, cfg, **_kw):
        out = {}
        for i, c in enumerate(tier1_calls):
            if i == 0:
                out[c.tool_call_id] = {
                    "verdict": "HALT",
                    "reason": "aggressive overreach",
                }
            else:
                out[c.tool_call_id] = {"verdict": "PASS", "reason": "ok"}
        return out

    monkeypatch.setattr(
        "owner.semantic_audit.auditor.audit_tier1_calls",
        _halt_one,
    )
    agent = _agent()
    tcs = [
        _tc("h1", "terminal", {"command": "systemctl restart nginx"}),
        _tc("h2", "write_file", {"path": "/etc/nginx/nginx.conf", "content": "x"}),
        _tc("h3", "read_file", {"path": "/tmp/ok"}),
    ]
    asst = SimpleNamespace(tool_calls=list(tcs), content="")
    messages: list = []

    assert maybe_audit_batch(agent, asst, messages, "t") is True
    assert agent._interrupt_requested is True
    result_ids = {
        m.get("tool_call_id") for m in messages if m.get("role") == "tool"
    }
    assert result_ids == {"h1", "h2", "h3"}


def test_detector_hardline_rm_rf_root():
    from owner.semantic_audit.detector import classify_tool_call

    c = classify_tool_call(_tc("1", "terminal", {"command": "sudo rm -rf /"}))
    assert c.tier == "hardline"


def test_detector_sensitive_path_tier1():
    from owner.semantic_audit.detector import classify_tool_call

    c = classify_tool_call(
        _tc("1", "write_file", {"path": "/etc/crontab", "content": "* * * * * root x"})
    )
    assert c.tier == "tier1"


def test_detector_skips_read_file():
    from owner.semantic_audit.detector import classify_tool_call

    c = classify_tool_call(_tc("1", "read_file", {"path": "/etc/hosts"}))
    assert c.tier == "skip"


def test_detector_process_kill_is_tier1():
    """process kill 必须进 tier1，不能被 _SAFE_TOOLS 跳过。"""
    from owner.semantic_audit.detector import classify_tool_call

    c = classify_tool_call(
        _tc("c1", "process", {"action": "kill", "session_id": "bg-1234"})
    )
    assert c.tier == "tier1", f"process kill must be tier1, got {c.tier}"
    assert "kill" in c.reason


def test_detector_process_write_submit_close_are_tier1():
    from owner.semantic_audit.detector import classify_tool_call

    for action in ("write", "submit", "close"):
        c = classify_tool_call(
            _tc("c2", "process", {"action": action, "session_id": "bg-1", "data": "x"})
        )
        assert c.tier == "tier1", f"process {action} must be tier1, got {c.tier}"


def test_detector_process_list_and_wait_skip():
    from owner.semantic_audit.detector import classify_tool_call

    for action in ("list", "poll", "log", "wait"):
        args = {"action": action}
        if action != "list":
            args["session_id"] = "bg-1"
        c = classify_tool_call(_tc("c3", "process", args))
        assert c.tier == "skip", f"process {action} must skip, got {c.tier}"
        assert c.reason == "process read-only action"


def test_detector_process_not_in_safe_tools():
    from owner.semantic_audit.detector import _SAFE_TOOLS

    assert "process" not in _SAFE_TOOLS


def test_block_message_no_dead_branch():
    from owner.semantic_audit.notify import block_message

    msg1 = block_message("terminal", "scope", strikes=1, max_strikes=2)
    assert "Strike 1/2." in msg1
    assert "next violation" not in msg1

    msg2 = block_message("terminal", "scope", strikes=2, max_strikes=2)
    assert "Strike 2/2" in msg2
    assert "HALT" in msg2


def test_extract_user_instructions_uses_pending_cli():
    from owner.semantic_audit.auditor import extract_user_instructions

    agent = SimpleNamespace(_pending_cli_user_message="  from cli  ")
    out = extract_user_instructions(
        [{"role": "user", "content": "history user"}],
        agent,
        max_items=3,
    )
    assert "from cli" in out[-1]


def test_unwrap_tool_call_bridge(monkeypatch):
    from owner.semantic_audit import detector

    # 构造 tool_call 桥
    tc = _tc(
        "1",
        "tool_call",
        {"name": "terminal", "arguments": {"command": "rm -rf /"}},
    )
    # resolve_underlying_call 需要 deferrable 名；若失败则 name 保持 tool_call
    c = detector.classify_tool_call(tc)
    # 无论 unwrap 是否成功，不应 crash
    assert c.tier in {"hardline", "tier1", "skip"}


def test_parse_verdicts_json():
    from owner.semantic_audit.auditor import parse_verdicts

    content = '{"verdicts":{"a":{"verdict":"BLOCK","reason":"no"},"b":{"verdict":"PASS","reason":"ok"}}}'
    out = parse_verdicts(content, ["a", "b"])
    assert out["a"]["verdict"] == "BLOCK"
    assert out["b"]["verdict"] == "PASS"


def test_build_audit_prompt_includes_batch_siblings_and_skill_context():
    from owner.semantic_audit.auditor import build_audit_prompt
    from owner.semantic_audit.detector import ClassifiedCall

    tier1 = ClassifiedCall(
        tool_call_id="t1",
        original_name="terminal",
        name="terminal",
        args={"command": "systemctl restart nginx"},
        tier="tier1",
        reason="dangerous",
    )
    prompt = build_audit_prompt(
        user_instructions=["check nginx"],
        assistant_text="following skill",
        tier1_calls=[tier1],
        prior_tools=[],
        batch_siblings=[
            {
                "tool_call_id": "s1",
                "name": "skill_view",
                "tier": "skip",
                "args": '{"name":"ops-nginx"}',
            },
            {
                "tool_call_id": "t1",
                "name": "terminal",
                "tier": "tier1",
                "args": '{"command":"systemctl restart nginx"}',
            },
        ],
        skill_context=[
            {
                "skill": "ops-nginx",
                "file_path": "SKILL.md",
                "content": "When restarting nginx use systemctl restart nginx",
                "source": "skill_view",
            }
        ],
    )
    user_payload = json.loads(prompt[1]["content"])
    assert "batch_siblings" in user_payload
    assert len(user_payload["batch_siblings"]) == 2
    assert user_payload["batch_siblings"][0]["name"] == "skill_view"
    assert "skill_context" in user_payload
    assert user_payload["skill_context"][0]["skill"] == "ops-nginx"
    assert "SOP" in prompt[0]["content"] or "skill_context" in prompt[0]["content"]


def test_collect_skill_context_loads_sibling_skill_view(monkeypatch):
    """同批 skill_view 未执行时，审计侧应主动 skill_view 拿到正文。"""
    import owner.semantic_audit.auditor as auditor
    from owner.semantic_audit.detector import ClassifiedCall

    def fake_skill_view(name, file_path=None, task_id=None, preprocess=True):
        return json.dumps(
            {
                "success": True,
                "name": name,
                "description": "nginx ops SOP",
                "content": (
                    "## Procedure\n"
                    "1. systemctl status nginx\n"
                    "2. systemctl restart nginx\n"
                ),
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(
        "tools.skills_tool.skill_view",
        fake_skill_view,
        raising=False,
    )
    # also patch if already imported path used inside _load_skill_content
    import tools.skills_tool as st

    monkeypatch.setattr(st, "skill_view", fake_skill_view)

    batch = [
        ClassifiedCall(
            tool_call_id="s1",
            original_name="skill_view",
            name="skill_view",
            args={"name": "ops-nginx"},
            tier="skip",
            reason="safe tool",
        ),
        ClassifiedCall(
            tool_call_id="t1",
            original_name="terminal",
            name="terminal",
            args={"command": "systemctl restart nginx"},
            tier="tier1",
            reason="dangerous",
        ),
    ]
    ctx = auditor.collect_skill_context(batch, messages=[])
    assert len(ctx) == 1
    assert ctx[0]["skill"] == "ops-nginx"
    assert "systemctl restart nginx" in ctx[0]["content"]
    assert ctx[0]["source"] == "skill_view"


def test_collect_skill_context_from_prior_tool_result():
    from owner.semantic_audit.auditor import collect_skill_context

    body = json.dumps(
        {
            "success": True,
            "name": "deploy-app",
            "description": "deploy sop",
            "content": "Step: kubectl apply -f deploy.yaml",
        },
        ensure_ascii=False,
    )
    messages = [
        {
            "role": "tool",
            "name": "skill_view",
            "tool_call_id": "old1",
            "content": body,
        }
    ]
    ctx = collect_skill_context([], messages)
    assert len(ctx) == 1
    assert ctx[0]["skill"] == "deploy-app"
    assert "kubectl apply" in ctx[0]["content"]
    assert ctx[0]["source"] == "prior_tool_result"


def test_extract_prior_tool_calls_longer_for_skill_view():
    from owner.semantic_audit.auditor import extract_prior_tool_calls

    long_body = "S" * 800
    messages = [
        {
            "role": "tool",
            "name": "read_file",
            "tool_call_id": "a",
            "content": "X" * 500,
        },
        {
            "role": "tool",
            "name": "skill_view",
            "tool_call_id": "b",
            "content": long_body,
        },
    ]
    prior = extract_prior_tool_calls(messages)
    by_name = {p["name"]: p for p in prior}
    assert len(by_name["read_file"]["preview"]) <= 121
    assert len(by_name["skill_view"]["preview"]) > 200


def test_audit_tier1_prompt_wires_siblings(monkeypatch):
    """audit_tier1_calls 应把整批 siblings 和 skill 写入 LLM prompt。"""
    from owner.semantic_audit import auditor
    from owner.semantic_audit.detector import ClassifiedCall

    captured = {}

    def fake_llm(**kwargs):
        captured["messages"] = kwargs["messages"]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "verdicts": {
                                    "t1": {
                                        "verdict": "PASS",
                                        "reason": "matches skill SOP",
                                    }
                                }
                            }
                        )
                    )
                )
            ]
        )

    monkeypatch.setattr(auditor, "_call_llm_sync", fake_llm)
    monkeypatch.setattr(
        auditor,
        "collect_skill_context",
        lambda *a, **k: [
            {
                "skill": "ops",
                "file_path": "SKILL.md",
                "content": "restart ok",
                "source": "skill_view",
            }
        ],
    )

    tier1 = ClassifiedCall(
        tool_call_id="t1",
        original_name="terminal",
        name="terminal",
        args={"command": "systemctl restart nginx"},
        tier="tier1",
        reason="dangerous",
    )
    skill_skip = ClassifiedCall(
        tool_call_id="s1",
        original_name="skill_view",
        name="skill_view",
        args={"name": "ops"},
        tier="skip",
        reason="safe tool",
    )
    out = auditor.audit_tier1_calls(
        agent=_agent(),
        messages=[{"role": "user", "content": "fix nginx"}],
        assistant_message=SimpleNamespace(content="using skill", tool_calls=[]),
        tier1_calls=[tier1],
        batch_calls=[skill_skip, tier1],
        cfg={
            "timeout": 5,
            "provider": "auto",
            "model": "auto",
        },
    )
    assert out["t1"]["verdict"] == "PASS"
    payload = json.loads(captured["messages"][1]["content"])
    assert any(s["name"] == "skill_view" for s in payload["batch_siblings"])
    assert payload["skill_context"][0]["skill"] == "ops"


def test_run_agent_glue_fail_open(monkeypatch):
    """run_agent 胶水在 import 失败时 fail-open（不阻断 dispatch）。"""
    import run_agent as ra

    called = {"seq": False}

    def _seq(self, *a, **k):
        called["seq"] = True

    # 用真实 AIAgent 子类，避免 MagicMock 吞掉方法查找
    class _Tiny(ra.AIAgent):
        def __init__(self):
            # 跳过沉重 __init__
            self._executing_tools = False

        def _execute_tool_calls_sequential(self, *a, **k):
            called["seq"] = True

    monkeypatch.setattr(ra.AIAgent, "_execute_tool_calls_sequential", _seq)

    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "owner.semantic_audit" or (
            isinstance(name, str) and name.startswith("owner.semantic_audit")
        ):
            raise ImportError("no owner")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    agent = _Tiny()
    asst = SimpleNamespace(
        tool_calls=[_tc("z", "read_file", {"path": "/tmp/x"})],
        content="",
    )
    messages: list = []
    ra.AIAgent._execute_tool_calls(agent, asst, messages, "task")
    assert called["seq"] is True
