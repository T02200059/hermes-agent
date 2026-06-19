# opencode ACP 探针结论

> 日期：2026-06-19
> opencode 版本：**1.17.0**（`/opt/homebrew/bin/opencode`）
> 探针方法：直接 spawn `opencode acp`，手发 JSON-RPC，记录全部 stdout/stderr。
> 关联：[opencode-acp-delegation-设计.md](./opencode-acp-delegation-设计.md) §7「实现前必须坐实的依赖」
>       [opencode-acp-delegation-实现计划.md](./opencode-acp-delegation-实现计划.md) Phase 0 gate

## 0. 命令入口（修正设计文档的前提）

设计/计划假设 opencode 的 ACP 入口是 `opencode --acp`。**实际是 `opencode acp`（子命令，非 flag）**。
`opencode --help` 列出 `opencode acp  start ACP (Agent Client Protocol) server`。这会改写
`owner/acp/backends.py` 的默认 args（从 `["--acp"]` 改为 `["acp"]`，command 仍为 `opencode`）。

## 1. request_permission 行为 — **不发**（设计安全前提失效）

对「写文件 + 跑 shell」任务（`创建 hello.py 写入 print('hi') 然后运行 python hello.py`）
以及对显式 shell 执行任务（`Run this shell command: echo DANGER_PROBE`），全程**零** `session/request_permission`。

opencode 直接自主执行了：
- `tool_call` / `tool_call_update`（`kind: "edit"` 写文件、`kind: "execute"` 跑 bash）
- 执行完毕发 `agent_message_chunk`，最后 `session/prompt` 返回 `stopReason: "end_turn"`。

**结论 #1 = 否。** opencode 1.17.0 对 shell/写文件**不发** `session/request_permission`。
这正是设计 §7 验证项 #1 与计划 Phase 0 gate 所担心的情形，也是 copilot #845 的同款困境。

## 2. fs 谁做 — **opencode 自己做**（不委托 client）

未观察到任何 `fs/read_text_file` 或 `fs/write_text_file` 服务端请求。写文件以
`tool_call_update`(`kind:"edit"`, `rawInput.filePath`/`rawInput.content`) 的形式由 opencode 内部完成。
**结论 #2 = opencode 自己做 fs。** 因此「输出 redaction / 路径沙箱」只剩输出侧
（stream_bridge）一层，输入侧（cwd 内）我们无法在 fs 操作上中介。

## 3. session/load 能力位 — **支持**

`initialize` response：
```json
"agentCapabilities": {
  "loadSession": true,
  "mcpCapabilities": {"http": true, "sse": true},
  "promptCapabilities": {"embeddedContext": true, "image": true},
  "sessionCapabilities": {"close": {}, "fork": {}, "list": {}, "resume": {}}
}
```
**结论 #3 = 支持。** `loadSession: true`，`session/load` 可用。（形状未在本探针单独拉取，
但能力位为真，按设计 §4.3 的回退逻辑：先 `session/load` 失败再 `session/new`，安全。）

## 4. update 事件形状

观察到的 `sessionUpdate` 取值：
- `available_commands_update`（会话开始时一次性下发 skills 列表）
- `tool_call`（`toolCallId`/`title`/`kind`(`edit`/`execute`)/`status`(`pending`/`in_progress`/`completed`)/`locations`/`rawInput`）
- `tool_call_update`（同上，携带 `content`/`rawOutput` 增量）
- `agent_message_chunk`（`messageId`/`content.type:"text"`/`content.text`）
- `usage_update`（`used`/`size`/`cost`）

未观察到 `agent_thought_chunk` / `plan`（可能与所选 mode 有关）。

## 对设计的影响（GATE 触发）

**Phase 0 gate 命中：#1 = 否。按计划第 93 行的 gate 指令，停止 Phase 1+，把结论带回重新评估安全策略。**

设计的核心安全模型（§5.2 三层防护的第 1 层「输入侧拦截」）依赖「opencode 对危险 shell/写文件
发 `session/request_permission`，Hermes 在此边界中介」。探针证明 opencode 1.17.0 **不发**，
因此 Hermes **无法在 ACP 协议边界拦截 opencode 的危险动作** —— 这把「带审批的自主委派」
降级成「裸 yolo 委派」，与设计目标（§1.2 关键判断 #3「yolo 与审批兼得」）直接冲突。

### 可行的安全替代（需带回 brainstorming 重新决策，不在本计划内拍板）

1. **要求 opencode 跑严格权限 mode**：opencode 自身有 permission 配置（`opencode.json` 的
   `permission` 段 / `--permission` 类参数）。需调研能否配置成「所有 edit/execute 都走 ACP
   `request_permission`」。若能，则安全前提在「用户显式开启该 mode」下成立；若不能，方案破产。
2. **放弃 opencode，换一个真发 request_permission 的 ACP 良民**（设计 §1.2 #4 已点名 opencode 是
   良民——此判断在 1.17.0 上**不成立**，需复核其它版本/其它 agent 如 zed-agent、kiro）。
3. **接受裸 yolo + 仅输出侧 redaction + cwd confinement**：明确文档标注「Hermes 无法中介
   opencode 的危险动作，等同 tmux yolo」，退回设计 §1.2 #3 所说的「伪二选一」的另一端。这与
   设计初衷相悖，不推荐。
4. **不在 ACP 边界拦，改在 opencode 工具层拦**：fork/patch opencode 让其发 request_permission
   —— 违反「不改外部依赖」原则，排除。

### 当前状态

Phase 1–10 **未实现**。等待对上述替代的安全决策后再决定是否继续、以哪种形态继续。
本探针结论已落档，设计文档状态保持「设计已确认，待实现」不变（安全前提被证伪，需修订）。
