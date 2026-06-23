"""Tests for owner/checkpoint_predictor/static_parser.py — 命令静态解析。

纯函数测试, 无 mock, 无网络。
"""

from __future__ import annotations

from owner.checkpoint_predictor.static_parser import static_parse, GIT_REPO_SENTINEL


# ── sed -i ─────────────────────────────────────────────────────────────


def test_sed_inplace_single_file():
    assert static_parse("sed -i 's/a/b/' foo.py", "/cwd") == ["foo.py"]


def test_sed_inplace_with_flags():
    assert static_parse("sed -i.bak 's/a/b/' foo.py", "/cwd") == ["foo.py"]


# ── cp / install / mv ─────────────────────────────────────────────────


def test_cp_target_is_last_arg():
    # cp 的目标是最后一个参数 (被覆盖/创建的)
    assert static_parse("cp src dst", "/cwd") == ["dst"]


def test_install_target_is_last_arg():
    assert static_parse("install -m 644 src dst", "/cwd") == ["dst"]


def test_mv_target_is_last_arg():
    assert static_parse("mv old new", "/cwd") == ["new"]


# ── truncate / dd ──────────────────────────────────────────────────────


def test_truncate_target():
    assert static_parse("truncate -s 0 f.log", "/cwd") == ["f.log"]


def test_dd_of_target():
    assert static_parse("dd if=/dev/null of=f.img", "/cwd") == ["f.img"]


# ── rm / rmdir / shred (删除类, 取所有路径) ───────────────────────────


def test_rm_all_paths():
    # rm 删除多个文件, 全部都要快照 (以便回滚删除)
    result = static_parse("rm a b c", "/cwd")
    assert set(result) == {"a", "b", "c"}


def test_rmdir_all_paths():
    result = static_parse("rmdir d1 d2", "/cwd")
    assert set(result) == {"d1", "d2"}


def test_shred_all_paths():
    assert static_parse("shred secret.key", "/cwd") == ["secret.key"]


# ── > 重定向 ───────────────────────────────────────────────────────────


def test_redirect_overwrite():
    assert static_parse("echo x > f.txt", "/cwd") == ["f.txt"]


def test_redirect_append_not_matched():
    # >> 是追加, 严格说也改文件, 但 _is_destructive_command 不匹配 >>
    # 静态解析保守起见也不匹配 >> (和现有行为对齐)
    assert static_parse("echo x >> f.txt", "/cwd") == []


# ── tee ────────────────────────────────────────────────────────────────


def test_tee_first_path():
    assert static_parse("tee out.log <<< hi", "/cwd") == ["out.log"]


def test_tee_with_dash_a_append():
    # tee -a 是追加, 仍改文件
    assert static_parse("tee -a out.log", "/cwd") == ["out.log"]


# ── git checkout/reset/clean → 哨兵 ────────────────────────────────────


def test_git_reset_returns_sentinel():
    assert static_parse("git reset --hard", "/cwd") == [GIT_REPO_SENTINEL]


def test_git_checkout_returns_sentinel():
    assert static_parse("git checkout .", "/cwd") == [GIT_REPO_SENTINEL]


def test_git_clean_returns_sentinel():
    assert static_parse("git clean -fd", "/cwd") == [GIT_REPO_SENTINEL]


# ── 触发 LLM 兜底的命令 (返回空) ──────────────────────────────────────


def test_python_c_returns_empty():
    assert static_parse('python -c "print(1)"', "/cwd") == []


def test_ls_returns_empty():
    assert static_parse("ls -la", "/cwd") == []


def test_make_returns_empty():
    assert static_parse("make", "/cwd") == []


def test_npm_run_returns_empty():
    assert static_parse("npm run build", "/cwd") == []


def test_malformed_command_returns_empty():
    # shlex 解析失败 → 空 (触发 LLM)
    assert static_parse("echo 'unterminated quote", "/cwd") == []


# ── 绝对路径保留 ───────────────────────────────────────────────────────


def test_absolute_path_preserved():
    assert static_parse("rm /etc/hosts", "/cwd") == ["/etc/hosts"]


# ── 管道/复合命令 ──────────────────────────────────────────────────────


def test_piped_destructive_takes_left_side():
    # "rm a | grep x" — rm 在左侧, 仍解析
    result = static_parse("rm a | grep x", "/cwd")
    assert "a" in result
