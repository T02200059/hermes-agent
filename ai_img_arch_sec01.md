# 1. 执行摘要与技术全景

## 1.1 调研背景与目标

AI 图片生成技术在 2024–2026 年间经历了从"玩具"到"生产工具"的质变。然而，当扩散模型与 Diagram-as-Code 工具链交汇于**互联网行业架构图绘制**这一垂直场景时，业界面临一个核心矛盾：通用文生图模型擅长视觉表现却无法保证几何精确，专用图表工具精于结构控制却缺乏视觉丰富度，而中文文本渲染——架构图中最基础的信息载体——竟成为横跨两类方案的共性瓶颈。

本调研聚焦 AI Agent 图片生成工作流在**架构图绘制**场景的工程可行性，覆盖**文生图、图生图、改图**三大工作流类型，核心评估维度包括：中文短文本标签的字符级准确率、框线与箭头的几何精度、模块层次的分组排版质量，以及输出格式的可编辑性。目标读者为技术决策者、SRE 工程师与架构师——他们需要的不只是一张"好看的图"，而是能够嵌入技术文档、随代码迭代同步更新、在评审会议中被逐行质疑的**工程资产**。

互联网架构图对"确定性"有着极端要求。一张包含 20 个微服务模块的架构图，若文本标签的独立准确率为 97%，则至少出现一处错误的概率高达 46%[^1]。此外，架构图需要精确表达拓扑关系、遵循企业级图标规范、支持版本控制（Git diff 可审查），这些需求将通用工具同时推向能力边界。

## 1.2 技术全景概览

### 1.2.1 当前 AI 图片生成技术栈分层

从工程实现视角，AI 架构图生成技术栈可划分为四层。**基础模型层**涵盖文生图扩散模型（Qwen-Image、GLM-Image、ERNIE-Image、FLUX.1-dev、Z-Image）与多模态理解模型（GPT-4o、Qwen2.5-VL）。**条件控制层**通过 ControlNet（Canny、LineArt、Depth、MLSD）、T2I-Adapter 与 CtrLoRA 等机制，将几何约束注入扩散模型的去噪过程，是弥合"视觉丰富度"与"结构精确性"差距的关键桥梁[^2]。**工作流编排层**由 Dify、Coze、ComfyUI 等平台构成，负责任务调度与多模型路由——典型 ComfyUI 架构图工作流包含 6–10 个节点[^3]。**应用层**面向终端用户，分为专用架构图工具（boardmix、ProcessOn、DiagramGPT）、通用白板（Miro、Lucidchart、Excalidraw）与代码驱动工具（Mermaid、PlantUML、D2）三大阵营。

### 1.2.2 架构图生成领域的四大技术路线

当前业界实践可归纳为四条技术路线。**纯扩散模型路线**以端到端文生图为核心，Qwen-Image 2.0 支持 1000-token 复杂提示词，可直接生成含 flow arrows 与 color-coded elements 的信息图[^4]；但该路线受限于扩散模型对精确几何的固有缺陷，IJCAI 2024 论文指出 DALL-E 3 生成的架构图"looks fancy but the information is non-sense and meaningless"[^5]。**Diagram-as-Code 路线**通过 LLM 生成 Mermaid/PlantUML/D2 代码，再由确定性渲染引擎输出矢量图，Claude 在节点级预测上达到 F1=0.94，但链接级预测仅 F1=0.30[^6]；该路线在版本控制与可编辑性上无可替代，却在视觉表现力上存在天然天花板。**专用工具路线**以 boardmix、DiagramGPT、阿里云 CADT AI 助理为代表，通过规则引擎+LLM 微调的混合推理机制，将中文技术描述转换为专业拓扑图，boardmix 在中文语义理解上显著优于 Lucidchart 等海外工具[^7]。**混合工作流路线**——即 IJCAI 2024 论文验证的"LLM 结构基础 → Mermaid 渲染 → 扩散模型视觉增强 → VLM 质量控制"四阶段 pipeline——被证明在结构保真度与视觉丰富度上均优于任何单一方案[^5]，正快速成为企业级架构图生成的工程标准。

### 1.2.3 中文文本渲染能力是架构图生成的核心瓶颈

中文文本渲染质量是架构图生成领域最具决定性的约束变量。在 LongText-Bench-ZH 这一专门针对中文长文本的基准测试中，开源模型呈现数量级的分化格局：

| 模型 | 参数量 | LongText-Bench-ZH | CVTG-2K (WA) | 开源许可 | 显存需求 (FP16) |
|------|--------|-------------------|--------------|----------|-----------------|
| GLM-Image | 9B+7B | 0.9788 [^8] | 91.16% [^8] | MIT | ~23 GB (CPU offload) |
| Ovis-Image | 7B | 0.964 [^9] | 92.00% [^9] | 开源 | ~20 GB |
| Qwen-Image | 20B | 0.9647 [^10] | 82.88% [^9] | Apache 2.0 | ~60 GB (FP16) |
| ERNIE-Image | 8B | >0.96 [^11] | — | Apache 2.0 | ~24 GB |
| Z-Image Turbo | 6B | 0.936 [^12] | — | Apache 2.0 | ~16 GB |
| GPT-Image-1 | — | 0.619 [^10] | — | 闭源 | API 调用 |
| FLUX.1-dev | 12B | 0.005 [^10] | — | 非商用 | ~24 GB (FP8) |

上表揭示"本土主导、海外边缘化"的显著格局。GLM-Image 以 0.9788 的 LongText-Bench-ZH 得分位居开源第一，其自回归模块（9B）负责布局与文本结构规划、扩散解码器（7B）负责像素绘制的混合架构，对架构图"先规划后绘制"的工作模式具有天然适配性[^8]。Ovis-Image 在 CVTG-2K 多区域文本基准上以 92.00% 的平均词准确率超越 Qwen-Image（82.88%）与 GPT4o（85.69%），证明"以文本为中心的训练配方"比单纯堆叠参数更重要[^9]。与此形成 stark contrast 的是，FLUX.1-dev 在相同基准上仅得 0.005——差距近 200 倍——这意味着海外主流模型在中文架构图场景中几乎处于不可用状态[^10]。这一分化的根源在于数据壁垒：中文字符平均 20–30 笔画，需要专门的 CJK 文本-图像对训练数据，ERNIE-Image 的字符感知编码器即通过此类数据实现 LongTextBench 超 0.96 的准确率[^11]，而 FLUX.1 系列的原生训练数据以英文为主，CJK 覆盖不足。

然而，即便在表现最优的本土模型中，文本渲染仍非"已解决问题"。ControlNet 在保持几何结构的同时会严重破坏中文文本——MiniText-Benchmark 上的句子准确率被压低至 0.0006[^13]，这迫使工作流设计者必须将"结构控制"与"文本生成"物理解耦。GenFix 后处理 pipeline 虽可将 OCR F1 提升 20–30%，但超过 64% 的失败案例源于修复阶段仍生成错误文本[^14]——后处理只能缓解，不能根治。因此，工程实践中的最优策略不是追求"更高的文本准确率"，而是引入**确定性文本渲染层**（SVG 文本叠加、HTML 合成），让扩散模型仅负责背景、风格与纹理，文本标签由不可变的确定性引擎渲染。这一从"端到端生成"到"分层合成"的范式转变，是架构图工作流从实验室走向生产环境的必要条件。

[^1]: 基于概率论独立事件计算。当单标签准确率 $p=0.97$、标签数 $n=20$ 时，全对概率 $P=(0.97)^{20}\approx0.54$，出错概率 $1-P\approx0.46$。

[^2]: LACE 论文与 GeoSVG-RL 论文均指出扩散模型天生不擅精确几何布局，需依赖 ControlNet/T2I-Adapter/CtrLoRA 等条件控制机制。见 ai_img_arch_cross_verification.md High Confidence 发现 #7。

[^3]: Dify 1.13.0 接入 Qwen-Image 需异步 API 轮询（5 秒间隔）；ComfyUI 典型工作流含 6–10 节点。见 ai_img_arch_dim05.md 与 ai_img_arch_cross_verification.md Medium Confidence 发现 #8。

[^4]: Qwen-Image 2.0 支持 1000-token 复杂提示词，可直接生成含 flow arrows、color-coded elements 和 precise label positioning 的信息图。Qwen-Image Technical Report, Alibaba, 2025-08-04. https://qianwen-res.oss-cn-beijing.aliyuncs.com/Qwen-Image/Qwen_Image.pdf

[^5]: IJCAI 2024. "Integrating LLM, VLM, and Text-to-Image Models for Enhanced Information Graphics." 2024. https://www.ijcai.org/proceedings/2024/0995.pdf

[^6]: FlowLearn: Evaluating Large Vision-Language Models on Flowchart Understanding. arXiv:2407.05183, 2024-07. https://arxiv.org/pdf/2407.05183v1

[^7]: CSDN. "国内外4大流程图工具深度横评（2026年）." Apr 2026. https://blog.csdn.net/xiami_world/article/details/160401688

[^8]: GLM-Image Technical Blog, Zhipu AI, 2026-01-14. https://z.ai/blog/glm-image; DeepLearning.ai "Zhipu's GLM-Image Blends Transformer and Diffusion Architectures", 2026-02-16. https://www.deeplearning.ai/the-batch/zhipus-glm-image-blends-transformer-and-diffusion-architectures-for-better-text-in-images

[^9]: Ovis-Image Technical Report, arXiv:2511.22982, 2025-11-28. https://arxiv.org/abs/2511.22982

[^10]: 综合 Qwen-Image Technical Report、NTIRE 2025 及多项独立评测。FLUX.1-dev LongText-Bench-ZH 0.005 与 GLM-Image 0.9788 的差距近 200 倍。见 ai_img_arch_cross_verification.md High Confidence 发现 #1、#3。

[^11]: Baidu ERNIE-Image GitHub, 2026-04-14. https://github.com/baidu/ernie-image; Stable-Learn "Baidu ERNIE-Image: 8B Open-Source Text-to-Image AI", 2026-04-15. https://stable-learn.com/en/baidu-ernie-image-opensource/

[^12]: Z-Image Technical Report, arXiv:2511.22699v1, 2025-11-11. https://arxiv.org/html/2511.22699v1

[^13]: ControlNet 导致 MiniText-Benchmark Sen.Acc 仅 0.0006。见 ai_img_arch_cross_verification.md High Confidence 发现 #4。

[^14]: GenFix 论文。后处理 pipeline 中 64% 失败源于修复阶段仍生成错误文本。见 ai_img_arch_cross_verification.md Medium Confidence 发现 #4。
