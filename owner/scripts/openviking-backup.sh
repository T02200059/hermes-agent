#!/usr/bin/env bash
# ~/.hermes/hermes-agent/owner/scripts/openviking-backup.sh
# Daily backup of OpenViking via `ov backup` -> node010
# Uses OpenViking's native .ovpack format (verified, not filesystem tar)
# Schedule: 04:30 daily.  Retention: last 3 archives.
# Cron: no_agent=true, deliver=qqbot on failure.
#
# Exit codes:
#   0 = success (silent when BACKUP_QUIET=1)
#   non-zero = failure (stderr delivered to QQ)
set -euo pipefail

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
ARCHIVE_NAME="openviking-${STAMP}.ovpack"
REMOTE_KEEP=3
LOCAL_TTL_MIN=60
MAX_RETRIES=3
RETRY_DELAYS=(5 15 30)
OVPACK_PATH="${STAGING_DIR}/${ARCHIVE_NAME}"
LOG_TAG="[openviking-backup]"

log()  {
    if [ "${BACKUP_QUIET:-0}" != "1" ]; then
        echo "${LOG_TAG} $*"
    fi
}
fail() { echo "${LOG_TAG} FAIL: $*" >&2; exit 1; }

# --- Preflight ---
for cmd in ssh scp docker; do
    command -v "$cmd" >/dev/null 2>&1 || fail "missing required command: $cmd"
done

# Check container is running
docker ps --format '{{.Names}}' | grep -q "^openviking$" || fail "openviking container not running"

ssh -o BatchMode=yes -o ConnectTimeout=8 "${BACKUP_REMOTE_HOST}" \
    "mkdir -p '${BACKUP_REMOTE_DIR}' && test -w '${BACKUP_REMOTE_DIR}'" \
    >/dev/null 2>&1 \
    || fail "cannot write to ${BACKUP_REMOTE_HOST}:${BACKUP_REMOTE_DIR}"

mkdir -p "$STAGING_DIR" || fail "cannot create staging dir: $STAGING_DIR"

# --- Phase 1: ov backup (inside container) ---
log "phase 1/3: ov backup"
docker exec openviking ov backup "/tmp/${ARCHIVE_NAME}" >/dev/null 2>&1 || fail "ov backup failed"

# Copy out of container
docker cp "openviking:/tmp/${ARCHIVE_NAME}" "${OVPACK_PATH}" || fail "docker cp failed"

# Verify size
LOCAL_SIZE=$(stat -f '%z' "${OVPACK_PATH}" 2>/dev/null || stat -c '%s' "${OVPACK_PATH}")
[ "${LOCAL_SIZE}" -gt 1000 ] || fail "ovpack too small (${LOCAL_SIZE} bytes) - backup may be empty"
log "ovpack ready: ${LOCAL_SIZE} bytes"

# --- Phase 2: Upload ---
upload_attempt() {
    local attempt="$1"
    log "attempt ${attempt}/${MAX_RETRIES}: scp -> ${BACKUP_REMOTE_HOST}"
    if ! scp -o BatchMode=yes -o ConnectTimeout=15 \
        "${OVPACK_PATH}" \
        "${BACKUP_REMOTE_HOST}:${BACKUP_REMOTE_DIR}/${ARCHIVE_NAME}" \
        >/dev/null 2>&1; then
        log "attempt ${attempt}: scp failed"
        return 1
    fi

    # Verify remote size
    local rsize
    rsize=$(ssh -o BatchMode=yes "${BACKUP_REMOTE_HOST}" \
        "stat -c '%s' '${BACKUP_REMOTE_DIR}/${ARCHIVE_NAME}' 2>/dev/null" \
        2>/dev/null)
    if [ -z "$rsize" ] || [ "$rsize" != "$LOCAL_SIZE" ]; then
        log "attempt ${attempt}: size mismatch (local=${LOCAL_SIZE} remote=${rsize:-MISSING})"
        return 1
    fi
    log "attempt ${attempt}: remote verified (${rsize} bytes)"
    return 0
}

log "phase 2/3: upload"
attempt=1
while [ "$attempt" -le "$MAX_RETRIES" ]; do
    if upload_attempt "$attempt"; then
        break
    fi
    if [ "$attempt" -eq "$MAX_RETRIES" ]; then
        fail "all ${MAX_RETRIES} attempts failed."
    fi
    local_idx=$((attempt - 1))
    delay=${RETRY_DELAYS[$local_idx]:-30}
    log "retrying in ${delay}s..."
    sleep "$delay"
    attempt=$((attempt + 1))
done

# --- Phase 3: Rotation + cleanup ---
log "phase 3/3: rotation + cleanup"

# Remove old ovpacks (keep newest REMOTE_KEEP)
ssh -o BatchMode=yes "${BACKUP_REMOTE_HOST}" \
    "cd '${BACKUP_REMOTE_DIR}' && \
     ls -1t openviking-*.ovpack 2>/dev/null | \
     awk 'NR>\"${REMOTE_KEEP}\"' | \
     xargs -r rm -f" \
    >/dev/null 2>&1 \
    || log "WARN: remote rotation had issues (non-fatal)"

# Cleanup old .tar.gz (legacy format)
ssh -o BatchMode=yes "${BACKUP_REMOTE_HOST}" \
    "rm -f '${BACKUP_REMOTE_DIR}'/openviking-*.tar.gz 2>/dev/null" \
    >/dev/null 2>&1 || true

# Cleanup local staging
find "$STAGING_DIR" -maxdepth 1 \
    -name 'openviking-*.ovpack' \
    -mmin "+${LOCAL_TTL_MIN}" \
    -delete 2>/dev/null

# Remove temp file from container
docker exec openviking rm -f "/tmp/${ARCHIVE_NAME}" 2>/dev/null || true

if [ "${BACKUP_QUIET:-0}" = "1" ]; then
    : # silent success
else
    REMAINING=$(ssh -o BatchMode=yes "${BACKUP_REMOTE_HOST}" \
        "ls -1 '${BACKUP_REMOTE_DIR}'/openviking-*.ovpack 2>/dev/null | wc -l" \
        2>/dev/null)
    log "done. local: ${OVPACK_PATH} (clears in ${LOCAL_TTL_MIN}m); remote retains ${REMAINING:-?} ovpack(s)"
fi

exit 0
