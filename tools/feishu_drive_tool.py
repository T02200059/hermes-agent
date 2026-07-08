"""Feishu Drive Tools -- document comment operations via Feishu/Lark API.

Provides tools for listing, replying to, and adding document comments.
Uses the same lazy-import + BaseRequest pattern as feishu_comment.py.

The lark client is injected per-thread by the comment event handler when one
is active; otherwise we build a tenant client from ``FEISHU_APP_ID`` /
``FEISHU_APP_SECRET`` so the tools also work in plain DM/group-chat contexts.
Shared helpers (``do_request``) live in :mod:`tools.feishu_client_utils`.
"""

import logging
import threading

from tools.feishu_client_utils import do_request, resolve_client
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


def _check_feishu():
    # See ``tools/feishu_doc_tool.py::_check_feishu`` — ``find_spec`` keeps
    # CLI startup fast (the SDK itself takes ~5s to import eagerly).
    import importlib.util
    try:
        return importlib.util.find_spec("lark_oapi") is not None
    except (ImportError, ValueError):
        return False


# ---------------------------------------------------------------------------
# feishu_drive_list_comments
# ---------------------------------------------------------------------------

_LIST_COMMENTS_URI = "/open-apis/drive/v1/files/:file_token/comments"

FEISHU_DRIVE_LIST_COMMENTS_SCHEMA = {
    "name": "feishu_drive_list_comments",
    "description": (
        "List comments on a Feishu document. "
        "Use is_whole=true to list whole-document comments only."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "file_token": {
                "type": "string",
                "description": "The document file token.",
            },
            "file_type": {
                "type": "string",
                "description": "File type (default: docx).",
                "default": "docx",
            },
            "is_whole": {
                "type": "boolean",
                "description": "If true, only return whole-document comments.",
                "default": False,
            },
            "page_size": {
                "type": "integer",
                "description": "Number of comments per page (max 100).",
                "default": 100,
            },
            "page_token": {
                "type": "string",
                "description": "Pagination token for next page.",
            },
        },
        "required": ["file_token"],
    },
}


def _handle_list_comments(args: dict, **kwargs) -> str:
    client = resolve_client(get_client())
    if client is None:
        return tool_error(
            "Feishu client not available (set FEISHU_APP_ID and "
            "FEISHU_APP_SECRET, or run from a Feishu comment context)"
        )

    file_token = args.get("file_token", "").strip()
    if not file_token:
        return tool_error("file_token is required")

    file_type = args.get("file_type", "docx") or "docx"
    is_whole = args.get("is_whole", False)
    page_size = args.get("page_size", 100)
    page_token = args.get("page_token", "")

    queries = [
        ("file_type", file_type),
        ("user_id_type", "open_id"),
        ("page_size", str(page_size)),
    ]
    if is_whole:
        queries.append(("is_whole", "true"))
    if page_token:
        queries.append(("page_token", page_token))

    code, msg, data = do_request(
        client, "GET", _LIST_COMMENTS_URI,
        paths={"file_token": file_token},
        queries=queries,
    )
    if code != 0:
        return tool_error(f"List comments failed: code={code} msg={msg}")

    return tool_result(data)


# ---------------------------------------------------------------------------
# feishu_drive_list_comment_replies
# ---------------------------------------------------------------------------

_LIST_REPLIES_URI = "/open-apis/drive/v1/files/:file_token/comments/:comment_id/replies"

FEISHU_DRIVE_LIST_REPLIES_SCHEMA = {
    "name": "feishu_drive_list_comment_replies",
    "description": "List all replies in a comment thread on a Feishu document.",
    "parameters": {
        "type": "object",
        "properties": {
            "file_token": {
                "type": "string",
                "description": "The document file token.",
            },
            "comment_id": {
                "type": "string",
                "description": "The comment ID to list replies for.",
            },
            "file_type": {
                "type": "string",
                "description": "File type (default: docx).",
                "default": "docx",
            },
            "page_size": {
                "type": "integer",
                "description": "Number of replies per page (max 100).",
                "default": 100,
            },
            "page_token": {
                "type": "string",
                "description": "Pagination token for next page.",
            },
        },
        "required": ["file_token", "comment_id"],
    },
}


def _handle_list_replies(args: dict, **kwargs) -> str:
    client = resolve_client(get_client())
    if client is None:
        return tool_error(
            "Feishu client not available (set FEISHU_APP_ID and "
            "FEISHU_APP_SECRET, or run from a Feishu comment context)"
        )

    file_token = args.get("file_token", "").strip()
    comment_id = args.get("comment_id", "").strip()
    if not file_token or not comment_id:
        return tool_error("file_token and comment_id are required")

    file_type = args.get("file_type", "docx") or "docx"
    page_size = args.get("page_size", 100)
    page_token = args.get("page_token", "")

    queries = [
        ("file_type", file_type),
        ("user_id_type", "open_id"),
        ("page_size", str(page_size)),
    ]
    if page_token:
        queries.append(("page_token", page_token))

    code, msg, data = do_request(
        client, "GET", _LIST_REPLIES_URI,
        paths={"file_token": file_token, "comment_id": comment_id},
        queries=queries,
    )
    if code != 0:
        return tool_error(f"List replies failed: code={code} msg={msg}")

    return tool_result(data)


# ---------------------------------------------------------------------------
# feishu_drive_reply_comment
# ---------------------------------------------------------------------------

_REPLY_COMMENT_URI = "/open-apis/drive/v1/files/:file_token/comments/:comment_id/replies"

FEISHU_DRIVE_REPLY_SCHEMA = {
    "name": "feishu_drive_reply_comment",
    "description": (
        "Reply to a local comment thread on a Feishu document. "
        "Use this for local (quoted-text) comments. "
        "For whole-document comments, use feishu_drive_add_comment instead."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "file_token": {
                "type": "string",
                "description": "The document file token.",
            },
            "comment_id": {
                "type": "string",
                "description": "The comment ID to reply to.",
            },
            "content": {
                "type": "string",
                "description": "The reply text content (plain text only, no markdown).",
            },
            "file_type": {
                "type": "string",
                "description": "File type (default: docx).",
                "default": "docx",
            },
        },
        "required": ["file_token", "comment_id", "content"],
    },
}


def _handle_reply_comment(args: dict, **kwargs) -> str:
    client = resolve_client(get_client())
    if client is None:
        return tool_error(
            "Feishu client not available (set FEISHU_APP_ID and "
            "FEISHU_APP_SECRET, or run from a Feishu comment context)"
        )

    file_token = args.get("file_token", "").strip()
    comment_id = args.get("comment_id", "").strip()
    content = args.get("content", "").strip()
    if not file_token or not comment_id or not content:
        return tool_error("file_token, comment_id, and content are required")

    file_type = args.get("file_type", "docx") or "docx"

    body = {
        "content": {
            "elements": [
                {
                    "type": "text_run",
                    "text_run": {"text": content},
                }
            ]
        }
    }

    code, msg, data = do_request(
        client, "POST", _REPLY_COMMENT_URI,
        paths={"file_token": file_token, "comment_id": comment_id},
        queries=[("file_type", file_type)],
        body=body,
    )
    if code != 0:
        return tool_error(f"Reply comment failed: code={code} msg={msg}")

    return tool_result(success=True, data=data)


# ---------------------------------------------------------------------------
# feishu_drive_add_comment
# ---------------------------------------------------------------------------

_ADD_COMMENT_URI = "/open-apis/drive/v1/files/:file_token/new_comments"

FEISHU_DRIVE_ADD_COMMENT_SCHEMA = {
    "name": "feishu_drive_add_comment",
    "description": (
        "Add a new whole-document comment on a Feishu document. "
        "Use this for whole-document comments or as a fallback when "
        "reply_comment fails with code 1069302."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "file_token": {
                "type": "string",
                "description": "The document file token.",
            },
            "content": {
                "type": "string",
                "description": "The comment text content (plain text only, no markdown).",
            },
            "file_type": {
                "type": "string",
                "description": "File type (default: docx).",
                "default": "docx",
            },
        },
        "required": ["file_token", "content"],
    },
}


def _handle_add_comment(args: dict, **kwargs) -> str:
    client = resolve_client(get_client())
    if client is None:
        return tool_error(
            "Feishu client not available (set FEISHU_APP_ID and "
            "FEISHU_APP_SECRET, or run from a Feishu comment context)"
        )

    file_token = args.get("file_token", "").strip()
    content = args.get("content", "").strip()
    if not file_token or not content:
        return tool_error("file_token and content are required")

    file_type = args.get("file_type", "docx") or "docx"

    body = {
        "file_type": file_type,
        "reply_elements": [
            {"type": "text", "text": content},
        ],
    }

    code, msg, data = do_request(
        client, "POST", _ADD_COMMENT_URI,
        paths={"file_token": file_token},
        body=body,
    )
    if code != 0:
        return tool_error(f"Add comment failed: code={code} msg={msg}")

    return tool_result(success=True, data=data)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

registry.register(
    name="feishu_drive_list_comments",
    toolset="feishu_drive",
    schema=FEISHU_DRIVE_LIST_COMMENTS_SCHEMA,
    handler=_handle_list_comments,
    check_fn=_check_feishu,
    requires_env=[],
    is_async=False,
    description="List document comments",
    emoji="\U0001f4ac",
)

registry.register(
    name="feishu_drive_list_comment_replies",
    toolset="feishu_drive",
    schema=FEISHU_DRIVE_LIST_REPLIES_SCHEMA,
    handler=_handle_list_replies,
    check_fn=_check_feishu,
    requires_env=[],
    is_async=False,
    description="List comment replies",
    emoji="\U0001f4ac",
)

registry.register(
    name="feishu_drive_reply_comment",
    toolset="feishu_drive",
    schema=FEISHU_DRIVE_REPLY_SCHEMA,
    handler=_handle_reply_comment,
    check_fn=_check_feishu,
    requires_env=[],
    is_async=False,
    description="Reply to a document comment",
    emoji="\u2709\ufe0f",
)

registry.register(
    name="feishu_drive_add_comment",
    toolset="feishu_drive",
    schema=FEISHU_DRIVE_ADD_COMMENT_SCHEMA,
    handler=_handle_add_comment,
    check_fn=_check_feishu,
    requires_env=[],
    is_async=False,
    description="Add a whole-document comment",
    emoji="\u2709\ufe0f",
)
