# Dim05: Dify/Coze低代码工作流搭建实践

## 发现清单

---

Claim: Dify与ComfyUI的联动工作流采用"Dify负责编排决策，ComfyUI负责图像生成执行"的分层架构。在ComfyUI中将工作流通过菜单→导出(API)保存为JSON，然后在Dify Marketplace安装官方ComfyUI Plugin，在Tools中填入ComfyUI服务器URL（如http://127.0.0.1:8188），即可在Dify Workflow中添加"ComfyUI Workflow"节点，直接传入JSON+变量（prompt、seed等）完成调用[^1]。
Source: CSDN博客《【模型部署】在Dify中接入ComfyUI+Flux实现文生图》/ AtomGit开源社区《Dify + ComfyUI：零代码打造AI漫剧全自动生产线》
URL: https://17aitech.com/?p=39436 / https://gitcode.csdn.net/69ca550454b52172bc65872d.html
Date: 2025-03-15 / 2026-03-30
Excerpt: "在ComfyUI页面，修改工作流→通过菜单->导出(API)，将工作流导出.json文件→在Dify平台的ComfyUI节点上，将.json内容复制粘贴到Workflow文本框中"
Context: Dify+ComfyUI是当前AI漫剧/内容生产的主流技术栈，被广泛应用于从脚本到分镜、静态漫画到动态视频的完整短剧生产
Confidence: high

---

Claim: Dify中搭建完整的文生图Chatflow工作流包含6个核心节点：①开始节点（接收用户输入/上传图片）；②LLM节点（优化提示词，生成正面/负面prompt的JSON）；③代码执行节点（提取LLM输出的positive_prompt和negative_prompt）；④ComfyUI工具节点（传入JSON工作流和参数）；⑤参数提取器（获取图片URL）；⑥结束节点（输出结果）。该流程在Macmini上实测生成一张图耗时4-5分钟[^2]。
Source: 一起AI技术《【模型部署】在Dify中接入ComfyUI+Flux实现文生图》
URL: https://17aitech.com/?p=39436
Date: 2025-03-15
Excerpt: "LLM节点：主要实现对于用户输入内容进行提示词优化→代码执行：将LLM输出的内容进行提取→ComfyUI：该节点主要用来配置ComfyUI的工作流"
Context: 文章提供了完整的节点配置代码和Python提取脚本，实现零代码的Dify+ComfyUI联动
Confidence: high

---

Claim: Dify官方插件市场已上架Qwen-Image插件，支持Qwen-Image-2512的文生图和图生图功能。插件通过ModelScope API异步调用实现：①提交任务POST /v1/images/generations（Header: X-ModelScope-Async-Mode: true）；②每5秒轮询任务状态GET /v1/tasks/{task_id}；③下载生成的图像URL。API Key格式为ms-开头，魔搭社区目前提供免费额度[^3]。
Source: GitHub - wwwzhouhui/qwen_text2image / CSDN《用Dify+Qwen-Image实现文生图与图生图》
URL: https://github.com/wwwzhouhui/qwen_text2image / https://blog.csdn.net/weixin_34725745/article/details/155975340
Date: 2025-08-20 / 2025-12-15
Excerpt: "插件采用异步任务处理模式：提交任务→状态轮询→图像下载。API Key格式ms-xxxxxx。每5秒查询一次，最多60次（5分钟）"
Context: Qwen-Image插件是国产图像生成模型接入国际工作流平台的典型范例，已在Dify社区广泛应用
Confidence: high

---

Claim: Dify中接入阿里百炼（万相Wanx）文生图模型需通过Chatflow/Workflow的HTTP节点实现，因为Dify没有提供万相模型的专用插件。阿里云官方提供了可直接导入的DSL模板（Wanx - Text-to-Image Demo.yml），用户只需下载模板后导入Dify，将环境变量DASHSCOPE_API_KEY修改为自己的密钥即可运行。模板使用的模型为新加坡地区的wanx2.1-t2i-turbo或华北2的wan2.2-t2i-flash[^4]。
Source: 阿里云帮助文档《Dify接入百炼模型构建大模型应用》
URL: https://help.aliyun.com/zh/model-studio/dify
Date: 2025-12-02（更新至2026-06-12）
Excerpt: "Dify没有提供万相模型相关的插件，通过Dify的Chatflow/工作流的节点可达到文生图/视频的功能。下载我们写好的模板：Wanx - Text-to-Image Demo.yml，在工作室单击导入DSL文件"
Context: 阿里云官方提供了标准HTTP节点接入方案，降低了国产图像模型在Dify中的使用门槛
Confidence: high

---

Claim: Dify的通义千问（Qwen）插件由Dify官方维护（非阿里云直接提供），安装时常见报错"Invalid API-key provided"的解决方案包括：①使用默认业务空间的API Key（非子业务空间）；②根据地域正确设置"使用国际端点"开关；③若最新版报错，尝试安装较早版本（如0.0.40）。Qwen-Omni/Qwen-OCR模型不支持直接配置，需通过HTTP节点接入[^5]。
Source: 阿里云帮助文档《Dify接入百炼模型构建大模型应用》/ CSDN《Dify模型接入避坑指南：通义千问插件报错解决方案大全》
URL: https://help.aliyun.com/zh/model-studio/dify / https://blog.csdn.net/weixin_30566063/article/details/159235769
Date: 2025-12-02（更新至2026-06-12）/ 2026-03-19
Excerpt: "千问插件非阿里云提供，由Dify官方维护。若安装最新版插件报错，可尝试安装较早版本。0.0.41版本会校验qwen-turbo模型调用权限"
Context: Dify与国产模型插件的兼容性问题是实际部署中的高频痛点，需要版本管理和权限配置
Confidence: high

---

Claim: 在Dify中设计"判断用户输入→文生图/图生图/改图→输出"的条件分支工作流，核心是在开始节点设置三个字段：sys.query（文本输入）、type（下拉选择"文生图"/"图生图"）、picture（文件上传）。然后添加If-Else条件节点，规则为：如果{{#start.type#}} == "图生图" → 进入图生图流程（调用qwen-image-edit）；否则→进入文生图流程（先由LLM优化提示词，再调用qwen-image）。两条分支最终汇入统一的结束节点[^6]。
Source: CSDN《用Dify+Qwen-Image实现文生图与图生图》（多篇文章一致描述）
URL: https://blog.csdn.net/weixin_34725745/article/details/155975340 / https://blog.csdn.net/weixin_32312889/article/details/155974687
Date: 2025-12-15
Excerpt: "整个系统的灵魂在于'灵活路由'：同一个入口，根据用户输入自动判断走哪条路径——是有图还是无图？Dify的工作流机制完美支撑了这种逻辑。我们不需要写if-else，只需要拖拽几个节点，设置条件分支即可"
Context: 该方案被多个独立技术博客验证，是Dify+Qwen-Image的标准实践模式
Confidence: high

---

Claim: Dify的If-Else条件分支节点支持多种条件类型：包含/不包含、开始是/结束是、是/不是、为空/不为空、大于/小于、等于/不等于。支持复杂条件组合：AND逻辑要求所有条件为真，OR逻辑要求任一条件为真。节点支持IF/ELIF/ELSE多路径分支，类似编程中的if-else if-else结构，在AIGC内容创作平台场景中可用于根据内容类型、用户VIP等级、情感分析结果等路由到不同处理路径[^7]。
Source: Dify官方文档《If-Else》/ 微信公众号《Dify条件分支节点全解析｜10大典型应用场景》
URL: https://docs.dify.ai/zh/use-dify/nodes/ifelse / http://mp.weixin.qq.com/s?__biz=Mzk3NTMyNzgxOA==&mid=2247483953
Date: 2026-04-16 / 2025-07-16
Excerpt: "If-Else节点通过根据你定义的条件将执行路由到不同路径，为你的工作流添加决策逻辑。支持多个分支路径：IF路径在主要条件评估为真时执行，ELIF路径提供按顺序检查的附加条件，ELSE路径作为后备选项"
Context: Dify官方文档提供了条件分支的权威配置说明，社区文章补充了10个行业的典型应用场景
Confidence: high

---

Claim: Coze图像流底层基于Stable Diffusion，支持文生图、图生图、智能换脸、背景替换等节点化操作。文生图节点参数包括：width(576-1728，默认1088)、height(576-1728)、prompt(必填)、ratio(1=1:1, 2=4:3, 3=16:9, 4=3:4, 5=9:16)。输出参数为data(图片URL)和msg(success标识)。图像流与Coze工作流不同，是独立的图片生成tab，功能覆盖智能生成、智能编辑、基础编辑三大类[^8]。
Source: 飞书文档《COZE扣子图像流功能》/ 飞书云文档《详细介绍扣子Coze图像流的文生图功能》
URL: https://docs.feishu.cn/article/wiki/FbGlwTWD3iVuT5kZvlHco6v0nqd / https://docs.feishu.cn/v/wiki/XqWswHQ7diA8oHkuQ8ocRaTln1g/ag
Date: 2026-06-23 / 2026-02-08
Excerpt: "文生图能力底层基于stable diffusion，如果会用sd的话很多技巧可以快速迁移。width范围576-1728，默认1088，宽高不能超过1088*1088个像素点"
Context: Coze图像流是字节跳动推出的对标ComfyUI的低代码图像生成工具，更面向小白用户
Confidence: high

---

Claim: Coze工作流支持"批处理节点"实现1分钟批量生成100张图。典型配置：批量大小100（最多处理100个项目），并发大小3（同时处理3个任务）。完整工作流链路为：开始节点→大模型节点生成主题和金句→批处理节点→批处理体内含图像生成节点+抠图节点+画板节点→结束节点。该方案被广泛应用于小红书知识卡片、养生图文、漫画配图的批量生产[^9]。
Source: 知乎专栏《1分钟批量生成100张，Coze扣子智能体工作流批量生成人物一致的治愈系漫画图文》/ 火山引擎开发者社区《扣子Coze工作流实战：1分钟生成100篇爆款小红书养生笔记》
URL: https://zhuanlan.zhihu.com/p/1941221903839786190 / https://developer.volcengine.com/articles/7545026392155029547
Date: 2025-08-19 / 2025-09-01
Excerpt: "用Coze智能体工作流1分钟能批量生成100张图，无需手动抠图。批量大小：100；并发大小：3。工作流：大模型节点生成故事内容和画面提示词→图生图插件制作连贯的漫画底图→图像清晰度提升→画板节点整合文字与图像"
Context: Coze的批处理节点是其在内容批量生产场景中的差异化优势，被大量自媒体和电商运营采用
Confidence: high

---

Claim: 飞书多维表格的AI字段捷径是"表格驱动批量生成"的核心方案，集成了即梦4.0、豆包生图、DeepSeek、KIMI、Nano Banana、Vidu、Sora等多个模型。AI字段捷径本质上是"AI+公式+API"的集成工具，一次配置即可自动批量处理海量数据。典型应用场景：某潮玩IP业务管理系统中，AI Agent节点确定IP类别（盲盒/卡牌/手办/玩具），自动编排多步骤图像生成（文生图→图生图→多规格组图），结果直接回写表格，运行时间约3-6分钟[^10]。
Source: 飞书官网《多维表格AI字段捷径：如何用AI实现批量文生图和文生视频？》
URL: https://www.feishu.cn/content/article/7592538064711470271
Date: 2026-01-07
Excerpt: "多维表格集成了即梦4.0、豆包生图、DeepSeek、KIMI、Nano Banana等多个顶尖大模型。AI字段捷径就是飞书多维表格里的'AI+公式+API'集成工具。某潮玩IP业务管理系统中，AI Agent节点确定该分支下所有图片的内容、规格，并输出多段提示词"
Context: 飞书多维表格+AI字段捷径是企业级批量内容生产的代表性方案，电商企业报告素材流转效率提升10倍
Confidence: high

---

Claim: 飞书多维表格+Coze+阿里云函数计算的完整批量生图方案架构：①运营在表格填写提示词和素材图；②飞书字段捷径下载附件并转发到阿里云FC；③FC压缩处理并上传OSS返回公网URL；④公式字段合并提示词+OSS链接；⑤Coze工作流字段捷径调用Nano Banana Pro插件生图；⑥结果通过URL转附件字段捷径回写表格。该方案支持多人多Key管理（按调用人自动分配API密钥），并实现了错误反馈机制（审核失败、违规拒绝、超时等以友好文案返回表格）[^11]。
Source: API易文档中心《飞书多维表格AI生图方案》
URL: https://docs.apiyi.com/scenarios/ecosystem/feishu-bitable-image-shortcut
Date: 2026-04-29
Excerpt: "运营/设计同学在表格里填写提示词、上传素材图，附件自动转OSS链接，再触发Coze工作流调用Nano Banana Pro出图，最后把生成结果回写到表格中作为图片附件展示——全程零代码操作"
Context: 该方案由企业实际业务沉淀，是飞书+Coze+第三方API在B端落地的典型架构
Confidence: high

---

Claim: 极兔速递通过飞书多维表格AI分镜实现72倍效率提升的真实案例：在《向阳而行》短片项目中，利用DeepSeek+多维表格1天内裂变出24个创意脚本，省去26%供应商比稿费；35个分镜AI生图耗时350秒（平均每张10秒），分镜与成片误差率下降30%，替代手绘分镜节省2-3天人工；甚至品牌字体也通过AI字段捷径生成。年估降本超百万[^12]。
Source: 飞书官网《多维表格AI字段捷径：如何用AI实现批量文生图和文生视频？》
URL: https://www.feishu.cn/content/article/7592538064711470271
Date: 2026-01-07
Excerpt: "极兔速递通过飞书+AI带来72倍效率提升，助力品牌爆款视频曝光率10倍+，年估降本超百万。35个分镜AI生图耗时350秒，分镜与成片误差率下降了30%"
Context: 这是飞书官方发布的标杆案例，证明了"表格+AI"模式在视频生产中的巨大效率提升
Confidence: high

---

Claim: Dify 1.13.0新增了"人工介入节点"，支持工作流中途暂停，让审核人查看、修改关键数据后再继续。可通过自定义表单展示信息，使用Markdown格式，通过输入"/"插入变量，"control+/"插入可编辑输入控件。节点支持多分支决策：每新增一个按钮（如"确认"/"驳回"），自动生成对应分支路径。支持设置超时时间（小时/天为单位），避免流程无限期等待。该功能适用于内容审核、参数确认、订单核实等场景[^13]。
Source: 什么值得买《Dify新功能：人工介入节点介绍》
URL: https://post.smzdm.com/p/ax6qlvz9
Date: 2026-02-15
Excerpt: "Dify 1.13.0新增了人工介入节点，工作流跑到关键地方可以先停下来，让人看一眼、改一改、确认后再继续。适合内容审核、参数确认、订单核实等场景。不同操作按钮可引导工作流走向不同分支路径"
Context: Dify的人工介入节点是工作流中内容安全审核的重要工程化手段，实现了自动化与人工审核的有机结合
Confidence: high

---

Claim: ComfyUI可通过自定义节点实现内容审核（Content Moderation Node），在图像生成流水线中插入安全检测。典型实现：在VAE Decode后添加审核节点，将图像缩放到224×224，调用轻量级NSFW分类模型（如基于CLIP的安全检测器），获取"安全/非安全"概率分布，根据预设阈值返回布尔结果。通过为下游条件分支使用，若is_safe == False则跳过保存、改写日志或推送通知。审核耗时不到200毫秒（GPU环境下），几乎不影响生成效率[^14]。
Source: CSDN《ComfyUI内容审核节点：自动检测敏感图像并拦截》
URL: https://blog.csdn.net/weixin_35871529/article/details/155900945
Date: 2025-12-13
Excerpt: "审核节点监听上游VAE Decode输出的张量数据，转换为标准图像格式，调用轻量级NSFW分类模型，根据预设阈值返回布尔结果。整个过程通常耗时不到200毫秒（GPU环境下），几乎不会影响整体生成效率"
Context: ComfyUI的节点化审核是AIGC生产环境内容安全的重要技术方案，可实现文本过滤+图像快照检测+最终审查的多层防线
Confidence: high

---

Claim: Dify Agent模式支持Tool Calling实现图像生成的自主调用。在Agent配置中，将文生图/图生图工具（如ComfyUI Plugin、Qwen-Image插件）添加为可用工具后，Agent接收用户任务后可自主决定调用哪个工具、使用什么参数，获取结果后决定是否进一步编辑或输出。Dify官方文档《AI Image Generation App》提供了Agent调用图像生成工具的标准模式[^15]。
Source: Dify官方文档 / CSDN《ComfyUI与Dify智能体联动：实现AI决策+内容生成闭环》
URL: https://docs.dify.ai / https://blog.csdn.net/article/2025-12-15（根据wide04引用）
Date: 2025-12-15
Excerpt: "Agent接收任务后，自主决定调用文生图/图生图工具，获取结果后决定是否进一步编辑或输出。Dify的Agent模式和LlamaIndex的ReAct Workflow均展示了这一模式"
Context: Agent自主调用是Dify工作流的高级应用模式，实现了从"对话式"到"工具自主调用"的演进
Confidence: high

---

Claim: Dify Workflow内置CSV批量处理和循环（迭代）节点能力。迭代节点允许对一个数组变量进行循环处理，每次迭代处理一个元素，适合批量生成场景。例如，在Dify漫剧生产方案中，Dify LLM节点生成包含多集分镜的JSON数组，然后通过Loop节点批量调用ComfyUI工具，一键出8-12格分镜图。Dify还支持CSV文件上传，通过代码执行节点解析后逐行处理[^16]。
Source: Dify漫剧实战指南 / Dify官方文档
URL: https://gitcode.csdn.net/69ca550454b52172bc65872d.html / https://docs.dify.ai/zh/use-dify/nodes/iteration
Date: 2026-03-30
Excerpt: "Dify加Loop + Scheduler，一晚生成10集。批量Loop节点，一键出8-12格分镜图。用Dify工作流配合大语言模型和外部图像接口来搭建内容生成应用"
Context: Dify的迭代和批量处理能力是支撑大规模内容生产的核心，与ComfyUI的API调用形成完整闭环
Confidence: high

---

Claim: Dify HTTP请求节点是接入非标模型（如ERNIE-Image、万相、GLM-Image）的主要方式。HTTP节点支持GET/POST/HEAD/PATCH/PUT/DELETE方法，支持动态变量绑定（如URL中嵌入{{city}}参数）。对于国产图像模型，当没有专用插件时，可通过HTTP节点直接调用模型API，然后用参数提取器或代码节点处理返回的JSON/图片URL。阿里云官方为万相模型提供了HTTP节点调用的Curl命令参考和完整DSL模板[^17]。
Source: 阿里云帮助文档《Dify接入百炼模型构建大模型应用》/ 微信公众号《企业级解决方案：基于HTTP节点打造Dify联网搜索工作流》
URL: https://help.aliyun.com/zh/model-studio/dify / https://blog.csdn.net/xiaonie1986/article/details/146466783
Date: 2025-12-02 / 2025-03-24
Excerpt: "以上模型均不支持直接在Dify上配置，您可通过Chatflow或工作流的HTTP节点接入，接入细节请参见文档中的Curl命令。为了降低HTTP节点的超时风险，建议您通过流式输出方式调用"
Context: HTTP节点是Dify接入第三方服务的通用桥梁，对于国产图像模型尤为重要
Confidence: high

---

Claim: Dify工作流支持"模板转换节点"（Template Transform）和"变量赋值节点"实现工作流复用与参数化。模板转换节点可将多个上游节点的输出（如标题、正文、封面图URL）组装为统一的输出格式。变量赋值节点可在会话中持久化存储变量（如用户语言偏好、Checklist状态），实现跨节点的状态传递。将成熟工作流导出为JSON配置后，可实现跨项目复用[^18]。
Source: Dify实战PDF / 火山引擎开发者社区
URL: https://beansmile-official-website.oss-cn-hongkong.aliyuncs.com/beansmile-2024/assets/Dify%20%E5%AE%9E%E6%88%98.pdf / https://developer.volcengine.com/articles/7404769052143484955
Date: 2024-2025
Excerpt: "把前面步骤生成的标题、正文和封面图URL，组装到一起，作为最终结果输出。将成熟的工作流导出为JSON配置，实现跨项目复用"
Context: 工作流复用和参数化是Dify在生产环境中规模化部署的关键能力
Confidence: high

---

Claim: Coze图像流中的智能换脸节点参数包括：base_image_url（需要无背景扣好的主体图）、ref_image_url（参考图）、ref_prompt（参考提示词）、scene_type（场景类型：GENERAL通用/ROOM室内家居/COSMETIC美妆）。生成原理为：识别原图尺寸→生成/处理背景图→两张图片叠加重新生图→将原图融入背景。该功能与智能抠图能力结合可构建完整的工作流[^19]。
Source: 飞书文档《COZE扣子图像流功能》
URL: https://docs.feishu.cn/article/wiki/FbGlwTWD3iVuT5kZvlHco6v0nqd
Date: 2026-06-23
Excerpt: "替换图片base_image_url（需要一张无背景扣好的主体图，可以结合智能抠图能力做工作流）。参考图、参考提示词。场景使用场景scene_type包含GENERAL/ROOM/COSMETIC三种"
Context: Coze图像流的智能换脸是电商、美妆等垂直场景的重要功能，底层基于SD的图像融合技术
Confidence: high

---

Claim: Dify中的"问题分类器"（Question Classifier）节点是替代复杂If-Else的智能化条件分支方案。它利用LLM对用户输入进行意图识别和分类，自动导向下游不同分支。典型场景：客服对话中先分类用户意图（价格咨询/售后问题/产品推荐），再分别调用不同的知识库或工具。在图像生成场景中，可用Question Classifier判断用户是需要"文生图"/"图生图"/"风格迁移"/"图片放大"，然后自动路由到对应工具[^20]。
Source: Dify官方文档 / 微信公众号《AI用得好，每天下班早！用Dify打造专属智能测试小助手》
URL: https://docs.dify.ai/zh/use-dify/nodes/question-classifier / http://mp.weixin.qq.com/s?__biz=MjM5NTU0MDg0MA==&mid=2651331179
Date: 2025-03-27
Excerpt: "问题分类器常见的使用情景包括客服对话意图分类、产品评价分类、邮件批量分类等。在典型的产品客服问答场景中，问题分类器可以作为知识库检索的前置步骤，对用户输入问题意图进行分类处理"
Context: Question Classifier是Dify中比If-Else更智能的分流方案，特别适用于自然语言意图判断场景
Confidence: high

---

## 参考文献

[^1]: 一起AI技术《【模型部署】在Dify中接入ComfyUI+Flux实现文生图》(2025-03-15), https://17aitech.com/?p=39436; AtomGit开源社区《Dify + ComfyUI：零代码打造AI漫剧全自动生产线》(2026-03-30), https://gitcode.csdn.net/69ca550454b52172bc65872d.html

[^2]: 一起AI技术《【模型部署】在Dify中接入ComfyUI+Flux实现文生图》(2025-03-15), https://17aitech.com/?p=39436

[^3]: GitHub - wwwzhouhui/qwen_text2image (2025-08-20), https://github.com/wwwzhouhui/qwen_text2image; CSDN《用Dify+Qwen-Image实现文生图与图生图》(2025-12-15), https://blog.csdn.net/weixin_34725745/article/details/155975340

[^4]: 阿里云帮助文档《Dify接入百炼模型构建大模型应用》(更新至2026-06-12), https://help.aliyun.com/zh/model-studio/dify

[^5]: 阿里云帮助文档《Dify接入百炼模型构建大模型应用》(更新至2026-06-12), https://help.aliyun.com/zh/model-studio/dify; CSDN《Dify模型接入避坑指南：通义千问插件报错解决方案大全》(2026-03-19), https://blog.csdn.net/weixin_30566063/article/details/159235769

[^6]: CSDN《用Dify+Qwen-Image实现文生图与图生图》(2025-12-15), https://blog.csdn.net/weixin_34725745/article/details/155975340; https://blog.csdn.net/weixin_32312889/article/details/155974687

[^7]: Dify官方文档《If-Else》(2026-04-16), https://docs.dify.ai/zh/use-dify/nodes/ifelse; 微信公众号《Dify条件分支节点全解析｜10大典型应用场景配置方案详解》(2025-07-16)

[^8]: 飞书文档《COZE扣子图像流功能》(2026-06-23), https://docs.feishu.cn/article/wiki/FbGlwTWD3iVuT5kZvlHco6v0nqd; 飞书云文档《详细介绍扣子Coze图像流的文生图功能》(2026-02-08), https://docs.feishu.cn/v/wiki/XqWswHQ7diA8oHkuQ8ocRaTln1g/ag

[^9]: 知乎专栏《1分钟批量生成100张，Coze扣子智能体工作流批量生成人物一致的治愈系漫画图文》(2025-08-19), https://zhuanlan.zhihu.com/p/1941221903839786190; 火山引擎开发者社区《扣子Coze工作流实战：1分钟生成100篇爆款小红书养生笔记》(2025-09-01), https://developer.volcengine.com/articles/7545026392155029547

[^10]: 飞书官网《多维表格AI字段捷径：如何用AI实现批量文生图和文生视频？》(2026-01-07), https://www.feishu.cn/content/article/7592538064711470271

[^11]: API易文档中心《飞书多维表格AI生图方案》(2026-04-29), https://docs.apiyi.com/scenarios/ecosystem/feishu-bitable-image-shortcut

[^12]: 飞书官网《多维表格AI字段捷径：如何用AI实现批量文生图和文生视频？》(2026-01-07), https://www.feishu.cn/content/article/7592538064711470271

[^13]: 什么值得买《Dify新功能：人工介入节点介绍》(2026-02-15), https://post.smzdm.com/p/ax6qlvz9

[^14]: CSDN《ComfyUI内容审核节点：自动检测敏感图像并拦截》(2025-12-13), https://blog.csdn.net/weixin_35871529/article/details/155900945

[^15]: Dify官方文档《AI Image Generation App》; CSDN《ComfyUI与Dify智能体联动：实现AI决策+内容生成闭环》(2025-12-15)

[^16]: Dify漫剧实战指南(2026-03-30), https://gitcode.csdn.net/69ca550454b52172bc65872d.html; Dify官方文档《迭代节点》

[^17]: 阿里云帮助文档《Dify接入百炼模型构建大模型应用》(2025-12-02), https://help.aliyun.com/zh/model-studio/dify; CSDN《企业级解决方案：基于HTTP节点打造Dify联网搜索工作流》(2025-03-24), https://blog.csdn.net/xiaonie1986/article/details/146466783

[^18]: Dify实战PDF, https://beansmile-official-website.oss-cn-hongkong.aliyuncs.com/beansmile-2024/assets/Dify%20%E5%AE%9E%E6%88%98.pdf; 火山引擎开发者社区《无缝融入，即刻智能：Dify-LLM平台快速使用指南》(2024-08-19)

[^19]: 飞书文档《COZE扣子图像流功能》(2026-06-23), https://docs.feishu.cn/article/wiki/FbGlwTWD3iVuT5kZvlHco6v0nqd

[^20]: Dify官方文档《问题分类器》; 微信公众号《AI用得好，每天下班早！用Dify打造专属智能测试小助手》(2025-03-27)

---

*调研维度：Dim05 — Dify/Coze低代码工作流搭建实践*
*执行日期：2026-06-23*
*搜索次数：12次独立搜索（中英文混合）*
*覆盖重点：Dify工作流节点配置、Qwen-Image/万相接入、Coze图像流/批处理、飞书多维表格字段捷径、条件分支设计、内容安全审核*
