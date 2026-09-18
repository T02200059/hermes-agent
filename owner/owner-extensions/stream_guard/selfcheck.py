"""stream_guard 离线自检 —— 不联网、不依赖进程内 agent 或 sqlite。

用法：
    python owner/owner-extensions/stream_guard/selfcheck.py

覆盖：
1. 合成"阶段边界循环"（S1+S2 投票）必须命中；
2. 合成"纯复读"（S3 单独成立）必须命中；
3. 变化度充分的正常长文必须不命中；
4. 若存在真实事故样本（samples/ 已 gitignore），回放并报告命中位置；
5. 阈值余量报告：各信号的实测值与阈值对比。

真实事故样本与全库长回复的完整标定见 owner/docs/degenerate-stream-guard-design.md
§6（8 条正例全命中 / 318 条正常长回复 0 误伤）。
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
# 仓库根必须进 sys.path：`python path/to/selfcheck.py` 时 sys.path[0] 是脚本
# 所在目录，而 S3 依赖官方 `agent.repetition_guard`。不补这一条，该 import 会
# 静默失败（被 evaluate_window 的 fail-open 吞掉），S3 恒为 0、"纯复读"用例
# 永久漏判 —— 本脚本曾在仓库根执行时报 AssertionError，正是这个原因。
_REPO_ROOT = _HERE.parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_WINDOW = 4096
_STEP = 512


def _load():
    spec = importlib.util.spec_from_file_location("owner_stream_guard_selfcheck", _HERE / "__init__.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["owner_stream_guard_selfcheck"] = mod
    spec.loader.exec_module(mod)
    return mod


def _first_trip(mod, text: str, cfg: dict):
    """滑动窗口找首个 trip（返回 (offset, signals) 或 None）。"""
    n = len(text)
    for start in range(0, max(n - 1, 0), _STEP):
        buf = text[start:start + _WINDOW]
        if len(buf) < cfg["min_stream_chars"]:
            break
        sig = mod.evaluate_window(buf, cfg)
        if sig["trip"]:
            return start, sig
    return None


def main() -> int:
    # S3 依赖官方 repetition_guard；一旦导入不可用，"纯复读"这一类会永久漏判，
    # 因此这里显式报错而不是静默降级（静默降级正是本脚本此前的缺陷）。
    try:
        from agent.repetition_guard import is_repetition_dominated  # noqa: F401
    except Exception as exc:
        raise SystemExit(
            f"stream_guard selfcheck: 无法导入 agent.repetition_guard（{exc}）；"
            " 请在仓库根执行本脚本"
        )

    mod = _load()
    cfg = dict(mod.DEFAULTS)
    cfg["window_chars"] = _WINDOW
    cfg["eval_interval_chars"] = _STEP

    loop_text = "DONE THINKING. WRITING RESPONSE. ฅ^•ﻌ•^ฅ\n" * 200
    repeat_text = "call\n\n" * 600
    # 变化度充分的正常长文（同一句重复 N 次本身就是复读形态，不能当负样本）
    normal_text = "".join(
        tpl.format(i=i)
        for i in range(1, 26)
        for tpl in (
            "部署前需要确认配置项 {i} 的默认值与目标环境一致，避免灰度期行为漂移。",
            "第 {i} 节说明参数 {i} 与上游服务的交互协议与超时重试取值依据。",
            "关于开关 {i}：默认关闭，灰度放量后按批次逐步启用，回滚时逆序关闭。",
            "依赖项 {i} 已在上一轮巡检中确认健康，本轮仅需在发布单登记版本号。",
            "回滚预案 {i} 沿用上一版本的快照恢复流程，恢复窗口不超过十五分钟。",
            "告警规则 {i} 的静默窗口已与值班同学核对，覆盖周末与节假日高峰。",
            "配额项 {i} 与账单口径已对齐，历史误差控制在千分之三以内。",
            "监控面板 {i} 新增三个分位指标，用于观察长尾请求对时延的贡献。",
        )
    )

    # 1) 阶段边界循环 → S1 + S2 投票
    hit = _first_trip(mod, loop_text, cfg)
    assert hit, "合成边界循环未命中"
    _off, sig_loop = hit
    assert sig_loop["s1_marker_rate"] >= cfg["marker_rate_per_kb"], sig_loop
    assert sig_loop["s2_signature_multiple"] >= cfg["signature_rate_multiple"], sig_loop
    assert sig_loop["votes"] >= cfg["vote_threshold"], sig_loop

    # 2) 纯复读 → 仅 S3，靠 s3_solo 触发
    hit = _first_trip(mod, repeat_text, cfg)
    assert hit, "合成纯复读未命中"
    _off, sig_rep = hit
    assert sig_rep["s3_no_progress"] == 1, sig_rep
    assert sig_rep["s1_marker_rate"] == 0.0 and sig_rep["s2_signature_multiple"] == 0.0, sig_rep

    # 3) 正常长文 → 零命中
    assert _first_trip(mod, normal_text, cfg) is None, "正常长文被误伤"

    # 4) 真实事故样本（可选）
    incident_report = "（未找到样本：samples/ 已 gitignore）"
    sample = _HERE / "samples" / "incident_9_17_thinking_loop.txt"
    if sample.exists():
        text = sample.read_text(encoding="utf-8")
        hit = _first_trip(mod, text, cfg)
        assert hit, "2026-09-17 事故样本未命中"
        off, sig = hit
        incident_report = (
            f"chars={len(text)} 首个命中窗口 @{off} ({off / len(text):.0%}) "
            f"s1={sig['s1_marker_rate']}/KB s2=x{sig['s2_signature_multiple']} "
            f"s3={sig['s3_no_progress']} votes={sig['votes']}"
        )

    print("stream_guard selfcheck: 全部通过 ✓")
    print(f"  阈值：S1>={cfg['marker_rate_per_kb']}/KB  S2>=x{cfg['signature_rate_multiple']}  "
          f"投票>={cfg['vote_threshold']}  S3 单独成立={cfg['s3_solo']}")
    print(f"  合成边界循环：s1={sig_loop['s1_marker_rate']}/KB s2=x{sig_loop['s2_signature_multiple']} "
          f"votes={sig_loop['votes']}")
    print(f"  合成纯复读：  s3={sig_rep['s3_no_progress']} votes={sig_rep['votes']}（s3_solo 触发）")
    print(f"  正常长文：    未命中（{len(normal_text)} 字符）")
    print(f"  真实事故回放：{incident_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
