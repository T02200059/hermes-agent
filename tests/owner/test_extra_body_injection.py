"""Guard: 模型级 extra_body 注入的 allowlist（偿还 `model-extra-body-injection` 债务）。

2026-10-23 新基线守卫。此前登记在 `owner/validation/coverage_gaps.txt`：

    model-extra-body-injection  tests/owner/test_extra_body_injection.py removed
    2026-10-20; allowlist/passthrough of patch.yaml extra_body unpinned

按 §2.2.0 偿还策略撤销登记。

## 这条为什么是安全控制而不是配置功能

`extra_body` 会被**逐字合并进发给 LLM 的请求体**。`patch.yaml` 位于
`~/.hermes/`，是运维可写的 —— 本身可信，但一个被攻破的 cron 脚本、一次误编辑，
都能往里塞任意键。没有 allowlist 时，一条

    tools: [{...任意工具定义...}]

会被原样送进请求，等于让配置文件替模型定义它能调用什么。所以这里的 allowlist
是**纵深防御**：不是假设 patch.yaml 已被攻破，而是让"被攻破"不等于"直接生效"。

## 三层过滤

1. 顶层键白名单：`_ALLOWED_EXTRA_BODY_KEYS = {enable_thinking, thinking}`。
   其余一律丢弃并告警 —— 丢弃要**留下痕迹**，否则运维改了配置却不生效、
   查不出原因。
2. 嵌套白名单：`thinking` 是 dict 时，只保留 `{type, clear_thinking}`。
   深度只一层 —— 再深的层级原样透传，因为 owner 目前没有更深的键；一旦有人加，
   必须同时扩白名单，而不是依赖"反正不会有人写那么深"。
3. 合并方向：只 `update` 到调用方给的 `extra_body` 上，**不反向覆盖**已有键？
   —— 实际是覆盖（`update` 语义）。这一条要钉住，因为"配置优先还是代码优先"
   一旦反转，注入的内容会被请求方悄悄改掉。

## 两个必须钉住的失败方向

- **配置读取失败 → 跳过注入**（`except: logger.debug`）：patch.yaml 是可选的，
  API 调用不能因为它挂了而失败。这是有意的 fail-open **只针对"没有配置"**；
  它不得被扩大成"allowlist 也跳过"。
- **参数不全 → 直接返回**：`extra_body` 不是 dict / provider 为空 / model 为空，
  三者任一都应静默不注入（不是注入空 dict，也不是抛）。
"""

from __future__ import annotations

import pytest

from owner import extra_body_injection as ebi


@pytest.fixture(autouse=True)
def _stub_config(monkeypatch):
    """默认无配置，用例按需覆盖。真实 patch.yaml 不参与测试。"""
    monkeypatch.setattr(
        ebi, "_injected_from_config", None, raising=False
    )
    import owner.patch_config as pc

    monkeypatch.setattr(pc, "get_model_extra_body", lambda p, m: {}, raising=True)
    yield


def _inject(monkeypatch, additions, *, provider="xfyun", model="m"):
    """以给定的 patch.yaml additions 跑一次注入，返回被合并后的 dict。"""
    import owner.patch_config as pc

    monkeypatch.setattr(
        pc, "get_model_extra_body",
        lambda p, m: dict(additions) if additions else {}, raising=True,
    )
    target: dict = {}
    ebi.inject_model_extra_body(target, provider, model)
    return target


# ── 顶层白名单 ────────────────────────────────────────────────────────────

def test_allowlisted_key_is_merged(monkeypatch):
    """正向基线：没有它，下面所有负例都可能只是"永远不注入"。"""
    out = _inject(monkeypatch, {"enable_thinking": True})
    assert out == {"enable_thinking": True}


def test_non_allowlisted_key_is_dropped(monkeypatch):
    """核心负例：任意键不得进入请求体。

    `tools` 是最危险的形态 —— 它能让配置文件替模型定义可调用的工具。
    """
    out = _inject(monkeypatch, {"tools": [{"name": "evil"}]})
    assert out == {}, "非白名单键被合并进了请求体"


def test_mixed_keys_only_allowlisted_survive(monkeypatch):
    """白名单键与非白名单键混在一起时，只保留前者。"""
    out = _inject(monkeypatch, {"enable_thinking": False, "tools": [1], "temperature": 2})
    assert out == {"enable_thinking": False}


def test_dropped_key_is_logged(monkeypatch):
    """丢弃必须留下痕迹：否则运维改了配置不生效、查不出原因。"""
    msgs: list = []
    monkeypatch.setattr(
        ebi.logger, "warning",
        lambda fmt, *a, **k: msgs.append(fmt % a if a else fmt),
    )
    _inject(monkeypatch, {"tools": [1]})
    assert any("tools" in str(m) for m in msgs), "丢弃非白名单键时没有告警"


# ── 嵌套白名单 ────────────────────────────────────────────────────────────

def test_nested_thinking_keeps_only_allowed_subkeys(monkeypatch):
    """`thinking` 是 dict 时，未登记的嵌套键要丢掉。"""
    out = _inject(monkeypatch, {
        "thinking": {"type": "enabled", "evil": "x", "clear_thinking": True},
    })
    assert out == {"thinking": {"type": "enabled", "clear_thinking": True}}


def test_nested_filter_does_not_touch_non_dict_values(monkeypatch):
    """`thinking: true` 这种标量形态必须原样保留（不是所有 provider 都用 dict）。"""
    out = _inject(monkeypatch, {"thinking": True})
    assert out == {"thinking": True}


def test_unknown_nested_keys_of_an_unlisted_parent_are_untouched(monkeypatch):
    """没有嵌套白名单的父键（`enable_thinking`）不做嵌套过滤 —— 它通常是标量。

    这里断言的是"只对登记过嵌套白名单的父键递归"，避免有人把嵌套过滤扩展成
    "对所有 dict 值都过滤"，那会误伤未来新增的 dict 型配置。
    """
    out = _inject(monkeypatch, {"enable_thinking": {"anything": 1}})
    assert out == {"enable_thinking": {"anything": 1}}


# ── 合并方向 ──────────────────────────────────────────────────────────────

def test_injection_overwrites_the_caller_value(monkeypatch):
    """patch.yaml 的值覆盖调用方已有的同名键 —— 这是当前语义。

    钉住它是为了：若有人把方向反成"调用方优先"，注入会静默失效（配置写了
    但请求仍用默认值）。两种方向都可以是对的，但**改变必须是有意的**。
    """
    import owner.patch_config as pc

    monkeypatch.setattr(
        pc, "get_model_extra_body", lambda p, m: {"enable_thinking": False}, raising=True
    )
    target = {"enable_thinking": True}
    ebi.inject_model_extra_body(target, "xfyun", "m")
    assert target["enable_thinking"] is False


def test_target_is_mutated_in_place(monkeypatch):
    """接口契约是原地修改（返回 None）—— 调用方不接返回值。"""
    import owner.patch_config as pc

    monkeypatch.setattr(
        pc, "get_model_extra_body", lambda p, m: {"enable_thinking": True}, raising=True
    )
    target: dict = {}
    ret = ebi.inject_model_extra_body(target, "xfyun", "m")
    assert ret is None
    assert target["enable_thinking"] is True


# ── 无配置 / 参数不全：静默跳过 ───────────────────────────────────────────

def test_no_configuration_leaves_the_target_untouched(monkeypatch):
    out = _inject(monkeypatch, {})
    assert out == {}


@pytest.mark.parametrize("provider,model", [
    (None, "m"),
    ("", "m"),
    ("xfyun", None),
    ("xfyun", ""),
])
def test_missing_provider_or_model_skips_injection(monkeypatch, provider, model):
    """provider 与 model 都是定位配置的必需维度，缺一即不注入。"""
    import owner.patch_config as pc

    called = []
    monkeypatch.setattr(
        pc, "get_model_extra_body",
        lambda p, m: called.append((p, m)) or {"enable_thinking": True},
        raising=True,
    )
    target: dict = {}
    ebi.inject_model_extra_body(target, provider, model)
    assert target == {}
    assert called == [], "参数不全时不应去读配置"


def test_non_dict_extra_body_is_ignored(monkeypatch):
    import owner.patch_config as pc

    monkeypatch.setattr(
        pc, "get_model_extra_body", lambda p, m: {"enable_thinking": True}, raising=True
    )
    # 传一个不可变对象：不应抛，也不应尝试 update
    ebi.inject_model_extra_body("not-a-dict", "xfyun", "m")  # type: ignore[arg-type]


# ── 失败方向：读配置炸了不能炸 API 调用 ───────────────────────────────────

def test_config_read_failure_does_not_raise(monkeypatch):
    """patch.yaml 是可选配置，读它失败不能中断 API 调用。"""
    import owner.patch_config as pc

    def _boom(p, m):
        raise RuntimeError("config exploded")

    monkeypatch.setattr(pc, "get_model_extra_body", _boom, raising=True)
    target = {"existing": 1}
    ebi.inject_model_extra_body(target, "xfyun", "m")
    assert target == {"existing": 1}, "配置读失败时不应改动目标"


def test_config_read_failure_does_not_bypass_the_allowlist(monkeypatch):
    """**关键边界**：fail-open 只针对"没有配置"，不得扩大成"跳过白名单"。

    构造一个配置读取成功但返回恶意内容的场景 —— 白名单必须仍然生效。
    若有人把 `except` 的范围扩大到覆盖 `_filter_extra_body`，这条会红。
    """
    out = _inject(monkeypatch, {"tools": [{"name": "evil"}], "enable_thinking": True})
    assert "tools" not in out
    assert out == {"enable_thinking": True}


def test_filter_is_pure_and_does_not_mutate_input(monkeypatch):
    """`_filter_extra_body` 不应改掉传进来的 additions（调用方可能复用）。"""
    additions = {"enable_thinking": True, "tools": [1]}
    ebi._filter_extra_body(additions)
    assert additions == {"enable_thinking": True, "tools": [1]}
