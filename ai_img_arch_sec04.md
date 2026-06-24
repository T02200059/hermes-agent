## 4. 架构图专用工具与混合工作流

### 4.1 AI 架构图专用工具深度评测

架构图生成领域存在两条截然不同的技术路径：专用工具与通用扩散模型。前者以结构化输出和可编辑性见长，后者追求视觉丰富度和艺术表现力。对于互联网行业的技术决策者而言，理解两类工具的适用边界是选型决策的前提。

在自然语言生成工具层面，DiagramGPT（Eraser）与 ArchitectureDiagram.ai 代表了当前海外专用工具的第一梯队。赫尔辛基大学2025年的系统性评测表明，在 Mermaid 组件图代码生成任务中，DiagramGPT 与 Claude 能够持续输出无语法错误的代码，而 ChatGPT、DeepSeek 和 Gemini 均存在不同程度的语法缺陷；在 PlantUML 代码生成中，DiagramGPT 和 Claude 同样表现稳定，但 Gemini 即使经过多次提示修正仍无法独立消除错误[^1]。ArchitectureDiagram.ai 作为2026年涌现的专用架构图平台，区别于通用白板工具，其内置的 "Expert Chat" 功能可提供资深架构师级别的图表反馈，并支持 Mermaid、draw.io、Excalidraw、AI 图片、PNG 和 SVG 六种输出格式[^2]。Napkin AI 则定位于快速草图生成，其生成速度优于竞品，但输出被锁定在专有格式中，长期可维护性存在隐忧[^3]。

代码驱动工具是工程师群体的首选。Mermaid 凭借 GitHub/GitLab 原生渲染能力成为技术文档的事实标准，但其在中文场景下存在字体错位、画布管理差、样式定制能力弱等六大核心限制[^4]。D2 图表语言在技术架构图领域优于 Mermaid 和 PlantUML，具备更丰富的形状库（六边形、圆柱、人物）、原生图标集成和多布局引擎（dagre/ELK/TALA），但缺少 GitHub 原生渲染支持[^5]。PlantUML 对 Java 环境依赖较重，且中文渲染需显式绑定中文字体（如 SimSun），否则默认字体（Arial）不包含 CJK 字符集[^6]。Cruderra 和 GitDiagram 代表了从代码到架构图的逆向工程路径：Cruderra 通过 MCP 协议将架构规则注入 AI 编码代理，自动扫描 Java/Python/Go/PHP 代码库生成 UML 图和 OpenAPI 规范，但 SaaS 版本仍在等待名单阶段，仅提供私有化部署[^7]；GitDiagram 则将 github.com 替换为 gitdiagram.com 即可通过 Claude 3.5 Sonnet 分析仓库结构生成可交互的 Mermaid 架构图[^8]。

国产工具在中文语义理解方面形成了显著优势。boardmix 博思白板在中文长难句和特定业务术语理解上准确率明显优于 Lucidchart 等海外工具，输入 "电商平台订单从下单到发货完整处理流程，包含支付、库存扣减、仓库发货、物流配送" 等复杂描述，15 秒即可生成 10 个以上节点带判断分支的完整流程图，结构合理且可直接使用[^9]。ProcessOn 在2023年接入讯飞星火大模型后 AI 功能限时免费开放，中文业务描述转换准确，实时协作能力成熟[^10]。阿里云 CADT AI 助理（云小搭）专门针对阿里云中文云架构场景优化，采用多模型协同与分步推理（Chain-of-Thought）架构，将复杂任务拆解为意图识别、网络规划、资源规划、属性配置等子任务，输出结构化 JSON 伪代码，确保生成结果的专业性与可执行性[^11]。万兴图示（EdrawMax）在2026年5月集成 DeepSeek-V4 大模型，覆盖 280 种以上图表类型，与 Visio 格式兼容，但中文自然语言理解能力略逊于 boardmix 和 ProcessOn[^10]。

从自然语言到专业架构图的准确率并非均等。MorphLLM 2026年的综合评测显示，AI 架构图生成器在标准模式（微服务、三层架构、数据管道）下准确率较高，但在复杂布局（15 至 20 组件以上）时仍需大量手动调整，安全边界和 VPC 分组常被错误放置，组织特定的命名和配色规范难以自动遵循[^12]。工程界的共识是 "AI 生成 80% 初稿，人工精修 20%"，这一定律在架构图场景仍成立。

通用扩散模型（Midjourney、DALL-E）用于技术架构图被业界普遍视为 "工具错配"（using the wrong tool for each job）。IJCAI 2024 论文明确指出，DALL-E 3 生成的图表 "looks fancy but the information is non-sense and meaningless"——视觉华丽但信息失真，无法精确表达系统组件间的拓扑关系，更不可编辑[^13]。相比之下，Claude 生成 Mermaid/SVG 代码在技术内容表达上 "often better than any image model"[^14]。

下表从核心维度对主流专用架构图工具进行系统对比：

| 工具 | 中文语义理解 | 输出格式可编辑性 | 代码逆向生成 | 适用场景 | 成本门槛 |
|------|-----------|---------------|-----------|---------|---------|
| DiagramGPT | 工程可用[^3] | 专有格式（可导出 SVG） | 不支持 | 技术架构描述、流程图 | 中等 |
| ArchitectureDiagram.ai | 良好 | Mermaid/draw.io/SVG/AI 图片[^2] | 不支持 | 多格式架构图、专业评审 | 中等 |
| boardmix | 最强（长难句准确率最高）[^9] | 专有格式+SVG/PNG | 不支持 | 中文业务流、协作白板 | 中等 |
| ProcessOn | 优秀[^10] | 专有格式+SVG/PNG | 不支持 | 中文流程图、团队协作 | 低（AI 免费） |
| 阿里云 CADT | 云架构专用（通义千问驱动）[^11] | JSON 伪代码+可部署 | 部分支持（从 JSON 部署） | 阿里云基础设施设计 | 按资源计费 |
| Mermaid | 需手动配置字体[^4] | 纯文本源码（Git 原生） | 支持（Claude Code/GitDiagram） | 技术文档、版本控制 | 零成本 |
| D2 | 需手动配置字体[^5] | 纯文本源码 | 支持（Claude Code Skill） | 复杂架构图、精确布局 | 零成本 |
| Cruderra | 未明确 | 专有格式 | 核心功能（扫描代码库）[^7] | 代码治理、架构即代码 | 高（私有化部署） |
| Claude Code + draw.io | 良好 | 原生 .drawio XML[^15] | 支持（扫描代码库） | 工程师工作流、活文档 | API 成本 |

上表揭示了架构图工具市场的分化格局。在中文语义理解维度，国产工具（boardmix、ProcessOn、阿里云 CADT）与海外工具（DiagramGPT、ArchitectureDiagram.ai）之间存在明显的断层，前者的长难句理解准确率显著高于后者，这不仅是技术差异，更是 CJK 文本-图像对训练数据壁垒的直接体现。在输出格式可编辑性维度，Mermaid 和 D2 的纯文本源码路径提供了版本控制和 PR 审查能力，这是工程文档场景的关键竞争力；但 Claude 的节点级预测准确率虽高（F1=0.94），链接级预测仍是显著短板（F1 仅 0.30），说明代码格式在关系复杂时仍需人工校验[^16]。代码逆向生成能力目前仍处于早期阶段，Cruderra 的 MCP 架构治理理念先进但 SaaS 未开放，Claude Code 的代码扫描+Mermaid 生成虽实用但缺乏对超大型代码库的系统评测。成本维度上，Mermaid/D2/PlantUML 的零边际成本与国产工具的中等订阅费用形成梯度，企业应根据使用频率和团队规模选择。

### 4.2 SVG 矢量图与混合工作流

架构图生成的技术路径可分为三类：纯矢量路径、纯位图路径和混合工作流。每条路径在精确性、视觉丰富度和可编辑性之间做出了不同的权衡。

纯矢量路径遵循 "LLM→Mermaid/D2/PlantUML→SVG" 的链条。该路径的核心优势在于几何精确和版本控制友好：Mermaid 源码可直接嵌入 GitHub/GitLab，实现 PR 级审查和 CI 验证；D2 的 ELK 布局引擎可处理复杂拓扑；draw.io 的 XML 格式 surprisingly git-friendly，AWS 和 Azure 图标库完备[^15]。然而，这条路径的视觉表现上限较低。ACM 2026年对比研究显示，直接由 LLM 生成 SVG 代码（如 Qwen2.5-14B 得分 0.66） visuals 往往过于简陋；间接方法（扩散模型生成位图+向量化转换，如 SD3.5M 得分 0.73）在视觉保真度上更优，但向量化过程会丢失曲线和细节[^17]。此外，所有主流 SVG 生成模型（LLM4SVG、StarVector、OmniSVG、Reason-SVG、GeoSVG-RL）的研究数据集中均缺乏中文文本相关训练样本，中文架构图 SVG 生成尚无专门模型支持[^18]。

纯位图路径指扩散模型直接生成架构图。该路径在视觉丰富度和艺术风格方面具有天然优势，FLUX.1-dev、Qwen-Image 等模型可生成光影、纹理、景深等视觉元素。但其根本缺陷在于：扩散模型天生不擅长精确几何布局，需要 ControlNet、T2I-Adapter 或 CtrLoRA 等条件控制工具才能勉强维持结构[^19]。更严重的是，ControlNet 在保持几何结构的同时会严重破坏中文文本——MiniText-Benchmark 显示，经 ControlNet 处理后中文句子准确率（Sen.Acc）骤降至 0.0006，几乎完全不可读[^20]。对于一张包含 20 个标签的架构图，即使模型在 97% 的情况下能正确渲染单个标签，至少有一个标签出错的概率仍高达 1-(0.97)^20 ≈ 46%，这在工程实践中意味着不可接受的不确定性。

混合工作流（推荐方案）将 Diagram-as-Code 的精确结构与扩散模型的视觉美感相结合。其典型流程为：自然语言描述 → LLM 生成 Mermaid/D2/PlantUML 结构代码 → 确定性渲染引擎输出基础 SVG → （可选）扩散模型进行视觉风格迁移或背景美化 → 确定性渲染引擎（HTML/SVG）叠加精确文本标签。IJCAI 2024 论文提出的 "LLM 结构基础→Mermaid 渲染→文本到图像模型视觉增强→VLM 质量控制" 三阶段工作流已验证该方案优于纯扩散模型[^13]。Beauty Diagram 提供的 API 服务可在 400 毫秒内完成 Mermaid 源码的美化重排（正交路由、泳道调整、现代配色），代表了确定性美化引擎的实用路径[^21]。ArchitectureDiagram.ai 内部也实现了类似的双轨设计：用户可选择 "可编辑代码" 或 "视觉冲击力强的 AI 图片" 两种输出[^2]。

下表对三种技术路径进行系统对比：

| 维度 | 纯矢量路径（Mermaid/D2/PlantUML） | 纯位图路径（扩散模型直接生成） | 混合工作流（推荐） |
|------|----------------------------------|---------------------------|----------------|
| 几何精确性 | 高（确定性渲染引擎） | 低（需 ControlNet 辅助）[^19] | 高（代码层精确控制） |
| 视觉丰富度 | 低（扁平、朴素） | 高（光影、纹理、景深） | 中到高（取决于美化程度） |
| 中文文本准确率 | 高（字体渲染引擎，>99%） | 低（Sen.Acc 0.0006 经 ControlNet）[^20] | 高（SVG/HTML 叠加确定性文本） |
| 可编辑性 | 极高（纯文本源码，Git 原生） | 无（静态像素） | 中高（结构层可编辑，视觉层可选可编辑） |
| 版本控制 | 原生支持（diff/review/merge） | 不支持 | 部分支持（结构代码可版本化） |
| 生成延迟 | 低（<1秒渲染） | 中（数秒至数十秒） | 中（结构生成快，美化可选异步） |
| 适用场景 | 技术文档、代码库同步、PR 审查 | 概念演示、静态展示、一次性汇报 | 专业架构图、可维护文档、动态资产 |
| 代表工具/论文 | Mermaid.js, D2, PlantUML, GeoSVG-RL | DALL-E 3, FLUX.1-dev, Qwen-Image | IJCAI 2024, Beauty Diagram, ArchitectureDiagram.ai |

三种路径的对比分析揭示了架构图生成领域的核心矛盾：精确性与美感之间存在结构性张力。纯矢量路径以牺牲视觉丰富度为代价换取了几何精确和可编辑性，这是工程文档场景的最优解；纯位图路径以牺牲精确性和可编辑性为代价换取了视觉冲击力，但在架构图场景下这一交换是得不偿失的——扩散模型无法可靠地表达拓扑关系，且中文文本破坏问题尚无根本解决方案。混合工作流通过将两个冲突的维度分配到不同的处理阶段（结构代码负责精确性，扩散模型负责美感，确定性渲染引擎负责文本），实现了帕累托改进。从工具生态的演进方向看，Mermaid.ai 的 "code first + AI refine" 产品策略和 Dify+ComfyUI 的分层架构（Dify 编排 + ComfyUI 执行）均指向同一范式：让 LLM 生成结构化代码，让确定性引擎渲染精确几何，让扩散模型负责可选的视觉增强[^22]。这一范式正在被越来越多的工具和平台采纳，成为架构图生成的事实标准。

### 4.3 后处理与排版修正技术

在架构图工作流中，后处理技术承担着文本纠错和排版修正的兜底角色。尽管其重要性不容忽视，但现有证据表明，后处理不应被视为主力方案，而应是确定性渲染引擎的补充。

GenFix Pipeline 是后处理领域的代表性工作。它提出了完整的 OCR→BLIP 语义→匈牙利算法对齐→能量优化→Stable Diffusion Inpainting 的技术链条，在 AI 生成图像的拼写错误修正上有效。然而，基于人类标注的错误分析显示，失败原因分布为：布局重叠（19%）、OCR 未检测错误（22%）、修复后仍生成错误文本（64%）[^23]。这意味着即使引入后处理，inpainting 阶段仍可能生成错误文本，这是后处理 Pipeline 的根本瓶颈——它检测并定位了错误，但最终修复仍依赖于扩散模型的文本生成能力，而后者正是问题的根源。SA-OcrPaint（模拟退火+OCR 感知递归修复）在 TextDiffuser 基础上将 OCR Word F1 提升 23%（MARIO-HARD 数据集），且随关键词长度增加提升更显著，但 2 次以上迭代会降低图像质量[^24]。对于架构图短标签（2 至 6 字），2 轮迭代足够；长文本修复仍不可靠。

PaddleOCR v4 是检测环节的最优选择。PP-OCRv4-server 在中文识别场景准确率达 85.19%，文档专用模型进一步提升至 86.58%，支持超过 15,000 字符（含繁体、日文、特殊字符）[^25]。但 AI 生成图像中的艺术化、变形、小字号中文文本需要额外预处理（ESRGAN 超分、自适应阈值），否则准确率会显著下降。PaddleOCR 社区明确列出中文 OCR 常见错误类型：生僻字误识别（如 "凪"→"正"）、字符拆分为子组件（如 "几"→"儿"）[^26]。在架构图场景，这些问题会直接导致拓扑标签的语义失真。

AnyText2 和 CharGen 代表了文本编辑技术的最新进展。AnyText2 通过 WriteNet+AttnX 架构将文本渲染与图像生成解耦，并引入文本嵌入模块（字形/位置/字体/颜色四编码器），实现每行文本的字体、颜色等属性自定义，推理速度比 AnyText 提升 19.8%[^27]。其字体编码器通过自适应阈值提取文本区域二进制图像，使用可训练的 PP-OCRv3 编码字体风格，推理时可接受任意字体文件或参考图像输入，对架构图场景可指定为宋体/黑体等标准字体以保证可读性[^27]。CharGen 通过字符级多模态编码器（逐字处理字形图像+文本嵌入）和 CharGen 感知损失（基于 ODM 去风格化模型），在 AnyText-benchmark 上中文 Sen.ACC 达 74.99%，比 AnyText 提升 5.5%，特别解决多笔画字符和相似字符的笔画缺失/添加问题[^28]。对于中文架构图标签，CharGen 的字符级编码优势显著——中文 "负载均衡" 四字共计 73 笔，扩散模型在极小区域渲染如此复杂的笔画结构极易出错，而字符级编码可逐字监督生成过程。

然而，后处理 Pipeline 的系统性局限决定了其不应成为架构图的主力方案。首先，误差累积问题：OCR 漏检（约 22%）→ mask 不准 → inpainting 仍错（约 64%），每一步都在放大前一步的错误[^23][^24]。其次，修复后的文本风格一致性难以保证，inpainting 模型可能生成与原图字体、字号、颜色略有差异的文本，导致整体视觉不协调。第三，后处理无法解决几何布局错误——如果扩散模型将两个组件的连线画错，OCR 和后处理对此无能为力。

当前最优的工程实践是：扩散模型负责生成底图（背景、风格、纹理、非文本装饰元素），LLM 负责生成布局结构（组件位置、连线关系），确定性渲染引擎（HTML/SVG/CSS）负责合成精确文本[^29]。这一方案将文本生成从扩散模型的概率性输出中剥离，交由渲染引擎的确定性输出处理，从根本上规避了 "扩散模型生成文本" 这一系统性风险。对于架构图这类 "精确几何 + 短文本标签" 场景，后处理 Pipeline 更适合作为兜底方案，处理少量生成失败的标签，而非端到端的主力工作流。企业在评估架构图生成方案时，应将预算优先投入到确定性文本渲染层（SVG/HTML 叠加引擎）的建设，而非后处理修复管道的复杂化。

[^1]: 赫尔辛基大学. "Generating diagrams as mermaid code — 学术论文." 2025. https://helda.helsinki.fi/server/api/core/bitstreams/36642c01-0788-470f-8695-0322aea69cb4/content

[^2]: ArchitectureDiagram.ai. "AI Architecture Diagram Tools Compared (2026 Guide)." Feb 2026. https://architecturediagram.ai/blog/ai-diagram-tools-compared

[^3]: Nimbalyst. "Best AI Diagram Tools for Engineers and Claude Code Workflows (2026)." May 2026. https://nimbalyst.com/blog/best-ai-diagram-tools-2026/

[^4]: CSDN. "Typora绘图 - Mermaid优缺点." Feb 2026. https://blog.csdn.net/sinat_41672927/article/details/157814250

[^5]: Tools Online. "D2 Diagrams Online Complete Architecture Diagram Guide." Oct 2025. https://www.tools-online.app/blog/D2-Diagrams-Online-Complete-Architecture-Diagram-Guide

[^6]: CSDN问答. "Windows下Graphviz中文乱码如何解决？" Dec 2025. https://ask.csdn.net/questions/9030129

[^7]: Cruderra. "Architecture Governance for AI Coding Agents." 2026. https://cruderra.com/

[^8]: AI Share Net. "GitDiagram: visualizing the structure of the GitHub codebase." Jan 2025. https://aisharenet.com/en/gitdiagram/

[^9]: CSDN. "国内外4大流程图工具深度横评（2026年）." Apr 2026. https://blog.csdn.net/xiami_world/article/details/160401688

[^10]: 博客园. "2026年AI流程图工具横向测评：8款主流方案使用体验与选型建议." May 2026. https://www.cnblogs.com/s-h-b-3/p/20056139

[^11]: 阿里云帮助文档. "使用AI助理通过自然语言生成云上架构图." Dec 2025. https://help.aliyun.com/zh/cadt/getting-started/ai-assistant-generates-cloud-architecture

[^12]: MorphLLM. "AI Architecture Diagram Generator (2026): 10 Tools Compared." Mar 2026. https://www.morphllm.com/ai-architecture-diagram-generator

[^13]: IJCAI 2024. "Integrating LLM, VLM, and Text-to-Image Models for Enhanced Information Graphics." https://www.ijcai.org/proceedings/2024/0995.pdf

[^14]: Stacking Jones. "Stop Guessing Which AI Image Tool to Use." Mar 2026. https://stackingjones.com/stop-guessing-which-ai-image-tool-to-use/

[^15]: gihyo.jp. "draw.io、Claude Code向けスキルを公開." Feb 2026. https://claudecode.jp/en/news/drawio-skill-for-claude-code

[^16]: arXiv. "FlowLearn: Evaluating Large Vision-Language Models on Flowchart Understanding." Jul 2024. https://arxiv.org/pdf/2407.05183v1

[^17]: ACM. "A Comparative Study of Text-to-SVG Generation Techniques." Apr 2026. https://dl.acm.org/doi/10.1145/3795926.3795973

[^18]: 综合各SVG生成论文数据集分析. 2026-06-23.

[^19]: 基于Phase 1W背景文件ai_img_arch_wide05.md趋势分析. 2026-06-23.

[^20]: ControlNet 社区实测; ComfyUI 论坛. 综合 Dim04, Dim06, Wide02.

[^21]: Beauty Diagram. "API: Beautify Mermaid, Export SVG/PNG, Share." May 2026. https://www.beauty-diagram.com/developers/api

[^22]: Dify 官方文档; 开发者社区案例. 综合 Dim02, Dim04, Dim05, Wide04.

[^23]: Sengupta. "Automated Text Rectification in AI Generated Visual Content." TechRxiv, 2025. https://www.techrxiv.org/doi/pdf/10.36227/techrxiv.174319638.82772972

[^24]: Lakhanpal et al. "Refining Text-to-Image Generation: Towards Accurate Training-Free Glyph-Enhanced Image Generation." WACV 2025. https://openaccess.thecvf.com/content/WACV2025/papers/Lakhanpal_Refining_Text-to-Image_Generation_Towards_Accurate_Training-Free_Glyph-Enhanced_Image_Generation_WACV_2025_paper.pdf

[^25]: PaddlePaddle. "PP-OCRv4/v5 Model Documentation." PaddleX. https://paddlepaddle.github.io/PaddleX/3.1/en/module_usage/tutorials/ocr_modules/text_recognition.html

[^26]: PaddlePaddle. "Chinese OCR help." GitHub Discussions, 2025-01-07. https://github.com/PaddlePaddle/PaddleOCR/discussions/14507

[^27]: Tuo et al. "AnyText2: Visual Text Generation and Editing With Customizable Attributes." arXiv:2411.15245, 2024. https://arxiv.org/html/2411.15245

[^28]: Ma et al. "CharGen: High Accurate Character-Level Visual Text Generation Model with MultiModal Encoder." arXiv:2412.17225, 2024. https://arxiv.org/html/2412.17225v1

[^29]: 综合 Dim06, Dim07 研判. 2026-06-23.
