# C11 底座 · 飞书 auto-card / early-typing

阶段二落地（**不含** diff 卡 / clarify 卡 / bot 菜单 —— 那些归阶段三「C11 余下」）。

## 做什么

1. **auto-card**：飞书 streaming 关闭时，长回复（≥ `owner.feishu_card.auto_card_threshold`）包成 interactive card；`agent:end` 用 `force=True` 无视 streaming。成功则 `already_sent`，抑制纯文本重复。超预算可拆多卡；`MEDIA:` / 裸路径在包卡前预投递。
2. **early-typing**：同一 chat 的上一条仍占着 `chat_lock` 时，新消息先打 Typing reaction，避免用户以为没收到。
3. **notice 卡**：`notice_titles` 按前缀给告警/旁白加 header（为 C13 进度/英文解说前缀预留）。

## 文件

| 路径 | 角色 |
|------|------|
| `owner/feishu/auto_card.py` | 阈值 / 可行性 / 拆分 / notice / `try_auto_card` |
| `owner/feishu/agent_end.py` | `try_auto_card_on_end`（媒体预投递 + force 包卡） |
| `owner/feishu/card_sender.py` | `send_card`（官方 `_feishu_send_with_retry`）+ 卡发送锁 + `[2200]` 已送达白名单 |
| `owner/feishu/plain_fallback.py` | 网关级纯文本兜底（不经过 auto-card） |
| `plugins/platforms/feishu/adapter.py` | 薄胶水：`send`/`send_card`/`_get_card_send_lock`/`_send_plain_fallback`/`early-typing` |
| `gateway/run_turn.py` | 薄胶水：footer 后 `try_auto_card_on_end`；进度气泡 `__hermes_progress_bubble` |
| `owner/config/overlay.yaml` | `feishu_card.*` |

## 配置（`owner.feishu_card`）

- `auto_card_enabled`（默认 true；false 时整条 auto-card 路径关闭，回复走普通消息）
- `auto_card_threshold`（默认 57；≤0 同样等于关闭，旧写法保留）
- `split_enabled` / `split_max_chars`
- `notice_titles`（替换内置表，非追加）

## 发送降级链（2026-11-26）

卡片发送失败**不重试**，改为固定三档、每档各一次：`v2 卡 → v1 卡 → 普通消息`。

- `auto_card.try_auto_card`：v2 被拒 → 用 `make_auto_card_v1` / `make_notice_card_v1` 同内容重发一次 → 仍失败返回 `None`，由 `adapter.send()` 走 post/text。历史上这里是 `_MAX_CARD_SEND_ATTEMPTS=3` 重试，一次失败会把同一段内容发 3 遍。
- `card_sender.send_card`：`[2200] internal error` 按**已送达**处理（实测＝消息已创建、正文没渲染成卡片；31 次 2200 与聊天里 32 条占位卡逐秒 1:1），记 INFO `delivered-with-error` 后返回成功，不降级、不重发。
- `adapter._send_plain_fallback`：覆写为直接 `msg_type=text`（`plain_fallback.send_plain_fallback`），保留「（响应格式化失败，以下为纯文本：）」前缀。官方默认实现会再调 `self.send()` → 重新进 auto-card，把一条回复放大成多张卡。
- 背景：`schema: "2.0"` 卡片在本租户/客户端下会被飞书落成「请升级至最新版本客户端，以查看内容」占位卡，v1（`config`+`elements`）能正常渲染。

## 相对旧树的优化

- `send_card` 走 `_feishu_send_with_retry` + `_finalize_send_result`；失败只做一次 v1 降级，之后回落纯文本，不做重试；不引入 REST 旁路。
- 配置读公共 `load_patch_config`（不再用私有 `_load_patch_owner_config`）。
- profile 按钮打标 fail-open 预留（真正路由在 C05）；本批不接 REST / bot 菜单 / clarify / diff。

## 未做（C11 余下 · 阶段三）

- diff 卡（工具改文件可视化）
- clarify 卡
- bot 菜单

## 测

```bash
cd ~/.hermes/hermes-agent
PYTHONPATH=. python -m pytest tests/owner/test_c11_auto_card.py tests/owner/test_feishu_agent_end_media.py -q
```
