"""编排器 —— terminal 工具执行前的预测式 checkpoint 触发。

数据流: 配置检查 → 静态解析 → (候选不足时) LLM 兜底 → 安全过滤 →
有合法 root 则 ensure_checkpoint；静态为空且官方判定破坏性时窄兜底拍 cwd；
其余失败：破坏性/过滤失败才用户可见 warn；只读降 debug（不盲目拍 cwd）。

永不抛异常 (与 CheckpointManager.ensure_checkpoint 的 "never raises" 一致)。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

from owner.checkpoint_predictor import config, llm_predict, static_parser

logger = logging.getLogger(__name__)


def _safe_roots(paths: List[str], cwd: str, agent) -> List[str]:
    """对每个预测路径映射项目根, 丢弃 == / 或 == home 的根。"""
    mgr = getattr(agent, "_checkpoint_mgr", None)
    if mgr is None:
        return []

    home = str(Path.home())
    roots: List[str] = []
    seen = set()

    for p in paths:
        if p == static_parser.GIT_REPO_SENTINEL:
            root = mgr.get_working_dir_for_path(cwd)
        else:
            abs_path = Path(p).expanduser()
            if not abs_path.is_absolute():
                abs_path = Path(cwd) / abs_path
            root = mgr.get_working_dir_for_path(str(abs_path))

        if root in {"/", home}:
            continue
        if root not in seen:
            seen.add(root)
            roots.append(root)

    return roots


def _emit_owner_warn(agent, msg: str) -> None:
    """Prefer ``_owner_warn_callback``, else ``_emit_warning`` (C17 hang point)."""
    cb = getattr(agent, "_owner_warn_callback", None)
    if cb is None:
        cb = getattr(agent, "_emit_warning", None)
    if cb is not None:
        try:
            cb(msg)
        except Exception:
            pass


def _command_looks_destructive(command: str) -> bool:
    """Reuse official destructive heuristic; fail-open False on import errors."""
    try:
        from agent.tool_dispatch_helpers import _is_destructive_command

        return bool(_is_destructive_command(command))
    except Exception:
        return False


def _warn_uncheckpointed(command: str, cwd: str, reason: str, agent, *, surface: bool) -> None:
    """预测失败时记录；仅可能改文件的命令才走用户可见 warn。"""
    detail = (
        f"checkpoint predict failed: {reason} "
        f"(cmd={command[:80]!r} cwd={cwd})"
    )
    if not surface:
        logger.debug("%s", detail)
        return
    msg = (
        "⚠️ checkpoint 预测失败,未创建快照\n"
        f"   命令: {command[:200]}\n"
        f"   cwd: {cwd}\n"
        f"   原因: {reason}\n"
        "   该命令造成的文件改动将无法通过 /rollback 回滚"
    )
    logger.warning("checkpoint predict failed: %s (cmd=%r)", reason, command[:80])
    _emit_owner_warn(agent, msg)


def _cwd_is_unsafe_snapshot_root(cwd: str) -> bool:
    """True when cwd resolves to ``/`` or home (same filter as ``_safe_roots``)."""
    try:
        resolved = str(Path(cwd).expanduser().resolve())
    except Exception:
        resolved = str(cwd)
    home = str(Path.home())
    return resolved in {"/", home} or str(cwd) in {"/", home}


def _destructive_cwd_fallback(command: str, cwd: str, agent, mgr) -> bool:
    """静态为空且官方 _is_destructive_command 为真 → 仍快照 cwd。返回是否已兜底。"""
    try:
        from agent.tool_dispatch_helpers import _is_destructive_command

        if not _is_destructive_command(command):
            return False
    except Exception:
        return False
    if _cwd_is_unsafe_snapshot_root(cwd):
        logger.debug(
            "destructive cwd fallback skipped unsafe cwd=%r (home or /)", cwd
        )
        return False
    reason_str = f"before terminal (destructive cwd fallback): {command[:60]}"
    try:
        snapped = mgr.ensure_checkpoint(cwd, reason_str)
    except Exception as exc:
        logger.debug("destructive cwd ensure_checkpoint failed: %s", exc)
        return False
    if snapped is False:
        # Official manager also refuses home/root; do not claim a snapshot.
        logger.debug("destructive cwd ensure_checkpoint returned False (cwd=%r)", cwd)
        return False
    msg = (
        "⚠️ checkpoint 静态预测为空，已按破坏性命令兜底快照 cwd\n"
        f"   命令: {command[:200]}\n"
        f"   cwd: {cwd}\n"
        "   回滚粒度可能偏粗（整个工作目录）"
    )
    logger.warning("checkpoint destructive cwd fallback (cmd=%r cwd=%r)", command[:80], cwd)
    _emit_owner_warn(agent, msg)
    return True


def predict_and_checkpoint(command: str, cwd: str, agent) -> None:
    """terminal 工具执行前的 checkpoint 预测编排。永不抛异常。"""
    try:
        cfg = config.get_checkpoints_cfg()
        if not cfg["predict_enabled"]:
            return

        mgr = getattr(agent, "_checkpoint_mgr", None)
        if mgr is None or not mgr.enabled:
            return

        # 1. 静态解析
        static_candidates = static_parser.static_parse(command, cwd)
        candidates = list(static_candidates)

        # 2. 静态不足时 LLM 兜底
        if len(candidates) < cfg["predict_static_threshold"]:
            llm_results = llm_predict.llm_predict(
                command,
                cwd,
                cfg["predict_llm_timeout_ms"],
                cache_size=cfg["predict_cache_size"],
            )
            seen = set(candidates)
            for p in llm_results:
                if p not in seen:
                    seen.add(p)
                    candidates.append(p)

        # 3. 安全过滤 → 项目根
        roots = _safe_roots(candidates, cwd, agent)

        if not roots:
            # 窄兜底：静态为空 + 官方破坏性判定 → 仍快照 cwd（恢复旧树覆盖面）
            if not static_candidates and _destructive_cwd_fallback(command, cwd, agent, mgr):
                return
            if candidates:
                reason = "预测路径均被安全过滤 (项目根为 / 或 home)"
                # Had write-path predictions but all roots were unsafe — always surface.
                surface = True
            else:
                reason = "静态解析与 LLM 均未能预测目标文件"
                # Empty prediction: only surface for destructive cmds (avoid ls/git noise).
                surface = _command_looks_destructive(command)
            _warn_uncheckpointed(command, cwd, reason, agent, surface=surface)
            return

        # 4. 对每个合法项目根拍快照
        reason_str = f"before terminal: {command[:60]}"
        for root in roots:
            try:
                mgr.ensure_checkpoint(root, reason_str)
            except Exception as exc:
                logger.debug("ensure_checkpoint failed for %s: %s", root, exc)

    except Exception as exc:
        logger.debug("predict_and_checkpoint error: %s", exc)
        _warn_uncheckpointed(
            command, cwd, f"编排异常: {exc}", agent, surface=True
        )
