"""C12-doc-ocr rework guards — official feishu tool files stay upstream-literal.

0b1e269dc0 rewrote tools/feishu_doc_tool.py from the 70-line upstream into a
247-line in-place extension (schema params + handler orchestration). The audit
rework restores the official file to upstream literal + a 3-line handler
delegate + top marker:

- schema extensions ride ``ToolEntry.dynamic_schema_overrides``
  (owner/feishu/doc_tool.py::SCHEMA_OVERRIDES, applied post-registration)
- handler orchestration lives in owner/feishu/doc_tool.py::handle_feishu_doc_read
- tools/feishu_drive_tool.py is upstream literal again; the env-fallback
  client is a runtime rebinding of its module-local ``get_client``
  (owner/feishu/drive_tool_patch.py)

These tests pin all three properties: upstream literal (static schema +
registered entry schema + no extension literals in the official sources),
applied behavior (all 7 extension params visible through
registry.get_definitions after apply_patch), and idempotency.
"""

import os
import pathlib
import unittest
from unittest import mock

# The upstream (main) FEISHU_DOC_READ_SCHEMA, verbatim — the official file's
# static schema must equal this byte-for-byte; extensions may only surface via
# dynamic_schema_overrides after apply_patch().
UPSTREAM_SCHEMA = {
    "name": "feishu_doc_read",
    "description": (
        "Read the full content of a Feishu/Lark document as plain text. "
        "Useful when you need more context beyond the quoted text in a comment."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "doc_token": {
                "type": "string",
                "description": "The document token (from the document URL or comment context).",
            },
        },
        "required": ["doc_token"],
    },
}

EXTENDED_PROPS = (
    "doc_token", "mode", "table_index", "limit", "filter", "offset", "mf_limit",
)

# Literals that exist only in the owner-side extension; their presence in an
# official source file means the inline rewrite crept back.
FORBIDDEN_OFFICIAL_LITERALS = (
    "mf_limit", "table_index", "resolve_client", "read_bitable_as_text",
    "read_docx_with_images", "merge_forward", "filter_expr", "vision_analyzed",
)


def _official_doc_source() -> str:
    import tools.feishu_doc_tool

    return pathlib.Path(tools.feishu_doc_tool.__file__).read_text(encoding="utf-8")


def _official_drive_source() -> str:
    import tools.feishu_drive_tool

    return pathlib.Path(tools.feishu_drive_tool.__file__).read_text(encoding="utf-8")


class TestOfficialDocToolStaysUpstream(unittest.TestCase):
    """Literal guard: official file = upstream schema + thin delegate + marker."""

    def test_static_schema_matches_upstream_literal(self):
        from tools.feishu_doc_tool import FEISHU_DOC_READ_SCHEMA

        self.assertEqual(FEISHU_DOC_READ_SCHEMA, UPSTREAM_SCHEMA)

    def test_registered_entry_schema_matches_upstream_literal(self):
        from tools.registry import registry

        entry = registry.get_entry("feishu_doc_read")
        self.assertIsNotNone(entry, "feishu_doc_read must be registered by the official module")
        self.assertEqual(entry.schema, UPSTREAM_SCHEMA)

    def test_official_source_has_no_extension_literals(self):
        src = _official_doc_source()
        for needle in FORBIDDEN_OFFICIAL_LITERALS:
            self.assertNotIn(needle, src, f"official feishu_doc_tool.py grew inline logic again: {needle!r}")
        # the thin-delegate marker must be present (spec §2.2: one marker per modified hunk)
        self.assertIn("# [owner] C12-doc-ocr", src)
        self.assertIn("from owner.feishu.doc_tool import handle_feishu_doc_read", src)

    def test_handler_delegates_args_and_kwargs_to_owner_impl(self):
        import tools.feishu_doc_tool
        from owner.feishu import doc_tool

        with mock.patch.object(
            doc_tool, "handle_feishu_doc_read", return_value="SENTINEL"
        ) as delegate:
            out = tools.feishu_doc_tool._handle_feishu_doc_read(
                {"doc_token": "tokc12"}, channel="feishu")
        self.assertEqual(out, "SENTINEL")
        delegate.assert_called_once_with({"doc_token": "tokc12"}, channel="feishu")


class TestAppliedSchemaExtensions(unittest.TestCase):
    """Behavior guard: after apply_patch, get_definitions serves the extended schema."""

    def _definitions(self):
        from tools.registry import registry

        entry = registry.get_entry("feishu_doc_read")
        self.assertIsNotNone(entry)
        # check_fn probes lark_oapi via find_spec; the test venv may lack the
        # SDK, so bypass availability gating for the schema-shape assertion.
        with mock.patch.object(entry, "check_fn", None):
            defs = registry.get_definitions({"feishu_doc_read"})
        self.assertEqual(len(defs), 1)
        return defs[0]["function"]

    def test_definitions_carry_all_extension_params_after_apply(self):
        from owner.feishu.doc_tool import SCHEMA_OVERRIDES, apply_patch

        self.assertTrue(apply_patch(), "apply_patch must succeed with the official tool registered")
        fn = self._definitions()
        expected = SCHEMA_OVERRIDES()
        self.assertEqual(fn["name"], "feishu_doc_read")
        self.assertEqual(fn["description"], expected["description"])
        self.assertEqual(fn["parameters"], expected["parameters"])
        props = fn["parameters"]["properties"]
        self.assertEqual(sorted(props), sorted(EXTENDED_PROPS))
        self.assertEqual(fn["parameters"]["required"], ["doc_token"])
        # spot-check two descriptions the inline rewrite used to carry
        self.assertIn("wiki node token", props["doc_token"]["description"])
        self.assertIn("merge_forward", props["offset"]["description"])

    def test_apply_is_idempotent(self):
        from owner.feishu.doc_tool import SCHEMA_OVERRIDES, apply_patch
        from tools.registry import registry

        self.assertTrue(apply_patch())
        first = registry.get_entry("feishu_doc_read").dynamic_schema_overrides
        self.assertTrue(apply_patch(), "re-apply must not fail")
        second = registry.get_entry("feishu_doc_read").dynamic_schema_overrides
        self.assertIs(first, second, "re-apply must not stack wrappers or replace the callable")
        self.assertIs(first, SCHEMA_OVERRIDES)
        fn = self._definitions()
        self.assertEqual(sorted(fn["parameters"]["properties"]), sorted(EXTENDED_PROPS))


class TestOfficialDriveToolStaysUpstream(unittest.TestCase):
    """Literal + behavior guard for the drive env-fallback runtime patch."""

    def test_drive_source_has_no_owner_literals(self):
        src = _official_drive_source()
        for needle in ("resolve_client", "# [owner]", "FEISHU_APP_ID"):
            self.assertNotIn(needle, src, f"official feishu_drive_tool.py grew inline logic again: {needle!r}")

    def test_get_client_wrapped_once_and_prefers_injected_client(self):
        import tools.feishu_drive_tool as drive
        from owner.feishu import drive_tool_patch

        self.assertTrue(drive_tool_patch.apply_patch())
        wrapped = drive.get_client
        self.assertTrue(drive_tool_patch.apply_patch(), "re-apply must not fail")
        self.assertIs(drive.get_client, wrapped, "re-apply must not double-wrap get_client")

        drive.set_client("INJECTED")
        try:
            self.assertIs(drive.get_client(), "INJECTED")
        finally:
            drive.set_client(None)

    def test_handler_reports_upstream_error_without_any_client(self):
        from owner.feishu import client_utils as fcu
        from owner.feishu import drive_tool_patch
        from tools.registry import registry

        self.assertTrue(drive_tool_patch.apply_patch())
        entry = registry.get_entry("feishu_drive_list_comments")
        self.assertIsNotNone(entry, "feishu_drive tools must be registered")
        fcu._fallback_client = None
        env = {k: v for k, v in os.environ.items()
               if k not in ("FEISHU_APP_ID", "FEISHU_APP_SECRET")}
        with mock.patch.dict(os.environ, env, clear=True):
            out = entry.handler({"file_token": "tokc12"})
        self.assertIn("Feishu client not available", out)
        self.assertIn("error", out)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
