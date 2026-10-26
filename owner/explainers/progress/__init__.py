"""[owner] C13 — progress explainer (silent-period narration)."""

from owner.explainers.progress.dispatcher import (
    ProgressExplainer,
    install_progress_explainer,
    register_hooks,
    stop,
)

__all__ = [
    "ProgressExplainer",
    "install_progress_explainer",
    "register_hooks",
    "stop",
]
