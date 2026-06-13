"""Tool schema for unified_diff_patch.

Kept in its own module so the glue file and tests can import it without
triggering the full tool interface at import time.
"""

from __future__ import annotations


_UNIFIED_DIFF_PATCH_DESCRIPTION = (
    "Apply a standard unified-diff patch to one or more files. "
    "The patch must use standard `@@ -old_start,old_count +new_start,new_count @@` "
    "hunk headers. Context lines (prefixed with a single space) must match the "
    "current file content; removed lines start with `-` and added lines start with `+`. "
    "Supports creating files (`--- /dev/null`), deleting files (`+++ /dev/null`), "
    "and editing multiple files in a single call.\n\n"

    "PATH RULES: Paths in `---` / `+++` headers are resolved against the task's "
    "current working directory (the agent's terminal cwd). "
    "Relative paths may be written as `a/relative/path` (the git-style `a/` prefix is "
    "stripped) or simply `relative/path`. Absolute paths may be written directly as "
    "`/absolute/path`.\n\n"

    "TIPS FOR HAND-WRITTEN DIFFS:\n"
    "- Always set `strict: true` when writing a diff by hand. It rejects formatting "
    "mistakes (blank lines, bare lines, wrong prefixes) with the exact body line number.\n"
    "- Run `dry_run: true` first to preview the patch; no files are changed and no locks are taken.\n"
    "- `auto_fix_header` (default true) silently fixes miscounted `@@` line counts.\n"
    "- `auto_fix_start` (default true) relocates a hunk when the `@@` line number is "
    "slightly off, as long as the context occurs only once in the file.\n\n"

    "HUNK COUNTING: `old_count` must equal context lines + removed lines; "
    "`new_count` must equal context lines + added lines. "
    "Count body lines before writing the header to avoid parse errors."
)


_PATCH_PARAM_DESCRIPTION = (
    "Unified diff text. Standard format:\n"
    "  --- a/src/main.py\n"
    "  +++ b/src/main.py\n"
    "  @@ -10,3 +10,4 @@\n"
    "   def old_func():\n"
    "  -    pass\n"
    "  +    return 42\n"
    "  +    # new line\n\n"
    "`old_count` = context + removed lines; `new_count` = context + added lines. "
    "Use absolute paths directly (`--- /tmp/foo.py`) or git-style relative paths."
)


UNIFIED_DIFF_PATCH_SCHEMA = {
    "name": "unified_diff_patch",
    "description": _UNIFIED_DIFF_PATCH_DESCRIPTION,
    "parameters": {
        "type": "object",
        "properties": {
            "patch": {
                "type": "string",
                "description": _PATCH_PARAM_DESCRIPTION,
            },
            "cross_profile": {
                "type": "boolean",
                "description": (
                    "Opt out of the cross-profile soft guard. When false (default), "
                    "the tool hard-errors if the patch would write to a different Hermes "
                    "profile's scoped directory. Set true only when the user explicitly "
                    "directed you to modify another profile's files."
                ),
                "default": False,
            },
            "strict": {
                "type": "boolean",
                "description": (
                    "When true, enforce standard diff format strictly: blank lines and "
                    "bare lines in hunk bodies are rejected with a precise error including "
                    "the hunk body line number. Recommended for ALL hand-written diffs."
                ),
                "default": False,
            },
            "dry_run": {
                "type": "boolean",
                "description": (
                    "Preview mode. Parses the patch and runs path safety checks, then "
                    "returns the unified diff that WOULD be applied without writing to disk, "
                    "taking file locks, or updating read timestamps. The result contains "
                    "`_dry_run: true` and empty `files_modified`/`created`/`deleted`. "
                    "Use this to verify a hand-written diff before committing."
                ),
                "default": False,
            },
            "auto_fix_header": {
                "type": "boolean",
                "description": (
                    "When true (default), silently correct hunk header line counts that "
                    "do not match the parsed body. This removes the most common cause of "
                    "parse failures for hand-written diffs."
                ),
                "default": True,
            },
            "auto_fix_start": {
                "type": "boolean",
                "description": (
                    "When true (default), if the context in a hunk does not match at the "
                    "declared @@ line number, search the entire file for a unique match and "
                    "apply the hunk there. Rejects ambiguous matches with a clear error. "
                    "Also tolerates trailing-whitespace differences in context lines."
                ),
                "default": True,
            },
        },
        "required": ["patch"],
    },
}
