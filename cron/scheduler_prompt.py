"""[owner] forward-ported minimal slice from upstream cron/scheduler_prompt (BASE 之后新增).

cron/scheduler_preflight (forward-ported) imports _job_skill_names from here at
call time. The full upstream module (381 lines) is the cron prompt lane; only
this function is consumed today — the rest arrives with the cron lane (A4-2+).
"""
from __future__ import annotations


def _job_skill_names(job: dict) -> list[str]:
    """Normalized skill names from ``skills`` (list or str) or the legacy singular ``skill``."""
    skills = job.get("skills")
    if skills is None:
        legacy = job.get("skill")
        skills = [legacy] if legacy else []
    elif isinstance(skills, str):
        skills = [skills]
    return [str(name).strip() for name in skills if str(name).strip()]
