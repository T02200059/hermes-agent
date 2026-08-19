"""[owner] output_guard — transform_llm_output 钩子：复读/乱码/超长检测与折叠。

背景
----
2026-08-12 `ark-agent-plan-deepseek-v4-flash` 在 git 推送确认场景陷入复读
死循环，单条输出 265,518 字符刷屏（见 owner/docs/output-guard-design.md）。
`model.max_tokens` 已在 API 层兜住膨胀，本模块做第二道防线：在响应发送给用户
**之前**（transform_llm_output 钩子，agent/turn_finalizer.py:556）识别退化输出
（复读 / 低信息 / 乱码 / 超长），折叠或截断并附警告标注。

契约
----
- 钩子返回非空字符串 → 整体替换最终响应（gateway 发送最终版）
- 返回 None → 保持原样（fail-safe：任何异常都回退 None，不影响主流程）
- 纯 stdlib、O(n)、微秒~毫秒级，不影响回复延迟

设计文档：owner/docs/output-guard-design.md
"""

from __future__ import annotations

import logging
import re
import zlib

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 阈值（多信号防误伤，详见设计文档 §判定）
# ---------------------------------------------------------------------------
# 低于此长度的响应不做任何判定（正常回复一般为 100~2000 token）
_MIN_CHARS = 3000
# 复读判定：top-1 句（归一化后）最少重复次数
_TOP_REPEAT_MIN_COUNT = 5
# 复读判定：top-1 句占比下限（事故形态占比 >95%；模板化长报告每段同收尾句
# 约 25~35%、半模板列表约 50%，均须排除 → 0.60）
_TOP_REPEAT_MIN_RATIO = 0.60
# 低信息判定：独有句占比上限（配合 top_count 门槛）
_UNIQUE_SENT_MIN_RATIO = 0.30
# 低信息兜底：zlib 压缩率上限（纯复读 <0.05，模板化长报告 ~0.15 → 取 0.08）
_COMPRESS_MAX_RATIO = 0.08
# 乱码判定：U+FFFD 替换符占比上限
_MOJIBAKE_MAX_RATIO = 0.005
# 长度护栏：超过此字符数且未触发其他判定时截断
_MAX_CHARS = 50000

# 中文/英文句子边界：句号、问号、感叹号、分号 + 换行
_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;])\s*|\n+")
# 归一化用：剥离空白与非单词字符（含中文标点）
_NORM_STRIP = re.compile(r"[\s\W_]+")
# 段落边界（折叠去重用）
_PARA_SPLIT = re.compile(r"\n\s*\n")


def _normalize(s: str) -> str:
    """剥离空白/标点，仅用于比较句段是否重复。"""
    return _NORM_STRIP.sub("", s)


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]


def analyze(text: str) -> dict:
    """统计输出信号并给出判定。

    verdict ∈ {"ok", "repeat", "mojibake", "too_long"}
    """
    n = len(text)
    out: dict = {
        "chars": n,
        "verdict": "ok",
        "comp_ratio": 1.0,
        "fffd_ratio": 0.0,
        "sentence_count": 0,
        "top_count": 0,
        "top_ratio": 0.0,
        "unique_ratio": 1.0,
    }

    try:
        # Compression ratio in BYTES (utf-8), not characters: CJK chars are
        # 3 bytes each, so a char-based denominator inflated the ratio ~3x
        # for Chinese and made the comp_belt signal nearly useless there
        # (P2-2). Byte/byte is language-neutral.
        _encoded_len = len(text.encode("utf-8", "replace"))
        out["comp_ratio"] = len(zlib.compress(text.encode("utf-8", "replace"))) / max(_encoded_len, 1)
    except Exception:
        pass
    out["fffd_ratio"] = text.count("\ufffd") / max(n, 1)

    sents = _split_sentences(text)
    if sents:
        out["sentence_count"] = len(sents)
        counter: dict[str, int] = {}
        for s in sents:
            k = _normalize(s)
            if k:
                counter[k] = counter.get(k, 0) + 1
        if counter:
            top, top_cnt = max(counter.items(), key=lambda kv: kv[1])
            out["top_sentence"] = top[:40]
            out["top_count"] = top_cnt
            out["top_ratio"] = top_cnt / len(sents)
            out["unique_ratio"] = len(counter) / len(sents)

    # 乱码信号不依赖长度：任何长度的文本都检测（短消息也可能乱码）
    if out["fffd_ratio"] > _MOJIBAKE_MAX_RATIO:
        out["verdict"] = "mojibake"
        return out

    if n < _MIN_CHARS:
        return out

    # 复读 / 低信息（多信号，防误伤）
    top_enough = out["top_count"] >= _TOP_REPEAT_MIN_COUNT
    repeat = top_enough and out["top_ratio"] >= _TOP_REPEAT_MIN_RATIO
    low_info = top_enough and out["unique_ratio"] < _UNIQUE_SENT_MIN_RATIO
    comp_belt = out["comp_ratio"] < _COMPRESS_MAX_RATIO and out["sentence_count"] >= 10
    if repeat or low_info or comp_belt:
        out["verdict"] = "repeat"
        return out

    if n > _MAX_CHARS:
        out["verdict"] = "too_long"
    return out


def _fold_paragraphs(text: str) -> str:
    """段落级去重（保留首现），复读刷屏 → 一份完整信息。

    丢弃行为：正文与代码块中的重复段落会被去掉；首现顺序保持不变。
    """
    seen: set[str] = set()
    kept: list[str] = []
    for p in _PARA_SPLIT.split(text):
        p = p.strip()
        if not p:
            continue
        k = _normalize(p)
        if k in seen:
            continue
        seen.add(k)
        kept.append(p)
    return "\n\n".join(kept)


def _build_note(verdict: str, sig: dict, model: str, folded_len: int) -> str:
    if verdict == "mojibake":
        detail = (
            f"疑似乱码（U+FFFD 替换符占比 {sig['fffd_ratio']:.2%}），"
            f"已折叠重复内容；原始 {sig['chars']} 字符 → {folded_len} 字符"
        )
    elif verdict == "too_long":
        detail = (
            f"输出超长（{sig['chars']} 字符 > {_MAX_CHARS}），已截断；"
            f"模型 {model}"
        )
    else:  # repeat / low_info / comp_belt
        detail = (
            f"复读/低信息（top 句 「{sig.get('top_sentence', '?')}」 重复 "
            f"{sig.get('top_count', 0)} 次，占比 {sig.get('top_ratio', 0):.0%}；"
            f"压缩率 {sig['comp_ratio']:.2f}），已去重折叠；"
            f"原始 {sig['chars']} 字符 → {folded_len} 字符；模型 {model}"
        )
    return (
        "\n\n---\n"
        f"⚠️ [output-guard] 检测到输出异常已修正：{detail}\n"
        "如非预期，请重试或换模型。"
    )


def _on_transform_llm_output(
    response_text: str,
    session_id: str = "",
    model: str = "",
    platform: str = "",
    **kwargs,
):
    """transform_llm_output 钩子 handler。返回 None 保持原样，返回 str 替换。"""
    if not response_text or not isinstance(response_text, str):
        return None
    try:
        sig = analyze(response_text)
        if sig["verdict"] == "ok":
            return None

        if sig["verdict"] == "too_long":
            folded = response_text[:_MAX_CHARS]
        else:
            folded = _fold_paragraphs(response_text)
            # [owner-patch P2-3] Paragraph folding only splits on blank lines;
            # single-\n-separated repeat loops (the 265k-char incident shape)
            # collapse to one giant paragraph and folding changes nothing.
            # Second-stage guard: hard-truncate anything still over budget so
            # the screen-flood is always bounded.
            if len(folded) > _MAX_CHARS:
                folded = folded[:_MAX_CHARS]

        note = _build_note(sig["verdict"], sig, model, len(folded))
        logger.warning(
            "output_guard %s session=%s model=%s chars=%s→%s top_count=%s top_ratio=%.2f comp=%.2f fffd=%.4f",
            sig["verdict"], session_id, model or "-", sig["chars"], len(folded),
            sig.get("top_count", 0), sig.get("top_ratio", 0.0),
            sig["comp_ratio"], sig["fffd_ratio"],
        )
        return folded + note
    except Exception:
        # fail-safe：任何异常都不破坏原始响应
        logger.exception("output_guard transform failed")
        return None


def register_hooks(ctx) -> None:
    """由 owner-extensions 聚合调用。"""
    ctx.register_hook("transform_llm_output", _on_transform_llm_output)
    logger.debug("output_guard: transform_llm_output hook registered")