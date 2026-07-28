# Semantic Audit Gate 设计文档

> 位置：`owner/semantic_audit/`  
> 接入：`run_agent.py` → `AIAgent._execute_tool_calls` 薄胶水（`# [owner]`）  
> 状态：已实现（feat/semantic-audit）

## 1. 问题

现有 approval 只能逐个 block 危险命令。模型陷入激进幻觉时（用户说「看 nginx 状态」，模型执行 `systemctl restart nginx`），会换姿势绕路。需要在 **tool dispatch 之前** 增加语义层审计：用 cheap LLM 判断操作是否超出用户指令范围。

## 2. 架构

```
AIAgent._execute_tool_calls
        │
        ▼
  [owner] maybe_audit_batch()     ← 仅此 1 处官方胶水（≤5 行 + fail-open）
        │
        ├─ detector.classify_batch   Tier 0 hardline / Tier 1 pattern / skip
        ├─ auditor.audit_tier1_calls call_llm(task="semantic_audit")
        ├─ policy.strike / merge     BLOCK→HALT 升级、session 隔离
        └─ notify + synthetic results + agent.interrupt()（仅 HALT）
```

### 三档 verdict

| Verdict | 行为 |
|---------|------|
| **PASS** | 放行 |
| **BLOCK** | 拒绝本次 call，注入 synthetic error；模型可继续迭代（strike +1 / batch） |
| **HALT** | 拒绝 + `agent.interrupt()`，整批所有 tool_call_id 注入 result，不给绕路机会 |

### Strike 升级

- 第 1 次 batch 出现 BLOCK → 警告（仍 BLOCK）
- 第 2 次（`max_strikes: 2`）→ 升级为 HALT
- Hardline（reboot / `rm -rf /` / mkfs / dd / DROP…）直接 HALT，不累计 strike
- 存储：模块级 `dict + threading.Lock`，key = `session_id or id(agent)`，turn_id 变化重置，TTL 30min

## 3. Tier 检测

| Tier | 条件 | 动作 |
|------|------|------|
| 0 Hardline | `detect_hardline_command` + 额外 DROP/TRUNCATE 等 | 直接 HALT，yolo 不可旁路 |
| 1 Pattern | `detect_dangerous_command`；`write_file`/`patch` 写到 `/etc/`、systemd、crontab、`authorized_keys` 等 | LLM 审计 |
| skip | `read_file` / `web_search` / `search_files` 等只读 | 不审计 |

审计前对 Tool Search 桥 `tool_call` 做 `resolve_underlying_call` unwrap。

## 4. LLM 审计

- API：`agent.auxiliary_client.call_llm(task="semantic_audit", …)` 同步
- 超时：默认 5s（`auxiliary.semantic_audit.timeout`）
- 输入：
  - 最近 2–3 条用户指令（截断 300 字）
  - assistant text（500 字）
  - `proposed_tool_calls`：本批 tier1（需裁决）
  - `batch_siblings`：本批**全部** tool_call（含 skill_view / read_file 等 skip）
  - `skill_context`：本批或近期 `skill_view` 的 skill 正文（同源 `tools.skills_tool.skill_view`，截断 ~3k）
  - `already_executed_tools`：历史 tool 摘要（skill_view 预览更长）
- 输出：`{"verdicts":{"<id>":{"verdict":"PASS|BLOCK|HALT","reason":"..."}}}`（仅 proposed ids）
- **SOP 防误判**：skill_context 视为主 agent 正在遵循的流程；与用户意图一致时优先 PASS
- **fail 策略**：超时/失败时，tier1（已标危险）→ BLOCK（fail-closed）；skip 工具不调用 LLM（等价 PASS）

压缩安全：首次审计时把 user 指令快照挂到 `agent._semantic_audit_user_snapshot`，避免只依赖可能被压缩的 messages。

## 5. 配置

用户 `config.yaml`（官方 DEFAULT_CONFIG 不改，缺省用 owner 内置默认）：

```yaml
auxiliary:
  semantic_audit:
    provider: "auto"
    model: "auto"
    timeout: 5

semantic_audit:
  enabled: true
  max_strikes: 2
  cron_enforce: true
  respect_yolo: false   # yolo 不关闭语义审计
```

## 6. 与其他路径的关系

| 场景 | 行为 |
|------|------|
| yolo | 默认仍审计；hardline 始终阻断 |
| cron | 默认 enforce（`cron_enforce: true`） |
| subagent | 独立 agent 实例 → 独立 session_key；child `interrupt` 不影响 parent |
| 删除 owner 包 | import 失败 → fail-open，核心零影响 |

## 7. 官方文件改动

仅 `run_agent.py` `_execute_tool_calls` 内：

```python
# [owner] semantic audit gate (see owner/semantic_audit/)
try:
    from owner.semantic_audit import maybe_audit_batch
    if maybe_audit_batch(self, assistant_message, messages, effective_task_id):
        return
except Exception:
    pass  # fail-open
```

BLOCK 过滤采用 **in-place** 修改 `assistant_message.tool_calls`，保证调用方局部别名一致。

## 8. 文件布局

```
owner/semantic_audit/
├── __init__.py      # maybe_audit_batch 导出
├── gate.py          # 编排
├── detector.py      # Tier 0/1
├── auditor.py       # prompt + call_llm + 解析
├── policy.py        # strike / 决策
├── notify.py        # 文案
├── config.py        # 配置读取
└── tests/
    └── test_semantic_audit.py
```

## 9. 测试

```bash
scripts/run_tests.sh owner/semantic_audit/tests/test_semantic_audit.py -q
# 或
scripts/run_tests.sh tests/owner/  # 若复制/软链到 tests/
```

当前测试文件位于 `owner/semantic_audit/tests/`，可用 pytest 直接指向该路径。
