#!/usr/bin/env bash
# 원격 after-start 시험의 준비 신호를 제한 시간 안에 확인합니다.

set -Eeuo pipefail
umask 077

MARKER="${B7_1_E2E_READY_MARKER:-}"
WAIT_SECONDS="${E2E_MARKER_WAIT_SECONDS:-360}"
REGION="${E2E_AWS_REGION:-}"
INSTANCE_ID="${E2E_EC2_INSTANCE_ID:-}"
[[ "${MARKER}" =~ ^/run/b7-1-e2e-ready-[A-Za-z0-9_-]{1,80}$ ]] || {
    printf '%s\n' '원격 준비 신호 경로가 올바르지 않습니다.' >&2
    exit 2
}
[[ "${WAIT_SECONDS}" =~ ^[1-9][0-9]{0,3}$ ]] && (( 10#${WAIT_SECONDS} <= 600 )) || {
    printf '%s\n' '원격 준비 대기 시간이 올바르지 않습니다.' >&2
    exit 2
}
remote_body="for attempt in \$(seq 1 ${WAIT_SECONDS}); do if [[ -f '${MARKER}' ]] && [[ \$(cat '${MARKER}') == ready ]]; then printf '%s\\n' E2E_AFTER_START_READY; exit 0; fi; sleep 1; done; exit 1"
printf -v remote_command 'bash -c %q' "${remote_body}"
E2E_SSM_TIMEOUT_SECONDS="${WAIT_SECONDS}" \
E2E_AWS_REGION="${REGION}" \
E2E_EC2_INSTANCE_ID="${INSTANCE_ID}" \
bash scripts/e2e/run_ssm_command.sh "${remote_command}"
