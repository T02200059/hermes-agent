# [owner] C12-doc-ocr: schema + handler extensions live in owner/feishu/doc_tool.py
# (schema applied post-registration via dynamic_schema_overrides; handler delegates below).
"""Feishu Document Tool -- read document content via Feishu/Lark API.

Provides ``feishu_doc_read`` for reading document content as plain text.
Uses the same lazy-import + BaseRequest pattern as feishu_comment.py.
"""

from tools.feishu_lark import (
    _check_feishu,
    build_request,
    get_client,
    raw_body,
    set_client)
from tools.registry import registry, tool_error, tool_result

_RAW_CONTENT_URI = "/open-apis/docx/v1/documents/:document_id/raw_content"

FEISHU_DOC_READ_SCHEMA = {
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


def _handle_feishu_doc_read(args: dict, **kwargs) -> str:
    # [owner] C12-doc-ocr: handler delegates to owner/feishu/doc_tool.py (schema patched post-registration)
    from owner.feishu.doc_tool import handle_feishu_doc_read
    return handle_feishu_doc_read(args, **kwargs)


registry.register(
    name="feishu_doc_read", toolset="feishu_doc", schema=FEISHU_DOC_READ_SCHEMA, handler=_handle_feishu_doc_read,
    check_fn=_check_feishu, requires_env=[], is_async=False, description="Read Feishu document content",
    emoji="\U0001f4c4")
