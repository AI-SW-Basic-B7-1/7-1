#!/usr/bin/env bash
# B7-1 SQLite 온라인 백업 스크립트
# 애플리케이션과 동일한 DB_PATH를 받아 백업 경로를 명확히 합니다.

set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
DB_PATH="${DB_PATH:-}"
BACKUP_DIR="${BACKUP_DIR:-${HOME}/db_backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
BACKUP_PREFIX="${BACKUP_PREFIX:-chatbot_backup}"
BACKUP_TIMESTAMP="${BACKUP_TIMESTAMP:-$(date +%Y%m%d_%H%M%S)}"
REQUIRE_DB="${REQUIRE_DB:-0}"

fail() {
    printf '[실패] %s\n' "$*" >&2
    exit 1
}

[[ -n "${DB_PATH}" ]] || fail 'DB_PATH를 명시해야 합니다.'
[[ "${RETENTION_DAYS}" =~ ^[0-9]+$ ]] || fail 'RETENTION_DAYS는 숫자여야 합니다.'
[[ "${BACKUP_PREFIX}" =~ ^[A-Za-z0-9_-]+$ ]] || fail 'BACKUP_PREFIX 형식이 올바르지 않습니다.'
[[ "${BACKUP_TIMESTAMP}" =~ ^[0-9]{8}_[0-9]{6}$ ]] || fail 'BACKUP_TIMESTAMP 형식이 올바르지 않습니다.'
[[ "${REQUIRE_DB}" == '0' || "${REQUIRE_DB}" == '1' ]] || fail 'REQUIRE_DB는 0 또는 1이어야 합니다.'
[[ "${BACKUP_DIR}" != *"'"* && "${BACKUP_DIR}" != *$'\n'* ]] || fail 'BACKUP_DIR에 지원하지 않는 문자가 있습니다.'

if [[ "${DB_PATH}" != /* ]]; then
    DB_PATH="${PROJECT_DIR}/${DB_PATH}"
fi
BACKUP_FILE="${BACKUP_DIR}/${BACKUP_PREFIX}_${BACKUP_TIMESTAMP}.db"

log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S%z')" "$*"
}

command -v sqlite3 >/dev/null 2>&1 || fail 'sqlite3 명령을 찾을 수 없습니다.'
mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

if [[ ! -f "${DB_PATH}" ]]; then
    if [[ "${REQUIRE_DB}" == '1' ]]; then
        fail "백업할 SQLite 파일이 없습니다: ${DB_PATH}"
    fi
    log "백업할 SQLite 파일이 아직 없습니다: ${DB_PATH}"
    exit 0
fi

temporary_backup="$(mktemp "${BACKUP_FILE}.tmp.XXXXXXXX")"
trap 'rm -f -- "${temporary_backup}"' EXIT
sqlite3 "${DB_PATH}" ".backup '${temporary_backup}'"
chmod 600 "${temporary_backup}"
integrity_result="$(sqlite3 "${temporary_backup}" 'PRAGMA integrity_check;')"
[[ "${integrity_result}" == 'ok' ]] || fail "백업 파일 무결성 검사에 실패했습니다: ${integrity_result}"
mv -f -- "${temporary_backup}" "${BACKUP_FILE}"
trap - EXIT

find "${BACKUP_DIR}" \
    -type f \
    \( -name 'chatbot_backup_*.db' -o -name 'predeploy_*.db' \) \
    -mtime "+${RETENTION_DAYS}" \
    -delete

log "SQLite 백업 완료: ${BACKUP_FILE}"
