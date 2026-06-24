# Plan: AI Agent 图片生成领域架构图工作流调研

## 任务目标
调研在 AI Agent 图片生成领域，适合做**图生图、文生图、改图**的工作流，**侧重于互联网行业的架构图绘制**，关注**中文文本质量与架构图排版**。

## 时间锚点
2026-06-23

## 执行路线
Route A（Wide Search）— 无文件上传，广泛探索性话题

## 阶段规划

### Stage 1: Phase 1W — 多Agent广泛探索（6个维度）
- **维度1**: 文生图基础模型与中文文本渲染能力（SD/Flux/Qwen-Image/ERNIE-Image等）
- **维度2**: 图生图与图像编辑工作流（ComfyUI、FLUX Kontext、局部重绘等）
- **维度3**: AI架构图专用生成工具（DiagramGPT、Mermaid、Eraser、PlantUML等）
- **维度4**: 工作流编排平台与Agent集成（Dify、ComfyUI、飞书多维表格、Coze等）
- **维度5**: 中文排版与架构图可视化技术（CJK文本渲染、SVG生成、矢量图输出）
- **维度6**: 企业级应用场景与商业化方案（成本、效率、质量对比）

### Stage 2: Phase 2 — 维度分解（基于广泛探索结果）
- 从Stage 1输出中提取主题，细化≥10个深度维度

### Stage 3: Phase 3 — 并行深度调研
- 每个维度部署一个 explore agent 进行深度调研

### Stage 4: Phase 4-6 — 交叉验证与洞察提取
- 汇总所有维度输出，进行交叉验证，提取洞察

### Stage 5: Phase 7 — 报告撰写
- 使用 report-writing 技能撰写最终调研报告
- 最终输出 .docx 格式

## 技能加载
- Stage 1-4: deep-research-swarm（已加载）
- Stage 5: report-writing + docx

## 输出目录
`/Users/yangtb/.hermes/hermes-agent/research/`
