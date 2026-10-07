#!/usr/bin/env bash
# B7-1 SQLite 온라인 백업 스크립트
# 실행 위치와 무관하게 현재 프로젝트의 data/chatbot.db를 백업합니다.

set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
DB_PATH="${DB_PATH:-${PROJECT_DIR}/data/chatbot.db}"
BACKUP_DIR="${BACKUP_DIR:-${HOME}/db_backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
BACKUP_TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_FILE="${BACKUP_DIR}/chatbot_backup_${BACKUP_TIMESTAMP}.db"

log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S%z')" "$*"
}

command -v sqlite3 >/dev/null 2>&1 || {
    log 'sqlite3 명령을 찾을 수 없습니다.'
    exit 1
}

mkdir -p "${BACKUP_DIR}"

if [[ ! -f "${DB_PATH}" ]]; then
    log "백업할 SQLite 파일이 아직 없습니다: ${DB_PATH}"
    exit 0
fi

sqlite3 "${DB_PATH}" ".backup '${BACKUP_FILE}'"
chmod 600 "${BACKUP_FILE}"

find "${BACKUP_DIR}" \
    -type f \
    -name 'chatbot_backup_*.db' \
    -mtime "+${RETENTION_DAYS}" \
    -delete

log "SQLite 백업 완료: ${BACKUP_FILE}"
