# Feishu Bot Menu + User Cache

## 功能描述

- **Bot Menu 事件处理**：接收飞书 `application.bot.menu_v6` 事件，根据点击的
  `event_key` 解析为 slash command 或文本提示，生成 synthetic `MessageEvent`
  注入 gateway 的消息处理 pipeline。
- **内建命令映射**：`owner/feishu/bot_menu.py::BUILTIN_BOT_MENU` 提供默认映射
  （如 `new` → `/new`）。
- **去重**：同一用户在 3 秒内重复点击同一菜单会被忽略。
- **Ack 反馈**：点击后可立即发送一段可配置的 ack 文本（默认 `⏳ 已收到…`）。
- **用户缓存**：`open_id` → `{name, p2p_chat_id, last_seen_at}`，其中
  `p2p_chat_id` 在用户进入 P2P 会话时缓存并持久化到
  `~/.hermes/feishu_chat_id_cache.json`。

## 架构

```text
gateway/platforms/feishu.py
├── import owner.feishu.user_cache                # [owner] bot-menu
├── __init__ 中初始化 _feishu_user_cache / _bot_menu_dedup
├── _build_event_handler 注册 register_p2_application_bot_menu_v6
├── _on_p2p_chat_entered 预热并保存 p2p_chat_id
└── _on_bot_menu_event 委托给 owner/feishu/bot_menu.py

owner/feishu/
├── bot_menu.py   # 核心：去重、命令解析、ack、synthetic event
└── user_cache.py # 核心：FeishuUserEntry、加载/保存 p2p_chat_id 缓存
```

所有核心逻辑都在 `owner/feishu/` 下；`gateway/platforms/feishu.py` 只做 import
与薄委托，每个改动点都有 `# [owner] bot-menu:` 标记。

## 可移除性

- 删除 `owner/feishu/bot_menu.py` 后，`application.bot.menu_v6` 事件不再被处理，
  但 `gateway/platforms/feishu.py` 仍可正常启动和运行。
- 删除 `owner/feishu/user_cache.py` 后，用户缓存降级为无缓存运行；
  `gateway/platforms/feishu.py` 不会因此崩溃。
- 两个模块的调用方都使用 try/except 或函数内懒加载进行保护。

## 配置

在 `~/.hermes/patch.yaml` 中自定义菜单映射与 ack：

```yaml
owner:
  feishu:
    bot_menu:
      my_custom_key: "/mycommand"
    bot_menu_dedup:
      enabled: true
      default_ack: "⏳ 已收到…"
      per_key:
        new:
          ack: "新建会话中…"
```
