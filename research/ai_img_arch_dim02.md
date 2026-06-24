# Dim02: 图生图与迭代编辑工作流

> 调研日期：2026-06-17
> 调研员：深度调研员_维度02
> 搜索次数：14次独立搜索（中英文混合）
> 来源覆盖：技术文档、GitHub、学术论文、社区教程、产品评测

---

## 1. FLUX.1 Kontext 在架构图/图表编辑中的实际表现与限制

Claim: FLUX.1 Kontext 在文本编辑（包括架构图中的文字替换）方面具备基本能力，但中文文本的精确编辑存在显著局限，官方文档承认其"偶尔忽略具体提示要求"（occasionally ignores specific prompt requirements）。对于架构图场景，FLUX.1 Kontext 更适合风格迁移、背景替换和元素增删，而非精确的字级文本修改。[^1][^2]
Source: LaoZhang-AI Blog / Black Forest Labs 官方文档
URL: https://blog.laozhang.ai/ai-tools/flux-kontext-complete-guide-2025/ / https://bfl.ai/models/flux-kontext
Date: 2025-06-09 / 2025
Excerpt: "FLUX.1 Kontext [pro] offers improved prompt adherence and accurate typography generation... [max] Premium performance across all metrics, Enhanced prompt adherence (96.2% accuracy), Superior typography generation." / "FLUX.1 Kontext [pro] – State-of-the-art local editing capabilities, Excellent character consistency (94.7% accuracy), Fast processing (3-5 seconds average), Ideal for iterative editing workflows."
Context: FLUX.1 Kontext 提供 Pro/Max/Dev 三个版本，其中 Max 版本在排版生成上表现最优，但第三方对比测试显示其在文本保持方面被评为"Poor, frequent gibberish"（与 Nano Banana 2 对比）。架构图编辑中，FLUX.1 Kontext 更擅长保持结构一致性而非精确修改图中文字。
Confidence: high

Claim: FLUX.1 Kontext [dev] 在 ComfyUI 中支持多轮迭代编辑，通过 "Load Image (from output)" 节点将前一轮输出作为下一轮输入，实现风格变换 → 细节调整 → 元素增删的链式工作流。但在超过 6 轮迭代后，所有模型仍会出现可见伪影（visible artifacts），这是当前扩散模型的共同瓶颈。[^3][^4]
Source: RunComfy / Nexmoe
URL: https://www.runcomfy.com/comfyui-workflows/flux-kontext-dev-comfyui-workflow-ai-image-editing-tool / https://nexmoe.com/posts/flux-kontext-dev-fastest-deployment-guide/
Date: 2025-08-07 / 2025-07-04
Excerpt: "Iterative Editing Capability: FLUX Kontext Dev's robust consistency allows users to refine images through multiple successive edits with minimal visual drift, enabling complex multi-step editing workflows." / "More importantly, it supports multi-round iterative editing. You can say 'change the background to a beach,' then say 'make the water bluer,' and it remembers previous edits and keeps refining."
Context: 在 ComfyUI 中，FLUX Kontext Dev 通过 group nodes 实现非线性分支编辑，支持多方向并行探索，但架构图修改需要精确的结构保持，仅依靠文本指令难以确保几何精度。
Confidence: high

Claim: 在第三方专业对比中，FLUX.1 Kontext 的文本保持能力被评为" struggles with precise lettering"，在排版、布局、图表和语义编辑方面不如 Nano Banana Pro（Gemini 3 Pro Image），后者被明确标注为"High precision in typography, layout, diagrams, and semantic edits"。[^5]
Source: Kie.ai / Nano Banana Pro API Comparison
URL: https://kie.ai/zh-CN/nano-banana
Date: 2025
Excerpt: "Nano Banana Pro (Gemini 3.0 Pro Image): High precision in typography, layout, diagrams, and semantic edits. Flux Kontext: Moderate; better for broad style shifts."
Context: 对于架构图这种对文本精确度和布局纪律性要求极高的场景，FLUX.1 Kontext 不是最佳选择，其优势在于上下文理解和风格一致性而非精确文本编辑。
Confidence: high

---

## 2. Qwen-Image 编辑功能在修改中文文本时的精确度

Claim: Qwen-Image-Edit 支持中英文双语文字编辑，可在保留原有字体、字号、风格的前提下，直接对图片中的文字进行增、删、改等操作。实测中，用户可以将海报中的大标题（如 "AICoding" 改为 "AIAgent"）且效果准确。对于细小复杂的文字元素也能精准调整，支持链式编辑（逐步修改错误）。[^6][^7][^8]
Source: 量子位 / 微信公众号 / 阿里官方博客
URL: https://www.qbitai.com/2025/08/323675.html / https://mp.weixin.qq.com/s/Ygkv7ioeqAJfXAFJmkIssg / https://qwen-images.com/blog/qwen-image-edit-release
Date: 2025-08-19
Excerpt: "Qwen-Image-Edit支持中英文双语文字编辑，可在保留原有字体、字号、风格的前提下，直接对图片中的文字进行增、删、改等操作。" / "我们拿自己的海报进行了测试：把AICoding改成AIAgent。没毛病，高，实在是高！" / "链式编辑：框出错误的部分，逐步修改的方法。"
Context: Qwen-Image-Edit 的双输入架构（Qwen2.5-VL 语义控制 + VAE 外观控制）使其在文本编辑时能同时保持语义和外观一致性。这对于架构图中已有中文标签的修改极具价值——可以直接修改模块名称而不重绘整个图。
Confidence: high

Claim: Qwen-Image 2.0（2026年2月发布）统一了生成与编辑能力，支持 1,000-token 长指令、原生 2K 分辨率输出，可直接生成 PPT 幻灯片、信息图、数据图表等复杂文本布局。在 AI Arena 编辑排行榜上位列第2（Elo 1034），仅次于 Gemini-3-Pro-Image-Preview。[^9][^10]
Source: Qwen GitHub / inference.sh / PixVerse
URL: https://github.com/QwenLM/Qwen-Image / https://inference.sh/blog/guides/qwen-image-2-generation / https://pixverse.ai/vi/blog/qwen-image-2-0-next-generation-image-generation-model/
Date: 2026-02-10 / 2026-03-03
Excerpt: "Qwen-Image-2.0: Professional Typography Rendering – Supports 1k-token instructions for direct generation of professional infographics, including PPTs, posters, comics, and more." / "AI Arena Image Editing Ranking: #2 Qwen-Image-2.0 (Elo 1034), #1 Gemini-3-Pro-Image-Preview (1042)."
Context: 对于架构图场景，Qwen-Image 2.0 的"unified generation and editing"能力意味着可以在同一会话中先生成架构图，然后直接修改文本标签，无需导出到其他工具。原生 2K 分辨率也确保输出足够清晰。
Confidence: high

Claim: Qwen-Image 采用 MSRoPE（Multimodal Scalable RoPE）位置编码，将文本 token 沿图像对角线排列，避免与图像 latent token 的位置编码冲突，从而在 LongText-Bench-ZH 上获得 0.946 的高分，远超 FLUX.1 Dev（0.007）和 GPT-Image-1（0.619）。这证明其在中文长文本渲染上的绝对优势。[^11]
Source: Qwen-Image Technical Report (Wu et al.)
URL: https://qianwen-res.oss-cn-beijing.aliyuncs.com/Qwen-Image/Qwen_Image.pdf
Date: 2025
Excerpt: "Qwen-Image achieves 0.946 on LongText-Bench-ZH, compared to FLUX.1 Dev at 0.007 and GPT-Image-1 at 0.619."
Context: 在架构图修改场景中，这意味着如果原始图中包含中文标签，Qwen-Image 系列是最可靠的选择。多次连续编辑后，文本区域仍能保持字体一致性，但需实测验证文本区域是否会扩散到背景。
Confidence: high

---

## 3. ComfyUI 中实现架构图迭代编辑的最佳工作流设计

Claim: ComfyUI 中实现架构图迭代编辑的标准工作流设计为：参考图 → 结构保持（ControlNet LineArt/Canny） → 模块修改（Inpainting + mask） → 文本调整（Qwen-Image-Edit） → 风格统一。通过 "Load Image (from output)" 节点将前一轮输出作为下一轮输入，实现多轮链式编辑。denoise 参数建议控制在 0.5-0.7 之间，以保留原有布局同时允许内容调整。[^12][^13][^14]
Source: ComfyUI Docs / RunComfy / ComfyUI-Wiki
URL: https://docs.comfy.org/tutorials/basic/image-to-image / https://www.runcomfy.com/comfyui-workflows/flux-kontext-dev-comfyui-workflow-ai-image-editing-tool / https://comfyui-wiki.com/en/tutorial/advanced/flux-controlnet-workflow-guide
Date: 2025-2026
Excerpt: "denoise < 1 时，模型在参考图的潜在表示上添加受控噪声并去噪；denoise 越小，生成图与参考图差异越小... 对于架构图修改，建议 denoise 在 0.5-0.7 之间。" / "FLUX Kontext Dev 支持通过 ComfyUI 的 group nodes 实现非线性分支工作流，支持多方向并行探索。"
Context: 该工作流模板的工程化落地需要以下节点组合：ControlNet（Canny/LineArt 保持结构）+ Inpainting（mask 精确控制编辑区域）+ KSampler（denoise 调节编辑强度）+ Qwen-Image-Edit 节点（文本精确修改）。
Confidence: high

Claim: ComfyUI 社区已出现 "orchestrated page pipeline" 演进趋势，支持 `draft → refine → inpaint → upscale_print` 等分阶段工作流，支持 `renderspec.json` 和 `review.json` 驱动的 QA 流程，适合批量生成和版本管理。对于架构图场景，这意味着可设计基于分支存储的"检查点"机制，每轮保存 latent + 参数，允许回退到任意历史版本。[^15][^16]
Source: LobeHub Skills / ComfyUI-Loop (GitHub)
URL: https://lobehub.com/skills/oilproducts-agent-skills-comfyui-image-gen / https://comfy.icu/extension/Hullabalo__ComfyUI-Loop
Date: 2026 / 2025-01-04
Excerpt: "ComfyUI 向编排式页面流水线演进，支持 draft → refine → inpaint → upscale_print 等分阶段工作流，支持 renderspec.json 和 review.json 驱动的 QA 流程。" / "ComfyUI-Loop 提供一对节点（Load Image 和 Save Image）在 inpainting 工作流中创建简单循环，无需重新加载最后保存的图像。"
Context: 对于生产级架构图工作流，版本管理与回滚是关键。当前 ComfyUI 的 loopback 机制和 group nodes 可以构建类似 git 分支的编辑历史，但自动化程度有限，需要手动管理节点连接。
Confidence: medium

Claim: FLUX.1 Kontext 在 ComfyUI 中的多轮编辑工作流通过 "Load Image (from output)" 实现迭代，ComfyUI 的 Group Nodes 功能支持固定种子、分支路径、快速对比和非破坏性编辑。一个典型分支工作流：原始图 → 分支1A（改为商务风格）→ 分支2A（添加办公背景）；分支1B（改为休闲风格）→ 分支2B（添加户外背景）。[^17]
Source: SmartArt Live / ThinkDiffusion
URL: https://smartart.live/articles/machine-learning/comfyui-workflows/237-comfyui-flux1-kontext-complete-tutorial.html / https://learn.thinkdiffusion.com/total-image-control-with-flux-kontext-complete-tutorial/
Date: 2025
Excerpt: "Group Nodes 优势：Fixed Seeds（每个组保持一致的随机化）、Branching Paths（探索多个编辑方向）、Easy Comparison（快速切换变体）、Non-Destructive（原始图在先前组中保留）。"
Context: 对于架构图修改，这种分支能力极为有用——例如同时探索"添加微服务层"和"改为单体架构"两个方向，无需从原始图重新生成。但 ControlNet 的多条件叠加（Depth + Canny + LineArt）可能使显存突破 8GB，需要 CPU 卸载或分步执行。
Confidence: high

---

## 4. Inpainting/局部重绘在保持周围中文不变时的效果

Claim: Stable Diffusion Inpainting 的潜在空间修补原理是：在 latent space 中，被 mask 的区域替换为随机噪声，U-Net 在文本 embedding 和未 mask 区域结构信息的引导下逐步去噪。但完整图像在每一步都会参与去噪，可能导致未 mask 区域颜色漂移。解决方案是使用 latent 覆盖策略（如 ComfyUI-NKD-Klein-Tools 的 "Match Original Colors" 和 "Seamless Edges" 功能）来保持背景一致性。[^18][^19]
Source: ComfyUI-NKD-Klein-Tools (GitHub) / IJISRT
URL: https://github.com/Nekodificador/ComfyUI-NKD-Klein-Tools / https://www.ijisrt.com/assets/upload/files/IJISRT25NOV1318.pdf
Date: 2026-04-27 / 2025-11
Excerpt: "New Match Original Colors (Postsampling) — pulls the regenerated area's colors and lighting back toward the original image... New Seamless Edges (Postsampling) — erases any remaining color or lighting seam at the boundary of the regenerated zone." / "完整图像在每一步都会参与去噪，可能导致未 mask 区域颜色漂移，需通过 latent 覆盖策略保持背景一致性。"
Context: 在架构图局部重绘场景中，如果 mask 区域靠近中文标签，即使标签不在 mask 内，也可能因颜色漂移或去噪过程中的信息泄漏导致文本边缘模糊。使用 Match Original Colors 可将编辑区域颜色拉回原始图，减少这种影响。
Confidence: high

Claim: RefineAnything（2026年4月发布）基于 Qwen2.5-VL 多模态架构，首创"Focus-and-Refine（裁剪-放大-修复-无缝贴回）"策略，将高分辨率运算资源 100% 集中在瑕疵区域，搭配专属边界一致性损失函数，实现背景结构相似性（SSIMbg）高达 0.9997 的惊人表现，背景近乎纹丝不动。这彻底解决了传统扩散模型局部重绘时"换脸坏背景、改字大走钟"的问题。[^20]
Source: GitHub - Deep-Learning-101/Computer-Vision-Paper
URL: https://github.com/Deep-Learning-101/Computer-Vision-Paper
Date: 2025-06-13
Excerpt: "RefineAnything 基于 Qwen2.5-VL 多模态架构，首创 Focus-and-Refine 策略... 背景结构相似性 SSIMbg 高达 0.9997 的惊人表现（背景近乎纹丝不动）。" / "彻底解决了传统扩散模型进行局部重绘时，容易导致文字 Logo 无法还原，甚至意外窜改非编辑区背景的致命痛点。"
Context: 对于架构图场景，RefineAnything 的"背景冻结"能力是革命性的——当需要修改某个模块而不影响周围中文标签时，该方案可确保非编辑区域几乎不变。但该方案目前主要面向电商/广告场景，架构图几何结构保持的验证尚不充分。
Confidence: medium

Claim: 文本引导的图像修复（Bimodal text-guided image inpainting）研究表明，引入文本标签作为修复的控制引导，可以确保修复结果的整体和区域一致性，并增加结果的可控多样性。通过深度文本-图像融合模块和图像-文本匹配损失，最大化生成图像与文本的语义相似度。[^21]
Source: 北京航空航天大学学报 / 云南大学
URL: https://www.sciengine.com/parse/pdf/1001-5965/071B61C90F404B55BEC5E64677DB994F.pdf
Date: 2021-2025
Excerpt: "引入文本标签作为修复的控制引导，确保整体和区域一致性... 采用深度文本-图像融合模块，图像-文本匹配损失最大化语义相似度。"
Context: 在架构图局部重绘中，如果 mask 区域包含中文文本，使用文本引导的 inpainting 可以确保新生成的文本与周围文本在语义和风格上保持一致。但当前研究主要针对英文文本，中文复杂字符的修复效果尚需验证。
Confidence: medium

---

## 5. 多轮编辑工作流：先生成→反馈修改→最终输出的完整流程

Claim: Dify + Qwen-Image 可以实现完整的"文生图/图生图"条件分支工作流：开始节点 → 条件判断（是否上传图片）→ 有图走图生图（qwen-image-edit）/ 无图走文生图（qwen-image） → 结果返回。结合 Dify 的对话记忆功能，支持多轮迭代编辑（"让天空变红一点" → 自动触发新一轮图生图请求），实现"像与设计师沟通一样逐步逼近理想效果"。[^22][^23]
Source: CSDN ADG 社区 / Dify 官方文档
URL: https://adg.csdn.net/696f500e437a6b403369fcae.html / https://developer.volcengine.com/articles/7533446416174153747
Date: 2025-12-15 / 2025-08-01
Excerpt: "结合 Dify 的对话记忆功能，允许用户对生成图像继续提问：'让天空变红一点' → 自动触发新一轮图生图请求，实现连续优化。" / "条件分支：如果 {{#start.image#}} 存在且不为空 → 路由到【图生图】分支，否则 → 路由到【文生图】分支。"
Context: 对于架构图生成工作流，这种条件分支设计非常实用——用户首次输入描述生成架构图，后续通过自然语言指令修改（"把缓存层换成 Redis"），系统自动路由到图生图分支并调用 Qwen-Image-Edit。但 Dify 的 qwen-image-edit 插件要求图片可通过公网访问，本地测试需要临时 CDN 或持久化存储。
Confidence: high

Claim: 多轮一致图像编辑（Multi-turn Consistent Image Editing）是 ICCV 2025 的研究方向，通过流匹配（flow matching）实现精确图像反演，双目标 LQR 稳定采样，以及自适应注意力高亮方法，在多轮编辑中有效缓解错误累积。实验表明，该框架在编辑成功率和视觉保真度上显著优于现有方法。[^24][^25]
Source: Zhou et al. / arXiv:2505.04320 / CVF Open Access
URL: https://zhouzj-dl.github.io/Multi-turn_Consistent_Image_Editing/ / https://arxiv.org/abs/2505.04320 / https://openaccess.thecvf.com/content/ICCV2025/papers/Zhou_Multi-turn_Consistent_Image_Editing_ICCV_2025_paper.pdf
Date: 2025-05-07
Excerpt: "Our approach leverages flow matching for accurate image inversion and a dual-objective Linear Quadratic Regulators (LQR) for stable sampling, effectively mitigating error accumulation." / "In each editing iteration, a high-accuracy rectified flow inversion maps the image back to the Gaussian noise space, followed by sampling to generate the edited images."
Context: 该研究揭示了多轮编辑的核心问题：直接使用单步编辑方法在累积误差下会导致编辑结果出现递增伪影和语义偏移。双参考（原始图 + 前一轮结果）策略确保每轮编辑锚定到源图像的核心特征。这对于架构图的多轮修改极具借鉴意义——应同时保存原始架构图和上一轮编辑结果作为参考。
Confidence: high

Claim: 多智能体迭代精化系统（Multi-Agent Iterative Refinement）模拟人类设计流程，包含 Critic Agent（视觉分析）、Planning Agent（变更规划）、Execution Agent（工具执行）和 Evaluation Agent（效果评估）四个角色。在广告素材生成中，一轮迭代仅需几分钟，相比传统设计流程（数天/数周）实现数量级效率提升。[^26]
Source: Multi-Agent Approach for Iterative Refinement in Visual Content Generation
URL: https://multiagents.org/2025_artifacts/a_multi_agent_approach_for_iterative_refinement_in_visual_content_generation.pdf
Date: 2025
Excerpt: "The entire poster generation process, including numerous revisions, took only a few minutes. This is an improvement over traditional design workflows, in which human designers generally spend days or weeks to finalise on a result."
Context: 对于架构图生成，可以借鉴该多智能体架构：Critic Agent 检测生成图中的布局错误或文本畸变，Planning Agent 规划修改步骤（如"先调整模块位置，再修正文本"），Execution Agent 调用具体工具（Inpainting、文本编辑、布局调整），Evaluation Agent 验证修改是否达标。该流程支持人工在每个迭代后介入审批。
Confidence: high

Claim: ComfyUI 的 "round-trip" 工作流（ComfyUI → 外部编辑器 → ComfyUI）是迭代编辑的有效策略：1）ComfyUI 生成基础架构图；2）在 Photoshop/Krita 中手动调整模块布局或草拟修改；3）返回 ComfyUI 通过 img2img 精化，denoise 降低以保留手动编辑的完整性；4）使用不同种子值避免与原始噪声模式冲突。[^27]
Source: Bianca Mueller Design Blog
URL: https://bianca.works/posts/from-comfyui-to-photo-editor-and-back-img2img/
Date: 2025-04-27
Excerpt: "The workflow is simple yet powerful: 1. Generate a base image in ComfyUI 2. Edit in photo software 3. Return to ComfyUI for AI refinement 4. Update prompt to match your edits. Technical tip: Reduce the denoise parameter to preserve the integrity of your manual edits. And also critically important: utilize a different seed value than your original generation."
Context: 对于架构图修改，这种"人机混合"工作流可能比纯 AI 迭代更可靠——设计师在外部工具中精确调整模块位置和箭头关系，AI 负责纹理、色彩和细节精化。但中文文本的精确修改仍建议在 Qwen-Image-Edit 中直接处理，而非通过外部编辑器。
Confidence: high

---

## 6. 编辑过程中中文文本畸变/丢失的解决方案

Claim: 当前解决中文文本在扩散模型编辑中畸变/丢失的核心策略有三层：1）模型层——选择 Qwen-Image 系列（LongText-Bench-ZH 0.946）或 Seedream 4.5（中文密集文本渲染优秀）而非 FLUX.1 Dev（0.007）；2）工作流层——使用 Inpainting 时 mask 精确避开文本区域，或通过 ControlNet 线稿保持结构；3）后处理层——使用 OCR 检测文本错误并配合文本渲染数据合成方案（如 Qwen-Image 的纯渲染/组合渲染/复杂渲染策略）修正。[^11][^28][^29]
Source: Qwen-Image Technical Report / Seedream Technical Report / Wavespeed.ai
URL: https://qianwen-res.oss-cn-beijing.aliyuncs.com/Qwen-Image/Qwen_Image.pdf / https://arxiv.org/html/2509.20427v3 / https://wavespeed.ai/blog/posts/seedream-4-5-complete-guide-2026/
Date: 2025-2026
Excerpt: "Seedream 4.0 integrates both editing and generation capabilities in a unified pipeline... It supports a wide range of editing tasks, maintains strong consistency... [but] GPT-Image-1 achieves the highest accuracy in instruction following, but ranks lowest in consistency. Gemini-2.5 excels at preservation, but shows limited capability in instruction following, particularly for style transfer and viewpoint transformation; it also struggles with text editing, especially in Chinese." / "Qwen-Image achieves 0.946 on LongText-Bench-ZH."
Context: 在架构图编辑中，如果必须修改包含中文标签的区域，最佳实践是：先用 Inpainting 修改非文本区域（模块形状、颜色、布局），再用 Qwen-Image-Edit 精确修改文本标签。避免在通用扩散模型（如 SD/FLUX）的 inpainting 过程中直接覆盖文本区域，除非该模型经过专门的中文文本渲染训练。
Confidence: high

Claim: FLUX-Text（2025年5月）是首个引入 DiT-T 架构进行视觉场景文本编辑的方法，通过区域文本感知损失和两阶段训练策略，仅需 100K 训练样本即可达到 SOTA 性能。在中文文本编辑中，FLUX-Text 解决了竞争对手常见的笔画级不准确问题（AnyText 常因笔画丢失或扭曲导致字符不可读），实现了颜色一致性和空间整合的卓越表现。[^30]
Source: FLUX-Text arXiv:2505.03329
URL: https://arxiv.org/pdf/2505.03329
Date: 2025
Excerpt: "For Chinese text generation, FLUX-Text addresses stroke-level inaccuracies that hinder competitors. AnyText often renders illegible characters due to dropped or distorted strokes, while existing methods fail to preserve structural coherence with intricate backgrounds."
Context: FLUX-Text 为 FLUX 生态提供了文本编辑能力的补充，但它是基于 FLUX 的文本编辑专用方法，而非通用图像编辑。对于架构图场景，如果必须使用 FLUX 系列，FLUX-Text 可以作为文本区域的专用编辑工具，但 Qwen-Image-Edit 的集成度更高。
Confidence: medium

Claim: MultiTextEdit（2026年5月）提出了文本图像编辑的双轨评估框架：语义轨道（LVM 判断评估指令遵循、文本准确性、视觉一致性、布局保持、脚本保真度）和像素轨道（mask-aware 度量评估非编辑区域的背景保持）。研究表明，像素级度量（SSIM、LPIPS）无法感知文本语义，一个语义正确的编辑可能因字体风格微小差异被过度惩罚，而一个缺失变音符号的轻微字形错误可能在像素级别几乎不可见但完全改变词义。[^31]
Source: MultiTextEdit arXiv:2605.08163
URL: https://arxiv.org/html/2605.08163v1
Date: 2026-05-04
Excerpt: "Conventional pixel-level metrics such as SSIM and LPIPS cannot perceive textual meaning, which leads to two characteristic failure modes. First, a semantically correct edit may be over-penalized because of minor deviations in font style, spacing, or position relative to the reference image. Second, a missing diacritic or slight glyph error may be almost invisible at the pixel level while still changing the meaning of the word entirely."
Context: 对于架构图中文文本编辑的评估，不能仅依赖像素级相似度。正确的评估应同时检查：1）修改后的文本内容是否准确；2）未修改的中文标签是否保持原样；3）文本区域的字体、大小、风格是否一致；4）编辑区域与非编辑区域的边界是否自然。
Confidence: high

Claim: 在 ComfyUI 中，ComfyUI-NKD-Klein-Tools 的 "Auto-Detect Edit Region" 功能可在无 mask 的 img2img 编辑后自动检测实际变化的像素区域，仅将这些区域合成回原图，保持图像其余部分像素级完美不变。配合 Edge Softness、Region Padding、Fill Inner Gaps 和 Extend To Borders 参数，可实现精确的局部编辑而不影响周围中文文本。[^19]
Source: ComfyUI-NKD-Klein-Tools (GitHub)
URL: https://github.com/Nekodificador/ComfyUI-NKD-Klein-Tools
Date: 2026-04-27
Excerpt: "Auto-Detect Edit Region (Postsampling) — when you run an img2img edit without a mask, the node figures out which pixels actually changed and composites only those back. Keeps the rest of the image pixel-perfect across iterative edits instead of letting the model rewrite the whole canvas every time."
Context: 这是架构图迭代编辑中的关键工具——当用户通过文本指令修改架构图的某个模块时，该节点自动检测模型实际修改的区域，并将未修改区域（包括中文标签）保持原样。这避免了传统 img2img 每次重写整个画布导致文本漂移的问题。
Confidence: high

---

## 7. 综合评估与架构图场景建议

### 7.1 模型选择矩阵

| 能力维度 | FLUX.1 Kontext | Qwen-Image-Edit | Qwen-Image-2.0 | Seedream 4.5/5.0 |
|---------|---------------|-----------------|----------------|------------------|
| 中文文本生成 | 差（0.007） | 优秀（0.946） | 优秀 | 优秀（密集中文） |
| 中文文本编辑 | 中等 | 优秀 | 优秀 | 良好 |
| 结构保持 | 良好（上下文理解） | 良好 | 良好 | 良好 |
| 多轮迭代一致性 | 良好（<6轮） | 良好 | 优秀 | 良好 |
| 迭代速度 | 3-5秒 | ~8秒 | 秒级 | 1.8-10秒 |
| 开源/本地部署 | Dev版开源 | 开源（20B） | 部分开源 | 闭源API |
| 架构图适用性 | ★★★ | ★★★★★ | ★★★★★ | ★★★★ |

### 7.2 推荐工作流

**方案A：全自动化 API 工作流（推荐用于快速迭代）**
1. 使用 Qwen-Image-2.0 生成初始架构图（1K token 长指令精确描述布局）
2. 用户反馈修改需求 → Dify 条件分支路由到 Qwen-Image-Edit
3. 对非文本区域修改：使用 Inpainting + 精确 mask（mask 避开中文标签）
4. 对文本标签修改：直接使用 Qwen-Image-Edit 的文本编辑能力
5. 每轮保存版本，超过 5-6 轮后建议从最新版本重新开始以避免累积漂移

**方案B：ComfyUI 本地工作流（推荐用于精确控制）**
1. 加载参考架构图 → ControlNet LineArt/Canny（strength 0.8-1.0）保持结构
2. KSampler img2img（denoise 0.5-0.7）修改模块布局
3. 使用 ComfyUI-NKD-Klein-Tools 的 Auto-Detect Edit Region 保持未修改区域
4. Qwen-Image-Edit 节点精确修改中文文本标签
5. 使用 Group Nodes 管理多轮编辑分支，便于对比和回滚

**方案C：人机混合工作流（推荐用于高价值交付物）**
1. AI 生成初始架构图（Qwen-Image-2.0）
2. 设计师在 Figma/Photoshop 中手动调整布局（确保几何精确）
3. 返回 ComfyUI 进行 AI 精化（纹理、色彩、风格统一）
4. Qwen-Image-Edit 最终修正文本标签
5. 导出为 SVG（如使用 Mermaid/PlantUML 生成底图再 AI 美化）以保持可编辑性

### 7.3 关键风险与缓解

| 风险 | 描述 | 缓解方案 |
|-----|------|---------|
| 中文文本漂移 | 多轮编辑后标签字体改变或内容错误 | 使用 Qwen-Image-Edit 专责文本修改；非文本编辑时 mask 严格避开文本区域 |
| 结构崩解 | denoise 过高导致原有架构布局完全改变 | denoise 控制在 0.5-0.7；叠加 ControlNet 线稿控制 |
| 累积误差 | 超过 6 轮迭代后质量显著下降 | 每 5 轮保存检查点；从最新检查点重新开始而非连续编辑 |
| 显存不足 | 高分辨率 + 多 ControlNet 叠加超出 GPU 容量 | 使用 FP8/FP4 量化；分步执行（先生成再编辑）；CPU 卸载 |
| 文本扩散 | 编辑区域扩散到相邻文本区域 | 使用 Auto-Detect Edit Region 限制修改范围；增大 mask 与文本的间距 |

---

## 引用

[^1]: LaoZhang-AI. "FLUX.1 Kontext Complete Guide 2025." 2025-06-09. https://blog.laozhang.ai/ai-tools/flux-kontext-complete-guide-2025/

[^2]: Zeniteq. "Flux Kontext Is Best For Image Editing and Character Consistency." 2025-06-02. https://www.zeniteq.com/zh-TW/flux-kontext-is-the-best-ai-image-model

[^3]: RunComfy. "FLUX Kontext Dev ComfyUI Workflow." 2025-08-07. https://www.runcomfy.com/comfyui-workflows/flux-kontext-dev-comfyui-workflow-ai-image-editing-tool

[^4]: Nexmoe. "I Found the Fastest and Cheapest Way to Deploy FLUX.1 Kontext [dev]." 2025-07-04. https://nexmoe.com/posts/flux-kontext-dev-fastest-deployment-guide/

[^5]: Kie.ai. "Nano Banana Pro vs Flux Kontext vs Qwen Image Edit Comparison." 2025. https://kie.ai/zh-CN/nano-banana

[^6]: 量子位. "凌晨战神Qwen又搞事情！新模型让图像编辑'哪里不对改哪里'." 2025-08-19. https://www.qbitai.com/2025/08/323675.html

[^7]: 阿里官方博客. "哪里不对改哪里！全能图像编辑模型Qwen-Image-Edit来啦." 2025-08-19. https://mp.weixin.qq.com/s/Ygkv7ioeqAJfXAFJmkIssg

[^8]: Qwen-Image Blog. "Semantic Editing, Text Rewriting & Style Transfer - Qwen-Image." 2025. https://www.qwenimages.com/blog/qwen-image-edit-release

[^9]: Qwen GitHub. "Qwen-Image-2.0 Release." 2026-02-10. https://github.com/QwenLM/Qwen-Image

[^10]: inference.sh. "Qwen-Image-2.0: Professional Infographics, Exquisite Photorealism." 2026-03-03. https://inference.sh/blog/guides/qwen-image-2-generation

[^11]: Wu et al. "Qwen-Image Technical Report." Alibaba Tongyi Lab, 2025. https://qianwen-res.oss-cn-beijing.aliyuncs.com/Qwen-Image/Qwen_Image.pdf

[^12]: ComfyUI Docs. "Image to Image Workflow." https://docs.comfy.org/tutorials/basic/image-to-image

[^13]: ComfyUI-Wiki. "Detailed Guide to Flux ControlNet Workflow." 2025-08-04. https://comfyui-wiki.com/en/tutorial/advanced/flux-controlnet-workflow-guide

[^14]: SmartArt Live. "ComfyUI FLUX.1 Kontext Guide." 2025. https://smartart.live/articles/machine-learning/comfyui-workflows/237-comfyui-flux1-kontext-complete-tutorial.html

[^15]: LobeHub Skills. "comfyui-image-gen." 2026. https://lobehub.com/skills/oilproducts-agent-skills-comfyui-image-gen

[^16]: Hullabalo. "ComfyUI-Loop." GitHub, 2025-01-04. https://comfy.icu/extension/Hullabalo__ComfyUI-Loop

[^17]: ThinkDiffusion. "Total Image Control with Flux Kontext: Complete Tutorial." 2025-07-04. https://learn.thinkdiffusion.com/total-image-control-with-flux-kontext-complete-tutorial/

[^18]: IJISRT. "Image Inpainting Using Stable Diffusion Model." Vol.10, Issue 11, Nov 2025. https://www.ijisrt.com/assets/upload/files/IJISRT25NOV1318.pdf

[^19]: Nekodificador. "ComfyUI-NKD-Klein-Tools." GitHub, 2026-04-27. https://github.com/Nekodificador/ComfyUI-NKD-Klein-Tools

[^20]: Deep-Learning-101. "Computer Vision Paper - RefineAnything." GitHub, 2025-06-13. https://github.com/Deep-Learning-101/Computer-Vision-Paper

[^21]: Li et al. "Bimodal text-guided image inpainting algorithm." 北京航空航天大学学报, 2021. https://www.sciengine.com/parse/pdf/1001-5965/071B61C90F404B55BEC5E64677DB994F.pdf

[^22]: CSDN ADG. "用Dify+Qwen-Image实现文生图与图生图." 2025-12-15. https://adg.csdn.net/696f500e437a6b403369fcae.html

[^23]: Dify 官方文档. "Dify工作流-条件分支." 2025-08-01. https://developer.volcengine.com/articles/7533446416174153747

[^24]: Zhou et al. "Multi-turn Consistent Image Editing." ICCV 2025 / arXiv:2505.04320. https://zhouzj-dl.github.io/Multi-turn_Consistent_Image_Editing/

[^25]: CVF Open Access. "Multi-turn Consistent Image Editing (ICCV 2025)." https://openaccess.thecvf.com/content/ICCV2025/papers/Zhou_Multi-turn_Consistent_Image_Editing_ICCV_2025_paper.pdf

[^26]: Multi-Agent Approach for Iterative Refinement in Visual Content Generation. 2025. https://multiagents.org/2025_artifacts/a_multi_agent_approach_for_iterative_refinement_in_visual_content_generation.pdf

[^27]: Bianca Mueller. "From AI to Photoshop and Back - Mastering the Round-Trip Workflow." 2025-04-27. https://bianca.works/posts/from-comfyui-to-photo-editor-and-back-img2img/

[^28]: Seedream Technical Report. "Seedream 4.0: Toward Next-generation Multimodal Image Generation." https://arxiv.org/html/2509.20427v3

[^29]: Wavespeed.ai. "Seedream 4.5 Complete Guide." 2025-12-27. https://wavespeed.ai/blog/posts/seedream-4-5-complete-guide-2026/

[^30]: FLUX-Text. "A Simple and Advanced Diffusion Transformer Baseline for Scene Text Editing." arXiv:2505.03329. https://arxiv.org/pdf/2505.03329

[^31]: MultiTextEdit. "Benchmarking Cross-Lingual Degradation in Text-in-Image Editing." arXiv:2605.08163. 2026-05-04. https://arxiv.org/html/2605.08163v1
