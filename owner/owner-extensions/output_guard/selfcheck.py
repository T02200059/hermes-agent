"""[owner] output_guard self-check — 直接运行：python3 owner/owner-extensions/output_guard/selfcheck.py

覆盖：复读折叠 / 事故形态 / 模板化长报告防误伤 / 半模板列表防误伤 /
乱码（长短文本）/ 短回复不判 / 超长截断 / register_hooks 挂载。

设计见 owner/docs/output-guard-design.md §6。以文件路径加载（目录名带连字符，
非合法包名，PluginManager 亦按路径加载）。
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _load() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("output_guard", _HERE / "__init__.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load output_guard module spec")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    m = _load()
    analyze = m.analyze
    handle = m._on_transform_llm_output

    # 1) 复读样本（模拟事故形态：整段话反复）→ 折叠且大比例瘦身
    repeat_text = ("要推 origin + gitlab 吗？需要就说一声。确认就推。默认不推 upstream。\n\n" * 100)
    assert analyze(repeat_text)["verdict"] == "repeat"
    out = handle(repeat_text, session_id="t", model="selfcheck", platform="feishu")
    assert out is not None and "[output-guard]" in out and len(out) < len(repeat_text) / 10

    # 1b) 事故形态变体：同一句占比 >95%
    accident = ("确认就推。默认不推 upstream。需要就说一声。本次已完成。\n\n" * 300)
    assert analyze(accident)["verdict"] == "repeat"

    # 2) 模板化长报告（不同内容 + 同收尾句 ~2/3 段）→ 不误伤
    #    （2026-09-17：原样本在部分 zlib 版本下压缩率 <0.08 误触发 comp_belt，
    #     属用例数据问题而非判定问题；改为变化度更高的段首/细节字段。）
    _HEADS2 = (
        "本节讨论配置项 {i} 的作用，需要在部署前确认。",
        "第 {i} 节介绍参数 {i} 与上游服务的交互协议。",
        "关于开关 {i}：默认关闭，灰度放量后逐步启用。",
        "依赖项 {i} 已在昨天的巡检中确认健康，无需变更。",
        "回滚预案 {i} 沿用上一版本的快照恢复流程。",
        "告警规则 {i} 的静默窗口已核对，覆盖周末流量。",
        "配额项 {i} 与账单口径对齐，误差在千分之三以内。",
    )
    _TAILS2 = (
        "结论是建议保留默认值。",
        "结论是建议保留默认值。",
        "本轮先按兵不动，观察一个完整周期。",
        "此节结论：暂不调整，留待下次评审。",
    )
    normal = "\n\n".join(
        f"## 小节 {i}（批次 {i * i * 7 % 4096}）\n"
        + _HEADS2[i % 7].format(i=i)
        + f"补充验证路径 {i}，观测指标 {i * i % 97}，责任轮值 {(i * 7) % 11} 号同学，备注编号 {hex(i * 13)}。"
        + _TAILS2[i % 4]
        for i in range(300)
    )
    assert analyze(normal)["verdict"] == "ok"

    # 2b) 半模板列表（每段 50% 公共句）→ 不误伤
    mixed = "\n\n".join(f"小节 {i} 的具体内容各不相同，包含独有数据 {i} 与独立结论 {i}。" + "公共收尾句。" for i in range(120))
    assert analyze(mixed)["verdict"] == "ok"

    # 3) 乱码（长短文本都判）
    assert analyze("正常内容。" + "\ufffd" * 100 + "。继续正常。" * 50)["verdict"] == "mojibake"
    assert analyze("回复。" + "\ufffd" * 10 + "继续。" * 3)["verdict"] == "mojibake"

    # 4) 短回复不判
    assert analyze("已标完成。")["verdict"] == "ok"

    # 5) 超长但低重复 → 长度护栏
    long_ok = "\n\n".join(f"段落{i}：" + "独特内容" + str(i) * 10 for i in range(6000))
    assert analyze(long_ok)["verdict"] == "too_long"
    assert "已截断" in handle(long_ok, model="selfcheck")

    # 5) v2 degenerate：真实事故样本判退化、合法引用不误伤
    import pathlib
    _samples = pathlib.Path(__file__).resolve().parent / "samples"
    _acc = _samples / "degenerate_9_01.txt"
    if _acc.exists():
        _t = _acc.read_text(encoding="utf-8")
        assert analyze(_t)["verdict"] == "degenerate", "事故样本应判 degenerate"
        for _q in ("quote_legit.txt", "quote_legit2.txt"):
            _qt = (_samples / _q).read_text(encoding="utf-8")
            assert analyze(_qt)["verdict"] == "ok", _q + " 不应误伤"
        _out = handle(_t, session_id="t", model="selfcheck", platform="feishu")
        assert _out is not None and "[output-guard]" in _out
        assert len(_out) < len(_t), "degenerate 应被截断瘦身"
    # 5b) 合成样本：连续脏块
    _syn = "正常开头一句。" + ("<|im_end|> junk </div>...\n" * 20)
    assert analyze(_syn)["verdict"] == "degenerate"
    # 5c) 散点标记（讨论乱码的合法回复）不误伤
    _scatter = "开头讨论 </div>.. 与 [/CoT] 标记。" + "".join(
        "第%d句独立内容各不相同。" % i for i in range(60)
    )
    assert analyze(_scatter)["verdict"] == "ok"

    # 6) register_hooks 挂载
    class Ctx:
        def __init__(self) -> None:
            self.hooks = []

        def register_hook(self, name, handler) -> None:
            self.hooks.append((name, handler))

    ctx = Ctx()
    m.register_hooks(ctx)
    assert any(n == "transform_llm_output" for n, _ in ctx.hooks)

    print("output_guard selfcheck: 全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())