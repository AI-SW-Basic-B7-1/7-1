#!/usr/bin/env bash
# 서비스 설정을 바꾸거나 고의 장애를 발생시키지 않고 요청 추적을 확인합니다.
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
SERVICE_NAME="${SERVICE_NAME:-chatbot.service}"
LOG_DIR="${LOG_DIR:-${PROJECT_DIR}/logs}"
INCIDENT_REQUEST_ID="${INCIDENT_REQUEST_ID:-}"

read_env_value() {
    local key="$1"
    local raw
    raw="$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "${PROJECT_DIR}/.env" | head -n 1 || true)"
    raw="${raw#*=}"
    raw="${raw#"${raw%%[![:space:]]*}"}"
    raw="${raw%"${raw##*[![:space:]]}"}"
    raw="${raw#\"}"
    raw="${raw%\"}"
    raw="${raw#\'}"
    raw="${raw%\'}"
    printf '%s' "${raw}"
}

SITE_DOMAIN="${SITE_DOMAIN:-$(read_env_value SITE_DOMAIN)}"
if [[ -n "${SITE_DOMAIN}" ]]; then
    [[ "${SITE_DOMAIN}" =~ ^[A-Za-z0-9.-]+$ ]] || {
        printf '%s\n' 'SITE_DOMAIN 형식이 올바르지 않습니다.' >&2
        exit 1
    }
    BASE_URL="${BASE_URL:-https://${SITE_DOMAIN}}"
else
    BASE_URL="${BASE_URL:-http://127.0.0.1}"
fi
BASE_URL="${BASE_URL%/}"
[[ "${BASE_URL}" =~ ^https?://[A-Za-z0-9._:-]+$ ]] || {
    printf '%s\n' '검증 주소는 경로가 없는 HTTP 또는 HTTPS 주소여야 합니다.' >&2
    exit 1
}
CURL_RESOLVE_ARGS=()
if [[ "${BASE_URL}" =~ ^https://([A-Za-z0-9.-]+)(:[0-9]+)?$ ]]; then
    base_host="${BASH_REMATCH[1]}"
    base_port='443'
    if [[ "${BASE_URL}" =~ :([0-9]+)$ ]]; then
        base_port="${BASH_REMATCH[1]}"
    fi
    if [[ "${base_host}" != '127.0.0.1' && "${base_host}" != 'localhost' ]]; then
        CURL_RESOLVE_ARGS=(--resolve "${base_host}:${base_port}:127.0.0.1")
    fi
fi

for command in systemctl curl awk grep mktemp sleep; do
    command -v "$command" >/dev/null || { printf '필수 명령 없음: %s\n' "$command" >&2; exit 1; }
done
systemctl is-active --quiet "$SERVICE_NAME" || {
    printf '서비스가 활성 상태가 아닙니다: %s\n' "$SERVICE_NAME" >&2
    exit 1
}
systemctl show "$SERVICE_NAME" -p StandardOutput -p StandardError

headers="$(mktemp)"
trap 'rm -f "$headers"' EXIT
curl --fail --silent --show-error --max-time 10 \
    "${CURL_RESOLVE_ARGS[@]}" \
    -D "$headers" -o /dev/null "${BASE_URL%/}/api/health"
request_id="$(awk 'tolower($1) == "x-request-id:" {gsub("\r", "", $2); print $2; exit}' "$headers")"
[[ "$request_id" =~ ^[[:xdigit:]]{8}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{12}$ ]] || {
    printf '헬스체크 응답에서 유효한 요청 ID를 찾지 못했습니다.\n' >&2
    exit 1
}

# 응답 전송 직후 완료 로그가 기록될 때까지 짧게 기다립니다.
found=0
for attempt in 1 2 3 4 5; do
    if grep -F "request_id=${request_id}" "${LOG_DIR}/app.log" | grep -q 'http_request_completed'; then
        found=1
        break
    fi
    sleep 1
done
[[ "$found" == 1 ]] || { printf 'app.log 요청 완료 기록 없음\n' >&2; exit 1; }
printf '정상 요청 추적 확인: %s\n' "$request_id"

for file in server.log nginx_access.log; do
    if [[ -r "${LOG_DIR}/${file}" ]]; then
        printf '로그 파일 읽기 가능: %s\n' "$file"
    else
        printf '확인 필요: %s 없음 또는 읽기 권한 없음 (journal·Nginx 설정 확인)\n' "$file"
    fi
done

if [[ -n "$INCIDENT_REQUEST_ID" ]]; then
    [[ "$INCIDENT_REQUEST_ID" =~ ^[[:xdigit:]]{8}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{12}$ ]] || { printf '사고 요청 ID 형식 오류\n' >&2; exit 1; }
    grep -Fq "request_id=${INCIDENT_REQUEST_ID}" "${LOG_DIR}/app.log" || {
        printf '현재 app.log에 사고 요청 ID 없음. 회전 로그도 확인하세요.\n' >&2
        exit 1
    }
    printf '사고 요청 ID 확인. 스택 트레이스 연결 여부는 제한된 터미널에서 별도 확인하세요.\n'
fi
printf '정상 요청 점검 완료. 실제 장애의 스택 트레이스·민감정보 비노출 검증은 별도입니다.\n'
