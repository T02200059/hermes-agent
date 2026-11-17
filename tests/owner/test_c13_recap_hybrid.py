"""[owner] C13 recap — 超预算混合输入兜底."""

from __future__ import annotations

from owner.explainers.recap.hybrid import (
    HYBRID_CALIBRATION_EVERY,
    MODE_CALIBRATION,
    MODE_FULL,
    MODE_HYBRID,
    MODE_TAIL,
    PriorRecap,
    load_prior_recaps,
    plan_recap_input,
    recap_body_text,
    should_calibrate,
)
from owner.explainers.recap.prompt import PREFIX, build_messages
from owner.explainers.recap.flatten import flatten_messages


HEAD_TOKEN = "UNIQUE_HEAD_TOKEN_AAA"
TAIL_TOKEN = "UNIQUE_TAIL_TOKEN_ZZZ"
PRIOR_TEXT = "先前已完成方案评估，正准备落地改动。"


def _long_messages(head: str = HEAD_TOKEN, tail: str = TAIL_TOKEN, pad: int = 400):
    return [
        {"role": "system", "content": "should-not-appear"},
        {"role": "notice", "display_kind": "recap", "content": f"{PREFIX}旧回顾不应被 flatten"},
        {"role": "notice", "display_kind": "progress", "content": "🧭 系统提示：进度卡不是回顾"},
        {"role": "user", "content": head + ("H" * pad)},
        {"role": "assistant", "content": ("T" * pad) + tail, "_row_id": 42},
    ]


def test_under_budget_stays_full_and_ignores_prior():
    msgs = [
        {"role": "user", "content": "请改回顾"},
        {"role": "assistant", "content": "已记下"},
    ]
    prior = [PriorRecap(content=f"{PREFIX}{PRIOR_TEXT}", input_mode=MODE_FULL)]
    plan = plan_recap_input(msgs, max_input_chars=64000, prior_notices=prior)
    assert plan.mode == MODE_FULL
    assert plan.truncated is False
    assert plan.prior_recap is None
    prompt = build_messages(plan.dialogue, prior_recap=plan.prior_recap)
    user = prompt[1]["content"]
    assert "请改回顾" in user
    assert "已记下" in user
    assert PRIOR_TEXT not in user
    assert "【先前回顾】" not in user


def test_over_budget_with_prior_includes_prior_and_tail_not_head():
    msgs = _long_messages(pad=400)
    prior = [PriorRecap(content=f"{PREFIX}{PRIOR_TEXT}", row_id=9, input_mode=MODE_FULL)]
    plan = plan_recap_input(msgs, max_input_chars=200, prior_notices=prior)
    assert plan.mode == MODE_HYBRID
    assert plan.truncated is True
    assert plan.prior_recap == PRIOR_TEXT
    assert plan.prior_recap_id == 9
    assert plan.covered_last_message_id == 42
    assert HEAD_TOKEN not in plan.dialogue
    assert TAIL_TOKEN in plan.dialogue
    prompt = build_messages(plan.dialogue, prior_recap=plan.prior_recap)
    user = prompt[1]["content"]
    assert "【先前回顾】" in user
    assert PRIOR_TEXT in user
    assert "【近期对话】" in user
    assert TAIL_TOKEN in user
    assert HEAD_TOKEN not in user
    assert "旧回顾不应被 flatten" not in user
    assert "进度卡不是回顾" not in user


def test_over_budget_without_prior_falls_back_to_tail():
    msgs = _long_messages(pad=400)
    plan = plan_recap_input(msgs, max_input_chars=200, prior_notices=[])
    assert plan.mode == MODE_TAIL
    assert plan.prior_recap is None
    assert TAIL_TOKEN in plan.dialogue
    assert HEAD_TOKEN not in plan.dialogue
    prompt = build_messages(plan.dialogue, prior_recap=plan.prior_recap)
    user = prompt[1]["content"]
    assert "【先前回顾】" not in user
    assert TAIL_TOKEN in user


def test_flatten_skips_notice_and_progress():
    msgs = _long_messages(pad=10)
    flat = flatten_messages(msgs, max_input_chars=64000)
    assert "旧回顾不应被 flatten" not in flat
    assert "进度卡不是回顾" not in flat
    assert "should-not-appear" not in flat
    assert HEAD_TOKEN in flat
    assert TAIL_TOKEN in flat


def test_calibration_skips_prior_after_every_three_hybrids():
    assert HYBRID_CALIBRATION_EVERY == 3
    msgs = _long_messages(pad=400)
    notices = []
    modes = []
    for i in range(8):
        plan = plan_recap_input(
            msgs,
            max_input_chars=200,
            prior_notices=notices + [PriorRecap(content=f"{PREFIX}{PRIOR_TEXT}", row_id=1)],
        )
        modes.append(plan.mode)
        if plan.mode == MODE_HYBRID:
            assert plan.prior_recap == PRIOR_TEXT
        elif plan.mode == MODE_CALIBRATION:
            assert plan.prior_recap is None
            assert plan.prior_recap_id == 1
            prompt = build_messages(plan.dialogue, prior_recap=plan.prior_recap)
            assert PRIOR_TEXT not in prompt[1]["content"]
            assert "【先前回顾】" not in prompt[1]["content"]
            assert TAIL_TOKEN in prompt[1]["content"]
        notices.append(PriorRecap(content=f"{PREFIX}{PRIOR_TEXT}", input_mode=plan.mode))
    # 3 hybrid, 1 calibration, repeating
    assert modes == [
        MODE_HYBRID,
        MODE_HYBRID,
        MODE_HYBRID,
        MODE_CALIBRATION,
        MODE_HYBRID,
        MODE_HYBRID,
        MODE_HYBRID,
        MODE_CALIBRATION,
    ]


def test_should_calibrate_ignores_legacy_and_full_modes():
    legacy = [PriorRecap(content="x") for _ in range(5)]
    assert should_calibrate(legacy) is False
    counted = [PriorRecap(content="x", input_mode=MODE_HYBRID) for _ in range(3)]
    assert should_calibrate(counted) is True
    assert should_calibrate(counted[:2]) is False


def test_recap_body_text_strips_prefix():
    assert recap_body_text(f"{PREFIX}{PRIOR_TEXT}") == PRIOR_TEXT
    assert recap_body_text(PRIOR_TEXT) == PRIOR_TEXT


def _make_db(tmp_path, monkeypatch):
    from hermes_state import SessionDB
    from owner.explainers.persist import persist_notice

    home = tmp_path / "hermes_home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = SessionDB(db_path=home / "state.db")
    return db, persist_notice


def test_lookup_follows_compression_chain_not_progress(tmp_path, monkeypatch):
    db, persist_notice = _make_db(tmp_path, monkeypatch)
    try:
        db.create_session("root", source="test")
        persist_notice(
            "root",
            "progress",
            "🧭 系统提示：正在处理，这不是回顾。",
            trigger="tick",
            db=db,
        )
        persist_notice(
            "root",
            "recap",
            f"{PREFIX}压缩前的回顾正文",
            trigger="auto",
            db=db,
        )
        db.end_session("root", end_reason="compression")
        db.create_session("tip", source="test", parent_session_id="root")
        persist_notice(
            "tip",
            "progress",
            "🧭 系统提示：tip 进度卡",
            trigger="tick",
            db=db,
        )
        notices = load_prior_recaps("tip", db=db)
        assert len(notices) == 1
        assert "压缩前的回顾正文" in recap_body_text(notices[-1].content)
        plan = plan_recap_input(
            _long_messages(pad=400),
            max_input_chars=200,
            session_id="tip",
            db=db,
        )
        assert plan.mode == MODE_HYBRID
        assert plan.prior_recap == "压缩前的回顾正文"
    finally:
        db.close()


def test_lookup_does_not_follow_session_reset_chain(tmp_path, monkeypatch):
    db, persist_notice = _make_db(tmp_path, monkeypatch)
    try:
        db.create_session("old", source="test")
        persist_notice(
            "old",
            "recap",
            f"{PREFIX}上一场会话的回顾，不应带到新场",
            trigger="manual",
            db=db,
        )
        db.end_session("old", end_reason="session_reset")
        db.create_session(
            "new",
            source="test",
            parent_session_id="old",
            model_config={"_reset_from": "old"},
        )
        notices = load_prior_recaps("new", db=db)
        assert notices == []
        plan = plan_recap_input(
            _long_messages(pad=400),
            max_input_chars=200,
            session_id="new",
            db=db,
        )
        assert plan.mode == MODE_TAIL
        assert plan.prior_recap is None
    finally:
        db.close()


def test_explain_hybrid_prompt_reaches_llm(monkeypatch):
    from owner.explainers.recap.explain import explain_from_messages

    captured = {}

    def _fake_llm(kind, messages, **kwargs):
        captured["kind"] = kind
        captured["messages"] = messages
        captured["max_tokens"] = kwargs.get("max_tokens")
        return "你已完成前半段，正在收尾。"

    monkeypatch.setattr(
        "owner.explainers.llm.call_explainer_llm",
        _fake_llm,
    )
    route_info = {}
    text = explain_from_messages(
        _long_messages(pad=400),
        cfg={"max_input_chars": 200, "max_output_chars": 350},
        route_info=route_info,
        prior_notices=[PriorRecap(content=f"{PREFIX}{PRIOR_TEXT}", row_id=3)],
    )
    assert text
    assert captured["kind"] == "recap"
    assert captured["max_tokens"] == 260
    user = captured["messages"][1]["content"]
    assert PRIOR_TEXT in user
    assert TAIL_TOKEN in user
    assert HEAD_TOKEN not in user
    assert route_info["recap_input"]["input_mode"] == MODE_HYBRID
    assert route_info["recap_input"]["truncated"] is True
