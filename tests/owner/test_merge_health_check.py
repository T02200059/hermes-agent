"""Tests for owner/validation/merge_health_check.py helper logic."""

import ast

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
