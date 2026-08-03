#!/usr/bin/env python3
"""Audit whether an owner←main merge dropped local code or orphaned owner glue.

Compares three trees (defaults suitable for a probe worktree after merge):

  BASE   = merge-base(OWNER_REF, MAIN_REF)
  OWNER  = pre-merge owner tip (local work still "should" be here)
  HEAD   = post-merge tip (what we are auditing)

Reports:

  A. Volume — how many lines / markers / owner-glue files each side owns
  B. Loss   — owner-unique fingerprints (markers, imports, anchors) missing at HEAD
  C. Arch   — upstream architectural renames that can turn owner glue into dead code
  D. Orphan — owner/* modules with zero external references outside owner/

Usage:
  python owner/validation/merge_loss_audit.py
  python owner/validation/merge_loss_audit.py --owner-ref owner --main-ref main --head-ref HEAD
  python owner/validation/merge_loss_audit.py --json /tmp/audit.json

Exit 0 = no FAIL (WARN OK); 1 = any FAIL.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
ANCHORS_PATH = SCRIPT_DIR / "anchors.yaml"

EXCLUDE_DIR_NAMES = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    "web_dist",
    "ui-tui/node_modules",
}

# Lines that identify owner glue when scanning official (non-owner/) trees.
GLUE_LINE_RE = re.compile(
    r"("
    r"\[owner(?:-patch)?\]"
    r"|_owner_import\s*\("
    r"|from\s+owner[\.\s]"
    r"|import\s+owner[\.\s]"
    r"|owner\.[A-Za-z_][A-Za-z0-9_\.]*"
    r"|owner_provider_name"
    r")"
)

# Pure-comment / noise tokens for fingerprinting.
_TOKEN_STOP = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
    "when",
    "into",
    "see",
    "via",
    "not",
    "owner",
    "patch",
    "import",
    "return",
    "true",
    "false",
    "none",
    "self",
    "try",
    "except",
    "pass",
}


@dataclass
class Finding:
    severity: str  # FAIL | WARN | INFO
    category: str  # loss | arch | orphan | volume
    message: str
    detail: str = ""


@dataclass
class AuditReport:
    base: str
    owner_ref: str
    main_ref: str
    head_ref: str
    findings: List[Finding] = field(default_factory=list)
    volumes: Dict[str, Dict[str, int]] = field(default_factory=dict)
    summary: Dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _run(cmd: Sequence[str], *, cwd: Path = REPO_ROOT) -> str:
    r = subprocess.run(
        list(cmd),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"cmd failed ({r.returncode}): {' '.join(cmd)}\n{r.stderr.strip()}"
        )
    return r.stdout


def _rev_parse(ref: str) -> str:
    return _run(["git", "rev-parse", "--verify", ref]).strip()


def _merge_base(a: str, b: str) -> str:
    return _run(["git", "merge-base", a, b]).strip()


def _ls_tree_files(ref: str, pathspec: str = "") -> List[str]:
    cmd = ["git", "ls-tree", "-r", "--name-only", ref]
    if pathspec:
        cmd.append(pathspec)
    out = _run(cmd)
    return [ln for ln in out.splitlines() if ln]


def _show_blob(ref: str, path: str) -> Optional[str]:
    try:
        return _run(["git", "show", f"{ref}:{path}"])
    except RuntimeError:
        return None


def _diff_name_status(a: str, b: str) -> List[Tuple[str, str]]:
    """Return list of (status, path) for a..b tree diff."""
    out = _run(["git", "diff", "--name-status", f"{a}...{b}"])
    rows: List[Tuple[str, str]] = []
    for ln in out.splitlines():
        if not ln.strip():
            continue
        parts = ln.split("\t")
        if len(parts) == 2:
            rows.append((parts[0], parts[1]))
        elif len(parts) >= 3 and parts[0].startswith("R"):
            # rename: R100 old new → treat as new path
            rows.append(("R", parts[-1]))
    return rows


def _numstat(a: str, b: str) -> Tuple[int, int]:
    """Return (added, deleted) lines between a and b."""
    out = _run(["git", "diff", "--numstat", f"{a}...{b}"])
    add = delete = 0
    for ln in out.splitlines():
        parts = ln.split("\t")
        if len(parts) < 3:
            continue
        if parts[0] == "-" or parts[1] == "-":
            continue
        try:
            add += int(parts[0])
            delete += int(parts[1])
        except ValueError:
            continue
    return add, delete


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------


def _is_scanned_path(path: str) -> bool:
    p = Path(path)
    if any(part in EXCLUDE_DIR_NAMES for part in p.parts):
        return False
    # Focus on code + config that carries glue
    return p.suffix in {".py", ".ts", ".tsx", ".js", ".yaml", ".yml"} or p.name in {
        "plugin.yaml",
        "SKILL.md",
    }


def _is_official_tree(path: str) -> bool:
    """True for files outside owner/ (official surface we glue into)."""
    return not path.startswith("owner/") and not path.startswith("tests/owner/")


def _glue_lines(text: str) -> List[str]:
    return [ln.rstrip() for ln in text.splitlines() if GLUE_LINE_RE.search(ln)]


def _normalize_line(ln: str) -> str:
    s = ln.strip()
    if s.startswith("#"):
        s = s.lstrip("#").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _fingerprint_set(lines: Iterable[str]) -> Set[str]:
    fps: Set[str] = set()
    for ln in lines:
        n = _normalize_line(ln)
        if len(n) < 12:
            continue
        # Prefer exact normalized line for high precision
        fps.add(n)
    return fps


def _load_anchors() -> List[Dict]:
    if not ANCHORS_PATH.is_file():
        return []
    try:
        import yaml  # type: ignore
    except ImportError:
        # Minimal YAML-ish parse for anchors.yaml (list of maps with contains)
        return _load_anchors_minimal(ANCHORS_PATH.read_text(encoding="utf-8"))
    data = yaml.safe_load(ANCHORS_PATH.read_text(encoding="utf-8")) or {}
    return list(data.get("anchors") or [])


def _load_anchors_minimal(text: str) -> List[Dict]:
    anchors: List[Dict] = []
    cur: Optional[Dict] = None
    for raw in text.splitlines():
        if raw.startswith("  - id:"):
            if cur:
                anchors.append(cur)
            cur = {"id": raw.split(":", 1)[1].strip(), "file": "", "contains": []}
        elif cur is not None and raw.startswith("    file:"):
            cur["file"] = raw.split(":", 1)[1].strip()
        elif cur is not None and raw.strip().startswith("- '") and "contains" in (
            # previous non-empty indent line context is fragile; accept any - ' under contains
        ):
            pass
        elif cur is not None and raw.strip().startswith("- '") and raw.strip().endswith("'"):
            item = raw.strip()[3:-1]
            cur.setdefault("contains", []).append(item)
        elif cur is not None and raw.strip().startswith('- "') and raw.strip().endswith('"'):
            item = raw.strip()[3:-1]
            cur.setdefault("contains", []).append(item)
    if cur:
        anchors.append(cur)
    return anchors


# ---------------------------------------------------------------------------
# Architecture probes
# ---------------------------------------------------------------------------

# (description, how to check at HEAD) — FAIL if critical owner path broken
ARCH_PROBES: List[Tuple[str, str, callable]] = []


def _arch_probes_head(head: str) -> List[Finding]:
    findings: List[Finding] = []

    def blob(path: str) -> str:
        return _show_blob(head, path) or ""

    # 1) SessionState legacy dict property still backs _running_agents
    run_py = blob("gateway/run.py")
    ss_py = blob("gateway/session_state.py")
    if "_running_agents" in run_py:
        if "legacy_dict_property" not in run_py and "SessionState" not in ss_py:
            findings.append(
                Finding(
                    "WARN",
                    "arch",
                    "gateway/run.py still mentions _running_agents but SessionState bridge unclear",
                    "Owner tests/glue may assume dict-shaped _running_agents.",
                )
            )
        elif "legacy_dict_property" in run_py and "_running_agents" in (ss_py or run_py):
            findings.append(
                Finding(
                    "INFO",
                    "arch",
                    "Upstream SessionState: _running_agents is a legacy_dict_property bridge",
                    "Owner code using runner._running_agents[sk]=agent remains valid.",
                )
            )

    # 2) busy_policy replaced mid-run if-chain
    commands_py = blob("hermes_cli/commands.py")
    if "busy_policy" in commands_py or "BUSY_" in commands_py:
        findings.append(
            Finding(
                "INFO",
                "arch",
                "Upstream declarative busy_policy on CommandDef",
                "Owner mid-turn command special-cases in gateway/run.py may be dead "
                "if they only reimplemented what busy_policy already covers.",
            )
        )

    # 3) cron approval ContextVar rename
    approval_py = blob("tools/approval.py")
    if "_is_cron_approval_context" in approval_py:
        if "_is_cron_session" not in approval_py:
            findings.append(
                Finding(
                    "WARN",
                    "arch",
                    "tools/approval.py has _is_cron_approval_context but no _is_cron_session alias",
                    "Owner tests/hooks importing _is_cron_session will break.",
                )
            )
        else:
            findings.append(
                Finding(
                    "INFO",
                    "arch",
                    "Cron approval helper renamed; _is_cron_session alias present",
                )
            )

    # 4) steer can_steer rejects media — owner vision path
    if "enrich_steer_with_vision" in run_py:
        # Ensure can_steer still allows media after enrichment
        if "not event.media_urls" in run_py and "enrich_steer_with_vision" in run_py:
            # Look for owner fuse comment or media allow branch near enrich
            if "bool(_steer_media_urls)" not in run_py and "image" not in run_py[
                run_py.find("enrich_steer_with_vision") : run_py.find("enrich_steer_with_vision") + 1200
            ].lower():
                findings.append(
                    Finding(
                        "FAIL",
                        "arch",
                        "steer vision glue present but can_steer may still reject media_urls",
                        "Upstream main rejects non-voice media for steer; §7.18 becomes dead.",
                    )
                )
            else:
                findings.append(
                    Finding(
                        "INFO",
                        "arch",
                        "Steer vision glue coexists with media-aware can_steer",
                    )
                )
    else:
        findings.append(
            Finding(
                "FAIL",
                "arch",
                "owner.gateway.steer_vision not referenced from gateway/run.py",
                "§7.18 steer vision enrichment missing after merge.",
            )
        )

    # 5) TurnRunner extraction — owner callbacks must still be reachable
    if "class TurnRunner" in run_py or "TurnRunner" in run_py:
        findings.append(
            Finding(
                "INFO",
                "arch",
                "Upstream TurnRunner extraction present in gateway/run.py",
                "Re-verify owner progress/display/diff_card hooks still fire inside TurnRunner path.",
            )
        )

    # 6) OpenViking auto-start still on main tree but owner disables via patch?
    ov = blob("plugins/memory/openviking/__init__.py")
    if "_start_local_openviking_server" in ov and "subprocess.Popen" in ov:
        if "auto-start" in ov.lower() or "Popen" in ov:
            # Check if owner patch disables it
            patch = blob("owner/patches/openviking_owner_recall_patch.py") + blob(
                "plugins/memory/openviking/__init__.py"
            )
            # If HEAD still has auto-start callable without owner disable flag, warn
            if "auto_start" in ov or "_start_local_openviking_server" in ov:
                findings.append(
                    Finding(
                        "WARN",
                        "arch",
                        "OpenViking local auto-start still present on HEAD tree",
                        "Owner intended to disable auto-start (Docker port race). "
                        "Confirm disable patch survived merge.",
                    )
                )

    # 7) Semantic audit glue
    run_agent = blob("run_agent.py")
    if "maybe_audit_batch" not in run_agent and "semantic_audit" not in run_agent:
        findings.append(
            Finding(
                "FAIL",
                "arch",
                "semantic audit gate glue missing from run_agent.py",
            )
        )

    # 8) load_config vs load_config_readonly for allowlist
    if "load_permanent_allowlist" in approval_py:
        if "load_config_readonly" in approval_py and "_load_patch_owner_config" in approval_py:
            findings.append(
                Finding(
                    "INFO",
                    "arch",
                    "allowlist uses load_config_readonly + patch.yaml merge (expected post-main)",
                )
            )
        elif "_load_patch_owner_config" not in approval_py:
            findings.append(
                Finding(
                    "FAIL",
                    "arch",
                    "patch.yaml command_allowlist merge missing from load_permanent_allowlist",
                )
            )

    # 9) Schema DDL relocated to hermes_state_common (not a loss)
    hsc = blob("hermes_state_common.py")
    hs = blob("hermes_state.py")
    if "owner_provider_name TEXT" in hsc and "owner_provider_name" in hs:
        findings.append(
            Finding(
                "INFO",
                "arch",
                "owner_provider_name / token columns live in hermes_state_common.py DDL",
                "hermes_state.py still uses the columns at INSERT/UPDATE sites — not lost.",
            )
        )
    elif "owner_provider_name TEXT" not in hsc and "owner_provider_name TEXT" not in hs:
        findings.append(
            Finding(
                "FAIL",
                "arch",
                "owner_provider_name TEXT DDL missing from hermes_state(_common).py",
            )
        )

    # 10) Cron session enter may be dead if main sets ContextVar natively
    sched = blob("cron/scheduler.py")
    if "owner_cron_session_enter" not in sched and "_cron_session_var.set" in sched:
        findings.append(
            Finding(
                "WARN",
                "arch",
                "owner_cron_session_enter no longer called from cron/scheduler.py",
                "Main sets HERMES_CRON_SESSION via native ContextVar. "
                "owner_cron_session_enter() may be dead on the production path; "
                "owner_cron_session_exit() may still scrub. Confirm single ContextVar identity.",
            )
        )
    elif "owner_cron_session_enter" in sched:
        findings.append(
            Finding(
                "INFO",
                "arch",
                "owner_cron_session_enter still wired in cron/scheduler.py",
            )
        )

    # 11) Progress dedup helper still present even if Chinese comments reshuffled
    if "_append_dedup_counter" in run_py:
        findings.append(
            Finding(
                "INFO",
                "arch",
                "gateway progress fence-safe dedup helper _append_dedup_counter present",
                "Deleted Chinese [owner] comments are cosmetic if helper + call sites remain.",
            )
        )

    return findings


# ---------------------------------------------------------------------------
# Orphan owner modules
# ---------------------------------------------------------------------------


def _owner_module_paths(ref: str) -> List[str]:
    files = _ls_tree_files(ref, "owner")
    return [
        f
        for f in files
        if f.endswith(".py")
        and not f.endswith("__init__.py")
        and "/validation/" not in f
        and "/scripts/" not in f
        and "/docs/" not in f
        and "/examples/" not in f
        and "/config/" not in f
        and "/skins/" not in f
        and "/sync/" not in f  # CLI pipeline, referenced by scripts
    ]


def _module_dotted_from_path(path: str) -> str:
    # owner/foo/bar.py -> owner.foo.bar
    assert path.startswith("owner/")
    rel = path[len("owner/") :]
    if rel.endswith(".py"):
        rel = rel[:-3]
    if rel.endswith("/__init__"):
        rel = rel[: -len("/__init__")]
    return "owner." + rel.replace("/", ".")


def _collect_external_owner_refs(head: str) -> Set[str]:
    """Scan official + tests trees for owner.* string references."""
    refs: Set[str] = set()
    files = _ls_tree_files(head)
    for path in files:
        if path.startswith("owner/"):
            continue
        if not _is_scanned_path(path):
            continue
        text = _show_blob(head, path)
        if not text or "owner." not in text and "_owner_import" not in text:
            continue
        for m in re.finditer(r"owner(?:\.[A-Za-z_][A-Za-z0-9_]*)+", text):
            refs.add(m.group(0))
        for m in re.finditer(r'_owner_import\(\s*["\']([^"\']+)["\']', text):
            refs.add(m.group(1))
    return refs


def _orphan_findings(head: str) -> List[Finding]:
    findings: List[Finding] = []
    modules = _owner_module_paths(head)
    ext_refs = _collect_external_owner_refs(head)

    # Also scan inside owner/ for internal refs (plugins register etc.)
    internal_text_parts: List[str] = []
    for path in _ls_tree_files(head, "owner"):
        if path.endswith(".py") or path.endswith(".yaml"):
            t = _show_blob(head, path)
            if t:
                internal_text_parts.append(t)
    internal_blob = "\n".join(internal_text_parts)

    for path in modules:
        dotted = _module_dotted_from_path(path)
        # parent package prefixes also count as reference
        candidates = {dotted}
        parts = dotted.split(".")
        for i in range(2, len(parts)):
            candidates.add(".".join(parts[:i]))

        hit_ext = any(any(c in r or r.startswith(c) for r in ext_refs) for c in candidates)
        # broader: any external ref string contains the leaf module path
        if not hit_ext:
            hit_ext = any(dotted in r or path.replace("/", ".")[:-3] in r for r in ext_refs)

        hit_int = dotted in internal_blob or path in internal_blob
        # owner-extensions register_hooks import style
        leaf = parts[-1]
        if not hit_ext and not hit_int:
            findings.append(
                Finding(
                    "WARN",
                    "orphan",
                    f"No references found to {dotted} ({path})",
                    "May be dead after merge, or only loaded dynamically — verify manually.",
                )
            )
        elif not hit_ext and hit_int:
            findings.append(
                Finding(
                    "INFO",
                    "orphan",
                    f"{dotted} only referenced inside owner/",
                    "OK if plugin self-registers; fail if it used to be called from core.",
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Main audit sections
# ---------------------------------------------------------------------------


def audit_volumes(base: str, owner: str, main: str, head: str) -> Dict[str, Dict[str, int]]:
    vols: Dict[str, Dict[str, int]] = {}

    for label, a, b in (
        ("owner_only", base, owner),
        ("main_only", base, main),
        ("head_vs_owner", owner, head),
        ("head_vs_main", main, head),
        ("head_vs_base", base, head),
    ):
        add, delete = _numstat(a, b)
        vols[label] = {"added": add, "deleted": delete}

    # Marker counts
    def count_markers(ref: str) -> int:
        n = 0
        for path in _ls_tree_files(ref):
            if not path.endswith(".py"):
                continue
            if path.startswith("owner/") or path.startswith("tests/"):
                # still count glue in official + tests that ship with owner
                pass
            text = _show_blob(ref, path)
            if not text:
                continue
            n += len(re.findall(r"\[owner(?:-patch)?\]", text))
        return n

    vols["markers"] = {
        "owner": count_markers(owner),
        "main": count_markers(main),
        "head": count_markers(head),
    }
    return vols


def audit_loss(base: str, owner: str, head: str) -> List[Finding]:
    findings: List[Finding] = []

    # Files owner changed vs base (candidate glue surfaces)
    owner_changed = {p for st, p in _diff_name_status(base, owner)}
    official_changed = {p for p in owner_changed if _is_official_tree(p) and _is_scanned_path(p)}

    missing_fps = 0
    checked_fps = 0
    lost_examples: List[str] = []

    for path in sorted(official_changed):
        owner_text = _show_blob(owner, path)
        head_text = _show_blob(head, path)
        base_text = _show_blob(base, path) or ""

        if owner_text is None:
            continue
        if head_text is None:
            findings.append(
                Finding(
                    "FAIL",
                    "loss",
                    f"File present on owner but missing at HEAD: {path}",
                )
            )
            continue

        # Owner-unique glue lines = glue on owner that was not on base
        owner_glue = _fingerprint_set(_glue_lines(owner_text))
        base_glue = _fingerprint_set(_glue_lines(base_text))
        head_glue = _fingerprint_set(_glue_lines(head_text))
        unique = owner_glue - base_glue
        if not unique:
            # Also consider raw owner_provider_name / inject lines without marker
            continue

        for fp in sorted(unique):
            checked_fps += 1
            # Survives if exact fingerprint or strong substring still in head glue or head text
            if fp in head_glue:
                continue
            # fuzzy: significant tokens
            tokens = {
                t
                for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", fp)
                if t.lower() not in _TOKEN_STOP
            }
            if len(tokens) >= 3:
                # require all owner.* module refs if any
                mods = set(re.findall(r"owner(?:\.[A-Za-z_][A-Za-z0-9_]*)+", fp))
                if mods and all(m in head_text for m in mods):
                    continue
                # else require high token overlap with some head glue line
                for hg in head_glue:
                    ht = {
                        t
                        for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", hg)
                        if t.lower() not in _TOKEN_STOP
                    }
                    if len(tokens & ht) >= min(4, len(tokens)):
                        break
                else:
                    # last chance: fp substring in head (reformatted)
                    if fp[:40] in head_text or any(tok in head_text for tok in list(tokens)[:2]):
                        # weak survival
                        if mods and not all(m in head_text for m in mods):
                            missing_fps += 1
                            if len(lost_examples) < 40:
                                lost_examples.append(f"{path}: {fp[:120]}")
                        continue
                    missing_fps += 1
                    if len(lost_examples) < 40:
                        lost_examples.append(f"{path}: {fp[:120]}")
            else:
                if fp not in head_text:
                    missing_fps += 1
                    if len(lost_examples) < 40:
                        lost_examples.append(f"{path}: {fp[:120]}")

    findings.append(
        Finding(
            "INFO",
            "volume",
            f"Owner-unique glue fingerprints checked={checked_fps} missing≈{missing_fps}",
            f"official files owner-touched={len(official_changed)}",
        )
    )
    if missing_fps > 0:
        sev = "FAIL" if missing_fps >= 5 else "WARN"
        findings.append(
            Finding(
                sev,
                "loss",
                f"{missing_fps} owner-unique glue fingerprint(s) not clearly present at HEAD",
                "\n".join(lost_examples[:25]),
            )
        )
    else:
        findings.append(
            Finding(
                "INFO",
                "loss",
                "No owner-unique glue fingerprints clearly missing at HEAD",
            )
        )

    # Anchors
    anchors = _load_anchors()
    for anc in anchors:
        path = anc.get("file") or ""
        contains = anc.get("contains") or []
        aid = anc.get("id") or path
        text = _show_blob(head, path)
        if text is None:
            findings.append(
                Finding("FAIL", "loss", f"Anchor file missing at HEAD: {aid} ({path})")
            )
            continue
        for needle in contains:
            if needle not in text:
                findings.append(
                    Finding(
                        "FAIL",
                        "loss",
                        f"Anchor '{aid}' missing needle in {path}",
                        repr(needle),
                    )
                )

    # Critical symbols that must exist somewhere
    critical_needles = [
        ("owner_provider_name", "attribution chain"),
        ("inject_model_extra_body", "extra_body injection"),
        ("maybe_audit_batch", "semantic audit"),
        ("enrich_steer_with_vision", "steer vision §7.18"),
        ("is_skill_script_allowed", "skill script approval"),
        ("skill_approval_gate", "skill manage approval card route"),
        ("_truncate_chatlog", "openviking ChatLog strip"),
        ("predict_and_checkpoint", "checkpoint predictor"),
        ("append_inbound_context", "inbound context"),
        ("try_auto_card", "feishu auto-card"),
    ]
    # Build a cheap multi-file search via git grep
    for needle, label in critical_needles:
        try:
            out = _run(["git", "grep", "-n", needle, head, "--", "*.py"])
        except RuntimeError:
            out = ""
        if not out.strip():
            findings.append(
                Finding(
                    "FAIL",
                    "loss",
                    f"Critical symbol/string missing at HEAD: {needle} ({label})",
                )
            )
        else:
            # prefer not only in tests
            non_test = [ln for ln in out.splitlines() if "/tests/" not in ln and "tests/" not in ln]
            if not non_test:
                findings.append(
                    Finding(
                        "WARN",
                        "loss",
                        f"{needle} ({label}) only found under tests/ at HEAD",
                    )
                )

    return findings


def format_report(rep: AuditReport) -> str:
    lines: List[str] = []
    lines.append("=" * 72)
    lines.append("Owner merge loss / architecture audit")
    lines.append("=" * 72)
    lines.append(f"BASE   {rep.base[:12]}")
    lines.append(f"OWNER  {rep.owner_ref}  ({_rev_parse(rep.owner_ref)[:12]})")
    lines.append(f"MAIN   {rep.main_ref}  ({_rev_parse(rep.main_ref)[:12]})")
    lines.append(f"HEAD   {rep.head_ref}  ({_rev_parse(rep.head_ref)[:12]})")
    lines.append("")
    lines.append("## A. Volume")
    for k, v in rep.volumes.items():
        if k == "markers":
            lines.append(
                f"  markers [owner]: owner={v.get('owner')} main={v.get('main')} head={v.get('head')}"
            )
        else:
            lines.append(f"  {k:16s}  +{v.get('added', 0):7d}  -{v.get('deleted', 0):7d}")
    lines.append("")
    lines.append("## B–D. Findings")
    by_sev: Dict[str, List[Finding]] = defaultdict(list)
    for f in rep.findings:
        by_sev[f.severity].append(f)
    for sev in ("FAIL", "WARN", "INFO"):
        items = by_sev.get(sev) or []
        lines.append(f"\n### {sev} ({len(items)})")
        if not items:
            lines.append("  (none)")
            continue
        for f in items:
            lines.append(f"  [{f.category}] {f.message}")
            if f.detail:
                for dln in f.detail.splitlines()[:12]:
                    lines.append(f"           {dln}")
    lines.append("")
    lines.append("## Summary")
    lines.append(
        f"  FAIL={rep.summary.get('FAIL', 0)}  "
        f"WARN={rep.summary.get('WARN', 0)}  "
        f"INFO={rep.summary.get('INFO', 0)}"
    )
    lines.append("=" * 72)
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--owner-ref", default="owner", help="Pre-merge owner tip (default: owner)")
    ap.add_argument("--main-ref", default="main", help="Upstream main (default: main)")
    ap.add_argument("--head-ref", default="HEAD", help="Post-merge tip (default: HEAD)")
    ap.add_argument("--base-ref", default="", help="Optional explicit merge-base")
    ap.add_argument("--json", default="", help="Write machine-readable JSON to path")
    ap.add_argument(
        "--skip-orphan",
        action="store_true",
        help="Skip orphan module scan (slower on large trees)",
    )
    args = ap.parse_args(argv)

    owner = _rev_parse(args.owner_ref)
    main = _rev_parse(args.main_ref)
    head = _rev_parse(args.head_ref)
    base = _rev_parse(args.base_ref) if args.base_ref else _merge_base(owner, main)

    rep = AuditReport(
        base=base,
        owner_ref=args.owner_ref,
        main_ref=args.main_ref,
        head_ref=args.head_ref,
    )

    print("Computing volumes…", file=sys.stderr)
    rep.volumes = audit_volumes(base, owner, main, head)

    print("Auditing owner glue loss…", file=sys.stderr)
    rep.findings.extend(audit_loss(base, owner, head))

    print("Probing architecture hazards…", file=sys.stderr)
    rep.findings.extend(_arch_probes_head(head))

    if not args.skip_orphan:
        print("Scanning for orphan owner modules…", file=sys.stderr)
        rep.findings.extend(_orphan_findings(head))

    counts = defaultdict(int)
    for f in rep.findings:
        counts[f.severity] += 1
    rep.summary = dict(counts)

    text = format_report(rep)
    print(text)

    if args.json:
        payload = {
            "base": rep.base,
            "owner_ref": rep.owner_ref,
            "main_ref": rep.main_ref,
            "head_ref": rep.head_ref,
            "volumes": rep.volumes,
            "summary": rep.summary,
            "findings": [asdict(f) for f in rep.findings],
        }
        Path(args.json).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        print(f"JSON written to {args.json}", file=sys.stderr)

    return 1 if rep.summary.get("FAIL", 0) else 0


if __name__ == "__main__":
    # fix type hint for older python without using Callable import in ARCH
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.exit(0)
