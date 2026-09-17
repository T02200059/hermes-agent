"""Regression test: the ``transform_llm_output`` hook must sync the transcript.

When a plugin's ``transform_llm_output`` hook replaces the final response
(first non-empty string wins), only ``final_response`` — the text the user
sees — used to change.  The assistant row already written into ``messages``
kept the raw pre-transform text, so the durable transcript (and the next
turn's context) kept feeding the possibly degenerated output back to the
model (2026-09-01 incident: garbled output persisted and re-polluted).

The finalizer must rewrite the transcript tail when — and only when — it
still holds the exact pre-transform text.
"""

import pytest

from agent.turn_finalizer import finalize_turn


class _StubBudget:
    used = 5
    max_total = 3
    remaining = 5


class _StubCompressor:
    last_prompt_tokens = 0


class _StubAgent:
    """Minimal agent surface that ``finalize_turn`` reads from."""

    def __init__(self):
        self.max_iterations = 3
        self.iteration_budget = _StubBudget()
        self.context_compressor = _StubCompressor()
        self.model = "stub/model"
        self.provider = "stub"
        self.base_url = "http://stub"
        self.session_id = "sess-1"
        self.quiet_mode = True
        self.platform = "cli"
        self._interrupt_requested = False
        self._interrupt_message = None
        self._tool_guardrail_halt_decision = None
        self._response_was_previewed = False
        self._skill_nudge_interval = 0
        self._iters_since_skill = 0
        for attr in (
            "session_input_tokens",
            "session_output_tokens",
            "session_cache_read_tokens",
            "session_cache_write_tokens",
            "session_reasoning_tokens",
            "session_prompt_tokens",
            "session_completion_tokens",
            "session_total_tokens",
            "session_estimated_cost_usd",
        ):
            setattr(self, attr, 0)
        self.session_cost_status = "ok"
        self.session_cost_source = "stub"

    # --- fallible cleanup surfaces (no-ops) ------------------------------
    def _save_trajectory(self, *a, **k):
        pass

    def _cleanup_task_resources(self, *a, **k):
        pass

    def _drop_trailing_empty_response_scaffolding(self, *a, **k):
        pass

    def _persist_session(self, *a, **k):
        pass

    # --- harmless no-ops --------------------------------------------------
    def _emit_status(self, *a, **k):
        pass

    def _safe_print(self, *a, **k):
        pass

    def _handle_max_iterations(self, messages, n):
        return "PARTIAL SUMMARY FROM MODEL"

    def _file_mutation_verifier_enabled(self):
        return False

    def _turn_completion_explainer_enabled(self):
        return False

    def _drain_pending_steer(self):
        return None

    def clear_interrupt(self):
        pass

    def _sync_external_memory_for_turn(self, **k):
        pass


def _install_hook(monkeypatch, results):
    """Swap ``hermes_cli.lifecycle.invoke_hook`` for a canned registry.

    ``finalize_turn`` imports ``invoke_hook`` inside the function body, so
    patching the module attribute is picked up on every call.  Hooks other
    than the ones listed in *results* (``post_llm_call``, ``on_session_end``)
    return an empty result list, matching the no-plugin behaviour.
    """
    import hermes_cli.lifecycle as lifecycle

    def _fake_invoke_hook(hook_name, **kwargs):
        return list(results.get(hook_name, ()))

    monkeypatch.setattr(lifecycle, "invoke_hook", _fake_invoke_hook)


def _run(agent):
    """Finalize a clean two-message turn whose assistant tail already holds
    the raw (pre-transform) response text."""
    messages = [
        {"role": "user", "content": "do a thing"},
        {"role": "assistant", "content": "RAW_DEGENERATE_TEXT"},
    ]
    result = finalize_turn(
        agent,
        final_response="RAW_DEGENERATE_TEXT",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=messages,
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="do a thing",
        original_user_message="do a thing",
        _should_review_memory=False,
        _turn_exit_reason="text_response(done)",
    )
    return messages, result


def test_transform_hook_syncs_transcript_tail(monkeypatch):
    agent = _StubAgent()
    _install_hook(monkeypatch, {"transform_llm_output": ["CLEANED_TEXT"]})
    messages, result = _run(agent)

    # The user sees the cleaned text...
    assert result["final_response"] == "CLEANED_TEXT"
    assert result["response_transformed"] is True
    # ...and so does the durable transcript tail.
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == "CLEANED_TEXT"


def test_transform_hook_none_keeps_transcript(monkeypatch):
    agent = _StubAgent()
    # No plugin answered the hook: invoke_hook returns an empty list and
    # the transcript must keep the raw text verbatim.
    _install_hook(monkeypatch, {"transform_llm_output": []})
    messages, result = _run(agent)

    assert result["final_response"] == "RAW_DEGENERATE_TEXT"
    assert result["response_transformed"] is False
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == "RAW_DEGENERATE_TEXT"


def test_transform_hook_runs_before_persist(monkeypatch):
    """C2 (owner, 2026-09-17): the replacement must reach the durable write.

    Regression for the ordering bug behind the 2026-09-17 runaway stream: the
    hook ran *after* ``_persist_session``, so a transformed response only fixed
    the in-memory transcript while state.db kept the raw degenerate text and
    re-polluted the next session load. The finalizer must now apply the hook
    before it persists, and hand the flush a tail that no longer carries the
    ``_db_persisted`` marker (so a mid-turn blank row is repaired in place).
    """
    agent = _StubAgent()
    captured = {}

    def _capture(messages, conversation_history=None):
        captured["messages"] = [dict(m) for m in messages]

    agent._persist_session = _capture
    _install_hook(monkeypatch, {"transform_llm_output": ["CLEANED_TEXT"]})
    messages, result = _run(agent)

    assert result["final_response"] == "CLEANED_TEXT"
    assert captured.get("messages"), "_persist_session must have run"
    assert captured["messages"][-1]["content"] == "CLEANED_TEXT"
    assert not captured["messages"][-1].get("_db_persisted")


def test_transform_hook_runs_on_interrupted_turn(monkeypatch):
    """C1 (owner, 2026-09-17): an interrupted turn must still be inspected.

    A runaway thinking/output loop is normally ended *by* an interrupt, so the
    old ``not interrupted`` gate skipped the guard exactly in the scenario it
    exists to catch (the 2026-09-17 incident persisted 30,742 chars of loop and
    was only ever stopped by Ctrl-C). The hook must fire on interrupted turns
    and receive the interrupt flag — plus the reasoning channel — in its
    payload.
    """
    import hermes_cli.lifecycle as lifecycle

    agent = _StubAgent()
    seen = {}

    def _fake_invoke_hook(hook_name, **kwargs):
        seen[hook_name] = kwargs
        return ["CLEANED_TEXT"] if hook_name == "transform_llm_output" else []

    monkeypatch.setattr(lifecycle, "invoke_hook", _fake_invoke_hook)

    messages = [
        {"role": "user", "content": "do a thing"},
        {"role": "assistant", "content": "RAW_DEGENERATE_TEXT"},
    ]
    result = finalize_turn(
        agent,
        final_response="RAW_DEGENERATE_TEXT",
        api_call_count=1,
        interrupted=True,
        failed=False,
        messages=messages,
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="do a thing",
        original_user_message="do a thing",
        _should_review_memory=False,
        _turn_exit_reason="interrupted_during_api_call",
    )

    assert "transform_llm_output" in seen, "hook must fire on an interrupted turn"
    assert seen["transform_llm_output"]["interrupted"] is True
    assert "reasoning_text" in seen["transform_llm_output"]
    assert result["final_response"] == "CLEANED_TEXT"
    assert messages[-1]["content"] == "CLEANED_TEXT"
