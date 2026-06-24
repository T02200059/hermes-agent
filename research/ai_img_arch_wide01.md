> 角色：AI图像生成技术调研员_维度01
> 调研时间：2026-06-23
> 主题：文生图基础模型与中文文本渲染能力

## Facet: 文生图基础模型与中文文本渲染能力

### Key Findings

- **中文文本渲染能力呈显著梯队分化**：当前模型在中文文本渲染上表现差距极大。GLM-Image以LongText-Bench-ZH 0.9788位居开源模型第一[^1]，ERNIE-Image在英中双语LongTextBench均超0.96[^2]，Ovis-Image达0.964[^3]；而FLUX.1-dev在同基准上仅0.005，几乎完全无法生成可辨识中文[^4]。
- **架构设计对CJK文本质量起决定性作用**：标准BPE（Byte-Pair Encoding）tokenization将单词切分为子词token，导致模型无法"看到"单个字母或汉字，本质是在猜测拼写。TextDiffuser-2研究显示，切换为字符级编码可将OCR准确率提升42.1个百分点（15.48%→57.58%）[^5]。Qwen-Image、ERNIE-Image、Seedream等中文强势模型均采用了专门的中文/双语文本编码器或字形特征注入机制。
- **Qwen-Image仍是20B量级的中文文本渲染标杆**：基于增强MMDiT架构，采用Qwen2.5-VL语义编码+VAE重建特征的双编码器设计，文本与图像流仅在attention阶段交叉融合。其在ChineseWord（8,105个规范汉字）和LongText-Bench上均显著领先同期模型，支持多行布局、段落语义和字体风格控制[^6][^7]。2026年2月发布的Qwen-Image-2.0将参数从20B缩减至7B，统一生成与编辑，并支持原生2K分辨率[^8]。
- **ERNIE-Image以8B参数实现"以小博大"**：百度2026年4月开源的ERNIE-Image采用单流DiT（text与image tokens共享权重），搭配ERNIE-based文本编码器和轻量Prompt Enhancer。在GenEval达0.8856，LongTextBench中英均超0.96，与数倍于己的模型竞争。24GB VRAM即可运行，并提供8步蒸馏的Turbo版本[^2][^9][^10]。
- **Ovis-Image是7B参数效率极限的代表**：阿里巴巴AIDC-AI团队于2025年11月发布的Ovis-Image在CVTG-2K（多区域英文文本）上取得0.9200平均词准确率，显著高于Qwen-Image（0.8288）和GPT4o（0.8569）；LongText-Bench-ZH达0.964，超越所有参测模型。其证明了"精心设计的以文本为中心的训练配方"比单纯堆参数更重要[^3][^11]。
- **GLM-Image开辟自回归+扩散混合路线**：智谱AI于2026年1月发布的GLM-Image采用9B自回归模块（GLM-4-9B）+ 7B扩散解码器的混合架构。在CVTG-2K平均WA 0.9116、LongText-Bench-ZH 0.9788，均位列开源第一。其自回归模块负责"规划"布局与文本结构，扩散解码器负责"绘制"像素，这种分工对需要精确信息排版的架构图场景尤为有利[^1][^12]。
- **FLUX.1中文能力极弱，但FLUX-Text微调展现了潜力**：FLUX.1-dev原生中文文本渲染几乎不可用（LongText-Bench-ZH 0.005）[^4]。然而基于FLUX-Fill的FLUX-Text框架，仅用100K样本微调，在AnyText-benchmark上取得中文Sen.Acc 71.32%，超越AnyText2的1.10%[^13]。说明基础模型架构（DiT+双编码器）具备潜力，但原生训练数据中的CJK覆盖严重不足。
- **字节Seedream系列是中文商业模型的顶尖水准**：Seedream 3.0（2025年4月）采用MMDiT+Cross-modality RoPE+混合分辨率训练，原生2K，约3秒生成[^14]。Seedream 4.0（2025年9月）统一T2I/编辑/多图组合，效率比3.0提升10倍[^15]。Seedream 5.0（2026年2月）引入"深度思考"规划器，支持100+语种、3K原生、14张参考图[^16]。其均采用自研双语LLM作为文本编码器，并结合Glyph-ByT5提取字形特征。
- **Recraft V3是英文/设计场景文本渲染的标杆，中文支持有限**：Recraft V3（2024年10月）通过训练自有OCR模型提取文本布局，再用LLM生成文本布局，最后以ControlNet-like方式注入图像生成模型。它支持任意长度文本和精确定位，在英文设计场景表现极佳，但公开资料未显示其具备与Seedream/Qwen同等级的中文渲染能力[^17][^18]。
- **GPT-4o/GPT Image 1英文极强，中文薄弱**：GPT-4o的图像生成在英文文本上表现" flawless"，LongText-Bench-EN达0.956，但中文仅0.619，存在显著的语言鸿沟[^4][^19]。OpenAI 2025年3月将GPT-4o原生图像生成引入ChatGPT，但非拉丁文本仍被官方文档列为已知挑战[^20]。
- **架构图场景的核心挑战：短文本精准度、小字清晰度、结构化布局**：互联网架构图通常需要模块标签（如"API Gateway"、"消息队列"）、技术栈标识（如"Redis"、"Kafka"）、数据流向说明。这些需求落在"多区域短文本"（CVTG-2K类型）和"结构化布局"（海报/幻灯片/信息图类型）的交叉领域。当前模型在>20字符时准确率下降，小字在高分辨率下可能模糊，且对框线、箭头的几何精确控制仍不稳定[^2][^6][^21]。
- **量化部署对文本渲染影响显著**：Qwen-Image在FP16下需约60GB VRAM，FP8可降至24GB，GGUF/Q4进一步降至8GB但会损失精细文字细节[^21][^22]。ERNIE-Image FP16约24GB，已属消费级可及。Ovis-Image和GLM-Image因参数更小，部署门槛更低[^3][^12]。

### Major Players & Sources

- **Qwen-Image / Qwen-Image-2.0 (Alibaba)**：开源中文文本渲染领导者，20B→7B MMDiT，Apache 2.0。适合需要高质量双语文本+复杂布局的海报、信息图、UI mockup场景[^6][^8][^22]。
- **ERNIE-Image (Baidu)**：2026年4月开源的8B单流DiT，Apache 2.0。以最小参数实现顶尖文本渲染，部署成本友好，是消费级硬件上的最优解之一[^2][^9][^10]。
- **Ovis-Image (Alibaba AIDC-AI)**：7B专攻文本渲染，CVTG-2K和LongText-Bench-ZH双高，是参数效率的典范[^3][^11]。
- **GLM-Image (Zhipu AI)**：9B+7B AR+Diffusion混合架构，LongText-Bench-ZH开源第一。对知识密集型、排版精确的场景（如架构图、幻灯片）有独特优势[^1][^12]。
- **Z-Image / Z-Image-Turbo (Tongyi-MAI)**：6B S3-DiT单流架构，Decoupled-DMD蒸馏实现8步推理。LongText-Bench-ZH 0.936，亚秒级H800推理，消费级16GB可运行[^4][^23]。
- **Seedream 3.0/4.0/5.0 (ByteDance)**：闭源商业模型，中文渲染顶尖，已集成至剪映/CapCut/小云雀。适合追求极致质量且接受API调用的场景[^14][^15][^16]。
- **FLUX.1 (Black Forest Labs)**：12B开源最大DiT之一，英文和通用图像质量强，但中文文本渲染原生极弱。dev版非商用许可，schnell为Apache 2.0[^13][^21][^24]。
- **Recraft V3 (Recraft AI)**：闭源设计专用模型，长文本和定位能力独特，英文设计场景标杆[^17][^18]。
- **GPT-4o / GPT Image 2 (OpenAI)**：闭源，多模态对话集成强，英文文本 flawless，中文弱[^19][^20]。
- **Stable Diffusion 3/3.5 (Stability AI)**：MMDiT架构开创者，三文本编码器（CLIP+OpenCLIP+T5）。SD3 Medium可在消费级硬件运行，但中文文本渲染能力远不如专门优化CJK的模型[^25][^26]。
- **Kolors (快手)**：基于SDXL，采用ChatGLM3-6B-Base作为双语文本编码器，支持256 tokens长提示词。中文渲染优于SD系列，但落后于Qwen/ERNIE/GLM-Image等新一代模型[^27]。
- **LongCat-Image (美团)**：MM-DiT+Single-DiT混合架构，ChineseWord 90.7分，超越所有竞品。ImgEdit 4.50（开源SOTA）[^27]。
- **Boogu-Image (Boogu Project)**：2026年6月发布的10B统一模型，Qwen3-VL-8B文本编码器，FP8量化降低部署门槛，支持超密集中英文字生成（海报、印章、文档界面）[^27]。

### Trends & Signals

- **文本渲染成为模型能力分层的"代理指标"**：前沿团队已将文本渲染（英/中）、长文本渲染、结构化内容渲染（流程图、公式、电路图）作为训练进度的默认观测指标。Nano Banana团队明确将文本渲染描述为训练进度指示器。JoyAI-Image的LongText-Bench 0.963和LongCat-Image的ChineseWord 90.7相比Seedream 4.0的58.5，在一年内拉开了30多分的差距，这种变化远早于整体感知指标（FID/CLIP）的饱和[^28]。
- **模型向"统一生成+编辑"演进**：Qwen-Image-2.0、Seedream 4.0、ERNIE-Image、Boogu-Image均将T2I和图像编辑统一为单一模型。这对架构图场景意味着：先生成框架图，再通过编辑指令局部调整模块名称或连接关系，无需重新生成整张图[^8][^15][^27]。
- **参数效率革命：小模型专精文本渲染**：Ovis-Image（7B）和ERNIE-Image（8B）在文本渲染上击败或持平20B+模型，表明训练配方和数据构成的权重正在超越纯参数规模。2026年模型发布的焦点已从"更大"转向"更专精+更轻量"[^3][^9][^11]。
- **自回归+扩散混合架构兴起**：GLM-Image（AR规划+Diffusion绘制）、NextStep-1（14B AR+157M Flow Matching head）代表新范式。自回归模块天然擅长处理离散符号（如文本token、布局指令），与架构图所需的结构化文本+几何布局高度契合[^1][^12][^27]。
- **国产硬件训练可行性得到验证**：GLM-Image是首个公开宣称完全基于华为昇腾Atlas 800T A2训练的工业级开源多模态模型，证明在美国出口限制下仍可构建竞争力模型[^12]。
- **CJK专用数据构建成为差异化壁垒**：Qwen-Image、ERNIE-Image、Seedream均强调内部构建了富含文本的图像数据集（包括合成数据、OCR标注、多模态大模型打标）。FLUX等西方模型缺乏此类数据，导致中文文本渲染能力鸿沟[^6][^14][^27]。
- **蒸馏与量化技术大幅降低部署门槛**：ERNIE-Image-Turbo（8步）、Z-Image-Turbo（8步）、Qwen-Image-Lightning（4步）等蒸馏版本使消费级GPU实时推理成为可能。FP8/INT8/INT4量化在保持可接受质量的同时，将VRAM需求从60GB+压缩至8-24GB[^2][^21][^22][^23]。

### Controversies & Conflicting Claims

- **Qwen-Image vs ERNIE-Image：谁是最佳开源中文文生图？** 两者均采用Apache 2.0。Qwen-Image-20B在DPG-Bench（88.32）和整体图像质量上领先，但ERNIE-Image（8B）在GenEval（0.8856 vs Qwen-Image 0.8683）和LongTextBench部分指标上反超，且部署成本仅约1/3。争议焦点在于：质量优先选Qwen，效率优先选ERNIE[^2][^6][^9]。
- **FLUX.1-dev许可证限制**：Black Forest Labs的dev版本采用非商用许可，禁止商业产品销售，而schnell版本质量牺牲较大。这与ERNIE-Image/Qwen-Image的完全开源商用形成鲜明对比，引发社区对"开源但非自由"模式的批评[^21][^24]。
- **评测基准的自报告可信度问题**：LLM-Stats的LongText-Bench leaderboard目前仅显示GLM-Image一家（0.966），标注为"self-reported"，且无第三方验证。多个模型在同一基准上的分数来自各自技术报告，跨报告比较存在评测条件不一致的风险[^1][^4][^28]。
- **OCR评测的局限性**：STRICT benchmark指出，当前文本渲染评测主要依赖OCR模型（如PaddleOCR、Qwen2.5-VL）提取生成图像中的文字，但OCR本身在识别艺术字体、小字、低对比度文本时也会失败。这可能导致"模型实际生成正确但OCR判错"或反之的情况，尤其影响罕见汉字和复杂书法的评估[^5][^13]。
- **GPT-4o中文文本渲染：社区体验与技术报告的矛盾**：部分中文用户反馈GPT-4o在简单中文标语上表现良好，但LongText-Bench-ZH官方数据仅0.619，远低于Seedream/Qwen/GLM-Image。可能的解释是：GPT-4o在短文本、常见字上尚可，但在长文本、罕见字、多区域布局上急剧退化，而基准测试覆盖了大量后者[^4][^19]。
- **"架构图"专用能力未被主流基准覆盖**：现有评测（ChineseWord、LongText-Bench、CVTG-2K）主要关注文本本身的正确性，而非文本与几何图形（框、线、箭头）的组合精确性。架构图需要的是"标签在正确框内、箭头指向正确、布局层次清晰"，这方面的专用benchmark尚未成熟[^21][^28]。

### Recommended Deep-Dive Areas

- **中文架构图专用Prompt Engineering与后处理管线**：研究如何为Qwen/ERNIE/GLM-Image设计最优提示词，以最大化短标签准确率、框线对齐度和层次布局稳定性。同时探索SVG/Mermaid代码生成+AI渲染的混合工作流，绕开纯像素生成的几何不精确问题。
- **量化对中文小字渲染的影响量化**：系统评估FP16→FP8→INT4→GGUF Q4过程中，中文模块标签（如"负载均衡"、"分布式事务"）的保真度变化，建立VRAM-质量权衡的精确曲线，为消费级部署提供决策依据。
- **FLUX-Text/AnyText2/Glyph-ByT5-V2的中文微调生态**：虽然FLUX.1原生中文弱，但其社区微调方案（FLUX-Text、EasyText LoRA）在有限数据下取得显著改善。深入调研这些方案在架构图短文本场景上的实际表现、训练成本与商用合规性。
- **自回归+扩散混合架构在结构化图表生成上的潜力**：GLM-Image和NextStep-1的混合架构使模型先"规划"后"绘制"，天然适合架构图这类需要强结构约束的场景。值得深入测试其在复杂系统拓扑（如微服务架构、云原生部署图）上的表现。
- **Seedream 5.0/ERNIE-Image的API vs 本地部署成本分析**：对比字节Seedream API定价、ERNIE-Image本地部署（24GB VRAM）的TCO（总拥有成本），以及Qwen-Image通过DiffSynth-Studio的4GB层卸载方案，评估不同规模团队的最优选择。
- **多模型协作管线**：针对架构图的不同元素（几何框线由代码生成、装饰性背景由FLUX生成、中文标签由Qwen/ERNIE生成），设计多模型分工+图像合成的混合管线，可能比单一模型更可靠。

---

[^1]: GLM-Image Technical Blog, Zhipu AI, 2026-01-14. https://z.ai/blog/glm-image; DeepLearning.ai "Zhipu's GLM-Image Blends Transformer and Diffusion Architectures", 2026-02-16. https://www.deeplearning.ai/the-batch/zhipus-glm-image-blends-transformer-and-diffusion-architectures-for-better-text-in-images
[^2]: Baidu ERNIE-Image Official Repo, 2026-04-15. https://github.com/baidu/ernie-image; Stable-Learn "Baidu ERNIE-Image: 8B Open-Source Text-to-Image AI", 2026-04-15. https://stable-learn.com/en/baidu-ernie-image-opensource/; TestingCatalog "Baidu's ERNIE-Image goes open source", 2026-04-17. https://testingcatalog.net/baidus-ernie-image-goes-open-source-promising-better-text-rendering-and-complex-layouts/
[^3]: Ovis-Image Technical Report, arXiv:2511.22982, 2025-11-28. https://arxiv.org/abs/2511.22982; ComfyUI-Wiki "Alibaba AIDC-AI Releases Ovis-Image", 2026-01-28. https://comfyui-wiki.com/en/news/2025-11-29-ovis-image-7b-text-to-image
[^4]: Z-Image Technical Report, https://zimage.net/Z_Image_Report.pdf; LLM-Stats LongText-Bench Leaderboard, 2026-06-02. https://llm-stats.com/benchmarks/longtext-bench
[^5]: NestContent "Text to Image AI: 15 Generators Tested and Ranked", 2026-04-12. https://nestcontent.com/blog/text-to-image-ai; Chen et al. TextDiffuser-2 (ICCV 2025)
[^6]: Qwen-Image Technical Report, Alibaba, 2025-08-04. https://qianwen-res.oss-cn-beijing.aliyuncs.com/Qwen-Image/Qwen_Image.pdf; QwenLM Blog "Qwen-Image: Crafting with Native Text Rendering", 2025-08-04. https://qwenlm.github.io/blog/qwen-image/
[^7]: AInvest "Alibaba Unveils Qwen-Image", 2025-09-04. https://www.ainvest.com/news/alibaba-unveils-qwen-image-revolutionary-20b-image-model-advanced-text-rendering-capabilities-2509/
[^8]: WaveSpeedAI "What Is Qwen Image 2.0?", 2026-02-11. https://wavespeed.ai/blog/posts/blog-what-is-qwen-image-2-0-features-benchmarks/
[^9]: Miraflow.ai "ERNIE-Image Just Dropped: 8B Parameters, Apache 2.0", 2026-04-19. https://miraflow.ai/blog/ernie-image-8b-apache-2-best-text-rendering-open-source
[^10]: Quasa.io "Baidu Drops ERNIE-Image: A Compact 8B Open-Source Text-to-Image Model", 2026-04-20. https://quasa.io/media/baidu-drops-ernie-image-a-compact-8b-open-source-text-to-image-model-that-tops-the-charts
[^11]: Liner Review "Ovis-Image Technical Report Quick Review", 2025-11-28. https://liner.com/review/ovisimage-technical-report; Eachlabs "Ovis Image", 2026-02-20. https://www.eachlabs.ai/openvision/ovis/ovis-image
[^12]: Stable-Learn "GLM-Image: First Open-Source Industrial-Grade Autoregressive Generation", 2026-01-15. https://stable-learn.com/en/glm-image-autoregressive-generation/; WaveSpeedAI "Introducing Z AI Glm Image", 2026-01-16. https://wavespeed.ai/blog/posts/introducing-z-ai-glm-image-text-to-image-on-wavespeedai/
[^13]: arXiv:2505.03329 "FLUX-Text: A Simple and Advanced Diffusion Transformer Baseline for Scene Text Editing", 2025-05-06. https://arxiv.org/html/2505.03329v1
[^14]: Seedream 3.0 Technical Report, arXiv:2504.11346, 2025-04-15. https://arxiv.org/html/2504.11346v1; Seedream Blog "Seedream 3.0 Technical Report Released", 2025-04-16. https://seed.bytedance.com/en/blog/seedream-3-0-text-to-image-model-technical-report-released
[^15]: Seedream 4.0 Technical Report, arXiv:2509.20427, 2025-09. https://arxiv.org/html/2509.20427v3
[^16]: GitHub leeguandong/Awesome-Chinese-Stable-Diffusion (compiled community info on Seedream 5.0). https://github.com/leeguandong/Awesome-Chinese-Stable-Diffusion
[^17]: Recraft AI Blog "How to create SOTA image generation with text", 2024-11-07. https://www.recraft.ai/blog/how-to-create-sota-image-generation-with-text-recrafts-ml-team-insights
[^18]: Recraft V3 Docs, 2026-05-28. https://www.recraft.ai/docs/recraft-models/recraft-V3; Replicate "recraft-ai/recraft-v3", 2025-10-30. https://replicate.com/recraft-ai/recraft-v3
[^19]: OpenAI-4o-Image-Generation "GPT-4o Image Generation Compared with Top AI Competitors", 2026-01-11. https://openai-4o-image-generation.pages.dev/posts/gpt-4o-image-generation-features-benchmarks-competitors/
[^20]: OpenAI-4o-Image-Generation "Troubleshooting Tips and FAQs", 2026-01-08. https://openai-4o-image-generation.pages.dev/posts/gpt-4o-image-generation-troubleshooting-faqs/
[^21]: BotMonster "Local Image Models in 2026: Qwen vs FLUX vs SDXL on VRAM", 2026-06-08. https://botmonster.com/ai/best-local-image-generation-models-2026/; WillItRunAI "Qwen Image VRAM Requirements", 2025-07-15. https://www.willitrunai.com/pt-BR/image-models/qwen-image
[^22]: Spheron "Qwen-Image-Bench VRAM Requirements", 2026-05-28. https://www.spheron.network/tools/gpu-recommender/Qwen/Qwen-Image-Bench/
[^23]: Z-Image Technical Report. https://zimage.net/Z_Image_Report.pdf; vLLM-Omni "Text-To-Image" docs (GPU requirements). https://docs.vllm.ai/projects/vllm-omni/en/latest/user_guide/examples/offline_inference/text_to_image/
[^24]: OfflineCreator "Flux Review: 12B Open-Weight Image Model", 2026-03-08. https://offlinecreator.com/tool/flux
[^25]: Stability AI "Stable Diffusion 3: Research Paper", 2024-03-05. https://stability.ai/news-updates/stable-diffusion-3-research-paper
[^26]: 10b.ai "Flux 1.1 vs Stable Diffusion 3", 2025-12-08. https://10b.ai/blog/flux-1-1-vs-stable-diffusion-3
[^27]: GitHub leeguandong/Awesome-Chinese-Stable-Diffusion (compiled overview of Chinese T2I models). https://github.com/leeguandong/Awesome-Chinese-Stable-Diffusion
[^28]: arXiv:2604.28185 "Visual Generation in the New Era: An Evolution from Atomic Mapping to Agentic World Modeling", 2026-04-30. https://arxiv.org/html/2604.28185v1
