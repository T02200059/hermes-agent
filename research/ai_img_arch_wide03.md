## Facet: AI架构图专用生成工具

### Key Findings
- **DiagramGPT（Eraser）** 是目前最广为人知的AI架构图生成工具，基于OpenAI GPT-4模型，支持自然语言、代码片段甚至图片输入生成流程图、ER图、云架构图、序列图和BPMN图等5种类型。它开创了"对AI说人话，自动出图"的范式，但并非独立工具，而是嵌入在Eraser云端协作平台中。[^1][^2]
- **ArchitectureDiagram.ai** 是2026年涌现的专用架构图生成平台，区别于通用白板工具，它专为架构图设计，支持多种输出格式：Mermaid、draw.io、Excalidraw、AI图片、PNG、SVG，并内置"Expert Chat"功能提供资深架构师级别的图表反馈。其核心优势是输出格式多样性，而非单一图表类型。[^3]
- **通用文生图模型（Midjourney/DALL-E）在架构图场景是"美丽的幻觉"**：Midjourney和DALL-E生成的是像素级艺术图，无法精确表达系统组件间的拓扑关系，更无法编辑。多位技术博主明确指出，Claude生成Mermaid/SVG代码比Midjourney"图表"更实用——前者可编辑、可缩放、准确，后者是" beautiful hallucination"。[^4][^5]
- **Claude Code/Claude.ai** 在架构图生成领域表现卓越，它不能直接生成位图，但能输出Mermaid、PlantUML、SVG和HTML架构图。Claude Code可以扫描整个代码库，识别服务和依赖关系，生成与代码结构一致的"图即代码"（diagram-as-code），实现版本控制、代码审查级同步。这被评价为当前技术图表生成的最佳实践。[^5][^6][^7]
- **Cruderra** 是反向工程型工具的代表：自动扫描Java/Python/Go/PHP代码库，解析数据流，生成UML图、OpenAPI规范和组件图。它通过MCP协议将架构规则直接注入AI编码代理（如Cursor、Copilot），实现"架构即代码"治理。但SaaS版本仍在等待名单阶段，目前仅提供私有化部署。[^8][^9]
- **ImageToDrawio** 提供了独特的"图片→可编辑图"转换路径：将PNG/JPG/白板照片等静态图片通过AI计算机视觉识别（形状检测+OCR+线条检测）转换为可编辑的Draw.io XML格式，转换后保留形状、文本和连接关系。对丢失原始源文件的场景极为实用，准确率约80%（简单流程图几乎完美，复杂网络图需微调）。[^10][^11]
- **Eraser Codebase Diagrams + Eraserbot** 实现了CI/CD集成：Eraserbot作为GitHub Action，在PR修改Terraform或K8s YAML时自动更新对应架构图并回提交到PR，从"AI辅助创建"迈向"AI驱动自动化"。这是当前文档与代码同步的最先进方案。[^12]
- **Mermaid AI / ChatGPT + Mermaid** 是零成本入门方案：ChatGPT免费版即可生成Mermaid代码，粘贴到GitHub、VS Code或mermaid.live即可渲染。但缺陷明显：无内置可视化、输出质量波动大、无导出工作流、历史记录不适合图表管理。[^3]
- **InfraSketch** 与Eraser定位差异鲜明：两者都支持自然语言生成架构图，但InfraSketch额外生成完整设计文档，并支持对话式架构精化；Eraser侧重白板协作。InfraSketch针对系统设计面试场景优化。[^13]
- **Napkin AI** 是2026年文本转可视化的黑马：粘贴结构化文本（步骤、对比、列表），3-8秒生成4-6种视觉选项，支持可编辑PPTX导出。但对抽象输入（如"公司价值观"）表现差，且不构建完整演示文稿。免费版每周500积分，已吸引500万+注册用户。[^14][^15]
- **Miro AWS Cloud View / Cloudairy** 代表"实时基础设施导入"流派：连接AWS/Azure/GCP API，直接从真实云资源生成架构图，这是保证图表与现实100%一致的唯一方式。Miro的AWS Cloud View被SRE团队用于 instantly understand what's actually running in long-standing environments。[^16][^17]
- **国产工具的语义优势显著**：boardmix博思白板在中文长难句和特定业务术语理解上准确率明显优于Lucidchart等海外工具。输入"电商平台订单从下单到发货完整处理流程，包含支付、库存扣减、仓库发货、物流配送"，15秒生成10+节点带判断分支的完整流程图，结构合理可直接使用。文心一言在中文PlantUML代码生成方面语义理解精准，KIMI在轻量化Mermaid生成方面零成本可用。[^18][^19]
- **阿里云CADT AI助理** 提供了云厂商原生的架构图生成能力：通过对话生成阿里云业务架构图，支持迭代修改（如"增加一个NLB"、"去掉一台ECS"），最终可手动调整美化和删除多余安全组。这代表了国内云厂商在AI架构图领域的具体实践。[^20]
- **DiagramGPT对中文架构描述的支持已达工程可用水平**：用户输入中文四层架构描述（接入层Nginx+WebSocket网关、服务层Spring Cloud Alibaba微服务、数据层MySQL+Redis+MongoDB、RocketMQ异步解耦），DiagramGPT可自动识别层级边界、组件类型、技术栈标签、通信协议和数据流向，生成具备专业拓扑逻辑和合理分组布局的矢量架构图。其基于规则引擎+LLM微调的混合推理机制，兼具形式化严谨性与自然语言包容性。[^21]

### Major Players & Sources
- **DiagramGPT / Eraser.io**: 自然语言生成架构图的开创者，已嵌入Eraser协作平台。支持代码片段、图片和文本输入，提供Eraser DSL（专有但可编辑）。[^1][^2]
- **ArchitectureDiagram.ai**: 2026年新兴的架构图专用AI平台，多格式输出（Mermaid/draw.io/Excalidraw/PNG/SVG/AI图片），内置专家级架构审查对话。[^3]
- **Claude (Anthropic)**: 通过SVG/Mermaid/PlantUML/HTML代码生成架构图，Claude Code可扫描代码库生成"活文档"。业界公认技术图表生成质量优于ChatGPT和Gemini。[^5][^6][^7]
- **Miro AI**: 实时协作白板+AI生成+AWS Cloud View实时基础设施导入。适合团队设计会议和SRE基础设施可视化。[^16]
- **Cloudairy**: 专注云架构图，连接AWS/Azure/GCP API生成实时基础设施图。提供高分辨率PDF/PNG/SVG导出和版本控制。[^17]
- **Cruderra**: 代码反向工程生成架构图，通过MCP为AI编码代理提供架构治理。目前仅私有化部署。[^8][^9]
- **ImageToDrawio**: 静态图片转可编辑Draw.io的利基工具，支持PNG/JPG/WEBP/GIF，转换后保留形状、文本和连接。[^10][^11]
- **InfraSketch**: 自然语言生成架构图+自动设计文档+对话式精化。针对系统设计和面试场景优化。[^13]
- **Napkin AI**: 文本转可视化（图表/信息图/流程图）的极速工具，3-8秒出图，可编辑PPTX导出。2026年注册用户超500万。[^14][^15]
- **boardmix 博思白板**: 国产AI流程图/架构图工具，原生中文优化，实时协作，内置Mermaid/PlantUML渲染。[^18]
- **ChatDiagram**: 完全免费的浏览器端AI架构图生成工具，无需注册，自然语言输入即可。[^1]
- **Draft1.ai**: 专注ER/UML/Kubernetes/网络图的软件工程专用工具，支持代码级细节。[^1]
- **Lucidchart AI**: 企业级图表工具，AI自动布局+数据导入，深度集成Confluence/Jira/Google Workspace。[^1]
- **阿里云CADT AI助理**: 国内云厂商原生AI架构图生成工具，对话式设计阿里云架构。[^20]
- **文心一言 / KIMI / ProcessOn AI**: 中文AI生成PlantUML/Mermaid代码的本土化方案，在中文语义理解方面优于海外工具。[^19]

### Trends & Signals
- **从"AI辅助创建"到"AI驱动自动化"**：Eraserbot（CI集成自动更新图表）和Cruderra（MCP架构治理）代表了文档与代码自动同步的新方向。文档不再是一次性快照，而是随代码演进的"活资产"。[^12][^9]
- **Diagram-as-Code成为工程标准**：Mermaid/PlantUML/D2等代码格式原生支持GitHub/GitLab渲染，实现版本控制、PR级同步和CI验证。对需要与代码库共同维护的架构图，AI生成代码再渲染的路径优于直接生成像素图。[^5][^22]
- **多模态输入融合**：领先的工具不再局限于纯文本输入。Eraser支持自然语言+代码+图片；ImageToDrawio支持图片转可编辑图；Napkin AI支持文档导入。输入模态越丰富，生成准确率越高。[^2][^10][^15]
- **专用工具 vs 通用AI助手的分化**：专用工具（Eraser、ArchitectureDiagram.ai、Cloudairy）提供精确控制、图标库和导出工作流；通用AI（Claude/ChatGPT）通过代码生成提供灵活性和零额外成本。两者不是替代关系，而是互补。[^3][^5]
- **国产工具的本土化优势凸显**：在中文架构图生成领域，boardmix、文心一言、KIMI、阿里云CADT在中文语义理解、合规部署（国内服务器）和中文模板库方面显著优于海外竞品。海外工具如Lucidchart的AI生成中文场景质量"可用但需大改"。[^18][^19]
- **输出格式的可编辑性成为核心竞争维度**：ArchitectureDiagram.ai和draw.io-mcp-skill将原生可编辑格式（.drawio XML、Mermaid源码）作为默认输出，而非仅提供PNG。用户越来越重视"生成后能否精细调整"，而非一次性到位。[^3][^23]
- **实时基础设施导入成为SRE刚需**：Miro AWS Cloud View和Cloudairy通过API直接读取生产环境生成架构图，解决了"图表过时"的最大痛点。这代表了从"设计时生成"到"运行时同步"的范式转移。[^16][^17]

### Controversies & Conflicting Claims
- **通用AI图片生成 vs 专用架构图工具**：Stacking Jones等博主认为DALL-E/Midjourney用于技术图表是"工具错配"（using the wrong tool for each job），Claude生成Mermaid/SVG代码对技术内容"often better than any image model"。但也有观点认为，对于客户汇报和演示，AI生成的精美像素图（如ArchitectureDiagram.ai的AI image generation）比代码渲染图更具视觉冲击力。两者适用场景不同。[^4][^3]
- **Eraser DSL的开放性问题**：Eraser的Diagram-as-Code使用专有DSL，虽然可编辑，但不如Mermaid/PlantUML开放。社区评论指出其可移植性受限，而ArchitectureDiagram.ai直接以Mermaid作为中间格式，更利于跨工具使用。[^3]
- **AI生成架构图的准确性边界**：虽然标准模式（微服务、3层架构、数据管道）准确率较高，但多位评测者指出：复杂布局（15-20组件以上）仍需手动调整；安全边界/VPC分组常被错误放置；组织特定的命名和配色规范AI难以自动遵循。"AI生成80%初稿，人工精修20%"仍是行业共识。[^5][^1]
- **Claude vs ChatGPT在SVG图表生成上的质量争议**：虽然多个中文评测认为Claude的SVG生成"质量稳定优于ChatGPT"，但也有人指出Claude不能原生生成位图，而ChatGPT集成DALL-E 3可一站式生成逼真图像。这取决于用户的真实需求是"精确技术图表"还是"视觉冲击力强的概念图"。[^6][^5]
- **国产工具vs海外工具的中文架构图质量**：多篇中文评测声称boardmix/文心一言在中文语义理解上"显著优于"Lucidchart，但这类评测多来自国产工具自身的营销内容，独立第三方对比数据较少。需注意潜在的宣传偏差。[^18][^19]

### Recommended Deep-Dive Areas
- **Diagram-as-Code的CI/CD集成实践**：如何将Mermaid/PlantUML代码生成与GitHub Actions结合，在每次代码变更时自动更新架构图。Eraserbot和Cruderra提供了不同路径（SaaS vs 私有化），值得深入对比实施成本和维护复杂度。[^12][^9]
- **中文互联网架构图的AI生成Prompt工程**：当前中文社区已验证一批高效提示词模板（如四层架构描述模板），但缺乏系统性的Prompt工程指南。如何引导AI正确识别隐含约束（如"接入层不直接访问MySQL"）和跨层调用规则，是提升中文场景生成质量的关键。[^21]
- **Draw.io原生XML作为AI生成目标格式的技术实现**：draw.io-mcp项目展示了让AI直接生成mxGraphModel XML的技术路径。相比Mermaid，这种格式更利于精确控制布局、使用AWS/Azure/GCP官方图标集。但XML生成对LLM的代码能力要求更高，值得研究其可靠性边界。[^23]
- **从代码库到架构图的自动化逆向工程**：Cruderra和Claude Code展示了两种不同技术路线（确定性引擎 vs LLM分析），在大型微服务代码库（如Hermes Agent自身）上的实际效果对比尚缺乏系统评测。这是"活文档"理念的核心技术挑战。[^8][^5]
- **AI架构图生成工具的商业模式可持续性**：目前多数工具（ArchitectureDiagram.ai、InfraSketch、Napkin）仍处于早期阶段，免费+低价订阅模式是否可持续？Eraser背靠成熟的协作平台，Miro/Lucidchart有企业用户基础，而纯AI初创工具可能面临被大平台功能整合的风险。[^3][^13][^15]

---

## 引用

[^1]: MorphLLM. "AI Architecture Diagram Generator (2026): 10 Tools Compared." Mar 2026. https://www.morphllm.com/ai-architecture-diagram-generator

[^2]: Eraser.io. "DiagramGPT – AI diagram generator created by Eraser." https://www.eraser.io/diagramgpt

[^3]: ArchitectureDiagram.ai. "AI Architecture Diagram Tools Compared (2026 Guide)." Feb 2026. https://architecturediagram.ai/blog/ai-diagram-tools-compared

[^4]: Stacking Jones. "Stop Guessing Which AI Image Tool to Use." Mar 2026. https://stackingjones.com/stop-guessing-which-ai-image-tool-to-use/

[^5]: MorphLLM. "AI Architecture Diagram Generator (2026): 10 Tools Compared – Coding Agents section." Mar 2026. https://www.morphllm.com/ai-architecture-diagram-generator

[^6]: 老张AI. "Claude能生成图片吗？Claude视觉能力完全指南（2026）." Mar 2026. https://blog.laozhang.ai/zh/posts/can-claude-generate-images

[^7]: CSDN. "Skills - 用AI 一键生成专业系统架构图." Apr 2026. https://blog.csdn.net/yangshangwei/article/details/160310186

[^8]: Cruderra. "Architecture Governance for AI Coding Agents." https://cruderra.com/

[^9]: VisionaryHub. "Cruderra | AI Documentation & Architecture Platform." https://visionaryhub.ai/en-US/tool/cruderra/

[^10]: ImageToDrawio. "#1 图片转Draw.io工具." https://imagetodrawio.com/zh

[^11]: Dynamic Business. "Convert images into editable Draw.io diagrams." Sep 2025. https://dynamicbusiness.com/ai-tools/imagetodrawio-convert-images-into-draw-io-diagrams.html

[^12]: Eraser.io Docs. "Codebase diagrams." Dec 2025. https://docs.eraser.io/docs/codebase-diagrams

[^13]: InfraSketch. "InfraSketch vs Eraser | AI Diagram Tool Comparison 2026." https://infrasketch.net/compare/eraser

[^14]: Alai Blog. "Napkin AI Review 2026: Is It Worth the Hype for Presentations?" Mar 2026. https://getalai.com/blog/napkin-ai-alternatives

[^15]: Napkin AI. "The visual AI for business storytelling." https://www.napkin.ai/

[^16]: Miro. "AI for Architecture Diagrams: Draft, Analyze & Document Faster." Aug 2025. https://miro.com/ai/diagram-ai/architecture-diagram/

[^17]: Cloudairy. "AWS Architecture Diagram Maker — AI-Powered." https://cloudairy.com/ai/ai-aws-architecture-diagram-maker

[^18]: CSDN. "国内外4大流程图工具深度横评（2026年）." Apr 2026. https://blog.csdn.net/xiami_world/article/details/160401688

[^19]: CSDN. "国内技术图生成全攻略：从 AI 代码到专业图表的一站式解决方案." May 2025. https://blog.csdn.net/lihaiming_2008/article/details/147879192

[^20]: 阿里云帮助文档. "使用AI助理通过自然语言生成云上架构图." Dec 2025. https://help.aliyun.com/zh/cadt/getting-started/ai-assistant-generates-cloud-architecture

[^21]: CSDN文库. "DiagramGPT：基于自然语言与代码生成系统架构图和流程图的AI绘图工具." Nov 2025. https://wenku.csdn.net/doc/6wk6f0zux8

[^22]: Diagrams.so. "Diagram as Code Comparison: Mermaid, PlantUML, D2." Jun 2026. https://diagrams.so/learn/diagram-as-code-comparison

[^23]: jgraph/drawio-mcp. "drawio-mcp/skill-cli README." Feb 2026. https://github.com/jgraph/drawio-mcp/blob/main/skill-cli/README.md
