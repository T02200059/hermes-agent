"""Shared helpers for the Feishu/Lark document and drive tools.

Two responsibilities live here so ``feishu_doc_tool.py`` and
``feishu_drive_tool.py`` don't have to duplicate them:

1. **Fallback lark client.** Both tools are normally driven by a lark client
   that the comment-event handler injects per-thread (``set_client`` /
   ``get_client``). Outside a comment context (a plain DM or group chat) no
   client is injected and the tools used to refuse to run. When
   ``FEISHU_APP_ID`` + ``FEISHU_APP_SECRET`` are present in the environment we
   build a tenant client on demand and cache it process-wide.

2. **Wiki node resolution + bitable reading.** ``feishu_doc_read`` only knew
   how to call the docx ``raw_content`` API. A wiki node token resolves to a
   real document (``obj_token``) whose type (``obj_type``) can be ``docx``,
   ``bitable``, ``sheet`` ... This module resolves the node and, for
   bitables, flattens every table into readable plain text.

``lark_oapi`` is imported lazily inside the functions that need it -- the SDK
eagerly loads a large surface and costs ~5s to import, which is why the
tool-availability probe (``_check_feishu``) uses ``find_spec`` instead.
"""

import json
import logging
import os
import threading

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

    http_method = HttpMethod.GET if method == "GET" else HttpMethod.POST

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
            pass
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

def extract_token(raw):
    """Pull the document token out of a user-supplied value.

    Accepts a bare token or a Feishu/Lark URL. Returns ``(token, is_wiki)``:
    ``is_wiki`` is True only when the input was a ``/wiki/<node_token>`` URL,
    because that is the one case where the raw token is a wiki *node* token
    rather than the final document token. ``/docx/<token>`` and ``/sheets/``
    paths already carry the real document token and are returned as-is.
    """
    if not raw:
        return "", False
    value = raw.strip()

    # URL form -- pull the path segment after the recognised doc path.
    if value.startswith("http://") or value.startswith("https://"):
        # Strip any fragment/query first.
        for sep in ("#", "?"):
            if sep in value:
                value = value.split(sep, 1)[0]
        # ``/wiki/<node_token>`` -> the node token must be resolved.
        if "/wiki/" in value:
            node = value.rsplit("/wiki/", 1)[1].strip("/")
            # A trailing path segment only; ignore anything after the token.
            node = node.split("/", 1)[0] if "/" in node else node
            return node, True
        # ``/docx/<token>`` / ``/doc/<token>`` / ``/sheets/<token>`` /
        # ``/base/<token>`` -- the token is already the obj_token.
        for prefix in ("/docx/", "/doc/", "/sheets/", "/base/", "/bitable/"):
            if prefix in value:
                tok = value.rsplit(prefix, 1)[1].strip("/")
                tok = tok.split("/", 1)[0] if "/" in tok else tok
                return tok, False
        # Unknown URL shape -- take the last path segment.
        tail = value.rstrip("/").rsplit("/", 1)[-1]
        return tail, False

    return value, False


_WIKI_GET_NODE_URI = "/open-apis/wiki/v2/spaces/get_node"


def resolve_wiki_node(client, node_token):
    """Resolve a wiki node token to ``(obj_token, obj_type)``.

    Returns ``(None, None)`` when the token is not a wiki node or the API
    rejects it. ``obj_type`` is one of ``docx`` / ``bitable`` / ``sheet`` /
    ``mindnote`` / ... (anything Feishu reports).
    """
    code, msg, data = do_request(
        client, "GET", _WIKI_GET_NODE_URI,
        queries=[("token", node_token)],
    )
    if code != 0:
        logger.debug("feishu_client_utils: wiki get_node failed code=%s msg=%s", code, msg)
        return None, None

    node = data.get("node") if isinstance(data, dict) else None
    if not isinstance(node, dict):
        return None, None

    obj_token = node.get("obj_token") or ""
    obj_type = node.get("obj_type") or ""
    if not obj_token or not obj_type:
        return None, None
    return obj_token, obj_type


# ---------------------------------------------------------------------------
# Bitable (多维表格) reading
# ---------------------------------------------------------------------------

_BITABLE_TABLES_URI = "/open-apis/bitable/v1/apps/:app_token/tables"
_BITABLE_RECORDS_URI = "/open-apis/bitable/v1/apps/:app_token/tables/:table_id/records"
# Cap how many records/tables we pull so the tool can't run away on a huge
# base. 500 records per table and 50 tables is plenty for "give me context".
_BITABLE_MAX_TABLES = 50
_BITABLE_PAGE_SIZE = 100
_BITABLE_MAX_RECORDS_PER_TABLE = 500


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


def _read_table_records(client, app_token, table_id, max_records):
    """Page through a table's records. Returns a list of ``{field: value}`` dicts."""
    records = []
    page_token = ""
    while True:
        queries = [("page_size", str(_BITABLE_PAGE_SIZE))]
        if page_token:
            queries.append(("page_token", page_token))
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
    return records


def read_bitable_as_text(client, app_token):
    """Flatten a bitable app into readable plain text.

    Lists each table, then each record as ``字段: 值`` lines. Capped at
    ``_BITABLE_MAX_TABLES`` tables and ``_BITABLE_MAX_RECORDS_PER_TABLE``
    records per table so the result stays usable as agent context.
    """
    code, msg, data = do_request(
        client, "GET", _BITABLE_TABLES_URI,
        paths={"app_token": app_token},
        queries=[("page_size", "100")],
    )
    if code != 0:
        return f"读取多维表格失败: code={code} msg={msg}"

    tables = data.get("items") or []
    if not tables:
        return f"多维表格 {app_token} 中没有表"

    lines = [f"=== 多维表格: {app_token} ==="]
    for idx, table in enumerate(tables[:_BITABLE_MAX_TABLES]):
        table_id = table.get("table_id", "")
        table_name = table.get("name", table_id)
        lines.append("")
        lines.append(f"--- 表 {idx + 1}: {table_name} (table_id={table_id}) ---")

        records = _read_table_records(
            client, app_token, table_id, _BITABLE_MAX_RECORDS_PER_TABLE,
        )
        if not records:
            lines.append("(无记录)")
            continue
        for r_idx, fields in enumerate(records, 1):
            lines.append(f"记录 {r_idx}:")
            if isinstance(fields, dict) and fields:
                for fname, fval in fields.items():
                    lines.append(f"  {fname}: {_stringify_field(fval)}")
            else:
                lines.append("  (空记录)")
        if len(records) >= _BITABLE_MAX_RECORDS_PER_TABLE:
            lines.append(f"  ...(已达到单表 {_BITABLE_MAX_RECORDS_PER_TABLE} 条上限)")

    if len(tables) > _BITABLE_MAX_TABLES:
        lines.append("")
        lines.append(f"...(共 {len(tables)} 张表，仅展示前 {_BITABLE_MAX_TABLES} 张)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sheet (电子表格) reading
# ---------------------------------------------------------------------------

# Spreadsheet API: list sheets -> read each sheet's used range as values.
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
        return f"读取电子表格失败: code={code} msg={msg}"

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
        return f"电子表格 {sheet_token} 中没有工作表"

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
            lines.append("(空工作表)")
            continue

        # Cap dimensions.
        rows_to_read = min(row_count, _SHEET_MAX_ROWS)
        cols_to_read = min(col_count, _SHEET_MAX_COLS)

        # Build A1-style range: A1:<last_col><last_row>.
        # Column index -> letter: 1->A, 26->Z, 27->AA ...
        def _col_letter(n):
            s = ""
            while n > 0:
                n, r = divmod(n - 1, 26)
                s = chr(65 + r) + s
            return s

        last_col = _col_letter(cols_to_read)
        range_str = f"{sheet_id}!A1:{last_col}{rows_to_read}"

        v_code, v_msg, v_data = do_request(
            client, "GET", _SHEET_VALUES_URI,
            paths={"spreadsheet_token": sheet_token, "range": range_str},
        )
        if v_code != 0:
            lines.append(f"(读取数据失败: code={v_code} msg={v_msg})")
            continue

        value_ranges = v_data.get("valueRange") if isinstance(v_data, dict) else None
        rows_data = []
        if isinstance(value_ranges, dict):
            rows_data = value_ranges.get("values") or []
        if not rows_data:
            lines.append("(无数据)")
            continue

        for r_idx, row in enumerate(rows_data, 1):
            cells = []
            for c_idx in range(cols_to_read):
                if c_idx < len(row) and row[c_idx] is not None:
                    cells.append(_stringify_field(row[c_idx]))
                else:
                    cells.append("")
            lines.append("\t".join(cells))

        if rows_to_read >= _SHEET_MAX_ROWS:
            lines.append(f"  ...(已达到 {_SHEET_MAX_ROWS} 行上限)")

    return "\n".join(lines)
