# Checkpoint Mutation Predictor

## 背景

`/rollback` 原本只在 `write_file`/`patch` 和"命中 `_is_destructive_command` 正则的 terminal 命令"前触发 `ensure_checkpoint`,且后者拍的是**整个 cwd**。

两个问题:
1. **盲区**: `python -c "open().write()"`、`tee`、`perl -i`、`npm run build` 等不命中正则的命令,改动逃逸出快照,`/rollback` 无能为力。
2. **过度覆盖**: 即便命中正则,拍整个 cwd 在 cwd 是 home/超大目录时有过度快照风险,连带 `_enforce_size_cap` 把其它项目的快照挤出 store。

## 方案

预测式触发源(非文件系统 watcher): terminal 工具执行前,静态解析命令提取目标文件 → 失败时 LLM 兜底 → 对预测出的文件所在项目根 `ensure_checkpoint`。

### legacy 分支停用说明

`agent/tool_executor.py` 两处 `_is_destructive_command(cmd)` + `ensure_checkpoint(cwd, ...)` 分支已**删除**(2026-06-19)。原因:
- 无差别快照整个 cwd 有过度覆盖风险
- 预测器静态层已覆盖其全部 pattern,且按文件定位
- `predict_enabled=false` 时 terminal 宁可不拍也不乱拍

`_is_destructive_command` 函数本身保留(在 `agent/tool_dispatch_helpers.py`),只是不再被 terminal checkpoint 分支调用。

### 失败降级

预测失败(静态空 + LLM 超时/失败/空 + 安全过滤后无合法 root)时:
- **不拍任何快照**
- 通过 adapter 报错,明示"该命令改动无法被 /rollback 回滚"
- **绝不降级拍 cwd**(过度覆盖风险)

### 配置

`owner/checkpoints`(patch.yaml):
- `predict_enabled`: 总开关(默认 true)
- `predict_llm_timeout_ms`: LLM 超时(默认 3000)
- `predict_cache_size`: 会话内 LRU(默认 32)
- `predict_static_threshold`: 静态阈值(默认 1)

### LLM 模型

复用 `auxiliary_client.call_llm(task="approval")`,即和 smart approval 同一条侧路、同一个模型(默认=主聊天模型)。零新配置面。

### 已知边界

- MCP/plugin 工具改文件: 不覆盖(需在 MCP 调度层单独 hook)
- 跨进程后台写入(`nohup ... &`): 不覆盖(需常驻 watcher)
- 动态目标(`os.rename('a', os.environ['X'])`): LLM 可能预测不出,降级报错

详见 `docs/superpowers/specs/2026-06-19-checkpoint-mutation-predictor-design.md`
