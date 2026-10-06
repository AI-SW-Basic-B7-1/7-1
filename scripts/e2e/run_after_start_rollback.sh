#!/usr/bin/env bash
# 새 코드 기동 뒤 저장 검증·협조적 롤백을 완료하고 A와 대화 복원을 확인합니다.

set -Eeuo pipefail
umask 077

MODE="${E2E_ROLLBACK_MODE:-}"
BRANCH="${E2E_DEPLOY_BRANCH:-}"
BASELINE_SHA="${E2E_BASELINE_SHA:-}"
REVISION="${E2E_DEPLOY_REVISION:-}"
REGION="${E2E_AWS_REGION:-}"
INSTANCE_ID="${E2E_EC2_INSTANCE_ID:-}"
SECRET_PARAMETER="${E2E_SECRET_PARAMETER:-}"
OUTPUT="$(mktemp)"
DEPLOY_PID=''
HANDSHAKE_SENT=0
WAIT_SECONDS=''

fail() {
    printf '[실패] %s\n' "$*" >&2
    exit 1
}

send_handshake() {
    local value="$1"
    local marker="${B7_1_E2E_READY_MARKER:-}"
    local remote_body remote_command
    [[ "${marker}" =~ ^/run/b7-1-e2e-ready-[A-Za-z0-9_-]{1,80}$ ]] || return 1
    remote_body="if [[ -f '${marker}' ]]; then printf '%s\\n' '${value}' > '${marker}'; else exit 1; fi"
    printf -v remote_command 'bash -c %q' "${remote_body}"
    E2E_SSM_TIMEOUT_SECONDS=120 \
    E2E_AWS_REGION="${REGION}" \
    E2E_EC2_INSTANCE_ID="${INSTANCE_ID}" \
    bash scripts/e2e/run_ssm_command.sh "${remote_command}"
}

cleanup() {
    local result=$?
    trap - EXIT
    if [[ -n "${DEPLOY_PID}" ]]; then
        if [[ "${HANDSHAKE_SENT}" != 1 ]]; then
            send_handshake abort >/dev/null 2>&1 || true
        fi
        wait "${DEPLOY_PID}" || true
    fi
    rm -f -- "${OUTPUT}"
    exit "${result}"
}

[[ "${MODE}" == after-start || "${MODE}" == timeout ]] || fail '롤백 시험 모드가 올바르지 않습니다.'
[[ "${BRANCH}" == feat/auth-ec2-ko ]] || fail '배포 브랜치가 고정 실행 브랜치와 다릅니다.'
[[ "${BASELINE_SHA}" =~ ^[0-9a-f]{40}$ && "${REVISION}" =~ ^[0-9a-f]{40}$ ]] || fail '배포 SHA 형식이 올바르지 않습니다.'
[[ "${INSTANCE_ID}" =~ ^i-[0-9a-f]{17}$ ]] || fail '대상 EC2 ID 형식이 올바르지 않습니다.'
[[ -n "${SECRET_PARAMETER}" ]] || fail 'SecureString 이름이 없습니다.'
[[ "${B7_1_E2E_PRESERVE_CHAT_MARKER:-}" =~ ^[A-Za-z0-9_-]{1,120}$ ]] || fail '기록 보존 표식이 올바르지 않습니다.'
[[ "${B7_1_E2E_READY_MARKER:-}" =~ ^/run/b7-1-e2e-ready-[A-Za-z0-9_-]{1,80}$ ]] || fail '배포 준비 표식 경로가 올바르지 않습니다.'

if [[ "${MODE}" == timeout ]]; then
    [[ -f .artifacts/e2e/r02-ready-seconds.txt ]] || fail 'R02 준비 시간 자료가 없습니다.'
    read -r ready_seconds < .artifacts/e2e/r02-ready-seconds.txt
    [[ "${ready_seconds}" =~ ^[0-9]{1,3}$ ]] || fail 'R02 준비 시간 자료가 올바르지 않습니다.'
    WAIT_SECONDS=$((ready_seconds + 45))
    (( WAIT_SECONDS <= 580 )) || fail '관측한 준비 시간 때문에 협조적 시간 초과를 안전하게 재현할 수 없습니다.'
    export B7_1_E2E_READY_TIMEOUT_SECONDS=600
else
    WAIT_SECONDS=900
    export B7_1_E2E_READY_TIMEOUT_SECONDS=300
fi
trap cleanup EXIT

started_at="$(date +%s)"
E2E_SSM_TIMEOUT_SECONDS=1800 \
E2E_DEPLOY_BRANCH="${BRANCH}" \
E2E_DEPLOY_REVISION="${REVISION}" \
E2E_AWS_REGION="${REGION}" \
E2E_EC2_INSTANCE_ID="${INSTANCE_ID}" \
E2E_SECRET_PARAMETER="${SECRET_PARAMETER}" \
WAIT_SECONDS="${WAIT_SECONDS}" \
bash -c 'bash scripts/ec2/run_ec2_deploy.sh --instance-id "$E2E_EC2_INSTANCE_ID" --region "$E2E_AWS_REGION" --branch "$E2E_DEPLOY_BRANCH" --revision "$E2E_DEPLOY_REVISION" --secret-parameter "$E2E_SECRET_PARAMETER" --failure-injection after-start --require-e2e-test-instance --wait-seconds "$WAIT_SECONDS"' \
    >"${OUTPUT}" 2>&1 &
DEPLOY_PID=$!

E2E_MARKER_WAIT_SECONDS=600 \
B7_1_E2E_READY_MARKER="${B7_1_E2E_READY_MARKER}" \
E2E_AWS_REGION="${REGION}" \
E2E_EC2_INSTANCE_ID="${INSTANCE_ID}" \
bash scripts/e2e/wait_remote_marker.sh
ready_at="$(date +%s)"
ready_elapsed=$((ready_at - started_at))
if [[ "${MODE}" == after-start ]]; then
    printf '%s\n' "${ready_elapsed}" > .artifacts/e2e/r02-ready-seconds.txt
fi

scenario_alias='R02'
report_name='R02-after-start-preserve.xml'
if [[ "${MODE}" == timeout ]]; then
    scenario_alias='R03'
    report_name='R03-timeout-preserve.xml'
fi
E2E_EXISTING_ACCOUNT=1 \
E2E_PRESERVE_CHAT_MARKER="${B7_1_E2E_PRESERVE_CHAT_MARKER}" \
E2E_PRESERVED_REQUEST_ID_FILE=.artifacts/e2e/preserved-chat-request-id.txt \
E2E_SCENARIO_ALIAS="${scenario_alias}" \
bash scripts/e2e/run_browser_suite.sh "${report_name}" N03 "${scenario_alias}"

if [[ "${MODE}" == after-start ]]; then
    send_handshake ack
    HANDSHAKE_SENT=1
fi

set +e
wait "${DEPLOY_PID}"
deploy_status=$?
set -e
DEPLOY_PID=''
[[ "${deploy_status}" -ne 0 ]] || fail 'after-start 실패 주입이 예상과 달리 성공했습니다.'
if [[ "${MODE}" == after-start ]]; then
    grep -Fq 'E2E_FAULT_INJECTION_REACHED=after-start' "${OUTPUT}" || fail 'after-start 주입 지점에 도달하지 못했습니다.'
else
    grep -Fq 'E2E_COOPERATIVE_TIMEOUT_REACHED=after-start' "${OUTPUT}" || fail '준비 지점 이후 협조적 시간 초과를 확인하지 못했습니다.'
fi
grep -Fq 'E2E_ROLLBACK_COMPLETE=1' "${OUTPUT}" || fail '기동 뒤 원격 롤백이 확인되지 않았습니다.'
! grep -Fq 'E2E_ROLLBACK_VERIFICATION_FAILED=1' "${OUTPUT}" || fail '기동 뒤 원격 롤백 검증이 실패했습니다.'

remote_revision="$(E2E_SSM_TIMEOUT_SECONDS=120 E2E_AWS_REGION="${REGION}" E2E_EC2_INSTANCE_ID="${INSTANCE_ID}" \
    bash scripts/e2e/run_ssm_command.sh 'git -c safe.directory=/home/ubuntu/app/B7-1/7-1 -C /home/ubuntu/app/B7-1/7-1 rev-parse HEAD')"
[[ "${remote_revision}" == "${BASELINE_SHA}" ]] || fail '기동 뒤 롤백에서 기준 SHA를 복원하지 못했습니다.'
service_state="$(E2E_SSM_TIMEOUT_SECONDS=120 E2E_AWS_REGION="${REGION}" E2E_EC2_INSTANCE_ID="${INSTANCE_ID}" \
    bash scripts/e2e/run_ssm_command.sh 'systemctl is-active chatbot.service')"
[[ "${service_state}" == active ]] || fail '기동 뒤 롤백 서비스가 active 상태가 아닙니다.'
E2E_SSM_TIMEOUT_SECONDS=120 E2E_AWS_REGION="${REGION}" E2E_EC2_INSTANCE_ID="${INSTANCE_ID}" \
    bash scripts/e2e/run_ssm_command.sh 'curl -fsS --max-time 5 http://127.0.0.1:8000/api/health >/dev/null && printf "E2E_HEALTH=ok\\n"'

E2E_EXISTING_ACCOUNT=1 \
E2E_SCENARIO_ALIAS="${scenario_alias}" \
bash scripts/e2e/run_browser_suite.sh "${scenario_alias}-after-rollback.xml" N03 "${scenario_alias}"
printf '{"scenario_id":"%s","status":"passed","ready_seconds":%s,"wait_seconds":%s}\n' \
    "${scenario_alias}" "${ready_elapsed}" "${WAIT_SECONDS}" >> .artifacts/e2e/rollback-evidence.jsonl
printf 'E2E_ROLLBACK_STAGE=%s status=passed baseline=%s\n' "${scenario_alias}" "${BASELINE_SHA}"
