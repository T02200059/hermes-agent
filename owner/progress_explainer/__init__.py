"""progress_explainer —— 沉默期进度旁白（owner 模块，官方源码零侵入）。

安装入口（网关侧，见 gateway/run.py 的 [owner] 胶水行）::

    from owner.progress_explainer import install_progress_explainer
    explainer = install_progress_explainer(
        runner=self, turn_ctx=turn_ctx, agent=agent, source=source,
        session_key=session_key, executor_ref=lambda: _executor_task,
    )

设计稿：owner/docs/design/silent-progress-narration/progress-explainer.md
"""

from owner.progress_explainer.dispatcher import (
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
