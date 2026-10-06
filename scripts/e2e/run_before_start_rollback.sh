#!/usr/bin/env bash
# B before-start 실패를 주입하고 A·DB·서비스·기존 기록 복원을 확인합니다.

set -Eeuo pipefail
umask 077

BRANCH="${E2E_DEPLOY_BRANCH:-}"
BASELINE_SHA="${E2E_BASELINE_SHA:-}"
REVISION="${E2E_DEPLOY_REVISION:-}"
REGION="${E2E_AWS_REGION:-}"
INSTANCE_ID="${E2E_EC2_INSTANCE_ID:-}"
SECRET_PARAMETER="${E2E_SECRET_PARAMETER:-}"
OUTPUT="$(mktemp)"

cleanup() {
    rm -f -- "${OUTPUT}"
}
trap cleanup EXIT

fail() {
    printf '[실패] %s\n' "$*" >&2
    exit 1
}

[[ "${BRANCH}" == feat/auth-ec2-ko ]] || fail '배포 브랜치가 고정 실행 브랜치와 다릅니다.'
[[ "${BASELINE_SHA}" =~ ^[0-9a-f]{40}$ && "${REVISION}" =~ ^[0-9a-f]{40}$ ]] || fail '배포 SHA 형식이 올바르지 않습니다.'
[[ "${INSTANCE_ID}" =~ ^i-[0-9a-f]{17}$ ]] || fail '대상 EC2 ID 형식이 올바르지 않습니다.'
[[ -n "${SECRET_PARAMETER}" ]] || fail 'SecureString 이름이 없습니다.'

set +e
bash scripts/ec2/run_ec2_deploy.sh \
    --instance-id "${INSTANCE_ID}" --region "${REGION}" --branch "${BRANCH}" \
    --revision "${REVISION}" --secret-parameter "${SECRET_PARAMETER}" \
    --failure-injection before-start --require-e2e-test-instance >"${OUTPUT}" 2>&1
deploy_status=$?
set -e
[[ "${deploy_status}" -ne 0 ]] || fail 'before-start 실패 주입이 예상과 달리 성공했습니다.'
grep -Fq 'E2E_FAULT_INJECTION_REACHED=before-start' "${OUTPUT}" || fail 'before-start 주입 지점에 도달하지 못했습니다.'
grep -Fq 'E2E_ROLLBACK_COMPLETE=1' "${OUTPUT}" || fail 'before-start 뒤 원격 롤백이 확인되지 않았습니다.'
! grep -Fq 'E2E_ROLLBACK_VERIFICATION_FAILED=1' "${OUTPUT}" || fail 'before-start 원격 롤백 검증이 실패했습니다.'

remote_revision="$(E2E_SSM_TIMEOUT_SECONDS=120 bash scripts/e2e/run_ssm_command.sh \
    "git -c safe.directory=/home/ubuntu/app/B7-1/7-1 -C /home/ubuntu/app/B7-1/7-1 rev-parse HEAD" )"
[[ "${remote_revision}" == "${BASELINE_SHA}" ]] || fail 'before-start 뒤 기준 SHA로 돌아오지 않았습니다.'
service_state="$(E2E_SSM_TIMEOUT_SECONDS=120 bash scripts/e2e/run_ssm_command.sh 'systemctl is-active chatbot.service')"
[[ "${service_state}" == active ]] || fail 'before-start 뒤 서비스가 active 상태가 아닙니다.'
E2E_SSM_TIMEOUT_SECONDS=120 bash scripts/e2e/run_ssm_command.sh \
    'curl -fsS --max-time 5 http://127.0.0.1:8000/api/health >/dev/null && printf "E2E_HEALTH=ok\\n"'

E2E_EXISTING_ACCOUNT=1 \
E2E_SCENARIO_ALIAS=R01 \
bash scripts/e2e/run_browser_suite.sh R01-recovery.xml N03 R01
printf 'E2E_ROLLBACK_STAGE=R01 status=passed baseline=%s\n' "${BASELINE_SHA}"
