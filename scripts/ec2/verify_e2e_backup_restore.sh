#!/usr/bin/env bash
# 앱 사용자로 SQLite 온라인 백업을 만들고 별도 사본에서 쓰기를 검증합니다.

set -Eeuo pipefail
umask 077

RUN_ID="${E2E_RUN_ID:-}"
EXPECTED_INSTANCE_ID="${EXPECTED_INSTANCE_ID:-}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(systemctl show chatbot.service -p WorkingDirectory --value)"
APP_USER="$(systemctl show chatbot.service -p User --value)"
APP_USER="${APP_USER:-ubuntu}"
WORK_ROOT='/var/lib/b7-1/e2e'

fail() {
    printf '[실패] %s\n' "$*" >&2
    exit 1
}

[[ "$(id -u)" -eq 0 ]] || fail 'root 권한이 필요합니다.'
[[ "${RUN_ID}" =~ ^[A-Za-z0-9_-]{1,100}$ ]] || fail '실행 ID가 올바르지 않습니다.'
[[ "${EXPECTED_INSTANCE_ID}" =~ ^i-[0-9a-f]{17}$ ]] || fail '테스트 EC2 ID가 올바르지 않습니다.'
[[ -f /etc/b7-1/e2e-test-instance && ! -L /etc/b7-1/e2e-test-instance ]] || fail '테스트 EC2 표식이 없습니다.'
[[ "$(stat -c '%U:%a' /etc/b7-1/e2e-test-instance)" == 'root:600' ]] || fail '테스트 EC2 표식 권한이 올바르지 않습니다.'
metadata_token="$(curl -fsS --connect-timeout 2 -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' http://169.254.169.254/latest/api/token 2>/dev/null || true)"
actual_instance="$(curl -fsS --connect-timeout 2 -H "X-aws-ec2-metadata-token: ${metadata_token}" http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null || true)"
unset metadata_token
[[ "${actual_instance}" == "${EXPECTED_INSTANCE_ID}" ]] || fail '현재 인스턴스가 지정 테스트 EC2와 다릅니다.'
[[ -d "${PROJECT_DIR}" && ! -L "${PROJECT_DIR}" ]] || fail '서비스 프로젝트 경로가 없습니다.'
[[ -f "${PROJECT_DIR}/.env" && ! -L "${PROJECT_DIR}/.env" ]] || fail '서비스 환경 파일이 없습니다.'
[[ -d "${WORK_ROOT}" && ! -L "${WORK_ROOT}" ]] || fail 'E2E 보호 경로가 없습니다.'
WORK_DIR="${WORK_ROOT}/backup-${RUN_ID}"
[[ ! -e "${WORK_DIR}" && ! -L "${WORK_DIR}" ]] || fail '같은 실행의 백업 검증 자료가 이미 있습니다.'
install -o "${APP_USER}" -g "${APP_USER}" -m 700 -d "${WORK_DIR}"
cleanup() {
    local result=$?
    trap - EXIT
    if [[ "${WORK_DIR}" == "${WORK_ROOT}"/backup-* && -d "${WORK_DIR}" && ! -L "${WORK_DIR}" ]]; then
        rm -rf -- "${WORK_DIR}"
    fi
    exit "${result}"
}
trap cleanup EXIT
BACKUP_DIR="${WORK_DIR}/backups"
install -o "${APP_USER}" -g "${APP_USER}" -m 700 -d "${BACKUP_DIR}"

database_url="$("${PROJECT_DIR}/venv/bin/python" - "${PROJECT_DIR}/.env" <<'PY'
import sys
from dotenv import dotenv_values

print(dotenv_values(sys.argv[1]).get("DATABASE_URL", ""))
PY
)"
[[ "${database_url}" == sqlite:///* ]] || fail 'SQLite 데이터베이스 경로 형식을 확인하지 못했습니다.'
database_path="${database_url#sqlite:///}"
[[ "${database_path}" == /* ]] || database_path="${PROJECT_DIR}/${database_path}"
database_path="$(realpath -e -- "${database_path}")"
[[ -f "${database_path}" && ! -L "${database_path}" ]] || fail 'SQLite 데이터베이스 파일이 없습니다.'
timestamp="$(date '+%Y%m%d_%H%M%S')"
backup_file="${BACKUP_DIR}/e2e_${RUN_ID}_${timestamp}.db"
runuser -u "${APP_USER}" -- env \
    HOME="$(getent passwd "${APP_USER}" | cut -d: -f6)" \
    DB_PATH="${database_path}" BACKUP_DIR="${BACKUP_DIR}" \
    BACKUP_PREFIX="e2e_${RUN_ID}" BACKUP_TIMESTAMP="${timestamp}" REQUIRE_DB=1 \
    bash "${PROJECT_DIR}/scripts/ec2/backup_db.sh" >/dev/null
[[ -f "${backup_file}" && ! -L "${backup_file}" ]] || fail '온라인 DB 백업 파일을 만들지 못했습니다.'
install -o "${APP_USER}" -g "${APP_USER}" -m 600 "${backup_file}" "${WORK_DIR}/restored-copy.db"

python3 - "${database_path}" "${backup_file}" <<'PY'
import hashlib
import json
import sqlite3
import sys

def summarize(path):
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    conversations = connection.execute("SELECT count(*) FROM conversations").fetchone()[0]
    rows = connection.execute("SELECT question, response FROM chat_logs ORDER BY chat_log_id").fetchall()
    digest = hashlib.sha256()
    for question, response in rows:
        digest.update(question.encode("utf-8"))
        digest.update(b"\0")
        digest.update(response.encode("utf-8"))
        digest.update(b"\0")
    connection.close()
    return integrity, not foreign_keys, conversations, len(rows), digest.hexdigest()

source = summarize(sys.argv[1])
backup = summarize(sys.argv[2])
if source != backup or source[0] != "ok" or not source[1]:
    raise SystemExit("원본 DB와 백업 내용·무결성이 일치하지 않습니다.")
print(json.dumps({"integrity": "ok", "foreign_keys": "ok", "conversations": source[2], "chat_logs": source[3]}))
PY

runuser -u "${APP_USER}" -- python3 - "${WORK_DIR}/restored-copy.db" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
connection.execute("BEGIN IMMEDIATE")
connection.execute("CREATE TABLE e2e_write_probe (probe_id INTEGER PRIMARY KEY)")
connection.execute("INSERT INTO e2e_write_probe DEFAULT VALUES")
connection.commit()
connection.execute("DROP TABLE e2e_write_probe")
connection.commit()
integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
connection.close()
if integrity != "ok":
    raise SystemExit("복원 사본에서 읽기·쓰기 확인에 실패했습니다.")
PY

python3 - "${database_path}" "${WORK_DIR}/restored-copy.db" <<'PY'
import json
import sqlite3
import sys

def counts(path):
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    values = (
        connection.execute("PRAGMA integrity_check").fetchone()[0],
        connection.execute("SELECT count(*) FROM conversations").fetchone()[0],
        connection.execute("SELECT count(*) FROM chat_logs").fetchone()[0],
    )
    connection.close()
    return values

source = counts(sys.argv[1])
restored = counts(sys.argv[2])
if source != restored or source[0] != "ok":
    raise SystemExit("복원 사본 확인 뒤 원본 DB 또는 행 수가 달라졌습니다.")
print(json.dumps({"integrity": "ok", "conversations": source[1], "chat_logs": source[2], "writable_copy": True}))
PY

printf 'E2E_BACKUP_RESTORE_VERIFIED=1\n'
