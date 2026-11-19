"""[owner] C12-doc-ocr: feishu_drive_* env-fallback client (runtime patch).

``tools/feishu_drive_tool.py`` stays upstream-literal. The DM/group-chat
fallback — build a tenant client from FEISHU_APP_ID / FEISHU_APP_SECRET when
no comment-context client was injected — is applied by rebinding the
module-local ``get_client`` name the drive handlers call, routing it through
``owner.feishu.client_utils.resolve_client`` (the same pipeline
``feishu_doc_read`` uses via owner/feishu/doc_tool.py).

Known delta vs the pre-rework inline edit in the official file: the
no-client error text stays the upstream short ``"Feishu client not
available"`` (the env-var hint sentence is gone — cosmetic only, nothing
asserted it).

Applied from ``owner/owner-extensions/__init__.py::register``; idempotent.
The drive tool module is light (``tools.feishu_lark`` imports only
json/threading; lark_oapi stays lazy), so force-importing it here is safe
even though plugin discovery can run before the tool stack is imported
(see owner/feishu/doc_tool.py's load-order note).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Module attribute marking the patch as applied (guards double-apply / re-wrap).
_APPLIED_ATTR = "_owner_env_fallback_client"


def apply_patch() -> bool:
    """Wrap tools.feishu_drive_tool.get_client with the env fallback (fail-open)."""
    try:
        import tools.feishu_drive_tool as drive
    except Exception:
        logger.warning(
            "owner: tools.feishu_drive_tool is not importable; env-fallback "
            "client patch skipped (fail-open)")
        return False
    if getattr(drive, _APPLIED_ATTR, False):
        return True  # already applied — idempotent
    from owner.feishu.client_utils import resolve_client

    original_get_client = drive.get_client

    def _get_client_with_env_fallback():
        return resolve_client(original_get_client())

    drive.get_client = _get_client_with_env_fallback
    setattr(drive, _APPLIED_ATTR, True)
    logger.debug("owner: feishu_drive_tool get_client wrapped with env fallback")
    return True
