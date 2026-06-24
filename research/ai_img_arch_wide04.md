## Facet: 工作流编排平台与Agent集成

### Key Findings
- **Dify** 提供完整的可视化工作流编排（Workflow/Chatflow），支持 LLM节点、条件分支（If/Else）、工具调用、知识检索、代码执行等节点。在图像生成方面，Dify Agent 可通过内置或自定义工具（如 Stability AI）调用文生图能力，官方也支持将 ComfyUI 工作流作为工具节点嵌入，实现外部图像生成引擎的调用[^1][^2][^3]。Dify 还内置 CSV 批量处理功能，支持大规模输入数据的自动化处理[^4]。
- **Coze（扣子）** 专为国内生态设计，拥有独立的“图像流”功能，对标 ComfyUI，支持文生图、图生图、智能换脸、背景替换等节点化操作，底层基于 Stable Diffusion。Coze 工作流支持“批处理”节点，可实现 1 分钟批量生成 100 张图，结合飞书多维表格可将工作流发布为批量自动化工具[^5][^6][^7]。
- **ComfyUI** 是本地节点式图像生成工作流的标杆，以 JSON 形式保存和复用工作流。通过自定义节点（如 Checkpoint Rotation、Grounding）支持多模型切换、批量处理、条件逻辑和循环迭代。ComfyUI 提供完整 REST API，可通过 FastAPI 网关被 Dify、Coze 或其他 Agent 平台调用，实现“AI 决策 + 图像生成”的闭环[^8][^9][^10]。
- **LangChain / LangGraph** 是 Agent 工作流编排的核心框架，支持 Prompt Chaining、Parallelization、Evaluator-Optimizer、Agent Loop 等模式。LangChain 的 `create_tool_calling_agent` 可统一调用图像生成工具（如 DALL-E），但自身偏向代码级编排，无原生可视化界面[^11][^12]。
- **Flowise** 基于 LangChain 的节点式无代码平台，对 LLM 和文本工作流支持完善，但图像生成和视频处理不是其核心强项，相关节点较为有限[^13][^14]。
- **飞书多维表格** 的 AI 字段捷径是“表格驱动批量生成”的典型代表，集成即梦 4.0、豆包、Sora、Vidu、DeepSeek、Nano Banana 等模型，支持零代码批量文生图/图生视频。AI Agent 节点可自动编排多步骤图像生成（如 IP 孵化中“文生图 → 图生图 → 多规格组图”），结果直接回写表格[^15][^16]。
- **国产模型集成** 方面，Dify 官方插件市场已上架 Qwen-Image 插件（支持 Qwen-Image-2512 文生图和图生图），通过 ModelScope API 异步调用实现。阿里百炼（含万相 Wanx）可通过 Dify Chatflow/Workflow 的 HTTP 节点接入，官方提供模板 DSL 文件[^17][^18]。Qwen-Image 作为 20B 参数的国产模型，在中文文本渲染和复杂编辑任务上超越部分闭源模型，并支持昇腾/寒武纪平台适配[^19]。
- **Agent 自主调用图像生成** 的主流模式是通过工具调用（Tool Calling）实现：Agent 接收任务后，自主决定调用文生图/图生图工具，获取结果后决定是否进一步编辑或输出。Dify 的 Agent 模式和 LlamaIndex 的 ReAct Workflow 均展示了这一模式[^1][^20]。
- **内容安全与质量评估** 已形成多层防线：阿里云图片审核增强版提供 90+ 风险标签和 AIGC 专项检测；TC260《生成式人工智能服务安全基本要求》对生成内容安全评估设定人工抽检（≥1000 条）合格率 ≥90% 的硬性标准；Azure AI 内容安全提供文本和图像 API；香港大学研究指出需从“内容质量”和“安全与责任”双维度评估图像生成模型[^21][^22][^23]。

### Major Players & Sources
- **Dify** (langgenius/dify): 开源 LLM 应用开发平台，核心定位是“Workflow + RAG + Agent”三位一体的编排层。对图像生成的支持主要通过插件和外部工具集成实现，其 ComfyUI 插件和 Qwen-Image 插件已上架官方市场[^2][^3][^17]。
- **Coze（扣子）** (字节跳动): 国内 Agent 开发平台，图像流和批处理节点是差异化优势。与飞书生态深度绑定，擅长“表格+工作流”的批量内容生产场景[^5][^6][^7]。
- **ComfyUI** (comfyanonymous/ComfyUI): 开源节点式 Stable Diffusion GUI，生态极其丰富。工作流可保存为 JSON 并通过 API 执行，是图像生成工作流的事实标准。在 Dify+ComfyUI 联动中扮演“执行引擎”角色[^8][^9][^10]。
- **LangChain / LangGraph** (langchain-ai): AI 工作流编排的底层框架，强调代码级灵活性和可扩展性。LangGraph 的 StateGraph 支持循环、分支、并行，适合构建复杂 Agent 工作流，但图像生成需额外工具封装[^11][^12]。
- **Flowise** (FlowiseAI): 基于 LangChain 的无代码 LLM 工作流平台，对纯文本/聊天场景友好，但图像生成支持有限，属于“文本友好、图像薄弱”平台[^13][^14]。
- **飞书多维表格** (字节跳动): 企业协作工具+AI 字段捷径的融合体，在“批量结构化生成”场景中效率极高。某电商企业报告素材流转效率提升 10 倍，极兔速递通过多维表格 AI 分镜实现 72 倍效率提升[^15][^16]。
- **Qwen-Image** (阿里通义千问): 20B 参数国产图像生成模型，支持文生图、图生图、像素级编辑。在 Dify 中通过 ModelScope 插件集成，是国产模型接入国际工作流平台的典型范例[^17][^18][^19]。

### Trends & Signals
- **“工作流即服务”成为图像生成的新交付模式**：ComfyUI 工作流通过 API 被 Dify、Coze 等上层平台调用，形成“上层编排决策 + 下层图像生成执行”的分层架构。Dify+ComfyUI 的联动方案已成为 2026 年 AI 漫剧/内容生产的主流技术栈[^2][^10]。
- **表格驱动批量生成是 B 端落地的关键路径**：飞书多维表格和 Coze 的批量工作流证明，将图像生成嵌入到数据表格中，通过字段捷径实现“一次配置、批量运行”，是企业在电商、营销、IP 孵化等场景降本增效的核心手段[^15][^16]。
- **国产模型插件化接入国际平台**：Qwen-Image 通过 Dify Plugin 市场提供标准化接入，标志着国产图像生成模型开始融入国际工作流生态。类似的，万相（Wanx）通过 HTTP 节点和模板 DSL 接入 Dify[^17][^18]。
- **Agent 从“对话式”走向“工具自主调用”**：Dify Agent 和 LlamaIndex ReAct Agent 均展示了 LLM 自主调用图像生成工具的模式。Agent 不再只是回答用户，而是主动执行“生成 → 评估 → 再编辑”的闭环[^1][^20]。
- **AIGC 内容安全评估走向标准化**：TC260 标准对生成内容的人工抽检、关键词抽检、分类模型抽检均提出量化要求（合格率 ≥90%），阿里云推出 AIGC 图片风险检测和 AI 生成图片鉴别服务，显示行业正从“事后审核”走向“全链路合规”[^21][^22][^23]。
- **多模型切换与成本优化成为刚需**：ComfyUI 的 Checkpoint Rotation 节点和 Nano Banana 系列的一键切换，反映了企业用户需要按场景/成本灵活选择模型（如日常用 NB2 $0.03/次，高质量用 NB Pro）[^8][^9]。

### Controversies & Conflicting Claims
- **Dify vs. ComfyUI 的分工边界**：Dify 的图像生成能力是否足够？部分开发者认为 Dify 的图像生成仅通过工具调用实现，难以替代 ComfyUI 的细粒度控制（如 LoRA、ControlNet、IP-Adapter）；而另一部分观点认为 Dify+ComfyUI 的联动才是最佳实践，无需在单一平台内解决所有问题[^2][^10]。
- **Coze 图像流的底层依赖**：Coze 图像流底层基于 Stable Diffusion，但官方未明确披露具体模型版本和微调细节。用户反馈“如果会用 SD 很多技巧可以快速迁移”，暗示其能力上限受限于底层 SD 实现，在复杂场景（如角色一致性、多步编辑）可能不如 ComfyUI 灵活[^5]。
- **LangChain 生态的复杂性 vs. 易用性**：LangChain/LangGraph 提供了极强的灵活性，但开发者社区中有反馈称“Sub-Agents 不遵循工作流序列、工具调用不触发”的问题，显示复杂 Agent 编排的调试成本仍然较高[^12]。
- **AIGC 安全评估的可操作性**：TC260 标准要求生成内容测试题库 ≥1000 条且合格率 ≥90%，但实际操作中如何定义“合格”存在主观性。尤其是图像生成领域，图文一致性、艺术表现力的评估缺乏统一标准，香港大学的研究试图通过美术专家打分和 Elo 评分解决，但规模化复制难度大[^22][^23]。
- **批量生成的质量与一致性矛盾**：Coze 和飞书多维表格宣称可 1 分钟生成 100 张图，但社区反馈“批量生成的小红书知识卡片中间火柴人图像雷同较多，需要继续优化提示词”。这反映了批量生产在效率与质量之间的固有张力[^6][^7]。

### Recommended Deep-Dive Areas
- **Dify + ComfyUI 端到端自动化工作流**：对于“互联网架构图绘制”这一具体场景，需要深入研究如何将 Dify 的 Agent 决策与 ComfyUI 的图像生成节点结合，实现“需求理解 → 架构描述 → 图像生成 → 质量评估 → 迭代优化”的闭环。已有 Dify+ComfyUI 漫剧生产线的实战案例可供参考[^2][^10]。
- **飞书多维表格 + Coze 的批量架构图生成**：如果目标是大规模批量生成可复用的架构图，飞书多维表格的 AI 字段捷径（结合 Coze 工作流）提供了一种“输入结构化参数 → 批量生成 → 结果入表”的高效模式。需探索如何将架构图的风格模板（如配色、布局）作为字段变量注入[^15][^16]。
- **国产模型（Qwen-Image/ERNIE-Image）在垂直场景的表现**：针对架构图绘制，需要实测 Qwen-Image 在中文文本渲染、技术图表生成、复杂布局理解等方面的能力，并与 Stable Diffusion + ControlNet 的方案做对比。Qwen-Image 的 20B 参数和 MMDiT 架构在中文场景有优势，但技术图表的专业性仍需验证[^17][^18][^19]。
- **工作流中的内容安全审核节点设计**：在批量生成互联网架构图时，需嵌入自动审核机制（如阿里云图片审核 API），对生成的图片进行涉政、违禁、侵权等风险检测。同时需要设计质量评估节点（如图文一致性打分、布局合理性检测），实现“生成 → 审核 → 过滤 → 输出”的自动化流水线[^21][^22][^23]。
- **工作流复用与模板化**：ComfyUI 的 JSON 工作流和 Dify 的 DSL 模板均可保存复用。研究如何将一套“架构图生成工作流”参数化（如输入架构类型、组件列表、风格偏好），使其成为可配置、可批量调用的模板，是落地“可复用、可配置、可批量生成”目标的关键[^8][^10]。

[^1]: Dify 官方文档《AI Image Generation App》(docs.dify.ai)
[^2]: 博客《Dify + ComfyUI：零代码打造AI漫剧全自动生产线》（2026-03-30）
[^3]: Dify Marketplace 官方 ComfyUI 插件 (marketplace.dify.ai)
[^4]: API易文档中心《Dify 批量处理》(docs.apiyi.com)
[^5]: 飞书文档《COZE扣子图像流功能》（2026-06-23）
[^6]: 什么值得买《使用扣子工作流多次生成图片、视频、批量》（2026-03-28）
[^7]: CSDN《揭秘爆款笔记背后的AI流水线：扣子Coze工作流批量生成100+小红书知识卡片》（2026-02-16）
[^8]: GitHub - trunksn1/comfyui-change-checkpoint-randomly (2025-11-04)
[^9]: APIYi 博客《Connect Nano Banana 2 to ComfyUI》（2026-02-27）
[^10]: CSDN《ComfyUI与Dify智能体联动：实现AI决策+内容生成闭环》（2025-12-15）
[^11]: LangChain 官方文档《Workflows and agents》(docs.langchain.com)
[^12]: GitHub Discussion - LangGraph Agent Workflow 子Agent工具调用问题（2024-10-29）
[^13]: myweirdprompts.com《Visual AI Pipelines: Beyond Python Glue Code》（2026-04-30）
[^14]: ResearchGate 论文《Beyond Text: Implementing Multimodal LLM-Powered Multi-Agent Systems Using a No-Code Platform》（2025-03-31）
[^15]: 飞书官网《多维表格AI字段捷径：如何用AI实现批量文生图和文生视频？》（2026-01-07）
[^16]: API易文档中心《飞书多维表格AI生图方案》（2026-04-29）
[^17]: Dify Marketplace《Qwen Text2Image & Image2Image》插件
[^18]: 阿里云帮助文档《使用Dify接入百鍊模型》（2025-12-02）
[^19]: CSDN《Qwen-Image-2512开源模型部署：支持国产昇腾/寒武纪平台》（2026-02-03）
[^20]: MLflow 官方教程《Building a Tool-calling Agent with LlamaIndex Workflow and MLflow》
[^21]: 阿里云帮助文档《图片审核增强版介绍及计费说明》（2025-12-02）
[^22]: 香港大学《多模态人工智能模型：图像生成能力评测与安全挑战》（2025-03-24）
[^23]: TC260《生成式人工智能服务安全基本要求》（2024-02-29）
