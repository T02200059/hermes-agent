"""终端命令静态解析 —— shlex + 正则, 提取命令将要修改的文件路径。

返回相对或绝对路径列表 (相对路径保留原样, 由 predictor 解析时 resolve)。
返回空列表表示"静态解析失败", 触发 LLM 兜底。

GIT_REPO_SENTINEL 是特殊值, 表示 git 操作影响整个 repo,
predictor 将其映射为 cwd 的项目根。
"""

from __future__ import annotations

import re
import shlex
from typing import List

GIT_REPO_SENTINEL = "__git_repo__"

# 覆盖式重定向 (> file 但不是 >>)
_REDIRECT_OVERWRITE = re.compile(r"[^>]>[^>]")

# git 操作影响整个 repo
_GIT_REPO_RE = re.compile(r"(?:^|\s|&&|;|\|)git\s+(?:reset|clean|checkout)(?:\s|$)")


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
    args: List[str], value_flags: set
) -> List[str]:
    """从 args 中提取位置参数 (非 flag), 跳过"flag + 其值"对。"""
    positionals: List[str] = []
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


def _parse_simple(cmd_tokens: List[str]) -> List[str]:
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


def static_parse(command: str, cwd: str) -> List[str]:
    """静态解析命令, 返回将要被修改的文件路径列表。"""
    if not command or not command.strip():
        return []

    if _GIT_REPO_RE.search(command):
        return [GIT_REPO_SENTINEL]

    if _REDIRECT_OVERWRITE.search(command):
        m = re.search(r"(?:^|[^>])>\s*([^\s|&;<>]+)", command)
        if m:
            return [m.group(1)]

    try:
        tokens = shlex.split(command)
    except ValueError:
        return []

    if not tokens:
        return []

    pipe_segments = re.split(r"\s\|\s", command)
    results: List[str] = []
    for seg in pipe_segments:
        try:
            seg_tokens = shlex.split(seg)
        except ValueError:
            continue
        seg_result = _parse_simple(seg_tokens)
        results.extend(seg_result)

    seen = set()
    deduped: List[str] = []
    for r in results:
        if r not in seen:
            seen.add(r)
            deduped.append(r)

    return deduped
