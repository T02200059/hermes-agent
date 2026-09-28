# T1-4 工作清单：官方文件内 owner 新增的 i18n 调用点

> 由 `owner/scripts/i18n-owner-sites.py` 生成（AST 扫描 + catalog 对照）。上游参照：`upstream/main`。

## 摘要

| 项 | 数量 |
|---|---|
| 使用官方 `t()` 的官方文件 | 48 |
| `t()` 字面量调用点合计 | 958 |
| 其中键仅 owner 有（需回退为英文 + 展示层翻译） | 644 |
| 其中键上游也在用（可与上游写法对齐） | 314 |
| `t()` 首参非字面量（需人工判定） | 21 |

## 分类判据

- **owner 键**：上游没有这个键，说明调用点是 owner 为本地化而加进官方函数体的。
  回退为英文原文后，中文由 `owner/i18n/display_filter.py` 在展示层完成——
  该处代码随即与上游逐字节一致，冲突块归零。
- **shared 键**：上游也用这个键。若调用点与上游同形，回退即与上游对齐；
  若同键但位置不同，说明是 owner 在别处补的调用，同样按 owner 键处理。

## 按文件分布

| 文件 | 调用点 | owner 键 | shared 键 |
|---|---|---|---|
| `gateway/slash_commands.py` | 339 | 54 | 285 |
| `gateway/run.py` | 170 | 163 | 7 |
| `tools/approval.py` | 75 | 70 | 5 |
| `agent/conversation_loop.py` | 62 | 62 | 0 |
| `cli.py` | 40 | 40 | 0 |
| `hermes_cli/models.py` | 39 | 39 | 0 |
| `tools/memory_tool.py` | 31 | 31 | 0 |
| `tools/computer_use/doctor.py` | 22 | 22 | 0 |
| `gateway/platforms/base.py` | 17 | 17 | 0 |
| `run_agent.py` | 17 | 17 | 0 |
| `gateway/platforms/qqbot/keyboards.py` | 16 | 16 | 0 |
| `tools/file_tools.py` | 16 | 16 | 0 |
| `gateway/kanban_watchers.py` | 14 | 8 | 6 |
| `hermes_cli/model_switch.py` | 11 | 11 | 0 |
| `hermes_cli/slash_exec.py` | 11 | 0 | 11 |
| `agent/context_breakdown.py` | 9 | 9 | 0 |
| `plugins/platforms/discord/adapter.py` | 9 | 9 | 0 |
| `gateway/relay/adapter.py` | 7 | 7 | 0 |
| `cron/scheduler.py` | 6 | 6 | 0 |
| `tools/terminal_tool.py` | 6 | 6 | 0 |
| `gateway/platforms/whatsapp_cloud.py` | 5 | 5 | 0 |
| `tools/discord_tool.py` | 5 | 5 | 0 |
| `tools/process_registry.py` | 5 | 5 | 0 |
| `tools/skill_manager_tool.py` | 5 | 5 | 0 |
| `plugins/platforms/slack/adapter.py` | 3 | 3 | 0 |
| `tools/computer_use/tool.py` | 3 | 3 | 0 |
| `agent/display.py` | 2 | 2 | 0 |
| `tools/session_search_tool.py` | 2 | 2 | 0 |
| `acp_adapter/server.py` | 1 | 1 | 0 |
| `agent/message_sanitization.py` | 1 | 1 | 0 |
| `gateway/platforms/api_server.py` | 1 | 1 | 0 |
| `gateway/platforms/api_server_media.py` | 1 | 1 | 0 |
| `gateway/platforms/qqbot/adapter.py` | 1 | 1 | 0 |
| `gateway/session_stall.py` | 1 | 1 | 0 |
| `plugins/platforms/matrix/adapter.py` | 1 | 1 | 0 |
| `tools/computer_use/backend.py` | 1 | 1 | 0 |
| `tools/cronjob_tools.py` | 1 | 1 | 0 |
| `tools/skills_tool.py` | 1 | 1 | 0 |
| `tools/website_policy.py` | 1 | 1 | 0 |

## 逐条清单（owner 键）

| 文件:行 | 键 | 英文原文（回退目标） | 中文译文（展示层） |
|---|---|---|---|
| `acp_adapter/server.py:2550` | `gateway.steer_failed` | `⚠️ Steer failed: {error}` | `⚠️ 导向失败：{error}` |
| `agent/context_breakdown.py:304` | `gateway.context.breakdown_by_category` | `Estimated usage by category` | `按类别估算用量` |
| `agent/context_breakdown.py:306` | `gateway.context.breakdown_no_data` | `(no data yet — send a message first)` | `（暂无数据——请先发送一条消息）` |
| `agent/context_breakdown.py:309` | `gateway.context.breakdown_free_space` | `Free space` | `空闲空间` |
| `agent/context_breakdown.py:332` | `gateway.context.breakdown_toolsets_header` | `Toolsets by schema cost (largest first)` | `工具集 schema 开销（由大到小）` |
| `agent/context_breakdown.py:340` | `gateway.context.breakdown_and_more` | `… and {remaining} more` | `… 另有 {remaining} 项` |
| `agent/context_breakdown.py:346` | `gateway.context.breakdown_skills_header` | `Skills by cost (index = always-on; SKILL.md = cost when loaded)` | `技能开销（index = 常驻；SKILL.md = 加载时开销）` |
| `agent/context_breakdown.py:359` | `gateway.context.breakdown_and_more` | `… and {remaining} more` | `… 另有 {remaining} 项` |
| `agent/context_breakdown.py:389` | `gateway.context.breakdown_window` | `Context window: {used} / {total} tokens ({pct}%)` | `上下文窗口：{used} / {total} tokens（{pct}%）` |
| `agent/context_breakdown.py:404` | `gateway.context.breakdown_expand_hint` | `Use /context all for per-skill and per-toolset costs.` | `使用 /context all 查看各技能与工具集开销。` |
| `agent/conversation_loop.py:782` | `gateway.error.billing_selected_provider` | `the selected provider` | `当前所选提供商` |
| `agent/conversation_loop.py:785` | `gateway.error.billing_selected_model` | `the selected model` | `当前所选模型` |
| `agent/conversation_loop.py:824` | `gateway.error.billing_guidance_anthropic_exhausted` | `{provider} reported that your Claude subscription usage is exhausted for {model} (included quota + extra-usage credits).` | `{provider} 反馈 Claude 订阅用量已耗尽（模型：{model}；含套餐额度 + 额外用量额度）。` |
| `agent/conversation_loop.py:829` | `gateway.error.billing_guidance_anthropic_options` | `Options: wait for the billing cycle to reset, or add extra usage at https://claude.ai/settings/usage` | `可选：等待计费周期重置，或在 https://claude.ai/settings/usage 增加额外用量。` |
| `agent/conversation_loop.py:830` | `gateway.error.billing_guidance_anthropic_switch` | `You can also switch to an Anthropic API key or another provider with /model <model> --provider <provider>.` | `也可改用 Anthropic API Key 或其他提供商：/model <model> --provider <provider>。` |
| `agent/conversation_loop.py:848` | `gateway.error.billing_guidance_exhausted` | `{provider} reported that billing, credits, or account entitlement is exhausted for {model}.` | `{provider} 反馈账户额度、余额或权益已耗尽（模型：{model}）。` |
| `agent/conversation_loop.py:853` | `gateway.error.billing_guidance_add_credits` | `Add credits or update billing with that provider, then retry.` | `请在该提供商处充值或更新账单配置后重试。` |
| `agent/conversation_loop.py:857` | `gateway.error.billing_guidance_url` | `{provider} billing: {url}` | `{provider} 账单页：{url}` |
| `agent/conversation_loop.py:863` | `gateway.error.billing_guidance_switch` | `You can switch providers temporarily with /model <model> --provider <provider>.` | `也可临时切换提供商：/model <model> --provider <provider>。` |
| `agent/conversation_loop.py:1534` | `gateway.model.content_policy_recovery_hint` | `Try rephrasing the request, narrowing the context, or adding a fallback provider with `hermes fallback add`.` | `尝试换一种表述、缩小上下文范围，或使用 `hermes fallback add` 添加备用提供方。` |
| `agent/conversation_loop.py:2244` | `gateway.runtime.tool_loop_interrupt` | `⚡ Breaking out of tool loop due to interrupt...` | `⚡ 因中断而退出工具循环…` |
| `agent/conversation_loop.py:2880` | `gateway.runtime.ollama_context_too_small` | `❌ Ollama runtime context is too small for Hermes tool use` | `❌ Ollama 运行时上下文过小，无法可靠使用 Hermes 工具` |
| `agent/conversation_loop.py:3722` | `gateway.runtime.fallback_empty_malformed` | `⚠️ Empty/malformed response — switching to fallback...` | `⚠️ 响应为空或格式异常，正在切换到 fallback 提供商…` |
| `agent/conversation_loop.py:3796` | `gateway.runtime.fallback_trying` | `⚠️ Max retries ({max_retries}) exhausted — trying fallback...` | `⚠️ 已重试 {max_retries} 次仍未成功，正在尝试 fallback 提供商…` |
| `agent/conversation_loop.py:3807` | `gateway.runtime.max_retries_invalid_response` | `❌ Max retries ({max_retries}) exceeded for invalid responses. Giving up.` | `❌ 无效响应已重试 {max_retries} 次，放弃继续。` |
| `agent/conversation_loop.py:3814` | `gateway.error.invalid_api_response` | `Invalid API response after {max_retries} retries: {failure_hint}` | `API 响应无效（已重试 {max_retries} 次）：{failure_hint}` |
| `agent/conversation_loop.py:3846` | `gateway.interrupt_retry` | `Operation interrupted during retry ({reason}, attempt {attempt}/{max}).` | `操作在重试时中断（{reason}，第 {attempt}/{max} 次）。` |
| `agent/conversation_loop.py:3977` | `gateway.model.content_policy_trying_fallback` | `Model declined to respond (safety refusal) — trying fallback...` | `模型拒绝响应（安全拒绝）— 正在尝试备用模型…` |
| `agent/conversation_loop.py:4001` | `gateway.model.content_policy_refusal_status` | `The model declined to respond to this request (safety refusal).` | `模型拒绝响应此请求（安全拒绝）。` |
| `agent/conversation_loop.py:4005` | `gateway.model.content_policy_explanation` | `Model's explanation: {explanation}` | `模型解释：{explanation}` |
| `agent/conversation_loop.py:4008` | `gateway.model.content_policy_no_explanation` | `The model returned no explanation.` | `模型未提供解释。` |
| `agent/conversation_loop.py:4012` | `gateway.model.content_policy_refusal_response` | `The model declined to respond to this request (safety refusal — not a Hermes/gateway failure).` | `模型拒绝响应此请求（安全拒绝 — 非 Hermes/网关故障）。` |
| `agent/conversation_loop.py:4102` | `gateway.runtime.thinking_budget_exhausted` | `⚠️ **Thinking Budget Exhausted**

The model used all its output tokens on reasoning and had none left for the actual response.

To fix this:
→ Lower reasoning effort: `/thinkon low` or `/thinkon minimal`
→ Or switch to a larger/non-reasoning model with `/model`` | `⚠️ **思考预算已耗尽**

模型把全部输出 token 都用在了推理上，没有剩余额度生成实际回复。

解决办法：
→ 降低推理力度：`/thinkon low` 或 `/thinkon minimal`
→ 或使用 `/model` 切换到更大/非推理模型` |
| `agent/conversation_loop.py:4603` | `gateway.runtime.cached_context_length` | `💾 Cached context length: {ctx} tokens for {model}` | `💾 已缓存上下文长度：{model} 为 {ctx} 个 token` |
| `agent/conversation_loop.py:5641` | `gateway.interrupt_api_error` | `Operation interrupted: handling API error ({error_type}: {error_detail}). Try again later or switch models with /model.` | `操作中断：正在处理 API 错误（{error_type}: {error_detail}）。建议稍后重试，或用 /model 切换模型。` |
| `agent/conversation_loop.py:5853` | `gateway.runtime.fallback_upstream_rate_limited` | `⚠️ Upstream {upstream} rate-limited — switching to fallback model...` | `⚠️ 上游 {upstream} 触发速率限制，正在切换到 fallback 模型…` |
| `agent/conversation_loop.py:5868` | `gateway.runtime.fallback_billing_exhausted` | `⚠️ Billing or credits exhausted — switching to fallback provider...` | `⚠️ 额度或余额已耗尽，正在切换到 fallback 提供商…` |
| `agent/conversation_loop.py:5872` | `gateway.runtime.fallback_provider_unreachable` | `⚠️ Provider unreachable — switching to fallback provider...` | `⚠️ 提供方不可达，正在切换到 fallback 提供商…` |
| `agent/conversation_loop.py:5875` | `gateway.runtime.fallback_rate_limited` | `⚠️ Rate limited — switching to fallback provider...` | `⚠️ 触发速率限制，正在切换到 fallback 提供商…` |
| `agent/conversation_loop.py:6033` | `gateway.error.payload_too_large_max_compression` | `Request payload too large: max compression attempts ({max_compression_attempts}) reached.` | `请求负载过大：已达最大压缩尝试次数（{max_compression_attempts}）。建议使用 /new 开启新对话。` |
| `agent/conversation_loop.py:6045` | `gateway.runtime.payload_too_large_compressing` | `⚠️ Request payload too large (413) — compression attempt {current}/{total}...` | `⚠️ 请求负载过大 (413) — 正在压缩（第 {current}/{total} 次）…` |
| `agent/conversation_loop.py:6147` | `gateway.error.payload_too_large_413` | `Request payload too large (413). Cannot compress further.` | `请求负载过大 (413)。无法进一步压缩。建议使用 /new 开启新对话。` |
| `agent/conversation_loop.py:6225` | `gateway.error.context_exceeded_max_compression` | `Context length exceeded: max compression attempts ({max_compression_attempts}) reached.` | `上下文长度超限：已达最大压缩尝试次数（{max_compression_attempts}）。建议使用 /new 开启新对话。` |
| `agent/conversation_loop.py:6388` | `gateway.error.context_exceeded_max_compression` | `Context length exceeded: max compression attempts ({max_compression_attempts}) reached.` | `上下文长度超限：已达最大压缩尝试次数（{max_compression_attempts}）。建议使用 /new 开启新对话。` |
| `agent/conversation_loop.py:6484` | `gateway.error.context_exceeded_tokens` | `Context length exceeded ({new_tokens} tokens). Cannot compress further.` | `上下文长度超限（{new_tokens} tokens）。无法进一步压缩。建议使用 /new 开启新对话。` |
| `agent/conversation_loop.py:6602` | `gateway.model.content_policy_provider_trying_fallback` | `Provider safety filter blocked this request — trying fallback...` | `提供方安全过滤器拦截了此请求 — 正在尝试备用模型…` |
| `agent/conversation_loop.py:6604` | `gateway.model.tls_cert_verification_failed_trying_fallback` | `` | `` |
| `agent/conversation_loop.py:6607` | `gateway.runtime.fallback_non_retryable` | `⚠️ Non-retryable error (HTTP {status_code}) — trying fallback...` | `⚠️ 不可重试错误（HTTP {status_code}），正在尝试 fallback…` |
| `agent/conversation_loop.py:6636` | `gateway.runtime.status_content_policy_blocked` | `❌ Provider safety filter blocked this request: {summary}` | `❌ 提供方安全过滤器拦截了此请求：{summary}` |
| `agent/conversation_loop.py:6643` | `gateway.runtime.status_ssl_cert_failed` | `❌ TLS certificate verification failed: {summary}` | `❌ TLS 证书校验失败：{summary}` |
| `agent/conversation_loop.py:6650` | `gateway.runtime.status_non_retryable` | `❌ Non-retryable error (HTTP {status_code}): {summary}` | `❌ 不可重试错误（HTTP {status_code}）：{summary}` |
| `agent/conversation_loop.py:6786` | `gateway.model.content_policy_provider_blocked` | `The model provider's safety filter blocked this request (not a Hermes/gateway failure).` | `模型提供方的安全过滤器拦截了此请求（非 Hermes/网关故障）。` |
| `agent/conversation_loop.py:6788` | `gateway.model.content_policy_provider_message` | `Provider message: {message}` | `提供方消息：{message}` |
| `agent/conversation_loop.py:6842` | `gateway.runtime.fallback_trying` | `⚠️ Max retries ({max_retries}) exhausted — trying fallback...` | `⚠️ 已重试 {max_retries} 次仍未成功，正在尝试 fallback 提供商…` |
| `agent/conversation_loop.py:6864` | `gateway.runtime.status_billing_exhausted` | `❌ Billing or credits exhausted — {summary}` | `❌ 额度或余额已耗尽 — {summary}` |
| `agent/conversation_loop.py:6886` | `gateway.runtime.status_rate_limited` | `❌ Rate limited after {max_retries} retries — {summary}` | `❌ 重试 {max_retries} 次后仍触发速率限制 — {summary}` |
| `agent/conversation_loop.py:6894` | `gateway.runtime.status_api_failed` | `❌ API failed after {max_retries} retries — {summary}` | `❌ API 调用在重试 {max_retries} 次后失败 — {summary}` |
| `agent/conversation_loop.py:7023` | `gateway.error.api_failed_after_retries` | `API call failed after {max_retries} retries: {final_summary}` | `API 调用在重试 {max_retries} 次后失败：{final_summary}` |
| `agent/conversation_loop.py:7118` | `gateway.runtime.retrying_in` | `⏳ Retrying in {wait_time}s (attempt {attempt}/{max})...` | `⏳ {wait_time} 秒后重试（第 {attempt}/{max} 次尝试）…` |
| `agent/conversation_loop.py:7147` | `gateway.interrupt_retry_after_error` | `Operation interrupted: retrying API call after error (retry {attempt}/{max}).` | `操作中断：错误后重试 API 调用（第 {attempt}/{max} 次重试）。` |
| `agent/conversation_loop.py:7650` | `gateway.error.invalid_tool_call` | `Model generated invalid tool call: {invalid_preview}. Try switching models with /model or start fresh with /new.` | `模型生成了无效的工具调用：{invalid_preview}。建议用 /model 切换模型或 /new 开启新对话。` |
| `agent/conversation_loop.py:8013` | `toolguard.halt_status` | `⚠️ Tool guardrail halted {tool_name}: {code}` | `⚠️ 工具护栏已暂停 {tool_name}：{code}` |
| `agent/conversation_loop.py:8287` | `gateway.runtime.empty_response_fallback` | `↻ Empty response after tool calls — using earlier content as final answer` | `↻ 工具调用后返回空响应 — 将使用之前的内容作为最终答案` |
| `agent/conversation_loop.py:8343` | `gateway.runtime.empty_after_tool_calls` | `⚠️ Model returned empty after tool calls — nudging to continue` | `⚠️ 模型在工具调用后返回空响应 — 正在提示其继续` |
| `agent/conversation_loop.py:8459` | `gateway.runtime.empty_response_retrying` | `⚠️ Empty response from model — retrying ({current}/{total})` | `⚠️ 模型返回空响应 — 正在重试（{current}/{total}）` |
| `agent/conversation_loop.py:8523` | `gateway.runtime.empty_response_switching_fallback` | `⚠️ Model returning empty responses — switching to fallback provider...` | `⚠️ 模型持续返回空响应 — 正在切换到 fallback 提供商…` |
| `agent/conversation_loop.py:8587` | `gateway.runtime.reasoning_no_visible` | `⚠️ Model produced reasoning but no visible response after all retries. Returning empty.` | `⚠️ 模型在全部重试后只产出了推理、没有可见回复。将返回空结果。` |
| `agent/conversation_loop.py:8937` | `gateway.runtime.kanban_exit_without_complete` | `⚠️ Kanban worker tried to exit without kanban_complete/kanban_block — nudging to finish` | `⚠️ Kanban worker 在未调用 kanban_complete/kanban_block 的情况下尝试退出 — 正在提示其完成` |
| `agent/conversation_loop.py:8972` | `gateway.runtime.conversation_completed` | `🎉 Conversation completed after {count} OpenAI-compatible API call(s)` | `🎉 对话已完成，共进行了 {count} 次 OpenAI 兼容 API 调用` |
| `agent/conversation_loop.py:9123` | `gateway.error.repeated_errors` | `I apologize, but I encountered repeated errors: {error_msg}` | `很抱歉，遇到了反复出现的错误：{error_msg}。如反复出现，建议用 /new 开启新对话或 /model 切换模型。` |
| `agent/conversation_loop.py:9127` | `gateway.error.repeated_errors` | `I apologize, but I encountered repeated errors: {error_msg}` | `很抱歉，遇到了反复出现的错误：{error_msg}。如反复出现，建议用 /new 开启新对话或 /model 切换模型。` |
| `agent/conversation_loop.py:9130` | `gateway.error.repeated_errors` | `I apologize, but I encountered repeated errors: {error_msg}` | `很抱歉，遇到了反复出现的错误：{error_msg}。如反复出现，建议用 /new 开启新对话或 /model 切换模型。` |
| `agent/display.py:838` | `display.tool_label.terminal_header` | `terminal` | `运行命令` |
| `agent/display.py:925` | `display.tool_status.using` | `is using {tool}` | `正在使用 {tool}` |
| `agent/message_sanitization.py:327` | `gateway.interrupt.placeholder` | `Operation interrupted.` | `操作已中断。` |
| `cli.py:14590` | `approval.slash_confirm.mcp_config_changed` | `🔄 MCP server config changed — reloading connections...` | `🔄 MCP 服务器配置已变更 — 正在重新加载连接...` |
| `cli.py:14696` | `approval.slash_confirm.choice_once` | `Approve Once` | `批准一次` |
| `cli.py:14696` | `approval.slash_confirm.hint_destructive_once` | `proceed this time only` | `仅本次执行` |
| `cli.py:14697` | `approval.slash_confirm.choice_always` | `Always Approve` | `始终批准` |
| `cli.py:14697` | `approval.slash_confirm.hint_destructive_always` | `proceed and silence this prompt permanently` | `执行并永久关闭此提示` |
| `cli.py:14698` | `approval.slash_confirm.choice_cancel` | `Cancel` | `取消` |
| `cli.py:14698` | `approval.slash_confirm.hint_destructive_cancel` | `keep current conversation` | `保留当前会话` |
| `cli.py:14701` | `approval.slash_confirm.destructive_title` | `⚠️  /{command} — destroys conversation state` | `⚠️  /{command} — 将销毁会话状态` |
| `cli.py:14702` | `approval.slash_confirm.destructive_detail_default` | `This will discard the current conversation history. This cannot be undone.` | `这将丢弃当前对话历史，无法撤销。` |
| `cli.py:14706` | `approval.slash_confirm.cancelled_no_input` | `🟡 /{command} cancelled (no input).` | `🟡 /{command} 已取消（无输入）。` |
| `cli.py:14710` | `approval.slash_confirm.cancelled_unrecognized` | `🟡 Unrecognized choice '{raw}'. /{command} cancelled.` | `🟡 无法识别的选择 '{raw}'。/{command} 已取消。` |
| `cli.py:14714` | `approval.slash_confirm.cancelled_explicit_destructive` | `🟡 /{command} cancelled. Conversation unchanged.` | `🟡 /{command} 已取消。会话不变。` |
| `cli.py:14719` | `approval.slash_confirm.optout_saved_destructive` | `🔒 Future /clear, /new, /reset, and /undo will run without confirmation.` | `🔒 以后的 /clear、/new、/reset 和 /undo 将不再需要确认。` |
| `cli.py:14720` | `approval.slash_confirm.optout_hint_destructive` | `   Re-enable via `approvals.destructive_slash_confirm: true` in config.yaml.` | `   在 config.yaml 中设置 `approvals.destructive_slash_confirm: true` 可重新启用。` |
| `cli.py:14722` | `approval.slash_confirm.optout_failed_destructive` | `⚠️  Couldn't persist opt-out — proceeding once.` | `⚠️  无法保存免确认设置 — 本次继续执行。` |
| `cli.py:14757` | `approval.slash_confirm.choice_once` | `Approve Once` | `批准一次` |
| `cli.py:14757` | `approval.slash_confirm.hint_mcp_once` | `reload now` | `立即重载` |
| `cli.py:14758` | `approval.slash_confirm.choice_always` | `Always Approve` | `始终批准` |
| `cli.py:14758` | `approval.slash_confirm.hint_mcp_always` | `reload now and silence this prompt permanently` | `立即重载并永久关闭此提示` |
| `cli.py:14759` | `approval.slash_confirm.choice_cancel` | `Cancel` | `取消` |
| `cli.py:14759` | `approval.slash_confirm.hint_mcp_cancel` | `leave MCP tools unchanged` | `保持 MCP 工具不变` |
| `cli.py:14762` | `approval.slash_confirm.mcp_title` | `⚠️  /{command} — Prompt cache invalidation warning` | `⚠️  /{command} — 提示词缓存失效警告` |
| `cli.py:14763` | `approval.slash_confirm.mcp_detail` | `Reloading MCP servers rebuilds the tool set for this session and invalidates the provider prompt cache. The next message will re-send full input tokens (can be expensive on long-context or high-reasoning models).` | `重新加载 MCP 服务器会重建本会话的工具集，并使提供方提示词缓存失效。 下一条消息将重新发送全部输入 token（对于长上下文或高推理模型可能 开销较大）。` |
| `cli.py:14767` | `approval.slash_confirm.cancelled_no_input` | `🟡 /{command} cancelled (no input).` | `🟡 /{command} 已取消（无输入）。` |
| `cli.py:14771` | `approval.slash_confirm.cancelled_unrecognized` | `🟡 Unrecognized choice '{raw}'. /{command} cancelled.` | `🟡 无法识别的选择 '{raw}'。/{command} 已取消。` |
| `cli.py:14775` | `approval.slash_confirm.cancelled_explicit_mcp` | `🟡 /{command} cancelled. MCP tools unchanged.` | `🟡 /{command} 已取消。MCP 工具不变。` |
| `cli.py:14780` | `approval.slash_confirm.optout_saved_mcp` | `🔒 Future /{command} calls will run without confirmation.` | `🔒 以后的 /{command} 调用将不再需要确认。` |
| `cli.py:14781` | `approval.slash_confirm.optout_hint_mcp` | `   Re-enable via `approvals.mcp_reload_confirm: true` in config.yaml.` | `   在 config.yaml 中设置 `approvals.mcp_reload_confirm: true` 可重新启用。` |
| `cli.py:14783` | `approval.slash_confirm.optout_failed_mcp` | `⚠️  Couldn't persist opt-out — reloading once.` | `⚠️  无法保存免确认设置 — 本次继续重载。` |
| `cli.py:14802` | `approval.slash_confirm.reloading_mcp` | `🔄 Reloading MCP servers...` | `🔄 正在重新加载 MCP 服务器...` |
| `cli.py:14909` | `approval.slash_confirm.reloading_skills` | `🔄 Reloading skills...` | `🔄 正在重新加载 skill...` |
| `cli.py:16667` | `approval.dangerous_title` | `⚠️  Dangerous Command` | `⚠️  危险命令` |
| `cli.py:16670` | `approval.choice_once` | `Allow once` | `允许一次` |
| `cli.py:16671` | `approval.choice_session` | `Allow for this session` | `允许本次会话` |
| `cli.py:16672` | `approval.choice_always` | `Add to permanent allowlist` | `添加到永久允许列表` |
| `cli.py:16673` | `approval.choice_deny` | `Deny` | `拒绝` |
| `cli.py:16674` | `approval.choice_view` | `Show full command` | `显示完整命令` |
| `cli.py:16694` | `approval.hint_choose_view` | `… (choose Show full command)` | `…（选择“显示完整命令”）` |
| `cli.py:16747` | `approval.hint_command_truncated` | `… (command truncated — use /logs or /debug for full text)` | `…（命令已截断 — 使用 /logs 或 /debug 查看完整文本）` |
| `cli.py:16764` | `approval.hint_description_truncated` | `… (description truncated)` | `…（描述已截断）` |
| `cron/scheduler.py:303` | `cron.fallback_job_name` | `cron job` | `定时任务` |
| `cron/scheduler.py:415` | `cron.failure_auth` | `⚠️ Cron '{job_name}' failed: provider authentication error. Full details saved in cron output.` | `⚠️ Cron '{job_name}' 执行失败：提供商身份认证错误。详细信息已保存到 cron 输出。` |
| `cron/scheduler.py:427` | `cron.failure_generic` | `⚠️ Cron '{job_name}' failed: {details}` | `⚠️ Cron '{job_name}' 执行失败：{details}` |
| `cron/scheduler.py:3091` | `cron.wrap_header` | `Cronjob Response: {task_name}` | `Cron 任务回复：{task_name}` |
| `cron/scheduler.py:3092` | `cron.wrap_job_id` | `(job_id: {job_id})` | `(job_id: {job_id})` |
| `cron/scheduler.py:3095` | `cron.wrap_footer` | `To stop or manage this job, send me a new message (e.g. "stop reminder {task_name}").` | `如需停止或管理此任务，请给我发一条新消息（例如「停止提醒 {task_name}」）。` |
| `gateway/kanban_watchers.py:878` | `gateway.kanban.wake.completed` | `completed` | `已完成` |
| `gateway/kanban_watchers.py:879` | `gateway.kanban.wake.gave_up` | `gave up (retries exhausted)` | `已放弃（重试次数耗尽）` |
| `gateway/kanban_watchers.py:880` | `gateway.kanban.wake.crashed` | `crashed (worker exited); dispatcher will retry` | `崩溃（worker 异常退出），dispatcher 将重试` |
| `gateway/kanban_watchers.py:881` | `gateway.kanban.wake.timed_out` | `timed out; dispatcher will retry` | `超时，dispatcher 将重试` |
| `gateway/kanban_watchers.py:882` | `gateway.kanban.wake.blocked` | `blocked; needs attention` | `被阻塞，需要处理` |
| `gateway/kanban_watchers.py:883` | `gateway.kanban.wake.review_requested` | `handed off for review; the implementation is done` | `已交付评审；实现已完成` |
| `gateway/kanban_watchers.py:884` | `gateway.kanban.wake.changes_requested` | `review requested changes (BLOCK); implementation is not approved` | `评审要求修改（BLOCK)，实现未获批准` |
| `gateway/kanban_watchers.py:885` | `gateway.kanban.wake.block_loop_detected` | `routed to triage after repeated blocks; needs a decision` | `反复阻塞后被转入待分诊，需要做出决定` |
| `gateway/platforms/api_server.py:8197` | `gateway.model.provider_auth_failed_detail` | `⚠️ Provider authentication failed: {error}` | `⚠️ 提供方认证失败：{error}` |
| `gateway/platforms/api_server_media.py:572` | `gateway.media_too_large` | `⚠️ Attachment {file_name} ({size}) exceeds the {limit} delivery limit and was not offered for download.` | `⚠️ 附件「{file_name}」（{size}）超过 {limit} 的投递上限，未提供下载。` |
| `gateway/platforms/base.py:4390` | `approval.card_title_exec` | `⚠️ Command Approval Required` | `⚠️ 命令审批请求` |
| `gateway/platforms/base.py:4397` | `approval.card_reason_prefix` | `Reason: ` | `原因：` |
| `gateway/platforms/base.py:4401` | `approval.card_smart_deny_note` | `Smart DENY: owner override applies to this one operation only.` | `智能审批拦截（Smart DENY）：本次覆盖仅对当前这一次操作生效。` |
| `gateway/platforms/base.py:4568` | `gateway.clarify_choices` | `❓ {question}

{choices}

Reply with the number, the option text, or your own answer.` | `❓ {question}

{choices}

回复数字、选项文本，或输入你自己的答案。` |
| `gateway/platforms/base.py:4576` | `gateway.clarify_choices` | `❓ {question}

{choices}

Reply with the number, the option text, or your own answer.` | `❓ {question}

{choices}

回复数字、选项文本，或输入你自己的答案。` |
| `gateway/platforms/base.py:4586` | `gateway.clarify_question` | `❓ {question}` | `❓ {question}` |
| `gateway/platforms/base.py:4825` | `gateway.audio_attachment_failed` | `⚠️ Couldn't deliver the audio attachment.` | `⚠️ 无法发送音频附件。` |
| `gateway/platforms/base.py:4969` | `gateway.video_attachment_failed` | `⚠️ Couldn't deliver the video attachment.` | `⚠️ 无法发送视频附件。` |
| `gateway/platforms/base.py:5001` | `gateway.file_attachment_failed_with_name` | `⚠️ Couldn't deliver the file attachment ({file_name}).` | `⚠️ 无法发送文件附件（{file_name}）。` |
| `gateway/platforms/base.py:5003` | `gateway.file_attachment_failed` | `⚠️ Couldn't deliver the file attachment.` | `⚠️ 无法发送文件附件。` |
| `gateway/platforms/base.py:5026` | `gateway.audio_attachment_failed` | `⚠️ Couldn't deliver the audio attachment.` | `⚠️ 无法发送音频附件。` |
| `gateway/platforms/base.py:5028` | `gateway.video_attachment_failed` | `⚠️ Couldn't deliver the video attachment.` | `⚠️ 无法发送视频附件。` |
| `gateway/platforms/base.py:5031` | `gateway.file_attachment_failed_with_name` | `⚠️ Couldn't deliver the file attachment ({file_name}).` | `⚠️ 无法发送文件附件（{file_name}）。` |
| `gateway/platforms/base.py:5070` | `gateway.image_attachment_failed` | `⚠️ Couldn't deliver the image attachment.` | `⚠️ 无法发送图片附件。` |
| `gateway/platforms/base.py:5857` | `gateway.delivery_failed_notice` | `⚠️ Message delivery failed after multiple attempts. Please try again — your request was processed but the response could not be sent.` | `⚠️ 消息多次尝试发送均失败。请重试 — 你的请求已处理，但响应无法送达。` |
| `gateway/platforms/base.py:5868` | `gateway.formatting_failed_prefix` | `(Response formatting failed, plain text:)` | `（响应格式化失败，纯文本：）` |
| `gateway/platforms/base.py:7182` | `gateway.handler_error` | `Sorry, I encountered an error ({error_type}).
{error_detail}
Try again or use /reset to start a fresh session.` | `抱歉，发生了错误（{error_type}）。
{error_detail}
请重试，或使用 /reset 开始新会话。` |
| `gateway/platforms/qqbot/adapter.py:2840` | `approval.qqbot_exec_subtitle` | `Execute this command?` | `执行此命令？` |
| `gateway/platforms/qqbot/keyboards.py:218` | `approval.qqbot_btn_once` | `✅ Allow Once` | `✅ 允许一次` |
| `gateway/platforms/qqbot/keyboards.py:219` | `approval.qqbot_visited_once` | `Allowed` | `已允许` |
| `gateway/platforms/qqbot/keyboards.py:228` | `approval.qqbot_btn_always` | `⭐ Always Allow` | `⭐ 始终允许` |
| `gateway/platforms/qqbot/keyboards.py:229` | `approval.qqbot_visited_always` | `Always Allowed` | `已始终允许` |
| `gateway/platforms/qqbot/keyboards.py:235` | `approval.qqbot_btn_deny` | `❌ Deny` | `❌ 拒绝` |
| `gateway/platforms/qqbot/keyboards.py:236` | `approval.qqbot_visited_deny` | `Denied` | `已拒绝` |
| `gateway/platforms/qqbot/keyboards.py:321` | `approval.qqbot_cwd_label` | `📁 Directory: {cwd}` | `📁 目录：{cwd}` |
| `gateway/platforms/qqbot/keyboards.py:325` | `approval.qqbot_reason_label` | `📝 {description}` | `📝 {description}` |
| `gateway/platforms/qqbot/keyboards.py:329` | `approval.qqbot_explanation_label` | `📖 **What this does:**
{explanation}` | `📖 **命令解读：**
{explanation}` |
| `gateway/platforms/qqbot/keyboards.py:335` | `approval.qqbot_smart_deny_note` | `🤖 **Smart DENY:** The smart-approval model assessed this command as genuinely dangerous.

You can still override, but **only for this single operation**. Always Allow is unavailable so one click cannot weaken protection for similar later commands.` | `🤖 **智能审批拦截（Smart DENY）**：辅助模型已判定该命令确实危险。

你仍可手动覆盖，但**仅限本次执行一次**。不提供「始终允许」，以免一次放行削弱后续同类命令的防护。` |
| `gateway/platforms/qqbot/keyboards.py:338` | `approval.qqbot_permanent_disabled` | `💡 Permanent approval is disabled. Choose Allow Once instead.` | `💡 永久允许已禁用，请选择允许一次。` |
| `gateway/platforms/qqbot/keyboards.py:340` | `approval.qqbot_timeout_label` | `⏱️ Timeout: {timeout} seconds` | `⏱️ 超时：{timeout} 秒` |
| `gateway/platforms/qqbot/keyboards.py:350` | `approval.qqbot_plugin_title` | `**Approval Request**` | `**审批请求**` |
| `gateway/platforms/qqbot/keyboards.py:353` | `approval.qqbot_reason_label` | `📝 {description}` | `📝 {description}` |
| `gateway/platforms/qqbot/keyboards.py:355` | `approval.qqbot_tool_label` | `🔧 Tool: {tool_name}` | `🔧 工具：{tool_name}` |
| `gateway/platforms/qqbot/keyboards.py:357` | `approval.qqbot_timeout_label` | `⏱️ Timeout: {timeout} seconds` | `⏱️ 超时：{timeout} 秒` |
| `gateway/platforms/whatsapp_cloud.py:875` | `approval.card_title_exec_md` | `⚠️ *Command Approval Required*` | `⚠️ *命令审批请求*` |
| `gateway/platforms/whatsapp_cloud.py:877` | `approval.reason_label` | `Reason: {description}` | `原因：{description}` |
| `gateway/platforms/whatsapp_cloud.py:879` | `approval.card_smart_deny_note` | `Smart DENY: owner override applies to this one operation only.` | `智能审批拦截（Smart DENY）：本次覆盖仅对当前这一次操作生效。` |
| `gateway/platforms/whatsapp_cloud.py:896` | `approval.whatsapp_btn_approve` | `✅ Approve` | `✅ 允许` |
| `gateway/platforms/whatsapp_cloud.py:903` | `approval.whatsapp_btn_deny` | `❌ Deny` | `❌ 拒绝` |
| `gateway/relay/adapter.py:2922` | `approval.relay_btn_once` | `Allow Once` | `允许一次` |
| `gateway/relay/adapter.py:2927` | `approval.relay_btn_session` | `Allow Session` | `本次会话允许` |
| `gateway/relay/adapter.py:2932` | `approval.relay_btn_always` | `Always Allow` | `始终允许` |
| `gateway/relay/adapter.py:2935` | `approval.relay_btn_deny` | `Deny` | `拒绝` |
| `gateway/relay/adapter.py:2940` | `approval.card_title_exec_md_strong` | `⚠️ **Command Approval Required**` | `⚠️ **命令审批请求**` |
| `gateway/relay/adapter.py:2942` | `approval.reason_label` | `Reason: {description}` | `原因：{description}` |
| `gateway/relay/adapter.py:2945` | `approval.relay_smart_deny_note` | `**Smart DENY:** owner override applies to this one operation only.` | `**智能审批拦截（Smart DENY）：**本次覆盖仅对当前这一次操作生效。` |
| `gateway/run.py:914` | `gateway.approval_fallback.heading` | `⚠️ **Dangerous command requires approval:**` | `⚠️ **危险命令需要审批：**` |
| `gateway/run.py:916` | `gateway.approval_fallback.heading_smart_deny` | `⚠️ **Smart DENY — owner override for one operation:**` | `⚠️ **智能拒绝 — 仅允许覆盖本次操作：**` |
| `gateway/run.py:919` | `gateway.approval_fallback.choice_once` | `Reply `{command_prefix}approve` to execute this one operation` | `回复 `{command_prefix}approve` 仅执行本次操作` |
| `gateway/run.py:923` | `gateway.approval_fallback.choice_session` | ``{command_prefix}approve session` to approve this pattern for the session` | ``{command_prefix}approve session` 在本会话批准该模式` |
| `gateway/run.py:930` | `gateway.approval_fallback.choice_always` | ``{command_prefix}approve always` to approve permanently` | ``{command_prefix}approve always` 永久批准` |
| `gateway/run.py:936` | `gateway.approval_fallback.choice_deny` | ``{command_prefix}deny` to cancel` | ``{command_prefix}deny` 取消` |
| `gateway/run.py:938` | `approval.reason_label` | `Reason: {description}` | `原因：{description}` |
| `gateway/run.py:939` | `gateway.approval_fallback.choices_join` | `{choices_head}, or {choices_tail}.` | `{choices_head}，或 {choices_tail}。` |
| `gateway/run.py:944` | `gateway.approval_fallback.body` | `{heading}
```
{cmd_preview}
```
{reason}

{choices}` | `{heading}
```
{cmd_preview}
```
{reason}

{choices}` |
| `gateway/run.py:955` | `gateway.model.provider_auth_failed` | `⚠️ Provider authentication failed. Check the configured credentials; raw provider details are in the gateway logs.` | `⚠️ 提供方认证失败。请检查配置的凭据；原始提供方详情见网关日志。` |
| `gateway/run.py:957` | `gateway.model.provider_policy_rejected` | `⚠️ The model provider rejected the request. I kept the raw provider error out of chat; check gateway logs for details or try rephrasing.` | `⚠️ 模型提供方拒绝了请求。原始提供方错误已保留在网关日志中，未回显到聊天 — 请查看日志了解详情或尝试重新表述。` |
| `gateway/run.py:959` | `gateway.model.rate_limited` | `⏱️ The model provider is rate-limiting requests. Please wait a moment and try again.` | `⏱️ 模型提供方正在限制请求速率。请稍后再试。` |
| `gateway/run.py:965` | `gateway.model.provider_failed_after_retries` | `⚠️ The model provider failed after retries. I kept raw provider details out of chat; check gateway logs for diagnostics.` | `⚠️ 模型提供方在重试后仍然失败。原始提供方详情已保留在网关日志中，未回显到聊天 — 请查看日志进行诊断。` |
| `gateway/run.py:4104` | `gateway.skill_disabled` | `The **{skill}** skill is installed but disabled. Enable it with: `hermes skills config`` | `**{skill}** 技能已安装但已禁用。 使用 `hermes skills config` 启用。` |
| `gateway/run.py:4122` | `gateway.skill_not_installed` | `The **{skill}** skill is available but not installed. Install it with: `hermes skills install {path}`` | `**{skill}** 技能可用但未安装。 使用 `hermes skills install {path}` 安装。` |
| `gateway/run.py:4565` | `gateway.model.context_too_large` | `⚠️ Session too large for the model's context window.
Use /compact to compress the conversation, or /reset to start fresh.` | `⚠️ 会话超出模型的上下文窗口。
使用 /compact 压缩对话，或 /reset 重新开始。` |
| `gateway/run.py:4566` | `gateway.model.request_failed` | `The request failed: {error}
Try again or use /reset to start a fresh session.` | `请求失败：{error}
请重试或使用 /reset 开始新的会话。` |
| `gateway/run.py:4579` | `gateway.interrupted_before_processing` | `⚠️ Your message was interrupted before processing started (likely by a recent /stop). Please send it again.` | `⚠️ 你的消息在开始处理前被中断了（多半是因为最近执行了 /stop）。请重新发送。` |
| `gateway/run.py:4586` | `gateway.processing_stopped` | `⚠️ Processing stopped: {error}. Try again.` | `⚠️ 处理已停止：{error}。请重试。` |
| `gateway/run.py:4587` | `gateway.model.no_response_generated` | `⚠️ Processing completed but no response was generated. This may be a transient error — try sending your message again.` | `⚠️ 处理已完成但未生成回复。这可能是暂时性错误 — 请重新发送你的消息。` |
| `gateway/run.py:4600` | `gateway.model.not_processed_prev_turn` | `⚠️ Your message wasn't processed (the previous turn was still being cleaned up). Please send it again.` | `⚠️ 你的消息未被处理（上一轮仍在清理中）。请重新发送。` |
| `gateway/run.py:6043` | `gateway.model.provider_auth_failed_detail` | `⚠️ Provider authentication failed: {error}` | `⚠️ 提供方认证失败：{error}` |
| `gateway/run.py:6803` | `gateway.clarify_timeout_notice` | `⏳ No response received within {minutes} minutes; the current operation has stopped. Send me a message if you need anything.` | `⏳ 未在 {minutes} 分钟内收到回复，已停止当前操作。需要的话再发消息给我。` |
| `gateway/run.py:8759` | `gateway.telegram_topic_lobby` | `This main chat is reserved for system commands.

To start a new Hermes chat, open the All Messages topic at the top of this bot interface and send any message there. Telegram will create a new topic for that message; each topic works as an independent Hermes session.` | `此主聊天专用于系统命令。

要开始新的 Hermes 聊天，请打开此机器人界面顶部的「所有消息」话题，在其中发送任意消息。Telegram 会为该消息创建新话题；每个话题都是独立的 Hermes 会话。` |
| `gateway/run.py:8762` | `gateway.telegram_topic_new` | `To start a new parallel Hermes chat, open the All Messages topic at the top of this bot interface and send a message there. Telegram will create a new topic for it.

Each topic is an independent Hermes session. Use /new inside an existing topic only if you want to replace that topic's current session.` | `要开始新的并行 Hermes 聊天，请打开此机器人界面顶部的「所有消息」话题，在其中发送消息。Telegram 会为其创建新话题。

每个话题都是独立的 Hermes 会话。仅在现有话题内使用 /new 替换该话题的当前会话。` |
| `gateway/run.py:8767` | `gateway.telegram_topic_header` | `Started a new Hermes session in this topic.

Tip: for parallel work, open All Messages and send a message there to create a separate topic instead of using /new here. /new replaces the session attached to the current topic.` | `已在此话题中开始新的 Hermes 会话。

提示：如需并行工作，请打开「所有消息」并发送消息来创建单独的话题，而非在此使用 /new。/new 会替换当前话题关联的会话。` |
| `gateway/run.py:11527` | `gateway.busy_steer_ack` | `⏩ Steered into current run{status_detail}. Your message arrives after the next tool call.` | `⏩ 已导向当前运行{status_detail}。你的消息将在下一次工具调用后送达。` |
| `gateway/run.py:11529` | `gateway.busy_redirect_ack` | `↪ Redirected current run{status_detail}. I'll adjust using your correction.` | `↪ 已重定向当前运行{status_detail}。我会根据你的修正进行调整。` |
| `gateway/run.py:11534` | `gateway.busy_subagent_queued` | `⏳ Subagent working{status_detail} — your message is queued for when it finishes (use /stop to cancel everything).` | `⏳ 子代理运行中{status_detail} — 你的消息已排队等待完成（使用 /stop 取消所有操作）。` |
| `gateway/run.py:11539` | `gateway.busy_compress_queued` | `⏳ Compressing context{status_detail} — your message is queued for when it finishes (use /stop to cancel everything).` | `⏳ 正在压缩上下文{status_detail} — 你的消息已排队，待压缩完成后进入下一轮（使用 /stop 取消所有操作）。` |
| `gateway/run.py:11541` | `gateway.busy_queue_ack` | `⏳ Queued for the next turn{status_detail}. I'll respond once the current task finishes.` | `⏳ 已排队到下一轮{status_detail}。当前任务完成后我会回复你。` |
| `gateway/run.py:11543` | `gateway.busy_interrupt_ack` | `⚡ Interrupting current task{status_detail}. I'll respond to your message shortly.` | `⚡ 正在中断当前任务{status_detail}。稍后我会回复你的消息。` |
| `gateway/run.py:18112` | `gateway.busy_cmd_blocked` | `⏳ Agent is running — `/{cmd}` can't run mid-turn. Wait for the current response or `/stop` first.` | `⏳ Agent 运行中 — `/{cmd}` 无法在当前轮次执行。请等待响应结束或先执行 `/stop`。` |
| `gateway/run.py:18202` | `gateway.queue_usage` | `Usage: /queue <prompt>` | `用法：/queue <提示>` |
| `gateway/run.py:18228` | `gateway.queue_queued` | `Queued for the next turn.` | `已排队到下一轮。` |
| `gateway/run.py:18229` | `gateway.queue_queued_with_depth` | `Queued for the next turn. ({depth} queued)` | `已排队到下一轮。（{depth} 条排队中）` |
| `gateway/run.py:18239` | `gateway.steer_usage` | `Usage: /steer <prompt>` | `用法：/steer <提示>` |
| `gateway/run.py:18255` | `gateway.busy_agent_starting` | `Agent still starting — /steer queued for the next turn.` | `Agent 正在启动 — /steer 已排队到下一轮。` |
| `gateway/run.py:18261` | `gateway.steer_failed` | `⚠️ Steer failed: {error}` | `⚠️ 导向失败：{error}` |
| `gateway/run.py:18264` | `gateway.steer_queued` | `⏩ Steer queued — arrives after the next tool call: '{preview}'` | `⏩ 导向已排队 — 将在下一次工具调用后送达：'{preview}'` |
| `gateway/run.py:18265` | `gateway.steer_empty` | `Steer rejected (empty payload).` | `导向被拒绝（内容为空）。` |
| `gateway/run.py:18278` | `gateway.busy_no_active_agent` | `No active agent — /steer queued for the next turn.` | `没有活跃的 Agent — /steer 已排队到下一轮。` |
| `gateway/run.py:18299` | `gateway.busy_goal_blocked` | `Agent is running — use /goal status / pause / clear / wait mid-run, or /stop before setting a new goal.` | `Agent 运行中 — 请使用 /goal status / pause / clear / wait 进行中间操作，或先 /stop 再设置新目标。` |
| `gateway/run.py:18503` | `gateway.pairing.unrecognized` | `Hi~ I don't recognize you yet!

Here's your pairing code: `{code}`

Ask the bot owner to run:
`hermes {profile_arg}pairing approve {platform_name} {code}`` | `嗨~ 我还不认识你！

你的配对码：`{code}`

请让机器人所有者运行：
`hermes {profile_arg}pairing approve {platform_name} {code}`` |
| `gateway/run.py:18515` | `gateway.pairing.rate_limited` | `Too many pairing requests right now~ Please try again later!` | `配对请求过多~ 请稍后再试！` |
| `gateway/run.py:18642` | `gateway.update_send_failed` | `✗ Failed to send response to update process: {error}` | `✗ 发送响应到更新进程失败：{error}` |
| `gateway/run.py:18645` | `gateway.update_sent` | `✓ Sent `{label}` to the update process.` | `✓ 已将 `{label}` 发送到更新进程。` |
| `gateway/run.py:19017` | `gateway.busy_cmd_blocked` | `⏳ Agent is running — `/{cmd}` can't run mid-turn. Wait for the current response or `/stop` first.` | `⏳ Agent 运行中 — `/{cmd}` 无法在当前轮次执行。请等待响应结束或先执行 `/stop`。` |
| `gateway/run.py:19067` | `gateway.force_stop_pending` | `⚡ Force-stopped. The agent was still starting — session unlocked.` | `⚡ 已强制停止。代理尚未启动完成 — 会话已解锁。` |
| `gateway/run.py:19237` | `gateway.chained_commands_executed` | `Commands executed.` | `命令已执行。` |
| `gateway/run.py:19323` | `gateway.hook_blocked` | `Command `/{command}` was blocked by a hook.` | `命令 `/{command}` 被 hook 拦截。` |
| `gateway/run.py:19401` | `gateway.learn_ack_described` | `Learning a skill from what you described…` | `正在根据你的描述学习技能…` |
| `gateway/run.py:19403` | `gateway.learn_ack_conversation` | `Learning a skill from this conversation…` | `正在根据本次对话学习技能…` |
| `gateway/run.py:19416` | `gateway.learn_failed` | `Could not start /learn — please try again.` | `无法启动 /learn — 请重试。` |
| `gateway/run.py:19458` | `gateway.init_failed` | `Could not start /init — please try again.` | `无法启动 /init — 请重试。` |
| `gateway/run.py:19460` | `gateway.init_ack_update` | `Updating AGENTS.md from a project scan…` | `正在根据项目扫描更新 AGENTS.md…` |
| `gateway/run.py:19462` | `gateway.init_ack_generate` | `Generating AGENTS.md from a project scan…` | `正在根据项目扫描生成 AGENTS.md…` |
| `gateway/run.py:19597` | `gateway.queue_usage` | `Usage: /queue <prompt>` | `用法：/queue <提示>` |
| `gateway/run.py:19609` | `gateway.steer_usage_no_agent` | `Usage: /steer <prompt>  (no agent is running; sending as a normal message)` | `用法：/steer <提示>（当前没有运行中的 Agent；将作为普通消息发送）` |
| `gateway/run.py:19663` | `gateway.moa_prepare_failed` | `Failed to prepare MoA turn.` | `准备 MoA 回合失败。` |
| `gateway/run.py:19715` | `gateway.quick_command_no_output` | `Command returned no output.` | `命令没有输出。` |
| `gateway/run.py:19717` | `gateway.quick_command_timeout` | `Quick command timed out (30s).` | `快捷命令已超时（30 秒）。` |
| `gateway/run.py:19719` | `gateway.quick_command_error` | `Quick command error: {error}` | `快捷命令出错：{error}` |
| `gateway/run.py:19721` | `gateway.quick_command_no_command` | `Quick command '/{command}' has no command defined.` | `快捷命令 '/{command}' 未定义 command。` |
| `gateway/run.py:19732` | `gateway.quick_command_no_target` | `Quick command '/{command}' has no target defined.` | `快捷命令 '/{command}' 未定义 target。` |
| `gateway/run.py:19734` | `gateway.quick_command_unsupported_type` | `Quick command '/{command}' has unsupported type (supported: 'exec', 'alias').` | `快捷命令 '/{command}' 类型不受支持（支持：'exec'、'alias'）。` |
| `gateway/run.py:19829` | `gateway.skill_disabled_for_platform` | `The **{skill}** skill is disabled for {platform}. Enable it with: `hermes skills config`` | `**{skill}** 技能在 {platform} 上已禁用。 使用 `hermes skills config` 启用。` |
| `gateway/run.py:19861` | `gateway.skills_disabled_stacked` | `The **{skills}** skill(s) in this stacked invocation are disabled for {platform}.
Enable them with: `hermes skills config`` | `此叠加调用中的 **{skills}** 技能在 {platform} 上已禁用。
使用 `hermes skills config` 启用。` |
| `gateway/run.py:19877` | `gateway.stacked_skills_load_failed` | `Failed to load stacked skills for /{command}.` | `无法为 /{command} 加载叠加技能。` |
| `gateway/run.py:19909` | `gateway.unknown_command` | `Unknown command `/{command}`. Type /commands to see what's available, or resend without the leading slash to send as a regular message.` | `未知命令 `/{command}`。输入 /commands 查看可用命令，或去掉前导斜杠重新发送以作为普通消息。` |
| `gateway/run.py:19985` | `gateway.turn_lease.gateway_timeout` | `⏳ Another turn is still running on this session. To protect the transcript, this message was not processed. Wait for the active turn to finish, then resend it.` | `⏳ 此会话上仍有另一轮对话在运行。为保护会话记录，你的消息未被处理。请等待当前轮次结束后重新发送。` |
| `gateway/run.py:21059` | `gateway.session_reset_reason_suspended` | `previous session was stopped or interrupted` | `上一个会话已被停止或中断` |
| `gateway/run.py:21061` | `gateway.session_reset_reason_resume_expired` | `gateway restart recovery timed out` | `网关重启恢复超时` |
| `gateway/run.py:21063` | `gateway.session_reset_reason_daily` | `daily schedule at {hour}:00` | `每日定时重置（{hour}:00）` |
| `gateway/run.py:21068` | `gateway.session_reset_reason_idle` | `inactive for {duration}` | `已闲置 {duration}` |
| `gateway/run.py:21069` | `gateway.session_reset_notice` | `◐ Session automatically reset ({reason}). Conversation history cleared.
Use /resume to browse and restore a previous session.
Adjust reset timing in config.yaml under session_reset.` | `◐ 会话已自动重置（{reason}）。对话历史已清除。
使用 /resume 浏览并恢复之前的会话。
可在 config.yaml 的 session_reset 下调整重置时间。` |
| `gateway/run.py:22296` | `gateway.model.compression_aborted` | `⚠️ Context compression aborted ({error}). No messages were dropped — conversation is unchanged. Run /compress to retry, /reset for a clean session, or check your auxiliary.compression model configuration.` | `⚠️ 上下文压缩已中止（{error}）。没有消息被丢弃 — 对话保持不变。运行 /compress 重试，/reset 开始新会话，或检查 auxiliary.compression 模型配置。` |
| `gateway/run.py:22315` | `gateway.aux_model_fallback` | `ℹ️ Configured compression model `{model}` failed ({error}). Recovered using your main model — context is intact — but you may want to check `auxiliary.compression.model` in config.yaml.` | `ℹ️ 配置的压缩模型 `{model}` 失败（{error}）。已使用主模型恢复 — 上下文完整 — 但建议检查 config.yaml 中的 `auxiliary.compression.model`。` |
| `gateway/run.py:22426` | `gateway.home_channel_notice` | `📬 No home channel is set for {platform}. A home channel is where Hermes delivers cron job results and cross-platform messages.

Type {sethome_cmd} to make this chat your home channel, or ignore to skip.` | `📬 {platform} 未设置主频道。主频道是 Hermes 发送定时任务结果和跨平台消息的地方。

输入 {sethome_cmd} 将此聊天设为主频道，或忽略跳过。` |
| `gateway/run.py:22616` | `gateway.model.empty_tool_response` | `⚠️ The model returned no response after processing tool results. This can happen with some models — try again or rephrase your question.` | `⚠️ 模型在处理工具结果后未返回响应。某些模型可能会出现这种情况 — 请重试或重新表述你的问题。` |
| `gateway/run.py:22956` | `gateway.session_auto_reset_exhausted` | `

🔄 Session auto-reset — the conversation exceeded the maximum context size and could not be compressed further. Your next message will start a fresh session.` | `

🔄 会话已自动重置 — 对话超出最大上下文且无法进一步压缩。你的下一条消息将开启新会话。` |
| `gateway/run.py:23284` | `gateway.agent_error_hint_auth` | ` Check your API key or run `claude /login` to refresh OAuth credentials.` | `请检查 API 密钥，或运行 `claude /login` 刷新 OAuth 凭证。` |
| `gateway/run.py:23286` | `gateway.agent_error_hint_billing` | ` Your API balance or quota is exhausted. Check your provider dashboard.` | `API 余额或额度已用尽，请检查服务商控制台。` |
| `gateway/run.py:23303` | `gateway.agent_error_hint_usage_limit_resets` | ` Your plan's usage limit has been reached. It resets in ~{hours}h.` | `当前套餐用量已达上限，约 {hours} 小时后重置。` |
| `gateway/run.py:23308` | `gateway.agent_error_hint_usage_limit` | ` Your plan's usage limit has been reached. Please wait until it resets.` | `当前套餐用量已达上限，请等待额度重置。` |
| `gateway/run.py:23310` | `gateway.agent_error_hint_rate_limited` | ` You are being rate-limited. Please wait a moment and try again.` | `当前触发了速率限制，请稍后再试。` |
| `gateway/run.py:23312` | `gateway.agent_error_hint_overloaded` | ` The API is temporarily overloaded. Please try again shortly.` | `API 暂时过载，请稍后重试。` |
| `gateway/run.py:23318` | `gateway.model.context_too_large` | `⚠️ Session too large for the model's context window.
Use /compact to compress the conversation, or /reset to start fresh.` | `⚠️ 会话超出模型的上下文窗口。
使用 /compact 压缩对话，或 /reset 重新开始。` |
| `gateway/run.py:23320` | `gateway.agent_error_hint_rejected` | ` The request was rejected by the API.` | `请求被 API 拒绝。` |
| `gateway/run.py:23321` | `gateway.agent_error` | `Sorry, I encountered an unexpected error.{status_hint}
Try again or use /reset to start a fresh session.` | `抱歉，遇到了意外错误。{status_hint}
请重试，或使用 /reset 开始新会话。` |
| `gateway/run.py:23362` | `gateway.model.ctx_source_config` | `config` | `配置` |
| `gateway/run.py:23364` | `gateway.model.ctx_source_default` | `default — set model.context_length in config to override` | `默认 — 在 config 中设置 model.context_length 可覆盖` |
| `gateway/run.py:23366` | `gateway.model.ctx_source_detected` | `detected` | `检测` |
| `gateway/run.py:23377` | `gateway.model.info_model` | `◆ Model: `{model}`` | `◆ 模型：`{model}`` |
| `gateway/run.py:23378` | `gateway.model.info_provider` | `◆ Provider: {provider}` | `◆ 提供方：{provider}` |
| `gateway/run.py:23379` | `gateway.model.info_context` | `◆ Context: {ctx} tokens ({source})` | `◆ 上下文：{ctx} tokens（{source}）` |
| `gateway/run.py:23384` | `gateway.model.info_endpoint` | `◆ Endpoint: {base_url}` | `◆ 端点：{base_url}` |
| `gateway/run.py:23422` | `gateway.admin_only_can_run` | `You can run: {commands}. Use /whoami for the full list.` | `你可运行：{commands}。使用 /whoami 查看完整列表。` |
| `gateway/run.py:23424` | `gateway.admin_only_none_enabled` | `No slash commands are enabled for non-admins on this platform. Ask an admin to add you to allow_admin_from or to set user_allowed_commands.` | `此平台未为非管理员启用任何斜杠命令。请让管理员将你加入 allow_admin_from，或设置 user_allowed_commands。` |
| `gateway/run.py:23425` | `gateway.admin_only` | `⛔ /{command} is admin-only here. {detail}` | `⛔ 此处 /{command} 仅管理员可用。{detail}` |
| `gateway/run.py:23592` | `gateway.suggestions_failed` | `Suggestions command failed: {error}` | `建议命令失败：{error}` |
| `gateway/run.py:23627` | `gateway.blueprint_failed` | `Cron blueprint command failed: {error}` | `定时任务蓝图命令失败：{error}` |
| `gateway/run.py:24205` | `gateway.voice_not_supported` | `Voice channels are not supported on this platform.` | `本平台不支持语音频道。` |
| `gateway/run.py:24209` | `gateway.voice_discord_only` | `This command only works in a Discord server.` | `此命令仅在 Discord 服务器中可用。` |
| `gateway/run.py:24215` | `gateway.voice_not_in_channel` | `You need to be in a voice channel first.` | `你需要先加入一个语音频道。` |
| `gateway/run.py:24237` | `gateway.voice_deps_missing` | `Voice dependencies are missing (PyNaCl / davey). Install with: `{command}`` | `缺少语音依赖（PyNaCl / davey）。请使用以下命令安装：`{command}`` |
| `gateway/run.py:24238` | `gateway.voice_join_failed_with_error` | `Failed to join voice channel: {error}` | `加入语音频道失败：{error}` |
| `gateway/run.py:24247` | `gateway.voice_joined` | `Joined voice channel **{channel}**.
I'll speak my replies and listen to you. Use /voice leave to disconnect.` | `已加入语音频道 **{channel}**。
我会用语音回复并聆听你。使用 /voice leave 断开连接。` |
| `gateway/run.py:24250` | `gateway.voice_join_failed` | `Failed to join voice channel. Check bot permissions (Connect + Speak).` | `加入语音频道失败。请检查机器人权限（连接 + 说话）。` |
| `gateway/run.py:24258` | `gateway.voice_not_connected` | `Not in a voice channel.` | `当前不在语音频道中。` |
| `gateway/run.py:24261` | `gateway.voice_not_connected` | `Not in a voice channel.` | `当前不在语音频道中。` |
| `gateway/run.py:24273` | `gateway.voice_left` | `Left voice channel.` | `已离开语音频道。` |
| `gateway/run.py:24861` | `gateway.background_task_failed` | `❌ Background task {task_id} failed: {error}` | `❌ 后台任务 {task_id} 失败：{error}` |
| `gateway/run.py:24958` | `gateway.background_task_error_prefix` | `Error: {error}` | `错误：{error}` |
| `gateway/run.py:24984` | `gateway.background_task_complete` | `✅ Background task complete
Prompt: "{preview}"

{response}` | `✅ 后台任务完成
提示："{preview}"

{response}` |
| `gateway/run.py:24994` | `gateway.background_task_complete` | `✅ Background task complete
Prompt: "{preview}"

{response}` | `✅ 后台任务完成
提示："{preview}"

{response}` |
| `gateway/run.py:24997` | `gateway.background_task_no_response` | `(No response generated)` | `（未生成响应）` |
| `gateway/run.py:25056` | `gateway.background_task_complete` | `✅ Background task complete
Prompt: "{preview}"

{response}` | `✅ 后台任务完成
提示："{preview}"

{response}` |
| `gateway/run.py:25059` | `gateway.background_task_no_response` | `(No response generated)` | `（未生成响应）` |
| `gateway/run.py:25069` | `gateway.background_task_failed` | `❌ Background task {task_id} failed: {error}` | `❌ 后台任务 {task_id} 失败：{error}` |
| `gateway/run.py:25176` | `gateway.telegram_topic_default` | `Hermes Chat` | `Hermes 聊天` |
| `gateway/run.py:25291` | `gateway.telegram_topic_default` | `Hermes Chat` | `Hermes 聊天` |
| `gateway/run.py:25642` | `gateway.chat_id_unknown` | `Could not determine chat ID.` | `无法确定聊天 ID。` |
| `gateway/run.py:25652` | `gateway.topic_mode_disabled` | `Multi-session topic mode is not currently enabled for this chat.` | `此聊天当前未启用多会话 topic 模式。` |
| `gateway/run.py:25657` | `gateway.topic_disable_failed` | `Failed to disable topic mode: {error}` | `关闭 topic 模式失败：{error}` |
| `gateway/run.py:25664` | `gateway.topic_disabled` | `Multi-session topic mode is now OFF for this chat.

Existing topics in Telegram aren't removed — they'll just stop being gated as independent sessions. The root DM works as a normal Hermes chat again. Run /topic to re-enable later.` | `此聊天的多会话 topic 模式已关闭。

Telegram 中现有的 topic 不会被移除——只是不再作为独立会话进行隔离。根私信恢复为普通 Hermes 聊天。如需重新启用，请发送 /topic。` |
| `gateway/run.py:25690` | `gateway.default_chat_name` | `Hermes Chat` | `Hermes Chat` |
| `gateway/run.py:25718` | `gateway.session_not_found` | `Session not found: {name}` | `未找到会话：{name}` |
| `gateway/run.py:25722` | `gateway.session_not_found` | `Session not found: {name}` | `未找到会话：{name}` |
| `gateway/run.py:25724` | `gateway.topic_not_telegram_session` | `That session is not a Telegram session and cannot be restored into this topic.` | `该会话不是 Telegram 会话，无法恢复到当前 topic。` |
| `gateway/run.py:25726` | `gateway.topic_wrong_user` | `That session does not belong to this Telegram user.` | `该会话不属于此 Telegram 用户。` |
| `gateway/run.py:25735` | `gateway.topic_already_linked` | `That session is already linked to another Telegram topic.` | `该会话已关联到另一个 Telegram topic。` |
| `gateway/run.py:25749` | `gateway.topic_already_linked` | `That session is already linked to another Telegram topic.` | `该会话已关联到另一个 Telegram topic。` |
| `gateway/run.py:25765` | `gateway.session_restored` | `Session restored: {title}` | `会话已恢复：{title}` |
| `gateway/run.py:25767` | `gateway.session_restored_last` | `

Last Hermes message:
{last_assistant}` | `

Hermes 上一条消息：
{last_assistant}` |
| `gateway/run.py:25808` | `gateway.reload_mcp.reconnected` | `♻️ Reconnected: {names}` | `♻️ 已重新连接：{names}` |
| `gateway/run.py:25810` | `gateway.reload_mcp.added` | `➕ Added: {names}` | `➕ 已添加：{names}` |
| `gateway/run.py:25812` | `gateway.reload_mcp.removed` | `➖ Removed: {names}` | `➖ 已移除：{names}` |
| `gateway/run.py:25943` | `gateway.destructive_slash_confirm.cancelled` | `🟡 /{command} cancelled. Conversation unchanged.` | `🟡 /{command} 已取消。会话不变。` |
| `gateway/run.py:25972` | `gateway.destructive_slash_confirm.always_note` | `

ℹ️ Future /clear, /new, /reset, and /undo will run without confirmation. Re-enable via `approvals.destructive_slash_confirm: true` in config.yaml.` | `

ℹ️ 今后 /clear、/new、/reset 和 /undo 将直接执行，不再询问。如需重新启用，请在 config.yaml 中设置 `approvals.destructive_slash_confirm: true`。` |
| `gateway/run.py:25978` | `gateway.destructive_slash_confirm.always_note_persist_failed` | `

⚠️ Could not save that preference (config.yaml is not writable), so /clear, /new, /reset, and /undo will ask again next time. To silence it permanently, set `approvals.destructive_slash_confirm: false` in config.yaml.` | `

⚠️ 无法保存该偏好（config.yaml 不可写），因此 /clear、/new、/reset 和 /undo 下次仍会询问。如需永久关闭，请在 config.yaml 中设置 `approvals.destructive_slash_confirm: false`。` |
| `gateway/run.py:25989` | `gateway.destructive_slash_confirm.prompt` | `⚠️ **Confirm /{command}**

{detail}

Choose:
• **Approve Once** — proceed this time only
• **Always Approve** — proceed and silence this prompt permanently
• **Cancel** — keep current conversation

_Text fallback: reply `{_p}approve`, `{_p}always`, or `{_p}cancel`._` | `⚠️ **确认 /{command}**

{detail}

请选择：
• **批准一次** — 仅本次执行
• **始终批准** — 立即执行并永久静默此提示
• **取消** — 保持当前会话不变

_文本备用：回复 `{_p}approve`、`{_p}always` 或 `{_p}cancel`。_` |
| `gateway/run.py:26367` | `gateway.update.finished` | `✅ Hermes update finished.` | `✅ Hermes 更新完成。` |
| `gateway/run.py:26373` | `gateway.update.failed_exit` | `❌ Hermes update failed (exit code {exit_code}).` | `❌ Hermes 更新失败（退出码 {exit_code}）。` |
| `gateway/run.py:26439` | `gateway.update.default_hint` | ` (default: {default})` | `（默认：{default}）` |
| `gateway/run.py:26446` | `gateway.update.needs_input` | `⚕ **Update needs your input:**

{prompt}{default_hint}

Reply `{command_prefix}approve` (yes) or `{command_prefix}deny` (no), or type your answer directly.` | `⚕ **更新需要你的输入：**

{prompt}{default_hint}

回复 `{command_prefix}approve`（是）或 `{command_prefix}deny`（否），或直接输入你的答案。` |
| `gateway/run.py:26477` | `gateway.update.timed_out` | `❌ Hermes update timed out after 30 minutes.` | `❌ Hermes 更新在 30 分钟后超时。` |
| `gateway/run.py:26580` | `gateway.update.finished_with_output` | `✅ Hermes update finished.

```
{output}
```` | `✅ Hermes 更新完成。

```
{output}
```` |
| `gateway/run.py:26582` | `gateway.update.failed_with_output` | `❌ Hermes update failed.

```
{output}
```` | `❌ Hermes 更新失败。

```
{output}
```` |
| `gateway/run.py:26584` | `gateway.update.finished_ok` | `✅ Hermes update finished successfully.` | `✅ Hermes 更新已成功完成。` |
| `gateway/run.py:26586` | `gateway.update.failed_details` | `❌ Hermes update failed. Check the gateway logs or run `hermes update` manually for details.` | `❌ Hermes 更新失败。请查看网关日志，或手动运行 `hermes update` 查看详情。` |
| `gateway/run.py:28493` | `gateway.bg_process_finished` | `[Background process {session_id} finished with exit code {exit_code}~ Here's the final output:
{output}]` | `[后台进程 {session_id} 已完成，退出码 {exit_code}~ 最终输出：
{output}]` |
| `gateway/run.py:28524` | `gateway.bg_process_running` | `[Background process {session_id} is still running~ New output:
{output}]` | `[后台进程 {session_id} 仍在运行~ 新输出：
{output}]` |
| `gateway/run.py:30148` | `gateway.proxy.aiohttp_missing` | `⚠️ Proxy mode requires aiohttp. Install with: pip install aiohttp` | `⚠️ 代理模式需要 aiohttp。请安装：pip install aiohttp` |
| `gateway/run.py:30157` | `gateway.proxy.url_not_configured` | `⚠️ Proxy URL not configured (GATEWAY_PROXY_URL or gateway.proxy_url)` | `⚠️ 未配置代理 URL（GATEWAY_PROXY_URL 或 gateway.proxy_url）` |
| `gateway/run.py:30295` | `gateway.proxy.http_error` | `⚠️ Proxy error ({status}): {error}` | `⚠️ 代理错误（{status}）：{error}` |
| `gateway/run.py:30359` | `gateway.proxy.connection_error` | `⚠️ Proxy connection error: {error}` | `⚠️ 代理连接错误：{error}` |
| `gateway/run.py:30399` | `gateway.no_proxy_response` | `(No response from remote agent)` | `（远程代理无响应）` |
| `gateway/run.py:31466` | `gateway.still_working` | `⏳ Working — {elapsed} min{status_detail}` | `⏳ 工作中 — {elapsed} 分钟{status_detail}` |
| `gateway/run.py:31729` | `gateway.no_activity_warning` | `⚠️ No activity for {elapsed} min. If the agent does not respond soon, it will be timed out in {remaining} min. You can continue waiting or use /reset.` | `⚠️ 已 {elapsed} 分钟无活动。如果代理未在 {remaining} 分钟内响应，将会超时。可继续等待或使用 /reset。` |
| `gateway/run.py:31823` | `gateway.agent_timeout_detail_tool` | `The agent appears stuck on tool `{cur_tool}` ({secs_since}s since last activity, iteration {iter_n}/{iter_max}).` | `代理似乎卡在工具 `{cur_tool}` 上（距离上次活动 {secs_since} 秒，迭代 {iter_n}/{iter_max}）。` |
| `gateway/run.py:31831` | `gateway.agent_timeout_detail_activity` | `Last activity: {last_desc} ({secs_since}s ago, iteration {iter_n}/{iter_max}). The agent may have been waiting on an API response.` | `上次活动：{last_desc}（{secs_since} 秒前，迭代 {iter_n}/{iter_max}）。代理可能一直在等待 API 响应。` |
| `gateway/run.py:31838` | `gateway.agent_timeout` | `⏱️ Agent inactive for {timeout_mins} min — no tool calls or API responses.
{detail}
To increase the limit, set agent.gateway_timeout in config.yaml (value in seconds, 0 = no limit) and restart the gateway.
Try again, or use /reset to start fresh.` | `⏱️ 代理已不活跃 {timeout_mins} 分钟 — 没有工具调用或 API 响应。
{detail}
如需提高限制，请在 config.yaml 中设置 agent.gateway_timeout（单位为秒，0 = 无限制）并重启网关。
请重试，或使用 /reset 重新开始。` |
| `gateway/session_stall.py:68` | `gateway.session_stall` | `⚠️ Agent session appears stalled (last activity {mins} min ago). Try /new to reset.` | `⚠️ 代理会话似乎已停滞（上次活动在 {mins} 分钟前）。请尝试 /new 重置。` |
| `gateway/slash_commands.py:2536` | `gateway.model.expensive_warning_cancelled` | `🟡 Model switch cancelled. Current model unchanged ({model}).` | `🟡 已取消模型切换。当前模型未更改（{model}）。` |
| `gateway/slash_commands.py:2549` | `gateway.model.expensive_warning_title` | `Expensive Model Warning` | `高费用模型警告` |
| `gateway/slash_commands.py:2550` | `gateway.model.expensive_warning_body` | `⚠️ **Expensive Model Warning**

{warning}

_Text fallback: reply `{prefix}approve` to switch or `{prefix}cancel` to keep the current model._` | `⚠️ **高费用模型警告**

{warning}

_文本备用：回复 `{prefix}approve` 以切换，或 `{prefix}cancel` 以保持当前模型。_` |
| `gateway/slash_commands.py:2783` | `gateway.goal.no_goal_set` | `No goal set.` | `未设置目标。` |
| `gateway/slash_commands.py:2791` | `gateway.goal.paused` | `⏸ Goal paused: {goal}` | `⏸ 目标已暂停：{goal}` |
| `gateway/slash_commands.py:2796` | `gateway.goal.no_resume` | `No goal to resume.` | `没有可恢复的目标。` |
| `gateway/slash_commands.py:2818` | `gateway.goal.resumed` | `▶ Goal resumed: {goal}
Continuing now — I'll take the next step right away.` | `▶ 目标已恢复：{goal}
立即继续 — 我马上进行下一步。` |
| `gateway/slash_commands.py:2830` | `gateway.goal_cleared` | `✓ Goal cleared.` | `✓ 目标已清除。` |
| `gateway/slash_commands.py:2830` | `gateway.no_active_goal` | `No active goal.` | `当前没有活跃的目标。` |
| `gateway/slash_commands.py:2836` | `gateway.goal_usage_wait` | `Usage: /goal wait <pid> [reason]` | `用法：/goal wait <pid> [reason]` |
| `gateway/slash_commands.py:2854` | `gateway.goal_no_wait_barrier` | `No wait barrier set.` | `没有设置等待屏障。` |
| `gateway/slash_commands.py:2894` | `gateway.goal_usage_draft` | `Usage: /goal draft <objective in plain language>` | `用法：/goal draft <用自然语言描述的目标>` |
| `gateway/slash_commands.py:2921` | `gateway.goal.invalid` | `Invalid goal: {error}` | `无效目标：{error}` |
| `gateway/slash_commands.py:2940` | `gateway.goal.set` | `⊙ Goal set ({budget}-turn budget): {goal}
I'll keep working until the goal is done, you pause/clear it, or the budget is exhausted.
Controls: /goal status · /goal pause · /goal resume · /goal clear` | `⊙ 目标已设置（{budget} 轮预算）：{goal}
我将持续工作直到目标完成、你暂停/清除它，或预算耗尽。
控制命令：/goal status · /goal pause · /goal resume · /goal clear` |
| `gateway/slash_commands.py:3134` | `gateway.goal_no_active` | `No active goal. Set one with /goal <text>.` | `当前没有活跃的目标。请先使用 /goal <文本> 设置一个。` |
| `gateway/slash_commands.py:3146` | `gateway.subgoal_usage_remove` | `Usage: /subgoal remove <n>` | `用法：/subgoal remove <n>` |
| `gateway/slash_commands.py:3164` | `gateway.subgoal_no_subgoals` | `No subgoals to clear.` | `没有可清除的子目标。` |
| `gateway/slash_commands.py:3381` | `gateway.voice.enabled_voice_only` | `Voice mode enabled.
I'll reply with voice when you send voice messages.
Use /voice tts to get voice replies for all messages.` | `语音模式已启用。
当你发送语音消息时，我会用语音回复。
使用 /voice tts 让所有消息都收到语音回复。` |
| `gateway/slash_commands.py:3387` | `gateway.voice.disabled_text` | `Voice mode disabled. Text-only replies.` | `语音模式已禁用。仅文本回复。` |
| `gateway/slash_commands.py:3393` | `gateway.voice.tts_enabled` | `Auto-TTS enabled.
All replies will include a voice message.` | `自动 TTS 已启用。
所有回复都将包含一条语音消息。` |
| `gateway/slash_commands.py:3401` | `gateway.voice.label_off` | `Off (text only)` | `关闭（仅文本）` |
| `gateway/slash_commands.py:3402` | `gateway.voice.label_voice_only` | `On (voice reply to voice messages)` | `开启（仅对语音消息进行语音回复）` |
| `gateway/slash_commands.py:3403` | `gateway.voice.label_all` | `TTS (voice reply to all messages)` | `TTS（对所有消息进行语音回复）` |
| `gateway/slash_commands.py:3429` | `gateway.voice.enabled_short` | `Voice mode enabled.` | `语音模式已启用。` |
| `gateway/slash_commands.py:3435` | `gateway.voice.disabled_short` | `Voice mode disabled.` | `语音模式已禁用。` |
| `gateway/slash_commands.py:3508` | `gateway.rollback.kept_user_edits` | `↷ Kept your hand-edits: {files}
Use /rollback <N> --all to restore those too.` | `↷ 已保留您的手动编辑：{files}
如需一并恢复这些文件，请使用 /rollback <N> --all。` |
| `gateway/slash_commands.py:3516` | `gateway.rollback.kept_oversize` | `↷ Kept (too large for checkpoints, no stored copy to revert to): {files}` | `↷ 已保留（文件过大无法纳入检查点，没有可恢复的存储副本）：{files}` |
| `gateway/slash_commands.py:3524` | `gateway.rollback.failed_deletes` | `⚠️ Could not remove (left in place): {files}` | `⚠️ 无法移除（保留原文件）：{files}` |
| `gateway/slash_commands.py:3819` | `gateway.reasoning.display_set_on` | `🧠 ✓ Reasoning display: **ON**
Model thinking will be shown before each response on **{platform}**.` | `🧠 ✓ 推理显示：**开启**
在 **{platform}** 上每次响应前将显示模型的思考过程。` |
| `gateway/slash_commands.py:3825` | `gateway.reasoning.display_set_off` | `🧠 ✓ Reasoning display: **OFF** for **{platform}**` | `🧠 ✓ **{platform}** 上的推理显示：**关闭**` |
| `gateway/slash_commands.py:3874` | `gateway.reasoning.choice_reset` | `reset — clear session override` | `reset — 清除会话覆盖` |
| `gateway/slash_commands.py:3875` | `gateway.reasoning.choice_show` | `show reasoning in replies` | `在回复中显示推理` |
| `gateway/slash_commands.py:3876` | `gateway.reasoning.choice_hide` | `hide reasoning from replies` | `在回复中隐藏推理` |
| `gateway/slash_commands.py:4142` | `gateway.fast.label_fast` | `FAST` | `FAST` |
| `gateway/slash_commands.py:4146` | `gateway.fast.label_normal` | `NORMAL` | `NORMAL` |
| `gateway/slash_commands.py:4181` | `gateway.fast.choice_fast` | `fast — Priority Processing on` | `fast — 开启优先处理` |
| `gateway/slash_commands.py:4186` | `gateway.fast.choice_normal` | `normal — standard processing` | `normal — 标准处理` |
| `gateway/slash_commands.py:4240` | `approval.yolo_auto_resolved` | `🔄 YOLO mode enabled — {count} pending approval(s) auto-resolved.` | `🔄 YOLO 模式已启用，{count} 条待审批命令已自动批准。` |
| `gateway/slash_commands.py:4262` | `approval.yolo_auto_resolved` | `🔄 YOLO mode enabled — {count} pending approval(s) auto-resolved.` | `🔄 YOLO 模式已启用，{count} 条待审批命令已自动批准。` |
| `gateway/slash_commands.py:4296` | `gateway.verbose.mode_off` | `⚙️ Tool progress: **OFF** — no tool activity shown.` | `⚙️ 工具进度：**OFF** — 不显示任何工具活动。` |
| `gateway/slash_commands.py:4297` | `gateway.verbose.mode_new` | `⚙️ Tool progress: **NEW** — shown when tool changes (preview length: `display.tool_preview_length`, default 40).` | `⚙️ 工具进度：**NEW** — 工具变化时显示（预览长度：`display.tool_preview_length`，默认 40）。` |
| `gateway/slash_commands.py:4298` | `gateway.verbose.mode_all` | `⚙️ Tool progress: **ALL** — every tool call shown (preview length: `display.tool_preview_length`, default 40).` | `⚙️ 工具进度：**ALL** — 显示每次工具调用（预览长度：`display.tool_preview_length`，默认 40）。` |
| `gateway/slash_commands.py:4299` | `gateway.verbose.mode_verbose` | `⚙️ Tool progress: **VERBOSE** — every tool call with full arguments.` | `⚙️ 工具进度：**VERBOSE** — 显示每次工具调用及完整参数。` |
| `gateway/slash_commands.py:4300` | `gateway.verbose.mode_log` | `⚙️ Tool progress: **LOG** — silent in chat; tool calls written to ~/.hermes/logs/tool_calls.log.` | `⚙️ 工具进度：**LOG** — 聊天中保持静默；工具调用写入 ~/.hermes/logs/tool_calls.log。` |
| `gateway/slash_commands.py:5040` | `gateway.topic.topics_disabled` | `Telegram topics are not enabled for this bot yet.

How to enable them:
1. Open @BotFather.
2. Choose your bot.
3. Open Bot Settings → Threads Settings.
4. Turn on Threaded Mode and make sure users are allowed to create new threads.

Then send /topic again.` | `此 bot 尚未启用 Telegram topics。

启用方法：
1. 打开 @BotFather。
2. 选择您的 bot。
3. 打开 Bot Settings → Threads Settings。
4. 开启 Threaded Mode，并确保允许用户创建新线程。

然后再次发送 /topic。` |
| `gateway/slash_commands.py:5044` | `gateway.topic.topics_user_disallowed` | `Telegram topics are enabled, but users are not allowed to create topics.

Open @BotFather → choose your bot → Bot Settings → Threads Settings, then turn off 'Disallow users to create new threads'.

Then send /topic again.` | `Telegram topics 已启用，但不允许用户创建 topics。

打开 @BotFather → 选择您的 bot → Bot Settings → Threads Settings，然后关闭 'Disallow users to create new threads'。

然后再次发送 /topic。` |
| `gateway/slash_commands.py:6168` | `gateway.reload_skills.added_header` | `➕ **Added Skills:**` | `➕ **新增技能：**` |
| `gateway/slash_commands.py:6172` | `gateway.reload_skills.removed_header` | `➖ **Removed Skills:**` | `➖ **移除技能：**` |
| `gateway/slash_commands.py:6274` | `gateway.approval_expired` | `⚠️ Approval expired (agent is no longer waiting). Ask the agent to try again.` | `⚠️ 批准已过期（代理不再等待）。请让代理重试。` |
| `gateway/slash_commands.py:6351` | `gateway.deny.stale` | `❌ Command denied (approval was stale).` | `❌ 命令已拒绝（批准已过期）。` |
| `gateway/slash_commands.py:6386` | `gateway.deny.denied_reason_plural` | `❌ Commands denied ({count} commands). Reason relayed to the agent: "{reason}"` | `❌ 命令已拒绝（{count} 条命令）。 已将原因转达给代理: "{reason}"` |
| `gateway/slash_commands.py:6388` | `gateway.deny.denied_reason_singular` | `❌ Command denied. Reason relayed to the agent: "{reason}"` | `❌ 命令已拒绝。 已将原因转达给代理: "{reason}"` |
| `gateway/slash_commands.py:6390` | `gateway.deny.denied_plural` | `❌ Commands denied ({count} commands).` | `❌ 命令已拒绝（{count} 条命令）。` |
| `gateway/slash_commands.py:6392` | `gateway.deny.denied_singular` | `❌ Command denied.` | `❌ 命令已拒绝。` |
| `hermes_cli/model_switch.py:371` | `gateway.model.validation_hermes_non_agentic` | `Nous Research Hermes 3 & 4 models are NOT agentic and are not designed for use with Hermes Agent. They lack the tool-calling capabilities required for agent workflows. Consider using an agentic model instead (Claude, GPT, Gemini, DeepSeek, etc.).` | `Nous Research Hermes 3 & 4 模型不是 agentic 模型，不适用于 Hermes Agent。它们缺少 agent 工作流所需的工具调用能力。请考虑改用 agentic 模型（Claude、GPT、Gemini、DeepSeek 等）。` |
| `hermes_cli/model_switch.py:1809` | `gateway.model.switch_unknown_provider` | `Unknown provider '{provider}'. Check 'hermes model' for available providers, or define it in config.yaml under 'providers:'.` | `未知的提供方 '{provider}'。运行 'hermes model' 查看可用提供方，或在 config.yaml 的 'providers:' 下定义。` |
| `hermes_cli/model_switch.py:1816` | `gateway.model.switch_config_issues` | `

Run 'hermes doctor' — config issues detected:` | `

运行 'hermes doctor' — 检测到配置问题：` |
| `hermes_cli/model_switch.py:1872` | `gateway.model.switch_alias_no_credentials` | `Provider '{alias}' is an alias that routes through {provider}, which has no credentials configured.{hint}` | `提供方 '{alias}' 是一个别名，路由到 {provider}，但该提供方没有配置凭据。{hint}` |
| `hermes_cli/model_switch.py:1893` | `gateway.model.switch_no_model_detected` | `No model detected on {provider} ({base_url}). Specify the model explicitly: /model <model-name> --provider {provider_slug}` | `在 {provider}（{base_url}）上未检测到模型。请显式指定模型：/model <model-name> --provider {provider_slug}` |
| `hermes_cli/model_switch.py:1906` | `gateway.model.switch_no_base_url` | `Provider '{provider}' has no base URL configured. Specify a model: /model <model-name> --provider {provider_slug}` | `提供方 '{provider}' 没有配置 base URL。请指定模型：/model <model-name> --provider {provider_slug}` |
| `hermes_cli/model_switch.py:1998` | `gateway.model.switch_alias_not_found` | `Alias '{alias}' maps to {vendor}/{family} but no matching model was found in any provider catalog. Try specifying the full model name.` | `别名 '{alias}' 映射到 {vendor}/{family}，但在所有提供方目录中均未找到匹配的模型。请尝试指定完整模型名称。` |
| `hermes_cli/model_switch.py:2082` | `gateway.model.switch_multiple_providers` | `'{model}' is declared by multiple configured providers ({providers}). Re-run with --provider <slug> to choose which one to use.` | `'{model}' 被多个已配置的提供方声明（{providers}）。请使用 --provider <slug> 重新运行以选择使用哪个。` |
| `hermes_cli/model_switch.py:2217` | `gateway.model.switch_credential_error` | `Could not resolve credentials for provider '{provider}': {error}` | `无法为提供方 '{provider}' 解析凭据：{error}` |
| `hermes_cli/model_switch.py:2436` | `gateway.model.validation_could_not_validate` | `Could not validate `{model}`: {error}` | `无法验证 `{model}`：{error}` |
| `hermes_cli/model_switch.py:2479` | `gateway.model.validation_invalid_model` | `Invalid model` | `无效模型` |
| `hermes_cli/models.py:6879` | `gateway.model.validation_empty` | `Model name cannot be empty.` | `模型名称不能为空。` |
| `hermes_cli/models.py:6892` | `gateway.model.validation_moa_not_found` | `MoA preset `{requested}` was not found. Run `hermes moa list`.` | `未找到 MoA 预设 `{requested}`。运行 `hermes moa list` 查看。` |
| `hermes_cli/models.py:6897` | `gateway.model.validation_moa_read_error` | `Could not read MoA presets: {error}` | `无法读取 MoA 预设：{error}` |
| `hermes_cli/models.py:6905` | `gateway.model.validation_no_spaces` | `Model names cannot contain spaces.` | `模型名称不能包含空格。` |
| `hermes_cli/models.py:6960` | `gateway.model.validation_lmstudio_auth` | `Set `LM_API_KEY` (or update it) to match the server's bearer token.` | `请设置 `LM_API_KEY`（或更新它）以匹配服务器的 bearer token。` |
| `hermes_cli/models.py:6966` | `gateway.model.validation_lmstudio_unreachable` | `Could not reach LM Studio's `/api/v1/models` to validate `{requested}`.` | `无法连接 LM Studio 的 `/api/v1/models` 来验证 `{requested}`。` |
| `hermes_cli/models.py:6972` | `gateway.model.validation_lmstudio_no_models_1` | `LM Studio is reachable but no chat-capable models are loaded. ` | `LM Studio 可连接但没有加载支持对话的模型。` |
| `hermes_cli/models.py:6973` | `gateway.model.validation_lmstudio_no_models_2` | `Load `{requested}` in LM Studio (Developer tab → Load Model) and try again.` | `请在 LM Studio 中加载 `{requested}`（开发者选项卡 → Load Model）后重试。` |
| `hermes_cli/models.py:6980` | `gateway.model.validation_lmstudio_not_found` | `Model `{requested}` was not found in LM Studio's model listing.` | `在 LM Studio 的模型列表中未找到模型 `{requested}`。` |
| `hermes_cli/models.py:7100` | `gateway.model.validation_auto_corrected` | `Auto-corrected `{requested}` → `{corrected}`` | `已自动纠正 `{requested}` → `{corrected}`` |
| `hermes_cli/models.py:7109` | `gateway.model.validation_custom_not_found_1` | `Note: `{requested}` was not found in this custom endpoint's model listing ({url}). ` | `提示：在当前自定义端点的模型列表中未找到 `{requested}`（{url}）。` |
| `hermes_cli/models.py:7110` | `gateway.model.validation_custom_not_found_2` | `It may still work if the server supports hidden or aliased models.` | `如果服务器支持隐藏或别名模型，它可能仍然可用。` |
| `hermes_cli/models.py:7115` | `gateway.model.validation_custom_fallback` | `
  Endpoint verification succeeded after trying `{url}`. Consider saving that as your base URL.` | `
  端点验证在尝试 `{url}` 后成功。建议将其保存为你的 base URL。` |
| `hermes_cli/models.py:7126` | `gateway.model.validation_custom_unreachable` | `Note: could not reach this custom endpoint's model listing at `{url}`. ` | `提示：无法连接当前自定义端点的模型列表 `{url}`。` |
| `hermes_cli/models.py:7127` | `gateway.model.validation_custom_unreachable_2` | `Hermes will still save `{requested}`, but the endpoint should expose `/models` for verification.` | `Hermes 仍会保存 `{requested}`，但端点应暴露 `/models` 以供验证。` |
| `hermes_cli/models.py:7130` | `gateway.model.validation_custom_anthropic_note` | `
  Many Anthropic-compatible proxies do not implement the Models API (GET /v1/models).  The model name has been accepted without verification.` | `
  许多 Anthropic 兼容代理不实现 Models API（GET /v1/models）。模型名称已接受但未经验证。` |
| `hermes_cli/models.py:7132` | `gateway.model.validation_custom_suggested_url` | `
  If this server expects `/v1`, try base URL: `{url}`` | `
  如果该服务器需要 `/v1`，请尝试 base URL：`{url}`` |
| `hermes_cli/models.py:7202` | `gateway.model.validation_auto_corrected` | `Auto-corrected `{requested}` → `{corrected}`` | `已自动纠正 `{requested}` → `{corrected}`` |
| `hermes_cli/models.py:7231` | `gateway.model.validation_codex_not_plausible` | ``{requested}` doesn't look like a {provider_label} model and isn't in its listing, so it was not accepted. If it belongs to another configured provider, switch with `--provider <slug>` (or select it from the `/model` picker).` | ``{requested}` 不像是 {provider_label} 模型，也不在其列表中，因此未被接受。如果它属于另一个已配置的提供方，请使用 `--provider <slug>` 切换（或从 `/model` 选择器中选择）。` |
| `hermes_cli/models.py:7238` | `gateway.model.validation_catalog_not_found` | `Note: `{requested}` was not found in the {provider_label} model listing. ` | `提示：在 {provider_label} 模型列表中未找到 `{requested}`。` |
| `hermes_cli/models.py:7239` | `gateway.model.validation_catalog_not_found_2` | `It may still work if your account has access to a newer or hidden model ID.` | `如果你的账号有较新或隐藏模型 ID 的访问权限，它可能仍然可用。` |
| `hermes_cli/models.py:7271` | `gateway.model.validation_auto_corrected` | `Auto-corrected `{requested}` → `{corrected}`` | `已自动纠正 `{requested}` → `{corrected}`` |
| `hermes_cli/models.py:7282` | `gateway.model.validation_minimax_not_found` | `Note: `{requested}` was not found in the MiniMax catalog.` | `提示：在 MiniMax 目录中未找到 `{requested}`。` |
| `hermes_cli/models.py:7284` | `gateway.model.validation_minimax_no_models_endpoint` | `
  MiniMax does not expose a /models endpoint, so Hermes cannot verify the model name.` | `
  MiniMax 不暴露 /models 端点，因此 Hermes 无法验证模型名称。` |
| `hermes_cli/models.py:7285` | `gateway.model.validation_minimax_may_still_work` | `
  The model may still work if it exists on the server.` | `
  如果该模型在服务器上存在，可能仍然可用。` |
| `hermes_cli/models.py:7315` | `gateway.model.validation_auto_corrected` | `Auto-corrected `{requested}` → `{corrected}`` | `已自动纠正 `{requested}` → `{corrected}`` |
| `hermes_cli/models.py:7329` | `gateway.model.validation_anthropic_not_found` | `Note: `{requested}` was not found in Anthropic's /v1/models listing. ` | `提示：在 Anthropic 的 /v1/models 列表中未找到 `{requested}`。` |
| `hermes_cli/models.py:7330` | `gateway.model.validation_anthropic_not_found_2` | `It may still work if you have early-access or snapshot IDs.` | `如果你有早期访问或快照 ID，它可能仍然可用。` |
| `hermes_cli/models.py:7356` | `gateway.model.validation_auto_corrected` | `Auto-corrected `{requested}` → `{corrected}`` | `已自动纠正 `{requested}` → `{corrected}`` |
| `hermes_cli/models.py:7364` | `gateway.model.validation_anthropic_messages_unverified` | `Note: could not verify `{requested}` against this endpoint's model listing.  Many Anthropic-compatible proxies do not implement GET /v1/models.  The model name has been accepted without verification.` | `提示：无法针对此端点的模型列表验证 `{requested}`。许多 Anthropic 兼容代理不实现 GET /v1/models。模型名称已接受但未经验证。` |
| `hermes_cli/models.py:7422` | `gateway.model.validation_auto_corrected` | `Auto-corrected `{requested}` → `{corrected}`` | `已自动纠正 `{requested}` → `{corrected}`` |
| `hermes_cli/models.py:7459` | `gateway.model.validation_live_not_found_catalog` | `Note: `{requested}` was not found in the live /v1/models listing but exists in the curated catalog — accepted.` | `提示：在实时 /v1/models 列表中未找到 `{requested}`，但存在于策划目录中 — 已接受。` |
| `hermes_cli/models.py:7503` | `gateway.model.validation_not_found_in_provider` | `Model `{requested}` was not found in this provider's model listing.` | `在当前提供方的模型列表中未找到模型 `{requested}`。` |
| `hermes_cli/models.py:7538` | `gateway.model.validation_bedrock_not_found` | `Note: `{requested}` was not found in Bedrock model discovery for {region}. ` | `提示：在 {region} 的 Bedrock 模型发现中未找到 `{requested}`。` |
| `hermes_cli/models.py:7539` | `gateway.model.validation_bedrock_not_found_2` | `It may still work with custom inference profiles or cross-account access.` | `它可能仍然适用于自定义推理配置文件或跨账号访问。` |
| `hermes_cli/models.py:7596` | `gateway.model.validation_auto_corrected` | `Auto-corrected `{requested}` → `{corrected}`` | `已自动纠正 `{requested}` → `{corrected}`` |
| `hermes_cli/models.py:7615` | `gateway.model.validation_catalog_fallback_not_found` | `Note: `{requested}` was not found in the {provider_label} curated catalog and the /models endpoint was unreachable.` | `提示：在 {provider_label} 策划目录中未找到 `{requested}`，且 /models 端点不可达。` |
| `hermes_cli/models.py:7617` | `gateway.model.validation_catalog_fallback_may_work` | `
  The model may still work if it exists on the provider.` | `
  如果该模型在提供方上存在，可能仍然可用。` |
| `hermes_cli/models.py:7628` | `gateway.model.validation_api_unreachable` | `Note: could not reach the {provider_label} API to validate `{requested}`. If the service isn't down, this model may not be valid.` | `提示：无法连接 {provider_label} API 来验证 `{requested}`。如果服务未宕机，此模型可能无效。` |
| `plugins/platforms/discord/adapter.py:5912` | `gateway.discord_slash.new_started` | `New conversation started~` | `新会话已开始~` |
| `plugins/platforms/discord/adapter.py:5916` | `gateway.discord_slash.reset_started` | `Session reset~` | `会话已重置~` |
| `plugins/platforms/discord/adapter.py:5954` | `gateway.discord_slash.retrying` | `Retrying~` | `正在重试~` |
| `plugins/platforms/discord/adapter.py:5962` | `gateway.discord_slash.status_sent` | `Status sent~` | `状态已发送~` |
| `plugins/platforms/discord/adapter.py:5970` | `gateway.discord_slash.stop_requested` | `Stop requested~` | `已请求停止~` |
| `plugins/platforms/discord/adapter.py:6037` | `gateway.discord_slash.update_initiated` | `Update initiated~` | `已开始更新~` |
| `plugins/platforms/discord/adapter.py:6041` | `gateway.discord_slash.restart_requested` | `Restart requested~` | `已请求重启~` |
| `plugins/platforms/discord/adapter.py:6072` | `gateway.discord_slash.queued` | `Queued for the next turn.` | `已加入下一轮队列。` |
| `plugins/platforms/discord/adapter.py:6077` | `gateway.discord_slash.background_started` | `Background task started~` | `后台任务已启动~` |
| `plugins/platforms/matrix/adapter.py:2984` | `gateway.attachment_failed` | `⚠️ Couldn't deliver the attachment.` | `⚠️ 无法发送附件。` |
| `plugins/platforms/slack/adapter.py:4780` | `gateway.image_attachment_failed` | `⚠️ Couldn't deliver the image attachment.` | `⚠️ 无法发送图片附件。` |
| `plugins/platforms/slack/adapter.py:4941` | `gateway.video_attachment_failed` | `⚠️ Couldn't deliver the video attachment.` | `⚠️ 无法发送视频附件。` |
| `plugins/platforms/slack/adapter.py:5009` | `gateway.file_attachment_failed_with_name` | `⚠️ Couldn't deliver the file attachment ({file_name}).` | `⚠️ 无法发送文件附件（{file_name}）。` |
| `run_agent.py:4294` | `gateway.turn_explainer.prefix` | `⚠️ No reply: ` | `⚠️ 无回复：` |
| `run_agent.py:4296` | `gateway.turn_explainer.empty_response_exhausted` | `the model returned empty content after retries and any fallback providers. Try `continue`, switch model/provider, or inspect the tool output above.` | `模型在重试和所有 fallback 服务商后仍返回空内容。建议发送 `continue` 重试，或用 /model 切换模型/服务商，也可检查上方的工具输出。` |
| `run_agent.py:4298` | `gateway.turn_explainer.all_retries_exhausted` | `all API retries were exhausted before a response was produced (provider errors / rate limits). Try `continue` or switch provider.` | `所有 API 重试均已耗尽，仍未产生响应（服务商错误 / 限流）。建议稍后发送 `continue` 重试，或用 /model 切换服务商。` |
| `run_agent.py:4300` | `gateway.turn_explainer.partial_stream_recovery` | `streaming stopped early and only a partial response was recovered. Send `continue` to resume from where it stopped.` | `流式响应提前中断，仅恢复了部分内容。请发送 `continue` 从中断处继续。` |
| `run_agent.py:4302` | `gateway.turn_explainer.fallback_prior_turn` | `no new content was produced this turn; showing recovered prior context. Send `continue` to retry.` | `本轮未产生新内容；正在显示恢复的先前上下文。请发送 `continue` 重试。` |
| `run_agent.py:4304` | `gateway.turn_explainer.interrupted_during_api_call` | `the request was interrupted mid-call before a reply was received. Send `continue` to retry.` | `请求在收到回复前被中断。请发送 `continue` 重试。` |
| `run_agent.py:4306` | `gateway.turn_explainer.budget_exhausted` | `the per-turn iteration/cost budget was exhausted before a final answer. Send `continue` to keep going.` | `本轮的迭代/成本预算在得到最终答复前已耗尽。请发送 `continue` 继续。` |
| `run_agent.py:4308` | `gateway.turn_explainer.ollama_context_too_small` | `the local model's context window was too small to finish. Increase the context size or use a larger model.` | `本地模型的上下文窗口太小，无法完成。请增大上下文长度或换用更大的模型。` |
| `run_agent.py:4310` | `gateway.turn_explainer.max_iterations` | `the maximum tool-iteration limit was reached before a final answer. Send `continue` to keep going, or raise `max_iterations`.` | `在得到最终答复前已达到最大工具迭代次数上限。请发送 `continue` 继续，或调高 `max_iterations`。` |
| `run_agent.py:4312` | `gateway.turn_explainer.error_near_max_iterations` | `an error occurred near the iteration limit before a final answer. Check the tool output above, then send `continue`.` | `在接近迭代上限时发生错误，未能给出最终答复。请检查上方的工具输出，然后发送 `continue` 继续。` |
| `run_agent.py:4321` | `gateway.turn_explainer.pending_tool_result` | `the turn stopped while a tool result was still pending and the model produced no follow-up text. Send `continue` to let it summarize.` | `轮次在工具结果仍挂起时停止，且模型未产生后续文本。请发送 `continue` 让其总结。` |
| `run_agent.py:9012` | `toolguard.halt_response` | `I stopped retrying {tool_name} because it hit the tool-call guardrail ({code}) after {count} repeated non-progressing attempts. The last tool result explains the blocker; the next step is to change strategy instead of repeating the same call.` | `我已停止重试 {tool_name}，因为它在 {count} 次重复无进展的尝试后触发了工具调用护栏（{code}）。最后一次工具结果已说明阻塞原因；下一步应改变策略，而不是重复相同的调用。` |
| `run_agent.py:9427` | `gateway.turn_lease.waiting` | `⏳ Another Hermes process is using this session; waiting for it to finish before starting your turn...` | `⏳ 另一个 Hermes 进程正在使用此会话；正在等待其结束后再开始本轮...` |
| `run_agent.py:9430` | `gateway.turn_lease.still_waiting` | `⏳ Still waiting for the other Hermes process on this session ({seconds}s)...` | `⏳ 仍在等待此会话上的另一个 Hermes 进程（{seconds} 秒）...` |
| `run_agent.py:9448` | `gateway.turn_lease.interrupted` | `Stopped waiting for another Hermes process on this session. Your message was not processed.` | `已停止等待此会话上的另一个 Hermes 进程。你的消息未被处理。` |
| `run_agent.py:9475` | `gateway.turn_lease.timeout` | `⏳ Another Hermes process kept this session busy too long. Your message was not processed - wait for the other process to finish, then send it again.` | `⏳ 另一个 Hermes 进程占用此会话时间过长。你的消息未被处理——请等待该进程结束后重新发送。` |
| `run_agent.py:9505` | `gateway.turn_lease.free` | `Session is free; loading the latest transcript...` | `会话已空闲；正在加载最新会话记录...` |
| `tools/approval.py:887` | `approval.user_deny_blocked` | `BLOCKED: this command matches the user-defined deny rule '{pattern}' (approvals.deny in config.yaml). It cannot be executed via the agent — not even with --yolo, /yolo, or approvals.mode=off. Do NOT retry or rephrase this command; the user has explicitly forbidden it.` | `已拦截：此命令匹配用户自定义的拒绝规则 '{pattern}'（config.yaml 中的 approvals.deny）。无法通过 agent 执行 — 即使使用 --yolo、/yolo 或 approvals.mode=off 也不行。请勿重试或改写此命令；用户已明确禁止它。` |
| `tools/approval.py:951` | `approval.hardline_blocked` | `BLOCKED (hardline): {description}. This command is on the unconditional blocklist and cannot be executed via the agent — not even with --yolo, /yolo, approvals.mode=off, or cron approve mode. If you genuinely need to run it, run it yourself in a terminal outside the agent.` | `已拦截（硬拦截）：{description}。此命令位于无条件拦截列表中，无法通过 agent 执行 — 即使使用 --yolo、/yolo、approvals.mode=off 或 cron 批准模式也不行。如果你确实需要运行它，请在 agent 外的终端中手动运行。` |
| `tools/approval.py:961` | `approval.hardline_recovery_saved` | ` RECOVERY: this block fires on oversized/unparseable inline command payloads (heredocs, giant one-liners), not on the operation itself. Your command was saved to {saved} — review it, then run: terminal(command="bash {saved}"). Do not retry inline.` | ` 恢复：此拦截针对超大/无法解析的内联命令载荷（heredoc、巨型单行命令），而非操作本身。你的命令已保存到 {saved} — 检查后运行：terminal(command="bash {saved}")。请勿内联重试。` |
| `tools/approval.py:963` | `approval.hardline_recovery_manual` | ` RECOVERY: this block fires on oversized/unparseable inline command payloads (heredocs, giant one-liners), not on the operation itself. Write the script to a file with write_file, then run it: terminal(command="bash /path/script.sh") or "python3 /path/script.py". Do not retry inline.` | ` 恢复：此拦截针对超大/无法解析的内联命令载荷（heredoc、巨型单行命令），而非操作本身。请用 write_file 将脚本写入文件，然后运行：terminal(command="bash /path/script.sh") 或 "python3 /path/script.py"。请勿内联重试。` |
| `tools/approval.py:982` | `approval.sudo_stdin_blocked` | `BLOCKED: {description}. Do not pipe passwords to 'sudo -S' — this is a brute-force attack vector. Set SUDO_PASSWORD in your .env file if the agent needs passwordless sudo, or run the sudo command manually in your own terminal.` | `已拦截：{description}。请勿通过管道向 'sudo -S' 传递密码 — 这是一个暴力破解攻击路径。如果 agent 需要免密 sudo，请在 .env 文件中设置 SUDO_PASSWORD，或者在你自己的终端中手动运行 sudo 命令。` |
| `tools/approval.py:2930` | `approval.circuit_breaker` | ` CIRCUIT BREAKER: {count} consecutive commands were blocked by the security reviewer. STOP attempting variations of this operation. Report the blocked operation to the user and either ask them to run it manually or use /approve.` | ` 熔断器：{count} 条连续命令被安全审查拦截。停止尝试此操作的变体。向用户报告被拦截的操作，并请用户手动运行或使用 /approve。` |
| `tools/approval.py:3473` | `approval.choose_smart_deny` | `      [o]nce  \|  [d]eny` | `      [o]仅此一次  \|  [d]拒绝` |
| `tools/approval.py:3475` | `approval.choose_long` | `      [o]nce  \|  [s]ession  \|  [a]lways  \|  [d]eny` | `      [o]仅此一次  \|  [s]本次会话  \|  [a]永久允许  \|  [d]拒绝` |
| `tools/approval.py:3477` | `approval.choose_short` | `      [o]nce  \|  [s]ession  \|  [d]eny` | `      [o]仅此一次  \|  [s]本次会话  \|  [d]拒绝` |
| `tools/approval.py:3486` | `approval.prompt_smart_deny` | `      Choice [o/D]: ` | `      选择 [o/D]: ` |
| `tools/approval.py:3488` | `approval.prompt_long` | `      Choice [o/s/a/D]: ` | `      选择 [o/s/a/D]: ` |
| `tools/approval.py:3488` | `approval.prompt_short` | `      Choice [o/s/D]: ` | `      选择 [o/s/D]: ` |
| `tools/approval.py:3521` | `approval.allowed_once` | `      ✓ Allowed once` | `      ✓ 本次允许` |
| `tools/approval.py:3524` | `approval.allowed_session` | `      ✓ Allowed for this session` | `      ✓ 本次会话内允许` |
| `tools/approval.py:3528` | `approval.allowed_session` | `      ✓ Allowed for this session` | `      ✓ 本次会话内允许` |
| `tools/approval.py:3530` | `approval.allowed_always` | `      ✓ Added to permanent allowlist` | `      ✓ 已加入永久允许列表` |
| `tools/approval.py:3533` | `approval.denied` | `      ✗ Denied` | `      ✗ 已拒绝` |
| `tools/approval.py:4016` | `approval.unattended_blocked` | `BLOCKED: approval required ({description}) but this session runs on an unattended platform ({platform}) with no user present to approve it. Find an alternative approach that avoids this action. To allow flagged actions on unattended platforms, set approvals.unattended_mode: approve in config.yaml.` | `已拦截：需要审批（{description}），但本会话运行在无人值守平台（{platform}）上，没有用户在场批准。请寻找替代方案来避免此操作。如需在无人值守平台允许被标记的操作，请在 config.yaml 中设置 approvals.unattended_mode: approve。` |
| `tools/approval.py:4038` | `approval.no_human_present` | `BLOCKED: approval required ({description}) but no interactive user or gateway is present to approve it.` | `已拦截：需要审批（{description}），但没有交互式用户或网关在场批准。` |
| `tools/approval.py:4078` | `approval.gateway_notify_failed` | `BLOCKED: Failed to send approval request to user. Do NOT retry.` | `已拦截：无法向用户发送审批请求。请勿重试。` |
| `tools/approval.py:4090` | `approval.reason_timeout` | `timed out without user response` | `因用户未响应而超时` |
| `tools/approval.py:4091` | `approval.silence_not_consent` | ` Silence is not consent.` | ` 沉默不等于同意。` |
| `tools/approval.py:4095` | `approval.reason_denied_by_user` | `denied by user` | `被用户拒绝` |
| `tools/approval.py:4100` | `approval.reason_user_given` | ` Reason given by the user: "{deny_reason}".` | ` 用户给出的理由："{deny_reason}"。` |
| `tools/approval.py:4105` | `approval.gateway_action_blocked` | `BLOCKED: Action {reason}.{reason_addendum} The user has NOT consented to this action. Do NOT retry it, do NOT rephrase it, and do NOT attempt the same outcome via a different path.{timeout_addendum}` | `已拦截：操作{reason}。{reason_addendum}用户未同意此操作。请勿重试，请勿改写，也请勿通过其他路径尝试实现相同结果。{timeout_addendum}` |
| `tools/approval.py:4147` | `approval.gateway_asking_target` | `⚠️ This action is potentially dangerous ({description}). Asking the user for approval.

**Target:**
```
{target}
```` | `⚠️ 此操作具有潜在危险（{description}）。正在请求用户批准。

**目标：**
```
{target}
```` |
| `tools/approval.py:4180` | `approval.cli_timeout_action` | `BLOCKED: Action timed out without user response. The user has NOT consented to this action. Do NOT retry it, do NOT rephrase it, and do NOT attempt the same outcome via a different path. Silence is not consent.` | `已拦截：操作因用户未响应而超时。用户未同意此操作。请勿重试，请勿改写，也请勿通过其他路径尝试实现相同结果。沉默不等于同意。` |
| `tools/approval.py:4190` | `approval.cli_denied_action` | `BLOCKED: User denied this potentially dangerous action (matched '{description}'). Do NOT retry — the user has explicitly rejected it.` | `已拦截：用户拒绝了此具有潜在危险的操作（匹配 '{description}'）。请勿重试 — 用户已明确拒绝。` |
| `tools/approval.py:4288` | `approval.cron_blocked` | `BLOCKED: Command flagged as dangerous ({description}) but cron jobs run without a user present to approve it. Find an alternative approach that avoids this command. To allow dangerous commands in cron jobs, set approvals.cron_mode: approve in config.yaml.` | `已拦截：命令被标记为危险（{description}），但定时任务运行时没有用户在场批准。请寻找替代方案来避免此命令。如需在定时任务中允许危险命令，请在 config.yaml 中设置 approvals.cron_mode: approve。` |
| `tools/approval.py:4289` | `approval.single_query_blocked` | `BLOCKED: Command flagged as dangerous ({description}) but single-query mode (-q) runs without a user present to approve it. Find an alternative approach that avoids this command. To allow dangerous commands in single-query mode, set approvals.single_query_mode: approve in config.yaml.` | `已拦截：命令被判为危险（{description}），但单查询模式（-q）运行时没有用户在场批准。请寻找替代方案来避免此命令。如需在单查询模式中允许危险命令，请在 config.yaml 中设置 approvals.single_query_mode: approve。` |
| `tools/approval.py:4343` | `approval.plugin_requires_approval` | `Plugin requires approval for {tool_name}` | `插件需要审批：{tool_name}` |
| `tools/approval.py:4366` | `approval.cron_blocked_tool` | `BLOCKED: Tool '{tool_name}' requires approval ({description}) but cron jobs run without a user present to approve it. Find an alternative approach. To allow flagged actions in cron jobs, set approvals.cron_mode: approve in config.yaml.` | `已拦截：工具 '{tool_name}' 需要审批（{description}），但定时任务运行时没有用户在场批准。请寻找替代方案。如需在定时任务中允许标记操作，请在 config.yaml 中设置 approvals.cron_mode: approve。` |
| `tools/approval.py:4370` | `approval.single_query_blocked_tool` | `BLOCKED: Tool '{tool_name}' requires approval ({description}) but single-query mode (-q) runs without a user present to approve it. Find an alternative approach. To allow flagged actions in single-query mode, set approvals.single_query_mode: approve in config.yaml.` | `已拦截：工具 '{tool_name}' 需要审批（{description}），但单查询模式（-q）运行时没有用户在场批准。请寻找替代方案。如需在单查询模式中允许被标记的操作，请在 config.yaml 中设置 approvals.single_query_mode: approve。` |
| `tools/approval.py:4379` | `approval.no_human_present_tool` | `BLOCKED: Tool '{tool_name}' requires approval ({description}) but no interactive user or gateway is present to approve it. A plugin flagged this action for human confirmation.` | `已拦截：工具 '{tool_name}' 需要审批（{description}），但没有交互式用户或网关在场批准。插件标记此操作需要人工确认。` |
| `tools/approval.py:4654` | `approval.tirith_issue_fallback` | `security issue detected` | `检测到安全问题` |
| `tools/approval.py:4660` | `approval.tirith_summary.timeout` | `tirith timed out ({timeout}s)` | `tirith 超时（{timeout}s）` |
| `tools/approval.py:4663` | `approval.tirith_summary.unavailable` | `tirith unavailable: {detail}` | `tirith 不可用：{detail}` |
| `tools/approval.py:4665` | `approval.tirith_summary.spawn_failed` | `{detail}` | `{detail}` |
| `tools/approval.py:4667` | `approval.tirith_summary.exit_code` | `{detail}` | `{detail}` |
| `tools/approval.py:4975` | `approval.scan_prefix` | `Security scan` | `安全扫描` |
| `tools/approval.py:4979` | `approval.scan_summary` | `{prefix}: {summary}` | `{prefix}：{summary}` |
| `tools/approval.py:4999` | `approval.scan_summary` | `{prefix}: {summary}` | `{prefix}：{summary}` |
| `tools/approval.py:5001` | `approval.scan_findings` | `{prefix} — {findings}` | `{prefix} — {findings}` |
| `tools/approval.py:5156` | `approval.transport_failed` | `BLOCKED: Selected approval transport failed ({failure}); the user has NOT consented to this action. Do NOT retry this command or attempt the same outcome through another route.` | `已拦截：所选审批通道失败（{failure}）；用户未同意此操作。不要重试此命令，也不要换其他途径尝试同一结果。` |
| `tools/approval.py:5540` | `approval.single_query_blocked` | `BLOCKED: Command flagged as dangerous ({description}) but single-query mode (-q) runs without a user present to approve it. Find an alternative approach that avoids this command. To allow dangerous commands in single-query mode, set approvals.single_query_mode: approve in config.yaml.` | `已拦截：命令被判为危险（{description}），但单查询模式（-q）运行时没有用户在场批准。请寻找替代方案来避免此命令。如需在单查询模式中允许危险命令，请在 config.yaml 中设置 approvals.single_query_mode: approve。` |
| `tools/approval.py:5558` | `approval.single_query_blocked_tirith` | `BLOCKED: {description} but single-query mode (-q) runs without a user present to approve it. Find an alternative approach that avoids this command. To allow dangerous commands in single-query mode, set approvals.single_query_mode: approve in config.yaml.` | `已拦截：{description}，但单查询模式（-q）运行时没有用户在场批准。请寻找替代方案来避免此命令。如需在单查询模式中允许危险命令，请在 config.yaml 中设置 approvals.single_query_mode: approve。` |
| `tools/approval.py:5581` | `approval.single_query_blocked_tirith_import` | `BLOCKED: the Tirith security scanner could not be imported and security.tirith_fail_open is false, so this command cannot be silently allowed — and single-query mode (-q) runs without a user present to approve it. Find an alternative approach, install tirith, or set approvals.single_query_mode: approve in config.yaml.` | `已拦截：无法导入 Tirith 安全扫描器，且 security.tirith_fail_open 为 false，因此不能静默放行——且单查询模式（-q）运行时没有用户在场批准。请寻找替代方案、安装 tirith，或在 config.yaml 中设置 approvals.single_query_mode: approve。` |
| `tools/approval.py:5595` | `approval.cron_blocked` | `BLOCKED: Command flagged as dangerous ({description}) but cron jobs run without a user present to approve it. Find an alternative approach that avoids this command. To allow dangerous commands in cron jobs, set approvals.cron_mode: approve in config.yaml.` | `已拦截：命令被标记为危险（{description}），但定时任务运行时没有用户在场批准。请寻找替代方案来避免此命令。如需在定时任务中允许危险命令，请在 config.yaml 中设置 approvals.cron_mode: approve。` |
| `tools/approval.py:5611` | `approval.cron_blocked_tirith` | `BLOCKED: {description} but cron jobs run without a user present to approve it. Find an alternative approach that avoids this command. To allow dangerous commands in cron jobs, set approvals.cron_mode: approve in config.yaml.` | `已拦截：{description}，但定时任务运行时没有用户在场批准。请寻找替代方案来避免此命令。如需在定时任务中允许危险命令，请在 config.yaml 中设置 approvals.cron_mode: approve。` |
| `tools/approval.py:5634` | `approval.cron_blocked_tirith_import` | `BLOCKED: the Tirith security scanner could not be imported and security.tirith_fail_open is false, so this command cannot be silently allowed — and cron jobs run without a user present to approve it. Find an alternative approach, install tirith, or set approvals.cron_mode: approve in config.yaml.` | `已拦截：无法导入 Tirith 安全扫描器，且 security.tirith_fail_open 为 false，因此不能静默放行——且定时任务运行时没有用户在场批准。请寻找替代方案、安装 tirith，或在 config.yaml 中设置 approvals.cron_mode: approve。` |
| `tools/approval.py:5647` | `approval.unattended_blocked_command` | `BLOCKED: Command flagged as dangerous ({description}) but this session runs on an unattended platform ({platform}) with no user present to approve it. Find an alternative approach that avoids this command. To allow dangerous commands on unattended platforms, set approvals.unattended_mode: approve in config.yaml.` | `已拦截：命令被判为危险（{description}），但本会话运行在无人值守平台（{platform}）上，没有用户在场批准。请寻找替代方案来避免此命令。如需在无人值守平台允许危险命令，请在 config.yaml 中设置 approvals.unattended_mode: approve。` |
| `tools/approval.py:5662` | `approval.unattended_blocked_tirith` | `BLOCKED: {description} but this session runs on an unattended platform ({platform}) with no user present to approve it. Find an alternative approach that avoids this command. To allow dangerous commands on unattended platforms, set approvals.unattended_mode: approve in config.yaml.` | `已拦截：{description}，但本会话运行在无人值守平台（{platform}）上，没有用户在场批准。请寻找替代方案来避免此命令。如需在无人值守平台允许危险命令，请在 config.yaml 中设置 approvals.unattended_mode: approve。` |
| `tools/approval.py:5679` | `approval.unattended_blocked_tirith_import` | `BLOCKED: the Tirith security scanner could not be imported and security.tirith_fail_open is false, so this command cannot be silently allowed — and this session runs on an unattended platform ({platform}) with no user present to approve it. Find an alternative approach, install tirith, or set approvals.unattended_mode: approve in config.yaml.` | `已拦截：无法导入 Tirith 安全扫描器，且 security.tirith_fail_open 为 false，因此不能静默放行——且本会话运行在无人值守平台（{platform}）上，没有用户在场批准。请寻找替代方案、安装 tirith，或在 config.yaml 中设置 approvals.unattended_mode: approve。` |
| `tools/approval.py:5795` | `approval.smart_denied` | `BLOCKED by smart approval: {description}. The command was assessed as genuinely dangerous. Do NOT retry.` | `智能审批拦截：{description}。此命令被评估为确实危险。请勿重试。` |
| `tools/approval.py:5874` | `approval.transport_denied` | `BLOCKED: User denied this command through the selected approval transport. The user has NOT consented to this action. Do NOT retry or attempt the same outcome through another route.` | `已拦截：用户已通过所选审批通道拒绝此命令。用户未同意此操作。不要重试，也不要换其他途径尝试同一结果。` |
| `tools/approval.py:5945` | `approval.gateway_notify_failed` | `BLOCKED: Failed to send approval request to user. Do NOT retry.` | `已拦截：无法向用户发送审批请求。请勿重试。` |
| `tools/approval.py:5979` | `approval.gateway_timeout_denied` | `BLOCKED: Command {reason}. The user has NOT consented to this action. Do NOT retry this command, do NOT rephrase it, and do NOT attempt the same outcome via a different command. Stop the current workflow and wait for the user to respond before taking any further destructive or irreversible action.{timeout_addendum}` | `已拦截：命令{reason}。用户未同意此操作。请勿重试此命令，请勿改写它，也请勿通过其他命令尝试实现相同结果。停止当前工作流，并在采取任何进一步破坏性或不可逆操作之前等待用户回应。{timeout_addendum}` |
| `tools/approval.py:6044` | `approval.gateway_asking_combined` | `⚠️ {description}. Asking the user for approval.

**Command:**
```
{command}
```` | `⚠️ {description}。正在请求用户批准。

**命令：**
```
{command}
```` |
| `tools/approval.py:6094` | `approval.cli_timeout_command` | `BLOCKED: Command timed out without user response. The user has NOT consented to this action. Do NOT retry this command, do NOT rephrase it, and do NOT attempt the same outcome via a different command. Stop the current workflow and wait for the user to respond before taking any further destructive or irreversible action. Silence is not consent.` | `已拦截：命令因用户未响应而超时。用户未同意此操作。请勿重试此命令，请勿改写它，也请勿通过其他命令尝试实现相同结果。停止当前工作流，并在采取任何进一步破坏性或不可逆操作之前等待用户回应。沉默不等于同意。` |
| `tools/approval.py:6107` | `approval.cli_denied` | `BLOCKED: User denied this command. The user has NOT consented to this action. Do NOT retry this command, do NOT rephrase it, and do NOT attempt the same outcome via a different command. Stop the current workflow and wait for the user to respond before taking any further destructive or irreversible action.` | `已拦截：用户拒绝了此命令。用户未同意此操作。请勿重试此命令，请勿改写它，也请勿通过其他命令尝试实现相同结果。停止当前工作流，并在采取任何进一步破坏性或不可逆操作之前等待用户回应。` |
| `tools/approval.py:6153` | `approval.execute_code_description` | `execute_code script execution. The script can spawn subprocesses or mutate files without passing through terminal command approval; approval is one-shot for this run.` | `execute_code 脚本执行。该脚本可生成子进程或修改文件，且不经过终端命令审批；本次批准仅对本次运行有效。` |
| `tools/approval.py:6180` | `approval.execute_code_single_query_blocked` | `BLOCKED: execute_code runs arbitrary local Python (including subprocess calls that bypass shell-string approval checks). Single-query mode (-q) runs without a user present to approve it. Use normal tools instead, or set approvals.single_query_mode: approve only if this single-query run is intentionally trusted.` | `已拦截：execute_code 会运行任意本地 Python（包括绕过 shell 字符串审批检查的子进程调用）。单查询模式（-q）运行时没有用户在场批准。请改用常规工具；仅当本次单查询运行是刻意信任的，才设置 approvals.single_query_mode: approve。` |
| `tools/approval.py:6196` | `approval.execute_code_cron_blocked` | `BLOCKED: execute_code runs arbitrary local Python (including subprocess calls that bypass shell-string approval checks). Cron jobs run without a user present to approve it. Use normal tools instead, or set approvals.cron_mode: approve only if this cron profile is intentionally trusted.` | `已拦截：execute_code 运行任意本地 Python（包括绕过 shell 字符串审批检查的子进程调用）。定时任务运行时没有用户在场批准。请使用其他工具替代，或仅在有意信任此 cron 配置时设置 approvals.cron_mode: approve。` |
| `tools/approval.py:6212` | `approval.execute_code_unattended_blocked` | `BLOCKED: execute_code runs arbitrary local Python (including subprocess calls that bypass shell-string approval checks). This session runs on an unattended platform ({platform}) with no user present to approve it. Use normal tools instead, or set approvals.unattended_mode: approve only if sessions on this surface are intentionally trusted.` | `已拦截：execute_code 会运行任意本地 Python（包括绕过 shell 字符串审批检查的子进程调用）。本会话运行在无人值守平台（{platform}）上，没有用户在场批准。请改用常规工具；仅当该平台上的会话是刻意信任的，才设置 approvals.unattended_mode: approve。` |
| `tools/approval.py:6277` | `approval.execute_code_smart_denied` | `BLOCKED by smart approval: execute_code script execution was assessed as genuinely dangerous. Do NOT retry.` | `智能审批拦截：execute_code 脚本执行被评估为确实危险。请勿重试。` |
| `tools/approval.py:6335` | `approval.execute_code_transport_denied` | `BLOCKED: User denied execute_code through the selected approval transport. The user has NOT consented.` | `已拦截：用户已通过所选审批通道拒绝 execute_code。用户未同意。` |
| `tools/approval.py:6405` | `approval.cli_timeout_action` | `BLOCKED: Action timed out without user response. The user has NOT consented to this action. Do NOT retry it, do NOT rephrase it, and do NOT attempt the same outcome via a different path. Silence is not consent.` | `已拦截：操作因用户未响应而超时。用户未同意此操作。请勿重试，请勿改写，也请勿通过其他路径尝试实现相同结果。沉默不等于同意。` |
| `tools/approval.py:6423` | `approval.execute_code_cli_denied` | `BLOCKED: User denied execute_code script execution (matched '{description}'). Do NOT retry — the user has explicitly rejected it.` | `已拦截：用户拒绝了 execute_code 脚本执行（匹配 '{description}'）。不要重试——用户已明确拒绝。` |
| `tools/approval.py:6467` | `approval.execute_code_gateway_asking` | `⚠️ {description}. Asking the user for approval.

**Code:**
```python
{code}
```` | `⚠️ {description}。正在请求用户批准。

**代码：**
```python
{code}
```` |
| `tools/approval.py:6498` | `approval.execute_code_notify_failed` | `BLOCKED: Failed to send execute_code approval request to user. Do NOT retry.` | `已拦截：无法向用户发送 execute_code 审批请求。请勿重试。` |
| `tools/computer_use/backend.py:228` | `tools.backend.no_typed_browser_route` | `This computer-use backend has no typed browser route; use native capture/input.` | `此 computer-use 后端没有类型化浏览器路由；请使用原生捕获/输入。` |
| `tools/computer_use/doctor.py:493` | `tools.doctor.platform_supported` | `platform={plat}` | `platform={plat}` |
| `tools/computer_use/doctor.py:500` | `tools.doctor.session_not_probed` | `not probed (doctor does not open a cua session)` | `未探测（doctor 不打开 cua 会话）` |
| `tools/computer_use/doctor.py:515` | `tools.doctor.accessibility_granted` | `Accessibility is granted.` | `辅助功能已授权。` |
| `tools/computer_use/doctor.py:522` | `tools.doctor.accessibility_not_granted` | `Accessibility is not granted.` | `辅助功能未授权。` |
| `tools/computer_use/doctor.py:523` | `tools.doctor.accessibility_hint` | `Grant Accessibility to CuaDriver in System Settings → Privacy & Security.` | `请在系统设置 → 隐私与安全性中为 CuaDriver 授予辅助功能权限。` |
| `tools/computer_use/doctor.py:530` | `tools.doctor.accessibility_absent` | `accessibility field absent from check_permissions` | `check_permissions 中缺少 accessibility 字段` |
| `tools/computer_use/doctor.py:537` | `tools.doctor.screen_recording_granted_not_capturable` | `Screen Recording granted but not capturable.` | `屏幕录制已授权但无法捕获。` |
| `tools/computer_use/doctor.py:538` | `tools.doctor.screen_recording_hint` | `Screen Recording permission may need a restart of CuaDriver or a re-grant in System Settings.` | `屏幕录制权限可能需要重启 CuaDriver 或在系统设置中重新授权。` |
| `tools/computer_use/doctor.py:548` | `tools.doctor.screen_recording_granted` | `Screen Recording is granted.` | `屏幕录制已授权。` |
| `tools/computer_use/doctor.py:558` | `tools.doctor.screen_recording_not_granted` | `Screen Recording is not granted.` | `屏幕录制未授权。` |
| `tools/computer_use/doctor.py:559` | `tools.doctor.screen_recording_grant_hint` | `Grant Screen Recording to CuaDriver in System Settings → Privacy & Security.` | `请在系统设置 → 隐私与安全性中为 CuaDriver 授予屏幕录制权限。` |
| `tools/computer_use/doctor.py:568` | `tools.doctor.screen_recording_absent` | `screen_recording field absent from check_permissions` | `check_permissions 中缺少 screen_recording 字段` |
| `tools/computer_use/doctor.py:574` | `tools.doctor.screen_recording_not_applicable` | `not applicable on {plat}` | `在 {plat} 上不适用` |
| `tools/computer_use/doctor.py:580` | `tools.doctor.check_permissions_unavailable` | `check_permissions unavailable` | `check_permissions 不可用` |
| `tools/computer_use/doctor.py:585` | `tools.doctor.check_permissions_unavailable` | `check_permissions unavailable` | `check_permissions 不可用` |
| `tools/computer_use/doctor.py:598` | `tools.doctor.list_apps_succeeded` | `list_apps succeeded{count_msg}` | `list_apps 成功{count_msg}` |
| `tools/computer_use/doctor.py:607` | `tools.doctor.list_apps_failed_despite_grant` | `list_apps failed despite accessibility grant` | `list_apps 失败（尽管已授权辅助功能）` |
| `tools/computer_use/doctor.py:609` | `tools.doctor.list_apps_failed` | `list_apps failed` | `list_apps 失败` |
| `tools/computer_use/doctor.py:617` | `tools.doctor.ax_inferred_from_grant` | `inferred from accessibility grant (list_apps not probed)` | `由辅助功能授权推断（未探测 list_apps）` |
| `tools/computer_use/doctor.py:623` | `tools.doctor.not_probed` | `not probed` | `未探测` |
| `tools/computer_use/doctor.py:627` | `tools.doctor.health_report_unavailable` | `health_report unavailable` | `health_report 不可用` |
| `tools/computer_use/doctor.py:633` | `tools.doctor.health_report_fallback` | `fallback composite (cua-driver 0.10 unclassified health_report); cause: {reason}` | `回退复合报告（cua-driver 0.10 未分类的 health_report）；原因：{reason}` |
| `tools/computer_use/tool.py:539` | `tools.computer_use.hint_dangerous_type_pattern` | `Dangerous shell patterns cannot be typed via computer_use.` | `无法通过 computer_use 输入危险的 shell 模式。` |
| `tools/computer_use/tool.py:549` | `tools.computer_use.hint_destructive_shortcuts_blocked` | `Destructive system shortcuts are hard-blocked.` | `破坏性系统快捷键已被硬性阻止。` |
| `tools/computer_use/tool.py:579` | `tools.computer_use.hint_backend_unavailable` | `If the cua-driver binary is missing, run `hermes computer-use install`. If a Python dependency is missing, the error above shows the exact install command.` | `如果缺少 cua-driver 二进制文件，请运行 `hermes computer-use install`。如果缺少 Python 依赖，上方错误信息会显示确切的安装命令。` |
| `tools/cronjob_tools.py:1782` | `tools.cronjob.removed` | `Cron job '{name}' removed.` | `定时任务 '{name}' 已移除。` |
| `tools/discord_tool.py:572` | `tools.discord.message_pinned` | `Message {message_id} pinned.` | `消息 {message_id} 已置顶。` |
| `tools/discord_tool.py:578` | `tools.discord.message_unpinned` | `Message {message_id} unpinned.` | `消息 {message_id} 已取消置顶。` |
| `tools/discord_tool.py:584` | `tools.discord.message_deleted` | `Message {message_id} deleted.` | `消息 {message_id} 已删除。` |
| `tools/discord_tool.py:620` | `tools.discord.role_added` | `Role {role_id} added to user {user_id}.` | `已为用户 {user_id} 添加角色 {role_id}。` |
| `tools/discord_tool.py:626` | `tools.discord.role_removed` | `Role {role_id} removed from user {user_id}.` | `已移除用户 {user_id} 的角色 {role_id}。` |
| `tools/file_tools.py:855` | `approval.protected_file_request` | `Write to protected agent-instruction file(s): {targets}. These files steer future agent behavior; approval is always required (not bypassed by auto-approve).` | `写入受保护的 agent 指令文件：{targets}。这些文件会引导 agent 未来的行为，因此始终需要审批（不会被 auto-approve 绕过）。` |
| `tools/file_tools.py:860` | `approval.protected_file_blocked` | `BLOCKED: write to protected agent-instruction file(s) ({targets}) {why} The user has NOT consented to this write. Do NOT retry it or attempt the same edit via another path (terminal, execute_code, etc.).` | `已拦截：写入受保护的 agent 指令文件（{targets}）{why}用户未同意此写入。不要重试，也不要换其他途径（terminal、execute_code 等）尝试同样的编辑。` |
| `tools/file_tools.py:865` | `approval.gate_why_approval_unavailable` | `requires approval but the approval subsystem is unavailable.` | `需要审批，但审批子系统不可用。` |
| `tools/file_tools.py:891` | `approval.gate_why_not_delivered` | `requires approval but the approval request could not be delivered.` | `需要审批，但审批请求无法送达。` |
| `tools/file_tools.py:898` | `approval.gate_why_timed_out` | `approval prompt timed out without a user response. Silence is not consent.` | `审批提示在用户响应前超时。沉默不等于同意。` |
| `tools/file_tools.py:899` | `approval.gate_why_denied_by_user` | `was denied by the user.` | `已被用户拒绝。` |
| `tools/file_tools.py:920` | `approval.gate_why_timed_out` | `approval prompt timed out without a user response. Silence is not consent.` | `审批提示在用户响应前超时。沉默不等于同意。` |
| `tools/file_tools.py:921` | `approval.gate_why_denied_by_user` | `was denied by the user.` | `已被用户拒绝。` |
| `tools/file_tools.py:925` | `approval.gate_why_no_human` | `requires approval but no interactive user or gateway is present to approve it.` | `需要审批，但没有交互式用户或网关在场批准。` |
| `tools/file_tools.py:979` | `approval.ssh_config_request` | `Write to SSH client config file(s): {targets}. The SSH config can carry ProxyCommand / Match exec directives that run commands, so writes require your approval.` | `写入 SSH 客户端配置文件：{targets}。SSH 配置可包含会执行命令的 ProxyCommand / Match exec 指令，因此写入需要你的审批。` |
| `tools/file_tools.py:983` | `approval.ssh_config_blocked` | `BLOCKED: write to SSH config file(s) ({targets}) {why} Do NOT retry it via another path (terminal, execute_code) without the user's explicit consent.` | `已拦截：写入 SSH 配置文件（{targets}）{why}未经用户明确同意，不要换其他途径（terminal、execute_code）重试。` |
| `tools/file_tools.py:988` | `approval.gate_why_approval_unavailable` | `requires approval but the approval subsystem is unavailable.` | `需要审批，但审批子系统不可用。` |
| `tools/file_tools.py:994` | `approval.gate_why_cron_denied` | `requires approval but this cron session denies it.` | `需要审批，但本定时任务会话拒绝该操作。` |
| `tools/file_tools.py:996` | `approval.gate_why_single_query_denied` | `requires approval but single-query (-q) sessions run without a user present to approve it. To allow flagged actions in single-query mode, set approvals.single_query_mode: approve in config.yaml.` | `需要审批，但单查询（-q）模式运行时没有用户在场批准。如需在单查询模式中允许被标记的操作，请在 config.yaml 中设置 approvals.single_query_mode: approve。` |
| `tools/file_tools.py:1000` | `approval.gate_why_no_human` | `requires approval but no interactive user or gateway is present to approve it.` | `需要审批，但没有交互式用户或网关在场批准。` |
| `tools/file_tools.py:1004` | `approval.gate_why_denied` | `was denied.` | `已被拒绝。` |
| `tools/memory_tool.py:115` | `memory.drift_error` | `Refusing to write {file}: file on disk has content that wouldn't round-trip through the memory tool (likely added by the patch tool, a shell append, a manual edit, or a concurrent session). A snapshot was saved to {backup}. Resolve the drift first — either rewrite the file as a clean §-delimited list of entries, or move the extra content out — then retry. This guard exists to prevent silent data loss (issue #26045).` | `拒绝写入 {file}：磁盘上的文件包含无法通过内存工具往返的内容（可能由 patch 工具、shell 追加、手动编辑或并发会话添加）。已将快照保存到 {backup}。请先解决偏移问题——将文件重写为干净的 § 分隔条目列表，或将额外内容移出——然后重试。此保护机制旨在防止静默数据丢失（issue #26045）。` |
| `tools/memory_tool.py:117` | `memory.drift_remediation` | `Open the .bak file, integrate the missing entries into the memory tool one at a time via memory(action=add, content=...), then remove or rewrite the original file to a clean state.` | `打开 .bak 文件，通过 memory(action=add, content=...) 将缺失的条目逐一整合到内存工具中，然后删除或重写原始文件至干净状态。` |
| `tools/memory_tool.py:137` | `memory.read_failed` | `Refusing to write {file}: the file exists on disk but could not be read right now (temporarily locked by another program, a permission change, invalid/corrupt text encoding, or a filesystem error). Treating an unreadable file as empty and saving would wipe existing memory, so the write is refused. Nothing was changed — retry in a moment.` | `拒绝写入 {file}：文件在磁盘上存在但当前无法读取（可能被其他程序临时锁定、权限更改、文本编码无效/损坏或文件系统错误）。将无法读取的文件视为空并保存会清除现有内存，因此写入被拒绝。未做任何更改——请稍后重试。` |
| `tools/memory_tool.py:400` | `memory.content_empty` | `Content cannot be empty.` | `内容不能为空。` |
| `tools/memory_tool.py:428` | `memory.entry_already_exists` | `Entry already exists (no duplicate added).` | `条目已存在（未添加重复条目）。` |
| `tools/memory_tool.py:438` | `memory.add_exceeds_limit` | `Memory at {current}/{limit} chars. Adding this entry ({entry_chars} chars) would exceed the limit. Consolidate now: use 'replace' to merge overlapping entries into shorter ones or 'remove' stale or less important entries (see current_entries below), then retry this add — all in this turn.` | `内存已用 {current}/{limit} 字符。新增此条目（{entry_chars} 字符）将超出上限。请立即整理：使用 'replace' 将重叠条目合并为更短内容，或使用 'remove' 删除过时或不太重要的条目（见下方 current_entries），然后在本回合内重试本次 add。` |
| `tools/memory_tool.py:452` | `memory.entry_added` | `Entry added.` | `条目已添加。` |
| `tools/memory_tool.py:459` | `memory.old_text_empty` | `old_text cannot be empty.` | `old_text 不能为空。` |
| `tools/memory_tool.py:461` | `memory.new_content_empty` | `new_content cannot be empty. Use 'remove' to delete entries.` | `new_content 不能为空。使用 'remove' 删除条目。` |
| `tools/memory_tool.py:481` | `memory.no_match_replace` | `No entry matched '{old_text}'. Check current_entries below and retry with the exact text of the entry you want to replace.` | `没有条目匹配 '{old_text}'。请查看下方 current_entries，使用要替换的条目的确切文本重试。` |
| `tools/memory_tool.py:492` | `memory.multiple_matches` | `Multiple entries matched '{old_text}'. Be more specific.` | `多个条目匹配 '{old_text}'。请更具体一些。` |
| `tools/memory_tool.py:509` | `memory.replace_exceeds_limit` | `Replacement would put memory at {new_total}/{limit} chars. Shorten the new content, or 'remove' other stale or less important entries to make room (see current_entries below), then retry — all in this turn.` | `替换后内存将达到 {new_total}/{limit} 字符。请缩短新内容，或使用 'remove' 删除其他过时或不太重要的条目以腾出空间（见下方 current_entries），然后在本回合内重试。` |
| `tools/memory_tool.py:518` | `memory.entry_replaced` | `Entry replaced.` | `条目已替换。` |
| `tools/memory_tool.py:524` | `memory.old_text_empty` | `old_text cannot be empty.` | `old_text 不能为空。` |
| `tools/memory_tool.py:539` | `memory.no_match_remove` | `No entry matched '{old_text}'. Check current_entries below and retry with the exact text of the entry you want to remove.` | `没有条目匹配 '{old_text}'。请查看下方 current_entries，使用要删除的条目的确切文本重试。` |
| `tools/memory_tool.py:550` | `memory.multiple_matches` | `Multiple entries matched '{old_text}'. Be more specific.` | `多个条目匹配 '{old_text}'。请更具体一些。` |
| `tools/memory_tool.py:560` | `memory.entry_removed` | `Entry removed.` | `条目已删除。` |
| `tools/memory_tool.py:576` | `memory.batch_empty` | `operations list is empty.` | `操作列表为空。` |
| `tools/memory_tool.py:586` | `memory.batch_op_scan_error` | `Operation {index}: {error}` | `操作 {index}：{error}` |
| `tools/memory_tool.py:604` | `memory.batch_op_pos` | `Operation {index} ({action})` | `操作 {index}（{action}）` |
| `tools/memory_tool.py:608` | `memory.batch_content_required` | `content is required.` | `content 为必填项。` |
| `tools/memory_tool.py:615` | `memory.batch_old_text_required` | `old_text is required.` | `old_text 为必填项。` |
| `tools/memory_tool.py:619` | `memory.batch_content_required_remove` | `content is required (use action='remove' to delete).` | `content 为必填项（使用 action='remove' 可删除）。` |
| `tools/memory_tool.py:623` | `memory.batch_no_match` | `no entry matched '{old_text}'.` | `没有条目匹配 '{old_text}'。` |
| `tools/memory_tool.py:627` | `memory.batch_multiple_matches` | `'{old_text}' matched multiple distinct entries -- be more specific.` | `'{old_text}' 匹配了多个不同条目 -- 请更具体一些。` |
| `tools/memory_tool.py:633` | `memory.batch_old_text_required` | `old_text is required.` | `old_text 为必填项。` |
| `tools/memory_tool.py:636` | `memory.batch_no_match` | `no entry matched '{old_text}'.` | `没有条目匹配 '{old_text}'。` |
| `tools/memory_tool.py:640` | `memory.batch_multiple_matches` | `'{old_text}' matched multiple distinct entries -- be more specific.` | `'{old_text}' 匹配了多个不同条目 -- 请更具体一些。` |
| `tools/memory_tool.py:647` | `memory.batch_unknown_action` | `unknown action. Use add, replace, or remove.` | `未知操作。请使用 add、replace 或 remove。` |
| `tools/memory_tool.py:677` | `memory.batch_nothing_applied` | `No operations were applied (batch is all-or-nothing).` | `未应用任何操作（批量操作为全有或全无模式）。` |
| `tools/memory_tool.py:1234` | `memory.unknown_action` | `Unknown staged action '{action}'.` | `未知的暂存操作 '{action}'。` |
| `tools/process_registry.py:647` | `tools.process_registry.watch_disabled` | `Watch patterns disabled for process {session_id} — {limit} consecutive rate-limit windows triggered (min spacing {min_spacing}s). Falling back to notify_on_complete semantics; you'll get exactly one notification when the process exits.` | `进程 {session_id} 的监视模式已禁用 — 连续 {limit} 个限流窗口被触发（最小间隔 {min_spacing} 秒）。将回退到 notify_on_complete 语义；进程退出时你将收到恰好一条通知。` |
| `tools/process_registry.py:747` | `tools.process_registry.watch_overflow_released` | `Watch-pattern notifications resumed. {suppressed} match event(s) were suppressed during the flood.` | `监视模式通知已恢复。洪泛期间已抑制 {suppressed} 个匹配事件。` |
| `tools/process_registry.py:793` | `tools.process_registry.watch_overflow_tripped` | `Watch-pattern overflow: >{max_per_window} notifications in {window_seconds}s across all processes. Suppressing further watch_match events for {cooldown_seconds}s.` | `监视模式溢出：所有进程在 {window_seconds} 秒内产生 >{max_per_window} 条通知。将在 {cooldown_seconds} 秒内抑制后续 watch_match 事件。` |
| `tools/process_registry.py:2555` | `tools.process_registry.eof_sent` | `EOF sent` | `已发送 EOF` |
| `tools/process_registry.py:2563` | `tools.process_registry.stdin_closed` | `stdin closed` | `已关闭 stdin` |
| `tools/session_search_tool.py:536` | `tools.session_search.browse_hint` | `Showing {count} most recent sessions. Pass a query= to search, or session_id+around_message_id to scroll.` | `显示最近 {count} 个会话。传入 query= 进行搜索，或传入 session_id+around_message_id 进行滚动。` |
| `tools/session_search_tool.py:807` | `tools.session_search.no_matches` | `No matching sessions found.` | `未找到匹配的会话。` |
| `tools/skill_manager_tool.py:1067` | `tools.skill_manage.created` | `Skill '{name}' created.` | `技能 '{name}' 已创建。` |
| `tools/skill_manager_tool.py:1162` | `tools.skill_manage.updated_full_rewrite` | `Skill '{name}' updated (full rewrite).` | `技能 '{name}' 已更新（完整重写）。` |
| `tools/skill_manager_tool.py:1297` | `tools.skill_manage.patched` | `Patched {target} in skill '{name}' ({count} replacement{plural}).` | `已修补技能 '{name}' 中的 {target}（{count} 处替换{plural}）。` |
| `tools/skill_manager_tool.py:1479` | `tools.skill_manage.file_written` | `File '{file_path}' written to skill '{name}'.` | `文件 '{file_path}' 已写入技能 '{name}'。` |
| `tools/skill_manager_tool.py:1538` | `tools.skill_manage.file_removed` | `File '{file_path}' removed from skill '{name}'.` | `文件 '{file_path}' 已从技能 '{name}' 中移除。` |
| `tools/skills_tool.py:861` | `tools.skills_list.no_skills_in_directory` | `No skills found in skills/ directory.` | `在 skills/ 目录中未找到技能。` |
| `tools/terminal_tool.py:2873` | `terminal_tool.invalid_command_type` | `Invalid command: expected string, got {type_name}` | `无效命令：期望字符串，得到 {type_name}` |
| `tools/terminal_tool.py:3049` | `terminal_tool.env_creation_failed` | `Terminal tool disabled: environment creation failed ({error})` | `终端工具已禁用：环境创建失败（{error}）` |
| `tools/terminal_tool.py:3561` | `terminal_tool.bg_process_start_failed` | `Failed to start background process: {error}` | `启动后台进程失败：{error}` |
| `tools/terminal_tool.py:3609` | `terminal_tool.command_timeout` | `Command timed out after {seconds} seconds` | `命令在 {seconds} 秒后超时` |
| `tools/terminal_tool.py:3626` | `terminal_tool.execution_failed` | `Command execution failed: {error_type}: {error}` | `命令执行失败：{error_type}：{error}` |
| `tools/terminal_tool.py:3925` | `terminal_tool.execute_command_failed` | `Failed to execute command: {error}` | `执行命令失败：{error}` |
| `tools/website_policy.py:280` | `tools.website_policy.blocked` | `Blocked by website policy: '{host}' matched rule '{pattern}' from {source}` | `已被网站策略阻止：'{host}' 匹配规则 '{pattern}'（来源 {source}）` |

## 首参非字面量（需人工判定）

| 文件:行 | 表达式 |
|---|---|
| `agent/context_breakdown.py:289` | `f"gateway.usage.breakdown_cat_{cat_id}"` |
| `agent/conversation_loop.py:8621` | `_reasoning_key` |
| `agent/display.py:866` | `key` |
| `agent/display.py:867` | `key` |
| `agent/display.py:883` | `key` |
| `agent/display.py:927` | `f"display.tool_status.{tool_name}"` |
| `agent/display.py:937` | `f"display.tool_status.{tool_name}"` |
| `agent/display.py:939` | `f"display.tool_status.{tool_name}_verb"` |
| `cron/scheduler.py:3067` | `key` |
| `gateway/platforms/qqbot/keyboards.py:316` | `title_key` |
| `gateway/run.py:3991` | `key` |
| `gateway/run.py:18098` | `reject_key` |
| `gateway/slash_commands.py:5673` | `key` |
| `gateway/slash_commands.py:5774` | `f"gateway.usage.breakdown_cat_{cat_id}"` |
| `gateway/slash_commands.py:6300` | `f"gateway.approve.{choice}_{plural}"` |
| `tools/approval.py:72` | `full_key` |
| `tools/approval.py:3517` | `"approval.allowed_once" if decision == "once" else "approval.denied"` |
| `tools/approval.py:4657` | `key` |
| `tools/approval.py:4683` | `key` |
| `tools/approval.py:4952` | `key` |
| `tools/approval.py:6519` | `"approval.execute_code_timeout_denied"
                    if not resolved
                    else "approval.execute_code_user_denied"` |
