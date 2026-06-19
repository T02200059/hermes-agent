"""编排器 —— terminal 工具执行前的预测式 checkpoint 触发。

数据流: 配置检查 → 静态解析 → (阈值不足时) LLM 兜底 → 安全过滤 →
有合法 root 则 ensure_checkpoint, 否则报错 (绝不降级拍 cwd)。

永不抛异常 (与 CheckpointManager.ensure_checkpoint 的 "never raises" 一致)。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

from owner.checkpoint_predictor import config, llm_predict, static_parser

logger = logging.getLogger(__name__)


def _safe_roots(paths: List[str], cwd: str, agent) -> List[str]:
    """对每个预测路径映射项目根, 丢弃 == / 或 == home 的根。

    返回去重后的合法项目根列表。
    """
    mgr = getattr(agent, "_checkpoint_mgr", None)
    if mgr is None:
        return []

    home = str(Path.home())
    roots: List[str] = []
    seen = set()

    for p in paths:
        if p == static_parser.GIT_REPO_SENTINEL:
            # git 操作 → cwd 的项目根
            root = mgr.get_working_dir_for_path(cwd)
        else:
            # 解析为绝对路径 (相对 cwd)
            abs_path = Path(p).expanduser()
            if not abs_path.is_absolute():
                abs_path = Path(cwd) / abs_path
            root = mgr.get_working_dir_for_path(str(abs_path))

        if root in {"/", home}:
            continue  # 安全过滤
        if root not in seen:
            seen.add(root)
            roots.append(root)

    return roots


def _warn_uncheckpointed(command: str, cwd: str, reason: str, agent) -> None:
    """预测失败时通过 agent 回调报错。

    绝不降级为 cwd 快照 —— cwd 可能是 home 或超大目录, 过度覆盖风险。
    """
    msg = (
        f"⚠️ checkpoint 预测失败,未创建快照\n"
        f"   命令: {command[:200]}\n"
        f"   cwd: {cwd}\n"
        f"   原因: {reason}\n"
        f"   该命令造成的文件改动将无法通过 /rollback 回滚"
    )
    logger.warning("checkpoint predict failed: %s (cmd=%r)", reason, command[:80])
    cb = getattr(agent, "_owner_warn_callback", None)
    if cb is not None:
        try:
            cb(msg)
        except Exception:
            pass


def predict_and_checkpoint(command: str, cwd: str, agent) -> None:
    """terminal 工具执行前的 checkpoint 预测编排。

    永不抛异常。预测失败时报错, 绝不降级拍 cwd。
    """
    try:
        cfg = config.get_checkpoints_cfg()
        if not cfg["predict_enabled"]:
            return  # terminal 不做 checkpoint (write_file/patch 不受影响)

        mgr = getattr(agent, "_checkpoint_mgr", None)
        if mgr is None or not mgr.enabled:
            return

        # 1. 静态解析
        candidates = static_parser.static_parse(command, cwd)

        # 2. 静态不足时 LLM 兜底
        if len(candidates) < cfg["predict_static_threshold"]:
            llm_results = llm_predict.llm_predict(
                command, cwd, cfg["predict_llm_timeout_ms"]
            )
            # 合并静态 + LLM 结果 (静态可能给了哨兵, LLM 给了具体路径)
            seen = set(candidates)
            for p in llm_results:
                if p not in seen:
                    seen.add(p)
                    candidates.append(p)

        # 3. 安全过滤 → 项目根
        roots = _safe_roots(candidates, cwd, agent)

        if not roots:
            # 4. 没有合法 root → 报错, 不拍
            if candidates:
                reason = "预测路径均被安全过滤 (项目根为 / 或 home)"
            else:
                reason = "静态解析与 LLM 均未能预测目标文件"
            _warn_uncheckpointed(command, cwd, reason, agent)
            return

        # 5. 对每个合法项目根拍快照
        reason_str = f"before terminal: {command[:60]}"
        for root in roots:
            try:
                mgr.ensure_checkpoint(root, reason_str)
            except Exception as exc:
                logger.debug("ensure_checkpoint failed for %s: %s", root, exc)

    except Exception as exc:
        # 编排器整体永不抛 —— 但记录一条 warning + 报错
        logger.debug("predict_and_checkpoint error: %s", exc)
        _warn_uncheckpointed(command, cwd, f"编排异常: {exc}", agent)
