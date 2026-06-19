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
# 例如 truncate -s N: -s 吞掉 N。
_FLAGS_WITH_VALUE = {
    "truncate": {"s"},
    "cp": {"S", "t", "T", "Z", "x"},  # -S, -t, -T 等带值 (GNU coreutils)
    "install": {"S", "t", "T", "Z"},
    "mv": {"S", "T", "Z"},
}


def _strip_positionals(
    args: List[str], value_flags: set
) -> List[str]:
    """从 args 中提取位置参数 (非 flag), 跳过"flag + 其值"对。

    value_flags: 该命令中以单字母形式出现时会吞掉下一个 token 的短 flag
    (不带前导 -)。例如 {"s"} 表示 -s 会吞掉下一个 token。
    """
    positionals: List[str] = []
    skip_next = False
    for tok in args:
        if skip_next:
            skip_next = False
            continue
        if _is_flag(tok):
            bare = tok.lstrip("-")
            # 检查组合 flag (如 -st) 里是否含值 flag —— 保守起见,
            # 只有"整个 bare 恰好是某个值 flag"或"bare 长度为 1 且在集合里"才吞
            if bare in value_flags or (len(bare) == 1 and bare in value_flags):
                skip_next = True
            continue
        positionals.append(tok)
    return positionals


def _parse_simple(cmd_tokens: List[str]) -> List[str]:
    """对已分词的命令做主命令模式匹配。

    cmd_tokens[0] 是主命令 (可能是带路径的, 如 /usr/bin/sed)。
    """
    if not cmd_tokens:
        return []

    main = cmd_tokens[0]
    # 去掉路径前缀, 取 basename
    main_basename = main.rsplit("/", 1)[-1]
    args = cmd_tokens[1:]

    if main_basename == "sed":
        # sed -i [SUFFIX] SCRIPT FILE...
        # 先确认有 -i (否则 sed 不改文件, 是只读过滤)
        has_inplace = False
        for tok in args:
            if _is_flag(tok):
                bare = tok.lstrip("-")
                # -i 或 -i.bak (GNU) 或 --in-place
                if bare == "i" or bare.startswith("i.") or tok == "--in-place":
                    has_inplace = True
                    break
        if not has_inplace:
            return []
        # 提取位置参数: 第一个是 SCRIPT, 其余是 FILE
        positionals = _strip_positionals(args, set())
        if len(positionals) >= 2:
            # positionals[0] 是 script, [1:] 是 files
            return positionals[1:]
        return []

    if main_basename in {"cp", "install", "mv"}:
        # 目标是最后一个位置参数
        value_flags = _FLAGS_WITH_VALUE.get(main_basename, set())
        positionals = _strip_positionals(args, value_flags)
        if positionals:
            return [positionals[-1]]
        return []

    if main_basename == "truncate":
        # truncate [-s N] FILE...
        positionals = _strip_positionals(args, _FLAGS_WITH_VALUE["truncate"])
        if positionals:
            return [positionals[0]]
        return []

    if main_basename == "dd":
        # dd of=... — 找 of= 赋值
        for tok in args:
            if tok.startswith("of="):
                return [tok[3:]]
        return []

    if main_basename in {"rm", "rmdir", "shred"}:
        # 所有位置参数都是目标
        return _strip_positionals(args, set())

    if main_basename == "tee":
        # tee [-a] FILE...
        positionals = _strip_positionals(args, set())
        if positionals:
            return [positionals[0]]
        return []

    return []


def static_parse(command: str, cwd: str) -> List[str]:
    """静态解析命令, 返回将要被修改的文件路径列表。

    返回空列表表示"静态解析失败或只读命令", 触发 LLM 兜底。
    路径保留原始形态 (相对或绝对), 由 predictor 层 resolve。
    """
    if not command or not command.strip():
        return []

    # git repo 操作 → 哨兵
    if _GIT_REPO_RE.search(command):
        return [GIT_REPO_SENTINEL]

    # 覆盖式重定向 → 取 > 右侧文件名
    if _REDIRECT_OVERWRITE.search(command):
        # 找 "> file" 模式 (排除 >> 和 2> 等流重定向中的意外匹配)
        m = re.search(r"(?:^|[^>])>\s*([^\s|&;<>]+)", command)
        if m:
            return [m.group(1)]

    # shlex 分词, 失败则返回空 (触发 LLM)
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []

    if not tokens:
        return []

    # 处理管道/复合命令: 取第一个管道段 (左侧通常是写操作)
    # 简单做法: 遇到 | 分割, 对每段尝试解析, 合并结果
    # 但更准确的是只取"会写"的那段。保守起见对所有段都解析, 合并。
    pipe_segments = re.split(r"\s\|\s", command)
    results: List[str] = []
    for seg in pipe_segments:
        try:
            seg_tokens = shlex.split(seg)
        except ValueError:
            continue
        seg_result = _parse_simple(seg_tokens)
        results.extend(seg_result)

    # 去重, 保持顺序
    seen = set()
    deduped: List[str] = []
    for r in results:
        if r not in seen:
            seen.add(r)
            deduped.append(r)

    return deduped
