"""Guard: SSE 出站脱敏与帧归属（T2-9 / T3-11）。

New-baseline owner test (2026-10-23). 这族代码原本**零测试覆盖** —— 全程没有
任何用例直接或间接引用 `_clip_tool_args_for_sse` / `_bind_tool_frame` /
`«redaction unavailable»`。按 §八.2 ④「每个安全控制项上线前必须有一条端到端
负例冒烟」，这一项此前是规范的反例；搬迁到 `owner/gateway/sse_redaction.py`
的同时把契约钉住。

为什么必须在 owner 侧自带：这套函数在上游**完全不存在**（`_clip*` / `_redact*`
在 `upstream/main:gateway/platforms/api_server.py` 一个都没有），是纯 owner 新增。
上游测试不会覆盖它，也只能由本仓自己守。

三层防护，逐层钉：

1. **帧归属** —— 别的请求的帧必须降级为 name+status，不得携带参数与输出。
   这是"SSE 只发给请求方"之外的独立一层：扇出型消费方按会话拿事件，隔离一旦
   失效，秘密就流向别人。
2. **脱敏** —— 秘密在上 wire 前被遮蔽。
3. **预算** —— 精简兜底不得突破声明的 wire budget（T3-11：旧实现 11 个键能编码
   到约 44 KB，是声明值的 7 倍）。

另钉两条容易回归的实现细节：脱敏必须先于截断（否则切口留残片），以及脱敏器
不可用时 fail-closed（返回占位符而非原文）。
"""

from __future__ import annotations

import json

import pytest

import gateway.platforms.api_server as api_server
from owner.gateway import sse_redaction as sr


@pytest.fixture(autouse=True)
def _reset_state():
    """`_redaction_failed` 是模块级一次性标志，用例间必须复位。"""
    sr.reset_redaction_state()
    yield
    sr.reset_redaction_state()


# ── 1. 帧归属：隔离层 ──────────────────────────────────────────────────────

def test_own_frame_is_recognised():
    frame = sr.bind_tool_frame("hermes.tool.progress", {"tool": "bash"}, "tok-a")
    assert sr.tool_frame_is_ours(frame, "tok-a") is True


def test_another_requests_frame_is_not_ours():
    """核心负例：别人 token 的帧不得被判为本流。"""
    frame = sr.bind_tool_frame("t", {"tool": "bash", "args": {"cmd": "x"}}, "tok-b")
    assert sr.tool_frame_is_ours(frame, "tok-a") is False


def test_unbound_frame_is_not_ours():
    """2 元组来自早于绑定机制的写入方 —— 视为不属于任何流。"""
    assert sr.tool_frame_is_ours(("t", {"tool": "bash"}), "tok-a") is False


@pytest.mark.parametrize("token", ["", None])
def test_empty_token_never_matches(token):
    """空 token 不能变成"任何帧都算我的"——那是致命的降级。"""
    frame = sr.bind_tool_frame("t", {"tool": "bash"}, "")
    assert sr.tool_frame_is_ours(frame, token) is False


def test_degrade_keeps_name_and_status_only():
    """降级而非丢弃：用户仍要看得到工具在跑，但带不走参数与输出。"""
    payload = {
        "tool": "bash",
        "status": "running",
        "args": {"command": "export API_KEY=sk-secret"},
        "result": "output with secret",
        "toolCallId": "call-1",
    }
    degraded = sr.stripped_tool_frame(payload)
    assert degraded == {
        "tool": "bash", "status": "running", "toolCallId": "call-1",
    }
    assert "args" not in degraded and "result" not in degraded


def test_bind_keeps_token_out_of_the_payload():
    """token 不能进 payload：payload 直接序列化上 wire。"""
    payload = {"tool": "bash"}
    frame = sr.bind_tool_frame("t", payload, "tok-secret")
    assert payload == {"tool": "bash"}, "payload 被就地修改了"
    assert frame[1] == "tok-secret"
    assert "tok-secret" not in json.dumps(frame[2])


# ── 2. 脱敏：遮蔽层 ────────────────────────────────────────────────────────

def test_known_secret_is_masked():
    out = sr.redact_for_sse("export GITHUB_TOKEN=ghp_0123456789abcdefghijABCDEF")
    assert "ghp_0123456789abcdefghijABCDEF" not in out


def test_redactor_unavailable_fails_closed(monkeypatch):
    """脱敏器加载失败必须返回占位符，**不得**原样返回输入。

    这是出站边界："无法验证"不得静默退化成"发出原文"。
    """
    import builtins

    real_import = builtins.__import__

    def _boom(name, *a, **k):
        if name == "agent.redact":
            raise ImportError("simulated")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _boom)

    out = sr.redact_for_sse("GITHUB_TOKEN=ghp_0123456789abcdefghijABCDEF")
    assert out == sr.SSE_REDACT_PLACEHOLDER
    assert "ghp_" not in out


def test_redundant_redaction_of_failure_is_stable(monkeypatch):
    """占位符本身再过一遍脱敏不应变化（幂等）。"""
    assert sr.redact_for_sse(sr.SSE_REDACT_PLACEHOLDER) == sr.SSE_REDACT_PLACEHOLDER


def test_nested_secret_is_reached():
    """嵌两层的凭据也要遮蔽（递归穿透 dict/list/tuple）。"""
    out = sr.redact_args_for_sse({
        "config": {"headers": {"Authorization": "Bearer sk-proj-abcdefghijklmnop"}},
    })
    assert "sk-proj-abcdefghijklmnop" not in json.dumps(out)


def test_result_shape_is_preserved_for_responses_channel():
    """Responses 通道回显 JSON：只遮蔽字符串叶子，形状不动。"""
    res = sr.redact_result_for_sse({"a": "plain", "b": [1, 2], "c": {"d": "text"}})
    assert set(res) == {"a", "b", "c"}
    assert res["b"] == [1, 2]


# ── 3. 脱敏先于截断 ────────────────────────────────────────────────────────

def test_redaction_runs_before_truncation():
    """先截断会在切口留下凭据残片，而残片太短、模式集认不出来。

    用带键名上下文的真实形态（``agent.redact`` 按上下文匹配，见
    ``test_bare_token_without_key_context_is_not_masked``）。截断点设在秘密中段：
    错误实现下输出会是 ``GITHUB_TOKEN=ghp_01…`` —— 前缀残片清晰可见。
    """
    text = "export GITHUB_TOKEN=ghp_0123456789abcdefghijABCDEF" + "y" * 200
    out = sr.clip_jsonable_value(text, max_chars=30)
    assert isinstance(out, str)
    assert "ghp_" not in out, f"切口留下了凭据残片: {out!r}"


def test_output_preview_masks_before_cutting():
    """先截断会在切口留下凭据残片。

    ``agent.redact`` 识别的是**带键名上下文**的凭据（``GITHUB_TOKEN=…``、
    ``Authorization: …``），所以这里用真实形态。错误实现（先截断）会输出
    ``GITHUB_TOKEN=ghp_0…`` —— 残片里还看得到 ``ghp_`` 前缀。
    """
    secret_line = "export GITHUB_TOKEN=ghp_0123456789abcdefghijABCDEF"
    out = sr.clip_tool_output_for_sse(
        {"stdout": secret_line + "\n" + "z" * 5000}, output_max=200
    )
    assert "ghp_" not in out, f"切口留下了凭据残片: {out[:80]!r}"
    assert out.startswith("export GITHUB_TOKEN=")


def test_bare_token_is_partially_masked_not_fully_withheld():
    """**已知边界**（记录而非认可）：裸 token 只做部分遮蔽，首尾字符保留。

    ``agent.redact`` 对**无键名上下文**的长随机串采用"保留首尾、中间省略"的
    部分遮蔽（``ghp_0123456789abcdefghijABCDEF`` → ``ghp_01...CDEF``）。对比
    ``GITHUB_TOKEN=<值>`` 那种带上下文的形态会被整体替换成 ``***``。

    后果：裸 token 的主体不再可还原，但**前缀与后缀各若干字符仍可见**。
    对 ``ghp_`` 这类"前缀即类型标识"的 token，泄漏量可接受；但对自定义格式的
    令牌，首尾可能是有效信息。

    这条用例存在的意义：钉住当前遮蔽强度。若将来升级为整体遮蔽会变红，
    提示同步更新模块文档里"复用 redact 模式集"的表述与本节说明。
    """
    bare = "ghp_0123456789abcdefghijABCDEF"
    out = sr.clip_tool_output_for_sse({"stdout": bare}, output_max=200)
    assert out != bare, "裸 token 未被任何处理地透传了 —— 这比部分遮蔽更糟"
    assert "ghp_0123456789abcdefghij" not in out, "token 主体泄漏"


def test_key_context_form_is_fully_withheld():
    """带上下文的形态整体替换为 ``***`` —— 零残余。"""
    out = sr.redact_for_sse("export GITHUB_TOKEN=ghp_0123456789abcdefghijABCDEF")
    assert out == "export GITHUB_TOKEN=***"


# ── 4. wire budget（T3-11）───────────────────────────────────────────────

def test_slim_fallback_respects_the_declared_budget():
    """精简兜底不得突破 _TOOL_ARGS_MAX_CHARS。

    旧实现把每个主键裁到 4000 且无总量上限：11 个主键 → 约 44 KB = 声明值的 7 倍。
    """
    args = {
        key: "A" * 20000
        for key in api_server._TOOL_ARG_PRIMARY_KEYS
    }
    out = sr.clip_tool_args_for_sse(
        args,
        max_chars=api_server._TOOL_ARGS_MAX_CHARS,
        value_max=api_server._TOOL_ARG_VALUE_MAX,
        primary_keys=api_server._TOOL_ARG_PRIMARY_KEYS,
    )
    encoded = json.dumps(out, ensure_ascii=False, default=str)
    assert len(encoded) <= api_server._TOOL_ARGS_MAX_CHARS, (
        f"编码后 {len(encoded)} 字符，超出声明预算 "
        f"{api_server._TOOL_ARGS_MAX_CHARS}"
    )


def test_args_are_capped_and_json_safe():
    out = sr.clip_tool_args_for_sse(
        {f"k{i}": "v" * 10 for i in range(50)},
        max_chars=api_server._TOOL_ARGS_MAX_CHARS,
        value_max=api_server._TOOL_ARG_VALUE_MAX,
        primary_keys=api_server._TOOL_ARG_PRIMARY_KEYS,
    )
    assert len(out) <= 24
    json.dumps(out)  # 不抛 = 可序列化


def test_non_dict_args_degrade_to_empty():
    assert sr.clip_tool_args_for_sse(
        "not-a-dict", max_chars=100, value_max=10, primary_keys=()
    ) == {}


# ── 5. 官方文件仍以薄委托暴露同名符号（调用点不改）─────────────────────

@pytest.mark.parametrize("name", [
    "_redact_for_sse", "_redact_args_for_sse", "_redact_nested_for_sse",
    "_redact_result_for_sse", "_bind_tool_frame", "_tool_frame_is_ours",
    "_stripped_tool_frame", "_clip_jsonable_value", "_clip_tool_args_for_sse",
    "_clip_tool_output_for_sse",
])
def test_official_module_still_exposes_the_same_symbols(name):
    """迁移不改变调用点：官方模块必须仍有同名可调用对象。"""
    assert callable(getattr(api_server, name, None)), f"{name} 在 api_server 里消失了"


def test_delegate_passes_upstream_budget_constants():
    """委托必须把上游常量传下去，不能在 owner 侧留副本（否则上游调预算会静默漂移）。"""
    args = {k: "A" * 20000 for k in api_server._TOOL_ARG_PRIMARY_KEYS}
    out = api_server._clip_tool_args_for_sse(args)
    encoded = json.dumps(out, ensure_ascii=False, default=str)
    assert len(encoded) <= api_server._TOOL_ARGS_MAX_CHARS


def test_official_delegate_matches_owner_implementation():
    """官方委托与 owner 实现必须给出同一结果（行为等价）。"""
    payload = {"command": "echo hi", "secret": "ghp_0123456789abcdefghijABCDEF"}
    assert api_server._clip_tool_args_for_sse(payload) == sr.clip_tool_args_for_sse(
        payload,
        max_chars=api_server._TOOL_ARGS_MAX_CHARS,
        value_max=api_server._TOOL_ARG_VALUE_MAX,
        primary_keys=api_server._TOOL_ARG_PRIMARY_KEYS,
    )
