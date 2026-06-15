# [owner] TOOL FILE — registration glue only; core in owner/tools/unified_diff_patch/.
# See owner/docs/our-commits-inventory.md §「官方目录中的 owner 强依赖胶水文件」.
from owner.tools.unified_diff_patch import (
    UNIFIED_DIFF_PATCH_SCHEMA,
    _check_file_reqs,
    _handle_unified_diff_patch,
    parse_unified_diff,
    unified_diff_patch_tool,
)
from tools.registry import registry

__all__ = [
    "parse_unified_diff",
    "unified_diff_patch_tool",
]

registry.register(
    name="unified_diff_patch",
    toolset="file",
    schema=UNIFIED_DIFF_PATCH_SCHEMA,
    handler=_handle_unified_diff_patch,
    check_fn=_check_file_reqs,
    emoji="🩹",
    max_result_size_chars=100_000,
)

# [owner] unified_diff_patch: disable legacy patch tool in favor of this tool.
registry.deregister("patch")
