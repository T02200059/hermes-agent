"""Tests for owner/validation/merge_health_check.py helper logic."""

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
