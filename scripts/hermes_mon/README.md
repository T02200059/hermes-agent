# Hermes 性能监控 (hermes_mon)

采集 Hermes 进程的 CPU/内存指标，按时间分片存储，支持自动聚合和截断。

## 数据架构

```
~/.hermes/local/hermes_mon/
├── raw/                     # 原始秒级数据，按小时分片
│   └── hermes_YYYYMMDD_HH.csv
│       每行: ts, pid, cpu_pct, mem_pct, rss_kb, vsz_kb
│
├── hourly/                  # 小时聚合（保留 30 天）
│   └── hourly_hermes_YYYYMMDD_HH.csv
│       每行: hour_ts, avg/max/min_cpu, avg/max/min_mem, ...
│
└── daily/                   # 天聚合（长期保留）
    └── daily.csv
        每行: day_ts, avg/max/min_cpu, avg/max/min_mem, ...
```

| 层级 | 粒度 | 保留期 | 来源 |
|------|------|--------|------|
| raw | 每 10 秒 | 24 小时 | collector 直接采集 |
| hourly | 每小时 | 30 天 | aggregator 压缩 raw |
| daily | 每天 | 永久 | aggregator 压缩 hourly |

## 组件说明

### `collector.py` — 采集器

- 每 10 秒由 launchd 触发执行
- 通过 `pgrep -f hermes` 查找所有 Hermes 进程
- 用 `ps -p PID -o '%cpu=,%mem=,rss=,vsz='` 采集（注意 macOS ps 不支持 `--no-headers`，用 `=` 号抑制标题）
- 追加写入 `~/.hermes/local/hermes_mon/raw/` 下当前小时的 CSV
- **零竞态：只写当前小时文件，不碰已过时的文件** — 采集器和聚合器永远不会同时操作同一文件

### `aggregator.py` — 聚合/截断器

- 每小时第 5 分钟由 launchd 触发执行
- **处理 raw 文件**：读取已关闭的小时文件 → 聚合为均值/最大/最小 → 追加到 `hourly/` → 超 24h 的删除
- **处理 hourly 文件**：超 30 天的 → 进一步聚合到天级 → 追加到 `daily/` → 删除原文件
- **零竞态保证**：只处理时间戳 < 当前小时的"已关闭"文件，采集器永远不会再碰这些文件

## launchd 安装

### 1. 注册服务

```bash
# 创建符号链接到 LaunchAgents 目录（或直接复制）
ln -sf ~/.hermes/hermes-agent/scripts/hermes_mon/com.yangtianbao.hermes-mon.collector.plist \
  ~/Library/LaunchAgents/com.yangtianbao.hermes-mon.collector.plist

ln -sf ~/.hermes/hermes-agent/scripts/hermes_mon/com.yangtianbao.hermes-mon.aggregator.plist \
  ~/Library/LaunchAgents/com.yangtianbao.hermes-mon.aggregator.plist
```

### 2. 加载启动

```bash
# 启动采集器（立即开始 + 每 10 秒触发）
launchctl load ~/Library/LaunchAgents/com.yangtianbao.hermes-mon.collector.plist
launchctl start com.yangtianbao.hermes-mon.collector

# 启动聚合器（每小时第 5 分钟自动运行）
launchctl load ~/Library/LaunchAgents/com.yangtianbao.hermes-mon.aggregator.plist
```

### 3. 常用管理命令

```bash
# 查看状态
launchctl list | grep hermes-mon

# 查看日志
tail -f /tmp/hermes-mon-collector.log
tail -f /tmp/hermes-mon-aggregator.log

# 手动触发一次聚合
launchctl start com.yangtianbao.hermes-mon.aggregator

# 停止并卸载
launchctl unload ~/Library/LaunchAgents/com.yangtianbao.hermes-mon.collector.plist
launchctl unload ~/Library/LaunchAgents/com.yangtianbao.hermes-mon.aggregator.plist
```

## 查看数据

```bash
# 最新采集的 raw 数据
tail ~/.hermes/local/hermes_mon/raw/hermes_$(date +%Y%m%d_%H).csv

# 小时聚合
cat ~/.hermes/local/hermes_mon/hourly/hourly_*.csv

# 天聚合
cat ~/.hermes/local/hermes_mon/daily/daily.csv

# 快速统计当前 CPU 趋势（最近 2 分钟）
tail -12 ~/.hermes/local/hermes_mon/raw/hermes_$(date +%Y%m%d_%H).csv | \
  awk -F',' 'NR>1{printf "%s  CPU: %5s%%  MEM: %5s%%  RSS: %s KB\n", strftime("%H:%M:%S",$1), $3, $4, $5}'
```

## 故障排查

- **数据目录不存在？** `collector.py` 和 `aggregator.py` 会在首次运行时自动创建
- **PID 找不到？** Hermes 进程未运行时，采集器无报错，CSV 中无新行
- **launchd 不执行？** 检查日志 `/tmp/hermes-mon-collector.log`，确认路径是否正确
- **想调整采集间隔？** 修改 plist 中 `<integer>10</integer>`，reload 即可
- **想调整保留期？** 修改 `aggregator.py` 顶部 `RAW_RETENTION_HOURS` 和 `HOUR_RETENTION_DAYS`
