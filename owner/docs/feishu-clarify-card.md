# Feishu Clarify 交互卡片

## 设计意图

默认的 clarify 在飞书上走网关文本回退： bot 发送带编号的纯文本列表，用户回复数字或文字。这种方式存在三个问题：

1. 移动端数字回复容易与日常消息混淆；
2. 长选项在纯文本中排版拥挤；
3. 没有超时状态提示，用户不知道之前的 prompt 已经过期。

因此引入飞书 Schema 2.0 交互卡片：用户看到带按钮的紫色卡片，点击后卡片原地冻结（按钮 disabled + 选中项标 ✅ + header 变绿），超时后整卡置灰，体验与飞书原生机器人一致。

## 架构说明

按《二次开发规范》把核心逻辑放在 `owner/` 下，官方源码只保留 import + 委托：

```
owner/
├── clarify/
│   ├── choice_normalizer.py    # choice 归一化 {display, key}
│   └── gateway_helpers.py      # get_choice_display / get_choice_key
├── feishu/
│   └── clarify_card.py         # 卡片构建 + REST 更新 + action 处理
└── docs/
    └── feishu-clarify-card.md  # 本文档
```

官方改动点（均带 `# [owner] clarify: ...` 标记）：

- `tools/clarify_tool.py`：入口调用 `normalize_choices()` 把 model 返回的 str/dict 统一成 `{display, key}`。
- `tools/clarify_gateway.py`：`register()` 中把 choices 以 `{display, key}` 格式存储，并导出 choice helpers。
- `gateway/platforms/feishu.py`：新增 `_clarify_state`、`send_clarify()` 委托、`expire_clarify()` 委托、action dispatch 路由、`_handle_clarify_card_action()` 委托。
- `gateway/platforms/telegram.py`：`send_clarify()` 用 `get_choice_display(c)` 替代 `str(c)`。
- `plugins/platforms/discord/adapter.py`：同上，渲染选项时读取 display。

## Choice 格式约定

归一化后的 choice 固定为：

```python
{"display": str, "key": Optional[str]}
```

- `display`：用户可见文本。
- `key`：发送回 model 的稳定标识符；缺失时平台回退到 `display`。

模型可能返回的原始形态：

- `str` → `{"display": s, "key": s}`
- `{"key": "A", "description": "方案 A"}` → `{"display": "A — 方案 A", "key": "A"}`
- `{"content": "仅正文"}` → `{"display": "仅正文", "key": None}`
- 其他 → `str(c)`

## 主要改动点清单

1. **Choice 归一化**（`owner/clarify/choice_normalizer.py`）
   - 提取自 owner 分支 `tools/clarify_tool.py`。
   - 新增 `normalize_choice` / `normalize_choices` / `render_dict_choice`。

2. **Choice 显示辅助**（`owner/clarify/gateway_helpers.py`）
   - 提取自 owner 分支 `tools/clarify_gateway.py`。
   - 兼容 legacy string choices。

3. **飞书卡片实现**（`owner/feishu/clarify_card.py`）
   - `build_clarify_card`：Schema 2.0，markdown 选项前置，无 `action` 容器。
   - `build_frozen_clarify_card`：点击后冻结。
   - `build_expired_clarify_card`：超时置灰。
   - `patch_message_via_rest`：用 `requests` 直接调用 Feishu PATCH API，避免 WebSocket token 刷新。
   - `send_clarify` / `expire_clarify` / `handle_clarify_card_action`：完整生命周期。

4. **官方薄胶水**
   - `tools/clarify_tool.py`：运行时 import 归一化器，不改 SCHEMA 常量。
   - `tools/clarify_gateway.py`：register 存储归一化后的 dict，导出 helpers。
   - `gateway/platforms/feishu.py`：状态 + 委托 + action 路由。
   - `gateway/platforms/telegram.py` & `plugins/platforms/discord/adapter.py`：选项渲染走 display。

## 可移除性

删除以下文件/目录即可完全回滚该功能：

- `owner/clarify/`
- `owner/feishu/clarify_card.py`
- `owner/docs/feishu-clarify-card.md`

官方文件中的 `# [owner] clarify:` 改动点也可按标记逐条还原。
