"""Tests for owner ``session_salt`` — API 会话 id 派生用的服务端盐（T2-8）。

设计约束见 ``owner/gateway/session_salt.py`` 模块 docstring 与
``owner/docs/owner改动清单.md`` §16.5。

覆盖:
  1. 优先级: env > config > 生成文件；空白与过短一律不当作「已配置」
  2. 生成: 落盘 HERMES_HOME/api_session_salt，权限 0600，跨进程/重启稳定
  3. 缓存: 同进程多次调用取同一值；reset 后按来源重新解析并归因
  4. 降级: 既有文件过短 → 不覆盖、不使用，改进程内盐并告警
  5. 降级: 无法落盘 / 无 HERMES_HOME → 仍返回非空盐，不上抛
  6. 端到端: 换盐 → 派生 id 变；同盐 → 碰撞依旧（盐不解决碰撞，显式钉住）
  7. 回落: owner/ 缺席时 api_server 仍用裸摘要，形状不变
"""

from __future__ import annotations

import hashlib
import logging
import os
import stat
from pathlib import Path

import pytest

from gateway.platforms import api_server as api_server_module
from owner.gateway import session_salt as ss

_HOME = lambda: Path(os.environ["HERMES_HOME"])  # noqa: E731 - 用例里读当前沙箱 home
_FLAT = lambda text: " ".join(text.split())  # noqa: E731


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """Env 与模块缓存都要清干净。

    ``HERMES_API_SESSION_SALT`` 不在 conftest 的凭证后缀表内（它结尾是 ``_SALT``），
    因此开发机 shell 里导出的同名变量会漏进用例 —— 这里显式删掉，用例各自按需设置。
    """
    monkeypatch.delenv(ss.ENV_VAR, raising=False)
    ss.reset_session_salt_cache()
    yield
    ss.reset_session_salt_cache()


# ---------------------------------------------------------------------------
# 1. 优先级
# ---------------------------------------------------------------------------


class TestPrecedence:
    def test_env_wins_and_does_not_touch_the_disk(self, monkeypatch):
        monkeypatch.setenv(ss.ENV_VAR, "e" * 32)
        ss.reset_session_salt_cache()

        assert ss.api_session_salt() == "e" * 32
        assert ss.session_salt_source() == "env"
        assert not (_HOME() / ss.FILE_NAME).exists(), "显式配置时不应再生成文件"

    def test_config_is_read_from_the_documented_key(self, monkeypatch):
        """真实走 ``gateway.api_server.session_salt`` 的取值路径，而不是打桩内部函数。"""
        from hermes_cli import config as hermes_config

        monkeypatch.setattr(
            hermes_config,
            "load_config",
            lambda *a, **k: {"gateway": {"api_server": {"session_salt": "c" * 24}}},
        )
        ss.reset_session_salt_cache()

        assert ss.api_session_salt() == "c" * 24
        assert ss.session_salt_source() == "config"

    def test_env_beats_config(self, monkeypatch):
        from hermes_cli import config as hermes_config

        monkeypatch.setattr(
            hermes_config,
            "load_config",
            lambda *a, **k: {"gateway": {"api_server": {"session_salt": "c" * 24}}},
        )
        monkeypatch.setenv(ss.ENV_VAR, "e" * 32)
        ss.reset_session_salt_cache()

        assert ss.api_session_salt() == "e" * 32

    def test_a_short_env_value_is_ignored_rather_than_trusted(self, monkeypatch, caplog):
        """占位符（如 ``changeme``）最坏的不是弱，而是**读起来像已配置**。"""
        monkeypatch.setenv(ss.ENV_VAR, "changeme")
        ss.reset_session_salt_cache()

        with caplog.at_level(logging.WARNING):
            salt = ss.api_session_salt()

        assert salt != "changeme"
        assert len(salt) >= ss.MIN_SALT_CHARS
        assert ss.session_salt_source() == "generated"
        assert ss.ENV_VAR in caplog.text and "below the" in caplog.text

    def test_blank_env_falls_through(self, monkeypatch):
        monkeypatch.setenv(ss.ENV_VAR, "   ")
        ss.reset_session_salt_cache()

        assert len(ss.api_session_salt()) >= ss.MIN_SALT_CHARS
        assert ss.session_salt_source() == "generated"


# ---------------------------------------------------------------------------
# 2. 生成与落盘
# ---------------------------------------------------------------------------


class TestGeneratedSecret:
    def test_generation_persists_a_0600_secret(self, monkeypatch):
        monkeypatch.delenv(ss.ENV_VAR, raising=False)
        ss.reset_session_salt_cache()

        salt = ss.api_session_salt()
        path = _HOME() / ss.FILE_NAME

        assert path.exists()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.read_text(encoding="utf-8").strip() == salt
        assert len(salt) >= ss.MIN_SALT_CHARS
        assert ss.session_salt_source() == "generated"

    def test_no_temp_file_is_left_behind(self, monkeypatch):
        monkeypatch.delenv(ss.ENV_VAR, raising=False)
        ss.reset_session_salt_cache()
        ss.api_session_salt()

        leftovers = [p.name for p in _HOME().iterdir() if p.name.startswith(f".{ss.FILE_NAME}")]
        assert leftovers == [], "原子写用的暂存文件必须清掉"

    def test_the_secret_survives_a_cache_reset(self, monkeypatch):
        """缓存重置等价于进程重启：落盘的盐必须让派生会话连续性活过一次重启。"""
        monkeypatch.delenv(ss.ENV_VAR, raising=False)
        ss.reset_session_salt_cache()
        first = ss.api_session_salt()

        ss.reset_session_salt_cache()  # 模拟重启后重新解析

        assert ss.api_session_salt() == first
        assert ss.session_salt_source() == "file", "第二阶段是从文件读到的，不再是新生成"


# ---------------------------------------------------------------------------
# 3/4/5. 降级路径
# ---------------------------------------------------------------------------


class TestDegradation:
    def test_a_short_existing_secret_is_neither_used_nor_overwritten(self, monkeypatch, caplog):
        """别人写的文件不是我们的文件：既不能信，也不能覆盖。"""
        monkeypatch.delenv(ss.ENV_VAR, raising=False)
        path = _HOME() / ss.FILE_NAME
        path.write_text("tiny\n", encoding="utf-8")
        ss.reset_session_salt_cache()

        with caplog.at_level(logging.ERROR):
            salt = ss.api_session_salt()

        assert salt != "tiny"
        assert len(salt) >= ss.MIN_SALT_CHARS
        assert path.read_text(encoding="utf-8") == "tiny\n", "不得覆盖操作者写的文件"
        assert ss.session_salt_source() == "degraded"
        assert ss.FILE_NAME in caplog.text

    def test_an_unwritable_secret_degrades_and_names_the_way_out(self, monkeypatch, caplog):
        monkeypatch.delenv(ss.ENV_VAR, raising=False)
        monkeypatch.setattr(ss, "_write_secret_file", lambda path, value: False)
        ss.reset_session_salt_cache()

        with caplog.at_level(logging.ERROR):
            salt = ss.api_session_salt()

        assert len(salt) >= ss.MIN_SALT_CHARS
        assert ss.session_salt_source() == "degraded"
        assert ss.ENV_VAR in caplog.text, "告警必须点名可用的出路，否则只是噪音"

    def test_a_missing_hermes_home_degrades_instead_of_raising(self, monkeypatch):
        monkeypatch.delenv(ss.ENV_VAR, raising=False)
        monkeypatch.setattr(ss, "_salt_file", lambda: None)
        ss.reset_session_salt_cache()

        salt = ss.api_session_salt()

        assert len(salt) >= ss.MIN_SALT_CHARS
        assert ss.session_salt_source() == "degraded"

    def test_degraded_secrets_are_per_process_not_fixed(self, monkeypatch):
        """降级的代价要看得见：换一次解析就是另一个盐（=重启后派生 id 会变）。"""
        monkeypatch.delenv(ss.ENV_VAR, raising=False)
        monkeypatch.setattr(ss, "_write_secret_file", lambda path, value: False)

        ss.reset_session_salt_cache()
        first = ss.api_session_salt()
        ss.reset_session_salt_cache()
        second = ss.api_session_salt()

        assert first != second
        assert ss.session_salt_source() == "degraded"

    def test_the_degraded_notice_is_not_repeated_on_the_request_path(self, monkeypatch, caplog):
        """每请求路径上不能反复刷同一条 ERROR。

        「只发一次」是**结构性**的：``_degrade`` 必定记忆化自己的结果，之后每次调用
        都在缓存处提前返回。所以本用例咬住的是「缓存必须挡住后续调用」—— 把那个
        提前返回删掉，它会红；而一个额外的 ``already-warned`` 布尔量在这里是够不
        着的死代码，已于实现侧移除。
        """
        monkeypatch.delenv(ss.ENV_VAR, raising=False)
        monkeypatch.setattr(ss, "_write_secret_file", lambda path, value: False)
        ss.reset_session_salt_cache()

        with caplog.at_level(logging.ERROR):
            first = ss.api_session_salt()
            for _ in range(5):
                assert ss.api_session_salt() == first

        notices = [r for r in caplog.records if "per-process session-id salt" in r.message]
        assert len(notices) == 1


# ---------------------------------------------------------------------------
# 6/7. 端到端：派生 id
# ---------------------------------------------------------------------------


class TestDerivedSessionIdIsKeyed:
    """`_derive_chat_session_id` 的带盐行为 —— T2-8 的验收项。"""

    def test_different_salt_yields_a_different_id(self, monkeypatch):
        """同输入换盐 → 不同 id：这就是「离线推导不可复现」的可测形式。"""
        monkeypatch.setattr(api_server_module, "_owner_session_salt", lambda: "salt-one")
        one = api_server_module._derive_chat_session_id("sys", "hello")
        monkeypatch.setattr(api_server_module, "_owner_session_salt", lambda: "salt-two")
        two = api_server_module._derive_chat_session_id("sys", "hello")

        assert one != two

    def test_env_salt_changes_the_id_end_to_end(self, monkeypatch):
        """走真实链路（env → owner 模块 → HMAC），不只打桩内部函数。"""
        monkeypatch.setenv(ss.ENV_VAR, "s" * 32)
        ss.reset_session_salt_cache()
        keyed = api_server_module._derive_chat_session_id("sys", "hello")

        bare = "api-" + hashlib.sha256(b"sys\nhello").hexdigest()[:16]
        assert keyed != bare, "带盐后不得等于内容的裸 sha256"

        monkeypatch.setenv(ss.ENV_VAR, "t" * 32)
        ss.reset_session_salt_cache()
        assert api_server_module._derive_chat_session_id("sys", "hello") != keyed

    def test_the_same_salt_still_collides_on_identical_inputs(self, monkeypatch):
        """盐不解决碰撞 —— 这一条是**显式记录的边界**，不是通过。

        盐是整个部署共享的，因此同系统提示词 + 同首条消息仍得同一 id（同容器
        内两用户即共享会话）。拆开它们需要一个本模块没有的「按身份」维度，
        §16.5 把它记为未闭合的边界。若某天真的按身份隔离了，本用例会红 ——
        那正是提醒去更新记录的信号。
        """
        monkeypatch.setenv(ss.ENV_VAR, "s" * 32)
        ss.reset_session_salt_cache()

        assert api_server_module._derive_chat_session_id("sys", "hello") == (
            api_server_module._derive_chat_session_id("sys", "hello")
        )

    def test_without_the_owner_module_the_bare_digest_is_the_fallback(self, monkeypatch):
        """owner/ 缺席（upstream sync）→ 回落裸摘要，且形状与带盐时一致。"""
        monkeypatch.setattr(api_server_module, "_owner_session_salt", lambda: "")
        unkeyed = api_server_module._derive_chat_session_id("sys", "hello")

        monkeypatch.setattr(api_server_module, "_owner_session_salt", lambda: "salt-one")
        keyed = api_server_module._derive_chat_session_id("sys", "hello")

        assert unkeyed != keyed
        assert len(unkeyed) == len(keyed) == len("api-") + 16

    def test_the_id_shape_is_unchanged(self):
        """形状是下游契约：派生 id 会落进磁盘产物名与响应头（§16.5）。"""
        body = api_server_module._derive_chat_session_id("sys", "hello")[len("api-"):]

        assert len(body) == 16
        assert all(ch in "0123456789abcdef" for ch in body)


# ---------------------------------------------------------------------------
# 归因
# ---------------------------------------------------------------------------


class TestAttribution:
    @pytest.mark.parametrize(
        ("setup", "expected"),
        [
            ("env", "env"),
            ("file", "file"),
            ("generated", "generated"),
            ("degraded", "degraded"),
        ],
    )
    def test_the_source_is_attributable(self, monkeypatch, setup, expected):
        """一个布尔值式的「盐是什么」必须能归因，否则会被读错（同 §15.7 的教训）。"""
        if setup == "env":
            monkeypatch.setenv(ss.ENV_VAR, "e" * 32)
        elif setup == "file":
            # 文件已在：本次是**读**到的，与首次生成的归因不同。
            (_HOME() / ss.FILE_NAME).write_text("p" * 32 + "\n", encoding="utf-8")
        elif setup == "degraded":
            monkeypatch.setattr(ss, "_write_secret_file", lambda path, value: False)
        ss.reset_session_salt_cache()

        ss.api_session_salt()

        assert ss.session_salt_source() == expected

    def test_source_is_safe_to_ask_before_any_use(self):
        assert ss.session_salt_source() in {
            "env",
            "config",
            "file",
            "generated",
            "degraded",
            "unresolved",
        }


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
