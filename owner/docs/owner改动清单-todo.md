# owner 改动清单（v2 todo · 从新开始）

> 生成：2026-10-23 · Asia/Shanghai  
> **不是**源清单 3000 行粘贴；从源清单提炼为可勾选 todo。

## 元信息

| 项 | 值 |
|----|----|
| 源清单 | `/Users/yangtb/.hermes/hermes-agent/owner/docs/owner改动清单.md` |
| 源仓 tip | `299e23205b66df082a2615aa1a4f3ed1edc69d25` |
| v2 worktree | `/Users/yangtb/.hermes/hermes-agent-v2` · 分支 `v2` |
| v2 tip（官方 main） | `3ba2b0787ed3a73ec3b08085ed0137f235209cf4` |
| 规范 | 同目录 `二次开发规范.md` |
| 实现顺序 | 同目录 `v2实现顺序.md` |
| bug 对照提示词 | 同目录 `小模型-bug对照提示词.md` |

**原则**：① 先整体过 **§ Bug**，对照官方 main 填验证状态；② 再落 **§ 定制**（P0→P1→P2）；③ yaml 整合穿插在定制落地时，不大爆炸；④ 部署继续 Linux 用户隔离，**不吃**官方 multiplex 换舰队路由。

**验证状态枚举**（bug 段）：`待对照官方 main` | `官方已修` | `仍存在/需自研` | `部分` | `不适用(纯 owner)` | `已退役`

勾选约定：`- [ ]` 未处理；`- [x]` 已结论（状态字段已填）。

---

## § Bug / 修复类（优先对照官方）

> 目标：区分「官方最新已修」vs「仍需我们带」。对照时在 v2 干净树搜代码/测例，**只读**。细节以源清单对应 § 为准。

### Provider / 模型切换

- [ ] **B01** · 源 §2.2.1 · credential pool `_seed_from_env` 不校验 key 格式（`ghp_` 误入 copilot 等） · **验证状态：待对照官方 main**
- [ ] **B02** · 源 §2.2.2 · provider discovery 慢探测（anthropic 无条件）+ 共享 models.dev 显示名退化 · **验证状态：待对照官方 main**
- [ ] **B03** · 源 §2.2.3 · env-only providers 未进 `/providers` 显示列表 · **验证状态：待对照官方 main**
- [ ] **B04** · 源 §2.2.4 · 飞书 model_picker stale session 卡 loading / action_value 形态 · **验证状态：待对照官方 main**
- [ ] **B05** · 源 §2.8.1 · damodel `/model` 校验时 `${ENV}` 未展开导致 crash · **验证状态：待对照官方 main**
- [ ] **B06** · 源 §7.16 · merge 后 exhausted credential pool 语义被冲掉 · **验证状态：待对照官方 main**

### 审批 / 安全

- [ ] **B07** · 源 §3.7 · CR-001~006 安全加固（path-token `\\n`、cron allowlist mtime 等） · **验证状态：待对照官方 main**
- [ ] **B08** · 源 §3.8 · SSRF（非 http scheme）+ Feishu user_name sanitize · **验证状态：待对照官方 main**
- [ ] **B09** · 源 §3.10 · QQ DM 审批按钮鉴权（`dm` vs `c2c`） · **验证状态：待对照官方 main**
- [ ] **B10** · 源 §3.12 · `_mask_quoted_newlines` 命令替换绕过硬黑名单；queue token 未 retire · **验证状态：待对照官方 main**
- [ ] **B11** · 源 §3.13 · 审批历史挖掘依赖英文文案，i18n 后漏检（应改结构标记） · **验证状态：待对照官方 main**

### TUI / CLI 稳定性

- [ ] **B12** · 源 §6.3 · Ctrl+C /exit 与 graceful drain（SIGINT 逃出清理链） · **验证状态：待对照官方 main**
- [ ] **B13** · 源 §6.4 · live compression sync 误清 per-model `context_length` · **验证状态：待对照官方 main**
- [ ] **B14** · 源 §7.20 · 后台插件发现超时死锁（启动空白屏） · **验证状态：待对照官方 main**

### Gateway / Agent 运行时

- [ ] **B15** · 源 §7.1 · QQ Bot WebSocket 重连链不稳 · **验证状态：待对照官方 main**
- [ ] **B16** · 源 §7.5 · executor-shutdown 不友好提示 · **验证状态：待对照官方 main**
- [ ] **B17** · 源 §7.6 · Clarify 清理路径缺 stop sentinel / 飞书 clarify 超时未中断 · **验证状态：待对照官方 main**
- [ ] **B18** · 源 §7.9 · 429 配额耗尽被当 transient 静默重试；长等待无即时状态 · **验证状态：待对照官方 main**
- [ ] **B19** · 源 §7.10 · 运行中 agent 时 plugin 斜杠命令被当普通文本注入 · **验证状态：待对照官方 main**
- [ ] **B20** · 源 §7.11 · `/memory` `/skills` 不能 mid-turn · **验证状态：待对照官方 main**
- [ ] **B21** · 源 §7.12 · gateway restart 未清 `__pycache__` 致 ImportError · **验证状态：待对照官方 main**
- [ ] **B22** · 源 §7.15 · Codex Responses reasoning 后空 `assistant content` 被严格网关拒 · **验证状态：待对照官方 main**
- [ ] **B23** · 源 §7.19 · lifecycle guard 遇二进制路径 `embedded null byte` 崩溃 · **验证状态：待对照官方 main**
- [ ] **B24** · 源 §7.21 · 出站 `message_id` 不落库 / 难撤回编辑 · **验证状态：待对照官方 main**
- [ ] **B25** · 源 §7.22 · Skills 索引 LRU 命中不按磁盘 manifest 复验（手动落盘 skill 不可见） · **验证状态：待对照官方 main**
- [ ] **B26** · 源 §7.23 · `/stop` 打在 runner 构造窗口留下孤儿轮次占租约 · **验证状态：待对照官方 main**（若官方无对等：标「仍存在/需自研」）
- [ ] **B27** · 源 §7.27 · 出站 DeepSeek BOS/EOS 可见泄漏 · **验证状态：待对照官方 main**

### 工具链 / Desktop / 性能

- [ ] **B28** · 源 §8.2 · read_file/search_files 无单执行超时 · **验证状态：待对照官方 main**
- [ ] **B29** · 源 §8.3 · delegate_task batch ACP 变量 NameError · **验证状态：待对照官方 main**
- [ ] **B30** · 源 §8.5 · read_file UTF-8 边界误判 binary · **验证状态：待对照官方 main**
- [ ] **B31** · 源 §13.1 · Windows 透明度档位过激 · **验证状态：待对照官方 main**
- [ ] **B32** · 源 §16.7 · output_guard 复读判据 O(n²) 拖住长回复 · **验证状态：待对照官方 main**

### API Server / LDAP 门（安全修复向）

- [ ] **B33** · 源 §15.3 · seen 缓存状态机权限提升 · **验证状态：待对照官方 main**（官方无 LDAP 则「不适用」或「仍需自研」）
- [ ] **B34** · 源 §15.8 · `enforce=seen` fail-closed · **验证状态：待对照官方 main**
- [ ] **B35** · 源 §15.9 · 带密码但无法验证时默认 fail-open 过宽 · **验证状态：待对照官方 main**
- [ ] **B36** · 源 §15.10 · 认证门在路由之后可被白名单/错配绕过 · **验证状态：待对照官方 main**

### 标记为「多半纯 owner / merge 债」（仍要填状态）

- [ ] **B37** · 源 §7.7 · `_owner_import` 不缓存瞬时 ImportError · **验证状态：待对照官方 main**
- [ ] **B38** · 源 §7.13 / §7.17 · merge 后死代码与 display resolution wiring 恢复 · **验证状态：待对照官方 main**（重放时再验）

**Bug 段合计：38 条。**

---

## § 定制功能类（bug 对照完成后再落）

> 优先级草案：P0 必保（现网依赖）/ P1 要留但可后移 / P2 暂缓。路由：**维持自研**跨进程转发，不对齐吃官方 multiplex。

### P0 必保

- [ ] **C01** · 源 §1.1–1.4 · `patch.yaml` 统一加载器 + 审批白名单合并 + 归因骨架 · **优先级：P0**
- [ ] **C02** · 源 §2.1–2.3 / §10 · per-turn 归因 + credential 合并 + billing 落盘 · **优先级：P0**
- [ ] **C03** · 源 §2.7–2.8 · damodel prompt cache / NewAPI proxy / MiMo thinking wire · **优先级：P0**
- [ ] **C04** · 源 §3.1–3.4 · 飞书审批卡片 + sender_name 缓存 + inbound 身份 + 多平台审批签名 · **优先级：P0**
- [ ] **C05** · 源 §4.1 · **飞书多 profile 舰队路由**（`profile_endpoints` HTTP 转发；**不吃**官方 `profile_routes`） · **优先级：P0**
- [ ] **C06** · 源 §15.1–15.6 · API Server LDAP 身份准入 + identity_routes + 头剥离/SSE · **优先级：P0**
- [ ] **C07** · 源 §16.1–16.6 · API 产物媒体 / `hermes.files` / tool.progress 脱敏与归属 · **优先级：P0**
- [ ] **C08** · 源 §7.27 / design · outbound BOS/EOS scrub（若 B27=官方已修则收窄） · **优先级：P0**
- [ ] **C09** · 源 §3.6 / §3.11 · skill 脚本自动审批 + skill_manage 飞书审批门 · **优先级：P0**
- [ ] **C10** · 源 i18n 层 · 显示层 i18n / `_localized` 与护栏文案（源 §12.2 / §16.9 相关） · **优先级：P0**

### P1

- [ ] **C11** · 源 §4.2–4.6 · auto-card / early-typing / diff·clarify 卡 / bot 菜单 · **优先级：P1**
- [ ] **C12** · 源 §4.10–4.15 · memory write-approval 卡 / feishu-guide / 上传守卫 / doc_read 图 OCR / @所有人 / merge_forward · **优先级：P1**
- [ ] **C13** · 源 §7.24–7.26 · progress / approval / english explainer · **优先级：P1**
- [ ] **C14** · 源 §14 · output_guard + stream_guard · **优先级：P1**
- [ ] **C15** · 源 §7.2–7.3 · Memory synthetic guard + OpenViking sync recall/card · **优先级：P1**
- [ ] **C16** · 源 §7.4 · Cron env 隔离（ContextVar + restart scrub） · **优先级：P1**
- [ ] **C17** · 源 §8.1 · Checkpoint Mutation Predictor · **优先级：P1**
- [ ] **C18** · 源 §9.1 · per-chat display overrides · **优先级：P1**
- [ ] **C19** · 源 §5 · 链式快捷命令 `;;` + Quick Alias · **优先级：P1**
- [ ] **C20** · 源 §3.9 · Semantic Audit Gate · **优先级：P1**（可后移若负担大）
- [ ] **C21** · 源 §2.4–2.6 / §2.9–2.11 · reasoning 转义 / MiniMax / Qwen debris / kimi-coding / model-switch 白名单 / cache TTL · **优先级：P1**

### P2 暂缓

- [ ] **C22** · 源 §6.1–6.2 · TUI skin / ruolin · **优先级：P2**
- [ ] **C23** · 源 §11 · 运维脚本 / HN Daily / Skill 同步 / Viking 治理 / 备份 / 周会脚本 · **优先级：P2**（按需拣）
- [ ] **C24** · 源 §12 / §16.8–16.16 · 治理标记、T2-11~20 换码债、全量 `[owner]` 铺开 · **优先级：P2**（v2 **不做**「官方测全绿」与全量标记战役）
- [ ] **C25** · 源 §4.7–4.9 · 编辑上限轮转 / 中文摘要 / `/providers` 等体验项 · **优先级：P2**（可拣进 P1）

**定制段合计：25 条（P0×10 / P1×11 / P2×4）。**

---

## § 明确不做 / 已退役（勿再做）

来源：源清单 **附录 D** 等。

- [x] Mixture-of-Agents 去 OpenRouter 硬绑定（旧 §18.2）— 已退役
- [x] Qdrant 记忆召回（旧 §9.2/§17.21）— 被 OpenViking 取代
- [x] Session Archiver 插件（旧 §13.2）
- [x] `hermes_mon` 性能监控（旧 §13.1）
- [x] memory_propose 批量提案（旧 §4.5/§17.5）
- [x] Copilot PAT 拒绝策略（旧 §4.1）
- [x] 频道级 `channel_prompts`（旧 §5.1）
- [x] 用官方 `multiplex_profiles` **替换** node010 Linux 用户舰队隔离 — **明确不做**
- [x] 把「官方测试套件全绿」当 v2 目标 — **明确不做**
- [x] 推倒 `owner/` 换魔法 patch 框架 — **明确不做**（减负靠能力包 + 短名单）

---

## § yaml 整合方向（只写方向，不改现网）

现状（源仓）：`owner/config/patch.yaml`（~436 行）+ `patch_feishu_profile.yaml`（~156 行，含 bots 路由与 LDAP）+ `upstream_sync.yaml`。

**目标**：定制 yaml **更小、更好读**；密钥仍可内网提交，对外另做 template。

建议（落地时穿插，非一次性大爆炸）：

1. **拆「路由/身份」与「行为开关」**  
   - 保留独立「舰队路由」文件亦可，但结构对齐：`feishu.bots.*.user_routing` / `profile_endpoints` 与 `ldap` / `identity_*` 分节清晰；避免 LDAP 埋在飞书文件里却无索引。  
   - **不**为对齐官方而改成 `gateway.profile_routes`（语义不覆盖跨进程）。
2. **`patch.yaml` 合并同类开关**  
   - `progress_explainer` / `approval_explainer` / `english_explainer` → 单一 `explainers:` 块。  
   - `openviking_sync_recall` + `openviking_recall_card` → `openviking:`。  
   - `feishu_card` notice_titles 与 auto_card 阈值保留一张表，删注释噪声。  
   - 长期 `enabled: false` 且无现网依赖的（如部分 `diff_card`）可迁「默认关 + 文档」，不占主文件行。
3. **行为默认进代码，yaml 只留差异**  
   - 与源规范一致：缺省 section = 合理默认；yaml 只写覆盖项。
4. **上游 sync 配置独立**  
   - `upstream_sync.yaml` 保持单独，不并进 patch。
5. **v2 落地顺序**  
   - 先按 C01 重接加载器 → 再迁键名（一次改加载器+文档+软链说明）→ 最后缩行数。

---

## 附录：对照时怎么用源清单

- 打开源 `owner改动清单.md`，按本 todo 的「源 §x.y」跳转。  
- 不要把附录 B 侵入流水账搬进 v2。  
- 官方已修的 bug：在本文件标 `官方已修`，定制重放时**跳过**或只留回归测。  
- 仍需自研：进入对应 C0x 或新建薄能力包条目。
