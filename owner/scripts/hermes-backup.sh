#!/usr/bin/env bash
# ~/.hermes/agent-scripts/hermes-backup.sh
# Daily backup of ~/.hermes to node010:/data/ai/hermes-backup/yangtb/
# Schedule: 04:00 daily.  Retention: last 3 archives.
# Cron: no_agent=true, deliver=qqbot on failure.
#
# SQLite 完整性策略:
#   对 state.db / kanban.db / response_store.db 三个非空库用 `sqlite3 .backup` 落一致副本
#   (hold read lock, page-by-page, 比 raw cp 安全),
#   tar 排除原主 db 文件, 用 Python tarfile 把 snapshot 副本以原名追加到归档.
#
# 重试策略:
#   pack+upload 阶段在 retry 包裹里跑 3 次, 指数退避 5s/15s/30s.
#
# 本地保留:
#   staging 目录里留 1 份, 60 分钟后自动清.
#
# Exit codes:
#   0 = success (silent)
#   non-zero = failure (stderr delivered to QQ)
set -u
set -o pipefail

# --- Config ---
BACKUP_REMOTE_DIR="/data/ai/hermes-backup/yangtb"
BACKUP_REMOTE_HOST="node010"
# Staging dirs MUST live outside ~/.hermes, otherwise BSD tar
# (`-C ~ .hermes`) sees the in-progress archive and aborts with
# "Can't add archive to itself".
STAGING_DIR="${TMPDIR:-/tmp}/hermes-backup-staging"
SQLITE_DUMP_DIR="${STAGING_DIR}/sqlite-snapshots"
STAMP="$(date +%Y%m%d-%H%M%S)"
ARCHIVE_NAME="hermes-${STAMP}.tar.gz"
LOCAL_TMP="${STAGING_DIR}/${ARCHIVE_NAME}"
REMOTE_KEEP=3
LOCAL_TTL_MIN=60
MAX_RETRIES=3
RETRY_DELAYS=(5 15 30)
SRC_DIR="${HOME}/.hermes"
LOG_TAG="[hermes-backup]"

log()  { echo "${LOG_TAG} $*"; }
fail() { echo "${LOG_TAG} FAIL: $*" >&2; exit 1; }

# --- Build exclude list file ---
# BSD tar --exclude-from: 模式按 *完整归档内路径* 匹配,
# 'dir' 匹配目录本身的 entry, 'dir/*' 匹配目录内所有内容.
# 二者都写才能彻底排除一个目录.
EXCLUDE_FILE="${STAGING_DIR}/.excludes"
write_exclude_file() {
    cat > "$1" <<'EXCLUDES'
.hermes/hermes-agent
.hermes/hermes-agent/*
.hermes/profiles
.hermes/profiles/*
.hermes/cache
.hermes/cache/*
.hermes/bootstrap-cache
.hermes/bootstrap-cache/*
.hermes/audio_cache
.hermes/audio_cache/*
.hermes/image_cache
.hermes/image_cache/*
.hermes/node
.hermes/node/*
.hermes/lsp
.hermes/lsp/*
.hermes/__pycache__
.hermes/__pycache__/*
.hermes/*/__pycache__
.hermes/*/__pycache__/*
.hermes/*/*/__pycache__
.hermes/*/*/__pycache__/*
*.pyc
.hermes/*/*.pyc
.hermes/*/*/*.pyc
*.wasm
*.map
.hermes/models_dev_cache.json
.hermes/provider_models_cache.json
.hermes/ollama_cloud_models_cache.json
.hermes/events-export.json
.hermes/docs
.hermes/docs/*
.hermes/pastes
.hermes/pastes/*
.hermes/pets
.hermes/pets/*
.hermes/.backups
.hermes/.backups/*
.hermes/.qoder
.hermes/.qoder/*
.hermes/.claude
.hermes/.claude/*
.hermes/.hermes_history
*.lock
.hermes/*.lock
.hermes/*/*.lock
.hermes/*/*/*.lock
*.pid
.hermes/*.pid
.hermes/*/*.pid
.hermes/*/*/*.pid
.hermes/.update_*
.hermes/.restart_*
.hermes/.scratch_*
.hermes/.install_method
.hermes/logs
.hermes/logs/*
.hermes/interrupt_debug.log
.hermes/agent-hooks
.hermes/agent-hooks/*
.hermes/state.db
.hermes/state.db-shm
.hermes/state.db-wal
.hermes/state.db.malformed-backup-*
.hermes/kanban.db
.hermes/kanban.db-shm
.hermes/kanban.db-wal
.hermes/kanban.db.dispatch.lock
.hermes/kanban.db.init.lock
.hermes/kanban.db.malformed-backup-*
.hermes/response_store.db
.hermes/response_store.db-shm
.hermes/response_store.db-wal
.hermes/response_store.db.malformed-backup-*
EXCLUDES
}

# --- Preflight ---
[ -d "$SRC_DIR" ] || fail "source dir not found: $SRC_DIR"
for cmd in ssh scp tar sqlite3 find python3; do
    command -v "$cmd" >/dev/null 2>&1 || fail "missing required command: $cmd"
done

ssh -o BatchMode=yes -o ConnectTimeout=8 "${BACKUP_REMOTE_HOST}" \
    "mkdir -p '${BACKUP_REMOTE_DIR}' && test -w '${BACKUP_REMOTE_DIR}'" \
    >/dev/null 2>&1 \
    || fail "cannot write to ${BACKUP_REMOTE_HOST}:${BACKUP_REMOTE_DIR}"

mkdir -p "$STAGING_DIR" "$SQLITE_DUMP_DIR" \
    || fail "cannot create staging dirs under: $STAGING_DIR"

write_exclude_file "$EXCLUDE_FILE"

# --- SQLite consistent snapshots ---
SQLITE_DBS=(state.db kanban.db response_store.db)

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

log "phase 1/3: sqlite consistent snapshots"
for db in "${SQLITE_DBS[@]}"; do
    snapshot_sqlite "$db"
done

# --- Pack + Upload, wrapped in retry loop ---
pack_and_upload() {
    local attempt="$1"
    local tar_path="${STAGING_DIR}/.work-${attempt}-${STAMP}.tar.gz"
    local out_path="${STAGING_DIR}/${ARCHIVE_NAME}"

    log "attempt ${attempt}/${MAX_RETRIES}: packing -> ${out_path}"

    # Step A: 打无 sqlite 主文件的归档 (snapshot 会由 Python 步骤补上)
    if ! tar -czf "$tar_path" \
        -C "$HOME" \
        --exclude-from="$EXCLUDE_FILE" \
        .hermes
    then
        log "attempt ${attempt}: tar A failed"
        rm -f "$tar_path"
        return 1
    fi

    # Step B: Python 重建归档 - 把 snapshot 副本以原名 .hermes/<db>.db 写入
    # (绕开 BSD tar 无 --transform 且 gz 不支持 append 的限制)
    local has_snapshots=0
    for db in "${SQLITE_DBS[@]}"; do
        [ -f "${SQLITE_DUMP_DIR}/${db}" ] && has_snapshots=1 && break
    done

    if [ "$has_snapshots" = "1" ]; then
        local rebuild_out="${tar_path%.gz}.rebuild"
        local ok
        ok=$(python3 -c '
import os, sys, tarfile, gzip, shutil
src_gz, out_tar, dump_dir, src_root, *sqlite_dbs = sys.argv[1:]
replaced_basenames = set(sqlite_dbs)

tmp_tar = src_gz + ".untar"
with gzip.open(src_gz, "rb") as gz, open(tmp_tar, "wb") as t:
    shutil.copyfileobj(gz, t)

with tarfile.open(tmp_tar, "r") as src_tar, \
     tarfile.open(out_tar, "w") as dst_tar:
    for ti in src_tar:
        # 规范化 entry name: BSD tar -C $HOME .hermes 实际存的就是 .hermes/...
        # 但少数 entry 可能是绝对路径 (如系统生成的). 全部裁到以 .hermes 开头.
        name = ti.name
        idx = name.find(".hermes")
        if idx >= 0:
            name = name[idx:]
        else:
            # 找 db 名字的 fallback
            for db in sqlite_dbs:
                idx = name.find("/" + db)
                if idx >= 0:
                    name = ".hermes/" + db
                    break
        ti.name = name

        basename = os.path.basename(name)
        if basename in replaced_basenames:
            continue
        if ti.isfile():
            data = src_tar.extractfile(ti)
            dst_tar.addfile(ti, data)
        else:
            dst_tar.addfile(ti)

    # 追加 snapshot 副本, 路径用 .hermes/<db>.db
    for db in sqlite_dbs:
        full = os.path.join(dump_dir, db)
        if not os.path.isfile(full):
            continue
        ti = tarfile.TarInfo(name=f".hermes/{db}")
        ti.size = os.path.getsize(full)
        ti.mtime = int(os.path.getmtime(full))
        ti.mode = 0o644
        with open(full, "rb") as f:
            dst_tar.addfile(ti, f)

os.remove(tmp_tar)
final_gz = out_tar + ".gz"
with open(out_tar, "rb") as t, gzip.open(final_gz, "wb", compresslevel=6) as gz:
    shutil.copyfileobj(t, gz)
os.remove(out_tar)
shutil.move(final_gz, src_gz)
print("ok")
' "$tar_path" "$rebuild_out" "$SQLITE_DUMP_DIR" "$HOME" "${SQLITE_DBS[@]}" 2>&1)
        if [ "$ok" != "ok" ]; then
            log "attempt ${attempt}: python rebuild failed: ${ok}"
            rm -f "$tar_path" "${rebuild_out}" "${rebuild_out}.gz"
            return 1
        fi
        log "attempt ${attempt}: rebuilt archive with ${#SQLITE_DBS[@]} sqlite snapshot(s)"
    fi

    mv -f "$tar_path" "$out_path" || { log "attempt ${attempt}: mv failed"; return 1; }

    local asize
    asize=$(stat -f '%z' "$out_path" 2>/dev/null || stat -c '%s' "$out_path")
    log "attempt ${attempt}: archive ready (${asize} bytes)"

    # Upload
    log "attempt ${attempt}: scp -> ${BACKUP_REMOTE_HOST}"
    if ! scp -o BatchMode=yes -o ConnectTimeout=15 \
        "$out_path" \
        "${BACKUP_REMOTE_HOST}:${BACKUP_REMOTE_DIR}/${ARCHIVE_NAME}" \
        >/dev/null 2>&1
    then
        log "attempt ${attempt}: scp failed"
        return 1
    fi

    local rsize
    rsize=$(ssh -o BatchMode=yes "${BACKUP_REMOTE_HOST}" \
        "stat -c '%s' '${BACKUP_REMOTE_DIR}/${ARCHIVE_NAME}' 2>/dev/null" \
        2>/dev/null)
    if [ -z "$rsize" ] || [ "$rsize" != "$asize" ]; then
        log "attempt ${attempt}: remote size mismatch (local=${asize} remote=${rsize:-MISSING})"
        return 1
    fi
    log "attempt ${attempt}: remote verified (${rsize} bytes)"
    return 0
}

log "phase 2/3: pack + upload (up to ${MAX_RETRIES} attempts)"
attempt=1
while [ "$attempt" -le "$MAX_RETRIES" ]; do
    if pack_and_upload "$attempt"; then
        break
    fi
    if [ "$attempt" -eq "$MAX_RETRIES" ]; then
        fail "all ${MAX_RETRIES} attempts failed. last error above."
    fi
    local_idx=$((attempt - 1))
    delay=${RETRY_DELAYS[$local_idx]:-30}
    log "retrying in ${delay}s..."
    sleep "$delay"
    attempt=$((attempt + 1))
done

# --- Phase 3: rotation + cleanup ---
log "phase 3/3: rotation + cleanup"

ssh -o BatchMode=yes "${BACKUP_REMOTE_HOST}" \
    "cd '${BACKUP_REMOTE_DIR}' && \
     ls -1t hermes-*.tar.gz 2>/dev/null | \
     awk 'NR>\"${REMOTE_KEEP}\"' | \
     xargs -r rm -f" \
    >/dev/null 2>&1 \
    || log "WARN: remote rotation had issues (non-fatal)"

touch "$LOCAL_TMP"   # 保护本次包
find "$STAGING_DIR" -maxdepth 1 \
    -name 'hermes-*.tar.gz' \
    -mmin "+${LOCAL_TTL_MIN}" \
    -delete 2>/dev/null

REMAINING=$(ssh -o BatchMode=yes "${BACKUP_REMOTE_HOST}" \
    "ls -1 '${BACKUP_REMOTE_DIR}'/hermes-*.tar.gz 2>/dev/null | wc -l" \
    2>/dev/null)
log "done. local copy: ${LOCAL_TMP} (clears in ${LOCAL_TTL_MIN}m); remote retains ${REMAINING:-?} archive(s)"

exit 0
