# 飞书 auto-card 吞掉 `MEDIA:` 标签 — 根因与修复

> 类型：`fix(owner)` —— bug fix，定制功能已有条目（飞书 auto-card）的 bug 修复
> 状态：根因已验证（line-level + runtime 复现）
> 影响范围：飞书平台 + agent:end auto-card 路径（`display.platforms.feishu.streaming` 为 true 或 `force=True` 时）

---

## 1. 症状

用户在飞书 DM 发 `MEDIA:/tmp/free_pagecache.txt`，期望 Hermes 自动把该文件作为附件
投递。实际效果：`MEDIA:/tmp/free_pagecache.txt` 作为**纯文本**出现在飞书卡片消息里，
文件从未被上传。

## 2. 根因（已逐行验证）

`owner/feishu/agent_end.py::try_auto_card_on_end` 在 agent 返回响应后、`extract_media`
之前被 `gateway/run.py` 调用。当 auto-card 成功发送卡片后，发生如下数据流：

1. `gateway/run.py:10068-10069` 调用 `try_auto_card_on_end`，把 **整个 response**（含
   `MEDIA:` 标签）作为 `body_text` 传给 `try_auto_card`（`owner/feishu/auto_card.py:63`）。
2. `auto_card._evaluate_card_feasibility` 不识别 `MEDIA:` 标签，把整段文本（含标签）
   包进卡片 markdown 元素。**已用真实代码复现**：
   ```
   response = 'Here is the file you asked for:\nMEDIA:/tmp/free_pagecache.txt'
   plan = _evaluate_card_feasibility(response, footer='')
   # → can_use_card=True, needs_split=False, risks=()
   card = make_auto_card(response, footer='')
   # → card body 含 'MEDIA:/tmp/free_pagecache.txt' 字面文本
   ```
3. 卡片发送成功 → `try_auto_card_on_end` 设置 `agent_result["already_sent"]=True` 并
   返回 `("", "")`（`agent_end.py:72-74`）。
4. `gateway/run.py:10350-10356` 看到 `already_sent` 为真，进入「streaming 已投递文本，
   补投 MEDIA 文件」分支：
   ```python
   if agent_result.get("already_sent") and not agent_result.get("failed"):
       if response:                      # ← response 此时是 ""，整个分支跳过
           ...
           await self._deliver_media_from_response(response, event, _media_adapter)
   ```
   因为 `response` 已被清成 `""`，`_deliver_media_from_response` **从不执行**。
5. `_handle_message_with_agent` 在 10372/10374 行返回 `None` / `""`。
6. `gateway/platforms/base.py:4578` 的 `_process_message_background` 拿到假值 response，
   在 `4598-4611` 行的 `if response:` 守卫下整段 `extract_media → filter_media → 投递`
   流程被跳过。

**净效果**：`MEDIA:` 标签既没被 auto-card 路径提取，也没被 streaming 补投路径提取，
也没被正常 `_process_message_background` 路径提取。三道防线全部 miss。

### 与已有 streaming 路径的对照

streaming 模式下文本是流式发出去的，`run.py:10350` 这条「streaming 已发，补投 MEDIA」
的分支就是为这种情况设计的。auto-card 路径复用了同一个 `already_sent=True` 标记，导致
代码把它误当成 streaming 已投递；但 auto-card 实际把**完整文本**包进卡片发出去了（含
`MEDIA:` 标签），既没流式也没提取，所以补投分支拿到的是空字符串。

## 3. force 参数行为（已验证）

`try_auto_card` 的 `force=True`（`agent_end.py:65` 传入）：
- 跳过 `is_feishu_streaming_disabled()` 检查 → 即便飞书开着 streaming，agent:end 也会
  发卡片。
- 跳过 `len(formatted_text) <= threshold` 长度检查 → 短文本也包卡片。
- **不跳过** `threshold <= 0`（patch.yaml `feishu_card.auto_card_threshold` 显式 ≤ 0
  时禁用）和 feasibility 风险检测。

这解释了为什么短回复也会触发卡片（用户报告场景）。

## 4. 修复方案

**位置**：`owner/feishu/agent_end.py` 一个文件。`gateway/run.py` 不动（符合二次开发规范
P1：官方文件只做 import + 委托）。

**做法**：在把 response 交给 `try_auto_card` 之前，先调用 `runner._deliver_media_from_response`
把 `MEDIA:` 标签（以及裸路径）提取并投递掉，然后用**清理后**的文本去包卡片。

为什么复用 `_deliver_media_from_response`：
- 它是 gateway 里权威的「response → 附件」管线，已经做了 MEDIA 标签 + 裸路径的联合
  提取、图片/视频/语音/文档分流、`filter_media_delivery_paths` 安全校验、[[as_document]]
  / [[audio_as_voice]] 指令处理。
- 自己在 owner/ 里再写一遍等于复制 ~120 行 gateway 逻辑，sync upstream 时两边漂移。
- 复用 = 把网关当成「稳定 API」调用，owner 只多一条 ~10 行委托。

**顺序**：先投附件，后发卡片。理由：
- 卡片文本干净，`MEDIA:` 标签不会再泄漏到用户可见文本里。
- 哪怕附件投递失败（网络抖动），卡片照样能发出去，文本信息不丢；附件投递失败只丢文件
  不丢回复，符合既有 `_deliver_media_from_response` 的「失败只 warning」语义。

**返回值**：仍按现状返回 `("", "")` + `already_sent=True`，让下游 plain-text 路径照常
跳过（避免重复发文本）。`MEDIA:` 投递这一步已经在本函数里独立完成，不依赖下游。

## 5. 修复 diff（核心）

```python
# owner/feishu/agent_end.py
    adapter = runner.adapters.get(Platform.FEISHU)
    if adapter is None:
        return response, footer_line

    # [owner] auto-card: 提前抽出并投递 MEDIA: 标签 / 裸路径，否则整段文本
    # （含 MEDIA: 字面标签）会被包进卡片当成纯文本发出，文件永远不会被上传。
    # 复用 gateway 的 _deliver_media_from_response（权威管线：MEDIA 标签 + 裸路径、
    # 图片/视频/语音/文档分流、安全过滤、[[as_document]]/[[audio_as_voice]]）。
    # 投递失败只 warning 不 raise —— 卡片照发，文本信息不丢。
    try:
        cleaned_for_card = await runner._deliver_media_from_response_and_return_clean(
            response, event, adapter,
        )
        if cleaned_for_card is not None:
            # footer 拆分要用清理后的文本，避免 footer 检测失败
            response = cleaned_for_card
    except Exception as exc:
        logger.debug("auto-card pre-deliver media failed: %s", exc)
```

（注：`_deliver_media_from_response` 现有签名不返回清理后文本。下面 6.2 给两种接法。）

## 6. 实现细节

### 6.1 footer 拆分顺序

现状（`agent_end.py:57-61`）：
```python
body_text = response
footer_text = ""
if footer_line and response.endswith(footer_line):
    body_text = response[: -len(footer_line)].rstrip("\n")
    footer_text = footer_line
```

`extract_media` 会**删除**文本里的 `MEDIA:` 标签子串。如果 MEDIA 标签出现在 footer 之
前（常见情况），`response.endswith(footer_line)` 在清理后仍成立（尾部没动）。如果
MEDIA 标签碰巧出现在 footer 之后（极罕见，因为 footer 是后拼上去的），则不成立，footer
会被当成 body 的一部分渲染 —— 但这是良性退化（footer 仍是合法 markdown 文本），不阻塞
修复。修复后保持「先清理、后拆 footer」即可。

### 6.2 取清理后文本的两种接法

`_deliver_media_from_response(response, event, adapter)` 当前签名不返回清理后的文本
（内部丢弃了 `cleaned`）。两种接法：

**A. 在 owner/ 里调 `adapter.extract_media` 取清理文本，再用 gateway 投递（推荐）**

`extract_media` 是 `BasePlatformAdapter` 上的 `@staticmethod`，FeishuAdapter 直接继承。
我们先拿到清理后的文本，再交给 gateway 投递。gateway 那个方法内部会再做一次
`extract_media`，但因为它幂等（标签已经被剥光了，第二次扫不到），是安全的，且保证
`extract_images` / `extract_local_files` 那两道管线也照常跑。代价：一次重复扫描（response
文本通常很短，可忽略）。

**B. 在 `gateway/run.py` 给 `_deliver_media_from_response` 加一个返回清理文本的变体**

更干净但要动 gateway 官方文件（哪怕只是加一个 `return_cleaned=False` 形参 + `# [owner]`
标记 + 委托），不符合「最小侵入」精神。

**选 A**：纯 owner/ 改动，gateway 零改动，sync 时零冲突。重复扫描的代价可接受。

### 6.3 何时跳过提前投递

- `response` 为空：函数开头 `not response` 已 return，不会走到这里。
- adapter 无 `extract_media`：理论上不会发生（所有 BasePlatformAdapter 子类都有），仍
  加 `hasattr` 守卫做防御。
- platform 不是飞书：函数开头已 return。

## 7. 测试

新增 `tests/owner/test_feishu_agent_end_media.py`：

1. **核心用例**：`try_auto_card_on_end` 收到含 `MEDIA:<tmp file>` 的 response，验证：
   - 文件通过 `send_document` 被投递（mock adapter 记录调用）。
   - 卡片文本（`send_card` 的 card body）**不含** `MEDIA:` 字面串。
   - 返回值仍是 `("", "")` + `already_sent=True`（下游 plain-text 不重复发）。
2. **无附件回归**：response 不含 `MEDIA:` 标签时，行为与现状一致（卡片文本原样、不调
   `send_document`）。
3. **图片分流回归**：`MEDIA:<png>` 应该走 `send_multiple_images`，不走 `send_document`。

mock `runner`、`adapter`、`event`、`source`；不触网；只用 stdlib + pytest + unittest.mock。

## 8. v16 改动清单维护

按规范 §6.1，这是**已有功能（飞书 auto-card）的 bug fix**，不新增项目。在对应条目的
「相关 commit」后追加本次 commit 号，并补一句：

> `fix(owner): auto-card 前先抽出 MEDIA: 标签投递，避免文件被卡片吞掉`

## 9. 已检查的旁证

- `force=True` 确实跳过 threshold / streaming 检查（`auto_card.py:386-392`），不跳过
  `threshold<=0` 禁用和 feasibility 风险检测。
- `FeishuAdapter` 继承 `BasePlatformAdapter.extract_media`（staticmethod，`FeishuAdapter.extract_media is BasePlatformAdapter.extract_media` = True），且有
  `send_document` / `send_card` / `send_multiple_images` / `send_video` / `send_voice`。
- `_process_message_background`（`base.py:4598-4611`）确实以 `if response:` 为唯一守卫，
  response 为假值时整段跳过 `extract_media`。
