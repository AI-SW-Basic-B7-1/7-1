#!/usr/bin/env bash
# 지정한 테스트 EC2에 안전한 원격 명령을 보내고 완료 상태를 확인합니다.

set -Eeuo pipefail
umask 077

REGION="${E2E_AWS_REGION:-}"
INSTANCE_ID="${E2E_EC2_INSTANCE_ID:-}"
TIMEOUT_SECONDS="${E2E_SSM_TIMEOUT_SECONDS:-360}"
COMMAND="${1:-}"

fail() {
    printf '[실패] %s\n' "$*" >&2
    exit 1
}

[[ "${REGION}" == ap-northeast-2 ]] || fail '허용한 AWS 리전이 아닙니다.'
[[ "${INSTANCE_ID}" =~ ^i-[0-9a-f]{17}$ ]] || fail '테스트 EC2 ID 형식이 올바르지 않습니다.'
[[ "${TIMEOUT_SECONDS}" =~ ^[1-9][0-9]{0,3}$ ]] && (( 10#${TIMEOUT_SECONDS} <= 1800 )) || fail 'SSM 제한 시간이 올바르지 않습니다.'
[[ -n "${COMMAND}" ]] || fail '원격 명령이 비어 있습니다.'
command_parameters="$(jq -cn --arg command "${COMMAND}" '{commands: [$command]}')"
command_id="$(aws ssm send-command \
    --region "${REGION}" \
    --document-name AWS-RunShellScript \
    --instance-ids "${INSTANCE_ID}" \
    --parameters "${command_parameters}" \
    --timeout-seconds "${TIMEOUT_SECONDS}" \
    --query 'Command.CommandId' \
    --output text)"
[[ "${command_id}" =~ ^[0-9a-f-]{36}$ ]] || fail 'SSM 명령 ID를 받지 못했습니다.'
if [[ -n "${E2E_SSM_COMMAND_ID_FILE:-}" ]]; then
    printf '%s\n' "${command_id}" >> "${E2E_SSM_COMMAND_ID_FILE}"
fi

deadline=$((SECONDS + TIMEOUT_SECONDS))
status='Pending'
while (( SECONDS < deadline )); do
    status="$(aws ssm get-command-invocation \
        --region "${REGION}" \
        --command-id "${command_id}" \
        --instance-id "${INSTANCE_ID}" \
        --query Status \
        --output text 2>/dev/null || true)"
    case "${status}" in
        Success|Failed|TimedOut|Cancelled|DeliveryTimedOut|ExecutionTimedOut|Undeliverable|Terminated)
            break
            ;;
        *) sleep 3 ;;
    esac
done

invocation="$(aws ssm get-command-invocation \
    --region "${REGION}" \
    --command-id "${command_id}" \
    --instance-id "${INSTANCE_ID}" \
    --query '{status:Status,stdout:StandardOutputContent,stderr:StandardErrorContent}' \
    --output json 2>/dev/null || true)"
if [[ -n "${invocation}" ]]; then
    jq -r '.stdout // empty' <<<"${invocation}"
    if [[ "${status}" != Success ]]; then
        jq -r '.stderr // empty' <<<"${invocation}" >&2
    fi
fi
[[ "${status}" == Success ]] || fail "SSM 원격 명령이 성공하지 않았습니다: ${status} (${command_id})"
