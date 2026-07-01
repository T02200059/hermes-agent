# HERMES_CRON_SESSION ContextVar Isolation Fix

## 根因

`cron/scheduler.py:run_job()`  historically wrote `os.environ["HERMES_CRON_SESSION"] = "1"` once at job start. Because `os.environ` is process-global, the marker leaked across concurrent/sequential scheduler worker threads and into the gateway restart watcher environment, causing non-cron contexts to be mis-identified as cron sessions.

## 修复方案

将 `HERMES_CRON_SESSION` 从进程级环境变量迁移到 `contextvars.ContextVar`，并在 `run_job()` 的 try/finally 中 set/reset，实现 per-context 隔离：

- `owner/cron/session_context.py` 创建 `_CRON_SESSION` ContextVar，并在模块加载时将其注册到 `gateway.session_context._VAR_MAP`。
- `owner/cron/run_job_hook.py` 提供 `owner_cron_session_enter()` / `owner_cron_session_exit()`，分别设置和重置 ContextVar，并在退出时防御性地清理 `os.environ`。
- `owner/cron/approval_helper.py` 提供 `owner_cron_is_active()`，通过 `get_session_env("HERMES_CRON_SESSION", "")` 读取，优先 ContextVar、回退到 `os.environ`。
- `owner/cron/restart_scrub.py` 提供 `owner_cron_scrub_watcher_env()`，清除重启 watcher env 中的 `HERMES_CRON_SESSION` / `HERMES_SESSION_KEY` / `HERMES_SESSION_ID`；并提供 `owner_cron_scrub_process_env()`，在 gateway 进程启动时清理 *自身* `os.environ` 中继承来的同名标记。

官方源码只保留薄胶水：

- `cron/scheduler.py`：把 `os.environ["HERMES_CRON_SESSION"] = "1"` 替换为 inline import + `owner_cron_session_enter()`；在 finally 末尾调用 `owner_cron_session_exit()`。
- `tools/approval.py`：新增 `_is_cron_session()` 薄函数（inline import 到 owner helper），并替换 4 处 `env_var_enabled("HERMES_CRON_SESSION")` 调用。
- `gateway/run.py`：在 restart watcher 构建 `watcher_env` 后 inline import 并调用 `owner_cron_scrub_watcher_env()`；并在进程启动设置 `_HERMES_GATEWAY` 标记后调用 `owner_cron_scrub_process_env()`，清除从启动环境继承的 `HERMES_CRON_SESSION`（见下方“硬化补充”）。
- `gateway/session_context.py`：在文件末尾增加 guarded import `import owner.cron.session_context`，触发 `_CRON_SESSION` 运行时注入 `_VAR_MAP`。import 失败时**记录 warning**（而非静默吞掉）——注册被跳过会让 `get_session_env` 静默回退到 `os.environ`、cron 审批模式失效，这类安全相关的缺口必须可见。删除 owner/cron 后该 import 仍不影响 `gateway.session_context` 的加载。

## 涉及的 owner/ 文件

```
owner/cron/
├── __init__.py              # 导入所有子模块，触发 ContextVar 注册
├── session_context.py       # 注册 _CRON_SESSION 到 _VAR_MAP
├── run_job_hook.py          # run_job() 的 set/reset token 钩子
├── approval_helper.py       # _is_cron_session() 实现
└── restart_scrub.py         # restart watcher 的 env scrub helper
```

## 硬化补充（对抗性 review 后）

迁移本身正确(approval 在 `run_job` 的 copied context 内 in-process 运行，ContextVar 经 `copy_context()` 正确传播)。后续 review 又补了三处加固:

1. **os.environ fallback 陷阱(启动期)**：迁移删掉了 writer，但 `get_session_env`/`owner_cron_is_active` 仍保留对 `os.environ` 的回退(供外部插件/hook 直接设置时使用)。若 `HERMES_CRON_SESSION` 出现在 gateway **启动时继承的环境**(operator / wrapper / systemd / `.env`)，则每条 context 未设 cron 变量的真人消息都会回退命中它 → 全进程被当成 cron → 审批被 auto-deny/approve。`restart_scrub` 只覆盖了 restart 路径，故新增 `owner_cron_scrub_process_env()` 在启动时清理自身 `os.environ`，关闭这条路径。fallback 本身保留(契约不变)。
2. **注册失败可见性**：`gateway/session_context.py` 的 guarded import 由静默吞掉改为 `logging.warning(exc_info=True)`。
3. **子进程是否依赖该 env 标记 —— 结论：不依赖。** 全仓搜索(`.py/.sh/.json/.yaml/.toml/.md`)确认除 `owner/cron/*`、`gateway/*`、本文档、`tests/conftest.py` 清理列表外，**无任何脚本/子进程/子代码读取 `HERMES_CRON_SESSION`**。唯一跨进程传播途径是旧的 `os.environ` 泄漏；`cron/scheduler.py:_run_job_script()` 的 `subprocess.run(... )` 不传 `env=`(继承 `os.environ`)。按设置点排序:
   - `no_agent` 作业在 `run_job` 短路返回(早于 ContextVar/旧 env 写入点)→ **新旧代码下脚本都从未见过该标记**,行为零变化;
   - prerun 脚本同样早于写入点运行,旧代码下仅因跨作业泄漏(即 bug 本身)*偶然*命中,新代码使其确定性地不再出现 → **更正确**。
   
   唯一理论残留:若有 cron 脚本**嵌套调起 `hermes` agent**并期望 cron 审批模式 —— 该模式从来只靠泄漏偶然生效,仓内无此实例。如确需,正解是对该次 spawn 显式传 `env={**os.environ, "HERMES_CRON_SESSION": "1"}`,而非进程级写入。

## 二次开发规范符合度自检

对照 `owner/docs/二次开发规范.md` 第六节 Checklist：

- [x] 这个功能**能用 hook 实现吗**？——不能；需要替换 `run_job()` 和 approval 中的具体读取/写入点，但已把核心逻辑抽到 `owner/`。
- [x] 核心逻辑是否全部放在 `owner/` 下？官方文件是否只剩薄薄的 import + 委托？——是。
- [x] 对于 schema、常量、方法体等官方定义，是否采用“官方源码保持原样 + owner/ 运行时 patch”的方式？——`_CRON_SESSION` 在 `gateway/session_context.py` 中未定义，由 `owner/cron/session_context.py` 运行时注入 `_VAR_MAP`；`_VAR_MAP` 的字面定义保持上游原样。
- [x] 官方文件里的改动处是否都加了 `# [owner] ` 短标记？——是。
- [x] 新文件是否放在了 `owner/` 下？——是。
- [x] 是否在 `owner/docs/` 下补充了设计文档？——是（本文件）。
- [x] 删除这个功能对应的 owner/ 子目录后，其余功能和官方代码能否正常运行？——删除后 `gateway.session_context`、`cron.scheduler`、`tools.approval` 仍可 import；运行时调用薄胶水会抛出清晰的 `ImportError`/`ModuleNotFoundError`。
- [x] 这个改动 sync fork 时会不会产生 merge 冲突？官方文件的字面 diff 是否已经最小化？——每个官方文件只有 1~3 行薄胶水 + 标记，`gateway/session_context.py` 仅追加一个 guarded import，冲突面极小。

## 验收命令

```bash
cd ~/.hermes/hermes-agent
source .venv/bin/activate 2>/dev/null

# 静态检查
python -c "from owner.cron.session_context import _CRON_SESSION; print('OK owner session_context')"
python -c "from owner.cron.run_job_hook import owner_cron_session_enter, owner_cron_session_exit; print('OK owner run_job_hook')"
python -c "from owner.cron.approval_helper import owner_cron_is_active; print('OK owner approval_helper')"
python -c "from owner.cron.restart_scrub import owner_cron_scrub_watcher_env; print('OK owner restart_scrub')"

# 官方代码仍可 import（owner/cron 注入后）
python -c "from gateway.session_context import _VAR_MAP; assert 'HERMES_CRON_SESSION' in _VAR_MAP; print('OK gateway session_context with owner injection')"
python -c "from cron.scheduler import run_job; print('OK scheduler')"
python -c "from tools.approval import _is_cron_session; print('OK approval')"

# 跑所有相关测试
pytest tests/tools/test_cron_session_contextvar_isolation.py -v
pytest tests/tools/test_cron_approval_mode.py tests/tools/test_execute_code_approval_cluster.py -v
```
