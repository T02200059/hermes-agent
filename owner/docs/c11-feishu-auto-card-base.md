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
| `owner/feishu/card_sender.py` | `send_card`（官方 `_feishu_send_with_retry`）+ 卡发送锁 |
| `plugins/platforms/feishu/adapter.py` | 薄胶水：`send`/`send_card`/`_get_card_send_lock`/`early-typing` |
| `gateway/run_turn.py` | 薄胶水：footer 后 `try_auto_card_on_end`；进度气泡 `__hermes_progress_bubble` |
| `owner/config/overlay.yaml` | `feishu_card.*` |

## 配置（`owner.feishu_card`）

- `auto_card_threshold`（默认 57；≤0 关）
- `split_enabled` / `split_max_chars`
- `notice_titles`（替换内置表，非追加）

## 相对旧树的优化

- `send_card` 走 `_feishu_send_with_retry` + `_finalize_send_result`（API 级失败可重试/回落纯文本）；不引入 REST 旁路。
- 配置读公共 `load_patch_config`（不再用私有 `_load_patch_owner_config`）。
- profile 按钮打标 fail-open 预留（真正路由在 C05）；本批不接 REST / bot 菜单 / clarify / diff。

## 未做（C11 余下 · 阶段三）

- diff 卡（工具改文件可视化）
- clarify 卡
- bot 菜单

## 测

```bash
cd ~/.hermes/hermes-agent-v2
PYTHONPATH=. python -m pytest tests/owner/test_c11_auto_card.py tests/owner/test_feishu_agent_end_media.py -q
```
