"""english_explainer —— 英文回复中文解说（owner 模块，官方源码零侵入）。

当 display.language 为中文、且 agent 终局回复被判定为整段英文时，侧路调用
辅助模型译成中文，并另发一条「🔤 系统提示：…」旁白（飞书升 notice 卡）。
不改写原英文回复。

安装：经 owner-extensions 注册 transform_llm_output + pre_gateway_dispatch。
配置：patch.yaml → owner.english_explainer.*（不污染 config.yaml）。
设计稿：owner/docs/design/english-reply-explainer/english-explainer.md
"""

from owner.english_explainer.config import load_config, resolve_enabled
from owner.english_explainer.detect import looks_like_english_reply
from owner.english_explainer.hook import register_hooks
from owner.english_explainer.prompt import PREFIX

__all__ = [
    "PREFIX",
    "load_config",
    "looks_like_english_reply",
    "register_hooks",
    "resolve_enabled",
]
