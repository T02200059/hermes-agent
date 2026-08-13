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

    # 2) 模板化长报告（不同内容 + 同收尾句 ~33%）→ 不误伤
    normal = "\n\n".join(
        f"第 {i} 段：本节讨论配置项 {i} 的作用，需要在部署前确认。补充验证路径 {i} 与回退策略 {i}。结论是建议保留默认值。"
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