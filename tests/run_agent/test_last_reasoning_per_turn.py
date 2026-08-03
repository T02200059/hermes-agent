"""Tests for per-turn reasoning extraction in AIAgent.run_conversation.

Verifies the reasoning field returned to display layers (CLI reasoning box,
gateway reasoning footer, TUI reasoning event) only reflects the CURRENT
turn's reasoning — never leaks from a prior turn — and is picked up
correctly when reasoning is attached to a tool-calling assistant step
rather than the final-answer assistant step.

Also covers whitespace-only / single-space pad stubs (Kimi Coding Plan
builtin thinking + Hermes reasoning_content pad) so they never become
the 💭 display payload.
"""
from __future__ import annotations

from agent.agent_runtime_helpers import (
    displayable_reasoning,
    extract_last_turn_reasoning,
)


def _extract_last_reasoning(messages):
    """Use the production helper so refactors can't drift from tests."""
    return extract_last_turn_reasoning(messages)


def test_displayable_reasoning_filters_pad_and_whitespace():
    assert displayable_reasoning(None) is None
    assert displayable_reasoning("") is None
    assert displayable_reasoning(" ") is None
    assert displayable_reasoning("\n\t  \n") is None
    assert displayable_reasoning("real thought") == "real thought"
    assert displayable_reasoning("  real thought  ") == "real thought"


def test_simple_turn_reasoning_present():
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi", "reasoning": "greeting the user"},
    ]
    assert _extract_last_reasoning(messages) == "greeting the user"










def test_empty_string_reasoning_treated_as_missing():
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello", "reasoning": ""},
    ]
    assert _extract_last_reasoning(messages) is None


def test_space_pad_stub_skipped_for_earlier_real_reasoning():
    """Kimi Coding often pads later tool steps with reasoning=\" \".

    That stub must not win over earlier real thinking in the same turn,
    or Feishu show_reasoning renders a dirty one-character box.
    """
    messages = [
        {"role": "user", "content": "investigate thinking"},
        {
            "role": "assistant",
            "content": "",
            "reasoning": "Need to search the kimi provider code",
            "reasoning_content": "Need to search the kimi provider code",
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": "search_files", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "matches"},
        {
            "role": "assistant",
            "content": "",
            "reasoning": " ",
            "reasoning_content": " ",
            "tool_calls": [{"id": "c2", "type": "function",
                            "function": {"name": "read_file", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "c2", "content": "ok"},
        {"role": "assistant", "content": "Done", "reasoning": None},
    ]
    assert _extract_last_reasoning(messages) == "Need to search the kimi provider code"


def test_space_pad_only_turn_yields_none():
    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "reasoning": " ",
            "reasoning_content": " ",
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": "terminal", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
        {"role": "assistant", "content": "done", "reasoning": " "},
    ]
    assert _extract_last_reasoning(messages) is None


def test_falls_back_to_reasoning_content_when_display_field_missing():
    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "ok",
            "reasoning": None,
            "reasoning_content": "thought only on wire field",
        },
    ]
    assert _extract_last_reasoning(messages) == "thought only on wire field"
