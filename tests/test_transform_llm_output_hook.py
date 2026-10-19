"""Tests for the ``transform_llm_output`` plugin hook.

The hook fires inside ``AIAgent.run_conversation`` once the tool-calling
loop has produced a final response. Driving the full agent loop from a
unit test would be prohibitively heavy, so these tests exercise the
invoke_hook dispatch semantics that the wiring in ``run_agent.py``
depends on:

    for _hook_result in _transform_results:
        if isinstance(_hook_result, str) and _hook_result:
            final_response = _hook_result
            break  # First non-empty string wins

Mirrors ``test_transform_tool_result_hook.py`` which tests the equivalent
contract for the generic tool-result seam.
"""

from pathlib import Path

import yaml

import hermes_cli.plugins as plugins_mod
from hermes_cli.plugins import PluginManager, VALID_HOOKS


def _make_enabled_plugin(hermes_home: Path, name: str, register_body: str) -> Path:
    """Create a plugin under <hermes_home>/plugins/<name> and opt it in."""
    plugin_dir = hermes_home / "plugins" / name
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text(
        yaml.safe_dump({"name": name, "version": "0.1.0"}), encoding="utf-8",
    )
    (plugin_dir / "__init__.py").write_text(
        "def register(ctx):\n"
        f"    {register_body}\n",
        encoding="utf-8",
    )
    cfg_path = hermes_home / "config.yaml"
    cfg = {}
    if cfg_path.exists():
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
    cfg.setdefault("plugins", {}).setdefault("enabled", []).append(name)
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return plugin_dir


def test_transform_llm_output_in_valid_hooks():
    assert "transform_llm_output" in VALID_HOOKS


def test_hook_receives_expected_kwargs(tmp_path, monkeypatch):
    """Hook callback should see response_text + session_id + model + platform."""
    hermes_home = tmp_path / "hermes_test"
    hermes_home.mkdir(exist_ok=True)
    _make_enabled_plugin(
        hermes_home, "capture_hook",
        register_body=(
            'ctx.register_hook("transform_llm_output", '
            'lambda **kw: f"{kw[\'response_text\']}|{kw[\'session_id\']}|'
            '{kw[\'model\']}|{kw[\'platform\']}")'
        ),
    )
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    mgr = PluginManager()
    mgr.discover_and_load()

    results = mgr.invoke_hook(
        "transform_llm_output",
        response_text="hello world",
        session_id="s1",
        model="anthropic/claude-sonnet-4.6",
        platform="cli",
    )
    assert results == ["hello world|s1|anthropic/claude-sonnet-4.6|cli"]






def test_hook_exception_does_not_replace_response(tmp_path, monkeypatch):
    """A plugin raising an exception must not break hook dispatch.

    PluginManager.invoke_hook catches per-callback exceptions, logs a
    warning, and continues — so a raising plugin contributes no entry
    to the results list, and the walk in run_agent.py finds nothing to
    replace with.
    """
    hermes_home = tmp_path / "hermes_test"
    hermes_home.mkdir(exist_ok=True)
    _make_enabled_plugin(
        hermes_home, "raising_hook",
        register_body=(
            'def _boom(**kw):\n'
            '        raise RuntimeError("boom")\n'
            '    ctx.register_hook("transform_llm_output", _boom)'
        ),
    )
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    mgr = PluginManager()
    mgr.discover_and_load()

    results = mgr.invoke_hook(
        "transform_llm_output",
        response_text="keep me",
        session_id="s1",
        model="m",
        platform="cli",
    )

    final_response = "keep me"
    for _hook_result in results:
        if isinstance(_hook_result, str) and _hook_result:
            final_response = _hook_result
            break

    assert final_response == "keep me"


def test_no_plugins_returns_empty_results(tmp_path, monkeypatch):
    """With no plugins loaded, invoke_hook returns [] and the response is unchanged."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes_empty"))
    plugins_mod._plugin_manager = PluginManager()

    mgr = plugins_mod._plugin_manager
    results = mgr.invoke_hook(
        "transform_llm_output",
        response_text="unchanged",
        session_id="",
        model="m",
        platform="",
    )
    assert results == []


# ---------------------------------------------------------------------------
# [owner] T3-18: the invocation was MOVED (C1/C2) — pin that it exists EXACTLY
# once. A future sync/merge could re-introduce upstream's original post-persist
# call site; two invocations would transform the response twice (and fire the
# C2 transcript sync twice). The old position keeps only a comment block.
# ---------------------------------------------------------------------------


def _count_transform_invocations(source: str) -> int:
    """Count ``invoke_hook("transform_llm_output", ...)`` call sites via AST."""
    import ast as _ast

    tree = _ast.parse(source)
    count = 0
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.Call):
            continue
        fname = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if fname not in ("invoke_hook", "_invoke_hook") or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, _ast.Constant) and first.value == "transform_llm_output":
            count += 1
    return count


def test_transform_hook_invoked_exactly_once_in_turn_finalizer():
    from pathlib import Path as _Path

    repo = _Path(__file__).resolve().parents[1]
    src = (repo / "agent" / "turn_finalizer.py").read_text(encoding="utf-8")
    assert _count_transform_invocations(src) == 1, (
        "transform_llm_output must be invoked exactly once in turn_finalizer "
        "(moved before persist by C1/C2 — see the MOVED comment block). Two "
        "sites would double-transform the response; zero would disable the "
        "degenerate-stream guard's durable-write fix."
    )
    # the MOVED tombstone comment must remain so the next sync reviewer sees it
    assert "transform_llm_output — MOVED" in src


def test_transform_hook_not_gated_on_interrupted():
    """[owner] C1: the hook must fire even for interrupted turns — a runaway
    stream is almost always ended BY an interrupt, and gating on ``not
    interrupted`` (upstream's old position) skipped the guard exactly when it
    was needed. Assert no enclosing ``if`` gate references ``interrupted``.

    (The call itself passes ``interrupted=bool(...)`` as a kwarg so the hook can
    see the state — that is expected and is NOT a gate; only ancestor If-tests
    count here.)
    """
    from pathlib import Path as _Path

    repo = _Path(__file__).resolve().parents[1]
    src = (repo / "agent" / "turn_finalizer.py").read_text(encoding="utf-8")
    import ast as _ast

    tree = _ast.parse(src)
    for node in _ast.walk(tree):
        for child in _ast.iter_child_nodes(node):
            child._parent = node

    call = None
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.Call):
            continue
        fname = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if fname not in ("invoke_hook", "_invoke_hook") or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, _ast.Constant) and first.value == "transform_llm_output":
            call = node
            break
    assert call is not None, "transform_llm_output invocation not found"

    n = call
    while hasattr(n, "_parent"):
        n = n._parent
        if isinstance(n, _ast.If):
            gate = _ast.unparse(n.test)
            assert "interrupted" not in gate, (
                f"transform_llm_output is gated by `if {gate}` — the C1 move "
                f"requires it to fire on interrupted turns too"
            )
