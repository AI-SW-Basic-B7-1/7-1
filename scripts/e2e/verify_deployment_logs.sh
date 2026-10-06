#!/usr/bin/env bash
# JUnit 증거의 요청 ID별 로그 이벤트를 테스트 EC2에서 대조합니다.

set -Eeuo pipefail
umask 077

REGION="${E2E_AWS_REGION:-}"
INSTANCE_ID="${E2E_EC2_INSTANCE_ID:-}"
EVIDENCE_FILE="${E2E_EVIDENCE_FILE:-.artifacts/e2e/evidence.jsonl}"
REMOTE_SCRIPT='/home/ubuntu/app/B7-1/7-1/scripts/ec2/verify_e2e_request_log.sh'

fail() {
    printf '[실패] %s\n' "$*" >&2
    exit 1
}

[[ -f "${EVIDENCE_FILE}" ]] || fail '요청 ID 증거 파일이 없습니다.'
[[ "${INSTANCE_ID}" =~ ^i-[0-9a-f]{17}$ ]] || fail '대상 EC2 ID 형식이 올바르지 않습니다.'

request_id_for() {
    local scenario="$1"
    local status="$2"
    local request_id
    request_id="$(jq -sr --arg scenario "${scenario}" --arg status "${status}" \
        'map(select(.scenario_id == $scenario and .status == ($status | tonumber) and .request_id != null)) | .[0].request_id // empty' \
        "${EVIDENCE_FILE}")"
    [[ "${request_id}" =~ ^[0-9a-fA-F-]{36}$ ]] || fail "${scenario} 요청 ID를 증거에서 찾지 못했습니다."
    printf '%s' "${request_id}"
}

verify_case() {
    local scenario="$1"
    local status="$2"
    local log_case="$3"
    local request_id remote_command
    request_id="$(request_id_for "${scenario}" "${status}")"
    printf -v remote_command 'EXPECTED_INSTANCE_ID=%q VERIFY_LOG_CASE=%q VERIFY_REQUEST_ID=%q bash %q' \
        "${INSTANCE_ID}" "${log_case}" "${request_id}" "${REMOTE_SCRIPT}"
    E2E_AWS_REGION="${REGION}" \
    E2E_EC2_INSTANCE_ID="${INSTANCE_ID}" \
    E2E_SSM_TIMEOUT_SECONDS=180 \
    bash scripts/e2e/run_ssm_command.sh "${remote_command}"
}

verify_case A01 401 auth-denied
verify_case I02 404 auth-denied
verify_case N03 200 success
verify_case F01 502 ai-failure
verify_case F02 504 ai-failure
verify_case F03 500 db-read
verify_case F04 500 db-write
printf '%s\n' 'E2E_O03_LOGS_VERIFIED=1'
