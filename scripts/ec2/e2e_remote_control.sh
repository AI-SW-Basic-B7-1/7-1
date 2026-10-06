#!/usr/bin/env bash
# 테스트 인스턴스의 임시 장애 설정을 SSM으로 적용하고 복원합니다.

set -Eeuo pipefail
umask 077

COMMAND="${1:-}"
RUN_ID="${2:-}"
MODE="${3:-}"
EXPECTED_INSTANCE_ID="${EXPECTED_INSTANCE_ID:-}"
ROOT_DIR='/var/lib/b7-1/e2e'
ACTIVE_FILE="${ROOT_DIR}/active-run"
SERVICE_NAME='chatbot.service'
UNIT_DIR='/etc/systemd/system/chatbot.service.d'
PROJECT_DIR="$(systemctl show "${SERVICE_NAME}" -p WorkingDirectory --value 2>/dev/null || true)"
APP_USER="$(systemctl show "${SERVICE_NAME}" -p User --value 2>/dev/null || true)"
[[ -n "${APP_USER}" ]] || APP_USER='ubuntu'
PREPARE_IN_PROGRESS=0
PREPARE_SUCCEEDED=0
PREPARE_STATE=''
PREPARE_CONTROL=''

fail() {
    printf '[실패] %s\n' "$*" >&2
    exit 1
}

cleanup_partial_prepare() {
    local result=$?
    if [[ "${PREPARE_IN_PROGRESS}" == 1 && "${PREPARE_SUCCEEDED}" != 1 ]]; then
        if [[ -f "${ACTIVE_FILE}" && ! -L "${ACTIVE_FILE}" && "$(cat "${ACTIVE_FILE}" 2>/dev/null || true)" == "${RUN_ID}" ]]; then
            rm -f -- "${ACTIVE_FILE}"
        fi
        [[ -n "${PREPARE_STATE}" && "${PREPARE_STATE}" == "${ROOT_DIR}/"* && -d "${PREPARE_STATE}" && ! -L "${PREPARE_STATE}" ]] && rm -rf -- "${PREPARE_STATE}"
        [[ -n "${PREPARE_CONTROL}" && -f "${PREPARE_CONTROL}" && ! -L "${PREPARE_CONTROL}" ]] && rm -f -- "${PREPARE_CONTROL}"
    fi
    return "${result}"
}
trap cleanup_partial_prepare EXIT

acquire_operation_lock() {
    exec 9>/run/lock/b7-1-e2e-operation.lock
    flock -n 9 || fail '배포 또는 다른 E2E 작업이 실행 중입니다.'
}

verify_instance() {
    [[ "$(id -u)" -eq 0 ]] || fail 'root 권한이 필요합니다.'
    [[ "${EXPECTED_INSTANCE_ID}" =~ ^i-[0-9a-f]{17}$ ]] || fail '기대 인스턴스 ID가 올바르지 않습니다.'
    [[ -f /etc/b7-1/e2e-test-instance && ! -L /etc/b7-1/e2e-test-instance ]] || fail '테스트 EC2 표식이 없습니다.'
    [[ "$(stat -c '%U:%a' /etc/b7-1/e2e-test-instance)" == 'root:600' ]] || fail '테스트 EC2 표식의 소유자 또는 권한이 올바르지 않습니다.'
    local token actual_instance
    token="$(curl -fsS --connect-timeout 2 -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' http://169.254.169.254/latest/api/token 2>/dev/null || true)"
    [[ -n "${token}" ]] || fail '인스턴스 메타데이터 토큰을 얻지 못했습니다.'
    actual_instance="$(curl -fsS --connect-timeout 2 -H "X-aws-ec2-metadata-token: ${token}" http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null || true)"
    unset token
    [[ "${actual_instance}" == "${EXPECTED_INSTANCE_ID}" ]] || fail '현재 서버가 지정 테스트 EC2와 일치하지 않습니다.'
}

validate_run_id() {
    [[ "${RUN_ID}" =~ ^[A-Za-z0-9_-]{1,100}$ ]] || fail '실행 ID 형식이 올바르지 않습니다.'
}

state_path() {
    printf '%s/%s' "${ROOT_DIR}" "${RUN_ID}"
}

control_path() {
    printf '/usr/local/sbin/b7-1-e2e-control-%s' "${RUN_ID}"
}

dropin_path() {
    printf '%s/95-b7-1-e2e-%s.conf' "${UNIT_DIR}" "${RUN_ID}"
}

timer_name() {
    printf 'b7-1-e2e-restore-%s.timer' "${RUN_ID}"
}

proxy_name() {
    printf 'b7-1-e2e-proxy-%s.service' "${RUN_ID}"
}

prepare_run() {
    verify_instance
    validate_run_id
    [[ -n "${PROJECT_DIR}" && -d "${PROJECT_DIR}" ]] || fail '서비스 프로젝트 경로가 없습니다.'
    [[ "${PROJECT_DIR}" =~ ^/[A-Za-z0-9._/-]+$ ]] || fail '서비스 프로젝트 경로에 허용하지 않는 문자가 있습니다.'
    local state control current_revision
    state="$(state_path)"
    control="$(control_path)"
    [[ ! -e "${ACTIVE_FILE}" && ! -L "${ACTIVE_FILE}" ]] || fail '다른 E2E 제어 실행이 이미 활성화되어 있습니다.'
    [[ ! -e "${state}" && ! -L "${state}" ]] || fail '같은 실행 ID의 이전 상태가 남아 있습니다.'
    [[ ! -e "${control}" && ! -L "${control}" ]] || fail '같은 실행 ID의 원격 제어 파일이 이미 있습니다.'
    PREPARE_IN_PROGRESS=1
    PREPARE_STATE="${state}"
    PREPARE_CONTROL="${control}"
    install -d -o root -g root -m 711 "${ROOT_DIR}" "${state}"
    install -d -o root -g root -m 755 "${UNIT_DIR}"
    install -o root -g root -m 700 "${BASH_SOURCE[0]}" "${control}"
    install -o root -g root -m 700 "${SCRIPT_DIR:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)}/e2e_delay_proxy.py" "${state}/delay_proxy.py"
    printf '%s\n' "${RUN_ID}" > "${ACTIVE_FILE}"
    chmod 600 "${ACTIVE_FILE}"
    printf '%s\n' "${EXPECTED_INSTANCE_ID}" > "${state}/instance-id"
    printf '%s\n' "${PROJECT_DIR}" > "${state}/project-dir"
    current_revision="$(git -c safe.directory="${PROJECT_DIR}" -C "${PROJECT_DIR}" rev-parse HEAD 2>/dev/null || true)"
    printf '%s\n' "${current_revision:-unknown}" > "${state}/baseline-revision"
    PREPARE_SUCCEEDED=1
    printf 'E2E_CONTROL_PREPARED=1 instance=%s revision=%s\n' "${EXPECTED_INSTANCE_ID}" "${current_revision:-unknown}"
}

arm_run() {
    verify_instance
    validate_run_id
    [[ "${RUN_ID}" == "$(cat "${ACTIVE_FILE}" 2>/dev/null || true)" ]] || fail '활성 실행 ID가 일치하지 않습니다.'
    [[ "${MODE}" =~ ^(jwt-expiry|gemini-error|proxy-timeout|db-read|db-write|observe-context)$ ]] || fail '지원하지 않는 장애 모드입니다.'
    local state control unit_file timer proxy context_file context_dir
    state="$(state_path)"
    control="$(control_path)"
    unit_file="$(dropin_path)"
    timer="$(timer_name)"
    proxy="$(proxy_name)"
    context_dir="${state}/context"
    context_file="${context_dir}/context-observed.json"
    [[ -f "${control}" && -f "${state}/instance-id" ]] || fail 'E2E 원복 보호 파일이 없습니다.'
    [[ ! -e "${unit_file}" && ! -L "${unit_file}" ]] || fail '같은 실행의 임시 서비스 설정이 이미 있습니다.'
    systemd-run --collect --quiet --unit="${timer%.timer}" --on-active=20m --setenv="EXPECTED_INSTANCE_ID=${EXPECTED_INSTANCE_ID}" "${control}" restore "${RUN_ID}" || fail '자동 원복 타이머를 등록하지 못했습니다.'
    if [[ "${MODE}" == observe-context ]]; then
        install -d -o "${APP_USER}" -g "${APP_USER}" -m 700 "${context_dir}"
    fi
    {
        printf '# 시험 실행 ID: %s\n' "${RUN_ID}"
        printf '[Service]\n'
        case "${MODE}" in
            jwt-expiry)
                printf 'Environment="ACCESS_TOKEN_EXPIRE_MINUTES=1"\n'
                ;;
            gemini-error)
                printf 'Environment="GEMINI_MODEL=e2e-invalid-model-%s"\n' "${RUN_ID}"
                ;;
            proxy-timeout)
                systemd-run --collect --quiet --unit="${proxy%.service}" --property=RuntimeMaxSec=20m /usr/bin/python3 "${state}/delay_proxy.py" --port 18765 --delay 12 || fail '루프백 시간 초과 프록시를 시작하지 못했습니다.'
                printf 'Environment="HTTPS_PROXY=http://127.0.0.1:18765"\n'
                printf 'Environment="NO_PROXY="\n'
                printf 'Environment="ALL_PROXY="\n'
                ;;
            db-read|db-write|observe-context)
                printf 'Environment="B7_1_E2E_FAULT_MODE=%s"\n' "${MODE}"
                if [[ "${MODE}" == observe-context ]]; then
                    printf 'Environment="B7_1_E2E_CONTEXT_FILE=%s"\n' "${context_file}"
                fi
                printf 'ExecStart=\n'
                printf 'ExecStart=%s/venv/bin/uvicorn scripts.ec2.e2e_fault_asgi:app --host 127.0.0.1 --port 8000\n' "${PROJECT_DIR}"
                ;;
        esac
    } > "${unit_file}"
    chown root:root "${unit_file}"
    chmod 600 "${unit_file}"
    if ! systemctl daemon-reload || ! systemctl restart "${SERVICE_NAME}"; then
        restore_run || true
        fail '임시 설정을 적용한 서비스 재기동이 실패했습니다.'
    fi
    for attempt in $(seq 1 30); do
        if curl -fsS --max-time 2 http://127.0.0.1:8000/api/health >/dev/null; then
            printf 'E2E_FAULT_ARMED=%s\n' "${MODE}"
            return 0
        fi
        sleep 1
    done
    restore_run || true
    fail '임시 설정 서비스의 내부 health 확인이 실패했습니다.'
}

restore_run() {
    verify_instance
    validate_run_id
    [[ -e "${ACTIVE_FILE}" ]] || {
        printf 'E2E_FAULT_ALREADY_RESTORED=1 run_id=%s\n' "${RUN_ID}"
        return 0
    }
    [[ ! -L "${ACTIVE_FILE}" && "${RUN_ID}" == "$(cat "${ACTIVE_FILE}" 2>/dev/null || true)" ]] || fail '활성 실행 표식이 안전하지 않거나 실행 ID가 다릅니다.'
    local state control unit_file proxy timer
    state="$(state_path)"
    control="$(control_path)"
    unit_file="$(dropin_path)"
    proxy="$(proxy_name)"
    timer="$(timer_name)"
    if [[ -L "${unit_file}" ]]; then
        fail '임시 서비스 설정이 심볼릭 링크입니다.'
    fi
    if [[ -e "${unit_file}" ]]; then
        [[ -f "${unit_file}" ]] || fail '임시 서비스 설정이 일반 파일이 아닙니다.'
        grep -Fqx "# 시험 실행 ID: ${RUN_ID}" "${unit_file}" || fail '현재 서비스 설정이 이 실행의 파일이 아닙니다.'
    fi
    systemctl stop "${timer}" >/dev/null 2>&1 || true
    systemctl stop "${proxy}" >/dev/null 2>&1 || true
    rm -f -- "${unit_file}"
    systemctl daemon-reload || fail '원복 뒤 systemd 설정 재읽기에 실패했습니다.'
    systemctl restart "${SERVICE_NAME}" >/dev/null 2>&1 || true
    local restored=0
    for attempt in $(seq 1 60); do
        if systemctl is-active --quiet "${SERVICE_NAME}" && curl -fsS --max-time 5 http://127.0.0.1:8000/api/health >/dev/null; then
            restored=1
            break
        fi
        sleep 2
    done
    [[ "${restored}" == 1 ]] || fail '원복 뒤 원본 서비스 health가 제한 시간 안에 회복되지 않았습니다.'
    rm -f -- "${ACTIVE_FILE}"
    rm -rf -- "${state}"
    rm -f -- "${control}"
    printf 'E2E_FAULT_RESTORED=1 run_id=%s\n' "${RUN_ID}"
}

show_counts() {
    verify_instance
    [[ -n "${PROJECT_DIR}" && -f "${PROJECT_DIR}/.env" ]] || fail '서비스 환경 파일이 없습니다.'
    local database_url database_path
    database_url="$(sed -n 's/^DATABASE_URL=//p' "${PROJECT_DIR}/.env" | head -n 1)"
    [[ "${database_url}" == sqlite:///* ]] || fail 'SQLite DATABASE_URL 형식을 확인하지 못했습니다.'
    database_path="${database_url#sqlite:///}"
    [[ "${database_path}" == /* ]] || database_path="${PROJECT_DIR}/${database_path}"
    [[ -f "${database_path}" && ! -L "${database_path}" ]] || fail 'SQLite 파일이 없습니다.'
    python3 - "${database_path}" <<'PY'
import json
import sqlite3
import sys

connection = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
conversations = connection.execute("SELECT count(*) FROM conversations").fetchone()[0]
chat_logs = connection.execute("SELECT count(*) FROM chat_logs").fetchone()[0]
connection.close()
print(json.dumps({"integrity": integrity, "conversations": conversations, "chat_logs": chat_logs}, separators=(",", ":")))
PY
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
case "${COMMAND}" in
    prepare) acquire_operation_lock; prepare_run ;;
    arm) acquire_operation_lock; arm_run ;;
    restore) acquire_operation_lock; restore_run ;;
    counts) show_counts ;;
    *) fail '사용법: e2e_remote_control.sh {prepare|arm|restore|counts} RUN_ID [MODE]' ;;
esac
