#!/usr/bin/env bash
# ~/.hermes/scripts/openviking-backup.sh
# Daily backup of ~/.openviking to node010:/data/ai/hermes-backup/yangtb/openviking/
# Schedule: 04:30 daily.  Retention: last 3 archives.
# Cron: no_agent=true, deliver=qqbot on failure.
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
        *) shift ;;
    esac
done

# --- Config ---
BACKUP_REMOTE_DIR="/data/ai/hermes-backup/yangtb/openviking"
BACKUP_REMOTE_HOST="node010"
STAGING_DIR="${TMPDIR:-/tmp}/openviking-backup-staging"
STAMP="$(date +%Y%m%d-%H%M%S)"
ARCHIVE_NAME="openviking-${STAMP}.tar.gz"
LOCAL_TMP="${STAGING_DIR}/${ARCHIVE_NAME}"
REMOTE_KEEP=3
LOCAL_TTL_MIN=60
MAX_RETRIES=3
RETRY_DELAYS=(5 15 30)
SRC_DIR="${HOME}/.openviking"
LOG_TAG="[openviking-backup]"

log()  {
    if [ "${BACKUP_QUIET:-0}" != "1" ]; then
        echo "${LOG_TAG} $*"
    fi
}
fail() { echo "${LOG_TAG} FAIL: $*" >&2; exit 1; }

# --- Preflight ---
[ -d "$SRC_DIR" ] || fail "source dir not found: $SRC_DIR"
for cmd in ssh scp tar; do
    command -v "$cmd" >/dev/null 2>&1 || fail "missing required command: $cmd"
done

ssh -o BatchMode=yes -o ConnectTimeout=8 "${BACKUP_REMOTE_HOST}" \
    "mkdir -p '${BACKUP_REMOTE_DIR}' && test -w '${BACKUP_REMOTE_DIR}'" \
    >/dev/null 2>&1 \
    || fail "cannot write to ${BACKUP_REMOTE_HOST}:${BACKUP_REMOTE_DIR}"

mkdir -p "$STAGING_DIR" || fail "cannot create staging dir: $STAGING_DIR"

# --- Pack + Upload, wrapped in retry loop ---
pack_and_upload() {
    local attempt="$1"
    local tar_path="${STAGING_DIR}/.work-${attempt}-${STAMP}.tar.gz"
    local out_path="${STAGING_DIR}/${ARCHIVE_NAME}"

    log "attempt ${attempt}/${MAX_RETRIES}: packing -> ${out_path}"

    if ! tar -czf "$tar_path" \
        -C "$HOME" \
        .openviking
    then
        log "attempt ${attempt}: tar failed"
        rm -f "$tar_path"
        return 1
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

log "phase 1/2: pack + upload (up to ${MAX_RETRIES} attempts)"
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

# --- Phase 2: rotation + cleanup ---
log "phase 2/2: rotation + cleanup"

ssh -o BatchMode=yes "${BACKUP_REMOTE_HOST}" \
    "cd '${BACKUP_REMOTE_DIR}' && \
     ls -1t openviking-*.tar.gz 2>/dev/null | \
     awk 'NR>\"${REMOTE_KEEP}\"' | \
     xargs -r rm -f" \
    >/dev/null 2>&1 \
    || log "WARN: remote rotation had issues (non-fatal)"

touch "$LOCAL_TMP"   # 保护本次包
find "$STAGING_DIR" -maxdepth 1 \
    -name 'openviking-*.tar.gz' \
    -mmin "+${LOCAL_TTL_MIN}" \
    -delete 2>/dev/null

REMAINING=$(ssh -o BatchMode=yes "${BACKUP_REMOTE_HOST}" \
    "ls -1 '${BACKUP_REMOTE_DIR}'/openviking-*.tar.gz 2>/dev/null | wc -l" \
    2>/dev/null)

if [ "${BACKUP_QUIET:-0}" = "1" ]; then
    : # success — stay silent
else
    log "done. local copy: ${LOCAL_TMP} (clears in ${LOCAL_TTL_MIN}m); remote retains ${REMAINING:-?} archive(s)"
fi

exit 0
