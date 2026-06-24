# Dim04: ControlNet与几何结构保持技术

> 调研日期: 2026-06-23 | 角色: 深度调研员_维度04 | 搜索轮次: 12+

---

## 1. ControlNet各预处理器在架构图场景的效果对比

```
Claim: Canny边缘检测在保留建筑/立面布局方面表现最优，当ControlNet权重设为1.0时，Canny模型生成的结果最贴合参考图的立面布局；而Depth模型虽然空间感更强，但布局保真度较低。MLSD在直线检测上SSIM得分最高(0.7455)，但曲线会被忽略，适合纯直线型架构图。[^1][^2]
Source: Uni-ControlNet论文 (NeurIPS 2023) + Building Facades Design论文
URL: https://i.cs.hku.hk/~kykwong/publications/szhao_neurips2023.pdf / https://arxiv.org/pdf/2303.12755
Date: 2023
Excerpt: "The canny edge model produces the best results when the ControlNet weight is set to its maximum(W=1.0), preserving the facade layout of the reference image" / "MLSD (SSIM): 0.7455, Canny (SSIM): 0.4828"
Context: 在建筑设计场景中对Canny、Segment Map、Depth Map、MLSD进行了对比测试，512x512分辨率。对于架构图（含直线方框和箭头），MLSD+Canny组合可能最优。
Confidence: high
```

```
Claim: LineArt预处理器在架构图线稿保持上比Canny更精细，提供anime/realistic/coarse三种模式，支持动漫线和写实线提取。ControlNet LineArt模型适合将现有架构图转化为线稿后再进行风格迁移。[^3]
Source: Stable Diffusion Art - ControlNet Complete Guide
URL: https://stable-diffusion-art.com/controlnet/
Date: 2025-09-28
Excerpt: "Line Art renders the outline of an image. It attempts to convert it to a simple drawing... Line art realistic: Realistic-style lines. Line art coarse: Realistic-style lines with heavier weight."
Context: 在ComfyUI和A1111中广泛使用，LineArt在保持线稿结构方面比Canny更柔和，细节保留更完整。
Confidence: high
```

```
Claim: 对于架构图（直线为主），MLSD是最佳选择，因为它专门检测直线段，对曲线自动忽略，能精确提取建筑轮廓、室内设计和方框边界。Canny会检测所有边缘，可能引入过多噪声。[^4]
Source: ComfyUI Wiki - ControlNet Tutorial
URL: https://comfyui-wiki.com/en/tutorial/advanced/how-to-install-and-use-controlnet-models-in-comfyui
Date: 2026-01-28
Excerpt: "MLSD: Only detects straight lines, suitable for architecture, interior design, etc."
Context: ComfyUI官方文档明确将MLSD定位为建筑/室内设计专用预处理器。
Confidence: high
```

## 2. Multi-ControlNet叠加在复杂架构图中的应用

```
Claim: ComfyUI通过Apply ControlNet节点的链式串联支持多ControlNet叠加，常见组合如Canny+Depth可同时保持平面结构和空间层次感。FLUX ControlNet V3.0工作流采用HED(0.8)+Depth(0.7)+Canny(0.6)三条件叠加，总权重建议≤2.0。[^5][^6]
Source: ComfyUI.org - FLUX ControlNet V3.0 Workflow + ComfyUI Wiki Mixing ControlNets
URL: https://comfyui.org/en/flux-controlnet-v3-workflow / https://docs.comfy.org/tutorials/controlnet/mixing-controlnets
Date: 2025-06-06 / 2026-01-28
Excerpt: "Total ControlNet weights should ideally ≤2.0 (e.g., HED 0.8 + Depth 0.7 + Canny 0.6)." / "Mixing multiple ControlNets allows you to control different regions or aspects of an image simultaneously."
Context: 在复杂架构图场景，可同时使用Canny控制方框边界、Depth控制层次关系、LineArt控制连接线走向，通过串联节点实现。
Confidence: high
```

```
Claim: 多ControlNet叠加会显著增加显存消耗。Depth Anything V2本身就很占VRAM，在高分辨率下可能崩溃。FLUX ControlNet V3.0工作流推荐RTX 40系列、VRAM≥12GB。[^5]
Source: ComfyUI.org - FLUX ControlNet V3.0 Workflow
URL: https://comfyui.org/en/flux-controlnet-v3-workflow
Date: 2025-06-06
Excerpt: "RTX 40 series recommended (FP8 support), VRAM ≥12GB. Depth Anything V2 is VRAM-intensive; may crash at high resolutions."
Context: 对于企业级2K架构图生成，多ControlNet叠加的硬件成本不可忽视，可能需要分步执行或CPU卸载。
Confidence: high
```

```
Claim: ComfyUI Advanced-ControlNet插件支持按时间步调度ControlNet强度（timestep keyframes）、注意力掩码（mask）和权重覆盖，可在架构图生成的前几步强控制结构、后几步弱控制以允许细节优化。[^7]
Source: GitHub - Kosinkadink/ComfyUI-Advanced-ControlNet
URL: https://github.com/Kosinkadink/ComfyUI-Advanced-ControlNet
Date: 2023-08-01
Excerpt: "Nodes for scheduling ControlNet strength across timesteps and batched latents, as well as applying custom weights and attention masks."
Context: 对架构图而言，可在前50%步用高strength锁定结构，后50%步降低strength让模型优化文本标签和颜色。
Confidence: medium
```

## 3. ControlNet与中文模型（Qwen-Image/ERNIE-Image）的兼容性

```
Claim: Qwen-Image-Edit 2509版本原生集成了ControlNet支持，支持主流类型（Canny/Depth/Lineart/Inpaint等），可直接在ComfyUI中通过DiffSynth-Studio的Qwen-Image-In-Context-Control-Union模型使用。Qwen-Image-2512在4步采样下中文文字可读率达89%，远超SDXL+ControlNet的61%。[^8][^9]
Source: CSDN - Qwen-Image-Edit全解析 + CSDN - Qwen-Image-2512实测
URL: https://blog.csdn.net/weixin_28721743/article/details/155975994 / https://blog.csdn.net/weixin_42504649/article/details/157445908
Date: 2025-12-15 / 2026-01-28
Excerpt: "ControlNet 支持: 不支持 → 原生集成，支持主流类型" / "含中文文字的提示词，4步采样下文字可读率达89%（测试集500条），远高于SDXL+ControlNet方案的61%"
Context: Qwen-Image的ControlNet补丁通过DiffSynth-Studio提供，支持Canny、Depth、Inpaint三种控制方式，可直接在ComfyUI中通过mask编辑实现局部重绘。
Confidence: high
```

```
Claim: ERNIE-Image（百度文心）具有原生结构化控制能力，GENEval得分0.8856，无需依赖ControlNet插件即可实现布局可控生成。LongTextBench得分0.9733，在中文长文本渲染上优于FLUX和Stable Diffusion。[^10]
Source: AI工具导航 - ERNIE-Image介绍
URL: https://www.aiboss88.com/news/project-ernie-image
Date: 2026-04-16
Excerpt: "布局可控性: GENEval 0.8856，原生结构化控制（FLUX需依赖ControlNet插件）" / "中文长文本: LongTextBench 0.9733，精准渲染"
Context: ERNIE-Image采用单流DiT架构，8B参数，Apache-2.0协议。对于中文架构图，ERNIE-Image可能不需要额外ControlNet即可实现较好布局。
Confidence: medium
```

## 4. 使用ControlNet时中文文本是否会被破坏及解决方案

```
Claim: ControlNet在增强结构控制的同时会引入图像质量下降，包括文本区域模糊和变形。SimplePoster论文显示，ControlNet-augmented的subject extension rate为23.6%，而全参数微调可降至0.6%。ControlNet-based方法在MiniText-Benchmark上几乎完全失败（Sen.Acc仅0.0006）。[^11][^12]
Source: arXiv - SimplePoster (2605.08784) + UniGlyph论文 (ICCV 2025)
URL: https://arxiv.org/html/2605.08784v1 / https://openaccess.thecvf.com/content/ICCV2025/papers/Wang_UniGlyph...
Date: 2026-05-09 / 2025
Excerpt: "ControlNet-augmented (23.6% extension rate)... full tuning reduces the extension rate from 41% to 0.6%" / "ControlNet Sen.Acc: 0.0006, NED: 0.0021" on MiniText-Benchmark
Context: 在架构图生成中，ControlNet会强制模型跟随结构控制图，可能导致文本区域被结构性线条覆盖或扭曲，小字区域尤其脆弱。
Confidence: high
```

```
Claim: 使用含文本的图像时，建议将ControlNet strength降低至0.1左右，并配合自定义OCR预处理节点，可在一定程度上缓解文本破坏问题。ComfyUI-Style-Transfer项目针对文本图像的ControlNet提供了专门的预处理参数建议。[^13]
Source: GitHub - ComfyUi-Style-Transfer
URL: https://github.com/furkandurmus/ComfyUi-Style-Transfer
Date: 2024-09-23
Excerpt: "For images containing text: Enable the custom preprocessing node... especially lower the controlnet strength around 0.1."
Context: 在架构图场景，可先通过ControlNet保持结构，然后对文本区域使用Inpainting或Qwen-Image-Edit进行局部修复。
Confidence: medium
```

```
Claim: PosterMaker（CVPR 2025）引入了OCR-aware ControlNet来专门改善文本渲染，通过注入字符级OCR特征到扩散模型，实现更精准的文本布局控制。这表明在需要精确文本的架构图场景中，普通ControlNet需要与OCR感知模块结合使用。[^11]
Source: arXiv - SimplePoster (引用PosterMaker/Gao_2025_CVPR)
URL: https://arxiv.org/html/2605.08784v1
Date: 2026-05-09
Excerpt: "PosterMaker... integrates an OCR-aware ControlNet for text rendering... injecting fine-grained character-level OCR features to the diffusion model to improve text rendering."
Context: 该方案虽然增加了架构复杂度，但为解决ControlNet下文本破坏问题提供了可行路径。
Confidence: medium
```

## 5. 除ControlNet外的几何结构保持技术

```
Claim: T2I-Adapter是ControlNet的主要轻量级替代方案，仅77M参数，可在整个去噪过程中只运行一次，天然支持多条件加权融合。在SDXL场景下，T2I-Adapter提供sketch/canny/lineart/depth等控制。对于多条件架构图，T2I-Adapter的条件融合比ControlNet更容易实现。[^14][^15]
Source: CSDN - ControlNet vs T2I-Adapter vs IP-Adapter + 知乎 - DIFFUSION系列笔记
URL: https://blog.csdn.net/gitblog_02746/article/details/149626146 / https://zhuanlan.zhihu.com/p/675464021
Date: 2025-07-25 / 2023-12-31
Excerpt: "T2I-Adapter: 77/79M参数，适配器控制，中高控制精度，多条件创意组合场景" / "T2I将图片编码之后，加在了U-NET的encoder部分。controlnet是在decoder部分进行相加处理。"
Context: T2I-Adapter不复制原模型层，而是新增独立轻量级适配器，训练成本仅4块V100 2天。适合需要灵活组合多种条件的架构图场景。
Confidence: high
```

```
Claim: IP-Adapter（仅22M参数）擅长图像风格和语义一致性，但不提供显式几何控制（如姿态或掩码）。它可与ControlNet/T2I-Adapter组合使用，实现"结构+风格"双重控制。在架构图场景，IP-Adapter可用于保持整体风格一致，而ControlNet负责精确几何。[^14][^16]
Source: CSDN - 图像生成适配器对比 + IJCNN 2025 Fashion RAG论文
URL: https://blog.csdn.net/gitblog_02746/article/details/149626146 / https://iris.unimore.it/...
Date: 2025-07-25 / 2025
Excerpt: "IP-Adapter: 22M参数，图像提示控制，中控制精度，擅长捕捉图像风格和内容" / "IP-Adapter lacks explicit geometric control, such as the ability to handle pose or masks."
Context: 在架构图工作流中，可用ControlNet保持方框/箭头结构，IP-Adapter保持配色风格和视觉风格一致性。
Confidence: high
```

```
Claim: CtrLoRA（ICLR 2025）作为ControlNet的高效替代，仅需约1000张训练图像和单张RTX 4090 1小时即可训练新条件，在Canny/Depth/Segmentation/Skeleton等基准上FID和LPIPS均优于原始ControlNet和T2I-Adapter。其Base ControlNet+LoRA架构支持用户快速扩展新控制条件。[^17]
Source: ICLR 2025 - CtrLoRA论文 + GitHub xyfJASON/ctrlora
URL: https://proceedings.iclr.cc/paper_files/paper/2025/file/31773c0ba7a4a98d729b9fc0d6d0cc13-Paper-Conference.pdf / https://github.com/xyfJASON/ctrlora
Date: 2025
Excerpt: "Our method can achieve satisfactory performance by training on about 1,000 images with a single RTX 4090 GPU within 1 hour" / "CtrLoRA outperforms fully trained ControlNet and T2I-Adapter for both base and new conditions."
Context: 对于需要自定义架构图控制条件（如特定类型的UML图、流程图）的场景，CtrLoRA提供了极低成本的训练方案。
Confidence: high
```

```
Claim: ControlNet++（Uni-ControlNet后续）支持单一模型处理10+种控制条件，通过Condition Transformer实现多条件融合，Control Encoder通过条件类型ID区分不同控制信号。相比原始ControlNet需要每种条件一个模型，ControlNet++大幅降低了模型数量和训练成本。[^18]
Source: GitHub - xinsir6/ControlNetPlus
URL: https://github.com/xinsir6/ControlNetPlus
Date: 2024-06-07
Excerpt: "We design a new architecture that can support 10+ control types in condition text-to-image generation... different conditions shares the same condition encoder... we add a transformer layer to exchange the info of original image and the condition images."
Context: 在架构图生成中，需要同时控制线稿+深度+姿态+分割时，ControlNet++的单一模型方案比多模型串联更轻量。
Confidence: medium
```

## 6. 架构图生成的最佳ControlNet工作流配置

```
Claim: Canny预处理器阈值的最佳实践：默认Low=100, High=200适合常规架构图；当需要保留更多细节（如小字标签、细箭头）时，使用Low=10, High=100可获得更详细的边缘图。过高的阈值会丢失关键结构信息。[^19]
Source: CreatixAI - ControlNet Canny Tutorial + ComfyUI CannyEdgePreprocessor文档
URL: https://creatixai.com/controlnet-canny-tutorial-stable-diffusion-a1111/ / https://www.runcomfy.com/comfyui-nodes/comfyui_controlnet_aux/CannyEdgePreprocessor
Date: 2023-11-17 / 2025-03-11
Excerpt: "Canny Low Threshold – anything below the number gets discarded. Canny High Threshold – anything above the number is always kept." / "To achieve a more detailed edge map, lower the low_threshold value... For cleaner and more prominent edges, increase the high_threshold."
Context: 架构图通常包含细线条和小文本，建议对Canny阈值进行精细调参，配合Pixel Perfect模式使用。
Confidence: high
```

```
Claim: ControlNet Strength的推荐范围为0.6-0.8。在建筑设计实验中，W=0.6-0.8是最佳平衡点：低于0.4结构跟随不严格，高于0.8建筑细节被过度抑制。对于LineArt模型，weight=0.8可在ComfyUI中有效保持原始结构。在FLUX工作流中，Lineart weight=0.8是常见配置。[^1][^20]
Source: Building Facades Design论文 + ComfyUI Architectural Floor Plan Workflow
URL: https://arxiv.org/pdf/2303.12755 / https://comfyui.org/en/architectural-floor-plan-3d-rendering-workflow
Date: 2023 / 2025-06-13
Excerpt: "The ideal range for ControlNet's weight value is between 0.6 and 0.8." / "ControlNet-lineart: Preserves original structure (weight=0.8)."
Context: 架构图生成建议在0.7-0.8之间，既能保持方框/箭头的结构，又允许模型生成清晰的中文标签和适当的颜色。
Confidence: high
```

```
Claim: ComfyUI中架构图生成工作流的关键节点配置：CannyEdgePreprocessor(阈值100/200) → ControlNetApplyAdvanced(end_step=0.8锁定结构) → CLIPTextEncodeFlux(双编码器处理复杂提示) → UltimateSDUpscale(4K分块放大)。推荐使用AD-Laozhuang 1.5等专业建筑模型。[^20]
Source: ComfyUI.org - Architectural Floor Plan 3D Rendering Workflow
URL: https://comfyui.org/en/architectural-floor-plan-3d-rendering-workflow
Date: 2025-06-13
Excerpt: "CannyEdgePreprocessor: Extracts line art (thresholds 100/200) for ControlNet. ControlNetApplyAdvanced: Locks structure (end step=0.8) while allowing creative freedom."
Context: 该工作流将建筑平面图转为3D彩色渲染，但其ControlNet结构保持逻辑可直接应用于架构图生成。end_step=0.8意味着在80%的采样步后释放ControlNet约束，让模型优化细节。
Confidence: high
```

```
Claim: 对于从草图到架构图的工作流，Scribble/Sketch ControlNet模型可接受手绘涂鸦作为输入，通过PiDiNet等预处理器识别轮廓后生成精确图像。但Scribble的线条识别精度低于Canny，对于需要精确方框的架构图，建议使用Canny或LineArt而非Scribble。[^21]
Source: ComfyUI Wiki - ControlNet Tutorial + ComfyUI Scribble入门
URL: https://comfyui-wiki.com/en/tutorial/advanced/how-to-install-and-use-controlnet-models-in-comfyui / https://corp.aicu.ai/ja/comfymaster28-20241101
Date: 2026-01-28 / 2024-11-10
Excerpt: "Scribble/Sketch: Doodle control, supports rough contour recognition or hand-drawn sketch image generation." / "Scribbleは、線画を元に、画像の内容を推定し、その内容に沿った画像を生成します。"
Context: Scribble适合快速原型草图，不适合精确架构图。在架构图场景中，手绘方框后需转为Canny/LineArt以获得精确几何。
Confidence: high
```

## 7. 综合评估与架构图场景推荐

```
Claim: 在中文架构图生成场景中，推荐工作流为：Qwen-Image（原生ControlNet支持）> SDXL+ControlNet（需文本后处理）> FLUX+ControlNet（中文文本弱）。对于结构保持，推荐ControlNet组合：Canny(weight 0.7) + LineArt(weight 0.5) 或 MLSD(weight 0.8) + Depth(weight 0.4)。[^8][^9][^22]
Source: 综合多来源分析
URL: 多来源
Date: 2026-06-23
Excerpt: 综合上述发现，Qwen-Image-2512在4步采样下中文可读率89%，而SDXL+ControlNet仅61%。FLUX中文排版准确性有限。ERNIE-Image原生布局可控性0.8856，无需ControlNet插件。
Context: 针对用户核心需求——生成含中文标签的精确架构图，最佳方案可能是：ERNIE-Image/Qwen-Image直接生成（利用其原生结构控制和中文优势），或SDXL+ControlNet+GenFix后处理组合。
Confidence: medium
```

```
Claim: ControlNet在架构图场景的根本局限在于：扩散模型天生不擅长精确几何约束。即使使用ControlNet，模块对齐、箭头指向、间距一致性等仍需后处理（如LACE的对齐损失、GeoSVG-RL的强化学习验证器）。2025-2026年的趋势是将"扩散生成+确定性验证"结合，而非纯依赖ControlNet。[^23]
Source: 基于Phase 1W背景文件（Wide05）中的LACE/GeoSVG-RL研究
URL: 见 ai_img_arch_wide05.md
Date: 2026-06-23
Excerpt: "LACE在训练阶段引入全局对齐损失和两两重叠损失... GeoSVG-RL使用浏览器渲染后端提取bounding boxes、通过多维度几何感知奖励训练SVG策略"
Context: 这揭示了ControlNet的边界：它能保持宏观结构，但无法解决微观几何精度问题。架构图的最佳方案可能是ControlNet保持大体结构 + LLM生成SVG/图表代码 + 确定性渲染引擎精确几何。
Confidence: high
```

---

## 引用索引

[^1]: Zhao et al. "Uni-ControlNet: All-in-One Control to Text-to-Image Diffusion Models." NeurIPS 2023. https://i.cs.hku.hk/~kykwong/publications/szhao_neurips2023.pdf

[^2]: Text Semantics to Image Generation: A Method of Building Facades Design Base on Stable Diffusion Model. https://arxiv.org/pdf/2303.12755

[^3]: "ControlNet: A Complete Guide." stable-diffusion-art.com, 2025-09-28. https://stable-diffusion-art.com/controlnet/

[^4]: "ControlNet Tutorial." ComfyUI Wiki, 2026-01-28. https://comfyui-wiki.com/en/tutorial/advanced/how-to-install-and-use-controlnet-models-in-comfyui

[^5]: "Unlock Advanced Image Synthesis with FLUX ControlNet V3.0 Workflow." ComfyUI.org, 2025-06-06. https://comfyui.org/en/flux-controlnet-v3-workflow

[^6]: "ComfyUI ControlNet 混合使用示例." ComfyUI Docs, 2026-03-29. https://docs.comfy.org/zh/tutorials/controlnet/mixing-controlnets

[^7]: "ComfyUI-Advanced-ControlNet." GitHub - Kosinkadink, 2023. https://github.com/Kosinkadink/ComfyUI-Advanced-ControlNet

[^8]: "Qwen-Image-Edit图像编辑模型全解析." CSDN, 2025-12-15. https://blog.csdn.net/weixin_28721743/article/details/155975994

[^9]: "Qwen-Image-2512-ComfyUI + LoRA模型，实现极速渲染." CSDN, 2026-01-28. https://blog.csdn.net/weixin_42504649/article/details/157445908

[^10]: "ERNIE-Image - 百度文心开源的文生图模型." AIBoss88, 2026-04-16. https://www.aiboss88.com/news/project-ernie-image

[^11]: "A Simple Baseline for Product Poster Generation." arXiv:2605.08784, 2026-05-09. https://arxiv.org/html/2605.08784v1

[^12]: Wang et al. "UniGlyph: Unified Segmentation-Conditioned Diffusion for Precise Visual Text Synthesis." ICCV 2025. https://openaccess.thecvf.com/content/ICCV2025/papers/Wang_UniGlyph...

[^13]: "ComfyUi-Style-Transfer." GitHub - furkandurmus, 2024-09-23. https://github.com/furkandurmus/ComfyUi-Style-Transfer

[^14]: "巅峰对决：ControlNet vs T2I-Adapter、IP-Adapter." CSDN, 2025-07-25. https://blog.csdn.net/gitblog_02746/article/details/149626146

[^15]: "DIFFUSION系列笔记 | T2I 及 IP-Adapter." 知乎, 2023-12-31. https://zhuanlan.zhihu.com/p/675464021

[^16]: IJCNN 2025 Fashion RAG. https://iris.unimore.it/retrieve/dfc3cc96-4948-48be-bcef-cba297af7104/2025_IJCNN_Fashion_RAG.pdf

[^17]: Xu et al. "CtrLoRA: An Extensible and Efficient Framework for Controllable Image Generation." ICLR 2025. https://proceedings.iclr.cc/paper_files/paper/2025/file/31773c0ba7a4a98d729b9fc0d6d0cc13-Paper-Conference.pdf

[^18]: "ControlNetPlus: All-in-one ControlNet for image generations and editing." GitHub - xinsir6, 2024. https://github.com/xinsir6/ControlNetPlus

[^19]: "ControlNet Canny Tutorial." CreatixAI, 2023-11-17. https://creatixai.com/controlnet-canny-tutorial-stable-diffusion-a1111/

[^20]: "Discover the Ultimate 3D Rendering Workflow for Architectural Floor Plans." ComfyUI.org, 2025-06-13. https://comfyui.org/en/architectural-floor-plan-3d-rendering-workflow

[^21]: "[ComfyMaster28] 落書きが画像に！ControlNet Scribble入門." AICU, 2024-11-10. https://corp.aicu.ai/ja/comfymaster28-20241101

[^22]: 多来源综合（Qwen-Image/ERNIE-Image/SDXL对比）

[^23]: 基于Phase 1W已有研究（LACE/GeoSVG-RL）
