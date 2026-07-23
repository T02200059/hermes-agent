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
import re
import threading
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

    Lists each table, then each record as ``field: value`` lines. Capped at
    ``_BITABLE_MAX_TABLES`` tables and ``_BITABLE_MAX_RECORDS_PER_TABLE``
    records per table so the result stays usable as agent context.

    Note: the tables listing fetches one page of up to 100 tables. Bitables
    with more than 100 tables will have the excess silently omitted.
    """
    code, msg, data = do_request(
        client, "GET", _BITABLE_TABLES_URI,
        paths={"app_token": app_token},
        queries=[("page_size", "100")],
    )
    if code != 0:
        return f"Failed to read bitable: code={code} msg={msg}"

    tables = data.get("items") or []
    if not tables:
        return f"Bitable {app_token} has no tables"

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
            lines.append("(no records)")
            continue
        for r_idx, fields in enumerate(records, 1):
            lines.append(f"记录 {r_idx}:")
            if isinstance(fields, dict) and fields:
                for fname, fval in fields.items():
                    lines.append(f"  {fname}: {_stringify_field(fval)}")
            else:
                lines.append("  (empty record)")
        if len(records) >= _BITABLE_MAX_RECORDS_PER_TABLE:
            lines.append(f"  ...(reached per-table limit of {_BITABLE_MAX_RECORDS_PER_TABLE})")

    if len(tables) > _BITABLE_MAX_TABLES:
        lines.append("")
        lines.append(f"...(total {len(tables)} tables, showing first {_BITABLE_MAX_TABLES})")

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


# ---------------------------------------------------------------------------
# Docx image blocks + media download
# ---------------------------------------------------------------------------

# Image block type in the docx blocks API (block_type=27 → image).
_IMAGE_BLOCK_TYPE = 27
_DOCX_BLOCKS_URI = "/open-apis/docx/v1/documents/:document_id/blocks"
_MEDIA_DOWNLOAD_URI = "/open-apis/drive/v1/medias/:file_token/download"

# Caps so a screenshot-heavy doc cannot explode disk / tool latency.
# Media download is rate-limited at ~5 QPS by Feishu; keep sequential.
_DOCX_MAX_IMAGES = 40
_DOCX_MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MiB per image
_DOCX_BLOCKS_PAGE_SIZE = 500
# Vision OCR: concurrent auxiliary calls (each image is one LLM call).
_DOCX_MAX_VISION_IMAGES = 40
_DOCX_VISION_WORKERS = 3
_DOCX_VISION_PROMPT = (
    "这是飞书文档中的嵌入图片（多为运维聊天截图、日志、表格或监控面板）。"
    "请完整转录图中全部可见文字（含 UI 标签、表格、代码、聊天记录、时间戳）。"
    "保留关键结构；若几乎无文字，则用 1-3 句中文概括画面。"
    "不要编造图中不存在的信息。"
)

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


def list_docx_image_tokens(client, doc_token, *, max_images=_DOCX_MAX_IMAGES):
    """Return ordered image descriptors from a docx document's blocks.

    Each item is ``{"token": str, "width": int|None, "height": int|None}``.
    Stops after ``max_images`` tokens. Pagination continues until the API
    reports no more pages (or the cap is hit).
    """
    images = []
    page_token = ""
    while len(images) < max_images:
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

        if len(images) >= max_images:
            break
        has_more = data.get("has_more")
        page_token = data.get("page_token", "") or ""
        if not has_more or not page_token:
            break
    return images


def download_media(client, file_token):
    """Download a drive media object.

    Returns ``(bytes_or_None, content_type_or_empty, error_or_None)``.
    Success sets ``error`` to ``None`` and returns the binary body.
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


def _image_cache_dir(doc_token: str) -> Path:
    from hermes_constants import get_hermes_home

    base = get_hermes_home() / "cache" / "feishu_doc_images" / _safe_slug(doc_token)
    base.mkdir(parents=True, exist_ok=True)
    return base


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


def _analyze_one_image(path: str, prompt: str) -> tuple:
    """Run auxiliary vision on one local path. Returns ``(analysis, error)``."""
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
