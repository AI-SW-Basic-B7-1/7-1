#!/usr/bin/env bash
# B7-1 애플리케이션 핵심 이벤트 로그를 확인합니다.

set -euo pipefail

LOG_FILE="${1:-logs/app.log}"
if [[ ! -f "${LOG_FILE}" ]]; then
    printf '로그 파일을 찾을 수 없습니다: %s\n' "${LOG_FILE}" >&2
    exit 1
fi

while IFS='|' read -r label pattern; do
    printf '\n[%s]\n' "${label}"
    if grep -Fq -- "${pattern}" "${LOG_FILE}"; then
        grep -F -- "${pattern}" "${LOG_FILE}" | tail -n 5
    else
        printf '기록 없음\n'
    fi
done <<'EVENTS'
요청 수신|request_received
AI 호출 시작|ai_call_start
AI 호출 성공|ai_call_success
AI 호출 실패|ai_call_failed
DB 저장 성공|db_save_success
DB 저장 실패|db_save_failed
EVENTS
