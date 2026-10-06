#!/usr/bin/env bash
# 테스트 EC2에서 로그 회전 전후의 앱·Nginx 요청 ID 연결과 쿼리 비기록을 확인합니다.

set -Eeuo pipefail
umask 077

VERIFY_BASE_URL="${VERIFY_BASE_URL:-${1:-}}"
VERIFY_BASE_URL="${VERIFY_BASE_URL%/}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$(cd -- "${SCRIPT_DIR}/../.." && pwd)}"
APP_LOG_DIR="${APP_LOG_DIR:-${PROJECT_DIR}/logs}"
NGINX_LOG_DIR="${NGINX_LOG_DIR:-/var/log/nginx/b7-1}"
LOGROTATE_FILE="${LOGROTATE_FILE:-/etc/logrotate.d/b7-1}"
VERIFY_CHAT_REQUEST_ID="${VERIFY_CHAT_REQUEST_ID:-}"
EXPECTED_INSTANCE_ID="${EXPECTED_INSTANCE_ID:-}"

[[ "$(id -u)" -eq 0 ]] || { printf '%s\n' 'root 권한이 필요합니다.' >&2; exit 1; }
[[ -f /etc/b7-1/e2e-test-instance && ! -L /etc/b7-1/e2e-test-instance ]] || {
    printf '%s\n' '강제 로그 회전 검증은 표시된 테스트 EC2에서만 실행할 수 있습니다.' >&2
    exit 1
}
[[ "$(stat -c '%U:%a' /etc/b7-1/e2e-test-instance)" == 'root:600' ]] || {
    printf '%s\n' '테스트 EC2 표시 파일은 root 소유 600 권한이어야 합니다.' >&2
    exit 1
}
[[ "${EXPECTED_INSTANCE_ID}" =~ ^i-[0-9a-f]{17}$ ]] || {
    printf '%s\n' '기대 테스트 EC2 ID가 올바르지 않습니다.' >&2
    exit 1
}
metadata_token="$(curl -fsS --connect-timeout 2 -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' http://169.254.169.254/latest/api/token 2>/dev/null || true)"
actual_instance="$(curl -fsS --connect-timeout 2 -H "X-aws-ec2-metadata-token: ${metadata_token}" http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null || true)"
unset metadata_token
[[ "${actual_instance}" == "${EXPECTED_INSTANCE_ID}" ]] || {
    printf '%s\n' '현재 인스턴스가 지정 테스트 EC2와 다릅니다.' >&2
    exit 1
}
[[ "${VERIFY_BASE_URL}" =~ ^https://([A-Za-z0-9.-]+)(:443)?$ ]] || {
    printf '%s\n' '검증 주소는 HTTPS 도메인 주소여야 합니다.' >&2
    exit 1
}
DOMAIN="${BASH_REMATCH[1]}"
[[ -f "${LOGROTATE_FILE}" ]] || { printf '%s\n' '로그 회전 설정을 찾을 수 없습니다.' >&2; exit 1; }
[[ -f "${APP_LOG_DIR}/app.log" && -f "${NGINX_LOG_DIR}/nginx_access.log" ]] || {
    printf '%s\n' '앱 또는 Nginx 활성 로그 파일을 찾을 수 없습니다.' >&2
    exit 1
}

WORK_DIR="$(mktemp -d)"
cleanup() {
    rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

CURL_RESOLVE=(--resolve "${DOMAIN}:443:127.0.0.1")

search_app_logs() {
    local mode="$1"
    local pattern="$2"
    local plain_files=()
    local compressed_files=()
    local path

    shopt -s nullglob
    for path in "${APP_LOG_DIR}"/app.log "${APP_LOG_DIR}"/app.log.[0-9]*; do
        [[ -f "${path}" && "${path}" != *.gz ]] && plain_files+=("${path}")
    done
    compressed_files=("${APP_LOG_DIR}"/app.log*.gz)
    if (( ${#plain_files[@]} > 0 )) && grep -h "${mode}" -- "${pattern}" "${plain_files[@]}" 2>/dev/null; then
        return 0
    fi
    if (( ${#compressed_files[@]} > 0 )) && zgrep -h "${mode}" -- "${pattern}" "${compressed_files[@]}" 2>/dev/null; then
        return 0
    fi
    return 1
}

assert_chat_events() {
    local request_id="$1"
    local start_entry
    local user_id

    [[ "${request_id}" =~ ^[[:xdigit:]]{8}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{12}$ ]] || {
        printf '%s\n' '브라우저가 전달한 채팅 요청 ID가 올바르지 않습니다.' >&2
        return 1
    }
    start_entry="$(search_app_logs -F 'ai_call_start user_id=' | grep -F "request_id=${request_id}" | tail -n 1 || true)"
    user_id="$(sed -n 's/.*ai_call_start user_id=\([^[:space:]]*\).*/\1/p' <<<"${start_entry}")"
    [[ "${user_id}" =~ ^[0-9]+$ ]] || {
        printf '%s\n' 'AI 시작 로그에서 사용자 ID를 확인하지 못했습니다.' >&2
        return 1
    }
    search_app_logs -F "request_received user_id=${user_id} path=/api/chat request_id=${request_id}" >/dev/null || {
        printf '%s\n' '채팅 요청 수신 로그를 확인하지 못했습니다.' >&2
        return 1
    }
    [[ -n "${start_entry}" ]] || {
        printf '%s\n' 'AI 호출 시작 로그를 확인하지 못했습니다.' >&2
        return 1
    }
    search_app_logs -F "ai_call_success request_id=${request_id}" >/dev/null || {
        printf '%s\n' 'AI 호출 성공 로그를 확인하지 못했습니다.' >&2
        return 1
    }
    search_app_logs -E "db_save_success user_id=${user_id} chat_id=[0-9]+ request_id=${request_id}" >/dev/null || {
        printf '%s\n' '대화 저장 성공 로그를 확인하지 못했습니다.' >&2
        return 1
    }
}

request_id_for_probe() {
    local probe="$1"
    local label="$2"
    local headers="${WORK_DIR}/${label}.headers"
    local status=''
    local request_id=''

    for ((attempt=1; attempt<=20; attempt++)); do
        if status="$(curl "${CURL_RESOLVE[@]}" -fsS --max-time 5 -D "${headers}" -o /dev/null -w '%{http_code}' "${VERIFY_BASE_URL}/api/health?probe=${probe}")" && [[ "${status}" == '200' ]]; then
            request_id="$(awk 'tolower($1) == "x-request-id:" {gsub("\r", "", $2); print $2; exit}' "${headers}")"
            if [[ "${request_id}" =~ ^[[:xdigit:]]{8}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{12}$ ]]; then
                printf '%s' "${request_id}"
                return 0
            fi
        fi
        sleep 1
    done
    printf 'HTTPS 요청 또는 요청 ID 확인에 실패했습니다: %s\n' "${label}" >&2
    return 1
}

assert_request_logs() {
    local request_id="$1"
    local app_path="$2"
    local nginx_path="$3"

    for ((attempt=1; attempt<=10; attempt++)); do
        if grep -Fq -- "request_id=${request_id}" "${app_path}" \
            && grep -Fq -- "request_id=${request_id}" "${nginx_path}"; then
            return 0
        fi
        sleep 1
    done
    printf '앱·Nginx 로그에 요청 ID가 모두 나타나지 않았습니다: %s\n' "${request_id}" >&2
    return 1
}

assert_probe_not_logged() {
    local probe="$1"
    local plain_files=()
    local compressed_files=()

    shopt -s nullglob
    plain_files=("${APP_LOG_DIR}"/app.log "${APP_LOG_DIR}"/app.log.[0-9]* "${NGINX_LOG_DIR}"/nginx_access.log "${NGINX_LOG_DIR}"/nginx_access.log.[0-9]*)
    compressed_files=("${APP_LOG_DIR}"/app.log*.gz "${NGINX_LOG_DIR}"/nginx_access.log*.gz)
    if (( ${#plain_files[@]} > 0 )) && grep -Fq -- "${probe}" "${plain_files[@]}"; then
        printf '%s\n' '검증용 쿼리 값이 앱 또는 Nginx 로그에 기록되었습니다.' >&2
        return 1
    fi
    if (( ${#compressed_files[@]} > 0 )) && zgrep -Fq -- "${probe}" "${compressed_files[@]}"; then
        printf '%s\n' '검증용 쿼리 값이 압축된 로그에 기록되었습니다.' >&2
        return 1
    fi
}

assert_sensitive_fields_not_logged() {
    local files=()
    local compressed=()

    shopt -s nullglob
    files=("${APP_LOG_DIR}"/app.log "${APP_LOG_DIR}"/app.log.[0-9]* "${NGINX_LOG_DIR}"/nginx_access.log "${NGINX_LOG_DIR}"/nginx_access.log.[0-9]*)
    compressed=("${APP_LOG_DIR}"/app.log*.gz "${NGINX_LOG_DIR}"/nginx_access.log*.gz)
    if (( ${#files[@]} > 0 )) && grep -hEi 'Bearer[[:space:]]+[A-Za-z0-9._~+/=-]{16,}|eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}|AIza[A-Za-z0-9_-]{20,}|(password|access_token|x-goog-api-key|secret_key|question|answer)=[^[:space:]]+' "${files[@]}" >/dev/null 2>&1; then
        printf '%s\n' '로그에서 비밀값 또는 대화 원문 형태를 발견했습니다.' >&2
        return 1
    fi
    if (( ${#compressed[@]} > 0 )) && zgrep -hEi 'Bearer[[:space:]]+[A-Za-z0-9._~+/=-]{16,}|eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}|AIza[A-Za-z0-9_-]{20,}|(password|access_token|x-goog-api-key|secret_key|question|answer)=[^[:space:]]+' "${compressed[@]}" >/dev/null 2>&1; then
        printf '%s\n' '압축 로그에서 비밀값 또는 대화 원문 형태를 발견했습니다.' >&2
        return 1
    fi
}

before_probe="b7_1_rotation_before_$(openssl rand -hex 16)"
if [[ -n "${VERIFY_CHAT_REQUEST_ID}" ]]; then
    assert_chat_events "${VERIFY_CHAT_REQUEST_ID}"
fi
before_id="$(request_id_for_probe "${before_probe}" before)"
assert_request_logs "${before_id}" "${APP_LOG_DIR}/app.log" "${NGINX_LOG_DIR}/nginx_access.log"
assert_probe_not_logged "${before_probe}"

logrotate --debug "${LOGROTATE_FILE}"
logrotate --state "${WORK_DIR}/logrotate.status" --force "${LOGROTATE_FILE}"
assert_request_logs "${before_id}" "${APP_LOG_DIR}/app.log.1" "${NGINX_LOG_DIR}/nginx_access.log.1"

after_probe="b7_1_rotation_after_$(openssl rand -hex 16)"
after_id="$(request_id_for_probe "${after_probe}" after)"
assert_request_logs "${after_id}" "${APP_LOG_DIR}/app.log" "${NGINX_LOG_DIR}/nginx_access.log"
assert_probe_not_logged "${before_probe}"
assert_probe_not_logged "${after_probe}"
assert_sensitive_fields_not_logged

printf '%s\n' '로그 회전 검증 완료: 회전 전후 앱·Nginx 요청 ID 연결, 쿼리 비기록 확인'
