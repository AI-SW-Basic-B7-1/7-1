#!/usr/bin/env bash
# 요청 ID별로 채팅 처리 이벤트와 민감정보 비기록을 확인합니다.

set -Eeuo pipefail
umask 077

CASE_NAME="${VERIFY_LOG_CASE:-}"
REQUEST_ID="${VERIFY_REQUEST_ID:-}"
EXPECTED_INSTANCE_ID="${EXPECTED_INSTANCE_ID:-}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$(cd -- "${SCRIPT_DIR}/../.." && pwd)}"
APP_LOG_DIR="${APP_LOG_DIR:-${PROJECT_DIR}/logs}"

fail() {
    printf '[실패] %s\n' "$*" >&2
    exit 1
}

[[ "$(id -u)" -eq 0 ]] || fail 'root 권한이 필요합니다.'
[[ "${EXPECTED_INSTANCE_ID}" =~ ^i-[0-9a-f]{17}$ ]] || fail '기대 테스트 EC2 ID가 올바르지 않습니다.'
[[ -f /etc/b7-1/e2e-test-instance && ! -L /etc/b7-1/e2e-test-instance ]] || fail '테스트 EC2 표식이 없습니다.'
[[ "$(stat -c '%U:%a' /etc/b7-1/e2e-test-instance)" == 'root:600' ]] || fail '테스트 EC2 표식의 소유자 또는 권한이 올바르지 않습니다.'
metadata_token="$(curl -fsS --connect-timeout 2 -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' http://169.254.169.254/latest/api/token 2>/dev/null || true)"
actual_instance="$(curl -fsS --connect-timeout 2 -H "X-aws-ec2-metadata-token: ${metadata_token}" http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null || true)"
unset metadata_token
[[ "${actual_instance}" == "${EXPECTED_INSTANCE_ID}" ]] || fail '현재 인스턴스가 지정 테스트 EC2와 다릅니다.'
[[ "${REQUEST_ID}" =~ ^[[:xdigit:]]{8}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{12}$ ]] || fail '요청 ID 형식이 올바르지 않습니다.'
[[ "${CASE_NAME}" =~ ^(success|ai-failure|db-read|db-write|auth-denied)$ ]] || fail '로그 검증 유형이 올바르지 않습니다.'

shopt -s nullglob
plain_files=("${APP_LOG_DIR}"/app.log "${APP_LOG_DIR}"/app.log.[0-9]*)
compressed_files=("${APP_LOG_DIR}"/app.log*.gz)
all_files=("${plain_files[@]}" "${compressed_files[@]}")
(( ${#all_files[@]} > 0 )) || fail '앱 로그를 찾을 수 없습니다.'

search_request_event() {
    local event="$1"
    if (( ${#plain_files[@]} > 0 )) && grep -hF -- "request_id=${REQUEST_ID}" "${plain_files[@]}" 2>/dev/null | grep -F -- "${event}" >/dev/null; then
        return 0
    fi
    if (( ${#compressed_files[@]} > 0 )) && zgrep -hF -- "request_id=${REQUEST_ID}" "${compressed_files[@]}" 2>/dev/null | grep -F -- "${event}" >/dev/null; then
        return 0
    fi
    return 1
}

require_event() {
    search_request_event "$1" || fail "요청 ID에 기대 이벤트가 없습니다: $1"
}

case "${CASE_NAME}" in
    success)
        for event in request_received ai_call_start ai_call_success db_save_success; do
            require_event "${event}"
        done
        ;;
    ai-failure)
        for event in request_received ai_call_start ai_call_failed; do
            require_event "${event}"
        done
        ;;
    db-read)
        require_event request_received
        require_event db_read_failed
        ;;
    db-write)
        for event in request_received ai_call_start ai_call_success db_save_failed; do
            require_event "${event}"
        done
        ;;
    auth-denied)
        search_request_event '' || fail '인증 거부 요청 ID가 앱 로그에 없습니다.'
        ;;
esac

case "${CASE_NAME}" in
    success) forbidden_events=(ai_call_failed db_read_failed db_save_failed) ;;
    ai-failure) forbidden_events=(ai_call_success db_save_success db_save_failed db_read_failed) ;;
    db-read) forbidden_events=(ai_call_start ai_call_success ai_call_failed db_save_success db_save_failed) ;;
    db-write) forbidden_events=(db_read_failed db_save_success) ;;
    auth-denied) forbidden_events=(ai_call_start ai_call_success ai_call_failed db_save_success db_save_failed db_read_failed) ;;
esac
for event in "${forbidden_events[@]}"; do
    if search_request_event "${event}"; then
        fail "요청 ID에서 발생하지 않아야 할 이벤트를 확인했습니다: ${event}"
    fi
done

if grep -hEi 'Bearer[[:space:]]+[A-Za-z0-9._~+/=-]{16,}|eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}|AIza[A-Za-z0-9_-]{20,}|(password|access_token|x-goog-api-key|secret_key|question|answer)=[^[:space:]]+' "${all_files[@]}" >/dev/null 2>&1; then
    fail '앱 로그에서 비밀값 또는 대화 원문 형태를 발견했습니다.'
fi

printf 'E2E_LOG_CASE_VERIFIED=%s request_id=%s\n' "${CASE_NAME}" "${REQUEST_ID}"
