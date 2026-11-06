# image-hub 迁移 overlay / 官方 image-gen 能力

状态：**代码 / mock / 隔离发现已完成，待软重启与生产验收**（2026-11-06；未重启，未做付费生图）
依据：本仓 v2 `f3ed6e4055`；上游 `main` `44ec783afd1193afb7576d9c01d7fe9d18c87339`（`git ls-remote upstream`，2026-11-06 查）。

## 1. 结论

- 官方已有 `image_generate` / `ImageGenProvider`、provider 注册表、本地/URL 图源和缓存。可选 FAL、OpenAI（含自定义兼容端点）、Codex、xAI、Krea、DeepInfra、OpenRouter、Meta 等；配置走 **`config.yaml:image_gen`**，不是我们的 `overlay.yaml:owner.image_gen`。
- **没有能原样替换 image-hub 的上游 DashScope multimodal-generation provider**。当前 5 个预设 `qwen` / `qwen-pro` / `wan` / `wan2` / `image-edit`，不是「FAL 有 qwen-image」就能平移：模型 ID、协议、编辑能力、计费、已有密钥均可能变化。
- 官方 OpenAI 自定义端点**不能**直接替代 `https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation`：request/response schema 不同。换 FAL/OpenRouter 属于换供应商、端到端验收的后续方案，不应夹带在 YAML 迁移中。
- 飞书不需要另写发图逻辑：`image_generate` 的本地 `image` 结果由 `gateway/run.py` 自动转 `MEDIA:`，飞书 adapter 用 `MEDIA:/absolute/path` 上传。本次移原插件的配置/注册，不新增 owner 发图协议。

## 2. 迁移前现状（历史基线）

- `~/.hermes/plugins/image-hub/` 为独立用户插件，`plugins.enabled` 含 `image-hub`，`config.yaml:image_gen.provider=image-hub`。
- 真源 `~/.hermes/plugins/image-hub/__init__.py` 调不存在的 `hermes_constants.get_patch_owner_config()` 后，**总是回落直读** `~/.hermes/patch.yaml`（软链到老 `hermes-agent-owner/owner/config/patch.yaml`），取 `owner.image_gen.current/presets`。
- 其余 Hermes 配置走 `hermes_cli/config.py` 的 `owner.patch_config.apply_owner_overlay()`；overlay 可放在官方 `config["owner"]` 下，故不必创造另一套 yaml loader。
- 当前 `current=dashscope-qwen`，preset 未填 `mode` 时代码默认 `dashscope-message`；5 个 preset 都含 `api_key:${DASHSCOPE_API_KEY}` 引用。保留引用，不把 `.env` 值复制进 yaml。
- `image_generate.model` 目前不能出现在本地 `_build_dynamic_image_schema()` 动态 schema，旧 `owner/tools/schema_patches.py` 未迁进 v2。preset alias 要工作必须一起迁，不能只改配置位置。
- 插件源码/测试不在 v2 git 版本控制，部署靠本机直接写。直接原地改会再次偏离版本管理。

## 3. 采用方案（已实施）

### Phase A：配置读取与原能力迁移（已完成代码）

1. **收管源码**：把 image-hub 迁为 `owner/image_hub/`，Python 包、README、测试与现有行为同迁；不从官方 `agent/`、`gateway/` 增加新文件。保持 `ImageGenProvider` 协议及本地图安全检查、缓存和超时。
2. **取 overlay**：读取 `owner.patch_config.load_owner_config()['image_gen']`（`owner.image_gen` 的 v2 扁平形态）；或 `hermes_cli.config` 的 `config['owner']['image_gen']`。删除 `get_patch_owner_config` 与直读 `patch.yaml` fallback，避免两份来源与各自缓存。测试用临时 HERMES_HOME，不能读生产凭据。
3. **标准注册**：仍 `ctx.register_image_gen_provider(ImageHubProvider())`。将 provider 注册挂在 `owner/owner-extensions` 的独立、fail-open 子模块，或经官方用户级 backend 插件加载 `owner/image_hub`；不得让 owner-extensions 聚合器 import 图像 SDK 失败影响无关 hooks。
4. **alias 透传**：最小 P1 官方 `_build_dynamic_image_schema()` 委托/容纳 provider 自定义 schema 扩展；全部 alias 逻辑留在 `owner/image_hub/schema.py`。需兼容 `IMAGE_GENERATE_SCHEMA` 与动态 schema 的实际 dispatch 路径，避免「静态改了但动态把它覆盖」。禁止恢复老 owner 分支的大段 schema_patches。
5. **复制配置**：把老 `owner.image_gen` 的 **内容**放 v2 `owner/config/overlay.yaml` 的 **顶层 `image_gen:`**（无外层 `owner:`），保留 `current/presets` 与 env var 引用。
6. **验收再撤依赖**：测试默认、每个 preset name/alias、i2i 本地路径安全检查、生成图缓存与 Feishu media 上传；待新代码上线并验证后删除/解绑 `~/.hermes/patch.yaml` 与旧 image-hub。除非再次全仓运行时代码和用户插件扫描证明无读者，不把「无读者」当结论。
7. **生效条件**：provider/schema 变更需软重启；本轮明确不重启。加载新配置前旧进程仍走老目录，以旧配置作只读过渡，不删文件。

### Phase B：选做，验证后再考虑全官方 provider

- 优先评估 FAL 的官方 Qwen 模型或 OpenRouter 的 Qwen image 3 pro；改官方 `config.yaml:image_gen.provider/model`。
- 必须分别 smoke 文生图、`image-edit`、飞书投图，并核计费/模型可用性。现有 `model='qwen-pro'/'wan'` 是**跨 provider preset 路由**，并不等于官方 `image_gen.model` 全部语义；若无可控 alias 层须显式记录行为差异，由用户拍板。
- 若继续用现阿里端点和 DashScope key，**停止 Phase B**：保留小 provider 比改 API 或换供应商更合理。

## 4. 验收结果（2026-11-06）

已完成：

- [x] overlay 读取；缺失、非法 overlay fail-open，新代码无 `patch.yaml` fallback。
- [x] 默认 qwen 与五组 preset name / alias 解析；隔离测只使用占位凭据，不打印实际密钥。
- [x] 四类文本生图的模型解析与 DashScope mock payload；`image-edit` 主图和 refs **合计**最多三张，本地图先过 file-safety，再转 data URI。
- [x] 动态 `image_generate.model` schema 和实际 dispatch 一致；未声明扩展的旧 provider 行为不变。
- [x] `$HERMES_HOME/cache/generated/images` 缓存与 URL→本地结果语义保留；官方 gateway 仍将本地 `image` 转 `MEDIA:`，飞书无需新增代码。
- [x] 用户级 backend 官方 `PluginManager.discover_and_load()` 与 disabled gate，和 owner-extensions 共存；隔离 HERMES_HOME 验证，不接触实际密钥。迁移及官方生图 / overlay 相关 **43 测通过**（最终代码）。
- [x] `~/.hermes/plugins/image-hub` 已改为指向仓内 `owner/image_hub` 的绝对目标目录链接，保留独立 `plugins.enabled` 开关。旧目录归档至 `~/.hermes/backups/image-hub-pre-overlay-20261106-113253`，不在插件扫描目录下。

待办 / 边界：

- [ ] **需软重启 gateway**：当前进程持有旧 provider 代码。新 provider 读取、schema / dispatch 与插件启停均要软重启后生效。本轮未重启。
- [ ] 软重启后做实际插件注册 / schema 检查、mock 生图与真实飞书投图验收；付费真实生图本轮未执行。
- [ ] **本轮不能撤 `~/.hermes/patch.yaml` 软链**：旧进程在重启前仍可能读取它。软重启及生产验收后再核运行时读者，最后解绑。
- [ ] `owner/patch_config.py` 改用仓内 `utils.fast_safe_load`（项目锁定 ruamel 的 YAML 支持），修正规 runner 中原有 overlay 测失败；未新增依赖。

部署回滚：将原插件目录从上述备份恢复为 `~/.hermes/plugins/image-hub` 后软重启；新版配置没有迁移或复制凭据，无需改 key。

参考：

- 原设计与前述结论保留，验证范围以本节实测为准。
 官方 Image Generation：https://hermes-agent.nousresearch.com/docs/user-guide/features/image-generation
- 官方 Image Generation Provider Plugins：https://hermes-agent.nousresearch.com/docs/developer-guide/image-gen-provider-plugin
