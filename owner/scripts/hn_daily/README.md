# HN Daily

每日 Hacker News 技术摘要脚本。

## 功能

- 获取 Hacker News Top N 条目
- 根据标题关键词匹配中文一句话摘要
- 推送飞书交互式卡片
- 本地 Markdown 归档

## 安装

```bash
mkdir -p ~/.hermes/hn_daily
cp owner/scripts/hn_daily/config.example.json ~/.hermes/hn_daily/config.json
# 编辑 config.json 填入非机密配置
cp owner/scripts/hn_daily/config.example.json ~/.hermes/hn_daily/.secrets.json
# 编辑 .secrets.json，只保留 feishu.app_id / app_secret / chat_id
```

## 运行

```bash
python3 owner/scripts/hn_daily.py
```

## 配置说明

| 配置项 | 说明 | 默认值 |
|---|---|---|
| `hn.top_n` | 获取条目数 | 20 |
| `hn.base_url` | HN Firebase API 地址 | `https://hacker-news.firebaseio.com/v0` |
| `http.top_stories_timeout` | 获取 ID 列表超时 | 15 |
| `http.item_timeout` | 单条详情超时 | 8 |
| `http.max_workers` | 并发数 | 8 |
| `http.retries` | 失败重试次数 | 3 |
| `http.backoff_base` | 重试退避基数 | 2.0 |
| `card.template` | 飞书卡片主题色 | `blue` |
| `card.timezone` | 卡片显示时区 | `CST` |
| `output.save_dir` | 本地归档目录 | `~/.hermes/hn_daily/archive` |
| `feishu.app_id` | 飞书应用 ID | 必填 |
| `feishu.app_secret` | 飞书应用密钥 | 必填 |
| `feishu.chat_id` | 飞书群聊 ID | 必填 |

## 自定义分类

复制 `owner/scripts/hn_daily/categories.json` 到 `~/.hermes/hn_daily/categories.json` 后编辑。每个规则支持：

- `mode: any`：命中任一关键词即匹配
- `mode: all`：命中所有 `keywords`，且命中 `also_any` 中任一关键词
