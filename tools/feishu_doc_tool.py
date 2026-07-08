"""Feishu Document Tool -- read document content via Feishu/Lark API.

Provides ``feishu_doc_read`` for reading document content as plain text.
Uses the same lazy-import + BaseRequest pattern as feishu_comment.py.

When a comment-event handler injects a lark client via ``set_client`` we use
it; otherwise we build a tenant client from ``FEISHU_APP_ID`` /
``FEISHU_APP_SECRET`` so the tool also works in plain DM/group-chat contexts.
Shared helpers live in :mod:`tools.feishu_client_utils`.
"""

import logging
import threading

from tools.feishu_client_utils import (
    do_request,
    extract_token,
    read_bitable_as_text,
    read_sheet_as_text,
    resolve_client,
    resolve_wiki_node,
)
from tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)

# Thread-local storage for the lark client injected by feishu_comment handler.
_local = threading.local()


def set_client(client):
    """Store a lark client for the current thread (called by feishu_comment)."""
    _local.client = client


def get_client():
    """Return the lark client for the current thread, or None."""
    return getattr(_local, "client", None)


# ---------------------------------------------------------------------------
# feishu_doc_read
# ---------------------------------------------------------------------------

_RAW_CONTENT_URI = "/open-apis/docx/v1/documents/:document_id/raw_content"

FEISHU_DOC_READ_SCHEMA = {
    "name": "feishu_doc_read",
    "description": (
        "Read the full content of a Feishu/Lark document as plain text. "
        "Useful when you need more context beyond the quoted text in a comment. "
        "Accepts a docx token, a wiki node token, or a full Feishu/Lark URL; "
        "docx documents, bitable (多维表格) bases, and sheets (电子表格) are supported."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "doc_token": {
                "type": "string",
                "description": (
                    "The document token or URL. May be a docx doc_token, a "
                    "wiki node token, or a full URL like "
                    "https://xxx.feishu.cn/wiki/<node_token> or "
                    "https://xxx.feishu.cn/docx/<doc_token>."
                ),
            },
        },
        "required": ["doc_token"],
    },
}


def _check_feishu():
    # Use ``importlib.util.find_spec`` — it checks whether ``lark_oapi``
    # is importable without actually executing its ``__init__``.
    # Executing the real import here costs ~5 seconds (the SDK eagerly
    # loads websockets, dispatcher, every api/v2 model) and this probe
    # fires at every ``hermes`` startup during tool-availability
    # evaluation.  Correctness is preserved because the actual tool
    # handler still does the real import when invoked.
    import importlib.util
    try:
        return importlib.util.find_spec("lark_oapi") is not None
    except (ImportError, ValueError):
        return False


def _read_docx_raw(client, doc_token):
    """Call the docx ``raw_content`` API. Returns ``(content_or_None, error_or_None)``."""
    code, msg, data = do_request(
        client, "GET", _RAW_CONTENT_URI,
        paths={"document_id": doc_token},
    )
    if code != 0:
        return None, f"Failed to read document: code={code} msg={msg}"

    content = ""
    if isinstance(data, dict):
        content = data.get("content", "") or ""
    if not content and hasattr(data, "content"):
        content = getattr(data, "content", "") or ""
    if not content:
        return None, "No content returned from document API"
    return content, None


def _handle_feishu_doc_read(args: dict, **kwargs) -> str:
    raw_token = args.get("doc_token", "").strip()
    if not raw_token:
        return tool_error("doc_token is required")

    # Prefer an injected (comment-context) client; fall back to a tenant
    # client built from FEISHU_APP_ID / FEISHU_APP_SECRET.
    client = resolve_client(get_client())
    if client is None:
        return tool_error(
            "Feishu client not available (set FEISHU_APP_ID and "
            "FEISHU_APP_SECRET, or run from a Feishu comment context)"
        )

    # Extract the token and decide whether it needs wiki node resolution.
    token, is_wiki = extract_token(raw_token)
    if not token:
        return tool_error("Could not extract a document token from the input")

    obj_token, obj_type = token, "docx"
    if is_wiki:
        obj_token, obj_type = resolve_wiki_node(client, token)
        if not obj_token:
            return tool_error(
                f"Could not resolve wiki node token '{token}' "
                "(check the token is correct and the app has wiki access)"
            )

    try:
        if obj_type == "docx":
            content, err = _read_docx_raw(client, obj_token)
            if err:
                return tool_error(err)
            return tool_result(success=True, content=content)

        if obj_type == "bitable":
            text = read_bitable_as_text(client, obj_token)
            return tool_result(success=True, content=text)

        if obj_type == "sheet":
            text = read_sheet_as_text(client, obj_token)
            return tool_result(success=True, content=text)

        return tool_error(
            f"Reading {obj_type} documents is not yet supported (supported: docx, bitable, sheet)"
        )
    except ImportError:
        return tool_error("lark_oapi not installed")
    except Exception as e:
        logger.exception("feishu_doc_read: unexpected error")
        return tool_error(f"Failed to read document: {e}")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

registry.register(
    name="feishu_doc_read",
    toolset="feishu_doc",
    schema=FEISHU_DOC_READ_SCHEMA,
    handler=_handle_feishu_doc_read,
    check_fn=_check_feishu,
    requires_env=[],
    is_async=False,
    description="Read Feishu document content",
    emoji="\U0001f4c4",
)
