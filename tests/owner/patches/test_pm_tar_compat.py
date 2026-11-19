"""[owner] pm_tar_compat 安全回归：无 PEP 706 解释器上的 tar 解包 fallback。

owner/patches/pm_tar_compat.py 是 pm.store.extract_tar 在老 Python（无
``tarfile.data_filter`` / ``TarInfo.replace``）上的逐成员安全解包路径。
失效方向是"恶意包经 PM 归档边界写归档外/带特权限位落地"，平时在
新解释器上不会执行，所以必须直接钉住它的行为：

- 逐成员先检后解（check-then-extract），检查用当前磁盘状态的 realpath；
  因此 SymlinkOrder（先放一个 symlink 再经它写目标外）在两步都被拦。
- 绝对路径成员、``../`` 逃逸、指向目标外的 symlink/hardlink 拒绝。
- setuid/setgid/sticky 清除，文件 mode 归一到 0o755 掩码 + 0o600 下限。
- 白名单外成员类型（fifo/设备文件）拒绝。
"""

from __future__ import annotations

import io
import os
import tarfile

import pytest

from owner.patches.pm_tar_compat import _legacy_data_filter, extract_tar_legacy


def _member(name, *, type=tarfile.REGTYPE, mode=0o644, linkname="", data=b"payload"):
    info = tarfile.TarInfo(name)
    info.type = type
    info.mode = mode
    info.linkname = linkname
    info.size = len(data) if type == tarfile.REGTYPE else 0
    return info, (data if type == tarfile.REGTYPE else None)


def _build_tar(members):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tf:
        for info, data in members:
            tf.addfile(info, io.BytesIO(data) if data is not None else None)
    buffer.seek(0)
    return tarfile.open(fileobj=buffer)


@pytest.fixture()
def dest(tmp_path):
    target = tmp_path / "dest"
    target.mkdir()
    return target


def _extract(members, dest):
    with _build_tar(members) as tf:
        extract_tar_legacy(tf, str(dest), os.path.realpath(dest))


# --- 正常解压 -------------------------------------------------------------

def test_normal_extraction_restores_tree_and_contents(dest):
    _extract([
        _member("pkg/", type=tarfile.DIRTYPE, mode=0o700),
        _member("pkg/data.txt", mode=0o644, data=b"hello"),
        _member("pkg/exec", mode=0o755, data=b"#!/bin/sh\n"),
        _member("pkg/link", type=tarfile.SYMTYPE, linkname="../pkg/data.txt"),
    ], dest)
    assert (dest / "pkg" / "data.txt").read_bytes() == b"hello"
    # 目录 mode 归一为 0o755（tar 里写的 0o700 不落地）。
    assert (os.stat(dest / "pkg").st_mode & 0o777) == 0o755
    assert (os.stat(dest / "pkg" / "exec").st_mode & 0o777) == 0o755
    # 指向归档内的合法 symlink 保留。
    link = dest / "pkg" / "link"
    assert link.is_symlink() and os.readlink(link).endswith("data.txt")


def test_hardlink_resolved_from_archive_root(dest):
    _extract([
        _member("real/file", mode=0o644, data=b"shared"),
        _member("sub/hl", type=tarfile.LNKTYPE, linkname="real/file"),
    ], dest)
    linked = dest / "sub" / "hl"
    assert linked.is_file() and linked.read_bytes() == b"shared"
    assert os.path.samefile(linked, dest / "real" / "file")
    # hardlink 与源文件同 inode（真的是硬链接，不是拷贝）。
    assert linked.stat().st_ino == (dest / "real" / "file").stat().st_ino
    assert linked.stat().st_nlink == 2


# --- 成员名与链接目标拒绝 --------------------------------------------------

def test_absolute_member_name_rejected(dest):
    with pytest.raises(tarfile.ExtractError, match="unsafe archive member name"):
        _extract([_member("/etc/evil", data=b"x")], dest)
    assert list(dest.iterdir()) == []


def test_empty_member_name_rejected(dest):
    with pytest.raises(tarfile.ExtractError, match="unsafe archive member name"):
        _extract([_member("", data=b"x")], dest)


@pytest.mark.parametrize("name", ["../evil", "a/../../evil", "sub/../../../evil"])
def test_dotdot_escape_rejected(dest, name):
    with pytest.raises(tarfile.ExtractError, match="escapes destination"):
        _extract([_member(name, data=b"x")], dest)
    assert list(dest.iterdir()) == []


@pytest.mark.parametrize("linkname", ["../../outside", "/etc/passwd"])
def test_symlink_target_outside_rejected(dest, linkname):
    with pytest.raises(tarfile.ExtractError, match="escapes destination|absolute archive link"):
        _extract([_member("esc", type=tarfile.SYMTYPE, linkname=linkname)], dest)
    assert not (dest / "esc").exists() and not (dest / "esc").is_symlink()


def test_hardlink_target_outside_rejected(dest):
    with pytest.raises(tarfile.ExtractError, match="escapes destination"):
        _extract([_member("hl", type=tarfile.LNKTYPE, linkname="../outside")], dest)


# --- 成员类型白名单 --------------------------------------------------------

@pytest.mark.parametrize("type_", [tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE])
def test_special_member_types_rejected(dest, type_):
    with pytest.raises(tarfile.ExtractError, match="unsupported special archive member"):
        _extract([_member("dev", type=type_)], dest)


# --- 限位清洗 --------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0o4755, 0o755),  # setuid + rwxr-xr-x -> rwxr-xr-x（setuid 清除，可执行文件保留执行位）
        (0o2755, 0o755),  # setgid 清除
        (0o1777, 0o755),  # sticky 清除
        (0o777, 0o755),   # 掩码到 0o755
        (0o644, 0o644),   # 普通文件不变
        (0o000, 0o600),   # 归一下限：所有者可读写
        (0o100, 0o700),   # 只执行无读写的文件不保留"不可读却可执行"
        (0o666, 0o644),   # 0o755 掩码剥掉 group/other 写位
    ],
)
def test_regular_file_mode_sanitized_on_disk(dest, raw, expected):
    _extract([_member("f", mode=raw, data=b"x")], dest)
    mode = os.stat(dest / "f").st_mode
    assert mode & 0o7777 == expected, oct(mode)
    assert not (mode & 0o7000), "setuid/setgid/sticky must never survive"


def test_filter_output_member_has_sanitized_metadata(dest):
    # 纯函数层：返回的成员 uid/gid 归零、mode 清洗，供 extract 使用。
    info, _ = _member("f", mode=0o4755, data=b"x")
    safe = _legacy_data_filter(info, str(dest))
    assert (safe.uid, safe.gid, safe.uname, safe.gname) == (0, 0, "", "")
    assert safe.mode == 0o755
    info_dir, _ = _member("d/", type=tarfile.DIRTYPE, mode=0o777)
    assert _legacy_data_filter(info_dir, str(dest)).mode is None


# --- SymlinkOrder：先放 symlink，再经它写目标外 -----------------------------

def test_symlink_order_attack_cannot_write_outside(dest, tmp_path):
    # 第一个成员就是逃逸 symlink：在 pivot 落地前就被拒，后续经它写的成员根本轮不到。
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel").write_text("keep")
    escape = os.path.relpath(outside, os.path.realpath(dest))
    with pytest.raises(tarfile.ExtractError):
        _extract([
            _member("pivot", type=tarfile.SYMTYPE, linkname=escape),
            _member("pivot/pwned", data=b"gotcha"),
        ], dest)
    assert list(outside.iterdir()) == [outside / "sentinel"]
    assert not (dest / "pivot").exists()


def test_symlink_order_traversal_through_previously_extracted_link_rejected(dest, tmp_path):
    # pivot 本身合法（指向归档内目录），但后续成员经它再 ".." 爬出归档：
    # 检查用当前磁盘状态 realpath，经已落地 symlink 解析后仍在 dest 外 -> 拒绝。
    with pytest.raises(tarfile.ExtractError, match="escapes destination"):
        _extract([
            _member("a", type=tarfile.SYMTYPE, linkname="b"),
            _member("b/", type=tarfile.DIRTYPE),
            _member("a/../../escape", data=b"gotcha"),
        ], dest)
    assert not (tmp_path / "escape").exists()
    assert (dest / "b").is_dir()
