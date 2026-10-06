#!/usr/bin/env bash
# 지정한 배포 브라우저 시나리오를 실행하고 민감정보 없는 JUnit을 검증합니다.

set -Eeuo pipefail
umask 077

REPORT_NAME="${1:-}"
shift || true
REPORT_DIR="${E2E_REPORT_DIR:-.artifacts/e2e}"
SCENARIOS=("$@")
[[ "${REPORT_NAME}" =~ ^[A-Za-z0-9_.-]+\.xml$ ]] || {
    printf '%s\n' 'JUnit 보고서 이름이 올바르지 않습니다.' >&2
    exit 2
}
(( ${#SCENARIOS[@]} > 0 )) || {
    printf '%s\n' '실행할 시나리오 ID가 없습니다.' >&2
    exit 2
}
mkdir -p "${REPORT_DIR}/playwright"
scenario_list="$(IFS=,; printf '%s' "${SCENARIOS[*]}")"
status=0
raw_output="$(mktemp)"
E2E_MODE=deployment python -m pytest -q tests/e2e \
    --e2e-mode deployment \
    --e2e-scenarios "${scenario_list}" \
    --browser chromium \
    --tracing=off --video=off --screenshot=off \
    --output="${REPORT_DIR}/playwright" \
    --junitxml="${REPORT_DIR}/${REPORT_NAME}" >"${raw_output}" 2>&1 || status=$?
rm -f -- "${raw_output}"
if [[ ! -f "${REPORT_DIR}/${REPORT_NAME}" ]]; then
    printf '%s\n' 'JUnit 보고서가 생성되지 않았습니다.' >&2
    exit 1
fi
python scripts/e2e/sanitize_junit_report.py "${REPORT_DIR}/${REPORT_NAME}"
required_args=(--required "${SCENARIOS[@]}")
if [[ -n "${E2E_SCENARIO_ALIAS:-}" ]]; then
    required_args+=("${E2E_SCENARIO_ALIAS}")
fi
python scripts/e2e/validate_junit_report.py "${REPORT_DIR}/${REPORT_NAME}" "${required_args[@]}"
printf 'E2E_PYTEST_EXIT=%s scenarios=%s report=%s\n' "${status}" "${scenario_list}" "${REPORT_NAME}"
exit "${status}"
