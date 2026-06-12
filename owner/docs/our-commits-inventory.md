1|# Our Commits Inventory
2|
3|> 自动生成于 **2026-06-12 21:02:34 **，源分支 `refs/heads/owner`（HEAD: `5b14bbf87`）
4|
5|> 生成器：`generate-our-commits-inventory.py`（一次性脚本）
6|
7|## 总览
8|
9|| 指标 | 值 |
10||---|---:|
11|| 源分支 commit 总数 | 10476 |
12|| **我们 commit 总数（yangtb + tianbao.yang）** | **522** |
13|| 我们累计新增行 | +83511 |
14|| 我们累计删除行 | −33168 |
15|| **我们净增行** | **+50343** |
16|| 占总 commit 比例 | 4.98% |
17|
18|## 按 author 拆分
19|
20|| author | commit 数 | 新增 | 删除 | 净增 |
21||---|---:|---:|---:|---:|
22|| `yangtb` | 360 | +59606 | −27737 | **+31869** |
23|| `tianbao.yang` | 162 | +23905 | −5431 | **+18474** |
24|
25|> 注：早期 commit 用拼音 `tianbao.yang`，后期切到 `yangtb`，邮箱均为占位 `123`。
26|> 两个 author 视为同一开发者（**杨天宝**）。
27|
28|## 完整 commit 列表（按时间倒序）
29|
30|- [ ] `5b14bbf` | 2026-06-12 | `yangtb` | chore: add SQL audit script for reasoning_content coverage | +58 | −0 |
31|- [ ] `871a364` | 2026-06-12 | `yangtb` | test: regression tests for xfyun/damodel reasoning_content echo | +210 | −0 |
32|- [ ] `854d2c3` | 2026-06-12 | `yangtb` | feat: add xfyun/damodel thinking-mode reasoning_content detector | +30 | −0 |
33|- [ ] `6ae8c57` | 2026-06-12 | `yangtb` | sync: align owner/SOUL.md with personalized SOUL.md (minus persona) | +33 | −7 |
34|- [ ] `19773fe` | 2026-06-12 | `yangtb` | fix(agent): add _needs_glm_tool_reasoning for damodel/bigmodel endpoints | +19 | −0 |
35|- [ ] `97a88a1` | 2026-06-12 | `yangtb` | fix(owner): use official thinking params for damodel glm-5.1/glm-5 | +13 | −1 |
36|- [ ] `3e448f9` | 2026-06-12 | `yangtb` | feat(owner): enable thinking for xfyun/damodel models (xopglm51, xopglm5, xopkimik26) | +12 | −0 |
37|- [ ] `2bb3f24` | 2026-06-12 | `yangtb` | docs(owner): delete §十 qdrant cleanup log + rewrite §四 from OpenViking to Qdrant + reorder sections | +61 | −243 |
38|- [ ] `5ee4631` | 2026-06-12 | `yangtb` | fix(owner): correct 10.1 'viking.md (跳板机)' mislabel → yaxin 项目访问配置 | +2 | −2 |
39|- [ ] `de00f9c` | 2026-06-12 | `yangtb` | docs(owner): log qdrant cleanup (10.1 删 2 条 OpenViking 历史记忆) | +54 | −0 |
40|- [ ] `8512faf` | 2026-06-12 | `yangtb` | docs(owner): mark qdrant sync status as done (2 points written, hook-faithful verified) | +21 | −26 |
41|- [ ] `0484b40` | 2026-06-12 | `yangtb` | docs(owner): append qdrant sync status (deferred, viking container down) | +37 | −0 |
42|- [ ] `4b3939b` | 2026-06-12 | `yangtb` | docs(owner): patch inventory 73→75, add P74 (P0 hard-cap) + P75 (per-turn attribution) | +14 | −3 |
43|- [ ] `1f82244` | 2026-06-12 | `yangtb` | docs(agent): document async_call_llm P0 hang and hard-cap fix | +166 | −0 |
44|- [ ] `c7fd830` | 2026-06-12 | `yangtb` | fix(agent): cap async_call_llm with asyncio.wait_for hard timeout | +15 | −1 |
45|- [ ] `1d52226` | 2026-06-12 | `yangtb` | test(feishu): add bot_menu routing tests — routed user forwarded, local user handled locally | +76 | −0 |
46|- [ ] `1a4f194` | 2026-06-12 | `yangtb` | feat(feishu): forward bot_menu synthetic commands to routed profile containers | +21 | −0 |
47|- [ ] `dc44c0c` | 2026-06-12 | `yangtb` | docs(feishu-v6): update implementation status table — add A4/B2/B3, collapse duplicate section 7 | +4 | −6 |
48|- [ ] `05d8f28` | 2026-06-12 | `yangtb` | test(feishu): add B3 card-action profile routing tests (inject, resolve-by-name, forward, guard) | +257 | −1 |
49|- [ ] `e818002` | 2026-06-12 | `yangtb` | feat(api_server): add POST /v1/feishu/card-actions endpoint for B3 profile routing | +54 | −0 |
50|- [ ] `aab7293` | 2026-06-12 | `yangtb` | feat(feishu): B3 card-action profile routing — inject hermes_profile into cards and forward to containers | +113 | −10 |
51|- [ ] `3c4f26b` | 2026-06-12 | `yangtb` | feat(config): add get_hermes_profile_name() for container self-identification | +8 | −0 |
52|- [ ] `6d78558` | 2026-06-12 | `yangtb` | docs(session-storage): document model/provider per-turn columns in messages schema | +6 | −0 |
53|- [ ] `ccaa607` | 2026-06-12 | `yangtb` | test(db): add tests for model/provider message attribution and backfill | +57 | −0 |
54|- [ ] `5165578` | 2026-06-12 | `yangtb` | test(feishu): fix connect tests (mock _start_health_server), fix reaction test (pre-populate sent registry) | +10 | −1 |
55|- [ ] `60e75f3` | 2026-06-12 | `yangtb` | feat(agent): pass model/provider to append_message for per-turn attribution | +2 | −0 |
56|- [ ] `c571ea8` | 2026-06-12 | `yangtb` | feat(agent): capture model/provider in build_assistant_message for per-turn attribution | +6 | −0 |
57|- [ ] `ef65e92` | 2026-06-12 | `yangtb` | feat(db): add model/provider columns to messages for per-turn attribution | +42 | −6 |
58|- [ ] `b35729e` | 2026-06-12 | `yangtb` | feat(config): reduce patch.yaml cache TTL 5min→1min, add invalidate_patch_owner_config_cache() | +8 | −2 |
59|- [ ] `4d258c0` | 2026-06-12 | `yangtb` | feat(api_server): warn once when API_SERVER_KEY is not set | +9 | −0 |
60|- [ ] `3e72fef` | 2026-06-12 | `yangtb` | feat(feishu): v6 external-container multi-profile routing | +172 | −103 |
61|- [ ] `2b2e02c` | 2026-06-12 | `yangtb` | test(feishu): add profile routing tests (_resolve_profile_route, _forward_to_profile_container, registry) | +496 | −0 |
62|- [ ] `d14cc49` | 2026-06-12 | `yangtb` | docs(feishu): add v6 single-bot multi-profile design doc (external container architecture) | +506 | −0 |
63|- [ ] `4b962fa` | 2026-06-12 | `yangtb` | docs(feishu): rename v1-v5 multi-profile docs to -已弃用 (v6 cleanup) | +0 | −0 |
64|- [ ] `e922b2a` | 2026-06-12 | `yangtb` | chore(test): remove test_feishu_profile_router.py (v6 cleanup) | +0 | −196 |
65|- [ ] `dfae252` | 2026-06-12 | `yangtb` | chore(feishu): remove feishu_profile_router.py (v6 cleanup) | +0 | −403 |
66|- [ ] `71b0869` | 2026-06-11 | `yangtb` | test(providers): update DeepSeek thinking test for MiniMax carve-out | +9 | −4 |
67|- [ ] `a311083` | 2026-06-11 | `yangtb` | feat(providers): MiniMax Anthropic endpoint thinking-block support | +32 | −4 |
68|- [ ] `b263fd5` | 2026-06-11 | `yangtb` | config: reduce openrouter rate limit to 20 req/min | +1 | −1 |
69|- [ ] `25561ad` | 2026-06-11 | `yangtb` | feat(providers): credential validation + model list overrides in /providers | +97 | −9 |
70|- [ ] `fc9c899` | 2026-06-10 | `yangtb` | feat(qdrant-recall): patch.yaml 配置化 + bot_menu 命令跳过 | +72 | −1 |
71|- [ ] `1fe0bf4` | 2026-06-10 | `yangtb` | feat(recall-card): compact标题增加 content 首行 # 提取 fallback | +8 | −5 |
72|- [ ] `28d65f8` | 2026-06-10 | `yangtb` | fix(feishu-card): diff/recall card cache 添加 3 小时 TTL | +35 | −10 |
73|- [ ] `b0e4483` | 2026-06-10 | `yangtb` | feat(qdrant-recall): 飞书卡片展示 + compact标题显示name/abstract | +361 | −3 |
74|- [ ] `eb514ee` | 2026-06-10 | `yangtb` | feat: skill script auto-approval (skill_script_allowlist) | +637 | −0 |
75|- [ ] `8c0b8dd` | 2026-06-10 | `yangtb` | feat(approval): auto-resolve pending approvals when YOLO enabled | +56 | −15 |
76|- [ ] `6f86bcd` | 2026-06-10 | `yangtb` | feat(gateway): strip hook-injected extra_context from history and archiving | +28 | −5 |
77|- [ ] `fbfa354` | 2026-06-10 | `yangtb` | feat(feishu): use 🟥 for memory proposal deny button | +4 | −4 |
78|- [ ] `84c7489` | 2026-06-10 | `yangtb` | chore(owner): restore local adjustments for qdrant hook (named vector search), session-archiver (DeepSeek/DashScope), pricing.yaml | +62 | −100 |
79|- [ ] `c24c8ee` | 2026-06-09 | `yangtb` | docs(owner): patch inventory 69→73, add P70-P71 (clarify multi-profile, display_hook_message_receive) | +14 | −5 |
80|- [x] ✅ 已迁移 `825145f` | 2026-06-09 | `yangtb` | docs(owner): patch inventory 65→69, add P66-P69 (intent-guard, credential_pool, qdrant-recall, session-archiver) | +18 | −2 |
81|- [x] ✅ 已迁移 `c974c92` | 2026-06-09 | `yangtb` | docs(owner): update patch inventory to 65, add P65 yolo tri-state entry | +4 | −3 |
82|- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `9b4dda1` | 2026-06-09 | `yangtb` | docs(AGENTS): update project structure and development guide | +187 | −81 |
83|- [ ] `ca0836e` | 2026-06-09 | `yangtb` | chore(config): add yolo_on/yolo_off ack text + sync patch.yaml | +17 | −1 |
84|- [ ] `e7d351c` | 2026-06-09 | `yangtb` | fix(feishu): bot_menu synthetic event message_id → None | +1 | −1 |
85|- [ ] `1be0241` | 2026-06-09 | `yangtb` | feat(gateway): /yolo on\ | off\ | status syntax sugar |
86|- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `8b5f0f7` | 2026-06-09 | `yangtb` | chore(config): update pricing.yaml exchange rate | +1 | −1 |
87|- [ ] `ef0d7bf` | 2026-06-09 | `yangtb` | fix(credential_pool): reject classic PATs in copilot env seeding | +11 | −0 |
88|- [ ] `88a8156` | 2026-06-08 | `yangtb` | docs(owner): add 6 patches to README (P58-P63 feishu + P62 tools) | +9 | −3 |
89|- [ ] `9f6fecd` | 2026-06-08 | `yangtb` | docs(owner): dual-agent cross-review architecture design draft | +354 | −0 |
90|- [ ] `8eadc82` | 2026-06-08 | `yangtb` | fix(feishu): bot_menu_dedup 对齐新增 model key | +4 | −0 |
91|- [ ] `b0a8f3c` | 2026-06-08 | `yangtb` | feat(feishu): bot_menu 增加 mimo / minimax 模型快捷键 | +2 | −0 |
92|- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `ab5cda7` | 2026-06-08 | `yangtb` | chore(owner): pricing.yaml daily exchange rate update | +1 | −1 |
93|- [ ] `86f575e` | 2026-06-08 | `yangtb` | docs(owner): archive rolled-back clarify-timeout-abort design | +108 | −0 |
94|- [ ] `e49f512` | 2026-06-08 | `yangtb` | feat(feishu): expire_clarify on timeout — grey card + interrupt turn | +145 | −3 |
95|- [ ] `5022ef4` | 2026-06-08 | `yangtb` | feat(tools): auto_fix_start option to unified_diff_patch | +124 | −21 |
96|- [ ] `b845c7a` | 2026-06-08 | `yangtb` | fix(code_execution): 🐍 → 🛠️ execute_code tool emoji | +1 | −1 |
97|- [ ] `16ae8a0` | 2026-06-08 | `yangtb` | chore(skills): remove custom skills from source tree | +0 | −1054 |
98|- [ ] `d490793` | 2026-06-08 | `yangtb` | scripts(backup-hermes-config): graceful fallback on patch.yaml parse error | +18 | −10 |
99|- [ ] `c09616f` | 2026-06-08 | `yangtb` | hooks(qdrant-memory-recall): filter disabled=true points | +5 | −1 |
100|- [ ] `5af60e9` | 2026-06-08 | `yangtb` | skills: add claude-code reference docs | +578 | −0 |
101|- [ ] `8333e30` | 2026-06-08 | `yangtb` | scripts: add skills_sync_preview utility | +218 | −0 |
102|- [ ] `6976b60` | 2026-06-08 | `yangtb` | tools: add auto_fix_header option to unified_diff_patch | +48 | −12 |
103|- [ ] `2f97677` | 2026-06-08 | `yangtb` | hooks: skip synthetic gateway messages in qdrant recall | +20 | −0 |
104|- [ ] `b47978f` | 2026-06-08 | `yangtb` | config: update default exchange rate to 6.7928 | +1 | −1 |
105|- [x] ✅ 已迁移 `2f1be0a` | 2026-06-07 | `yangtb` | minimax-cn: 收敛 catalog 到 M3/M2.7/M2.7-highspeed + aux 默认走 highspeed | +12 | −13 |
106|- [ ] `91460d8` | 2026-06-07 | `yangtb` | feat(feishu): model picker — alphabetical providers + back button | +22 | −0 |
107|- [ ] `adc1f0e` | 2026-06-07 | `yangtb` | fix(qdrant-memory-recall): filter low_quality hits to reduce hallucination risk | +8 | −2 |
108|- [ ] `0a2ea99` | 2026-06-06 | `yangtb` | docs(qdrant-memory-recall): clarify per-turn extra_context scope (CR-01) | +21 | −2 |
109|- [ ] `4626a1a` | 2026-06-06 | `yangtb` | fix(feishu-clarify): prepend full-text markdown options block before button row | +175 | −21 |
110|- [ ] `111f767` | 2026-06-06 | `yangtb` | fix(tool_guardrails): name the counter and threshold in warn messages | +78 | −5 |
111|- [ ] `6f64470` | 2026-06-06 | `yangtb` | docs(unified_diff_patch): clarify schema descriptions (5 fixes) | +79 | −61 |
112|- [ ] `a3b95e7` | 2026-06-06 | `yangtb` | fix(unified_diff_patch): 4 quality fixes (strict priority, line numbers, CRLF, dry_run) | +352 | −8 |
113|- [ ] `c536033` | 2026-06-06 | `yangtb` | feat(session-archiver): add ts field to event payload for Qdrant time-ordering | +1 | −0 |
114|- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `750ceb9` | 2026-06-06 | `yangtb` | chore(owner): pricing.yaml daily exchange rate update | +1 | −1 |
115|- [ ] `2a6f213` | 2026-06-06 | `yangtb` | feat(owner): qdrant-memory-recall hook 部署 | +346 | −0 |
116|- [ ] `69af045` | 2026-06-06 | `yangtb` | feat(owner): display_hook_message_receive config | +142 | −1 |
117|- [ ] `e5e0e4e` | 2026-06-05 | `yangtb` | chore(owner): list_models quick-action + pre_tool_call hooks stub | +4 | −0 |
118|- [ ] `137fd1c` | 2026-06-05 | `yangtb` | feat(commands): /providers command (feishu card + text fallback) | +58 | −0 |
119|- [ ] `502decf` | 2026-06-05 | `yangtb` | feat(feishu): interactive model picker card (schema 2.0) | +176 | −0 |
120|- [ ] `2be890a` | 2026-06-05 | `yangtb` | fix(intent-guard): fix 8 correctness issues found in code review | +98 | −70 |
121|- [ ] `a23b5fd` | 2026-06-05 | `yangtb` | feat(intent-guard): add circuit breaker + retry + 30s timeout + notify reserve | +294 | −18 |
122|- [ ] `deb958e` | 2026-06-05 | `yangtb` | chore(config): update CNY exchange rate | +1 | −1 |
123|- [ ] `460c4c6` | 2026-06-05 | `yangtb` | docs(owner): document file tool hang behavior and stop recovery | +370 | −0 |
124|- [ ] `29e6ba6` | 2026-06-05 | `yangtb` | docs(owner): add feishu single-bot multi-profile design iterations | +1040 | −0 |
125|- [ ] `dd936e1` | 2026-06-05 | `yangtb` | docs(owner): add README notes for gateway daemon exit timeout | +26 | −0 |
126|- [ ] `4a9a79c` | 2026-06-05 | `yangtb` | docs(intent-guard): add architecture doc and adversarial review report | +779 | −0 |
127|- [ ] `2172689` | 2026-06-05 | `yangtb` | feat(intent-guard): integrate interrupt protocol into Hermes core | +193 | −44 |
128|- [ ] `97ab075` | 2026-06-05 | `yangtb` | feat(intent-guard): add pre_tool_call hook with hard rules + LLM audit | +1006 | −5 |
129|- [ ] `c6b87d9` | 2026-06-04 | `yangtb` | feat(clarify): 飞书 clarify 卡片 + 多 profile 路由 + 跨平台 choice display | +1339 | −67 |
130|- [ ] `675f180` | 2026-06-04 | `yangtb` | fix(unified_diff_patch): add strict mode, clarify path resolution and guardrail errors | +255 | −17 |
131|- [ ] `77862a9` | 2026-06-04 | `yangtb` | feat(qdrant-insert): add skill source files (from feishu ff47ea5f3) | +476 | −0 |
132|- [ ] `df5471a` | 2026-06-04 | `yangtb` | chore(owner): cleanup hooks and scripts | +450 | −273 |
133|- [ ] `0b160cd` | 2026-06-04 | `yangtb` | chore(scripts): remove sre-archive.py (deployment removed 2026-05-28; orphan source cleanup) | +0 | −490 |
134|- [ ] `d93318d` | 2026-06-04 | `yangtb` | fix(reasoning): downgrade xhigh→high for Kimi; add bot_menu contract note; extend BM25 hash to 64-bit | +12 | −1 |
135|- [ ] `3468b67` | 2026-06-04 | `yangtb` | refactor(cost-estimate): add CLI args, dynamic exchange rate, improve code quality | +114 | −63 |
136|- [ ] `c41dffd` | 2026-06-04 | `yangtb` | fix(session-archiver): add log retention cleanup, fix tool_calls parse, fix Qdrant vectors | +24 | −27 |
137|- [ ] `2d38c8d` | 2026-06-04 | `yangtb` | perf(feishu): debounce chat_id cache writes to avoid sync I/O on hot path | +37 | −3 |
138|- [ ] `75db996` | 2026-06-04 | `yangtb` | feat(model): add MiniMax-M3 to provider catalog and opencode model lists | +4 | −0 |
139|- [ ] `9a8adcb` | 2026-06-04 | `yangtb` | feat(config): update bot_menu emoji ack for feishu | +11 | −11 |
140|- [ ] `0b50165` | 2026-06-04 | `yangtb` | feat(patch): add sync_sre_king bot menu command | +4 | −1 |
141|- [ ] `f747157` | 2026-06-04 | `yangtb` | feat(feishu): add sync_git_hermes bot menu entry with ack config | +3 | −0 |
142|- [ ] `aad84a1` | 2026-06-04 | `yangtb` | fix(feishu): persist p2p_chat_id to disk cache | +39 | −1 |
143|- [ ] `c0d5e2a` | 2026-06-04 | `yangtb` | feishu: aiohttp timeout 10→60s; pricing: 汇率更新; patch: inspect_gpu_cluster ack; 新增 hy3 成本估算脚本 | +176 | −2 |
144|- [ ] `b933cd6` | 2026-06-03 | `yangtb` | feat: add session-archiver plugin | +727 | −0 |
145|- [ ] `248bdb4` | 2026-06-03 | `yangtb` | docs: enhance unified_diff_patch schema with hunk counting rule and absolute path trick | +18 | −1 |
146|- [ ] `ab8fd79` | 2026-06-03 | `yangtb` | feat(feishu): bot menu dedup + configurable ack + reasoning xhigh | +384 | −1 |
147|- [ ] `fd20634` | 2026-06-03 | `yangtb` | fix(feishu): allow non-slash commands in bot_menu mapping | +1 | −1 |
148|- [ ] `a612263` | 2026-06-03 | `yangtb` | feat(feishu): add built-in bot_menu fallback + inspect_gpu_cluster menu item | +31 | −4 |
149|- [ ] `feac9c1` | 2026-06-03 | `yangtb` | fix(kimi-coding): correct base_url and api_mode for Kimi Coding Plan | +5 | −2 |
150|- [ ] `cbf4a70` | 2026-06-03 | `yangtb` | feat(owner): add generic SOUL.md template | +80 | −0 |
151|- [ ] `f31b40d` | 2026-06-03 | `yangtb` | feat(patch): add reasoning/model menu shortcuts, clean naming | +9 | −3 |
152|- [ ] `38304b8` | 2026-06-03 | `yangtb` | docs(owner): update README with P57 feishu bot menu + user cache | +3 | −2 |
153|- [ ] `d1ab5c8` | 2026-06-03 | `yangtb` | feat(feishu): bot menu events + structured user cache | +203 | −25 |
154|- [ ] `f1ba3bb` | 2026-06-03 | `yangtb` | fix: feishu diff card logging + memory proposal cleanup | +11 | −1 |
155|- [ ] `171d976` | 2026-06-03 | `yangtb` | docs: add feishu bot menu + user cache and rate limiter concurrency analysis | +485 | −0 |
156|- [ ] `53ff4d2` | 2026-06-03 | `yangtb` | refactor: simplify DEFAULT_AGENT_IDENTITY to concise Chinese, remove aggressive directives | +4 | −14 |
157|- [ ] `47b44a5` | 2026-06-02 | `yangtb` | docs: expand Phase 3 section with container design decisions | +83 | −9 |
158|- [ ] `f3de5be` | 2026-06-02 | `yangtb` | docs: add hermes config customizations classification + shareable baseline | +936 | −0 |
159|- [ ] `4242bea` | 2026-06-02 | `yangtb` | feat(feishu): add profile routing layer for multi-user dispatch (Phase 2) | +103 | −3 |
160|- [ ] `432fb0b` | 2026-06-02 | `yangtb` | docs: update feishu-multi-profile-routing spec with Phase 2 implementation details | +102 | −14 |
161|- [ ] `05faa2c` | 2026-06-02 | `yangtb` | feat(api_server): support X-Hermes-Reply-Via: feishu for profile container RPC | +109 | −0 |
162|- [ ] `b088690` | 2026-06-02 | `yangtb` | docs: add feishu multi-profile routing design spec | +207 | −0 |
163|- [ ] `deacdc3` | 2026-06-02 | `yangtb` | chore: remove yangtb/scripts/ directory | +0 | −274 |
164|- [ ] `947f141` | 2026-05-31 | `yangtb` | fix(memory_propose): WR-08/09/10 — fix Feishu card button not responding and store injection | +105 | −56 |
165|- [ ] `0ef6b91` | 2026-05-31 | `yangtb` | fix(feishu): clarify card freeze buttons + store choices in _clarify_state | +120 | −1 |
166|- [ ] `4130359` | 2026-05-31 | `yangtb` | fix(tool_executor): remove duplicate pre-tool-call block logic from merge | +1 | −15 |
167|- [ ] `cb208c5` | 2026-05-31 | `yangtb` | docs(owner): fix 3 README discrepancies found during merge audit | +3 | −3 |
168|- [x] ⏭️ 跳过 `a7ede52` | 2026-05-31 | `yangtb` | Merge main (synced with upstream) into owner | +0 | −0 |
169|- [ ] `6378913` | 2026-05-31 | `yangtb` | feat: memory proposal approval system + unified_diff_patch display support | +857 | −15 |
170|- [ ] `091bb10` | 2026-05-30 | `yangtb` | fix: unified_diff_patch路径解析 + daily-report sessions格式 + 禁用旧patch工具 | +7 | −3 |
171|- [ ] `3a9103b` | 2026-05-30 | `yangtb` | P54: add unified_diff_patch_tool record to owner/README | +9 | −1 |
172|- [ ] `d399df6` | 2026-05-30 | `yangtb` | feat(tools): add unified_diff_patch tool with exact line-number replacement | +551 | −5 |
173|- [ ] `2458489` | 2026-05-30 | `yangtb` | chore(owner): P12 orphan removal + Phase1 docs + minor config updates | +39 | −116 |
174|- [ ] `3141715` | 2026-05-30 | `yangtb` | fix(feishu): resolve sender name for approval card using open_id instead of short user_id | +5 | −2 |
175|- [ ] `90c9f20` | 2026-05-30 | `yangtb` | feat(patch): feishu: raise auto_card_threshold to 41, add interim/tool_progress settings | +7 | −1 |
176|- [ ] `08253ae` | 2026-05-29 | `yangtb` | chore: remove obsolete yangtb/scripts/send_daily_report.py (was accidentally committed by daily-report cron, caused persistent merge conflicts) | +0 | −76 |
177|- [x] ✅ 已迁移 `2c383a2` | 2026-05-29 | `yangtb` | merge: resolve conflict with gitlab/yangtb — keep HEAD P35+P36, adopt yangtb's send_daily_report (5-26 version) | +0 | −0 |
178|- [ ] `480bf03` | 2026-05-29 | `yangtb` | fix(qqbot): add 'dm' chat_type to approval authorization | +2 | −3291 |
179|- [ 

... [OUTPUT TRUNCATED - 2046 chars omitted out of 52046 total] ...

[x] ⏭️ 跳过 `a77231c` | 2026-05-28 | `yangtb` | Merge upstream/main into owner (v0.14.0+) | +0 | −0 |
198|- [ ] `c5b6992` | 2026-05-28 | `yangtb` | chore: remove viking-hint hook (empty stub, never implemented) | +0 | −49 |
199|- [ ] `0c23b27` | 2026-05-27 | `yangtb` | i18n(zh): add all 85 missing tirith rule translations, remove 2 stale entries | +193 | −9 |
200|- [ ] `bf295cd` | 2026-05-27 | `yangtb` | refactor(gateway): 外部 restart 走 launchctl kickstart -k 原子化生命周期 | +24 | −13 |
201|- [ ] `67373f7` | 2026-05-27 | `yangtb` | docs(owner): 新增 P39 飞书 Diff 卡片 + P40 step_callback 去 hooks 依赖 | +4 | −2 |
202|- [ ] `06c911a` | 2026-05-27 | `yangtb` | feat(feishu): patch/write_file 完成后发送 diff 卡片（红绿背景 + 查看完整 diff 按钮） | +207 | −1 |
203|- [ ] `016bb35` | 2026-05-27 | `yangtb` | chore(config): 移除 nous rate limit 配置，damodel max_requests 提频 30→60 | +1 | −4 |
204|- [ ] `1c887ef` | 2026-05-27 | `yangtb` | feat(feishu): approvals 卡片回调异步更新用户名，显示命令内容 | +67 | −17 |
205|- [ ] `601e79e` | 2026-05-27 | `yangtb` | chore(owner): add xfyun rate limit config to patch.yaml | +3 | −0 |
206|- [x] ✅ 已迁移 `25f1996` | 2026-05-27 | `yangtb` | docs(owner): 同步 patch 清单 P35-P38 + P9 CallBackCard 升级 | +12 | −8 |
207|- [x] ⚠️ 废弃：上游已修复，.env 加载时机已无问题 `2b801e5` | 2026-05-27 | `yangtb` | fix(gateway): eagerly load .env before any import that triggers load_config() | +15 | −0 |
208|- [ ] `c9cc868` | 2026-05-27 | `yangtb` | fix(feishu): return CallBackCard in approval card action to update card inline | +13 | −3 |
209|- [ ] `b7a199b` | 2026-05-26 | `yangtb` | feat: Viking health report API rewrite + fix TUI Cmd+C on macOS | +276 | −3 |
210|- [x] ✅ 已迁移 `8d359ee` | 2026-05-26 | `yangtb` | docs(yangtb): register P35 — extract_local_files double-backtick code span fix | +4 | −3 |
211|- [x] ✅ 已迁移 `ff19a78` | 2026-05-26 | `yangtb` | fix(gateway): add double-backtick code span detection in extract_local_files | +155 | −9 |
212|- [x] ✅ 已迁移 `ca3c24f` | 2026-05-26 | `yangtb` | fix(gateway): add double-backtick code span detection in extract_local_files | +146 | −5 |
213|- [ ] `d31f26b` | 2026-05-26 | `yangtb` | feat(i18n): translate all approval descriptions to Chinese via i18n | +333 | −16 |
214|- [ ] `9ef510c` | 2026-05-26 | `yangtb` | chore(owner): pricing rate update + backup-configs mkdir fallback | +8 | −5 |
215|- [ ] `8051cd9` | 2026-05-26 | `yangtb` | docs(owner): P33 approvals patch.yaml 白名单 — patch 清单更新 | +2 | −1 |
216|- [ ] `5ac061b` | 2026-05-26 | `yangtb` | feat(approval): patch.yaml 白名单支持 — load_permanent_allowlist() 合并 owner.approvals.command_allowlist | +20 | −2 |
217|- [ ] `49f6a6d` | 2026-05-25 | `yangtb` | fix: viking-auto-commit 直接用 expanduser(~) 推导家目录 | +1 | −3 |
218|- [ ] `f796063` | 2026-05-25 | `yangtb` | chore(owner): batch update scripts, hooks, config + gitignore .claude/.local | +186 | −73 |
219|- [ ] `38aa3ce` | 2026-05-23 | `yangtb` | chore: purge yangtb references — comments, paths, viking user → owner/default | +38 | −38 |
220|- [ ] `10d296e` | 2026-05-23 | `yangtb` | feat(memory): owner.memory.prefetch_enabled — disable passive Viking recall | +24 | −5 |
221|- [ ] `5311fe2` | 2026-05-23 | `yangtb` | feat: migrate personal profile from yangtb to owner | +49 | −12080 |
222|- [ ] `4e7faf4` | 2026-05-22 | `yangtb` | fix(xai-oauth): dual-field argument extraction for codex_responses normalize | +36 | −7 |
223|- [ ] `611f972` | 2026-05-22 | `yangtb` | config: add damodel provider rate limiting to owner/yangtb profiles | +6 | −0 |
224|- [ ] `288342c` | 2026-05-22 | `yangtb` | yangtb-patch: gateway session — add API disconnect recovery context + skills_loaded tracking | +26 | −1 |
225|- [x] ⏭️ 跳过 `c03e8da` | 2026-05-22 | `yangtb` | Merge upstream/main into owner | +0 | −0 |
226|- [x] ⚠️ 废弃：上游已重构，_limiter 不存在 `30ab336` | 2026-05-22 | `yangtb` | fix(credential_pool): False sentinel bypasses _limiter None check in select() | +3 | −1 |
227|- [ ] `1588a1e` | 2026-05-22 | `yangtb` | tools+prompt: harden patch schema descriptions; add Grok-4.3 tool-calling guidance | +41 | −2 |
228|- [ ] `8968786` | 2026-05-22 | `yangtb` | display: per-chat override support with patch.yaml integration | +67 | −13 |
229|- [ ] `fb19877` | 2026-05-22 | `yangtb` | feat: migrate from yangtb to owner profile | +12109 | −61 |
230|- [ ] `478b66a` | 2026-05-22 | `yangtb` | feat(cron): replace todo-scan.py with robust todo-scan.sh (macFUSE timeout protection) | +58 | −0 |
231|- [ ] `489aafd` | 2026-05-22 | `yangtb` | P31: 飞书审批卡片"永久允许"按钮可配置隐藏 | +61 | −28 |
232|- [ ] `64f53b1` | 2026-05-22 | `yangtb` | feat: add message:receive hook scaffolding for Viking context hint | +68 | −1 |
233|- [ ] `287a391` | 2026-05-22 | `yangtb` | feat(feishu): inline_code_copy configurable via patch.yaml, default off | +24 | −4 |
234|- [ ] `40e43ab` | 2026-05-22 | `yangtb` | feat(rate-limiter): add stepped cooldown + sliding window fixes | +574 | −15 |
235|- [ ] `89476ee` | 2026-05-22 | `yangtb` | 删除废弃的 viking-commit-runner.py wrapper | +0 | −5 |
236|- [ ] `5cd5d81` | 2026-05-21 | `yangtb` | chore(scripts): reorganize mac-specific scripts + add backup config | +227 | −111 |
237|- [ ] `54af397` | 2026-05-21 | `yangtb` | refactor(patch): consolidate hook configs under yangtb.hook namespace | +27 | −22 |
238|- [ ] `cdddbe2` | 2026-05-21 | `yangtb` | 修复auditor guard hook | +90 | −0 |
239|- [ ] `75eda7d` | 2026-05-21 | `yangtb` | refactor(hooks): remove mac/shell fallbacks, flatten viking-remember-guard | +93 | −211 |
240|- [ ] `b791919` | 2026-05-21 | `yangtb` | chore(hooks): switch auditor-guard/memory-guard to DAMODEL API, remove memory-guard | +8 | −174 |
241|- [ ] `37e6fba` | 2026-05-21 | `yangtb` | feat: model-level extra_body injection + cron args + backup scripts | +634 | −112 |
242|- [ ] `9e96955` | 2026-05-21 | `yangtb` | feat(provider): add provider_custom_name field for custom provider identity | +17 | −6 |
243|- [ ] `c7e5aaa` | 2026-05-20 | `yangtb` | fix: fall through to hardcoded defaults when model context length probe fails (prevent deepseek-v4-flash 1M default from being bypassed) | +50 | −6 |
244|- [ ] `ed95a26` | 2026-05-20 | `yangtb` | chore: remove audit-agent hook (agent:end file-change detection) | +1 | −973 |
245|- [ ] `2218a70` | 2026-05-20 | `yangtb` | fix: agent.chat_id -> agent._chat_id (AIAgent stores as _chat_id) | +6 | −6 |
246|- [ ] `b6e9852` | 2026-05-20 | `yangtb` | fix: pass platform/chat_id/user_message through pre_tool_call hook chain | +118 | −3 |
247|- [ ] `188be9d` | 2026-05-20 | `yangtb` | refactor: extract destructive_slash_confirm hardcoded strings into i18n locale files | +100 | −14 |
248|- [ ] `7d7cc28` | 2026-05-20 | `tianbao.yang` | feat(auditor-guard): suppress Branch D notification when built-in Approvals already approved the pattern | +42 | −10 |
249|- [ ] `94ccc55` | 2026-05-20 | `tianbao.yang` | fix(auditor-guard): align APPROVAL_FALLBACK_PATTERNS with Hermes DANGEROUS_PATTERNS + suppress Tirith variation_selector noise | +66 | −51 |
250|- [ ] `bb19362` | 2026-05-20 | `tianbao.yang` | feat(i18n): approvals 文案中文化 — 硬编码英文全部接入 t() 翻译 | +111 | −59 |
251|- [ ] `f138db1` | 2026-05-20 | `tianbao.yang` | refactor: replace plugins/image_gen/openai with openai_native | +388 | −38 |
252|- [ ] `befa350` | 2026-05-20 | `tianbao.yang` | docs(yangtb): add P30 (bare-domain base_url /v1 auto-append) to patch list | +4 | −3 |
253|- [ ] `a16843e` | 2026-05-20 | `tianbao.yang` | feat: auto-append /v1 for bare-domain base URLs (normalize_bare_domain_base_url) | +62 | −0 |
254|- [ ] `b917674` | 2026-05-20 | `tianbao.yang` | fix(agent): acp_args 空列表应存为 None 而非 [] | +1 | −1 |
255|- [ ] `022d45b` | 2026-05-20 | `tianbao.yang` | feat(image_gen): add model param to image_generate tool + yaml presets; update exchange rate | +52 | −9 |
256|- [ ] `f248f27` | 2026-05-20 | `tianbao.yang` | fix(auditor): 飞书卡片段落间 hr 重复横线问题 | +10 | −15 |
257|- [ ] `a6a18b3` | 2026-05-19 | `tianbao.yang` | Revert "feat(transports): add URL-based reasoning_effort support for LKeap/DeepSeek/DaModel" | +0 | −51 |
258|- [ ] `eb1df5d` | 2026-05-19 | `tianbao.yang` | Revert "refactor: extract _resolve_reasoning_effort helper, merge LKeap dual blocks" | +61 | −79 |
259|- [ ] `b30e774` | 2026-05-19 | `tianbao.yang` | Revert "fix: remove hardcoded extra_efforts from _resolve_reasoning_effort" | +15 | −5 |
260|- [ ] `54657dc` | 2026-05-19 | `tianbao.yang` | fix: remove hardcoded extra_efforts from _resolve_reasoning_effort | +5 | −15 |
261|- [ ] `5cbc280` | 2026-05-19 | `tianbao.yang` | refactor: extract _resolve_reasoning_effort helper, merge LKeap dual blocks | +79 | −61 |
262|- [ ] `083bb20` | 2026-05-19 | `tianbao.yang` | misc(yangtb): update patch list, pricing, auditor-guard templates | +11 | −3 |
263|- [ ] `1d00af0` | 2026-05-19 | `tianbao.yang` | feat(transports): add URL-based reasoning_effort support for LKeap/DeepSeek/DaModel | +51 | −0 |
264|- [ ] `9407c34` | 2026-05-19 | `tianbao.yang` | docs(yangtb): align patch list with v0.14.0 merge (P12/P22/P27/P28 marked covered) | +17 | −3 |
265|- [ ] `862b2cb` | 2026-05-19 | `tianbao.yang` | docs: bump patch count to 25 groups / 32 items, add P26 i18n gateway messages | +3 | −2 |
266|- [ ] `5110f6b` | 2026-05-19 | `tianbao.yang` | i18n: translate gateway lifecycle/busy-ack/steer/inactivity messages to Chinese | +480 | −36 |
267|- [ ] `4d33091` | 2026-05-19 | `tianbao.yang` | fix(feishu): add early-typing reaction when chat_lock is held | +21 | −0 |
268|- [ ] `e2fc1d0` | 2026-05-19 | `tianbao.yang` | auditor-guard: 修复 import 崩溃 + 新增 explain-only 模式 + JSON2 飞书卡片通知 | +349 | −70 |
269|- [ ] `d140932` | 2026-05-18 | `tianbao.yang` | feat(feishu): remove tool-activity filter from auto-card logic | +1 | −41 |
270|- [ ] `becd553` | 2026-05-18 | `tianbao.yang` | fix(feishu): add auto-card retry (3 attempts) + logging before plain-text fallback | +31 | −4 |
271|- [ ] `14d7ea7` | 2026-05-18 | `tianbao.yang` | fix: remove remaining provider_name traces after v0.14.0 merge | +0 | −2 |
272|- [ ] `c4d72ab` | 2026-05-18 | `tianbao.yang` | merge: sync yangtb with upstream v0.14.0 (v2026.5.16) | +0 | −0 |
273|- [ ] `429c8d5` | 2026-05-18 | `tianbao.yang` | feat(feishu): upgrade auto-card to JSON 2.0 schema for heading/table support | +4 | −1 |
274|- [ ] `06e17c1` | 2026-05-18 | `tianbao.yang` | feat(feishu): auto-card for long text responses when streaming disabled | +251 | −6 |
275|- [ ] `6dee454` | 2026-05-18 | `tianbao.yang` | refactor(auditor-guard): modular architecture v2 | +2644 | −969 |
276|- [ ] `2d941f4` | 2026-05-17 | `tianbao.yang` | fix: disk-watch-cron.py 路径修正 — cache-cleanup.py 已移至 mac/ 子目录 | +2 | −2 |
277|- [ ] `b5cbb31` | 2026-05-17 | `tianbao.yang` | fix(auditor): tirith detection + platform-aware delivery | +69 | −21 |
278|- [ ] `0214365` | 2026-05-17 | `tianbao.yang` | fix(feishu): preserve inline-code order when merging short spans for mobile copy-paste | +23 | −0 |
279|- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `d83c45b` | 2026-05-17 | `tianbao.yang` | refactor(token_stats): 移除pricing/cost计算，改为纯token用量统计，新增飞书卡片table支持 | +454 | −783 |
280|- [ ] `01dc1cf` | 2026-05-17 | `tianbao.yang` | feat(auditor): emotion auto-stop via API Server + session_id fix + 文案优化 | +174 | −28 |
281|- [ ] `5dc4608` | 2026-05-16 | `tianbao.yang` | fix(auditor-guard): merge session_id into extra for deliver_sync in qqbot | +330 | −158 |
282|- [ ] `edb1661` | 2026-05-16 | `tianbao.yang` | chore: sync hooks path fixes, update CHANGES.md with timeout→hard block design | +343 | −95 |
283|- [ ] `ca2cbe1` | 2026-05-16 | `tianbao.yang` | fix(auditor-guard): Stage 1 detected sensitive path should always trigger LLM audit even when fallback path string fails is_sensitive_path check | +3 | −1 |
284|- [ ] `979d7b2` | 2026-05-16 | `tianbao.yang` | feat(token_stats): add --from-date parameter for clean start date | +32 | −10 |
285|- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `73e2d37` | 2026-05-16 | `tianbao.yang` | fix: provider_name column now stores actual config name (fixes custom→custom bug) fix(token_stats): resolve env vars in ProviderRegistry URL index (case-sensitive) feat(pricing): add deepseek-company pricing (same as deepseek) fix(pricing): correct deepseek cache_read rates (/bin/zsh.0028//bin/zsh.003625 per official docs) | +133 | −10 |
286|- [ ] `dae8cd2` | 2026-05-16 | `tianbao.yang` | fix(auditor-guard): increase LLM timeout 15→60s, block on timeout instead of silent allow | +43 | −24 |
287|- [ ] `cae1a7c` | 2026-05-16 | `tianbao.yang` | refactor(scripts): migrate ~/.hermes/scripts/ to yangtb/scripts/ | +2926 | −8 |
288|- [ ] `d682be1` | 2026-05-16 | `tianbao.yang` | fix(feishu): render markdown tables natively in post md elements | +27 | −43 |
289|- [ ] `afbd94f` | 2026-05-15 | `tianbao.yang` | docs(auditor-guard): add CHANGES.md implementation changelog | +105 | −0 |
290|- [ ] `a7c635a` | 2026-05-15 | `tianbao.yang` | style(auditor-guard): move emoji to beginning of notification titles | +4 | −4 |
291|- [ ] `18e0591` | 2026-05-15 | `tianbao.yang` | style(auditor-guard): unify notification message format | +4 | −4 |
292|- [ ] `3860f6d` | 2026-05-15 | `tianbao.yang` | feat(auditor-guard): pass user_message through hook for real-time approval check | +1726 | −687 |
293|- [ ] `7a05837` | 2026-05-15 | `tianbao.yang` | fix(delivery_helpers): set chat_id in extra dict for _build_headers | +2 | −0 |
294|- [ ] `50880df` | 2026-05-15 | `tianbao.yang` | fix(delivery_helpers): resolve chat_id from HERMES_SESSION_KEY fallback | +55 | −1 |
295|- [ ] `8f5e18e` | 2026-05-15 | `tianbao.yang` | fix(auditor-guard): deliver hard block message to Feishu chat | +2 | −0 |
296|- [ ] `f8a5208` | 2026-05-15 | `tianbao.yang` | feat(auditor-guard): enhanced observability logging | +26 | −3 |
297|- [ ] `68e12e8` | 2026-05-15 | `tianbao.yang` | feat(auditor-guard): emotion-based blocking + user approval check | +86 | −16 |
298|- [ ] `923004a` | 2026-05-15 | `tianbao.yang` | refactor(hooks): extract shared utilities to hooks/common/ | +667 | −32 |
299|- [ ] `05d2d06` | 2026-05-15 | `tianbao.yang` | feat: add feishu_get_messages tool for reading chat message history | +311 | −0 |
300|- [ ] `67cf0fe` | 2026-05-15 | `tianbao.yang` | fix: add qwen3.6/3.5 family entries to DEFAULT_CONTEXT_LENGTHS | +6 | −3 |
301|- [x] ⏭️ 跳过 `f36852f` | 2026-05-14 | `tianbao.yang` | Merge upstream/main into yangtb (4 conflicts resolved intelligently) | +0 | −0 |
302|- [ ] `dd36093` | 2026-05-14 | `tianbao.yang` | chore: update daily viking health report script + add .serena config | +135 | −1 |
303|- [ ] `1ca28d8` | 2026-05-14 | `tianbao.yang` | feat(yangtb): rewrite daily-viking-health-report with full OpenViking diagnostics | +263 | −31 |
304|- [ ] `7b90874` | 2026-05-14 | `tianbao.yang` | refactor: remove channel field from config.yaml, centralize in patch.yaml | +78 | −144 |
305|- [ ] `f800b5a` | 2026-05-14 | `tianbao.yang` | feat(tui): dynamic provider name in banner from config.yaml model.provider | +20 | −1 |
306|- [ ] `2e163aa` | 2026-05-14 | `tianbao.yang` | feat(token_stats): add --card mode for Feishu interactive card delivery | +183 | −1 |
307|- [ ] `b242719` | 2026-05-14 | `tianbao.yang` | fix(sre-archive): async subprocess + retry + SKIP exit code + misc hardening | +592 | −62 |
308|- [ ] `c822adb` | 2026-05-13 | `tianbao.yang` | fix(session): source-level thinking-prefill filtering instead of dead read-path check | +7 | −0 |
309|- [ ] `4fee7db` | 2026-05-13 | `tianbao.yang` | fix(session): filter _thinking_prefill messages from get_messages() to prevent thinking leakage | +8 | −1 |
310|- [ ] `5a654df` | 2026-05-13 | `tianbao.yang` | fix(gateway): 过滤 thinking prefill 消息，防止污染会话历史 | +7 | −3 |
311|- [ ] `a5246ae` | 2026-05-13 | `tianbao.yang` | fix(sre-archive): use gateway/run.py's skill extraction logic instead of custom parser | +83 | −13 |
312|- [ ] `62ec570` | 2026-05-13 | `tianbao.yang` | refactor(hooks): 三根日志统一轮转为 DailySizeRotatingFileHandler | +334 | −18 |
313|- [ ] `a572c36` | 2026-05-12 | `tianbao.yang` | fix(feishu): emoji width compensation in _align_table | +9 | −1 |
314|- [ ] `ea163c7` | 2026-05-11 | `tianbao.yang` | feat(token): bailing provider daily 500k free tier support | +134 | −27 |
315|- [x] ✅ 已迁移 `e7edb2f` | 2026-05-11 | `tianbao.yang` | docs(yangtb): update patch count and add P29 env-var template leak fix to README | +5 | −4 |
316|- [x] ✅ 已迁移 `85d345e` | 2026-05-11 | `tianbao.yang` | fix: guard against env-var template leak in base_url resolution (#17101) | +22 | −3 |
317|- [ ] `14b8a31` | 2026-05-11 | `tianbao.yang` | audit-agent: i18n docstring/comments, get_hermes_home, batch git diff, checkpoint trim | +100 | −49 |
318|- [ ] `6b0c817` | 2026-05-11 | `tianbao.yang` | feat(credential-pool): add proactive sliding-window rate limiter per (provider, key) | +246 | −19 |
319|- [ ] `acebc2c` | 2026-05-11 | `tianbao.yang` | audit-agent: filter remote/SSH paths from LLM prompt, add terminal to FILE_MODIFY_TOOLS | +16 | −3 |
320|- [ ] `c1a60da` | 2026-05-11 | `tianbao.yang` | audit-agent: add LLM extraction error alert + mv/rm rename tracking | +172 | −17 |
321|- [ ] `3dd85dd` | 2026-05-11 | `tianbao.yang` | fix(audit-agent): per-auditor rate limiter, aiohttp delivery, alert improvements | +53 | −24 |
322|- [ ] `dae821a` | 2026-05-11 | `tianbao.yang` | refactor(audit-agent): plugin-style auditor architecture with error isolation | +423 | −293 |
323|- [ ] `8f8b76c` | 2026-05-10 | `tianbao.yang` | feat(audit-agent): move audit-agent hook source to yangtb/hooks/ | +652 | −1 |
324|- [ ] `f329993` | 2026-05-10 | `tianbao.yang` | feat(yangtb/scripts): 新增 daily-viking-health-report.py — 每日Memory整理报告脚本，对比Viking而非本地KB | +44 | −0 |
325|- [ ] `1284034` | 2026-05-10 | `tianbao.yang` | fix(cron): add yangtb/scripts/ symlink exemption to _validate_cron_script_path | +9 | −0 |
326|- [ ] `281e6fc` | 2026-05-10 | `tianbao.yang` | fix(gateway): add clarify_callback for messaging platforms | +12 | −2 |
327|- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `f0176ae` | 2026-05-10 | `tianbao.yang` | refactor(token_stats): multi-currency pricing support + markdown output | +90 | −47 |
328|- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `32333de` | 2026-05-10 | `tianbao.yang` | docs(yangtb/config): note pricing.yaml fields updated by cron scripts | +1 | −1 |
329|- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `f64ae67` | 2026-05-10 | `tianbao.yang` | feat(yangtb): add update_exchange_rate.py script + top-level default_exchange_rate in pricing.yaml | +115 | −9 |
330|- [⏸️ 已决策·暂不迁移] `3ea5daa` | 2026-05-10 | `tianbao.yang` | feat(api-server): expose model_aliases in /v1/models endpoint | +87 | −26 |
331|- [ ] `6fe0530` | 2026-05-10 | `tianbao.yang` | fix(qqbot): abort reconnect on disconnect, fix CLOSE→UP state bug | +215 | −34 |
332|- [x] ✅ 已迁移 `beecdcd` | 2026-05-09 | `tianbao.yang` | fix(gateway): resolve env-var template base_url in _format_session_info | +5 | −1 |
333|- [ ] `1fc7348` | 2026-05-09 | `tianbao.yang` | fix(qqbot): set proxy=None instead of proxies={} for httpx client | +1 | −1 |
334|- [ ] `ccfcdab` | 2026-05-09 | `yangtb` | feat(api_server): model_aliases routing — route requests by body.model to different provider | +70 | −2 |
335|- [ ] `c4071f9` | 2026-05-09 | `tianbao.yang` | fix(feishu): rebuild separator dashes from col_widths, not original dash count | +10 | −6 |
336|- [ ] `52b8356` | 2026-05-09 | `tianbao.yang` | fix(feishu): set wcswidth ambiguous_width=2 for CJK table alignment | +5 | −3 |
337|- [ ] `bf59dfc` | 2026-05-09 | `tianbao.yang` | fix(viking-remember): isolate viking_remember into temp session to avoid overlap with Hermes auto memory | +21 | −9 |
338|- [ ] `865b5fc` | 2026-05-09 | `tianbao.yang` | chore(yangtb): sre-archive hook, session skill tracking, config | +470 | −1 |
339|- [x] ✅ 已迁移 `efd22de` | 2026-05-08 | `tianbao.yang` | feat: local customizations — skin engine, TUI tweaks, cron scheduler | +39 | −7 |
340|- [x] ⏭️ 跳过 `2938886` | 2026-05-08 | `tianbao.yang` | Merge upstream/main into yangtb — v0.13.0 sync (237 commits) | +0 | −0 |
341|- [x] ⏸️ 已决策·暂不迁移（依赖 _append_inline_code_reference 函数整体迁移） `21d4700` | 2026-05-08 | `tianbao.yang` | fix(feishu): wrap multi-item inline-code ref in code block for one-tap copy | +9 | −1 |
342|- [x] ✅ 已迁移·TUI部分（hooks在owner/单独处理） `085513e` | 2026-05-08 | `tianbao.yang` | fix(tui): FaceTicker verb reads from skin spinner instead of hardcoded VERBS import | +357 | −6 |
343|- [x] ✅ 已迁移（skin YAML → owner/skins/） `3622735` | 2026-05-08 | `tianbao.yang` | refactor: move ruolin skins to yangtb/skins/ with symlinks | +236 | −8 |
344|- [x] ⏭️ 跳过（yangtb/README.md 文档 + OpenViking 已废弃） `5ce1904` | 2026-05-08 | `tianbao.yang` | docs: add external assets inventory to yangtb/README.md | +57 | −10 |
345|- [x] ⏭️ 跳过（yangtb/README.md 不存在于 owner-v16） `088ade4` | 2026-05-08 | `tianbao.yang` | docs: remove deprecated section from yangtb/README.md | +0 | −12 |
346|- [x] ⚠️ 废弃（yangtb/README.md OpenViking 文档，OpenViking 已停用） `3d438f8` | 2026-05-08 | `tianbao.yang` | docs: add OpenViking deployment and pitfalls to yangtb/README.md | +159 | −0 |
347|- [x] ⚠️ 废弃（yangtb/README.md 初始文档，不存在于 owner-v16） `8735a40` | 2026-05-08 | `tianbao.yang` | docs: add yangtb/README.md with full customization inventory | +160 | −0 |
348|- [x] ⏭️ 跳过（pricing废弃 + patch.yaml中TF-IDF延后单独处理） `2416220` | 2026-05-08 | `tianbao.yang` | refactor: move config files to yangtb/config/ | +226 | −1 |
349|- [x] ✅ 已迁移·部分（4脚本→owner/scripts/，token_stats/daily_memory废弃，viking废弃，tfidf延后） `fcc9291` | 2026-05-08 | `tianbao.yang` | refactor: move personal scripts to yangtb/scripts/ | +1509 | −0 |
350|- [ ] `cc7f46a` | 2026-05-08 | `tianbao.yang` | fix(tui): pass missing spinner arg to renderIndicator | +1 | −1 |
351|- [ ] `fad4db4` | 2026-05-08 | `tianbao.yang` | feat: auto-inject recovery context after LLM API disconnect | +78 | −1 |
352|- [ ] `22ed810` | 2026-05-08 | `tianbao.yang` | fix: LLM API silent disconnect now notifies user in current chat | +67 | −0 |
353|- [ ] `aed81f7` | 2026-05-08 | `tianbao.yang` | refactor: migrate tf-idf to patch.yaml + remove pin mechanism | +80 | −72 |
354|- [ ] `3b8031c` | 2026-05-08 | `tianbao.yang` | fix(feishu): rewording — 兼容性参考 → 手机端复制粘贴兼容 | +1 | −1 |
355|- [ ] `bf0832b` | 2026-05-08 | `tianbao.yang` | feat(feishu): append inline code spans as plain-text reference for mobile copy | +41 | −0 |
356|- [ ] `526eea8` | 2026-05-08 | `tianbao.yang` | feat(feishu): align markdown table columns in code blocks using wcwidth | +88 | −1 |
357|- [ ] `5031f9c` | 2026-05-08 | `tianbao.yang` | fix(feishu): prevent markdown format corruption from nested code fences and unsupported tables | +33 | −6 |
358|- [x] ⏭️ 跳过 `915baf1` | 2026-05-07 | `tianbao.yang` | Merge upstream/main into yangtb (503 commits behind) | +0 | −0 |
359|- [x] ⚠️ 废弃：OpenViking 插件已弃用，Qdrant 是当前 backing store `627f3e1` | 2026-05-07 | `tianbao.yang` | feat: add commit_all_on_new support via patch.yaml | +90 | −0 |
360|- [⏸️ 已决策·待后续观察] `e87a6f1` | 2026-05-05 | `tianbao.yang` | feat(tfidf): add pin list support for always-loaded skills | +12 | −0 |
361|- [ ] `c4fdf38` | 2026-05-05 | `tianbao.yang` | Fix UnboundLocalError: _classified nested inside skills_list_snapshot guard | +18 | −18 |
362|- [⏸️ 已决策·待后续观察] `4fac935` | 2026-05-05 | `tianbao.yang` | Phase 3c: LLM fallback line-mode + platform-level disable | +84 | −35 |
363|- [⏸️ 已决策·待后续观察] `e05beff` | 2026-05-05 | `tianbao.yang` | feat: enhance precompute to capture multi-message training data (Phase 3) | +52 | −27 |
364|- [ ] `e0194a6` | 2026-05-05 | `tianbao.yang` | fix: add missing yaml_load import in prompt_builder (Layer 3 fallback was dead code) | +1 | −0 |
365|- [⏸️ 已决策·待后续观察] `8b81f60` | 2026-05-05 | `tianbao.yang` | feat: integrate LLM fallback + skills snapshot into build_skills_system_prompt (Phase 3c) | +52 | −1 |
366|- [⏸️ 已决策·待后续观察] `29e0d91` | 2026-05-05 | `tianbao.yang` | feat: add LLM intent classifier for Layer 3 fallback (Phase 3c) | +247 | −0 |
367|- [ ] `cd3aa9c` | 2026-05-05 | `tianbao.yang` | fix: handle null skills in _get_top_usage_skills records | +1 | −1 |
368|- [⏸️ 已决策·待后续观察] `ca110e6` | 2026-05-05 | `tianbao.yang` | feat: add Layer 0 Top-N always-on skills to TF-IDF tracker (Phase 3a) | +58 | −0 |
369|- [⏸️ 已决策·待后续观察] `a06d719` | 2026-05-05 | `tianbao.yang` | feat: extract _is_high_info_message() as shared utility for TF-IDF pipeline | +74 | −0 |
370|- [⏸️ 已决策·暂不迁移] `248bebe` | 2026-05-05 | `tianbao.yang` | fix: strip 'source' and 'requested_provider' from runtime_kwargs in api_server._create_agent | +49 | −0 |
371|- [x] ✅ 已迁移 `9a95e21` | 2026-05-04 | `tianbao.yang` | fix(qqbot): add WebSocket heartbeat + receive_timeout to detect TCP half-open after WSL sleep/wake | +2 | −0 |
372|- [x] ⚠️ 废弃: 上游 v0.14.0 billing_provider 替代 `c1effe4` | 2026-05-04 | `tianbao.yang` | fix: separate provider_name from provider to preserve custom provider identity | +16 | −5 |
373|- [x] ✅ 已迁移 `97c43f6` | 2026-05-04 | `tianbao.yang` | fix(qqbot): rebuild httpx client on reconnect to fix WSL sleep/wake network reset | +28 | −0 |
374|- [⏸️ 已决策·暂不迁移] `b926356` | 2026-05-04 | `tianbao.yang` | fix(gateway): fallback /status model/provider display when DB values are None/custom | +12 | −2 |
375|- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `0b7742b` | 2026-05-04 | `tianbao.yang` | feat(pricing): dual-currency support (CNY/USD) + deepseek-v4 pricing + cache hit rate | +46 | −6 |
376|- [x] ⚠️ 废弃 `e8841ac` | 2026-05-03 | `tianbao.yang` | chore: update package-lock after upstream merge | +25 | −16 |
377|- [x] ⏭️ 跳过 `0d1302e` | 2026-05-03 | `tianbao.yang` | Merge upstream/main into yangtb (631 commits, 11 conflicts resolved) | +0 | −0 |
378|- [x] ✅ 已迁移 `e7d46fc` | 2026-05-03 | `tianbao.yang` | fix(hermes_mon): migrate data dir to ~/.local/share + dedup hourly aggregation | +29 | −4 |
379|- [x] ✅ 已迁移 `a8fc5d1` | 2026-05-03 | `tianbao.yang` | feat(skin): add tagline field for banner subtitle | +6 | −3 |
380|- [x] ✅ 已迁移 `889ef45` | 2026-05-03 | `tianbao.yang` | feat(skin): pipe spinner data (faces/verbs) from skin engine through to TUI FaceTicker | +39 | −11 |
381|- [x] ✅ 已迁移 `02278cd` | 2026-05-03 | `tianbao.yang` | feat(scripts): add hermes_mon - per-process perf monitoring with launchd | +483 | −0 |
382|- [x] ✅ 已迁移 `7c5bbdf` | 2026-05-02 | `tianbao.yang` | fix(qqbot): prevent silent dead-loop when WS closed after reconnect failure | +1 | −1 |
383|- [⏸️ 已决策·暂不迁移] `7d7e559` | 2026-05-02 | `tianbao.yang` | feat: 方案2 — 会话内 skill 创建跟踪 + 存活过滤 | +142 | −12 |
384|- [⏸️ 已决策·暂不迁移] `f81cca5` | 2026-05-02 | `tianbao.yang` | feat: recency exemption for TF-IDF skill filtering (72h mtime window) | +65 | −0 |
385|- [⏸️ 已决策·暂不迁移] `4e88521` | 2026-05-02 | `tianbao.yang` | feat: system prompt audit logging via write_sysprompt_audit_entry | +100 | −1 |
386|- [⏸️ 已决策·暂不迁移] `7634496` | 2026-05-02 | `tianbao.yang` | system prompt compression and skill utils refactor | +125 | −71 |
387|- [⏸️ 已决策·暂不迁移] `6c37b19` | 2026-05-02 | `tianbao.yang` | feat: integrate SkillsUsageTracker into run_agent.py | +35 | −2 |
388|- [⏸️ 已决策·暂不迁移] `304a5ad` | 2026-05-02 | `tianbao.yang` | feat: add SkillsUsageTracker for TF-IDF skill filtering | +510 | −6 |
389|- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `18d81fb` | 2026-05-02 | `tianbao.yang` | add pricing entries for grok-4-fast-reasoning, grok-4-fast-non-reasoning, grok-4-fast, grok-2, grok-2-vision-1212 | +50 | −0 |
390|- [x] ✅ 已迁移 `b14a2ee` | 2026-04-30 | `tianbao.yang` | fix(feishu): return empty P2CardActionTriggerResponse to avoid CallBackToast NameError in WS client | +3 | −9 |
391|- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `b65b962` | 2026-04-30 | `tianbao.yang` | feat(usage): extend pricing data with YAML-based provider pricing support | +314 | −0 |
392|- [⏸️ 已决策·暂不迁移] `28e513d` | 2026-04-30 | `tianbao.yang` | feat(file_tools): add headings_only parameter for markdown heading extraction | +39 | −6 |
393|- [⏸️ 已决策·暂不迁移] `a6b718b` | 2026-04-30 | `tianbao.yang` | fix(session_search): fast window mode around FTS5 hits for long sessions (#16671 workaround) | +149 | −2 |
394|- [x] ❌ DEPRECATED `0be2695` | 2026-04-30 | `tianbao.yang` | perf(agent): stabilize system prompt timestamp across compression cycles | +15 | −2 | (upstream PR #27675 merged as `4a3f13b`, date-only方案更简单无依赖)
395|- [x] ✅ P15 已迁移 `a484c2c` | 2026-04-29 | `tianbao.yang` | feat(tui): support ;; chained commands in quick_commands aliases | +141 | −64 |
396|- [x] ✅ 已迁移 `fbb98ae` | 2026-04-29 | `tianbao.yang` | feat(feishu): support channel_prompts from config.yaml | +4 | −0 |
397|- [x] ✅ 已迁移 `dbb99d5` | 2026-04-29 | `tianbao.yang` | feat(tui): 选中即复制 (auto copy-on-select) | +49 | −4 |
398|- [x] ✅ P15 已迁移 `1780ea8` | 2026-04-28 | `tianbao.yang` | refactor(gateway): canonical command routing in quick command handler | +131 | −6 |
399|- [x] ✅ P15 已迁移 `0cbcb3e` | 2026-04-28 | `tianbao.yang` | fix(cli): add quick_commands autocomplete to SlashCommandCompleter | +26 | −0 |
400|- [x] ⏭️ 跳过 `b1fff64` | 2026-04-28 | `tianbao.yang` | Merge remote-tracking branch 'upstream/main' into yangtb | +0 | −0 |
401|- [x] ⚠️ 废弃：/status model/provider 显示，不再需要 `c99f15f` | 2026-04-27 | `tianbao.yang` | fix(tui): resolve /status ambiguous command error | +36 | −14 |
402|- [x] ⏭️ 跳过 `3f510d0` | 2026-04-27 | `tianbao.yang` | Merge remote-tracking branch 'upstream/main' | +0 | −0 |
403|- [x] ✅ P15 已迁移 `0034173` | 2026-04-27 | `tianbao.yang` | fix(tui): resolve quick_commands alias in _mirror_slash_side_effects | +28 | −0 |
404|- [x] ✅ P15 已迁移 `6efc6a8` | 2026-04-27 | `tianbao.yang` | fix(cli): support ;; chain in quick_commands alias type | +25 | −4 |
405|- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `736da3a` | 2026-04-27 | `tianbao.yang` | feat: add xAI Grok pricing entries | +185 | −0 |
406|- [x] ✅ P15 已迁移 `552ad0b` | 2026-04-27 | `tianbao.yang` | feat(gateway): support chained quick_commands with ;; | +67 | −14 |
407|- [x] ⚠️ 废弃：/status model/provider 显示，不再需要 `cb0b2e7` | 2026-04-27 | `tianbao.yang` | fix: fetch model/provider from session_db instead of SessionEntry | +8 | −2 |
408|- [x] ⚠️ 废弃：/status model/provider 显示，不再需要 `67471f3` | 2026-04-27 | `tianbao.yang` | feat: add current session model and provider to /status output in gateway | +2 | −0 |
409|- [x] ✅ P15 已迁移 `22b90ab` | 2026-04-27 | `tianbao.yang` | fix(gateway): quick_command alias should explicitly call built-in command handlers | +10 | −2 |
410|- [x] ⚠️ 废弃：定价/AGENTS.md，不迁移 `4a0997d` | 2026-04-26 | `tianbao.yang` | docs: update AGENTS.md development guide | +141 | −630 |
411|
412|## 复现方式
413|
414|```bash
415|python3 owner/docs/generate-our-commits-inventory.py
416|python3 owner/docs/generate-our-commits-inventory.py --ref refs/heads/owner --output /tmp/our-commits.md
417|```
418|
419|## 作者身份说明
420|
421|- **`yangtb`** — 当前 git config user.name（commit 主流用名）
422|- **`tianbao.yang`** — 早期拼音形式（同一开发者，邮箱 `<空>`）
423|- 两个 author 视为同一人，**杨天宝**
424|- 邮箱均为占位 `123`，**建议未来改成真实邮箱后再统计**
425|
426|## 统计口径说明
427|
428|- **commit 数**：`git rev-list --count <ref> --author=<name>`
429|- **行数**：`git log <ref> --author=<name> --numstat` 累加每个文件的 `+` / `-` 行
430|- **二进制文件**：numstat 输出 `-\t-`，跳过不计
431|- **merge commit**：默认包含
432|
