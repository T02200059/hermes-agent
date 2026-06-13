"""Tests for unified_diff_patch tool strict mode + path resolution behavior."""
import json
import pytest
from tools.unified_diff_patch_tool import parse_unified_diff, unified_diff_patch_tool


# ===== strict mode: line-count handling =====

def test_lenient_mode_treats_blank_line_in_hunk_body_as_context():
    """Default: blank lines in hunk body are silently treated as context."""
    diff = (
        "--- a/test.py\n"
        "+++ b/test.py\n"
        "@@ -1,3 +1,4 @@\n"
        " line1\n"
        "+new line\n"
        "\n"          # truly blank line (no leading space)
        " line3\n"
    )
    fps, err = parse_unified_diff(diff, strict=False)
    assert err is None
    assert len(fps) == 1
    assert len(fps[0].hunks[0].old_lines) == 3
    assert len(fps[0].hunks[0].new_lines) == 4


def test_strict_mode_rejects_blank_line_in_hunk_body():
    """Strict: blank lines in hunk body are rejected with a precise error."""
    diff = (
        "--- a/test.py\n"
        "+++ b/test.py\n"
        "@@ -1,3 +1,4 @@\n"
        " line1\n"
        "+new line\n"
        "\n"          # blank line — would be silently accepted in lenient mode
        " line3\n"
    )
    fps, err = parse_unified_diff(diff, strict=True)
    assert fps == []
    assert err is not None
    assert "Strict parse error" in err
    assert "empty line without a leading space" in err
    assert "hunk 1" in err


def test_strict_mode_rejects_bare_line_in_hunk_body():
    """Strict: bare lines (no space/+/-/\\) are rejected with a precise error."""
    diff = (
        "--- a/test.py\n"
        "+++ b/test.py\n"
        "@@ -1,3 +1,4 @@\n"
        " line1\n"
        "+new line\n"
        "bareline\n"  # no leading space
        " line3\n"
    )
    fps, err = parse_unified_diff(diff, strict=True)
    assert fps == []
    assert err is not None
    assert "Strict parse error" in err
    assert "bare line" in err


def test_strict_mode_accepts_well_formed_diff():
    """Strict: a properly formatted diff (all lines have a leading space/+/-) passes."""
    diff = (
        "--- a/test.py\n"
        "+++ b/test.py\n"
        "@@ -1,2 +1,3 @@\n"
        " line1\n"
        "+new line\n"
        " line2\n"
    )
    fps, err = parse_unified_diff(diff, strict=True)
    assert err is None
    assert len(fps) == 1
    assert len(fps[0].hunks) == 1


def test_line_count_mismatch_reported_in_both_modes():
    """Line-count mismatches are reported regardless of strict mode."""
    diff = (
        "--- a/test.py\n"
        "+++ b/test.py\n"
        "@@ -1,3 +1,3 @@\n"  # header says 3/3 but body has 4 lines
        " line1\n"
        " line2\n"
        "+new line\n"
        " line3\n"
        " line4\n"
    )
    # lenient: still reports mismatch when auto_fix_header is disabled
    _, err_lenient = parse_unified_diff(diff, strict=False, auto_fix_header=False)
    assert "mismatch" in err_lenient
    # strict: also reports mismatch when auto_fix_header is disabled
    _, err_strict = parse_unified_diff(diff, strict=True, auto_fix_header=False)
    assert "mismatch" in err_strict


# ===== Fix #4: strict errors are NOT swallowed by line-count mismatch =====

def test_strict_error_takes_precedence_over_count_mismatch():
    """A patch with both a bare line AND a count mismatch should report the
    strict error first (it's the root cause; the count mismatch is a symptom)."""
    diff = (
        "--- a/test.py\n"
        "+++ b/test.py\n"
        "@@ -1,3 +1,3 @@\n"  # header says 3/3
        " line1\n"
        " line2\n"
        "line3\n"     # BARE: no leading space
        " line4\n"     # extra context line -> count mismatch
    )
    fps, err = parse_unified_diff(diff, strict=True)
    assert fps == []
    assert err is not None
    assert "Strict parse error" in err, f"Expected strict error first, got: {err}"
    assert "bare line" in err
    # The count-mismatch message must NOT be present
    assert "line count mismatch" not in err, f"Count mismatch leaked: {err}"


# ===== Fix #4b: strict mode errors include the hunk body line number =====

def test_strict_error_includes_body_line_number():
    """Strict error messages must pinpoint the offending line in the hunk body."""
    diff = (
        "--- a/test.py\n"
        "+++ b/test.py\n"
        "@@ -1,4 +1,5 @@\n"
        " line1\n"
        " line2\n"
        "line3\n"     # BARE at body line 3
        " line4\n"
    )
    fps, err = parse_unified_diff(diff, strict=True)
    assert err is not None
    assert "line 3" in err, f"Expected 'line 3' in error, got: {err}"

    # Same for empty line (no leading space)
    diff_empty = (
        "--- a/test.py\n"
        "+++ b/test.py\n"
        "@@ -1,4 +1,5 @@\n"
        " line1\n"
        "\n"          # EMPTY at body line 2
        " line3\n"
        " line4\n"
    )
    fps, err = parse_unified_diff(diff_empty, strict=True)
    assert err is not None
    assert "line 2" in err, f"Expected 'line 2' in error, got: {err}"


# ===== Fix #6: CRLF and CR line endings are normalized =====

def test_crlf_line_endings_normalized():
    """\r\n endings must be normalized so context matching works."""
    diff = "--- a/test.py\r\n+++ b/test.py\r\n@@ -1,2 +1,3 @@\r\n line1\r\n+new\r\n line2\r\n"
    fps, err = parse_unified_diff(diff)
    assert err is None, f"CRLF parsing failed: {err}"
    assert len(fps) == 1
    h = fps[0].hunks[0]
    # Lines must NOT have trailing \r
    assert h.old_lines == ["line1", "line2"], f"old_lines has \r: {h.old_lines!r}"
    assert h.new_lines == ["line1", "new", "line2"], f"new_lines has \r: {h.new_lines!r}"


def test_cr_only_line_endings_normalized():
    """\r-only endings (old Mac) must be normalized."""
    diff = "--- a/test.py\r+++ b/test.py\r@@ -1,2 +1,3 @@\r line1\r+new\r line2\r"
    fps, err = parse_unified_diff(diff)
    assert err is None, f"CR-only parsing failed: {err}"
    assert len(fps) == 1
    h = fps[0].hunks[0]
    assert h.old_lines == ["line1", "line2"]


# ===== Fix #8: dry_run parameter =====

@pytest.fixture
def dry_run_sandbox(tmp_path, monkeypatch):
    """Create a temp file and set TERMINAL_CWD to its parent directory.

    On macOS, /tmp/ resolves to /private/var/folders/... which the file
    tool's sensitive-path guard rejects. We monkeypatch the guard to a
    no-op for the duration of the test so we can exercise the dry-run
    logic against a real file.
    """
    from tools import file_tools
    monkeypatch.setattr(
        file_tools, "_check_sensitive_path", lambda filepath, task_id="default": None
    )
    monkeypatch.setattr(
        file_tools, "_check_cross_profile_path", lambda filepath, task_id="default": None
    )
    target = tmp_path / "sample.py"
    target.write_text("line1\nline2\nline3\nline4\n")
    monkeypatch.setenv("TERMINAL_CWD", str(tmp_path))
    return target


def test_dry_run_does_not_modify_file(dry_run_sandbox):
    """dry_run=True must NOT modify the target file."""
    target = dry_run_sandbox
    original = target.read_text()
    original_mtime = target.stat().st_mtime
    patch = (
        f"--- {target}\n"
        f"+++ {target}\n"
        "@@ -1,3 +1,4 @@\n"
        " line1\n"
        "+inserted\n"
        " line2\n"
        " line3\n"
    )
    result = json.loads(unified_diff_patch_tool(patch=patch, dry_run=True, strict=True))
    assert result["_dry_run"] is True
    assert result["success"] is True
    assert result["files_modified"] == []
    assert result["files_created"] == []
    assert result["files_deleted"] == []
    # File must be byte-identical
    assert target.read_text() == original
    assert target.stat().st_mtime == original_mtime


def test_dry_run_reports_context_mismatch_without_writing(dry_run_sandbox):
    """dry_run=True must still report context mismatches and NOT write the file."""
    target = dry_run_sandbox
    original = target.read_text()
    bad_patch = (
        f"--- {target}\n"
        f"+++ {target}\n"
        "@@ -1,2 +1,3 @@\n"
        " line1\n"
        "+inserted\n"
        " WRONG\n"  # doesn't match "line2"
    )
    result = json.loads(unified_diff_patch_tool(patch=bad_patch, dry_run=True, strict=True))
    assert result["_dry_run"] is True
    assert result["success"] is False
    assert "context mismatch" in result["error"]
    # File must still be unchanged
    assert target.read_text() == original


def test_dry_run_real_apply_actually_writes(dry_run_sandbox):
    """Sanity check: the real path (dry_run=False) still writes the file."""
    target = dry_run_sandbox
    patch = (
        f"--- {target}\n"
        f"+++ {target}\n"
        "@@ -1,3 +1,4 @@\n"
        " line1\n"
        "+inserted\n"
        " line2\n"
        " line3\n"
    )
    result = json.loads(unified_diff_patch_tool(patch=patch, dry_run=False, strict=True))
    assert result.get("_dry_run") is not True  # absent OR not True both pass
    assert result["success"] is True
    assert len(result["files_modified"]) == 1
    assert "inserted" in target.read_text()
