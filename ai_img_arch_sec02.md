## 2. 文生图工作流：模型选择与中文文本渲染

中文架构图生成的核心矛盾在于：模型在通用视觉生成上的能力跃升，与文本渲染精度之间存在结构性落差。根据交叉验证结果，当前主流模型在LongText-Bench-ZH基准上的表现呈现三个数量级的断层，这一分化直接决定了企业在技术选型中的可行集边界。[^1]

### 2.1 主流文生图模型中文能力对比

#### 2.1.1 第一梯队：文本精度接近工程可用阈值

在开源模型中，GLM-Image以0.9788的LongText-Bench-ZH得分居于首位，其9B自回归模块与7B扩散解码器的混合架构是这一优势的技术根基。[^1] 自回归模块负责规划文本布局与字符位置，扩散解码器负责像素级渲染，这种"先规划后绘制"的分工对架构图中多模块标签的框内对齐尤为有利。ERNIE-Image 8B在LongTextBench中英均超0.96，其单流DiT架构使文本与图像tokens共享权重，对结构化视觉任务（海报、信息图、漫画分镜）展现出原生适配性。[^4] Ovis-Image 7B在LongText-Bench-ZH上达0.964，且在CVTG-2K多区域文本基准上取得0.9200平均词准确率，2–5区域场景均保持>91%的稳定性，说明其"以文本为中心的训练配方"在标签密集型架构图中具有独特优势。[^2]

Qwen-Image系列的表现因版本而异。Qwen-Image 2.0支持1000-token复杂提示词，可生成包含流程箭头、色块编码和精确标签定位的完整信息图，其统一生成与编辑架构在图生图场景中位列编辑榜第二（Elo 1034）。[^3] 但在纯文本精度基准上，其LongText-Bench-ZH得分约0.946，略逊于GLM-Image和Ovis-Image。[^1]

#### 2.1.2 第二梯队：成本与精度的平衡方案

Z-Image Turbo 6B以16GB显存门槛和约0.01美元/张的API成本成为性价比最优解。[^11][^15] 其LongText-Bench-ZH得分0.936虽低于第一梯队，但8步推理可在H800上实现亚秒级延迟，且Apache 2.0许可支持LoRA微调，对预算敏感型团队具有显著吸引力。[^11] Boogu-Image 10B（2026年6月发布）采用Qwen3-VL-8B文本编码器，支持FP8量化，专攻"超密集文字生成"场景，但生态成熟度尚待验证。[^22]

#### 2.1.3 不可用梯队：海外模型的中文文本壁垒

FLUX.1-dev、DALL-E 3和Midjourney在中文架构图场景几乎不可用。FLUX.1-dev在LongText-Bench-ZH上的得分接近0.007，与第一梯队存在近200倍的差距。[^1] 这一断层并非模型规模不足，而是训练数据中CJK文本-图像对的结构性缺失所致。FLUX-Text研究证实，即使基于FLUX-Fill进行100K样本微调，中文Sen.Acc仅达71.32%，且原生FLUX.1-dev的非商用许可进一步限制了企业适配空间。[^17] 海外模型若要追平本土模型的中文文本能力，需投入大量CJK数据重新训练，成本极高，这一壁垒预计在短期内难以逾越。

下表汇总了各模型在中文文本渲染、部署成本和许可条款上的关键参数：

| 模型 | 参数量 | LongText-Bench-ZH | CVTG-2K (WA) | 显存需求 | 开源许可 | API成本 (1024px) |
|------|--------|-------------------|--------------|----------|----------|------------------|
| GLM-Image | 9B+7B | 0.9788 [^1] | 0.9116 [^1] | 23GB (CPU offload) [^14] | MIT | ~$0.015 [^14] |
| ERNIE-Image | 8B | >0.96 [^4] | — | 24GB (FP16) [^10] | Apache 2.0 | 未公开 |
| Ovis-Image | 7B | 0.964 [^2] | 0.9200 [^2] | ~20GB [^13] | 开源 | 未明确 |
| Qwen-Image 2.0 | 7B/20B | ~0.946 [^1] | 0.8288 [^2] | 24GB (FP8) [^6] | Apache 2.0 | $0.005–0.02 [^15] |
| Z-Image Turbo | 6B | 0.936 [^11] | — | 16GB [^11] | Apache 2.0 | ~$0.01 [^15] |
| FLUX.1-dev | 12B | ~0.007 [^1] | — | 可变 | 非商用 | 按需 |
| DALL-E 3 | — | — | — | 云端 | 闭源 | $0.04–0.08 |
| Midjourney | — | — | — | 云端 | 闭源 | $0.05–0.10 |

上表揭示了两个关键分化维度。第一，在文本精度上，开源本土模型已形成0.93–0.98的密集区间，而海外闭源模型因中文数据缺失被排除在可行集之外。第二，在显存效率上，Z-Image以16GB门槛覆盖了消费级硬件的最大公约数，而GLM-Image和ERNIE-Image的全精度方案需要23–24GB，仅适用于RTX 4090/3090级别的高端消费卡。对于技术决策者而言，这一矩阵意味着"选择模型"的决策应优先于"升级硬件"的决策——在16GB显存条件下，Z-Image的0.936得分已优于任何量化后的海外模型方案。

#### 2.1.4 模型选择矩阵：按场景推荐最优模型

不存在单一模型在所有维度上最优。GLM-Image文本精度最高但编辑能力未知；Qwen-Image 2.0编辑最强但7B精度略逊；ERNIE-Image本地部署最友好但信息图能力有限；Z-Image成本最低但质量中等。企业应将预算投入"模型路由"机制的构建，而非单一模型的极限优化。

| 应用场景 | 推荐模型 | 关键指标 | 选择理由 |
|----------|----------|----------|----------|
| 本地24GB，文本精度优先 | ERNIE-Image 8B FP16 | LongText-ZH >0.96 [^4]，显存24GB [^10] | 全精度运行无需量化，Apache 2.0可商用，结构化生成对框线对齐友好 |
| 本地16GB，成本优先 | Z-Image Turbo 6B | LongText-ZH 0.936 [^11]，显存16GB [^11] | 最低硬件门槛，支持LoRA微调，亚秒级8步推理 |
| API调用，文本精度优先 | GLM-Image | LongText-ZH 0.9788 [^1] | 开源精度第一，MIT许可，CPU offload可降至23GB |
| API复杂信息图/PPT | Qwen-Image 2.0 | 1000-token复杂提示 [^3]，原生2K | 统一生成+编辑架构，支持PPT/信息图直接输出 |
| 多标签密集型架构图 | Ovis-Image 7B | CVTG-2K 0.9200 [^2]，2–5区域>91% | 多区域文本稳定性最优，适合模块标签密集的拓扑图 |
| 批量生成，成本最低 | Z-Image Turbo / 豆包 Seedream | ~$0.01/张 [^15] | API成本最低，万级批量可享15–25%折扣 |

该矩阵表明，架构图工作流的技术选型应遵循"场景优先"原则。对于需要频繁迭代编辑的SRE团队，Qwen-Image 2.0的链式编辑能力（保留原字体/字号/风格）可降低返工成本；对于需要合规自托管的金融或政务场景，ERNIE-Image的Apache 2.0许可和全精度FP16运行是风险最低的选项；而对于需要快速验证原型或批量生成文档配图的产品团队，Z-Image Turbo的$0.01/张定价和16GB显存门槛提供了最低试错成本。值得注意的是，当架构图包含20个以上标签时，即使模型单标签准确率达97%，整体无错概率仅为(0.97)^20 ≈ 54%，这意味着"高准确率"模型在工程实践中仍可能频繁出错。因此，模型选择矩阵必须与工作流设计（如确定性文本渲染层的引入）配套使用，而非孤立依赖模型精度。

### 2.2 中文文本渲染的技术瓶颈与解决方案

#### 2.2.1 文本编码粒度：从子词到字符的结构性差距

中文文本渲染困难的根源在于文本编码器的设计范式。主流扩散模型采用BPE（Byte-Pair Encoding）将文本拆解为子词单元，这种粒度对图像生成任务过于粗糙——中文字符平均包含20–30笔画，在子词表示中笔画结构被严重模糊。ERNIE-Image团队针对这一瓶颈设计了字符感知编码器（character-aware encoder），通过专门训练CJK文本-图像对，将编码粒度下沉至字符级，从而在LongTextBench上达到中英均超0.96的准确率。[^4] Qwen-Image则采用MSRoPE（Multi-Scale Rotary Position Embedding）将文本沿图像对角线编码，使文本与图像模态的位置编码互不冲突，在密集文档图像的文本重建中展现出优于传统VAE的能力。[^21] 然而，即使采用这些优化，架构图中小标签（<20字符）的渲染仍面临固有挑战：ControlText研究表明，glyph控制嵌入层在字体非常小、非常细或非常长时会导致字体细节丢失，这解释了为何高分辨率（1280px以上）生成对保持小字清晰度至关重要。[^9] 对于架构图场景，当前业界尚未建立"<20字符短标签在方框内"的专用评测基准，现有CVTG-2K和LongText-Bench主要测试文本本身的正确性，而非文本与几何图形的组合精确性。[^5] 这一基准缺口意味着模型排名不能完全等同于架构图生成能力，企业需结合实际测试评估框线对齐度和标签定位精度。

#### 2.2.2 量化压缩对中文小字的隐性破坏

社区广泛推荐的"FP8/INT8量化让大模型在消费级显卡运行"的建议，对中文架构图场景可能是有害的。QuantDiff研究指出，在Stable Diffusion上，FP8/FP8相比INT8/INT8的质量提升达1.56倍；即使在相同位宽下，FP格式也系统性地优于INT格式。[^7] 中文小字的笔画精度对量化误差极为敏感：ERNIE-Image官方明确建议，若文本渲染是主要用例，应使用FP16/BF16而非INT8/NF4，因为量化版本"可测量地降低文本渲染质量"。[^10] FLUX.1-dev的实测数据进一步印证了这一风险：BNB NF4、FP8和INT8在低对比度小字场景均可能出现细节丢失，速度提升不等于质量保持。[^8] 对于包含"负载均衡""分布式事务"等复杂笔画的标签，量化误差可能导致笔画断裂或模糊，这一问题在端到端生成流程中无法通过后处理完全修复。

#### 2.2.3 消费级部署的最优解：ERNIE-Image 8B FP16

在24GB显存约束下，ERNIE-Image 8B FP16是当前消费级本地部署的最优解。该方案无需量化即可全精度运行，文本渲染质量无损，且Apache 2.0许可允许商用。[^10] 相比之下，Qwen-Image 20B在FP16下需约60GB VRAM，FP8量化后方可降至24GB，但存在前述的文本质量折损。[^6] Z-Image Turbo 6B虽仅需16GB，但0.936的文本精度在标签密集场景下可能不足以支撑工程可用性。[^11] 对于已拥有Qwen-Image但显存不足的用户，DiffSynth-Studio提供分层卸载方案（FP8+动态管理），但架构图的高分辨率需求（1280px以上）通常使24GB显存仍然紧张，建议开启CPU Offload组合模式。[^12] 综合评估，企业在本地部署时，若核心用例包含中文文本，应以"文本质量底线"而非"参数量上限"为核心决策标准。ERNIE-Image 8B FP16的24GB方案在质量、许可和硬件可及性之间提供了最佳平衡，预计在未来12–18个月内仍将是消费级部署的首选配置。

#### 2.2.4 架构图短标签场景的基准缺口

现有评测体系与工程需求之间存在显著错位。CVTG-2K测试的是2–5区域文本的准确性，LongText-Bench测试的是长文本段落，但架构图需要的是"标签在正确框内、箭头指向正确、布局层次清晰"的综合能力。[^5] 这意味着当前模型排名（GLM-Image > Ovis-Image > Qwen-Image > Z-Image）只能反映文本本身的正确性，不能等同于架构图生成能力。例如，Qwen-Image在CVTG-2K上仅获0.8288，低于Ovis-Image的0.9200，但在1000-token复杂提示下的信息图生成能力可能反超。[^2][^3] 这一基准缺口对技术决策者的启示是：模型选型不应仅依赖公开排行榜，而需构建内部评测集——用企业实际使用的架构图模板（如微服务拓扑、网络分层、数据流图）进行A/B测试，测量标签正确率、框线对齐度和布局一致性三项核心指标。在专用benchmark成熟之前，这种"以用例为中心的实测"是规避模型-场景错配风险的最可靠手段。

---

[^1]: GLM-Image Technical Blog, Zhipu AI, 2026-01-14. https://z.ai/blog/glm-image; DeepLearning.ai "Zhipu's GLM-Image Blends Transformer and Diffusion Architectures", 2026-02-16. https://www.deeplearning.ai/the-batch/zhipus-glm-image-blends-transformer-and-diffusion-architectures-for-better-text-in-images

[^2]: Ovis-Image Technical Report, arXiv:2511.22982, 2025-11-28. https://arxiv.org/abs/2511.22982; GitHub AIDC-AI/Ovis-Image, 2025-11-18. https://github.com/AIDC-AI/Ovis-Image

[^3]: inference.sh "Qwen-Image-2.0: Professional Infographics, Exquisite Photorealism", 2026-03-03. https://inference.sh/blog/guides/qwen-image-2-generation; WaveSpeedAI "What to Expect from Qwen Image 2.0", 2026-02-11. https://wavespeed.ai/blog/posts/blog-what-to-expect-from-qwen-image-2-0-ai-image-generation/

[^4]: Baidu ERNIE-Image GitHub, 2026-04-14. https://github.com/baidu/ernie-image; Stable-Learn "Baidu ERNIE-Image: 8B Open-Source Text-to-Image AI", 2026-04-15. https://stable-learn.com/en/baidu-ernie-image-opensource/

[^5]: ai_img_arch_wide01.md (Phase 1W 广泛探索结果), 2026-06-23. /Users/yangtb/.hermes/hermes-agent/research/ai_img_arch_wide01.md

[^6]: BotMonster "Local Image Models in 2026: Qwen vs FLUX vs SDXL on VRAM", 2026-06-08. https://botmonster.com/ai/best-local-image-generation-models-2026/; yingtu.ai "Nano Banana Pro vs Qwen-Image-2512", 2026-01-04. https://yingtu.ai/en/blog/nano-banana-pro-vs-qwen-image-2512

[^7]: QuantDiff IISWC 2024 Slides, MPI-SWS. https://people.mpi-sws.org/~cgiannoula/assets/slides/QuantDiff_iiswc24_Slides.pdf

[^8]: SDNext Wiki "Quantization", 2025-2026. https://github.com/vladmandic/sdnext/wiki/Quantization#gguf

[^9]: arXiv:2502.10999 "ControlText: Unlocking Controllable Fonts in Multilingual Text Rendering without Font Annotations", 2025-02. https://arxiv.org/pdf/2502.10999

[^10]: Baidu ERNIE-Image GitHub, 2026-04-14. https://github.com/baidu/ernie-image; ernieimage.ai "How to Install ERNIE Image Locally", 2026-04-25. https://ernieimage.ai/blog/how-to-install-ernie-image-locally

[^11]: Z-Image Technical Report, arXiv:2511.22699v1, 2025-11-11. https://arxiv.org/html/2511.22699v1; Tongyi-MAI/Z-Image GitHub, 2025-11-26. https://github.com/Tongyi-MAI/Z-Image; RunDiffusion "Z-Image Turbo", 2026-01-07. https://www.rundiffusion.com/z-image

[^12]: DiffSynth-Studio GitHub, 2025-11-18. https://github.com/modelscope/DiffSynth-Studio; CSDN "DiffSynth-Studio 显存管理", 2026-02-19. https://blog.csdn.net/u014177256/article/details/158179413

[^13]: Ovis-Image official website, 2025. https://ovisimage.org/; GitHub AIDC-AI/Ovis-Image, 2025-11-18. https://github.com/AIDC-AI/Ovis-Image

[^14]: Codersera "GLM-Image 2026: VRAM, Pricing, and Setup", 2026-05-31. https://codersera.com/blog/glm-image-complete-guide/

[^15]: Atlas Cloud "Cheapest AI Image Generation API 2026", 2026-06-12. https://www.atlascloud.ai/blog/guides/cheapest-ai-image-generation-api-2026; WaveSpeedAI "2026年AI图像生成API完整指南", 2025-12-27. https://wavespeed.ai/blog/zh-CN/posts/complete-guide-ai-image-apis-2026/

[^17]: arXiv:2505.03329 "FLUX-Text: A Simple and Advanced Diffusion Transformer Baseline for Scene Text Editing", 2025-05-06. https://arxiv.org/html/2505.03329v2

[^21]: Qwen-Image Technical Report, Alibaba, 2025-08-04. https://qianwen-res.oss-cn-beijing.aliyuncs.com/Qwen-Image/Qwen_Image.pdf

[^22]: GitHub boogu-project/Boogu-Image, 2026-06-16. https://github.com/boogu-project/Boogu-Image; Awesome-Chinese-Stable-Diffusion, 2023-07-07. https://github.com/leeguandong/Awesome-Chinese-Stable-Diffusion
