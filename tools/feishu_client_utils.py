"""Shared helpers for the Feishu/Lark document and drive tools.

Responsibilities live here so ``feishu_doc_tool.py`` and
``feishu_drive_tool.py`` don't have to duplicate them:

1. **Fallback lark client.** Both tools are normally driven by a lark client
   that the comment-event handler injects per-thread (``set_client`` /
   ``get_client``). Outside a comment context (a plain DM or group chat) no
   client is injected and the tools used to refuse to run. When
   ``FEISHU_APP_ID`` + ``FEISHU_APP_SECRET`` are present in the environment we
   build a tenant client on demand and cache it process-wide.

2. **Wiki node resolution + bitable/sheet reading.** A wiki node token
   resolves to a real document (``obj_token``) whose type (``obj_type``) can
   be ``docx``, ``bitable``, ``sheet`` ... This module resolves the node and,
   for bitables/sheets, flattens content into readable plain text.

3. **Docx image materialization + vision OCR.** The docx ``raw_content`` API
   turns image blocks into text placeholders like ``image.png``. We list
   image blocks (``block_type=27``), download each via
   ``/drive/v1/medias/{token}/download``, write under
   ``$HERMES_HOME/cache/feishu_doc_images/``, run auxiliary
   ``vision_analyze`` on each local file, and inject both the path and the
   transcribed text into the returned document so the agent sees image
   content without a second tool round-trip.

``lark_oapi`` is imported lazily inside the functions that need it -- the SDK
eagerly loads a large surface and costs ~5s to import, which is why the
tool-availability probe (``_check_feishu``) uses ``find_spec`` instead.
"""

import concurrent.futures
import json
import logging
import os
import random
import re
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Process-wide cache of the fallback client. Guarded by ``_fallback_lock``
# because tool handlers run in worker threads.
_fallback_client = None
_fallback_lock = threading.Lock()


def get_fallback_client():
    """Return a cached tenant lark client built from env vars, or ``None``.

    Builds the client the first time it is needed and reuses it thereafter.
    Returns ``None`` when ``lark_oapi`` is not importable or the credentials
    are not configured -- callers then surface a helpful error.
    """
    global _fallback_client
    if _fallback_client is not None:
        return _fallback_client

    app_id = os.getenv("FEISHU_APP_ID")
    app_secret = os.getenv("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        return None

    with _fallback_lock:
        # Re-check inside the lock -- another thread may have built it.
        if _fallback_client is not None:
            return _fallback_client

        try:
            import lark_oapi as lark
        except ImportError:
            logger.debug("feishu_client_utils: lark_oapi not installed; no fallback client")
            return None

        builder = lark.Client.builder().app_id(app_id).app_secret(app_secret)
        # ``FEISHU_DOMAIN`` lets Lark (larksuite.com) users point at the
        # international endpoint; the default covers feishu.cn.
        domain = os.getenv("FEISHU_DOMAIN", "").strip()
        if domain:
            builder = builder.domain(domain)
        try:
            client = builder.build()
        except Exception:  # pragma: no cover - defensive, SDK raises varied types
            logger.exception("feishu_client_utils: failed to build fallback lark client")
            return None

        _fallback_client = client
        logger.info("feishu_client_utils: built cached fallback lark client from FEISHU_APP_ID/SECRET")
        return _fallback_client


def resolve_client(local_client):
    """Prefer an injected (comment-context) client; fall back to env-built one.

    ``local_client`` is the per-thread client from a tool module's
    ``get_client()``. When it is ``None`` (DM/group chat, not a comment event)
    we build one from the environment so the tools still work.
    """
    if local_client is not None:
        return local_client
    return get_fallback_client()


# ---------------------------------------------------------------------------
# Low-level request helper (mirrors feishu_drive_tool._do_request)
# ---------------------------------------------------------------------------

def do_request(client, method, uri, paths=None, queries=None, body=None):
    """Build and execute a BaseRequest. Returns ``(code, msg, data_dict)``.

    ``data_dict`` is the parsed ``data`` object from the response body (or
    ``{}`` if there was none).
    """
    from lark_oapi import AccessTokenType
    from lark_oapi.core.enum import HttpMethod
    from lark_oapi.core.model.base_request import BaseRequest

    _METHOD_MAP = {"GET": HttpMethod.GET, "POST": HttpMethod.POST}
    http_method = _METHOD_MAP.get(method)
    if http_method is None:
        raise ValueError(f"Unsupported HTTP method: {method}")

    builder = (
        BaseRequest.builder()
        .http_method(http_method)
        .uri(uri)
        .token_types({AccessTokenType.TENANT})
    )
    if paths:
        builder = builder.paths(paths)
    if queries:
        builder = builder.queries(queries)
    if body is not None:
        builder = builder.body(body)

    request = builder.build()

    # Tool handlers run synchronously in a worker thread (no running event
    # loop), so call the blocking lark client directly.
    response = client.request(request)

    code = getattr(response, "code", None)
    msg = getattr(response, "msg", "")

    data = {}
    raw = getattr(response, "raw", None)
    if raw and hasattr(raw, "content"):
        try:
            body_json = json.loads(raw.content)
            data = body_json.get("data", {}) or {}
        except (json.JSONDecodeError, AttributeError, ValueError):
            logger.debug("feishu_client_utils: failed to parse raw.content, falling back to response.data")
    if not data:
        resp_data = getattr(response, "data", None)
        if isinstance(resp_data, dict):
            data = resp_data
        elif resp_data and hasattr(resp_data, "__dict__"):
            data = vars(resp_data)

    return code, msg, data


# ---------------------------------------------------------------------------
# Token extraction + wiki node resolution
# ---------------------------------------------------------------------------

# Path prefix -> Feishu obj_type. Wiki is omitted: the node must be resolved
# before the real type is known. Unknown / bare tokens yield "".
_TOKEN_PREFIX_TYPES = (
    ("/docx/", "docx"),
    ("/doc/", "docx"),
    ("/sheets/", "sheet"),
    ("/base/", "bitable"),
    ("/bitable/", "bitable"),
)


def extract_token(raw):
    """Pull the document token out of a user-supplied value.

    Accepts a bare token or a Feishu/Lark URL. Returns
    ``(token, is_wiki, inferred_type)``:

    - ``is_wiki`` is True only for ``/wiki/<node_token>`` URLs, because that
      is the one case where the raw token is a wiki *node* token rather than
      the final document token.
    - ``inferred_type`` is the document type inferred from the URL path
      (``"docx"`` / ``"sheet"`` / ``"bitable"``), or ``""`` when unknown
      (bare token, wiki URL that still needs ``resolve_wiki_node``, or an
      unrecognised path). Callers should fall back to a default (typically
      ``"docx"``) when the value is empty.
    """
    if not raw:
        return "", False, ""
    value = raw.strip()

    # URL form -- pull the path segment after the recognised doc path.
    if value.startswith("http://") or value.startswith("https://"):
        # Strip any fragment/query first.
        for sep in ("#", "?"):
            if sep in value:
                value = value.split(sep, 1)[0]
        # ``/wiki/<node_token>`` -> the node token must be resolved; type unknown.
        if "/wiki/" in value:
            node = value.rsplit("/wiki/", 1)[1].strip("/")
            # A trailing path segment only; ignore anything after the token.
            node = node.split("/", 1)[0] if "/" in node else node
            return node, True, ""
        # ``/docx/<token>`` / ``/doc/<token>`` / ``/sheets/<token>`` /
        # ``/base/<token>`` / ``/bitable/<token>`` -- token is the obj_token.
        for prefix, inferred_type in _TOKEN_PREFIX_TYPES:
            if prefix in value:
                tok = value.rsplit(prefix, 1)[1].strip("/")
                tok = tok.split("/", 1)[0] if "/" in tok else tok
                return tok, False, inferred_type
        # Unknown URL shape -- take the last path segment; type unknown.
        tail = value.rstrip("/").rsplit("/", 1)[-1]
        return tail, False, ""

    # Bare token -- type cannot be inferred from the string alone.
    return value, False, ""


_WIKI_GET_NODE_URI = "/open-apis/wiki/v2/spaces/get_node"
_WIKI_NODES_URI = "/open-apis/wiki/v2/spaces/:space_id/nodes"
# Cap the one-level folder listing so an oversized wiki folder cannot fan out
# into unbounded pagination / token bloat.
_WIKI_MAX_CHILD_NODES = 200


def resolve_wiki_node(client, node_token):
    """Resolve a wiki node token to ``(obj_token, obj_type, node_meta)``.

    Returns ``(None, None, None)`` when the token is not a wiki node or the
    API rejects it. ``obj_type`` is one of ``docx`` / ``bitable`` / ``sheet`` /
    ``mindnote`` / ... (anything Feishu reports).

    ``node_meta`` is a dict of node metadata used to tell a real document from
    a wiki *folder* (which holds child nodes and has no readable body)::

        {
            "title": str,          # node title
            "node_token": str,     # node token (== the input)
            "obj_type": str,       # document type the folder/obj resolves to
            "has_child": bool,     # True for a folder with children
            "node_type": str,      # "origin" / "shortcut"
            "space_id": str,       # wiki space id (needed to list children)
        }

    ``node_meta`` is ``None`` for a plain (non-folder) document node; callers
    that don't need folder semantics can ignore it.
    """
    code, msg, data = do_request(
        client, "GET", _WIKI_GET_NODE_URI,
        queries=[("token", node_token)],
    )
    if code != 0:
        logger.debug("feishu_client_utils: wiki get_node failed code=%s msg=%s", code, msg)
        return None, None, None

    node = data.get("node") if isinstance(data, dict) else None
    if not isinstance(node, dict):
        return None, None, None

    obj_token = node.get("obj_token") or ""
    obj_type = node.get("obj_type") or ""
    if not obj_token or not obj_type:
        return None, None, None

    has_child = bool(node.get("has_child"))
    meta = None
    if has_child:
        meta = {
            "title": node.get("title") or "",
            "node_token": node.get("node_token") or node_token,
            "obj_type": obj_type,
            "has_child": has_child,
            "node_type": node.get("node_type") or "",
            "space_id": node.get("space_id") or "",
        }
    return obj_token, obj_type, meta


def list_wiki_children(client, space_id, parent_node_token):
    """List the direct child nodes of a wiki folder as readable text.

    Uses the paged ``nodes`` endpoint (``page_size=50``) rather than
    ``get_children``, which can return empty for deep sub-folders. Returns a
    flat one-level listing of child node titles with a type marker
    (``[文件夹]`` / ``[文档]``) and the node token, or an error string
    starting with ``Failed to list wiki children``. Pagination is capped at
    ``_WIKI_MAX_CHILD_NODES`` so an oversized folder cannot run away.
    """
    if not space_id:
        return "Failed to list wiki children: missing space_id"

    lines = []
    page_token = ""
    while True:
        queries = [("parent_node_token", parent_node_token), ("page_size", "50")]
        if page_token:
            queries.append(("page_token", page_token))
        code, msg, data = do_request(
            client, "GET", _WIKI_NODES_URI,
            paths={"space_id": space_id},
            queries=queries,
        )
        if code != 0:
            logger.debug("feishu_client_utils: wiki nodes failed code=%s msg=%s", code, msg)
            return f"Failed to list wiki children: {msg or code}"

        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return "Failed to list wiki children: unexpected response"
        for node in items:
            if not isinstance(node, dict):
                continue
            if len(lines) >= _WIKI_MAX_CHILD_NODES:
                lines.append(f"⚠️ 子节点超过上限，仅展示前 {_WIKI_MAX_CHILD_NODES} 个。")
                return "\n".join(lines)
            title = node.get("title") or "(untitled)"
            ntoken = node.get("node_token") or ""
            marker = "[文件夹]" if node.get("has_child") else "[文档]"
            suffix = f" node_token={ntoken}" if ntoken else ""
            lines.append(f"- {marker} {title}{suffix}")

        has_more = data.get("has_more") if isinstance(data, dict) else None
        page_token = data.get("page_token") or "" if isinstance(data, dict) else ""
        if not has_more or not page_token:
            break

    if not lines:
        return "(empty folder — no child nodes)"
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Bitable (多维表格) reading
# ---------------------------------------------------------------------------

_BITABLE_TABLES_URI = "/open-apis/bitable/v1/apps/:app_token/tables"
_BITABLE_RECORDS_URI = "/open-apis/bitable/v1/apps/:app_token/tables/:table_id/records"
_BITABLE_FIELDS_URI = "/open-apis/bitable/v1/apps/:app_token/tables/:table_id/fields"
# Cap how many records/tables we pull so the tool can't run away on a huge
# base. 500 records per table and 50 tables is plenty for "give me context".
_BITABLE_MAX_TABLES = 50
_BITABLE_PAGE_SIZE = 100
_BITABLE_MAX_RECORDS_PER_TABLE = 500

# Bitable field type int -> human label (from the bitable fields API).
# type 19/1005 are real formula fields; type 18/20 are lookup / duplex-link
# fields (关联/查找引用) which are derived and can bloat output.
_BITABLE_FIELD_TYPE_NAMES = {
    1: "文本", 2: "数字", 3: "单选", 4: "多选", 5: "日期", 7: "复选框",
    11: "人员", 13: "电话号码", 15: "超链接", 17: "附件", 18: "单向关联",
    19: "公式", 20: "双向关联", 21: "地理位置", 22: "群组", 23: "创建时间",
    24: "最后更新时间", 25: "创建人", 26: "修改人", 27: "自动编号",
    1001: "查找引用", 1002: "进度", 1003: "货币", 1004: "评分",
    1005: "公式",
}


def _stringify_field(value):
    """Render a bitable field value as readable text.

    Bitable fields can be scalars, lists (people/options/attachments), or
    nested dicts. We collapse to a compact string instead of dumping raw JSON.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                # Common shapes: {"text": "..."} (option/label),
                # {"name": "..."} (user), {"file_token": "..."} (attachment).
                for k in ("text", "name", "file_token", "title", "value"):
                    if k in item:
                        parts.append(str(item[k]))
                        break
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        return ", ".join(p for p in parts if p)
    if isinstance(value, dict):
        for k in ("text", "name", "value", "title"):
            if k in value:
                return str(value[k])
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _read_table_records(client, app_token, table_id, max_records, filter_expr=None):
    """Page through a table's records.

    Returns ``(records, total)`` where ``records`` is a list of
    ``{field: value}`` dicts and ``total`` is the API-reported total record
    count (or ``None`` when unavailable). ``filter_expr`` is passed through to
    the records API ``filter`` query when provided (e.g.
    ``CurrentValue.[GPU]="H800"``).
    """
    records = []
    total = None
    page_token = ""
    while True:
        queries = [("page_size", str(_BITABLE_PAGE_SIZE))]
        if page_token:
            queries.append(("page_token", page_token))
        if filter_expr:
            queries.append(("filter", filter_expr))
        code, msg, data = do_request(
            client, "GET", _BITABLE_RECORDS_URI,
            paths={"app_token": app_token, "table_id": table_id},
            queries=queries,
        )
        if code != 0:
            logger.debug(
                "feishu_client_utils: bitable records failed app=%s table=%s code=%s msg=%s",
                app_token, table_id, code, msg,
            )
            break

        if total is None:
            total = data.get("total")
        items = data.get("items") or []
        for rec in items:
            records.append(rec.get("fields", {}) if isinstance(rec, dict) else {})
            if len(records) >= max_records:
                break
        if len(records) >= max_records:
            break

        has_more = data.get("has_more")
        page_token = data.get("page_token", "") or ""
        if not has_more or not page_token:
            break
    return records, total


def _read_table_fields(client, app_token, table_id):
    """Return ``[(field_name, type_int, is_formula), ...]`` for a table.

    ``is_formula`` is True for type 19/1005 or when the field property flags
    ``is_formula``. On API error returns ``[]`` (callers degrade gracefully).
    """
    fields = []
    page_token = ""
    while True:
        queries = [("page_size", "100")]
        if page_token:
            queries.append(("page_token", page_token))
        code, msg, data = do_request(
            client, "GET", _BITABLE_FIELDS_URI,
            paths={"app_token": app_token, "table_id": table_id},
            queries=queries,
        )
        if code != 0:
            logger.debug(
                "feishu_client_utils: bitable fields failed app=%s table=%s code=%s msg=%s",
                app_token, table_id, code, msg,
            )
            break
        for fd in (data.get("items") or []):
            if not isinstance(fd, dict):
                continue
            prop = fd.get("property") or {}
            ftype = fd.get("type")
            is_formula = bool(prop.get("is_formula") or fd.get("is_formula")) \
                or ftype in (19, 1005)
            fields.append((fd.get("field_name") or "", ftype, is_formula))
        has_more = data.get("has_more")
        page_token = data.get("page_token", "") or ""
        if not has_more or not page_token:
            break
    return fields


def _table_record_total(client, app_token, table_id, filter_expr=None):
    """Return the record count for a table (from the records API ``total``).

    Reads a single record (page_size=1) so structure mode can report totals
    without pulling any row data. Returns ``None`` on API error.
    """
    queries = [("page_size", "1")]
    if filter_expr:
        queries.append(("filter", filter_expr))
    code, msg, data = do_request(
        client, "GET", _BITABLE_RECORDS_URI,
        paths={"app_token": app_token, "table_id": table_id},
        queries=queries,
    )
    if code != 0:
        return None
    return data.get("total")


def _list_bitable_tables(client, app_token, *, stop_after=None):
    """List tables (paginated), stopping after ``stop_after`` items.

    Default cap is ``_BITABLE_MAX_TABLES`` so a huge base cannot fan out
    into unbounded per-table record/field requests. Callers that need a
    specific ``table_index`` pass ``stop_after=table_index`` so table 51+
    stays addressable without listing the whole base.

    Returns ``(tables, total_tables, code, msg)``. ``total_tables`` keeps
    the real API total so the caller can report "N tables (first 50 shown)".
    """
    cap = stop_after if stop_after is not None else _BITABLE_MAX_TABLES
    if cap < 1:
        cap = _BITABLE_MAX_TABLES
    tables = []
    total = None
    page_token = ""
    while True:
        queries = [("page_size", "100")]
        if page_token:
            queries.append(("page_token", page_token))
        code, msg, data = do_request(
            client, "GET", _BITABLE_TABLES_URI,
            paths={"app_token": app_token},
            queries=queries,
        )
        if code != 0:
            return None, None, code, msg
        if total is None:
            total = data.get("total")
        tables += data.get("items") or []
        if len(tables) >= cap:
            tables = tables[:cap]
            break
        has_more = data.get("has_more")
        page_token = data.get("page_token", "") or ""
        if not has_more or not page_token:
            break
    return tables, total, 0, ""


def read_bitable_as_text(client, app_token, *, table_index=None, limit=None,
                         mode="full", filter_expr=None):
    """Flatten a bitable app into readable plain text.

    ``mode``:
      - ``"full"`` (default): list each table then each record as
        ``field: value`` lines (capped per table; reports the true record
        total when it exceeds the cap).
      - ``"structure"``: list the table catalogue only — table name,
        table_id, record total, and field definitions (name + type + formula
        marker). Reads no record data.

    ``table_index`` (1-based) limits output to a single table.
    ``limit`` overrides the per-table record cap (default 500).
    ``filter_expr`` is passed through to the records API ``filter`` query.

    Note: structure mode makes one extra cheap records call per table (a
    page_size=1 total probe); full mode reuses the total from the first
    records page, so it does not add a request.
    """
    max_records = limit if limit is not None else _BITABLE_MAX_RECORDS_PER_TABLE
    mode = (mode or "full").lower()
    if mode not in ("full", "structure"):
        return (f"mode must be 'full' or 'structure' (got '{mode}')")

    stop_after = table_index if table_index is not None else _BITABLE_MAX_TABLES
    tables, total_tables, code, msg = _list_bitable_tables(
        client, app_token, stop_after=stop_after
    )
    if code != 0:
        return f"Failed to read bitable: code={code} msg={msg}"
    if not tables:
        return f"Bitable {app_token} has no tables"
    header_total = total_tables if total_tables else len(tables)
    truncated = (
        table_index is None
        and total_tables is not None
        and len(tables) < int(total_tables or 0)
    )

    if table_index is not None:
        if not (1 <= table_index <= len(tables)):
            return (f"table_index={table_index} out of range (1..{len(tables)}). "
                    f"共 {header_total} 张表，索引从 1 开始。")
        tables = [tables[table_index - 1]]

    lines = [f"=== 多维表格: {app_token} (共 {header_total} 表) ==="]
    if truncated:
        lines.append(f"⚠️ 表数超过上限，仅展示前 {_BITABLE_MAX_TABLES} 张。")
    for idx, table in enumerate(tables):
        table_id = table.get("table_id", "")
        table_name = table.get("name", table_id)
        lines.append("")

        if mode == "structure":
            fields = _read_table_fields(client, app_token, table_id)
            formula_ct = sum(1 for _, _, isf in fields if isf)
            rec_total = _table_record_total(
                client, app_token, table_id, filter_expr=filter_expr)
            header = f"--- 表 {idx + 1}: {table_name} (table_id={table_id}"
            if rec_total is not None:
                header += f", 记录数={rec_total}"
            if fields:
                header += f", 字段={len(fields)}"
                if formula_ct:
                    header += f", 公式字段={formula_ct}"
            header += ") ---"
            lines.append(header)
            if fields:
                for fname, ftype, isf in fields:
                    tname = _BITABLE_FIELD_TYPE_NAMES.get(ftype, f"type={ftype}")
                    mark = " [公式]" if isf else ""
                    lines.append(f"  - {fname} ({tname}){mark}")
            else:
                lines.append("  (无字段或字段读取失败)")
            continue

        # full mode: read records (request sequence unchanged vs legacy).
        lines.append(f"--- 表 {idx + 1}: {table_name} (table_id={table_id}) ---")
        records, rec_total = _read_table_records(
            client, app_token, table_id, max_records, filter_expr=filter_expr)
        if not records:
            lines.append("(no records)")
            continue
        for r_idx, fields in enumerate(records, 1):
            lines.append(f"记录 {r_idx}:")
            if isinstance(fields, dict) and fields:
                for fname, fval in fields.items():
                    lines.append(f"  {fname}: {_stringify_field(fval)}")
            else:
                lines.append("  (empty record)")
        if len(records) >= max_records and rec_total is not None \
                and rec_total > max_records:
            lines.append(
                f"  ...(达到上限 {max_records} 条；该表实际共 {rec_total} 条)"
            )

    if not table_index and header_total > len(tables):
        lines.append("")
        lines.append(f"...(总 {header_total} 表，本次仅展示 {len(tables)})")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sheet (电子表格) reading
# ---------------------------------------------------------------------------

# Spreadsheet API: list sheets -> read each sheet's used range as values.
def _col_letter(n):
    """Convert 1-based column number to A1-style letter (1→A, 26→Z, 27→AA)."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


_SHEET_META_URI = "/open-apis/sheets/v3/spreadsheets/:spreadsheet_token/sheets/query"
_SHEET_VALUES_URI = (
    "/open-apis/sheets/v2/spreadsheets/:spreadsheet_token/values/:range"
)
_SHEET_MAX_ROWS = 500
_SHEET_MAX_COLS = 50


def read_sheet_as_text(client, sheet_token):
    """Flatten a Feishu spreadsheet into readable plain text.

    Lists every sheet (tab), reads its used range (capped at 500 rows x 50
    columns), and renders rows as tab-separated values with a header line.
    """
    # 1. Get spreadsheet metadata to find all sheets.
    code, msg, data = do_request(
        client, "GET", _SHEET_META_URI,
        paths={"spreadsheet_token": sheet_token},
    )
    if code != 0:
        return f"Failed to read spreadsheet: code={code} msg={msg}"

    sheets = []
    if isinstance(data, dict):
        # /sheets/query returns data["sheets"] directly.
        # The basic /spreadsheets/:token endpoint wraps under
        # data["spreadsheet"]["sheets"] -- handle both for safety.
        spreadsheet = data.get("spreadsheet") or {}
        if isinstance(spreadsheet, dict):
            sheets = spreadsheet.get("sheets") or []
        if not sheets:
            sheets = data.get("sheets") or []
    if not sheets:
        return f"Spreadsheet {sheet_token} has no sheets"

    lines = [f"=== 电子表格: {sheet_token} ==="]
    for idx, sheet in enumerate(sheets):
        sheet_id = sheet.get("sheet_id", "")
        sheet_name = sheet.get("title", sheet_id)
        row_count = sheet.get("grid_properties", {}).get("row_count", 0)
        col_count = sheet.get("grid_properties", {}).get("column_count", 0)

        lines.append("")
        lines.append(
            f"--- 工作表 {idx + 1}: {sheet_name} "
            f"(sheet_id={sheet_id}, {row_count}行 x {col_count}列) ---"
        )

        if row_count == 0 or col_count == 0:
            lines.append("(empty sheet)")
            continue

        # Cap dimensions.
        rows_to_read = min(row_count, _SHEET_MAX_ROWS)
        cols_to_read = min(col_count, _SHEET_MAX_COLS)

        # Build A1-style range: A1:<last_col><last_row>.
        last_col = _col_letter(cols_to_read)
        range_str = f"{sheet_id}!A1:{last_col}{rows_to_read}"

        v_code, v_msg, v_data = do_request(
            client, "GET", _SHEET_VALUES_URI,
            paths={"spreadsheet_token": sheet_token, "range": range_str},
        )
        if v_code != 0:
            lines.append(f"(read data failed: code={v_code} msg={v_msg})")
            continue

        value_ranges = v_data.get("valueRange") if isinstance(v_data, dict) else None
        rows_data = []
        if isinstance(value_ranges, dict):
            rows_data = value_ranges.get("values") or []
        if not rows_data:
            lines.append("(no data)")
            continue

        row_lines = []
        for r_idx, row in enumerate(rows_data, 1):
            cells = []
            for c_idx in range(cols_to_read):
                if c_idx < len(row) and row[c_idx] is not None:
                    cells.append(_stringify_field(row[c_idx]))
                else:
                    cells.append("")
            row_lines.append("\t".join(cells))

        # Strip trailing all-empty rows (spreadsheets often pad to grid size).
        while row_lines and not any(c.strip() for c in row_lines[-1].split("\t")):
            row_lines.pop()
        lines.extend(row_lines)

        if rows_to_read >= _SHEET_MAX_ROWS:
            lines.append(f"  ...(已达到 {_SHEET_MAX_ROWS} 行上限)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Docx image blocks + media download
# ---------------------------------------------------------------------------

# Image block type in the docx blocks API (block_type=27 → image).
_IMAGE_BLOCK_TYPE = 27
_DOCX_BLOCKS_URI = "/open-apis/docx/v1/documents/:document_id/blocks"
_MEDIA_DOWNLOAD_URI = "/open-apis/drive/v1/medias/:file_token/download"

# Caps so a screenshot-heavy doc cannot explode disk / tool latency.
# Media download is rate-limited at ~5 QPS by Feishu; keep sequential.
# 500 images would be >=100s of sequential downloads (worse with rate-limit
# retries) and up to ~5 GiB of cache per doc — 100 is plenty for context.
_DOCX_MAX_IMAGES = 100
_DOCX_MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MiB per image
_DOCX_BLOCKS_PAGE_SIZE = 500
# [owner-patch] Hard budget on how many blocks are scanned for images before
# giving up (40 pages of 500): bounds pagination on huge block trees.
_DOCX_MAX_BLOCKS_SCANNED = 20000
# Vision OCR: concurrent auxiliary calls (each image is one LLM call).
# Concurrency stays modest; the cap matches download so large
# screenshot-heavy docs can still be OCR'd in one read.
_DOCX_MAX_VISION_IMAGES = 100
_DOCX_VISION_WORKERS = 3
# [owner-patch] Cache-budget guard: when the cumulative doc-image cache
# exceeds these, prune oldest files (by mtime) so long-lived gateways do not
# accumulate unbounded disk usage.
_DOCX_CACHE_MAX_FILES = 1000
_DOCX_CACHE_MAX_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB total
_DOCX_VISION_PROMPT = (
    "这是飞书文档中的嵌入图片（多为运维聊天截图、日志、表格或监控面板）。"
    "请完整转录图中全部可见文字（含 UI 标签、表格、代码、聊天记录、时间戳）。"
    "保留关键结构；若几乎无文字，则用 1-3 句中文概括画面。"
    "不要编造图中不存在的信息。"
)

# Shared 429 / rate-limit backoff for media download + vision OCR.
_RATE_LIMIT_MAX_RETRIES = 5
_RATE_LIMIT_BASE_SLEEP_S = 1.0
_RATE_LIMIT_MAX_SLEEP_S = 60.0

# raw_content turns every image block into a bare filename-like token.
_RAW_IMAGE_PLACEHOLDER_RE = re.compile(
    r"\bimage\.(png|jpe?g|gif|webp|bmp)\b",
    re.IGNORECASE,
)

_MIME_TO_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/x-ms-bmp": ".bmp",
}


def _safe_slug(value: str, *, max_len: int = 40) -> str:
    """Filesystem-safe fragment from a Feishu token (alphanumeric + _-)."""
    slug = re.sub(r"[^A-Za-z0-9_-]", "", value or "")
    return (slug[:max_len] if slug else "img")


def _sniff_image_ext(data: bytes) -> str:
    """Guess a file extension from magic bytes; default ``.bin``."""
    if not data:
        return ".bin"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8"):
        return ".jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:2] == b"BM":
        return ".bmp"
    return ".bin"


def _header_value(headers, *names):
    """Case-insensitive header lookup on a dict-like headers object."""
    if not headers:
        return ""
    # Prefer exact keys first, then a case-folded scan.
    for name in names:
        if name in headers:
            val = headers.get(name)
            if val is not None:
                return str(val)
    try:
        lowered = {str(k).lower(): v for k, v in headers.items()}
    except Exception:
        return ""
    for name in names:
        val = lowered.get(name.lower())
        if val is not None:
            return str(val)
    return ""


def _is_rate_limited_error(detail) -> bool:
    """True when an error string/code looks like HTTP 429 / provider rate limit."""
    if detail is None:
        return False
    text = str(detail).lower()
    if "429" in text:
        return True
    # Feishu open-platform frequency limit code.
    if "99991400" in text:
        return True
    if "rate limit" in text or "rate_limit" in text or "ratelimit" in text:
        return True
    if "too many request" in text:
        return True
    if "frequency" in text and "limit" in text:
        return True
    if "quota" in text and ("exceed" in text or "exhausted" in text):
        return True
    return False


def _rate_limit_sleep(attempt: int) -> float:
    """Exponential backoff with jitter. ``attempt`` is 0-based (first retry)."""
    base = min(
        _RATE_LIMIT_MAX_SLEEP_S,
        _RATE_LIMIT_BASE_SLEEP_S * (2 ** attempt),
    )
    # ±20% jitter so concurrent workers don't stampede.
    delay = base * (0.8 + 0.4 * random.random())
    time.sleep(delay)
    return delay


def _call_with_rate_limit_retry(fn, *, label: str, max_retries: int = _RATE_LIMIT_MAX_RETRIES):
    """Run ``fn()`` and retry on rate-limit errors.

    ``fn`` must return ``(ok_payload..., error_or_None)`` where the **last**
    element is the error string (or ``None`` on success). On non-rate-limit
    errors, or after exhausting retries, the last result is returned as-is.
    """
    last = None
    for attempt in range(max_retries + 1):
        last = fn()
        if not isinstance(last, tuple) or not last:
            return last
        err = last[-1]
        if err is None or not _is_rate_limited_error(err):
            return last
        if attempt >= max_retries:
            break
        delay = _rate_limit_sleep(attempt)
        logger.info(
            "feishu_client_utils: rate limited on %s (attempt %s/%s), "
            "sleeping %.1fs then retrying: %s",
            label, attempt + 1, max_retries, delay, err,
        )
    return last


def list_docx_image_tokens(client, doc_token, *, max_images=_DOCX_MAX_IMAGES):
    """Return ordered image descriptors from a docx document's blocks.

    Each item is ``{"token": str, "width": int|None, "height": int|None}``.
    Stops after ``max_images`` tokens. Pagination continues until the API
    reports no more pages (or the cap is hit). A total block budget also
    bounds pagination so a huge block tree cannot fan out into unbounded
    requests when images are sparse (P2-4).
    """
    images = []
    page_token = ""
    scanned_blocks = 0
    while len(images) < max_images and scanned_blocks < _DOCX_MAX_BLOCKS_SCANNED:
        queries = [("page_size", str(_DOCX_BLOCKS_PAGE_SIZE))]
        if page_token:
            queries.append(("page_token", page_token))
        code, msg, data = do_request(
            client, "GET", _DOCX_BLOCKS_URI,
            paths={"document_id": doc_token},
            queries=queries,
        )
        if code != 0:
            logger.debug(
                "feishu_client_utils: list blocks failed doc=%s code=%s msg=%s",
                doc_token, code, msg,
            )
            break

        items = data.get("items") or []
        scanned_blocks += len(items)
        for block in items:
            if not isinstance(block, dict):
                continue
            if block.get("block_type") != _IMAGE_BLOCK_TYPE:
                continue
            image = block.get("image") or {}
            if not isinstance(image, dict):
                continue
            token = image.get("token") or ""
            if not token:
                continue
            images.append({
                "token": token,
                "width": image.get("width"),
                "height": image.get("height"),
            })
            if len(images) >= max_images:
                break

        if len(images) >= max_images or scanned_blocks >= _DOCX_MAX_BLOCKS_SCANNED:
            break
        has_more = data.get("has_more")
        page_token = data.get("page_token", "") or ""
        if not has_more or not page_token:
            break
    return images


def _download_media_once(client, file_token):
    """Single attempt to download a drive media object.

    Returns ``(bytes_or_None, content_type_or_empty, error_or_None)``.
    """
    from lark_oapi import AccessTokenType
    from lark_oapi.core.enum import HttpMethod
    from lark_oapi.core.model.base_request import BaseRequest

    request = (
        BaseRequest.builder()
        .http_method(HttpMethod.GET)
        .uri(_MEDIA_DOWNLOAD_URI)
        .token_types({AccessTokenType.TENANT})
        .paths({"file_token": file_token})
        .build()
    )
    response = client.request(request)

    code = getattr(response, "code", None)
    msg = getattr(response, "msg", "") or ""
    raw = getattr(response, "raw", None)
    status = getattr(raw, "status_code", None) if raw is not None else None

    def _error_detail(default):
        detail = default
        if raw is not None and getattr(raw, "content", None):
            try:
                body = json.loads(raw.content)
                if isinstance(body, dict):
                    detail = (
                        f"code={body.get('code', code)} "
                        f"msg={body.get('msg', msg) or detail}"
                    )
            except (json.JSONDecodeError, TypeError, UnicodeDecodeError, ValueError):
                pass
        return detail

    # Feishu JSON errors set ``code`` != 0. Binary success sets code=0.
    # Non-JSON HTTP errors may leave code as None with a non-2xx status.
    if code not in (0, None):
        return None, "", _error_detail(msg or f"code={code}")
    if status is not None and not (200 <= int(status) < 300):
        return None, "", _error_detail(f"HTTP {status} msg={msg}")

    if raw is None:
        return None, "", "empty response (no raw body)"

    content = getattr(raw, "content", None)
    if content is None:
        return None, "", "empty response body"
    if isinstance(content, str):
        content = content.encode("utf-8")
    if not isinstance(content, (bytes, bytearray)):
        return None, "", f"unexpected body type: {type(content).__name__}"
    content = bytes(content)
    if not content:
        return None, "", "empty response body"

    headers = getattr(raw, "headers", None) or {}
    content_type = _header_value(headers, "Content-Type", "content-type")
    # Strip "; charset=..." etc.
    if ";" in content_type:
        content_type = content_type.split(";", 1)[0].strip()

    return content, content_type, None


def download_media(client, file_token):
    """Download a drive media object with 429 / rate-limit backoff retries.

    Returns ``(bytes_or_None, content_type_or_empty, error_or_None)``.
    Success sets ``error`` to ``None`` and returns the binary body.
    """
    return _call_with_rate_limit_retry(
        lambda: _download_media_once(client, file_token),
        label=f"media_download:{file_token[:16]}",
    )


def _image_cache_dir(doc_token: str) -> Path:
    from hermes_constants import get_hermes_home

    base = get_hermes_home() / "cache" / "feishu_doc_images" / _safe_slug(doc_token)
    base.mkdir(parents=True, exist_ok=True)
    return base


def _prune_docx_image_cache() -> None:
    """[owner-patch] Enforce the doc-image cache budget (LRU by mtime).

    Deletes the oldest files (across all docs) until both the file-count and
    total-bytes ceilings are under budget. Best-effort: failures degrade
    silently — a cache slightly over budget is not worth crashing a read.
    """
    from hermes_constants import get_hermes_home

    base = get_hermes_home() / "cache" / "feishu_doc_images"
    try:
        files = [
            p for p in base.rglob("*")
            if p.is_file() and not p.name.startswith(".")
        ]
    except OSError:
        return
    if not files:
        return
    sized = []
    for p in files:
        try:
            st = p.stat()
            sized.append((p, st.st_size, st.st_mtime))
        except OSError:
            continue
    if not sized:
        return
    total_bytes = sum(sz for _, sz, _ in sized)
    if len(sized) <= _DOCX_CACHE_MAX_FILES and total_bytes <= _DOCX_CACHE_MAX_BYTES:
        return
    sized.sort(key=lambda item: item[2])  # oldest mtime first
    removed = 0
    for p, sz, _mtime in sized:
        if len(sized) - removed <= _DOCX_CACHE_MAX_FILES and (
            total_bytes <= _DOCX_CACHE_MAX_BYTES
        ):
            break
        try:
            p.unlink()
            total_bytes -= sz
            removed += 1
        except OSError:
            continue
    if removed:
        logger.info(
            "feishu_client_utils: pruned %d doc-image cache files "
            "(files=%d bytes=%d)",
            removed,
            len(sized) - removed,
            total_bytes,
        )


def download_docx_images(client, doc_token, image_tokens, *, max_bytes=_DOCX_MAX_IMAGE_BYTES):
    """Download image tokens to ``$HERMES_HOME/cache/feishu_doc_images/<doc>/``.

    ``image_tokens`` is the list from :func:`list_docx_image_tokens`.
    Returns a list of dicts::

        {
          "index": 1-based int,
          "token": str,
          "path": str or "",
          "width": ...,
          "height": ...,
          "error": str or None,
          "bytes": int,
        }
    """
    if not image_tokens:
        return []

    dest_dir = _image_cache_dir(doc_token)
    results = []
    for i, meta in enumerate(image_tokens, 1):
        token = meta.get("token") or ""
        entry = {
            "index": i,
            "token": token,
            "path": "",
            "width": meta.get("width"),
            "height": meta.get("height"),
            "error": None,
            "bytes": 0,
        }
        if not token:
            entry["error"] = "missing image token"
            results.append(entry)
            continue

        data, content_type, err = download_media(client, token)
        if err or not data:
            entry["error"] = err or "download returned no data"
            results.append(entry)
            logger.debug(
                "feishu_client_utils: media download failed token=%s err=%s",
                token, entry["error"],
            )
            continue

        if len(data) > max_bytes:
            entry["error"] = (
                f"image too large ({len(data)} bytes, max {max_bytes})"
            )
            results.append(entry)
            continue

        mime_key = (content_type or "").lower().strip()
        ext = _MIME_TO_EXT.get(mime_key) or _sniff_image_ext(data)
        filename = f"img_{i:02d}_{_safe_slug(token, max_len=20)}{ext}"
        path = dest_dir / filename
        try:
            path.write_bytes(data)
        except OSError as exc:
            entry["error"] = f"write failed: {exc}"
            results.append(entry)
            continue

        entry["path"] = str(path)
        entry["bytes"] = len(data)
        results.append(entry)

    # [owner-patch] Enforce cache budget once per batch, after all writes.
    try:
        _prune_docx_image_cache()
    except OSError:
        logger.debug("feishu_client_utils: doc-image cache prune skipped", exc_info=True)

    return results


def _format_image_marker(img: dict) -> str:
    """Render one image as a block for the returned document text.

    Prefer embedding vision OCR text so the agent does not need a second
    round-trip. Always keep the local path for re-inspection.
    """
    n = img.get("index") or 0
    path = img.get("path") or ""
    analysis = (img.get("analysis") or "").strip()
    vision_err = img.get("vision_error")

    if not path:
        err = img.get("error") or "download failed"
        return f"[Image {n}: unavailable ({err})]"

    if analysis:
        return f"[Image {n}: {path}]\n{analysis}"

    if vision_err:
        return (
            f"[Image {n}: {path}]\n"
            f"(vision unavailable: {vision_err}; "
            f"use vision_analyze on this path to read the image)"
        )

    return (
        f"[Image {n}: {path}]\n"
        f"(no vision text; use vision_analyze on this path to read the image)"
    )


def inject_image_paths_into_content(content: str, images: list) -> str:
    """Replace raw_content ``image.png`` placeholders with image blocks.

    Placeholders are substituted in document order. Each successful download
    becomes ``[Image N: /abs/path]`` plus vision OCR text when available.
    Failures become ``[Image N: unavailable (...)]``. If more images exist
    than placeholders (or zero placeholders matched), an appendix lists the
    remainder so the agent still sees every image.
    """
    if not images:
        return content or ""

    text = content or ""
    cursor = 0

    def _repl(_match):
        nonlocal cursor
        if cursor >= len(images):
            return _match.group(0)
        marker = _format_image_marker(images[cursor])
        cursor += 1
        return marker

    new_text = _RAW_IMAGE_PLACEHOLDER_RE.sub(_repl, text)

    # Images that never got a placeholder slot (API shape drift, or more
    # image blocks than raw_content placeholders) still need to surface.
    if cursor < len(images):
        leftover = images[cursor:]
        lines = ["", "--- Document images ---"]
        for img in leftover:
            lines.append(_format_image_marker(img))
        new_text = new_text.rstrip() + "\n" + "\n".join(lines)

    return new_text


def _analyze_one_image_once(path: str, prompt: str) -> tuple:
    """Single vision attempt. Returns ``(analysis, error)``."""
    try:
        from model_tools import _run_async
        from tools.vision_tools import vision_analyze_tool
    except ImportError as exc:
        return None, f"vision import failed: {exc}"

    try:
        result_json = _run_async(
            vision_analyze_tool(image_url=path, user_prompt=prompt)
        )
    except Exception as exc:
        logger.debug(
            "feishu_client_utils: vision_analyze failed path=%s err=%s",
            path, exc,
        )
        return None, str(exc)

    try:
        data = json.loads(result_json) if isinstance(result_json, str) else result_json
    except (json.JSONDecodeError, TypeError) as exc:
        return None, f"invalid vision response: {exc}"

    if not isinstance(data, dict):
        return None, "invalid vision response type"

    if data.get("success"):
        analysis = (data.get("analysis") or "").strip()
        if analysis:
            return analysis, None
        return None, "empty vision analysis"

    return None, data.get("error") or data.get("message") or "vision failed"


def _analyze_one_image(path: str, prompt: str) -> tuple:
    """Run auxiliary vision with 429 / rate-limit backoff retries.

    Returns ``(analysis, error)``.
    """
    return _call_with_rate_limit_retry(
        lambda: _analyze_one_image_once(path, prompt),
        label=f"vision:{Path(path).name}",
    )


def analyze_docx_images(
    images: list,
    *,
    max_vision: int = _DOCX_MAX_VISION_IMAGES,
    max_workers: int = _DOCX_VISION_WORKERS,
    prompt: str = _DOCX_VISION_PROMPT,
) -> list:
    """Run auxiliary vision OCR on downloaded docx images (in place).

    Adds ``analysis`` and/or ``vision_error`` keys to each image dict that
    has a local ``path``. Caps at ``max_vision`` successful path candidates;
    remaining images keep path-only markers. Concurrent via a small thread
    pool (each worker bridges to the async vision tool).
    """
    if not images:
        return images

    # Skip entirely when no vision backend is configured — path markers alone
    # are still useful, and we avoid N hard failures.
    try:
        from tools.vision_tools import check_vision_requirements
        if not check_vision_requirements():
            for img in images:
                if img.get("path") and not img.get("error"):
                    img["vision_error"] = "vision backend not configured"
            return images
    except Exception as exc:
        logger.debug("feishu_client_utils: vision requirement check failed: %s", exc)
        for img in images:
            if img.get("path") and not img.get("error"):
                img["vision_error"] = f"vision unavailable: {exc}"
        return images

    # Collect work items (indexes into ``images``); cap at max_vision.
    work = []
    for i, img in enumerate(images):
        if not img.get("path") or img.get("error"):
            continue
        if len(work) < max_vision:
            work.append(i)
        else:
            img["vision_error"] = f"vision skipped (capped at {max_vision} images)"

    if not work:
        return images

    workers = max(1, min(max_workers, len(work)))

    def _job(idx: int):
        path = images[idx]["path"]
        analysis, err = _analyze_one_image(path, prompt)
        return idx, analysis, err

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_job, idx) for idx in work]
            for fut in concurrent.futures.as_completed(futures):
                try:
                    idx, analysis, err = fut.result()
                except Exception as exc:
                    logger.debug(
                        "feishu_client_utils: vision worker crashed: %s", exc,
                    )
                    continue
                if analysis:
                    images[idx]["analysis"] = analysis
                    images[idx]["vision_error"] = None
                else:
                    images[idx]["vision_error"] = err or "vision failed"
    except Exception as exc:
        logger.warning(
            "feishu_client_utils: vision pool failed: %s", exc,
        )
        for idx in work:
            if not images[idx].get("analysis"):
                images[idx]["vision_error"] = f"vision pool failed: {exc}"

    return images


def read_docx_with_images(
    client,
    doc_token,
    *,
    max_images=_DOCX_MAX_IMAGES,
    analyze_images: bool = True,
):
    """Read a docx as plain text, download images, and OCR them via vision.

    Returns ``(content_or_None, error_or_None, images_list)``.
    ``images_list`` is always a list (empty on failure / no images). When
    ``analyze_images`` is True (default), each downloaded image is passed
    through auxiliary vision and the transcript is embedded in ``content``.
    """
    code, msg, data = do_request(
        client, "GET",
        "/open-apis/docx/v1/documents/:document_id/raw_content",
        paths={"document_id": doc_token},
    )
    if code != 0:
        return None, f"Failed to read document: code={code} msg={msg}", []

    content = ""
    if isinstance(data, dict):
        content = data.get("content", "") or ""
    if not content and hasattr(data, "content"):
        content = getattr(data, "content", "") or ""
    if not content:
        return None, "No content returned from document API", []

    image_tokens = list_docx_image_tokens(
        client, doc_token, max_images=max_images,
    )
    if not image_tokens:
        return content, None, []

    images = download_docx_images(client, doc_token, image_tokens)
    if analyze_images:
        images = analyze_docx_images(images)

    content = inject_image_paths_into_content(content, images)

    # Note truncation so the agent knows more images may exist.
    if len(image_tokens) >= max_images:
        content = (
            content.rstrip()
            + f"\n\n...(image download capped at {max_images}; "
            "later images were not fetched)"
        )

    return content, None, images
