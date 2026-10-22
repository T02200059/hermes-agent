"""Guard: the queued reply lane goes through the delivery-ledger bracket.

New-baseline owner test (2026-10-22). Not an owner/localization divergence — it
pins a contract this fork has to supply itself.

Why the fork owns it: T2-20 rewrote `gateway/run_*.py` from upstream but, by the
"replace no dependency file" decision, left `gateway/platforms/base.py` on the
fork-point version. Upstream had meanwhile added `send_final_ledgered` (a
refactor that extracted the ledger bracket out of `_deliver_response` so the
queued lane could reuse it). The rewritten caller had the call, the base class
had no such method, and `_send_queued_final_text`'s `isinstance(adapter,
BasePlatformAdapter)` guard ensured every real platform took the AttributeError
path — silently, since the caller logs a warning and moves on.

So a queued-lane final reply (a follow-up processed while another turn was
running) never reached the user. The three behaviour tests in
`tests/gateway/test_run_progress_topics.py` caught it, but they only assert
"something was sent": restoring the bare `adapter.send` fallback for the
session-key path would turn them green again without the ledger row. That is
what this file pins.

Every assertion here fails if the owner-side work is undone:

* delete `send_final_ledgered` from the base class     -> the hasattr checks fail
* route the queued lane back to a bare `adapter.send`   -> the AST check fails
* record without finalizing                             -> the obligation check fails
"""

import ast
import pathlib

import pytest

from gateway.platforms.base import BasePlatformAdapter


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
QUEUED_LANE_SOURCE = REPO_ROOT / "gateway" / "run_notifications.py"
QUEUED_LANE_FUNC = "_send_queued_final_text"


def _queued_lane_function() -> ast.AsyncFunctionDef:
    tree = ast.parse(QUEUED_LANE_SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == QUEUED_LANE_FUNC:
            return node
    raise AssertionError(f"{QUEUED_LANE_FUNC} not found in {QUEUED_LANE_SOURCE.name}")


class TestBaseClassContract:
    @pytest.mark.parametrize(
        "method",
        [
            "send_final_ledgered",
            "_record_delivery_obligation",
            "_finalize_delivery_obligation",
        ],
    )
    def test_ledger_bracket_exists_on_the_base_adapter(self, method):
        # The caller reaches these through a real adapter instance, which is always a
        # BasePlatformAdapter subclass — so a missing definition is not a subclass gap,
        # it is a hard AttributeError on every platform.
        assert hasattr(BasePlatformAdapter, method), method
        assert callable(getattr(BasePlatformAdapter, method)), method

    def test_send_final_ledgered_takes_the_caller_signature(self):
        import inspect

        params = inspect.signature(BasePlatformAdapter.send_final_ledgered).parameters
        for name in ("event", "session_key", "text_content", "metadata", "reply_to"):
            assert name in params, name
        assert params["reply_to"].kind is inspect.Parameter.KEYWORD_ONLY

    def test_send_final_ledgered_records_and_finalizes(self):
        # Both halves matter: recording without finalizing leaves every send stuck in
        # "attempting" and the boot sweep re-delivers replies that already arrived.
        source = ast.get_source_segment(
            _read_base_source(), _find_def(BasePlatformAdapter.__name__ + ".send_final_ledgered"))
        assert "_record_delivery_obligation" in source
        assert "_finalize_delivery_obligation" in source


class TestQueuedLaneUsesTheBracket:
    def test_queued_lane_calls_send_final_ledgered(self):
        func = _queued_lane_function()
        called = {
            node.func.attr
            for node in ast.walk(func)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "send_final_ledgered" in called

    def test_queued_lane_keeps_a_plain_send_only_as_the_non_ledger_fallback(self):
        # The fallback is legitimate for adapters without the base contract and for
        # sends with no session key. What must not happen is the ledger path being
        # replaced by it wholesale — which is exactly the "make the red tests green"
        # move this file exists to block.
        func = _queued_lane_function()
        has_base_guard = False
        for node in ast.walk(func):
            if not isinstance(node, ast.If):
                continue
            for inner in ast.walk(node.test):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Name)
                    and inner.func.id == "isinstance"
                ):
                    has_base_guard = True
        assert has_base_guard, "no isinstance(...) guard around the ledger path"


def _read_base_source() -> str:
    return (REPO_ROOT / "gateway" / "platforms" / "base.py").read_text(encoding="utf-8")


def _find_def(qualified_name: str) -> ast.AST:
    method = qualified_name.split(".", 1)[1]
    tree = ast.parse(_read_base_source())
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == method:
            return node
    raise AssertionError(f"{method} not found")
