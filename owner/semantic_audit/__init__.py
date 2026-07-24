"""Semantic Audit Gate — tool dispatch 前的语义审计门。

入口：maybe_audit_batch(agent, assistant_message, messages, task_id) -> bool
返回 True 表示已处理完毕、跳过后续 dispatch（HALT / 全 BLOCK / 混合 BLOCK
已在 gate 内按序写入全部 tool results）。
返回 False 表示继续 dispatch（无审计动作，tool_calls 原样）。

官方文件 run_agent.py 只做 ≤5 行薄胶水（见 # [owner] 标记）。
删除本包后 import 失败 → fail-open，核心仍可用。
"""

from __future__ import annotations

from owner.semantic_audit.gate import maybe_audit_batch

__all__ = ["maybe_audit_batch"]
