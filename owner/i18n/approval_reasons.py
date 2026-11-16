"""Owner display-layer translations for exec-approval reason descriptions.

English ``description`` strings from ``tools/approval_detection.py`` (and
``tools.approval._EXECUTE_CODE_DESCRIPTION``) are also allowlist / pattern keys.
Never rewrite those English strings in detectors or persist Chinese into allowlists.

Use :func:`translate_reason` only when rendering user-visible approval cards /
CLI headers / plain-text approval bodies. On English language, or on any miss,
return the original description unchanged.
"""

from __future__ import annotations

import re

from agent.i18n import DEFAULT_LANGUAGE, get_language

# Exact English description -> Simplified Chinese display string.
# Keys must match detector / gate outputs character-for-character.
REASON_ZH: dict[str, str] = {
    'PowerShell destructive delete (Remove-Item)': 'PowerShell 破坏性删除（Remove-Item）',
    'PowerShell encoded command execution': 'PowerShell 编码命令执行',
    'SQL DELETE without WHERE': '无 WHERE 的 SQL DELETE',
    'SQL DROP': 'SQL DROP',
    'SQL TRUNCATE': 'SQL TRUNCATE',
    'Windows PowerShell destructive delete': 'Windows PowerShell 破坏性删除',
    'Windows cmd destructive delete': 'Windows cmd 破坏性删除',
    'Windows destructive delete (recursive/quiet switch)': 'Windows 破坏性删除（递归/静默开关）',
    'access to Hermes secrets (Windows path)': '访问 Hermes 密钥（Windows 路径）',
    'access to SSH keys (Windows path)': '访问 SSH 密钥（Windows 路径）',
    'chmod +x followed by immediate execution': 'chmod +x 后立即执行',
    'cloud metadata endpoint access (instance credentials)': '访问云元数据端点（实例凭证）',
    'command parser limit exceeded': '命令解析器超出限制',
    'command parser limit or malformed executable payload': '命令解析器超限或可执行载荷格式错误',
    'copy/move file into sensitive credential/SSH/shell-rc path': '复制/移动文件到敏感凭证/SSH/shell-rc 路径',
    'copy/move file into system config path': '复制/移动文件到系统配置路径',
    'dd to raw block device': 'dd 写入原始块设备',
    'delete backups (wbadmin)': '删除备份（wbadmin）',
    'delete in root path': '在根路径删除',
    'delete volume shadow copies (vssadmin)': '删除卷影副本（vssadmin）',
    'disk copy': '磁盘复制',
    'disk partitioning (diskpart)': '磁盘分区（diskpart）',
    'docker compose restart/stop/kill/down (container lifecycle)': 'docker compose restart/stop/kill/down（容器生命周期）',
    'docker context use (switches default daemon for future commands)': 'docker context use（切换后续命令的默认 daemon）',
    'docker restart/stop/kill (container lifecycle)': 'docker restart/stop/kill（容器生命周期）',
    'docker with daemon redirect (--context: alternate daemon)': 'docker 重定向 daemon（--context：备用 daemon）',
    'docker with remote daemon redirect (-H/--host)': 'docker 重定向到远程 daemon（-H/--host）',
    'docker/podman daemon redirect via environment (DOCKER_HOST/CONTAINER_HOST)': '通过环境变量重定向 docker/podman daemon（DOCKER_HOST/CONTAINER_HOST）',
    'dynamic shell word may expand to arbitrary program execution flag': '动态 shell 词可能展开为任意程序执行参数',
    'execute remote content via Invoke-Expression': '通过 Invoke-Expression 执行远程内容',
    'execute remote content via command substitution': '通过命令替换执行远程内容',
    'execute remote script via process substitution': '通过进程替换执行远程脚本',
    'execute_code script execution. The script can spawn subprocesses or mutate files without passing through terminal command approval; approval is one-shot for this run.': 'execute_code 脚本执行。该脚本可在不经过终端命令审批的情况下派生子进程或修改文件；本次运行为一次性审批。',
    'find -delete': 'find -delete',
    'find -exec/-execdir rm': 'find -exec/-execdir rm',
    'find dynamic shell word may expand to destructive flag': 'find 动态 shell 词可能展开为破坏性参数',
    'force kill processes': '强制结束进程',
    'force kill processes (Stop-Process -Force)': '强制结束进程（Stop-Process -Force）',
    'force kill processes (killall -KILL)': '强制结束进程（killall -KILL）',
    'force kill processes (killall -s KILL)': '强制结束进程（killall -s KILL）',
    'force kill processes (taskkill /F)': '强制结束进程（taskkill /F）',
    'force stop service (Stop-Service -Force)': '强制停止服务（Stop-Service -Force）',
    'fork bomb': 'fork bomb',
    'format drive (format.com)': '格式化驱动器（format.com）',
    'format filesystem': '格式化文件系统',
    'format filesystem (Format-Volume)': '格式化文件系统（Format-Volume）',
    'format filesystem (mkfs)': '格式化文件系统（mkfs）',
    'git branch force delete': 'git 强制删除分支',
    'git branch force delete (long flags)': 'git 强制删除分支（长参数）',
    'git branch force delete (long flags, force-first)': 'git 强制删除分支（长参数，force 在前）',
    'git clean with force (deletes untracked files)': 'git clean 强制清理（删除未跟踪文件）',
    'git force push (rewrites remote history)': 'git 强制推送（改写远程历史）',
    'git force push short flag (rewrites remote history)': 'git 强制推送短参数（改写远程历史）',
    'git reset --hard (destroys uncommitted changes)': 'git reset --hard（销毁未提交更改）',
    'grant Everyone access (icacls)': '授予 Everyone 访问权限（icacls）',
    'hermes update (restarts gateway, kills running agents)': 'hermes update（重启 gateway，终止运行中的 agent）',
    'in-place edit of Hermes config/env': '原地编辑 Hermes config/env',
    'in-place edit of Hermes config/env (long flag)': '原地编辑 Hermes config/env（长参数）',
    'in-place edit of Hermes config/env (perl/ruby)': '原地编辑 Hermes config/env（perl/ruby）',
    'in-place edit of sensitive credential/SSH/shell-rc path': '原地编辑敏感凭证/SSH/shell-rc 路径',
    'in-place edit of sensitive credential/SSH/shell-rc path (long flag)': '原地编辑敏感凭证/SSH/shell-rc 路径（长参数）',
    'in-place edit of sensitive credential/SSH/shell-rc path (perl/ruby)': '原地编辑敏感凭证/SSH/shell-rc 路径（perl/ruby）',
    'in-place edit of system config': '原地编辑系统配置',
    'in-place edit of system config (long flag)': '原地编辑系统配置（长参数）',
    'init 0/6 (shutdown/reboot)': 'init 0/6（关机/重启）',
    'invisible or bidirectional Unicode control character (possible obfuscation)': '不可见或双向 Unicode 控制字符（可能是混淆）',
    'kill all processes': '结束全部进程',
    'kill hermes/gateway process (self-termination)': '结束 hermes/gateway 进程（自我终止）',
    'kill process via backtick pgrep/pidof expansion (self-termination)': '通过反引号 pgrep/pidof 展开结束进程（自我终止）',
    'kill process via pgrep/pidof expansion (self-termination)': '通过 pgrep/pidof 展开结束进程（自我终止）',
    'kill processes by regex (killall -r)': '按正则结束进程（killall -r）',
    'modify boot configuration (bcdedit /set)': '修改引导配置（bcdedit /set）',
    'overwrite project env/config file': '覆盖项目 env/config 文件',
    'overwrite project env/config via redirection': '通过重定向覆盖项目 env/config',
    'overwrite project env/config via tee': '通过 tee 覆盖项目 env/config',
    'overwrite system config': '覆盖系统配置',
    'overwrite system file via redirection': '通过重定向覆盖系统文件',
    'overwrite system file via tee': '通过 tee 覆盖系统文件',
    'package manager uninstall': '包管理器卸载',
    'pipe a credential file into a curl/wget upload (possible exfiltration)': '将凭证文件管道传给 curl/wget 上传（可能是外泄）',
    'pipe decoded content to shell (possible command obfuscation)': '将解码内容管道传给 shell（可能是命令混淆）',
    'pipe openssl-decoded content to shell (possible command obfuscation)': '将 openssl 解码内容管道传给 shell（可能是命令混淆）',
    'pipe remote content to PowerShell (iwr | iex)': '将远程内容管道传给 PowerShell（iwr | iex）',
    'pipe remote content to shell': '将远程内容管道传给 shell',
    'pipe tr-transformed output to shell (possible command obfuscation)': '将 tr 变换输出管道传给 shell（可能是命令混淆）',
    'pipe xxd-decoded content to shell (possible command obfuscation)': '将 xxd 解码内容管道传给 shell（可能是命令混淆）',
    'podman remote mode (-r/--remote: remote daemon)': 'podman 远程模式（-r/--remote：远程 daemon）',
    'podman with remote daemon redirect (--url/--connection/--identity)': 'podman 重定向到远程 daemon（--url/--connection/--identity）',
    'recursive chown to root': '递归 chown 为 root',
    'recursive chown to root (long flag)': '递归 chown 为 root（长参数）',
    'recursive delete': '递归删除',
    'recursive delete (flags after operands)': '递归删除（参数在操作数之后）',
    'recursive delete (long flag)': '递归删除（长参数）',
    'recursive delete of home directory': '递归删除 home 目录',
    'recursive delete of root filesystem': '递归删除根文件系统',
    'recursive delete of system directory': '递归删除系统目录',
    'recursive world/other-writable (long flag)': '递归设置全局/其他人可写（长参数）',
    'redirect to raw block device': '重定向到原始块设备',
    'registry delete (reg delete)': '删除注册表（reg delete）',
    'registry value delete (Remove-ItemProperty -Force)': '删除注册表值（Remove-ItemProperty -Force）',
    'reset ACLs recursively (icacls /reset)': '递归重置 ACL（icacls /reset）',
    'script execution via -e/-c flag': '通过 -e/-c 参数执行脚本',
    'script execution via heredoc': '通过 heredoc 执行脚本',
    'shell command via -c/-lc flag': '通过 -c/-lc 参数执行 shell 命令',
    'shell execution via heredoc': '通过 heredoc 执行 shell',
    "start gateway outside systemd (use 'systemctl --user restart hermes-gateway')": "在 systemd 外启动 gateway（请使用 'systemctl --user restart hermes-gateway'）",
    'stop/delete service (sc)': '停止/删除服务（sc）',
    'stop/restart hermes gateway (kills running agents)': '停止/重启 hermes gateway（终止运行中的 agent）',
    'stop/restart hermes gateway via shell-spliced verb (kills running agents)': '通过 shell 拼接动词停止/重启 hermes gateway（终止运行中的 agent）',
    'stop/restart hermes launchd service (kills running agents)': '停止/重启 hermes launchd 服务（终止运行中的 agent）',
    'stop/restart system service': '停止/重启系统服务',
    'sudo password guessing via stdin (sudo -S)': '通过 stdin 猜测 sudo 密码（sudo -S）',
    'sudo with combined-flag privilege escalation': '带组合参数的 sudo 提权',
    'sudo with privilege flag (stdin/askpass/shell/list)': '带提权参数的 sudo（stdin/askpass/shell/list）',
    'system shutdown/reboot': '系统关机/重启',
    'systemctl poweroff/reboot': 'systemctl poweroff/reboot',
    'telinit 0/6 (shutdown/reboot)': 'telinit 0/6（关机/重启）',
    'upload a secret or credential file via curl/wget (possible exfiltration)': '通过 curl/wget 上传密钥或凭证文件（可能是外泄）',
    'wipe disk (Clear-Disk)': '擦除磁盘（Clear-Disk）',
    'wipe free space (cipher /w)': '擦除空闲空间（cipher /w）',
    'world/other-writable permissions': '全局/其他人可写权限',
    'write to block device': '写入块设备',
    'xargs with rm': 'xargs 配合 rm',
}

# Dynamic f-string shapes from ``_execution_flag_findings`` (tool/flag vary).
# Each entry: (compiled pattern, formatter(match) -> str).
_REASON_ZH_TEMPLATES: tuple[tuple[re.Pattern[str], object], ...] = (
    (
        re.compile(r"^arbitrary program execution via (.+)$"),
        lambda m: f"通过 {m.group(1)} 执行任意程序",
    ),
)


def _language_is_zh(lang: str | None) -> bool:
    """True for Simplified / other ``zh*`` active language ids."""
    if not lang:
        return False
    key = lang.strip().lower().replace("_", "-")
    return key == "zh" or key.startswith("zh-")


def translate_reason(description: str | None) -> str | None:
    """Translate an approval reason for display; never raise; never invent keys.

    - ``None`` / empty -> returned as-is (``None`` stays ``None``; ``""`` stays ``""``).
    - Active language not Chinese -> original English unchanged (table unused).
    - Exact ``REASON_ZH`` hit -> Chinese.
    - Dynamic template hit -> Chinese with tool/flag preserved.
    - Otherwise -> original (fallback).
    """
    if description is None:
        return None
    if description == "":
        return ""
    try:
        lang = get_language()
    except Exception:
        return description
    if lang == DEFAULT_LANGUAGE or not _language_is_zh(lang):
        return description
    hit = REASON_ZH.get(description)
    if hit is not None:
        return hit
    for pattern, fmt in _REASON_ZH_TEMPLATES:
        m = pattern.match(description)
        if m:
            try:
                return fmt(m)
            except Exception:
                return description
    return description



def collect_static_detector_descriptions() -> set[str]:
    """Static description strings the drift test must cover (no dynamic templates)."""
    from tools.approval_detection import (
        DANGEROUS_PATTERNS,
        HARDLINE_PATTERNS,
        _GATEWAY_LIFECYCLE_SPLICE_DESCRIPTION,
        _MALFORMED_EXEC_DESCRIPTION,
        _PARSER_LIMIT_DESCRIPTION,
    )
    from tools.approval import _EXECUTE_CODE_DESCRIPTION

    out: set[str] = {d for _, d in DANGEROUS_PATTERNS}
    out |= {d for _, d in HARDLINE_PATTERNS}
    out |= {
        _PARSER_LIMIT_DESCRIPTION,
        _MALFORMED_EXEC_DESCRIPTION,
        _GATEWAY_LIFECYCLE_SPLICE_DESCRIPTION,
        "script execution via -e/-c flag",
        "script execution via heredoc",
        "shell command via -c/-lc flag",
        "sudo password guessing via stdin (sudo -S)",
        _EXECUTE_CODE_DESCRIPTION,
    }
    return out


__all__ = [
    "REASON_ZH",
    "collect_static_detector_descriptions",
    "translate_reason",
]
