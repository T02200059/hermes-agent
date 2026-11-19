"""[owner] C12-doc-ocr: feishu_doc_read extensions — schema overrides + handler.

The official ``tools/feishu_doc_tool.py`` stays upstream-literal (a 3-line
handler delegate + top marker). Everything the 0b1e269dc0 rewrite grew lives
here instead:

1. ``SCHEMA_OVERRIDES()`` — full ``{"description", "parameters"}`` replacement
   (wiki/bitable/sheet typing, docx image-OCR note, embedded-sheet TSV note
   from C33, om_ paging params). Applied post-registration by setting
   ``ToolEntry.dynamic_schema_overrides``: ``registry.get_definitions`` calls
   it and shallow-merges the dict over the static schema
   (tools/registry.py::get_definitions), so the official static schema never
   needs to change.
2. ``handle_feishu_doc_read(args, **kwargs)`` — the orchestration the official
   handler delegates to: env-fallback client, ``om_`` merge-forward paging,
   wiki node resolution (incl. folder child listing), docx/bitable/sheet
   dispatch, docx image materialization + vision-OCR summaries.
3. ``apply_patch()`` — idempotent wiring, called from
   ``owner/owner-extensions/__init__.py::register``.

Load-order note (why apply_patch force-imports the tool module): the gateway
discovers plugins BEFORE ``model_tools`` imports the tool stack
(gateway/run_startup.py::_start_register_plugins_relay_hooks), so the entry
often does not exist yet when ``register()`` runs. ``tools.feishu_doc_tool``
is light (``tools.feishu_lark`` imports only json/threading; lark_oapi stays
lazy), so importing it here is cheap and deadlock-free — unlike the
``gateway.run`` import that motivated queue_cancel_patch's deferred apply.
If the official tool is gone entirely (upstream trimmed it), we log a
warning and fail open.
"""

from __future__ import annotations

import copy
import logging

from owner.feishu.client_utils import (
    extract_token,
    list_wiki_children,
    read_bitable_as_text,
    read_docx_with_images,
    read_merge_forward_as_text,
    read_sheet_as_text,
    resolve_client,
    resolve_wiki_node,
)
from tools.feishu_lark import get_client
from tools.registry import tool_error, tool_result

logger = logging.getLogger(__name__)

TOOL_NAME = "feishu_doc_read"

_EXTENDED_DESCRIPTION = (
    "Read the full content of a Feishu/Lark document as plain text. "
    "Useful when you need more context beyond the quoted text in a comment. "
    "Accepts a docx token, a wiki node token, or a full Feishu/Lark URL; "
    "docx documents, bitable (多维表格) bases, and sheets (电子表格) are supported. "
    "For docx, embedded images are downloaded, OCR'd via auxiliary vision, "
    "and inlined into the text as [Image N: /path] plus the transcribed "
    "content (screenshot-heavy docs become readable without a second tool call). "
    "Embedded bitables and embedded spreadsheets (电子表格 blocks) are "
    "rendered as tab-separated tables appended to the text. "
    "Local paths remain available for re-inspection with vision_analyze."
)

_EXTENDED_PARAMETERS = {
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
}


def SCHEMA_OVERRIDES() -> dict:
    """Full-key schema replacement for ``feishu_doc_read`` (see module docstring).

    Returns a deep copy so callers that mutate the merged definition
    (schema rewriters in model_tools) can never pollute this template.
    """
    return {
        "description": _EXTENDED_DESCRIPTION,
        "parameters": copy.deepcopy(_EXTENDED_PARAMETERS),
    }


def handle_feishu_doc_read(args: dict, **kwargs) -> str:
    # [owner] C12-doc-ocr: 上游没有的能力（wiki / bitable / sheet 读取、docx 图片物化 + vision OCR、
    # ``om_`` 合并转发分页、DM/群聊的 env-fallback client）全在共享模块里；上游把这些
    # 行放在文件头，为避免与其 ``tools.feishu_lark`` 抽取同区相撞，此处按需导入。
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


def apply_patch() -> bool:
    """Install SCHEMA_OVERRIDES on the registered entry (idempotent, fail-open).

    Called from owner-extensions ``register()``. Only the schema is patched —
    the handler side is the official file's thin delegate, which needs no
    patching. Re-applying is a no-op (``dynamic_schema_overrides`` is set to
    the same callable, no stacked side effects).
    """
    from tools.registry import registry

    entry = registry.get_entry(TOOL_NAME)
    if entry is None:
        # Plugin discovery can run before the tool stack is imported (gateway
        # startup) — force the registration; the module is light. See the
        # module docstring for the load-order analysis.
        try:
            import tools.feishu_doc_tool
        except Exception:
            logger.warning(
                "owner: %s is not registered and tools.feishu_doc_tool is not "
                "importable; schema overrides skipped (fail-open)", TOOL_NAME)
            return False
        entry = registry.get_entry(TOOL_NAME)
    if entry is None:
        logger.warning(
            "owner: %s missing from the registry; schema overrides skipped "
            "(fail-open)", TOOL_NAME)
        return False
    if entry.dynamic_schema_overrides is SCHEMA_OVERRIDES:
        return True  # already applied — idempotent
    entry.dynamic_schema_overrides = SCHEMA_OVERRIDES
    logger.debug("owner: feishu_doc_read schema overrides installed (post-registration)")
    return True
