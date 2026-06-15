#!/usr/bin/env python3
"""
Cron job health check script for Hermes Agent.

Analyzes the past 24 hours of cron job executions and reports:
- Failed jobs (last_status != ok or last_error != null)
- Jobs exceeding duration threshold (default 8 minutes)
- Delivery failures (last_delivery_error != null)

Outputs structured JSON for the agent to format and send.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Configuration
DURATION_THRESHOLD_SECONDS = 480  # 8 minutes


def _hermes_home() -> Path:
    from hermes_constants import get_hermes_home

    return get_hermes_home()


HERMES_HOME = _hermes_home()
JOBS_FILE = HERMES_HOME / "cron" / "jobs.json"
AGENT_LOG = HERMES_HOME / "logs" / "agent.log"


def load_jobs() -> dict:
    """Load cron jobs configuration."""
    if not JOBS_FILE.exists():
        return {"jobs": []}
    with open(JOBS_FILE) as f:
        return json.load(f)


def parse_log_timestamp(line: str) -> datetime | None:
    """Parse timestamp from log line."""
    # Format: "2026-04-29 18:00:36,502 INFO ..."
    match = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
    if match:
        return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
    return None


def get_job_execution_times(job_id: str, cutoff: datetime) -> dict:
    """
    Analyze agent.log to find execution times for a specific job.
    
    Returns dict with execution_id -> {start, end, duration_seconds}
    """
    if not AGENT_LOG.exists():
        return {}
    
    # Pattern: [cron_<job_id>_<timestamp>] or "Running job '<name>' (ID: <job_id>)"
    executions = {}
    current_exec_id = None
    current_start = None
    current_end = None
    
    with open(AGENT_LOG) as f:
        for line in f:
            ts = parse_log_timestamp(line)
            if ts is None or ts < cutoff:
                continue
            
            # Match execution context: [cron_<job_id>_YYYYMMDD_HHMMSS]
            exec_match = re.search(rf"\[cron_{job_id}_\d+_\d+\]", line)
            if exec_match:
                exec_id = exec_match.group(0)[1:-1]  # Remove brackets
                if exec_id not in executions:
                    executions[exec_id] = {"start": ts, "end": ts}
                else:
                    executions[exec_id]["end"] = ts
            
            # Match "Running job '<name>' (ID: <job_id>)"
            running_match = re.search(rf"Running job.*\(ID: {job_id}\)", line)
            if running_match:
                # This marks the start, but we use the exec_id pattern for precision
                pass
    
    # Calculate durations
    for exec_id, data in executions.items():
        data["duration_seconds"] = int((data["end"] - data["start"]).total_seconds())
    
    return executions


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
            except (ValueError, TypeError):
                pass
        else:
            continue
        
        report["executed_count"] += 1
        
        # Get execution times from log
        exec_times = get_job_execution_times(job_id, cutoff)
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
    
    return report


def main():
    """Main entry point."""
    report = analyze_jobs_24h()
    
    # Output as JSON for agent to consume
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()