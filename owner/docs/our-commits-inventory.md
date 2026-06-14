# Our Commits Inventory

> 自动生成于 **2026-06-12 21:02:34 **，源分支 `refs/heads/owner`（HEAD: `5b14bbf87`）

> 生成器：`generate-our-commits-inventory.py`（一次性脚本）

## 总览

| 指标 | 值 |
|---|---:|
| 源分支 commit 总数 | 10476 |
| **我们 commit 总数（yangtb + tianbao.yang）** | **522** |
| 我们累计新增行 | +83511 |
| 我们累计删除行 | −33168 |
| **我们净增行** | **+50343** |
| 占总 commit 比例 | 4.98% |

## 按 author 拆分

| author | commit 数 | 新增 | 删除 | 净增 |
|---|---:|---:|---:|---:|
| `yangtb` | 360 | +59606 | −27737 | **+31869** |
| `tianbao.yang` | 162 | +23905 | −5431 | **+18474** |

> 注：早期 commit 用拼音 `tianbao.yang`，后期切到 `yangtb`，邮箱均为占位 `123`。
> 两个 author 视为同一开发者（**杨天宝**）。

## 完整 commit 列表（按时间倒序）

- [ ] `5b14bbf` | 2026-06-12 | `yangtb` | chore: add SQL audit script for reasoning_content coverage | +58 | −0 |
- [ ] `871a364` | 2026-06-12 | `yangtb` | test: regression tests for xfyun/damodel reasoning_content echo | +210 | −0 |
- [ ] `854d2c3` | 2026-06-12 | `yangtb` | feat: add xfyun/damodel thinking-mode reasoning_content detector | +30 | −0 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`6ae8c57` | 2026-06-12 | `yangtb` | sync: align owner/SOUL.md with personalized SOUL.md (minus persona) | +33 | −7 |
- [ ] `19773fe` | 2026-06-12 | `yangtb` | fix(agent): add _needs_glm_tool_reasoning for damodel/bigmodel endpoints | +19 | −0 |
- [ ] `97a88a1` | 2026-06-12 | `yangtb` | fix(owner): use official thinking params for damodel glm-5.1/glm-5 | +13 | −1 |
- [ ] `3e448f9` | 2026-06-12 | `yangtb` | feat(owner): enable thinking for xfyun/damodel models (xopglm51, xopglm5, xopkimik26) | +12 | −0 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`2bb3f24` | 2026-06-12 | `yangtb` | docs(owner): delete §十 qdrant cleanup log + rewrite §四 from OpenViking to Qdrant + reorder sections | +61 | −243 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`5ee4631` | 2026-06-12 | `yangtb` | fix(owner): correct 10.1 'viking.md (跳板机)' mislabel → yaxin 项目访问配置 | +2 | −2 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`de00f9c` | 2026-06-12 | `yangtb` | docs(owner): log qdrant cleanup (10.1 删 2 条 OpenViking 历史记忆) | +54 | −0 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`8512faf` | 2026-06-12 | `yangtb` | docs(owner): mark qdrant sync status as done (2 points written, hook-faithful verified) | +21 | −26 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`0484b40` | 2026-06-12 | `yangtb` | docs(owner): append qdrant sync status (deferred, viking container down) | +37 | −0 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`4b3939b` | 2026-06-12 | `yangtb` | docs(owner): patch inventory 73→75, add P74 (P0 hard-cap) + P75 (per-turn attribution) | +14 | −3 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`1f82244` | 2026-06-12 | `yangtb` | docs(agent): document async_call_llm P0 hang and hard-cap fix | +166 | −0 |
- [ ] `c7fd830` | 2026-06-12 | `yangtb` | fix(agent): cap async_call_llm with asyncio.wait_for hard timeout | +15 | −1 |
- [ ] `1d52226` | 2026-06-12 | `yangtb` | test(feishu): add bot_menu routing tests — routed user forwarded, local user handled locally | +76 | −0 |
- [ ] `1a4f194` | 2026-06-12 | `yangtb` | feat(feishu): forward bot_menu synthetic commands to routed profile containers | +21 | −0 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`dc44c0c` | 2026-06-12 | `yangtb` | docs(feishu-v6): update implementation status table — add A4/B2/B3, collapse duplicate section 7 | +4 | −6 |
- [ ] `05d8f28` | 2026-06-12 | `yangtb` | test(feishu): add B3 card-action profile routing tests (inject, resolve-by-name, forward, guard) | +257 | −1 |
- [ ] `e818002` | 2026-06-12 | `yangtb` | feat(api_server): add POST /v1/feishu/card-actions endpoint for B3 profile routing | +54 | −0 |
- [ ] `aab7293` | 2026-06-12 | `yangtb` | feat(feishu): B3 card-action profile routing — inject hermes_profile into cards and forward to containers | +113 | −10 |
- [ ] `3c4f26b` | 2026-06-12 | `yangtb` | feat(config): add get_hermes_profile_name() for container self-identification | +8 | −0 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`6d78558` | 2026-06-12 | `yangtb` | docs(session-storage): document model/provider per-turn columns in messages schema | +6 | −0 |
- [ ] `ccaa607` | 2026-06-12 | `yangtb` | test(db): add tests for model/provider message attribution and backfill | +57 | −0 |
- [ ] `5165578` | 2026-06-12 | `yangtb` | test(feishu): fix connect tests (mock _start_health_server), fix reaction test (pre-populate sent registry) | +10 | −1 |
- [ ] `60e75f3` | 2026-06-12 | `yangtb` | feat(agent): pass model/provider to append_message for per-turn attribution | +2 | −0 |
- [ ] `c571ea8` | 2026-06-12 | `yangtb` | feat(agent): capture model/provider in build_assistant_message for per-turn attribution | +6 | −0 |
- [ ] `ef65e92` | 2026-06-12 | `yangtb` | feat(db): add model/provider columns to messages for per-turn attribution | +42 | −6 |
- [ ] `b35729e` | 2026-06-12 | `yangtb` | feat(config): reduce patch.yaml cache TTL 5min→1min, add invalidate_patch_owner_config_cache() | +8 | −2 |
- [ ] `4d258c0` | 2026-06-12 | `yangtb` | feat(api_server): warn once when API_SERVER_KEY is not set | +9 | −0 |
- [ ] `3e72fef` | 2026-06-12 | `yangtb` | feat(feishu): v6 external-container multi-profile routing | +172 | −103 |
- [ ] `2b2e02c` | 2026-06-12 | `yangtb` | test(feishu): add profile routing tests (_resolve_profile_route, _forward_to_profile_container, registry) | +496 | −0 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`d14cc49` | 2026-06-12 | `yangtb` | docs(feishu): add v6 single-bot multi-profile design doc (external container architecture) | +506 | −0 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`4b962fa` | 2026-06-12 | `yangtb` | docs(feishu): rename v1-v5 multi-profile docs to -已弃用 (v6 cleanup) | +0 | −0 |
- [ ] `e922b2a` | 2026-06-12 | `yangtb` | chore(test): remove test_feishu_profile_router.py (v6 cleanup) | +0 | −196 |
- [ ] `dfae252` | 2026-06-12 | `yangtb` | chore(feishu): remove feishu_profile_router.py (v6 cleanup) | +0 | −403 |
- [ ] `71b0869` | 2026-06-11 | `yangtb` | test(providers): update DeepSeek thinking test for MiniMax carve-out | +9 | −4 |
- [ ] `a311083` | 2026-06-11 | `yangtb` | feat(providers): MiniMax Anthropic endpoint thinking-block support | +32 | −4 |
- [⏸️ 已决策·暂不迁移（rate limiter 不存在于 owner-v16，需整体评估）] `b263fd5` | 2026-06-11 | `yangtb` | config: reduce openrouter rate limit to 20 req/min | +1 | −1 |
- [ ] `25561ad` | 2026-06-11 | `yangtb` | feat(providers): credential validation + model list overrides in /providers | +97 | −9 |
- [ ] `fc9c899` | 2026-06-10 | `yangtb` | feat(qdrant-recall): patch.yaml 配置化 + bot_menu 命令跳过 | +72 | −1 |
- [ ] `1fe0bf4` | 2026-06-10 | `yangtb` | feat(recall-card): compact标题增加 content 首行 # 提取 fallback | +8 | −5 |
- [ ] `28d65f8` | 2026-06-10 | `yangtb` | fix(feishu-card): diff/recall card cache 添加 3 小时 TTL | +35 | −10 |
- [ ] `b0e4483` | 2026-06-10 | `yangtb` | feat(qdrant-recall): 飞书卡片展示 + compact标题显示name/abstract | +361 | −3 |
- [ ] `eb514ee` | 2026-06-10 | `yangtb` | feat: skill script auto-approval (skill_script_allowlist) | +637 | −0 |
- [ ] `8c0b8dd` | 2026-06-10 | `yangtb` | feat(approval): auto-resolve pending approvals when YOLO enabled | +56 | −15 |
- [ ] `6f86bcd` | 2026-06-10 | `yangtb` | feat(gateway): strip hook-injected extra_context from history and archiving | +28 | −5 |
- [ ] `fbfa354` | 2026-06-10 | `yangtb` | feat(feishu): use 🟥 for memory proposal deny button | +4 | −4 |
- [ ] `84c7489` | 2026-06-10 | `yangtb` | chore(owner): restore local adjustments for qdrant hook (named vector search), session-archiver (DeepSeek/DashScope), pricing.yaml | +62 | −100 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`c24c8ee` | 2026-06-09 | `yangtb` | docs(owner): patch inventory 69→73, add P70-P71 (clarify multi-profile, display_hook_message_receive) | +14 | −5 |
- [x] ✅ 已迁移 `825145f` | 2026-06-09 | `yangtb` | docs(owner): patch inventory 65→69, add P66-P69 (intent-guard, credential_pool, qdrant-recall, session-archiver) | +18 | −2 |
- [x] ✅ 已迁移 `c974c92` | 2026-06-09 | `yangtb` | docs(owner): update patch inventory to 65, add P65 yolo tri-state entry | +4 | −3 |
- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `9b4dda1` | 2026-06-09 | `yangtb` | docs(AGENTS): update project structure and development guide | +187 | −81 |
- [ ] `ca0836e` | 2026-06-09 | `yangtb` | chore(config): add yolo_on/yolo_off ack text + sync patch.yaml | +17 | −1 |
- [ ] `e7d351c` | 2026-06-09 | `yangtb` | fix(feishu): bot_menu synthetic event message_id → None | +1 | −1 |
- [ ] `1be0241` | 2026-06-09 | `yangtb` | feat(gateway): /yolo on\ | off\ | status syntax sugar |
- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `8b5f0f7` | 2026-06-09 | `yangtb` | chore(config): update pricing.yaml exchange rate | +1 | −1 |
- [ ] `ef0d7bf` | 2026-06-09 | `yangtb` | fix(credential_pool): reject classic PATs in copilot env seeding | +11 | −0 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`88a8156` | 2026-06-08 | `yangtb` | docs(owner): add 6 patches to README (P58-P63 feishu + P62 tools) | +9 | −3 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`9f6fecd` | 2026-06-08 | `yangtb` | docs(owner): dual-agent cross-review architecture design draft | +354 | −0 |
- [ ] `8eadc82` | 2026-06-08 | `yangtb` | fix(feishu): bot_menu_dedup 对齐新增 model key | +4 | −0 |
- [ ] `b0a8f3c` | 2026-06-08 | `yangtb` | feat(feishu): bot_menu 增加 mimo / minimax 模型快捷键 | +2 | −0 |
- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `ab5cda7` | 2026-06-08 | `yangtb` | chore(owner): pricing.yaml daily exchange rate update | +1 | −1 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`86f575e` | 2026-06-08 | `yangtb` | docs(owner): archive rolled-back clarify-timeout-abort design | +108 | −0 |
- [x] ✅ 已迁移 `47a8e5db6` `e49f512` | 2026-06-08 | `yangtb` | feat(feishu): expire_clarify on timeout — grey card + interrupt turn | +145 | −3 |
- [x] ✅ 已迁移 `7646add45` `5022ef4` | 2026-06-08 | `yangtb` | feat(tools): auto_fix_start option to unified_diff_patch | +124 | −21 |
- [ ] `b845c7a` | 2026-06-08 | `yangtb` | fix(code_execution): 🐍 → 🛠️ execute_code tool emoji | +1 | −1 |
- [ ] `16ae8a0` | 2026-06-08 | `yangtb` | chore(skills): remove custom skills from source tree | +0 | −1054 |
- [ ] `d490793` | 2026-06-08 | `yangtb` | scripts(backup-hermes-config): graceful fallback on patch.yaml parse error | +18 | −10 |
- [ ] `c09616f` | 2026-06-08 | `yangtb` | hooks(qdrant-memory-recall): filter disabled=true points | +5 | −1 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`5af60e9` | 2026-06-08 | `yangtb` | skills: add claude-code reference docs | +578 | −0 |
- [ ] `8333e30` | 2026-06-08 | `yangtb` | scripts: add skills_sync_preview utility | +218 | −0 |
- [x] ✅ 已迁移 `7646add45` `6976b60` | 2026-06-08 | `yangtb` | tools: add auto_fix_header option to unified_diff_patch | +48 | −12 |
- [ ] `2f97677` | 2026-06-08 | `yangtb` | hooks: skip synthetic gateway messages in qdrant recall | +20 | −0 |
- [ ] `b47978f` | 2026-06-08 | `yangtb` | config: update default exchange rate to 6.7928 | +1 | −1 |
- [x] ✅ 已迁移 `2f1be0a` | 2026-06-07 | `yangtb` | minimax-cn: 收敛 catalog 到 M3/M2.7/M2.7-highspeed + aux 默认走 highspeed | +12 | −13 |
- [ ] `91460d8` | 2026-06-07 | `yangtb` | feat(feishu): model picker — alphabetical providers + back button | +22 | −0 |
- [ ] `adc1f0e` | 2026-06-07 | `yangtb` | fix(qdrant-memory-recall): filter low_quality hits to reduce hallucination risk | +8 | −2 |
- [ ] `0a2ea99` | 2026-06-06 | `yangtb` | docs(qdrant-memory-recall): clarify per-turn extra_context scope (CR-01) | +21 | −2 | ⚠️ 混有代码：hooks/qdrant-memory-recall/HOOK.yaml + handler.py
- [x] ✅ 已迁移（代码部分；测试文件后续单独迁移）`47a8e5db6` `4626a1a` | 2026-06-06 | `yangtb` | fix(feishu-clarify): prepend full-text markdown options block before button row | +175 | −21 |
- [ ] `111f767` | 2026-06-06 | `yangtb` | fix(tool_guardrails): name the counter and threshold in warn messages | +78 | −5 |
- [x] ✅ 已迁移 `7646add45` `6f64470` | 2026-06-06 | `yangtb` | docs(unified_diff_patch): clarify schema descriptions (5 fixes) | +79 | −61 | ⚠️ 混有代码：tools/unified_diff_patch_tool.py
- [x] ✅ 已迁移 `7646add45` `a3b95e7` | 2026-06-06 | `yangtb` | fix(unified_diff_patch): 4 quality fixes (strict priority, line numbers, CRLF, dry_run) | +352 | −8 |
- [ ] `c536033` | 2026-06-06 | `yangtb` | feat(session-archiver): add ts field to event payload for Qdrant time-ordering | +1 | −0 |
- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `750ceb9` | 2026-06-06 | `yangtb` | chore(owner): pricing.yaml daily exchange rate update | +1 | −1 |
- [ ] `2a6f213` | 2026-06-06 | `yangtb` | feat(owner): qdrant-memory-recall hook 部署 | +346 | −0 |
- [ ] `69af045` | 2026-06-06 | `yangtb` | feat(owner): display_hook_message_receive config | +142 | −1 |
- [ ] `e5e0e4e` | 2026-06-05 | `yangtb` | chore(owner): list_models quick-action + pre_tool_call hooks stub | +4 | −0 |
- [ ] `137fd1c` | 2026-06-05 | `yangtb` | feat(commands): /providers command (feishu card + text fallback) | +58 | −0 |
- [ ] `502decf` | 2026-06-05 | `yangtb` | feat(feishu): interactive model picker card (schema 2.0) | +176 | −0 |
- [ ] `2be890a` | 2026-06-05 | `yangtb` | fix(intent-guard): fix 8 correctness issues found in code review | +98 | −70 |
- [ ] `a23b5fd` | 2026-06-05 | `yangtb` | feat(intent-guard): add circuit breaker + retry + 30s timeout + notify reserve | +294 | −18 |
- [ ] `deb958e` | 2026-06-05 | `yangtb` | chore(config): update CNY exchange rate | +1 | −1 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`460c4c6` | 2026-06-05 | `yangtb` | docs(owner): document file tool hang behavior and stop recovery | +370 | −0 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`29e6ba6` | 2026-06-05 | `yangtb` | docs(owner): add feishu single-bot multi-profile design iterations | +1040 | −0 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`dd936e1` | 2026-06-05 | `yangtb` | docs(owner): add README notes for gateway daemon exit timeout | +26 | −0 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`4a9a79c` | 2026-06-05 | `yangtb` | docs(intent-guard): add architecture doc and adversarial review report | +779 | −0 |
- [ ] `2172689` | 2026-06-05 | `yangtb` | feat(intent-guard): integrate interrupt protocol into Hermes core | +193 | −44 |
- [ ] `97ab075` | 2026-06-05 | `yangtb` | feat(intent-guard): add pre_tool_call hook with hard rules + LLM audit | +1006 | −5 |
- [x] ✅ 已迁移·部分（clarify 卡片部分；多 profile 路由已有独立 v6 方案）`47a8e5db6` `c6b87d9` | 2026-06-04 | `yangtb` | feat(clarify): 飞书 clarify 卡片 + 多 profile 路由 + 跨平台 choice display | +1339 | −67 |
- [x] ✅ 已迁移 `7646add45` `675f180` | 2026-06-04 | `yangtb` | fix(unified_diff_patch): add strict mode, clarify path resolution and guardrail errors | +255 | −17 |
- [ ] `77862a9` | 2026-06-04 | `yangtb` | feat(qdrant-insert): add skill source files (from feishu ff47ea5f3) | +476 | −0 |
- [ ] `df5471a` | 2026-06-04 | `yangtb` | chore(owner): cleanup hooks and scripts | +450 | −273 |
- [ ] `0b160cd` | 2026-06-04 | `yangtb` | chore(scripts): remove sre-archive.py (deployment removed 2026-05-28; orphan source cleanup) | +0 | −490 |
- [ ] `d93318d` | 2026-06-04 | `yangtb` | fix(reasoning): downgrade xhigh→high for Kimi; add bot_menu contract note; extend BM25 hash to 64-bit | +12 | −1 |
- [ ] `3468b67` | 2026-06-04 | `yangtb` | refactor(cost-estimate): add CLI args, dynamic exchange rate, improve code quality | +114 | −63 |
- [ ] `c41dffd` | 2026-06-04 | `yangtb` | fix(session-archiver): add log retention cleanup, fix tool_calls parse, fix Qdrant vectors | +24 | −27 |
- [ ] `2d38c8d` | 2026-06-04 | `yangtb` | perf(feishu): debounce chat_id cache writes to avoid sync I/O on hot path | +37 | −3 |
- [ ] `75db996` | 2026-06-04 | `yangtb` | feat(model): add MiniMax-M3 to provider catalog and opencode model lists | +4 | −0 |
- [ ] `9a8adcb` | 2026-06-04 | `yangtb` | feat(config): update bot_menu emoji ack for feishu | +11 | −11 |
- [ ] `0b50165` | 2026-06-04 | `yangtb` | feat(patch): add sync_sre_king bot menu command | +4 | −1 |
- [ ] `f747157` | 2026-06-04 | `yangtb` | feat(feishu): add sync_git_hermes bot menu entry with ack config | +3 | −0 |
- [ ] `aad84a1` | 2026-06-04 | `yangtb` | fix(feishu): persist p2p_chat_id to disk cache | +39 | −1 |
- [ ] `c0d5e2a` | 2026-06-04 | `yangtb` | feishu: aiohttp timeout 10→60s; pricing: 汇率更新; patch: inspect_gpu_cluster ack; 新增 hy3 成本估算脚本 | +176 | −2 |
- [ ] `b933cd6` | 2026-06-03 | `yangtb` | feat: add session-archiver plugin | +727 | −0 |
- [x] ✅ 已迁移 `7646add45` `248bdb4` | 2026-06-03 | `yangtb` | docs: enhance unified_diff_patch schema with hunk counting rule and absolute path trick | +18 | −1 | ⚠️ 混有代码：tools/unified_diff_patch_tool.py
- [ ] `ab8fd79` | 2026-06-03 | `yangtb` | feat(feishu): bot menu dedup + configurable ack + reasoning xhigh | +384 | −1 |
- [ ] `fd20634` | 2026-06-03 | `yangtb` | fix(feishu): allow non-slash commands in bot_menu mapping | +1 | −1 |
- [ ] `a612263` | 2026-06-03 | `yangtb` | feat(feishu): add built-in bot_menu fallback + inspect_gpu_cluster menu item | +31 | −4 |
- [ ] `feac9c1` | 2026-06-03 | `yangtb` | fix(kimi-coding): correct base_url and api_mode for Kimi Coding Plan | +5 | −2 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`cbf4a70` | 2026-06-03 | `yangtb` | feat(owner): add generic SOUL.md template | +80 | −0 |
- [ ] `f31b40d` | 2026-06-03 | `yangtb` | feat(patch): add reasoning/model menu shortcuts, clean naming | +9 | −3 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`38304b8` | 2026-06-03 | `yangtb` | docs(owner): update README with P57 feishu bot menu + user cache | +3 | −2 |
- [ ] `d1ab5c8` | 2026-06-03 | `yangtb` | feat(feishu): bot menu events + structured user cache | +203 | −25 |
- [ ] `f1ba3bb` | 2026-06-03 | `yangtb` | fix: feishu diff card logging + memory proposal cleanup | +11 | −1 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`171d976` | 2026-06-03 | `yangtb` | docs: add feishu bot menu + user cache and rate limiter concurrency analysis | +485 | −0 |
- [ ] `53ff4d2` | 2026-06-03 | `yangtb` | refactor: simplify DEFAULT_AGENT_IDENTITY to concise Chinese, remove aggressive directives | +4 | −14 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`47b44a5` | 2026-06-02 | `yangtb` | docs: expand Phase 3 section with container design decisions | +83 | −9 |
- [ ] `f3de5be` | 2026-06-02 | `yangtb` | docs: add hermes config customizations classification + shareable baseline | +936 | −0 | ⚠️ 混有配置：owner/docs/shareable-config.yaml
- [ ] `4242bea` | 2026-06-02 | `yangtb` | feat(feishu): add profile routing layer for multi-user dispatch (Phase 2) | +103 | −3 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`432fb0b` | 2026-06-02 | `yangtb` | docs: update feishu-multi-profile-routing spec with Phase 2 implementation details | +102 | −14 |
- [ ] `05faa2c` | 2026-06-02 | `yangtb` | feat(api_server): support X-Hermes-Reply-Via: feishu for profile container RPC | +109 | −0 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`b088690` | 2026-06-02 | `yangtb` | docs: add feishu multi-profile routing design spec | +207 | −0 |
- [ ] `deacdc3` | 2026-06-02 | `yangtb` | chore: remove yangtb/scripts/ directory | +0 | −274 |
- [ ] `947f141` | 2026-05-31 | `yangtb` | fix(memory_propose): WR-08/09/10 — fix Feishu card button not responding and store injection | +105 | −56 |
- [x] ✅ 已迁移 `47a8e5db6` `0ef6b91` | 2026-05-31 | `yangtb` | fix(feishu): clarify card freeze buttons + store choices in _clarify_state | +120 | −1 |
- [ ] `4130359` | 2026-05-31 | `yangtb` | fix(tool_executor): remove duplicate pre-tool-call block logic from merge | +1 | −15 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`cb208c5` | 2026-05-31 | `yangtb` | docs(owner): fix 3 README discrepancies found during merge audit | +3 | −3 |
- [x] ⏭️ 跳过 `a7ede52` | 2026-05-31 | `yangtb` | Merge main (synced with upstream) into owner | +0 | −0 |
- [ ] `6378913` | 2026-05-31 | `yangtb` | feat: memory proposal approval system + unified_diff_patch display support | +857 | −15 |
- [x] ✅ 已迁移 `7646add45` `091bb10` | 2026-05-30 | `yangtb` | fix: unified_diff_patch路径解析 + daily-report sessions格式 + 禁用旧patch工具 | +7 | −3 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`3a9103b` | 2026-05-30 | `yangtb` | P54: add unified_diff_patch_tool record to owner/README | +9 | −1 |
- [x] ✅ 已迁移 `7646add45` `d399df6` | 2026-05-30 | `yangtb` | feat(tools): add unified_diff_patch tool with exact line-number replacement | +551 | −5 |
- [x] ⏭️ 全部跳过：hermes_state.py(P12 已覆盖)/owner/README.md(文件不存在)/patch.yaml(已是57)/pricing.yaml(定价废弃)/file_tools.py(legacy工具，被unified_diff_patch替代) `2458489` | 2026-05-30 | `yangtb` | chore(owner): P12 orphan removal + Phase1 docs + minor config updates | +39 | −116 |
- [ ] `3141715` | 2026-05-30 | `yangtb` | fix(feishu): resolve sender name for approval card using open_id instead of short user_id | +5 | −2 |
- [x] ✅ 已迁移 `1a4aa7bf6` `90c9f20` | 2026-05-30 | `yangtb` | feat(patch): feishu: raise auto_card_threshold to 41, add interim/tool_progress settings | +7 | −1 |
- [x] ⚠️ 废弃（纯删除已不存在的脚本，无功能价值）`08253ae` | 2026-05-29 | `yangtb` | chore: remove obsolete yangtb/scripts/send_daily_report.py (was accidentally committed by daily-report cron, caused persistent merge conflicts) | +0 | −76 |
- [x] ✅ 已迁移 `2c383a2` | 2026-05-29 | `yangtb` | merge: resolve conflict with gitlab/yangtb — keep HEAD P35+P36, adopt yangtb's send_daily_report (5-26 version) | +0 | −0 |
- [x] ⚠️ 废弃（owner-v16 已覆盖：qqbot 已包含 'dm' chat_type；auditor-guard 已被 P66 Intent Guard 替代）`480bf03` | 2026-05-29 | `yangtb` | fix(qqbot): add 'dm' chat_type to approval authorization | +2 | −3291 |
- [ 

... [OUTPUT TRUNCATED - 2046 chars omitted out of 52046 total] ...

[x] ⏭️ 跳过 `a77231c` | 2026-05-28 | `yangtb` | Merge upstream/main into owner (v0.14.0+) | +0 | −0 |
- [ ] `c5b6992` | 2026-05-28 | `yangtb` | chore: remove viking-hint hook (empty stub, never implemented) | +0 | −49 |
- [x] ⚠️ 废弃（手动补录 — 功能已被 upstream #15844 + custom_providers Step 0b 覆盖）`4a60dd1c` | 2026-05-28 | `yangtb` | fix(model_metadata): support dict format provider models in get_model_context_length (P41) | +21 | −12 |
- [x] 📌 待统一处理i18n（纯i18n，仅locales文件）`0c23b27` | 2026-05-27 | `yangtb` | i18n(zh): add all 85 missing tirith rule translations, remove 2 stale entries | +193 | −9 |
- [x] ✅ 已迁移 `44d7189c5` `bf295cd` | 2026-05-27 | `yangtb` | refactor(gateway): 外部 restart 走 launchctl kickstart -k 原子化生命周期 | +24 | −13 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`67373f7` | 2026-05-27 | `yangtb` | docs(owner): 新增 P39 飞书 Diff 卡片 + P40 step_callback 去 hooks 依赖 | +4 | −2 |
- [x] ⚠️ 废弃（已被 owner/diff_card/ 替代）`06c911a` | 2026-05-27 | `yangtb` | feat(feishu): patch/write_file 完成后发送 diff 卡片（红绿背景 + 查看完整 diff 按钮） | +207 | −1 |
- [⏸️ 已决策·暂不迁移（rate limiter 不存在于 owner-v16，需整体评估）] `016bb35` | 2026-05-27 | `yangtb` | chore(config): 移除 nous rate limit 配置，damodel max_requests 提频 30→60 | +1 | −4 |
- [ ] `1c887ef` | 2026-05-27 | `yangtb` | feat(feishu): approvals 卡片回调异步更新用户名，显示命令内容 | +67 | −17 |
- [⏸️ 已决策·暂不迁移（rate limiter 不存在于 owner-v16，需整体评估）] `601e79e` | 2026-05-27 | `yangtb` | chore(owner): add xfyun rate limit config to patch.yaml | +3 | −0 |
- [x] ✅ 已迁移 `25f1996` | 2026-05-27 | `yangtb` | docs(owner): 同步 patch 清单 P35-P38 + P9 CallBackCard 升级 | +12 | −8 |
- [x] ⚠️ 废弃：上游已修复，.env 加载时机已无问题 `2b801e5` | 2026-05-27 | `yangtb` | fix(gateway): eagerly load .env before any import that triggers load_config() | +15 | −0 |
- [ ] `c9cc868` | 2026-05-27 | `yangtb` | fix(feishu): return CallBackCard in approval card action to update card inline | +13 | −3 |
- [x] ✅ 完成-取部分 `9589b4940` `b7a199b` | 2026-05-26 | `yangtb` | feat: Viking health report API rewrite + fix TUI Cmd+C on macOS | +276 | −3 | （TUI Cmd+C fix 已提取；Viking health report 废弃）
- [x] ✅ 已迁移 `8d359ee` | 2026-05-26 | `yangtb` | docs(yangtb): register P35 — extract_local_files double-backtick code span fix | +4 | −3 |
- [x] ✅ 已迁移 `ff19a78` | 2026-05-26 | `yangtb` | fix(gateway): add double-backtick code span detection in extract_local_files | +155 | −9 |
- [x] ✅ 已迁移 `ca3c24f` | 2026-05-26 | `yangtb` | fix(gateway): add double-backtick code span detection in extract_local_files | +146 | −5 |
- [x] 📌 待统一处理i18n（approval 文案中文化，零功能改动）`d31f26b` | 2026-05-26 | `yangtb` | feat(i18n): translate all approval descriptions to Chinese via i18n | +333 | −16 |
- [x] ⚠️ 废弃（pricing.yaml 不迁移；owner-v16 无 backup-configs.sh，已由 backup-hermes-config.py 替代）`9ef510c` | 2026-05-26 | `yangtb` | chore(owner): pricing rate update + backup-configs mkdir fallback | +8 | −5 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`8051cd9` | 2026-05-26 | `yangtb` | docs(owner): P33 approvals patch.yaml 白名单 — patch 清单更新 | +2 | −1 |
- [ ] `5ac061b` | 2026-05-26 | `yangtb` | feat(approval): patch.yaml 白名单支持 — load_permanent_allowlist() 合并 owner.approvals.command_allowlist | +20 | −2 |
- [x] ⚠️ 废弃（owner-v16 无 viking-auto-commit.py 脚本，Viking 已停用）`49f6a6d` | 2026-05-25 | `yangtb` | fix: viking-auto-commit 直接用 expanduser(~) 推导家目录 | +1 | −3 |
- [x] ✅ 部分采纳 `.gitignore` 部分；`patch.yaml` backup excludes 已由 `owner/scripts/backup-hermes-config.py` 的 DEFAULT_CONFIG 覆盖 `f796063` | 2026-05-25 | `yangtb` | chore(owner): batch update scripts, hooks, config + gitignore .claude/.local | +186 | −73 |
- [x] ⚠️ 废弃（owner-v16 官方文件中已无 yangtb 残留，清理已完成）`38aa3ce` | 2026-05-23 | `yangtb` | chore: purge yangtb references — comments, paths, viking user → owner/default | +38 | −38 | ⚠️ 混有代码：credential_pool.py + usage_pricing.py + scheduler.py + run.py 等9文件
- [x] ⏭️ 跳过（owner-v16 使用 Qdrant，无 Viking prefetch 需求，该开关不适用）`10d296e` | 2026-05-23 | `yangtb` | feat(memory): owner.memory.prefetch_enabled — disable passive Viking recall | +24 | −5 |
- [x] ⏭️ 跳过（owner/ 目录结构与命名迁移已由 `fb19877` 等分散完成）`5311fe2` | 2026-05-23 | `yangtb` | feat: migrate personal profile from yangtb to owner | +49 | −12080 |
- [⏸️ 已决策·暂不迁移（xai-oauth/grok 相关，待上游稳定后评估）] `4e7faf4` | 2026-05-22 | `yangtb` | fix(xai-oauth): dual-field argument extraction for codex_responses normalize | +36 | −7 |
- [⏸️ 已决策·暂不迁移（rate limiter 不存在于 owner-v16，需整体评估）] `611f972` | 2026-05-22 | `yangtb` | config: add damodel provider rate limiting to owner/yangtb profiles | +6 | −0 |
- [⏸️ 已决策·暂不迁移（recovery context 注入为独立功能，需与 fad4db4 一起评估）] `288342c` | 2026-05-22 | `yangtb` | yangtb-patch: gateway session — add API disconnect recovery context + skills_loaded tracking | +26 | −1 |
- [x] ⏭️ 跳过 `c03e8da` | 2026-05-22 | `yangtb` | Merge upstream/main into owner | +0 | −0 |
- [x] ⚠️ 废弃：上游已重构，_limiter 不存在 `30ab336` | 2026-05-22 | `yangtb` | fix(credential_pool): False sentinel bypasses _limiter None check in select() | +3 | −1 |
- [⏸️ 已决策·暂不迁移（xai-oauth/grok 相关，待上游稳定后评估）] `1588a1e` | 2026-05-22 | `yangtb` | tools+prompt: harden patch schema descriptions; add Grok-4.3 tool-calling guidance | +41 | −2 |
- [x] ✅ 已迁移（实现于 owner/display_overrides.py；gateway/display_config.py 与 gateway/run.py 仅保留 [owner] 胶水）`8968786` | 2026-05-22 | `yangtb` | display: per-chat override support with patch.yaml integration | +67 | −13 |
- [x] ✅ 已覆盖（owner/ 目录结构与命名迁移已由多个 commit 分散完成；auditor-guard/sre-archive/viking/token_stats/pricing 等按决策废弃）`fb19877` | 2026-05-22 | `yangtb` | feat: migrate from yangtb to owner profile | +12109 | −61 |
- [x] ✅ 已迁移 `489b7f886` | 2026-05-22 | `yangtb` | feat(cron): replace todo-scan.py with robust todo-scan.sh (macFUSE timeout protection) | +58 | −0 |
- [x] ✅ 已迁移 `e64a1aeac` `489aafd` | 2026-05-22 | `yangtb` | P31: 飞书审批卡片"永久允许"按钮可配置隐藏 | +61 | −28 |
- [x] ⚠️ 废弃（唯一消费者为 viking-hint 空 handler，且 owner-v16 不需要 message:receive hook 点）`64f53b1` | 2026-05-22 | `yangtb` | feat: add message:receive hook scaffolding for Viking context hint | +68 | −1 |
- [x] ⚠️ 废弃（inline_code_copy 不再需要；feishu_card→feishu.card 命名空间重构与 owner-v16 目标命名空间 owner.feishu_card.* 不一致）`287a391` | 2026-05-22 | `yangtb` | feat(feishu): inline_code_copy configurable via patch.yaml, default off | +24 | −4 |
- [⏸️ 已决策·暂不迁移（rate limiter 不存在于 owner-v16，需整体评估）] `40e43ab` | 2026-05-22 | `yangtb` | feat(rate-limiter): add stepped cooldown + sliding window fixes | +574 | −15 |
- [x] ⚠️ 废弃（仅删除 viking-commit-runner.py wrapper，viking 相关组件在 owner-v16 已不存在）`89476ee` | 2026-05-22 | `yangtb` | 删除废弃的 viking-commit-runner.py wrapper | +0 | −5 |
- [x] ⚠️ 废弃（auditor-guard / sre-archive / viking / memory-guard 已不存在于 owner-v16）`5cd5d81` | 2026-05-21 | `yangtb` | chore(scripts): reorganize mac-specific scripts + add backup config | +227 | −111 |
- [x] ⚠️ 废弃（auditor-guard / sre-archive / viking / memory-guard 已不存在于 owner-v16）`54af397` | 2026-05-21 | `yangtb` | refactor(patch): consolidate hook configs under yangtb.hook namespace | +27 | −22 |
- [x] ⚠️ 废弃（auditor-guard / sre-archive / viking / memory-guard 已不存在于 owner-v16）`cdddbe2` | 2026-05-21 | `yangtb` | 修复auditor guard hook | +90 | −0 |
- [x] ⚠️ 废弃（auditor-guard / sre-archive / viking / memory-guard 已不存在于 owner-v16）`75eda7d` | 2026-05-21 | `yangtb` | refactor(hooks): remove mac/shell fallbacks, flatten viking-remember-guard | +93 | −211 |
- [x] ⚠️ 废弃（auditor-guard / sre-archive / viking / memory-guard 已不存在于 owner-v16）`b791919` | 2026-05-21 | `yangtb` | chore(hooks): switch auditor-guard/memory-guard to DAMODEL API, remove memory-guard | +8 | −174 |
- [x] ✅ 已迁移（cron args + model_extra_body；backup scripts 按决策忽略）`37e6fba` → `b84b43927` | 2026-05-21 | `yangtb` | feat: model-level extra_body injection + cron args + backup scripts | +634 | −112 |
- [x] ✅ 已迁移（改为 owner_provider_name，保持 agent.provider 不变，新增 DB 字段写入 sessions/messages）`9e96955` | 2026-05-21 | `yangtb` | feat(provider): add provider_custom_name field for custom provider identity | +17 | −6 |
- [x] ⚠️ 废弃（probe fall-through 已被 2e61de063 覆盖，P41 完整功能已被 custom_providers Step 0b 覆盖）`c7e5aaa` | 2026-05-20 | `yangtb` | fix: fall through to hardcoded defaults when model context length probe fails (prevent deepseek-v4-flash 1M default from being bypassed) | +50 | −6 |
- [x] ⚠️ 废弃（yangtb/hooks/audit-agent 不存在于 owner-v16）`ed95a26` | 2026-05-20 | `yangtb` | chore: remove audit-agent hook (agent:end file-change detection) | +1 | −973 |
- [x] ⚠️ 废弃（修 b6e9852 hook chain 传参 bug — b6e9852 已废弃，hook chain 在 owner-v16 已重构）`2218a70` | 2026-05-20 | `yangtb` | fix: agent.chat_id -> agent._chat_id (AIAgent stores as _chat_id) | +6 | −6 |
- [x] ⚠️ 废弃（yangtb/hooks/auditor-guard 不存在于 owner-v16 — owner-v16 hook chain 已重构，P66 Intent Guard 替代）`b6e9852` | 2026-05-20 | `yangtb` | fix: pass platform/chat_id/user_message through pre_tool_call hook chain | +118 | −3 |
- [x] 📌 待统一处理i18n（纯i18n，run.py字符串替换+locales）`188be9d` | 2026-05-20 | `yangtb` | refactor: extract destructive_slash_confirm hardcoded strings into i18n locale files | +100 | −14 |
- [x] ⚠️ 废弃（yangtb/hooks/auditor-guard 不存在于 owner-v16 — P66 Intent Guard 替代）`7d7cc28` | 2026-05-20 | `tianbao.yang` | feat(auditor-guard): suppress Branch D notification when built-in Approvals already approved the pattern | +42 | −10 |
- [x] ⏭️ 跳过（仅改 yangtb/hooks/auditor-guard/rules.py；auditor-guard 不存在于 owner-v16，已被 P66 Intent Guard 替代）`94ccc55` | 2026-05-20 | `tianbao.yang` | fix(auditor-guard): align APPROVAL_FALLBACK_PATTERNS with Hermes DANGEROUS_PATTERNS + suppress Tirith variation_selector noise | +66 | −51 |
- [x] 📌 待统一处理i18n（纯i18n：approval.py BLOCKED 文案 + feishu.py 审批卡片文案走 t()，en/zh.yaml 各 +25 key，零功能改动）`bb19362` | 2026-05-20 | `tianbao.yang` | feat(i18n): approvals 文案中文化 — 硬编码英文全部接入 t() 翻译 | +111 | −59 |
- [x] ⚠️ 废弃（重命名无真实冲突，且会增加 upstream merge 成本；核心 model 参数已单独迁移）`f138db1` | 2026-05-20 | `tianbao.yang` | refactor: replace plugins/image_gen/openai with openai_native | +388 | −38 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`befa350` | 2026-05-20 | `tianbao.yang` | docs(yangtb): add P30 (bare-domain base_url /v1 auto-append) to patch list | +4 | −3 |
- [x] ✅ 已迁移 `a16843e` | 2026-05-20 | `tianbao.yang` | feat: auto-append /v1 for bare-domain base URLs (normalize_bare_domain_base_url) | +62 | −0 |
- [x] ✅ 已迁移 `b917674` | 2026-05-20 | `tianbao.yang` | fix(agent): acp_args 空列表应存为 None 而非 [] | +1 | −1 |
- [x] ✅ 已迁移（代码：model 参数；配置：dashscope presets；汇率更新未迁移；openrouter 预留未实现）`022d45b` | 2026-05-20 | `tianbao.yang` | feat(image_gen): add model param to image_generate tool + yaml presets; update exchange rate | +52 | −9 |
- [x] ⏭️ 跳过（混合 commit，各部分均无需迁移：auditor-guard notification/templates 不存在于 v16；backup-hermes-config 静默模式已在 owner/scripts/；backup-viking 已废弃；locales/zh.yaml 单条归 i18n 批次）`f248f27` | 2026-05-20 | `tianbao.yang` | fix(auditor): 飞书卡片段落间 hr 重复横线问题 | +10 | −15 |
- [x] ⏭️ 跳过：revert commit `a6a18b3` | 2026-05-19 | `tianbao.yang` | Revert "feat(transports): add URL-based reasoning_effort support for LKeap/DeepSeek/DaModel" | +0 | −51 |
- [x] ⚠️ 跳过（revert commit）`eb1df5d` | 2026-05-19 | `tianbao.yang` | Revert "refactor: extract _resolve_reasoning_effort helper, merge LKeap dual blocks" | +61 | −79 |
- [x] ⏭️ 跳过：revert commit `b30e774` | 2026-05-19 | `tianbao.yang` | Revert "fix: remove hardcoded extra_efforts from _resolve_reasoning_effort" | +15 | −5 |
- [x] ⚠️ 废弃：reasoning_effort 链被 revert `54657dc` | 2026-05-19 | `tianbao.yang` | fix: remove hardcoded extra_efforts from _resolve_reasoning_effort | +5 | −15 |
- [x] ⚠️ 废弃：reasoning_effort 链被 revert `5cbc280` | 2026-05-19 | `tianbao.yang` | refactor: extract _resolve_reasoning_effort helper, merge LKeap dual blocks | +79 | −61 |
- [x] ⚠️ 废弃：yangtb/ 目录不存在，pricing+auditor-guard 已废弃 `083bb20` | 2026-05-19 | `tianbao.yang` | misc(yangtb): update patch list, pricing, auditor-guard templates | +11 | −3 |
- [x] ⚠️ 废弃：reasoning_effort 链被 revert `1d00af0` | 2026-05-19 | `tianbao.yang` | feat(transports): add URL-based reasoning_effort support for LKeap/DeepSeek/DaModel | +51 | −0 |
- [x] ⚠️ 废弃：yangtb/README.md 纯文档 `9407c34` | 2026-05-19 | `tianbao.yang` | docs(yangtb): align patch list with v0.14.0 merge (P12/P22/P27/P28 marked covered) | +17 | −3 |
- [x] ⚠️ 废弃：yangtb/README.md 纯文档 `862b2cb` | 2026-05-19 | `tianbao.yang` | docs: bump patch count to 25 groups / 32 items, add P26 i18n gateway messages | +3 | −2 |
- [x] 📌 待统一处理i18n（纯i18n，零功能改动，16个locale文件）`5110f6b` | 2026-05-19 | `tianbao.yang` | i18n: translate gateway lifecycle/busy-ack/steer/inactivity messages to Chinese | +480 | −36 |
- [x] `4d33091` | 2026-05-19 | `tianbao.yang` | fix(feishu): add early-typing reaction when chat_lock is held | +25 | −0 | ✅已迁移（改进：存 task 引用防 GC） |
- [x] ⚠️ 废弃（auditor-guard 不存在于 owner-v16）`e2fc1d0` | 2026-05-19 | `tianbao.yang` | auditor-guard: 修复 import 崩溃 + 新增 explain-only 模式 + JSON2 飞书卡片通知 | +349 | −70 |
- [x] ✅ 已迁移 `1a4aa7bf6` `d140932` | 2026-05-18 | `tianbao.yang` | feat(feishu): remove tool-activity filter from auto-card logic | +1 | −41 |
- [x] ✅ 已迁移 `1a4aa7bf6` `becd553` | 2026-05-18 | `tianbao.yang` | fix(feishu): add auto-card retry (3 attempts) + logging before plain-text fallback | +31 | −4 |
- [x] ⚠️ 废弃：上游已重构 provider_name，无残留；owner-v16 用 `owner_provider_name` 独立字段实现 `9e96955` `14d7ea7` | 2026-05-18 | `tianbao.yang` | fix: remove remaining provider_name traces after v0.14.0 merge | +0 | −2 |
- [x] ⏭️ 跳过 `c4d72ab` | 2026-05-18 | `tianbao.yang` | merge: sync yangtb with upstream v0.14.0 (v2026.5.16) | +0 | −0 |
- [x] ✅ 已迁移 `1a4aa7bf6` `429c8d5` | 2026-05-18 | `tianbao.yang` | feat(feishu): upgrade auto-card to JSON 2.0 schema for heading/table support | +4 | −1 |
- [x] ✅ 已迁移 `1a4aa7bf6` `06e17c1` | 2026-05-18 | `tianbao.yang` | feat(feishu): auto-card for long text responses when streaming disabled | +251 | −6 |
- [x] ⚠️ 废弃：auditor-guard hook 已删除 `6dee454` | 2026-05-18 | `tianbao.yang` | refactor(auditor-guard): modular architecture v2 | +2644 | −969 |
- [x] ✅ 已迁移 `2d941f4` | 2026-05-17 | `tianbao.yang` | fix: disk-watch-cron.py 路径修正 — cache-cleanup.py 已移至 mac/ 子目录 | +2 | −2 |
- [x] ⚠️ 废弃（auditor-guard 适配，混入 plugins.py + run_agent.py 参数扩展）`b5cbb31` | 2026-05-17 | `tianbao.yang` | fix(auditor): tirith detection + platform-aware delivery | +69 | −21 |
- [x] ⚠️ 废弃（_append_inline_code_reference 不存在于 owner-v16）`0214365` | 2026-05-17 | `tianbao.yang` | fix(feishu): preserve inline-code order when merging short spans for mobile copy-paste | +23 | −0 |
- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `d83c45b` | 2026-05-17 | `tianbao.yang` | refactor(token_stats): 移除pricing/cost计算，改为纯token用量统计，新增飞书卡片table支持 | +454 | −783 |
- [x] ⚠️ 废弃（auditor-guard 适配，混入 api_server interrupt endpoint + run_agent.py）`01dc1cf` | 2026-05-17 | `tianbao.yang` | feat(auditor): emotion auto-stop via API Server + session_id fix + 文案优化 | +174 | −28 |
- [x] ⚠️ 废弃（auditor-guard 不存在于 owner-v16）`5dc4608` | 2026-05-16 | `tianbao.yang` | fix(auditor-guard): merge session_id into extra for deliver_sync in qqbot | +330 | −158 |
- [x] ⚠️ 废弃（auditor-guard 适配，混入 token-stats-cron.py 等无关改动）`edb1661` | 2026-05-16 | `tianbao.yang` | chore: sync hooks path fixes, update CHANGES.md with timeout→hard block design | +343 | −95 |
- [x] ⚠️ 废弃（auditor-guard 不存在于 owner-v16）`ca2cbe1` | 2026-05-16 | `tianbao.yang` | fix(auditor-guard): Stage 1 detected sensitive path should always trigger LLM audit even when fallback path string fails is_sensitive_path check | +3 | −1 |
- [x] ⚠️ 废弃（token_stats 整体废弃）`979d7b2` | 2026-05-16 | `tianbao.yang` | feat(token_stats): add --from-date parameter for clean start date | +32 | −10 |
- [x] ✅ 已覆盖（provider_name 保存真实身份的需求由 `owner_provider_name` 实现；定价/token_stats 部分仍废弃）`73e2d37` | 2026-05-16 | `tianbao.yang` | fix: provider_name column now stores actual config name (fixes custom→custom bug) fix(token_stats): resolve env vars in ProviderRegistry URL index (case-sensitive) feat(pricing): add deepseek-company pricing (same as deepseek) fix(pricing): correct deepseek cache_read rates (/bin/zsh.0028//bin/zsh.003625 per official docs) | +133 | −10 |
- [x] ⚠️ 废弃（auditor-guard hook 不存在于 owner-v16）`dae8cd2` | 2026-05-16 | `tianbao.yang` | fix(auditor-guard): increase LLM timeout 15→60s, block on timeout instead of silent allow | +43 | −24 |
- [x] ✅ 部分采纳（仅 backup-hermes-config.py、mac/cache-cleanup.py、daily-report.py 取最新版）`cae1a7c` | 2026-05-16 | `tianbao.yang` | refactor(scripts): migrate ~/.hermes/scripts/ to yangtb/scripts/ | +2926 | −8 |
- [x] ✅ 部分覆盖（_convert_tables_to_code_blocks 已删除，当前强制 text mode 绕过）`d682be1` | 2026-05-16 | `tianbao.yang` | fix(feishu): render markdown tables natively in post md elements | +27 | −43 |
- [x] ⚠️ 废弃（auditor-guard hook 不存在于 owner-v16）`afbd94f` | 2026-05-15 | `tianbao.yang` | docs(auditor-guard): add CHANGES.md implementation changelog | +105 | −0 |
- [x] ⚠️ 废弃（auditor-guard hook 不存在于 owner-v16）`a7c635a` | 2026-05-15 | `tianbao.yang` | style(auditor-guard): move emoji to beginning of notification titles | +4 | −4 |
- [x] ⚠️ 废弃（auditor-guard hook 不存在于 owner-v16）`18e0591` | 2026-05-15 | `tianbao.yang` | style(auditor-guard): unify notification message format | +4 | −4 |
- [x] ⚠️ 废弃（auditor-guard hook 不存在于 owner-v16）`3860f6d` | 2026-05-15 | `tianbao.yang` | feat(auditor-guard): pass user_message through hook for real-time approval check | +1726 | −687 |
- [x] ⚠️ 废弃（delivery_helpers 不存在于 owner-v16）`7a05837` | 2026-05-15 | `tianbao.yang` | fix(delivery_helpers): set chat_id in extra dict for _build_headers | +2 | −0 |
- [x] ⚠️ 废弃（delivery_helpers 不存在于 owner-v16）`50880df` | 2026-05-15 | `tianbao.yang` | fix(delivery_helpers): resolve chat_id from HERMES_SESSION_KEY fallback | +55 | −1 |
- [x] ⚠️ 废弃（auditor-guard hook 不存在于 owner-v16）`8f5e18e` | 2026-05-15 | `tianbao.yang` | fix(auditor-guard): deliver hard block message to Feishu chat | +2 | −0 |
- [x] ⚠️ 废弃（auditor-guard hook 不存在于 owner-v16）`f8a5208` | 2026-05-15 | `tianbao.yang` | feat(auditor-guard): enhanced observability logging | +26 | −3 |
- [x] ⚠️ 废弃（auditor-guard hook 不存在于 owner-v16）`68e12e8` | 2026-05-15 | `tianbao.yang` | feat(auditor-guard): emotion-based blocking + user approval check | +86 | −16 |
- [x] ⚠️ 废弃（hooks/common/ 不存在于 owner-v16）`923004a` | 2026-05-15 | `tianbao.yang` | refactor(hooks): extract shared utilities to hooks/common/ | +667 | −32 |
- [⏸️ 已决策·暂不迁移（feishu_get_messages 不存在于 owner-v16，需评估必要性）] `05d2d06` | 2026-05-15 | `tianbao.yang` | feat: add feishu_get_messages tool for reading chat message history | +311 | −0 |
- [x] ✅ 已覆盖（qwen3.6-plus 已在 model_metadata.py）`67cf0fe` | 2026-05-15 | `tianbao.yang` | fix: add qwen3.6/3.5 family entries to DEFAULT_CONTEXT_LENGTHS | +6 | −3 |
- [x] ⏭️ 跳过 `f36852f` | 2026-05-14 | `tianbao.yang` | Merge upstream/main into yangtb (4 conflicts resolved intelligently) | +0 | −0 |
- [x] ⚠️ 废弃（Viking 已停用）`dd36093` | 2026-05-14 | `tianbao.yang` | chore: update daily viking health report script + add .serena config | +135 | −1 |
- [x] ⚠️ 废弃（Viking 已停用）`1ca28d8` | 2026-05-14 | `tianbao.yang` | feat(yangtb): rewrite daily-viking-health-report with full OpenViking diagnostics | +263 | −31 |
- [x] ⚠️ 废弃：定价/token_stats，不迁移 `7b90874` | 2026-05-14 | `tianbao.yang` | refactor: remove channel field from config.yaml, centralize in patch.yaml | +78 | −144 |
- [⏸️ 已决策·暂不迁移（TUI banner 仍硬编码 Nous Research，需整体评估）] `f800b5a` | 2026-05-14 | `tianbao.yang` | feat(tui): dynamic provider name in banner from config.yaml model.provider | +20 | −1 |
- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `2e163aa` | 2026-05-14 | `tianbao.yang` | feat(token_stats): add --card mode for Feishu interactive card delivery | +183 | −1 |
- [x] ⚠️ 废弃（sre-archive hook 已删除 0b160cd）`b242719` | 2026-05-14 | `tianbao.yang` | fix(sre-archive): async subprocess + retry + SKIP exit code + misc hardening | +592 | −62 |
- [x] ✅ 已覆盖（conversation_loop.py 已 pop _thinking_prefill）`c822adb` | 2026-05-13 | `tianbao.yang` | fix(session): source-level thinking-prefill filtering instead of dead read-path check | +7 | −0 |
- [x] ✅ 已覆盖（conversation_loop.py 已 pop _thinking_prefill）`4fee7db` | 2026-05-13 | `tianbao.yang` | fix(session): filter _thinking_prefill messages from get_messages() to prevent thinking leakage | +8 | −1 |
- [x] ✅ 已覆盖（conversation_loop.py 已在消息层面 pop _thinking_prefill）`5a654df` | 2026-05-13 | `tianbao.yang` | fix(gateway): 过滤 thinking prefill 消息，防止污染会话历史 | +7 | −3 |
- [x] ⚠️ 废弃（sre-archive hook 已删除 0b160cd）`a5246ae` | 2026-05-13 | `tianbao.yang` | fix(sre-archive): use gateway/run.py's skill extraction logic instead of custom parser | +83 | −13 |
- [x] ⚠️ 废弃（yangtb/ 目录 + audit-agent 依赖，均不存在于 owner-v16）`62ec570` | 2026-05-13 | `tianbao.yang` | refactor(hooks): 三根日志统一轮转为 DailySizeRotatingFileHandler | +334 | −18 |
- [x] ⚠️ 废弃（_align_table 被 d682be1 飞书原生表格方案替代）`a572c36` | 2026-05-12 | `tianbao.yang` | fix(feishu): emoji width compensation in _align_table | +9 | −1 |
- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `ea163c7` | 2026-05-11 | `tianbao.yang` | feat(token): bailing provider daily 500k free tier support | +134 | −27 |
- [x] ✅ 已迁移 `e7edb2f` | 2026-05-11 | `tianbao.yang` | docs(yangtb): update patch count and add P29 env-var template leak fix to README | +5 | −4 |
- [x] ✅ 已迁移 `85d345e` | 2026-05-11 | `tianbao.yang` | fix: guard against env-var template leak in base_url resolution (#17101) | +22 | −3 |
- [x] ⚠️ 废弃（audit-agent hook 已删除 ed95a26）`14b8a31` | 2026-05-11 | `tianbao.yang` | audit-agent: i18n docstring/comments, get_hermes_home, batch git diff, checkpoint trim | +100 | −49 |
- [⏸️ 已决策·暂不迁移（rate limiter 不存在于 owner-v16，需整体评估）] `6b0c817` | 2026-05-11 | `tianbao.yang` | feat(credential-pool): add proactive sliding-window rate limiter per (provider, key) | +246 | −19 |
- [x] ⚠️ 废弃（audit-agent hook 已删除 ed95a26）`acebc2c` | 2026-05-11 | `tianbao.yang` | audit-agent: filter remote/SSH paths from LLM prompt, add terminal to FILE_MODIFY_TOOLS | +16 | −3 |
- [x] ⚠️ 废弃（audit-agent hook 已删除 ed95a26）`c1a60da` | 2026-05-11 | `tianbao.yang` | audit-agent: add LLM extraction error alert + mv/rm rename tracking | +172 | −17 |
- [x] ⚠️ 废弃（audit-agent hook 已删除 ed95a26）`3dd85dd` | 2026-05-11 | `tianbao.yang` | fix(audit-agent): per-auditor rate limiter, aiohttp delivery, alert improvements | +53 | −24 |
- [x] ⚠️ 废弃（audit-agent hook 已删除 ed95a26）`dae821a` | 2026-05-11 | `tianbao.yang` | refactor(audit-agent): plugin-style auditor architecture with error isolation | +423 | −293 |
- [x] ⚠️ 废弃（audit-agent hook 已删除 ed95a26）`8f8b76c` | 2026-05-10 | `tianbao.yang` | feat(audit-agent): move audit-agent hook source to yangtb/hooks/ | +652 | −1 |
- [x] ⚠️ 废弃（Viking 已停用，Qdrant 是当前 backing store）`f329993` | 2026-05-10 | `tianbao.yang` | feat(yangtb/scripts): 新增 daily-viking-health-report.py — 每日Memory整理报告脚本，对比Viking而非本地KB | +44 | −0 |
- [x] ✅ 已迁移（owner/scripts/ 替代 yangtb/scripts/，exemption 已在 cronjob_tools.py）`1284034` | 2026-05-10 | `tianbao.yang` | fix(cron): add yangtb/scripts/ symlink exemption to _validate_cron_script_path | +9 | −0 |
- [x] ✅ 已迁移·部分（clarify_callback 已在 owner-v16，emoji ❓→🤔 未迁移）`281e6fc` | 2026-05-10 | `tianbao.yang` | fix(gateway): add clarify_callback for messaging platforms | +12 | −2 |
- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `f0176ae` | 2026-05-10 | `tianbao.yang` | refactor(token_stats): multi-currency pricing support + markdown output | +90 | −47 |
- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `32333de` | 2026-05-10 | `tianbao.yang` | docs(yangtb/config): note pricing.yaml fields updated by cron scripts | +1 | −1 |
- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `f64ae67` | 2026-05-10 | `tianbao.yang` | feat(yangtb): add update_exchange_rate.py script + top-level default_exchange_rate in pricing.yaml | +115 | −9 |
- [⏸️ 已决策·暂不迁移] `3ea5daa` | 2026-05-10 | `tianbao.yang` | feat(api-server): expose model_aliases in /v1/models endpoint | +87 | −26 |
- [x] ✅ 已迁移·部分（qqbot _stop_retry 已在 owner-v16，scripts 3个已迁移到 owner/scripts/，token_stats 废弃）`6fe0530` | 2026-05-10 | `tianbao.yang` | fix(qqbot): abort reconnect on disconnect, fix CLOSE→UP state bug | +215 | −34 |
- [x] ✅ 已迁移 `beecdcd` | 2026-05-09 | `tianbao.yang` | fix(gateway): resolve env-var template base_url in _format_session_info | +5 | −1 |
- [x] ✅ 已迁移（proxy=None 已在 owner-v16 qqbot adapter 中）`1fc7348` | 2026-05-09 | `tianbao.yang` | fix(qqbot): set proxy=None instead of proxies={} for httpx client | +1 | −1 |
- [⏸️ 已决策·暂不迁移（model_aliases P24 为 local-only 功能，qqbot proxy 已迁移，yangtb/ 文件废弃）] `ccfcdab` | 2026-05-09 | `yangtb` | feat(api_server): model_aliases routing — route requests by body.model to different provider | +70 | −2 |
- [x] ⚠️ 废弃（_align_table 被 d682be1 飞书原生表格方案替代）`c4071f9` | 2026-05-09 | `tianbao.yang` | fix(feishu): rebuild separator dashes from col_widths, not original dash count | +10 | −6 |
- [x] ⚠️ 废弃（_align_table 被 d682be1 飞书原生表格方案替代）`52b8356` | 2026-05-09 | `tianbao.yang` | fix(feishu): set wcswidth ambiguous_width=2 for CJK table alignment | +5 | −3 |
- [x] ⚠️ 废弃（OpenViking 插件已弃用，Qdrant 是当前 backing store）`bf59dfc` | 2026-05-09 | `tianbao.yang` | fix(viking-remember): isolate viking_remember into temp session to avoid overlap with Hermes auto memory | +21 | −9 |
- [x] ⚠️ 废弃（sre-archive hook 已删除 0b160cd，_extract_ai_invoked_skills + skills_loaded 不存在于 owner-v16）`865b5fc` | 2026-05-09 | `tianbao.yang` | chore(yangtb): sre-archive hook, session skill tracking, config | +470 | −1 |
- [x] ✅ 已迁移 `efd22de` | 2026-05-08 | `tianbao.yang` | feat: local customizations — skin engine, TUI tweaks, cron scheduler | +39 | −7 |
- [x] ⏭️ 跳过 `2938886` | 2026-05-08 | `tianbao.yang` | Merge upstream/main into yangtb — v0.13.0 sync (237 commits) | +0 | −0 |
- [x] ⏸️ 已决策·暂不迁移（依赖 _append_inline_code_reference 函数整体迁移） `21d4700` | 2026-05-08 | `tianbao.yang` | fix(feishu): wrap multi-item inline-code ref in code block for one-tap copy | +9 | −1 |
- [x] ✅ 已迁移·TUI部分（hooks在owner/单独处理） `085513e` | 2026-05-08 | `tianbao.yang` | fix(tui): FaceTicker verb reads from skin spinner instead of hardcoded VERBS import | +357 | −6 |
- [x] ✅ 已迁移（skin YAML → owner/skins/） `3622735` | 2026-05-08 | `tianbao.yang` | refactor: move ruolin skins to yangtb/skins/ with symlinks | +236 | −8 |
- [x] ⏭️ 跳过（yangtb/README.md 文档 + OpenViking 已废弃） `5ce1904` | 2026-05-08 | `tianbao.yang` | docs: add external assets inventory to yangtb/README.md | +57 | −10 |
- [x] ⏭️ 跳过（yangtb/README.md 不存在于 owner-v16） `088ade4` | 2026-05-08 | `tianbao.yang` | docs: remove deprecated section from yangtb/README.md | +0 | −12 |
- [x] ⚠️ 废弃（yangtb/README.md OpenViking 文档，OpenViking 已停用） `3d438f8` | 2026-05-08 | `tianbao.yang` | docs: add OpenViking deployment and pitfalls to yangtb/README.md | +159 | −0 |
- [x] ⚠️ 废弃（yangtb/README.md 初始文档，不存在于 owner-v16） `8735a40` | 2026-05-08 | `tianbao.yang` | docs: add yangtb/README.md with full customization inventory | +160 | −0 |
- [x] ⏭️ 跳过（pricing废弃 + patch.yaml中TF-IDF延后单独处理） `2416220` | 2026-05-08 | `tianbao.yang` | refactor: move config files to yangtb/config/ | +226 | −1 |
- [x] ✅ 已迁移·部分（4脚本→owner/scripts/，token_stats/daily_memory废弃，viking废弃，tfidf延后） `fcc9291` | 2026-05-08 | `tianbao.yang` | refactor: move personal scripts to yangtb/scripts/ | +1509 | −0 |
- [x] ✅ 已覆盖（由 `03b25424` spinner faces 迁移一并处理） `cc7f46a` | 2026-05-08 | `tianbao.yang` | fix(tui): pass missing spinner arg to renderIndicator | +1 | −1 |
- [⏸️ 已决策·暂不迁移（recovery context 注入为独立功能，需单独评估）] `fad4db4` | 2026-05-08 | `tianbao.yang` | feat: auto-inject recovery context after LLM API disconnect | +78 | −1 |
- [x] ✅ 部分迁移（仅 empty-response 断连文案区分，stream drop 通知上游已覆盖）`22ed810` | 2026-05-08 | `tianbao.yang` | fix: LLM API silent disconnect now notifies user in current chat | +67 | −0 |
- [x] ⏭️ 延后（TF-IDF SkillsUsageTracker + OpenViking 均不存在于 owner-v16，get_patch_yangtb_config 已被 config_cache.py 替代）`aed81f7` | 2026-05-08 | `tianbao.yang` | refactor: migrate tf-idf to patch.yaml + remove pin mechanism | +80 | −72 |
- [x] ⚠️ 废弃（_append_inline_code_reference 函数不存在于 owner-v16，bf0832b 已标废弃）`3b8031c` | 2026-05-08 | `tianbao.yang` | fix(feishu): rewording — 兼容性参考 → 手机端复制粘贴兼容 | +1 | −1 |
- [x] ⚠️ 废弃 `bf0832b` | 2026-05-08 | `tianbao.yang` | feat(feishu): append inline code spans as plain-text reference for mobile copy | +41 | −0 |
- [x] ⚠️ 废弃（被 `d682be1` 飞书原生表格方案替代） `526eea8` | 2026-05-08 | `tianbao.yang` | feat(feishu): align markdown table columns in code blocks using wcwidth | +88 | −1 |
- [x] ⚠️ 废弃（被 `d682be1` 飞书原生表格方案替代） `5031f9c` | 2026-05-08 | `tianbao.yang` | fix(feishu): prevent markdown format corruption from nested code fences and unsupported tables | +33 | −6 |
- [x] ⏭️ 跳过 `915baf1` | 2026-05-07 | `tianbao.yang` | Merge upstream/main into yangtb (503 commits behind) | +0 | −0 |
- [x] ⚠️ 废弃：OpenViking 插件已弃用，Qdrant 是当前 backing store `627f3e1` | 2026-05-07 | `tianbao.yang` | feat: add commit_all_on_new support via patch.yaml | +90 | −0 |
- [⏸️ 已决策·待后续观察] `e87a6f1` | 2026-05-05 | `tianbao.yang` | feat(tfidf): add pin list support for always-loaded skills | +12 | −0 |
- [x] ⏭️ 延后（classify_intent TF-IDF 代码不存在于 owner-v16） `c4fdf38` | 2026-05-05 | `tianbao.yang` | Fix UnboundLocalError: _classified nested inside skills_list_snapshot guard | +18 | −18 |
- [⏸️ 已决策·待后续观察] `4fac935` | 2026-05-05 | `tianbao.yang` | Phase 3c: LLM fallback line-mode + platform-level disable | +84 | −35 |
- [⏸️ 已决策·待后续观察] `e05beff` | 2026-05-05 | `tianbao.yang` | feat: enhance precompute to capture multi-message training data (Phase 3) | +52 | −27 |
- [x] ⏭️ 延后（yaml_load TF-IDF fallback 代码不存在于 owner-v16） `e0194a6` | 2026-05-05 | `tianbao.yang` | fix: add missing yaml_load import in prompt_builder (Layer 3 fallback was dead code) | +1 | −0 |
- [⏸️ 已决策·待后续观察] `8b81f60` | 2026-05-05 | `tianbao.yang` | feat: integrate LLM fallback + skills snapshot into build_skills_system_prompt (Phase 3c) | +52 | −1 |
- [⏸️ 已决策·待后续观察] `29e0d91` | 2026-05-05 | `tianbao.yang` | feat: add LLM intent classifier for Layer 3 fallback (Phase 3c) | +247 | −0 |
- [x] ⏭️ 延后（TF-IDF SkillsUsageTracker 代码不存在于 owner-v16） `cd3aa9c` | 2026-05-05 | `tianbao.yang` | fix: handle null skills in _get_top_usage_skills records | +1 | −1 |
- [⏸️ 已决策·待后续观察] `ca110e6` | 2026-05-05 | `tianbao.yang` | feat: add Layer 0 Top-N always-on skills to TF-IDF tracker (Phase 3a) | +58 | −0 |
- [⏸️ 已决策·待后续观察] `a06d719` | 2026-05-05 | `tianbao.yang` | feat: extract _is_high_info_message() as shared utility for TF-IDF pipeline | +74 | −0 |
- [⏸️ 已决策·暂不迁移] `248bebe` | 2026-05-05 | `tianbao.yang` | fix: strip 'source' and 'requested_provider' from runtime_kwargs in api_server._create_agent | +49 | −0 |
- [x] ✅ 已迁移 `9a95e21` | 2026-05-04 | `tianbao.yang` | fix(qqbot): add WebSocket heartbeat + receive_timeout to detect TCP half-open after WSL sleep/wake | +2 | −0 |
- [x] ✅ 已覆盖（由 `owner_provider_name` 实现替代，避免改动 `agent.provider`）`c1effe4` | 2026-05-04 | `tianbao.yang` | fix: separate provider_name from provider to preserve custom provider identity | +16 | −5 |
- [x] ✅ 已迁移 `97c43f6` | 2026-05-04 | `tianbao.yang` | fix(qqbot): rebuild httpx client on reconnect to fix WSL sleep/wake network reset | +28 | −0 |
- [⏸️ 已决策·暂不迁移] `b926356` | 2026-05-04 | `tianbao.yang` | fix(gateway): fallback /status model/provider display when DB values are None/custom | +12 | −2 |
- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `0b7742b` | 2026-05-04 | `tianbao.yang` | feat(pricing): dual-currency support (CNY/USD) + deepseek-v4 pricing + cache hit rate | +46 | −6 |
- [x] ⚠️ 废弃 `e8841ac` | 2026-05-03 | `tianbao.yang` | chore: update package-lock after upstream merge | +25 | −16 |
- [x] ⏭️ 跳过 `0d1302e` | 2026-05-03 | `tianbao.yang` | Merge upstream/main into yangtb (631 commits, 11 conflicts resolved) | +0 | −0 |
- [x] ✅ 已迁移 `e7d46fc` | 2026-05-03 | `tianbao.yang` | fix(hermes_mon): migrate data dir to ~/.local/share + dedup hourly aggregation | +29 | −4 |
- [x] ✅ 已迁移 `a8fc5d1` | 2026-05-03 | `tianbao.yang` | feat(skin): add tagline field for banner subtitle | +6 | −3 |
- [x] ✅ 已迁移 `889ef45` | 2026-05-03 | `tianbao.yang` | feat(skin): pipe spinner data (faces/verbs) from skin engine through to TUI FaceTicker | +39 | −11 |
- [x] ✅ 已迁移 `02278cd` | 2026-05-03 | `tianbao.yang` | feat(scripts): add hermes_mon - per-process perf monitoring with launchd | +483 | −0 |
- [x] ✅ 已迁移 `7c5bbdf` | 2026-05-02 | `tianbao.yang` | fix(qqbot): prevent silent dead-loop when WS closed after reconnect failure | +1 | −1 |
- [⏸️ 已决策·暂不迁移] `7d7e559` | 2026-05-02 | `tianbao.yang` | feat: 方案2 — 会话内 skill 创建跟踪 + 存活过滤 | +142 | −12 |
- [⏸️ 已决策·暂不迁移] `f81cca5` | 2026-05-02 | `tianbao.yang` | feat: recency exemption for TF-IDF skill filtering (72h mtime window) | +65 | −0 |
- [⏸️ 已决策·暂不迁移] `4e88521` | 2026-05-02 | `tianbao.yang` | feat: system prompt audit logging via write_sysprompt_audit_entry | +100 | −1 |
- [⏸️ 已决策·暂不迁移] `7634496` | 2026-05-02 | `tianbao.yang` | system prompt compression and skill utils refactor | +125 | −71 |
- [⏸️ 已决策·暂不迁移] `6c37b19` | 2026-05-02 | `tianbao.yang` | feat: integrate SkillsUsageTracker into run_agent.py | +35 | −2 |
- [⏸️ 已决策·暂不迁移] `304a5ad` | 2026-05-02 | `tianbao.yang` | feat: add SkillsUsageTracker for TF-IDF skill filtering | +510 | −6 |
- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `18d81fb` | 2026-05-02 | `tianbao.yang` | add pricing entries for grok-4-fast-reasoning, grok-4-fast-non-reasoning, grok-4-fast, grok-2, grok-2-vision-1212 | +50 | −0 |
- [x] ✅ 已迁移 `b14a2ee` | 2026-04-30 | `tianbao.yang` | fix(feishu): return empty P2CardActionTriggerResponse to avoid CallBackToast NameError in WS client | +3 | −9 |
- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `b65b962` | 2026-04-30 | `tianbao.yang` | feat(usage): extend pricing data with YAML-based provider pricing support | +314 | −0 |
- [⏸️ 已决策·暂不迁移] `28e513d` | 2026-04-30 | `tianbao.yang` | feat(file_tools): add headings_only parameter for markdown heading extraction | +39 | −6 |
- [⏸️ 已决策·暂不迁移] `a6b718b` | 2026-04-30 | `tianbao.yang` | fix(session_search): fast window mode around FTS5 hits for long sessions (#16671 workaround) | +149 | −2 |
- [x] ❌ DEPRECATED `0be2695` | 2026-04-30 | `tianbao.yang` | perf(agent): stabilize system prompt timestamp across compression cycles | +15 | −2 | (upstream PR #27675 merged as `4a3f13b`, date-only方案更简单无依赖)
- [x] ✅ P15 已迁移 `a484c2c` | 2026-04-29 | `tianbao.yang` | feat(tui): support ;; chained commands in quick_commands aliases | +141 | −64 |
- [x] ✅ 已迁移 `fbb98ae` | 2026-04-29 | `tianbao.yang` | feat(feishu): support channel_prompts from config.yaml | +4 | −0 |
- [x] ✅ 已迁移 `dbb99d5` | 2026-04-29 | `tianbao.yang` | feat(tui): 选中即复制 (auto copy-on-select) | +49 | −4 |
- [x] ✅ P15 已迁移 `1780ea8` | 2026-04-28 | `tianbao.yang` | refactor(gateway): canonical command routing in quick command handler | +131 | −6 |
- [x] ✅ P15 已迁移 `0cbcb3e` | 2026-04-28 | `tianbao.yang` | fix(cli): add quick_commands autocomplete to SlashCommandCompleter | +26 | −0 |
- [x] ⏭️ 跳过 `b1fff64` | 2026-04-28 | `tianbao.yang` | Merge remote-tracking branch 'upstream/main' into yangtb | +0 | −0 |
- [x] ⚠️ 废弃：/status model/provider 显示，不再需要 `c99f15f` | 2026-04-27 | `tianbao.yang` | fix(tui): resolve /status ambiguous command error | +36 | −14 |
- [x] ⏭️ 跳过 `3f510d0` | 2026-04-27 | `tianbao.yang` | Merge remote-tracking branch 'upstream/main' | +0 | −0 |
- [x] ✅ P15 已迁移 `0034173` | 2026-04-27 | `tianbao.yang` | fix(tui): resolve quick_commands alias in _mirror_slash_side_effects | +28 | −0 |
- [x] ✅ P15 已迁移 `6efc6a8` | 2026-04-27 | `tianbao.yang` | fix(cli): support ;; chain in quick_commands alias type | +25 | −4 |
- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `736da3a` | 2026-04-27 | `tianbao.yang` | feat: add xAI Grok pricing entries | +185 | −0 |
- [x] ✅ P15 已迁移 `552ad0b` | 2026-04-27 | `tianbao.yang` | feat(gateway): support chained quick_commands with ;; | +67 | −14 |
- [x] ⚠️ 废弃：/status model/provider 显示，不再需要 `cb0b2e7` | 2026-04-27 | `tianbao.yang` | fix: fetch model/provider from session_db instead of SessionEntry | +8 | −2 |
- [x] ⚠️ 废弃：/status model/provider 显示，不再需要 `67471f3` | 2026-04-27 | `tianbao.yang` | feat: add current session model and provider to /status output in gateway | +2 | −0 |
- [x] ✅ P15 已迁移 `22b90ab` | 2026-04-27 | `tianbao.yang` | fix(gateway): quick_command alias should explicitly call built-in command handlers | +10 | −2 |
- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `4a0997d` | 2026-04-26 | `tianbao.yang` | docs: update AGENTS.md development guide | +141 | −630 |

## 追加：inventory 生成器跳过的遗漏 commit（按 commit date 升序）

> 由 inventory gap 分析脚本（`/tmp/emit_appendix.py`）于 2026-06-13 输出。
> 这些 commit 在原 inventory 生成时（2026-06-12 21:02:34）未被收录。
> 全部为 yangtb 在 2026-05-28 / 2026-05-29 的 commit，疑似 generator 当日运行异常。
> 行号前缀省略（与原 inventory 的 `369|- [ ]` 格式不同）；下次重生成时统一编号。

- [⏸️ 已决策·待后续 i18n 统一处理] `07a584a` | 2026-05-28 | `yangtb` | style(i18n): 网关重启/关闭提示 emoji 从 ⚠️ 换成 ⏸️ | +2 | −2 |
- [⏸️ 已决策·待后续 i18n 统一处理] `082e0be` | 2026-05-28 | `yangtb` | feat(i18n): translate all tips to Chinese | +455 | −458 |
- [x] ⚠️ 废弃（.env 加载时机 v16 已解决；Bearer 正则改动会导致 token 泄漏回归）`0a3fa8c` | 2026-05-28 | `yangtb` | fix: gateway/run.py 对抗性 review 修复 | +15 | −5 |
- [x] ⚠️ 废弃（owner-v16 已无 sre-archive/tool-call-logger 相关文件）`191183e` | 2026-05-28 | `yangtb` | chore: remove unused hooks (sre-archive, tool-call-logger) | +0 | −790 |
- [x] ⚠️ 废弃（auditor-guard/rate_limiter/_align_table 在 v16 已不存在；backup 脚本修复已存在于 owner-v16）`1b41e23` | 2026-05-28 | `yangtb` | fix: owner 分支定制化模块对抗性 review 修复 | +88 | −10 |
- [x] ⚠️ 废弃（纯文档 owner/README.md，不迁移）`43687be` | 2026-05-28 | `yangtb` | docs(owner): register P42 — QQ Bot diff markdown display | +3 | −2 |
- [x] ⚠️ 废弃（纯文档 owner/README.md，不迁移）`4c40f92` | 2026-05-28 | `yangtb` | docs: P39 更新 — 三阶段渐进展开交互 | +1 | −1 |
- [x] ✅ 已迁移 `1da7ada8e` `7e7cb58` | 2026-05-28 | `yangtb` | feat(qqbot): diff markdown display for patch/write_file/skill_manage | +116 | −0 |
- [x] ⚠️ 废弃（纯文档 owner/README.md，不迁移）`a422f7d` | 2026-05-28 | `yangtb` | docs(owner): 更新 P39 飞书 Diff 卡片描述 — 三工具触发+四色渲染+踩坑记录 | +2 | −2 |
- [x] ✅ 已迁移 `1da7ada8e` `bb542ba` | 2026-05-28 | `yangtb` | feat: diff 卡片三阶段渐进展开 (compact → expanded → full) | +189 | −39 |
- [x] ✅ 已迁移 `1da7ada8e` `bec5b1e` | 2026-05-28 | `yangtb` | feat: feishu diff cards for write_file + skill_manage + purple header styling | +76 | −9 |
- [⏸️ 已决策·待后续 i18n 统一处理] `d452156` | 2026-05-28 | `yangtb` | i18n: gateway lifecycle emoji → skyline series (🌇🌆🌃🏙) | +8 | −8 |
- [x] ⏭️ 跳过（已被 owner-v16 P14 迁移 commit 59ebc9954 完整覆盖）`dd0b53e` | 2026-05-28 | `yangtb` | fix(tui): pass missing spinner prop to FaceTicker in StatusRule | +1 | −1 |
- [⏸️ 已决策·见下表“审批卡片相关遗漏 commit”] `de36b03` | 2026-05-28 | `yangtb` | refactor(feishu): resolve sender name synchronously before approval card response | +13 | −34 |
- [⏸️ 已决策·暂不迁移（rate limiter 不存在于 owner-v16，需整体评估）] `ed7d88e` | 2026-05-28 | `yangtb` | chore: add xiaomi rate limit config to patch.yaml | +3 | −0 |
- [x] ✅ 已迁移 `9fbba42b6` `3198a71` | 2026-05-29 | `yangtb` | fix(agent): 向 system_prompt 注入 current_user 字段，消除 API 响应中的占位符 | +129 | −24 |
- [x] ⚠️ 废弃（纯文档md，不迁移）`5a886a4` | 2026-05-29 | `yangtb` | docs: 更新 patch 总列表，新增 P53/P54/P55（37组/45项） | +6 | −3 |

## 追加 2：审批卡片相关遗漏 commit

> 经人工核查，`owner` 分支上飞书/QQ Bot 审批卡片演进链还有多条 owner 定制 commit 未被 inventory 生成器收录。
> 这些 commit 与 `原有改动清单.md` 中的 P9 / P31 / P45 / P55 对应，建议按功能块统一迁移。

### Feishu 审批卡片（P9 + P31 + P45）

- [x] ⚠️ 废弃（临时绕过，已被 `c9cc868a9` 覆盖）`b14a2ee1a` | 2026-04-30 | `tianbao.yang` | fix(feishu): return empty P2CardActionTriggerResponse to avoid CallBackToast NameError in WS client | +3 | −9 |
- [x] ⚠️ 废弃（临时 revert，已被最终方案覆盖）`598197f91` | 2026-06-12 | `杨天宝` | fix(feishu): comment out CallBackCard response to avoid NameError on CallBackToast | +16 | −9 |
- [⏸️ 已决策·待后续 i18n 统一处理] `bb19362eb` | 2026-05-20 | `tianbao.yang` | feat(i18n): approvals 文案中文化 — 硬编码英文全部接入 t() 翻译 | +111 | −59 |
- [x] ✅ 已迁移 `e64a1aeac` `489aafd05` | 2026-05-22 | `yangtb` | P31: 飞书审批卡片"永久允许"按钮可配置隐藏 | +61 | −28 |
- [x] ✅ 已迁移 `e64a1aeac` `c9cc868a9` | 2026-05-27 | `yangtb` | fix(feishu): return CallBackCard in approval card action to update card inline | +13 | −3 |
- [x] ✅ 已迁移 `e64a1aeac` `1c887efaa` | 2026-05-27 | `yangtb` | feat(feishu): approvals 卡片回调异步更新用户名，显示命令内容 | +67 | −17 |
- [x] ✅ 已迁移 `e64a1aeac` `de36b0341` | 2026-05-28 | `yangtb` | refactor(feishu): resolve sender name synchronously before approval card response | +13 | −34 |
- [x] ✅ 已迁移 `e64a1aeac` `31417156d` | 2026-05-30 | `yangtb` | fix(feishu): resolve sender name for approval card using open_id instead of short user_id | +5 | −2 |
- [x] ✅ 已薄化提取 (e64a1aeac 之后重构) | 2026-06 | `yangtb` | refactor(owner): 审批卡片 + open_id->中文名 cache 完整提取到 owner/feishu/ (sender_name_cache.py + approval.py)，feishu.py 只剩薄胶水 + 委托 + 统一短 [owner] 标记（对齐 diff_card 模式）；chat_id 缓存部分按补充推后实现。官方 diff 显著缩小，便于 upstream sync。 | (extraction) | (extraction)

### Memory 提案审批（P55）

- [x] ✅ 已迁移（owner/memory/ + owner/feishu/memory_proposal.py + 运行时 toolset patch；unified_diff_patch display 部分已在前一 commit 单独迁移）`637891346` | 2026-05-31 | `yangtb` | feat: memory proposal approval system + unified_diff_patch display support | +857 | −15 |
- [x] ✅ 已迁移（WR-08/09/10 fix 已纳入 09a91bb94 的 owner/memory/ 与 owner/feishu/memory_proposal.py 实现）`947f1412e` | 2026-05-31 | `yangtb` | fix(memory_propose): WR-08/09/10 — fix Feishu card button not responding and store injection | +105 | −56 |

## 复现方式

```bash
python3 owner/docs/generate-our-commits-inventory.py
python3 owner/docs/generate-our-commits-inventory.py --ref refs/heads/owner --output /tmp/our-commits.md
```

## 作者身份说明

- **`yangtb`** — 当前 git config user.name（commit 主流用名）
- **`tianbao.yang`** — 早期拼音形式（同一开发者，邮箱 `<空>`）
- 两个 author 视为同一人，**杨天宝**
- 邮箱均为占位 `123`，**建议未来改成真实邮箱后再统计**

## 统计口径说明

- **commit 数**：`git rev-list --count <ref> --author=<name>`
- **行数**：`git log <ref> --author=<name> --numstat` 累加每个文件的 `+` / `-` 行
- **二进制文件**：numstat 输出 `-\t-`，跳过不计
- **merge commit**：默认包含

