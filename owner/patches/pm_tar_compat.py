"""[owner] PM tar fallback for bootstrap interpreters without PEP 706 support.

Keep the containment checks at pm.store.extract_tar: the package-manager
archive boundary. The normal path still uses the stdlib ``data`` filter.
"""

import copy
import os
import tarfile


def _legacy_data_filter(member, dest):
    name = member.name
    if not name or os.path.isabs(name):
        raise tarfile.ExtractError(f"unsafe archive member name: {name!r}")
    target = os.path.realpath(os.path.join(dest, name))
    if os.path.commonpath([target, dest]) != dest:
        raise tarfile.ExtractError(f"archive member escapes destination: {name!r}")
    if not (member.isreg() or member.isdir() or member.issym() or member.islnk()):
        raise tarfile.ExtractError(f"unsupported special archive member: {name!r}")
    if member.issym() or member.islnk():
        if os.path.isabs(member.linkname):
            raise tarfile.ExtractError(f"absolute archive link target: {member.linkname!r}")
        # Match the new-Python PM convention: symlinks resolve from their own
        # directory; hardlinks remain rooted at the archive destination.
        base = os.path.dirname(name) if member.issym() else ""
        link_target = os.path.realpath(os.path.join(dest, base, member.linkname))
        if os.path.commonpath([link_target, dest]) != dest:
            raise tarfile.ExtractError(f"archive link escapes destination: {name!r}")

    result = copy.copy(member)
    result.uid = result.gid = 0
    result.uname = result.gname = ""
    mode = member.mode
    if mode is not None:
        mode &= 0o755
        if member.isreg() or member.islnk():
            if not mode & 0o100:
                mode &= ~0o111
            mode |= 0o600
        else:
            mode = None
        result.mode = mode
    return result


def extract_tar_legacy(tf, dest, real_dest):
    """Extract each checked member on Python versions without ``filter=``."""
    for member in tf:
        safe = _legacy_data_filter(member, real_dest)
        tf.extract(safe, dest, set_attrs=False)
        if not safe.issym():
            mode = safe.mode if safe.mode is not None else 0o755
            os.chmod(os.path.join(dest, safe.name), mode, follow_symlinks=False)
