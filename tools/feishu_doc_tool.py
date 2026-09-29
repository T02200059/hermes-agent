"""Feishu Document Tool -- read document content via Feishu/Lark API.

Provides ``feishu_doc_read`` for reading document content as plain text.
Uses the same lazy-import + BaseRequest pattern as feishu_comment.py.
"""

from tools.feishu_lark import (  # noqa: F401  (set_client/get_client are imported by feishu_comment)
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
        "Useful when you need more context beyond the quoted text in a comment. "
        "Accepts a docx token, a wiki node token, or a full Feishu/Lark URL; "
        "docx documents, bitable (多维表格) bases, and sheets (电子表格) are supported. "
        "For docx, embedded images are downloaded, OCR'd via auxiliary vision, "
        "and inlined into the text as [Image N: /path] plus the transcribed "
        "content (screenshot-heavy docs become readable without a second tool call). "
        "Local paths remain available for re-inspection with vision_analyze."
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
            "mode": {
                "type": "string",
                "enum": ["full", "structure"],
                "description": (
                    "Only applies to bitable (多维表格). 'full' (default) "
                    "dumps table records. 'structure' returns ONLY the table "
                    "catalogue (table names, table_ids, record totals, and "
                    "field definitions with types/formula markers) — use it "
                    "to see the directory of a bitable without pulling any "
                    "records. Ignored for docx/sheet."
                ),
            },
            "table_index": {
                "type": "integer",
                "description": (
                    "Only applies to bitable. 1-based index selecting a single "
                    "table to read (see the table list in 'structure' mode). "
                    "When omitted, reads up to 50 tables."
                ),
            },
            "limit": {
                "type": "integer",
                "description": (
                    "Only applies to bitable. Max records to read per table "
                    "(default 500). Ignored in 'structure' mode."
                ),
            },
            "filter": {
                "type": "string",
                "description": (
                    "Only applies to bitable. A Feishu bitable record filter "
                    "expression passed to the records API, e.g. "
                    'CurrentValue.[GPU]="H800" — reads only matching records.'
                ),
            },
            "offset": {
                "type": "integer",
                "description": (
                    "Only applies to merge_forward messages (doc_token=om_...). "
                    "Skip the first N child messages — use the offset shown in "
                    "the truncation hint to page through long forwards."
                ),
            },
            "mf_limit": {
                "type": "integer",
                "description": (
                    "Only applies to merge_forward messages (doc_token=om_...). "
                    "Max child messages to render in this call (default 100)."
                ),
            },
        },
        "required": ["doc_token"],
    },
}


def _handle_feishu_doc_read(args: dict, **kwargs) -> str:
    # [owner] 上游没有的能力（wiki / bitable / sheet 读取、docx 图片物化 + vision OCR、
    # ``om_`` 合并转发分页、DM/群聊的 env-fallback client）全在共享模块里；上游把这些
    # 行放在文件头，为避免与其 ``tools.feishu_lark`` 抽取同区相撞，此处按需导入。
    import logging

    from tools.feishu_client_utils import (
        extract_token,
        list_wiki_children,
        read_bitable_as_text,
        read_docx_with_images,
        read_sheet_as_text,
        resolve_client,
        resolve_wiki_node,
    )
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

    # [owner] merge_forward: doc_token om_... → read forwarded chat log
    # via GET /im/v1/messages/{id} (parent + N children). Supports offset /
    # limit paging so long forwards are never silently truncated.
    raw_token_stripped = raw_token.strip()
    if raw_token_stripped.startswith("om_"):
        from tools.feishu_client_utils import read_merge_forward_as_text

        text, err = read_merge_forward_as_text(
            client,
            raw_token_stripped,
            offset=int(args.get("offset", 0) or 0),
            limit=args.get("mf_limit"),
        )
        if err:
            return tool_error(err)
        return tool_result(success=True, content=text)

    # Extract the token and decide whether it needs wiki node resolution.
    # inferred_type comes from the URL path (/sheets/ → sheet, /base/ →
    # bitable, …); bare tokens and wiki URLs leave it empty so we default
    # to docx until resolve_wiki_node (or the caller) supplies a real type.
    token, is_wiki, inferred_type = extract_token(raw_token)
    if not token:
        return tool_error("Could not extract a document token from the input")

    obj_token, obj_type, node_meta = token, (inferred_type or "docx"), None
    if is_wiki:
        obj_token, obj_type, node_meta = resolve_wiki_node(client, token)
        if not obj_token:
            return tool_error(
                f"Could not resolve wiki node token '{token}' "
                "(check the token is correct and the app has wiki access)"
            )

    # A wiki folder node has no readable body -- list its child titles instead.
    if node_meta and node_meta.get("has_child"):
        listing = list_wiki_children(
            client, node_meta.get("space_id") or "", token
        )
        title = node_meta.get("title") or token
        return tool_result(
            success=True,
            content=f"=== 文件夹: {title} ===\n{listing}",
        )

    try:
        if obj_type == "docx":
            content, err, images = read_docx_with_images(client, obj_token)
            if err:
                return tool_error(err)
            # Compact image summary for structured consumers; full OCR text
            # is already embedded in ``content`` for the model to see.
            image_summaries = []
            vision_ok = 0
            for img in images:
                summary = {
                    "index": img.get("index"),
                    "token": img.get("token"),
                    "path": img.get("path") or "",
                }
                if img.get("error"):
                    summary["error"] = img["error"]
                if img.get("vision_error"):
                    summary["vision_error"] = img["vision_error"]
                analysis = (img.get("analysis") or "").strip()
                if analysis:
                    summary["has_analysis"] = True
                    vision_ok += 1
                else:
                    summary["has_analysis"] = False
                if img.get("width") is not None:
                    summary["width"] = img["width"]
                if img.get("height") is not None:
                    summary["height"] = img["height"]
                image_summaries.append(summary)
            return tool_result(
                success=True,
                content=content,
                images=image_summaries,
                image_count=len(image_summaries),
                vision_analyzed=vision_ok,
            )

        if obj_type == "bitable":
            text = read_bitable_as_text(
                client, obj_token,
                table_index=args.get("table_index"),
                limit=args.get("limit"),
                mode=args.get("mode", "full"),
                filter_expr=args.get("filter"),
            )
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
        logging.getLogger(__name__).exception("feishu_doc_read: unexpected error")
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
