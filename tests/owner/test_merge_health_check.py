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
