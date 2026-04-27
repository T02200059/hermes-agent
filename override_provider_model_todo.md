# Override Provider Model Patch Todo

## 背景

`override_provider_model.yaml` 现在改为仅做“平台 -> provider/model”的覆盖补丁，不再重复保存 `api_key`、`base_url`、`context_length`、完整模型目录等基础信息。

当前职责拆分建议：

- `config.yaml`
  - 继续作为 Hermes 主配置源
  - 保存全局默认 `model.provider` / `model.default`
  - 保存 `providers`、`custom_providers`、gateway 配置、tool 配置等
- `override_provider_model.yaml`
  - 只保存平台级 provider/model patch
  - 不保存 provider 基础连接信息
- `gateway.json`
  - 仅保留 legacy gateway fallback
  - 逐步退出 provider/model 路由职责

## 目标

- 新增一条平台级 provider/model 覆盖链路
- 保持现有 `config.yaml` 逻辑可回退
- 不破坏 session `/model` 临时切换
- 让 CLI、TUI、Gateway、API Server 至少能命中统一的平台 patch 规则

## 推荐优先级

1. session `/model` override
2. `override_provider_model.yaml`
3. `config.yaml.model.provider` + `config.yaml.model.default`
4. `HERMES_INFERENCE_PROVIDER` / 其他 env fallback
5. auto provider detection

## Todo

- [ ] 明确 patch 文件最终 schema
  - 建议使用：
    - `default.provider`
    - `default.model`
    - `platforms.<platform>.provider`
    - `platforms.<platform>.model`

- [ ] 新增独立加载模块
  - 建议新增 `hermes_cli/provider_model_override.py`
  - 负责读取 `~/.hermes/override_provider_model.yaml`
  - 负责 YAML 校验、平台匹配、默认值回退
  - 输出统一结果：`provider`、`model`

- [ ] 在 Gateway 主链路接入平台 patch
  - 目标函数：`gateway/run.py::_resolve_session_agent_runtime()`
  - 顺序：先 session override，再平台 patch，再全局 runtime provider

- [ ] 在 Gateway 全局 model 解析处接入平台 patch
  - 目标函数：`gateway/run.py::_resolve_gateway_model()`
  - 避免 Gateway 仍只看 `config.yaml.model.default`

- [ ] 在 API Server 路径接入平台 patch
  - 目标文件：`gateway/platforms/api_server.py`
  - `platforms.api_server.extra.model/provider` 保留兼容，但不再作为主入口

- [ ] 在 CLI 路径接入 `cli` 平台 patch
  - 目标文件：`cli.py`
  - 确保普通 CLI 会话能命中 `platforms.cli`

- [ ] 在 TUI 路径接入 `tui` 平台 patch
  - 目标文件：`tui_gateway/server.py`
  - 现有 TUI 直接读取 `config.yaml.model`，需要改为优先读取 patch

- [ ] 决定 Cron 是否纳入 patch 规则
  - 如果纳入：修改 `cron/scheduler.py`
  - 如果不纳入：明确文档说明 cron 仍走全局 `config.yaml`

- [ ] 处理 `context_length` 的来源策略
  - 当前 patch 文件不再保存 `context_length`
  - 需要明确 built-in provider / `config.yaml.providers` / custom provider 的优先级

- [ ] 明确 `/model` 的持久化行为
  - 继续只写 `config.yaml.model.*`
  - 还是新增“写回 patch 文件”的能力
  - 需要避免“保存成功但平台 patch 覆盖后看起来没生效”的混乱

- [ ] 增加测试
  - patch 文件解析与校验
  - 平台 fallback 到 `default`
  - Gateway 命中 `feishu/wecom/weixin/api_server`
  - CLI 命中 `cli`
  - TUI 命中 `tui`
  - patch 文件不存在时回退到 `config.yaml`

## 实施顺序

1. 先完成 patch 文件 schema 和加载模块
2. 再接入 Gateway 主链路和 API Server
3. 再接入 CLI / TUI
4. 最后处理 cron、`/model` 持久化、测试与文档

## 本阶段边界

当前阶段只调整设计文档和 YAML 示例：

- 不修改 Python 代码
- 不改现有 runtime 行为
- 不迁移 `config.yaml.providers` 语义
