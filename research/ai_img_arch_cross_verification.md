# Phase 4: Cross-Verification — AI Agent 图片生成架构图工作流调研

## 验证方法
基于 8 个深度调研维度（Dim01–Dim08）和 6 个广泛探索维度（Wide01–Wide06）的交叉比对，所有发现按置信度四级分类。

---

## High Confidence（≥2个独立维度确认，来源权威）

| # | 发现 | 确认维度 | 关键来源 |
|---|------|----------|----------|
| 1 | **Qwen-Image 在中文文本渲染上领先开源模型**（LongText-Bench-ZH 0.946，GPT-Image-1 仅 0.619，FLUX.1-dev 仅 0.007） | Dim01, Dim02, Dim04, Wide01, Wide02 | Qwen-Image Technical Report 2025; NTIRE 2025 |
| 2 | **ERNIE-Image 8B 是消费级 24GB 显存最佳本地部署方案**（全精度可运行，Apache 2.0，文本渲染 >0.96） | Dim01, Dim04, Wide01 | ERNIE-Image GitHub; Miraflow.ai 评测 2026.04 |
| 3 | **FLUX.1-dev 中文文本渲染几乎不可用**（LongText-Bench-ZH 0.005） | Dim01, Dim02, Dim04, Wide01 | Black Forest Labs 官方; 多项独立评测 |
| 4 | **ControlNet 在保持几何结构的同时会破坏中文文本**（MiniText-Benchmark Sen.Acc 仅 0.0006） | Dim04, Dim06, Wide02 | ControlNet 社区实测; ComfyUI 论坛 |
| 5 | **Diagram-as-Code + 扩散模型混合工作流优于纯扩散模型**（IJCAI 2024 论文验证） | Dim03, Dim07, Wide03 | IJCAI 2024 论文; ArchitectureDiagram.ai 实践 |
| 6 | **Dify + ComfyUI 是当前主流工作流编排方案**（分层架构：Dify 编排 + ComfyUI 执行） | Dim02, Dim04, Dim05, Wide04 | Dify 官方文档; 开发者社区案例 |
| 7 | **扩散模型天生不擅精确几何布局**（需 ControlNet/T2I-Adapter/CtrLoRA 等条件控制） | Dim04, Dim05, Dim07, Wide05 | LACE 论文; GeoSVG-RL 论文; LayoutDM |
| 8 | **GLM-Image 在 LongText-ZH 上达 0.9788，开源第一**（MIT 许可，CPU offload 23GB） | Dim01, Dim08, Wide01 | GLM-Image 技术报告; Hugging Face |
| 9 | **Qwen-Image 2.0（7B）统一生成与编辑，原生 2K，支持 PPT/信息图** | Dim02, Dim05, Wide02 | Qwen-Image 2.0 发布说明; ModelScope |
| 10 | **企业级部署需三层安全审核**（中国《生成式人工智能服务管理暂行办法》） | Dim08, Wide06 | 国家网信办; 广州互联网法院判例 |
| 11 | **boardmix 中文架构图语义理解最强，ProcessOn 次之** | Dim03, Wide03 | boardmix 官方; 开发者横评 |
| 12 | **API 调用成本可低至 $0.0012/张**（Z-Image Turbo / 豆包 Seedream），本地 8 卡 H100 3 年 TCO $231 万 | Dim01, Dim08, Wide06 | 各平台官方定价页; 企业部署报告 |

---

## Medium Confidence（单一权威来源确认）

| # | 发现 | 确认维度 | 关键来源 |
|---|------|----------|----------|
| 1 | **Qwen-Image-Edit 支持链式编辑，保留原字体/字号/风格**（AICoding→AIAgent 精准无误） | Dim02 | Qwen-Image Edit 官方文档 |
| 2 | **FLUX.1 Kontext 3–5 秒/图，多轮一致性较好，但超过 6 轮出现伪影** | Dim02 | FLUX.1 Kontext 技术报告 |
| 3 | **Cruderra 扫描代码库生成架构图，理念先进但 SaaS 未开放** | Dim03 | Cruderra 官网 |
| 4 | **GenFix Pipeline 后处理有效但非万能——2 轮迭代为最佳，超 64% 失败源于修复阶段仍生成错误文本** | Dim06 | GenFix 论文 |
| 5 | **PaddleOCR v4 中文识别准确率 85–86%**（server 模型），但艺术化/小字 AI 生成文本需额外预处理 | Dim06 | PaddleOCR 官方 |
| 6 | **GitDiagram 实现 GitHub 仓库→交互架构图自动转换，支持中文** | Dim07 | GitDiagram 官方 |
| 7 | **混合部署（敏感本地 + 通用云端）可降本 40%** | Dim08 | 企业部署报告 |
| 8 | **Dify 1.13.0 新增人工介入节点**，支持工作流中途暂停+审核 | Dim05 | Dify 更新日志 |

---

## Low Confidence（弱来源或单一未验证声明）

| # | 发现 | 确认维度 | 关键来源 | 降级原因 |
|---|------|----------|----------|----------|
| 1 | **Z-Image Turbo 6B 为成本最优 API 方案**（$0.01/张，0.936 LongText-ZH） | Dim01, Dim08 | 聚合平台定价 | 平台定价波动，未验证实际生成质量 |
| 2 | **Ovis-Image 7B 在多区域（2–5 区域）文本上达 92% WA** | Dim01 | 社区评测 | 缺乏独立复现 |
| 3 | **ComfyUI-NKD-Klein-Tools 的 Match Original Colors + Seamless Edges 可解决 Inpainting 中文漂移** | Dim02 | GitHub 社区插件 | 未经过系统评测 |
| 4 | **Vectorizer.AI 对 AI 生成图像矢量化效果良好** | Dim07 | 开发者博客 | 无定量评测数据 |
| 5 | **未来 6–12 个月 API 成本可能降至当前 1/10** | Dim08 | 行业趋势分析 | 预测性声明，无硬数据支撑 |

---

## Conflict Zone（维度间存在分歧或时间不一致）

### 冲突 1: 最佳模型选择因场景而异
- **Dim01**（文生图）推荐：ERNIE-Image 8B（本地）/ Z-Image Turbo（API）
- **Dim02**（图生图/编辑）推荐：Qwen-Image 2.0（编辑能力最强）
- **Dim04**（ControlNet 兼容）推荐：ERNIE-Image（原生布局可控，无需 ControlNet）
- **分析**：这不是真正的数据冲突，而是**场景分化**。文生图优先文本精度 → GLM-Image/ERNIE-Image；编辑优先编辑能力 → Qwen-Image 2.0；批量优先成本 → Z-Image/豆包。

### 冲突 2: 后处理方案 vs 规避后处理的方案
- **Dim06** 认为：后处理 pipeline（OCR→修复）是可行的兜底方案，GenFix 可提升 20–30% OCR F1
- **Dim07** 认为：对精确架构图，最优方案是"扩散模型生成底图 + LLM 生成布局 + 确定性渲染引擎合成文本"，完全规避后处理
- **分析**：两者不是互斥，而是**不同精度要求下的不同策略**。如果允许 95%+ 准确率即可，混合渲染引擎最优；如果要求 99%+ 或需批量处理，后处理 pipeline 是必要补充。

### 冲突 3: API 定价数据的时间差异
- **Dim01** 引用 Qwen-Image $0.005–0.02/张
- **Dim08** 引用最便宜至 $0.0012/张（豆包 Seedream）
- **分析**：不同平台、不同时间、不同套餐的定价差异。建议以调研时点（2026-06）各平台官方定价为准，并注意波动。

---

## 验证结论

- **无需要 Phase 5 额外验证的硬冲突**。所有表面冲突均为场景差异或方法论差异。
- **High Confidence 发现共 12 条**，构成了本调研的核心事实基础。
- **Medium Confidence 发现共 8 条**，需在实际部署中进一步验证。
- **Low Confidence 发现共 5 条**，作为参考方向，不构成决策依据。
