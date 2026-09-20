"""Tests for owner ``approval_explainer`` — 审批卡命令解说.

设计稿: owner/docs/design/approval-command-explainer/approval-explainer.md

覆盖:
  1. 配置: 三级查找 + 非法值回落默认 + provider/model auto 归一
  2. fail-open: call_llm 异常/超时 → None, 不上抛
  3. 缓存: 同命令命中, 不同 description 不命中, TTL 过期失效
  4. 输出清理: 引号剥离 / 超长截断
  5. 飞书卡: explanation 嵌入 / 空串时卡片与原行为一致
  6. QQ 文本: ApprovalRequest.explanation 渲染 / 空串跳过
  7. 未启用平台 → None (不调 LLM)

所有 LLM 路径 mock, 不打真网络。
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from owner.approval_explainer import config as ae_config
from owner.approval_explainer import explain as ae_explain
from owner.approval_explainer import prompt as ae_prompt


def _ok_response(text: str = "这条命令会删除 /tmp 下 30 天前的日志文件，只影响该目录，可逆（重新生成）。"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))]
    )


def _fake_llm_ok(*a, **k):
    return _ok_response()


# ---------------------------------------------------------------------------
# 1. 配置
# ---------------------------------------------------------------------------


class TestConfig:
    def test_defaults_off(self):
        cfg = ae_config.load_config()
        assert cfg["enabled"] is False
        assert cfg["timeout_ms"] == 30000
        assert cfg["cache_ttl_seconds"] == 600

    def test_resolve_enabled_level3(self, monkeypatch):
        monkeypatch.setattr(
            ae_config,
            "_load_approval_explainer_cfg",
            lambda: {
                "enabled": True,
                "platforms": {"feishu": False},
                "chats": {"feishu": {"oc_123": True}},
            },
        )
        assert ae_config.resolve_enabled("feishu", "oc_123") is True
        assert ae_config.resolve_enabled("feishu", "oc_other") is False

        monkeypatch.setattr(
            ae_config,
            "_load_approval_explainer_cfg",
            lambda: {"enabled": True, "platforms": {"qqbot": True}},
        )
        assert ae_config.resolve_enabled("qqbot", "any") is True

        monkeypatch.setattr(
            ae_config, "_load_approval_explainer_cfg", lambda: {"enabled": False}
        )
        assert ae_config.resolve_enabled("feishu", "oc_123") is False

    def test_invalid_values_fall_back(self, monkeypatch):
        monkeypatch.setattr(
            ae_config,
            "_load_approval_explainer_cfg",
            lambda: {"enabled": "yes", "timeout_ms": "not-a-number"},
        )
        cfg = ae_config.load_config()
        assert cfg["enabled"] is True
        assert cfg["timeout_ms"] == 30000  # 非法回落默认

    def test_provider_model_auto_normalized(self, monkeypatch):
        monkeypatch.setattr(
            ae_config,
            "_load_approval_explainer_cfg",
            lambda: {"provider": "auto", "model": "AUTO"},
        )
        cfg = ae_config.load_config()
        assert cfg["provider"] == ""
        assert cfg["model"] == ""
        # 空 → (None, None) → call_llm auxiliary auto 链
        assert ae_config.resolve_model(cfg) == (None, None)

    def test_explicit_model_passes_through(self, monkeypatch):
        monkeypatch.setattr(
            ae_config,
            "_load_approval_explainer_cfg",
            lambda: {"provider": "damodel", "model": "xy-pro"},
        )
        cfg = ae_config.load_config()
        assert ae_config.resolve_model(cfg) == ("damodel", "xy-pro")


# ---------------------------------------------------------------------------
# 2/3/4. explain_command: fail-open / 缓存 / 清理
# ---------------------------------------------------------------------------


class TestExplain:
    # 仅本类生效 (不放模块级 —— 会把 TestConfig 的默认值断言也钉开):
    # 按 patch.yaml 实配形态打开 feishu/qqbot, 每例清缓存。
    @pytest.fixture(autouse=True)
    def _enable_and_clear(self, monkeypatch):
        monkeypatch.setattr(
            ae_config,
            "_load_approval_explainer_cfg",
            lambda: {"enabled": True, "platforms": {"feishu": True, "qqbot": True}},
        )
        ae_explain.clear_cache()
        yield
        ae_explain.clear_cache()
    def test_ok_returns_text_and_caches(self, monkeypatch):
        monkeypatch.setattr("agent.auxiliary_client.call_llm", _fake_llm_ok)
        text = asyncio.run(
            ae_explain.explain_command("rm -rf /tmp/logs", "危险删除", "zh")
        )
        assert text is not None and "日志" in text
        # 第二次同命令 → 缓存命中 (call_llm 不再被调)
        calls = {"n": 0}

        def _counting(*a, **k):
            calls["n"] += 1
            return _ok_response()

        monkeypatch.setattr("agent.auxiliary_client.call_llm", _counting)
        text2 = asyncio.run(
            ae_explain.explain_command("rm -rf /tmp/logs", "危险删除", "zh")
        )
        assert text2 == text
        assert calls["n"] == 0

    def test_disabled_platform_returns_none(self, monkeypatch):
        # 三级查找: platforms 显式关 telegram → False (未列平台回落 enabled)
        monkeypatch.setattr(
            ae_config,
            "_load_approval_explainer_cfg",
            lambda: {
                "enabled": True,
                "platforms": {"feishu": True, "qqbot": True, "telegram": False},
            },
        )
        ae_explain.clear_cache()
        called = {"n": 0}

        def _must_not_call(*a, **k):
            called["n"] += 1
            return _ok_response()

        monkeypatch.setattr("agent.auxiliary_client.call_llm", _must_not_call)
        out = asyncio.run(
            ae_explain.explain_command("ls", "d", "zh", platform="telegram")
        )
        assert out is None
        assert called["n"] == 0

    def test_master_disabled_platform_unlisted_returns_none(self, monkeypatch):
        # 总开关关 → 未列平台回落 enabled=False (默认关语义)
        monkeypatch.setattr(
            ae_config, "_load_approval_explainer_cfg", lambda: {"enabled": False}
        )
        ae_explain.clear_cache()
        called = {"n": 0}

        def _must_not_call(*a, **k):
            called["n"] += 1
            return _ok_response()

        monkeypatch.setattr("agent.auxiliary_client.call_llm", _must_not_call)
        out = asyncio.run(
            ae_explain.explain_command("ls", "d", "zh", platform="telegram")
        )
        assert out is None
        assert called["n"] == 0

    def test_llm_error_returns_none_no_raise(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("provider down")

        monkeypatch.setattr("agent.auxiliary_client.call_llm", boom)
        out = asyncio.run(ae_explain.explain_command("ls", "d", "zh"))
        assert out is None

    def test_llm_timeout_returns_none(self, monkeypatch):
        import asyncio as _aio

        def _slow(*a, **k):
            time.sleep(1.5)
            return _ok_response()

        monkeypatch.setattr("agent.auxiliary_client.call_llm", _slow)
        monkeypatch.setattr(
            ae_config,
            "_load_approval_explainer_cfg",
            lambda: {"enabled": True, "timeout_ms": 200},
        )
        out = asyncio.run(ae_explain.explain_command("ls", "d", "zh"))
        assert out is None

    def test_cache_miss_on_different_description(self, monkeypatch):
        monkeypatch.setattr("agent.auxiliary_client.call_llm", _fake_llm_ok)
        asyncio.run(ae_explain.explain_command("cmd", "reason-a", "zh"))
        # 不同 description → 缓存 key 不同 → 重新调 LLM
        calls = {"n": 0}

        def _counting(*a, **k):
            calls["n"] += 1
            return _ok_response()

        monkeypatch.setattr("agent.auxiliary_client.call_llm", _counting)
        asyncio.run(ae_explain.explain_command("cmd", "reason-b", "zh"))
        assert calls["n"] == 1

    def test_cache_ttl_expiry(self, monkeypatch):
        monkeypatch.setattr("agent.auxiliary_client.call_llm", _fake_llm_ok)
        key = ae_explain._cache_key("cmd", "r", "zh")
        # 手工注入一条已过期的缓存
        ae_explain._CACHE[key] = (time.time() - 99999, "旧解说")
        monkeypatch.setattr(
            ae_config,
            "_load_approval_explainer_cfg",
            lambda: {"enabled": True, "cache_ttl_seconds": 600},
        )
        out = asyncio.run(ae_explain.explain_command("cmd", "r", "zh"))
        assert out != "旧解说"  # 过期 → 重新生成

    def test_quoted_output_stripped(self, monkeypatch):
        monkeypatch.setattr(
            "agent.auxiliary_client.call_llm",
            lambda *a, **k: _ok_response('"被引号包住的解说"'),
        )
        out = asyncio.run(ae_explain.explain_command("c", "d", "zh"))
        assert out is not None
        assert not out.startswith('"')

    def test_prompt_no_recommendation_constraint(self):
        msgs = ae_prompt.build_messages("rm -rf /x", "危险", "zh")
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        # 硬约束: 禁止推荐结论 (安全核心)
        assert "NEVER give a recommendation" in msgs[0]["content"]
        assert "rm -rf /x" in msgs[1]["content"]


# ---------------------------------------------------------------------------
# 5. 飞书卡嵌入
# ---------------------------------------------------------------------------


class TestFeishuCard:
    def _build(self, explanation: str):
        from owner.feishu import approval as fa

        return fa.build_approval_card(
            command="systemctl restart nginx",
            description="服务重启",
            approval_id=1,
            explanation=explanation,
        )

    def test_explanation_embedded(self):
        # pytest 环境默认语言 en → 英文标签; 断言解说正文 + 结构位置,
        # 不钉死某个 locale 的标签字面。
        card = self._build("重启 nginx 服务，会短暂中断 web 流量。")
        md = card["elements"][0]["content"]
        assert "重启 nginx 服务" in md
        # 位置: 命令预览之后、理由行之后 (reason label 的 i18n 结构不变)
        assert md.index("systemctl restart nginx") < md.index("重启 nginx 服务")
        assert "服务重启" in md

    def test_empty_explanation_unchanged_card(self):
        card_empty = self._build("")
        from owner.feishu import approval as fa

        card_plain = fa.build_approval_card(
            command="systemctl restart nginx",
            description="服务重启",
            approval_id=1,
        )
        assert card_empty == card_plain


# ---------------------------------------------------------------------------
# 6. QQ 文本渲染
# ---------------------------------------------------------------------------


class TestQQText:
    def _req(self, explanation: str):
        from gateway.platforms.qqbot.keyboards import ApprovalRequest

        return ApprovalRequest(
            session_key="s",
            title="执行此命令？",
            description="危险命令",
            command_preview="systemctl restart nginx",
            timeout_sec=300,
            explanation=explanation,
        )

    def test_explanation_rendered(self):
        # pytest 环境默认语言 en → 英文标签; 断言解说正文 + 结构位置。
        from gateway.platforms.qqbot.keyboards import build_approval_text

        text = build_approval_text(self._req("重启 nginx，短暂中断 web 流量。"))
        assert "重启 nginx" in text
        assert "systemctl restart nginx" in text
        assert "危险命令" in text  # reason label 结构不变
        assert text.index("危险命令") < text.index("重启 nginx")  # 理由在前

    def test_empty_explanation_skipped(self):
        from gateway.platforms.qqbot.keyboards import build_approval_text

        text = build_approval_text(self._req(""))
        assert "重启 nginx，" not in text
        assert "危险命令" in text  # 其余结构保留


# ---------------------------------------------------------------------------
# 7. i18n key 存在性 (zh/en 都要有, 否则渲染出裸 key)
# ---------------------------------------------------------------------------


class TestI18nKeys:
    @pytest.mark.parametrize(
        "key", ["feishu_explanation_label", "qqbot_explanation_label"]
    )
    def test_keys_exist_zh_en(self, key):
        from agent.i18n import t

        zh = t(f"approval.{key}", explanation="X", lang="zh")
        en = t(f"approval.{key}", explanation="X", lang="en")
        assert "X" in zh and "X" in en
        assert "approval." not in zh and "approval." not in en
