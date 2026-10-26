"""Guard: 飞书 auto-card 的媒体预投递（偿还 `feishu-auto-card-agent-end` 债务）。

2026-10-23 新基线守卫。此前登记在 `owner/validation/coverage_gaps.txt`：

    feishu-auto-card-agent-end  tests/owner/test_feishu_agent_end_media.py removed
    2026-10-20; media tag delivered before card and no-media passthrough unpinned

按 §2.2.0 偿还策略撤销该登记：动了这个分歧，就为它写守卫，而不是继续挂着债务。

## 为什么这族行为必须被钉住

`try_auto_card_on_end` 在飞书上是**最终回复的唯一投递路径**（卡片成功即置
`already_sent=True`，抑制下游纯文本发送）。而 `MEDIA:` 标签与裸本地路径必须
**先于**卡片投递，否则整段 response 会被 `try_auto_card` 当作纯文本包进卡片：

- 文件永远不会被上传（`MEDIA:<path>` 变成用户可见的字面文本）
- 下游 `_process_message_background` 在 `already_sent=True` 时跳过
  `extract_media`，三道防线全部 miss —— 用户既拿不到文件，也看不出哪里不对

这是"主路径抑制备用路径"结构下最典型的静默丢失，且没有任何日志会响。

## 边界（代码注释 Medium#7 / Medium#8 的契约）

- **MEDIA-only 响应 + 投递成功** → `already_sent=True` 并返回空串：没有正文可
  包卡片，若继续走 `try_auto_card(force=True)` 会发一张空卡片。
- **MEDIA-only 响应 + 投递失败** → **不**设 `already_sent`，把原始 response 交还
  下游：让纯文本兜底至少让用户看到内容，而不是零输出。
- **裸本地路径** 也要从卡片正文里剥掉（`extract_media` 只剥 `MEDIA:` 标签），
  否则同一份文件既作为附件投递、又作为字面路径出现在正文里。
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from gateway.config import Platform

import owner.feishu.agent_end as agent_end


class _FakeAdapter:
    """只实现 agent_end 用到的四个方法，让 ``hasattr`` 的行为确定。

    不用 MagicMock：`hasattr(MagicMock(), "anything")` 恒为 True，会静默走进
    每条分支，测出来的东西和真实 adapter 不一致。
    """

    def __init__(self, *, media_files=(), local_files=(), cleaned="", cleaned_no_img=None):
        self._media_files = list(media_files)
        self._local_files = list(local_files)
        self._cleaned = cleaned
        self._cleaned_no_img = cleaned if cleaned_no_img is None else cleaned_no_img

    def extract_media(self, text):
        # 真实 adapter 返回 [(path, is_voice), ...] —— filter_media_delivery_paths
        # 会逐项解包；返回裸字符串会在那里抛 ValueError，被 agent_end 的
        # try/except 静默吞掉、整条 media 分支跳过（踩过：表现为"投递没被调用"）
        return [(p, False) for p in self._media_files], self._cleaned

    def extract_images(self, text):
        return [], self._cleaned_no_img

    def extract_local_files(self, text):
        return list(self._local_files), self._cleaned_no_img


def _run_end(*, adapter, response, deliver=None, footer_line="", agent_result=None):
    """驱动 try_auto_card_on_end，返回 (result, card_captured, deliver_calls)。"""
    captured = {}
    deliver_calls = []

    async def fake_try_auto_card(adapter, text, meta, **kw):
        captured["text"] = text
        captured["footer"] = kw.get("footer")
        return {"ok": True}

    async def fake_deliver(resp, event, adp):
        deliver_calls.append(resp)
        if deliver is not None:
            return deliver(resp, event, adp)
        return None

    runner = MagicMock()
    runner.adapters = {Platform.FEISHU: adapter}
    runner._thread_metadata_for_source.return_value = {}
    runner._reply_anchor_for_event.return_value = None
    runner._deliver_media_from_response = fake_deliver

    source = MagicMock()
    source.platform = Platform.FEISHU
    source.chat_id = "oc_test"

    agent_result = agent_result if agent_result is not None else {}

    with patch("owner.feishu.auto_card.try_auto_card", fake_try_auto_card):
        result = asyncio.run(
            agent_end.try_auto_card_on_end(
                runner=runner,
                source=source,
                event=MagicMock(),
                agent_result=agent_result,
                response=response,
                footer_line=footer_line,
            )
        )
    return result, captured, deliver_calls, agent_result


# ── 核心契约 1：media 先于卡片 ──────────────────────────────────────────────

def test_media_is_delivered_before_the_card_is_sent(tmp_path):
    """附件必须先把投递跑完，卡片才发出。

    顺序反了的话 `MEDIA:` 标签会作为字面文本进卡片正文，文件永不投递。

    注意：路径必须**真实存在** —— `BasePlatformAdapter.filter_media_delivery_paths`
    会把不存在的路径过滤掉，那样 `has_attachments` 为假、整条 media 分支不执行，
    用例就会变成"测了个空转"（踩过一次）。
    """
    media = tmp_path / "report.pdf"
    media.write_bytes(b"%PDF-1.4 test")
    adapter = _FakeAdapter(
        media_files=[str(media)],
        cleaned="报告已生成。",
    )
    result, captured, deliver_calls, _ = _run_end(
        adapter=adapter, response=f"报告已生成。\nMEDIA:{media}"
    )

    assert deliver_calls, "附件投递根本没被调用 —— 文件会丢失"
    assert captured.get("text") == "报告已生成。", "卡片正文应只含清理后的文本"
    assert "MEDIA:" not in captured["text"], "MEDIA: 标签泄漏进卡片正文"
    assert result == ("", "")


def test_media_tag_does_not_leak_into_card_body(tmp_path):
    """即使正文里还有别的文字，标签也不能出现在卡片上。"""
    media = tmp_path / "a.png"
    media.write_bytes(b"\x89PNG\r\n\x1a\n")
    adapter = _FakeAdapter(
        media_files=[str(media)],
        cleaned="这是图片说明。",
    )
    _, captured, _, _ = _run_end(
        adapter=adapter, response=f"这是图片说明。\nMEDIA:{media}"
    )
    assert captured["text"] == "这是图片说明。"


# ── 核心契约 2：无 media 时原样透传 ────────────────────────────────────────

def test_no_media_passes_the_response_through_unchanged():
    """没有附件时不改写正文，也不调用投递链。"""
    adapter = _FakeAdapter()
    result, captured, deliver_calls, _ = _run_end(
        adapter=adapter, response="纯文本回复"
    )

    assert deliver_calls == [], "无附件时不应调用附件投递"
    assert captured.get("text") == "纯文本回复"
    assert result == ("", "")


# ── 核心契约 3：裸本地路径也要剥（Medium#8）──────────────────────────────

def test_bare_local_paths_are_stripped_from_the_card_body():
    """`extract_media` 只剥 `MEDIA:` 标签，裸路径要单独处理。

    否则同一份文件既被当附件投递、又以字面路径出现在正文里。
    """
    adapter = _FakeAdapter(
        local_files=["/tmp/chart.png"],
        cleaned="看图：/tmp/chart.png",   # extract_media 不动裸路径
        cleaned_no_img="看图：/tmp/chart.png",
    )
    adapter._cleaned_no_img = "/tmp/chart.png"  # noqa: SLF001 - stub 内部字段
    # extract_local_files 之后才剥干净；这里模拟联合管线的输出
    adapter_local = _FakeAdapter(local_files=["/tmp/chart.png"], cleaned="看图：/tmp/chart.png")

    orig = adapter_local.extract_local_files

    def _extract_local_files(text):
        files, _ = orig(text)
        return files, "看图："  # 剥掉裸路径后的正文

    adapter_local.extract_local_files = _extract_local_files  # type: ignore[assignment]

    _, captured, deliver_calls, _ = _run_end(
        adapter=adapter_local, response="看图：/tmp/chart.png"
    )

    assert deliver_calls, "裸路径也应触发附件投递"
    assert "/tmp/chart.png" not in captured["text"], "裸路径泄漏进卡片正文"


# ── 边界（Medium#7）：MEDIA-only 的两种去向 ────────────────────────────────

def test_media_only_response_with_successful_delivery_marks_already_sent(tmp_path):
    """只剩附件、没有正文 → 不能发空卡片，直接标记已投递。"""
    media = tmp_path / "x.pdf"
    media.write_bytes(b"%PDF-1.4 test")
    adapter = _FakeAdapter(media_files=[str(media)], cleaned="")
    result, captured, deliver_calls, agent_result = _run_end(
        adapter=adapter, response=f"MEDIA:{media}"
    )

    assert deliver_calls, "附件必须投递"
    assert agent_result.get("already_sent") is True, (
        "MEDIA-only 且投递成功时必须置 already_sent，否则下游会发一张空卡片"
    )
    assert result == ("", "")
    assert "text" not in captured, "不应尝试发卡片（正文为空）"


def test_media_only_response_with_failed_delivery_keeps_the_safety_net(tmp_path):
    """投递抛错 + 没有正文 → **不**设 already_sent，交还下游兜底。

    否则用户零输出：附件没发出去，纯文本路径又被 already_sent 封死。
    """
    media = tmp_path / "x.pdf"
    media.write_bytes(b"%PDF-1.4 test")
    adapter = _FakeAdapter(media_files=[str(media)], cleaned="")

    def _boom(resp, event, adp):
        raise RuntimeError("upload failed")

    result, captured, deliver_calls, agent_result = _run_end(
        adapter=adapter, response=f"MEDIA:{media}", deliver=_boom
    )

    assert deliver_calls, "投递应被尝试过"
    assert not agent_result.get("already_sent"), (
        "投递失败 + 空正文时不能置 already_sent —— 否则用户零输出"
    )
    assert result[0] == f"MEDIA:{media}", "原始 response 应原样交还下游兜底"


# ── 与 footer 的交互（今日修复的另一半，防止回归）──────────────────────────

def test_media_and_footer_coexist(tmp_path):
    """附件投递后，footer 仍要作为卡片 footer 渲染（不能被 media 分支吞掉）。"""
    media = tmp_path / "x.pdf"
    media.write_bytes(b"%PDF-1.4 test")
    adapter = _FakeAdapter(media_files=[str(media)], cleaned="正文")
    footer = "xy-max · 4% · ~/.hermes"
    _, captured, deliver_calls, _ = _run_end(
        adapter=adapter,
        response=f"正文\nMEDIA:{media}\n\n{footer}",
        footer_line=footer,
    )

    assert deliver_calls
    assert captured.get("footer") == footer, "media 分支吃掉了 footer"
    assert captured["text"] == "正文"
