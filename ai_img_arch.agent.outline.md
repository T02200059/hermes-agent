# AI Agent 图片生成架构图工作流调研报告

## 1. 执行摘要与技术全景（~1500字，1个表格）
### 1.1 调研背景与目标
#### 1.1.1 AI Agent 图片生成领域的三大工作流类型：文生图、图生图、改图
#### 1.1.2 互联网行业架构图绘制的特殊需求：精确几何、中文文本、专业排版、可编辑性
### 1.2 技术全景概览
#### 1.2.1 当前 AI 图片生成技术栈分层：基础模型层、条件控制层、工作流编排层、应用层
#### 1.2.2 架构图生成领域的四大技术路线：纯扩散模型、Diagram-as-Code、专用工具、混合工作流
#### 1.2.3 中文文本渲染能力是架构图生成的核心瓶颈（表格：各模型中文文本基准对比）

## 2. 文生图工作流：模型选择与中文文本渲染（~2000字，2个表格）
### 2.1 主流文生图模型中文能力对比
#### 2.1.1 第一梯队：GLM-Image（0.9788）、ERNIE-Image（>0.96）、Qwen-Image（0.946）——开源中文文本渲染领军者
#### 2.1.2 第二梯队：Z-Image（0.936）、Ovis-Image（0.964）——性价比与轻量选择
#### 2.1.3 不可用梯队：FLUX.1-dev（0.005）、DALL-E、Midjourney——中文文本渲染几近为零
#### 2.1.4 模型选择矩阵：按场景（文生图/编辑/批量/本地）推荐最优模型（表格：模型×场景×成本）
### 2.2 中文文本渲染的技术瓶颈与解决方案
#### 2.2.1 根本瓶颈：BPE tokenization 使模型"看不到"单个汉字，字符级编码可提升 OCR 准确率 42.1%
#### 2.2.2 量化压缩对中文小字的隐性破坏：FP8 质量损失 1.56 倍，INT4/NF4 小字易模糊
#### 2.2.3 消费级部署方案：ERNIE-Image 8B FP16（24GB 全精度）为中文架构图最优选择
#### 2.2.4 架构图短标签（<20 字符）场景的特殊挑战：无专用 benchmark，现有长文本基准不适用

## 3. 图生图与改图工作流：迭代编辑与条件控制（~2000字，1个表格，1个流程图）
### 3.1 图生图编辑技术对比
#### 3.1.1 FLUX.1 Kontext：3-5 秒/图，多轮一致性较好，但中文精确编辑受限，6 轮后伪影
#### 3.1.2 Qwen-Image 2.0：统一生成+编辑，原生 2K，链式编辑保留字体/字号/风格，中文架构图编辑首选
#### 3.1.3 ComfyUI img2img：denoise 0.5-0.7 为架构图编辑 sweet spot，Group Nodes 支持非线性分支
### 3.2 条件控制技术：保持几何结构的代价
#### 3.2.1 ControlNet 预处理器对比：Canny（保布局最优）vs LineArt（更精细）vs MLSD（直线架构图最佳）
#### 3.2.2 Multi-ControlNet 叠加：HED(0.8)+Depth(0.7)+Canny(0.6)，总权重≤2.0，VRAM≥12GB
#### 3.2.3 ControlNet 的文本破坏效应：MiniText-Benchmark Sen.Acc 仅 0.0006，必须设计文本保护 mask
#### 3.2.4 替代方案：T2I-Adapter（77M 轻量）、IP-Adapter（风格一致性）、CtrLoRA（1000 图+1 小时训练超 ControlNet）
### 3.3 多轮迭代编辑最佳工作流
#### 3.3.1 标准链：参考图 → ControlNet（结构保持）→ Inpainting（模块修改）→ Qwen-Image-Edit（文本调整）→ 风格统一
#### 3.3.2 API 方案：Dify + Qwen-Image 条件分支（有图→图生图/无图→文生图）+ 对话记忆多轮迭代
#### 3.3.3 中文文本畸变的系统性解决方案：扩散模型负责视觉，确定性渲染引擎（SVG/HTML）负责文本

## 4. 架构图专用工具与混合工作流（~2000字，2个表格）
### 4.1 AI 架构图专用工具深度评测
#### 4.1.1 自然语言生成工具：DiagramGPT（基于 Eraser）、ArchitectureDiagram.ai、Napkin AI
#### 4.1.2 代码驱动工具：Mermaid Chart、D2、PlantUML、Cruderra（代码库扫描）、GitDiagram（GitHub→交互图）
#### 4.1.3 国产工具：boardmix（中文语义最强）、ProcessOn、阿里云 CADT（云架构垂直）、文心一言/KIMI
#### 4.1.4 专用工具 vs 通用扩散模型：专用工具精确但视觉有限，扩散模型视觉强但几何差（表格：工具对比矩阵）
### 4.2 SVG 矢量图与混合工作流
#### 4.2.1 纯矢量路径：LLM→Mermaid/D2/PlantUML→渲染引擎→SVG，可编辑但视觉朴素
#### 4.2.2 纯位图路径：扩散模型直接生成，视觉丰富但几何不精确、文本不可编辑
#### 4.2.3 混合工作流（推荐）：Diagram-as-Code 生成精确结构 → 扩散模型美化风格/纹理 → SVG 叠加精确文本
#### 4.2.4 IJCAI 2024 验证：混合工作流优于纯扩散模型（DALL-E 3 直接生成"looks fancy but non-sense"）
### 4.3 后处理与排版修正技术
#### 4.3.1 GenFix Pipeline：OCR→BLIP 语义→匈牙利对齐→能量优化→修复，有效但 64% 失败源于修复仍出错
#### 4.3.2 AnyText2/CharGen：字体编码器支持任意字体输入，字符级编码对中文多笔画字优势显著（+5.5%）
#### 4.3.3 后处理不是主力方案：对精确架构图，最优方案是"扩散模型底图 + 确定性渲染引擎文本"

## 5. 工作流编排平台与企业级方案（~2000字，1个表格，1个流程图）
### 5.1 低代码工作流平台实践
#### 5.1.1 Dify + ComfyUI 分层架构：Dify 负责 Agent 编排与决策，ComfyUI 作为底层图像生成执行引擎
#### 5.1.2 Dify 接入国产模型：Qwen-Image 插件市场直装；ERNIE-Image/万相通过 HTTP 节点+官方 DSL 接入
#### 5.1.3 Coze + 飞书多维表格：批量生成效率极高（1 分钟 100 张），零代码 AI 字段捷径，极兔速递 72 倍效率提升案例
#### 5.1.4 条件分支工作流设计：If-Else 多路径 + Question Classifier LLM 意图分类 + 内容安全审核节点
### 5.2 企业级部署与成本优化
#### 5.2.1 API 调用成本矩阵：Z-Image Turbo $0.01/张 → GLM-Image $0.015/张 → Qwen-Image $0.02/张 → 豆包 $0.03/张（表格：平台×模型×单价）
#### 5.2.2 三档企业方案：初创（API 优先，月耗<$500）→ 中型（混合部署，降本 40%）→ 大型（本地集群，8 卡 H100 3 年 TCO $231 万）
#### 5.2.3 质量评估框架：R2ABench（结构图指标+多维评分+反模式检测）+ 五维 LLM 评估体系
#### 5.2.4 安全合规三层防线：中国《暂行办法》+《标识办法》+ 阿里云 AIGC 审核 + 人工介入节点
### 5.3 未来趋势与战略建议
#### 5.3.1 架构图从静态文档进化为动态资产：代码仓库→实时架构图→自动同步（Cruderra/GitDiagram 方向）
#### 5.3.2 模型路由成为核心竞争力：按场景自动选择 GLM-Image/ERNIE-Image/Qwen-Image/专用工具
#### 5.3.3 实时生成毫秒化：FLUX Schnell 已达 sub-second，SemanticDraw 0.64 秒/帧，架构图实时生成可期

## 6. 结论与推荐工作流（~1000字，1个表格）
### 6.1 核心结论
#### 6.1.1 混合工作流是唯一可行路径：扩散模型负责视觉，确定性引擎负责结构与文本
#### 6.1.2 中文文本是木桶短板：即使 97% 准确率，20 标签架构图至少一错概率达 46%
#### 6.1.3 本土模型主导中文市场：海外模型因 CJK 数据壁垒在中文场景近乎不可用
### 6.2 推荐工作流（按场景）
#### 6.2.1 快速原型/概念图：boardmix/DiagramGPT → 直接输出可编辑架构图
#### 6.2.2 专业架构图/PPT：Mermaid/D2 → SVG → 扩散模型（Qwen-Image/ERNIE-Image）美化 → 精确文本叠加
#### 6.2.3 批量生成/电商素材：Dify/Coze + 飞书多维表格 → API 批量调用 → 自动审核
#### 6.2.4 代码驱动/实时同步：GitDiagram/Cruderra → CI/CD 集成 → 自动更新架构图
#### 6.2.5 企业部署推荐矩阵：按规模、预算、精度要求的最优方案（表格）

# References
## ai_img_arch.agent.outline.md
- **Type**: Report outline
- **Description**: This outline file
- **Path**: {workspace}/ai_img_arch.agent.outline.md

## Research Files
- **Type**: Deep research dimension reports
- **Description**: 8 dimension deep-dive reports, 6 wide-exploration reports, cross-verification, and insights
- **Path**: {workspace}/research/ai_img_arch_dim01.md – dim08.md, ai_img_arch_wide01.md – wide06.md, ai_img_arch_cross_verification.md, ai_img_arch_insight.md
