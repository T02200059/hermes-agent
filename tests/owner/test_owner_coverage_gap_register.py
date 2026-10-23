"""Guard for the acknowledged test-coverage debt register (Check 7).

New-baseline owner test (2026-10-22). The register in
``owner/validation/coverage_gaps.txt`` records the eighteen divergences that lost
their behavioural coverage when the pre-fork owner suite was deleted
(``eee05c3090``, 2026-10-20). It exists so that "the test is gone" stays visible
instead of silently reading as "the behaviour is covered".

What this file pins, and why each assertion can actually fail:

* an undeclared missing test still FAILS (deleting the register line must not
  turn the demand green);
* a declared gap passes as debt, but a declaration whose test file exists again
  FAILS as stale (so the register can only shrink);
* a declaration naming an unknown item FAILS (dead entries cannot mask a future
  re-introduction);
* one missing file is reported once, even when the item also runs
  ``file_contains`` over it (no double-counting).

The first half drives ``check_validation_inventory`` against a throwaway repo
root, so it asserts the mechanism rather than today's repo state. The last test
runs the real inventory, which is what catches someone editing the live register
to silence a failure.
"""

import pathlib
import textwrap

import pytest

from owner.validation import merge_health_check as mhc


INVENTORY_TEMPLATE = """\
items:
  - id: demo-item
    title: "demo"
    category: test
    source: demo
    static_checks:
      - type: test_coverage
        path: tests/owner/test_demo.py
{extra}
"""

EXTRA_CONTAINS = """\
      - type: file_contains
        file: tests/owner/test_demo.py
        contains:
          - 'test_demo_contract'
"""


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """Point Check 7 at a throwaway repo root with its own inventory + register."""
    root = tmp_path
    (root / "tests/owner").mkdir(parents=True)
    (root / "owner/validation").mkdir(parents=True)

    inventory = root / "owner/validation/inventory.yaml"
    gaps = root / "owner/validation/coverage_gaps.txt"
    gaps.write_text("", encoding="utf-8")

    monkeypatch.setattr(mhc, "REPO_ROOT", root)
    monkeypatch.setattr(mhc, "INVENTORY_PATH", inventory)
    monkeypatch.setattr(mhc, "_COVERAGE_GAPS", gaps)

    def write_inventory(extra: str = "") -> None:
        inventory.write_text(INVENTORY_TEMPLATE.format(extra=extra), encoding="utf-8")

    def write_gaps(text: str) -> None:
        gaps.write_text(textwrap.dedent(text), encoding="utf-8")

    def write_test_file(body: str = "def test_demo_contract():\n    assert True\n") -> None:
        (root / "tests/owner/test_demo.py").write_text(body, encoding="utf-8")

    write_inventory()
    return {
        "root": root,
        "gaps": gaps,
        "write_inventory": write_inventory,
        "write_gaps": write_gaps,
        "write_test_file": write_test_file,
        "run": mhc.check_validation_inventory,
    }


def _issues(box):
    name, issues, _checks, _items, acknowledged = box["run"]()
    return issues, acknowledged


class TestUndeclaredGapFails:
    def test_missing_test_fails_when_not_declared(self, sandbox):
        issues, acknowledged = _issues(sandbox)
        assert len(issues) == 1
        assert "tests/owner/test_demo.py" in issues[0]
        assert "coverage_gaps.txt" in issues[0]
        assert acknowledged == {}

    def test_present_test_passes(self, sandbox):
        sandbox["write_test_file"]()
        issues, acknowledged = _issues(sandbox)
        assert issues == []
        assert acknowledged == {}


class TestDeclaredGapIsDebtNotSilence:
    def test_declared_gap_reports_debt_and_no_issue(self, sandbox):
        sandbox["write_gaps"]("demo-item  test deleted for a documented reason\n")
        issues, acknowledged = _issues(sandbox)
        assert issues == []
        assert acknowledged == {"demo-item": "test deleted for a documented reason"}

    def test_declaration_without_reason_is_malformed(self, sandbox):
        sandbox["write_gaps"]("demo-item\n")
        issues, _acknowledged = _issues(sandbox)
        assert any("malformed entry" in issue for issue in issues)

    def test_duplicate_declaration_is_reported(self, sandbox):
        sandbox["write_gaps"](
            "demo-item  first reason\n"
            "demo-item  second reason\n"
        )
        issues, _acknowledged = _issues(sandbox)
        assert any("duplicate entry" in issue for issue in issues)


class TestRegisterCanOnlyShrink:
    def test_restored_test_makes_declaration_stale(self, sandbox):
        sandbox["write_gaps"]("demo-item  was missing\n")
        sandbox["write_test_file"]()
        issues, acknowledged = _issues(sandbox)
        assert acknowledged == {}
        assert any("stale entry" in issue and "exists again" in issue for issue in issues)

    def test_unknown_item_id_is_stale(self, sandbox):
        sandbox["write_gaps"]("no-such-item  invented\n")
        issues, _acknowledged = _issues(sandbox)
        assert any(
            "stale entry" in issue and "no-such-item" in issue for issue in issues
        )


class TestNoDoubleReporting:
    def test_one_missing_file_yields_one_issue(self, sandbox):
        # The same item asserts existence *and* scans the file for needles. With
        # the file gone, only the existence check owns the message.
        sandbox["write_inventory"](EXTRA_CONTAINS)
        issues, _acknowledged = _issues(sandbox)
        assert len(issues) == 1, issues

    def test_needles_are_enforced_again_once_the_file_returns(self, sandbox):
        sandbox["write_inventory"](EXTRA_CONTAINS)
        sandbox["write_test_file"]("def test_something_else():\n    pass\n")
        issues, _acknowledged = _issues(sandbox)
        assert len(issues) == 1
        assert "missing 'test_demo_contract'" in issues[0]


class TestLiveRegister:
    """The real register, run against the real inventory."""

    def test_live_inventory_has_no_unmet_coverage_demand(self):
        _name, issues, _checks, _items, _acknowledged = mhc.check_validation_inventory()
        assert issues == [], issues

    def test_live_register_declares_the_deleted_owner_suite(self):
        gaps, gap_issues = mhc._load_coverage_gaps()
        assert gap_issues == []
        # Eighteen divergences lost their behavioural coverage on 2026-10-20.
        # Raising this number requires a reason per entry; lowering it requires
        # actually restoring that test (the stale-entry check enforces this).
        #
        # 18 -> 17 (2026-10-23): `feishu-auto-card-agent-end` was drained, not
        # edited away -- `tests/owner/test_feishu_agent_end_media.py` now pins the
        # media-before-card ordering, the MEDIA-tag leak, the no-media passthrough
        # and the MEDIA-only success/failure split. Writing it also surfaced a real
        # bug (the failed-delivery branch returned an already-cleared response, so
        # a media-only reply whose upload failed produced zero output).
        #
        # 17 -> 11 (2026-10-23): the six security-control gaps were drained as one
        # batch, because their failure mode is "a check that should deny starts
        # allowing" rather than "a display is wrong". Each new guard was
        # mutation-verified by disabling the specific gate it protects:
        #   - skill-script-auto-approval  -> tests/owner/test_skill_script_approval.py
        #     (5 gates; removing gate 2/3/4/5 turns 5/5/6/1 cases red)
        #   - cron-env-isolation          -> tests/owner/test_cron_session_contextvar_isolation.py
        #     (cross-thread leak + env scrub; reverting to the os.environ write turns 2 red)
        #   - model-extra-body-injection  -> tests/owner/test_extra_body_injection.py
        #     (allowlist bypass turns 4 red)
        #   - memory-synthetic-guard      -> tests/owner/patches/test_memory_synthetic_guard_patch.py
        #     (prefix widening + unguarded sync_all turn red)
        #   - file-tool-timeout           -> tests/owner/test_file_tool_timeout.py
        #     (blocking shutdown / global flag / 0-timeout each turn 1 red)
        #   - feishu-profile-routing      -> tests/owner/test_feishu_profile_routing.py
        #     (whitelist-in-group / chat-vs-user priority / ownership-strictness each turn red)
        # The remaining eleven are behaviour-correctness gaps (B/C groups); they stay
        # declared on purpose -- the register exists to keep silence visible, not to
        # be emptied.
        assert len(gaps) == 11, sorted(gaps)
        for item_id, reason in gaps.items():
            assert "removed 2026-10-20" in reason, item_id
