# Viking Memory Quality Tools

只读分析 OpenViking 记忆质量，产出结构化报告，供后续治理流程使用。

## 目标

| 分析项 | 说明 |
|--------|------|
| **非中文** | 默认检测 pt/es/it/fr/de 污染（中文占比低）；英文需 `--include-english` |
| **近相似** | 用 OpenViking 已存 dense vector 做余弦相似度；**排除** user↔peer 完全镜像 |

**不做**：自动翻译、自动合并、删除写入（fix 入口仅汇总待办）。

## 连接配置

只从 Hermes 环境读取：

1. 进程环境变量 `OPENVIKING_*`
2. `$HERMES_HOME/.env`（默认 `~/.hermes/.env`）

需要：

```bash
OPENVIKING_ENDPOINT=http://127.0.0.1:1933
OPENVIKING_API_KEY=...
OPENVIKING_USER=yangtb
OPENVIKING_ACCOUNT=default   # optional
OPENVIKING_AGENT=hermes      # optional, peer id
```

不读取 `~/.openviking/ov.conf` / `ovcli.conf`，不做 admin 换 key。

## 入口

```bash
# 健康检查
python3 scripts/viking-memory-quality/viking_memory.py doctor

# 完整分析（推荐人工/流水线）
python3 scripts/viking-memory-pipeline.py --threshold 0.85
python3 scripts/viking-memory-pipeline.py --output /tmp/viking-report.json

# Cron 友好：无问题时静默；有问题时 stdout JSON
python3 scripts/viking-memory-quality-scan.py --json

# 仅近相似
python3 scripts/viking-memory-dedup-scan.py --threshold 0.85

# 待办汇总（不写库）
python3 scripts/viking-memory-fix.py --report /tmp/viking-report.json
```

## 报告要点

- `inventory.exact_mirrors_marked`：内容完全一致的 user/peer 镜像对数（结构双写，不当作近相似）
- `non_chinese` / `tier1.items`：非中文候选项
- `similar_pairs` / `tier2.items`：语义近重复对（已去掉 structural mirror）
- `has_work`：是否有后续可处理项

## 模块

| 文件 | 角色 |
|------|------|
| `viking_memory_lib.py` | 配置、HTTP 客户端、检测与扫描逻辑 |
| `viking-memory-quality/viking_memory.py` | 子命令 CLI（`scan` / `doctor`） |
| `viking-memory-quality-scan.py` | Cron 入口（兼容旧 `--json`） |
| `viking-memory-pipeline.py` | 统一报告（tier1+tier2） |
| `viking-memory-dedup-scan.py` | 仅近相似 |
| `viking-memory-fix.py` | 后续流程占位（默认不写） |

## 镜像 vs 近相似

OpenViking session commit 可能把 **同一条** event 落到：

- `viking://user/{u}/memories/events/...`
- `viking://user/{u}/peers/hermes/memories/events/...`

正文完全相同。工具会识别并排除这类 **structural mirror**，只报告不同路径/不同内容上的 **near-duplicate**。
