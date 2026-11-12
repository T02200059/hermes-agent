"""终端命令静态解析 —— shlex + 正则, 提取命令将要修改的文件路径。

返回相对或绝对路径列表 (相对路径保留原样, 由 predictor 解析时 resolve)。
返回空列表表示"静态解析失败", 触发 LLM 兜底。

GIT_REPO_SENTINEL 是特殊值, 表示 git 操作影响整个 repo,
predictor 将其映射为 cwd 的项目根。
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

GIT_REPO_SENTINEL = "__git_repo__"

# 重定向目标里没有回滚价值的: 写它们不算文件改动。
_HARMLESS_TARGETS = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"}

# 只被这些动词写过才算"破坏性"(决定是否向用户发 tip)。tee / > 新建落在 home 的
# 常规写入不算 —— 历史上它们占了绝大多数噪音, 但真值仍值得记 debug。
_DESTRUCTIVE_VERBS = {"rm", "rmdir", "shred", "cp", "install", "mv", "truncate", "dd"}

# 只读动词白名单: 所有 segment 的主动词都在此表 (且没有写信号) 时不调 LLM、不发 tip。
_READ_ONLY_VERBS = {
    "ls", "cat", "head", "tail", "wc", "grep", "egrep", "fgrep", "rg", "awk",
    "ps", "date", "df", "du", "stat", "echo", "printf", "which", "type", "file",
    "hostname", "uptime", "free", "id", "whoami", "env", "printenv", "tree", "jq",
    "cut", "sort", "uniq", "tr", "diff", "cmp", "md5sum", "sha256sum", "shasum",
    "readlink", "realpath", "dirname", "basename", "seq", "uname", "nproc",
    "lscpu", "lsblk", "ss", "netstat", "dig", "ping", "traceroute", "nslookup",
    "host", "nvidia-smi", "ssh", "pgrep", "journalctl", "dmesg", "lsof",
    "vmstat", "iostat", "kill", "pkill", "killall",
}

# 包装器: 真正命令在它们之后 (timeout 25 ssh ...)。
_WRAPPERS = {"timeout", "nice", "nohup", "sudo", "command", "stdbuf", "env", "builtin"}

# 只读子命令表 (verb -> 允许的首个子命令)。
_READ_ONLY_SUBCOMMANDS = {
    "git": {
        "status", "log", "diff", "show", "ls-files", "rev-parse", "blame",
        "describe", "show-ref", "for-each-ref", "ls-tree", "cat-file", "shortlog",
        "reflog", "worktree",
    },
    "docker": {
        "ps", "logs", "inspect", "images", "version", "info", "top", "port",
        "history", "diff",
    },
    "kubectl": {
        "get", "describe", "logs", "top", "explain", "api-resources",
        "api-versions", "version", "cluster-info", "auth",
    },
    "systemctl": {
        "status", "show", "is-active", "is-enabled", "list-units",
        "list-unit-files", "cat", "--version",
    },
}

# find 的写副作用 flag; awk 程序里的文件/IPC 写入。
_FIND_WRITE_FLAGS = {
    "-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf", "-fls",
}
_AWK_WRITE_RE = re.compile(r"(?:print|printf)\b[^;|]*?>>?\s*[\"']|\bsystem\s*\(")

# 子命令前可跳过的、带取值的全局 flag。
_GLOBAL_FLAGS_WITH_VALUE = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "-H", "--context",
     "--config", "--kubeconfig", "-n", "--server"}
)

# <<EOF / <<'EOF' / <<"EOF" / <<-EOF  heredoc 起始
_HEREDOC_START = re.compile(
    r"<<-?\s*(?:'([^']+)'|\"([^\"]+)\"|\\?(\S+))"
)

# git 操作影响整个 repo
_GIT_REPO_RE = re.compile(r"(?:^|\s|&&|;|\|)git\s+(?:reset|clean|checkout)(?:\s|$)")

# 命令开头的 cd 链: cd <字面量目录> [&&|;|&||] ...
_CD_LEAD_RE = re.compile(
    r"^\s*cd\s+(?:\"([^\"]*)\"|'([^']*)'|([^\s;&|]+))\s*(?:&&|\|\||;|&)?\s*"
)


def _is_flag(tok: str) -> bool:
    """token 是否是 flag (-x 或 --xxx)。"""
    return tok.startswith("-") and tok != "-"


# 每个命令中"会吞掉下一个 token 作为值"的 flag 集合 (短 flag 形式)。
_FLAGS_WITH_VALUE = {
    "truncate": {"s"},
    "cp": {"S", "t", "T", "Z", "x"},
    "install": {"S", "t", "T", "Z"},
    "mv": {"S", "T", "Z"},
}


def _strip_positionals(
    args: list[str], value_flags: set
) -> list[str]:
    """从 args 中提取位置参数 (非 flag), 跳过"flag + 其值"对。"""
    positionals: list[str] = []
    skip_next = False
    for tok in args:
        if skip_next:
            skip_next = False
            continue
        if _is_flag(tok):
            bare = tok.lstrip("-")
            if bare in value_flags or (len(bare) == 1 and bare in value_flags):
                skip_next = True
            continue
        positionals.append(tok)
    return positionals


def _parse_simple(cmd_tokens: list[str]) -> list[str]:
    """对已分词的命令做主命令模式匹配。"""
    if not cmd_tokens:
        return []

    main = cmd_tokens[0]
    main_basename = main.rsplit("/", 1)[-1]
    args = cmd_tokens[1:]

    if main_basename == "sed":
        has_inplace = False
        for tok in args:
            if _is_flag(tok):
                bare = tok.lstrip("-")
                if bare == "i" or bare.startswith("i.") or tok == "--in-place":
                    has_inplace = True
                    break
        if not has_inplace:
            return []
        positionals = _strip_positionals(args, set())
        if len(positionals) >= 2:
            return positionals[1:]
        return []

    if main_basename in {"cp", "install", "mv"}:
        value_flags = _FLAGS_WITH_VALUE.get(main_basename, set())
        positionals = _strip_positionals(args, value_flags)
        if positionals:
            return [positionals[-1]]
        return []

    if main_basename == "truncate":
        positionals = _strip_positionals(args, _FLAGS_WITH_VALUE["truncate"])
        if positionals:
            return [positionals[0]]
        return []

    if main_basename == "dd":
        for tok in args:
            if tok.startswith("of="):
                return [tok[3:]]
        return []

    if main_basename in {"rm", "rmdir", "shred"}:
        return _strip_positionals(args, set())

    if main_basename == "tee":
        positionals = _strip_positionals(args, set())
        if positionals:
            return [positionals[0]]
        return []

    return []



def _split_segments(command: str) -> list[str]:
    """按未加引号的 ``|`` ``||`` ``&&`` ``;`` 换行切分命令。

    ``re.split`` 会切坏 ``sed 's/a;b/'`` / JSON 参数里的 ``|``; 这里逐字符扫,
    引号内与转义字符原样保留。heredoc 体应已由调用方抹掉。
    """
    segments: list[str] = []
    buf: list[str] = []
    quote = ""
    i, n = 0, len(command)
    while i < n:
        ch = command[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < n:
                buf.append(command[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            buf.append(ch)
            buf.append(command[i + 1])
            i += 2
            continue
        two = command[i : i + 2]
        if two in ("&&", "||"):
            segments.append("".join(buf))
            buf = []
            i += 2
            continue
        if ch in ("|", ";", "\n"):
            segments.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    segments.append("".join(buf))
    return [s for s in (seg.strip() for seg in segments) if s]


def scan_redirects(command: str, *, include_append: bool = False) -> list[str]:
    """引号感知地提取覆盖式重定向目标 (``>`` / ``&>`` / ``>|``)。

    引号里的 ``>`` (awk ``$1>2048`` / ``NR>1`` / ``echo "a -> b"``) 不是重定向;
    ``>>``(追加)、``>&``(fd 复向)、``>=``(比较) 按既有契约不计;
    ``2>/dev/null`` 这类无回滚价值的目标直接丢弃。返回按出现顺序去重。
    """
    visible = strip_heredoc_bodies(command)
    targets: list[str] = []
    quote = ""
    i, n = 0, len(visible)
    while i < n:
        ch = visible[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < n:
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch != ">":
            i += 1
            continue
        nxt = visible[i + 1] if i + 1 < n else ""
        if nxt == ">":  # 追加: 默认按契约不跟踪; 只读判定要算写信号
            i += 2
            if include_append:
                j = i
                while j < n and visible[j] in " \t":
                    j += 1
                k = j
                while k < n and visible[k] not in " \t\n|&;<>()":
                    k += 1
                target = visible[j:k]
                if target and target not in _HARMLESS_TARGETS and target not in targets:
                    targets.append(target)
                i = max(k, i)
            continue
        if nxt in ("&", "="):  # >&2 / >= 比较
            i += 2
            continue
        j = i + 1
        if j < n and visible[j] == "|":  # >| clobber
            j += 1
        while j < n and visible[j] in " \t":
            j += 1
        if j < n and visible[j] == "&":  # >&fd
            i = j + 1
            continue
        if j < n and visible[j] in ("'", '"'):
            q = visible[j]
            k = j + 1
            start = k
            while k < n and visible[k] != q:
                k += 1
            target = visible[start:k]
            k = min(k + 1, n)
        else:
            k = j
            while k < n and visible[k] not in " \t\n|&;<>()":
                k += 1
            target = visible[j:k]
        if target and target not in _HARMLESS_TARGETS and target not in targets:
            targets.append(target)
        i = max(k, i + 1)
    return targets


def _first_word(args: list[str]) -> tuple[int, str]:
    """跳过带值的全局 flag, 返回首个非 flag 的位置与内容。"""
    i = 0
    while i < len(args):
        tok = args[i]
        if _is_flag(tok):
            i += 2 if tok in _GLOBAL_FLAGS_WITH_VALUE else 1
            continue
        return i, tok
    return -1, ""


_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _strip_env_prefix(toks: list[str]) -> list[str]:
    """去掉 ``FOO=1 cmd`` 的前置赋值。"""
    i = 0
    while i < len(toks) and _ENV_ASSIGN_RE.match(toks[i]):
        i += 1
    return toks[i:]


def _strip_wrappers(toks: list[str]) -> list[str]:
    """剥掉 ``timeout 25`` / ``sudo`` / ``nohup`` 这类包装器, 返回真正的命令。"""
    while toks and toks[0].rsplit("/", 1)[-1] in _WRAPPERS:
        wrapper = toks[0].rsplit("/", 1)[-1]
        toks = toks[1:]
        if wrapper == "timeout":
            while toks and (toks[0].startswith("-") or toks[0].replace(".", "", 1).isdigit()):
                toks = toks[1:]
        elif wrapper == "env":
            toks = [t for t in toks if not _ENV_ASSIGN_RE.match(t) and not t.startswith("-")]
        else:
            while toks and _is_flag(toks[0]):
                toks = toks[1:]
    return toks


def _read_only_segment(seg: str) -> bool:
    """单段命令是否只读 (不含写信号)。"""
    try:
        toks = _strip_wrappers(_strip_env_prefix(shlex.split(seg)))
    except ValueError:
        return False
    if not toks:
        return True

    # mysql 的 -e 取值是 SQL 而不是子命令, 先按 SQL 判读写。
    if toks[0].rsplit("/", 1)[-1] in ("mysql", "mariadb"):
        sql = " ".join(toks[1:]).upper()
        return not re.search(
            r"\b(INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|"
            r"INTO\s+OUTFILE|INTO\s+DUMPFILE|LOAD\s+DATA)\b",
            sql,
        )

    # 剥掉 timeout/nohup/sudo 这类包装器, 判真正的命令。
    toks = _strip_wrappers(toks)
    if not toks:
        return True

    idx, verb = _first_word(toks)
    if idx < 0:
        return True
    verb = verb.rsplit("/", 1)[-1]
    args = toks[idx + 1 :]

    if verb == "curl":
        # 只有真正落盘的输出 flag 才算写; -o /dev/null 是探测。
        for i, a in enumerate(args):
            if a in {"-O", "--remote-name"}:
                return False
            if a in {"-o", "--output", "-c", "--cookie-jar", "-D", "--dump-header"}:
                target = args[i + 1] if i + 1 < len(args) else ""
                if a in {"-o", "--output"} and target in _HARMLESS_TARGETS:
                    continue
                return False
        return True

    if verb == "cd":
        return True
    if verb == "sed":
        has_quiet = any(
            a in {"-n", "--quiet", "--silent"} or (a.startswith("-n") and not a.startswith("--"))
            for a in args
        )
        inplace = any(a == "-i" or a.startswith("-i") or a == "--in-place" for a in args)
        return has_quiet and not inplace
    if verb == "awk":
        return not _AWK_WRITE_RE.search(" ".join(args))
    if verb == "xargs":
        # xargs 后的才是真命令; 逐个 flag 剥掉后递归判它。
        rest = [a for a in args if not _is_flag(a)]
        return bool(rest) and _read_only_segment(" ".join(shlex.quote(a) for a in rest))
    if verb == "find":
        return not any(a in _FIND_WRITE_FLAGS for a in args)
    if verb == "nvidia-smi":
        return not any(
            a.startswith("--gpu-reset") or a in {"-pm", "-pl", "-lgc", "-rgc", "-ac", "-rac"}
            for a in args
        )
    if verb in _READ_ONLY_SUBCOMMANDS:
        sub_idx, sub = _first_word(args)
        if sub_idx < 0:
            return True
        if verb == "git" and sub == "branch":
            return not any(a in {"-d", "-D", "-m", "-M", "--delete", "--move"} for a in args)
        if verb == "git" and sub == "stash":
            return args[sub_idx + 1 : sub_idx + 2] == ["list"]
        if verb == "docker" and sub == "system":
            return args[sub_idx + 1 : sub_idx + 2] == ["df"]
        return sub in _READ_ONLY_SUBCOMMANDS[verb]
    return verb in _READ_ONLY_VERBS


def is_read_only_command(command: str) -> bool:
    """命令是否完全只读 (可为空操作): 无重定向目标、无写动词、无 heredoc。

    供 predictor 在"静态解析为空"时短路: 只读命令不调 LLM、不弹 checkpoint tip。
    """
    if not command or not command.strip():
        return False
    visible = strip_heredoc_bodies(command)
    if "<<" in visible:  # 解释器读脚本执行, 写不写无法静态判定 → 不归为只读
        return False
    if scan_redirects(visible, include_append=True):
        return False
    if _GIT_REPO_RE.search(visible):
        return False
    segments = _split_segments(visible)
    if not segments:
        return False
    return all(_read_only_segment(seg) for seg in segments)


def destructive_signal(command: str) -> bool:
    """命令是否有会覆盖/删除/移动文件的写信号 (引号感知, 不认比较运算)。

    取代 ``_is_destructive_command`` 的 quote-blind 正则, 用于决定 checkpoint
    告警是否对用户可见。
    """
    if not command or not command.strip():
        return False
    visible = strip_heredoc_bodies(command)
    if _GIT_REPO_RE.search(visible) or scan_redirects(visible):
        return True
    for seg in _split_segments(visible):
        try:
            toks = _strip_wrappers(_strip_env_prefix(shlex.split(seg)))
        except ValueError:
            continue
        idx, verb = _first_word(toks)
        if idx < 0:
            continue
        verb = verb.rsplit("/", 1)[-1]
        args = toks[idx + 1 :]
        if verb in _DESTRUCTIVE_VERBS:
            return True
        if verb == "sed" and any(
            a == "-i" or a.startswith("-i") or a == "--in-place" for a in args
        ):
            return True
        if verb == "find" and any(a in _FIND_WRITE_FLAGS for a in args):
            return True
    return False


def strip_heredoc_bodies(command: str) -> str:
    """把 heredoc 体替换成等长空白, 避免体里的 `>`/`>=` 被当成 shell 重定向。

    保留 `<<EOF` 标记与结束定界行, 只抹掉中间正文。未闭合 heredoc 则抹掉余下全部。
    """
    if not command or "<<" not in command:
        return command
    out: list[str] = []
    i = 0
    n = len(command)
    while i < n:
        m = _HEREDOC_START.search(command, i)
        if not m:
            out.append(command[i:])
            break
        out.append(command[i:m.end()])
        delim = next(g for g in m.groups() if g is not None)
        rest = command[m.end():]
        end_re = re.compile(r"\n(?:\t)*" + re.escape(delim) + r"(?=\n|$)")
        em = end_re.search(rest)
        if not em:
            out.append(" " * len(rest))
            break
        out.append(" " * em.start())
        out.append(em.group(0))
        i = m.end() + em.end()
    return "".join(out)


def static_parse(command: str, cwd: str) -> list[str]:
    """静态解析命令, 返回将要被修改的文件路径列表。"""
    if not command or not command.strip():
        return []

    # heredoc 体内的 Python/脚本比较运算符不能当重定向; 外壳上的 > file 仍保留。
    shell_visible = strip_heredoc_bodies(command)

    if _GIT_REPO_RE.search(shell_visible):
        return [GIT_REPO_SENTINEL]

    results: list[str] = list(scan_redirects(shell_visible))
    for seg in _split_segments(shell_visible):
        try:
            seg_tokens = _strip_wrappers(_strip_env_prefix(shlex.split(seg)))
        except ValueError:
            continue
        results.extend(_parse_simple(seg_tokens))

    seen = set()
    deduped: list[str] = []
    for r in results:
        if r not in seen:
            seen.add(r)
            deduped.append(r)

    return deduped


def effective_cwd(command: str, cwd: str) -> str:
    """命令真正生效的目录: 消费开头的 ``cd`` 链, 返回最终目录。

    相对路径预测必须按这个目录解析 —— 用 session cwd 解析 ``cd /x && ... > out.txt``
    会把 ``out.txt`` 错算到 cwd 下 (cwd 为 home 时直接被安全过滤, 误报"预测失败")。

    只处理字面量目标; 目标含变量/通配符/``cd -`` 时停止消费 (无法静态确定)。
    永不抛异常, 解析不出变化时原样返回 ``cwd``。
    """
    try:
        current = cwd
        rest = command or ""
        changed = False
        while True:
            m = _CD_LEAD_RE.match(rest)
            if not m:
                break
            target = next((g for g in m.groups() if g is not None), "")
            if not target or target == "-" or any(ch in target for ch in "$`*?"):
                break
            try:
                path = Path(target).expanduser()
            except (OSError, RuntimeError):
                break
            if not path.is_absolute():
                path = Path(current) / path
            try:
                current = str(path.resolve())
            except (OSError, RuntimeError):
                current = os.path.normpath(str(path))
            changed = True
            rest = rest[m.end():]
        return current if changed else cwd
    except Exception:
        return cwd
