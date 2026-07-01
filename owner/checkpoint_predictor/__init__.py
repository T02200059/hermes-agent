"""Checkpoint mutation predictor — terminal 工具执行前的预测式快照触发。

核心逻辑全部在此包内 (遵循二次开发规范§2.2)。官方文件
agent/tool_executor.py 只做薄胶水委托。
"""

from owner.checkpoint_predictor.predictor import predict_and_checkpoint

__all__ = ["predict_and_checkpoint"]
