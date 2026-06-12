# Skins 目录说明

## 皮肤文件

| 文件 | 切换命令 | 特点 |
|------|---------|------|
| `ruolin.yaml` | `/skin ruolin` | 樱花粉、自定义 spinner 表情/动词/翅膀、品牌名 |
| `ruolin-light.yaml` | `/skin ruolin-light` | 基于 ruolin 的浅色变体，适配浅色终端 |

## 使用方式

将皮肤文件软链接到 `~/.hermes/skins/`：

```bash
ln -sf ~/projects/ai/hermes-agent/owner/skins/ruolin.yaml ~/.hermes/skins/ruolin.yaml
ln -sf ~/projects/ai/hermes-agent/owner/skins/ruolin-light.yaml ~/.hermes/skins/ruolin-light.yaml
```

然后在 CLI 中执行 `/skin ruolin` 或在 `config.yaml` 中设置 `display.skin: ruolin`。

## 设计原则

与 `owner/scripts/` 和 `owner/config/` 一致：物理文件放 `owner/skins/`，随 git 仓库迁移；`~/.hermes/skins/` 下通过软链接指向。
