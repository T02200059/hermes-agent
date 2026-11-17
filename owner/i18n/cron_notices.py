"""Owner display-layer translations for user-visible cron delivery notices.

Official producers keep English literals (some shapes are also classifier /
notice-prefix keys). Translate only when rendering a scheduled-job delivery
to a messaging surface. English UI, unknown strings, and exceptions fail
open to the original text.

Commands such as ``hermes cron run``, ``/login``, and config keys stay
verbatim. Job names, ids, paths, timestamps, and other parameters are
preserved. Emoji prefixes (``💡`` / ``⛔``) are kept so Feishu notice-card
rules can still match.
"""

from __future__ import annotations

import os
import re
from typing import Callable, Match, Optional, Pattern, Sequence

from agent.i18n import DEFAULT_LANGUAGE, get_language

_Fmt = Callable[[Match[str]], str]
_Template = tuple[Pattern[str], _Fmt]


def _lang_is_chinese(force_chinese: Optional[bool]) -> bool:
    if force_chinese is not None:
        return bool(force_chinese)
    try:
        return str(get_language() or "").strip().lower().startswith("zh")
    except Exception:
        return False


def _should_translate(force_chinese: Optional[bool]) -> bool:
    if force_chinese is not None:
        return bool(force_chinese)
    # Prefer the process env before get_language(): official tests pin
    # HERMES_LANGUAGE=en, and get_language() may touch profile config.
    env = (os.environ.get("HERMES_LANGUAGE") or "").strip().lower()
    if env and not env.startswith("zh"):
        return False
    if not _lang_is_chinese(None):
        return False
    try:
        if get_language() == DEFAULT_LANGUAGE:
            return False
    except Exception:
        return False
    return True


_WRAP_RE = re.compile(
    r"^Cronjob Response: (?P<name>.+)\n"
    r"\(job_id: (?P<job_id>.*)\)\n"
    r"-------------\n\n"
    r"(?P<body>.*)\n\n"
    r"To stop or manage this job, send me a new message "
    r'\(e\.g\. "stop reminder (?P=name)"\)\.\s*$',
    re.DOTALL,
)


def _zh_wrap(name: str, job_id: str, body: str) -> str:
    return (
        f"定时任务回复：{name}\n"
        f"（任务 ID：{job_id}）\n"
        "-------------\n\n"
        f"{body}\n\n"
        f"要停止或管理此任务，请给我发一条新消息（例如「停止提醒 {name}」）。"
    )


# --- suffix phrases appended after a failure body ---------------------------------

_SUFFIXES: Sequence[_Template] = (
    (
        re.compile(
            r"\nThe provider's usage window is closed for about ([0-9.]+)h\. "
            r"This job is held through (.+?) and resumes at the first safe "
            r"opportunity afterwards; no further alerts are sent while the "
            r"provider is unavailable\.$"
        ),
        lambda m: (
            f"\n供应商的用量窗口大约关闭 {m.group(1)} 小时。"
            f"此任务将暂停至 {m.group(2)}，之后在首次安全时机恢复；"
            "供应商不可用期间不会再发送提醒。"
        ),
    ),
    (
        re.compile(
            r"\nThis job has failed (\d+) runs in a row — worth a review\. "
            r"Fix its prompt/config, or pause it with `(hermes cron pause [^`]+)` "
            r"\(resume/remove also available\) to stop the noise\.$"
        ),
        lambda m: (
            f"\n此任务已连续失败 {m.group(1)} 次，建议检查一下。"
            f"请修复其提示词/配置，或用 `{m.group(2)}` 暂停"
            "（也可恢复/删除），以免继续打扰。"
        ),
    ),
    (
        re.compile(
            r" Likely cause: the gateway is running stale code "
            r"\(booted on (\S+), disk is at (\S+)\) — "
            r"run `hermes gateway restart` to fix it\.$"
        ),
        lambda m: (
            f" 可能原因：网关正在运行过期代码（启动时为 {m.group(1)}，"
            f"磁盘上为 {m.group(2)}）——请运行 `hermes gateway restart` 修复。"
        ),
    ),
)


def _peel_suffixes(text: str) -> tuple[str, list[str]]:
    found: list[str] = []
    changed = True
    while changed and text:
        changed = False
        for pat, fmt in _SUFFIXES:
            m = pat.search(text)
            if not m or m.end() != len(text):
                continue
            try:
                found.append(fmt(m))
            except Exception:
                return text, []
            text = text[: m.start()]
            changed = True
            break
    found.reverse()
    return text, found


# --- closed-set clauses inside provider notices -----------------------------------

_CAUSES: Sequence[tuple[str, str]] = (
    (
        "the AI model service did not respond in time",
        "AI 模型服务未及时响应",
    ),
    (
        "the AI model service was rate-limited (too many requests)",
        "AI 模型服务触发了速率限制（请求过多）",
    ),
    (
        "the AI model service is overloaded right now",
        "AI 模型服务当前过载",
    ),
    (
        "the AI model service returned an internal error",
        "AI 模型服务返回了内部错误",
    ),
    (
        "the AI model service says the account's usage or credit limit is reached",
        "AI 模型服务表示账户用量或额度已达上限",
    ),
    (
        "the AI model service rejected the sign-in",
        "AI 模型服务拒绝了登录",
    ),
    (
        "a firewall/CDN in front of the AI model service blocked the request",
        "AI 模型服务前的防火墙/CDN 拦截了请求",
    ),
    (
        "the model this job uses was not found at the AI model service",
        "此任务使用的模型在 AI 模型服务上未找到",
    ),
    (
        "the AI model service's safety filter rejected the request",
        "AI 模型服务的安全过滤器拒绝了该请求",
    ),
    (
        "the AI model service refused the request because of a policy on the account",
        "AI 模型服务因账户策略拒绝了该请求",
    ),
    (
        "the job's context holds a connected-app result that needs a model that does not train on data",
        "此任务的上下文包含已连接应用的结果，需要使用不会用数据训练的模型",
    ),
    (
        "the job's request grew too large for the model",
        "此任务的请求对模型来说过大",
    ),
)


_ACTION_TEMPLATES: Sequence[_Template] = (
    (
        re.compile(
            r"^This job is pinned to its own provider/model, so it does not fall back to "
            r"`fallback_providers`; `(hermes cron edit \S+ --unpin)` lets it follow the "
            r"main model and its fallback chain\.$"
        ),
        lambda m: (
            "此任务已固定使用自己的供应商/模型，因此不会回退到 `fallback_providers`；"
            f"使用 `{m.group(1)}` 可让它跟随主模型及其回退链。"
        ),
    ),
    (
        re.compile(r"^No backup provider succeeded either\.$"),
        lambda m: "备用供应商也未成功。",
    ),
    (
        re.compile(
            r"^No backup provider is configured — add one with `hermes fallback add`, "
            r"or set a cron-wide default via `cron\.model` \+ `cron\.model_provider` in config\.yaml\.$"
        ),
        lambda m: (
            "未配置备用供应商 — 可用 `hermes fallback add` 添加，"
            "或在 config.yaml 中通过 `cron.model` + `cron.model_provider` 设置定时任务默认值。"
        ),
    ),
    (
        re.compile(
            r"^It will run again at its next scheduled time; "
            r"`(hermes cron run [^`]+)` tries now\.$"
        ),
        lambda m: f"它将在下次计划时间再运行；`{m.group(1)}` 可立即重试。",
    ),
    (
        re.compile(
            r"^Top up or wait for the limit to reset, or pin another provider with "
            r"`(hermes cron edit [^`]+)`\.$"
        ),
        lambda m: f"请充值或等待限额重置，或用 `{m.group(1)}` 指定其他供应商。",
    ),
    (
        re.compile(
            r"^Sign in again with /login \(or `([^`]+)` in a terminal\), or pin a "
            r"working provider with `(hermes cron edit [^`]+)`, then "
            r"`(hermes cron run [^`]+)` to retry\.$"
        ),
        lambda m: (
            f"请用 /login 重新登录（或在终端中运行 `{m.group(1)}`），"
            f"或用 `{m.group(2)}` 指定可用供应商，然后用 `{m.group(3)}` 重试。"
        ),
    ),
    (
        re.compile(
            r"^Pick another model with `(hermes cron edit [^`]+)`\.$"
        ),
        lambda m: f"请用 `{m.group(1)}` 更换模型。",
    ),
    (
        re.compile(
            r"^A firewall in front of the provider blocked the request \(not your key\): "
            r"set a User-Agent via `extra_headers` on the provider's custom_providers entry, "
            r"or pin another provider with `(hermes cron edit [^`]+)`\.$"
        ),
        lambda m: (
            "供应商前的防火墙拦截了请求（不是密钥问题）："
            "请在该供应商 custom_providers 条目上通过 `extra_headers` 设置 User-Agent，"
            f"或用 `{m.group(1)}` 指定其他供应商。"
        ),
    ),
    (
        re.compile(
            r"^Shorten the job's prompt with `(hermes cron edit [^`]+)`\.$"
        ),
        lambda m: f"请用 `{m.group(1)}` 缩短任务提示词。",
    ),
    (
        re.compile(
            r"^Reword the job's prompt with `(hermes cron edit [^`]+)`, or pick another "
            r"model with `(hermes cron edit [^`]+)`\.$"
        ),
        lambda m: (
            f"请用 `{m.group(1)}` 改写任务提示词，或用 `{m.group(2)}` 更换模型。"
        ),
    ),
    (
        re.compile(
            r"^Retrying won't help: check the account's status and data/privacy settings "
            r"with the provider, or pin another model with `(hermes cron edit [^`]+)`\.$"
        ),
        lambda m: (
            "重试无效：请向供应商检查账户状态和数据/隐私设置，"
            f"或用 `{m.group(1)}` 指定其他模型。"
        ),
    ),
    (
        re.compile(
            r"^Run it again with `(hermes cron run [^`]+)`, or edit it with "
            r"`(hermes cron edit [^`]+)`\.$"
        ),
        lambda m: f"请用 `{m.group(1)}` 再跑一次，或用 `{m.group(2)}` 编辑。",
    ),
)


def _translate_action(action: str) -> str:
    s = action.strip()
    # Transient actions are "{backup phrase} It will run again..."
    rec = re.compile(
        r"^(.*) It will run again at its next scheduled time; "
        r"`(hermes cron run [^`]+)` tries now\.$"
    )
    m = rec.fullmatch(s)
    if m:
        backup = _apply_templates(m.group(1).strip(), _ACTION_TEMPLATES) or m.group(1).strip()
        if backup and not backup.endswith(("。", ".", "！", "？")):
            backup += "。"
        return f"{backup}它将在下次计划时间再运行；`{m.group(2)}` 可立即重试。"
    return _apply_templates(s, _ACTION_TEMPLATES) or s


def _apply_templates(text: str, templates: Sequence[_Template]) -> Optional[str]:
    for pat, fmt in templates:
        m = pat.fullmatch(text)
        if not m:
            continue
        try:
            return fmt(m)
        except Exception:
            return None
    return None


# --- preflight / auto-pause reasons interpolated into notices ---------------------

_REASON_TEMPLATES: Sequence[_Template] = (
    (
        re.compile(
            r"^provider credential missing: (.*) \[profile '([^']+)', HERMES_HOME (.+)\]\. "
            r"Set the provider API key in \.env \(or `hermes setup`\) for that home, or pin a "
            r"working provider via `(hermes cron edit [^`]+)`\.$"
        ),
        lambda m: (
            f"供应商凭证缺失：{m.group(1)} [profile '{m.group(2)}', HERMES_HOME {m.group(3)}]。"
            "请在该 home 的 .env 中设置供应商 API 密钥（或运行 `hermes setup`），"
            f"或用 `{m.group(4)}` 指定可用供应商。"
        ),
    ),
    (
        re.compile(
            r"^delivery platform '([^']+)' is not a known cron "
            r"delivery target\. Fix the job's `deliver` value or configure "
            r"the platform's gateway credentials\.$"
        ),
        lambda m: (
            f"投递平台「{m.group(1)}」不是已知的定时任务投递目标。"
            "请修正任务的 `deliver` 值，或配置该平台的网关凭证。"
        ),
    ),
    (
        re.compile(
            r"^delivery platform '([^']+)' has no gateway "
            r"credentials configured \(not connected\)\. Configure it via "
            r"`hermes setup` or change the job's `deliver` target\.$"
        ),
        lambda m: (
            f"投递平台「{m.group(1)}」未配置网关凭证（未连接）。"
            "请通过 `hermes setup` 配置，或更改任务的 `deliver` 目标。"
        ),
    ),
    (
        re.compile(
            r"^attached skill '([^']+)' is not ready: missing "
            r"(.+)\. Provide the missing prerequisites or detach the "
            r"skill from this job\.$"
        ),
        lambda m: (
            f"附加技能「{m.group(1)}」尚未就绪：缺少 {_zh_missing_detail(m.group(2))}。"
            "请补齐缺失的前提条件，或将该技能从此任务中移除。"
        ),
    ),
    (
        re.compile(
            r"^MCP server\(s\) (.+) named in this job's enabled_toolsets "
            r"resolved to zero tools for this profile \(never connected for this profile, or connected "
            r"for another profile only\)\. If the server is only temporarily unreachable this clears by itself — "
            r"the check re-runs on every dispatch and the job resumes once the server reconnects\. "
            r"If the name is wrong or belongs to another profile, fix the server or remove it from "
            r"the job's toolsets\.$"
        ),
        lambda m: (
            f"此任务 enabled_toolsets 中指定的 MCP 服务器 {m.group(1)} "
            "在当前 profile 下未解析到任何工具（此 profile 从未连接，或只连接在其他 profile）。"
            "如果只是暂时不可达，会自行恢复 — 每次调度都会重新检查，服务器重连后任务会继续运行。"
            "如果名称有误或不属于此 profile，请修复该服务器或将其从任务的 toolsets 中移除。"
        ),
    ),
    (
        re.compile(
            r"^no_agent=True requires a script — with no agent and no script "
            r"there is nothing for the job to run\.$"
        ),
        lambda m: "no_agent=True 需要提供脚本 — 既没有 agent 也没有脚本时，任务没有可执行的内容。",
    ),
    (
        re.compile(
            r"^Cron job has nothing to run: the prompt is blank and no script or "
            r"skill\(s\) are set\. Provide a prompt, a script, or at least one skill\.$"
        ),
        lambda m: "定时任务没有可执行内容：提示词为空，且未设置脚本或技能。请提供提示词、脚本，或至少一个技能。",
    ),
    (
        re.compile(r"^Script execution failed: (.*)$"),
        lambda m: f"脚本执行失败：{m.group(1)}",
    ),
    (
        re.compile(r"^required setup incomplete$"),
        lambda m: "必要设置不完整",
    ),
)


def _zh_missing_detail(detail: str) -> str:
    if detail == "required setup incomplete":
        return "必要设置不完整"
    return detail


def _translate_reason(reason: str) -> str:
    s = reason.strip()
    return _apply_templates(s, _REASON_TEMPLATES) or s


def _translate_cause(cause: str) -> str:
    for en, zh in _CAUSES:
        if cause == en:
            return zh
    return cause


# --- body templates ----------------------------------------------------------------

def _script_timeout_zh(m: Match[str]) -> str:
    return (
        f"💡 定时任务「{m.group(1)}」失败：其脚本超时。未调用模型。"
        f"请查看 {m.group(2)} 下的脚本输出，或使用 `{m.group(3)}`，"
        f"然后用 `{m.group(4)}` 再跑一次。"
    )


def _inactivity_zh(m: Match[str]) -> str:
    return (
        f"💡 定时任务「{m.group(1)}」失败：任务停滞——长时间没有任何动作，已被中止。"
        f"请查看 {m.group(2)} 下保存的输出（`{m.group(3)}`），"
        f"然后用 `{m.group(4)}` 再跑一次。"
    )


def _blocked_zh(m: Match[str]) -> str:
    reason = _translate_reason(m.group(2).rstrip())
    if reason and reason[-1] not in "。.！!？?":
        reason += "。"
    return (
        f"⛔ 定时任务「{m.group(1)}」未运行：{reason} 未产生任何费用。"
        "Hermes 会在下次计划时间再试，并且不会重复发送此提醒；"
        "可用 `hermes cron doctor` 检查。"
    )


def _generic_zh(m: Match[str]) -> str:
    return (
        f"💡 定时任务「{m.group(1)}」失败：{_translate_reason(m.group(2))}。"
        f"完整运行记录请用 `{m.group(3)}` 查看（输出保存在 {m.group(4)}）；"
        f"可用 `{m.group(5)}` 再跑一次，用 `{m.group(6)}` 编辑，"
        f"或用 `{m.group(7)}` 暂停。"
    )


def _provider_zh(m: Match[str]) -> str:
    cause = _translate_cause(m.group(2))
    action = _translate_action(m.group(3))
    if action and not action.endswith(("。", ".", "！", "？")):
        action += "。"
    return (
        f"💡 定时任务「{m.group(1)}」失败：{cause}。{action}"
        f"运行日志：`{m.group(4)}`。"
    )


def _watchdog_zh(m: Match[str]) -> str:
    output = _translate_reason(m.group(2))
    return (
        f"💡 定时任务看门狗「{m.group(1)}」的脚本失败\n\n"
        f"{output}\n\n"
        f"时间：{m.group(3)}"
    )


def _monitor_zh(m: Match[str]) -> str:
    error = _translate_reason(m.group(2))
    return (
        f"💡 定时任务监视器「{m.group(1)}」的数据源失败\n\n"
        f"{error}\n\n"
        f"时间：{m.group(3)}"
    )


def _paused_zh(m: Match[str]) -> str:
    return (
        f"💡 定时任务「{m.group(1)}」已被自动暂停\n\n"
        f"{_translate_reason(m.group(2))}"
    )


_BODY_TEMPLATES: Sequence[_Template] = (
    (
        re.compile(
            r"^💡 Cron '(.+?)' failed: its script timed out\. No model was invoked\. "
            r"Check the script's output under (.+?) or `(hermes cron runs [^`]+)`, "
            r"then run it again with `(hermes cron run [^`]+)`\.$"
        ),
        _script_timeout_zh,
    ),
    (
        re.compile(
            r"^💡 Cron '(.+?)' failed: the job stalled — it stopped doing anything for too long "
            r"and was cut off\. Check what it was doing in the saved output under "
            r"(.+?) \(`(hermes cron runs [^`]+)`\), then run it again with "
            r"`(hermes cron run [^`]+)`\.$"
        ),
        _inactivity_zh,
    ),
    (
        re.compile(
            r"^⛔ Cron '(.+?)' did not run: (.+) Nothing was charged\. Hermes will try again at "
            r"the next scheduled time and will not repeat this alert; check with "
            r"`hermes cron doctor`\.$",
            re.DOTALL,
        ),
        _blocked_zh,
    ),
    (
        re.compile(
            r"^💡 Cron '(.+?)' failed: (.+)\. See the full run with `(hermes cron runs [^`]+)` "
            r"\(output saved under (.+?)\); run it again with `(hermes cron run [^`]+)`, "
            r"edit it with `(hermes cron edit [^`]+)`, or pause it with `(hermes cron pause [^`]+)`\.$",
            re.DOTALL,
        ),
        _generic_zh,
    ),
    (
        re.compile(
            r"^💡 Cron '(.+?)' failed: (.+?)\. (.+) Run log: `(hermes cron runs [^`]+)`\.$",
            re.DOTALL,
        ),
        _provider_zh,
    ),
    (
        re.compile(
            r"^💡 Cron watchdog '(.+?)' script failed\n\n(.*)\n\nTime: (.+)$",
            re.DOTALL,
        ),
        _watchdog_zh,
    ),
    (
        re.compile(
            r"^💡 Cron monitor '(.+?)' source failed\n\n(.*)\n\nTime: (.+)$",
            re.DOTALL,
        ),
        _monitor_zh,
    ),
    (
        re.compile(
            r"^💡 Cron job '(.+?)' was auto-paused\n\n(.*)$",
            re.DOTALL,
        ),
        _paused_zh,
    ),
)


def _translate_body(text: str) -> str:
    body, suffixes = _peel_suffixes(text)
    translated = _apply_templates(body, _BODY_TEMPLATES)
    if translated is None:
        # A bare known reason / suffix-only fragment still deserves a pass.
        translated = _translate_reason(body)
        if translated == body:
            cause = _translate_cause(body)
            if cause != body:
                translated = cause
            else:
                translated = body
    return translated + "".join(suffixes)


def translate_cron_delivery(
    text: str | None,
    *,
    force_chinese: Optional[bool] = None,
) -> str:
    """Return a Simplified Chinese display string, or the original on miss / English UI."""
    if text is None:
        return ""
    s = str(text)
    if not s.strip():
        return s
    if not _should_translate(force_chinese):
        return s
    try:
        wrapped = _WRAP_RE.fullmatch(s)
        if wrapped:
            body = _translate_body(wrapped.group("body"))
            return _zh_wrap(wrapped.group("name"), wrapped.group("job_id"), body)
        return _translate_body(s)
    except Exception:
        return s


__all__ = ["translate_cron_delivery"]
