"""approval_explainer —— 审批命令解说 (owner 模块, 官方源码最小侵入)。

当 hermes 执行命令触发 approval 时, 在审批卡上追加一段「这条命令在
做什么 / 有什么风险」的人话解说, 帮不懂具体命令的用户判断该不该批准。

触发时机 (严格与 approvals 一致): 解说生成嵌在两端 send_exec_approval
内部 (飞书 plugins/platforms/feishu/adapter.py / QQ
gateway/platforms/qqbot/adapter.py 的 [owner] 胶水), 即用户收到审批卡
的时刻 —— 不是定时器, 不是每条命令; 审批不发卡的三条路径 (纯文本
fallback / submit_pending 队列 / CLI 交互) 不在本功能范围。

模型配置 (2026-09-20 定稿): patch.yaml ``owner.approval_explainer``
段 (provider/model/timeout_ms); 未配置或 "auto" → auxiliary auto 链
(config.yaml auxiliary.approval_explainer 任务段 → 主聊天模型) —
与 progress_explainer 同语义。

设计稿: owner/docs/design/approval-command-explainer/approval-explainer.md
"""

from owner.approval_explainer.config import load_config, resolve_enabled
from owner.approval_explainer.explain import clear_cache, explain_command

__all__ = [
    "clear_cache",
    "explain_command",
    "load_config",
    "resolve_enabled",
]
