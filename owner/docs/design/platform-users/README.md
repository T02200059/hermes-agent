# platform_users — 平台显示名 sqlite 目录

## 意图

在 `state.db` 旁路表持久保存「平台侧用户显示名」（飞书中文名等），供查询 / 后续 C05 路由复用。  
**不是** C04 的 `feishu_chat_id_cache.json`（那仍是热缓存）；本表是可 SQL 查询的用户名目录。

## 设计

| 项 | 选择 |
|----|------|
| 表 | `platform_users(platform, user_id, display_name, updated_at)` PK `(platform, user_id)` |
| 库 | 与 sessions 同库 `~/.hermes/state.db` |
| SCHEMA | **不改**官方 `hermes_state_common` 字面；运行时 `CREATE TABLE IF NOT EXISTS`（仿 delivery_ledger） |
| 写入 | resolve 成功 → C04 JSON **照旧** + **upsert** 本表（双写） |
| 读取 | `get_display_name(platform, user_id)`；**不**改写 `sessions.display_name` 语义 |
| 回填 | `FeishuUserStore` 启动时从已加载的 JSON cache 条目 best-effort 种子；新 resolve 继续渐进填充 |

## 落点

- `owner/platform_users/store.py` — ensure / upsert / get / backfill / `dual_write_feishu_name`
- `owner/feishu/user_store.py` — `_store_resolved_name` 双写；`__init__` 调 `_backfill_platform_users`
- 测：`tests/owner/test_platform_users.py`

## 非目标

- 不替代 C04 TTL / 审批卡预热路径
- 本轮只接通飞书；表字段已通用，其它平台有钩子再接
