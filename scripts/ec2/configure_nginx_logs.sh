#!/usr/bin/env bash
# Nginx 로그와 챗봇 서비스 출력을 모으고 로그 디렉터리 접근을 차단합니다.

set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
SITE_CONFIG="${SITE_CONFIG:-/etc/nginx/sites-enabled/chatbot}"
VERIFY_BASE_URL="${VERIFY_BASE_URL:-http://127.0.0.1}"
LOG_DIR="${PROJECT_DIR}/logs"
SERVICE="${SERVICE_NAME:-chatbot.service}"
MODE="${1:---apply}"
DROPIN_DIR="/etc/systemd/system/${SERVICE}.d"
DROPIN_FILE="${DROPIN_DIR}/90-b7-1-logging.conf"
BEGIN_MARKER='# BEGIN B7-1 MANAGED LOGGING'
END_MARKER='# END B7-1 MANAGED LOGGING'
FORMAT_BEGIN='# BEGIN B7-1 ACCESS FORMAT'
FORMAT_END='# END B7-1 ACCESS FORMAT'

if [[ "${1:-}" == '--help' ]]; then
    printf '%s\n' '사용법: sudo bash scripts/ec2/configure_nginx_logs.sh [--apply|--prepare|--verify]' \
        '--prepare: 설정만 설치합니다. 서비스 활성화와 실패 시 복원은 배포 호출자가 담당합니다.' \
        '--verify: 실행 중인 서비스와 로그를 검사합니다. 설정을 변경하지 않습니다.' \
        '선택 설정: SERVICE_NAME (기본값: chatbot.service)' \
        '선택 설정: SITE_CONFIG (기본값: /etc/nginx/sites-enabled/chatbot)' \
        '선택 설정: VERIFY_BASE_URL (기본값: http://127.0.0.1)' \
        '단일 사이트의 HTTP·HTTPS server 블록을 지원합니다. 기존 로그는 이동하지 않습니다.' \
        'chatbot.service의 출력 경로를 설정하고 서비스를 재시작합니다.' \
        '주의: 재시작 중 요청이 중단될 수 있습니다. 회전 정책은 configure_log_rotation.sh가 설치합니다.'
    exit 0
fi
[[ $# -le 1 && "${MODE}" =~ ^--(apply|prepare|verify)$ ]] || { printf '%s\n' '지원하지 않는 인자입니다.' >&2; exit 1; }
[[ "${SERVICE}" =~ ^[a-zA-Z0-9_-]+\.service$ ]] || exit 1
[[ $EUID -eq 0 ]] || { printf '%s\n' 'sudo로 실행해 주세요.' >&2; exit 1; }
for command in nginx systemctl realpath readlink awk mktemp curl openssl; do
    command -v "${command}" >/dev/null || exit 1
done
[[ -f "${SITE_CONFIG}" ]] || { printf '%s\n' '사이트 설정 파일이 없습니다.' >&2; exit 1; }
VERIFY_BASE_URL="${VERIFY_BASE_URL%/}"
[[ "${VERIFY_BASE_URL}" =~ ^https?://[a-zA-Z0-9._:-]+$ ]] || {
    printf '%s\n' '검증 주소는 경로가 없는 HTTP 또는 HTTPS 주소여야 합니다.' >&2
    exit 1
}
CURL_RESOLVE_ARGS=()
if [[ "${VERIFY_BASE_URL}" =~ ^(https?)://([a-zA-Z0-9.-]+)(:([0-9]+))?$ ]]; then
    verify_scheme="${BASH_REMATCH[1]}"
    verify_host="${BASH_REMATCH[2]}"
    verify_port="${BASH_REMATCH[4]:-}"
    if [[ -z "${verify_port}" ]]; then
        if [[ "${verify_scheme}" == 'https' ]]; then verify_port=443; else verify_port=80; fi
    fi
    if [[ "${verify_host}" != '127.0.0.1' && "${verify_host}" != 'localhost' ]]; then
        CURL_RESOLVE_ARGS=(--resolve "${verify_host}:${verify_port}:127.0.0.1")
    fi
fi
# 경로를 설정에 삽입하므로 특수문자와 디렉터리 심볼릭 링크는 허용하지 않습니다.
[[ "${LOG_DIR}" =~ ^/[a-zA-Z0-9_./-]+$ && ! -L "${LOG_DIR}" ]] || {
    printf '%s\n' '로그 경로에 지원하지 않는 문자 또는 심볼릭 링크가 있습니다.' >&2
    exit 1
}
SITE_CONFIG="$(realpath -- "${SITE_CONFIG}")"
if [[ "${MODE}" != '--prepare' ]]; then
    nginx -t
    systemctl is-active --quiet nginx
    systemctl is-active --quiet "${SERVICE}"
    SERVICE_PROJECT="$(systemctl show "${SERVICE}" -p WorkingDirectory --value)"
    [[ "$(realpath -- "${SERVICE_PROJECT}")" == "${PROJECT_DIR}" ]] || {
        printf '%s\n' '챗봇 서비스의 작업 경로와 스크립트 프로젝트 경로가 다릅니다.' >&2
        exit 1
    }
fi
[[ ! -L "${DROPIN_DIR}" && ! -L "${DROPIN_FILE}" ]] || exit 1
[[ ! -e "${DROPIN_FILE}" || -f "${DROPIN_FILE}" ]] || exit 1
if [[ "${MODE}" == '--apply' ]]; then
    printf '주의: 로그 설정 적용 과정에서 %s를 재시작합니다.\n' "${SERVICE}"
fi

WORK_DIR="$(mktemp -d)"
BACKUP=''
CHANGED=0
SERVICE_CHANGED=0
DROPIN_EXISTED=0
SERVICE_BACKUP=''
cleanup() {
    local result=$?
    trap - EXIT
    set +e
    if [[ $result -ne 0 && $SERVICE_CHANGED -eq 1 ]]; then
        if [[ $DROPIN_EXISTED -eq 1 ]]; then
            cp -p -- "${SERVICE_BACKUP}" "${DROPIN_FILE}"
        else
            rm -f -- "${DROPIN_FILE}"
        fi
        if [[ "${MODE}" == '--apply' ]]; then
            systemctl daemon-reload
            systemctl restart "${SERVICE}" || printf '%s\n' '서비스 복구 실패: journalctl로 확인해 주세요.' >&2
        fi
        printf '%s\n' '서비스 로그 설정을 이전 상태로 복원했습니다.' >&2
    fi
    if [[ $result -ne 0 && $CHANGED -eq 1 ]]; then
        cp -p -- "${BACKUP}" "${SITE_CONFIG}"
        printf '설정을 복원했습니다. 백업: %s\n' "${BACKUP}" >&2
        if [[ "${MODE}" == '--apply' ]]; then
            nginx -t && systemctl reload nginx || true
        fi
    fi
    rm -rf -- "${WORK_DIR}"
    exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ "${MODE}" != '--verify' ]]; then
# 직접 관리하는 블록만 제거하여 반복 실행 시 중복 삽입을 방지합니다.
awk -v begin="${BEGIN_MARKER}" -v end="${END_MARKER}" \
    -v format_begin="${FORMAT_BEGIN}" -v format_end="${FORMAT_END}" '
    index($0, format_begin) { if (inside || format_seen++) exit 2; inside=2; next }
    index($0, format_end) { if (inside != 2) exit 2; inside=0; next }
    index($0, begin) { if (inside) exit 2; inside=1; next }
    index($0, end) { if (inside != 1) exit 2; inside=0; next }
    !inside { print }
    END { if (inside) exit 2 }
' "${SITE_CONFIG}" > "${WORK_DIR}/base"

# 임의의 Nginx 문법을 재작성하지 않고 제공된 단일 사이트의 server 블록들을 지원합니다.
awk '
    /^[[:space:]]*server[[:space:]]*\{[[:space:]]*$/ { servers++ }
    /^[[:space:]]*(access_log|error_log|include)[[:space:]]/ { conflict=1 }
    /^[[:space:]]*location[[:space:]].*\/logs/ { conflict=1 }
    END { if (servers < 1 || conflict) exit 1 }
' "${WORK_DIR}/base" || {
    printf '%s\n' 'server 블록이 없거나 기존 로그/include/로그 경로 설정이 있습니다. 수동 확인이 필요합니다.' >&2
    exit 1
}

awk -v dir="${LOG_DIR}" -v begin="${BEGIN_MARKER}" -v end="${END_MARKER}" \
    -v format_begin="${FORMAT_BEGIN}" -v format_end="${FORMAT_END}" '
    BEGIN {
        print format_begin
        print "log_format b7_1_request_trace \047$remote_addr [$time_local] method=$request_method path=$uri protocol=$server_protocol status=$status bytes=$body_bytes_sent request_id=$upstream_http_x_request_id nginx_request_id=$request_id\047;"
        print format_end
    }
    { print }
    /^[[:space:]]*server[[:space:]]*\{[[:space:]]*$/ {
        print "    " begin
        print "    access_log " dir "/nginx_access.log b7_1_request_trace;"
        print "    error_log " dir "/nginx_error.log warn;"
        print "    location = /logs { return 404; }"
        print "    location ^~ /logs/ { return 404; }"
        print "    " end
    }
' "${WORK_DIR}/base" > "${WORK_DIR}/candidate"

mkdir -p -- "${LOG_DIR}"
for name in nginx_access.log nginx_error.log server.log; do
    target="${LOG_DIR}/${name}"
    [[ ! -L "${target}" && ( ! -e "${target}" || -f "${target}" ) ]] || exit 1
    touch -- "${target}"
    chmod 640 -- "${target}"
done

# 백업은 sites-enabled 밖에 두어 Nginx가 별도 사이트로 읽지 않게 합니다.
mkdir -p /var/backups/b7-1-nginx
BACKUP="$(mktemp /var/backups/b7-1-nginx/chatbot.XXXXXXXX)"
cp -p -- "${SITE_CONFIG}" "${BACKUP}"
if [[ -f "${DROPIN_FILE}" ]]; then
    SERVICE_BACKUP="${BACKUP}.systemd"
    cp -p -- "${DROPIN_FILE}" "${SERVICE_BACKUP}"
    DROPIN_EXISTED=1
fi
CHANGED=1
cat "${WORK_DIR}/candidate" > "${SITE_CONFIG}"
nginx -t
mkdir -p -- "${DROPIN_DIR}"
SERVICE_CHANGED=1
printf '[Service]\nStandardOutput=append:%s/server.log\nStandardError=inherit\n' \
    "${LOG_DIR}" > "${DROPIN_FILE}"
chmod 644 "${DROPIN_FILE}"
fi

if [[ "${MODE}" == '--prepare' ]]; then
    CHANGED=0
    SERVICE_CHANGED=0
    printf '%s\n' '로그 설정 준비 완료. 서비스 재시작 후 --verify 검증이 필요합니다.'
    exit 0
fi

if [[ "${MODE}" == '--apply' ]]; then
    systemctl daemon-reload
fi
# 다른 설정에 의해 출력 방식이 덮어써졌는지 확인합니다.
[[ "$(systemctl show "${SERVICE}" -p StandardOutput --value)" == 'append' ]] || {
    printf '%s\n' '서비스 표준 출력이 append 모드가 아닙니다.' >&2
    exit 1
}
[[ "$(systemctl show "${SERVICE}" -p StandardError --value)" == 'inherit' ]] || {
    printf '%s\n' '서비스 표준 오류가 표준 출력을 상속하지 않습니다.' >&2
    exit 1
}
if [[ "${MODE}" == '--apply' ]]; then
    systemctl reload nginx
    systemctl restart "${SERVICE}"
fi
systemctl is-active --quiet "${SERVICE}"
# 출력 경로는 실행 중인 프로세스의 파일 디스크립터로 확인합니다.
SERVICE_PID="$(systemctl show "${SERVICE}" -p MainPID --value)"
[[ "${SERVICE_PID}" =~ ^[1-9][0-9]*$ ]] || {
    printf '%s\n' '서비스 프로세스 ID를 확인하지 못했습니다.' >&2
    exit 1
}
for descriptor in 1 2; do
    [[ "$(readlink -f "/proc/${SERVICE_PID}/fd/${descriptor}")" == "${LOG_DIR}/server.log" ]] || {
        printf '서비스 출력 경로가 server.log와 다릅니다: fd=%s\n' "${descriptor}" >&2
        exit 1
    }
done

# 실제 Nginx 요청으로 쿼리 비기록, 요청 ID 연결과 로그 경로 차단을 확인합니다.
QUERY_PROBE="b7_1_query_probe_$(openssl rand -hex 16)"
HEADERS_FILE="${WORK_DIR}/health_headers"
HEALTH_READY=0
for ((attempt=1; attempt<=30; attempt++)); do
    if health_status="$(curl "${CURL_RESOLVE_ARGS[@]}" -fsS --max-time 3 -D "${HEADERS_FILE}" -o /dev/null \
        -H "Referer: ${VERIFY_BASE_URL}/?ref=${QUERY_PROBE}" -w '%{http_code}' \
        "${VERIFY_BASE_URL}/api/health?probe=${QUERY_PROBE}")" && [[ "${health_status}" == '200' ]]; then
        HEALTH_READY=1
        break
    fi
    sleep 1
done
[[ "${HEALTH_READY}" -eq 1 ]] || {
    printf '%s\n' 'Nginx 경유 헬스체크에 실패했습니다.' >&2
    exit 1
}

APP_REQUEST_ID="$(awk 'tolower($1) == "x-request-id:" {gsub("\r", "", $2); print $2; exit}' "${HEADERS_FILE}")"
[[ "${APP_REQUEST_ID}" =~ ^[[:xdigit:]]{8}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{12}$ ]] || {
    printf '%s\n' '응답에서 유효한 앱 요청 ID를 확인하지 못했습니다.' >&2
    exit 1
}

ACCESS_ENTRY=''
APP_LOG_FOUND=0
for ((attempt=1; attempt<=5; attempt++)); do
    ACCESS_ENTRY="$(awk -v id="request_id=${APP_REQUEST_ID}" '{for (i=1; i<=NF; i++) if ($i == id) print}' "${LOG_DIR}/nginx_access.log")"
    if [[ -n "${ACCESS_ENTRY}" ]] && awk -v id="request_id=${APP_REQUEST_ID}" '
        /http_request_completed / {for (i=1; i<=NF; i++) if ($i == id) found=1}
        END {exit !found}
    ' "${LOG_DIR}/app.log"; then
        APP_LOG_FOUND=1
        break
    fi
    sleep 1
done
[[ "${APP_LOG_FOUND}" -eq 1 ]] || {
    printf '%s\n' '응답·Nginx·앱 로그의 요청 ID 연결을 확인하지 못했습니다.' >&2
    exit 1
}
[[ "${ACCESS_ENTRY}" =~ (^|[[:space:]])nginx_request_id=[[:xdigit:]]{32}([[:space:]]|$) ]] || {
    printf '%s\n' 'Nginx 요청 ID가 접근 로그에 기록되지 않았습니다.' >&2
    exit 1
}
# 과거 실행과 다른 요청의 로그는 이번 설정의 판정에 사용하지 않습니다.
if [[ "${ACCESS_ENTRY}" == *"${QUERY_PROBE}"* ]]; then
    printf '%s\n' '이번 요청의 접근 로그에 쿼리 또는 Referer 값이 기록되었습니다.' >&2
    exit 1
fi

for blocked_path in /logs /logs/ /logs/app.log /logs/app.log.1 /logs/server.log /logs/nginx_access.log; do
    blocked_status="$(curl "${CURL_RESOLVE_ARGS[@]}" -sS --max-time 5 -o /dev/null -w '%{http_code}' \
        "${VERIFY_BASE_URL}${blocked_path}" || true)"
    [[ "${blocked_status}" == '404' ]] || {
        printf '로그 경로 외부 차단 검증 실패: %s (HTTP %s)\n' \
            "${blocked_path}" "${blocked_status}" >&2
        exit 1
    }
done

CHANGED=0
SERVICE_CHANGED=0
if [[ "${MODE}" == '--apply' ]]; then
    printf '설정 완료. 백업: %s\n' "${BACKUP}"
fi
printf '로그: %s/nginx_access.log, nginx_error.log, server.log\n' "${LOG_DIR}"
printf '%s\n' '서비스 출력은 journal 대신 server.log에 기록됩니다. 기존 journal 기록은 이동하지 않습니다.' \
    '접근 로그의 request_id는 앱 응답 헤더이며, 앱을 거치지 않은 요청은 -로 표시됩니다. nginx_request_id는 별도 Nginx 추적 번호입니다.' \
    '검증 완료: 쿼리 문자열 비기록, 앱·Nginx 요청 ID 연결, /logs 하위 경로 HTTP 404' \
    '애플리케이션 콘솔 로그는 app.log와 server.log에 중복 기록될 수 있습니다.' \
    '회전 정책은 configure_log_rotation.sh가 설치하며 deploy_ec2.sh에서 자동 호출합니다.'
