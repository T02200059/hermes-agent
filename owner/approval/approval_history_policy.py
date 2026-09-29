"""Approval-history block detection — language-independent (T2-1).

问题
====
``hermes_cli/approvals_suggest.py`` 从会话 DB 挖掘「隐含批准」：把危险命令
的 ``role='tool'`` 结果当作「用户批准过」的证据，据此生成 ``command_allowlist``
建议。判定「该命令并未自由执行」的方式原本是**按人类可读文案做子串匹配**：

* ``_BLOCK_MARKERS`` —— 11 条硬编码英文字面量；
* SQL 预过滤 —— ``content LIKE '%BLOCKED%' OR content LIKE '%approval%'``。

但审批消息的文案自 ``5d85ec89ac``（owner i18n 改造）起搬进了
``locales/*.yaml``，``t()`` 在中文环境返回译文（``已拦截：…``）。英文 marker
与英文 SQL 预过滤**同时失效**（双重漏检）：被用户拒绝的危险命令于是被当成
「执行过且隐含批准」，达到 ``min_count`` 后进入建议，经 ``--apply`` 永久写入
``config.yaml`` 的 ``command_allowlist``，此后该类命令免审批自动执行。

这与 T1-1 是同一个失效模式 —— **同一个字符串既被展示、又被逻辑匹配**，
本地化必然击穿逻辑。那次击穿的是返回值，这次是工具结果。

修法
====
不再匹配文案文字，改为**结构标记**。三层，按可靠性降序：

1. **结果状态字段**（语言无关）—— ``terminal`` 拦截时写
   ``"status": "blocked"``，等待用户批准时写 ``"status": "pending_approval"``；
   ``approval`` 层另有 ``outcome`` / ``user_consent`` 字段（见
   ``tools/approval.py`` 的 ``_transport_denied_result`` 等）。
2. **catalog 键白名单**（结构标识）—— 审批消息的每个语义分支都有稳定的
   i18n key（``approval.cli_denied`` …）。**键**是语言无关的；取这些键在
   全部已安装语言下的值、抽出静态片段作为 marker，于是「上游改文案」「新增
   语言」都自动跟随，不必改本文件。
3. **硬编码兜底** —— catalog 不可用（缺 pyyaml / 缺 ``locales/``）时的最小
   英中标记集。

SQL 预过滤同样改为**结构锚点**，并由测试断言「锚点是 marker 集合的超集」
—— 这正是原缺陷的第二个根源：预过滤与判定表各自维护、互相漂移，谁也发现
不了对方的漏项。

删除本模块（或 import 失败）后，``hermes_cli/approvals_suggest.py`` 退回上游
行为：不崩溃，但恢复「本地化后漏检」。
"""

from __future__ import annotations

import json
import logging
import re
import string
import threading
from pathlib import Path
from typing import Any, Dict, FrozenSet, Optional, Tuple

logger = logging.getLogger(__name__)

# 对官方**私有**符号（``agent.i18n._locales_dir``）的依赖必须可降级且**可观测**：
# 降级本身已有自解析兜底，但静默兜底会让「上游改了名字、我们一直在走次优路径」
# 这件事永远不显形。
_private_dep_notices: set = set()


def _warn_once(key: str, message: str, *args: Any) -> None:
    """Log ``message`` once per process per ``key``."""
    if key in _private_dep_notices:
        return
    _private_dep_notices.add(key)
    logger.warning(message, *args)


# ---------------------------------------------------------------------------
# 层 1：结果状态字段（语言无关）
# ---------------------------------------------------------------------------

#: ``role='tool'`` 结果里表示「命令没有被自由执行」的 ``status`` 值。
#: 来源：``tools/terminal_tool.py`` —— 拦截写 ``"blocked"``，等待批准写
#: ``"pending_approval"``；``tools/approval.py`` 的 gateway 路径写
#: ``"approval_required"``。
#:
#: 刻意**不含** ``timeout`` —— 那是「命令执行超时」（命令已经跑过），与
#: 「审批超时 = 视为拒绝」是两回事；后者由文案层区分。
NON_EXECUTION_STATUSES: FrozenSet[str] = frozenset(
    {"blocked", "pending_approval", "approval_required", "denied", "rejected"}
)

#: ``approval`` 层返回 dict 上的 ``outcome`` 值（部分写入路径会保留）。
NON_EXECUTION_OUTCOMES: FrozenSet[str] = frozenset({"denied", "timeout"})

#: ``outcome`` 前缀式拒绝（``transport_<failure>``）。
NON_EXECUTION_OUTCOME_PREFIXES: Tuple[str, ...] = ("transport_",)

# ---------------------------------------------------------------------------
# 层 2：catalog 键白名单
# ---------------------------------------------------------------------------

#: 语义为「拦截 / 拒绝 / 待审批」的 i18n 键（``approval`` 段内）。
#: 这些键是**语言无关的结构标识** —— 只有值才分语言。
MESSAGE_KEYS: Tuple[str, ...] = (
    # 硬拦截 / 用户规则 / 受保护文件
    "hardline_blocked",
    "user_deny_blocked",
    "sudo_stdin_blocked",
    "protected_file_blocked",
    "ssh_config_blocked",
    # 拒绝
    "user_denied",
    "cli_denied",
    "cli_denied_action",
    "transport_denied",
    "smart_denied",
    "execute_code_user_denied",
    "execute_code_cli_denied",
    "execute_code_transport_denied",
    "execute_code_smart_denied",
    # 审批超时（视为拒绝）
    "cli_timeout_command",
    "cli_timeout_action",
    "gateway_timeout_denied",
    "execute_code_timeout_denied",
    # 无人在场 / 非交互模式
    "no_human_present",
    "no_human_present_tool",
    "unattended_blocked",
    "unattended_blocked_command",
    "unattended_blocked_tirith",
    "unattended_blocked_tirith_import",
    "cron_blocked",
    "cron_blocked_tool",
    "cron_blocked_tirith",
    "cron_blocked_tirith_import",
    "single_query_blocked",
    "single_query_blocked_tool",
    "single_query_blocked_tirith",
    "single_query_blocked_tirith_import",
    "execute_code_cron_blocked",
    "execute_code_single_query_blocked",
    "execute_code_unattended_blocked",
    # 通道故障
    "gateway_notify_failed",
    "execute_code_notify_failed",
    "transport_failed",
    # 其他
    "gateway_action_blocked",
    "plugin_requires_approval",
    # 待审批提示（命令尚未执行）
    "gateway_asking",
    "gateway_asking_combined",
    "gateway_asking_target",
    "execute_code_gateway_asking",
)

#: 结果 dict 中承载拦截文案的字段。刻意**不含** ``output`` —— 那是命令/脚本
#: 的真实输出，可能只是「提及」了 BLOCKED 字样，纳入会引入误报。
MESSAGE_FIELDS: Tuple[str, ...] = ("error", "message")

# ---------------------------------------------------------------------------
# 层 3：兜底标记
# ---------------------------------------------------------------------------

#: catalog 不可用时的最小标记集（英 + 中）。刻意保持很小 —— 它的职责只是
#: 「catalog 全挂时别退化成只靠 status 字段」，不是主力判据。
FALLBACK_MARKERS: FrozenSet[str] = frozenset(
    {
        "BLOCKED",
        "The user has NOT consented",
        "Asking the user for approval",
        "Plugin requires approval",
        "approval_required",
        "已拦截",
        "智能审批拦截",
        "插件需要审批",
        "用户未同意",
        "正在请求用户批准",
    }
)

# ---------------------------------------------------------------------------
# SQL 预过滤锚点
# ---------------------------------------------------------------------------

#: SQL ``LIKE`` 粗筛锚点。必须是 :func:`load_markers` 结果的**超集** —— 任何
#: 能被 marker 命中的内容，至少含一个锚点，否则该行根本进不了 Python 判定，
#: 形成与原始缺陷同源的静默漏检。
#:
#: 由 ``tests/owner/test_approval_suggest_i18n_blocks.py`` 断言；
#: 新增语言/键导致断言失败时，在此补锚点即可。
#:
#: 注意 SQLite 的 ``LIKE`` 对 ASCII 大小写不敏感，故 ``blocked`` 同时覆盖
#: ``BLOCKED`` 与 ``"status": "blocked"``。
SQL_LIKE_ANCHORS: Tuple[str, ...] = (
    '"status"',   # 任何结构化结果（blocked / pending_approval / …）
    "blocked",    # 英文前缀 + 结构化 status
    "approval",   # approval_required / pending_approval / 英文提示
    "consented",  # "The user has NOT consented"
    "拦截",        # zh：已拦截 / 智能审批拦截
    "审批",        # zh：需要审批 / 插件需要审批
    "批准",        # zh：正在请求用户批准
    "未同意",      # zh：用户未同意
    "拒绝",        # zh：用户拒绝
)

# ---------------------------------------------------------------------------
# 实现
# ---------------------------------------------------------------------------

#: 静态片段的最小长度（字符）。低于此值的片段太容易偶然命中真实输出。
_MIN_FRAGMENT_CHARS = 4

_cache_lock = threading.Lock()
_marker_cache: Optional[FrozenSet[str]] = None
_pattern_cache: Optional["re.Pattern[str]"] = None


def _locales_dir() -> Optional[Path]:
    """``locales/`` 目录。

    优先复用上游 ``agent.i18n`` 的解析，保证与 ``t()`` 读同一份 catalog；
    该私有符号不存在时退回仓库根自解析。
    """
    try:
        from agent.i18n import _locales_dir as _upstream_locales_dir

        path = Path(_upstream_locales_dir())
        if path.is_dir():
            return path
    except Exception as exc:
        _warn_once(
            "approval_history_policy.upstream_locales_dir",
            "owner.approval.approval_history_policy fell back to its own "
            "locales/ resolution: cannot reach agent.i18n._locales_dir (%s). "
            "If the catalog diverges from t()'s, re-point this import; see "
            "owner/docs/owner改动清单.md §16.13.",
            exc,
        )

    candidate = Path(__file__).resolve().parents[2] / "locales"
    return candidate if candidate.is_dir() else None


def _load_approval_segment(path: Path) -> Dict[str, str]:
    """读取某语言 catalog 的 ``approval`` 段；失败返回空表。"""
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    segment = data.get("approval")
    if not isinstance(segment, dict):
        return {}
    return {str(k): str(v) for k, v in segment.items() if isinstance(v, str)}


def _is_meaningful(text: str) -> bool:
    """片段是否可作 marker：够长，且含至少一个字母/数字/CJK 字符。

    ``str.isalnum()`` 对 CJK 返回 True，因此中英片段用同一套阈值。
    """
    stripped = text.strip()
    if len(stripped) < _MIN_FRAGMENT_CHARS:
        return False
    return any(ch.isalnum() for ch in stripped)


def _contains_anchor(text: str) -> bool:
    """文本是否含任一 SQL 锚点。

    按 SQL ``LIKE`` 的语义比较：**ASCII 大小写不敏感**（SQLite 默认），
    否则 ``BLOCKED`` 会被判为不含锚点 ``blocked``，而它在 SQL 侧明明能
    通过粗筛 —— 这层不一致正是原缺陷的成因。
    """
    lowered = text.lower()
    return any(anchor.lower() in lowered for anchor in SQL_LIKE_ANCHORS)


def _marker_for_template(template: str) -> Optional[str]:
    """从 catalog 模板抽出一个有辨识度的静态片段作为 marker。

    有占位符时取**最长**的静态片段。理由：

    * 片段边界由占位符决定，与用户数据无关 —— 上游给消息追加
      ``breaker_addendum`` 之类的后缀不影响命中，而占位符里的命令文本、
      描述若被当作 marker 会永远匹配不上。
    * 长度即辨识度。按句拆分会产出大量短碎片（``"' pattern)."``），它们
      既容易被真实输出偶然命中（误报），又常常不含任何 SQL 锚点（漏检）。

    无占位符的模板整串即 marker；整串是实际消息的前缀，子串匹配成立。
    """
    try:
        parsed = list(string.Formatter().parse(template))
    except (ValueError, IndexError):
        return None

    has_field = any(name is not None for _lit, name, _spec, _conv in parsed)
    if not has_field:
        return template.strip() if _is_meaningful(template) else None

    literals = [
        literal
        for literal, _name, _spec, _conv in parsed
        if literal and _is_meaningful(literal)
    ]
    if not literals:
        return None

    # 取**首个**含锚点的片段：片段边界由占位符决定，与用户数据无关，故头部
    # 片段最稳定；中段片段会被描述文本里的括号、标点冲散（如以 ``)`` 开头
    # 的片段，一旦描述自带 ``)`` 就失配）。marker 必须能被粗筛放行，否则该行
    # 进不了 Python 判定。
    for literal in literals:
        if _contains_anchor(literal):
            return literal.strip()
    return max(literals, key=len).strip()


def load_markers() -> FrozenSet[str]:
    """返回全部语言的拦截标记集合（带进程内缓存）。

    来源 = catalog 白名单键在**所有已安装语言**下的静态片段 ∪
    :data:`FALLBACK_MARKERS`。
    """
    global _marker_cache
    with _cache_lock:
        cached = _marker_cache
    if cached is not None:
        return cached

    markers: set = set(FALLBACK_MARKERS)
    directory = _locales_dir()
    if directory is None:
        logger.warning(
            "approval_history_policy: locales/ 不可用，退回硬编码兜底标记"
        )
    else:
        for path in sorted(directory.glob("*.yaml")):
            segment = _load_approval_segment(path)
            for key in MESSAGE_KEYS:
                value = segment.get(key)
                if not value:
                    continue
                marker = _marker_for_template(value)
                if marker:
                    markers.add(marker)

    frozen = frozenset(m for m in markers if _is_meaningful(m))
    with _cache_lock:
        _marker_cache = frozen
    return frozen


def clear_cache() -> None:
    """清空标记与正则缓存（测试、或运行期改 locale 后使用）。"""
    global _marker_cache, _pattern_cache
    with _cache_lock:
        _marker_cache = None
        _pattern_cache = None


def _marker_pattern() -> "re.Pattern[str]":
    global _pattern_cache
    with _cache_lock:
        cached = _pattern_cache
    if cached is not None:
        return cached

    markers = sorted(load_markers(), key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(m) for m in markers))
    with _cache_lock:
        _pattern_cache = pattern
    return pattern


def text_blocks_execution(text: str) -> bool:
    """文本是否含任一拦截标记。"""
    if not text:
        return False
    return _marker_pattern().search(text) is not None


def _parse_json_object(content: str) -> Optional[Dict[str, Any]]:
    if not content.lstrip().startswith("{"):
        return None
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _status_is_non_execution(data: Dict[str, Any]) -> bool:
    status = data.get("status")
    if isinstance(status, str) and status.strip().lower() in NON_EXECUTION_STATUSES:
        return True

    if data.get("approval_pending") is True:
        return True

    outcome = data.get("outcome")
    if isinstance(outcome, str):
        normalized = outcome.strip().lower()
        if normalized in NON_EXECUTION_OUTCOMES:
            return True
        if any(normalized.startswith(p) for p in NON_EXECUTION_OUTCOME_PREFIXES):
            return True

    if data.get("user_consent") is False:
        return True

    return False


def result_blocks_execution(content: str) -> bool:
    """``role='tool'`` 结果是否表示「命令没有自由执行」。

    结构化结果先看状态字段（语言无关），再看承载文案的字段；非结构化结果
    整体匹配标记。判定只发生在这一处 —— SQL 侧只做粗筛，避免两处判据漂移。
    """
    if not content:
        return False

    data = _parse_json_object(content)
    if data is None:
        return text_blocks_execution(content)

    if _status_is_non_execution(data):
        return True

    for field in MESSAGE_FIELDS:
        value = data.get(field)
        if isinstance(value, str) and value and text_blocks_execution(value):
            return True
    return False


def sql_like_anchors() -> Tuple[str, ...]:
    """返回 SQL 粗筛用的 ``LIKE`` 锚点（供上游拼 WHERE 片段）。"""
    return SQL_LIKE_ANCHORS


def anchor_covers(marker: str) -> bool:
    """该 marker 能否被某个 SQL 锚点覆盖（供超集断言使用）。"""
    return _contains_anchor(marker)


__all__ = [
    "FALLBACK_MARKERS",
    "MESSAGE_FIELDS",
    "MESSAGE_KEYS",
    "NON_EXECUTION_OUTCOMES",
    "NON_EXECUTION_OUTCOME_PREFIXES",
    "NON_EXECUTION_STATUSES",
    "SQL_LIKE_ANCHORS",
    "anchor_covers",
    "clear_cache",
    "load_markers",
    "result_blocks_execution",
    "sql_like_anchors",
    "text_blocks_execution",
]
