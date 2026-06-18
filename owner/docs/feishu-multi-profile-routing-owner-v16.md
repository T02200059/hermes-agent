# Feishu 多 Profile 路由（owner-v16 外部容器架构）

> ⚠️ **本文为 v1.x 历史归档，当前实现已迁移到 inject_inbound 模式。**
>
> 请勿以本文作为当前代码的设计参考。v1.x 中描述的 `/v1/runs` +
> `X-Hermes-Reply-Via: feishu` + `feishu_reply()` 回复路径已被删除。
>
> 当前最终设计见
> [`飞书多profile路由与子profile-gateway架构设计.md`](飞书多profile路由与子profile-gateway架构设计.md)（v2.0）。
>
> 关键变化：主 gateway 把消息 `POST /v1/feishu/inbound`，子容器通过
> `FeishuAdapter.inject_inbound()` 把消息注入原生飞书 pipeline（复用
> auto-card、`runtime_footer` 等完整能力）。
