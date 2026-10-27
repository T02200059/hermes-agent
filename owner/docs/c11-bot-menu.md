# C11-bot-menu · 飞书 Bot 菜单

> 状态：**已落地**（阶段三）

## 做什么

飞书 bot 自定义菜单点击（`application.bot.menu_v6`）映射为会话内斜杠命令或提示词，并带三层去重与即时 ack。

## 入口

| 层 | 路径 |
|----|------|
| 逻辑 | `owner/feishu/bot_menu.py` |
| 胶水 | `plugins/platforms/feishu/adapter.py`（`_on_bot_menu_event` + 注册 + p2p 暖缓存） |
| 配置 | `overlay.yaml` → `feishu.bot_menu` / `feishu.bot_menu_dedup` |
| 依赖 | C04 `FeishuUserStore.cache_p2p_chat_id` / `get_p2p_chat_id`（菜单路由前置） |

## 行为要点

1. **三层去重**：`event_id` 精确去重 → in-flight 合并 → 到达间隔 TTL（防手抖）。
2. **暖缓存**：`p2p_chat_entered` 与 p2p inbound 写入 `open_id → p2p_chat_id`；冷缓存时提示先发一条私聊，不误报「菜单未配置」。
3. **映射**：优先 `overlay.yaml`；缺省回退 `BUILTIN_BOT_MENU`。
4. **本批范围**：不做 C05 profile 路由与 C12 guide 卡直发（无实现时 fail-open，走命令映射）。

## 测

`tests/owner/test_owner_feishu_bot_menu_cold_cache.py`
