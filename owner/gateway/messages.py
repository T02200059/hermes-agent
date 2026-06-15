"""Gateway user-facing message helpers (owner i18n consolidation).

Thin wrappers around agent.i18n.t for gateway/run.py owner-added strings.
Keeps run.py free of scattered # [owner] i18n markers.
"""

from __future__ import annotations

from agent.i18n import t


def busy_drain_queued(action: str) -> str:
    return t("gateway.busy_drain_queued", action=action)


def busy_drain_not_accepting(action: str) -> str:
    return t("gateway.busy_drain_not_accepting", action=action)


def busy_drain_no_work(action: str) -> str:
    return t("gateway.busy_drain_no_work", action=action)


def busy_queue_ack(status_detail: str) -> str:
    return t("gateway.busy_queue_ack", status_detail=status_detail)


def busy_interrupt_ack(status_detail: str) -> str:
    return t("gateway.busy_interrupt_ack", status_detail=status_detail)


def shutdown_notify_restart() -> str:
    return t("gateway.shutdown_notify_restart")


def shutdown_notify_stop() -> str:
    return t("gateway.shutdown_notify_stop")


def steer_failed(error: str) -> str:
    return t("gateway.steer_failed", error=error)


def steer_queued(preview: str) -> str:
    return t("gateway.steer_queued", preview=preview)


def steer_empty() -> str:
    return t("gateway.steer_empty")


def force_stop_pending() -> str:
    return t("gateway.force_stop_pending")


def destructive_slash_cancelled(command: str) -> str:
    return t("gateway.destructive_slash_confirm.cancelled", command=command)


def destructive_slash_always_note() -> str:
    return t("gateway.destructive_slash_confirm.always_note")


def destructive_slash_prompt(*, command: str, detail: str, _p: str) -> str:
    return t(
        "gateway.destructive_slash_confirm.prompt",
        command=command,
        detail=detail,
        _p=_p,
    )


def restart_success() -> str:
    return t("gateway.restart_success")


def online() -> str:
    return t("gateway.online")