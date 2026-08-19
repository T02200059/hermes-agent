#!/usr/bin/env python3
"""
Cron job health check script for Hermes Agent.

Analyzes the past 24 hours of cron job executions and reports:
- Failed jobs (last_status != ok or last_error != null)
- Jobs exceeding duration threshold (default 8 minutes)
- Delivery failures (last_delivery_error != null)
- node010 bifang-backup.sh cron status

Outputs structured JSON for the agent to format and send.
"""

import json
import os
import re
import subprocess
import sys
import base64
from datetime import datetime, timedelta
from pathlib import Path

# Configuration
DURATION_THRESHOLD_SECONDS = 480  # 8 minutes
HERMES_HOME = Path.home() / ".hermes"
JOBS_FILE = HERMES_HOME / "cron" / "jobs.json"
AGENT_LOG = HERMES_HOME / "logs" / "agent.log"

# node010 backup check config
NODE010_HOST = "node010"
NODE010_LOG = "/tmp/bifang-backup.log"
NODE010_ARCHIVE_DIR = "/data/ai/hermes-backup/bifang"
NODE010_CRON_PATTERN = "bifang-backup.sh"


def load_jobs() -> dict:
    """Load cron jobs configuration."""
    if not JOBS_FILE.exists():
        return {"jobs": []}
    with open(JOBS_FILE) as f:
        return json.load(f)


def parse_log_timestamp(line: str) -> datetime | None:
    """Parse timestamp from log line."""
    match = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
    if match:
        return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
    return None


def _line_has_today(line: str, today: str) -> bool:
    """True only when *line* carries today's date (YYYY-MM-DD or YYYYMMDD).

    Date-less lines are NOT treated as today: tail -30 can span multiple
    days on a low-frequency log, and a time-only "restore completed" is
    not evidence the restore ran today (P1-6).
    """
    compact_line = line.replace("-", "")
    compact_today = today.replace("-", "")
    return compact_today in compact_line


def interpret_restore_log(restore_log: str, today: str) -> tuple:
    """Classify a restore-log tail.

    Returns ``(today_restore_done, has_fail, last_done_line)``. The last
    matching event wins: a later FAIL after a completed line is a failure;
    a later completed line after an older FAIL is success — but only when
    that completed line is dated today.
    """
    last_event = None
    last_done_line = ""
    for line in restore_log.split("\n"):
        if "restore completed" in line:
            last_event = "done"
            last_done_line = line
        elif "FAIL" in line or "ERROR" in line:
            last_event = "fail"
    today_restore_done = last_event == "done" and _line_has_today(
        last_done_line, today
    )
    has_fail = last_event == "fail"
    return today_restore_done, has_fail, last_done_line


def scan_all_executions_once(cutoff: datetime) -> dict:
    """Scan agent.log once and group executions by job_id.

    Returns ``{job_id: {exec_id: {start, end, duration_seconds}}}``.
    """
    result: dict = {}
    if not AGENT_LOG.exists():
        return result

    _exec_re = re.compile(r"\[cron_([A-Za-z0-9_-]+)_\d+_\d+\]")
    with open(AGENT_LOG) as f:
        for line in f:
            ts = parse_log_timestamp(line)
            if ts is None or ts < cutoff:
                continue
            m = _exec_re.search(line)
            if not m:
                continue
            job_id = m.group(1)
            exec_id = m.group(0)[1:-1]
            per_job = result.setdefault(job_id, {})
            if exec_id not in per_job:
                per_job[exec_id] = {"start": ts, "end": ts}
            else:
                per_job[exec_id]["end"] = ts

    for per_job in result.values():
        for data in per_job.values():
            data["duration_seconds"] = int((data["end"] - data["start"]).total_seconds())

    return result


def _parse_sections(output: str) -> dict:
    """Parse === SECTION_NAME === delimited output into dict."""
    sections = {}
    current_section = None
    current_lines = []

    for line in output.split("\n"):
        if line.startswith("=== ") and line.endswith(" ==="):
            if current_section:
                sections[current_section] = current_lines
            current_section = line[4:-4]
            current_lines = []
        else:
            current_lines.append(line)
    if current_section:
        sections[current_section] = current_lines

    return sections


def check_node010_backup() -> dict:
    """
    Check node010 bifang-backup.sh cron job status via SSH.
    Returns a status dict for the report.
    """
    today = datetime.now().strftime("%Y%m%d")

    # Build remote script (base64 to avoid quote escaping issues)
    remote_script = f'''
CRON_ENTRY=$(crontab -l 2>/dev/null | grep -F "{NODE010_CRON_PATTERN}" || echo "__NO_CRON__")
echo "=== CRON ==="
echo "$CRON_ENTRY"

echo "=== LOG_TAIL ==="
tail -15 {NODE010_LOG} 2>/dev/null || echo "__NO_LOG_FILE__"

echo "=== TODAY_ARCHIVES ==="
ls -lt {NODE010_ARCHIVE_DIR}/hermes-{today}-*.tar.gz 2>/dev/null | head -3 || echo "__NO_ARCHIVES__"

echo "=== ALL_ARCHIVES ==="
ls -lt {NODE010_ARCHIVE_DIR}/hermes-*.tar.gz 2>/dev/null | head -3 || echo "__NO_ARCHIVES__"
'''

    encoded = base64.b64encode(remote_script.encode()).decode()

    try:
        result = subprocess.run(
            ["ssh", NODE010_HOST, f"echo {encoded} | base64 -d | bash"],
            capture_output=True,
            text=True,
            timeout=30
        )
    except subprocess.TimeoutExpired:
        return {
            "job_id": "node010-bifang-backup",
            "job_name": "node010 bifang-backup",
            "run_time": "-",
            "issue_type": "SSH超时",
            "error": "连接 node010 超时（30s），可能网络不通或 SSH agent 不可用",
            "duration_seconds": 0,
            "source": "remote"
        }
    except Exception as e:
        return {
            "job_id": "node010-bifang-backup",
            "job_name": "node010 bifang-backup",
            "run_time": "-",
            "issue_type": "检查失败",
            "error": f"SSH 执行异常: {str(e)[:120]}",
            "duration_seconds": 0,
            "source": "remote"
        }

    if result.returncode != 0:
        return {
            "job_id": "node010-bifang-backup",
            "job_name": "node010 bifang-backup",
            "run_time": "-",
            "issue_type": "SSH失败",
            "error": f"rc={result.returncode}: {(result.stderr or result.stdout).strip()[:120]}",
            "duration_seconds": 0,
            "source": "remote"
        }

    sections = _parse_sections(result.stdout)

    cron_text = "\n".join(sections.get("CRON", [])).strip()
    log_tail = "\n".join(sections.get("LOG_TAIL", [])).strip()
    today_archives = "\n".join(sections.get("TODAY_ARCHIVES", [])).strip()
    all_archives = "\n".join(sections.get("ALL_ARCHIVES", [])).strip()

    # Check 1: crontab entry exists
    if "__NO_CRON__" in cron_text or not cron_text:
        return {
            "job_id": "node010-bifang-backup",
            "job_name": "node010 bifang-backup",
            "run_time": "-",
            "issue_type": "crontab缺失",
            "error": "node010 上未找到 bifang-backup.sh 的 crontab 条目",
            "duration_seconds": 0,
            "source": "remote"
        }

    # Check 2: log file exists
    if "__NO_LOG_FILE__" in log_tail or not log_tail:
        return {
            "job_id": "node010-bifang-backup",
            "job_name": "node010 bifang-backup",
            "run_time": "-",
            "issue_type": "无日志",
            "error": f"{NODE010_LOG} 不存在，备份从未运行过",
            "duration_seconds": 0,
            "source": "remote"
        }

    # Check 3: today's archive exists
    if "__NO_ARCHIVES__" in today_archives or not today_archives:
        # No archive for today - check log for failure clues
        has_fail = "FAIL" in log_tail
        if has_fail:
            fail_line = next((l for l in log_tail.split("\n") if "FAIL" in l), "unknown")
            return {
                "job_id": "node010-bifang-backup",
                "job_name": "node010 bifang-backup",
                "run_time": "-",
                "issue_type": "失败",
                "error": fail_line.strip()[:150],
                "duration_seconds": 0,
                "source": "remote"
            }

        # Check if any archive exists at all
        if "__NO_ARCHIVES__" in all_archives or not all_archives:
            return {
                "job_id": "node010-bifang-backup",
                "job_name": "node010 bifang-backup",
                "run_time": "-",
                "issue_type": "从未成功",
                "error": "归档目录为空，备份从未成功完成",
                "duration_seconds": 0,
                "source": "remote"
            }

        # Has archives but not today - might not have run yet (before 05:00)
        return {
            "job_id": "node010-bifang-backup",
            "job_name": "node010 bifang-backup",
            "run_time": "-",
            "issue_type": "今日未运行",
            "error": f"今天 {today} 尚无备份归档，可能尚未到调度时间或启动失败",
            "duration_seconds": 0,
            "source": "remote"
        }

    # Check 4: today's archive exists - verify log shows ALL DONE
    has_done = "ALL DONE" in log_tail
    has_fail = "FAIL" in log_tail

    # Extract run time from log tail
    run_time = "-"
    for line in log_tail.split("\n"):
        time_match = re.search(r"(\d{2}:\d{2}:\d{2})", line)
        if time_match:
            run_time = time_match.group(1)
            break

    if has_done and not has_fail:
        return {
            "job_id": "node010-bifang-backup",
            "job_name": "node010 bifang-backup",
            "run_time": run_time,
            "issue_type": None,
            "error": None,
            "duration_seconds": 0,
            "source": "remote"
        }

    if has_fail:
        fail_line = next((l for l in log_tail.split("\n") if "FAIL" in l), "unknown")
        return {
            "job_id": "node010-bifang-backup",
            "job_name": "node010 bifang-backup",
            "run_time": run_time,
            "issue_type": "失败",
            "error": fail_line.strip()[:150],
            "duration_seconds": 0,
            "source": "remote"
        }

    # Archive exists but log tail is ambiguous
    return {
        "job_id": "node010-bifang-backup",
        "job_name": "node010 bifang-backup",
        "run_time": run_time,
        "issue_type": "状态不明",
        "error": "今日归档存在但日志无明确成功/失败标记，需人工确认",
        "duration_seconds": 0,
        "source": "remote"
    }


def check_damodel_211() -> dict:
    """
    Check 100.64.10.211 (damodel) cron status.
    Two chains:
    1. Backup: mysql_backup.sh every 3h -> /data/backup/mysql/
    2. Restore: restore.sh daily at 01:00 -> docker mysql-damodel
    """
    today = datetime.now().strftime("%Y%m%d")
    today_dashed = datetime.now().strftime("%Y-%m-%d")
    host = "100.64.10.211"
    log_path = "/data/ai/damodel/mysql/logs/restore.log"
    backup_dir = "/data/backup/mysql"
    cron_restore = "restore.sh"
    cron_backup = "mysql_backup.sh"

    # Build remote script
    remote_script = f'''
CRON_RESTORE=$(crontab -l 2>/dev/null | grep -F "{cron_restore}" || echo "__NO_CRON__")
CRON_BACKUP=$(grep -r "{cron_backup}" /etc/crontab /etc/cron.d/ 2>/dev/null | head -3 || echo "__NO_CRON__")
echo "=== CRON_RESTORE ==="
echo "$CRON_RESTORE"
echo "=== CRON_BACKUP ==="
echo "$CRON_BACKUP"

echo "=== RESTORE_LOG ==="
tail -30 {log_path} 2>/dev/null || echo "__NO_LOG__"

echo "=== TODAY_BACKUPS ==="
ls -lt {backup_dir} | grep "{today_dashed}" | head -5 || echo "__NO_TODAY__"

echo "=== ALL_BACKUPS ==="
ls -lt {backup_dir} | head -5 || echo "__NO_BACKUPS__"
'''

    encoded = base64.b64encode(remote_script.encode()).decode()

    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=no",
             "-o", "UserKnownHostsFile=/dev/null",
             f"root@{host}", f"echo {encoded} | base64 -d | bash"],
            capture_output=True, text=True, timeout=30
        )
    except subprocess.TimeoutExpired:
        return {
            "job_id": "damodel-211",
            "job_name": "211 damodel-restore",
            "run_time": "-",
            "issue_type": "SSH超时",
            "error": "连接 100.64.10.211 超时（30s）",
            "duration_seconds": 0,
            "source": "remote"
        }
    except Exception as e:
        return {
            "job_id": "damodel-211",
            "job_name": "211 damodel-restore",
            "run_time": "-",
            "issue_type": "检查失败",
            "error": f"SSH 执行异常: {str(e)[:120]}",
            "duration_seconds": 0,
            "source": "remote"
        }

    if result.returncode != 0:
        return {
            "job_id": "damodel-211",
            "job_name": "211 damodel-restore",
            "run_time": "-",
            "issue_type": "SSH失败",
            "error": f"rc={result.returncode}: {(result.stderr or result.stdout).strip()[:120]}",
            "duration_seconds": 0,
            "source": "remote"
        }

    sections = _parse_sections(result.stdout)
    cron_restore_text = "\n".join(sections.get("CRON_RESTORE", [])).strip()
    cron_backup_text = "\n".join(sections.get("CRON_BACKUP", [])).strip()
    restore_log = "\n".join(sections.get("RESTORE_LOG", [])).strip()
    today_backups = "\n".join(sections.get("TODAY_BACKUPS", [])).strip()
    all_backups = "\n".join(sections.get("ALL_BACKUPS", [])).strip()

    # Check 1: restore cron exists
    if "__NO_CRON__" in cron_restore_text or not cron_restore_text:
        return {
            "job_id": "damodel-211",
            "job_name": "211 damodel-restore",
            "run_time": "-",
            "issue_type": "crontab缺失(restore)",
            "error": "未找到 restore.sh 的 crontab 条目",
            "duration_seconds": 0,
            "source": "remote"
        }

    # Check 2: backup cron exists
    no_today_backup = ("__NO_TODAY__" in today_backups or not today_backups)
    if "__NO_CRON__" in cron_backup_text or not cron_backup_text:
        if no_today_backup:
            return {
                "job_id": "damodel-211",
                "job_name": "211 damodel-restore",
                "run_time": "-",
                "issue_type": "备份链路失效",
                "error": "mysql_backup.sh crontab 缺失 且 今天无备份归档",
                "duration_seconds": 0,
                "source": "remote"
            }
        else:
            return {
                "job_id": "damodel-211",
                "job_name": "211 damodel-restore",
                "run_time": "-",
                "issue_type": "crontab缺失(backup)",
                "error": "mysql_backup.sh 无 crontab，但今天仍有归档（可能已改 systemd 或手动触发）",
                "duration_seconds": 0,
                "source": "remote"
            }

    # Check 3: backup cron exists but no today backup
    if no_today_backup:
        if "__NO_BACKUPS__" in all_backups or not all_backups:
            return {
                "job_id": "damodel-211",
                "job_name": "211 damodel-restore",
                "run_time": "-",
                "issue_type": "备份目录为空",
                "error": "备份目录 /data/backup/mysql 完全为空",
                "duration_seconds": 0,
                "source": "remote"
            }
        else:
            return {
                "job_id": "damodel-211",
                "job_name": "211 damodel-restore",
                "run_time": "-",
                "issue_type": "今日无备份",
                "error": f"今天 {today} 无备份归档，可能备份脚本失败或未到调度时间",
                "duration_seconds": 0,
                "source": "remote"
            }

    # Check 4: restore log check
    if "__NO_LOG__" in restore_log or not restore_log:
        return {
            "job_id": "damodel-211",
            "job_name": "211 damodel-restore",
            "run_time": "-",
            "issue_type": "无恢复日志",
            "error": f"{log_path} 不存在",
            "duration_seconds": 0,
            "source": "remote"
        }

    # Check 5: today's restore status from log
    today_restore_done, has_fail, last_done_line = interpret_restore_log(
        restore_log, today
    )

    # Extract run time
    run_time = "-"
    for line in restore_log.split("\n"):
        time_match = re.search(r"(\d{2}:\d{2}:\d{2})", line)
        if time_match:
            run_time = time_match.group(1)
            break

    if today_restore_done and not has_fail:
        return {
            "job_id": "damodel-211",
            "job_name": "211 damodel-restore",
            "run_time": run_time,
            "issue_type": None,
            "error": None,
            "duration_seconds": 0,
            "source": "remote"
        }

    if has_fail:
        fail_line = next((l for l in restore_log.split("\n") if "FAIL" in l), "unknown")
        return {
            "job_id": "damodel-211",
            "job_name": "211 damodel-restore",
            "run_time": run_time,
            "issue_type": "失败",
            "error": fail_line.strip()[:150],
            "duration_seconds": 0,
            "source": "remote"
        }

    # Today's archives exist but no "restore completed" in recent log
    # Could be normal if log rotated and restore hasn't run yet today
    return {
        "job_id": "damodel-211",
        "job_name": "211 damodel-restore",
        "run_time": run_time,
        "issue_type": "今日未恢复",
        "error": f"备份链路正常，但今天 {today} 恢复日志未显示完成",
        "duration_seconds": 0,
        "source": "remote"
    }


def analyze_jobs_24h() -> dict:
    """
    Analyze all cron jobs executed in the past 24 hours.
    Returns structured report.
    """
    now = datetime.now()
    cutoff = now - timedelta(hours=24)

    jobs_data = load_jobs()
    jobs = jobs_data.get("jobs", [])

    report = {
        "check_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "period_start": cutoff.strftime("%Y-%m-%d %H:%M:%S"),
        "period_end": now.strftime("%Y-%m-%d %H:%M:%S"),
        "total_jobs": len(jobs),
        "executed_count": 0,
        "issues": [],
        "healthy": []
    }

    # [owner-patch P1-6] Read agent.log exactly once for all jobs.
    all_execs = scan_all_executions_once(cutoff)

    for job in jobs:
        job_id = job.get("id", "?")
        job_name = job.get("name", "Unknown")
        last_run_at = job.get("last_run_at")
        last_status = job.get("last_status")
        last_error = job.get("last_error")
        last_delivery_error = job.get("last_delivery_error")

        # Skip jobs not run in past 24h
        if last_run_at:
            try:
                run_time = datetime.fromisoformat(last_run_at.replace("+08:00", "").replace("+00:00", ""))
                if run_time < cutoff:
                    continue
            except:
                pass
        else:
            continue

        report["executed_count"] += 1

        # Get execution times from log — [owner-patch P1-6] single scan
        # shared by all jobs instead of re-reading the whole log per job.
        exec_times = all_execs.get(job_id, {})
        max_duration = max((e["duration_seconds"] for e in exec_times.values()), default=0)

        issue = None

        # Check for failures
        if last_status != "ok":
            issue = "失败"
            error_msg = last_error or "状态异常"
        elif last_error:
            issue = "失败"
            error_msg = last_error
        elif last_delivery_error:
            issue = "投递失败"
            error_msg = last_delivery_error
        elif max_duration > DURATION_THRESHOLD_SECONDS:
            issue = "超时"
            error_msg = f"执行时长 {max_duration//60}分钟{max_duration%60}秒"

        run_time_str = last_run_at.split("T")[1][:8] if "T" in last_run_at else last_run_at[:19]

        if issue:
            report["issues"].append({
                "job_id": job_id,
                "job_name": job_name,
                "run_time": run_time_str,
                "issue_type": issue,
                "error": error_msg,
                "duration_seconds": max_duration
            })
        else:
            report["healthy"].append({
                "job_id": job_id,
                "job_name": job_name,
                "run_time": run_time_str,
                "duration_seconds": max_duration
            })

    # Check node010 remote backup
    node010_status = check_node010_backup()
    report["total_jobs"] += 1
    if node010_status.get("issue_type"):
        report["issues"].append(node010_status)
    else:
        report["healthy"].append(node010_status)

    # Check damodel-211
    damodel_status = check_damodel_211()
    report["total_jobs"] += 1
    if damodel_status.get("issue_type"):
        report["issues"].append(damodel_status)
    else:
        report["healthy"].append(damodel_status)

    return report


def main():
    """Main entry point."""
    report = analyze_jobs_24h()

    # Output as JSON for agent to consume
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
