# 英文回复中文解说（english_explainer）

> 状态：已实现（代码落盘；需进程重新加载 owner-extensions 后生效；本次不重启 gateway）
> 对应清单：§7.26

## 1. 背景

`display.language: zh` 时，agent 仍可能偶发整段英文终局回复。用户需要一条与「进度旁白」同形态的系统提示，给出基于上下文的中文解说，并在飞书升为 notice 卡。

## 2. 约束

1. **顶级约束**：仅当 `agent.i18n.get_language()` 以 `zh` 开头时才可能触发。
2. **配置只在** `patch.yaml → owner.english_explainer.*`，不污染 `config.yaml`。
3. **代码默认 `enabled: false`**；本机实配 `true`，`model: xy-flash`（`provider: damodel`）。
4. **模型语义**：空 / `auto` → `call_llm(task="english_explainer")` auxiliary auto 链；显式值直连。
5. **不改写原英文回复**（`transform_llm_output` 始终 `return None`）。
6. **零重启热读**：开关/模型走 `load_patch_config` mtime 缓存；notice 标题可走 `feishu_card.notice_titles`。

## 3. 判定

`owner/english_explainer/detect.py`：剥离代码块后，用英文虚词/语气词密度 + 低中文占比，区分「夹英文术语」与「整段英文」。思路对齐 `owner/scripts/viking_memory_lib.detect_non_chinese` 的 english_heavy 分支，但自包含、不依赖扫描脚本。

## 4. 接线

- `pre_gateway_dispatch`：缓存 gateway adapters，记录 session→(platform, chat_id)
- `transform_llm_output`：判定后后台线程翻译 + `adapter.send(PREFIX+译文)`
- 飞书：`PREFIX = "🔤 系统提示："` 命中 notice 规则 → 标题「🔤 英文解说」

## 5. 模块

`owner/english_explainer/`：`config` / `detect` / `prompt` / `explain` / `hook` / `__init__`

## 6. 验证

- 单测：`tests/owner/test_english_explainer.py`（判定/配置/前缀钉死/hook 不改原文）
- E2E（真网关偶发英文回复）[未验证]；全新 hook 需进程加载后生效
