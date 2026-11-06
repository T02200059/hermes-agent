# Image Hub

DashScope multimodal-generation 与 OpenAI 兼容生图后端。保留原协议、凭据引用、本地图安全检查与图片缓存，不改供应商。

## 配置

- `overlay.yaml` 顶层 `image_gen.current / presets`；`config.yaml:image_gen.provider=image-hub`。
- 默认 `dashscope-qwen`。五组 preset name / alias：`dashscope-qwen` (`qwen`)、`dashscope-qwen-pro` (`qwen-pro`)、`dashscope-wan` (`wan`)、`dashscope-wan2-pro` (`wan2`)、`dashscope-image-edit` (`image-edit`)。
- yaml 只保留 `${ENV_VAR}` 引用，不复制或打印凭据。旧 `patch.yaml` fallback 已删除。
- `ImageGenProvider.tool_parameter_overrides()` 让动态 schema 声明可选 `model`；name / alias 切换整组 preset，其他字符串仅覆盖模型 id。
- `image-edit` 的主图与参考图总计最多三张；本地图先经过 file-safety，再转 data URI。结果继续落 `$HERMES_HOME/cache/generated/images`，飞书沿用现有 `MEDIA:` 链路。

## 本机部署（2026-11-06）

- 用户级 backend：`~/.hermes/plugins/image-hub` 为指向仓内绝对路径 `owner/image_hub` 的目录 symlink，仍受 `plugins.enabled` 独立开关控制。不要放入 bundled `plugins/`，以免绕过用户级开关。
- 旧实现归档到 `~/.hermes/backups/image-hub-pre-overlay-20261106-113253`，不在插件扫描目录。
- **软重启 gateway 后才生效；本轮未重启、未发付费生图、未发飞书图片。** 旧进程仍持有旧代码，运行期间 `~/.hermes/patch.yaml` 软链保留。
- reload 出现错误时关闭 `image-hub` 插件或软重启，再用存档恢复插件路径；恢复后需再次软重启。新配置无需回滚凭据。

## 验收范围

`tests/owner/test_image_hub_overlay.py` 用隔离 HERMES_HOME、占位凭据和 mock 网络覆盖 overlay、五预设、动态 `model` 实际透传、安全本地图、缓存、独立插件发现和启停。不会改变 provider 的可选扩展接口不影响其他 backend。

```bash
bash scripts/run_tests.sh tests/owner/test_image_hub_overlay.py \
  tests/owner/test_patch_config.py \
  tests/tools/test_image_generate_schema.py \
  tests/tools/test_image_generation_plugin_dispatch.py \
  tests/tools/test_image_generation_image_to_image.py
```
