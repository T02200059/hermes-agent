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

# 覆盖式重定向 (> file 但不是 >> / >= 比较 / fd 复向)。
# 官方旧式 [^>]>[^>] 会把 Python `n>=maxn` / `printed>0` 当成重定向。
_REDIRECT_OVERWRITE = re.compile(r"(?<![>&])>(?!>)(?!&)(?!=)")

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

    if _GIT_REPO_RE.search(command):
        return [GIT_REPO_SENTINEL]

    # heredoc 体内的 Python/脚本比较运算符不能当重定向; 外壳上的 > file 仍保留。
    shell_visible = strip_heredoc_bodies(command)

    if _REDIRECT_OVERWRITE.search(shell_visible):
        m = re.search(r"(?:^|[^>])>\s*([^\s|&;<>]+)", shell_visible)
        if m and not m.group(1).startswith("="):
            return [m.group(1)]

    try:
        tokens = shlex.split(command)
    except ValueError:
        return []

    if not tokens:
        return []

    pipe_segments = re.split(r"\s\|\s", command)
    results: list[str] = []
    for seg in pipe_segments:
        try:
            seg_tokens = shlex.split(seg)
        except ValueError:
            continue
        seg_result = _parse_simple(seg_tokens)
        results.extend(seg_result)

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
