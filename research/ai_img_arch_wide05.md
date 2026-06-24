## Facet: 中文排版与架构图可视化技术

> 调研日期: 2026-06-23 | 角色: AI图像生成技术调研员_维度05 | 搜索轮次: 13

---

### Key Findings

#### 1. 中文文本在AI生成图像中的排版现状

- **头部模型中文渲染能力已大幅提升**。GPT-Image-2 的CJK文字排版准确率从前代的70-85%跃升至 **99%+**[^1]，采用全新独立架构（Spud多模态推理模型），支持单步推理，分辨率提升至4096×4096。实测可稳定输出宋体、黑体、楷体及书法字体，多语言混排也可行。
- **Qwen-Image系列在中文场景表现突出**。通义千问200亿参数模型Qwen-Image中文文本渲染准确率达 **97.29%**[^2]，Qwen-Image-Edit在中文编辑场景下单字准确率高达97.29%，远超Seedream3.0（53.48%）和GPT Image 1（68.37%），支持多行布局、段落级文本生成及书法对联等复杂排版需求[^3]。
- **长文本与细小字体仍是普遍痛点**。即使是GPT-Image-2，中文长文本（超过10个汉字）仍有约10-15%的失败率，繁简混用、笔画缺失、字体不统一是高频问题[^4]。Qwen-Image-2512测评显示，CJK字形在大尺寸下表现良好，但**细笔画在小字号下会崩塌（collapse）**[^5]。独立测试表明GPT-4o对较小中文字符"几乎完全错误"[^6]。
- **模型间差距显著**。DALL-E 3中文准确率约78%，Midjourney v6约60-75%，Ideogram 3.0约90-95%但中文仅约60%[^1][^7]。Z-Image-Turbo通过内置双语tokenizer和大量带文字的训练数据，在"福"字等案例中80%概率避免了SDXL上常见的偏旁缺失或部首粘连[^8]。

#### 2. AI生成架构图时的几何布局问题

- **扩散模型天生不擅长精确几何**。扩散模型的核心机制是"先加噪、再去噪"，擅长创意生成但在严格几何约束（模块对齐、箭头指向、层次关系、间距一致性）上表现薄弱[^9]。LACE（LAyout Constriant Diffusion modEl）论文指出，扩散模型虽然FID得分领先，但在**对齐（alignment）和MaxIoU得分**上通常不如早期基于Transformer的模型[^10]。
- **强化学习正在成为解决几何精度的关键路径**。GeoSVG-RL（Geometry-Aware Reinforcement Learning for Layout-Constrained Text-to-SVG Diagram Generation）提出"先规划布局、再生成SVG"的两阶段方法，使用浏览器渲染后端提取bounding boxes、文本边界和锚点，通过多维度几何感知奖励（canvas fit、text containment、anchor alignment、graph consistency、code cleanliness）训练SVG策略，采用**Group-Relative Policy Optimization (GRPO)**确保生成图表的结构可靠性[^11]。
- **后处理约束优化是弥补扩散模型不足的实用手段**。LACE在训练阶段引入全局对齐损失和两两重叠损失，推理后阶段通过阈值检测近似对齐的坐标对并强制对齐，在不牺牲FID的前提下显著改善布局质量[^10]。
- **布局生成领域已形成"文本→结构化表示→几何渲染"的共识范式**。HouseDiffusion等模型将平面图表示为向量序列，通过扩散模型去噪生成，相比栅格化表示能更好保持拓扑和几何结构[^12]。

#### 3. SVG/矢量图生成 vs 位图生成的架构图优势对比

- **矢量图在架构图场景具有根本性优势**。矢量图形（SVG/AI/EPS）基于数学公式描述几何原语，具有**无限缩放性、分辨率独立性、文件体积小、可逐元素编辑**等优势，而位图（PNG/JPG）在放大时会出现像素化且难以精确修改[^13][^14]。
- **当前AI工作流以"位图生成+后矢量化"为主流**。ACM 2026年的对比研究显示，直接由LLM生成SVG代码（如Qwen2.5-14B得分0.66） visuals往往过于简陋；而间接方法（扩散模型生成位图+向量化转换，如Stable Diffusion 3.5M得分0.73）在视觉保真度上更优，但**向量化过程会丢失曲线和细节**[^15]。
- **纯LLM生成SVG代码正在快速发展**。LLM4SVG（CVPR 2025）通过引入可学习的语义token、结构化SVG编码和58万条SVG指令数据，使LLM能直接理解并生成复杂矢量图形，解决了传统LLM将SVG源码视为普通文本导致token效率低下和数值精度不足的问题[^16]。StarVector、OmniSVG等模型也在通过视觉-语言架构将图像或文本映射到SVG代码[^17]。
- **关键权衡：位图保真度 vs 矢量可编辑性**。对于需要后续编辑的架构图，矢量格式是必选项；对于追求视觉丰富度的海报，位图+有限后处理仍是主流。Kroki等统一API（支持Mermaid/Graphviz/D2/PlantUML等20+格式转SVG）提供了工程化的中间路径[^18]。

#### 4. 从文本描述生成结构化图表的技术原理

- **Diagrams as Code 工具链成熟度高**。Graphviz（1991，DOT语言）、PlantUML（2009，UML标准）、Mermaid（2014，GitHub原生支持）、D2（2022，ELK布局引擎，Go实现）形成完整生态[^19][^20]。D2使用ELK布局引擎生成"最美观易读的图表"，支持SVG/PNG/PDF/PowerPoint导出[^19]。
- **AI工具正在将自然语言直接映射到图表代码**。Napkin（文本识别逻辑→可视化图表）、Eraser（Code First Diagram→Mermaid兼容）、DiagramGPT（Eraser基础，自然语言→架构图）、ProcessOn AI（10秒生成专业级架构图，支持连续对话迭代）等工具已落地[^21][^22]。Claude 3.7可一键生成SVG格式系统架构图[^23]。
- **技术架构通常是"自然语言→中间表示（Mermaid/PlantUML/D2）→渲染引擎→SVG/PNG"**。这避免了直接让扩散模型生成精确几何，而是利用LLM的语言理解能力和确定性渲染引擎的几何精度，形成**优势互补的混合架构**[^22]。
- **Python生态支持程序化架构图生成**。`diagrams`库（39K stars）支持云架构图，`mermaid-py`生成Mermaid图表，`d2-python-wrapper`封装D2渲染，NetworkX和igraph用于图分析，Kroki提供统一HTTP API[^24]。

#### 5. AI生成图片后的OCR检测与排版修正后处理

- **OCR+视觉语言模型+扩散修复的Pipeline已成为主流**。GenFix模型提出完整的AI生成图像文本修正Pipeline：使用TrOCR/EasyOCR检测文本区域→BLIP-2生成图像上下文描述→图匹配算法（匈牙利算法）对齐OCR文本与语义正确序列→能量函数优化几何布局（保持位置、高度、间距、对齐）→Stable Diffusion Inpainting风格保持修复[^25]。
- **中文OCR后处理具有特殊性**。PaddleOCR讨论指出，中文常见错误包括：生僻字误识别（如"凪"→"正"）、字符拆分为子组件（如"几"→"儿"），需通过**多语言模型切换、后处理替换脚本、自适应阈值、ESRGAN超分**等手段改善[^26]。华为云OCR采用深度学习预处理分离表格线/印章、倾斜校正、最大轮廓提取、集成学习+词典+Levenshtein距离纠正[^27]。
- **LLM在OCR后校正领域展现潜力**。研究表明，基于Transformer的方法在OCR后校正上已超越传统非Transformer方法，且LLM方法随着模型进步仍有提升空间[^28]。
- **排版引擎修正的思路：能量优化**。GenFix的能量函数同时惩罚位置偏移（λ₁）、高度变化（λ₂）、水平间距不一致（μ）、高度不一致（ν），保证修正后的文本在视觉流上的连贯性[^25]。

#### 6. 中文字体在AI图像中的渲染问题

- **AnyText系列开创了多语言视觉文本生成的系统方法**。AnyText（阿里）通过辅助潜在模块（编码字形、位置、掩码图像）和文本嵌入模块（OCR编码笔画信息+tokenizer图像标题嵌入），配合文本感知损失，在AnyText-benchmark上中文Sen.ACC达到 **66%**（远超其他方法），AnyText2进一步将中文文本准确率提升3.3%[^29][^30]。
- **CharGen从字符级编码解决笔画错误**。CharGen通过字符级多模态编码器，在中文生成上解决笔画缺失、添加、不准确等问题，在AnyText-benchmark上中文Sen.ACC达到 **74.99%**（比AnyText提升5.5%），英文达80.96%（提升8.8%），尤其在多笔画字符和相似字符上优势显著[^31]。
- **FonTS实现了字体和排版属性的词级控制**。FonTS（Text Rendering with Typography and Style Controls）通过HTML渲染构建排版控制数据集（TC-Dataset），支持粗体、斜体、下划线等词级属性，以及艺术风格控制，使用包围修饰token标记属性位置，实现字体内在一致性和风格可控性[^32]。
- **字体风格保持仍面临挑战**。当前AI生成中文字体时，风格lora + ControlNet条件控制是Stable Diffusion生态中应用最广泛的方式，但"排版、质感、可控性等方面远不及英文文本渲染"[^33]。Kolors等国产模型虽能生成准确字形，但字体风格控制仍待提升。

---

### Major Players & Sources

| 实体 | 角色/相关性 |
|------|----------|
| **OpenAI (GPT-Image-2)** | 当前CJK文本渲染准确率最高的商业模型（99%+），采用全新Spud架构，支持单步推理和PSD分层导出[^1] |
| **阿里通义千问 (Qwen-Image/Edit)** | 中文场景最优开源模型之一，200亿参数，中文准确率97.29%，支持编辑和复杂排版[^2][^3] |
| **阿里AnyText/AnyText2** | 多语言视觉文本生成先驱，首创OCR笔画嵌入+文本感知损失，支持多行/变形区域/多语言/编辑[^29][^30] |
| **CharGen** | 字符级编码突破者，中文Sen.ACC 74.99%，解决笔画错误[^31] |
| **GeoSVG-RL团队** | 将RLHF（强化学习）引入SVG布局约束生成，使用浏览器渲染器作为几何验证器[^11] |
| **LLM4SVG (北航)** | 使LLM直接理解并生成SVG的开创工作，CVPR 2025，提出语义token和58万SVG指令数据[^16] |
| **LACE团队** | 扩散模型布局约束优化的代表，通过美学约束损失改善对齐和重叠[^10] |
| **D2/Terrastruct** | 现代图表脚本语言，使用ELK布局引擎，2022年发布，在软件架构图领域迅速崛起[^19] |
| **Mermaid** | 最广泛采用的Markdown兼容图表语言，GitHub原生支持，生态最成熟[^20] |
| **Kroki** | 统一图表渲染API（20+格式→SVG/PNG/PDF），支持自托管，适合CI/CD和文档自动化[^18] |
| **GenFix** | AI生成图像文本修正的端到端Pipeline，OCR+BLIP+图匹配+能量优化+Stable Diffusion修复[^25] |
| **PaddleOCR (百度)** | 中文OCR事实标准，PP-OCRv4在多场景中文识别上领先，社区活跃[^26] |
| **GlyphDraw2** | 结合扩散模型和LLM自动生成复杂字形海报，中英文渲染精度均超越AnyText[^34] |
| **Z-Image-Turbo** | 亚秒级推理，通过双语tokenizer和联合建模优化中文文字渲染[^8] |
| **ProcessOn/Eraser/Napkin** | AI生成架构图商业工具代表，将自然语言直接映射到可编辑图表[^21][^22] |

---

### Trends & Signals

- **从"位图生成"到"结构化代码生成"的范式迁移**：越来越多架构图生成工具不再追求让扩散模型直接画像素，而是让LLM生成Mermaid/PlantUML/D2/SVG代码，再由确定性渲染引擎输出。这从根本上解决了扩散模型不擅长精确几何的问题[^22][^15]。
- **强化学习（RLHF/GRPO）正在进入视觉生成领域**：GeoSVG-RL使用浏览器渲染反馈作为奖励信号，Reason-SVG引入"Drawing-with-Thought"推理范式，RLRF使用VLM渲染反馈优化。这表明**生成+验证+强化优化**的闭环正在成为高质量结构化图形生成的新标准[^11][^16]。
- **中文AI排版能力正经历"从可用到好用"的跨越**：2024-2026年间，头部模型中文准确率从70%提升至99%，标志着中文不再是AI图像生成的边缘场景。但**小字、长文本、复杂混排、字体风格精细控制**仍是接下来1-2年的攻关方向[^1][^5][^4]。
- **OCR后处理正在从"工具链拼接"走向"端到端系统"**：GenFix等Pipeline将OCR检测、语义理解、几何优化、图像修复整合为统一流程，未来可能与生成模型本身更紧密耦合[^25]。
- **矢量图生成与扩散模型正在融合**：扩散模型先生成位图再矢量化的"两步走"仍是主流，但LLM4SVG、StarVector等直接生成SVG代码的方法正在缩小差距，未来可能出现**扩散模型直接在隐空间生成矢量参数**的统一框架[^15][^16][^17]。

---

### Controversies & Conflicting Claims

- **GPT-Image-2中文准确率"99%" vs 实际压力测试的局限性**：部分测评者指出，尽管GPT-Image-2短文本准确率极高，但在**竖排、书法、变形艺术字**上仍有10-15%失败率，且与Seedream 5.0 Lite相比，中文字体风格丰富度仍略弱[^4]。另一篇测评更保守地认为中文短文本（3-5字）准确率约75-80%，超过10字错误率大幅上升[^7]。这种差异可能源于测试用例的复杂度不同——生产级海报标题 vs 极限压力测试。
- **直接LLM生成SVG vs 扩散+矢量化的优劣之争**：ACM 2026年对比研究明确显示，LLM直接生成SVG代码 syntactically valid但"往往简陋、缺乏视觉吸引力"（Qwen2.5-14B最佳得分0.66），而扩散+矢量化方法视觉保真度更高（SD3.5M得分0.73）但会丢失曲线和细节[^15]。这揭示了一个核心矛盾：**精确可控性 vs 视觉丰富度难以兼得**。
- **扩散模型用于布局生成的价值存疑**：LACE论文承认，连续扩散模型的坐标搜索空间远大于离散模型，存在大量FID相似但视觉质量差异显著的局部最优解。约束优化和后处理虽能改善，但扩散模型是否真的比自回归模型更适合布局生成，学术界尚未形成共识[^10]。
- **AnyText商业落地缓慢**：尽管AnyText在技术上开创了多语言文本生成，但社区有评论指出"直到现在好像也没有进一步的商用化落地，实在令人惋惜"[^33]。这可能反映了视觉文本生成技术从研究到产品化仍面临推理成本、用户交互、商业模式等挑战。

---

### Recommended Deep-Dive Areas

1. **LLM直接生成SVG/图表代码的精细化**：当前LLM生成SVG的代码简洁但视觉简陋，未来研究可探索如何让LLM在保持代码紧凑的同时生成更丰富的视觉层次（渐变、阴影、复杂路径）。LLM4SVG的语义token和结构化编码是可行方向[^16]。
2. **中文小字号渲染（<14pt）的专项突破**：小字渲染是AI图像中文字排版的"最后一块硬骨头"，需要字级监督（如CharGen的字符级编码）或字形嵌入辅助（如AnyText的OCR笔画编码）[^31][^29]。
3. **AI生成架构图的"人机协作"交互范式**：ProcessOn/Eraser已证明"自然语言描述→AI生成初稿→人工微调"是高效工作流。研究可进一步探索**增量式对话编辑**（如"将缓存层从Redis改为Memcached，保持其他不变"）的语义理解和最小变更渲染技术[^22]。
4. **OCR-感知损失作为生成模型训练信号**：AnyText的文本感知损失、GlyphDraw2的PWAcc指标都证明，在训练阶段引入OCR识别作为辅助监督能显著提升文本准确率。将PaddleOCR或TrOCR嵌入训练Pipeline作为可微或近可微损失函数，是提升中文生成质量的关键技术路径[^29][^34]。
5. **SVG图表的语义一致性验证**：GeoSVG-RL使用Edge Connectivity F1评估图表结构正确性，但当前验证器仍较简单。对于复杂互联网架构图（含多层容器、条件分支、双向箭头），需要**更强大的图拓扑验证**和**领域特定约束检查器**[^11]。
6. **矢量图与位图的混合表示**：对于既有精确几何又有丰富纹理的架构图（如3D等距数据中心图），纯矢量可能不够，纯位图又不可编辑。研究可探索**"几何层矢量+装饰层位图"的混合编码**，或神经网络直接在矢量参数上操作的新型扩散模型[^15]。

---

### References

[^1]: 腾讯云. "GPT-Image-2 实测：中文排版准确率99%". 2026-04-22. https://cloud.tencent.com/developer/article/2658403
[^2]: CSDN. "Qwen-Image：2025年中文图像生成新标杆，97.29%文本准确率重构创意生产". 2024-04-10. https://blog.csdn.net/weixin_44212848/article/details/137567675
[^3]: 掘金. "挑战GPT-4o！阿里开源Qwen-Image-Edit模型，在中文图像渲染与编辑上取得突破". 2025-08-19. https://juejin.cn/post/7539922410282582057
[^4]: 人人都是产品经理. "GPT-Image-2 实测 8 维：哪些场景今天就能替代设计师，哪些还会翻车". 2026-04-27. https://www.woshipm.com/ai/6384448.html
[^5]: WaveSpeed AI. "Qwen Image 2512 Text Rendering Guide: Create Readable Posters & Typography". 2026-01-09. https://wavespeed.ai/blog/posts/qwen-image-2512-text-rendering/
[^6]: GitHub - NiceRingNode. "GPT-4o-Image-Generation-for-OCR: Evaluating GPT-4o's image generation and editing ability in OCR tasks". 2025-09-16. https://github.com/NiceRingNode/GPT-4o-Image-Generation-for-OCR
[^7]: 掘金. "GPT-Image-2 实际出图效果测评：写实、插画、排版三大方向逐一体验". 2026-04-26. https://juejin.cn/post/7632518581080604712
[^8]: CSDN. "AI绘画提速秘诀：Z-Image-Turbo亚秒级推理实测". 2026-02-02. https://blog.csdn.net/weixin_36235398/article/details/157627776
[^9]: 微信公众号. "一步步解密 AI 绘画：从噪声到高清图的扩散模型实战". 2025-08-25. http://mp.weixin.qq.com/s?__biz=MzA3NDg4MDQ0Nw==&mid=2650693108
[^10]: Li et al. "Towards Aligned Layout Generation via Diffusion Model with Aesthetic Constraints". arXiv:2402.04754v2, 2024.
[^11]: GeoSVG-RL. "GeoSVG-RL: Geometry-Aware Reinforcement Learning for Layout-Constrained Text-to-SVG Diagram Generation". arXiv:2605.25447v1, 2026-05-25.
[^12]: Sordo et al. "Computer-Aided Layout Generation for Building Design: A Review". arXiv:2504.09694v1, 2025.
[^13]: upuply. "A Deep Guide to Adobe Illustrator Vector Art in the Age of AI Generation Platforms". 2025-11-29. https://www.upuply.com/blog/adobe-illustrator-vector-art
[^14]: putracetol. "Bitmap or Vector? The Complete Guide for Designers". 2025-10-19. https://putracetol.com/bitmap-vector/
[^15]: ACM. "A Comparative Study of Text-to-SVG Generation Techniques". 2026-04-19. https://dl.acm.org/doi/10.1145/3795926.3795973
[^16]: Xing et al. "Empowering LLMs to Understand and Generate Complex Vector Graphics". CVPR 2025. https://openaccess.thecvf.com/content/CVPR2025/papers/Xing_Empowering_LLMs_to_Understand_and_Generate_Complex_Vector_Graphics_CVPR_2025_paper.pdf
[^17]: StarVector. https://starvector.github.io/
[^18]: LobeHub. "Kroki Diagram API: Unified HTTP endpoint for 20+ text-based diagram formats". 2026-05-15. https://lobehub.com/it/skills/wentorai-research-plugins-kroki-diagram-api
[^19]: D2 Docs. "How does this compare to Mermaid, Graphviz, PlantUML?" https://d2lang.com/tour/faq/
[^20]: Simmering. "Diagrams as Code: Supercharged by AI Assistants". 2024-12-28. https://simmering.dev/blog/diagrams/
[^21]: 掘金. "程序员最强AI画图工具大全!". 2026-03-15. https://juejin.cn/post/7616943516187262976
[^22]: ProcessOn. "简单3步用AI快速生成架构图-对话式交互，可持续优化". 2026-01-23. https://www.processon.com/knowledge/aijiagoutu
[^23]: 字节跳动开发者社区. "Claude 3.7一键生成系统架构图：技术人的效率神器". 2025-07-21. https://developer.volcengine.com/articles/7529428219703853107
[^24]: GitHub i2mint/ij. "Python libraries enable programmatic diagram generation". https://github.com/i2mint/ij/discussions/1
[^25]: Sengupta. "Automated Text Rectification in AI-Generated Visual Content". TechRxiv, 2025. https://www.techrxiv.org/doi/pdf/10.36227/techrxiv.174319638.82772972
[^26]: PaddlePaddle. "Chinese OCR help". GitHub Discussions, 2025-01-07. https://github.com/PaddlePaddle/PaddleOCR/discussions/14507
[^27]: HUAWEI CLOUD. "From Recognition to Business Insight". https://www.huaweicloud.com/intl/en-us/cloudplus/fourthphase/detail_09.html
[^28]: Veninga. "LLMs for OCR Post-Correction". UT Student Theses. https://essay.utwente.nl/fileshare/file/102117/Veninga_MA_EEMCS.pdf
[^29]: Tuo et al. "AnyText: Multilingual Visual Text Generation and Editing". arXiv:2311.03054, 2024-02-21.
[^30]: Tuo et al. "AnyText2: Visual Text Generation and Editing With Customizable Attributes". arXiv:2411.15245, 2024.
[^31]: CharGen. "CharGen: High Accurate Character-Level Visual Text Generation Model with MultiModal Encoder". arXiv:2412.17225, 2024.
[^32]: FonTS. "FonTS: Text Rendering with Typography and Style Controls". arXiv:2412.00136v2, 2024.
[^33]: 优设AIGC. "高手都在用 AI 做字体设计了！这 5 个神器你一定要了解". 2024-09-18. https://www.uisdc.com/ai-font
[^34]: GlyphDraw2. "GlyphDraw2: Automatic Generation of Complex Glyph Posters with Diffusion Models and Large Language Models". arXiv:2407.02252, 2024.
