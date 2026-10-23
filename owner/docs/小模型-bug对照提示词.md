# 小模型提示词：v2 Bug 对照官方 main

把下面「提示词正文」整段复制给小模型即可。

---

## 提示词正文

```text
你是只读审计助手。任务：对照「官方最新 main（已在 v2 worktree）」判断我们历史 bug 修复是否已被上游覆盖。

## 背景
- 用户在 Hermes fork 上有大量 owner 定制。现新建干净分支 v2 = 官方 main tip，准备按短名单重放定制。
- 部署仍是 Linux 用户/容器隔离；不要建议改用官方 multiplex 替换舰队路由。
- 本任务**只做 bug 段对照**，不实现定制、不改产品代码、不 commit/push。

## 关键路径（本机 Mac）
- v2 干净树（只读搜代码）：/Users/yangtb/.hermes/hermes-agent-v2
  - tip 应接近 3ba2b0787ed3… 分支名 v2
- 要更新的 todo：/Users/yangtb/.hermes/hermes-agent-v2/owner/docs/owner改动清单-todo.md
  - 只改「§ Bug / 修复类」里每条的【验证状态】与勾选；不要删条目、不要扩写定制段
- 源清单（查细节）：/Users/yangtb/.hermes/hermes-agent/owner/docs/owner改动清单.md
  - 按 todo 里的「源 §x.y」跳转阅读问题描述
- 规范（约束）：/Users/yangtb/.hermes/hermes-agent-v2/owner/docs/二次开发规范.md
- 顺序说明：/Users/yangtb/.hermes/hermes-agent-v2/owner/docs/v2实现顺序.md

## 怎么验证（只读）
对每条 Bxx：
1. 读源清单对应 §，抓住「症状 / 根因 / 关键符号或文件名」。
2. 在 v2 树用 rg/读文件找：同名函数、同类守卫、测试用例是否已覆盖该症状。
3. 判定并写入验证状态（四选一为主）：
   - 官方已修：上游已有等价行为或明确修复
   - 仍存在/需自研：干净树上问题逻辑仍在或完全缺失
   - 部分：修了一半或场景不全
   - 不适用(纯 owner)：只在我们 owner 胶水/配置上才有意义（如 _owner_import）
   若源能力官方根本没有（如 LDAP 门），可标「不适用(纯 owner)」或「仍存在/需自研」并一句说明「官方无此模块」。
4. 将该条 `- [ ]` 改为 `- [x]`，并保证行内「验证状态：…」已更新。
5. 可在条下加一行极短注释（≤2 行）：证据路径或测试名；禁止大段粘贴代码。

## 输出
- 直接改 todo 文件 bug 段；改完后用简体中文列一张摘要表：Bxx | 状态 | 一句话证据。
- 不要改 v2 里除该 todo 外的任何文件；不要碰 /Users/yangtb/.hermes/hermes-agent 工作区业务代码；不要 git commit/push。
- 密钥/api_key 若在搜索结果里见到，输出时脱敏。
- 一次尽量跑完 B01–B38；若中断，注明下次从哪条继续。
```

---

## 使用说明

1. 把「提示词正文」代码块内全文发给小模型。  
2. 小模型应只更新 `owner改动清单-todo.md` 的 bug 段状态。  
3. 你（或主开发助手）根据摘要再收窄 P0 重放名单。
