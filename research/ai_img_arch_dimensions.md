# Phase 2: 维度分解

基于 Phase 1W 广泛探索（6个维度），分解为以下8个深度调研维度：

## Dim01: 中文文生图模型技术对比与架构图适用性
- **范围**：GLM-Image、ERNIE-Image、Qwen-Image、Ovis-Image、Z-Image等在中文架构图标签生成方面的实测对比
- **角度**：模型架构差异、文本渲染准确率（ChineseWord/LongText-Bench）、硬件要求、部署成本、开源许可
- **相关文件**：ai_img_arch_wide01.md（文生图模型）、ai_img_arch_wide05.md（中文排版技术）
- **重点**：哪类模型最适合架构图的中文短标签生成？量化对中文小字的影响？

## Dim02: 图生图与迭代编辑工作流
- **范围**：FLUX.1 Kontext、Qwen-Image编辑、ComfyUI img2img、Inpainting、局部重绘在架构图修改中的实际效果
- **角度**：编辑精度、中文文本保持、迭代效率、多轮编辑工作流设计
- **相关文件**：ai_img_arch_wide02.md（图生图编辑）、ai_img_arch_wide04.md（工作流编排）
- **重点**：修改架构图时如何保持已有中文不畸变？最佳迭代工作流是什么？

## Dim03: AI架构图专用工具深度评测
- **范围**：DiagramGPT、Eraser、Mermaid AI、Claude SVG、PlantUML GPT、ArchitectureDiagram.ai、boardmix等
- **角度**：中文支持、输出格式（SVG/drawio/PNG）、可编辑性、精确度、与扩散模型对比
- **相关文件**：ai_img_arch_wide03.md（专用工具）、ai_img_arch_wide05.md（SVG/矢量技术）
- **重点**：专用工具 vs 通用扩散模型，哪个更适合架构图？中文场景谁更强？

## Dim04: ControlNet与几何结构保持技术
- **范围**：Canny/LineArt/Depth/MLSD/Scribble在架构图生成中的应用，Multi-ControlNet叠加
- **角度**：结构保真度、几何精度、与扩散模型结合的工作流、中文文本保持
- **相关文件**：ai_img_arch_wide02.md（ControlNet）、ai_img_arch_wide05.md（几何精度）
- **重点**：ControlNet能否让扩散模型生成精确的架构图？中文文本会受影响吗？

## Dim05: Dify/Coze低代码工作流搭建实践
- **范围**：Dify、Coze、飞书多维表格、ComfyUI实际搭建文生图/图生图工作流
- **角度**：易用性、节点配置、模型接入、条件分支、批量生成、Agent自主调用
- **相关文件**：ai_img_arch_wide04.md（工作流编排）、ai_img_arch_wide06.md（企业应用）
- **重点**：如何零代码搭建一个完整的架构图生成工作流？最佳实践？

## Dim06: 中文文本后处理与排版修正技术
- **范围**：OCR检测文本错误、GenFix、PaddleOCR、排版引擎修正、字体替换、AnyText等
- **角度**：架构图场景适用性、与扩散模型生成的结合方案、准确率提升效果
- **相关文件**：ai_img_arch_wide05.md（中文排版）、ai_img_arch_wide01.md（文本渲染）
- **重点**：生成后如何自动修正中文文本错误？最佳后处理pipeline？

## Dim07: SVG矢量图生成与混合工作流
- **范围**：Mermaid/D2/PlantUML→SVG、LLM生成SVG（LLM4SVG/StarVector）、代码到图表（Cruderra/GitDiagram）
- **角度**：可编辑性优势、与扩散模型美化结合的混合方案、中文排版支持
- **相关文件**：ai_img_arch_wide03.md（专用工具）、ai_img_arch_wide05.md（SVG技术）
- **重点**：Diagram-as-Code + AI美化的混合工作流是否最优？中文支持如何？

## Dim08: 企业级部署与成本优化
- **范围**：API调用（各平台定价）、本地部署（GPU要求）、混合部署、质量评估、安全合规
- **角度**：不同规模企业最优方案、成本效益分析、TC260合规、版权风险
- **相关文件**：ai_img_arch_wide06.md（企业应用）、ai_img_arch_wide01.md（部署成本）
- **重点**：中小型互联网公司应该选择什么方案？成本和质量如何平衡？
