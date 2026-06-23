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

# 2026-06-22: 临时解禁官方 patch、停用 unified_diff_patch（实测对比）。
# 恢复方式：恢复下方 unified_diff_patch 注册 + registry.deregister("patch")。
# registry.register(name="unified_diff_patch", toolset="file", ...)  # 暂时停
