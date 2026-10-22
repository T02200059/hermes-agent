"""Owner-branch regression guards — new baseline (2026-10-22 onward).

These tests are **not** the historical owner suite. The 715 owner-only test
files that existed before 2026-10-20 were deleted (`eee05c3090`) because they
encoded pre-fork product expectations and masked real gaps; the suite was
reset to the pure upstream baseline. From 2026-10-22 onward, a new owner test
is added **only** alongside a deliberate, documented owner divergence, and it
exists to pin the divergence so an upstream sync cannot silently revert it.

Rule of thumb for anything added here: if the assertion would still hold
after deleting the owner code it claims to protect, it is not a guard.

First entry: §7.9 (429 quota wall) — see `owner/docs/owner改动清单.md`.
"""

from types import SimpleNamespace

import pytest
from agent.error_classifier import (
    FailoverReason,
    _has_long_reset_window,
    classify_api_error,
)


class MockAPIError(Exception):
    """Simulates an OpenAI SDK APIStatusError (upstream test double shape)."""

    def __init__(self, message, status_code=None, body=None, headers=None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body or {}
        self.response = SimpleNamespace(headers=headers or {})


def _classify(message, *, provider="opencode-go", body=None, headers=None):
    err = MockAPIError(message, status_code=429, body=body, headers=headers)
    return classify_api_error(err, provider=provider, model="test-model")


class TestLongResetWindowMatcher:
    """Unit surface of the narrow matcher, independent of the 429 pipeline."""

    @pytest.mark.parametrize(
        "message",
        [
            "Weekly usage limit reached. Resets in 2 days.",
            "usage limit reached; resets in 3 days",
            "quota exhausted, reset after 2 weeks",
            "Usage limit reached, Resets In 1 Day",
            "usage limit reached, resets in 10 DAYS",
            "rate budget spent; resets after 1 week",
        ],
    )
    def test_matches_day_and_week_horizons(self, message):
        assert _has_long_reset_window(message) is True

    @pytest.mark.parametrize(
        "message",
        [
            # Sub-day horizons are waitable inside the 600s Retry-After cap.
            "Weekly usage limit reached. Resets in 6hr 29min.",
            "usage limit reached, reset after 3600s",
            "usage limit reached, available in 42 minutes",
            "usage limit reached; resets at 2026-08-24T10:00:00Z",
            # Time-of-day wording that carries no day/week count.
            "usage limit reached, resets tomorrow",
            # A duration that merely mentions days without naming a reset.
            "You have 3 days of usage remaining",
            # No horizon at all.
            "usage limit reached",
        ],
    )
    def test_ignores_anything_else(self, message):
        assert _has_long_reset_window(message) is False


class TestQuotaWallStaysTerminal:
    """§7.9 motivation: a day/week wall must not enter the retry loop.

    The loop caps ``Retry-After`` at 600s, so such a wall can never be
    outwaited — retrying only burns attempts and delays the visible error.
    """

    @pytest.mark.parametrize(
        "message",
        [
            "Weekly usage limit reached. Resets in 2 days.",
            "usage limit reached; resets in 3 days",
            "quota exhausted, reset after 2 weeks",
        ],
    )
    def test_day_or_week_wall_is_non_retryable_billing(self, message):
        result = _classify(message)
        assert result.reason == FailoverReason.billing
        assert result.retryable is False
        assert result.should_rotate_credential is True
        assert result.should_fallback is True

    def test_wall_wins_even_when_provider_also_sends_retry_after(self):
        # A provider that states a multi-day wall in the body and a matching
        # Retry-After in the header must not be treated as waitable.
        result = _classify(
            "Weekly usage limit reached. Resets in 2 days.",
            headers={"Retry-After": "172800"},
        )
        assert result.reason == FailoverReason.billing
        assert result.retryable is False


class TestWaitableWindowsStayTransient:
    """The narrowing must not swallow genuinely retryable 429s.

    Mirrors the shape of the upstream cases that the pre-2026-10-22 owner
    block used to fail, so a re-introduction of that block turns these red.
    """

    @pytest.mark.parametrize(
        "message",
        [
            "Weekly usage limit reached. Resets in 6hr 29min.",
            "usage limit reached, reset after 3600s",
            "usage limit reached, available in 42 minutes",
            "usage limit reached; 20 requests per minute",
        ],
    )
    def test_message_level_short_horizon_is_rate_limit(self, message):
        result = _classify(message, provider="anthropic")
        assert result.reason == FailoverReason.rate_limit
        assert result.retryable is True

    def test_iso_timestamp_in_body_text_is_rate_limit(self):
        result = _classify(
            "usage limit reached; resets at 2026-08-24T10:00:00Z",
            provider="anthropic",
        )
        assert result.reason == FailoverReason.rate_limit

    @pytest.mark.parametrize(
        "field,value",
        [
            ("resets_in_seconds", 3600),
            ("resets_at", "2026-08-24T10:00:00Z"),
            ("reset_at", "2026-08-24T10:00:00Z"),
            ("retry_after", 3600),
        ],
    )
    def test_structured_reset_field_in_body_is_rate_limit(self, field, value):
        # The owner narrowing inspects message text only; a structured reset
        # field must therefore keep upstream's transient verdict.
        result = _classify(
            "usage limit reached",
            provider="anthropic",
            body={"error": {"type": "usage_limit_reached", field: value}},
        )
        assert result.reason == FailoverReason.rate_limit

    @pytest.mark.parametrize("header", ["Retry-After", "x-ratelimit-reset"])
    def test_reset_response_header_is_rate_limit(self, header):
        result = _classify(
            "usage limit reached",
            provider="anthropic",
            headers={header: "3600"},
        )
        assert result.reason == FailoverReason.rate_limit


class TestUpstreamVerdictsPreserved:
    """Owner narrowing is subtractive only — it must never upgrade to billing.

    Each case below already produced this verdict upstream; if one flips, the
    narrowing has grown beyond its documented scope.
    """

    def test_bare_usage_limit_without_horizon_is_billing_upstream(self):
        result = _classify("usage limit reached", provider="anthropic")
        assert result.reason == FailoverReason.billing
        assert result.retryable is False

    def test_explicit_credit_exhaustion_is_billing(self):
        result = _classify(
            "insufficient credit balance on this account",
            provider="anthropic",
        )
        assert result.reason == FailoverReason.billing

    @pytest.mark.parametrize(
        "message",
        [
            "Rate limit exceeded, please slow down.",
            "Too many requests; rate_limit hit.",
        ],
    )
    def test_explicit_rate_limit_phrase_wins(self, message):
        result = _classify(message, provider="anthropic")
        assert result.reason == FailoverReason.rate_limit
        assert result.retryable is True

    @pytest.mark.parametrize(
        "message",
        [
            # An explicit rate-limit phrase outranks the wall wording: it is
            # upstream's documented precedence and the narrowing must respect it.
            "Rate limit exceeded; resets in 2 days.",
            "Too many requests; resets in 3 days",
        ],
    )
    def test_explicit_rate_limit_phrase_outranks_day_wording(self, message):
        result = _classify(message)
        assert result.reason == FailoverReason.rate_limit
        assert result.retryable is True


class TestNoSecondBillingBranch:
    """Structural guard against re-porting a self-contained disambiguation block.

    The pre-2026-10-22 owner code ran its own "usage limit without a short
    window" test at the top of the 429 branch and returned billing before any
    upstream logic — which is what made nine upstream cases fail. The narrowed
    hook reintroduces no second decision point, so the 429 branch must contain
    exactly one ``FailoverReason.billing`` return: upstream's.
    """

    @staticmethod
    def _billing_returns_in_429_branch():
        import ast
        from pathlib import Path

        source = Path("agent/error_classifier.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if node.name != "_classify_by_status":
                continue
            for sub in ast.walk(node):
                if not isinstance(sub, ast.If):
                    continue
                # Match ``if status_code == 429:``
                test = sub.test
                if not isinstance(test, ast.Compare):
                    continue
                if not (
                    isinstance(test.left, ast.Name)
                    and test.left.id == "status_code"
                    and len(test.comparators) == 1
                    and isinstance(test.comparators[0], ast.Constant)
                    and test.comparators[0].value == 429
                ):
                    continue
                count = 0
                for inner in ast.walk(sub):
                    if not isinstance(inner, ast.Call):
                        continue
                    if not (isinstance(inner.func, ast.Name) and inner.func.id == "result_fn"):
                        continue
                    if not inner.args:
                        continue
                    first = inner.args[0]
                    if (
                        isinstance(first, ast.Attribute)
                        and first.attr == "billing"
                        and isinstance(first.value, ast.Name)
                        and first.value.id == "FailoverReason"
                    ):
                        count += 1
                return count
        raise AssertionError("_classify_by_status / `if status_code == 429:` not found")

    def test_429_branch_has_single_billing_return(self):
        assert self._billing_returns_in_429_branch() == 1
