"""Chinese tip translations for the random tip display.

Loaded by ``hermes_cli/tips.py::get_random_tip()`` when
``HERMES_LANGUAGE`` starts with ``zh``.

可移除性：删除此文件后，中文环境用户回退到英文 tips，
功能不受影响。
"""

TIPS = [
    # --- Slash 命令 ---
    "/background <prompt>（别名 /bg 或 /btw）在独立 session 中运行任务，当前对话保持空闲。",
    "/branch 分叉当前会话，让你在不丢失进度的情况下探索不同方向。",
    "/compress 手动压缩对话上下文，内容过长时使用。",
    "/rollback 列出文件系统检查点 — 将 agent 修改过的文件恢复到任意之前的状态。",
    "/rollback diff 2 预览自检查点 2 以来的变更，不实际恢复。",
    "/rollback 2 src/file.py 从指定检查点恢复单个文件。",
    '/title "my project" 为会话命名 — 之后可用 /resume 或 hermes -c 继续。',
    "/resume 继续之前命名的会话。",
    "/queue <prompt> 将消息排队到下一轮，不打断当前执行。",
    "/undo 删除最后一轮用户/助手交互。",
    "/retry 重发你的最后一条消息 — 当 agent 的回复不够好时使用。",
    "/verbose 循环切换工具进度显示模式：off → new → all → verbose。",
    "/reasoning high 提高模型的思考深度。/reasoning show 显示推理过程。",
    "/fast 切换优先处理模式，获取更快的 API 响应（取决于 provider）。",
    "/yolo 跳过本会话中所有危险命令审批提示。",
    "/model 让你中途切换模型 — 试试 /model sonnet 或 /model gpt-5。",
    "/model --global 永久更改默认模型。",
    "/personality pirate 设置趣味人格 — 14 种内置选项，从 kawaii 到 shakespeare。",
    "/skin 更换 CLI 主题 — 试试 ares、mono、slate、poseidon 或 charizard。",
    "/statusbar 切换持久状态栏，显示模型、token、上下文填充率、费用和时长。",
    "/tools disable browser 临时移除当前会话的 browser 工具。",
    "/browser connect 通过 CDP 将 browser 工具连接到你正在运行的 Chromium 系列 browser。",
    "/plugins 列出已安装的插件及其状态。",
    "/cron 管理定时任务 — 设置循环提示，可投递到任意平台。",
    "/reload-mcp 热重载 MCP 服务器配置，无需重启。",
    "/usage 显示 token 用量、费用明细和会话时长。",
    "/insights 显示最近 30 天的使用分析。",
    "/paste 检查剪贴板中的图片并附加到下一条消息。",
    "/profile 显示当前活跃的 profile 名称及其 home 目录。",
    "/config 显示当前配置概览。",
    "/stop 终止 agent 启动的所有后台进程。",

    # --- @ 上下文引用 ---
    "@file:path/to/file.py 将文件内容直接注入你的消息。",
    "@file:main.py:10-50 只注入文件的第 10-50 行。",
    "@folder:src/ 注入目录树列表。",
    "@diff 注入你未暂存的 git 变更。",
    "@staged 注入你已暂存的 git 变更（git diff --staged）。",
    "@git:5 注入最近 5 条提交及其完整补丁。",
    "@url:https://example.com 获取并注入网页内容。",
    "输入 @ 触发文件系统路径补全 — 交互式导航到任意文件。",
    '可以组合多个引用："Review @file:main.py and @file:test.py for consistency."',

    # --- 快捷键 ---
    "Alt+Enter 插入换行，用于多行输入。（Windows Terminal 会拦截 Alt+Enter — 改用 Ctrl+Enter。）",
    "Ctrl+C 中断 agent。2 秒内双击强制退出。",
    "Ctrl+Z 将 Hermes 挂起到后台 — 在 shell 中运行 fg 恢复。",
    "Tab 接受自动建议的幽灵文本或补全 slash 命令。",
    "在 agent 工作时输入新消息可以中断并重定向。",
    "Alt+V 从剪贴板粘贴图片到对话中。",
    "粘贴 5 行以上内容会自动保存到文件，并插入紧凑引用。",

    # --- CLI 参数 ---
    'hermes -c 继续最近的 CLI 会话。hermes -c "project name" 按标题继续。',
    "hermes -w 创建一个隔离的 git worktree — 适合并行 agent 工作流。",
    'hermes -w -q "Fix issue #42" 组合 worktree 隔离和一次性查询。',
    "hermes chat -t web,terminal 只启用特定 toolset 的专注会话。",
    "hermes chat -s github-pr-workflow 启动时预加载 skill。",
    'hermes chat -q "query" 运行单次非交互查询后退出。',
    "hermes chat --max-turns 200 覆盖默认的每轮 90 次迭代限制。",
    "hermes chat --checkpoints 在每次破坏性文件变更前启用文件系统快照。",
    "hermes --yolo 跳过整个会话的所有危险命令审批提示。",
    "hermes chat --source telegram 为会话打标签，方便在 hermes sessions list 中筛选。",
    "hermes -p work chat 在指定 profile 下运行，不改变默认配置。",
    "hermes doctor --fix 诊断并自动修复配置和依赖问题。",
    "hermes dump 输出精简的配置摘要 — 适合写 bug 报告。",

    # --- CLI 子命令 ---
    "hermes config set KEY VALUE 自动将密钥路由到 .env，其余写入 config.yaml。",
    "hermes config edit 在默认编辑器中打开 config.yaml。",
    "hermes config check 扫描缺失或过期的配置项。",
    "hermes sessions browse 打开带搜索的交互式会话选择器。",
    "hermes sessions stats 显示各平台会话数和数据库大小。",
    "hermes sessions prune --older-than 30 清理旧会话。",
    "hermes skills search react --source skills-sh 搜索 skills.sh 公共目录。",
    "hermes skills check 扫描已安装的 hub skill 是否有上游更新。",
    "hermes skills tap add myorg/skills-repo 添加自定义 GitHub skill 来源。",
    "hermes skills snapshot export setup.json 导出 skill 配置用于备份或分享。",
    "hermes mcp add github --command npx 从命令行添加 MCP 服务器。",
    "hermes mcp serve 将 Hermes 自身作为 MCP 服务器供其他 agent 使用。",
    "hermes auth add 让你添加多个 API key 用于凭证池轮换。",
    "hermes completion bash >> ~/.bashrc 为所有命令和 profile 启用 tab 补全。",
    "hermes logs -f 实时跟踪 agent.log。--level WARNING --since 1h 过滤输出。",
    "hermes backup 创建整个 Hermes home 目录的 zip 备份。",
    "hermes profile create coder 创建隔离的 profile，它会成为独立的命令。",
    "hermes profile create work --clone 将当前配置和密钥复制到新 profile。",
    "hermes update 自动将新的内置 skill 同步到所有 profile。",
    "hermes gateway install 将 Hermes 安装为系统服务（systemd/launchd）。",
    "hermes memory setup 让你配置外部 memory provider（Honcho、Mem0 等）。",
    "hermes webhook subscribe 创建带 HMAC 验证的事件驱动 webhook 路由。",
    "省钱技巧：hermes tools 禁用不用的工具，hermes skills config 精简 skill 列表。",
    "/reasoning low 或 /reasoning minimal 将思考深度降到默认（medium）以下 — 更快更省。",
    "hermes models routes 将 vision、压缩和辅助任务路由到更便宜的模型 — 不降级主聊天模型的情况下削减 85%+ 的后台 token 开销。",

    # --- 配置 ---
    "在 config.yaml 中设置 display.bell_on_complete: true，长任务完成时响铃。",
    "设置 display.streaming: true 实时查看模型生成 token。",
    "设置 display.show_reasoning: true 观看模型的思维链推理。",
    "设置 display.compact: true 减少输出空白，信息更紧凑。",
    "设置 display.busy_input_mode: queue 排队消息而非中断 agent，或设为 steer 通过 /steer 中途注入。",
    "设置 display.resume_display: minimal 恢复会话时跳过完整对话回顾。",
    "设置 compression.threshold: 0.50 控制自动压缩触发时机（默认：上下文 50%）。",
    "设置 agent.max_turns: 200 让 agent 每轮执行更多工具调用步骤。",
    "设置 file_read_max_chars: 200000 增加每次 read_file 调用的最大内容量。",
    "设置 approvals.mode: smart 让 LLM 自动批准安全命令、自动拒绝危险命令。",
    "在 config.yaml 中设置 fallback_model 自动故障转移到备用 provider。",
    "设置 privacy.redact_pii: true 在发送给 LLM 之前哈希用户 ID 和电话号码。",
    "设置 browser.record_sessions: true 自动将 browser 会话录制为 WebM 视频。",
    "在 config.yaml 中设置 worktree: true 始终创建 git worktree（同 hermes -w）。",
    "设置 security.website_blocklist.enabled: true 阻止 web 工具访问指定域名。",
    "设置 cron.wrap_response: false 投递原始 agent 输出，不带 cron 头尾。",
    "HERMES_TIMEZONE 用任意 IANA 时区字符串覆盖服务器时区。",
    "config.yaml 支持环境变量替换：使用 ${VAR_NAME} 语法。",
    "config.yaml 中的 Quick commands 无需 token 即可即时运行 shell 命令。",
    "自定义人格可在 config.yaml 的 agent.personalities 下定义。",
    "provider_routing 控制 OpenRouter provider 的排序、白名单和黑名单。",

    # --- 工具与能力 ---
    "execute_code 运行可编程调用 Hermes 工具的 Python 脚本 — 结果不进入上下文。",
    "delegate_task 默认最多生成 3 个并发 sub-agent（delegation.max_concurrent_children），各拥有隔离上下文用于并行工作。",
    "web_extract 支持 PDF URL — 传入任何 PDF 链接即可转换为 markdown。",
    "search_files 基于 ripgrep，比 grep 更快 — 用它代替终端 grep。",
    "patch 使用 9 种模糊匹配策略，轻微空白差异不会导致编辑失败。",
    "patch 支持 V4A 格式，单次调用即可批量编辑多个文件。",
    "read_file 在文件找不到时会建议相似文件名。",
    "read_file 自动去重 — 重新读取未变更的文件返回轻量占位。",
    "browser_vision 截图并用 AI 分析 — 适用于 CAPTCHA 和视觉内容。",
    "browser_console 可以在页面上下文中执行 JavaScript 表达式。",
    "image_generate 使用 FLUX 2 Pro 创建图片，自动 2x 放大。",
    "text_to_speech 将文字转语音 — 在 Telegram 上以语音气泡播放。",
    "send_message 可以在会话中向任何已连接的消息平台发送消息。",
    "todo 工具帮助 agent 在会话中追踪复杂的多步骤任务。",
    "session_search 对所有历史对话执行全文搜索。",
    "agent 自动将偏好、纠正和环境信息保存到 memory。",
    "mixture_of_agents 将难题路由给 4 个前沿 LLM 协作处理。",
    "Terminal 命令支持后台模式，配合 notify_on_complete 处理长时间运行的任务。",
    "Terminal 后台进程支持 watch_patterns，在特定输出行出现时提醒。",
    "terminal 工具支持 6 种后端：local、Docker、SSH、Modal、Daytona 和 Singularity。",

    # --- Profiles ---
    "每个 profile 拥有独立的 config、API key、memory、session、skill 和 cron 任务。",
    "Profile 名称会变成 shell 命令 — 'hermes profile create coder' 会创建 'coder' 命令。",
    "hermes profile export coder -o backup.tar.gz 创建可移植的 profile 归档。",
    "如果两个 profile 意外共享同一个 bot token，第二个 gateway 会被阻止并给出清晰错误。",

    # --- 会话 ---
    "会话在第一次交互后自动生成描述性标题 — 无需手动命名。",
    '会话标题支持系列/继承命名："my project" → "my project #2" → "my project #3"。',
    "退出时，Hermes 会打印带有 session ID 和统计信息的恢复命令。",
    "hermes sessions export backup.jsonl 导出所有会话用于备份或分析。",
    "hermes -r SESSION_ID 按 ID 恢复任意历史会话。",

    # --- Memory ---
    "Memory 是冻结快照 — 变更只在下次会话开始时出现在系统提示中。",
    "Memory 条目会自动扫描 prompt 注入和数据泄露模式。",
    "agent 有两个 memory 存储：个人笔记（约 2200 字符）和用户画像（约 1375 字符）。",
    '你给 agent 的纠正（"不对，这样做"）通常会自动保存到 memory。',

    # --- Skills ---
    "80+ 内置 skill，覆盖 github、creative、mlops、productivity、research 等。",
    "每个已安装的 skill 自动成为 slash 命令 — 输入 / 查看全部。",
    "hermes skills install official/security/1password 从仓库安装可选 skill。",
    "Skill 可以限制在特定 OS 平台 — 有些只在 macOS 或 Linux 上加载。",
    "config.yaml 中的 skills.external_dirs 让你从自定义目录加载 skill。",
    "agent 可以使用 skill_manage 创建自己的 skill 作为程序记忆。",
    "plan skill 将 markdown 计划保存到活跃工作区的 .hermes/plans/ 下。",

    # --- Cron 与调度 ---
    'Cron 任务可以附加 skill：hermes cron add --skill blogwatcher "Check for new posts"。',
    "Cron 投递目标包括 telegram、discord、slack、email、sms 等 12+ 个平台。",
    "如果 cron 响应以 [SILENT] 开头，投递会被抑制 — 适合纯监控任务。",
    "Cron 支持相对延迟（30m）、间隔（every 2h）、cron 表达式和 ISO 时间戳。",
    "Cron 任务在全新的 agent session 中运行 — prompt 必须自包含。",

    # --- 语音 ---
    "如果安装了 faster-whisper（免费本地语音转文字），语音模式无需任何 API key。",
    "五种 TTS provider 可用：Edge TTS（免费）、ElevenLabs、OpenAI、NeuTTS（免费本地）、MiniMax。",
    "/voice on 在 CLI 中启用语音模式。Ctrl+B 切换按键说话录音。",
    "流式 TTS 边生成边播放句子 — 无需等待完整响应。",
    "Telegram、Discord、WhatsApp 和 Slack 上的语音消息会自动转录。",

    # --- Gateway 与消息平台 ---
    "Hermes 运行在 21 个消息平台上：Telegram、Discord、Slack、WhatsApp、Signal、Matrix、IRC、Microsoft Teams、email 等。",
    "hermes gateway install 将其安装为开机自启的系统服务。",
    "钉钉使用 Stream Mode — 无需 webhooks 或公网 URL。",
    "BlueBubbles 通过本地 macOS 服务器将 iMessage 接入 Hermes。",
    "Webhook 路由支持 HMAC 验证、速率限制和事件过滤。",
    "API server 暴露 OpenAI 兼容端点，兼容 Open WebUI 和 LibreChat。",
    "Discord 语音频道模式：bot 加入语音频道，转录语音并语音回复。",
    "group_sessions_per_user: true 让群聊中每个人拥有独立 session。",
    "/sethome 将聊天标记为 cron 任务投递的 home channel。",
    "gateway 支持基于不活跃的超时 — 活跃的 agent 可以无限运行。",

    # --- 安全 ---
    "危险命令审批有 4 个等级：once、session、always（永久白名单）、deny。",
    "Smart 审批模式使用 LLM 自动批准安全命令并标记危险命令。",
    "SSRF 防护阻止私有网络、回环地址、链路本地和云元数据地址。",
    "Tirith 预执行扫描检测同形字 URL 伪造和管道解释器模式。",
    "MCP 子进程接收过滤后的环境变量 — 只有安全的系统变量通过。",
    "上下文文件（.hermes.md、AGENTS.md）在加载前会进行安全扫描，检测 prompt 注入。",
    "config.yaml 中的 command_allowlist 永久批准特定 shell 命令模式。",

    # --- 上下文与压缩 ---
    "上下文达到阈值时自动压缩 — memory 被刷出，历史被摘要。",
    "状态栏随上下文填充变黄、变橙、变红。",
    "~/.hermes/SOUL.md 是 agent 的主要身份 — 自定义它来塑造行为。",
    "Hermes 从 .hermes.md、AGENTS.md、CLAUDE.md 或 .cursorrules（最先匹配）加载项目上下文。",
    "子目录中的 AGENTS.md 文件会随着 agent 导航到对应文件夹时逐步发现。",
    "上下文文件上限 20,000 字符，使用智能头尾截断。",

    # --- Browser ---
    "五种 browser provider：local Chromium、Browserbase、Browser Use、Camofox 和 Firecrawl。",
    "Camofox 是反检测 browser — 基于 Firefox 的 C++ 指纹伪造分支。",
    "browser_navigate 自动返回页面快照 — 之后无需调用 browser_snapshot。",
    "browser_vision 加 annotate=true 会在交互元素上叠加编号标签。",

    # --- MCP ---
    "hermes mcp 打开交互式选择器，一键安装 Nous 认证的 MCP。",
    "hermes mcp catalog 列出仓库附带的 Nous 认证 MCP 服务器。",
    "hermes mcp install <name> 安装目录条目、提示输入凭证、让你选择启用哪些工具。",
    "MCP 服务器在 config.yaml 中配置 — 同时支持 stdio 和 HTTP 传输。",
    "每服务器工具过滤：tools.include 白名单，tools.exclude 黑名单特定工具。",
    "MCP 服务器运行时自动生成 toolset — hermes tools 可按平台切换。",
    "MCP OAuth 支持：auth: oauth 启用基于浏览器的 PKCE 授权。",

    # --- 检查点与回滚 ---
    "未修改文件时检查点零开销 — 默认启用。",
    "回滚前自动保存快照，所以你可以撤销撤销操作。",
    "/rollback 同时撤销对话轮次，所以 agent 不会记得已回滚的变更。",
    "检查点使用 ~/.hermes/checkpoints/ 下的影子仓库 — 不会触碰项目的 .git。",

    # --- 批量与数据 ---
    "batch_runner.py 并行处理数百条 prompt，用于训练数据生成。",
    "hermes chat -Q 启用安静模式用于程序化调用 — 抑制 banner 和 spinner。",
    "轨迹保存（--save-trajectories）捕获完整工具使用痕迹用于模型训练。",

    # --- 插件 ---
    "三种插件类型：通用（工具/钩子）、memory provider 和上下文引擎。",
    "hermes plugins install owner/repo 直接从 GitHub 安装插件。",
    "8 个外部 memory provider 可用：Honcho、OpenViking、Mem0、Hindsight 等。",
    "Plugin 钩子包括 pre/post_tool_call、pre/post_llm_call 和 transform_terminal_output（用于输出规范化）。",

    # --- 杂项 ---
    "Prompt caching（Anthropic）通过复用缓存的系统提示前缀降低成本。",
    "agent 在后台线程自动生成会话标题 — 零延迟影响。",
    # "Smart 模型路由可自动将简单查询路由到更便宜的模型。",  # removed: feature deleted in #12732 (2026-04-19)
    "Slash 命令支持前缀匹配：/h 解析为 /help，/mod 解析为 /model。",
    "将文件路径拖入终端自动附加图片或作为上下文发送。",
    "仓库根目录的 .worktreeinclude 列出要复制到 worktree 的 gitignored 文件。",
    "hermes acp 将 Hermes 作为 ACP 服务器运行，用于 VS Code、Zed 和 JetBrains 集成。",
    "自定义 provider：在 config.yaml 的 custom_providers 下保存命名端点。",
    "HERMES_EPHEMERAL_SYSTEM_PROMPT 注入一个不会持久化到历史的系统提示。",
    "credential_pool_strategies 支持 fill_first、round_robin、least_used 和 random 轮换。",
    "hermes auth add nous 或 hermes auth add openai-codex 设置基于 OAuth 的 provider。",
    "API server 同时支持 Chat Completions 和 Responses API，带服务端状态。",
    "config 中 tool_preview_length: 0 在 spinner 活动信息中显示完整文件路径。",
    "hermes status --deep 对所有组件运行更深入的诊断检查。",

    # --- 隐藏功能与高级技巧 ---
    "Cron 任务可以附加 Python 脚本（--script），其 stdout 作为上下文注入 prompt。",
    "Cron 脚本存放在 ~/.hermes/scripts/，在 agent 之前运行 — 适合数据收集管道。",
    "config.yaml 中的 prefill_messages_file 在每次 API 调用中注入 few-shot 示例，从不保存到历史。",
    "SOUL.md 完全替换 agent 的默认身份 — 重写它让 Hermes 变成你自己的。",
    "SOUL.md 在首次运行时自动填充默认人格。编辑 ~/.hermes/SOUL.md 来自定义。",
    "/compress <focus topic> 将 60-70% 的摘要预算分配给你的主题，其余部分激进压缩。",
    "第二次及以后的压缩，压缩器会更新之前的摘要而非从头开始。",
    "在 gateway 会话重置前，Hermes 会在后台自动将重要信息刷入 memory。",
    "config.yaml 中 network.force_ipv4: true 修复 IPv6 故障服务器上的挂起 — 会 monkey-patch socket。",
    "terminal 工具会标注常见退出码：grep 返回 1 = 'No matches found (not an error)'。",
    "失败的前台 terminal 命令自动重试最多 3 次，带指数退避（2s、4s、8s）。",
    "裸 sudo 命令会自动改写为从 .env 读取 SUDO_PASSWORD 并通过管道传入 — 无需交互式提示。",
    "execute_code 内置辅助函数：json_parse() 容错解析、shell_quote()、retry() 带退避。",
    "execute_code 的 7 个沙箱工具（web_search、terminal、read/write/search/patch）使用 RPC — 永不进入上下文。",
    "同一文件区域被读取 3 次以上会触发警告。4 次以上会被硬阻止以防循环。",
    "write_file 和 patch 会检测文件自上次读取后是否被外部修改，并警告过期。",
    "V4A patch 格式支持 Add File、Delete File 和 Move File 指令 — 不止 Update。",
    "MCP 服务器可以通过 sampling 请求 LLM 补全 — agent 变成服务器的工具。",
    "MCP 服务器发送 notifications/tools/list_changed 触发自动工具重新注册，无需重启。",
    "delegate_task 加 acp_command: 'claude' 可以从任何平台生成 Claude Code 作为子 agent。",
    "Delegation 有心跳线程 — 子 agent 活动传播到父级，防止 gateway 超时。",
    "当 provider 返回 HTTP 402（需要付费）时，auxiliary client 自动回退到下一个。",
    "agent.tool_use_enforcement 引导那些只描述动作而不调用工具的模型 — GPT/Codex 自动启用。",
    "agent.restart_drain_timeout（默认 60s）让运行中的 agent 在 gateway 重启前完成。",
    "agent.api_max_retries（默认 3）控制 agent 在显示错误前重试失败 API 调用的次数 — 降低它可加快回退。",
    "gateway 按 session 缓存 AIAgent 实例 — 销毁此缓存会破坏 Anthropic prompt caching。",
    "任何网站可以通过 /.well-known/skills/index.json 暴露 skill — skills hub 会自动发现。",
    "skill 审计日志在 ~/.hermes/skills/.hub/audit.log，记录每次安装和删除操作。",
    "过期的 git worktree 会被自动清理：24-72 小时且无未推送提交的会在启动时被修剪。",
    "Profile 通过 HERMES_HOME 隔离 Hermes 状态；除非 terminal.home_mode 设为 profile，否则 host tool 子进程仍使用真实 HOME。",
    "HERMES_HOME_MODE 环境变量（八进制，如 0701）设置 web 服务器遍历的自定义目录权限。",
    "容器模式：在 HERMES_HOME 中放置 .container-mode，host CLI 会自动 exec 进容器。",
    "Ctrl+C 有 5 个优先级：取消录音 → 取消提示 → 取消选择器 → 中断 agent → 退出。",
    "agent 运行期间的每次中断都会记录到 ~/.hermes/interrupt_debug.log，带时间戳。",
    "BROWSER_CDP_URL 将 browser 工具连接到任何运行中的 Chromium 系列 browser — 接受 WebSocket、HTTP 或 host:port。",
    "BROWSERBASE_ADVANCED_STEALTH=true 启用高级反检测，使用自定义 Chromium（Scale Plan）。",
    "CLI 在宽度小于 80 列的终端中自动切换到紧凑模式。",
    "Quick commands 支持两种类型：exec（直接运行 shell 命令）和 alias（重定向到另一个命令）。",
    "每任务 delegation 模型：config 中的 delegation.model 和 delegation.provider 将 subagent 路由到更便宜的模型。",
    "delegation.reasoning_effort 独立控制 subagent 的思考深度。",
    "config.yaml 中的 display.platforms 允许按平台覆盖显示设置：{telegram: {tool_progress: all}}。",
    "config 中的 human_delay.mode 模拟人类打字速度 — 可配置 min_ms/max_ms 范围。",
    "配置版本迁移在加载时自动运行 — 新配置项无需手动干预即可出现。",
    "GPT 和 Codex 模型会获得特殊的系统提示引导，确保工具调用规范和强制使用工具。",
    "Gemini 模型会获得定制指令，涵盖绝对路径、并行工具调用和非交互式命令。",
    "config.yaml 中的 context.engine 可设置为插件名，用于替代上下文管理策略。",
    "超过 8000 token 的 browser 页面会由 auxiliary LLM 自动摘要后再返回给 agent。",
    "压缩器有廉价预扫描：超过 200 字符的工具输出在 LLM 运行前被替换为占位符。",
    "压缩失败时，后续尝试暂停 10 分钟以避免 API 请求风暴。",
    "长度超过 70 字符的危险命令在审批提示中会获得 'view' 选项，可先查看完整内容。",
    "语音录制时显示 ▁▂▃▄▅▆▇ 音量条，基于麦克风 RMS 电平。",
    "Profile 名称不能与现有 PATH 二进制冲突 — 'hermes profile create ls' 会被拒绝。",
    "hermes profile create backup --clone-all 复制所有内容（config、key、SOUL.md、memory、skill、session）。",
    "语音录制键可通过 config.yaml 中的 voice.record_key 配置 — 不限于 Ctrl+B。",
    ".cursorrules 和 .cursor/rules/*.mdc 文件会被自动检测并作为项目上下文加载。",
    "上下文文件支持 10+ 种 prompt 注入模式检测 — 不可见 Unicode、'ignore instructions'、数据泄露尝试。",
    "GPT-5 和 Codex 在消息格式中使用 'developer' 角色而非 'system'。",
    "每任务 auxiliary 覆盖：config.yaml 中的 auxiliary.vision.provider、auxiliary.compression.model 等。",
    "auxiliary client 将 'main' 视为 provider 别名 — 解析为你实际的主 provider + model。",
    "hermes claw migrate --dry-run 预览 OpenClaw 迁移，不写入任何内容。",
    "带引号或转义空格的文件路径会被自动处理 — 无需手动清理。",
    "Slash 命令不触发大粘贴折叠 — 带大参数的 /command 也能正常工作。",
    "中断模式下，agent 执行期间输入的 slash 命令绕过中断逻辑立即运行。",
    "HERMES_DEV=1 绕过容器模式检测，用于本地开发。",
    "每个 MCP 服务器获得独立的 toolset（mcp-servername），可通过 hermes tools 单独切换。",
    "MCP config 中的 ${ENV_VAR} 占位符在服务器启动时解析 — 包括 ~/.hermes/.env 中的变量。",
    "来自可信仓库（NousResearch）的 skill 获得 'trusted' 安全级别；社区 skill 获得额外扫描。",
    "skill 隔离区在 ~/.hermes/skills/.hub/quarantine/，存放待安全审查的 skill。",

    # --- 高级 Slash 命令 ---
    "/steer <prompt> 在下一个工具调用后注入提示 — 中途调整方向，不打断执行。",
    "/goal <text> 设置持续 Ralph-loop 目标 — Hermes 每轮自动继续，直到 judge 判定完成。",
    "/snapshot create [label] 保存 Hermes 配置的完整状态快照；/snapshot restore <id> 之后恢复。",
    "/copy [N] 将最后一条助手回复复制到剪贴板，加数字则复制倒数第 N 条。",
    "/redraw 强制全屏重绘 — 修复 tmux resize 或鼠标选择后的终端漂移。",
    "/agents（别名 /tasks）显示当前会话中的活跃 agent 和运行中的后台任务。",
    "/footer 切换 gateway 回复末尾的脚注，显示模型、工具调用次数和轮次耗时。",
    "/busy queue|steer|interrupt 控制 Hermes 工作时按 Enter 的行为。",
    "/topic 在 Telegram DM 中启用用户管理的多会话话题模式 — /topic <id> 内联恢复过去的会话。",
    "/approve session|always 以你选择的信任范围批准待审批的危险命令；/deny 拒绝。",
    "/restart 优雅重启 gateway（等待活跃任务结束），重启后通知请求者。",
    "/kanban boards switch <slug> 在聊天中切换活跃的多项目 Kanban 看板。",
    "/reload 将 ~/.hermes/.env 重新加载到运行中的会话 — 无需重启即可获取新 API key。",

    # --- Cron（no-agent 与脚本）---
    "cronjob 加 no_agent=True 按计划运行脚本并直接发送 stdout — 零 token、零 LLM。",
    "Cron 脚本 stdout 为空意味着静默 tick — 不投递任何内容，完美适合阈值监控。",
    "HERMES_CRON_MAX_PARALLEL（默认 4）限制每个 tick 同时运行的 cron 任务数，防止突发流量耗尽你的 key。",

    # --- Gateway 钩子 ---
    "Gateway 钩子位于 ~/.hermes/hooks/<name>/，包含 HOOK.yaml + handler.py — handler 必须命名为 `handle`。",
    "钩子事件包括 gateway:startup、session:start、agent:step 和 command:* 通配订阅。",
    "在 ~/.hermes/BOOT.md 放一个清单，gateway:startup 钩子会在每次启动时将其作为一次性 agent 运行。",

    # --- Curator ---
    "hermes curator run --dry-run 预览 curator 会归档或合并什么，不修改任何内容。",
    "hermes curator pin <skill> 对 skill 加硬防护，阻止自动归档和 agent 的 skill_manage 工具。",
    "hermes curator rollback 从预运行快照恢复 skill — 备份在 skills/.curator_backups/ 下。",

    # --- 凭证池与路由 ---
    "hermes auth reset <provider> 清除凭证池上的所有冷却和耗尽标记。",
    "credential_pool_strategies.<provider>: round_robin 均匀轮换 key，而非默认的 fill_first。",
    "use_gateway: true 按工具将 web、image、tts 或 browser 路由通过你的 Nous 订阅 — 无需额外 key。",
    "provider_routing.data_collection: deny 在 OpenRouter 上排除存储数据的 provider。",
    "provider_routing.require_parameters: true 只路由到支持你请求中每个参数的 provider。",

    # --- TUI 与 Dashboard ---
    "HERMES_TUI_RESUME=1 启动时自动重新附加到最近的 TUI session — SSH 断线后很方便。",
    "HERMES_TUI_THEME=light|dark|<hex> 在不设置 COLORFGBG 的终端上强制 TUI 主题。",
    "TUI 中 Ctrl+G 或 Ctrl+X Ctrl+E 在 $EDITOR 中打开输入缓冲区，用于长多行提示。",
    "TUI 内联渲染 LaTeX — $E=mc^2$ 变成 Unicode 数学符号而非原始 TeX。",
    "hermes dashboard 在 127.0.0.1:9119 启动本地 web UI — 零数据离开 localhost。",
    "hermes dashboard --tui 通过 xterm.js 和 WebSocket PTY 在浏览器中嵌入完整 Hermes TUI。",
    "在 ~/.hermes/dashboard-themes/ 放一个 YAML 文件指定两种调色板颜色即可重绘整个 dashboard。",
    "Dashboard 插件即放即用：在 ~/.hermes/dashboard-plugins/ 放 manifest.json + JS 包 — 无需 npm 构建。",
    "Dashboard 主题中的 layoutVariant: cockpit 添加 260px 左侧栏，插件可通过 sidebar slot 填充内容。",

    # --- 环境变量与配置开关 ---
    "display.tool_progress_command: true 在消息平台上开放 /verbose；默认仅限 CLI。",
    "HERMES_BACKGROUND_NOTIFICATIONS=result 只在后台任务完成时通知（vs all/error/off）。",
    "HERMES_WRITE_SAFE_ROOT 限制 write_file 和 patch 到目录前缀；外部写入需要审批。",
    "HERMES_IGNORE_RULES 跳过 AGENTS.md、SOUL.md、.cursorrules、memory 和预加载 skill 的自动注入。",
    "HERMES_ACCEPT_HOOKS 自动批准 config.yaml 中声明的未见 shell 钩子，无需 TTY 确认。",
    "auxiliary.goal_judge.model 将 /goal judge 路由到便宜快速的模型，使循环成本接近零。",
    "检查点会跳过超过 50,000 个文件的目录，以避免在超大型 monorepo 上执行慢速 git 操作。",

    # --- TTS ---
    "tts.provider: piper 在 CPU 上运行 44 语言本地 TTS — 语音自动下载到 ~/.hermes/cache/piper-voices/。",
    "tts.providers.<name>.type: command 连接任何 CLI TTS 引擎，使用 {input_path} 和 {output_path} 占位符。",

    # --- API Server 与代理 ---
    "API_SERVER_ENABLED=true 在 gateway 旁运行 OpenAI 兼容端点，用于 Open WebUI 和 LibreChat。",
    "GATEWAY_PROXY_URL 运行分离架构：平台 I/O 在本地，agent 工作委托给远程 API server。",

    # --- 平台专属 ---
    "MATRIX_DEVICE_ID 为 E2EE 固定稳定的设备 ID — 没有它，密钥每次启动都会轮换，历史解密会失效。",
    "TELEGRAM_WEBHOOK_SECRET 在设置 TELEGRAM_WEBHOOK_URL 时是必需的 — 用 openssl rand -hex 32 生成。",

    # --- 批处理 ---
    "batch_runner.py --resume 按文本匹配已完成的 prompt，所以数据集重排不会重复运行已完成的工作。",

    # --- 不太常见的 Slash 命令 ---
    "/new 在原地开始新会话（别名 /reset） — 新 session ID、干净历史、CLI 保持打开。",
    "/clear 清屏并开始新会话 — 一键视觉重置。",
    "/history 在 CLI 中内联打印当前对话 — 方便快速回顾。",
    "/save 将当前对话保存到磁盘，不结束会话。",
    "/status 显示会话概览：ID、标题、模型、token 用量和时长。",
    "/image <path> 附加本地图片文件，无需粘贴或拖放。",
    "/platforms 显示 gateway 和消息平台连接状态。",
    "/commands 分页显示全部 slash 命令 + 已安装 skill 列表 — 适合没有 tab 补全的平台。",
    "/toolsets 列出所有可用的 toolset，让你知道 -t/--toolsets 接受什么。",
    "/gquota 当 Google Gemini Code Assist provider 活跃时，显示配额用量和进度条。",
    "/voice tts 切换纯 TTS 模式 — agent 用语音回复，但你仍然打字输入。",
    "/reload-skills 重新扫描 ~/.hermes/skills/，让新增的 skill 无需重启会话即可生效。",
    "/indicator kaomoji|emoji|unicode|ascii 选择 agent 运行时 TUI 显示的忙碌指示器样式。",
    "/debug 上传支持包（系统信息 + 日志）并返回可分享的链接 — 在聊天中也能用。",

    # --- CLI 子命令与参数 ---
    'hermes -z "<prompt>" 是最纯粹的一次性模式：最终答案输出到 stdout — 适合在脚本中管道使用。',
    "hermes chat --pass-session-id 将 session ID 注入系统提示，让 agent 可以自引用。",
    "hermes chat --image path/to/pic.png 附加本地图片到单次 -q 查询，无需单独上传。",
    "hermes chat --ignore-user-config 跳过 ~/.hermes/config.yaml — 用于可复现的 bug 报告和 CI 运行。",
    'hermes chat --source tool 标记程序化聊天，使其不出现在 hermes sessions list 中。',
    "hermes dump --show-keys 包含脱敏的 API key 指纹，用于更深入的支持调试。",
    'hermes sessions rename <ID> "new title" 重命名任意历史会话；hermes sessions delete <ID> 删除一个。',
    "hermes import 恢复 sessions export 或 profile export 生成的会话导出或 profile 归档。",
    "hermes fallback 交互式管理 fallback_model 链 — 无需手动编辑 config.yaml。",
    "hermes pairing 轮换 DM 配对 token — 轮换后第一个发消息的人获得 bot 访问权。",
    "hermes setup 通过一次性交互流程引导新用户配置 provider、key 和平台连接。",
    "hermes status --deep 对每个组件运行完整健康检查；纯 hermes status 是快速视图。",

    # --- Agent 行为环境变量 ---
    "HERMES_AGENT_TIMEOUT=0 禁用 gateway 对运行中 agent 的不活跃终止 — 适合长时间研究任务。",
    "HERMES_ENABLE_PROJECT_PLUGINS=1 自动加载 ./.hermes/plugins/ 中的仓库本地插件 — 设计上受信任门控。",
    "HERMES_DISABLE_FILE_STATE_GUARD=1 关闭 patch 和 write_file 上的 '文件自读取后已变更' 防护。",
    "HERMES_ALLOW_PRIVATE_URLS=true 允许 web 工具访问 localhost 和私有网络 — gateway 模式下默认关闭。",
    "HERMES_OPTIONAL_SKILLS=name1,name2 在每个 profile 首次运行时自动安装额外的可选目录 skill。",
    "HERMES_BUNDLED_SKILLS 指向自定义的内置 skill 树 — Homebrew 和 Nix 打包使用。",
    "HERMES_DUMP_REQUEST_STDOUT=1 将每个 API 请求 payload 转储到 stdout 而非日志文件。",
    "HERMES_OAUTH_TRACE=1 记录脱敏的 OAuth token 交换和刷新尝试，用于调试 provider 认证。",
    "HERMES_STREAM_RETRIES（默认 3）控制瞬态网络错误时的中流重连尝试次数。",

    # --- Gateway 行为环境变量 ---
    "HERMES_GATEWAY_BUSY_ACK_ENABLED=false 静默用户给忙碌 agent 发消息时的 ⚡/⏳/⏩ 确认消息。",
    "HERMES_AGENT_NOTIFY_INTERVAL（默认 180s）设置 gateway 在长轮次中发送进度通知的间隔。",
    "HERMES_RESTART_DRAIN_TIMEOUT（默认 900s）限制 /restart 等待运行中任务的最长时间。",
    "HERMES_CHECKPOINT_TIMEOUT（默认 30s）限制文件系统检查点创建时间 — 在超大 monorepo 上可提高。",

    # --- 辅助任务与生图 ---
    "config.yaml 中的 image_gen.model 选择 FAL 模型：flux-2/klein、gpt-image-2、nano-banana-pro 等。",
    "image_gen.provider 通过插件（OpenAI Images、Codex、FAL）路由图片生成，而非默认方式。",
    "AUXILIARY_VISION_BASE_URL + AUXILIARY_VISION_API_KEY 将视觉分析指向任何 OpenAI 兼容端点。",

    # --- 安全 ---
    "security.tirith_fail_open: false 使 Hermes 在 tirith 扫描器自身出错时阻止命令。",
    "TIRITH_FAIL_OPEN 环境变量覆盖 tirith_fail_open 配置 — 无需编辑 config.yaml 的快速开关。",

    # --- 会话与来源标签 ---
    "--source tool 的聊天默认从 hermes sessions list 中排除 — 显式设置 --source 才能看到。",
    "Session ID 带时间戳前缀（20250305_091523_abcd），所以在 ls 和 jq 中可以自然排序。",

    # --- 杂项 ---
    "API_SERVER_MODEL_NAME 自定义 /v1/models 上的模型名称 — 多 profile Open WebUI 配置必备。",
    "Dashboard 插件从 /dashboard-plugins/<name>/ 提供 — 将文件放入 ~/.hermes/dashboard-plugins/。",
]
