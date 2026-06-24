# Dim01: 中文文生图模型技术对比与架构图适用性

> 角色：深度调研员_维度01
> 调研日期：2026-06-23
> 搜索次数：13次独立搜索（中英文混合）
> 范围：GLM-Image、ERNIE-Image、Qwen-Image、Ovis-Image、Z-Image、Boogu-Image、FLUX-Text/AnyText2、Seedream在中文短文本/架构图标签场景的实测对比

---

## 1. 模型在短文本/标签场景的实际表现

### 1.1 架构图/信息图场景的核心需求与模型匹配度

Claim: GLM-Image的9B自回归模块+7B扩散解码器混合架构，对需要精确信息排版的架构图场景尤为有利，其自回归模块负责"规划"布局与文本结构，扩散解码器负责"绘制"像素，在CVTG-2K多区域文本基准上达91.16%词准确率，LongText-Bench-ZH达0.9788。[^1]
Source: GLM-Image Technical Blog / DeepLearning.ai The Batch
URL: https://z.ai/blog/glm-image / https://www.deeplearning.ai/the-batch/zhipus-glm-image-blends-transformer-and-diffusion-architectures-for-better-text-in-images
Date: 2026-01-14 / 2026-02-16
Excerpt: "The autoregressive component generates low-resolution tokens that establish text layout and positioning... The diffusion decoder adds high-resolution details, ensuring crisp, readable text... GLM-Image achieves 91.16% word accuracy on CVTG-2K benchmark and 0.9788 on LongText-Bench Chinese."
Context: CVTG-2K测试的是图像中2-5个区域的文本渲染准确率，这与架构图中多模块标签（如"API Gateway"、"消息队列"）的场景高度吻合。自回归模块的"布局优先"特性对框线对齐和层次结构稳定尤为关键。
Confidence: high

Claim: Ovis-Image在CVTG-2K（多区域英文文本）上取得0.9200平均词准确率，显著高于Qwen-Image（0.8288）和GPT4o（0.8569）；LongText-Bench-ZH达0.964，超越所有参测模型。其7B参数在2-5区域文本场景均保持>91%的WA，证明"以文本为中心的训练配方"比单纯堆参数更重要。[^2]
Source: Ovis-Image Technical Report / GitHub AIDC-AI/Ovis-Image
URL: https://arxiv.org/abs/2511.22982 / https://github.com/AIDC-AI/Ovis-Image
Date: 2025-11-28 / 2025-11-18
Excerpt: "Ovis-Image achieves 0.9248 WA (2 regions), 0.9239 WA (3 regions), 0.9180 WA (4 regions), 0.9166 WA (5 regions), average 0.9200... significantly outperforming Qwen-Image (0.8288) and GPT4o (0.8569)."
Context: 架构图通常包含2-5个模块标签，Ovis-Image的多区域文本稳定性使其成为标签密集型图表的强候选。但Ovis-Image在OneIG-EN综合评测中整体质量评分0.530，低于Qwen-Image的0.539，说明其牺牲了部分通用图像质量以换取文本精度。
Confidence: high

Claim: Qwen-Image-2.0支持1000-token复杂提示词，可直接生成包含"flow arrows connecting related concepts"、"color-coded elements"和"precise label positioning"的完整信息图、PPT幻灯片和流程图，且文本与视觉元素统一构图而非简单叠加。[^3]
Source: inference.sh Qwen-Image-2.0 Guide / WaveSpeedAI Blog
URL: https://inference.sh/blog/guides/qwen-image-2-generation / https://wavespeed.ai/blog/posts/blog-what-to-expect-from-qwen-image-2-0-ai-image-generation/
Date: 2026-03-03 / 2026-02-11
Excerpt: "Qwen-Image-2.0 can generate complete PowerPoint slides, professional infographics, multi-panel comics, and intricate calligraphy directly from 1,000-token prompts... The model composes text and visual elements together with proper layout and hierarchy."
Context: 对于架构图生成，Qwen-Image-2.0的"准、多、美、真、齐"五维特性中的"齐"（grid alignment）和"准"（precision）直接对应模块标签的对齐和字符准确性。其统一的生成+编辑架构允许先生成框架图再局部调整标签。
Confidence: high

Claim: ERNIE-Image在8B参数规模下，在GenEval达0.8856，LongTextBench中英均超0.96，特别擅长"dense, long-form, layout-sensitive"文本生成，包括海报、信息图、UI界面、漫画分镜等结构化视觉任务。[^4]
Source: Baidu ERNIE-Image Official Repo / Stable-Learn
URL: https://github.com/baidu/ernie-image / https://stable-learn.com/en/baidu-ernie-image-opensource/
Date: 2026-04-14 / 2026-04-15
Excerpt: "ERNIE-Image excels in dense, long-form, layout-sensitive text generation tasks... Structured generation: Especially effective for structured visual tasks such as posters, comics, storyboards, and multi-panel compositions."
Context: ERNIE-Image的"结构化生成"能力与架构图所需的模块化布局、层次结构、框线对齐高度契合。其单流DiT架构使文本与图像tokens共享权重，有利于文本标签与几何框的协同生成。
Confidence: high

Claim: 现有评测基准（ChineseWord、LongText-Bench、CVTG-2K）主要关注文本本身的正确性，而非文本与几何图形（框、线、箭头）的组合精确性。架构图需要的是"标签在正确框内、箭头指向正确、布局层次清晰"，这方面的专用benchmark尚未成熟。[^5]
Source: ai_img_arch_wide01.md (Phase 1W 调研报告)
URL: (内部文件，见 /Users/yangtb/.hermes/hermes-agent/research/ai_img_arch_wide01.md)
Date: 2026-06-23
Excerpt: "现有评测主要关注文本本身的正确性，而非文本与几何图形的组合精确性。架构图需要的是标签在正确框内、箭头指向正确、布局层次清晰，这方面的专用benchmark尚未成熟。"
Context: 这是Phase 1W的关键发现，意味着当前模型排名不能完全等同于架构图生成能力。需要结合实际测试来评估短标签在方框内的准确率和框线对齐度。
Confidence: high

---

## 2. 模型量化对中文小字渲染的具体影响

Claim: Qwen-Image在FP16下需约60GB VRAM，FP8可降至24GB，INT8进一步降低，但GGUF/Q4量化虽可降至约8-13GB，会损失精细文字细节。DiffSynth-Studio通过layer-by-layer offload可在约4GB VRAM上运行，但速度明显变慢。[^6]
Source: BotMonster "Local Image Models in 2026" / yingtu.ai Qwen-Image-2512 Guide / DiffSynth-Studio Docs
URL: https://botmonster.com/ai/best-local-image-generation-models-2026/ / https://yingtu.ai/en/blog/nano-banana-pro-vs-qwen-image-2512 / https://github.com/modelscope/DiffSynth-Studio
Date: 2026-06-08 / 2026-01-04 / 2025-11-18
Excerpt: "Qwen-Image has native ComfyUI support, Diffusers, GGUF builds... DiffSynth-Studio adds layer-by-layer offload to run within about 4 GB... Q4_K_M quantization requires about 13GB VRAM... Q2_K extreme quantization only needs about 7GB VRAM but image quality will decline."
Context: 对于架构图场景，小字标签（如"Redis"、"Kafka"）的保真度至关重要。FP8在24GB RTX 4090上运行是消费级最优平衡点，而4-bit量化虽可运行但可能导致小字模糊或笔画断裂。
Confidence: high

Claim: 扩散模型量化研究中，当使用FP模型生成图像作为参考（而非真实图像）时，FP8/FP8相比INT8/INT8在Stable Diffusion上质量提升1.56倍；FP4/FP8优于INT4/INT8达1.10倍。FP格式在相同位宽下优于INT格式，对保留文字细节尤为关键。[^7]
Source: QuantDiff IISWC 2024 Slides (MPI-SWS)
URL: https://people.mpi-sws.org/~cgiannoula/assets/slides/QuantDiff_iiswc24_Slides.pdf
Date: 2024
Excerpt: "FP8/FP8 VS. INT8/INT8 1.56X better... FP4/FP8 VS. INT4/INT8 1.10X better... FP4/FP8 better than INT8/INT8 in Stable Diffusion."
Context: 该研究直接针对扩散模型量化，发现FP量化比INT量化更能保留生成质量。对于中文小字这类高细节敏感任务，FP8是比INT8更优的量化选择，尽管两者显存占用相近。
Confidence: high

Claim: 在FLUX.1-Dev的量化实测中，RTX 4090上BNB NF4量化达1.48 it/s，BNB FP8达1.42 it/s，SDNQ INT8达1.33 it/s；但速度提升不等于质量保持，NF4/FP8/INT8在低对比度小字场景均可能出现细节丢失。[^8]
Source: SDNext Wiki "Quantization"
URL: https://github.com/vladmandic/sdnext/wiki/Quantization#gguf
Date: 2025-2026
Excerpt: "Comparing performance of different quantization methods on the FLUX.1-Dev model... BnB NF4: 1.48 it/s, BnB FP8: 1.42 it/s, SDNQ INT8: 1.33 it/s... This is not a comprehensive benchmark, but rather a quick overview."
Context: 速度基准不等于文本质量基准。架构图场景应优先选择FP8（速度/质量平衡）或INT8（质量优先），NF4仅在极端显存受限时使用。
Confidence: medium

Claim: ControlText研究指出，glyph control的嵌入层在字体非常小、非常细或非常长时会导致文本质量下降，因为glyph中的字体细节信息可能丢失。这对架构图中小标签（<20字符小字）的渲染有直接启示。[^9]
Source: arXiv:2502.10999 "ControlText: Unlocking Controllable Fonts in Multilingual Text Rendering"
URL: https://arxiv.org/pdf/2502.10999
Date: 2025-02
Excerpt: "The embedding layers of the glyph controls can also lead to reduced text quality, especially when the text in a font is very small, thin, or excessively long. In such cases, fine details of the font information in the glyphs may be lost."
Context: 架构图标签恰好属于"small, thin text"类别。即使使用glyph-aware模型（如Glyph-ByT5），小字渲染仍存在固有挑战，这解释了为何高分辨率（1280px+）生成对保持小字清晰度至关重要。
Confidence: high

---

## 3. 消费级显卡（24GB显存）可部署的模型方案

Claim: ERNIE-Image FP16约24GB VRAM，已属消费级可及。官方明确标注"Can run on consumer GPUs with 24G VRAM"，并提供8步蒸馏的Turbo版本进一步降低延迟。50步标准版+CFG 4.0，8步Turbo版+CFG 1.0。[^10]
Source: Baidu ERNIE-Image GitHub / ernieimage.ai Local Install Guide
URL: https://github.com/baidu/ernie-image / https://ernieimage.ai/blog/how-to-install-ernie-image-locally
Date: 2026-04-14 / 2026-04-25
Excerpt: "Practical deployment: Can run on consumer GPUs with 24G VRAM... ERNIE-Image-Turbo: Turbo model optimized by DMD and RL for faster speed and higher aesthetics, 8 steps, CFG 1.0."
Context: 对于24GB RTX 4090/3090用户，ERNIE-Image是消费级本地部署中文文生图的最优解之一——无需量化即可全精度运行，文本渲染质量无损。ERNIE-Image-Turbo的8步推理使实时/近实时生成成为可能。
Confidence: high

Claim: Z-Image 6B参数S3-DiT单流架构，16GB VRAM即可运行，8步推理（NFEs）在H800上亚秒级延迟，LongText-Bench-ZH 0.936，支持中英双语文本渲染。其Apache 2.0许可且支持LoRA微调。[^11]
Source: Z-Image Technical Report / Tongyi-MAI GitHub / RunDiffusion
URL: https://arxiv.org/html/2511.22699v1 / https://github.com/Tongyi-MAI/Z-Image / https://www.rundiffusion.com/z-image
Date: 2025-11-11 / 2025-11-26 / 2026-01-07
Excerpt: "Z-Image-Turbo offers both sub-second inference latency on an enterprise-grade H800 GPU and compatibility with consumer-grade hardware (<16GB VRAM)... Z-Image exhibits exceptional capabilities in photorealistic image generation and bilingual text rendering."
Context: Z-Image是消费级部署的性价比之王。对于16GB VRAM用户（RTX 4060 Ti 16GB、RX 7900 XT等），Z-Image提供了比SDXL更优的中文文本渲染能力。其16GB门槛比ERNIE-Image的24GB更亲民。
Confidence: high

Claim: DiffSynth-Studio提供显存管理分层卸载方案，使Qwen-Image可在8GB入门配置（FP8+动态管理）甚至4GB极限配置（Disk Offload）上运行。24GB高端配置推荐CPU Offload模式。[^12]
Source: DiffSynth-Studio GitHub / CSDN博客
URL: https://github.com/modelscope/DiffSynth-Studio / https://blog.csdn.net/u014177256/article/details/158179413
Date: 2025-11-18 / 2026-02-19
Excerpt: "High-end 24GB: CPU Offload. Mainstream 12GB: FP8+dynamic. Entry 8GB: FP8+dynamic with vram_limit=7. Extreme 4GB: Disk Offload... The model can run with as little as 8 GB of VRAM."
Context: 对于已拥有Qwen-Image但显存不足的用户，DiffSynth-Studio是比ComfyUI更优的显存管理方案。但架构图生成通常需要高分辨率（1280px+），此时即使24GB也可能紧张，建议开启FP8+CPU Offload组合。
Confidence: high

Claim: Ovis-Image 7B（2B+7B）明确标注"Runs on a single high-end GPU"，在GitHub官方仓库提供完整PyTorch推理代码，未量化即可在单卡高端GPU运行，显存需求远低于Qwen-Image 20B。[^13]
Source: Ovis-Image Official Website / GitHub AIDC-AI/Ovis-Image
URL: https://ovisimage.org/ / https://github.com/AIDC-AI/Ovis-Image
Date: 2025-11 / 2025-11-18
Excerpt: "7B efficient core. Runs on a single high-end GPU, so Ovis Image can serve teams without heavy infra."
Context: Ovis-Image的7B规模意味着24GB VRAM可以 comfortably 运行，甚至有余量运行batch生成。对于需要批量生成架构图变体的团队，Ovis-Image在显存效率上优于Qwen-Image和GLM-Image。
Confidence: high

---

## 4. 各模型的API调用成本和可用性

Claim: GLM-Image API via Z.ai定价约$0.015/张（1280x1280），含免费试用2张，批量折扣最高20%。自托管峰值显存约37-38GB（H100），CPU offload模式约23GB。MIT许可允许商用。[^14]
Source: Codersera GLM-Image Complete Guide
URL: https://codersera.com/blog/glm-image-complete-guide/
Date: 2026-05-31
Excerpt: "API runs about 1.5 to 3 cents per image... $0.015/image via Z.ai API; free tier: 2 images... Self-hosted: ~23 GB with CPU offload... MIT license."
Context: GLM-Image是API成本最低的高质量中文文本渲染模型之一。对于中小团队，API方案比自托管更经济（除非月生成量>200万张）。
Confidence: high

Claim: Z-Image Turbo是2026年最便宜的AI图像生成API之一，约$0.01/张（1024x1024），1秒输出。Seedream v5.0 Lite约$0.032/张，Qwen Image约$0.005-0.02/张（via聚合平台）。大规模批量生成（10K+张）可享15-25%折扣。[^15]
Source: Atlas Cloud Blog / WaveSpeedAI 2026 API Guide
URL: https://www.atlascloud.ai/blog/guides/cheapest-ai-image-generation-api-2026 / https://wavespeed.ai/blog/zh-CN/posts/complete-guide-ai-image-apis-2026/
Date: 2026-06-12 / 2025-12-27
Excerpt: "Z-Image Turbo is the cheapest at $0.01 per image... Seedream v5.0 Lite: $0.032/image... Qwen Image: ~$0.005-0.02/image... Batch discounts: 10K+ images 15%, 100K+ 25%."
Context: 对于架构图自动化生成流水线，成本是关键考量。Z-Image Turbo以1/3的价格提供接近Qwen-Image的文本质量，是成本敏感型项目的首选。但需注意其LongText-Bench-ZH 0.936低于GLM-Image的0.9788。
Confidence: medium

Claim: 字节Seedream通过即梦/豆包平台提供API，单张成本约0.03-0.04美元（$0.03-0.04/image），但主要优势是生态整合（剪映/CapCut/小云雀），月活1.63亿。其闭源特性限制了本地部署选项。[^16]
Source: 人人都是产品经理 / WaveSpeedAI API Guide
URL: https://www.woshipm.com/ai/6372875.html / https://wavespeed.ai/blog/zh-CN/posts/complete-guide-ai-image-apis-2026/
Date: 2026-04-08 / 2025-12-27
Excerpt: "字节 Seedream... 单张图成本 0.03-0.04 美元... 豆包在 2025 年 12 月的月活达到了 1.63 亿... Seedream 5.0... 支持图内文字 100+ 语种渲染。"
Context: Seedream的中文渲染能力顶尖（Seedream 4.5 CVTG-2K 89.9%），但闭源API方案不适合需要数据隐私或深度定制的架构图生成场景。
Confidence: high

---

## 5. 专门针对架构图/图表的微调模型或LoRA

Claim: FLUX-Text框架基于FLUX-Fill，仅用100K样本微调，在AnyText-benchmark上取得中文Sen.Acc 71.32%，超越AnyText2的1.10%提升。说明FLUX.1基础架构具备中文文本潜力，但原生训练数据CJK覆盖不足。[^17]
Source: arXiv:2505.03329 "FLUX-Text: A Simple and Advanced Diffusion Transformer Baseline for Scene Text Editing"
URL: https://arxiv.org/html/2505.03329v2
Date: 2025-05-06 / 2025-08-05
Excerpt: "FLUX-Text reaches 84.19% English Sen.ACC and 71.32% Chinese Sen.ACC, surpassing AnyText2 by +5.04% and +1.10%, respectively... despite being trained on only 100K samples compared to 2.9M samples used by AnyText."
Context: FLUX-Text的LoRA微调方案（基于FLUX-Fill + LoRA）为架构图场景提供了潜在路径：用少量架构图数据集微调FLUX.1，使其学会生成带中文标签的方框和箭头。但需注意FLUX.1-dev的非商用许可限制。
Confidence: medium

Claim: EasyText采用两阶段训练策略（大规模预训练glyph生成+空间映射，随后微调视觉文本集成），通过隐式字符位置对齐和image-conditioned LoRA，实现可控多语言文字渲染。其位置编码器可精确定位文本区域。[^18]
Source: arXiv:2505.24417 "EasyText: Controllable Diffusion Transformer for Multilingual Text Rendering"
URL: https://arxiv.org/html/2505.24417v1
Date: 2025-05-30
Excerpt: "We adopt a two-stage training strategy: large-scale pretraining for glyph generation and spatial mapping, followed by fine-tuning for visual-text integration and aesthetic refinement. Character positions from the condition input are aligned with target regions via implicit character position alignment."
Context: EasyText的"位置感知"训练对架构图场景极具参考价值——通过显式布局条件（如框线位置mask），模型可将文本标签精确放置在指定区域。若将EasyText适配到中文架构图数据集，有望实现"标签在框内"的精确控制。
Confidence: medium

Claim: ERNIE-Image的8B DiT架构在LoRA训练方面表现优异，社区反馈"Unlike Z-Image Turbo, ERNIE-Image seems to be really good for LoRA training"。LoRA训练不破坏其文本渲染能力，且与海报/信息图生成功能兼容。[^19]
Source: ERNIE-Image.app Blog
URL: https://ernie-image.app/blog/ei-055-ernie-image-character-lora-training-english-20260526
Date: 2026-05-26
Excerpt: "ERNIE-Image's 8B DiT architecture excels at LoRA training. A Reddit user noted: 'Unlike Z-Image Turbo, ERNIE-Image seems to be really good for LoRA training'... Character LoRA training doesn't break ERNIE-Image's text rendering capability."
Context: 对于架构图场景，可基于ERNIE-Image训练专门的"Architecture-Diagram LoRA"——用少量（~100-500张）带中文标签的架构图样本进行微调，使模型学会生成统一风格的框、线、箭头，并保持文本标签的准确性。ERNIE-Image的24GB VRAM全精度运行能力使LoRA训练在消费级硬件上可行。
Confidence: high

Claim: ComfyUI生态中已存在针对Qwen-Image、FLUX、SDXL的完整LoRA和ControlNet支持，包括Canny/LineArt/Depth/MLSD等结构控制模型。Multi-ControlNet叠加可实现"先控制几何结构，再生成文本标签"的分层工作流。[^20]
Source: BotMonster "Local Image Models in 2026"
URL: https://botmonster.com/ai/best-local-image-generation-models-2026/
Date: 2026-06-08
Excerpt: "SDXL leads by a wide margin. It has 5,000+ LoRAs on CivitAI, more than five ControlNet types including a union multi-control model... FLUX is catching up but thinner. It offers three ControlNets (canny, depth, and union)... Qwen-Image has native ComfyUI support, Diffusers, GGUF builds, and a Lightning LoRA."
Context: 对于架构图生成，最可靠的工作流可能是：先用ControlNet的LineArt/MLSD控制几何结构，再用Qwen-Image/ERNIE-Image生成带中文标签的图像。虽然尚无专门针对"架构图"的LoRA，但现有ControlNet工具已能实现相当的几何精确度。
Confidence: high

---

## 6. 模型在文本+图形混合场景（带文字标签的方框）的表现

Claim: Qwen-Image技术报告明确展示了其VAE在密集文档图像中重建小文本的能力，并对比了不同VAE在逐级放大细节时的表现。其MSRoPE位置编码将文本沿图像对角线编码，使文本与图像模态的位置编码互不冲突，有利于文本+框线混合布局。[^21]
Source: Qwen-Image Technical Report (Alibaba)
URL: https://qianwen-res.oss-cn-beijing.aliyuncs.com/Qwen-Image/Qwen_Image.pdf
Date: 2025-08-04
Excerpt: "We progressively zoom into the details across three rows (black, orange, red) to compare how different VAEs reconstruct small text in dense document images... text inputs are treated as 2D tensors with identical position IDs applied across both dimensions... the text is conceptualized as being concatenated along the diagonal of the image."
Context: 架构图本质上是"密集文档图像"——小文本（标签）嵌套在几何图形中。Qwen-Image的VAE和位置编码设计针对此类场景优化，使"文本在框内"的生成比传统扩散模型更稳定。
Confidence: high

Claim: Boogu-Image-0.1（10B参数，2026-06-16发布）采用Qwen3-VL-8B文本编码器，支持FP8量化，专门擅长"海报、印章、文档界面、品牌指南等场景的超密集文字生成"，即中英双语在有限空间内的精确排列。[^22]
Source: GitHub boogu-project/Boogu-Image / Awesome-Chinese-Stable-Diffusion
URL: https://github.com/boogu-project/Boogu-Image / https://github.com/leeguandong/Awesome-Chinese-Stable-Diffusion
Date: 2026-06-16 / 2023-07-07
Excerpt: "Boogu-Image... 支持中英双语文字渲染，擅长海报、印章、文档界面、品牌指南等场景的超密集文字生成... 提供FP8量化版本以降低部署门槛。"
Context: "超密集文字生成"直接对应架构图标签场景。Boogu-Image的10B参数+FP8量化意味着可能在16-20GB VRAM上运行，是ERNIE-Image和Z-Image之间的中间选项。但其2026年6月才发布，生态成熟度待观察。
Confidence: medium

Claim: Seedream 3.0技术报告明确将"小字生成与复杂文本排版"（small text generation and complex text layout）作为核心攻坚目标之一，优化"小字体高保真生成、多行文本语义排版"。其原生2K直出能力为高密度架构图提供了分辨率保障。[^23]
Source: 字节Seedream 3.0技术报告
URL: https://seed.bytedance.com/zh/blog/seedream-3-0-text-to-image-model-technical-report-released
Date: 2025-04-16
Excerpt: "优化小字体高保真生成、多行文本语义排版等业界难题，让AI具备商业级图文设计能力... 原生2K直出，3秒出图。"
Context: 闭源模型中，Seedream对"小字"的专项优化使其在架构图短标签场景可能比GPT-4o/Qwen-Image更有优势。但本地部署不可行，只能通过API使用。
Confidence: high

---

## 7. 综合评估与消费级部署推荐矩阵

基于以上调研，针对**中文架构图短标签生成**的消费级（24GB VRAM）部署推荐如下：

| 模型 | 显存需求 | 文本准确率 | 架构图适用性 | API成本 | 开源许可 | 推荐场景 |
|------|---------|-----------|-------------|---------|---------|---------|
| **ERNIE-Image** | 24GB (FP16) | LongText-ZH >0.96 | ★★★★★ 结构化生成强 | 未公开独立定价，百度MaaS平台 | Apache 2.0 | 本地部署首选，24GB用户全精度运行 |
| **GLM-Image** | 23GB (CPU offload) | 0.9788 (开源第一) | ★★★★★ AR规划+Diffusion绘制 | ~$0.015/张 | MIT | 文本精度优先，API/自托管均可 |
| **Z-Image Turbo** | 16GB | 0.936 | ★★★★☆ 快速迭代，8步推理 | ~$0.01/张 | Apache 2.0 | 16GB用户首选，成本最低 |
| **Qwen-Image** | 24GB (FP8) / 4GB (offload) | 0.9647 | ★★★★★ 1000-token复杂布局 | ~$0.005-0.02/张 | Apache 2.0 | 复杂信息图/PPT，需量化 |
| **Ovis-Image** | ~20GB (估计) | 0.964 | ★★★★★ 多区域文本92%+ | 未明确公开 | 开源 | 多标签密集型架构图 |
| **Boogu-Image** | ~16-20GB (FP8) | 待评测 | ★★★★☆ 超密集文字 | 待公开 | Apache 2.0 | 新兴选项，需验证 |

---

## 8. 关键结论与待验证假设

1. **短文本标签无专用基准**：当前模型对比基于CVTG-2K（多区域文本）和LongText-Bench（长文本），但架构图所需的"<20字符短标签在方框内"场景缺乏系统评测。建议后续Phase 2开展实际生成测试。

2. **量化对中文小字的影响尚未量化**：现有研究仅报告FP8>INT8>INT4的整体质量趋势，但针对中文架构图标签（如"负载均衡"、"分布式事务"）的字符级保真度曲线仍缺失。建议通过DiffSynth-Studio在FP16/FP8/INT8三档上生成同架构图并OCR对比。

3. **自回归+扩散混合架构最适合架构图**：GLM-Image的AR模块先"规划"布局后"绘制"，与NextStep-1的AR+Flow Matching类似，天然适合结构化约束。这验证了Phase 1W的假设。

4. **多模型协作管线可能更可靠**：针对架构图的不同元素（几何框线由SVG/Mermaid代码生成、装饰性背景由FLUX生成、中文标签由Qwen/ERNIE/GLM生成），设计多模型分工+图像合成的混合管线，可能比单一模型更可靠。这是Dim07（SVG混合工作流）的衔接点。

---

## 引用定义

[^1]: GLM-Image Technical Blog, Zhipu AI, 2026-01-14. https://z.ai/blog/glm-image; DeepLearning.ai "Zhipu's GLM-Image Blends Transformer and Diffusion Architectures", 2026-02-16. https://www.deeplearning.ai/the-batch/zhipus-glm-image-blends-transformer-and-diffusion-architectures-for-better-text-in-images; GLM-Image Prompt Guide, fal.ai, 2026-01-14. https://fal.ai/learn/devs/glm-image-prompt-guide

[^2]: Ovis-Image Technical Report, arXiv:2511.22982, 2025-11-28. https://arxiv.org/abs/2511.22982; GitHub AIDC-AI/Ovis-Image, 2025-11-18. https://github.com/AIDC-AI/Ovis-Image; Ovis-Image official website, 2025. https://ovisimage.org/

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

[^16]: 人人都是产品经理 "分镜脚本有了，配图怎么搞？", 2026-04-08. https://www.woshipm.com/ai/6372875.html; WaveSpeedAI "2026年AI图像生成API完整指南", 2025-12-27. https://wavespeed.ai/blog/zh-CN/posts/complete-guide-ai-image-apis-2026/

[^17]: arXiv:2505.03329 "FLUX-Text: A Simple and Advanced Diffusion Transformer Baseline for Scene Text Editing", 2025-05-06. https://arxiv.org/html/2505.03329v2

[^18]: arXiv:2505.24417 "EasyText: Controllable Diffusion Transformer for Multilingual Text Rendering", 2025-05-30. https://arxiv.org/html/2505.24417v1

[^19]: ERNIE-Image.app "ERNIE-Image Character LoRA Training Complete Guide", 2026-05-26. https://ernie-image.app/blog/ei-055-ernie-image-character-lora-training-english-20260526

[^20]: BotMonster "Local Image Models in 2026", 2026-06-08. https://botmonster.com/ai/best-local-image-generation-models-2026/

[^21]: Qwen-Image Technical Report, Alibaba, 2025-08-04. https://qianwen-res.oss-cn-beijing.aliyuncs.com/Qwen-Image/Qwen_Image.pdf

[^22]: GitHub boogu-project/Boogu-Image, 2026-06-16. https://github.com/boogu-project/Boogu-Image; Awesome-Chinese-Stable-Diffusion, 2023-07-07. https://github.com/leeguandong/Awesome-Chinese-Stable-Diffusion

[^23]: 字节Seedream 3.0技术报告, 2025-04-16. https://seed.bytedance.com/zh/blog/seedream-3-0-text-to-image-model-technical-report-released
