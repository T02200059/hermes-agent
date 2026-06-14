"""Tests for owner.clarify.choice_normalizer."""

import pytest
from owner.clarify.choice_normalizer import (
    MAX_CHOICES,
    normalize_choice,
    normalize_choices,
    render_dict_choice,
)


class TestNormalizeChoice:
    def test_plain_string(self):
        assert normalize_choice("hello") == {"display": "hello", "key": "hello"}

    def test_strips_whitespace(self):
        assert normalize_choice("  world  ") == {"display": "world", "key": "world"}

    def test_empty_string_returns_none(self):
        assert normalize_choice("") is None
        assert normalize_choice("   ") is None

    def test_int_fallback(self):
        assert normalize_choice(42) == {"display": "42", "key": "42"}

    def test_bool_fallback(self):
        assert normalize_choice(True) == {"display": "True", "key": "True"}

    def test_dict_with_display_body(self):
        result = normalize_choice({"description": "A great option", "key": "opt1"})
        assert result == {"display": "opt1 — A great option", "key": "opt1"}

    def test_dict_body_only(self):
        result = normalize_choice({"content": "just content"})
        assert result == {"display": "just content", "key": None}

    def test_dict_identifier_only(self):
        result = normalize_choice({"label": "LABEL"})
        assert result == {"display": "LABEL", "key": "LABEL"}

    def test_dict_identifier_equals_body(self):
        result = normalize_choice({"key": "same", "value": "same"})
        assert result == {"display": "same", "key": "same"}

    def test_dict_nothing_useful(self):
        assert normalize_choice({}) is None
        assert normalize_choice({"unknown": 123}) is None

    def test_none_falls_back_to_str(self):
        assert normalize_choice(None) == {"display": "None", "key": "None"}


class TestNormalizeChoices:
    def test_normal_list(self):
        result = normalize_choices(["a", "b"])
        assert result == [
            {"display": "a", "key": "a"},
            {"display": "b", "key": "b"},
        ]

    def test_drops_empty_items(self):
        result = normalize_choices(["a", "", "   ", "b"])
        assert result is not None
        assert len(result) == 2

    def test_trims_to_max(self):
        long_list = [f"x{i}" for i in range(MAX_CHOICES + 3)]
        result = normalize_choices(long_list)
        assert result is not None
        assert len(result) == MAX_CHOICES

    def test_empty_list_returns_none(self):
        assert normalize_choices([]) is None
        assert normalize_choices(["", " "]) is None

    def test_none_returns_none(self):
        assert normalize_choices(None) is None

    def test_non_list_returns_none(self):
        assert normalize_choices("not_a_list") is None
        assert normalize_choices({"a": 1}) is None

    def test_mixed_types(self):
        result = normalize_choices([
            "plain",
            {"key": "k", "description": "desc"},
            True,
        ])
        assert result is not None
        assert len(result) == 3
        assert result[0] == {"display": "plain", "key": "plain"}
        assert result[2] == {"display": "True", "key": "True"}


class TestRenderDictChoice:
    def test_field_priority_content(self):
        d = {"description": "desc", "content": "cnt", "key": "k"}
        result = render_dict_choice(d)
        assert result is not None
        assert result["display"] == "k — desc"

    def test_field_fallback_next(self):
        d = {"content": "body text"}
        result = render_dict_choice(d)
        assert result is not None
        assert result["display"] == "body text"
        assert result["key"] is None

    def test_label_as_id(self):
        d = {"label": "lbl", "text": "txt"}
        result = render_dict_choice(d)
        assert result is not None
        assert result["display"] == "lbl — txt"
        assert result["key"] == "lbl"
