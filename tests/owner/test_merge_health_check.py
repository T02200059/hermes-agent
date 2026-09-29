"""Tests for owner/validation/merge_health_check.py helper logic."""

import ast

import pytest

from owner.validation import merge_health_check as mhc


def test_deleted_marker_exact_survival_counts_as_resolved():
    deleted = "    # [owner] skill script auto-approval: if the command only runs scripts from"
    current = """
def check_all_command_guards():
    # [owner] skill script auto-approval: if the command only runs scripts from
    pass
"""

    assert mhc._deleted_owner_marker_has_surviving_glue(deleted, current)


def test_deleted_marker_owner_module_survival_counts_as_resolved():
    deleted = "    # [owner] display glue delegated to owner.display_overrides"
    current = """
from owner.display_overrides import resolve_per_chat_override

def resolve():
    return resolve_per_chat_override({}, "feishu", "chat", "tool_progress")
"""

    assert mhc._deleted_owner_marker_has_surviving_glue(deleted, current)


def test_deleted_marker_without_current_glue_is_unresolved():
    deleted = "    # [owner] skill script auto-approval: if the command only runs scripts from"
    current = """
def check_all_command_guards():
    return {"approved": True}
"""

    assert not mhc._deleted_owner_marker_has_surviving_glue(deleted, current)


def test_deleted_marker_diff_iterator_tracks_old_line_number():
    diff_text = """@@ -10,4 +10,3 @@
 context
-    # [owner] per-chat display override
+    value = fallback
 another context
"""

    assert mhc._iter_deleted_owner_marker_lines(diff_text) == [
        (11, "    # [owner] per-chat display override")
    ]


def test_top_level_names_include_annotated_constants():
    """An annotated module-level constant is an export like any other.

    The direct-``owner.*`` import check resolves imported symbols by parsing the
    target module and collecting its top-level names. Without ``AnnAssign`` an
    annotated constant is invisible, so ``gateway/run.py``'s CR-004 delegate —
    which imports ``OWNER_RAW_TEXT_PLATFORMS``, declared as
    ``OWNER_RAW_TEXT_PLATFORMS: FrozenSet[str] = ...`` — was reported as a
    broken import on every run: a standing false FAIL that could hide a real one.
    """
    tree = ast.parse("FLAG: bool = True\nPAIR: tuple = (1, 2)\nPLAIN = 3\n")

    assert mhc._get_top_level_names(tree) >= {"FLAG", "PAIR", "PLAIN"}


def test_top_level_names_still_cover_the_other_declaration_shapes():
    tree = ast.parse("import os\nfrom x import y as z\ndef f(): pass\nclass K: pass\n")

    assert mhc._get_top_level_names(tree) >= {"os", "z", "f", "K"}


# ---------------------------------------------------------------------------
# Check 8: modified official files must carry an [owner] marker
# ---------------------------------------------------------------------------


def test_generated_artifacts_are_excluded_from_marker_coverage():
    """A lockfile is rewritten wholesale, so a marker inside it is transient.

    Marking uv.lock would be worse than useless: ``uv lock`` wipes the marker on
    the next regeneration, and during a sync conflict the marker argues for
    keeping our generated lines instead of regenerating the file. The pin is
    tracked at its hand-authored source instead (pyproject.toml).
    """
    assert mhc._is_generated_artifact("uv.lock")
    assert mhc._is_generated_artifact("sub/dir/package-lock.json")

    assert not mhc._is_generated_artifact("gateway/delivery_ledger.py")
    assert not mhc._is_generated_artifact("locales/zh.yaml")


def test_upstream_base_resolves_to_a_full_commit_id():
    base = mhc._resolve_upstream_base()

    if base is None:
        pytest.skip("no upstream/main, origin/main or main ref in this checkout")

    assert len(base) == 40
    assert all(ch in "0123456789abcdef" for ch in base)


def test_every_modified_official_file_carries_an_owner_marker():
    """The guard behind T2-11.

    Resolving a fork sync means deciding per hunk whether a change is ours or
    upstream's, and the marker at the change site is the only signal that
    answers it. Before T2-11, 58 modified official files had no marker at all:
    merge 315551234 had already swallowed four markers that way (Check 5), and
    nothing in the suite noticed. Deleting any single marker here put a file
    back in that state -- which is why this asserts on the issue list, not on a
    count.
    """
    if mhc._resolve_upstream_base() is None:
        pytest.skip("no upstream base ref in this checkout")

    name, issues, examined, covered = mhc.check_changed_file_markers()

    assert examined > 0, f"{name}: resolved a base but found no modified official files"
    assert issues == [], f"{name}: {len(issues)} unmarked file(s): {issues}"
    assert covered == examined


# ---------------------------------------------------------------------------
# Check 6 / Check 7: anchors + inventory as pytest gates
# ---------------------------------------------------------------------------
#
# Both checks are pure file reads (0.13s together), yet they lived only inside
# the out-of-band health-check script -- so a regression could not surface in
# pytest, and any "green suite" claim silently excluded them.
#
# T2-14 hit exactly that: the card-action branch table moved out of
# ``plugins/platforms/feishu/adapter.py`` into ``owner/feishu/card_action.py``
# and left thin shells behind, which is a *deliberate, correct* refactor -- but
# ``anchors.yaml`` / ``inventory.yaml`` still pinned every dispatch anchor to the
# adapter. Check 6 went to 5 issues, Check 7 to 2, and the 134-path regression
# corpus (which does include this file) stayed green because nothing here ran
# them. The anchors are the registry of WHERE owner glue lives; when glue moves,
# the registry has to move with it, and only a gate makes that mandatory.


def test_critical_owner_anchors_all_resolve():
    """Check 6: every ``anchors.yaml`` entry still matches its target file."""
    name, issues, checked, total = mhc.check_critical_owner_anchors()

    assert total > 0, f"{name}: no anchor specs loaded -- anchors.yaml missing or malformed"
    assert checked == total, f"{name}: {total - checked} spec(s) could not be read: {issues}"
    assert issues == [], f"{name}: {len(issues)} missing anchor(s): {issues}"


def test_owner_inventory_static_checks_all_resolve():
    """Check 7: every ``inventory.yaml`` static check still holds."""
    name, issues, checks_run, items = mhc.check_validation_inventory()

    assert items > 0, f"{name}: no inventory items loaded -- inventory.yaml missing or malformed"
    assert checks_run > 0, f"{name}: inventory loaded but declared no static checks"
    assert issues == [], f"{name}: {len(issues)} broken static check(s): {issues}"


def test_the_card_action_branch_table_stays_registered():
    """The registry must keep *its* entry, not just stay internally consistent.

    ``test_critical_owner_anchors_all_resolve`` compares ``checked`` against
    ``total`` -- both derived from the file -- so deleting the anchor entry
    entirely silences it: 27 specs, 27 readable, zero issues. That is precisely
    the lazy fix for a stale anchor, and it silently drops the coverage the
    anchor was providing. So T2-14's migration is pinned by id here: the branch
    table must be registered against its new home, and the adapter entry must
    assert the *call into* it rather than the dispatch table itself.
    """
    specs, issues = mhc._load_anchor_specs()
    assert issues == []

    by_id = {spec["id"]: spec for spec in specs}
    branch_table = by_id.get("feishu-card-action-branch-table")
    assert branch_table is not None, "the card-action branch table lost its anchor entry"
    assert branch_table["file"] == "owner/feishu/card_action.py"
    # Each of the branch-table branches that only exist in our tree.
    assert {"owner.diff_card.feishu", "handle_feishu_diff_action"} <= set(branch_table["contains"])
    assert {"owner.feishu.resume_card", "owner.feishu.memory_approval"} <= set(branch_table["contains"])

    adapter = by_id.get("feishu-adapter-card-routes")
    assert adapter is not None
    assert adapter["file"] == "plugins/platforms/feishu/adapter.py"
    # The adapter keeps the thin shell and the wiring; the table itself is gone.
    assert {"owner.feishu.card_action", "dispatch_card_action"} <= set(adapter["contains"])
    assert "handle_feishu_diff_action" not in adapter["contains"]
