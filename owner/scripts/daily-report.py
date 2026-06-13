#!/usr/bin/env python3
"""
每日工作日报 - 飞书卡片版
查询过去24小时的有效Session，生成日报并发送飞书卡片
"""
import json
import os
import sys
import re
import requests
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# Hermes cron 以 root 运行，Path.home() 是 /var/root
_HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
DB_PATH = _HERMES_HOME / "state.db"

def format_number(num):
    """格式化数字"""
    if num >= 1000000:
        return f"{num/1000000:.1f}M"
    elif num >= 1000:
        return f"{num/1000:.1f}k"
    return str(num)

def query_recent_sessions(hours=24):
    """查询过去N小时的有效Session"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cutoff = (datetime.now() - timedelta(hours=hours)).timestamp()
    
    cursor.execute("""
        SELECT 
            id,
            title,
            started_at,
            ended_at,
            model,
            message_count,
            tool_call_count,
            input_tokens,
            output_tokens,
            api_call_count,
            source
        FROM sessions
        WHERE started_at > ?
        AND message_count > 3  -- 过滤短对话
        ORDER BY started_at DESC
    """, (cutoff,))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(r) for r in rows]

def generate_report(sessions):
    """生成日报文本（模仿原来的LLM prompt输出格式）"""
    if not sessions:
        return "## 过去24小时\n\n暂无有效Session数据"
    
    # 按来源分组
    by_source = {}
    for s in sessions:
        source = s['source'] or 'unknown'
        by_source.setdefault(source, []).append(s)
    
    lines = []
    lines.append("## 过去24小时技术日报")
    lines.append("")
    lines.append(f"**统计周期:** 过去24小时")
    lines.append(f"**Session数:** {len(sessions)}")
    lines.append(f"**总API调用:** {sum(s['api_call_count'] or 0 for s in sessions)} 次")
    lines.append(f"**总Token:** in={format_number(sum(s['input_tokens'] or 0 for s in sessions))}, out={format_number(sum(s['output_tokens'] or 0 for s in sessions))}")
    lines.append("")
    
    # Session列表（取前10个）
    lines.append("### 主要Session (Top 10)")
    lines.append("")
    for i, s in enumerate(sessions[:10], 1):
        title = s['title'] or '无标题'
        model = s['model'] or 'unknown'
        msg_count = s['message_count'] or 0
        api_calls = s['api_call_count'] or 0
        lines.append(f"{i}. **{title}**")
        lines.append(f"   - 模型: {model} | 消息: {msg_count} | API调用: {api_calls}")
    
    lines.append("")
    lines.append("### 按来源统计")
    lines.append("")
    for source, sess_list in sorted(by_source.items(), key=lambda x: len(x[1]), reverse=True):
        lines.append(f"- **{source}**: {len(sess_list)} sessions")
    
    return "\n".join(lines)

def text_to_card(text):
    """Convert report text to Feishu card JSON."""
    import re
    
    # 按段落分割
    paragraphs = re.split(r'\n\s*\n', text)
    
    elements = []
    h2_counter = 0
    h3_counter = 0
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        
        # 检测 ## 标题
        h2_match = re.match(r'^##\s+(.+)$', para)
        if h2_match:
            h2_counter += 1
            h3_counter = 0
            title_text = h2_match.group(1)
            para = f"**{h2_counter}. {title_text}**"
        
        # 检测 ### 标题
        h3_match = re.match(r'^###\s+(.+)$', para)
        if h3_match:
            h3_counter += 1
            title_text = h3_match.group(1)
            para = f"**{h2_counter}.{h3_counter} {title_text}**"
        
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": para}
        })
    
    if not elements:
        return None
    
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "📝 每日工作日报"},
            "template": "blue"
        },
        "elements": elements
    }
    return card

def send_feishu_card(card, chat_id=None):
    """Send Feishu card via lark_oapi.
    
    Args:
        card: Card JSON dict
        chat_id: Target chat_id. If None, reads from FEISHU_CHAT_ID env var.
                 Must be provided explicitly (no hardcoded defaults).
    """
    app_id = os.getenv("FEISHU_APP_ID")
    app_secret = os.getenv("FEISHU_APP_SECRET")
    
    # Resolve chat_id: parameter > environment variable
    if chat_id is None:
        chat_id = os.getenv("FEISHU_CHAT_ID")
    
    if not chat_id:
        print("❌ chat_id 未提供！请通过参数传入或设置 FEISHU_CHAT_ID 环境变量", file=sys.stderr)
        return False
    
    if not app_id or not app_secret:
        print("❌ FEISHU_APP_ID 或 FEISHU_APP_SECRET 未设置", file=sys.stderr)
        return False
    
    # Get token
    token_url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(token_url, json={"app_id": app_id, "app_secret": app_secret})
    data = resp.json()
    if data.get("code") != 0:
        print(f"❌ 获取token失败: {data}", file=sys.stderr)
        return False
    
    access_token = data["tenant_access_token"]
    
    # Send card
    send_url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "receive_id": chat_id,
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False)
    }
    
    resp = requests.post(send_url, headers=headers, json=payload)
    result = resp.json()
    
    if result.get("code") == 0:
        print(f"✅ 卡片发送成功！消息ID: {result['data']['message_id']}")
        return True
    else:
        print(f"❌ 发送失败: {result}", file=sys.stderr)
        return False

def main():
    print("🔍 查询过去24小时的Session...", file=sys.stderr)
    sessions = query_recent_sessions(24)
    
    print(f"📊 找到 {len(sessions)} 个有效Session", file=sys.stderr)
    
    print("📝 生成日报...", file=sys.stderr)
    report = generate_report(sessions)
    
    print(report)

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Daily work report with optional Feishu card sending')
    parser.add_argument('--card', action='store_true', help='Send as Feishu card')
    parser.add_argument('--chat-id', type=str, default=None, help='Feishu chat_id (overrides FEISHU_CHAT_ID env var)')
    args = parser.parse_args()
    
    if args.card:
        # Redirect stdout to capture main() output
        import io
        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()
        main()
        sys.stdout = old_stdout
        report_text = buffer.getvalue()
        
        card = text_to_card(report_text)
        if card:
            send_feishu_card(card, chat_id=args.chat_id)
        else:
            print("❌ 无法生成卡片", file=sys.stderr)
            sys.exit(1)
    else:
        main()
