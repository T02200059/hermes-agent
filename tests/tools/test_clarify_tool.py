"""Tests for tools/clarify_tool.py - Interactive clarifying questions."""

import json
from typing import List, Optional


from tools.clarify_tool import (
    clarify_tool,
    check_clarify_requirements,
    MAX_CHOICES,
    CLARIFY_SCHEMA,
    CLARIFY_STOP_SENTINEL,
    ClarifyStopped,
    _flatten_choice,
)


class TestClarifyToolBasics:
    """Basic functionality tests for clarify_tool."""

    def test_simple_question_with_callback(self):
        """Should return user response for simple question."""
        def mock_callback(question: str, choices: Optional[List[str]]) -> str:
            assert question == "What color?"
            assert choices is None
            return "blue"

        result = json.loads(clarify_tool("What color?", callback=mock_callback))
        assert result["question"] == "What color?"
        assert result["choices_offered"] is None
        assert result["user_response"] == "blue"

    def test_question_with_choices(self):
        """Should pass choices to callback and return response.

        [owner] clarify: choices are normalized to ``{"display", "key"}``
        dicts by owner.clarify.choice_normalizer so platform adapters can
        render rich labels. For bare strings, display == key == the string.
        """
        def mock_callback(question: str, choices: Optional[List[str]]) -> str:
            assert question == "Pick a number"
            assert choices == [
                {"display": "1", "key": "1"},
                {"display": "2", "key": "2"},
                {"display": "3", "key": "3"},
            ]
            return "2"

        result = json.loads(clarify_tool(
            "Pick a number",
            choices=["1", "2", "3"],
            callback=mock_callback
        ))
        assert result["question"] == "Pick a number"
        assert result["choices_offered"] == [
            {"display": "1", "key": "1"},
            {"display": "2", "key": "2"},
            {"display": "3", "key": "3"},
        ]
        assert result["user_response"] == "2"

    def test_empty_question_returns_error(self):
        """Should return error for empty question."""
        result = json.loads(clarify_tool("", callback=lambda q, c: "ignored"))
        assert "error" in result
        assert "required" in result["error"].lower()

    def test_whitespace_only_question_returns_error(self):
        """Should return error for whitespace-only question."""
        result = json.loads(clarify_tool("   \n\t  ", callback=lambda q, c: "ignored"))
        assert "error" in result

    def test_no_callback_returns_error(self):
        """Should return error when no callback is provided."""
        result = json.loads(clarify_tool("What do you want?"))
        assert "error" in result
        assert "not available" in result["error"].lower()


class TestClarifyToolChoicesValidation:
    """Tests for choices parameter validation."""

    def test_choices_trimmed_to_max(self):
        """Should trim choices to MAX_CHOICES."""
        choices_passed = []

        def mock_callback(question: str, choices: Optional[List[str]]) -> str:
            choices_passed.extend(choices or [])
            return "picked"

        many_choices = ["a", "b", "c", "d", "e", "f", "g"]
        clarify_tool("Pick one", choices=many_choices, callback=mock_callback)

        assert len(choices_passed) == MAX_CHOICES

    def test_empty_choices_become_none(self):
        """Empty choices list should become None (open-ended)."""
        choices_received = ["marker"]

        def mock_callback(question: str, choices: Optional[List[str]]) -> str:
            choices_received.clear()
            if choices is not None:
                choices_received.extend(choices)
            return "answer"

        clarify_tool("Open question?", choices=[], callback=mock_callback)
        assert choices_received == []  # Was cleared, nothing added

    def test_choices_with_only_whitespace_stripped(self):
        """Whitespace-only choices should be stripped out.

        [owner] clarify: choices normalize to ``{"display", "key"}`` dicts;
        whitespace-only items drop out entirely (normalize_choice → None).
        """
        choices_received = []

        def mock_callback(question: str, choices: Optional[List[str]]) -> str:
            choices_received.extend(choices or [])
            return "answer"

        clarify_tool("Pick", choices=["valid", "  ", "", "also valid"], callback=mock_callback)
        assert choices_received == [
            {"display": "valid", "key": "valid"},
            {"display": "also valid", "key": "also valid"},
        ]

    def test_invalid_choices_type_returns_error(self):
        """Non-list choices should return error."""
        result = json.loads(clarify_tool(
            "Question?",
            choices="not a list",  # type: ignore
            callback=lambda q, c: "ignored"
        ))
        assert "error" in result
        assert "list" in result["error"].lower()

    def test_choices_converted_to_strings(self):
        """Non-string choices should be converted to display/key dicts.

        [owner] clarify: int/bool scalars coerce via ``str(c)`` so the
        normalized dict carries ``{"display": "1", "key": "1"}``.
        """
        choices_received = []

        def mock_callback(question: str, choices: Optional[List[str]]) -> str:
            choices_received.extend(choices or [])
            return "answer"

        clarify_tool("Pick", choices=[1, 2, 3], callback=mock_callback)  # type: ignore
        assert choices_received == [
            {"display": "1", "key": "1"},
            {"display": "2", "key": "2"},
            {"display": "3", "key": "3"},
        ]


class TestClarifyToolCallbackHandling:
    """Tests for callback error handling."""

    def test_callback_exception_returns_error(self):
        """Should return error if callback raises exception."""
        def failing_callback(question: str, choices: Optional[List[str]]) -> str:
            raise RuntimeError("User cancelled")

        result = json.loads(clarify_tool("Question?", callback=failing_callback))
        assert "error" in result
        assert "Failed to get user input" in result["error"]
        assert "User cancelled" in result["error"]


    def test_user_response_stripped(self):
        """User response should be stripped of whitespace."""
        def mock_callback(question: str, choices: Optional[List[str]]) -> str:
            return "  response with spaces  \n"

        result = json.loads(clarify_tool("Q?", callback=mock_callback))
        assert result["user_response"] == "response with spaces"

    def test_stop_sentinel_raises_clarify_stopped(self):
        """Gateway/Feishu timeout sentinel should stop the agent, not feed LLM."""
        def stop_callback(question: str, choices: Optional[List[str]]) -> str:
            return CLARIFY_STOP_SENTINEL

        try:
            clarify_tool("Q?", callback=stop_callback)
        except ClarifyStopped:
            return
        raise AssertionError("ClarifyStopped was not raised")

    def test_callback_raising_clarify_stopped_propagates(self):
        def stop_callback(question: str, choices: Optional[List[str]]) -> str:
            raise ClarifyStopped("stop")

        try:
            clarify_tool("Q?", callback=stop_callback)
        except ClarifyStopped:
            return
        raise AssertionError("ClarifyStopped was not propagated")


class TestCheckClarifyRequirements:
    """Tests for the requirements check function."""

    def test_always_returns_true(self):
        """clarify tool has no external requirements."""
        assert check_clarify_requirements() is True


class TestClarifyDictChoices:
    """Dict-shaped choices must be unwrapped to user-facing text at the source.

    LLMs sometimes emit [{"description": "..."}] instead of bare strings. The
    naive str(c) coercion leaked the Python dict repr onto every surface (CLI
    panel, Discord buttons, Telegram list) AND returned it verbatim as the
    user's answer. _flatten_choice normalises at the one platform-agnostic
    entry point so the whole class is fixed in one place.
    """

    def test_flatten_unwraps_label_first(self):
        assert _flatten_choice({"label": "Short", "description": "Long"}) == "Short"


    def test_dict_choices_reach_callback_as_clean_text(self):
        """The whole point: the UI callback never sees a dict repr.

        [owner] clarify: dict choices normalize to ``{"display", "key"}``
        via owner.clarify.choice_normalizer. The ``display`` field carries
        the user-facing label (most descriptive body field); ``key`` is the
        bare identifier (key/label) when present, else None so platforms
        fall back to sending display as the value.
        """
        seen = []

        def cb(question, choices):
            seen.extend(choices or [])
            return choices[0]["display"]

        result = json.loads(clarify_tool(
            "Pick a layout",
            choices=[
                {"choice": "Tight", "description": "Tight, covers all 3 points"},
                {"description": "Loose layout"},
                {"name": "modelid", "value": "abc"},  # not a clean label
                "A plain string choice",
            ],
            callback=cb,
        ))  # type: ignore
        # Each item is normalized to a {"display", "key"} dict — never a raw
        # Python dict repr landing on a button label.
        assert seen == [
            {"display": "Tight, covers all 3 points", "key": None},
            {"display": "Loose layout", "key": None},
            {"display": "abc", "key": None},
            {"display": "A plain string choice", "key": "A plain string choice"},
        ]
        # and the resolved answer is clean text, not a dict repr
        assert result["user_response"] == "Tight, covers all 3 points"
        assert "{" not in result["user_response"]
        assert all("{" not in c["display"] for c in result["choices_offered"])


class TestClarifySchema:
    """Tests for the OpenAI function-calling schema."""

    def test_schema_name(self):
        """Schema should have correct name."""
        assert CLARIFY_SCHEMA["name"] == "clarify"


    def test_max_choices_is_four(self):
        """MAX_CHOICES constant should be 4."""
        assert MAX_CHOICES == 4


    def test_schema_multi_select_default_false(self):
        """multi_select should default to false (not in required)."""
        # The model should treat it as false when omitted
        assert "multi_select" not in CLARIFY_SCHEMA["parameters"]["required"]


class TestClarifyToolMultiSelect:
    """Tests for multi_select (checkbox) support added to clarify_tool."""

    def test_multi_select_false_keeps_existing_behavior(self):
        """When multi_select=False, user_response should be a single string."""
        def mock_callback(question, choices):
            return "blue"

        result = json.loads(clarify_tool(
            "What color?",
            choices=["red", "blue", "green"],
            multi_select=False,
            callback=mock_callback,
        ))
        assert result["user_response"] == "blue"
        assert isinstance(result["user_response"], str)

    def test_multi_select_true_returns_list(self):
        """When multi_select=True, user_response should be a list of strings."""
        def mock_callback(question, choices):
            return "red, blue"

        result = json.loads(clarify_tool(
            "Which colors?",
            choices=["red", "blue", "green"],
            multi_select=True,
            callback=mock_callback,
        ))
        assert result["user_response"] == ["red", "blue"]
        assert isinstance(result["user_response"], list)

    def test_multi_select_single_choice_still_list(self):
        """Even a single selection should be a list when multi_select=True."""
        def mock_callback(question, choices):
            return "red"

        result = json.loads(clarify_tool(
            "Which color?",
            choices=["red", "blue"],
            multi_select=True,
            callback=mock_callback,
        ))
        assert result["user_response"] == ["red"]
        assert isinstance(result["user_response"], list)


    def test_multi_select_max_choices_enforced(self):
        """MAX_CHOICES enforcement should still work with multi_select."""
        choices_passed = []

        def mock_callback(question, choices):
            choices_passed.extend(choices or [])
            return "a, b, c, d"

        many_choices = ["a", "b", "c", "d", "e", "f"]
        clarify_tool(
            "Pick some",
            choices=many_choices,
            multi_select=True,
            callback=mock_callback,
        )
        assert len(choices_passed) == MAX_CHOICES


class TestInvokeCallbackDispatch:
    """_invoke_callback uses signature inspection, never a TypeError retry."""

    def test_internal_typeerror_not_swallowed_or_retried(self):
        """A compatible callback that raises TypeError internally must be
        invoked exactly once and its error surfaced — not retried with the
        legacy 2-arg form (which would prompt the user twice)."""
        from tools.clarify_tool import _invoke_callback
        calls = []

        def bad_callback(question, choices, multi_select=False):
            calls.append(1)
            raise TypeError("internal bug")

        import pytest
        with pytest.raises(TypeError, match="internal bug"):
            _invoke_callback(bad_callback, "Q?", ["a"], True)
        assert len(calls) == 1


    def test_var_keyword_callback_receives_flag(self):
        from tools.clarify_tool import _invoke_callback
        seen = {}

        def kw_cb(question, choices, **kwargs):
            seen.update(kwargs)
            return "ok"

        _invoke_callback(kw_cb, "Q?", ["a"], True)
        assert seen.get("multi_select") is True


class TestRegistryMultiSelectPassThrough:
    """The registered tool handler must forward multi_select from tool args."""

    def test_handler_passes_multi_select(self):
        from tools.registry import registry
        entry = registry.get_entry("clarify")
        seen = {}

        def cb(question, choices, multi_select=False):
            seen["multi"] = multi_select
            return "a, b"

        result = json.loads(entry.handler(
            {"question": "Pick", "choices": ["a", "b"], "multi_select": True},
            callback=cb,
        ))
        assert seen["multi"] is True
        assert result["user_response"] == ["a", "b"]

    def test_handler_default_single_select(self):
        from tools.registry import registry
        entry = registry.get_entry("clarify")
        seen = {}

        def cb(question, choices, multi_select=False):
            seen["multi"] = multi_select
            return "a"

        result = json.loads(entry.handler(
            {"question": "Pick", "choices": ["a", "b"]},
            callback=cb,
        ))
        assert seen["multi"] is False
        assert result["user_response"] == "a"
