# Checkpoint Mutation Predictor

## 概述

owner-v17 的 checkpoint mutation predictor 替代了 main 的 `_is_destructive_command` + `ensure_checkpoint(cwd)` 无差别快照。

### main 的问题

main 的 `_is_destructive_command` 是正则启发式 —— 匹配到就对 **cwd** 整个目录拍快照。问题：

1. cwd 可能是 `~` 或超大目录 → 过度覆盖
2. 无法区分"命令改了哪个项目" → 误拍不相关项目
3. 正则粗糙 → 非破坏性命令也会误触发

### owner predictor 的做法

1. **静态解析** (shlex + 模式匹配)：提取命令将要修改的文件路径
   - `sed -i` → 目标文件
   - `cp/mv/install` → 目标路径
   - `rm/rmdir/shred` → 所有位置参数
   - `dd of=...` → of 值
   - `> file` 覆盖重定向 → 目标文件
   - `git reset/clean/checkout` → GIT_REPO_SENTINEL → cwd 项目根

2. **LLM 兜底** (当静态解析 < 阈值时)：
   - 复用 `agent.auxiliary_client.call_llm(task="approval")`
   - 同侧路，不进主 messages，prompt caching 不受影响
   - LRU 缓存 (command, cwd)，超时返回空列表
   - 配置：`owner.checkpoints.predict_llm_timeout_ms` (默认 3000ms，owner 配 20000ms)

3. **安全过滤**：预测路径 → `get_working_dir_for_path()` → 项目根
   - 丢弃 == `/` 或 == `~` 的根
   - 每个合法项目根只拍一次

4. **永不抛异常**：预测失败 → 报错回调 (如有)，不拍快照，不阻塞工具执行

## 配置

`owner/config/patch.yaml` 的 `owner.checkpoints` 段：

```yaml
owner:
  checkpoints:
    predict_enabled: true           # 总开关
    predict_llm_timeout_ms: 20000   # LLM 兜底超时 (ms)
    predict_cache_size: 32          # LRU 缓存大小
    predict_static_threshold: 1     # 静态解析 >= N 个候选就直接用
```

## 文件结构

```
owner/checkpoint_predictor/
├── __init__.py        # 导出 predict_and_checkpoint
├── config.py          # 读 patch.yaml checkpoints 配置, fail-open
├── static_parser.py   # shlex + 正则提取文件路径
├── llm_predict.py     # LLM 兜底 (auxiliary 侧路)
└── predictor.py       # 编排器
```

## 接线

`agent/tool_executor.py` 两个入口点 (主循环 + `_run_tool`)：

```python
# [owner] checkpoint: terminal 预测式快照
if function_name == "terminal" and agent._checkpoint_mgr.enabled:
    try:
        from owner.checkpoint_predictor import predict_and_checkpoint
        cmd = function_args.get("command", "")
        cwd = function_args.get("workdir") or os.getenv("TERMINAL_CWD", os.getcwd())
        predict_and_checkpoint(cmd, cwd, agent)
    except Exception:
        pass  # never block tool execution
```

替换了 main 的 `if _is_destructive_command(cmd): ensure_checkpoint(cwd)`。
