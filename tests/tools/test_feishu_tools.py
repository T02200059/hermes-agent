"""Tests for feishu_doc_tool and feishu_drive_tool — registration, schema validation,
and the client-plumbing/error-path contracts shared with ``tools.feishu_lark``."""

import importlib
import unittest
from unittest import mock

from tools.registry import registry

# Trigger tool discovery so feishu tools get registered
importlib.import_module("tools.feishu_doc_tool")
importlib.import_module("tools.feishu_drive_tool")


class TestFeishuToolRegistration(unittest.TestCase):
    """Verify feishu tools are registered and have valid schemas."""

    EXPECTED_TOOLS = {
        "feishu_doc_read": "feishu_doc",
        "feishu_drive_list_comments": "feishu_drive",
        "feishu_drive_list_comment_replies": "feishu_drive",
        "feishu_drive_reply_comment": "feishu_drive",
        "feishu_drive_add_comment": "feishu_drive",
    }

    def test_all_tools_registered(self):
        for tool_name, toolset in self.EXPECTED_TOOLS.items():
            entry = registry.get_entry(tool_name)
            self.assertIsNotNone(entry, f"{tool_name} not registered")
            self.assertEqual(entry.toolset, toolset)


    def test_drive_tools_require_file_token(self):
        for tool_name in self.EXPECTED_TOOLS:
            if tool_name == "feishu_doc_read":
                continue
            entry = registry.get_entry(tool_name)
            props = entry.schema["parameters"].get("properties", {})
            self.assertIn("file_token", props, f"{tool_name} missing file_token param")
            self.assertIn("file_type", props, f"{tool_name} missing file_type param")

    def test_the_client_plumbing_is_shared_not_copied(self):
        """Both modules must re-export the objects ``tools.feishu_lark`` owns.

        ``feishu_comment`` injects its lark client by calling ``set_client`` on
        these two modules. If either kept a private copy, the injected client
        would land in a thread-local that ``get_client`` never reads -- and the
        tools would silently fall back (or refuse to run) inside a comment.
        """
        import tools.feishu_lark as shared

        for module_name in ("tools.feishu_doc_tool", "tools.feishu_drive_tool"):
            module = importlib.import_module(module_name)
            for symbol in ("set_client", "get_client", "_check_feishu"):
                self.assertIs(
                    getattr(module, symbol),
                    getattr(shared, symbol),
                    f"{module_name}.{symbol} is not the shared tools.feishu_lark one",
                )

    def test_an_injected_client_is_visible_through_get_client(self):
        import tools.feishu_lark as shared

        doc_tool = importlib.import_module("tools.feishu_doc_tool")
        drive_tool = importlib.import_module("tools.feishu_drive_tool")
        try:
            doc_tool.set_client("doc-client")
            self.assertEqual(shared.get_client(), "doc-client")
            self.assertEqual(drive_tool.get_client(), "doc-client")
        finally:
            shared.set_client(None)
        self.assertIsNone(drive_tool.get_client())

    def test_an_unexpected_read_error_is_logged_and_returned(self):
        """The docx/bitable/sheet dispatch must log the traceback it swallows.

        Everything below ``_handle_feishu_doc_read``'s dispatch is a backstop: a
        bug there is reported to the model as ``Failed to read document: ...``
        and nowhere else, so the log record is the only traceback a maintainer
        gets from a comment-triggered read.
        """
        doc_tool = importlib.import_module("tools.feishu_doc_tool")
        fcu = importlib.import_module("tools.feishu_client_utils")

        with mock.patch.object(fcu, "resolve_client", return_value=object()), \
             mock.patch.object(fcu, "extract_token", return_value=("TOK", False, "docx")), \
             mock.patch.object(fcu, "read_docx_with_images", side_effect=RuntimeError("boom")):
            with self.assertLogs("tools.feishu_doc_tool", level="ERROR") as captured:
                out = doc_tool._handle_feishu_doc_read({"doc_token": "TOK"})

        self.assertIn("boom", out)
        self.assertTrue(
            any("unexpected error" in line for line in captured.output),
            captured.output,
        )


if __name__ == "__main__":
    unittest.main()
