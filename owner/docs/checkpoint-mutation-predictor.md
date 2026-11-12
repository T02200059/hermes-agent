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

`owner/config/overlay.yaml` 的 `owner.checkpoints` 段：

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
├── config.py          # 读 overlay.yaml checkpoints 配置, fail-open
├── static_parser.py   # shlex + 正则提取文件路径
├── llm_predict.py     # LLM 兜底 (auxiliary 侧路)
└── predictor.py       # 编排器
```

## 接线

`agent/tool_executor.py` `_begin_tool_execution` 的 terminal 分支（write_file/patch 仍走官方 `_ensure_file_checkpoint`）：

```python
# [owner] checkpoint: terminal 预测式快照 (委托 owner/checkpoint_predictor)
from tools.file_tools_paths import container_backend_for_task
if container_backend_for_task(effective_task_id or "default") is None:
    from agent.runtime_cwd import scope_terminal_cwd
    from owner.checkpoint_predictor import predict_and_checkpoint
    command = function_args.get("command", "")
    cwd = function_args.get("workdir") or scope_terminal_cwd() or os.getcwd()
    predict_and_checkpoint(command, cwd, agent)
```

替换了官方的 `if _is_destructive_command(cmd): ensure_checkpoint(cwd)`。容器后端跳过（与官方一致）。

## 2026-11 降噪（基于 node010 7 天 1610 条 terminal 实测）

线上症状：只读命令（`sed -n`/`diff`/`grep`/`awk`/`ssh`/`docker logs`）被拍快照；
`awk '$1>2048'`、`awk 'NR>1'`、`echo "a -> b"` 里的 `>` 被当成重定向；
`2>/dev/null` 把根解析成 `/dev`；LLM 兜底对 `bash xxx.sh | grep` 猜出 `~/.ssh` 并整目录入 store；
`docker logs` / `echo` 这类命令发出"checkpoint 预测失败"飞书 tip。

四处改动：

1. **引号感知重定向** (`static_parser.scan_redirects`)：逐字符扫 `>`，引号内/转义不认，
   跳过 `>>`（既有契约）、`>&`、`>=`，丢弃 `/dev/null` 这类无回滚价值目标；
   支持一条命令多个目标（`> out 2> err`）。`static_parse` 改为按未加引号的
   `|`/`||`/`&&`/`;`/换行切段（`_split_segments`），多行 `cd && cp` 也能认出真目标。
2. **只读闸门** (`static_parser.is_read_only_command`)：静态为空且每个 segment 的主动词
   都在只读白名单（含 `timeout`/`sudo` 包装器剥离、`git`/`docker`/`kubectl`/`systemctl`
   子命令表、`xargs` 递归判定、`find -delete/-exec` 与 `awk print > "f"` 反向排除）
   → 直接 return：不调 LLM、不弹 tip。实测 LLM 调用 1070 → 698（-35%）。
3. **告警口径** (`static_parser.destructive_signal`)：tip 只看真实写信号
   （`rm`/`cp`/`mv`/`sed -i`/`find -exec`/引号外 `>`），不再复用官方 quote-blind 正则；
   实测"破坏性"判定 37% → 4.3%。
4. **凭据目录黑名单** (`predictor._SECRET_COMPONENTS`)：`.ssh`/`.aws`/`.gnupg`/`.kube`/`.docker`/`.password-store`
   不作为快照根，LLM 猜错也不会把私钥灌进 shadow store。

残留（有意保留）：`python3 script.py`、`bash script.sh`、`for` 循环、多段 `cd ... && mkdir`
无法静态判定写不写，仍走 LLM 兜底（约 43%），这是漏拍与误拍的折中点。
