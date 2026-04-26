# Hermes Agent 开发指南

AI 编码助手在 hermes-agent 代码库工作时的指导。

## 开发环境

```bash
source venv/bin/activate  # 运行 Python 前必须激活
```

## 项目结构

```
hermes-agent/
├── run_agent.py          # AIAgent 类 — 核心对话循环
├── model_tools.py        # 工具编排，发现内置工具，处理函数调用
├── toolsets.py           # 工具集定义
├── cli.py                # HermesCLI 类 — 交互式 CLI
├── hermes_state.py       # SessionDB — SQLite 会话存储
├── agent/                # Agent 内部模块
│   ├── prompt_builder.py     # 系统提示组装
│   ├── context_compressor.py # 自动上下文压缩
│   ├── prompt_caching.py     # Anthropic 提示缓存
│   ├── auxiliary_client.py   # 辅助 LLM 客户端（视觉、摘要）
│   ├── model_metadata.py     # 模型上下文长度
│   ├── models_dev.py         # models.dev 注册集成
│   ├── display.py            # KawaiiSpinner，工具预览
│   └── skill_commands.py     # Skill 斜杠命令
├── hermes_cli/           # CLI 子命令
│   ├── main.py           # 入口点
│   ├── config.py         # 默认配置
│   ├── commands.py      # 斜杠命令定义
│   ├── callbacks.py      # 终端回调（确认、sudo、批准）
│   ├── setup.py          # 交互式设置向导
│   ├── skin_engine.py   # 皮肤/主题引擎
│   ├── skills_config.py # 技能配置
│   ├── tools_config.py  # 工具配置
│   ├── models.py         # 模型目录
│   └── auth.py           # 凭据解析
├── tools/                # 工具实现
│   ├── registry.py       # 中央工具注册表
│   ├── approval.py       # 危险命令检测
│   ├── terminal_tool.py  # 终端编排
│   ├── file_tools.py     # 文件读写搜索
│   ├── web_tools.py      # 网页搜索/抓取
│   ├── browser_tool.py   # 浏览器自动化
│   ├── code_execution_tool.py # 代码执行沙箱
│   ├── delegate_tool.py  # 子代理委托
│   ├── mcp_tool.py       # MCP 客户端
│   └── environments/     # 终端后端（local, docker, ssh, modal, daytona）
├── gateway/              # 消息平台网关
│   ├── run.py            # 主循环，斜杠命令，消息分发
│   ├── session.py        # SessionStore — 会话持久化
│   └── platforms/       # 适配器：telegram, discord, slack, whatsapp, qqbot 等
├── ui-tui/               # Ink 终端 UI — `hermes --tui`
├── tui_gateway/          # Python JSON-RPC 后端
├── acp_adapter/          # ACP 服务器（VS Code / Zed / JetBrains）
├── cron/                 # 调度器
└── tests/                # Pytest 套件
```

**用户配置:** `~/.hermes/config.yaml`, `~/.hermes/.env`

## 文件依赖链

```
tools/registry.py → tools/*.py → model_tools.py → run_agent.py, cli.py
```

---

## AIAgent 类 (run_agent.py)

```python
class AIAgent:
    def __init__(self,
        model: str = "anthropic/claude-opus-4.6",
        max_iterations: int = 90,
        enabled_toolsets: list = None,
        disabled_toolsets: list = None,
        platform: str = None,           # "cli", "telegram" 等
        session_id: str = None,
        skip_context_files: bool = False,
        skip_memory: bool = False,
    ): ...

    def chat(self, message: str) -> str:
        """简单接口 — 返回最终响应字符串"""

    def run_conversation(self, user_message: str, system_message: str = None,
                         conversation_history: list = None) -> dict:
        """完整接口 — 返回包含 final_response + messages 的字典"""
```

### Agent 循环

核心循环在 `run_conversation()` 中 — 完全同步：

```python
while api_call_count < self.max_iterations:
    response = client.chat.completions.create(model=model, messages=messages, tools=tool_schemas)
    if response.tool_calls:
        for tool_call in response.tool_calls:
            result = handle_function_call(tool_call.name, tool_call.args)
            messages.append(tool_result_message(result))
    else:
        return response.content
```

消息格式遵循 OpenAI：`{"role": "system/user/assistant/tool", ...}`

---

## CLI 架构

- **Rich** 用于横幅/面板，**prompt_toolkit** 用于带自动补全的输入
- **KawaiiSpinner** (`agent/display.py`) — API 调用期间的动画表情
- 皮肤引擎 (`hermes_cli/skin_engine.py`) — 数据驱动的 CLI 主题定制
- 技能斜杠命令：`agent/skill_commands.py` 扫描 `~/.hermes/skills/`，注入为用户消息

### 斜杠命令注册

所有斜杠命令在 `COMMAND_REGISTRY` 中定义，自动派生到：
- CLI — `process_command()` 解析并分发
- Gateway — `GATEWAY_KNOWN_COMMANDS` 用于钩子
- Telegram — 生成 BotCommand 菜单
- Slack — 生成子命令路由
- 自动补全

### 添加斜杠命令

1. 在 `COMMAND_REGISTRY` 添加 `CommandDef`
2. 在 `cli.py` 添加处理器到 `process_command()`
3. 如果 Gateway 需要，在 `gateway/run.py` 添加处理器

---

## TUI 架构

TUI 通过 `hermes --tui` 或 `HERMES_TUI=1` 激活。

### 进程模型

```
hermes --tui
  └─ Node (Ink)  ──stdio JSON-RPC──  Python (tui_gateway)
       │                                  └─ AIAgent + tools + sessions
       └─ 渲染转录、输入、提示、活动
```

---

## 添加新工具

需要修改 **2 个文件**：

**1. 创建 `tools/your_tool.py`：**
```python
from tools.registry import registry

def check_requirements() -> bool:
    return bool(os.getenv("EXAMPLE_API_KEY"))

def example_tool(param: str, task_id: str = None) -> str:
    return json.dumps({"success": True, "data": "..."})

registry.register(
    name="example_tool",
    toolset="example",
    schema={"name": "example_tool", "description": "...", "parameters": {...}},
    handler=lambda args, **kw: example_tool(param=args.get("param", ""), task_id=kw.get("task_id")),
    check_fn=check_requirements,
    requires_env=["EXAMPLE_API_KEY"],
)
```

**2. 添加到 `toolsets.py`** — `_HERMES_CORE_TOOLS` 或新工具集

自动发现：任何带 `registry.register()` 调用的 `tools/*.py` 文件自动导入。

---

## 添加配置

### config.yaml 选项：
1. 添加到 `hermes_cli/config.py` 的 `DEFAULT_CONFIG`
2. 增加 `_config_version` 触发迁移

### .env 变量：
添加到 `OPTIONAL_ENV_VARS`：
```python
"NEW_API_KEY": {
    "description": "用途",
    "prompt": "显示名称",
    "url": "https://...",
    "password": True,
    "category": "tool",
},
```

---

## 皮肤/主题系统

皮肤引擎 (`hermes_cli/skin_engine.py`) 提供数据驱动的视觉定制。

**内置皮肤：**
- `default` — 经典金色/kawaii
- `ares` — 深红/青铜战神主题
- `mono` — 干净灰度单色
- `slate` — 冷蓝开发者主题

### 添加皮肤

内置皮肤添加到 `_BUILTIN_SKINS`，用户皮肤创建 `~/.hermes/skins/<name>.yaml`

---

## 重要政策

### 提示缓存不能破坏

不要实现以下更改：
- 中途改变过去上下文
- 中途切换工具集
- 中途重新加载记忆或重建系统提示

### 工作目录行为
- **CLI**: 当前目录
- **消息平台**: `MESSAGING_CWD` 环境变量（默认主目录）

---

## 多实例支持（Profiles）

Hermes 支持 profiles — 多个完全隔离的实例，每个有独立 `HERMES_HOME`。

### 规则

1. **使用 `get_hermes_home()`** — 不要硬编码 `~/.hermes`
2. **使用 `display_hermes_home()`** 用于用户面向消息
3. **模块级常量可以** — 在 `_apply_profile_override()` 后缓存

---

## 已知陷阱

- **不要硬编码 `~/.hermes`** — 使用 `get_hermes_home()`
- **不要用 `simple_term_menu`** — 使用 `curses`（stdlib）
- **不要用 `\033[K`** — 使用空格填充
- **测试不能写 `~/.hermes/`** — 使用 `tests/conftest.py` 的 `_isolate_hermes_home`

---

## 测试

**始终使用 `scripts/run_tests.sh`** — 不要直接调用 pytest

```bash
scripts/run_tests.sh                                  # 完整套件
scripts/run_tests.sh tests/gateway/                   # 单一目录
scripts/run_tests.sh tests/agent/test_foo.py::test_x  # 单一测试
```

### 为什么需要包装器

| | 无包装器 | 有包装器 |
|---|---|---|
| API 密钥 | 你的环境 | 全部 unset |
| HOME | 你的真实配置 | 临时目录 |
| 时区 | 本地 | UTC |
| 语言 | 本地 | C.UTF-8 |
| xdist workers | 所有核心 | 4（匹配 CI） |

始终在推送前运行完整套件。
