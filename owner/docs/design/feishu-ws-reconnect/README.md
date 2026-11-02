# Feishu WS reconnect guard

> 2026-11-02 · 本机飞书「没反应」事故后落地

## 根因

keepalive ping timeout → SDK `_reconnect` 打出 `trying to reconnect for the 1st time` → 卡在同步 `requests.post`（`Client._get_conn_url` **无 timeout**）。WS 线程仍活着，`_supervise_websocket_thread` 不会重建；进程 `/health` 正常，入站全哑，直到整进程重启。

次要：服务端 `ClientConfig` 可把 `_reconnect_count` 写成有限/异常值；Hermes 原 `_apply_runtime_ws_overrides` **不**回写 count。

## 策略（用户拍板）

- **禁止**默认 `hermes gateway restart` 当恢复手段
- 断连后由 supervisor **约每 10 分钟**重建一次（首次可更快）
- 同一时刻最多 1 个 rebuild in-flight；旧 client 随 `start()` 返回结束，不叠连接
- 连续失败达上限 → 低频告警 + **停止自动重试**（`note_link_up` / 人工恢复前不空转）
- 给 `_get_conn_url` 加 per-thread `requests.post` timeout，并强制有限 SDK ladder

## 落点

| 层 | 路径 |
|----|------|
| 核心 | `owner/feishu/ws_reconnect_guard.py` |
| 薄挂 | `plugins/platforms/feishu/adapter.py`（`# [owner]` → apply / supervise / note_*） |
| 配置 | overlay `feishu.ws_reconnect_guard`（可选；默认见 DEFAULTS） |
| 测 | `tests/owner/test_feishu_ws_reconnect_guard.py` |

## 配置（DEFAULTS）

```yaml
feishu:
  ws_reconnect_guard:
    enabled: true
    sdk_reconnect_count: 2          # 强制有限 ladder（禁止 -1 无限）
    conn_url_timeout_s: 30          # 卡住的 endpoint POST
    first_supervisor_retry_s: 30    # 首次重建等待
    supervisor_retry_interval_s: 600  # 之后约 10 min
    max_failures: 18                # 约 3h 后停自动重试
```

## 生效

改的是 gateway 进程内适配器逻辑，**需重启 gateway** 后新 WS 客户端才带上 guard（本轮实现不强制替你重启）。
