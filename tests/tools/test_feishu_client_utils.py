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


def _make_response(code=0, msg="", data=None, raw_content=None, headers=None, status_code=200):
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
        r.raw.headers = headers or {}
        r.raw.status_code = status_code
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
        tok, is_wiki, inferred = fcu.extract_token("ABCdef123")
        self.assertEqual(tok, "ABCdef123")
        self.assertFalse(is_wiki)
        self.assertEqual(inferred, "")

    def test_docx_url(self):
        tok, is_wiki, inferred = fcu.extract_token("https://xxx.feishu.cn/docx/DocToken123")
        self.assertEqual(tok, "DocToken123")
        self.assertFalse(is_wiki)
        self.assertEqual(inferred, "docx")

    def test_wiki_url_is_flagged(self):
        tok, is_wiki, inferred = fcu.extract_token("https://xxx.feishu.cn/wiki/NodeToken456")
        self.assertEqual(tok, "NodeToken456")
        self.assertTrue(is_wiki)
        self.assertEqual(inferred, "")

    def test_wiki_url_strips_query_and_fragment(self):
        tok, is_wiki, inferred = fcu.extract_token(
            "https://xxx.feishu.cn/wiki/NodeToken456?from=menu#section"
        )
        self.assertEqual(tok, "NodeToken456")
        self.assertTrue(is_wiki)
        self.assertEqual(inferred, "")

    def test_sheets_url(self):
        tok, is_wiki, inferred = fcu.extract_token("https://xxx.feishu.cn/sheets/SheetToken")
        self.assertEqual(tok, "SheetToken")
        self.assertFalse(is_wiki)
        self.assertEqual(inferred, "sheet")

    def test_empty(self):
        self.assertEqual(fcu.extract_token(""), ("", False, ""))
        self.assertEqual(fcu.extract_token("   "), ("", False, ""))


class TestResolveWikiNode(unittest.TestCase):
    def test_parses_obj_token_and_type(self):
        client = _StubClient(_make_response(data={
            "node": {"obj_token": "realDocToken", "obj_type": "docx"}
        }))
        obj_token, obj_type, meta = fcu.resolve_wiki_node(client, "node123")
        self.assertEqual(obj_token, "realDocToken")
        self.assertEqual(obj_type, "docx")
        self.assertIsNone(meta)  # plain doc -> no folder metadata

    def test_folder_returns_metadata(self):
        client = _StubClient(_make_response(data={
            "node": {
                "obj_token": "folderObj",
                "obj_type": "docx",
                "title": "模型推理能力建设",
                "node_token": "nodeFolder",
                "has_child": True,
                "node_type": "origin",
                "space_id": "space123",
            }
        }))
        obj_token, obj_type, meta = fcu.resolve_wiki_node(client, "nodeFolder")
        self.assertEqual(obj_token, "folderObj")
        self.assertEqual(obj_type, "docx")
        self.assertIsNotNone(meta)
        self.assertTrue(meta["has_child"])
        self.assertEqual(meta["space_id"], "space123")
        self.assertEqual(meta["title"], "模型推理能力建设")

    def test_returns_none_on_api_error(self):
        client = _StubClient(_make_response(code=1254030, msg="no permission"))
        self.assertEqual(fcu.resolve_wiki_node(client, "node"), (None, None, None))

    def test_returns_none_when_node_missing(self):
        client = _StubClient(_make_response(data={}))
        self.assertEqual(fcu.resolve_wiki_node(client, "node"), (None, None, None))


class TestListWikiChildren(unittest.TestCase):
    def test_lists_child_titles(self):
        resp = _make_response(data={
            "items": [
                {"title": "DGX", "node_token": "ndgx", "has_child": True},
                {"title": "分布式多机多卡部署大模型", "node_token": "ndoc1", "has_child": False},
            ],
            "has_more": False,
        })
        client = _StubClient([resp])
        text = fcu.list_wiki_children(client, "space123", "parent")
        self.assertIn("[文件夹] DGX", text)
        self.assertIn("node_token=ndgx", text)
        self.assertIn("[文档] 分布式多机多卡部署大模型", text)
        self.assertIn("node_token=ndoc1", text)

    def test_paginates(self):
        r1 = _make_response(data={
            "items": [{"title": "A", "node_token": "na", "has_child": False}],
            "has_more": True, "page_token": "p1",
        })
        r2 = _make_response(data={
            "items": [{"title": "B", "node_token": "nb", "has_child": False}],
            "has_more": False,
        })
        client = _StubClient([r1, r2])
        text = fcu.list_wiki_children(client, "space123", "parent")
        self.assertIn("- [文档] A", text)
        self.assertIn("- [文档] B", text)

    def test_empty_folder(self):
        client = _StubClient([_make_response(data={"items": [], "has_more": False})])
        self.assertIn("empty folder", fcu.list_wiki_children(client, "s", "p"))

    def test_caps_at_max_child_nodes(self):
        # One page of 300 items: the listing must stop at _WIKI_MAX_CHILD_NODES
        # instead of scanning every node (P2-5).
        many = [
            {"title": f"n{i}", "node_token": f"tok{i}", "has_child": False}
            for i in range(300)
        ]
        client = _StubClient(
            [_make_response(data={"items": many, "has_more": True, "page_token": "p1"})]
        )
        text = fcu.list_wiki_children(client, "s", "p")
        lines = [l for l in text.splitlines() if l.startswith("- ")]
        self.assertEqual(len(lines), fcu._WIKI_MAX_CHILD_NODES)
        self.assertIn("超过上限", text)
        self.assertEqual(len(client.calls), 1)  # no further pagination

    def test_missing_space_id(self):
        self.assertIn(
            "missing space_id",
            fcu.list_wiki_children(_StubClient([]), "", "p"),
        )

    def test_reports_api_error(self):
        client = _StubClient([_make_response(code=1254000, msg="bad space")])
        self.assertIn("Failed to list wiki children", fcu.list_wiki_children(client, "s", "p"))


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


class TestReadBitableModes(unittest.TestCase):
    """New bitable control modes: structure, table_index, limit, filter, totals."""

    def test_structure_mode_lists_tables_fields_and_totals(self):
        table_resp = _make_response(data={"items": [
            {"table_id": "tblA", "name": "Tasks"},
        ]})
        fields_resp = _make_response(data={"items": [
            {"field_name": "任务", "type": 1},
            {"field_name": "日计费率", "type": 20},
            {"field_name": "序号", "type": 1005},
        ]})
        total_resp = _make_response(data={"items": [], "total": 500})
        client = _StubClient([table_resp, fields_resp, total_resp])
        text = fcu.read_bitable_as_text(client, "app1", mode="structure")
        self.assertIn("Tasks", text)
        self.assertIn("任务 (文本)", text)
        self.assertIn("日计费率 (双向关联)", text)
        self.assertIn("序号 (公式) [公式]", text)
        self.assertIn("记录数=500", text)
        # structure mode must NOT dump any record data
        self.assertNotIn("记录 1:", text)

    def test_full_mode_reports_total_when_capped(self):
        table_resp = _make_response(data={"items": [{"table_id": "t1", "name": "Big"}]})
        rec_resp = _make_response(data={
            "items": [{"fields": {"v": str(i)}} for i in range(3)],
            "total": 999,
            "has_more": False,
        })
        client = _StubClient([table_resp, rec_resp])
        text = fcu.read_bitable_as_text(client, "app1", limit=3)
        self.assertIn("实际共 999 条", text)

    def test_table_index_selects_single_table(self):
        table_resp = _make_response(data={"items": [
            {"table_id": "t1", "name": "TableA"},
            {"table_id": "t2", "name": "TableB"},
        ]})
        rec_resp = _make_response(data={"items": [{"fields": {"x": "1"}}], "has_more": False})
        client = _StubClient([table_resp, rec_resp])
        text = fcu.read_bitable_as_text(client, "app1", table_index=2)
        self.assertIn("表 1: TableB", text)
        self.assertNotIn("TableA", text)

    def test_table_index_out_of_range(self):
        table_resp = _make_response(data={"items": [{"table_id": "t1", "name": "A"}]})
        client = _StubClient(table_resp)
        text = fcu.read_bitable_as_text(client, "app1", table_index=5)
        self.assertIn("out of range", text)

    def test_invalid_mode_rejected_before_network(self):
        client = _StubClient(_make_response())
        text = fcu.read_bitable_as_text(client, "app1", mode="bogus")
        self.assertIn("mode must be", text)
        self.assertEqual(len(client.calls), 0)

    def test_default_listing_caps_at_max_tables(self):
        items = [{"table_id": f"t{i}", "name": f"T{i}"} for i in range(60)]
        client = _StubClient(_make_response(
            data={"items": items, "total": 60, "has_more": False}
        ))
        text = fcu.read_bitable_as_text(client, "app1", mode="structure")
        self.assertIn("共 60 表", text)
        self.assertIn("超过上限", text)
        self.assertIn("T1", text)
        self.assertNotIn("T59", text)

    def test_table_index_past_default_cap_still_selectable(self):
        items = [{"table_id": f"t{i}", "name": f"T{i}"} for i in range(60)]
        table_resp = _make_response(
            data={"items": items, "total": 60, "has_more": False}
        )
        rec_resp = _make_response(
            data={"items": [{"fields": {"x": "1"}}], "has_more": False}
        )
        client = _StubClient([table_resp, rec_resp])
        text = fcu.read_bitable_as_text(client, "app1", table_index=55)
        self.assertIn("T54", text)
        self.assertNotIn("超过上限", text)


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
        tok, is_wiki, inferred = fcu.extract_token("https://xxx.feishu.cn/base/AppToken123")
        self.assertEqual(tok, "AppToken123")
        self.assertFalse(is_wiki)
        self.assertEqual(inferred, "bitable")

    def test_bitable_url_variant(self):
        tok, is_wiki, inferred = fcu.extract_token("https://xxx.feishu.cn/bitable/AppToken456")
        self.assertEqual(tok, "AppToken456")
        self.assertFalse(is_wiki)
        self.assertEqual(inferred, "bitable")


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
        records, total = fcu._read_table_records(client, "app1", "tbl1", max_records=100)
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0]["name"], "Alice")
        self.assertEqual(records[2]["name"], "Charlie")
        self.assertEqual(len(client.calls), 2)

    def test_returns_total_from_first_page(self):
        page1 = _make_response(data={
            "items": [{"fields": {"name": "Alice"}}],
            "total": 999,
            "has_more": False,
        })
        client = _StubClient(page1)
        records, total = fcu._read_table_records(client, "app1", "tbl1", max_records=100)
        self.assertEqual(total, 999)

    def test_passes_filter_query(self):
        page1 = _make_response(data={
            "items": [{"fields": {"GPU": "H800"}}],
            "total": 1,
            "has_more": False,
        })
        client = _StubClient(page1)
        _, total = fcu._read_table_records(
            client, "app1", "tbl1", max_records=100,
            filter_expr='CurrentValue.[GPU]="H800"')
        self.assertEqual(total, 1)
        # the filter must be in the request queries
        qs = dict(client.calls[0].queries or [])
        self.assertEqual(qs.get("filter"), 'CurrentValue.[GPU]="H800"')

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
        records, _ = fcu._read_table_records(client, "app1", "tbl1", max_records=2)
        self.assertEqual(len(records), 2)

    def test_api_error_breaks_loop(self):
        client = _StubClient(_make_response(code=1254000, msg="err"))
        records, total = fcu._read_table_records(client, "app1", "tbl1", max_records=100)
        self.assertEqual(records, [])
        self.assertIsNone(total)


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


# ---------------------------------------------------------------------------
# Docx image materialization
# ---------------------------------------------------------------------------

# Minimal valid PNG (1x1 pixel)
_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f"
    b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


class TestListDocxImageTokens(unittest.TestCase):
    def test_extracts_image_blocks_in_order(self):
        blocks = _make_response(data={
            "items": [
                {"block_type": 1, "text": {"elements": []}},
                {
                    "block_type": 27,
                    "image": {"token": "imgTokA", "width": 100, "height": 50},
                },
                {"block_type": 2},
                {
                    "block_type": 27,
                    "image": {"token": "imgTokB", "width": 200, "height": 80},
                },
            ],
            "has_more": False,
        })
        client = _StubClient(blocks)
        images = fcu.list_docx_image_tokens(client, "doc123")
        self.assertEqual(len(images), 2)
        self.assertEqual(images[0]["token"], "imgTokA")
        self.assertEqual(images[0]["width"], 100)
        self.assertEqual(images[1]["token"], "imgTokB")

    def test_paginates_blocks(self):
        page1 = _make_response(data={
            "items": [
                {"block_type": 27, "image": {"token": "t1"}},
            ],
            "has_more": True,
            "page_token": "p2",
        })
        page2 = _make_response(data={
            "items": [
                {"block_type": 27, "image": {"token": "t2"}},
            ],
            "has_more": False,
        })
        client = _StubClient([page1, page2])
        images = fcu.list_docx_image_tokens(client, "doc123")
        self.assertEqual([i["token"] for i in images], ["t1", "t2"])
        self.assertEqual(len(client.calls), 2)

    def test_respects_max_images(self):
        blocks = _make_response(data={
            "items": [
                {"block_type": 27, "image": {"token": f"t{i}"}}
                for i in range(5)
            ],
            "has_more": False,
        })
        client = _StubClient(blocks)
        images = fcu.list_docx_image_tokens(client, "doc", max_images=2)
        self.assertEqual(len(images), 2)

    def test_skips_image_blocks_without_token(self):
        blocks = _make_response(data={
            "items": [
                {"block_type": 27, "image": {}},
                {"block_type": 27, "image": {"token": "ok"}},
            ],
            "has_more": False,
        })
        client = _StubClient(blocks)
        images = fcu.list_docx_image_tokens(client, "doc")
        self.assertEqual([i["token"] for i in images], ["ok"])

    def test_api_error_returns_empty(self):
        client = _StubClient(_make_response(code=999, msg="fail"))
        self.assertEqual(fcu.list_docx_image_tokens(client, "doc"), [])


class TestInjectImagePaths(unittest.TestCase):
    def test_replaces_placeholders_in_order(self):
        content = "before\nimage.png\nmiddle\nimage.png\nafter"
        images = [
            {"index": 1, "path": "/tmp/a.png", "error": None, "analysis": "图A文字"},
            {"index": 2, "path": "/tmp/b.png", "error": None, "analysis": "图B文字"},
        ]
        out = fcu.inject_image_paths_into_content(content, images)
        self.assertIn("[Image 1: /tmp/a.png]", out)
        self.assertIn("图A文字", out)
        self.assertIn("[Image 2: /tmp/b.png]", out)
        self.assertIn("图B文字", out)
        self.assertNotIn("image.png", out)
        self.assertIn("before", out)
        self.assertIn("after", out)

    def test_failed_download_marker(self):
        content = "x image.png y"
        images = [{"index": 1, "path": "", "error": "HTTP 403"}]
        out = fcu.inject_image_paths_into_content(content, images)
        self.assertIn("[Image 1: unavailable (HTTP 403)]", out)

    def test_appendix_when_more_images_than_placeholders(self):
        content = "only one image.png here"
        images = [
            {"index": 1, "path": "/tmp/a.png", "analysis": "first"},
            {"index": 2, "path": "/tmp/b.png", "analysis": "second"},
        ]
        out = fcu.inject_image_paths_into_content(content, images)
        self.assertIn("[Image 1: /tmp/a.png]", out)
        self.assertIn("first", out)
        self.assertIn("--- Document images ---", out)
        self.assertIn("[Image 2: /tmp/b.png]", out)
        self.assertIn("second", out)

    def test_vision_error_keeps_path_hint(self):
        content = "image.png"
        images = [{
            "index": 1,
            "path": "/tmp/a.png",
            "vision_error": "vision backend not configured",
        }]
        out = fcu.inject_image_paths_into_content(content, images)
        self.assertIn("[Image 1: /tmp/a.png]", out)
        self.assertIn("vision unavailable", out)
        self.assertIn("vision_analyze", out)

    def test_empty_images_passthrough(self):
        self.assertEqual(
            fcu.inject_image_paths_into_content("hello image.png", []),
            "hello image.png",
        )


class TestSniffAndSlug(unittest.TestCase):
    def test_sniff_png(self):
        self.assertEqual(fcu._sniff_image_ext(_PNG_1X1), ".png")

    def test_sniff_jpeg(self):
        self.assertEqual(fcu._sniff_image_ext(b"\xff\xd8\xff\xe0rest"), ".jpg")

    def test_safe_slug_strips(self):
        self.assertEqual(fcu._safe_slug("ab/../cd!@#ef"), "abcdef")
        self.assertEqual(fcu._safe_slug(""), "img")


class TestDownloadDocxImages(unittest.TestCase):
    def test_writes_png_to_cache(self):
        import tempfile
        from pathlib import Path

        media_resp = _make_response(
            raw_content=_PNG_1X1,
            headers={"Content-Type": "image/png"},
            status_code=200,
        )
        client = _StubClient(media_resp)
        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = Path(tmp) / ".hermes"
            hermes_home.mkdir()
            with mock.patch.dict("os.environ", {"HERMES_HOME": str(hermes_home)}):
                results = fcu.download_docx_images(
                    client,
                    "DocTokenXYZ",
                    [{"token": "MediaTok1", "width": 10, "height": 20}],
                )
            self.assertEqual(len(results), 1)
            self.assertIsNone(results[0]["error"])
            path = Path(results[0]["path"])
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_bytes(), _PNG_1X1)
            self.assertTrue(str(path).endswith(".png"))
            self.assertEqual(results[0]["bytes"], len(_PNG_1X1))

    def test_download_error_recorded(self):
        err_body = b'{"code": 99991400, "msg": "rate limited"}'
        media_resp = _make_response(
            code=99991400,
            msg="rate limited",
            raw_content=err_body,
            headers={"Content-Type": "application/json"},
            status_code=400,
        )
        client = _StubClient(media_resp)
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = Path(tmp) / ".hermes"
            hermes_home.mkdir()
            with mock.patch.dict("os.environ", {"HERMES_HOME": str(hermes_home)}):
                results = fcu.download_docx_images(
                    client, "doc", [{"token": "badTok"}]
                )
        self.assertEqual(results[0]["path"], "")
        self.assertIn("99991400", results[0]["error"])

    def test_rejects_oversized_image(self):
        big = b"\x89PNG\r\n\x1a\n" + (b"x" * 100)
        media_resp = _make_response(
            raw_content=big,
            headers={"Content-Type": "image/png"},
        )
        client = _StubClient(media_resp)
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = Path(tmp) / ".hermes"
            hermes_home.mkdir()
            with mock.patch.dict("os.environ", {"HERMES_HOME": str(hermes_home)}):
                results = fcu.download_docx_images(
                    client,
                    "doc",
                    [{"token": "bigTok"}],
                    max_bytes=50,
                )
        self.assertIn("too large", results[0]["error"])
        self.assertEqual(results[0]["path"], "")


class TestRateLimitRetry(unittest.TestCase):
    def test_detects_429_and_feishu_codes(self):
        self.assertTrue(fcu._is_rate_limited_error("HTTP 429 Too Many Requests"))
        self.assertTrue(fcu._is_rate_limited_error("code=99991400 msg=rate limited"))
        self.assertTrue(fcu._is_rate_limited_error("RateLimitError: quota exceeded"))
        self.assertFalse(fcu._is_rate_limited_error("HTTP 403 forbidden"))
        self.assertFalse(fcu._is_rate_limited_error(None))

    def test_retries_then_succeeds(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                return None, "HTTP 429 rate limited"
            return b"ok", None

        with mock.patch.object(fcu, "_rate_limit_sleep", return_value=0.0) as sleep_mock:
            data, err = fcu._call_with_rate_limit_retry(flaky, label="test", max_retries=5)

        self.assertEqual(data, b"ok")
        self.assertIsNone(err)
        self.assertEqual(calls["n"], 3)
        self.assertEqual(sleep_mock.call_count, 2)

    def test_gives_up_after_max_retries(self):
        calls = {"n": 0}

        def always_429():
            calls["n"] += 1
            return None, "429"

        with mock.patch.object(fcu, "_rate_limit_sleep", return_value=0.0):
            data, err = fcu._call_with_rate_limit_retry(
                always_429, label="test", max_retries=2,
            )

        self.assertIsNone(data)
        self.assertEqual(err, "429")
        # initial + 2 retries = 3
        self.assertEqual(calls["n"], 3)

    def test_non_rate_limit_not_retried(self):
        calls = {"n": 0}

        def hard_fail():
            calls["n"] += 1
            return None, "HTTP 403 forbidden"

        with mock.patch.object(fcu, "_rate_limit_sleep") as sleep_mock:
            data, err = fcu._call_with_rate_limit_retry(hard_fail, label="test")

        self.assertEqual(err, "HTTP 403 forbidden")
        self.assertEqual(calls["n"], 1)
        sleep_mock.assert_not_called()


class TestPruneDocxImageCache(unittest.TestCase):
    def test_vanished_file_during_stat_does_not_raise(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = Path(tmp) / ".hermes"
            cache = hermes_home / "cache" / "feishu_doc_images" / "doc"
            cache.mkdir(parents=True)
            gone = cache / "gone.png"
            gone.write_bytes(b"x")
            kept = cache / "kept.png"
            kept.write_bytes(b"y")

            real_stat = Path.stat

            def flaky_stat(self, *args, **kwargs):
                if self == gone:
                    raise FileNotFoundError(str(self))
                return real_stat(self, *args, **kwargs)

            with mock.patch.dict("os.environ", {"HERMES_HOME": str(hermes_home)}):
                with mock.patch.object(Path, "stat", flaky_stat):
                    fcu._prune_docx_image_cache()

    def test_download_media_retries_on_429(self):
        err_body = b'{"code": 99991400, "msg": "rate limited"}'
        fail = _make_response(
            code=99991400,
            msg="rate limited",
            raw_content=err_body,
            headers={"Content-Type": "application/json"},
            status_code=400,
        )
        ok = _make_response(
            raw_content=_PNG_1X1,
            headers={"Content-Type": "image/png"},
            status_code=200,
        )
        client = _StubClient([fail, ok])
        with mock.patch.object(fcu, "_rate_limit_sleep", return_value=0.0):
            data, ct, err = fcu.download_media(client, "tok1")
        self.assertIsNone(err)
        self.assertEqual(data, _PNG_1X1)
        self.assertEqual(len(client.calls), 2)


class TestAnalyzeDocxImages(unittest.TestCase):
    def test_attaches_analysis_from_vision(self):
        images = [
            {"index": 1, "path": "/tmp/a.png", "error": None},
            {"index": 2, "path": "/tmp/b.png", "error": None},
        ]

        def fake_analyze(path, prompt):
            return (f"OCR for {path}", None)

        with mock.patch(
            "tools.vision_tools.check_vision_requirements", return_value=True,
        ), mock.patch.object(fcu, "_analyze_one_image", side_effect=fake_analyze):
            out = fcu.analyze_docx_images(images, max_workers=2)

        self.assertEqual(out[0]["analysis"], "OCR for /tmp/a.png")
        self.assertEqual(out[1]["analysis"], "OCR for /tmp/b.png")

    def test_marks_when_vision_unavailable(self):
        images = [{"index": 1, "path": "/tmp/a.png", "error": None}]
        with mock.patch(
            "tools.vision_tools.check_vision_requirements", return_value=False,
        ):
            out = fcu.analyze_docx_images(images)
        self.assertIn("not configured", out[0].get("vision_error", ""))
        self.assertIsNone(out[0].get("analysis"))

    def test_respects_max_vision_cap(self):
        images = [
            {"index": i, "path": f"/tmp/{i}.png", "error": None}
            for i in range(1, 5)
        ]
        with mock.patch(
            "tools.vision_tools.check_vision_requirements", return_value=True,
        ), mock.patch.object(
            fcu, "_analyze_one_image", return_value=("ok", None),
        ):
            out = fcu.analyze_docx_images(images, max_vision=2)
        self.assertEqual(out[0].get("analysis"), "ok")
        self.assertEqual(out[1].get("analysis"), "ok")
        self.assertIn("capped", out[2].get("vision_error", ""))
        self.assertIn("capped", out[3].get("vision_error", ""))


class TestReadDocxWithImages(unittest.TestCase):
    def test_end_to_end_replaces_placeholders_and_ocr(self):
        import tempfile
        from pathlib import Path

        raw = _make_response(data={
            "content": "Title\nimage.png\nFooter text",
        })
        blocks = _make_response(data={
            "items": [
                {
                    "block_type": 27,
                    "image": {"token": "ImgTok1", "width": 736, "height": 202},
                },
            ],
            "has_more": False,
        })
        media = _make_response(
            raw_content=_PNG_1X1,
            headers={"Content-Type": "image/png"},
        )
        client = _StubClient([raw, blocks, media])

        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = Path(tmp) / ".hermes"
            hermes_home.mkdir()
            with mock.patch.dict("os.environ", {"HERMES_HOME": str(hermes_home)}), \
                 mock.patch(
                     "tools.vision_tools.check_vision_requirements",
                     return_value=True,
                 ), \
                 mock.patch.object(
                     fcu, "_analyze_one_image",
                     return_value=("聊天截图：模型起来了", None),
                 ):
                content, err, images = fcu.read_docx_with_images(client, "DocABC")

        self.assertIsNone(err)
        self.assertNotIn("image.png", content)
        self.assertIn("[Image 1:", content)
        self.assertIn("聊天截图：模型起来了", content)
        self.assertEqual(len(images), 1)
        self.assertTrue(images[0]["path"])
        self.assertEqual(images[0].get("analysis"), "聊天截图：模型起来了")
        self.assertIn(images[0]["path"], content)
        self.assertIn("Title", content)
        self.assertIn("Footer text", content)

    def test_analyze_images_false_skips_vision(self):
        import tempfile
        from pathlib import Path

        raw = _make_response(data={"content": "image.png"})
        blocks = _make_response(data={
            "items": [{"block_type": 27, "image": {"token": "T1"}}],
            "has_more": False,
        })
        media = _make_response(
            raw_content=_PNG_1X1,
            headers={"Content-Type": "image/png"},
        )
        client = _StubClient([raw, blocks, media])
        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = Path(tmp) / ".hermes"
            hermes_home.mkdir()
            with mock.patch.dict("os.environ", {"HERMES_HOME": str(hermes_home)}), \
                 mock.patch.object(fcu, "analyze_docx_images") as mock_vision:
                content, err, images = fcu.read_docx_with_images(
                    client, "DocSkip", analyze_images=False,
                )
        mock_vision.assert_not_called()
        self.assertIsNone(err)
        self.assertIn("[Image 1:", content)
        self.assertTrue(images[0]["path"])

    def test_no_images_returns_raw_text(self):
        raw = _make_response(data={"content": "just text"})
        blocks = _make_response(data={"items": [{"block_type": 1}], "has_more": False})
        client = _StubClient([raw, blocks])
        content, err, images = fcu.read_docx_with_images(client, "DocNoImg")
        self.assertIsNone(err)
        self.assertEqual(content, "just text")
        self.assertEqual(images, [])

    def test_raw_content_failure(self):
        client = _StubClient(_make_response(code=1770032, msg="forbidden"))
        content, err, images = fcu.read_docx_with_images(client, "DocX")
        self.assertIsNone(content)
        self.assertIn("1770032", err)
        self.assertEqual(images, [])


if __name__ == "__main__":
    unittest.main()
