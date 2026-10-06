#!/usr/bin/env bash
# 저장소의 원격 준비 스크립트를 압축해 SSM 입력으로 전달합니다.

set -Eeuo pipefail
umask 077

SCRIPT_PATH="${1:-}"
REGION="${E2E_AWS_REGION:-}"
INSTANCE_ID="${E2E_EC2_INSTANCE_ID:-}"
[[ "${SCRIPT_PATH}" == scripts/ec2/e2e_instance_preflight.sh ]] || {
    printf '%s\n' '허용하지 않은 원격 준비 스크립트입니다.' >&2
    exit 2
}
[[ -f "${SCRIPT_PATH}" ]] || {
    printf '%s\n' '원격 준비 스크립트 파일이 없습니다.' >&2
    exit 2
}
[[ "${REGION}" == ap-northeast-2 && "${INSTANCE_ID}" =~ ^i-[0-9a-f]{17}$ ]] || {
    printf '%s\n' '대상 AWS 리전 또는 인스턴스 ID가 올바르지 않습니다.' >&2
    exit 2
}
encoded="$(gzip -c -- "${SCRIPT_PATH}" | base64 -w0)"
remote_command="printf '%s' '${encoded}' | base64 -d | gzip -d | EXPECTED_INSTANCE_ID='${INSTANCE_ID}' E2E_AWS_REGION='${REGION}' E2E_SECRET_PARAMETER='${E2E_SECRET_PARAMETER:-}' bash"
E2E_SSM_TIMEOUT_SECONDS=1800 bash scripts/e2e/run_ssm_command.sh "${remote_command}"
