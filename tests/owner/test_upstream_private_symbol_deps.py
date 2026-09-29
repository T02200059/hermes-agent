"""[owner] 对官方**私有符号**的依赖：常驻守卫（T2-16 + 同类普查）。

背景
----
`gateway/platforms/api_server_media.py`（owner 在官方树内新增的文件）曾这样调
官方符号：

    from gateway.platforms.api_server import _resolve_media_to_data_urls

`_resolve_media_to_data_urls` 是**官方私有**符号 —— 上游已经搬过它一次
（`api_server.py` 我方基点 1165 → 上游 873），并在 2026-09-02（`581d97e545`）
重写了它的正文。裸导入的后果是：任何一次改名/迁移都会让**媒体投递路径**上
出现 ImportError，而启动自检不看那里。

修法（2026-09-29 用户决策）是**不复制实现**：调用点按名字在运行时解析、允许
失败、降级为「不内联」（图片转为可下载附件而非内联 data URL）并 **warn 一次**；
再**按名字把它钉住**，让下一次 sync 的改名变成一条点名的红用例。

为什么不复制
------------
复制会把基点（1165 处）的语义永久写进我们自己的树里。实测该函数在上游**已经
变了**（重写 docstring、重构 `_to_data_url`、新增 `_terminal_sentinel_start()`
处理 `#111046` 的尾部 `<|eos|>` 令牌），所以复制等于主动放弃上游后续的所有修复。
同理也**不要**用 `safe_load` 式的「看起来等价」的重写来简化这里的解析。

本文件三类断言
--------------
1. 被我们按名字够到的官方私有符号**仍然存在**（并按签名核对）—— 断裂点在 CI 显形。
2. 降级路径**真的可用且可观测**（不含内联仍能把图片交付出去；只告警一次；
   告警文案点名 §16.13 的处置指引）。
3. **全仓普查守卫**：`owner/` 与官方树内 owner 新增文件里，凡 `from <官方> import _x`
   必须在 `try:` 块内，或在 allowlist 里并写明为什么不能降级。
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pathlib
import sys
import types
from typing import Any, Dict, List, Tuple

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]

# 官方（非 owner）模块前缀。命中这些前缀的私有符号才需要可降级 + 可观测。
OFFICIAL_PREFIXES = (
    "gateway",
    "agent",
    "tools",
    "hermes_cli",
    "cron",
    "run_agent",
    "plugins",
    "ui",
)

# 被我们按名字够到的官方私有符号：(模块, 属性, 为什么需要它 / 谁在用)。
#
# 这份表就是「同类普查」的常驻形态 —— 加一条新依赖时也必须在这里加一行，
# 否则 `test_the_census_covers_every_guarded_private_import` 会红。
PRIVATE_SYMBOLS: List[Tuple[str, str, str]] = [
    (
        "gateway.platforms.api_server",
        "_resolve_media_to_data_urls",
        "gateway/platforms/api_server_media.py::_inline_image_data_urls（T2-16 本体）",
    ),
    (
        "hermes_cli.runtime_provider",
        "_get_model_config",
        "owner/patches/pool_base_url_override.py::config_base_url_override",
    ),
    (
        "agent.i18n",
        "_locales_dir",
        "owner/i18n/display_filter.py::_locales_dir + "
        "owner/approval/approval_history_policy.py::_locales_dir",
    ),
    (
        "agent.i18n",
        "_load_catalog",
        "owner/i18n/display_filter.py::_load_catalog",
    ),
    (
        "agent.context_compressor",
        "_SUMMARY_END_MARKER",
        "owner/feishu/compression_summary.py::_strip_summary_prefix（摘要尾标，格式常量）",
    ),
    (
        "agent.context_compressor",
        "_HISTORICAL_SUMMARY_PREFIXES",
        "owner/feishu/compression_summary.py::_strip_summary_prefix（历史摘要前缀，格式常量）",
    ),
    (
        "tools.approval",
        "_YOLO_MODE_FROZEN",
        "owner/semantic_audit/policy.py::should_skip_for_yolo",
    ),
    (
        "tools.approval",
        "_lock",
        "owner/approval/skill_manage_gate.py（skill 审批门的会话锁）",
    ),
    (
        "tools.approval",
        "_gateway_notify_cbs",
        "owner/approval/skill_manage_gate.py（网关通知回调表）",
    ),
    (
        "tools.approval",
        "_await_gateway_decision",
        "owner/approval/skill_manage_gate.py（等待用户审批决定）",
    ),
    (
        "plugins.platforms.feishu.adapter",
        "_render_merge_forward_entries",
        "tools/feishu_client_utils.py::read_merge_forward_as_text",
    ),
    (
        "gateway.session_context",
        "_UNSET",
        "owner/cron/session_context.py（ContextVar 的 default，必须就是上游那个哨兵）",
    ),
    (
        "gateway.session_context",
        "_VAR_MAP",
        "owner/cron/session_context.py（注册 HERMES_CRON_SESSION 的目标表）",
    ),
]

# 有意**不**降级的私有依赖：文件 → 理由。
#
# 可降级的前提是「降级后语义仍然成立」。注册类依赖不满足这一点：目标表没了
# 就注册不了，静默跳过只会让 cron 悄悄丢掉会话上下文 —— 比启动即报错更糟。
FAIL_LOUD_ALLOWLIST: Dict[str, str] = {
    "owner/cron/session_context.py": (
        "模块的全部职责就是往官方 _VAR_MAP 注入；表没了就没有可回退的语义，"
        "且 _UNSET 必须**就是**上游那个哨兵（被按身份比较），换成本地占位符会改"
        "变比较结果。故保留硬导入 + 由本文件的用例钉住。"
    ),
}


class _Recorder:
    """记录 ``logger.warning(message, *args)`` 的调用（不格式化，保留模板）。"""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, Tuple[Any, ...]]] = []

    def __call__(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((message, args))

    @property
    def messages(self) -> List[str]:
        return [message for message, _args in self.calls]


@pytest.fixture
def api_server_module():
    return importlib.import_module("gateway.platforms.api_server")


@pytest.fixture
def media_module():
    return importlib.import_module("gateway.platforms.api_server_media")


# ---------------------------------------------------------------------------
# 1. 被够到的官方私有符号仍然存在
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module_name,attr,why",
    PRIVATE_SYMBOLS,
    ids=[f"{m.split('.')[-1]}.{a}" for m, a, _ in PRIVATE_SYMBOLS],
)
def test_official_private_symbols_we_reach_for_still_exist(module_name, attr, why):
    """断裂点必须在 CI 上显形，而不是在运行期的某条投递路径上。

    ``why`` 一并断言非空 —— 表里每一行都要说清「谁在用」，否则这份普查会
    退化成一份没人敢删也看不懂的清单。
    """
    assert why, f"{module_name}.{attr} 在 PRIVATE_SYMBOLS 里必须写明用途"

    module = importlib.import_module(module_name)
    assert hasattr(module, attr), (
        f"{module_name}.{attr} 不见了（上游改名或迁移）。"
        f"调用方：{why}。请把它改指到新位置，并同步更新本文件的 PRIVATE_SYMBOLS。"
    )


def test_the_api_server_resolver_keeps_the_signature_we_call_it_with(api_server_module):
    """改名之外，**签名**变了同样会坏：我们按 ``(text)`` 单参调用它。"""
    resolver = getattr(api_server_module, "_resolve_media_to_data_urls")
    params = list(inspect.signature(resolver).parameters.values())

    assert [p.name for p in params] == ["text"], (
        "gateway.platforms.api_server._resolve_media_to_data_urls 的签名变了；"
        "gateway/platforms/api_server_media.py::_inline_image_data_urls 按 (text) 调它"
    )
    assert params[0].default is inspect.Parameter.empty, "text 不应变成可选参数"
    assert inspect.signature(resolver).return_annotation in (str, "str", inspect.Signature.empty)


def test_the_cron_session_var_is_registered_into_the_upstream_var_map():
    """注册类依赖的正面断言：既要求注册发生，也要求哨兵**是上游那个对象**。"""
    session_context = importlib.import_module("gateway.session_context")
    owner_cron = importlib.import_module("owner.cron.session_context")

    assert owner_cron._CRON_SESSION is session_context._VAR_MAP.get("HERMES_CRON_SESSION"), (
        "owner.cron.session_context 没有把 _CRON_SESSION 注册进 gateway.session_context._VAR_MAP"
    )
    assert owner_cron._CRON_SESSION.get() is session_context._UNSET, (
        "_CRON_SESSION 的默认值必须**就是** gateway.session_context._UNSET（被按身份比较），"
        "不能是本地自造的哨兵"
    )


# ---------------------------------------------------------------------------
# 2. 降级路径真的可用、且可观测
# ---------------------------------------------------------------------------


def test_finalize_api_media_degrades_when_the_resolver_is_gone(
    api_server_module, media_module, monkeypatch, tmp_path
):
    """解析器不见了：**不抛异常**，把标签之外的正文本原样带出去交给 ``extract_media``。

    输入必须真的含 ``MEDIA:`` 标签 —— ``finalize_api_media`` 在没有标签时会提前
    返回，那条路径压根走不到解析器，用例会「绿得毫无意义」（实测：这曾让
    「降级改成抛异常」「降级丢掉文本」两个变异体双双逃逸）。
    """
    image = tmp_path / "chart.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)

    monkeypatch.delattr(api_server_module, "_resolve_media_to_data_urls")
    monkeypatch.setattr(media_module, "_inline_resolver_warned", False)

    store = media_module.ApiMediaStore(root=tmp_path / "store")
    cleaned, files, _notices = media_module.finalize_api_media(
        f"before\nMEDIA:{image}\nafter\n", store
    )

    assert "before" in cleaned, (
        f"降级不得吞掉标签之外的正文本，实际 cleaned={cleaned!r}"
    )
    assert "after" in cleaned, (
        f"降级不得吞掉标签之后的正文本，实际 cleaned={cleaned!r}"
    )
    assert "data:image/png;base64," not in cleaned, "解析器不可用时不应再产出内联 data URL"
    assert files, "降级腿必须仍然把图片作为附件交付，而不是让调用点直接抛异常"


def test_the_degrade_keeps_an_image_deliverable_as_a_file(
    api_server_module, media_module, monkeypatch, tmp_path
):
    """降级是「换一种交付方式」，不是「丢件」。

    两条腿各自的契约：
      * 解析器可用 → 图片**内联**进文本（markdown data URL），不登记附件；
      * 解析器不可用 → 图片**不内联**，但仍被登记为可下载附件。
    两腿共同的底线：``MEDIA:`` 标签不许把原始服务端路径泄漏给客户端。
    """
    image = tmp_path / "chart.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)

    monkeypatch.setattr(media_module, "_inline_resolver_warned", False)
    inlined_text, inlined_files, _n1 = media_module.finalize_api_media(
        f"See MEDIA:{image}\n", media_module.ApiMediaStore(root=tmp_path / "store")
    )
    assert "data:image/png;base64," in inlined_text, "解析器可用时应当内联成 data URL"
    assert inlined_files == [], "已内联的图片不应再被登记为附件（否则会交付两份）"

    monkeypatch.delattr(api_server_module, "_resolve_media_to_data_urls")
    degraded_text, degraded_files, _n2 = media_module.finalize_api_media(
        f"See MEDIA:{image}\n", media_module.ApiMediaStore(root=tmp_path / "store2")
    )
    assert degraded_files, "解析器不可用时图片必须仍然作为附件交付，而不是消失"
    assert "data:image/png;base64," not in degraded_text, "降级腿不应再产出内联 data URL"

    for text in (inlined_text, degraded_text):
        assert "MEDIA:" not in text, "MEDIA: 标签无论如何都不能泄漏原始路径给客户端"


def test_the_degrade_warns_exactly_once_and_names_the_fix(
    api_server_module, media_module, monkeypatch, tmp_path
):
    """静默降级是这次修法要消灭的东西：必须 warn，且**只 warn 一次**。"""
    recorder = _Recorder()
    monkeypatch.setattr(media_module.logger, "warning", recorder)
    monkeypatch.setattr(media_module, "_inline_resolver_warned", False)
    monkeypatch.delattr(api_server_module, "_resolve_media_to_data_urls")

    store = media_module.ApiMediaStore(root=tmp_path / "store")
    for _ in range(3):
        media_module.finalize_api_media("See MEDIA:/tmp/x.png\n\x00", store)

    assert len(recorder.calls) == 1, (
        f"降级告警应每进程一次，实际 {len(recorder.calls)} 次：{recorder.messages}"
    )
    assert "§16.13" in recorder.messages[0], (
        "告警必须点名处置指引（owner/docs/owner改动清单.md §16.13），"
        "否则下一个人只看到一条没有出路的 warning"
    )


@pytest.mark.parametrize(
    "module_name,attr,owner_module,flag",
    [
        ("agent.i18n", "_locales_dir", "owner.i18n.display_filter", "_private_dep_notices"),
        ("agent.i18n", "_load_catalog", "owner.i18n.display_filter", "_private_dep_notices"),
        (
            "agent.i18n",
            "_locales_dir",
            "owner.approval.approval_history_policy",
            "_private_dep_notices",
        ),
        (
            "hermes_cli.runtime_provider",
            "_get_model_config",
            "owner.patches.pool_base_url_override",
            "_private_dep_notices",
        ),
    ],
)
def test_owner_side_degrade_paths_are_observable(
    module_name, attr, owner_module, flag, monkeypatch
):
    """四个 owner 站点原本就是「静默降级」（``except Exception: pass``）。

    降级本身没问题，静默才有问题：上游换了名字而我们还走次优路径这件事，
    必须留下一条 warn。
    """
    upstream = importlib.import_module(module_name)
    owner_mod = importlib.import_module(owner_module)

    # 清掉 warn-once 状态，否则同 key 的第二个参数化用例会看到 0 条告警
    monkeypatch.setattr(owner_mod, flag, set())
    recorder = _Recorder()
    monkeypatch.setattr(owner_mod.logger, "warning", recorder)

    if owner_module.endswith("pool_base_url_override"):
        monkeypatch.delattr(upstream, attr)
        result = owner_mod.config_base_url_override("xiaomi", "http://example.invalid")
        assert result is None
    elif attr == "_locales_dir":
        monkeypatch.delattr(upstream, attr)
        resolved = owner_mod._locales_dir()
        assert resolved is None or resolved.is_dir(), "降级后必须落到本地解析，而不是抛异常"
    else:
        monkeypatch.delattr(upstream, attr)
        catalog = owner_mod._load_catalog("zh")
        assert isinstance(catalog, dict)

    assert recorder.calls, f"{owner_module} 的降级路径没有留下任何告警（静默降级）"
    assert "§16.13" in recorder.messages[0], (
        f"{owner_module} 的降级告警必须点名 owner/docs/owner改动清单.md §16.13"
    )


# ---------------------------------------------------------------------------
# 2b. 三个「模块级 / 安全门 / 无副作用」站点的降级
# ---------------------------------------------------------------------------


def test_compression_summary_disables_itself_when_the_anchors_are_gone(monkeypatch):
    """格式锚点拿不到时必须**整个能力关闭**，不能「照原样交出去」。

    这两条锚点是官方私有的格式常量，猜不了：返回未剥离前缀/尾标的原文会让
    下游把「摘要 + 真正的一轮对话」当成摘要整段播出去 —— 那比不播更糟。
    """
    compressor = importlib.import_module("agent.context_compressor")
    summary = importlib.import_module("owner.feishu.compression_summary")

    recorder = _Recorder()
    monkeypatch.setattr(summary.logger, "warning", recorder)
    monkeypatch.delattr(compressor, "_SUMMARY_END_MARKER")
    monkeypatch.delattr(compressor, "_HISTORICAL_SUMMARY_PREFIXES")

    try:
        reloaded = importlib.reload(summary)
        assert reloaded._SUMMARY_ANCHORS_AVAILABLE is False, (
            "锚点导入失败后 _SUMMARY_ANCHORS_AVAILABLE 必须为 False"
        )
        messages = [
            {
                reloaded.COMPRESSED_SUMMARY_METADATA_KEY: True,
                "content": f"{reloaded.SUMMARY_PREFIX}body{reloaded.SUMMARY_PREFIX}",
            }
        ]
        assert reloaded.find_compressed_summary(messages) is None, (
            "锚点不可用时 find_compressed_summary 必须返回 None（能力关闭），"
            "而不是把未剥离的原文当摘要交出去"
        )
        assert recorder.calls, "锚点不可用必须留下一条告警（不能静默降级）"
        assert "§16.13" in recorder.messages[0]
    finally:
        monkeypatch.undo()
        importlib.reload(summary)

    assert importlib.import_module(
        "owner.feishu.compression_summary"
    )._SUMMARY_ANCHORS_AVAILABLE is True, "本用例必须把模块恢复原状"


def test_merge_forward_renderer_degrades_to_the_functions_own_failure_shape(
    monkeypatch,
):
    """官方渲染器够不到时，走本函数**既有**的 ``(None, msg)`` 失败形态。

    不能改成抛异常：那样一条被改名的导入会打掉整个 merge_forward 读取；
    也不能返回 ``(text, None)`` 假装成功 —— 调用方会把 ``None`` 当渲染结果用。
    """
    utils = importlib.import_module("tools.feishu_client_utils")
    monkeypatch.setattr(utils, "_private_dep_notices", set())
    recorder = _Recorder()
    monkeypatch.setattr(utils.logger, "warning", recorder)

    monkeypatch.setattr(
        utils,
        "do_request",
        lambda *a, **k: (0, "ok", {"items": [{"upper_message_id": "om_1", "message_id": "c1"}]}),
    )
    # 用一个不含该私有符号的替身模块顶掉真 adapter —— 既模拟「上游改名」，
    # 也避免为一个守卫用例去重型导入整个飞书适配器。
    monkeypatch.setitem(
        sys.modules, "plugins.platforms.feishu.adapter", types.ModuleType("plugins.platforms.feishu.adapter")
    )

    text, err = utils.read_merge_forward_as_text(client=None, message_id="om_1")

    assert text is None and isinstance(err, str) and err, (
        "降级必须走 (None, msg)，实际得到 "
        f"({text!r}, {err!r})"
    )
    assert recorder.calls, "降级必须留下告警"
    assert "§16.13" in recorder.messages[0]


def test_semantic_audit_policy_warns_when_the_yolo_probe_is_unreachable(monkeypatch):
    """降级方向安全（不跳过审计 = 更严格），但 `respect_yolo` 不能变成空开关。"""
    approval = importlib.import_module("tools.approval")
    policy = importlib.import_module("owner.semantic_audit.policy")

    monkeypatch.setattr(policy, "_private_dep_notices", set())
    recorder = _Recorder()
    monkeypatch.setattr(policy.logger, "warning", recorder)
    monkeypatch.delattr(approval, "_YOLO_MODE_FROZEN")

    assert policy.should_skip_for_yolo({"respect_yolo": True}) is False, (
        "探针不可用时必须退到「不跳过审计」"
    )
    assert recorder.calls, "respect_yolo 静默失效是这次修法要消灭的形态"
    assert "§16.13" in recorder.messages[0]


# ---------------------------------------------------------------------------
# 3. 全仓普查守卫：官方私有导入必须在 try 内，或在 allowlist 里写明理由
# ---------------------------------------------------------------------------


def _is_official(module: str) -> bool:
    return module.split(".")[0] in OFFICIAL_PREFIXES


def _private_imports(path: pathlib.Path) -> List[Tuple[int, str, str, bool]]:
    """[(行号, 模块, 符号, 是否在 try 块内)]。"""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    found: List[Tuple[int, str, str, bool]] = []

    def visit(node: ast.AST, guarded: bool) -> None:
        if isinstance(node, ast.Try):
            for child in node.body:
                visit(child, True)
            for handler in node.handlers:
                visit(handler, guarded)
            for child in node.orelse + node.finalbody:
                visit(child, guarded)
            return
        if isinstance(node, ast.ImportFrom) and _is_official(node.module or ""):
            for alias in node.names:
                if alias.name.startswith("_"):
                    found.append((node.lineno, node.module or "", alias.name, guarded))
        for child in ast.iter_child_nodes(node):
            visit(child, guarded)

    visit(tree, False)
    return found


def _census_targets() -> List[pathlib.Path]:
    """owner/ 全量 + 官方树内「owner 新增」的文件（它们没有 owner/ 前缀）。"""
    targets = sorted((REPO / "owner").rglob("*.py"))
    extra = [
        REPO / "gateway/platforms/api_server_media.py",
        REPO / "tools/feishu_client_utils.py",
    ]
    targets += [p for p in extra if p.is_file()]
    return targets


def test_no_official_private_import_is_left_unguarded():
    """裸导入官方私有符号 = 下一次 sync 的静默断裂点。"""
    offenders: List[str] = []
    for path in _census_targets():
        rel = path.relative_to(REPO).as_posix()
        if rel in FAIL_LOUD_ALLOWLIST:
            continue
        for lineno, module, symbol, guarded in _private_imports(path):
            if not guarded:
                offenders.append(f"{rel}:{lineno} — from {module} import {symbol}")

    assert not offenders, (
        "以下官方私有符号是**裸导入**（不在 try 块内）。要么改成可降级 + 可观测"
        "（并在 tests/owner/test_upstream_private_symbol_deps.py 的 PRIVATE_SYMBOLS 里"
        "登记），要么加进 FAIL_LOUD_ALLOWLIST 并写明为什么不能降级：\n  "
        + "\n  ".join(offenders)
    )


def test_the_fail_loud_allowlist_is_still_justified():
    """allowlist 里的每一行都必须**确实**是裸导入。

    否则它就从「记录一个刻意的决定」退化成了「一条掩盖新裸导入的免检通道」。
    """
    for rel, reason in FAIL_LOUD_ALLOWLIST.items():
        assert reason.strip(), f"{rel} 在 FAIL_LOUD_ALLOWLIST 里必须写明理由"

        path = REPO / rel
        assert path.is_file(), f"{rel} 在 FAIL_LOUD_ALLOWLIST 里但文件不存在"

        raw = _private_imports(path)
        assert raw, f"{rel} 不再是裸导入了 —— 请把它从 allowlist 里删掉"
        assert any(not guarded for _l, _m, _s, guarded in raw), (
            f"{rel} 已经被包进 try 块了 —— 请把它从 FAIL_LOUD_ALLOWLIST 里删掉，"
            "并按可降级站点登记"
        )


def test_the_census_covers_every_guarded_private_import():
    """反向校验：所有「已包进 try」的官方私有导入都必须在 PRIVATE_SYMBOLS 里有登记。

    只查「有没有裸导入」是不够的 —— 那样在 try 里偷偷加一条没人知道的依赖
    是无声通过的。这条让清单与代码互为约束。
    """
    registered = {(module, attr) for module, attr, _why in PRIVATE_SYMBOLS}

    missing: List[str] = []
    for path in _census_targets():
        rel = path.relative_to(REPO).as_posix()
        if rel in FAIL_LOUD_ALLOWLIST:
            continue
        for lineno, module, symbol, guarded in _private_imports(path):
            if guarded and (module, symbol) not in registered:
                missing.append(f"{rel}:{lineno} — from {module} import {symbol}")

    assert not missing, (
        "以下**已可降级**的官方私有导入没有登记在 PRIVATE_SYMBOLS 里"
        "（加依赖必须同时上清单，否则这份普查没有约束力）：\n  "
        + "\n  ".join(missing)
    )


def test_the_census_actually_reaches_the_files_it_claims_to_guard():
    """守卫自证：普查目标集合必须真的覆盖到已知的站点，且能解析出导入。

    防止「路径写错 ⇒ 枚举为空 ⇒ 全绿」这种自证通过的形态。
    """
    targets = {p.relative_to(REPO).as_posix() for p in _census_targets()}

    for expected in (
        "owner/cron/session_context.py",
        "owner/i18n/display_filter.py",
        "owner/approval/approval_history_policy.py",
        "owner/patches/pool_base_url_override.py",
        "gateway/platforms/api_server_media.py",
    ):
        assert expected in targets, f"普查目标集合漏了 {expected}"

    assert len(targets) > 100, f"普查目标只有 {len(targets)} 个文件，路径枚举明显不对"

    parsed = sum(1 for p in _census_targets() if _private_imports(p))
    assert parsed >= 5, f"只有 {parsed} 个文件解析出官方私有导入，ast 扫描可能失效了"
