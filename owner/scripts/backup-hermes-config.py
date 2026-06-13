#!/usr/bin/env python3
"""备份 ~/.hermes 配置，从 patch.yaml 读取配置（有默认值兜底）。no_agent 用"""
import os, subprocess, sys, glob, yaml

# Hermes cron 以 root 运行，~ 展开为 /var/root，从 HERMES_HOME 推导用户家目录
_HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
_USER_HOME = os.path.dirname(_HERMES_HOME)

def _resolve(path):
    """将路径中的 ~ 替换为用户家目录（处理 patch.yaml 中带 ~ 的配置值）"""
    if path.startswith("~/"):
        return os.path.join(_USER_HOME, path[2:])
    return path

# 默认配置（patch.yaml 不存在或解析失败时使用）
DEFAULT_CONFIG = {
    "dest_dir": "~/projects/settings/backup",
    "keep": 3,
    "hermes": {
        "src": "~/.hermes",
        "name": "hermes-config-backup",
        "excludes": [
            "backups", "hermes-agent", "cron/output", "logs",
            "cache", "audio_cache", "image_cache", "sandboxes",
            "node_modules", "heapdump*", "*.hprof",
            "interrupt_debug.log", "models_dev_cache.json",
            "models_dev_cache.json.bak", "ollama_cloud_models_cache.json",
            "state.db", "state.db-wal", "state.db-shm",
            "sessions", "lsp", "kanban", "profiles",
            "spawn-trees", "response_store.db*",
        ]
    }
}

# 从 patch.yaml 读取配置；任何失败都降级到 DEFAULT_CONFIG，保证 backup 链路不挂
patch_path = os.path.join(_HERMES_HOME, "patch.yaml")
patch = {}
cfg = {}
hermes_cfg = {}
if os.path.exists(patch_path):
    try:
        with open(patch_path) as f:
            patch = yaml.safe_load(f) or {}
        cfg = patch.get("owner", {}).get("backup", {})
        hermes_cfg = cfg.get("hermes", {})
    except yaml.YAMLError as e:
        # patch.yaml 语法损坏时降级到 DEFAULT_CONFIG
        # 仅 stderr（cron 失败能告警；no_agent 成功路径不输出）
        sys.stderr.write(
            f"⚠️  patch.yaml 解析失败 ({type(e).__name__}): {e}\n"
            f"   降级使用 DEFAULT_CONFIG，请检查 {patch_path}\n"
        )

# 合并配置（patch.yaml 值优先，缺失则用默认值）
BACKUP_DIR = _resolve(cfg.get("dest_dir") or DEFAULT_CONFIG["dest_dir"])
SRC = _resolve(hermes_cfg.get("src") or DEFAULT_CONFIG["hermes"]["src"])
KEEP = cfg.get("keep") or DEFAULT_CONFIG["keep"]
NAME = hermes_cfg.get("name") or DEFAULT_CONFIG["hermes"]["name"]
EXCLUDES = hermes_cfg.get("excludes") or DEFAULT_CONFIG["hermes"]["excludes"]

os.makedirs(BACKUP_DIR, exist_ok=True)

timestamp = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
archive = os.path.join(BACKUP_DIR, f"{NAME}-{timestamp}.tar.gz")

# 构建排除参数
exclude_patterns = []
for ex in EXCLUDES:
    # 处理 .hermes 前缀（脚本里排除的是 .hermes/xxx）
    if not ex.startswith("*") and not ex.startswith("heapdump"):
        exclude_patterns.append(f"--exclude=.hermes/{ex}")
    else:
        exclude_patterns.append(f"--exclude={ex}")

cmd = ["tar", "-czf", archive] + exclude_patterns + ["-C", _USER_HOME, ".hermes"]

result = subprocess.run(
    cmd,
    stdout=subprocess.DEVNULL,  # 静默模式，不需要 stdout
    stderr=subprocess.PIPE,      # 只保留 stderr 用于错误诊断
    timeout=300,
)

if result.returncode == 0:
    # 静默模式 — 成功不输出，no_agent 空 stdout 即不发送
    # 保留最近 KEEP 个，删除旧的
    backups = sorted(glob.glob(os.path.join(BACKUP_DIR, f"{NAME}-*.tar.gz")))
    while len(backups) > KEEP:
        old = backups.pop(0)
        os.remove(old)
else:
    # 只输出 stderr 的前 500 字符，避免内存爆炸
    err = (result.stderr or b"").decode("utf-8", errors="replace")[:500]
    print(f"❌ 备份失败: {err}")
    sys.exit(1)