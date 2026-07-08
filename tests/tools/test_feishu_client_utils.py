"""Tests for tools.feishu_client_utils.

Covers the behavior contracts introduced for the DM/group-chat fallback:
- fallback client is built once from env vars and cached
- resolve_client prefers an injected client over the fallback
- extract_token handles bare tokens, docx URLs, and wiki URLs
- resolve_wiki_node parses the wiki get_node response
- read_bitable_as_text flattens tables/records into readable text

No live network. The lark client is a stub with a ``request`` mock; the lark
SDK is never imported (the helper imports it lazily inside ``get_fallback_client``).
"""

import sys
import threading
import types
import unittest
from unittest import mock

from tools import feishu_client_utils as fcu


def _make_response(code=0, msg="", data=None, raw_content=None):
    """Build a stub lark response object."""

    class _Raw:
        pass

    class _Resp:
        pass

    r = _Resp()
    r.code = code
    r.msg = msg
    r.data = data
    if raw_content is not None:
        r.raw = _Raw()
        r.raw.content = raw_content
    else:
        r.raw = None
    return r


class _StubClient:
    """Records requests and returns queued responses."""

    def __init__(self, responses):
        # ``responses`` is a list of _Resp (or a single one).
        if isinstance(responses, list):
            self._queue = list(responses)
        else:
            self._queue = [responses]
        self.calls = []

    def request(self, req):
        self.calls.append(req)
        if len(self._queue) == 1:
            return self._queue[0]
        return self._queue.pop(0)


class TestGetFallbackClient(unittest.TestCase):
    """Behavior: built once from env, cached, thread-safe."""

    def setUp(self):
        # Reset the module-level cache so each test is isolated.
        fcu._fallback_client = None

    def tearDown(self):
        fcu._fallback_client = None

    def test_returns_none_without_credentials(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            for var in ("FEISHU_APP_ID", "FEISHU_APP_SECRET"):
                if var in __import__("os").environ:
                    del __import__("os").environ[var]
            self.assertIsNone(fcu.get_fallback_client())

    def test_builds_and_caches_client(self):
        fake_lark = types.ModuleType("lark_oapi")

        class _Client:
            pass

        built = []

        class _Builder:
            def app_id(self, v):
                return self

            def app_secret(self, v):
                return self

            def domain(self, v):
                return self

            def build(self):
                c = _Client()
                built.append(c)
                return c

        fake_lark.Client = types.SimpleNamespace(builder=lambda: _Builder())
        with mock.patch.dict("os.environ", {"FEISHU_APP_ID": "id", "FEISHU_APP_SECRET": "sec"}), \
                mock.patch.dict(sys.modules, {"lark_oapi": fake_lark}):
            c1 = fcu.get_fallback_client()
            c2 = fcu.get_fallback_client()
            self.assertIs(c1, c2)  # cached, not rebuilt
            self.assertEqual(len(built), 1)

    def test_concurrent_build_only_creates_one_client(self):
        fake_lark = types.ModuleType("lark_oapi")
        build_count = {"n": 0}
        build_lock = threading.Lock()

        class _Builder:
            def app_id(self, v):
                return self

            def app_secret(self, v):
                return self

            def domain(self, v):
                return self

            def build(self):
                # Slow down so other threads pile on the lock.
                import time
                time.sleep(0.02)
                with build_lock:
                    build_count["n"] += 1
                return types.SimpleNamespace(_id=build_count["n"])

        fake_lark.Client = types.SimpleNamespace(builder=lambda: _Builder())
        with mock.patch.dict("os.environ", {"FEISHU_APP_ID": "id", "FEISHU_APP_SECRET": "sec"}), \
                mock.patch.dict(sys.modules, {"lark_oapi": fake_lark}):
            results = []

            def worker():
                results.append(fcu.get_fallback_client())

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertEqual(build_count["n"], 1)  # only one build
            self.assertEqual(len({id(r) for r in results}), 1)  # all same instance


class TestResolveClient(unittest.TestCase):
    def setUp(self):
        fcu._fallback_client = None

    def tearDown(self):
        fcu._fallback_client = None

    def test_prefers_injected_client(self):
        injected = types.SimpleNamespace(injected=True)
        with mock.patch.object(fcu, "get_fallback_client", return_value="FALLBACK"):
            self.assertIs(fcu.resolve_client(injected), injected)

    def test_falls_back_when_no_injection(self):
        with mock.patch.object(fcu, "get_fallback_client", return_value="FALLBACK"):
            self.assertEqual(fcu.resolve_client(None), "FALLBACK")


class TestExtractToken(unittest.TestCase):
    def test_bare_token(self):
        tok, is_wiki = fcu.extract_token("ABCdef123")
        self.assertEqual(tok, "ABCdef123")
        self.assertFalse(is_wiki)

    def test_docx_url(self):
        tok, is_wiki = fcu.extract_token("https://xxx.feishu.cn/docx/DocToken123")
        self.assertEqual(tok, "DocToken123")
        self.assertFalse(is_wiki)

    def test_wiki_url_is_flagged(self):
        tok, is_wiki = fcu.extract_token("https://xxx.feishu.cn/wiki/NodeToken456")
        self.assertEqual(tok, "NodeToken456")
        self.assertTrue(is_wiki)

    def test_wiki_url_strips_query_and_fragment(self):
        tok, is_wiki = fcu.extract_token(
            "https://xxx.feishu.cn/wiki/NodeToken456?from=menu#section"
        )
        self.assertEqual(tok, "NodeToken456")
        self.assertTrue(is_wiki)

    def test_sheets_url(self):
        tok, is_wiki = fcu.extract_token("https://xxx.feishu.cn/sheets/SheetToken")
        self.assertEqual(tok, "SheetToken")
        self.assertFalse(is_wiki)

    def test_empty(self):
        self.assertEqual(fcu.extract_token(""), ("", False))
        self.assertEqual(fcu.extract_token("   "), ("", False))


class TestResolveWikiNode(unittest.TestCase):
    def test_parses_obj_token_and_type(self):
        client = _StubClient(_make_response(data={
            "node": {"obj_token": "realDocToken", "obj_type": "docx"}
        }))
        obj_token, obj_type = fcu.resolve_wiki_node(client, "node123")
        self.assertEqual(obj_token, "realDocToken")
        self.assertEqual(obj_type, "docx")

    def test_returns_none_on_api_error(self):
        client = _StubClient(_make_response(code=1254030, msg="no permission"))
        self.assertEqual(fcu.resolve_wiki_node(client, "node"), (None, None))

    def test_returns_none_when_node_missing(self):
        client = _StubClient(_make_response(data={}))
        self.assertEqual(fcu.resolve_wiki_node(client, "node"), (None, None))


class TestReadBitableAsText(unittest.TestCase):
    def test_flattens_tables_and_records(self):
        # 1 table, 2 records, no pagination (has_more absent).
        table_resp = _make_response(data={
            "items": [
                {"table_id": "tblA", "name": "Tasks"},
                {"table_id": "tblB", "name": "Owners"},
            ]
        })
        records_a = _make_response(data={
            "items": [
                {"fields": {"任务": "写文档", "状态": "done"}},
                {"fields": {"任务": "发邮件"}},
            ],
            "has_more": False,
        })
        records_b = _make_response(data={"items": [], "has_more": False})
        client = _StubClient([table_resp, records_a, records_b])

        text = fcu.read_bitable_as_text(client, "appBASExxx")
        self.assertIn("Tasks", text)
        self.assertIn("Owners", text)
        self.assertIn("任务: 写文档", text)
        self.assertIn("状态: done", text)
        self.assertIn("发邮件", text)
        self.assertIn("(no records)", text)

    def test_reports_api_error(self):
        client = _StubClient(_make_response(code=1254000, msg="app not found"))
        text = fcu.read_bitable_as_text(client, "appBad")
        self.assertIn("Failed to read bitable", text)
        self.assertIn("1254000", text)

    def test_handles_list_field_values(self):
        """List-shaped field values (people/options) stringify to text."""
        table_resp = _make_response(data={
            "items": [{"table_id": "t1", "name": "T"}]
        })
        rec_resp = _make_response(data={
            "items": [{
                "fields": {
                    "负责人": [{"name": "Alice"}, {"name": "Bob"}],
                    "标签": [{"text": "P0"}, {"text": "bug"}],
                }
            }],
            "has_more": False,
        })
        client = _StubClient([table_resp, rec_resp])
        text = fcu.read_bitable_as_text(client, "app1")
        self.assertIn("Alice, Bob", text)
        self.assertIn("P0, bug", text)


class TestDoRequest(unittest.TestCase):
    def test_parses_raw_content_data(self):
        import json as _json
        client = _StubClient(_make_response(raw_content=_json.dumps({"data": {"foo": "bar"}}).encode()))
        code, msg, data = fcu.do_request(client, "GET", "/x", paths={"a": "b"})
        self.assertEqual(code, 0)
        self.assertEqual(data, {"foo": "bar"})

    def test_falls_back_to_response_data_attr(self):
        client = _StubClient(_make_response(data={"k": "v"}))
        code, msg, data = fcu.do_request(client, "POST", "/x", body={"a": 1})
        self.assertEqual(data, {"k": "v"})

    def test_unsupported_method_raises(self):
        client = _StubClient(_make_response())
        with self.assertRaises(ValueError):
            fcu.do_request(client, "DELETE", "/x")


class TestExtractTokenBitable(unittest.TestCase):
    def test_bitable_url(self):
        tok, is_wiki = fcu.extract_token("https://xxx.feishu.cn/base/AppToken123")
        self.assertEqual(tok, "AppToken123")
        self.assertFalse(is_wiki)

    def test_bitable_url_variant(self):
        tok, is_wiki = fcu.extract_token("https://xxx.feishu.cn/bitable/AppToken456")
        self.assertEqual(tok, "AppToken456")
        self.assertFalse(is_wiki)


class TestReadTableRecordsPagination(unittest.TestCase):
    def test_multi_page_records(self):
        """Records continue across pages until has_more is False."""
        page1 = _make_response(data={
            "items": [
                {"fields": {"name": "Alice"}},
                {"fields": {"name": "Bob"}},
            ],
            "has_more": True,
            "page_token": "page2tok",
        })
        page2 = _make_response(data={
            "items": [
                {"fields": {"name": "Charlie"}},
            ],
            "has_more": False,
        })
        client = _StubClient([page1, page2])
        records = fcu._read_table_records(client, "app1", "tbl1", max_records=100)
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0]["name"], "Alice")
        self.assertEqual(records[2]["name"], "Charlie")
        self.assertEqual(len(client.calls), 2)

    def test_max_records_truncates_mid_page(self):
        """Reading stops when max_records is reached."""
        page1 = _make_response(data={
            "items": [
                {"fields": {"v": "1"}},
                {"fields": {"v": "2"}},
                {"fields": {"v": "3"}},
            ],
            "has_more": True,
            "page_token": "next",
        })
        client = _StubClient(page1)
        records = fcu._read_table_records(client, "app1", "tbl1", max_records=2)
        self.assertEqual(len(records), 2)

    def test_api_error_breaks_loop(self):
        client = _StubClient(_make_response(code=1254000, msg="err"))
        records = fcu._read_table_records(client, "app1", "tbl1", max_records=100)
        self.assertEqual(records, [])


class TestReadSheetAsText(unittest.TestCase):
    def test_reads_single_sheet(self):
        meta_resp = _make_response(data={
            "sheets": [
                {
                    "sheet_id": "s1",
                    "title": "Sheet1",
                    "grid_properties": {"row_count": 2, "column_count": 2},
                }
            ]
        })
        values_resp = _make_response(data={
            "valueRange": {
                "values": [
                    ["Name", "Age"],
                    ["Alice", 30],
                ]
            }
        })
        client = _StubClient([meta_resp, values_resp])
        text = fcu.read_sheet_as_text(client, "spreadsheet123")
        self.assertIn("Sheet1", text)
        self.assertIn("Name\tAge", text)
        self.assertIn("Alice\t30", text)

    def test_handles_empty_sheet(self):
        meta_resp = _make_response(data={
            "sheets": [
                {"sheet_id": "s1", "title": "Empty", "grid_properties": {"row_count": 0, "column_count": 0}}
            ]
        })
        client = _StubClient(meta_resp)
        text = fcu.read_sheet_as_text(client, "ss1")
        self.assertIn("Empty", text)
        self.assertIn("(empty sheet)", text)

    def test_handles_api_error(self):
        client = _StubClient(_make_response(code=1254000, msg="not found"))
        text = fcu.read_sheet_as_text(client, "bad")
        self.assertIn("Failed to read spreadsheet", text)
        self.assertIn("1254000", text)

    def test_handles_no_sheets(self):
        client = _StubClient(_make_response(data={"sheets": []}))
        text = fcu.read_sheet_as_text(client, "ss1")
        self.assertIn("has no sheets", text)

    def test_multi_sheet_with_nested_data(self):
        """Data wrapped under data.spreadsheet.sheets is also handled."""
        meta_resp = _make_response(data={
            "spreadsheet": {
                "sheets": [
                    {
                        "sheet_id": "a",
                        "title": "Tab A",
                        "grid_properties": {"row_count": 1, "column_count": 1},
                    },
                    {
                        "sheet_id": "b",
                        "title": "Tab B",
                        "grid_properties": {"row_count": 1, "column_count": 1},
                    },
                ]
            }
        })
        val_a = _make_response(data={"valueRange": {"values": [["hello"]]}})
        val_b = _make_response(data={"valueRange": {"values": [["world"]]}})
        client = _StubClient([meta_resp, val_a, val_b])
        text = fcu.read_sheet_as_text(client, "ss1")
        self.assertIn("Tab A", text)
        self.assertIn("Tab B", text)
        self.assertIn("hello", text)
        self.assertIn("world", text)

    def test_column_letter_generation(self):
        """Verify _col_letter produces correct A1-style column names."""
        self.assertEqual(fcu._col_letter(1), "A")
        self.assertEqual(fcu._col_letter(26), "Z")
        self.assertEqual(fcu._col_letter(27), "AA")
        self.assertEqual(fcu._col_letter(52), "AZ")


if __name__ == "__main__":
    unittest.main()
