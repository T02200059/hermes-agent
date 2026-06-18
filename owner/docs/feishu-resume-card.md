# 飞书 /resume 交互卡片

> 最后更新：2026-06-18
> 关联代码：`owner/feishu/resume_card.py`、`gateway/slash_commands.py`（飞书分支）、`gateway/platforms/feishu.py`（薄胶水）

---

## 一、需求背景

`/resume`（无参数）原本输出一段纯文本会话列表（编号 + 标题 + 预览）。在飞书手机端长文本会被截断，且需要用户手动输入 `/resume N` 才能恢复。

目标：飞书平台收到 `/resume`（无参数）时，渲染交互卡片：
- 卡片标题：`📋 恢复最近会话`（i18n 化）
- 卡片正文：保留完整的 10 条列表内容（解决手机端截断）
- 卡片按钮：1~10 个数字按钮（不内嵌选项文本），三个一行
- 用户点击数字按钮 → 合成 `/resume N` 走标准命令管线

非飞书平台维持原文本行为不变。

---

## 二、设计要点

### 2.1 文件分工（二次开发规范 P1 import 编排）

| 文件 | 改动 | 角色 |
|------|------|------|
| `owner/feishu/resume_card.py` | 新建 | 真实逻辑：build_resume_card / send_resume_card / handle_resume_card_action |
| `gateway/slash_commands.py` | +飞书分支 ~36 行 | 在 `_handle_resume_command` 无参数列表分支调用 `adapter.send_resume_card`，失败 fall through 到原文本路径 |
| `gateway/platforms/feishu.py` | +20 行薄胶水 | `send_resume_card` 方法委托到 owner；`_handle_card_action` 中 `hermes_action == "resume_select"` 路由到 owner |
| `locales/zh.yaml` / `en.yaml` | +1 行 | 新增 `gateway.resume.card_title` |

### 2.2 卡片渲染：v2 schema

跟项目里 `owner/feishu/model_picker.py` 保持一致——用 v2 schema。

**重要 v2 限制**：v2 schema **不再支持 `tag: action` 容器**（API 返回错误 230099 / "cards of schema V2 no longer support this capability"）。多按钮排版必须用 `column_set` + `column` 容器。每个按钮作为顶层 element 时独占一行；要"3 个一行"必须包在 `column_set` 里。

我们采用 `column_set` 实现 3 列等宽布局，10 个按钮排成 3+3+3+1 行。

```python
{
    "schema": "2.0",
    "config": {"wide_screen_mode": True},
    "header": {"title": ..., "template": "blue"},
    "body": {"elements": [...]},
}
```

### 2.3 按钮回调：合成消息走标准管线

跟 `model_picker.py:_route_picker_command` 完全一致的模式：

1. **Build 卡片时**：把 `source.to_dict()` 序列化进每个 button 的 `value.source_dict` 字段（飞书 button.value 限制 ~2KB，SessionSource 序列化后约 200~400 字节）。
2. **回调进来时**：`gateway/platforms/feishu.py` 的 `_handle_card_action` 识别 `hermes_action == "resume_select"`，路由到 `owner/feishu/resume_card.py:handle_resume_card_action`。
3. **Owner 模块**：从 `action_value["source_dict"]` 重建 `SessionSource`，构造 `MessageEvent(text=f"/resume {N}", message_type=MessageType.COMMAND)`，通过 `adapter._submit_on_loop(loop, _dispatch())` + `await adapter._handle_message_with_guards(synthetic_event)` 投回标准管线。
4. **回调返回值**：返回空的 `P2CardActionTriggerResponse()` —— 不更新卡片，因为 `/resume N` 命令自身会发后续的"已切换"消息回用户。

为什么用 `source_dict` 而不是在 adapter 加 `_resume_picker_state` 字典？
- **可移除性更好**：删除 `owner/feishu/resume_card.py` 后官方 adapter 完全无残留状态字段（model_picker 因为有"返回上一步"等多步交互必须维护 state，resume 是无状态点击不需要）。
- **状态自包含**：button.value 自带恢复所需的全部信息，没有 TTL/清理问题。
- **风险**：source_dict 会被发到飞书服务器再发回——理论上敏感字段（chat_topic 等）会经过第三方。当前 SessionSource 字段都不算秘密，可接受。如果未来引入秘密字段需要重新评估。

### 2.4 失败降级

两层 fallback：
1. **Owner 内部**：`send_resume_card` try 块捕获 build/send 异常 → 降级 plain text → 仍失败则 logger.warning。
2. **Gateway 调用侧**：`slash_commands.py` 的飞书分支再包一层 try/except，所有异常都 fall through 到原文本渲染路径（line 2917 之后），保证用户至少能看到列表。

---

## 三、i18n key

新增 `gateway.resume.card_title`：
- `zh.yaml`: `恢复最近会话`
- `en.yaml`: `Resume recent session`

复用现有 key：
- `gateway.resume.list_header`（卡片正文第一行）
- `gateway.resume.list_item_numbered`（每条会话）
- `gateway.resume.list_preview_suffix`（预览文本前缀）
- `gateway.resume.list_footer_numbered`（卡片正文末尾）

---

## 四、按钮 value 协议

```json
{
    "hermes_action": "resume_select",
    "resume_index": 3,
    "session_key": "agent:main:feishu:oc_xxxx",
    "source_dict": {
        "platform": "feishu",
        "chat_id": "oc_xxxx",
        "chat_type": "dm",
        "user_id": "ou_xxxx",
        "user_id_alt": "on_xxxx",
        ...
    }
}
```

---

## 五、删除/回滚

完全删除本功能：
1. 删除 `owner/feishu/resume_card.py`
2. 还原 `gateway/slash_commands.py:2879-2916` 的飞书分支（删除整个 `if source.platform == Platform.FEISHU:` 块）
3. 还原 `gateway/platforms/feishu.py:2186-2206`（删除 `send_resume_card` 方法）
4. 还原 `gateway/platforms/feishu.py:2746-2754`（删除 `if hermes_action == "resume_select":` 路由分支）
5. 还原 `locales/zh.yaml` / `locales/en.yaml`（删除 `card_title` 行）

删除后所有平台（包括飞书）走原文本路径，行为退回到本功能引入前。

---

## 六、跟踪的 Bug

历次修复：
- `'GatewayRunner' object has no attribute '_adapters'` → 改用 `self.adapters`
- `'SessionSource' object has no attribute 'open_id'` → 飞书 open_id 在 `SessionSource.user_id` 字段
- 按钮回调 `from gateway.event import ...` 路径完全错（模块不存在） → 改为 `gateway.platforms.base` + `gateway.session`
- 按钮回调用 `Source(...)` 类（不存在） + `_gateway_ref.handle_message_event`（方法不存在） → 整段重写，改为复用 model_picker 的合成消息模式
- `t("...", default="...")` 不被 i18n 支持 → 在 catalog 里加 `card_title` 键
- v2 schema 不支持 `tag: action` 容器（错误 230099） → 改用 `column_set` + `column` 实现 3 列布局
