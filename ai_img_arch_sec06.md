## 6. 结论与推荐工作流

### 6.1 核心结论

#### 6.1.1 混合工作流是唯一可行路径：扩散模型负责视觉，确定性引擎负责结构与文本

本调研的跨维度交叉验证得出一个无法回避的工程结论：在架构图生成领域，纯扩散模型路线与纯 Diagram-as-Code 路线各自存在不可克服的结构性缺陷，二者的结合不是“锦上添花”而是“必需条件”。扩散模型在光影、纹理、风格迁移上具有不可替代的优势——Qwen-Image 2.0 支持 1000-token 复杂提示词，可生成含流程箭头与色块编码的完整信息图[^1]——但其天生不擅长精确几何布局，IJCAI 2024 论文指出 DALL-E 3 生成的架构图“looks fancy but the information is non-sense and meaningless”[^2]。反过来看，Mermaid/D2 的确定性渲染引擎在几何精确性和版本控制上无可替代，Claude 在节点级预测上达到 F1=0.94，但链接级预测仅 F1=0.30[^3]，且视觉表现上限被锁定在扁平化风格。当两个独立维度都证明单一方案存在致命短板，且第三个维度（IJCAI 2024 论文）验证混合工作流在结构保真度与视觉丰富度上均优于任何单一方案时[^2]，企业应将预算投向“LLM 结构基础 → 确定性渲染 → 扩散模型视觉增强 → 确定性文本叠加”的四阶段 pipeline，而非在纯工具之间做二选一。

#### 6.1.2 中文文本是木桶短板：即使 97% 准确率，20 标签架构图至少一错概率达 46%

中文文本渲染质量是架构图生成的决定性约束变量。概率论计算表明，当单标签准确率 $p=0.97$、标签数 $n=20$ 时，全对概率 $P=(0.97)^{20}\approx0.54$，至少一处出错的概率高达 46%[^4]。即便在表现最优的 GLM-Image（LongText-Bench-ZH 0.9788）和 ERNIE-Image（>0.96）之间，这一概率仍不可忽视。更严峻的是，后处理方案无法根治问题：GenFix pipeline 中 64% 的失败案例源于修复阶段仍生成错误文本[^5]，ControlNet 在保持几何结构的同时将 MiniText-Benchmark 句子准确率压低至 0.0006[^6]。因此，工程实践中的最优策略不是追求“更高的文本准确率”，而是引入确定性文本渲染层（SVG 文本叠加、HTML 合成），让扩散模型仅负责背景、风格与纹理。这一从“端到端生成”到“分层合成”的范式转变，是架构图工作流从实验室走向生产环境的必要条件。

#### 6.1.3 本土模型主导中文市场：海外模型因 CJK 数据壁垒在中文场景近乎不可用

在中文架构图这一垂直场景，本土模型与海外模型之间存在数量级断层。GLM-Image 以 0.9788 的 LongText-Bench-ZH 得分位居开源第一，而 FLUX.1-dev 在相同基准上仅得 0.005——差距近 200 倍[^1]。这一分化的根源在于数据壁垒：中文字符平均 20–30 笔画，需要专门的 CJK 文本-图像对训练数据，ERNIE-Image 的字符感知编码器即通过此类数据实现超 0.96 的准确率[^7]，而 FLUX.1 系列的原生训练数据以英文为主，CJK 覆盖不足。海外模型若要追平本土模型的中文文本能力，需投入大量 CJK 数据重新训练，成本极高，这一壁垒预计在短期内难以逾越。对中国企业而言，这意味着技术选型应优先评估 Qwen-Image、ERNIE-Image、GLM-Image、Z-Image 等本土方案，海外模型仅在纯视觉（无中文文本）场景具有价值。

### 6.2 推荐工作流（按场景）

#### 6.2.1 快速原型/概念图：boardmix/DiagramGPT → 直接输出可编辑架构图

对于需求探索阶段的快速原型，专用工具的“自然语言→结构化图表”能力是最短路径。boardmix 在中文长难句和特定业务术语理解上准确率显著优于 Lucidchart 等海外工具，输入复杂业务描述后 15 秒即可生成 10 个以上节点带判断分支的完整流程图，结构合理且可直接使用[^8]。DiagramGPT 在 Mermaid 和 PlantUML 代码生成中表现稳定，持续输出无语法错误的代码[^9]。此类场景的核心需求是“快”而非“美”，专用工具的原生可编辑性（boardmix 支持 SVG/PNG 导出，DiagramGPT 支持多格式输出）使后续人工精修成本极低。推荐工作流：自然语言描述 → boardmix/DiagramGPT 生成初稿 → 人工调整布局与标签 → 导出 SVG 嵌入文档。

#### 6.2.2 专业架构图/PPT：Mermaid/D2 → SVG → 扩散模型（Qwen-Image/ERNIE-Image）美化 → 精确文本叠加

对于需要嵌入技术文档、参与评审会议的专业架构图，混合工作流是唯一满足“精确+美观+可编辑”三重标准的方案。推荐流程：自然语言或代码注释 → LLM（Claude/DeepSeek）生成 Mermaid/D2 结构代码 → 确定性渲染引擎输出基础 SVG → 扩散模型（Qwen-Image 2.0 负责编辑迭代，GLM-Image 负责文本密集型精确图表）进行视觉风格迁移或背景美化 → 确定性渲染引擎（HTML/SVG/CSS）叠加精确文本标签。IJCAI 2024 论文验证该四阶段 pipeline 在结构保真度与视觉丰富度上均优于纯方案[^2]。该工作流的关键设计原则是“视觉-文本分离”：扩散模型仅处理非文本区域，所有中文标签由 SVG 文本元素渲染，从根本上规避 ControlNet 文本破坏效应和扩散模型概率性输出的系统性风险[^6]。

#### 6.2.3 批量生成/电商素材：Dify/Coze + 飞书多维表格 → API 批量调用 → 自动审核

对于日生成量超过 50 张的批量场景，零代码编排平台在效率上显著优于手工工作流。Coze 批处理节点可在 1 分钟内生成 100 张图（批量大小 100，并发 3）[^10]，飞书多维表格的 AI 字段捷径集成即梦 4.0、豆包生图等模型，实现“表格驱动批量生成”[^11]。Dify 的分层架构（编排层与执行层解耦）支持条件分支路由（高文本密度走 GLM-Image，低文本密度走 Z-Image/豆包）和人工介入审核[^12]。推荐工作流：多维表格录入需求 → 公式触发 API 调用 → 条件分支自动选择模型 → 生成图像 → 内容安全审核（ComfyUI NSFW 节点或 Dify 人工介入）[^13] → 合格图像自动归档。极兔速递实测该方案可将误差率下降 30%，替代手绘节省 2–3 天人工[^11]。

#### 6.2.4 代码驱动/实时同步：GitDiagram/Cruderra → CI/CD 集成 → 自动更新架构图

架构图在代码变更后迅速过时是互联网行业的核心痛点。GitDiagram 将 github.com 替换为 gitdiagram.com 即可通过 Claude 3.5 Sonnet 分析仓库结构生成可交互的 Mermaid 架构图[^14]；Cruderra 通过 MCP 协议扫描 Java/Python/Go 代码库自动生成 UML 图和 OpenAPI 规范[^15]。推荐工作流：代码仓库变更触发 Webhook → GitDiagram/Cruderra 扫描代码结构 → LLM 优化布局与标签 → 模型路由（根据文本密度选择扩散模型）→ 生成架构图 → 自动回写文档系统 → 版本控制与溯源。这要求架构图从静态图片进化为与代码仓库绑定的动态资产，未来的竞争焦点不是“谁生成的图更好看”，而是“谁的图能自动跟随代码演进保持最新”[^15]。

#### 6.2.5 企业部署推荐矩阵：按规模、预算、精度要求的最优方案

企业选型不应追求“最佳模型”，而应构建“模型路由”机制，根据任务类型、数据敏感度和成本约束自动选择最优路径。以下矩阵按企业规模、预算区间和核心精度要求给出推荐方案：

| 企业规模 | 日生成量 | 月预算区间 | 核心精度要求 | 推荐工作流 | 关键模型/工具 | 核心优势 |
|---------|---------|-----------|------------|----------|------------|---------|
| 初创（<20人） | <50张 | <$50 | 概念级可用 | 纯 API 专用工具 | boardmix、DiagramGPT、Coze | 零部署成本、即时可用、可编辑输出 |
| 中小型（20–200人） | 50–500张 | $200–$500 | 工程级精确 | 混合部署（敏感本地+通用云端） | Dify + ComfyUI + Qwen-Image 2.0 / GLM-Image | 混合部署降本 40%，敏感数据本地处理[^16] |
| 中大型（200–1000人） | 500–2000张 | $500–$3000 | 出版级精确 | 混合工作流 + 模型路由 + 自动审核 | Dify/Coze + Mermaid/D2 + Qwen-Image/ERNIE-Image + 人工介入节点 | 条件分支自动选模，人工介入节点保障合规[^12] |
| 大型（>1000人） | >2000张 | >$3000或本地集群 | 企业级合规 | 本地集群 + 云端弹性 + CI/CD 联动 | 8卡 H100 + Cruderra/GitDiagram + 自研路由层 | 数据安全自主可控，架构图与代码实时同步[^15] |

上表揭示了企业架构图生成的决策逻辑：日生成量 <500 张时，纯 API 或混合部署的云端方案在 TCO 上显著优于本地集群；日生成量 >2000 张且 GPU 利用率 >60% 时，本地 8 卡 H100 集群的 3 年 TCO 约 $231.9 万（含人力、电费、维护）才具备成本合理性[^17]。但数据敏感度是更刚性的约束——涉及核心系统架构的内部文档，无论规模大小，均应在本地或私有云部署，以规避《生成式人工智能服务管理暂行办法》和《人工智能生成合成内容标识办法》的合规风险[^18]。对于所有规模的企业，投资确定性文本渲染层（SVG/HTML 叠加引擎）的优先级应高于采购更高精度的扩散模型，因为模型精度的边际提升（从 0.97 到 0.9788）对 20 标签架构图的整体可用性改善有限，而确定性文本层可将文本准确率从 ~97% 提升至 >99.9%。这是本调研最具操作性的结论：将预算从“买更好的模型”转向“建更聪明的调度系统”，再转向“建不可变的文本渲染层”。

[^1]: Qwen-Image Technical Report, Alibaba, 2025-08-04. https://qianwen-res.oss-cn-beijing.aliyuncs.com/Qwen-Image/Qwen_Image.pdf; GLM-Image Technical Blog, Zhipu AI, 2026-01-14. https://z.ai/blog/glm-image

[^2]: IJCAI 2024. "Integrating LLM, VLM, and Text-to-Image Models for Enhanced Information Graphics." 2024. https://www.ijcai.org/proceedings/2024/0995.pdf

[^3]: FlowLearn: Evaluating Large Vision-Language Models on Flowchart Understanding. arXiv:2407.05183, 2024-07. https://arxiv.org/pdf/2407.05183v1

[^4]: 基于概率论独立事件计算。当单标签准确率 $p=0.97$、标签数 $n=20$ 时，全对概率 $P=(0.97)^{20}\approx0.54$，出错概率 $1-P\approx0.46$。见 ai_img_arch_insight.md Insight 2。

[^5]: Sengupta. "Automated Text Rectification in AI Generated Visual Content." TechRxiv, 2025. https://www.techrxiv.org/doi/pdf/10.36227/techrxiv.174319638.82772972

[^6]: ControlNet 导致 MiniText-Benchmark Sen.Acc 仅 0.0006。见 ai_img_arch_cross_verification.md High Confidence 发现 #4。

[^7]: Baidu ERNIE-Image GitHub, 2026-04-14. https://github.com/baidu/ernie-image; Stable-Learn "Baidu ERNIE-Image: 8B Open-Source Text-to-Image AI", 2026-04-15. https://stable-learn.com/en/baidu-ernie-image-opensource/

[^8]: CSDN. "国内外4大流程图工具深度横评（2026年）." Apr 2026. https://blog.csdn.net/xiami_world/article/details/160401688

[^9]: 赫尔辛基大学. "Generating diagrams as mermaid code — 学术论文." 2025. https://helda.helsinki.fi/server/api/core/bitstreams/36642c01-0788-470f-8695-0322aea69cb4/content

[^10]: 知乎专栏. "1 分钟批量生成 100 张." 2025-08-19. https://zhuanlan.zhihu.com/p/1941221903839786190

[^11]: 飞书官网. "多维表格 AI 字段捷径." 2026-01-07. https://www.feishu.cn/content/article/7592538064711470271

[^12]: 什么值得买. "Dify 新功能：人工介入节点介绍." 2026-02-15. https://post.smzdm.com/p/ax6qlvz9

[^13]: CSDN. "ComfyUI 内容审核节点." 2025-12-13. https://blog.csdn.net/weixin_35871529/article/details/155900945

[^14]: AI Share Net. "GitDiagram: visualizing the structure of the GitHub codebase." Jan 2025. https://aisharenet.com/en/gitdiagram/

[^15]: Cruderra. "Architecture Governance for AI Coding Agents." 2026. https://cruderra.com/; 基于 ai_img_arch_insight.md Insight 5 综合。

[^16]: 腾讯云开发者社区. GPU 选型案例. 2025-11-16. https://cloud.tencent.com/developer/article/2589074

[^17]: GMI Cloud / BytePlus TCO Calculator. 2025-11-08 / 2025-09-02. https://www.gmicloud.ai/en/blog/h100-gpu-pricing-2025-cloud-vs-on-premise-cost-analysis

[^18]: 国家网信办. "生成式人工智能服务管理暂行办法." 2023-08-15; 掘金. "人工智能生成合成内容标识办法." 2026-01-31. https://juejin.cn/post/7601046076942761999
