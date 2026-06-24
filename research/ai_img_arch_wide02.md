## Facet: 图生图与图像编辑工作流

### Key Findings

- **ComfyUI img2img 的核心机制是 KSampler 的 `denoise` 参数**。denoise < 1 时，模型在参考图的潜在表示上添加受控噪声并去噪；denoise 越小，生成图与参考图差异越小，denoise 越大则编辑越强。当 denoise=1 时，参考图完全丢失，退化为纯文生图 [^1]。对于架构图修改，建议 denoise 在 0.5–0.7 之间，以保留原有布局同时允许内容调整。

- **FLUX.1 Kontext 是图生图与编辑领域的重要突破**。它采用流匹配（Flow Matching）架构，通过序列拼接（sequence concatenation）将文本和图像上下文统一处理，在单一框架内实现局部编辑、全局编辑和角色一致性。1024×1024 图像生成仅需 3–5 秒，支持多轮迭代且视觉漂移（visual drift）显著低于 GPT-Image-1 和 Runway Gen-4 [^2][^3]。在 KontextBench（1026 对图像-提示）上，其在单轮质量和多轮一致性方面均达到 SOTA 水平。

- **Qwen-Image 系列在中文文本渲染与图像编辑上具有独特优势**。Qwen-Image（20B）采用 MMDiT 架构，支持语义编辑、外观编辑和文本编辑（含中英双语），在 LongText-Bench-ZH 上得分 0.946，远超 FLUX.1 Dev（0.007）和 GPT-Image-1（0.619）[^4]。Qwen Image 2.0（7B）进一步统一生成与编辑，支持 1000 token 提示、原生 2K 输出，可直接渲染 PPT 幻灯片、信息图、数据图表等复杂文本布局 [^5]。

- **Qwen-Image-Edit 支持三种编辑维度**：语义编辑（风格迁移、物体旋转、场景变换）、外观编辑（增删元素、调色、背景替换、细节增强）、文本编辑（在图像内直接修改中英文字，保留原字体、大小和风格）[^6]。这对架构图场景极具价值：可直接修改图中的模块名称、标签文字而无需重绘整个图。

- **Stable Diffusion Inpainting 的潜在空间修补原理**：在 latent space 中，被 mask 的区域替换为随机噪声，U-Net 在文本 embedding 和未 mask 区域结构信息的引导下逐步去噪，VAE 解码为最终图像。SAM 可自动分割 mask 区域，支持像素级精确控制 [^7]。但需要注意：完整图像在每一步都会参与去噪，可能导致未 mask 区域颜色漂移，需通过 latent 覆盖策略保持背景一致性 [^8]。

- **ControlNet 为架构图生成提供结构化条件控制**。通过 Canny 边缘检测、LineArt 线稿、Depth 深度图、MLSD 直线检测等预处理器，可将参考图的结构信息作为空间约束注入扩散过程。ComfyUI 支持多 ControlNet 叠加（如 Depth + Canny + Color），在保持结构的同时实现风格迁移 [^9][^10]。FLUX.1 的 ControlNet 线稿模型（如 flux-controlnet-lineart-promeai）支持 1024px 高分辨率输出，可在 ComfyUI 和 Diffusers 中部署 [^11]。

- **ComfyUI 中已存在成熟的 FLUX Kontext Dev 多轮迭代工作流**。通过 `Load Image (from output)` 节点将前一轮输出作为下一轮输入，实现：风格变换 → 细节调整 → 元素增删 → 色彩光照平衡的链式编辑 [^12]。同时支持 Image Stitch 拼接多图、Scribble-to-Image 涂鸦引导编辑，为架构图的草图→精化→文字调整流程提供了完整技术路径。

- **Dify 已有官方/社区插件支持 Qwen-Image 的 text2img 和 img2img**。插件 `wwwzhouhui/qwen_text2image` 支持异步任务处理、自定义尺寸、自动尺寸检测，以及 Qwen-Image-Edit-2511 等编辑模型，可在 Dify 工作流中实现"有图 → 图生图编辑"的条件分支 [^13]。ComfyUI 社区也有原生 Qwen-Image 工作流和 ControlNet 补丁（Canny/Depth/Inpaint），支持 mask 编辑和线条控制 [^14]。

- **中文文本保持的关键在于模型本身的文本渲染能力**。通用模型（如 FLUX.1 Dev）在 LongText-Bench-ZH 上几乎完全失败（0.005），而 Qwen-Image 通过 MSRoPE（Multimodal Scalable RoPE）位置编码，将文本 token 沿图像对角线排列，避免与图像 latent token 的位置编码冲突，从而实现了中英双语的精准文本生成与编辑 [^4]。这意味着在架构图绘制中，若图中包含中文标签，Qwen-Image 系列是目前最可靠的选择。

- **IP-Adapter 在风格迁移和角色一致性中起重要作用**。在 ComfyUI 工作流中，IP-Adapter 可通过源图像的语义信息修改模型，使迭代混合采样（Iterative Mixing）的输出更精确地对齐低分辨率参考图的构图。与 ControlNet 类似，但侧重于语义/风格条件而非空间结构 [^15]。

### Major Players & Sources

- **Black Forest Labs (FLUX.1 Kontext)**: 开源流匹配图生图/编辑模型，12B 参数，以多轮一致性和交互速度著称。提供 Pro/Dev 版本，API 定价 $0.04/图 [^2][^3]。
- **阿里巴巴通义实验室 (Qwen-Image / Qwen-Image-Edit)**: 20B MMDiT 架构，中文文本渲染 SOTA，支持开源。Qwen Image 2.0（7B）统一生成与编辑，2K 原生分辨率，AI Arena ELO 双榜第一 [^4][^5][^6]。
- **ComfyUI 社区**: 提供 FLUX Kontext Dev 工作流、Qwen-Image 原生工作流、ControlNet 多条件叠加工作流、Iterative Mixing 节点等，是图生图工作流的事实标准平台 [^1][^12][^14]。
- **Dify 插件生态**: `wwwzhouhui/qwen_text2image` 插件支持 Qwen-Image 在 Dify 中的异步 text2img/img2img 调用，便于构建自动化流程 [^13]。
- **Lvmin Zhang / Stanford (ControlNet)**: 条件控制架构开创者，通过锁定大模型参数、训练可附加编码层副本，实现 Canny/Depth/LineArt/Pose 等多种条件控制，已扩展至 FLUX 生态 [^9][^10]。
- **RunComfy / ComfyUI 教程站点**: 提供 FLUX Kontext Dev 工作流模板和详细教程，是实践层面的重要参考来源 [^12]。
- **fal.ai / Replicate**: 提供 FLUX.1 Kontext Pro 和 Qwen Image 2.0 Pro 的托管 API，便于快速原型验证 [^3][^5]。

### Trends & Signals

- **"生成-编辑一体化"成为主流方向**。FLUX.1 Kontext 和 Qwen Image 2.0 均放弃独立的生成/编辑模型，采用统一架构。这简化了工作流，降低了多轮迭代中模型切换带来的风格漂移风险 [^2][^5]。

- **多轮迭代编辑的"视觉漂移"问题正在被攻克**。FLUX.1 Kontext 通过 AuraFace 嵌入余弦相似度度量，显示其在连续编辑中角色一致性衰减速度明显慢于 GPT-Image-1 和 Runway Gen-4。但超过 6 轮迭代后仍会出现可见伪影，这是当前所有模型的共同瓶颈 [^2]。

- **中文文本渲染能力成为模型分化的关键维度**。LongText-Bench 显示，FLUX.1 Dev 在中文长文本上几乎不可用（0.005），而 Qwen-Image（0.946）和 Seedream 3.0（0.878）领先。这意味着面向中文架构图的场景，模型选择范围被大幅收窄 [^4]。

- **ControlNet 从 SD 生态扩展到 FLUX 生态**。XLabs-AI 的 `flux-controlnet-collections` 支持 Depth、Canny、HED 等控制图，与 FLUX 基础模型结合使用。FLUX.1-controlnet-lineart-promeai 等专用模型支持 1024px 线稿控制，训练成本约 3 天（A100-80G）[^11]。

- **ComfyUI 向"编排式页面流水线"（orchestrated page pipeline）演进**。社区已出现 `draft → refine → inpaint → upscale_print` 等分阶段工作流，支持 `renderspec.json` 和 `review.json` 驱动的 QA 流程，适合书籍/多页资产生产，对架构图的批量生成和版本管理具有借鉴意义 [^16]。

- **Qwen-Image 的 ControlNet 补丁（DiffSynth-ControlNets）**提供了 Canny、Depth、Inpaint 三种控制方式，可直接在 ComfyUI 中通过 mask 编辑实现局部重绘，通过 Canny 控制保持架构图线条结构 [^14]。

### Controversies & Conflicting Claims

- **FLUX.1 Kontext 的文本编辑能力 vs 专用文本模型**。FLUX.1 Kontext 支持文本编辑（如将图中 "MONTREAL" 替换为 "FREIBURG"），但官方文档承认其偶尔忽略具体提示要求。相比之下，Qwen-Image-Edit 的文本编辑能力被专门优化，能保留字体、大小和风格，且支持中英双语。对于架构图中大量文本标签的修改，Qwen 可能更可靠 [^2][^6]。

- **denoise 参数的"编辑强度" vs "质量损失"**。ComfyUI 文档指出 denoise 越大差异越大，但实践中过高 denoise（>0.8）在架构图场景会导致原有结构完全崩解。而太低（<0.3）又无法实现有效修改。用户需在保留结构和实现修改之间手动权衡，缺乏自动化的最优 denoise 推荐机制 [^1]。

- **多 ControlNet 叠加的显存消耗 vs 控制精度**。虽然 Depth + Canny + LineArt 叠加可极大提高结构保真度，但 ComfyUI 社区反馈，多链路同时运行可能使显存突破 8GB（甚至 12GB），需要 CPU 卸载或分步执行。对于需要高分辨率架构图（如 2K）的场景，硬件成本不可忽视 [^10][^14]。

- **Qwen-Image 2.0 的 img2img  pipeline 争议**。GitHub 有用户报告，在 ComfyUI 中使用标准 img2img 流程运行 Qwen Image（非 Edit 版本）时，结果" garbled and overcooked"，推测 Qwen 需要专门的 img2img/inpainting pipeline 实现，而 ComfyUI 核心尚未完全支持。这提示直接使用 Qwen Image 做图生图可能存在兼容性风险，建议使用 Qwen-Image-Edit 或官方原生工作流 [^17]。

- **开源 vs 闭源在架构图场景的可行性**。闭源模型如 GPT-Image-1、Seedream 在整体质量上可能更优，但中文文本渲染（尤其长文本）和成本可控性不如开源 Qwen-Image。对于需要本地化部署、数据敏感的企业架构图生成，开源方案具有不可替代的优势 [^4][^5]。

### Recommended Deep-Dive Areas

- **ComfyUI 多轮迭代工作流模板设计**：针对架构图绘制场景，设计"参考图 → 结构保持（ControlNet LineArt/Canny） → 模块修改（Inpainting + mask） → 文本调整（Qwen-Image-Edit） → 风格统一"的标准化节点模板，可大幅提升工程化落地效率。

- **Dify + Qwen-Image-Edit 条件分支工作流**：深入研究如何在 Dify 中通过变量判断（如用户是否上传了参考图）自动路由到 text2img 或 img2img 分支，结合异步轮询机制实现稳定的交互式架构图生成服务。

- **ControlNet 在架构图结构保持中的最优控制图组合**：验证 Canny（边缘） vs LineArt（线稿） vs MLSD（直线） vs Depth（深度）在架构图生成中的效果差异，寻找保结构最强且伪影最少的控制图组合及 strength 参数范围。

- **中文文本标签的编辑一致性**：Qwen-Image-Edit 虽能修改文本，但在多次连续编辑后，文本区域是否仍保持字体一致性、是否存在文本区域扩散到背景的风险，需要针对架构图场景进行实测验证。

- **多轮迭代中的版本管理与回滚**：FLUX Kontext 和 Qwen-Image 均支持多轮编辑，但超过 5–6 轮后质量下降。设计基于分支存储的"检查点"机制（如每轮保存 latent + 参数），允许用户回退到任意历史版本，是构建生产级工作流的关键。

- **2K 分辨率架构图的生成与编辑策略**：Qwen Image 2.0 支持原生 2K，但编辑和 ControlNet 控制在高分辨率下的显存消耗和细节一致性尚无充分测试。需要研究分块编辑（tile-based inpainting）或 latent 级联放大（iterative mixing upscale）与架构图细节保持的兼容性。

---

## 引用

[^1]: ComfyUI. "Image to Image Workflow." ComfyUI Docs, 2026. https://docs.comfy.org/tutorials/basic/image-to-image

[^2]: Batifol et al. "FLUX.1 Kontext: Flow Matching for In-Context Image Generation and Editing in Latent Space." Black Forest Labs, arXiv:2506.15742, 2025. https://arxiv.org/pdf/2506.15742

[^3]: fal.ai. "FLUX.1 Kontext [pro] (Image to Image) API." fal, 2026. https://fal.ai/models/fal-ai/flux-pro/kontext

[^4]: Wu et al. "Qwen-Image Technical Report." Alibaba Tongyi Lab, 2025. https://qianwen-res.oss-cn-beijing.aliyuncs.com/Qwen-Image/Qwen_Image.pdf

[^5]: fal.ai. "Qwen Image 2.0 - Professional Image Generation & Editing." fal, 2026. https://fal.ai/qwen-image-2.0

[^6]: Qwen-Image Blog. "Semantic Editing, Text Rewriting & Style Transfer - Qwen-Image." 2025. https://www.qwenimages.com/blog/qwen-image-edit-release

[^7]: "Image Inpainting Using Stable Diffusion Model." IJISRT, Vol.10, Issue 11, Nov 2025. https://www.ijisrt.com/assets/upload/files/IJISRT25NOV1318.pdf

[^8]: "Inference-Time Loss-Guided Colour Preservation in Diffusion Sampling." TechRxiv, 2025. https://www.techrxiv.org/users/1021762/articles/1381838

[^9]: Zhang et al. "Adding Conditional Control to Text-to-Image Diffusion Models." arXiv:2302.05543, 2023. https://arxiv.org/pdf/2302.05543

[^10]: "ControlNet: A Complete Guide." stable-diffusion-art.com, 2025. https://stable-diffusion-art.com/controlnet/

[^11]: promeai. "FLUX.1-controlnet-lineart-promeai." PromptLayer, 2025. https://www.promptlayer.com/models/flux1-controlnet-lineart-promeai/

[^12]: RunComfy. "FLUX Kontext Dev ComfyUI Workflow | AI Image Editing Tool." 2025. https://www.runcomfy.com/comfyui-workflows/flux-kontext-dev-comfyui-workflow-ai-image-editing-tool

[^13]: Dify Marketplace. "Qwen Text2Image & Image2Image." Dify Plugin, 2025. https://marketplace.dify.ai/plugin/wwwzhouhui/qwen_text2image

[^14]: ComfyOrg. "Qwen-Image ComfyUI Native Workflow Example." ComfyUI Docs. https://docs.comfy.org/tutorials/image/qwen/qwen-image

[^15]: ttulttul. "ComfyUI-Iterative-Mixer." GitHub, 2023. https://github.com/ttulttul/ComfyUI-Iterative-Mixer

[^16]: LobeHub Skills. "comfyui-image-gen." 2026. https://lobehub.com/skills/oilproducts-agent-skills-comfyui-image-gen

[^17]: comfyanonymous/ComfyUI. "Qwen image img2img pipeline not working correctly." GitHub Issue #10063, 2025. https://github.com/comfyanonymous/ComfyUI/issues/10063
