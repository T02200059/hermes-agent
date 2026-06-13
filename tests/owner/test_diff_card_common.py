"""Tests for owner.diff_card.common helpers."""

from pathlib import Path

import pytest

from agent.display import LocalEditSnapshot
from owner.diff_card.common import (
    DIFF_CARD_TOOLS,
    basename_for_display,
    cache_get,
    cache_put,
    count_diff_changes,
    diff_card_emoji,
    diff_card_max_lines,
    display_file_path,
)


def test_diff_card_tools_does_not_include_unified_diff_patch():
    """unified_diff_patch is intentionally deferred until that tool is merged."""
    assert "patch" in DIFF_CARD_TOOLS
    assert "write_file" in DIFF_CARD_TOOLS
    assert "skill_manage" in DIFF_CARD_TOOLS
    assert "unified_diff_patch" not in DIFF_CARD_TOOLS


def test_diff_card_max_lines():
    assert diff_card_max_lines("patch") == 60
    assert diff_card_max_lines("write_file") == 10
    assert diff_card_max_lines("skill_manage") == 10
    assert diff_card_max_lines("unknown") == 10


def test_diff_card_emoji():
    assert diff_card_emoji("patch") == "🔧"
    assert diff_card_emoji("write_file") == "✍️"
    assert diff_card_emoji("skill_manage") == "📚"
    assert diff_card_emoji("other") == "📝"


def test_count_diff_changes():
    diff = (
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-old\n"
        "+new\n"
        " context\n"
    )
    assert count_diff_changes(diff) == (1, 1)


def test_count_diff_changes_ignores_headers():
    diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1,1 +1,1 @@\n--- not removed\n+++ not added\n"
    assert count_diff_changes(diff) == (0, 0)


def test_basename_for_display():
    assert basename_for_display("/path/to/file.py") == "file.py"
    assert basename_for_display("file.py") == "file.py"
    assert basename_for_display("") == "file"


def test_display_file_path_write_file():
    assert display_file_path("write_file", {"path": "foo.py"}, None, None) == "foo.py"


def test_display_file_path_patch():
    assert display_file_path("patch", {"path": "bar.py"}, None, None) == "bar.py"


def test_display_file_path_skill_manage_prefers_snapshot():
    snapshot = LocalEditSnapshot(paths=[Path("/skills/x/SKILL.md")])
    assert display_file_path("skill_manage", {"file_path": "SKILL.md"}, snapshot, None) == "/skills/x/SKILL.md"


def test_display_file_path_skill_manage_falls_back_to_file_path():
    assert display_file_path("skill_manage", {"file_path": "refs/a.md"}, None, None) == "refs/a.md"


def test_display_file_path_uses_result_files_modified():
    result = {"files_modified": ["/tmp/a.py", "/tmp/b.py"]}
    assert display_file_path("patch", {}, None, result) == "/tmp/a.py, /tmp/b.py"


def test_cache_put_and_get():
    cache = {}
    cache_put(cache, "k1", {"diff": "x"}, ttl=60)
    assert cache_get(cache, "k1") == {"diff": "x", "_ts": pytest.approx(cache["k1"]["_ts"]), "_ttl": 60}


def test_cache_get_expired():
    cache = {}
    cache_put(cache, "k1", {"diff": "x"}, ttl=0.001)
    import time
    time.sleep(0.002)
    assert cache_get(cache, "k1", ttl=0.001) is None
    assert "k1" not in cache


def test_cache_put_evicts_expired():
    cache = {}
    cache_put(cache, "old", {"diff": "x"}, ttl=0.001)
    import time
    time.sleep(0.002)
    cache_put(cache, "new", {"diff": "y"}, ttl=60)
    assert "old" not in cache
    assert "new" in cache
