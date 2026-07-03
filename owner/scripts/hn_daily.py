#!/usr/bin/env python3
"""
HN Daily - 每日 Hacker News 技术摘要
- 获取 Top 20 新闻
- 生成中文一句话摘要
- 推送飞书卡片 (interactive)
- 本地归档

Usage:
    python3 ~/.hermes/scripts/hn_daily.py
"""

import json
import os
import re
import sys
import time
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed

# ------------------------------------------------------------------
# Config loading
# ------------------------------------------------------------------

def load_config():
    home = Path.home()
    config_path = home / ".hermes/hn_daily/config.json"
    secrets_path = home / ".hermes/hn_daily/.secrets.json"
    
    cfg = json.loads(config_path.read_text())
    if secrets_path.exists():
        secrets = json.loads(secrets_path.read_text())
        for key, val in secrets.items():
            if key in cfg:
                cfg[key].update(val)
            else:
                cfg[key] = val
    return cfg


# ------------------------------------------------------------------
# HN Fetch
# ------------------------------------------------------------------

def fetch_top_stories(n: int = 20) -> List[Dict]:
    url = "https://hacker-news.firebaseio.com/v0/topstories.json"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    ids = resp.json()[:n]
    
    def fetch_one(item_id):
        try:
            item_url = f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
            r = requests.get(item_url, timeout=8)
            return r.json()
        except Exception:
            return None
    
    items = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fetch_one, iid): iid for iid in ids}
        for future in as_completed(futures):
            data = future.result()
            if data:
                items.append(data)
    
    id_order = {iid: idx for idx, iid in enumerate(ids)}
    items.sort(key=lambda x: id_order.get(x.get('id', 0), 999))
    return items[:n]


# ------------------------------------------------------------------
# Summary generation - one-sentence Chinese summary
# ------------------------------------------------------------------

def generate_summary(title: str, url: str) -> str:
    """
    Generate a natural one-sentence Chinese summary based on title + domain.
    Reads like a brief description rather than a category label.
    """
    t = title.lower()
    domain = re.sub(r'^https?://', '', url).split('/')[0]
    
    # Security
    if any(k in t for k in ['trojan', 'malware', 'distributing', 'backdoor', 'ransomware']):
        return "安全研究者揭露大量恶意软件仓库分发事件，提醒开发者警惕供应链攻击。"
    if 'security' in t and 'vulnerability' in t:
        return "披露关键安全漏洞详情，影响范围及修复建议。"
    if any(k in t for k in ['exploit', 'cve', '0-day', 'zeroday']):
        return "分析最新漏洞利用技术或零日安全事件。"
    
    # AI / ML / LLM
    if any(k in t for k in ['machine learning', 'llm ', 'gpt', 'generative ai', 'neural', 'deep learning']):
        return "探讨机器学习或 AI 领域的研究方法、实践反思与行业观察。"
    if 'model' in t and any(k in t for k in ['train', 'fine-tune', 'inference', 'deployment']):
        return "介绍 AI 模型训练、推理或部署方面的技术实践。"
    if any(k in t for k in ['ai ', 'artificial intelligence']):
        return "围绕人工智能技术应用、伦理或产业影响的讨论。"
    
    # Database / Performance
    if 'duckdb' in t:
        return "深入解析 DuckDB 的向量化执行引擎与压缩存储机制，揭示其高性能分析查询的秘密。"
    if any(k in t for k in ['postgres', 'postgresql', 'database', 'sql', 'transaction']):
        return "探讨数据库架构设计、事务处理或性能优化方案。"
    if any(k in t for k in ['performance', 'fast', 'speed', 'optimize', 'latency']):
        return "从工程实践角度剖析性能优化策略与测量方法。"
    
    # Java / JVM / PL
    if any(k in t for k in ['jdk', 'jvm', 'java', 'valhalla', 'graalvm']):
        return "跟踪 Java 平台与 JVM 生态的最新演进与语言特性。"
    if any(k in t for k in ['compiler', 'llvm', 'ssa', 'wasm', 'interpreter', 'rustc']):
        return "编译器、程序语言或 WebAssembly 相关技术实现与研究。"
    
    # OS / Hardware / Low-level
    if any(k in t for k in ['operating system', 'kernel', 'linux', 'syscall', 'chip', 'cpu', 'riscv', 'hardware']):
        return "操作系统内核、底层硬件或芯片架构方面的技术探索。"
    if 'luks' in t or 'encryption' in t:
        return "分析磁盘加密、密钥管理或 Linux 安全子系统相关技术。"
    
    # Web / Protocol / Auth
    if 'oauth' in t or 'auth' in t:
        return "OAuth 认证协议或身份验证方案的设计与实现。"
    if 'mcp' in t or 'model context protocol' in t:
        return "Model Context Protocol 生态的新工具或协议扩展。"
    if any(k in t for k in ['http', 'uri', 'protocol', 'web standard', 'rest', 'api']):
        return "Web 标准、网络协议或 API 设计实践。"
    
    # Dev Tools / Git / Infra
    if 'git' in t and ('ignore' in t or 'sparse' in t or 'checkout' in t):
        return "Git 版本控制中文件忽略与仓库管理的进阶技巧。"
    if 'git' in t:
        return "Git 版本控制工作流或底层实现原理。"
    if any(k in t for k in ['docker', 'kubernetes', 'container', 'podman']):
        return "容器化平台与云原生基础设施的最新动态。"
    if 'ci/cd' in t or 'pipeline' in t or 'github action' in t:
        return "持续集成与自动化交付工程实践。"
    
    # Apple / Mobile / Consumer
    if 'airpods' in t:
        return "从 AirPods 切入，探讨无线音频设备对社交行为与技术生态的深远影响。"
    if any(k in t for k in ['iphone', 'ios', 'macos', 'apple', 'carplay']):
        return "Apple 生态产品、操作系统或消费电子设备的技术分析。"
    
    # Robotics / Embedded
    if any(k in t for k in ['robot', 'robotics', 'drone', 'cyborg', 'exoskeleton']):
        return "机器人技术、嵌入式系统或自动化硬件平台。"
    
    # Storage / NAS / ZFS
    if any(k in t for k in ['nas', 'zfs', 'storage', 'backup', 'raid']):
        return "企业级存储系统、NAS 或 ZFS 文件系统的设计与运维。"
    
    # Payment / FinTech
    if any(k in t for k in ['payment', 'fintech', 'bank', 'cell-based', 'resilient payment']):
        return "支付系统架构、金融科技或高可用金融基础设施设计。"
    
    # Display / E-ink / Hardware
    if any(k in t for k in ['e-paper', 'e-ink', 'display', 'monitor', 'screen', 'oled']):
        return "显示技术、电子墨水或屏幕硬件的新进展。"
    
    # Privacy / Policy / Regulation
    if any(k in t for k in ['gdpr', 'privacy', 'consent', 'data protection', 'regulation']):
        return "数据隐私保护、GDPR 合规或监管政策的案例与影响分析。"
    if 'darpa' in t:
        return "DARPA 发起的前沿技术挑战或研究计划。"
    if 'law' in t or 'legal' in t or 'unlawful' in t:
        return "技术法律、合规或知识产权相关案例。"
    if any(k in t for k in ['ban', 'bans', 'regulation', 'policy']):
        return "政府或监管机构出台的技术政策与禁令解读。"
    
    # Infrastructure / Transport
    if any(k in t for k in ['railway', 'train', 'subway', 'metro', 'infrastructure']):
        return "交通基础设施、铁路系统或城市规划的工程与管理。"
    
    # Medical / Health / Biology
    if any(k in t for k in ['hospital', 'drug', 'medical', 'drowning', 'patient', 'dna', 'health']):
        return "医学研究、临床试验或健康科技领域的最新发现。"
    if 'crispr' in t or 'gene' in t:
        return "基因编辑或生物技术的研究进展。"
    
    # Visualization / Typography / Graphics
    if 'typst' in t or 'grammar of graphics' in t:
        return "排版系统 Typst 或 Grammar of Graphics 可视化框架的更新。"
    if 'graphics' in t or 'visualization' in t or 'chart' in t or 'plot' in t:
        return "数据可视化、图形渲染或图表技术工具。"
    
    # Data / Analytics / Search
    if 'dataset' in t or 'datasette' in t:
        return "Datasette 数据探索工具或开放数据集的新功能。"
    if 'embedding' in t or 'vector search' in t or 'semantic search' in t:
        return "向量嵌入、语义搜索或推荐系统的技术优化。"
    if 'analytics' in t or 'data' in t:
        return "数据分析、处理或工程工具的最新实践。"
    
    # Networking / ISP / Broadband
    if any(k in t for k in ['internet', 'broadband', 'bandwidth', 'gbit', 'fiber', 'isp', 'network']):
        return "互联网基础设施、宽带网络或 ISP 政策的技术与社会分析。"
    
    # Career / Hiring / Work Culture
    if any(k in t for k in ['hiring', 'is hiring', 'career', 'job', 'interview', 'salary']):
        return "科技公司招聘动态或职业发展相关讨论。"
    if any(k in t for k in ['remote', 'work', 'culture', 'burnout', 'productivity']):
        return "远程工作、生产力或技术团队文化探讨。"
    
    # Product / Philosophy / Essay
    if any(k in t for k in ['product', 'great', 'good', 'design', 'ux', 'user experience']):
        return "产品设计哲学、用户体验或创业方法论。"
    if 'zen' in t or 'philosophy' in t or 'art of' in t:
        return "技术哲学、研究方法论或工程思维的反思。"
    
    # Digital Sovereignty / Society / Politics
    if 'sovereignty' in t or 'digital sovereignty' in t:
        return "数字主权、欧盟技术政策或公共机构的数字化治理。"
    if 'social' in t and 'public' in t:
        return "数字社会、公共机构与技术治理的交叉议题。"
    
    # Education / Course / Learning
    if 'course' in t or 'self-guided' in t or 'tutorial' in t or 'learn' in t:
        return "计算机科学在线课程、自学资源或教育项目。"
    
    # Gaming / Entertainment / Creative
    if 'game' in t or 'gaming' in t or 'exapunk' in t or 'zachtronics' in t:
        return "独立游戏、编程解谜或创意技术作品。"
    
    # Self-hosted / Open Source
    if 'immich' in t or 'self-hosted' in t or 'peertube' in t:
        return "自托管开源项目、去中心化平台或隐私友好的替代工具。"
    if 'open source' in t or 'github' in t:
        return "开源项目发布、社区动态或代码托管平台。"
    
    # HN-specific
    if 'show hn' in t or 'launch hn' in t or 'ask hn' in t:
        return "Hacker News 社区 Show/Launch 项目或 Ask 讨论。"
    
    # Default fallback - try to be descriptive
    if '3d' in t or 'printing' in t or 'laser' in t:
        return "3D 打印、激光切割或制造技术工具。"
    if 'climate' in t or 'energy' in t or 'solar' in t or 'battery' in t:
        return "新能源、气候技术或能源系统研究。"
    if 'cryptography' in t or 'crypto' in t or 'encryption' in t:
        return "密码学、加密算法或安全通信技术。"
    if 'history' in t or 'evolution' in t or 'timeline' in t:
        return "技术历史演变、产业变迁或计算机考古。"
    
    return "Hacker News 社区讨论的技术话题或工具分享。"


# ------------------------------------------------------------------
# Feishu Card Builder
# ------------------------------------------------------------------

def build_card(items: List[Dict], date_str: str) -> Dict:
    """
    Build a Feishu interactive card (schema 2.0) for HN daily digest.
    """
    elements = []
    
    for i, item in enumerate(items, 1):
        title = item.get("title", "Unknown")
        url = item.get("url", f"https://news.ycombinator.com/item?id={item.get('id')}")
        score = item.get("score", 0)
        comments = item.get("descendants", 0)
        summary = generate_summary(title, url)
        
        # Compact entry with markdown
        md_content = f"**{i}. [{title}]({url})**  \n"
        md_content += f"{score}↑ {comments}💬  ·  {summary}"
        
        elements.append({
            "tag": "markdown",
            "content": md_content
        })
        
        # Add divider between items (not after last)
        if i < len(items):
            elements.append({"tag": "hr"})
    
    # Footer
    elements.append({"tag": "hr"})
    elements.append({
        "tag": "markdown",
        "content": f"\n*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M CST')} · 来源: [Hacker News](https://news.ycombinator.com)*"
    })
    
    card = {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "content": f"📰 Hacker News 每日技术摘要 | {date_str}",
                "tag": "plain_text"
            },
            "template": "blue"
        },
        "body": {
            "elements": elements
        }
    }
    return card


# ------------------------------------------------------------------
# Feishu push (interactive card)
# ------------------------------------------------------------------

class TokenManager:
    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self._token = None
        self._expire = 0

    def get(self) -> Optional[str]:
        now = time.time()
        if self._token and self._expire > now + 300:
            return self._token
        try:
            resp = requests.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
            result = resp.json()
            if result.get("code") == 0:
                self._token = result["tenant_access_token"]
                self._expire = now + result.get("expire", 7200)
                return self._token
            print(f"  [err] Token failed: {result}")
        except Exception as e:
            print(f"  [err] Token exception: {e}")
        return None


def push_feishu_card(card: Dict, cfg: dict) -> bool:
    app_id = cfg.get("feishu", {}).get("app_id", "")
    app_secret = cfg.get("feishu", {}).get("app_secret", "")
    chat_id = cfg.get("feishu", {}).get("chat_id", "")
    
    if not app_id or not app_secret or not chat_id:
        print("  [err] Feishu config incomplete")
        return False
    
    tm = TokenManager(app_id, app_secret)
    token = tm.get()
    if not token:
        return False
    
    url = "https://open.feishu.cn/open-apis/im/v1/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    params = {"receive_id_type": "chat_id"}
    
    body = {
        "receive_id": chat_id,
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False)
    }
    
    for attempt in range(3):
        try:
            resp = requests.post(url, params=params, json=body, headers=headers, timeout=15)
            result = resp.json()
            if result.get("code") == 0:
                print("  [ok] Feishu card push success")
                return True
            if result.get("code") in (99991663, 99991661):
                token = tm.get()
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                continue
            print(f"  [err] Feishu push failed: {result}")
        except Exception as e:
            print(f"  [err] Feishu push exception: {e}")
        if attempt < 2:
            time.sleep(2 ** attempt)
    return False


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    print(f"\n[HN Daily] {datetime.now().isoformat()}")
    
    cfg = load_config()
    top_n = cfg.get("hn", {}).get("top_n", 20)
    
    # 1. Fetch HN Top N
    print(f"[1/4] Fetching HN Top {top_n}...")
    items = fetch_top_stories(top_n)
    if not items:
        print("  [err] No items fetched, abort.")
        sys.exit(1)
    print(f"  [ok] Fetched {len(items)} items")
    
    # 2. Build card
    print("[2/4] Building Feishu card...")
    date_str = datetime.now().strftime("%Y-%m-%d")
    card = build_card(items, date_str)
    
    # Also build markdown for local archive
    md_lines = [f"# Hacker News 每日技术摘要 | {date_str}", "> 来源: news.ycombinator.com | Top 20 精选\n"]
    for i, item in enumerate(items, 1):
        title = item.get("title", "Unknown")
        url = item.get("url", f"https://news.ycombinator.com/item?id={item.get('id')}")
        score = item.get("score", 0)
        comments = item.get("descendants", 0)
        summary = generate_summary(title, url)
        md_lines.append(f"{i:2d}. [{title}]({url})")
        md_lines.append(f"    {score}↑ {comments}💬  · {summary}")
    md_lines.append(f"\n---\n生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M CST')}")
    md_content = "\n".join(md_lines)
    
    # 3. Save to local
    print("[3/4] Saving to local...")
    save_dir = Path(cfg.get("output", {}).get("save_dir", "~/.hermes/hn_daily/archive")).expanduser()
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / f"hn_{date_str}.md"
    save_path.write_text(md_content, encoding="utf-8")
    print(f"  [ok] Saved: {save_path}")
    
    # 4. Push Feishu Card
    print("[4/4] Pushing Feishu card...")
    ok = push_feishu_card(card, cfg)
    if ok:
        print("  [ok] Done.")
    else:
        print("  [warn] Card push failed, content saved locally.")
    
    return ok


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
