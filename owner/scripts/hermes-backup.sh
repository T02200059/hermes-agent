#!/usr/bin/env bash
# ~/.hermes/agent-scripts/hermes-backup.sh
# Daily backup of ~/.hermes to node010:/data/ai/hermes-backup/yangtb/
# Schedule: 04:00 daily.  Retention: last 3 archives.
# Cron: no_agent=true, deliver=qqbot on failure.
#
# === 增量快照策略 (D 方案) ===
# 旧版: 本地 tar 整个 ~/.hermes → scp 整个 .tar.gz 到 node010
#       → 13k+ 文件 / 几百 MB,经常被 120s timeout 截断.
# 新版: rsync 增量(只传差异)到 remote staging/
#       → remote 上 cp -al 硬链到 snapshots/<STAMP>/(瞬时)
#       → remote 上 tar -czf 压该目录到 archives/<STAMP>.tar.gz
#     整个流程通常 <30s,即使首次全量也比旧版快(避免双倍压缩: 增量+gz 一次完成).
#
# SQLite 完整性:
#   state.db / kanban.db / response_store.db 三个非空库,本地用 sqlite3 .backup
#   落一致副本到 staging, rsync 把副本传到 remote 覆盖在同层 .hermes/<db>.db.
#   remote 上 cp -al 硬链副本(更省空间)+ 跳过原 db 文件以保持只读一致性.
#
# 重试:
#   rsync + remote-snapshot 阶段在 retry 包裹里跑 3 次, 指数退避 5/15/30s.
#
# 本地保留:
#   本地不再留归档副本 (节省磁盘). staging 临时目录跑完清空.
#
# Exit codes:
#   0 = success (silent)
#   non-zero = failure (stderr delivered to QQ)
set -u
set -o pipefail

# --- Parse CLI args (cron scheduler passes --KEY VALUE) ---
while [ $# -gt 0 ]; do
    case "$1" in
        --BACKUP_QUIET) BACKUP_QUIET="$2"; shift 2 ;;
        --timeout_seconds) shift 2 ;;
        *) shift ;;
    esac
done

# --- Config ---
BACKUP_REMOTE_DIR="/data/ai/hermes-backup/yangtb"
BACKUP_REMOTE_HOST="node010"
# Remote layout under BACKUP_REMOTE_DIR:
#   staging/.hermes/    ←  rsync 目标,rsync 端用一个目录装 .hermes 树
#   snapshots/<prev>/   ←  上一次成功的硬链快照
#   snapshots/<stamp>/  ←  本次新硬链快照
#   archives/<stamp>.tar.gz  ←  本次打包(基于 <stamp> 目录)
REMOTE_STAGING="${BACKUP_REMOTE_DIR}/staging"
REMOTE_SNAPSHOTS="${BACKUP_REMOTE_DIR}/snapshots"
REMOTE_ARCHIVES="${BACKUP_REMOTE_DIR}/archives"

STAMP="$(date +%Y%m%d-%H%M%S)"
# 本地 staging 目录:只放 sqlite snapshot (几个 db 文件),用完清空.
LOCAL_STAGING="${TMPDIR:-/tmp}/hermes-backup-staging"
SQLITE_DUMP_DIR="${LOCAL_STAGING}/sqlite-snapshots"
SQLITE_DBS=(state.db kanban.db response_store.db)

REMOTE_KEEP=3
MAX_RETRIES=3
RETRY_DELAYS=(5 15 30)
SRC_DIR="${HOME}/.hermes"
LOG_TAG="[hermes-backup]"

log()  {
    if [ "${BACKUP_QUIET:-0}" != "1" ]; then
        echo "${LOG_TAG} $*"
    fi
}
fail() { echo "${LOG_TAG} FAIL: $*" >&2; exit 1; }

# --- rsync exclude patterns ---
# openrsync 兼容: 支持 --exclude=PATTERN (多次).
# 排掉: 代码仓本身 (hermes-agent 7万+ 文件)、各 profile、cache、agent-hooks 等.
# 注: SQLite 主 db 文件不直接 rsync (--exclude),改用本地 .backup 一致副本.
EXCLUDES=(
    # 排除大体积/临时内容.
    # 重要: rsync 模式下 entry 路径是顶层目录名(不是 .hermes/xxx),
    #       跟 BSD tar -C $HOME .hermes 的 .hermes/xxx 模式不同.
    # 代码仓本身 (hermes-agent) ~3.4GB,有独立 git 跟踪,不进备份.
    --exclude='hermes-agent/'
    # Owner 临时 review 区,~148M,内容本机有 git 跟踪.
    --exclude='agent-owner-review/'
    # 各 profile、cache、agent-hooks 等.
    --exclude='profiles/'
    --exclude='cache/'
    --exclude='bootstrap-cache/'
    --exclude='audio_cache/'
    --exclude='image_cache/'
    --exclude='node/'
    --exclude='lsp/'
    --exclude='__pycache__/'
    --exclude='*.pyc'
    --exclude='*.wasm'
    --exclude='*.map'
    --exclude='models_dev_cache.json'
    --exclude='provider_models_cache.json'
    --exclude='ollama_cloud_models_cache.json'
    --exclude='events-export.json'
    --exclude='docs/'
    --exclude='pastes/'
    --exclude='pets/'
    --exclude='.backups/'
    --exclude='.qoder/'
    --exclude='.claude/'
    --exclude='.hermes_history'
    --exclude='*.lock'
    --exclude='*.pid'
    --exclude='.update_*'
    --exclude='.restart_*'
    --exclude='.scratch_*'
    --exclude='.install_method'
    --exclude='logs/'
    --exclude='interrupt_debug.log'
    --exclude='agent-hooks/'
    # SQLite 主 db + WAL/SHM (用 .backup 副本覆盖)
    --exclude='state.db'
    --exclude='state.db-shm'
    --exclude='state.db-wal'
    --exclude='state.db.malformed-backup-*'
    --exclude='kanban.db'
    --exclude='kanban.db-shm'
    --exclude='kanban.db-wal'
    --exclude='kanban.db.dispatch.lock'
    --exclude='kanban.db.init.lock'
    --exclude='kanban.db.malformed-backup-*'
    --exclude='response_store.db'
    --exclude='response_store.db-shm'
    --exclude='response_store.db-wal'
    --exclude='response_store.db.malformed-backup-*'
)

# --- Preflight ---
[ -d "$SRC_DIR" ] || fail "source dir not found: $SRC_DIR"
for cmd in ssh scp rsync tar sqlite3 find python3; do
    command -v "$cmd" >/dev/null 2>&1 || fail "missing required command: $cmd"
done

# rsync 必须在 remote 也有 (用于 archive 阶段可能不用,但 hardlink 必须 cp -al)
ssh -o BatchMode=yes -o ConnectTimeout=8 "${BACKUP_REMOTE_HOST}" \
    "mkdir -p '${REMOTE_STAGING}' '${REMOTE_SNAPSHOTS}' '${REMOTE_ARCHIVES}' && \
     test -w '${BACKUP_REMOTE_DIR}'" \
    >/dev/null 2>&1 \
    || fail "cannot write to ${BACKUP_REMOTE_HOST}:${BACKUP_REMOTE_DIR}"

mkdir -p "$SQLITE_DUMP_DIR" \
    || fail "cannot create staging dir: $SQLITE_DUMP_DIR"

# --- SQLite consistent snapshots (本地) ---
snapshot_sqlite() {
    local dbname="$1"
    local src="${SRC_DIR}/${dbname}"
    local dst="${SQLITE_DUMP_DIR}/${dbname}"

    [ -f "$src" ] || { log "sqlite: ${dbname} not present, skip"; return 0; }
    local size
    size=$(stat -f '%z' "$src" 2>/dev/null || stat -c '%s' "$src")
    if [ "${size:-0}" -eq 0 ]; then
        log "sqlite: ${dbname} is 0 bytes, skip snapshot"
        return 0
    fi

    log "sqlite: snapshotting ${dbname} (${size} bytes)"
    if ! sqlite3 "$src" ".timeout 8000" ".backup '$dst'" 2>/dev/null; then
        fail "sqlite: ${dbname} .backup command failed (consistency required)"
    fi
    if ! sqlite3 "$dst" "PRAGMA quick_check;" >/dev/null 2>&1; then
        fail "sqlite: ${dbname} snapshot failed quick_check (refuse to upload)"
    fi
}

log "phase 1/4: sqlite consistent snapshots"
for db in "${SQLITE_DBS[@]}"; do
    snapshot_sqlite "$db"
done

# --- Phase 2-4: rsync + hardlink snapshot + archive (retry-wrapped) ---
sync_and_snapshot() {
    local attempt="$1"
    local remote_prev
    local remote_new="${REMOTE_SNAPSHOTS}/${STAMP}"

    # 找上一次成功的 snapshot (按文件名排序,取最大)
    remote_prev=$(ssh -o BatchMode=yes "${BACKUP_REMOTE_HOST}" \
        "ls -1d ${REMOTE_SNAPSHOTS}/hermes-*/ 2>/dev/null | sort | tail -1" \
        2>/dev/null)
    if [ -n "$remote_prev" ] && [ "${remote_prev%/}" = "${remote_new}" ]; then
        # 极端情况: STAMP 跟上次重了 → 用秒级后缀
        remote_prev=$(ssh -o BatchMode=yes "${BACKUP_REMOTE_HOST}" \
            "ls -1d ${REMOTE_SNAPSHOTS}/hermes-*/ 2>/dev/null | sort | tail -2 | head -1" \
            2>/dev/null)
    fi

    # Step A: 增量 rsync (本地 .hermes -> remote staging/.hermes/)
    log "attempt ${attempt}: rsync -> ${BACKUP_REMOTE_HOST}:${REMOTE_STAGING}/.hermes/"
    if [ -n "$remote_prev" ]; then
        log "  link-dest reference: ${remote_prev}.hermes"
    fi
    if ! rsync -a --delete \
        "${EXCLUDES[@]}" \
        ${remote_prev:+"--link-dest=${remote_prev}.hermes"} \
        -e 'ssh -o BatchMode=yes -o ConnectTimeout=15' \
        "${SRC_DIR}/" \
        "${BACKUP_REMOTE_HOST}:${REMOTE_STAGING}/.hermes/"
    then
        log "attempt ${attempt}: rsync failed"
        return 1
    fi

    # Step B: 上传 sqlite snapshot 副本,直接覆盖到 remote staging/.hermes/<db>.db
    # (rsync 单文件多次,简单可靠)
    for db in "${SQLITE_DBS[@]}"; do
        if [ ! -f "${SQLITE_DUMP_DIR}/${db}" ]; then
            continue
        fi
        log "attempt ${attempt}: scp sqlite ${db} -> remote"
        if ! scp -o BatchMode=yes -o ConnectTimeout=15 \
            "${SQLITE_DUMP_DIR}/${db}" \
            "${BACKUP_REMOTE_HOST}:${REMOTE_STAGING}/.hermes/${db}" \
            >/dev/null 2>&1
        then
            log "attempt ${attempt}: scp ${db} failed"
            return 1
        fi
    done

    # Step C: 远端 hardlink snapshot (cp -al 把 staging 硬链到 snapshots/<stamp>/)
    log "attempt ${attempt}: remote cp -al -> ${remote_new}"
    if ! ssh -o BatchMode=yes "${BACKUP_REMOTE_HOST}" \
        "rm -rf '${remote_new}' && \
         cp -al '${REMOTE_STAGING}/.hermes' '${remote_new}.hermes' && \
         chmod -R u+rwX '${remote_new}.hermes'"
    then
        log "attempt ${attempt}: remote hardlink failed"
        return 1
    fi

    # Step D: 远端 tar 出 archive. 用 pigz 多核加速 (server 端有 /usr/bin/pigz).
    # 1.4GB 内容 gz 单核 ~2min,pigz -p 4 降到 ~30s.
    local archive="${REMOTE_ARCHIVES}/hermes-${STAMP}.tar.gz"
    log "attempt ${attempt}: remote tar (pigz -p 4) -> ${archive}"
    if ! ssh -o BatchMode=yes "${BACKUP_REMOTE_HOST}" \
        "cd '${remote_new}.hermes' && \
         tar -cf - --use-compress-program='pigz -p 4' . > '${archive}' && \
         test -s '${archive}'"
    then
        log "attempt ${attempt}: remote tar failed"
        return 1
    fi

    # 验证 archive size 合理 (>1KB)
    local rsize
    rsize=$(ssh -o BatchMode=yes "${BACKUP_REMOTE_HOST}" \
        "stat -c '%s' '${archive}' 2>/dev/null" 2>/dev/null)
    if [ -z "$rsize" ] || [ "$rsize" -lt 1024 ]; then
        log "attempt ${attempt}: archive too small or missing (size=${rsize:-MISSING})"
        return 1
    fi
    log "attempt ${attempt}: archive ready (${rsize} bytes)"

    return 0
}

log "phase 2-4: rsync + snapshot + archive (up to ${MAX_RETRIES} attempts)"
attempt=1
last_err=""
while [ "$attempt" -le "$MAX_RETRIES" ]; do
    if sync_and_snapshot "$attempt"; then
        last_err=""
        break
    fi
    last_err="attempt ${attempt} failed"
    if [ "$attempt" -eq "$MAX_RETRIES" ]; then
        fail "${last_err}. all ${MAX_RETRIES} attempts exhausted."
    fi
    local_idx=$((attempt - 1))
    delay=${RETRY_DELAYS[$local_idx]:-30}
    log "retrying in ${delay}s..."
    sleep "$delay"
    attempt=$((attempt + 1))
done

# --- Phase 5: rotation (remote archives) ---
log "phase 5/5: remote rotation (keep last ${REMOTE_KEEP} archives)"
ssh -o BatchMode=yes "${BACKUP_REMOTE_HOST}" \
    "cd '${REMOTE_ARCHIVES}' && \
     ls -1t hermes-*.tar.gz 2>/dev/null | \
     awk 'NR>\"${REMOTE_KEEP}\"' | \
     xargs -r rm -f" \
    >/dev/null 2>&1 \
    || log "WARN: remote archive rotation had issues (non-fatal)"

# 同步清旧 snapshot 目录 (保留最近 5 个,跟 archive keep 对齐)
ssh -o BatchMode=yes "${BACKUP_REMOTE_HOST}" \
    "cd '${REMOTE_SNAPSHOTS}' && \
     ls -1dt hermes-*/ 2>/dev/null | \
     awk 'NR>5' | \
     xargs -r rm -rf" \
    >/dev/null 2>&1 \
    || log "WARN: remote snapshot rotation had issues (non-fatal)"

REMAINING=$(ssh -o BatchMode=yes "${BACKUP_REMOTE_HOST}" \
    "ls -1 '${REMOTE_ARCHIVES}'/hermes-*.tar.gz 2>/dev/null | wc -l" \
    2>/dev/null)

if [ "${BACKUP_QUIET:-0}" = "1" ]; then
    : # success — stay silent
else
    log "done. remote retains ${REMAINING:-?} archive(s)"
fi

exit 0
