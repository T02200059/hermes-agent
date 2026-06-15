#!/usr/bin/env python3
"""
macOS 缓存目录扫描与清理工具
扫描经典缓存目录，报告大小 + 可回收空间。支持 --clean 模式。

用法:
  python3 cache-cleanup.py             只扫描报告 (默认)
  python3 cache-cleanup.py --report    同上
  python3 cache-cleanup.py --clean     报告 + 清理可安全回收的缓存
  python3 cache-cleanup.py --clean --force  跳过确认，直接清理
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, date
from pathlib import Path

# macOS user cache paths — use real user home, not HERMES_HOME/profile state
HOME = os.environ.get("HOME") or str(Path.home())


# ── 辅助函数 ──────────────────────────────────────────────────

def run(cmd: list, timeout: int = 30) -> str:
    """执行命令，返回 stdout；失败返回错误信息。"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception as e:
        return f"<error: {e}>"


def du(path: str) -> str:
    """人类可读的 du -sh，失败返回 '-'"""
    if not os.path.exists(path):
        return "-"
    return run(["du", "-sh", path, "2>/dev/null"]).split("\t")[0] or "-"


def fmt_size_kb(kb: int) -> str:
    """KB 转人类可读"""
    if kb < 0:
        return "-"
    if kb < 1024:
        return f"{kb} KB"
    mb = kb / 1024
    if mb < 1024:
        return f"{mb:.1f} MB"
    gb = mb / 1024
    return f"{gb:.2f} GB"


def yesno(prompt: str) -> bool:
    """交互式确认"""
    try:
        return input(f"{prompt} [y/N] ").strip().lower() == "y"
    except (EOFError, KeyboardInterrupt):
        return False


# ── 缓存收集器 ────────────────────────────────────────────────

def collect_caches() -> list:
    """返回所有缓存项列表，每项：{name, path, current, reclaimable, clean_cmd, clean_desc}"""
    caches = []

    # 1. ~/Library/Caches - 顶级
    lc = os.path.join(HOME, "Library", "Caches")
    caches.append({
        "name": "~/Library/Caches (含子目录)",
        "path": lc,
        "current": du(lc),
        "reclaimable": "-",
        "reclaimable_kb": -1,
        "safe": False,
        "clean_cmd": None,
        "clean_desc": "需逐个确认子目录，⚠️ 某些 app 依赖缓存",
        "children": []
    })

    # 子目录 TOP 5
    if os.path.isdir(lc):
        child_sizes = []
        for entry in sorted(os.listdir(lc)):
            fp = os.path.join(lc, entry)
            if os.path.isdir(fp) and not os.path.islink(fp):
                sz = run(["du", "-sk", fp]).split("\t")[0]
                try:
                    sz_kb = int(sz)
                except (ValueError, TypeError):
                    sz_kb = 0
                child_sizes.append((sz_kb, entry, fp))
        child_sizes.sort(reverse=True)
        for sz_kb, name, fp in child_sizes[:5]:
            caches[-1]["children"].append({
                "name": name,
                "current": fmt_size_kb(sz_kb),
                "path": fp,
            })

    # 2. Homebrew 缓存
    brew_cache = run(["brew", "--cache"]).strip()
    cur = du(brew_cache) if brew_cache and os.path.exists(brew_cache) else "-"
    # 预览可回收
    preview = run(["brew", "cleanup", "-n"], timeout=60)
    reclaimable_str = "-"
    reclaimable_kb = -1
    for line in preview.split("\n"):
        if "would free approximately" in line:
            parts = line.split()
            try:
                idx = parts.index("approximately")
                val = parts[idx + 1]
                unit = parts[idx + 2] if idx + 2 < len(parts) else ""
                if "MB" in unit:
                    reclaimable_kb = int(float(val) * 1024)
                    reclaimable_str = f"{val} MB"
                elif "GB" in unit:
                    reclaimable_kb = int(float(val) * 1024 * 1024)
                    reclaimable_str = f"{val} GB"
                elif "KB" in unit:
                    reclaimable_kb = int(val)
                    reclaimable_str = f"{val} KB"
            except (ValueError, TypeError):
                pass
    caches.append({
        "name": "Homebrew 缓存",
        "path": brew_cache if brew_cache else "$(brew --cache)",
        "current": cur,
        "reclaimable": reclaimable_str,
        "reclaimable_kb": reclaimable_kb,
        "safe": True,
        "clean_cmd": ["brew", "cleanup", "-s"],
        "clean_desc": "brew cleanup -s：移除旧版本、下载缓存",
    })

    # 3. npm 缓存
    npm_cache = os.path.join(HOME, ".npm")
    caches.append({
        "name": "npm 缓存",
        "path": npm_cache,
        "current": du(npm_cache),
        "reclaimable": "-",
        "reclaimable_kb": -1,
        "safe": True,
        "clean_cmd": ["npm", "cache", "clean", "--force"],
        "clean_desc": "npm cache clean --force：清除所有 npm 缓存包",
    })

    # 3.5. pnpm 缓存
    pnpm_store = run(["pnpm", "store", "path"]).strip()
    if not pnpm_store or "<error" in pnpm_store:
        pnpm_store = os.path.join(HOME, "Library", "pnpm")
    caches.append({
        "name": "pnpm 缓存",
        "path": pnpm_store,
        "current": du(pnpm_store),
        "reclaimable": "-",
        "reclaimable_kb": -1,
        "safe": True,
        "clean_cmd": ["pnpm", "store", "prune"],
        "clean_desc": "pnpm store prune：清除 pnpm 全局 store 中未被引用的包缓存",
    })

    # 4. pip 缓存
    pip_cache = os.path.join(HOME, "Library", "Caches", "pip")
    info = run(["pip", "cache", "info"]).strip()
    pip_size = "-"
    for line in info.split("\n"):
        if "size" in line.lower():
            pip_size = line.split(":")[-1].strip()
            break
    caches.append({
        "name": "pip 缓存",
        "path": pip_cache,
        "current": du(pip_cache) if os.path.exists(pip_cache) else "不存在",
        "reclaimable": pip_size,
        "reclaimable_kb": -1,
        "safe": True,
        "clean_cmd": ["pip", "cache", "purge"],
        "clean_desc": "pip cache purge：清除 pip 下载缓存",
    })

    # 5. ~/.cache/ (杂项工具缓存)
    dot_cache = os.path.join(HOME, ".cache")
    caches.append({
        "name": "~/.cache/ (杂项工具)",
        "path": dot_cache,
        "current": du(dot_cache),
        "reclaimable": "-",
        "reclaimable_kb": -1,
        "safe": False,
        "clean_cmd": None,
        "clean_desc": "包含 yarn/pip/其他工具缓存，不直接清理",
    })

    # 6. ~/.cargo/ 缓存
    cargo_dir = os.path.join(HOME, ".cargo")
    caches.append({
        "name": "~/.cargo/ (Rust 依赖)",
        "path": cargo_dir,
        "current": du(cargo_dir),
        "reclaimable": "-",
        "reclaimable_kb": -1,
        "safe": False,
        "clean_cmd": None,
        "clean_desc": "Rust 编译缓存 & registry，不直接清理",
    })

    # 7. Docker/Orbstack
    dockerd = run(["docker", "system", "df"]).strip()
    reclaimable_parts = []
    reclaimable_bytes = 0
    for line in dockerd.split("\n"):
        parts = line.split()
        if len(parts) >= 5 and parts[4] and parts[4] != "RECLAIMABLE":
            # 最后一列是 RECLAIMABLE
            reclaimable = parts[4]
            if reclaimable and reclaimable != "0B" and reclaimable != "0" and reclaimable != "(0%)":
                reclaimable_parts.append(reclaimable)
                # 简单累加
                if "GB" in reclaimable:
                    val = reclaimable.replace("GB", "").strip()
                    if val.replace(".", "").isdigit():
                        reclaimable_bytes += 1024 * 1024 * int(float(val))
                elif "MB" in reclaimable:
                    val = reclaimable.replace("MB", "").strip()
                    if val.replace(".", "").isdigit():
                        reclaimable_bytes += 1024 * int(float(val))

    docker_total_cur = run(["du", "-sh", "/var/lib/docker"]).split("\t")[0] if os.path.exists(
        "/var/lib/docker") else "见下方"
    # 从 docker system df 提取总大小
    docker_total_display = "-"
    for line in dockerd.split("\n"):
        if "Images" in line:
            parts = line.split()
            if len(parts) >= 4:
                docker_total_display = parts[3]
            break

    caches.append({
        "name": "Docker (Orbstack) - 镜像/容器/卷/构建缓存",
        "path": "/var/lib/docker (Orbstack VM 内)",
        "current": f"镜像 {docker_total_display}, 详见下方",
        "reclaimable": ", ".join(reclaimable_parts) if reclaimable_parts else docker_total_display,
        "reclaimable_kb": reclaimable_bytes // 1024 if reclaimable_bytes > 0 else -1,
        "safe": True,
        "clean_cmd": ["docker", "system", "prune", "-a", "-f"],
        "clean_desc": "docker system prune -a -f：清除停止的容器、未使用的镜像/网络/构建缓存",
        "detail": dockerd,
    })

    # 8. Hermes 备份归档
    bak_dir = os.path.join(HOME, ".hermes", "backups")
    bak_count = 0
    bak_total = 0
    if os.path.isdir(bak_dir):
        for f in os.listdir(bak_dir):
            if f.endswith(".tar.gz"):
                bak_count += 1
                fp = os.path.join(bak_dir, f)
                try:
                    bak_total += os.path.getsize(fp)
                except OSError:
                    pass
    caches.append({
        "name": "Hermes 备份归档",
        "path": bak_dir,
        "current": du(bak_dir),
        "reclaimable": f"{bak_count} 个文件",
        "reclaimable_kb": bak_total // 1024,
        "safe": True,
        "clean_cmd": None,  # 交互式：保留最近 N 个
        "clean_desc": f"保留最近 3 个，删除更早的 (当前 {bak_count} 个)",
        "keep_last": 3,
    })

    # 9. Hermes 会话数据
    sess_dir = os.path.join(HOME, ".hermes", "sessions")
    caches.append({
        "name": "Hermes 会话数据",
        "path": sess_dir,
        "current": du(sess_dir),
        "reclaimable": "-",
        "reclaimable_kb": -1,
        "safe": False,
        "clean_cmd": None,
        "clean_desc": "Hermes 运行依赖会话数据，不直接清理",
    })

    # 10. Hermes 音视频/图片缓存
    for sub in ["audio_cache", "image_cache"]:
        p = os.path.join(HOME, ".hermes", sub)
        sz = du(p)
        if sz != "0B" and sz != "-":
            caches.append({
                "name": f"Hermes {sub}",
                "path": p,
                "current": sz,
                "reclaimable": sz,
                "reclaimable_kb": -1,
                "safe": True,
                "clean_cmd": ["rm", "-rf", p + "/*"],
                "clean_desc": f"清空 {sub}/",
            })

    # 11. pyenv 缓存
    pyenv_cache = os.path.join(HOME, ".pyenv", "cache")
    caches.append({
        "name": "pyenv 源码缓存",
        "path": pyenv_cache,
        "current": du(pyenv_cache),
        "reclaimable": du(pyenv_cache),
        "reclaimable_kb": -1,
        "safe": True,
        "clean_cmd": ["rm", "-rf", pyenv_cache + "/*"],
        "clean_desc": "清空 pyenv 下载的 Python 源码包",
    })

    return caches


# ── 报告打印 ──────────────────────────────────────────────────

def print_report(caches: list):
    """打印缓存报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{'=' * 70}")
    print(f"  🧹 macOS 缓存扫描报告 — {now}")
    print(f"{'=' * 70}\n")

    total_current = 0
    total_reclaimable = 0

    for i, c in enumerate(caches):
        tag = "✅" if c["safe"] else "⚠️"
        status = "可安全清理" if c["safe"] else "注意甄别"
        print(f"  [{i + 1}] {tag} {c['name']}")
        print(f"      路径:   {c['path']}")
        print(f"      当前:   {c['current']}")
        print(f"      可回收: {c['reclaimable']}")
        print(f"      状态:   {status}")
        if c.get("children"):
            print(f"      子目录: ", end="")
            for ch in c["children"][:5]:
                print(f"{ch['name']}({ch['current']}) ", end="")
            print()
        if c.get("detail"):
            for line in c["detail"].split("\n"):
                print(f"      {line}")
        if c["clean_desc"]:
            print(f"      操作:   {c['clean_desc']}")
        print()

    # 统计总空间
    print(f"{'─' * 70}")
    print(f"  提示: ✅ = 可安全清理  ⚠️ = 需甄别后清理")
    print(f"  使用 --clean 参数执行清理操作")
    print(f"{'=' * 70}\n")


# ── 清理执行 ──────────────────────────────────────────────────

def do_clean(caches: list, force: bool):
    """执行清理"""
    print(f"\n{'=' * 60}")
    print(f"  开始清理 ({'自动模式' if force else '交互模式'})")
    print(f"{'=' * 60}\n")

    cleaned = []
    skipped = []
    errors = []

    for i, c in enumerate(caches):
        if not c["safe"]:
            skipped.append((c["name"], "不可安全清理"))
            continue

        print(f"[{i+1}] {c['name']}...", end=" ", flush=True)

        # Hermes 备份清理 (特殊处理)
        if c["name"] == "Hermes 备份归档":
            bak_dir = c["path"]
            keep = c.get("keep_last", 3)
            if os.path.isdir(bak_dir):
                files = sorted([f for f in os.listdir(bak_dir) if f.endswith(".tar.gz")])
                to_del = files[:-keep] if len(files) > keep else []
                if not to_del:
                    print(f"无需清理 (保留最近 {keep} 个)")
                    continue
                if not force:
                    print(f"将删除 {len(to_del)} 个旧备份, 保留最近 {keep} 个")
                    if not yesno("  确认?"):
                        print("  ⏭ 跳过")
                        skipped.append((c["name"], "用户跳过"))
                        continue
                for f in to_del:
                    fp = os.path.join(bak_dir, f)
                    try:
                        os.remove(fp)
                    except Exception as e:
                        errors.append((c["name"], str(e)))
                print(f"✅ 已删除 {len(to_del)} 个旧备份, 保留 {keep} 个")
                cleaned.append((c["name"], f"删除 {len(to_del)} 个旧备份"))
            continue

        if c["clean_cmd"] is None:
            skipped.append((c["name"], "无自动清理命令"))
            continue

        # 交互确认
        if not force:
            print(f"\n    操作: {c['clean_cmd']}")
            print(f"    说明: {c['clean_desc']}")
            if not yesno("  确认执行?"):
                print("  ⏭ 跳过")
                skipped.append((c["name"], "用户跳过"))
                continue

        # 执行清理
        try:
            r = subprocess.run(c["clean_cmd"], capture_output=True, text=True, timeout=120)
            if r.returncode == 0:
                output = r.stdout.strip()
                # 提取关键信息
                summary = output.split("\n")[-3:] if output else "无输出"
                print(f"✅ 完成")
                for line in summary:
                    if line.strip():
                        print(f"    {line.strip()}")
                cleaned.append((c["name"], output[:200] if output else "ok"))
            else:
                print(f"❌ 失败 (exit={r.returncode})")
                if r.stderr:
                    print(f"    {r.stderr[:200]}")
                errors.append((c["name"], r.stderr[:300] if r.stderr else f"exit={r.returncode}"))
        except subprocess.TimeoutExpired:
            print(f"⏳ 超时 (>120s)")
            errors.append((c["name"], "超时"))
        except Exception as e:
            print(f"❌ 异常: {e}")
            errors.append((c["name"], str(e)))

    # 清理后的二次扫描
    print(f"\n{'─' * 60}")
    print(f"  清理后重新扫描...")
    new_caches = collect_caches()

    print(f"\n{'=' * 60}")
    print(f"  清理结果汇总")
    print(f"{'=' * 60}")
    print(f"  ✅ 成功: {len(cleaned)} 项")
    for name, detail in cleaned:
        print(f"     - {name}")
    if skipped:
        print(f"  ⏭ 跳过: {len(skipped)} 项")
        for name, reason in skipped:
            print(f"     - {name} ({reason})")
    if errors:
        print(f"  ❌ 失败: {len(errors)} 项")
        for name, err in errors:
            print(f"     - {name}: {err}")

    print(f"\n  清理前后对比:")
    for old, new in zip(caches, new_caches):
        if old["name"] == new["name"] and old["current"] != new["current"]:
            print(f"     {old['name']}: {old['current']} → {new['current']}")

    print(f"\n{'=' * 60}\n")


# ── 磁盘空间监控 ─────────────────────────────────────────────

DISK_WARN_THRESHOLD_GB = 50


def get_disk_info() -> dict:
    """获取根卷磁盘信息，返回 {total, used, free, free_gb, used_pct}"""
    try:
        r = subprocess.run(
            ["df", "-k", "/"],
            capture_output=True, text=True, timeout=10
        )
        lines = r.stdout.strip().split("\n")
        if len(lines) >= 2:
            parts = lines[1].split()
            # df -k: blocks used avail capacity mounted
            # 不同系统列数可能不同，找容量列
            # macOS APFS: Filesystem  512-blocks  Used  Available  Capacity ...
            # 我们只需要 Available (人类可读) 和 Capacity
            # 用 diskutil 更准确
            pass
    except (OSError, subprocess.SubprocessError, ValueError):
        pass

    # 用 diskutil 获取精确的容器信息
    try:
        r = subprocess.run(
            ["diskutil", "info", "/"],
            capture_output=True, text=True, timeout=10
        )
        total_gb = 0.0
        free_gb = 0.0
        for line in r.stdout.split("\n"):
            line = line.strip()
            if "Container Total Space" in line:
                # "Container Total Space:     494.4 GB (494384795648 Bytes)"
                m = line.split(":")[-1].strip()
                val = m.split()[0]
                try:
                    total_gb = float(val)
                except ValueError:
                    pass
            elif "Container Free Space" in line or "Volume Free Space" in line:
                m = line.split(":")[-1].strip()
                val = m.split()[0]
                try:
                    free_gb = float(val)
                except ValueError:
                    pass
    except (OSError, subprocess.SubprocessError, ValueError):
        pass

    # fallback: df -h
    if total_gb == 0.0 or free_gb == 0.0:
        try:
            r = subprocess.run(
                ["df", "-h", "/"],
                capture_output=True, text=True, timeout=10
            )
            lines = r.stdout.strip().split("\n")
            if len(lines) >= 2:
                parts = lines[1].split()
                # Filesystem Size Used Avail Use%
                if len(parts) >= 4:
                    sz = parts[1]
                    avail = parts[3]
                    # parse human-readable
                    for val_str, target in [(sz, "total_gb"), (avail, "free_gb")]:
                        val = val_str.upper()
                        if val.endswith("G") or val.endswith("GI"):
                            num = float(val.replace("G", "").replace("I", "").replace("i", ""))
                            if target == "total_gb":
                                total_gb = num
                            else:
                                free_gb = num
                        elif val.endswith("T") or val.endswith("TI"):
                            num = float(val.replace("T", "").replace("I", "").replace("i", ""))
                            if target == "total_gb":
                                total_gb = num * 1024
                            else:
                                free_gb = num * 1024
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            pass

    used_gb = round(total_gb - free_gb, 1) if total_gb > 0 else 0.0
    used_pct = round((used_gb / total_gb) * 100, 1) if total_gb > 0 else 0.0
    free_gb = round(free_gb, 1)
    total_gb = round(total_gb, 1)

    return {
        "total_gb": total_gb,
        "used_gb": used_gb,
        "free_gb": free_gb,
        "used_pct": used_pct,
        "alert": free_gb < DISK_WARN_THRESHOLD_GB,
        "threshold_gb": DISK_WARN_THRESHOLD_GB,
    }


def print_disk_info(disk: dict):
    """打印磁盘信息"""
    total = disk["total_gb"]
    free = disk["free_gb"]
    used = disk["used_gb"]
    pct = disk["used_pct"]
    alert = disk["alert"]
    thresh = disk["threshold_gb"]

    icon = "🟢" if not alert else "🔴"
    print(f"{icon}  磁盘空间: {used}G / {total}G ({pct}%)  剩余: {free}G")
    if alert:
        print(f"      ⚠️  剩余空间 {free}G < {thresh}G 阈值！建议清理缓存")


def do_disk_watch() -> dict:
    """--disk-watch 模式：输出 JSON 给 cron 消费"""
    disk = get_disk_info()
    result = {
        "timestamp": datetime.now().isoformat(),
        "disk": disk,
        "alert": disk["alert"],
        "message": None,
    }
    if disk["alert"]:
        result["message"] = (
            f"🔴 磁盘空间不足告警\n"
            f"  剩余: {disk['free_gb']}G / {disk['total_gb']}G ({disk['used_pct']}%)\n"
            f"  阈值: < {disk['threshold_gb']}G\n"
            f"  建议: 运行 cache-cleanup.py --clean --force 清理缓存"
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


# ── 主入口 ──────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="macOS 缓存扫描与清理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                        只扫描报告
  %(prog)s --report               同上
  %(prog)s --clean                扫描 + 清理 (交互确认)
  %(prog)s --clean --force        扫描 + 清理 (自动跳过确认)
  %(prog)s --disk-watch           仅检查磁盘空间 (cron 用, 输出 JSON)
  %(prog)s --disk-watch --report  缓存报告 + 磁盘空间
        """
    )
    parser.add_argument("--report", action="store_true", help="只扫描报告（默认）")
    parser.add_argument("--clean", action="store_true", help="扫描 + 清理")
    parser.add_argument("--force", action="store_true", help="跳过确认（需配合 --clean）")
    parser.add_argument("--disk-watch", action="store_true", help="磁盘空间检查 (cron用, 输出 JSON)")
    args = parser.parse_args()

    # --disk-watch 模式：纯检查，输出 JSON
    if args.disk_watch and not args.report:
        do_disk_watch()
        return

    # 正常模式：报告 + 可选清理
    caches = collect_caches()
    print_report(caches)

    disk = get_disk_info()
    print_disk_info(disk)

    if args.clean:
        do_clean(caches, force=args.force)
    elif args.disk_watch and args.report:
        # --disk-watch --report: 也输出 JSON 报警
        if disk["alert"]:
            print("\n" + json.dumps({"alert": True, "disk": disk}, ensure_ascii=False, indent=2))
    else:
        print("  提示: 添加 --clean 参数执行清理\n")


if __name__ == "__main__":
    main()
