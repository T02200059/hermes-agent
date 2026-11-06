# image-hub 迁移 overlay / 官方 image-gen 能力

状态：**已调研，待实现**（2026-11-06；本轮未改生效插件、未重启）
依据：本仓 v2 `f3ed6e4055`；上游 `main` `44ec783afd1193afb7576d9c01d7fe9d18c87339`（`git ls-remote upstream`，2026-11-06 查）。

## 1. 结论

- 官方已有 `image_generate` / `ImageGenProvider`、provider 注册表、本地/URL 图源和缓存。可选 FAL、OpenAI（含自定义兼容端点）、Codex、xAI、Krea、DeepInfra、OpenRouter、Meta 等；配置走 **`config.yaml:image_gen`**，不是我们的 `overlay.yaml:owner.image_gen`。
- **没有能原样替换 image-hub 的上游 DashScope multimodal-generation provider**。当前 5 个预设 `qwen` / `qwen-pro` / `wan` / `wan2` / `image-edit`，不是「FAL 有 qwen-image」就能平移：模型 ID、协议、编辑能力、计费、已有密钥均可能变化。
- 官方 OpenAI 自定义端点**不能**直接替代 `https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation`：request/response schema 不同。换 FAL/OpenRouter 属于换供应商、端到端验收的后续方案，不应夹带在 YAML 迁移中。
- 飞书不需要另写发图逻辑：`image_generate` 的本地 `image` 结果由 `gateway/run.py` 自动转 `MEDIA:`，飞书 adapter 用 `MEDIA:/absolute/path` 上传。本次移原插件的配置/注册，不新增 owner 发图协议。

## 2. 本机现状

- `~/.hermes/plugins/image-hub/` 为独立用户插件，`plugins.enabled` 含 `image-hub`，`config.yaml:image_gen.provider=image-hub`。
- 真源 `~/.hermes/plugins/image-hub/__init__.py` 调不存在的 `hermes_constants.get_patch_owner_config()` 后，**总是回落直读** `~/.hermes/patch.yaml`（软链到老 `hermes-agent-owner/owner/config/patch.yaml`），取 `owner.image_gen.current/presets`。
- 其余 Hermes 配置走 `hermes_cli/config.py` 的 `owner.patch_config.apply_owner_overlay()`；overlay 可放在官方 `config["owner"]` 下，故不必创造另一套 yaml loader。
- 当前 `current=dashscope-qwen`，preset 未填 `mode` 时代码默认 `dashscope-message`；5 个 preset 都含 `api_key:${DASHSCOPE_API_KEY}` 引用。保留引用，不把 `.env` 值复制进 yaml。
- `image_generate.model` 目前不能出现在本地 `_build_dynamic_image_schema()` 动态 schema，旧 `owner/tools/schema_patches.py` 未迁进 v2。preset alias 要工作必须一起迁，不能只改配置位置。
- 插件源码/测试不在 v2 git 版本控制，部署靠本机直接写。直接原地改会再次偏离版本管理。

## 3. 推荐路径（保留 image_hub provider，换官方注册与 overlay）

### Phase A：配置读取与原能力迁移（本次目标）

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

## 4. 验收清单（未执行）

- [ ] overlay 读取；旧 `patch.yaml` 缺失、空、非法 YAML 仍不崩溃且不被读取。
- [ ] current = qwen 默认；全 5 preset name/alias 解析；不输出或记录 api_key。
- [ ] 4 类文本生图走 DashScope message；`image-edit` 接受最多 3 张图，本地源图通过 file_safety。
- [ ] 动态 `image_generate.model` schema 与 dispatch 一致；不支持自定义能力的 provider 不受影响。
- [ ] 插件注册开关可禁用；owner-extensions 无图像环境也可导入；现有测试回归。
- [ ] 生成结果落地 `$HERMES_HOME/cache`，Feishu adapter 走现有 image 上传；不硬编码消费 URL。
- [ ] 初次启用只做 dry-run / mock；付费生图不在本调研中进行。
- [ ] 生产新路径验收后移除 `~/.hermes/patch.yaml` 软链和陈旧插件。

## 5. 本轮边界

- **已迁 overlay 顶层 `image_gen`（作为待用配置，旧插件仍不读）**，已写设计与待办；**未改 image-hub、官方生图工具、`config.yaml`**。
- 本轮不使用付费 API，不发飞书、不重启。
- `config.yaml` 是生效后端路由阶段文件，不建议把 `owner.image_gen` 与 `image_gen.provider` 混写进 overlay（overlay 由 `apply_owner_overlay` 整体塞到 `config['owner']`）。

参考：
- 官方 Image Generation：https://hermes-agent.nousresearch.com/docs/user-guide/features/image-generation
- 官方 Image Generation Provider Plugins：https://hermes-agent.nousresearch.com/docs/developer-guide/image-gen-provider-plugin
