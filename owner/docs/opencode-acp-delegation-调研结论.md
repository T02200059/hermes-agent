# opencode 委派 — 调研结论（推翻 ACP 方案）

> 状态：**结论已定，原 ACP 方案放弃**
> 日期：2026-06-19
> 适用分支：`owner-v16`
> 取代：原 `opencode-acp-delegation-设计.md` / `实现计划.md` / `probe-findings.md`（已删）

---

## 一、问题回顾

背景诉求（原设计文档 §1-§2 提炼）：主 agent 在对话中委派一个**有界复杂编码任务**给一个**跑完整自主
loop**的强代码执行体，执行体的危险动作要能**路由到 Hermes 审批**，进度实时流式，会话按对话复用。

原方案：建一套基于 ACP（Agent Client Protocol）的 opencode 委派工具，把 opencode 的
`session/request_permission` 路由到 Hermes 审批管线，落在 `owner/acp/` 六个新文件。

## 二、为什么推翻原方案

### 2.1 Hermes 主线已经用「跑 CLI」解决了 opencode 委派

本仓库 `skills/autonomous-ai-agents/` 有**同构三件套**，模式完全一致 —— 用已有的 `terminal`/`process`
工具 spawn CLI，agent 自己跑原生 loop：

| Skill | 做法 | 文件 |
|---|---|---|
| `opencode` | `terminal(command="opencode run '...'")` 一次性；或 `opencode` + `background=true,pty=true` + `process` 交互 | `skills/autonomous-ai-agents/opencode/SKILL.md` |
| `claude-code` | 同模式 | `skills/autonomous-ai-agents/claude-code/SKILL.md` |
| `codex` | 同模式 | `skills/autonomous-ai-agents/codex/SKILL.md` |

**零 ACP、零 MCP、零新代码。** 会话复用走 `opencode -c`/`-s`（CLI 原生），结构化输出走
`--format json`。社区插件 `zaycruz/hermes-opencode-plugin` 也是同一路子。原计划建 `owner/acp/` 六个
文件去做这件事，是在重复造一个上游已经造好、且更简单的轮子。

### 2.2 ACP 的定位是「editor ↔ agent」，不是「agent ↔ agent」

ACP 由 Zed Industries 发起，类比 LSP，设计意图是**编辑器与编码 agent 之间的标准通道**。本仓库
`acp_adapter/` 正是此用途（VS Code/Zed/JetBrains 集成）。原设计文档把它当作「agent 间委派协议」是
**用错了场景**。

agent ↔ agent 委派的事实标准是「主 agent 用工具跑 CLI/子进程」（Hermes、OpenClaw 都这么干）。
学术上有 Google A2A（HTTP+SSE+JSON-RPC）但落地少；MCP 是 agent↔tool，方向不对。

### 2.3 「子 agent 审批边界下传」是全行业开放难题，ACP 解不了

这是原方案的安全核心，也是致命伤。实测 + 调研证明：

- **opencode 1.17.0 默认不发 `session/request_permission`**（探针 #1 证伪）。要强制 ask mode 得靠
  `opencode.json` 注入 + XDG 隔离，一整套脆弱胶水，且 opencode 版本敏感（1.17.0 的 `session/load`
  必须传 `mcpServers:[]`、permission optionId=`once`/`always`/`reject`、bug #31964/#14301…）。
- **即便开了 ask mode，子 session 的 permission 请求被静默丢弃**（[opencode #12133](https://github.com/anomalyco/opencode/issues/12133)）——
  opencode 用其 `task` 工具派子 agent 时，子 agent 的危险动作**不发权限请求**。这是堵不死的安全洞。
- **同类问题在 Claude Code 也未解决**：[claude-code #43772](https://github.com/anthropics/claude-code/issues/43772)
  ——`bypassPermissions` 模式下 subagent 完全跳过 PreToolUse hooks。

**结论：靠 ACP 把「主agent委派子agent + 逐动作审批」做可靠，当前生态做不到。** 原方案的卖点（路由
permission 到 Hermes 审批）建立在一个流沙地基上。

### 2.4 投入产出对比

| | 原计划：建 `owner/acp/` | 既有：terminal 跑 CLI（skill） |
|---|---|---|
| 代码量 | 6 owner 文件 + 1 官方 shim + 测试 | **0**（skill 已存在） |
| 官方文件足迹 | 1 个新文件 | 0 |
| 复用 | 自建传输，与 `copilot_acp_client.py` 重复 | 复用成熟 `terminal`/`process` |
| 安全（审批） | **堵不死的洞**（#12133 子 session 绕过） | 诚实可靠：terminal 的 hardline floor + command guards + gateway 审批（`check_all_command_guards`），管辖 opencode 子进程的 shell |
| 版本耦合 | 强（1.17.0 的 mcpServers/permission/XDG 细节） | 弱（CLI 接口稳定） |
| 多后端 | 只有 opencode | **天然支持**（claude-code/codex skill 已在） |
| 会话复用 | 自写 manager + session/load | `opencode -c`/`-s` 原生 |

## 三、关键澄清：terminal 路线的安全边界是可靠的

需要诚实区分两种「审批」：

- **terminal 审批**：Hermes `terminal` 工具执行 shell 时过 `check_all_command_guards` → hardline floor +
  dangerous command 检测 + gateway 审批卡片（`_await_gateway_decision`）。这是**成熟、可靠**的边界。
  把 opencode 当一个受 terminal 管辖的子进程跑（`opencode run` / `pty` + `process`），opencode 进程
  执行的外层命令过这道关。
- **ACP permission 审批**：opencode 内部 LLM「想」执行的 edit/bash，理论上经 `request_permission`
  上报。但 #12133 证明子 session 会绕过 —— 这是**不可靠**的边界。

原方案想抓的是后者（opencode 内部动作），但那正是堵不住的洞。前者（terminal 外层）才是可靠投资。
差别看似细微，实则是「可靠 vs 流沙」的分水岭：与其在一个会绕过的边界上堆胶水，不如在可靠的
terminal 边界上把姿态做对。

## 四、采用方案

**放弃 ACP。沿用主线 `skills/autonomous-ai-agents/opencode`。**

1. **opencode 委派已由主线 skill 解决**，`/cc` 命令（若要做）只需引导 agent 走该 skill + `terminal`，
   不重写为 ACP 指令，不建 `owner/acp/`。
2. **安全姿态靠 terminal 审批管线**（现状已具备），必要时在 skill 里补一段「受限 workdir + Hermes
   侧 command guards 已开」的说明，把 opencode 当受管辖子进程。**不依赖 opencode 的 ACP permission。**
3. **若真要「主agent大脑 + 子agent编码」的强分离**：投资增强 `delegate_task` 的审批中介（子 agent
   = AIAgent，可指定外部强编码模型 `delegation.provider`/`model`，把现在 `_subagent_auto_deny`/
   `_subagent_auto_approve` 的二元选择换成「路由到父会话用户审批」），而非接 opencode。这是另一份
   独立设计，不在本文档范围。

## 五、Phase 0 探针的可用副产物（备查）

虽然不建 ACP，但本轮对真 opencode 1.17.0 的实测结论仍有参考价值，留此备查（未来若 opencode 修了
#12133 且确需结构化进度流，可重启 ACP 评估）：

- ACP 入口是 `opencode acp`（子命令），非 `--acp`。
- 默认 permission mode 不发 `request_permission`；cwd 放 `opencode.json` 设 `permission:{"*":"ask"}`
  后才发，options 的 optionId=`once`/`always`/`reject`，kind=`allow_once`/`allow_always`/`reject_once`。
- fs 由 opencode 自己做（无 `fs/*` 委托 client）。
- `session/load` 支持（`loadSession:true`），但 1.17.0 必须传 `mcpServers:[]`，否则 -32602。
- 配置隔离靠 `XDG_CONFIG_HOME`（重定向后 opencode 不读用户真实 `~/.config/opencode/`，零污染用户 TUI）；
  但项目 `./opencode.json` 优先级高于 XDG 全局。
- 已知 bug：[#12133](https://github.com/anomalyco/opencode/issues/12133)（子 session permission 丢弃，
  致命）、[#31964](https://github.com/anomalyco/opencode/issues/31964)、[#14301](https://github.com/anomalyco/opencode/issues/14301)、
  [#31781](https://github.com/anomalyco/opencode/issues/31781)；1.17.0 未复现 #31964 的 load 后权限丢失。

## 六、参考资料

- [Hermes 官方 opencode skill（本仓库）](https://hermes-agent.nousresearch.com/docs/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-opencode)
- [Hermes 官方 codex skill](https://hermes-agent.nousresearch.com/docs/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-codex) · [claude-code skill](https://www.remoteopenclaw.com/skills/hermes/built-in-claude-code)
- [zaycruz/hermes-opencode-plugin](https://github.com/zaycruz/hermes-opencode-plugin)
- [OpenClaw Sub-agents](https://docs.openclaw.ai/tools/subagents) · [OpenClaw ACP agents（acpx 后端插件）](https://docs.openclaw.ai/tools/acp-agents)
- [ACP = editor↔agent（Marc Nuri）](https://blog.marcnuri.com/agent-client-protocol-acp-introduction) · [A2A vs MCP（Atlan）](https://atlan.com/know/google-a2a-protocol/)
- [opencode #12133](https://github.com/anomalyco/opencode/issues/12133) · [claude-code #43772](https://github.com/anthropics/claude-code/issues/43772)
