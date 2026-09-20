# approval-explainer 设计稿（审批卡命令解说）

> 状态：**已实现（2026-09-20）**，代码在 `owner/approval_explainer/`（4 模块）+ 两端 `[owner]` 胶水；单测 `tests/owner/test_approval_explainer.py` 20 项全绿；相关回归（tests/tools/test_approval.py 128 例、tests/owner 审批卡系列、tests/plugins/platforms/feishu/）全绿。既有环境性失败 4 例（`tests/gateway/test_feishu_approval_buttons.py` TestCardActionCallbackResponse，stash 改动后同样失败，与本功能无关 [未验证根因]）。
> 起草：2026-09-20
> 存放约定：设计稿统一放 `owner/docs/design/<功能短名>/`。
> 本功能目录：**`approval-command-explainer`**，与代码模块 `owner/approval_explainer/` 对号。
> 遵循 [`../../二次开发规范.md`](../../二次开发规范.md)：P0/P1 优先、官方源码最小侵入、核心逻辑全在 `owner/`。

---

## 1. 一句话与边界

**做什么**：hermes 执行命令触发 approval 时，在飞书/QQ 审批卡上追加一段 2-3 句的「这条命令做什么 / 有什么风险」人话解说，帮不懂具体命令的用户判断该不该批准。

**非目标（明确不做）**：
- 不覆盖审批不发卡的三条路径：① notify 发送失败回落纯文本 `/approve` 指引（降级态）② 无 notify_cb 的 `submit_pending` /approve 队列 ③ CLI 交互提示。v1 范围=飞书+QQ 卡片（用户点名「其他渠道只适配 qq」）。
- 不做建议：解说器**只给事实**，绝不输出「建议批准/拒绝」——approval 的决策权留给用户。
- 不改 approval 判定链路本身：`tools/approval.py` 零改动。
- 不进 config.yaml（模型配置全收拢 patch.yaml，与 progress_explainer 同约定）。

## 2. 触发时机（严格与 approvals 一致）

用户通知路径（源码实测）：

```
tools/approval.py:4027  _await_gateway_decision()
  → notify_cb(dict(entry.data))                    # 5294，入队后、阻塞前
  → gateway/run.py:6878  _approval_notify_sync()   # agent 线程同步桥接
  → adapter.send_exec_approval()                   # 每张用户可见审批卡恰一次
      飞书: plugins/platforms/feishu/adapter.py → owner/feishu/approval.py
      QQ:  gateway/platforms/qqbot/adapter.py → keyboards.py
```

**挂点选型（方案 A）**：解说生成嵌在两端 `send_exec_approval` 内部、建卡之前。语义：**每张 feishu/qq 审批卡都携带解说（或 fail-open 缺席），且除审批卡外无处生成解说**——不是定时器、不是每条命令。与卡片投递 1:1（并发相同命令已由 `_await_gateway_decision` 的 coalescing 合并去重）。

否掉的备选：B（run.py 包装 `_approval_notify_sync`——跨线程 stash + 巨闭包内注册点，复杂度更高）；C（订阅 `pre_approval_request` 插件钩子——对 cli/smart/coalesced surface 都 fire，需过滤，无时机增益）。

## 3. 输入与安全

- 命令到达 adapter 时**已双重脱敏**：`redact_sensitive_text`（tools/approval.py:4022）+ `_redact_approval_command`（gateway/run.py:6930 附近）——解说器输入天然无凭据。
- 输入只有两样：脱敏后的命令（截 2000 字符）+ description（官方 flag 理由，截 500 字符）。**不含会话上下文、不含 CoT**——无泄漏面。
- Prompt 硬约束：NEVER 给推荐/结论性建议；NEVER 编造命令里没有的细节；≤3 句；无 markdown 标题/代码块；temperature=0、max_tokens≈250。
- 超时默认 30s（2026-09-20 定稿）：run.py 侧 `_approval_send_outcome(fut, timeout=15)` 只等 15s，超时按 ambiguous 处理（不重发、prompt 保持 armed，晚到的卡片点击仍可 resolve）——即解说耗时 30s 时最多造成网关日志一条 ambiguous warning，功能语义无损；实配下 xy-pro 通常 2-5s 返回。

## 4. 模块结构

```
owner/approval_explainer/
├── __init__.py    # 导出 explain_command / load_config / resolve_enabled / clear_cache
├── config.py      # patch.yaml owner.approval_explainer，三级查找，fail-open
├── prompt.py      # 提示词模板 + 输出约束（截断策略集中在此）
└── explain.py     # call_llm 包装：to_thread + wait_for + 永不抛 + 同命令 TTL 缓存
```

## 5. 配置面（patch.yaml，不进 config.yaml）

```yaml
owner:
  approval_explainer:
    enabled: true            # 代码默认 false；本机实配 true（落地不改他人行为）
    provider: auto           # auto/留空 → auxiliary auto 链（见 §6）
    model: auto
    timeout_ms: 30000        # 卡片等待解说上限，超时→无解说段照发
    cache_ttl_seconds: 600   # 同命令(含 description+language)短 TTL 缓存
    platforms:
      feishu: true
      qqbot: true
```

查找顺序：`chats.<platform>.<chat_id>` → `platforms.<platform>` → `enabled`（owner 侧三级查找，与 diff_card / progress_explainer 一致）。复用 `load_patch_config()`（60s TTL + mtime 失效 → 改完不重启）。

## 6. 模型解析（2026-09-20 定稿，与 progress_explainer 统一）

- `provider/model` 空（或 `auto`）→ 两个参数传 None → `call_llm(task="approval_explainer")` 走 **auxiliary auto 链**：config.yaml `auxiliary.approval_explainer` 任务段有配置按其生效，否则回落主聊天模型——**承接 hermes 自己的配置体系**（用户改主模型，解说跟着走）。
- 显式 provider/model → 作为 call_llm 显式参数直连（最高优先）。
- 本机实配：patch.yaml 写 `auto`；config.yaml 未建任务段（回落主聊天模型 glm-5.3/damodel，fallback 链含 xy-pro）。

**顺手对齐 progress_explainer**（同批改动）：`_DEFAULT_TIMEOUT_MS` 15000→30000；config 默认段加 provider/model（"auto"→空串归一）；patch.yaml `provider/model: auto` + `explainer_timeout_ms: 30000`；explain.py 注释更新。

## 7. 呈现

- **飞书**（零新增官方 diff——`build_approval_card` 本就在 owner/）：`explanation` 参数，md_content 在理由行之后追加 `📖 命令解读：\n{...}`（i18n `approval.feishu_explanation_label`）；空串时卡片与原行为**字节一致**。interactive 卡不走 `notice_titles` 文本转卡规则，无冲突。smart_deny 卡也带解说（帮用户判断要不要一次性推翻）。
- **QQ**：`ApprovalRequest` 加 `explanation: str = ""` 字段；`_build_exec_text` 在理由行后渲染（i18n `approval.qqbot_explanation_label`）；空串跳过。
- i18n：zh/en 各 2 个 key（其余 locale 走英文 fallback，与 feishu_reason_label 现状同覆盖面）。

## 8. 官方源码改动清单（实际）

| 文件 | 改动 | 标记 |
|---|---|---|
| `plugins/platforms/feishu/adapter.py` | send_exec_approval 内 await 解说 + 传参（~22 行） | `[owner]` |
| `gateway/platforms/qqbot/adapter.py` | 同上（~19 行） | `[owner]` |
| `gateway/platforms/qqbot/keyboards.py` | ApprovalRequest 字段 + 渲染（~10 行） | `[owner]` |
| `locales/zh.yaml` / `locales/en.yaml` | 各 +2 i18n key | — |
| `tools/approval.py`、`gateway/run.py`、`agent/*` | **不动** | 0 |

owner/ 侧：`owner/feishu/approval.py`（build_approval_card +explanation）；`owner/progress_explainer/`（timeout/auto 对齐）；`owner/config/patch.yaml`（§7.25 段 + §7.24 修订）。

## 9. 降级与兼容

| 情形 | 行为 |
|---|---|
| LLM 超时/异常 | fail-open：`explain_command` 永不抛 → 空串 → 卡片照发（无解说段） |
| 平台/会话未启用 | 入口直接 None，不调 LLM，零开销 |
| owner 模块缺席（import 失败） | 胶水 try/except 吞，卡片照发 |
| 同命令重复审批 | TTL 缓存命中，零延迟 |
| LLM 输出不准 | 缓解：prompt 只准陈述命令内事实 + 官方 description 仍置顶 + 📖 标记可辨识；无推荐结论 |
| smart approval 辅助 LLM | 不同 task，互不干扰 |

## 10. 测试

**单测** `tests/owner/test_approval_explainer.py`（20 例，mock call_llm 不打网络）：配置三级查找/auto 归一/非法回落；fail-open（异常/超时）；缓存命中/不命中/TTL 过期；引号剥离；飞书卡嵌入与空串字节一致；QQ 渲染与空串跳过；i18n key zh/en 存在性。

**回归**：`tests/tools/test_approval.py` 128、`tests/owner/`（progress_explainer 25 + approval_fail_card + notice_card + patch_allowlist + skill_script 16 + memory/feishu 卡系列 93 + skill_manage_gate）、`tests/plugins/platforms/feishu/` 12、`tests/gateway/test_slack_approval_buttons.py` 20——全绿。`tests/gateway/test_feishu_approval_buttons.py` 4 例存量环境性失败（改动前后同失败，非本功能引入）。

**E2E（真网关触发一次审批）**：[未验证]——需网关重启后真实触发一次 approval 卡观察 📖 段。

## 11. 二次开发规范 checklist

- [x] 主体逻辑全在 `owner/approval_explainer/`（4 模块），飞书建卡复用既有 owner/feishu/approval.py
- [x] 官方文件只有 `[owner]` 标记胶水（adapter ×2 + keyboards），tools/approval.py 零改动
- [x] 新配置 key 全在 patch.yaml（不进 config.yaml、不进官方 display_config）
- [x] 删除 owner/approval_explainer/ + 胶水后其余功能不受影响（fail-open 链）
- [x] 设计文档位于 `owner/docs/design/approval-command-explainer/`（本文件）
- [x] 改动清单：`owner/docs/owner改动清单.md` §7.25 独立条目
- [x] sync fork 冲突面：官方 adapter/keyboards 各一小块 `[owner]`，locales 纯增量
