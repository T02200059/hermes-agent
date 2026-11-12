"""编排器 —— terminal 工具执行前的预测式 checkpoint 触发。

数据流: 配置检查 → 解析 cd 前缀得生效目录 → 静态解析 → 只读命令短路 → (候选不足时)
LLM 兜底 → 安全过滤 (丢弃 / 与 home, 丢弃凭据/临时/内部目录) → 有合法 root 则
ensure_checkpoint；静态为空且官方判定破坏性时窄兜底拍 cwd。

warn 策略：只有真实写信号 (rm/cp/mv/sed -i/find -exec/引号外 >) 才用户可见；
只读命令、落在 home/root 的非破坏性写入、以及落在黑名单目录的写入都只记 debug
—— 这几类占历史上 9 成以上的噪音。只读命令整体短路，连 LLM 都不调。
heredoc 体内的 ``>``/``>=`` 比较不算破坏性（不发飞书 tip）。

永不抛异常 (与 CheckpointManager.ensure_checkpoint 的 "never raises" 一致)。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List

from owner.checkpoint_predictor import config, llm_predict, static_parser

logger = logging.getLogger(__name__)

# 临时/系统/挂载类目录: 快照它们没有回滚价值, 只会把 GB 级缓存灌进 store。
_EPHEMERAL_PREFIXES = (
    "/dev", "/proc", "/sys", "/run", "/tmp", "/var/tmp", "/var/run",
    "/var/cache", "/var/lib/docker", "/var/lib/containers", "/snap",
    "/mnt", "/media", "/Volumes",
)

# 目录名本身就是缓存/内部状态的根。
_JUNK_COMPONENTS = {
    ".git", "__pycache__", "node_modules", ".venv", "site-packages",
    ".cache", "chrome-clean-profile", ".Trash", ".cargo", ".rustup",
}

# 凭据目录: 快照它们没有回滚价值, 却会把私钥灌进 shadow store。
_SECRET_COMPONENTS = {
    ".ssh", ".aws", ".gnupg", ".kube", ".docker", ".password-store",
}


def _hermes_scratch_prefixes() -> tuple[str, ...]:
    """Hermes 自身的临时目录 (cache/tmp/logs/...), 不做快照。"""
    base = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
    try:
        base = str(Path(base).expanduser().resolve())
    except (OSError, RuntimeError):
        pass
    return tuple(f"{base}/{name}" for name in ("cache", "tmp", "logs", "sandboxes", "checkpoints"))


def _root_is_blacklisted(root: str) -> bool:
    """项目根是否落在不纳入快照的目录 (临时/系统/内部缓存)。

    同时比较字面路径与 realpath: macOS 上 ``/tmp`` 就是 ``/private/tmp``,
    只比字面会让 ``cd /tmp`` 绕过黑名单。
    """
    try:
        path = Path(root)
    except (OSError, RuntimeError):
        return False
    candidates = {path}
    try:
        candidates.add(path.resolve())
    except (OSError, RuntimeError):
        pass
    if any(_JUNK_COMPONENTS.intersection(c.parts) for c in candidates):
        return True
    if any(_SECRET_COMPONENTS.intersection(c.parts) for c in candidates):
        return True
    for prefix in _EPHEMERAL_PREFIXES + _hermes_scratch_prefixes():
        bases = {Path(prefix)}
        try:
            bases.add(Path(prefix).resolve())
        except (OSError, RuntimeError):
            pass
        for base in bases:
            if any(c == base or base in c.parents for c in candidates):
                return True
    return False


def _safe_roots(paths: list[str], cwd: str, agent) -> tuple[list[str], bool]:
    """对每个预测路径映射项目根。

    返回 ``(合法根, 是否有根被黑名单剔除)``。丢弃 == /、== home (官方 manager
    也拒绝) 的根; 黑名单目录的根静默跳过, 由调用方降级为 debug。
    """
    mgr = getattr(agent, "_checkpoint_mgr", None)
    if mgr is None:
        return [], False

    home = str(Path.home())
    roots: list[str] = []
    seen = set()
    blacklisted = False

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
        if _root_is_blacklisted(root):
            blacklisted = True
            continue
        if root not in seen:
            seen.add(root)
            roots.append(root)

    return roots, blacklisted


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
    """Reuse official destructive heuristic; fail-open False on import errors.

    Strip heredoc bodies first so Python/script comparisons like ``n>=maxn`` /
    ``printed>0`` inside ``<<EOF`` are not treated as shell redirects (and thus
    do not surface a Feishu tip when the project root is filtered).
    """
    try:
        from agent.tool_dispatch_helpers import _is_destructive_command

        visible = static_parser.strip_heredoc_bodies(command)
        return bool(_is_destructive_command(visible))
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
        "💡 checkpoint 预测失败,未创建快照\n"
        f"   命令: {command[:200]}\n"
        f"   cwd: {cwd}\n"
        f"   原因: {reason}\n"
        "   该命令造成的文件改动将无法通过 /rollback 回滚"
    )
    logger.warning("checkpoint predict failed: %s (cmd=%r)", reason, command[:80])
    _emit_owner_warn(agent, msg)


def _cwd_is_unsafe_snapshot_root(cwd: str) -> bool:
    """True when cwd resolves to ``/``, home, or a blacklisted root."""
    try:
        resolved = str(Path(cwd).expanduser().resolve())
    except (OSError, RuntimeError):
        resolved = str(cwd)
    home = str(Path.home())
    if resolved in {"/", home} or str(cwd) in {"/", home}:
        return True
    return _root_is_blacklisted(resolved)


def _destructive_cwd_fallback(command: str, cwd: str, agent, mgr) -> bool:
    """静态为空且官方破坏性判定为真 → 仍快照 cwd。返回是否已兜底。

    走 ``_command_looks_destructive``（已剥 heredoc），避免 Python 比较运算符误触发兜底/弹卡。
    """
    if not _command_looks_destructive(command):
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
        "💡 checkpoint 静态预测为空，已按破坏性命令兜底快照 cwd\n"
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

        # 0. 命令自带 cd 前缀时, 相对路径要按生效目录解析 (session cwd 会算错)
        work_dir = static_parser.effective_cwd(command, cwd)

        # 1. 静态解析
        static_candidates = static_parser.static_parse(command, work_dir)
        candidates = list(static_candidates)

        # 1b. 只读闸门: 静态为空且整条命令没有写信号 → 不调 LLM、不弹 tip。
        # 旧解析器下 7 天 1610 条 terminal 有 66% 静态为空 (含 449 条 2>/dev/null 假目标),
        # 其中只读命令占大头; 让它们走 LLM 兜底既加延迟又会猜出 ~/.ssh。
        if not static_candidates and static_parser.is_read_only_command(command):
            logger.debug("checkpoint predict skipped: read-only cmd=%r", command[:80])
            return

        # 2. 静态不足时 LLM 兜底
        if len(candidates) < cfg["predict_static_threshold"]:
            llm_results = llm_predict.llm_predict(
                command,
                work_dir,
                cfg["predict_llm_timeout_ms"],
                cache_size=cfg["predict_cache_size"],
            )
            seen = set(candidates)
            for p in llm_results:
                if p not in seen:
                    seen.add(p)
                    candidates.append(p)

        # 3. 安全过滤 → 项目根
        roots, blacklisted = _safe_roots(candidates, work_dir, agent)

        if not roots:
            # 窄兜底：静态为空 + 官方破坏性判定 → 仍快照 cwd（恢复旧树覆盖面）
            if not static_candidates and _destructive_cwd_fallback(command, work_dir, agent, mgr):
                return
            destructive = static_parser.destructive_signal(command)
            if candidates and not blacklisted:
                reason = "预测路径均被安全过滤 (项目根为 / 或 home)"
                # 非破坏性的 home 写入 (cd ~ && echo > out.txt) 不值得弹卡: 预测本身已尽力。
                surface = destructive
            elif blacklisted:
                reason = "预测路径落在不纳入快照的目录 (临时/缓存/内部目录)"
                surface = False
            else:
                reason = "静态解析与 LLM 均未能预测目标文件"
                surface = destructive
            _warn_uncheckpointed(command, work_dir, reason, agent, surface=surface)
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
