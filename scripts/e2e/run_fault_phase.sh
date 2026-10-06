#!/usr/bin/env bash
# 지정한 실제 장애를 적용·검증·원복하고 정상 복구 채팅까지 확인합니다.

set -Eeuo pipefail
umask 077

MODE="${E2E_FAULT_MODE:-}"
SCENARIO="${E2E_SCENARIO_ID:-}"
RUN_ID="${E2E_RUN_ID:-}"
REGION="${E2E_AWS_REGION:-}"
INSTANCE_ID="${E2E_EC2_INSTANCE_ID:-}"
REPORT_DIR="${E2E_REPORT_DIR:-.artifacts/e2e}"
REMOTE_CONTROL='/home/ubuntu/app/B7-1/7-1/scripts/ec2/e2e_remote_control.sh'
ACTIVE=0
PREPARED=0

fail() {
    printf '[실패] %s\n' "$*" >&2
    exit 1
}

remote() {
    E2E_AWS_REGION="${REGION}" \
    E2E_EC2_INSTANCE_ID="${INSTANCE_ID}" \
    E2E_SSM_TIMEOUT_SECONDS=360 \
    bash scripts/e2e/run_ssm_command.sh "$1"
}

control_command() {
    printf 'EXPECTED_INSTANCE_ID=%q bash %q %q %q %q' \
        "${INSTANCE_ID}" "${REMOTE_CONTROL}" "$1" "${RUN_ID}" "${2:-}"
}

run_pytest() {
    local selected="$1"
    local report="$2"
    local alias="${3:-}"
    local status=0
    local raw_output
    local -a required_args=(--required "${selected}")
    [[ -n "${alias}" ]] && required_args+=("${alias}")
    raw_output="$(mktemp)"
    E2E_MODE=deployment \
    E2E_SCENARIO_ALIAS="${alias}" \
    E2E_REPORT_DIR="${REPORT_DIR}" \
    python -m pytest -q tests/e2e \
        --e2e-mode deployment \
        --e2e-scenarios "${selected}" \
        --browser chromium \
        --tracing=off --video=off --screenshot=off \
        --output="${REPORT_DIR}/playwright" \
        --junitxml="${REPORT_DIR}/${report}" >"${raw_output}" 2>&1 || status=$?
    rm -f -- "${raw_output}"
    if [[ -f "${REPORT_DIR}/${report}" ]]; then
        python scripts/e2e/sanitize_junit_report.py "${REPORT_DIR}/${report}"
        python scripts/e2e/validate_junit_report.py "${REPORT_DIR}/${report}" "${required_args[@]}"
    fi
    printf 'E2E_PYTEST_EXIT=%s scenario=%s report=%s\n' "${status}" "${selected}" "${report}"
    return "${status}"
}

cleanup() {
    local result=$?
    trap - EXIT
    if [[ "${ACTIVE}" == 1 || "${PREPARED}" == 1 ]]; then
        remote "$(control_command restore)" || result=1
    fi
    exit "${result}"
}

[[ "${MODE}" =~ ^(jwt-expiry|gemini-error|proxy-timeout|db-read|db-write|observe-context)$ ]] || fail '장애 모드가 올바르지 않습니다.'
[[ "${SCENARIO}" =~ ^(A02|F01|F02|F03|F04|I04)$ ]] || fail '필수 시나리오 ID가 올바르지 않습니다.'
[[ "${RUN_ID}" =~ ^[A-Za-z0-9_-]{1,100}$ ]] || fail '실행 ID가 올바르지 않습니다.'
[[ "${INSTANCE_ID}" =~ ^i-[0-9a-f]{17}$ ]] || fail '대상 EC2 ID가 올바르지 않습니다.'
[[ -d "${REPORT_DIR}" ]] || mkdir -p "${REPORT_DIR}"
trap cleanup EXIT

if [[ "${MODE}" == db-read || "${MODE}" == db-write ]]; then
    before_counts="$(remote "$(control_command counts)")"
    printf '%s\n' "${before_counts}" > "${REPORT_DIR}/${SCENARIO}-db-before.json"
fi
remote "$(control_command prepare)"
PREPARED=1
remote "$(control_command arm "${MODE}")"
ACTIVE=1

case "${SCENARIO}" in
    A02) required='A02' ;;
    F01) required='F01' ;;
    F02) required='F02' ;;
    F03) required='F03' ;;
    F04) required='F04' ;;
    I04) required='I04' ;;
esac
run_pytest "${required}" "${SCENARIO}-${MODE}.xml"

if [[ "${MODE}" == observe-context ]]; then
    observed="$(remote "EXPECTED_INSTANCE_ID=${INSTANCE_ID} cat /var/lib/b7-1/e2e/${RUN_ID}/context/context-observed.json")"
    printf '%s\n' "${observed}" > "${REPORT_DIR}/context-observed.json"
    python scripts/e2e/compare_context_observation.py \
        "${REPORT_DIR}/context-expected.json" \
        "${REPORT_DIR}/context-observed.json"
fi

remote "$(control_command restore)"
ACTIVE=0
PREPARED=0
if [[ "${MODE}" == db-read || "${MODE}" == db-write ]]; then
    after_counts="$(remote "$(control_command counts)")"
    printf '%s\n' "${after_counts}" > "${REPORT_DIR}/${SCENARIO}-db-after.json"
    jq -e --argjson before "${before_counts}" \
        '.integrity == "ok" and .conversations == $before.conversations and .chat_logs == $before.chat_logs' \
        <<<"${after_counts}" >/dev/null || fail 'DB 장애 뒤 행 수 또는 무결성이 복원 기준과 다릅니다.'
fi

run_pytest F05 "F05-after-${MODE}.xml"
printf 'E2E_PHASE_COMPLETE=%s\n' "${SCENARIO}"
