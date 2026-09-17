"""[owner] output_guard — transform_llm_output 钩子：复读/乱码/超长检测与折叠。

背景
----
2026-08-12 `ark-agent-plan-deepseek-v4-flash` 在 git 推送确认场景陷入复读
死循环，单条输出 265,518 字符刷屏（见 owner/docs/output-guard-design.md）。
`model.max_tokens` 已在 API 层兜住膨胀，本模块做第二道防线：在响应发送给用户
**之前**（transform_llm_output 钩子）识别退化输出
（复读 / 低信息 / 乱码 / 超长），折叠或截断并附警告标注。

2026-09-17 增补（C1/C2/C3，见 owner/docs/degenerate-stream-guard-design.md §5）
------------------------------------------------------------------------
- **C1** 钩子调用不再带 `not interrupted` 门槛（`agent/turn_finalizer.py`）。
  失控生成的典型结局就是被人工打断，原门槛让护栏恰在最需要时失效。
- **C2** 钩子与 transcript 尾行回写前移到 `_persist_session` 之前，落库即为
  干净文本（原先只改内存，state.db 保留退化原文并在下次会话加载时二次污染）。
- **C3** 新增 `reasoning_text` 入参：思考通道单独扫描。当正文健康而思考退化
  （纯 thinking 循环）时**保留正文**、只追加告警注解，不替换正文。

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

# --- v2: 生成退化（degenerate）判定（2026-09-01 乱码事故形态）---
# 实测：事故本体 dirty_run=5 / word_repeat=2；合法引用 run=1 / 0。
_DEGENERATE_MIN_CHARS = 400
_BLOCK_SIZE = 200
_DIRTY_RUN_MIN = 3
_WORD_REPEAT = re.compile(r"(\S+)( \1){5,}")
_TEMPLATE_MARKERS = ("<|im_end|>", "<|im_start|>", "[/CoT]")
_JUNK_PATTERNS = (
    re.compile(r"</div>\.{2,}"),
    re.compile(r"(</){3,}"),
    re.compile(r"\\end\{g"),
)

# --- C3: reasoning（思考）通道扫描（2026-09-17）---
# 思考天然比正文长，且合法思考里出现重复短语是常态，因此只在「远超正常思考
# 长度 + 命中退化形态」时才判定。门槛取 8000 字符（正常长思考 ~2–6K）。
# 今日事故（msg 108360）的 reasoning_content 为 NULL，属纯 content 退化——
# 本通道是为 thinking-heavy provider（Claude thinking / DeepSeek v4 /
# GLM thinking）未来"正文健康但思考空转"的形态补盲，而非复现今日样本。
_REASONING_MIN_CHARS = 8000

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


def _block_score(block: str) -> int:
    """单块（_BLOCK_SIZE 字符）内模板标记 + 乱码模式命中数。"""
    hits = sum(block.count(m) for m in _TEMPLATE_MARKERS)
    hits += sum(len(p.findall(block)) for p in _JUNK_PATTERNS)
    return hits


def _degenerate_scan(text: str) -> dict:
    """v2 信号扫描：dirty_run / word_repeat / first_offense（最早信号位置）。"""
    n = len(text)
    scores = [_block_score(text[i : i + _BLOCK_SIZE]) for i in range(0, n, _BLOCK_SIZE)]
    run = best = 0
    first_dirty = None
    for idx, s in enumerate(scores):
        run = run + 1 if s > 0 else 0
        best = best if best >= run else run
        if s > 0 and first_dirty is None:
            first_dirty = idx * _BLOCK_SIZE
    rep = _WORD_REPEAT.search(text)
    offenses = [p for p in (first_dirty, rep.start() if rep else None) if p is not None]
    return {
        "dirty_run": best,
        "word_repeat": 1 if rep else 0,
        "first_offense": min(offenses) if offenses else None,
    }


def analyze(text: str) -> dict:
    """统计输出信号并给出判定。

    verdict ∈ {"ok", "repeat", "mojibake", "too_long", "degenerate"}
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

    # v2 生成退化判定（先于 v1：模板标记泄漏/复读循环门槛更低，任何
    # ≥ _DEGENERATE_MIN_CHARS 的文本都扫，避免被 _MIN_CHARS 早返回吞掉）
    if n >= _DEGENERATE_MIN_CHARS:
        _scan = _degenerate_scan(text)
        if _scan["dirty_run"] >= _DIRTY_RUN_MIN or _scan["word_repeat"] >= 1:
            out["verdict"] = "degenerate"
            out.update(_scan)
            return out

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


def _scan_reasoning(text: str) -> dict | None:
    """C3：思考通道扫描。

    返回信号 dict（命中退化）或 None（未达门槛 / 形态正常）。思考文本从不被
    替换或截断 —— 它不直接面向用户，只有正文才需要裁剪；本函数只负责"发现
    并报告"，动作由调用方决定。
    """
    if not isinstance(text, str) or len(text) < _REASONING_MIN_CHARS:
        return None
    try:
        sig = analyze(text)
    except Exception:
        logger.exception("output_guard reasoning scan failed")
        return None
    if sig.get("verdict") in ("degenerate", "repeat"):
        return sig
    return None


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
            f"已保留首段；原始 {sig['chars']} 字符 → {folded_len} 字符"
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


def _reasoning_note(sig: dict) -> str:
    """C3：思考通道退化时的告警后缀（正文始终保留）。"""
    return (
        "\n\n---\n"
        f"⚠️ [output-guard] 思考通道检测到退化（{sig.get('verdict')}，"
        f"{sig.get('chars')} 字符，压缩率 {sig.get('comp_ratio', 1.0):.2f}）："
        "正文已保留，但本轮推理过程不可信，建议重新提问或换模型。"
    )


def _on_transform_llm_output(
    response_text: str,
    session_id: str = "",
    model: str = "",
    platform: str = "",
    reasoning_text: str = "",
    interrupted: bool = False,
    **kwargs,
):
    """transform_llm_output 钩子 handler。返回 None 保持原样，返回 str 替换。

    C1：调用方已不再用 ``not interrupted`` 过滤本钩子 —— 被中断的轮次恰恰是
        失控生成的主场，必须照样判定。
    C3：``reasoning_text`` 是思考通道。正文健康而思考退化时只追加注解、不替换
        正文（思考不面向用户，裁剪它没有意义）。
    """
    if not response_text or not isinstance(response_text, str):
        return None
    try:
        _rsig = _scan_reasoning(reasoning_text or "")
        sig = analyze(response_text)
        if sig["verdict"] == "ok":
            if _rsig is None:
                return None
            # 正文正常、思考退化：只报告，不裁剪。
            logger.warning(
                "output_guard reasoning-degenerate session=%s model=%s "
                "interrupted=%s reason_chars=%s reason_verdict=%s "
                "top_count=%s top_ratio=%.2f comp=%.2f",
                session_id, model or "-", bool(interrupted),
                _rsig.get("chars"), _rsig.get("verdict"),
                _rsig.get("top_count", 0), _rsig.get("top_ratio", 0.0),
                _rsig.get("comp_ratio", 1.0),
            )
            return response_text + _reasoning_note(_rsig)

        # 正文判定非 ok。思考通道的退化若同时存在，用后缀一并说明（正文动作
        # 仍由上面的 verdict 决定）。
        _reason_suffix = ""
        if _rsig is not None:
            logger.warning(
                "output_guard reasoning-degenerate (alongside %s) session=%s "
                "model=%s reason_chars=%s reason_verdict=%s",
                sig["verdict"], session_id, model or "-",
                _rsig.get("chars"), _rsig.get("verdict"),
            )
            _reason_suffix = _reasoning_note(_rsig)

        if sig["verdict"] == "degenerate":
            cut = sig.get("first_offense")
            if cut is None or cut < 50:
                cut = 50
            kept = response_text[:cut].rstrip()
            logger.warning(
                "output_guard degenerate session=%s model=%s interrupted=%s "
                "chars=%s→%s dirty_run=%s word_repeat=%s first_offense=%s",
                session_id, model or "-", bool(interrupted),
                sig["chars"], len(kept),
                sig.get("dirty_run"), sig.get("word_repeat"), sig.get("first_offense"),
            )
            return (
                kept
                + "\n\n---\n[output-guard] 检测到生成退化（模板标记泄漏/复读循环），"
                "已截断后续内容。本次输出不可信，建议让我重新生成。"
                + ("（本轮生成已被中止。）" if interrupted else "")
                + _reason_suffix
            )

        if sig["verdict"] == "too_long":
            folded = response_text[:_MAX_CHARS]
        elif sig["verdict"] == "mojibake":
            # Keep the first paragraph only — folding does not remove U+FFFD,
            # so "已保留首段" must be the actual behaviour (P2-3).
            first = _PARA_SPLIT.split(response_text, maxsplit=1)[0].strip()
            folded = first or response_text
            if len(folded) > min(_MAX_CHARS, 2000):
                folded = folded[: min(_MAX_CHARS, 2000)]
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
        return folded + note + _reason_suffix
    except Exception:
        # fail-safe：任何异常都不破坏原始响应
        logger.exception("output_guard transform failed")
        return None


def register_hooks(ctx) -> None:
    """由 owner-extensions 聚合调用。"""
    ctx.register_hook("transform_llm_output", _on_transform_llm_output)
    logger.debug("output_guard: transform_llm_output hook registered")