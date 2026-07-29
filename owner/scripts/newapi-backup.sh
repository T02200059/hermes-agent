#!/usr/bin/env bash
# ~/.hermes/scripts/newapi-backup.sh
# Daily backup of NewAPI (MySQL + app data + config) on node010.
# All work done remotely via a SINGLE SSH session (multiplexed).
# Schedule: 05:00 daily.  Retention: last 3 archives each.
# Cron: no_agent=true, deliver=qqbot on failure.
#
# Backup contents (stored under node010:/data/ai/hermes-backup/yangtb/newapi/):
#   1. MySQL dump: newapi-YYYYMMDD_HHMMSS.sql.gz (via docker compose backup service)
#   2. App data:   newapi-data-YYYYMMDD-HHMMSS.tar.gz (newapi-data/ + compose config)
set -u
set -o pipefail

REMOTE_HOST="node010"
REMOTE_BASE="/data/ai/newapi"
REMOTE_BACKUPS="/data/ai/hermes-backup/yangtb/newapi"
STAMP="$(date +%Y%m%d-%H%M%S)"
MYSQL_STAMP="$(date +%Y%m%d_%H%M%S)"
MYSQL_ARCHIVE="newapi-${MYSQL_STAMP}.sql.gz"
DATA_ARCHIVE="newapi-data-${STAMP}.tar.gz"
REMOTE_KEEP=3
LOG_TAG="[newapi-backup]"

log()  {
    if [ "${BACKUP_QUIET:-0}" != "1" ]; then
        echo "${LOG_TAG} $*"
    fi
}
fail() { echo "${LOG_TAG} FAIL: $*" >&2; exit 1; }

# --- Single SSH session: run all remote work in one heredoc ---
log "starting backup (single SSH session)"

# In quiet mode, suppress remote stdout (success logs). stderr still flows to fail().
# Use process substitution to avoid duplicating the heredoc.
if [ "${BACKUP_QUIET:-0}" = "1" ]; then
    exec 3>/dev/null
else
    exec 3>&1
fi

ssh -o BatchMode=yes -o ConnectTimeout=15 "${REMOTE_HOST}" bash -s >&3 <<REMOTE_SCRIPT || { exec 3>&-; fail "remote execution failed"; }
set -e
cd '${REMOTE_BASE}'

# Phase 1: MySQL dump
echo "[remote] MySQL dump..."
docker compose run --rm backup 2>&1 | tail -3

# Phase 2: tar app data + config
echo "[remote] tar app data..."
tar -czf '${REMOTE_BACKUPS}/${DATA_ARCHIVE}' \
    newapi-data/ \
    docker-compose.yaml \
    safe-entrypoint.sh

# Phase 3: rotation (keep last ${REMOTE_KEEP})
cd '${REMOTE_BACKUPS}'
ls -1t newapi-????????_??????.sql.gz 2>/dev/null | awk 'NR>${REMOTE_KEEP}' | xargs -r rm -f
ls -1t newapi-data-*.tar.gz 2>/dev/null | awk 'NR>${REMOTE_KEEP}' | xargs -r rm -f

# Phase 4: report
MYSQL_SIZE=\$(stat -c '%s' '${MYSQL_BACKUPS:-/dev/null}' 2>/dev/null || ls -1t newapi-????????_??????.sql.gz 2>/dev/null | head -1 | xargs stat -c '%s' 2>/dev/null || echo "?")
DATA_SIZE=\$(stat -c '%s' '${DATA_ARCHIVE}' 2>/dev/null || echo "?")
MYSQL_COUNT=\$(ls -1 newapi-????????_??????.sql.gz 2>/dev/null | wc -l)
DATA_COUNT=\$(ls -1 newapi-data-*.tar.gz 2>/dev/null | wc -l)
echo "[remote] done. mysql: \${MYSQL_COUNT} archive(s) (\${MYSQL_SIZE} bytes), data: \${DATA_COUNT} archive(s) (\${DATA_SIZE} bytes)"
REMOTE_SCRIPT
exec 3>&-

log "done"
exit 0
