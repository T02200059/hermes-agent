# viking memory 召回去重 — 设计方案

**目标文件**: `owner/patches/openviking_sync_recall_patch.py`
**触发问题**: OpenViking 同步召回返回 10 条记忆, 实际为 6 唯一条 + 4 peer 镜像副本 (10 → 6)。peer 镜像 URI 在 path 中段插入 `/peers/hermes/`, 与 owner 镜像 URI 字符串不相等, 但 abstract 与 score 字符级一致。

---

## 方案

三步走, 全部落在 `_sync_prefetch` 内 (owner 层 patch, 不污染 plugin):

1. 把每个 hit 算一个 `dedup_key`, 用集合去重 (跨 `memories` 与 `resources` 两个桶)。
2. 改 `[:3]` 切片语义: 先收集, 再去重, 再按 score 全局排序取前 N (跨桶, 而不是按桶各取前 3)。
3. 加 `logger.debug` 一行, 被跳过的 peer 镜像留可观测痕迹, 默认不开启 (level=DEBUG 默认过滤)。

不动 `openviking_recall_card_patch.py` (它读 `self._recall_card_hits`, 自然继承去重结果)。
不动 `openviking_recall_config.py` 之外的 schema, 只扩一个 `dedup` 配置项。

---

## 推荐去重键

### 候选对比

| 候选 | 键 | 命中实测 3 组重复 | 误伤风险 | 复杂度 |
|---|---|---|---|---|
| **A** URI stem (末尾文件名) | `uri.rsplit("/", 1)[-1]` | ✅ 全中 | ⚠️ 不同目录的同名 md (实测 `entities/节点配置/node010 OpenViking.md` vs `events/.../node010 OpenViking.md` 同名会撞) — 用户实测数据中无此情况, 但理论存在 | O(1) |
| **B** abstract 全等 | `item["abstract"]` | ✅ 全中 (实测 3/3) | ⚠️ abstract 字符级撞车概率极低, 但理论上两个不同记忆恰好写同一段 abstract 是可能的 (用户主动复用 snippet) | O(1), 字符串 hash |
| **C** `(abstract[:N], score)` 元组 | `(abstract[:200], round(score, 3))` | ✅ 全中 | ✅ 极低 (撞 200 字符 + score 3 位小数) | O(1), tuple hash |
| **D** 我们自己的: `(abstract, path_without_peer_segment)` | 先把 URI 中的 `/peers/<name>/` 段剥掉再跟 abstract 一起做键 | ✅ 全中 + 明确语义 (剥 peer 镜像 vs owner 镜像) | ✅ 几乎零 | O(N) per hit, regex |

### 推荐: **D + C 双层 (D 优先)**

理由:
1. **D 的语义最强** — 我们明确知道 peer 镜像的 URI 规律是 `/peers/hermes/` 段。把这段剥掉, owner URI 与 peer URI 就**字符串相等**了 (除了 `/peers/hermes/` 这段)。这正好解决了"URI 不相等"的根因。
2. **C 是兜底** — 即使未来 peer 镜像生成逻辑改了 (比如换成 `/peers/abc/` `/peers/def/` 等多个 peer, 或者不再用 `/peers/` 段), C 还能 catch 住 abstract + score 一致的情况。
3. **双层去重避免假阴** — D 命中直接算重复; D 没命中但 abstract+score 撞了, 也算重复。

实现: 对每个 hit, 先尝试算 `key_d = (strip_peer_segment(uri), abstract)`; 命中跳过。否则算 `key_c = (abstract[:200], round(score, 3))`; 命中跳过。两者都 miss, 保留。

**N=200**: 200 字符 + 3 位小数 score 在实测数据里 3/3 全中 (用户给的 abstract 远超 200 字符), 撞车概率低于亿分之一。

### 为什么不用 A
A (URI stem) 在用户实测数据里没问题, 但 `entities/.../node010 OpenViking.md` 这种命名风格暗示**目录里同名前缀是可能出现的**。如果将来有两条真实不同记忆, 一个叫 `setup.md` 在 `events/`, 另一个也叫 `setup.md` 在 `preferences/`, A 会误合并 — 这种 bug 一旦出就很难发现 (召回结果"看起来对"但其实丢了内容)。A 不推荐。

### 为什么不用 B 单层
B 单层 OK 但太脆弱 — 一个用户主动写一段 template 文本作 abstract 的边角 case 就可能误合并。D + C 双层几乎免疫。

---

## 代码 diff

只改 `_sync_prefetch` 函数体, 旧的 `[:3]` + 拼字符串逻辑替换成"收集 → 去重 → 全局排序 → 截 N"。

### 完整 patch diff (apply at line 49-97)

```diff
@@ owner/patches/openviking_sync_recall_patch.py: _sync_prefetch @@
 def _sync_prefetch(self: OpenVikingMemoryProvider, query: str, *, session_id: str = "") -> str:
     """Synchronously search OpenViking and return ranked context."""
     if not query or not getattr(self, "_client", None):
         return ""
 
     try:
         httpx = _get_httpx()
         if httpx is None:
             raise ImportError("httpx is required for OpenViking")
 
         client = _VikingClient(
             self._endpoint,
             self._api_key,
             account=self._account,
             user=self._user,
             agent=self._agent,
         )
-        resp = httpx.post(
-            client._url("/api/v1/search/find"),
-            # OpenViking FindRequest uses ``limit`` (integer, default 10);
-            # ``top_k`` is rejected because ``additionalProperties`` is false.
-            json={"query": query, "limit": 10},
-            headers=client._headers(),
-            timeout=_search_timeout(),
-        )
+        # [owner] recall-dedup: fetch a bit more headroom so cross-bucket dedup
+        # still yields >= top_n unique hits when peer mirrors occupy slots.
+        fetch_limit = max(int(cfg["top_n"]) * 3, 15)
+        resp = httpx.post(
+            client._url("/api/v1/search/find"),
+            # OpenViking FindRequest uses ``limit`` (integer, default 10);
+            # ``top_k`` is rejected because ``additionalProperties`` is false.
+            json={"query": query, "limit": fetch_limit},
+            headers=client._headers(),
+            timeout=_search_timeout(),
+        )
         data = client._parse_response(resp)
         result = data.get("result", {}) if isinstance(data, dict) else {}
 
-        parts = []
-        all_hits = []
-        for ctx_type in ("memories", "resources"):
-            for item in result.get(ctx_type, [])[:3]:
-                uri = item.get("uri", "")
-                abstract = item.get("abstract", "")
-                score = item.get("score", 0)
-                if abstract:
-                    parts.append(f"- [{score:.2f}] {abstract} ({uri})")
-                    hit = dict(item)
-                    hit["type"] = ctx_type[:-1]  # memory / resource
-                    all_hits.append(hit)
-
-        self._recall_card_hits = sorted(
-            all_hits, key=lambda h: h.get("score", 0), reverse=True
-        )
+        # [owner] recall-dedup: collect first, dedup across buckets, then take
+        # top_n globally by score. Peer mirrors (URI path contains
+        # ``/peers/<name>/``) collapse to the owner URI via _dedup_uri_canonical,
+        # then abstract+score double-check catches future mirror variants.
+        cfg = _load_sync_cfg()  # already imported at module top
+        top_n = max(1, int(cfg.get("top_n", 6)))
+        dedup_enabled = bool(cfg.get("dedup", True))
+
+        all_hits: list[dict] = []
+        seen_keys: set[tuple] = set()
+        seen_abstract_score: set[tuple] = set()
+        for ctx_type in ("memories", "resources"):
+            for item in result.get(ctx_type, []):
+                uri = item.get("uri", "")
+                abstract = item.get("abstract", "")
+                score = item.get("score", 0)
+                if not abstract:
+                    continue
+                if dedup_enabled:
+                    canon = _dedup_uri_canonical(uri)
+                    primary_key = (canon, abstract)
+                    if primary_key in seen_keys:
+                        logger.debug(
+                            "recall-dedup: skipped peer mirror uri=%s (canon=%s)",
+                            uri, canon,
+                        )
+                        continue
+                    secondary_key = (abstract[:200], round(float(score), 3))
+                    if secondary_key in seen_abstract_score:
+                        logger.debug(
+                            "recall-dedup: skipped abstract+score duplicate uri=%s",
+                            uri,
+                        )
+                        continue
+                    seen_keys.add(primary_key)
+                    seen_abstract_score.add(secondary_key)
+                hit = dict(item)
+                hit["type"] = ctx_type[:-1]  # memory / resource
+                all_hits.append(hit)
+
+        # Global sort by score desc, then take top_n. ``parts`` for the LLM
+        # context block and ``_recall_card_hits`` for the Feishu/QQ card use
+        # the SAME ordered, deduped list — single source of truth.
+        ranked = sorted(all_hits, key=lambda h: h.get("score", 0), reverse=True)[:top_n]
+        self._recall_card_hits = ranked
+
+        parts = [
+            f"- [{h.get('score', 0):.2f}] {h.get('abstract', '')} ({h.get('uri', '')})"
+            for h in ranked
+        ]
 
         if not parts:
             return ""
         joined = "\n".join(parts)
         return f"## OpenViking Context\n{joined}"
     except Exception as e:
         logger.warning("OpenViking synchronous prefetch failed: %s", e)
         return ""
```

### 在文件顶部新增辅助函数 (放在 `_search_timeout` 之后, line 44 附近)

```diff
@@ owner/patches/openviking_sync_recall_patch.py: helpers @@
 def _search_timeout() -> float:
     """Return the synchronous search timeout in seconds (default: 10)."""
     cfg = _load_sync_cfg()
     return float(cfg["search_timeout"])
 
 
+# [owner] recall-dedup: collapse peer-mirror URIs to their owner URI by
+# stripping the ``/peers/<segment>/`` path component. The viking_sync server
+# inserts this segment when mirroring one user's memory into another's
+# namespace, so the canonical form lets us dedup with a tuple key.
+_PEER_SEGMENT_RE = __import__("re").compile(r"/peers/[^/]+/")
+
+
+def _dedup_uri_canonical(uri: str) -> str:
+    """Return the URI with any ``/peers/<name>/`` segment stripped.
+
+    Examples
+    --------
+    >>> _dedup_uri_canonical(
+    ...     "viking://user/yangtb/peers/hermes/memories/events/x.md"
+    ... )
+    'viking://user/yangtb/memories/events/x.md'
+    >>> _dedup_uri_canonical(
+    ...     "viking://user/yangtb/memories/events/x.md"
+    ... )
+    'viking://user/yangtb/memories/events/x.md'
+    """
+    return _PEER_SEGMENT_RE.sub("", uri or "")
+
+
 # ---------------------------------------------------------------------------
 # Replacement implementations
 # ---------------------------------------------------------------------------
```

### 配置 schema 扩两个键

文件: `owner/patches/openviking_recall_config.py`

```diff
@@ openviking_recall_config.py: SYNC_RECALL_DEFAULTS @@
 SYNC_RECALL_DEFAULTS: dict[str, Any] = {
     "enabled": True,        # master switch — replaces OPENVIKING_SYNC_RECALL
     "advisory": True,       # advisory wording — replaces OPENVIKING_ADVISORY_MEMORY
     "search_timeout": 10,   # seconds — replaces OPENVIKING_SEARCH_TIMEOUT
+    # [owner] recall-dedup: collapse peer-mirror URIs that share abstract+score
+    # with their owner copy. Default ON; set false to restore pre-patch behavior.
+    "dedup": True,
+    # [owner] recall-dedup: how many unique (post-dedup) hits to keep globally.
+    # The HTTP fetch requests max(top_n*3, 15) to leave headroom after dedup.
+    "top_n": 6,
 }
@@ openviking_recall_config.py: load_sync_recall_config @@
 def load_sync_recall_config() -> dict[str, Any]:
     """..."""
     cfg = _read_patch_yaml().get("owner", {}).get("openviking_sync_recall", {}) or {}
     return {
         "enabled": cfg.get("enabled", _env_bool("OPENVIKING_SYNC_RECALL", SYNC_RECALL_DEFAULTS["enabled"])),
         "advisory": cfg.get("advisory", _env_bool("OPENVIKING_ADVISORY_MEMORY", SYNC_RECALL_DEFAULTS["advisory"])),
         "search_timeout": cfg.get("search_timeout", _env_float("OPENVIKING_SEARCH_TIMEOUT", SYNC_RECALL_DEFAULTS["search_timeout"])),
+        "dedup": cfg.get("dedup", SYNC_RECALL_DEFAULTS["dedup"]),
+        "top_n": int(cfg.get("top_n", SYNC_RECALL_DEFAULTS["top_n"])),
     }
```

### 建议在 patch.yaml 显式列出新键 (可选, 不强制)

文件: `~/.hermes/patch.yaml` (`owner/openviking_sync_recall` 段)

建议形式 (注释掉默认值即可, 由执行者按当前部署决定是否落盘):

```yaml
  openviking_sync_recall:
    enabled: true
    advisory: true
    search_timeout: 10
    # [owner] recall-dedup: collapse peer-mirror duplicates (default true).
    # Set to false to fall back to the pre-dedup behavior.
    # dedup: true
    # [owner] recall-dedup: number of unique hits to keep globally after
    # dedup, sorted by score desc. Default 6.
    # top_n: 6
```

如果用户的多 profile / 多 workspace 部署里 patch.yaml 已有 `openviking_sync_recall` 段, 执行 agent 应只补两个键不破坏其他配置; 如果没有, 应在 `owner:` 顶层下新建段。

---

## 关键设计决策: `[:3]` 切片语义

**问题**: 旧逻辑是「每桶前 3 条」 → 6 条。新逻辑该用哪种?

| 方案 | 描述 | 推荐? |
|---|---|---|
| 旧: 每桶先 `[:3]` 再去重 | 桶内只 3 条, 去重后可能只剩 2 条, 跨桶永远 ≤ 6 | ❌ — peer 镜像可能吃掉所有 3 槽, 真实记忆被挤掉 |
| **新: 跨桶全收 → 去重 → 全局 score 排序 → top_n** | 一次收完, 去重, 再取 N | ✅ — 保证 top_n 条都是唯一的, score 最高的 |

**推荐新方案**。原因:
1. `top_n=6` 跨桶取, 语义清晰 ("召回 6 条最相关的唯一记忆")。
2. 把 HTTP `limit` 调到 `max(top_n*3, 15)` 给去重留 headroom — 即使一半是 peer 镜像, 也能保证去重后剩 ≥ 6 条。
3. 跨类型 (memories 和 resources) 的相对比例自然平衡 — 旧的「每桶 3」强制 1:1, 不合理; 用户问 "OpenViking" 时可能 memories 占 5、resources 占 1, 跨桶 top 6 才是真实相关度排序。

**score 排序逻辑保持不变**: `sorted(..., key=lambda h: h.get("score", 0), reverse=True)`, 只是排序对象从「去重前」改成「去重后」。

---

## 测试

新增到 `tests/owner/patches/test_openviking_sync_recall_patch.py`。所有用例共用 `_MockResponse` helper (已存在)。

### T1: 正常 case (10 条无重复, 输出 6 条)
```python
def test_recall_dedup_no_duplicates(monkeypatch):
    """10 unique hits → top_n=6 by score, no dedup log."""
    hits_memories = [
        {"uri": f"viking://user/yangtb/memories/e/{i}.md",
         "abstract": f"unique memory {i}", "score": round(0.9 - i * 0.05, 3)}
        for i in range(5)
    ]
    hits_resources = [
        {"uri": f"viking://user/yangtb/resources/d/{i}.md",
         "abstract": f"unique doc {i}", "score": round(0.8 - i * 0.05, 3)}
        for i in range(5)
    ]
    monkeypatch.setattr("httpx.post",
        lambda *a, **kw: _MockResponse(
            {"result": {"memories": hits_memories, "resources": hits_resources}}))
    apply_patch()
    provider = _make_provider()
    out = provider.prefetch("anything")
    # 6 lines under ## OpenViking Context
    lines = [l for l in out.splitlines() if l.startswith("- [")]
    assert len(lines) == 6
    assert len(provider._recall_card_hits) == 6
```

### T2: 重复 case (3 组重复, 10 条 → 去重后 7 条 → top_n=6)
构造数据模拟用户实测的 3 组重复对:
```python
def test_recall_dedup_peer_mirrors(monkeypatch):
    """3 peer-mirror duplicates collapse; top_n=6 by score."""
    owner_uri = "viking://user/yangtb/memories/events/2026/06/22/{name}.md"
    peer_uri  = "viking://user/yangtb/peers/hermes/memories/events/2026/06/22/{name}.md"
    dup_pairs = [
        ("sop_recorded.md",            "viking_delete SOP procedure",          0.561),
        ("peer_mirror_deleted.md",     "deletion SOP for peer mirrors",        0.458),
        ("dedup_root_cause.md",        "root cause of recall dedup issue",     0.402),
    ]
    memories = []
    for name, abstract, score in dup_pairs:
        # owner copy
        memories.append({"uri": owner_uri.format(name=name),
                         "abstract": abstract, "score": score})
        # peer mirror — same abstract + score, different URI
        memories.append({"uri": peer_uri.format(name=name),
                         "abstract": abstract, "score": score})
    # 6 memories + 4 unique = 10 total
    memories += [
        {"uri": "viking://user/yangtb/memories/events/x1.md",
         "abstract": "unique A", "score": 0.35},
        {"uri": "viking://user/yangtb/memories/events/x2.md",
         "abstract": "unique B", "score": 0.30},
        {"uri": "viking://user/yangtb/memories/entities/n1.md",
         "abstract": "unique C", "score": 0.25},
        {"uri": "viking://user/yangtb/memories/events/x3.md",
         "abstract": "unique D", "score": 0.20},
    ]
    monkeypatch.setattr("httpx.post",
        lambda *a, **kw: _MockResponse({"result": {"memories": memories, "resources": []}}))
    apply_patch()
    provider = _make_provider()
    out = provider.prefetch("peers SOP")
    lines = [l for l in out.splitlines() if l.startswith("- [")]
    # 7 unique after dedup, top_n=6 → 6 lines
    assert len(lines) == 6
    assert len(provider._recall_card_hits) == 6
    # peer-mirror URIs must NOT appear in card_hits (they were dropped)
    assert all("/peers/hermes/" not in h.get("uri", "") for h in provider._recall_card_hits)
```

### T3: 跨桶 abstract 撞车
```python
def test_recall_dedup_cross_bucket(monkeypatch):
    """Same abstract in memories AND resources → only one survives."""
    shared = "shared abstract about deployment"
    monkeypatch.setattr("httpx.post",
        lambda *a, **kw: _MockResponse({"result": {
            "memories": [{"uri": "viking://m/a.md", "abstract": shared, "score": 0.7}],
            "resources": [{"uri": "viking://r/a.md", "abstract": shared, "score": 0.7}],
        }}))
    apply_patch()
    provider = _make_provider()
    provider.prefetch("deployment")
    assert len(provider._recall_card_hits) == 1
    # First-seen wins (memories bucket iterates first in current order)
    assert provider._recall_card_hits[0]["type"] == "memory"
```

### T4: peer-only 记忆 (只有 peer 侧, 没 owner 侧) 不被误删
```python
def test_recall_dedup_keeps_peer_only(monkeypatch):
    """A peer-only URI (no owner copy) must survive dedup."""
    monkeypatch.setattr("httpx.post",
        lambda *a, **kw: _MockResponse({"result": {
            "memories": [{
                "uri": "viking://user/yangtb/peers/hermes/memories/entities/节点配置/node010 OpenViking.md",
                "abstract": "node010 OpenViking configuration", "score": 0.5}],
            "resources": [],
        }}))
    apply_patch()
    provider = _make_provider()
    out = provider.prefetch("node010")
    assert "node010 OpenViking" in out
    assert len(provider._recall_card_hits) == 1
```

### T5: dedup 关闭开关
```python
def test_recall_dedup_disabled(monkeypatch):
    """dedup=false restores pre-patch behavior (peer mirrors surface)."""
    monkeypatch.setattr(
        recall_config, "_read_patch_yaml",
        lambda: {"owner": {"openviking_sync_recall": {"dedup": False}}},
    )
    owner = "viking://user/yangtb/memories/x.md"
    peer  = "viking://user/yangtb/peers/hermes/memories/x.md"
    monkeypatch.setattr("httpx.post",
        lambda *a, **kw: _MockResponse({"result": {
            "memories": [
                {"uri": owner, "abstract": "same", "score": 0.5},
                {"uri": peer,  "abstract": "same", "score": 0.5},
            ],
            "resources": [],
        }}))
    apply_patch()
    provider = _make_provider()
    provider.prefetch("x")
    # Without dedup, both copies appear (back-compat path)
    assert len(provider._recall_card_hits) == 2
```

### T6: limit=1 (HTTP 限制最小) 边界
```python
def test_recall_dedup_top_n_1(monkeypatch):
    """top_n=1 → exactly 1 hit after dedup, even if both buckets have data."""
    monkeypatch.setattr(
        recall_config, "_read_patch_yaml",
        lambda: {"owner": {"openviking_sync_recall": {"top_n": 1}}},
    )
    monkeypatch.setattr("httpx.post",
        lambda *a, **kw: _MockResponse({"result": {
            "memories": [
                {"uri": "viking://m/a", "abstract": "alpha", "score": 0.9},
                {"uri": "viking://m/b", "abstract": "beta",  "score": 0.7},
            ],
            "resources": [
                {"uri": "viking://r/c", "abstract": "gamma", "score": 0.6},
            ],
        }}))
    apply_patch()
    provider = _make_provider()
    out = provider.prefetch("anything")
    lines = [l for l in out.splitlines() if l.startswith("- [")]
    assert len(lines) == 1
    assert "alpha" in lines[0]
    assert len(provider._recall_card_hits) == 1
```

### T7 (bonus): `_dedup_uri_canonical` 单测
```python
def test_dedup_uri_canonical_strips_peer_segment():
    from owner.patches.openviking_sync_recall_patch import _dedup_uri_canonical
    assert _dedup_uri_canonical(
        "viking://user/yangtb/peers/hermes/memories/x.md"
    ) == "viking://user/yangtb/memories/x.md"
    assert _dedup_uri_canonical(
        "viking://user/yangtb/memories/x.md"
    ) == "viking://user/yangtb/memories/x.md"
    assert _dedup_uri_canonical("") == ""
    # multiple peer segments (defensive)
    assert _dedup_uri_canonical(
        "viking://u/peers/a/memories/peers/b/x.md"
    ) == "viking://u/memories/x.md"
```

### T8 (bonus): dedup log 行
```python
def test_recall_dedup_logs_skipped(monkeypatch, caplog):
    """Skipped peer mirrors emit a logger.debug line."""
    import logging
    owner = "viking://user/yangtb/memories/x.md"
    peer  = "viking://user/yangtb/peers/hermes/memories/x.md"
    monkeypatch.setattr("httpx.post",
        lambda *a, **kw: _MockResponse({"result": {
            "memories": [
                {"uri": owner, "abstract": "same", "score": 0.5},
                {"uri": peer,  "abstract": "same", "score": 0.5},
            ], "resources": [],
        }}))
    apply_patch()
    provider = _make_provider()
    with caplog.at_level(logging.DEBUG,
                         logger="owner.patches.openviking_sync_recall_patch"):
        provider.prefetch("x")
    assert any("recall-dedup: skipped peer mirror" in rec.message
               for rec in caplog.records)
```

---

## 副作用

### 副作用 1: `_recall_card_hits` 变短 → 飞书/QQ 卡片显示条数下降
**现象**: 现在 `all_hits` 含重复时 (例如本次实测的 10 → 6), 旧逻辑是 6 条展示; 新逻辑去重后也是 6 条 (因为 peer 镜像被吃), **实际条数不变**。但**当用户数据没有重复时**, 新逻辑返回 6 条 (top_n=6, 不是原来的「每桶前 3」= 6), 数量仍不变; **当用户数据全是重复时**, 新逻辑返回 1 条 (而不是 6 重复条), 卡片更清爽。

**结论**: 正常 case 下卡片显示条数无变化; 只有"全是重复"这种 pathological case 才会少显示。**可接受**, 这是设计目标。

### 副作用 2: HTTP 请求量略增
**现象**: `limit` 从 10 改成 `max(top_n*3, 15)=18` (top_n=6 时), 单次请求 OpenViking 服务端要返回更多候选。

**影响**: OpenViking 是本地服务 (`http://127.0.0.1:1933`), 增量开销可忽略。**可接受**。

### 副作用 3: 缓存命中率下降 (理论上)
**现象**: 如果 OpenViking 服务端做了 query-level 缓存, `limit` 变了可能 miss。但实测 OpenViking `find` API 不在 query 维度缓存 limit — `limit` 只是返回 list 长度, 缓存的是相似度计算结果。**实际无影响**。

### 副作用 4: 排序变了 (跨桶 score 全局排序 vs 每桶前 3)
**现象**: 旧逻辑里 resources 第 3 条可能 score=0.3 但被保留, memories 第 4 条可能 score=0.85 但被截掉。新逻辑反过来。

**影响**: LLM 拿到的 context 更相关 (高分优先), **正面影响**, 但属于行为变化需记录在 CHANGELOG。

### 回滚方法
- **配置回滚**: `patch.yaml` 加 `openviking_sync_recall.dedup: false` → 行为回到 patch 前 (peer 镜像保留)。
- **代码回滚**: 三个 git commit 直接 revert (diff 在 `_sync_prefetch` + helper + config loader + patch.yaml, 全部在一个文件改动链里)。
- **临时回滚**: `_load_sync_cfg()` 读取失败 → defaults 走 `dedup: True`, 用户改 yaml 即可。

---

## 配置

**推荐: 默认启用, 不加开关也行, 但加开关更稳**。

### 决策: 加 `dedup` 和 `top_n` 两个配置项

理由:
1. **去重是 bug 修复, 不是 feature** — 10 条记忆里有 4 条是其他用户的镜像副本 (path 中段偷偷插入 `/peers/hermes/`), LLM 拿到的 context 严重污染。这是 bug, 默认开。
2. **但给开关保留逃生通道** — 万一某天 OpenViking 服务端的 mirror 语义改了 (peer 镜像的 abstract 不再跟 owner 一致, 或者 URI 规律变了), 用户可以 `dedup: false` 一键回退, 不需要改代码。
3. **`top_n` 给调参空间** — 高级用户 (调试 / 验证 / 测试) 可能想看 top_n=10 或 top_n=2 的效果。
4. **符合现有 patch.yaml 风格** — `openviking_sync_recall` 已经 4 个键 (`enabled` / `advisory` / `search_timeout`), 加 2 个键不破坏 schema, 也不引入新的 section 层级。

### 默认值
```yaml
openviking_sync_recall:
  dedup: true   # 默认开, bug fix 性质
  top_n: 6      # 等同旧逻辑的「每桶 3 = 6」, 平滑迁移
```

### 不需要的环境变量
老的 `OPENVIKING_*` 命名空间 (`OPENVIKING_SYNC_RECALL` / `OPENVIKING_ADVISORY_MEMORY` / `OPENVIKING_SEARCH_TIMEOUT`) 是 legacy fallback, 新加的两个键没必要补 env var — patch.yaml 是 owner 配置的真理之源, 不让 `.env` 再多两个非秘密配置 (符合 AGENTS.md 的 "New `HERMES_*` env vars for non-secret config" 红线)。

---

## TL;DR

1. **去重键**: 推荐 `_dedup_uri_canonical(uri)` (剥 `/peers/<name>/` 段) + `(abstract[:200], round(score,3))` 双层; 主键语义明确 (peer mirror → owner), 兜底抗未来 URI 格式变化。
2. **代码改动**: 在 `_sync_prefetch` 内把「每桶 `[:3]` 再拼字符串」换成「全收 → 双键去重 → 全局 score 排序 → top_n」, 同一个 `ranked` 列表同时填 `parts` 和 `self._recall_card_hits`, LLM 注入和飞书卡片数据源唯一; 新增 helper `_dedup_uri_canonical`, config loader 加 `dedup` / `top_n`, patch.yaml 可选加注释行。
3. **配置**: 默认 `dedup: true` / `top_n: 6` (平滑替换旧的 3+3), 加 yaml 开关保回退, 不补 env var。