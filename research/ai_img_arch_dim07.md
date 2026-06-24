# Dim07: SVG矢量图生成与混合工作流

> 调研日期: 2026-06-23 | 角色: 深度调研员_维度07 | 搜索轮次: 12

---

## 1. Mermaid/D2/PlantUML生成中文架构图的实际效果与限制

```
Claim: Mermaid默认中文支持一般，部分平台渲染时易出现乱码或字体错位，需手动配置fontFamily指定中文字体（如"Microsoft YaHei"）解决[^1]
Source: CSDN技术博客（Mermaid.js可视化实战指南）
URL: https://blog.csdn.net/gitblog_01021/article/details/152103674
Date: 2025-09-26
Excerpt: "问题1：中文显示乱码。解决：在配置中指定中文字体。mermaid.initialize({ fontFamily: '\"Microsoft YaHei\", sans-serif' })"
Context: Mermaid.js在Citrix虚拟桌面架构图可视化中的中文配置实践
Confidence: high
```

```
Claim: Mermaid中文场景下存在字体未正确嵌入导致的跨平台乱码问题，SVG/PDF导出时需在代码头部声明UTF-8编码或勾选"Use base64 encoding"选项[^2]
Source: CSDN问答（Drawio导出代码中文乱码问题）
URL: https://ask.csdn.net/questions/8630889
Date: 2025-08-12
Excerpt: "字体未正确嵌入：导出格式（如SVG、PDF）默认未将字体嵌入文件中，导致目标设备缺少相应字体。编码未设置为UTF-8：HTML或SVG文件未指定UTF-8编码，导致浏览器或渲染器无法正确解析中文字符。"
Context: Draw.io/diagrams.net导出SVG时的中文乱码问题诊断
Confidence: high
```

```
Claim: PlantUML对中文渲染存在字体路径注册、环境变量配置等系统级依赖，需显式指定fontname属性绑定中文字体（如SimSun），否则默认字体（Arial）不包含CJK字符集[^3]
Source: CSDN问答（Windows下Graphviz中文乱码）
URL: https://ask.csdn.net/questions/9030129
Date: 2025-12-01
Excerpt: "Graphviz默认使用的字体（如\"Arial\"或未指定字体）不包含中文字符集，导致文本无法正常渲染。即使系统安装了SimSun、Microsoft YaHei等字体，Graphviz可能无法自动发现其物理路径。"
Context: Windows平台Graphviz/PlantUML中文渲染的系统性问题分析
Confidence: high
```

```
Claim: D2图表语言默认使用"Source Sans Pro"字体，原生不针对CJK优化；虽然支持SVG/PNG/PDF/PPTX/ASCII多格式导出，但中文架构图需手动配置字体文件[^4]
Source: GitHub - terrastruct/d2
URL: https://github.com/terrastruct/d2.git
Date: 2025-05-02
Excerpt: "D2 ships with 'Source Sans Pro' as the font in renders. If you wish to use a different one, please see ./d2renderers/d2fonts."
Context: D2官方文档对字体配置的技术说明
Confidence: high
```

```
Claim: D2在技术架构图领域优于Mermaid和PlantUML，具备更丰富的形状库（六边形、圆柱、人物）、原生图标集成、多布局引擎（dagre/ELK/TALA）和更好的性能，但缺少GitHub原生渲染支持[^5]
Source: D2 Diagrams Online Complete Architecture Diagram Guide
URL: https://www.tools-online.app/blog/D2-Diagrams-Online-Complete-Architecture-Diagram-Guide
Date: 2025-10-10
Excerpt: "D2 is generally better for complex architecture diagrams because it offers more shape options (hexagons, cylinders, persons), precise layout control, and advanced styling. Mermaid is better for simple flowcharts and documentation."
Context: D2 vs Mermaid/PlantUML对比评测
Confidence: high
```

```
Claim: Mermaid中文场景存在六大核心限制：样式定制能力弱、超大图表画布管理差、仅静态无交互、复杂代码可读性下降、版本兼容问题、中文适配需手动配置[^6]
Source: CSDN博客（Typora绘图/Mermaid优缺点分析）
URL: https://blog.csdn.net/sinat_41672927/article/details/157814250
Date: 2026-02-06
Excerpt: "核心缺点：样式定制能力弱，颜值上限低。中文适配需手动配置：默认中文支持一般，部分平台易乱码/字体错位，需手动加指令指定中文字体。"
Context: Mermaid在中文长文档/技术写作中的局限性总结
Confidence: high
```

---

## 2. LLM直接生成SVG技术的最新进展与中文支持

```
Claim: LLM4SVG（CVPR 2025，北航）通过引入可学习语义token、结构化SVG编码和58万条SVG指令数据，使LLM能直接理解并生成复杂矢量图形，解决了传统LLM将SVG源码视为普通文本导致token效率低下和数值精度不足的问题[^7]
Source: LLM4SVG Project Page / CVPR 2025 Paper
URL: https://ximinng.github.io/LLM4SVGProject/
Date: 2024-12-15
Excerpt: "LLM4SVG facilitates a deeper understanding of SVG components through learnable semantic tokens, which precisely encode these tokens and their corresponding properties to generate semantically aligned SVG outputs."
Context: LLM4SVG官方项目页面及论文摘要
Confidence: high
```

```
Claim: StarVector作为多模态CodeLLM，使用CLIP图像编码器+StarCoder代码生成器，通过Adapter层对齐视觉token与SVG token，但主要用于image-to-SVG转换，text-to-SVG能力尚未公开模型权重[^8]
Source: StarVector Paper (arXiv:2312.11556)
URL: https://arxiv.org/pdf/2312.11556
Date: 2023-12
Excerpt: "StarVector integrates an Image Encoder i.e., CLIP, with a CodeLLM i.e., StarCoder through an Adapter layer... Since StarVector has not yet opened up its text-to-SVG model weights, our MMSVG-Bench does not evaluate StarVector's text-to-SVG capabilities."
Context: StarVector原始论文的技术架构与公开范围说明
Confidence: high
```

```
Claim: Reason-SVG（CVPR 2026）引入"Drawing-with-Thought"（DwT）推理范式，将SVG生成分解为6个结构化阶段（概念草图→画布规划→形状分解→坐标计算→样式着色→最终组装），通过GRPO强化学习显著提升结构有效性和视觉连贯性[^9]
Source: Reason-SVG Paper (arXiv:2505.24499)
URL: https://arxiv.org/pdf/2505.24499
Date: 2026
Excerpt: "The DwT mechanism instantiates a structured reasoning process that emulates the typical workflow of human designers... decomposes the generation of SVG graphics into six sequential stages: (a) Concept Sketching, (b) Canvas Planning, (c) Shape Decomposition, (d) Coordinate Calculation, (e) Styling and Coloring, (f) Final Assembly."
Context: Reason-SVG论文中DwT推理范式的详细定义
Confidence: high
```

```
Claim: GeoSVG-RL（2026年5月）提出"先规划布局、再生成SVG"的两阶段方法，使用浏览器渲染后端提取bounding boxes、文本边界和锚点，通过多维度几何感知奖励（canvas fit、text containment、anchor alignment、graph consistency）训练SVG策略[^10]
Source: GeoSVG-RL Paper (arXiv:2605.25447)
URL: https://arxiv.org/html/2605.25447v1
Date: 2026-05-25
Excerpt: "Recent methods have begun to incorporate reasoning and rendering feedback into the training process... GeoSVG-RL uses browser rendering feedback as reward signals, adopting Group-Relative Policy Optimization (GRPO) to ensure structural reliability."
Context: GeoSVG-RL论文中关于RLHF/GRPO在SVG生成中的应用综述
Confidence: high
```

```
Claim: 当前LLM/VLM直接生成SVG的学术研究集中在图标、emoji、艺术图形设计，科学图表（如架构图）的SVG生成数据集和评估基准严重匮乏；VFIG-DATA和VFIG-BENCH是首个面向科学图表到SVG转换的大规模数据集[^11]
Source: VFIG Paper (arXiv:2603.24575)
URL: https://arxiv.org/pdf/2603.24575
Date: 2026
Excerpt: "Existing datasets for SVG generation largely focus on icons, emojis, and artistic graphic designs, offering limited coverage of scientific figures and diagrams. We introduce VFIG-DATA, a large-scale dataset for diverse scientific figure-to-SVG conversion."
Context: VFIG论文对现有SVG生成数据集的领域覆盖分析
Confidence: high
```

```
Claim: ACM 2026年对比研究显示，直接由LLM生成SVG代码（如Qwen2.5-14B得分0.66） visuals往往过于简陋；间接方法（扩散模型生成位图+向量化转换，如SD3.5M得分0.73）在视觉保真度上更优，但向量化过程会丢失曲线和细节[^12]
Source: ACM Comparative Study (引用自wide05背景文件)
URL: https://dl.acm.org/doi/10.1145/3795926.3795973
Date: 2026-04-19
Excerpt: "直接由LLM生成SVG代码 visuals往往过于简陋；而间接方法（扩散模型生成位图+向量化转换）在视觉保真度上更优，但向量化过程会丢失曲线和细节。"
Context: 基于背景文件wide05中的ACM对比研究引用
Confidence: high
```

```
Claim: 所有主流SVG生成模型（LLM4SVG、StarVector、OmniSVG、Reason-SVG、GeoSVG-RL）的研究数据集中均缺乏中文文本/中文字形相关的训练样本，中文架构图SVG生成尚无专门模型支持[^13]
Source: 综合上述论文数据集分析
URL: 多个来源交叉验证
Date: 2026-06-23
Excerpt: 各论文数据集中SVG-Stack、MMSVG-2M、SVGX-SFT等均以英文图标/emoji/插画为主，未提及中文CJK字形或中文架构图数据。
Context: 基于多个SVG生成论文的数据集描述交叉验证
Confidence: high
```

---

## 3. "Diagram-as-Code + 扩散模型美化"的混合工作流实际案例

```
Claim: IJCAI 2024论文提出"LLM结构基础→Mermaid渲染→文本到图像模型视觉增强→VLM质量控制"的三阶段混合工作流，并指出纯扩散模型直接生成图表（如DALL-E 3）"looks fancy but the information is non-sense and meaningless"[^14]
Source: IJCAI 2024 Proceedings - Integrating LLM, VLM, and Text-to-Image Models for Enhanced Information Graphics
URL: https://www.ijcai.org/proceedings/2024/0995.pdf
Date: 2024
Excerpt: "Once the structural foundation is laid out by the LLM and rendered by Mermaid, the methodology introduces the use of text-to-image models... A phylogenetic tree generated by using DALL-E 3. Although it looks fancy, the information it depicts is non-sense and meaningless."
Context: 学术论文中提出的混合信息图生成方法论
Confidence: high
```

```
Claim: Mermaid.ai（官方产品）已实践"code first + AI refine"的混合工作流：用户可用自然语言或Mermaid代码开始，通过AI辅助生成、代码编辑和点击调整三种方式切换，支持实时协作和导出[^15]
Source: Mermaid.ai Official Website
URL: https://mermaid.ai/web/
Date: 2026
Excerpt: "Choose how you build. Start with code, refine with AI, or adjust with clicks – switch between workflows to fit your needs... Mermaid solved a major portability problem for us, making charts behave like code. The real game-changer is using AI to analyze our software so we can visualize complex logic instantly."
Context: Mermaid.ai产品官网对混合工作流的官方描述
Confidence: high
```

```
Claim: 架构图工作流生态已形成四个象限：手绘草图（Excalidraw）→代码生成（Mermaid）→AI生成（Fireworks等）→专业设计（Figma/Visio），混合工作流填补"快速+精确+可编辑"的空白地带[^16]
Source: IDEAICU - Fireworks Tech Graph生态定位
URL: https://ideaicu.com/posts/fireworks-tech-graph-natural-language-diagrams
Date: 2026-04-12
Excerpt: "├────────────── 架构图工具生态 ──────────────┤ │ 手绘草图    代码生成    AI 生成    专业设计 │ │ Excalidraw  Mermaid  Fireworks  Figma/Visio │ │   👆          👆         👆 你在这里    👆   │ │ 快速脑暴    版本控制    自然语言      精细设计   │"
Context: Fireworks Tech Graph对架构图工具生态的四象限划分
Confidence: medium
```

```
Claim: D2 Diagram Creation Skill for Claude Code支持通过自然语言生成结构化D2代码，利用ELK/grid布局引擎、验证图标库和可复用样式类，实现从文本到专业架构图的自动化[^17]
Source: MCP Market - D2 Diagram Creation Skill
URL: https://mcpmarket.com/tools/skills/d2-diagram-creation
Date: 2026
Excerpt: "This skill enables the creation of clear, well-structured, and visually appealing diagrams using the D2 scripting language... Integrates validated icons for cloud services, databases, and software components. Optimizes diagram layouts using advanced engines like ELK and grid structures."
Context: Claude Code生态中D2架构图生成Skill的官方说明
Confidence: high
```

---

## 4. 代码到架构图（GitDiagram、Claude Code）的转换流程与中文支持

```
Claim: GitDiagram使用Claude 3.5 Sonnet/O4-mini分析GitHub仓库结构、README和文件树，生成可交互的Mermaid架构图，用户只需将github.com替换为gitdiagram.com即可使用[^18]
Source: GitDiagram Official / AI Share Net
URL: https://aisharenet.com/en/gitdiagram/
Date: 2025-01-17
Excerpt: "GitDiagram is an innovative GitHub codebase visualization tool... uses advanced AI technology (Claude 3.5 Sonnet) to give developers a new way to view and understand their codebase. Users simply replace 'hub' with 'diagram' in the GitHub URL."
Context: GitDiagram产品介绍和功能定义
Confidence: high
```

```
Claim: Understand-Anything（Claude Code插件）支持中文本地化输出（--language zh），通过Tree-sitter确定性解析+LLM语义分析的多智能体管道，将代码库转换为交互式知识图谱[^19]
Source: GitHub - Egonex-AI/Understand-Anything
URL: https://github.com/Egonex-AI/Understand-Anything
Date: 2026-05-19
Excerpt: "Localized output: Use --language to generate content in your preferred language... /understand --language zh. The --language parameter affects: Node summaries and descriptions in the knowledge graph, Dashboard UI labels, buttons, and tooltips, Guided tour explanations."
Context: Understand-Anything插件对中文本地化的完整支持说明
Confidence: high
```

```
Claim: Claude Code + Architecture Diagram Creator skill可生成自包含HTML+SVG架构图，支持通过对话迭代修改（如"将缓存层从Redis改为Memcached"），输出包含SVG可视化、数据流、处理管道和系统架构[^20]
Source: GitHub - Cocoon-AI/architecture-diagram-generator
URL: https://github.com/Cocoon-AI/architecture-diagram-generator
Date: 2025-12-22
Excerpt: "Claude generates a self-contained HTML file... Includes: Header with animated status indicator, Main diagram with SVG with all components and connections, Summary cards, Footer with project metadata."
Context: Claude Code Architecture Diagram Skill的输出生成流程
Confidence: high
```

```
Claim: 基于Claude 3.7/4.0+SVG绘制架构图、集成图、逻辑关系图已成中文技术社区的成熟实践，通过HTML/SVG直接输出可保持无限缩放和可编辑性[^21]
Source: 知乎专栏（强大的Claude4.0+SVG绘制框架图）
URL: https://zhuanlan.zhihu.com/p/1928398559918662630
Date: 2025-07-15
Excerpt: "今天接着聊通过AI大模型进行SVG绘图方面的实践经验分享。我在早期分享过通过Claude3.7+Cursor+SVG进行相关的架构图，集成图，逻辑关系图方面的绘制。"
Context: 中文技术社区对Claude+SVG架构图生成实践的经验分享
Confidence: medium
```

---

## 5. AI位图架构图转换为可编辑矢量图的技术

```
Claim: ImageToDrawio使用AI计算机视觉（形状检测+OCR+线条检测）将静态图片转换为Draw.io原生XML格式，对简单流程图准确率几乎完美，复杂网络图约80%准确率需微调，支持中文文本识别[^22]
Source: ImageToDrawio Official / Dynamic Business
URL: https://dynamicbusiness.com/ai-tools/imagetodrawio-convert-images-into-draw-io-diagrams.html
Date: 2025-09-04
Excerpt: "Utilizing advanced AI, Image to Draw.io accurately transforms images into editable Draw.io files, preserving shapes, text, and connections."
Context: ImageToDrawio产品功能和技术原理介绍
Confidence: high
```

```
Claim: ImageToDrawio的AI分析流程分三步：理解Draw.io的mxGraph XML格式→AI视觉模型检测形状/文本/连接（含布局分析保留空间关系）→以原生格式重建mxCell元素，实现完全可编辑[^23]
Source: ImageToDrawio Official Website
URL: https://imagetodrawio.com/
Date: 2024
Excerpt: "AI图像分析：先进的计算机视觉识别并提取流程图组件。形状检测：矩形、圆形、菱形、自定义形状。OCR技术提取带有位置和格式的文本。线条和箭头检测识别连接和流程。布局分析保留空间关系。"
Context: ImageToDrawio官方对技术流程的详细说明
Confidence: high
```

```
Claim: Vectorizer.AI使用自研Deep Vector Engine（深度学习网络+计算几何算法），支持SVG/PDF/EPS/DXF/PNG输出，可自动识别复杂几何形状（圆、椭圆、圆角矩形、参数星形），对AI生成图像向量化效果良好[^24]
Source: Vectorizer.AI Official Website
URL: https://vectorizer.ai/
Date: 2026
Excerpt: "Our AI-powered image vectorizer turns pixels into editable shapes, with smooth curves, fine details, and clean colors for logos, illustrations, diagrams... Does this work on AI-generated images? Yes, in fact they seem to be a popular category, and we've been pleased to see how well our algorithm works on those images!"
Context: Vectorizer.AI官方FAQ对AI生成图像的向量化效果确认
Confidence: high
```

```
Claim: AI向量化技术相比传统Potrace等工具的优势：可处理渐变（映射为SVG linearGradient）、纹理（识别为纹理而非数千微路径）、文字（保持笔画一致性）、复杂复合形状（理解z-order和交集逻辑）和噪声/压缩伪影[^25]
Source: VectoSolve Blog - How AI Vectorization Works
URL: https://vectosolve.com/blog/ai-image-vectorization-explained
Date: 2026-02-24
Excerpt: "Potrace cannot represent gradients — it quantizes to flat fills. AI detects gradient regions and maps them to SVG linearGradient or radialGradient elements with accurate color stops. A halftone pattern causes classical tracers to emit thousands of micro-paths. The AI recognizes texture as texture and simplifies it."
Context: AI向量化技术对传统算法的超越分析
Confidence: high
```

```
Claim: Eraser.io支持将静态图片（PNG/JPG）导入后通过AI"Re-draw this diagram"转换为可编辑的Eraser图，适用于从Lucidchart、Visio、draw.io迁移或手绘草图数字化[^26]
Source: Eraser.io Docs - Image Import
URL: https://docs.eraser.io/docs/image-import
Date: 2026-05-20
Excerpt: "You can import static image files (.png, .jpeg) and automatically convert them into editable diagrams in Eraser. This is especially useful for migrating diagrams from other tools like Lucidchart, Visio, draw.io, or even photos of hand-drawn diagrams."
Context: Eraser.io官方文档对图片导入功能的技术说明
Confidence: high
```

---

## 6. 混合工作流最佳实践：何时用Diagram-as-Code，何时用扩散模型

```
Claim: Diagram-as-Code（Mermaid/PlantUML/D2）+ 确定性渲染引擎的路径，从根本上解决了扩散模型不擅长精确几何的问题，是架构图生成的工程标准；扩散模型适用于视觉美化但结构不可靠[^27]
Source: 架构师工具箱：建模、可视化与决策辅助
URL: https://quant67.com/post/architecture/83-architect-toolbox/architect-toolbox.html
Date: 2026-04-13
Excerpt: "用代码描述架构，纳入版本控制。架构图通常以二进制格式存储，无法像代码一样做diff、review和merge。架构建模与描述：Structurizr、PlantUML、Mermaid。架构可视化：D2、Graphviz、Excalidraw。"
Context: 架构师工具箱对Diagram-as-Code作为工程标准的论述
Confidence: high
```

```
Claim: 从"位图生成"到"结构化代码生成"的范式迁移正在加速，越来越多工具不再追求让扩散模型直接画像素，而是让LLM生成Mermaid/PlantUML/D2/SVG代码，再由确定性渲染引擎输出[^28]
Source: 基于wide05背景文件趋势分析
URL: 综合来源
Date: 2026-06-23
Excerpt: "从'位图生成'到'结构化代码生成'的范式迁移：越来越多架构图生成工具不再追求让扩散模型直接画像素，而是让LLM生成Mermaid/PlantUML/D2/SVG代码，再由确定性渲染引擎输出。"
Context: 基于Phase 1W背景调研的趋势总结
Confidence: high
```

```
Claim: 混合工作流的核心原则：需要版本控制/精确拓扑/可编辑性的场景（技术文档、代码库同步）→ Diagram-as-Code；需要视觉冲击力/客户汇报/概念演示的场景 → 扩散模型或"代码生成+后美化"[^29]
Source: 综合wide03与wide05背景调研
URL: 综合来源
Date: 2026-06-23
Excerpt: 专用工具（Eraser、ArchitectureDiagram.ai）提供精确控制、图标库和导出工作流；通用AI（Claude/ChatGPT）通过代码生成提供灵活性和零额外成本。两者不是替代关系，而是互补。
Context: 基于Phase 1W广泛调研的工具对比分析
Confidence: high
```

```
Claim: 最佳实践工作流建议：自然语言描述→AI生成Mermaid/D2/PlantUML代码→渲染引擎输出SVG→（可选）AI向量化增强→导入draw.io/Excalidraw精修→版本控制同步。此流程兼顾效率、准确性和可编辑性[^30]
Source: 综合本维度全部调研
URL: 综合来源
Date: 2026-06-23
Excerpt: 本维度调研的综合结论：Diagram-as-Code提供精确几何和版本控制，扩散模型提供视觉丰富度，AI向量化桥接二者，形成互补的混合工作流。
Context: 维度07综合研判
Confidence: high
```

---

## 关键结论汇总

| 维度 | 核心结论 |
|------|----------|
| Mermaid/D2/PlantUML中文 | 均支持中文但需手动配置字体；Mermaid最普及但样式受限；D2功能最强但无GitHub原生渲染；PlantUML对Java环境依赖重 |
| LLM直接生成SVG | LLM4SVG/StarVector/OmniSVG/Reason-SVG等技术进步显著，但均面向英文/图标场景，中文架构图SVG生成缺乏专门支持 |
| 混合工作流 | IJCAI 2024论文和Mermaid.ai已验证"LLM结构+确定性渲染+可选扩散美化"的三阶段混合工作流，优于纯扩散模型 |
| 代码到图表 | GitDiagram/Claude Code/Understand-Anything已支持中文本地化，技术路径成熟 |
| 位图转矢量 | ImageToDrawio（~80%准确率）、Vectorizer.AI（AI生成图像效果良好）、Eraser Image Import已形成工具链 |
| 最佳实践 | 精确架构用Diagram-as-Code，视觉演示用扩散模型，二者可通过"代码生成→SVG→向量化/精修"桥接 |

---

## 引用

[^1]: CSDN. "3分钟上手！用Mermaid.js可视化Citrix虚拟桌面架构的实战指南." 2025-09-26. https://blog.csdn.net/gitblog_01021/article/details/152103674

[^2]: CSDN问答. "Drawio导出代码时如何处理中文乱码问题？" 2025-08-12. https://ask.csdn.net/questions/8630889

[^3]: CSDN问答. "Windows下Graphviz中文乱码如何解决？" 2025-12-01. https://ask.csdn.net/questions/9030129

[^4]: GitHub - terrastruct/d2. "D2 is a modern diagram scripting language." 2025-05-02. https://github.com/terrastruct/d2.git

[^5]: Tools Online. "D2 Diagrams Online Complete Architecture Diagram Guide." 2025-10-10. https://www.tools-online.app/blog/D2-Diagrams-Online-Complete-Architecture-Diagram-Guide

[^6]: CSDN. "Typora绘图 - Mermaid优缺点." 2026-02-06. https://blog.csdn.net/sinat_41672927/article/details/157814250

[^7]: Xing et al. "Empowering LLMs to Understand and Generate Complex Vector Graphics." CVPR 2025. https://ximinng.github.io/LLM4SVGProject/

[^8]: Rodriguez et al. "StarVector: Generating Scalable Vector Graphics Code from Images." arXiv:2312.11556. https://arxiv.org/pdf/2312.11556

[^9]: Xing et al. "Reason-SVG: Drawing-with-Thought." CVPR 2026. arXiv:2505.24499. https://arxiv.org/pdf/2505.24499

[^10]: GeoSVG-RL. "GeoSVG-RL: Geometry-Aware Reinforcement Learning for Layout-Constrained Text-to-SVG Diagram Generation." arXiv:2605.25447. https://arxiv.org/html/2605.25447v1

[^11]: VFIG Paper. arXiv:2603.24575. https://arxiv.org/pdf/2603.24575

[^12]: ACM. "A Comparative Study of Text-to-SVG Generation Techniques." 2026-04-19. https://dl.acm.org/doi/10.1145/3795926.3795973

[^13]: 综合各SVG生成论文数据集分析. 2026-06-23.

[^14]: IJCAI 2024. "Integrating LLM, VLM, and Text-to-Image Models for Enhanced Information Graphics." https://www.ijcai.org/proceedings/2024/0995.pdf

[^15]: Mermaid.ai. "AI-Powered Diagramming & Text-to-Chart Tool." https://mermaid.ai/web/

[^16]: IDEAICU. "Fireworks Tech Graph：用自然语言生成工业级架构图." 2026-04-12. https://ideaicu.com/posts/fireworks-tech-graph-natural-language-diagrams

[^17]: MCP Market. "D2 Diagram Creation: Claude Code Skill for Architecture." https://mcpmarket.com/tools/skills/d2-diagram-creation

[^18]: AI Share Net. "GitDiagram: visualizing the structure of the GitHub codebase." 2025-01-17. https://aisharenet.com/en/gitdiagram/

[^19]: GitHub - Egonex-AI/Understand-Anything. 2026-05-19. https://github.com/Egonex-AI/Understand-Anything

[^20]: GitHub - Cocoon-AI/architecture-diagram-generator. 2025-12-22. https://github.com/Cocoon-AI/architecture-diagram-generator

[^21]: 知乎. "强大的Claude4.0+SVG绘制框架图，逻辑图和知识卡片." 2025-07-15. https://zhuanlan.zhihu.com/p/1928398559918662630

[^22]: Dynamic Business. "Convert images into editable Draw.io diagrams." 2025-09-04. https://dynamicbusiness.com/ai-tools/imagetodrawio-convert-images-into-draw-io-diagrams.html

[^23]: ImageToDrawio Official. https://imagetodrawio.com/

[^24]: Vectorizer.AI Official. https://vectorizer.ai/

[^25]: VectoSolve. "How AI Vectorization Works: The Tech Behind Instant SVG Conversion." 2026-02-24. https://vectosolve.com/blog/ai-image-vectorization-explained

[^26]: Eraser.io Docs. "Image-to-diagram." 2026-05-20. https://docs.eraser.io/docs/image-import

[^27]: Quant67. "架构师工具箱：建模、可视化与决策辅助." 2026-04-13. https://quant67.com/post/architecture/83-architect-toolbox/architect-toolbox.html

[^28]: 基于Phase 1W背景文件ai_img_arch_wide05.md趋势分析. 2026-06-23.

[^29]: 综合wide03与wide05背景调研. 2026-06-23.

[^30]: 维度07综合研判. 2026-06-23.
